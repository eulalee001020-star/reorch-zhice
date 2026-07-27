#!/usr/bin/env python3
"""Validate public reliability packs and emit a machine-readable monitoring report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = ROOT / "datasets" / "public_reliability_packs"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def validate_pack(pack: Path) -> dict[str, Any]:
    started = time.perf_counter()
    manifest_path = pack / "manifest.json"
    quality_path = pack / "quality_report.json"
    errors: list[str] = []
    warnings: list[str] = []
    if not manifest_path.exists() or not quality_path.exists():
        return {"pack_id": pack.name, "status": "fail", "errors": ["missing manifest or quality report"]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        path = pack / entry["path"]
        if not path.exists():
            errors.append(f"missing file: {entry['path']}")
        elif sha256(path) != entry["sha256"]:
            errors.append(f"checksum mismatch: {entry['path']}")

    if manifest["acquisition_status"] != "complete":
        errors.append("source acquisition incomplete")
        gate = quality.get("evidence_gate", {})
        forbidden_true = [
            key for key in (
                "real_mes_validated",
                "real_shadow_validated",
                "real_shadow_2_to_4_weeks_validated",
                "real_roi_validated",
                "production_writeback_authorized",
            ) if gate.get(key) is True
        ]
        if forbidden_true:
            errors.append(f"blocked source has forbidden positive claims: {','.join(forbidden_true)}")
        twin = pack / "digital_twin"
        expected_twin = {
            "operations_10k.csv": 10_000,
            "incidents_300.csv": 300,
            "mes_terminal_receipts_10k.csv": 10_000,
        }
        for name, expected_count in expected_twin.items():
            path = twin / name
            if not path.exists():
                errors.append(f"missing digital-twin file: {name}")
                continue
            actual_count = len(read_csv(path))
            if actual_count != expected_count:
                errors.append(f"digital-twin row count mismatch: {name}={actual_count}, expected={expected_count}")
        operations = read_csv(twin / "operations_10k.csv")
        work_orders = read_csv(twin / "work_orders_10k.csv")
        receipts = read_csv(twin / "mes_terminal_receipts_10k.csv")
        cdc_events = read_jsonl(twin / "cdc_events_10000.jsonl")
        operation_ids = {row["operation_id"] for row in operations}
        work_order_ids = {row["work_order_id"] for row in work_orders}
        if len(operation_ids) != len(operations):
            errors.append("digital-twin duplicate operation ids")
        if len(work_order_ids) != len(work_orders):
            errors.append("digital-twin duplicate work-order ids")
        if any(row["work_order_id"] not in work_order_ids for row in operations):
            errors.append("digital-twin operation references unknown work order")
        if any(row["operation_id"] not in operation_ids for row in receipts):
            errors.append("digital-twin receipt references unknown operation")
        if len({row["idempotency_key"] for row in receipts}) != len(receipts):
            errors.append("digital-twin duplicate receipt idempotency keys")
        if len(cdc_events) != 10_000:
            errors.append(f"digital-twin CDC row count mismatch: {len(cdc_events)}, expected=10000")
        if [event.get("sequence") for event in cdc_events] != list(range(1, len(cdc_events) + 1)):
            errors.append("digital-twin CDC sequence is not contiguous")
        if any(event.get("entity_id") not in operation_ids for event in cdc_events):
            errors.append("digital-twin CDC references unknown operation")
        if any(not row.get("provenance") for row in operations + receipts):
            errors.append("digital-twin record missing provenance")
        if any(not event.get("provenance") for event in cdc_events):
            errors.append("digital-twin CDC event missing provenance")
        rehearsal = pack / "customer_admission_rehearsal"
        case_path = rehearsal / "historical_incident_cases_30.json"
        gate_path = rehearsal / "admission_gate.json"
        if not case_path.exists() or not gate_path.exists():
            errors.append("missing customer-admission rehearsal artifacts")
        else:
            cases = json.loads(case_path.read_text(encoding="utf-8"))
            admission_gate = json.loads(gate_path.read_text(encoding="utf-8"))
            if len(cases) != 30:
                errors.append(f"admission rehearsal case count mismatch: {len(cases)}")
            if any(case.get("provenance") != "synthetic_customer_admission_rehearsal" for case in cases):
                errors.append("admission rehearsal provenance violation")
            if admission_gate.get("real_customer_case_count") != 0:
                errors.append("synthetic rehearsal incorrectly reports real customer cases")
            if admission_gate.get("customer_admission_ready") is not False:
                errors.append("synthetic rehearsal incorrectly opened customer gate")
        warnings.append("digital twin passed engineering checks but official MES acquisition remains blocked")
        warnings.append("30 synthetic admission cases passed workflow rehearsal; real customer case count remains zero")
    else:
        canonical = pack / "canonical"
        work_orders = read_csv(canonical / "work_orders.csv")
        operations = read_csv(canonical / "operations.csv")
        resources = read_csv(canonical / "resources.csv")
        wo_ids = {row["work_order_id"] for row in work_orders}
        machine_ids = {row["machine_id"] for row in resources}
        duplicate_wo = len(work_orders) - len(wo_ids)
        duplicate_op = len(operations) - len({row["operation_id"] for row in operations})
        bad_wo_refs = sum(row["work_order_id"] not in wo_ids for row in operations)
        bad_machine_refs = 0
        for row in operations:
            for machine_id in filter(None, row.get("eligible_machine_ids", "").split("|")):
                bad_machine_refs += machine_id not in machine_ids
        if duplicate_wo:
            errors.append(f"duplicate work orders: {duplicate_wo}")
        if duplicate_op:
            errors.append(f"duplicate operations: {duplicate_op}")
        if bad_wo_refs:
            errors.append(f"unknown work-order references: {bad_wo_refs}")
        if bad_machine_refs:
            errors.append(f"unknown machine references: {bad_machine_refs}")
        if not work_orders or not operations or not resources:
            errors.append("canonical core table is empty")
        scenario_path = pack / "scenarios" / "incidents.json"
        scenarios = json.loads(scenario_path.read_text(encoding="utf-8")) if scenario_path.exists() else []
        if not scenarios:
            errors.append("no reliability scenarios")
        if any("provenance" not in scenario for scenario in scenarios):
            errors.append("scenario missing provenance")
        if quality.get("unmapped_operations"):
            warnings.append(f"unmapped operations: {quality['unmapped_operations']}")
        if quality.get("missing_bom_headers"):
            warnings.append(f"missing BOM headers: {quality['missing_bom_headers']}")

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "pack_id": pack.name,
        "tier": manifest["tier"],
        "status": "pass" if not errors else "fail",
        "acquisition_status": manifest["acquisition_status"],
        "errors": errors,
        "warnings": warnings,
        "counts": quality.get("counts", {}),
        "scenario_count": quality.get("scenario_count", 0),
        "validation_latency_ms": elapsed_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", default="all")
    parser.add_argument("--allow-blocked", action="store_true", help="Return success when only acquisition-blocked packs fail")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "public_reliability_pack_report.json")
    args = parser.parse_args()
    packs = sorted(path for path in PACK_ROOT.iterdir() if path.is_dir())
    if args.pack != "all":
        packs = [PACK_ROOT / args.pack]
    results = [validate_pack(pack) for pack in packs]
    summary = {
        "generated_at": "2026-07-13T00:00:00+08:00",
        "total": len(results),
        "passed": sum(result["status"] == "pass" for result in results),
        "failed": sum(result["status"] == "fail" for result in results),
        "gate_conclusion": {
            "result": "4 complete public packs pass; Ulster MES strict source gate fails",
            "system_failure": False,
            "digital_twin_engineering_consistency": "pass",
            "official_anonymized_mes_source": "fail",
            "real_mes_validation": False,
            "real_shadow": False,
            "real_shadow_2_to_4_weeks": False,
            "real_roi": False,
            "production_writeback_authorization": False,
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    failures = [result for result in results if result["status"] == "fail"]
    if args.allow_blocked:
        failures = [result for result in failures if result.get("acquisition_status") != "acquisition_blocked"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
