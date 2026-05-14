"""Seed and validate the fixed customer-demo sandbox dataset."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import request

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.adapters.csv_adapter import CSVAdapter  # noqa: E402
from app.adapters.mapping_validator import validate_customer_payloads  # noqa: E402

DEFAULT_SOURCE_DIR = REPO_ROOT / "demo" / "data"
DEFAULT_RUNTIME_DIR = REPO_ROOT / "demo" / "runtime"
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "demo" / "demo_validation_report.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument(
        "--api-base-url",
        default=None,
        help="Optional running backend API base URL, e.g. http://localhost:8000/api/v1",
    )
    args = parser.parse_args()

    return asyncio.run(
        seed_demo_data(
            source_dir=args.source_dir,
            runtime_dir=args.runtime_dir,
            report_path=args.report_path,
            api_base_url=args.api_base_url,
        )
    )


async def seed_demo_data(
    *,
    source_dir: Path,
    runtime_dir: Path,
    report_path: Path,
    api_base_url: str | None = None,
) -> int:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    raw = {
        "work_orders": _read_csv(source_dir / "work_orders.csv"),
        "operations": _read_csv(source_dir / "operations.csv"),
        "machines": _read_csv(source_dir / "machines.csv"),
        "incidents": _read_csv(source_dir / "incidents.csv"),
        "execution_feedback": _read_csv(source_dir / "execution_feedback.csv"),
    }
    report = validate_customer_payloads(
        raw_work_orders=raw["work_orders"],
        raw_operations=raw["operations"],
        raw_machines=raw["machines"],
        raw_incidents=raw["incidents"],
    )

    adapter = CSVAdapter(source_dir)
    snapshot = await adapter.fetch_current_schedule(workshop_id="DEMO-LINE-01")
    affected = _affected_operations(raw["operations"], raw["incidents"][0])

    artifacts = {
        "source_dir": str(source_dir),
        "work_order_count": len(raw["work_orders"]),
        "operation_count": len(raw["operations"]),
        "machine_count": len(raw["machines"]),
        "incident_count": len(raw["incidents"]),
        "execution_feedback_count": len(raw["execution_feedback"]),
        "affected_operation_count": len(affected),
        "affected_work_order_count": len({item["work_order_id"] for item in affected}),
        "validation_report": report.model_dump(mode="json"),
    }

    _write_json(runtime_dir / "demo_summary.json", artifacts)
    _write_json(runtime_dir / "schedule_snapshot.json", snapshot.model_dump(mode="json"))
    _write_json(runtime_dir / "incident_payload.json", raw["incidents"][0])
    _write_json(runtime_dir / "affected_operations.json", affected)
    _write_json(runtime_dir / "demo_validation_report.json", report.model_dump(mode="json"))
    if api_base_url:
        api_result = _seed_running_api(
            api_base_url=api_base_url,
            schedule_snapshot=snapshot.model_dump(mode="json"),
            incident=raw["incidents"][0],
        )
        _write_json(runtime_dir / "api_seed_result.json", api_result)
    report_path.write_text(
        _render_markdown_report(artifacts),
        encoding="utf-8",
    )

    print(f"Demo data validated: blocking_errors={report.blocking_errors}, warnings={report.warnings}")
    print(f"Wrote runtime artifacts to {runtime_dir}")
    print(f"Wrote validation report to {report_path}")
    if api_base_url:
        print(f"Seeded running API at {api_base_url}")
    return 0 if report.is_valid else 1


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _seed_running_api(
    *,
    api_base_url: str,
    schedule_snapshot: dict[str, Any],
    incident: dict[str, Any],
) -> dict[str, Any]:
    base_url = api_base_url.rstrip("/")
    snapshot_response = _post_json(
        f"{base_url}/schedule-snapshots",
        schedule_snapshot,
    )
    incident_response = _post_json(
        f"{base_url}/incidents",
        {
            "incident_type": "equipment_failure",
            "external_event_id": incident["incident_id"],
            "occurred_at": incident["start_time"],
            "workshop_id": "DEMO-LINE-01",
            "resource_id": incident["machine_id"],
            "report_source": "MES",
            "source_system": "sandbox_demo",
            "description": incident["description"],
            "idempotency_key": f"demo:{incident['incident_id']}",
            "raw_payload": incident,
        },
    )
    return {
        "schedule_snapshot": snapshot_response,
        "incident": incident_response,
    }


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with request.urlopen(req, timeout=10) as response:
        response_body = response.read().decode("utf-8")
    return json.loads(response_body) if response_body else {}


def _affected_operations(
    operations: list[dict[str, Any]],
    incident: dict[str, Any],
) -> list[dict[str, Any]]:
    machine_id = incident["machine_id"]
    start = datetime.fromisoformat(incident["start_time"])
    end = start + timedelta(hours=4)
    affected: list[dict[str, Any]] = []
    for operation in operations:
        if operation.get("machine_id") != machine_id:
            continue
        op_start = datetime.fromisoformat(operation["start_time"])
        op_end = datetime.fromisoformat(operation["end_time"])
        if op_start < end and op_end > start:
            affected.append(
                {
                    "operation_id": operation["operation_id"],
                    "work_order_id": operation["work_order_id"],
                    "machine_id": operation["machine_id"],
                    "start_time": operation["start_time"],
                    "end_time": operation["end_time"],
                    "priority_hint": "urgent_or_high",
                }
            )
    return affected


def _render_markdown_report(artifacts: dict[str, Any]) -> str:
    validation = artifacts["validation_report"]
    issues = validation["issues"]
    issue_lines = "\n".join(
        f"- `{item['severity']}` `{item['code']}` {item['entity_type']} {item.get('entity_id')}: {item['message']}"
        for item in issues
    ) or "- No validation issues."
    return f"""# Demo Validation Report

## Dataset

| Item | Count |
| --- | ---: |
| Work orders | {artifacts["work_order_count"]} |
| Operations | {artifacts["operation_count"]} |
| Machines | {artifacts["machine_count"]} |
| Incidents | {artifacts["incident_count"]} |
| Execution feedback rows | {artifacts["execution_feedback_count"]} |
| Affected operations in scenario window | {artifacts["affected_operation_count"]} |
| Affected work orders in scenario window | {artifacts["affected_work_order_count"]} |

## Adapter-Level Validation

| Check | Result |
| --- | ---: |
| Total records | {validation["total_records"]} |
| Valid records | {validation["valid_records"]} |
| Invalid records | {validation["invalid_records"]} |
| Missing required fields | {validation["missing_required_fields"]} |
| Enum errors | {validation["enum_errors"]} |
| Time parse errors | {validation["time_parse_errors"]} |
| Reference integrity errors | {validation["reference_integrity_errors"]} |
| Blocking errors | {validation["blocking_errors"]} |
| Warnings | {validation["warnings"]} |

## Result

```text
blocking_errors: {validation["blocking_errors"]}
warnings: {validation["warnings"]}
status: {"PASS" if validation["blocking_errors"] == 0 else "FAIL"}
```

## Issues

{issue_lines}

## Interpretation

The sandbox dataset is suitable for a representative customer demo when
`blocking_errors` is 0. This proves adapter-level data consistency for the
demo data only. It does not prove real customer ERP/MES/APS integration.
"""


if __name__ == "__main__":
    raise SystemExit(main())
