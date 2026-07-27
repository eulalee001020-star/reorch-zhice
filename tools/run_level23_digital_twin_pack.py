"""Evaluate a ReOrch Level 2/3 digital-twin workbook pack.

This CLI is intentionally outside the app runtime path: it uses pandas for
offline workbook parsing, then calls the production evaluator with plain rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHEET_TO_FIELD = {
    "Resources": "resources",
    "WorkOrders": "work_orders",
    "Operations": "operations",
    "RoutingPrecedence": "routing_precedence",
    "ScheduleSnapshot": "schedule_snapshot",
    "Constraints": "constraints",
    "MaterialInventory": "material_inventory",
    "Incidents": "incidents",
    "ManualOutcomes": "manual_outcomes",
    "ExecutionFeedback": "execution_feedback",
    "CandidatePlans": "candidate_plans",
    "ReplayComparison": "replay_comparison",
    "PolicyEffectiveness": "policy_effectiveness",
    "ReadinessScorecard": "readiness_scorecard",
}


def main() -> None:
    from app.services.level23_digital_twin import Level23DigitalTwinReplayEvaluator

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    request = load_request(args.workbook)
    response = Level23DigitalTwinReplayEvaluator().evaluate(request)
    payload = response.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


def load_request(path: Path):
    from app.models.level23_digital_twin import Level23DigitalTwinReplayRequest
    from app.services.level23_digital_twin import workbook_pack_id

    workbook = pd.ExcelFile(path)
    values: dict[str, Any] = {
        "pack_id": workbook_pack_id(path),
        "source_workbook_name": path.name,
    }
    for sheet_name, field_name in SHEET_TO_FIELD.items():
        if sheet_name not in workbook.sheet_names:
            values[field_name] = []
            continue
        values[field_name] = _read_rows(workbook, sheet_name)
    return Level23DigitalTwinReplayRequest(**values)


def _read_rows(workbook: pd.ExcelFile, sheet_name: str) -> list[dict[str, Any]]:
    if sheet_name in {"ManualOutcomes", "ExecutionFeedback"}:
        header = _find_header_row(workbook, sheet_name)
        frame = workbook.parse(sheet_name, header=header)
    else:
        frame = workbook.parse(sheet_name)
    frame = frame.dropna(how="all")
    return [_clean_row(row) for row in frame.to_dict(orient="records")]


def _find_header_row(workbook: pd.ExcelFile, sheet_name: str) -> int:
    raw = workbook.parse(sheet_name, header=None)
    expected = "incident_id"
    for index, row in raw.iterrows():
        values = {str(value).strip() for value in row.tolist() if pd.notna(value)}
        if expected in values:
            return int(index)
    return 0


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if pd.isna(value):
            cleaned[str(key)] = None
        elif hasattr(value, "isoformat"):
            cleaned[str(key)] = value.isoformat()
        else:
            cleaned[str(key)] = value
    return cleaned


if __name__ == "__main__":
    main()
