"""Evaluate the three-industry synthetic replay Excel pack.

This script intentionally treats the workbook as public-source-derived
synthetic evidence. It does not convert the pack into customer evidence.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from app.models.synthetic_replay_evidence import SyntheticScenarioPack
from app.services.synthetic_replay_evidence import SyntheticReplayEvidenceEvaluator


SCENARIO_PREFIXES = {
    "CNC_AUTO_FJSP": "CNC_AU",
    "SEMI_LED_FAB": "SEMI_L",
    "PCBA_SMT_TEST": "PCBA_S",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()

    scenarios = load_workbook(args.workbook)
    response = SyntheticReplayEvidenceEvaluator().evaluate(
        pack_id=args.workbook.stem,
        scenarios=scenarios,
    )
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            response.model_dump_json(indent=2),
            encoding="utf-8",
        )
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(_markdown(response.model_dump(mode="json")), encoding="utf-8")
    print(response.model_dump_json(indent=2))


def load_workbook(path: Path) -> list[SyntheticScenarioPack]:
    sheets = pd.read_excel(path, sheet_name=None)
    summary_by_id = {
        str(row.get("scenario_id")): _clean_row(row)
        for row in sheets["ScenarioSummary"].to_dict("records")
    }
    scenarios: list[SyntheticScenarioPack] = []
    for scenario_id, prefix in SCENARIO_PREFIXES.items():
        scenarios.append(
            SyntheticScenarioPack(
                scenario_id=scenario_id,
                scenario_summary=summary_by_id.get(scenario_id, {}),
                historical_anomaly_cases=_records(sheets[f"{prefix}_historical_anomaly_c"]),
                planner_decisions=_records(sheets[f"{prefix}_planner_decisions"]),
                execution_feedback=_records(sheets[f"{prefix}_execution_feedback"]),
                hidden_rules_freeze_logic=_records(sheets[f"{prefix}_hidden_rules_freeze_"]),
                counterfactual_policy_matrix=_records(sheets[f"{prefix}_counterfactual_polic"]),
                field_mapping=_records(sheets[f"{prefix}_field_mapping"]),
                data_readiness_report=_records(sheets[f"{prefix}_data_readiness_repor"]),
            )
        )
    return scenarios


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [_clean_row(row) for row in df.to_dict("records")]


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in row.items():
        if pd.isna(value):
            clean[str(key)] = None
        else:
            clean[str(key)] = value.item() if hasattr(value, "item") else value
    return clean


def _markdown(response: dict[str, Any]) -> str:
    lines = [
        "# Three-Industry Synthetic Replay Pack Evaluation",
        "",
        "## Claim Boundary",
        "",
        response["claim_boundary"],
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total incidents | {response['total_incident_count']} |",
        f"| Planner decisions | {response['total_planner_decision_count']} |",
        f"| Execution feedback rows | {response['total_execution_feedback_count']} |",
        f"| Can run solver replay | {response['can_run_solver_replay']} |",
        "",
        "## Scenario Metrics",
        "",
        "| Scenario | Evidence level | Incidents | Decisions | Feedback | Decision time saved min | Delay reduction min | Trial reduction | Audit complete | Secondary anomaly | Solver replay |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in response["scenario_metrics"]:
        lines.append(
            "| {scenario_id} | {evidence_level} | {incident_count} | "
            "{planner_decision_count} | {execution_feedback_count} | "
            "{average_decision_time_saved_min:.2f} | "
            "{average_delay_reduction_min:.2f} | "
            "{average_trial_reduction:.2f} | "
            "{audit_complete_rate:.2%} | "
            "{secondary_anomaly_rate:.2%} | "
            "{can_run_solver_replay} |".format(**item)
        )
    lines.extend(
        [
            "",
            "## Required Next Tables For Solver Replay",
            "",
            *[f"- `{table}`" for table in response["required_next_tables_for_solver"]],
            "",
            "## Safe External Wording",
            "",
            (
                "ReOrch has evaluated a public-source-derived synthetic-realistic "
                "three-industry replay pack covering CNC automotive FJSP, "
                "semiconductor/LED fab, and PCBA SMT/test repair scenarios. "
                "The pack supports evidence-structure, ROI-proxy, and PoC "
                "pre-check validation. It is not real customer production data, "
                "not customer ROI proof, and not production writeback evidence."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
