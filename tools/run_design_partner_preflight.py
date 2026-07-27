#!/usr/bin/env python3
"""Run a source-backed Design Partner preflight from a customer data pack."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.adapters.mapping_schema import AdapterMappingProfile  # noqa: E402
from app.models.design_partner import DesignPartnerPreflightRequest  # noqa: E402
from app.models.reality_harness import (  # noqa: E402
    FieldMappingCompileRequest,
    P0RealityHarnessRequest,
)
from app.services.design_partner_preflight import (  # noqa: E402
    DesignPartnerPreflightService,
)
from app.services.field_mapping_compiler import FieldMappingCompiler  # noqa: E402

_CSV_CANDIDATES = {
    "work_orders": ("work_orders.csv", "erp_work_orders.csv"),
    "operations": ("operations.csv", "mes_operations.csv"),
    "machines": ("machines.csv", "aps_resources.csv"),
    "incidents": ("incidents.csv", "mes_downtime_events.csv"),
}


def main() -> int:
    args = _parse_args()
    pack_dir = args.pack_dir.resolve()
    output_dir = (args.output_dir or pack_dir / "preflight_output").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        csv_paths = {
            entity: _resolve_input_file(pack_dir, candidates)
            for entity, candidates in _CSV_CANDIDATES.items()
        }
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    rows = {entity: _read_csv(path) for entity, path in csv_paths.items()}
    metadata_path = pack_dir / "preflight_metadata.json"
    if not metadata_path.exists():
        template_path = output_dir / "preflight_metadata.template.json"
        _write_json(template_path, _metadata_template())
        print(
            "ERROR: preflight_metadata.json is missing. "
            f"Complete the generated template: {template_path}",
            file=sys.stderr,
        )
        return 2

    metadata = _read_json(metadata_path)
    mapping_path = pack_dir / "mapping_profile.json"
    if not mapping_path.exists():
        draft = FieldMappingCompiler().compile(
            FieldMappingCompileRequest(
                source_system=str(metadata.get("source_system") or "customer_export"),
                raw_work_orders=rows["work_orders"],
                raw_operations=rows["operations"],
                raw_machines=rows["machines"],
                raw_incidents=rows["incidents"],
            )
        )
        draft_path = output_dir / "mapping_profile.draft.json"
        _write_json(draft_path, draft.profile.model_dump(mode="json"))
        _write_json(
            output_dir / "mapping_suggestions.json",
            draft.model_dump(mode="json"),
        )
        print(
            "MAPPING_REVIEW_REQUIRED: no customer-approved mapping_profile.json. "
            f"Review {draft_path}, obtain customer confirmation, and rerun.",
            file=sys.stderr,
        )
        if draft.unmapped_required_fields:
            print(
                "Unmapped required fields: "
                + ", ".join(draft.unmapped_required_fields),
                file=sys.stderr,
            )
        return 2

    try:
        profile = AdapterMappingProfile.model_validate(_read_json(mapping_path))
        request = _build_request(metadata, profile, rows)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: invalid metadata or mapping profile: {exc}", file=sys.stderr)
        return 2

    response = DesignPartnerPreflightService().assess(request)
    input_files = [*csv_paths.values(), metadata_path, mapping_path]
    manifest = _input_manifest(pack_dir, input_files)
    _write_json(output_dir / "input_manifest.json", manifest)
    _write_json(
        output_dir / "design_partner_preflight.json",
        _redacted_report(
            response.model_dump(mode="json"),
            canonical_data_generated=args.include_canonical_data,
        ),
    )
    (output_dir / "design_partner_preflight.md").write_text(
        _render_markdown(response.model_dump(mode="json")),
        encoding="utf-8",
    )
    (output_dir / "data_fingerprint.txt").write_text(
        response.data_fingerprint + "\n",
        encoding="utf-8",
    )
    if args.include_canonical_data:
        _write_json(
            output_dir / "canonical_dataset.private.json",
            response.reality_harness.dataset.model_dump(mode="json"),
        )

    print(f"preflight_id={response.preflight_id}")
    print(f"stage={response.stage}")
    print(f"data_fingerprint={response.data_fingerprint}")
    print(f"report={output_dir / 'design_partner_preflight.md'}")
    return 3 if response.stage == "data_repair" else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a customer workshop data/evidence pack before replay or shadow mode."
    )
    parser.add_argument(
        "--pack-dir",
        type=Path,
        required=True,
        help="Directory containing CSV files, metadata, and an approved mapping profile.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory; defaults to <pack-dir>/preflight_output.",
    )
    parser.add_argument(
        "--include-canonical-data",
        action="store_true",
        help="Write normalized customer rows to a clearly marked private file.",
    )
    return parser.parse_args()


def _build_request(
    metadata: dict[str, Any],
    profile: AdapterMappingProfile,
    rows: dict[str, list[dict[str, str]]],
) -> DesignPartnerPreflightRequest:
    required = ["evidence_scope", "customer_ref", "site_id", "provenance"]
    missing = [key for key in required if not metadata.get(key)]
    if missing:
        raise KeyError(f"missing metadata keys: {', '.join(missing)}")
    if metadata["evidence_scope"] != "customer_provided":
        raise ValueError("customer pack CLI requires evidence_scope=customer_provided")

    planning_start = metadata.get("planning_start")
    reality_request = P0RealityHarnessRequest(
        source_system=str(metadata.get("source_system") or profile.source_system),
        workshop_id=str(metadata["site_id"]),
        planning_start=(
            datetime.fromisoformat(planning_start)
            if planning_start
            else datetime.now(tz=timezone.utc)
        ),
        raw_work_orders=rows["work_orders"],
        raw_operations=rows["operations"],
        raw_machines=rows["machines"],
        raw_incidents=rows["incidents"],
        profile=profile,
    )
    payload = {
        **metadata,
        "reality_request": reality_request.model_dump(mode="json"),
    }
    return DesignPartnerPreflightRequest.model_validate(payload)


def _redacted_report(
    report: dict[str, Any],
    *,
    canonical_data_generated: bool,
) -> dict[str, Any]:
    reality = report["reality_harness"]
    dataset = reality.pop("dataset")
    snapshot = reality.pop("snapshot", None)
    reality["data_summary"] = {
        "work_order_count": len(dataset.get("work_orders", [])),
        "operation_count": len(dataset.get("operations", [])),
        "machine_count": len(dataset.get("machines", [])),
        "incident_count": len(dataset.get("incidents", [])),
        "snapshot_id": snapshot.get("snapshot_id") if snapshot else None,
        "raw_rows_embedded": False,
    }
    report["report_security"] = {
        "raw_rows_embedded": False,
        "canonical_data_file_generated": canonical_data_generated,
        "note": "Use --include-canonical-data only inside the approved customer environment.",
    }
    return report


def _render_markdown(report: dict[str, Any]) -> str:
    checks = report["checks"]
    moat = report["moat_layers"]
    roi = report["roi_summary"]
    next_actions = report["required_next_actions"]
    lines = [
        "# Design Partner Preflight",
        "",
        f"- Preflight ID: `{report['preflight_id']}`",
        f"- Customer ref: `{report['customer_ref']}`",
        f"- Site: `{report['site_id']}`",
        f"- Highest safe stage: **{report['stage']}**",
        f"- Data fingerprint: `{report['data_fingerprint']}`",
        "- Raw customer rows embedded: **No**",
        "",
        "## Evidence Gates",
        "",
        "| Gate | Status | Finding |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {item['check_id']} | {item['status']} | {_md(item['finding'])} |"
        for item in checks
    )
    lines.extend(
        [
            "",
            "## ROI Boundary",
            "",
            f"- Evidence level: **{roi['evidence_level']}**",
            f"- Eligible cases: {roi['eligible_case_count']}/{roi['submitted_case_count']}",
            f"- Estimated case savings: {roi['currency']} {roi['estimated_case_savings']}",
            f"- Realized case savings: {roi['currency']} {roi['realized_case_savings']}",
            f"- Allowed claim: {roi['claim_allowed']}",
            "",
            "## Moat Evidence Coverage",
            "",
            "| Layer | Coverage | Status | Private assets | Reusable deidentified assets |",
            "|---|---:|---|---:|---:|",
        ]
    )
    lines.extend(
        "| {layer} | {score:.1f}% | {status} | {private} | {reusable} |".format(
            layer=item["layer"],
            score=item["evidence_coverage_score"],
            status=item["status"],
            private=item["customer_private_asset_count"],
            reusable=item["reusable_deidentified_asset_count"],
        )
        for item in moat
    )
    lines.extend(["", "## Required Next Actions", ""])
    lines.extend(f"- {item}" for item in next_actions)
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            report["claim_boundary"],
            "",
        ]
    )
    return "\n".join(lines)


def _metadata_template() -> dict[str, Any]:
    return {
        "evidence_scope": "customer_provided",
        "customer_ref": "PSEUDONYMOUS-CUSTOMER-ID",
        "site_id": "WORKSHOP-ID",
        "source_system": "customer_export",
        "planning_start": datetime.now(tz=timezone.utc).isoformat(),
        "provenance": {
            "dataset_name": "",
            "source_systems": [],
            "exported_at": None,
            "data_window_start": None,
            "data_window_end": None,
            "data_owner_role": None,
            "data_owner_approved": False,
            "replay_authorized": False,
            "desensitized": False,
            "provenance_ref": None,
            "mapping_profile_ref": "mapping_profile.json",
            "mapping_approved_by": None,
        },
        "constraints": [],
        "governance_approvals": [],
        "recovery_cases": [],
        "roi_cost_model": {"currency": "CNY"},
        "workflow_evidence": {},
    }


def _resolve_input_file(pack_dir: Path, candidates: tuple[str, ...]) -> Path:
    for name in candidates:
        path = pack_dir / name
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"required CSV missing in {pack_dir}; accepted names: {', '.join(candidates)}"
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path.name} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _input_manifest(pack_dir: Path, files: list[Path]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "pack_ref": pack_dir.name,
        "files": [
            {
                "path": str(path.relative_to(pack_dir)),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(files)
        ],
    }


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
