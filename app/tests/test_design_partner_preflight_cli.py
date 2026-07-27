"""End-to-end tests for the customer data pack preflight CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.adapters.mapping_schema import AdapterMappingProfile

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_PACK = _REPO_ROOT / "datasets" / "p0_reality_pack"
_CLI = _REPO_ROOT / "tools" / "run_design_partner_preflight.py"
_NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


def _prepare_pack(pack_dir: Path, *, include_mapping: bool) -> None:
    pack_dir.mkdir()
    for filename in (
        "erp_work_orders.csv",
        "mes_operations.csv",
        "aps_resources.csv",
        "mes_downtime_events.csv",
    ):
        shutil.copy(_SAMPLE_PACK / filename, pack_dir / filename)

    metadata = {
        "evidence_scope": "customer_provided",
        "customer_ref": "CUSTOMER-TEST",
        "site_id": "SITE-CLI-01",
        "source_system": "customer_export",
        "planning_start": _NOW.isoformat(),
        "provenance": {
            "dataset_name": "cli-test-pack",
            "source_systems": ["ERP", "MES", "APS"],
            "exported_at": _NOW.isoformat(),
            "data_window_start": (_NOW - timedelta(days=30)).isoformat(),
            "data_window_end": _NOW.isoformat(),
            "data_owner_role": "MES owner",
            "data_owner_approved": True,
            "replay_authorized": True,
            "desensitized": True,
            "provenance_ref": "evidence/data-manifest.pdf",
            "mapping_profile_ref": "mapping_profile.json",
            "mapping_approved_by": "MES owner",
        },
        "governance_approvals": [
            {
                "approval_type": approval_type,
                "approved": True,
                "approver_role": "Data owner",
                "evidence_ref": f"evidence/{approval_type}.pdf",
                "approved_at": _NOW.isoformat(),
            }
            for approval_type in (
                "data_use",
                "historical_replay",
                "retention",
                "security_review",
            )
        ],
    }
    (pack_dir / "preflight_metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    if include_mapping:
        profile = AdapterMappingProfile(source_system="customer_export")
        (pack_dir / "mapping_profile.json").write_text(
            profile.model_dump_json(indent=2),
            encoding="utf-8",
        )


def _run(pack_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CLI), "--pack-dir", str(pack_dir)],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_stops_until_mapping_is_customer_approved(tmp_path: Path) -> None:
    pack_dir = tmp_path / "customer-pack"
    _prepare_pack(pack_dir, include_mapping=False)

    result = _run(pack_dir)

    assert result.returncode == 2
    assert "MAPPING_REVIEW_REQUIRED" in result.stderr
    assert (pack_dir / "preflight_output" / "mapping_profile.draft.json").exists()


def test_cli_generates_redacted_report_and_input_manifest(tmp_path: Path) -> None:
    pack_dir = tmp_path / "customer-pack"
    _prepare_pack(pack_dir, include_mapping=True)

    result = _run(pack_dir)

    assert result.returncode == 0, result.stderr
    assert "stage=replay_ready" in result.stdout
    output_dir = pack_dir / "preflight_output"
    report_text = (output_dir / "design_partner_preflight.json").read_text(
        encoding="utf-8"
    )
    report = json.loads(report_text)
    manifest = json.loads(
        (output_dir / "input_manifest.json").read_text(encoding="utf-8")
    )
    assert report["reality_harness"]["data_summary"]["raw_rows_embedded"] is False
    assert "raw_payload" not in report_text
    assert len(manifest["files"]) == 6
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
    assert not (output_dir / "canonical_dataset.private.json").exists()
