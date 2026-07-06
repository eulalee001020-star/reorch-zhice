"""Level 2/3 digital-twin replay rehearsal evaluator."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from pathlib import Path

from app.models.level23_digital_twin import (
    Level23DigitalTwinReplayRequest,
    Level23DigitalTwinReplayResponse,
    Level23ExecutionMetrics,
    Level23LinkageMetrics,
    Level23PolicySummary,
    Level23ReplayMetrics,
    Level23TableStatus,
    TwinRow,
)
from app.models.production_readiness import ProductionReadinessEvidence
from app.services.production_readiness import ProductionReadinessGate


class Level23DigitalTwinReplayEvaluator:
    """Evaluates a Level 2/3 workbook-shaped rehearsal data pack."""

    def evaluate(
        self, request: Level23DigitalTwinReplayRequest
    ) -> Level23DigitalTwinReplayResponse:
        table_statuses = _table_statuses(request)
        readiness_score = _readiness_score(request.readiness_scorecard, table_statuses)
        linkage = _linkage_metrics(request)
        replay = _replay_metrics(request)
        execution = _execution_metrics(request.execution_feedback)
        policies = _policy_summaries(request)
        rehearsal_level = _rehearsal_level(
            table_statuses=table_statuses,
            readiness_score=readiness_score,
            linkage=linkage,
            replay=replay,
        )
        production_readiness = ProductionReadinessGate().evaluate(
            _production_evidence(request, readiness_score, replay)
        )
        return Level23DigitalTwinReplayResponse(
            pack_id=request.pack_id,
            source_workbook_name=request.source_workbook_name,
            rehearsal_level=rehearsal_level,
            readiness_score=readiness_score,
            table_statuses=table_statuses,
            linkage_metrics=linkage,
            replay_metrics=replay,
            execution_metrics=execution,
            policy_summaries=policies,
            production_readiness=production_readiness,
            next_actions=_next_actions(rehearsal_level, production_readiness.decision),
            claim_boundary=(
                "This Level 2/3 digital-twin pack can validate parser coverage, "
                "schedule-context linkage, replay comparison, and simulated "
                "feedback learning. Simulated planner outcomes and execution "
                "feedback must be replaced by real customer shadow/execution data "
                "before ROI, production readiness, or Recovery Policy Graph "
                "confidence claims."
            ),
        )


def _table_statuses(request: Level23DigitalTwinReplayRequest) -> list[Level23TableStatus]:
    specs = [
        ("resources", request.resources, 1, True),
        ("work_orders", request.work_orders, 1, True),
        ("operations", request.operations, 1, True),
        ("routing_precedence", request.routing_precedence, 1, True),
        ("schedule_snapshot", request.schedule_snapshot, 1, True),
        ("incidents", request.incidents, 1, True),
        ("candidate_plans", request.candidate_plans, 1, True),
        ("replay_comparison", request.replay_comparison, 1, True),
        ("manual_outcomes", request.manual_outcomes, 1, True),
        ("execution_feedback", request.execution_feedback, 1, True),
        ("policy_effectiveness", request.policy_effectiveness, 1, False),
        ("readiness_scorecard", request.readiness_scorecard, 1, False),
    ]
    statuses: list[Level23TableStatus] = []
    for table_name, rows, min_rows, required in specs:
        notes: list[str] = []
        if len(rows) < min_rows:
            status = "blocker" if required else "warning"
            notes.append(f"expected_at_least_{min_rows}_rows")
        else:
            status = "pass"
        if table_name in {"manual_outcomes", "execution_feedback"} and rows:
            if _source_is_simulated(rows):
                notes.append("simulated_evidence_not_customer_proof")
        statuses.append(
            Level23TableStatus(
                table_name=table_name,
                row_count=len(rows),
                required=required,
                status=status,
                notes=notes,
            )
        )
    return statuses


def _readiness_score(
    rows: list[TwinRow],
    table_statuses: list[Level23TableStatus],
) -> float:
    scores = [_float(row.get("score")) for row in rows if row.get("score") is not None]
    if scores:
        return round(sum(scores) / len(scores), 4)
    blocked = sum(1 for status in table_statuses if status.status == "blocker")
    warning = sum(1 for status in table_statuses if status.status == "warning")
    return max(0.0, round(1.0 - 0.2 * blocked - 0.05 * warning, 4))


def _linkage_metrics(request: Level23DigitalTwinReplayRequest) -> Level23LinkageMetrics:
    schedule_ids = {str(row.get("schedule_id")) for row in request.schedule_snapshot}
    operation_ids = {str(row.get("operation_id")) for row in request.operations}
    work_order_ids = {str(row.get("work_order_id")) for row in request.work_orders}
    candidate_incident_ids = {
        str(row.get("incident_id")) for row in request.candidate_plans if row.get("incident_id")
    }
    schedule_links = 0
    operation_links = 0
    work_order_links = 0
    candidate_links = 0
    subgraph_ready = 0
    for incident in request.incidents:
        has_schedule = str(incident.get("linked_schedule_id")) in schedule_ids
        has_operation = str(incident.get("linked_operation_id")) in operation_ids
        has_work_order = str(incident.get("linked_work_order_id")) in work_order_ids
        has_candidate = str(incident.get("incident_id")) in candidate_incident_ids
        schedule_links += int(has_schedule)
        operation_links += int(has_operation)
        work_order_links += int(has_work_order)
        candidate_links += int(has_candidate)
        subgraph_ready += int(has_operation and has_work_order and has_candidate)
    count = len(request.incidents)
    return Level23LinkageMetrics(
        incident_count=count,
        incident_to_schedule_link_count=schedule_links,
        incident_to_operation_link_count=operation_links,
        incident_to_work_order_link_count=work_order_links,
        incident_with_candidate_count=candidate_links,
        affected_subgraph_ready_count=subgraph_ready,
        affected_subgraph_ready_rate=_rate(subgraph_ready, count),
    )


def _replay_metrics(request: Level23DigitalTwinReplayRequest) -> Level23ReplayMetrics:
    replay_rows = request.replay_comparison
    top1_match = sum(
        1
        for row in replay_rows
        if _text(row.get("manual_strategy")) == _text(row.get("system_top1_strategy"))
    )
    top3_coverage = sum(
        1 for row in replay_rows if _is_yes(row.get("top3_contains_manual_strategy"))
    )
    hard_feasible = sum(
        1 for row in replay_rows if _is_yes(row.get("hard_feasible_top1"))
    )
    review_needed = sum(
        1 for row in replay_rows if _is_yes(row.get("planner_review_needed"))
    )
    delay_deltas = [
        _float(row.get("delay_delta_system_minus_manual"))
        for row in replay_rows
        if row.get("delay_delta_system_minus_manual") is not None
    ]
    perturb_deltas = [
        _float(row.get("perturbation_delta_system_minus_manual"))
        for row in replay_rows
        if row.get("perturbation_delta_system_minus_manual") is not None
    ]
    feasible_candidates = sum(
        1
        for row in request.candidate_plans
        if _is_yes(row.get("feasible_flag")) or _float(row.get("hard_violation_count")) == 0
    )
    return Level23ReplayMetrics(
        incident_count=len(request.incidents),
        candidate_plan_count=len(request.candidate_plans),
        feasible_candidate_count=feasible_candidates,
        simulated_manual_outcome_count=len(request.manual_outcomes),
        simulated_execution_feedback_count=len(request.execution_feedback),
        top1_exact_match_count=top1_match,
        top1_exact_match_rate=_rate(top1_match, len(replay_rows)),
        top3_manual_coverage_count=top3_coverage,
        top3_manual_coverage_rate=_rate(top3_coverage, len(replay_rows)),
        hard_feasible_top1_count=hard_feasible,
        hard_feasible_top1_rate=_rate(hard_feasible, len(replay_rows)),
        planner_review_needed_count=review_needed,
        planner_review_needed_rate=_rate(review_needed, len(replay_rows)),
        average_delay_delta_system_minus_manual=_average(delay_deltas),
        average_perturbation_delta_system_minus_manual=_average(perturb_deltas),
    )


def _execution_metrics(rows: list[TwinRow]) -> Level23ExecutionMetrics:
    success = sum(1 for row in rows if _is_yes(row.get("execution_success_flag")))
    secondary = sum(1 for row in rows if _is_yes(row.get("secondary_incident_flag")))
    delays = [
        _float(row.get("actual_delay_min"))
        for row in rows
        if row.get("actual_delay_min") is not None
    ]
    satisfaction = [
        _float(row.get("planner_satisfaction_score"))
        for row in rows
        if row.get("planner_satisfaction_score") is not None
    ]
    return Level23ExecutionMetrics(
        execution_success_count=success,
        execution_success_rate=_rate(success, len(rows)),
        secondary_incident_count=secondary,
        secondary_incident_rate=_rate(secondary, len(rows)),
        average_actual_delay_min=_average(delays),
        average_planner_satisfaction_score=_average(satisfaction),
    )


def _policy_summaries(request: Level23DigitalTwinReplayRequest) -> list[Level23PolicySummary]:
    if request.policy_effectiveness:
        return [
            Level23PolicySummary(
                strategy_type=str(row.get("strategy_type")),
                candidate_count=int(_float(row.get("candidate_count"))),
                feasible_rate=round(_float(row.get("feasible_rate")), 4),
                manual_selection_rate=round(_float(row.get("manual_selection_rate")), 4),
                execution_success_rate=round(_float(row.get("execution_success_rate")), 4),
                average_predicted_delay_min=round(_float(row.get("avg_predicted_delay_min")), 2),
                average_actual_delay_min=round(_float(row.get("avg_actual_delay_min")), 2),
                confidence_level=_simulated_confidence(row),
                source_boundary="simulated_policy_effectiveness_not_customer_evidence",
            )
            for row in request.policy_effectiveness
            if row.get("strategy_type")
        ]
    return _derive_policy_summaries(request)


def _derive_policy_summaries(request: Level23DigitalTwinReplayRequest) -> list[Level23PolicySummary]:
    by_strategy: dict[str, list[TwinRow]] = defaultdict(list)
    for row in request.candidate_plans:
        by_strategy[str(row.get("strategy_type"))].append(row)
    selected = Counter(str(row.get("manual_strategy")) for row in request.manual_outcomes)
    executed = defaultdict(list)
    for row in request.execution_feedback:
        executed[str(row.get("executed_strategy"))].append(row)

    summaries: list[Level23PolicySummary] = []
    total_manual = len(request.manual_outcomes)
    for strategy, rows in sorted(by_strategy.items()):
        feasible = sum(
            1
            for row in rows
            if _is_yes(row.get("feasible_flag")) or _float(row.get("hard_violation_count")) == 0
        )
        delays = [
            _float(row.get("predicted_delay_min"))
            for row in rows
            if row.get("predicted_delay_min") is not None
        ]
        exec_rows = executed.get(strategy, [])
        exec_success = sum(
            1 for row in exec_rows if _is_yes(row.get("execution_success_flag"))
        )
        actual_delays = [
            _float(row.get("actual_delay_min"))
            for row in exec_rows
            if row.get("actual_delay_min") is not None
        ]
        summaries.append(
            Level23PolicySummary(
                strategy_type=strategy,
                candidate_count=len(rows),
                feasible_rate=_rate(feasible, len(rows)),
                manual_selection_rate=_rate(selected[strategy], total_manual),
                execution_success_rate=_rate(exec_success, len(exec_rows)),
                average_predicted_delay_min=_average(delays),
                average_actual_delay_min=_average(actual_delays),
                confidence_level="simulated_medium" if len(rows) >= 30 else "simulated_low",
                source_boundary="derived_from_simulated_level_2_3_rehearsal_rows",
            )
        )
    return summaries


def _production_evidence(
    request: Level23DigitalTwinReplayRequest,
    readiness_score: float,
    replay: Level23ReplayMetrics,
) -> ProductionReadinessEvidence:
    solver_ms = _p95(
        [
            _float(row.get("solver_runtime_sec")) * 1000
            for row in request.candidate_plans
            if row.get("solver_runtime_sec") is not None
        ]
    )
    return ProductionReadinessEvidence(
        site_id=request.pack_id,
        evidence_source="public_benchmark",
        real_customer_data=False,
        customer_provenance_confirmed=False,
        p0_permission_level="shadow_ready" if readiness_score >= 0.85 else "replay_only",
        p0_readiness_score=readiness_score,
        snapshot_available=bool(request.schedule_snapshot),
        work_order_count=len(request.work_orders),
        operation_count=len(request.operations),
        resource_count=len(request.resources),
        incident_count=len(request.incidents),
        solved_incident_count=replay.incident_count
        if replay.hard_feasible_top1_count == replay.incident_count
        else replay.hard_feasible_top1_count,
        feasible_option_count=replay.feasible_candidate_count,
        infeasible_option_count=max(
            0, replay.candidate_plan_count - replay.feasible_candidate_count
        ),
        planner_decision_count=0,
        planner_override_reason_count=0,
        execution_outcome_count=0,
        strategy_effect_matrix_cell_count=len(request.policy_effectiveness),
        high_confidence_policy_cell_count=0,
        ai_role_limited_to_explanation=True,
        quality_gate_enforced=True,
        human_confirmation_enforced=False,
        p95_solver_latency_ms=solver_ms,
        p95_gate_latency_ms=None,
        concurrent_incident_tested=1,
        performance_targets_tested=[len(request.operations)] if request.operations else [],
    )


def _rehearsal_level(
    *,
    table_statuses: list[Level23TableStatus],
    readiness_score: float,
    linkage: Level23LinkageMetrics,
    replay: Level23ReplayMetrics,
) -> str:
    if any(status.status == "blocker" for status in table_statuses if status.required):
        return "blocked"
    if readiness_score < 0.85:
        return "level_2_schedule_bridge_ready"
    if (
        linkage.affected_subgraph_ready_count == linkage.incident_count
        and replay.top3_manual_coverage_rate > 0
        and replay.simulated_execution_feedback_count == replay.incident_count
    ):
        return "level_2_3_rehearsal_ready"
    return "level_2_schedule_bridge_ready"


def _next_actions(rehearsal_level: str, production_decision: str) -> list[str]:
    actions = [
        "replace_simulated_manual_outcomes_with_real_planner_accept_adjust_reject_records",
        "replace_simulated_execution_feedback_with_mes_iot_qms_execution_outcomes",
        "rerun_replay_on_customer_readonly_schedule_snapshots",
    ]
    if rehearsal_level != "level_2_3_rehearsal_ready":
        actions.insert(0, "fix_level_2_3_table_or_linkage_blockers")
    if production_decision != "production_ready":
        actions.append("keep_writeback_disabled_until_production_readiness_gate_passes")
    return actions


def _source_is_simulated(rows: list[TwinRow]) -> bool:
    source_values = " ".join(
        str(row.get("source_basis", "")) + " " + str(row.get("feedback_source", ""))
        for row in rows[:10]
    ).lower()
    return "simulated" in source_values or "digital_twin" in source_values


def _simulated_confidence(row: TwinRow) -> str:
    count = _float(row.get("candidate_count"))
    if count >= 30 and _float(row.get("feasible_rate")) >= 0.9:
        return "simulated_medium"
    return "simulated_low"


def _rate(numerator: int | float, denominator: int | float) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 4)
    return round(statistics.quantiles(values, n=100, method="inclusive")[94], 4)


def _float(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _is_yes(value) -> bool:
    return _text(value) in {"y", "yes", "true", "1", "pass"}


def workbook_pack_id(path: str | Path) -> str:
    """Stable pack ID helper for CLI adapters."""

    return Path(path).stem.replace("reorch_", "").replace("_data_pack", "")
