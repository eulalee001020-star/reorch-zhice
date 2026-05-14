#!/usr/bin/env python3
"""Validate a ReOrch benchmark dataset and compute baseline scheduling KPIs.

This script deliberately has no third-party dependency so it can run in CI
before the full backend stack is available.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def iter_operations(dataset: dict[str, Any]):
    for wo in dataset.get("work_orders", []):
        for op in wo.get("operations", []):
            yield wo, op


def validate_required_fields(dataset: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ["scenario_id", "workshop_id", "captured_at", "work_orders"]:
        if field not in dataset:
            errors.append(f"missing top-level field: {field}")
    for wo, op in iter_operations(dataset):
        for field in ["operation_id", "work_order_id", "resource_id", "start_time", "end_time"]:
            if field not in op:
                errors.append(f"{wo.get('work_order_id', '<unknown>')}: operation missing {field}")
    return errors


def validate_precedence(dataset: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ops = {op["operation_id"]: op for _, op in iter_operations(dataset)}
    for _, op in iter_operations(dataset):
        start = parse_dt(op["start_time"])
        for pred_id in op.get("predecessor_ids", []):
            pred = ops.get(pred_id)
            if pred is None:
                errors.append(f"{op['operation_id']}: predecessor not found: {pred_id}")
                continue
            if parse_dt(pred["end_time"]) > start:
                errors.append(f"{op['operation_id']}: starts before predecessor {pred_id} ends")
    return errors


def validate_resource_capacity(dataset: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    by_resource: dict[str, list[dict[str, Any]]] = {}
    for _, op in iter_operations(dataset):
        by_resource.setdefault(op["resource_id"], []).append(op)
    for resource_id, ops in by_resource.items():
        ordered = sorted(ops, key=lambda op: parse_dt(op["start_time"]))
        for left, right in zip(ordered, ordered[1:]):
            if parse_dt(left["end_time"]) > parse_dt(right["start_time"]):
                errors.append(
                    f"{resource_id}: {left['operation_id']} overlaps {right['operation_id']}"
                )
    return errors


def compute_kpis(dataset: dict[str, Any]) -> dict[str, Any]:
    total_tardiness = 0.0
    max_tardiness = 0.0
    on_time = 0
    for wo in dataset.get("work_orders", []):
        operations = wo.get("operations", [])
        if not operations:
            continue
        completion = max(parse_dt(op["end_time"]) for op in operations)
        due_date = parse_dt(wo["due_date"])
        tardiness = max(0.0, (completion - due_date).total_seconds() / 60)
        total_tardiness += tardiness
        max_tardiness = max(max_tardiness, tardiness)
        if tardiness == 0:
            on_time += 1
    total_orders = len(dataset.get("work_orders", []))
    return {
        "work_order_count": total_orders,
        "operation_count": sum(1 for _ in iter_operations(dataset)),
        "total_tardiness_minutes": round(total_tardiness, 2),
        "max_tardiness_minutes": round(max_tardiness, 2),
        "otd_rate": round(on_time / total_orders, 4) if total_orders else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dataset",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1] / "datasets" / "dynamic_fjsp_small.json"),
    )
    args = parser.parse_args()

    dataset = load_json(Path(args.dataset))
    errors = []
    errors.extend(validate_required_fields(dataset))
    errors.extend(validate_precedence(dataset))
    errors.extend(validate_resource_capacity(dataset))

    report = {
        "scenario_id": dataset.get("scenario_id"),
        "valid": not errors,
        "errors": errors,
        "kpis": compute_kpis(dataset),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

