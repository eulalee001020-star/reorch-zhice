"""Evaluate synthetic-realistic replay evidence packs."""

from __future__ import annotations

from app.models.synthetic_replay_evidence import (
    SyntheticReplayEvidenceResponse,
    SyntheticReplayRow,
    SyntheticScenarioEvidenceMetrics,
    SyntheticScenarioPack,
)


class SyntheticReplayEvidenceEvaluator:
    """Scores evidence-only replay packs without overstating solver readiness."""

    def evaluate(
        self,
        *,
        pack_id: str,
        scenarios: list[SyntheticScenarioPack],
    ) -> SyntheticReplayEvidenceResponse:
        metrics = [_scenario_metrics(scenario) for scenario in scenarios]
        return SyntheticReplayEvidenceResponse(
            pack_id=pack_id,
            scenario_metrics=metrics,
            total_incident_count=sum(item.incident_count for item in metrics),
            total_planner_decision_count=sum(item.planner_decision_count for item in metrics),
            total_execution_feedback_count=sum(item.execution_feedback_count for item in metrics),
            can_run_solver_replay=all(item.can_run_solver_replay for item in metrics),
            required_next_tables_for_solver=[
                "work_orders",
                "operations",
                "resources",
                "current_schedule",
                "routing_precedence",
                "customer_constraint_tables_if_available",
            ],
            claim_boundary=(
                "This evaluates public-source-derived synthetic replay evidence. "
                "It can support BP technical validation, ROI proxy demonstration, "
                "and PoC pre-checks. It is not real customer production evidence, "
                "not customer ROI proof, and not solver replay unless baseline "
                "work order, operation, resource, and schedule tables are present."
            ),
        )


def _scenario_metrics(scenario: SyntheticScenarioPack) -> SyntheticScenarioEvidenceMetrics:
    incidents = scenario.historical_anomaly_cases
    decisions = scenario.planner_decisions
    feedback = scenario.execution_feedback
    policy = scenario.counterfactual_policy_matrix
    incident_ids = _ids(incidents, "incident_id")
    decision_incidents = _ids(decisions, "incident_id")
    feedback_incidents = _ids(feedback, "incident_id")
    blockers: list[str] = []
    warnings = [
        "synthetic_realistic_not_customer_production_log",
        "solver_replay_requires_baseline_schedule_tables",
    ]
    if len(incidents) < 10:
        blockers.append("fewer_than_10_incidents")
    if not decisions:
        blockers.append("missing_planner_decisions")
    if not feedback:
        blockers.append("missing_execution_feedback")

    readiness_score = _readiness_score(scenario)
    matched_decision_rate = _rate(len(incident_ids & decision_incidents), len(incident_ids))
    matched_feedback_rate = _rate(len(incident_ids & feedback_incidents), len(incident_ids))
    accepted_or_tweak = sum(
        1
        for row in decisions
        if str(row.get("planner_action")) in {"accepted", "accepted_with_tweak"}
    )
    reference_or_reject = sum(
        1
        for row in decisions
        if str(row.get("planner_action")) in {"reference_only", "rejected"}
    )
    decision_time_saved = [
        _float(row.get("manual_baseline_decision_time_min"))
        - _float(row.get("candidate_generation_time_min"))
        for row in feedback
    ]
    delay_reduction = [
        _float(row.get("delay_before_min")) - _float(row.get("delay_after_min"))
        for row in feedback
    ]
    trial_reduction = [
        _float(row.get("planner_trial_count_before"))
        - _float(row.get("planner_trial_count_after"))
        for row in feedback
    ]
    medium_or_high = sum(
        1
        for row in policy
        if str(row.get("confidence_level")).lower() in {"medium", "high"}
    )

    evidence_level = "blocked"
    if not blockers and readiness_score >= 0.85 and matched_decision_rate >= 0.95:
        evidence_level = "synthetic_shadow_ready"
    elif not blockers:
        evidence_level = "synthetic_replay_ready"

    return SyntheticScenarioEvidenceMetrics(
        scenario_id=scenario.scenario_id,
        evidence_level=evidence_level,
        incident_count=len(incidents),
        planner_decision_count=len(decisions),
        execution_feedback_count=len(feedback),
        hidden_rule_count=len(scenario.hidden_rules_freeze_logic),
        policy_matrix_cell_count=len(policy),
        matched_decision_rate=matched_decision_rate,
        matched_feedback_rate=matched_feedback_rate,
        planner_accept_or_tweak_rate=_rate(accepted_or_tweak, len(decisions)),
        reference_or_reject_rate=_rate(reference_or_reject, len(decisions)),
        average_candidate_generation_time_min=_avg(
            [_float(row.get("candidate_generation_time_min")) for row in feedback]
        ),
        average_manual_baseline_decision_time_min=_avg(
            [_float(row.get("manual_baseline_decision_time_min")) for row in feedback]
        ),
        average_decision_time_saved_min=_avg(decision_time_saved),
        average_delay_reduction_min=_avg(delay_reduction),
        average_trial_reduction=_avg(trial_reduction),
        audit_complete_rate=_rate(
            sum(1 for row in feedback if _truthy(row.get("audit_complete"))),
            len(feedback),
        ),
        secondary_anomaly_rate=_rate(
            sum(1 for row in feedback if _truthy(row.get("secondary_anomaly"))),
            len(feedback),
        ),
        medium_or_high_confidence_policy_cells=medium_or_high,
        readiness_score=readiness_score,
        can_run_solver_replay=False,
        blockers=blockers,
        warnings=warnings,
    )


def _readiness_score(scenario: SyntheticScenarioPack) -> float:
    if scenario.data_readiness_report:
        return round(_float(scenario.data_readiness_report[0].get("readiness_score")), 4)
    return 0.0


def _ids(rows: list[SyntheticReplayRow], key: str) -> set[str]:
    return {str(row.get(key)) for row in rows if row.get(key) is not None}


def _float(value: object) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "t", "yes", "y", "1"}
