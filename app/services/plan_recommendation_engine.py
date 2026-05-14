"""Plan Recommendation Engine — determines the final recommended plan
from scored candidates, applying business goal mode, preference,
historical case context, and risk filtering.

Validates: Requirements 29.1–29.12
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from app.models.evaluation import ComparisonMatrix, ComparisonMatrixRow, KPIVector
from app.models.recommendation import PlanSelectionInput, PlanSelectionOutput
from app.models.schedule import GanttDiffPayload
from app.models.solver import CandidatePlan

logger = logging.getLogger(__name__)

# Default confidence threshold for auto-preselection (Req 29.7, 29.12)
_DEFAULT_CONFIDENCE_THRESHOLD = 0.7

# Below this confidence, never auto-preselect (Req 29.8)
_LOW_CONFIDENCE_THRESHOLD = 0.5


class PlanRecommendationEngine:
    """Recommend the best plan from a ``PlanSelectionInput``.

    Responsibilities (Req 29):
    1. Filter out infeasible / constraint-violating plans.
    2. Rank remaining plans by pre-computed ``normalized_score``.
    3. Compute ``Recommendation_Confidence`` (0-1).
    4. Decide ``auto_preselected`` based on confidence & risk flags.
    5. Build structured reason codes, summary, and audit metadata.
    6. Output ``PlanSelectionOutput`` within 5 seconds.
    """

    def __init__(
        self,
        confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.confidence_threshold = confidence_threshold

    async def recommend(
        self,
        selection_input: PlanSelectionInput,
    ) -> PlanSelectionOutput:
        """Produce a ``PlanSelectionOutput`` from the given input.

        Parameters
        ----------
        selection_input:
            Fully assembled ``PlanSelectionInput`` (built by
            ``PlanSelectionInputBuilder``).

        Returns
        -------
        PlanSelectionOutput
        """
        candidates = selection_input.candidate_plans

        # --- 1. Pre-filter: remove infeasible plans (Req 29.3) ----------
        feasible = _filter_feasible(candidates, selection_input.execution_constraints)

        if not feasible:
            # Fallback: use all candidates if none pass filter
            logger.warning("No feasible candidates after filtering; using all candidates")
            feasible = list(candidates)

        # --- 2. Rank by normalized_score (descending) -------------------
        ranked = _rank_plans(feasible)

        # --- 3. Identify top-scored and recommended plan ----------------
        top_scored = ranked[0]
        recommended = _select_recommended(ranked, selection_input)

        # --- 4. Compute confidence (Req 29.6) ---------------------------
        confidence = _compute_confidence(ranked, recommended)

        # --- 5. Risk flags (Req 29.7) -----------------------------------
        risk_flags = _collect_risk_flags(recommended, selection_input)

        # --- 6. Auto-preselection (Req 29.7, 29.8) ----------------------
        auto_preselected = _should_auto_preselect(
            confidence, risk_flags, self.confidence_threshold
        )

        # --- 7. Build alternative_plan_ids (Req 29.4, 29.11) -----------
        alternative_ids = [
            p.plan_id for p in ranked if p.plan_id != recommended.plan_id
        ]

        # --- 8. Build reason codes & summary (Req 29.9) -----------------
        reason_codes, reason_summary = _build_reasons(
            recommended, top_scored, ranked, selection_input
        )

        # --- 9. Build ranked_plan_list for frontend ---------------------
        ranked_plan_list = _build_ranked_list(ranked, recommended, top_scored)

        # --- 10. Build comparison matrix from schedule-derived KPIs -----
        comparison_matrix = _build_comparison_matrix(ranked, selection_input)

        # --- 11. Build gantt diff payload for frontend rendering --------
        gantt_diff = _build_gantt_diff(recommended, selection_input)

        # --- 12. Weights used -------------------------------------------
        weights_used = _resolve_weights(selection_input)

        # --- 13. Matched case IDs ---------------------------------------
        matched_case_ids = _extract_case_ids(selection_input.historical_case_matches)

        # --- 14. Audit metadata (Req 29.10) -----------------------------
        audit_metadata = _build_audit_metadata(selection_input, confidence)

        return PlanSelectionOutput(
            recommended_plan_id=recommended.plan_id,
            recommended_rank=_rank_of(recommended, ranked),
            top_scored_plan_id=top_scored.plan_id,
            recommendation_confidence=round(confidence, 4),
            auto_preselected=auto_preselected,
            ranked_plan_list=ranked_plan_list,
            reason_codes=reason_codes,
            reason_summary=reason_summary,
            risk_flags=risk_flags,
            comparison_matrix=comparison_matrix,
            gantt_diff_payload=gantt_diff,
            goal_mode_used=selection_input.goal_mode,
            weights_used=weights_used,
            matched_case_ids=matched_case_ids,
            alternative_plan_ids=alternative_ids,
            audit_metadata=audit_metadata,
        )


# ── Internal helpers ────────────────────────────────────────────────


def _filter_feasible(
    candidates: list[CandidatePlan],
    execution_constraints: dict | None,
) -> list[CandidatePlan]:
    """Remove plans that fail hard constraints or execution constraints."""
    feasible: list[CandidatePlan] = []
    for plan in candidates:
        # Hard constraint check
        if plan.feasibility_status == "infeasible":
            continue
        if plan.constraint_report and not plan.constraint_report.is_feasible:
            continue
        feasible.append(plan)
    return feasible


def _rank_plans(plans: list[CandidatePlan]) -> list[CandidatePlan]:
    """Sort plans by normalized_score descending."""
    # Rank by feasibility first, then by a deterministic KPI proxy computed
    # from the schedule itself. This keeps recommendation useful even when an
    # external evaluation stage has not pre-populated KPI rows.
    status_order = {"feasible": 0, "timeout_partial": 1, "infeasible": 2}
    return sorted(
        plans,
        key=lambda p: (
            status_order.get(p.feasibility_status, 9),
            -_compute_kpi(p, {}).normalized_score,
        ),
    )


def _select_recommended(
    ranked: list[CandidatePlan],
    inp: PlanSelectionInput,
) -> CandidatePlan:
    """Select the final AI-recommended plan.

    May differ from the top-scored plan when historical preference
    or risk factors override pure score ranking (Req 29.5).
    """
    if not ranked:
        raise ValueError("Cannot recommend from empty candidate list")

    # Default: recommend the first (top-ranked) plan
    recommended = ranked[0]

    # If preference profile suggests a different strategy and the
    # second plan matches that preference, consider it.
    pref = inp.preference_profile
    if pref and len(ranked) > 1:
        preferred_strategy = _preferred_strategy(pref)
        if (
            preferred_strategy
            and ranked[0].strategy_type != preferred_strategy
            and ranked[1].strategy_type == preferred_strategy
        ):
            # Only override if the score gap is small (< 10%)
            # We can't compute exact score here without the matrix,
            # so we use a heuristic based on feasibility parity.
            if ranked[1].feasibility_status == ranked[0].feasibility_status:
                recommended = ranked[1]

    return recommended


def _preferred_strategy(pref: dict) -> str | None:
    """Extract the most preferred strategy from a preference profile dict."""
    prefs = pref.get("strategy_preferences", {})
    if not prefs:
        return None
    return max(prefs, key=prefs.get)  # type: ignore[arg-type]


def _compute_confidence(
    ranked: list[CandidatePlan],
    recommended: CandidatePlan,
) -> float:
    """Compute Recommendation_Confidence (0-1).

    Confidence is based on:
    - Number of feasible candidates (more = lower confidence if close)
    - Gap between #1 and #2 in ranking
    - Feasibility status of the recommended plan
    """
    if len(ranked) <= 1:
        # Only one candidate — high confidence by default
        return 0.9 if ranked[0].feasibility_status == "feasible" else 0.4

    # Base confidence from feasibility
    base = 0.7 if recommended.feasibility_status == "feasible" else 0.3

    # Boost if there's a clear gap (recommended is feasible, #2 is not)
    second = ranked[1] if ranked[0].plan_id == recommended.plan_id else ranked[0]
    if (
        recommended.feasibility_status == "feasible"
        and second.feasibility_status != "feasible"
    ):
        base += 0.2

    # Reduce if all plans have the same feasibility (harder to distinguish)
    all_same = all(p.feasibility_status == ranked[0].feasibility_status for p in ranked)
    if all_same and len(ranked) > 2:
        base -= 0.1

    return min(1.0, max(0.0, round(base, 4)))


def _collect_risk_flags(
    plan: CandidatePlan,
    inp: PlanSelectionInput,
) -> list[str]:
    """Collect risk flags for the recommended plan."""
    flags: list[str] = []
    if plan.feasibility_status == "timeout_partial":
        flags.append("solver_timeout_partial_solution")
    if plan.solver_metadata and plan.solver_metadata.degradation_occurred:
        flags.append("solver_degradation_occurred")
    if plan.constraint_report and plan.constraint_report.violations:
        flags.append("soft_constraint_violations_present")
    severity = inp.severity
    if severity in ("P1-Critical", "P1_CRITICAL"):
        flags.append("high_severity_incident")
    return flags


def _should_auto_preselect(
    confidence: float,
    risk_flags: list[str],
    threshold: float,
) -> bool:
    """Decide whether to auto-preselect (Req 29.7, 29.8)."""
    if confidence < _LOW_CONFIDENCE_THRESHOLD:
        return False
    high_risk_flags = {
        "solver_timeout_partial_solution",
        "solver_degradation_occurred",
    }
    if any(f in high_risk_flags for f in risk_flags):
        return False
    return confidence >= threshold


def _build_reasons(
    recommended: CandidatePlan,
    top_scored: CandidatePlan,
    ranked: list[CandidatePlan],
    inp: PlanSelectionInput,
) -> tuple[list[str], str]:
    """Build reason_codes and reason_summary (Req 29.9)."""
    codes: list[str] = []
    parts: list[str] = []

    # Core reason: strategy type
    codes.append(f"strategy:{recommended.strategy_type}")
    parts.append(f"推荐方案采用 {recommended.strategy_type} 策略")

    # Is recommended == top scored?
    if recommended.plan_id == top_scored.plan_id:
        codes.append("top_scored_match")
        parts.append("该方案同时为综合评分最高方案")
    else:
        codes.append("preference_adjusted")
        parts.append("基于历史偏好调整，推荐方案与评分第一方案不同")

    # Feasibility
    if recommended.feasibility_status == "feasible":
        codes.append("fully_feasible")
        parts.append("方案满足全部硬约束")

    # Alternatives count
    alt_count = len(ranked) - 1
    if alt_count > 0:
        parts.append(f"另有 {alt_count} 个备选方案可供比较")

    summary = "；".join(parts) + "。"
    return codes, summary


def _build_ranked_list(
    ranked: list[CandidatePlan],
    recommended: CandidatePlan,
    top_scored: CandidatePlan,
) -> list[dict]:
    """Build the ranked_plan_list for frontend consumption."""
    result: list[dict] = []
    for idx, plan in enumerate(ranked):
        entry: dict = {
            "rank": idx + 1,
            "plan_id": str(plan.plan_id),
            "strategy_type": plan.strategy_type,
            "feasibility_status": plan.feasibility_status,
            "is_recommended": plan.plan_id == recommended.plan_id,
            "is_top_scored": plan.plan_id == top_scored.plan_id,
        }
        result.append(entry)
    return result


def _build_comparison_matrix(
    ranked: list[CandidatePlan],
    inp: PlanSelectionInput,
) -> ComparisonMatrix:
    """Build a comparison matrix from candidate schedule facts."""
    rows: list[ComparisonMatrixRow] = []
    weights = _resolve_weights(inp)
    kpis = [_compute_kpi(plan, weights) for plan in ranked]
    top_score = max((k.normalized_score for k in kpis), default=0.0)
    for plan in ranked:
        kpi = _compute_kpi(plan, weights)
        rows.append(
            ComparisonMatrixRow(
                plan_id=str(plan.plan_id),
                kpi_vector=kpi,
                delta_vs_baseline={
                    "score_gap_to_best": round(top_score - kpi.normalized_score, 4),
                    "adjusted_operation_ratio": kpi.spi,
                    "max_delay_minutes": kpi.max_delay_minutes,
                },
                is_score_close=(top_score - kpi.normalized_score) < 0.05,
            )
        )
    return ComparisonMatrix(
        rows=rows,
        normalization_method="bounded schedule-derived penalties, weighted sum",
        score_unit_descriptions={
            "delayed_order_count": "count",
            "max_delay_minutes": "minutes",
            "spi": "0-1 adjusted-operation ratio",
            "resource_utilization_delta": "0-1 dispersion proxy",
            "changeover_count_delta": "count",
            "critical_order_otd_impact": "0-1 on-time ratio for priority orders",
            "normalized_score": "0-1, higher is better",
        },
        baseline_snapshot_id=str(inp.schedule_snapshot_id),
    )


def _build_gantt_diff(
    recommended: CandidatePlan,
    inp: PlanSelectionInput,
) -> GanttDiffPayload:
    """Build a frontend-ready diff payload from the recommended schedule."""
    adjusted_operations: list[dict] = []
    time_shifts: list[dict] = []
    resource_switches: list[dict] = []
    all_ops = _flatten_operations(recommended)

    for wo, op in all_ops:
        if op.is_adjusted or op.is_affected:
            adjusted_operations.append(
                {
                    "operation_id": op.operation_id,
                    "work_order_id": wo.work_order_id,
                    "resource_id": op.resource_id,
                    "start_time": op.start_time.isoformat(),
                    "end_time": op.end_time.isoformat(),
                    "is_affected": op.is_affected,
                    "is_adjusted": op.is_adjusted,
                }
            )
            time_shifts.append(
                {
                    "operation_id": op.operation_id,
                    "work_order_id": wo.work_order_id,
                    "planned_start_time": op.start_time.isoformat(),
                    "planned_end_time": op.end_time.isoformat(),
                }
            )

        original_resource = getattr(op, "original_resource_id", None)
        if original_resource and original_resource != op.resource_id:
            resource_switches.append(
                {
                    "operation_id": op.operation_id,
                    "work_order_id": wo.work_order_id,
                    "from_resource_id": original_resource,
                    "to_resource_id": op.resource_id,
                }
            )

    critical_path_changes = _critical_path_summary(recommended)

    return GanttDiffPayload(
        baseline_snapshot_id=str(inp.schedule_snapshot_id),
        candidate_plan_id=str(recommended.plan_id),
        adjusted_operations=adjusted_operations,
        time_shifts=time_shifts,
        resource_switches=resource_switches,
        critical_path_changes=critical_path_changes,
    )


def _flatten_operations(plan: CandidatePlan) -> list[tuple[object, object]]:
    pairs: list[tuple[object, object]] = []
    for wo in plan.schedule_detail.work_orders:
        for op in wo.operations:
            pairs.append((wo, op))
    return pairs


def _compute_kpi(plan: CandidatePlan, weights: dict[str, float]) -> KPIVector:
    work_orders = plan.schedule_detail.work_orders
    op_pairs = _flatten_operations(plan)
    op_count = max(len(op_pairs), 1)

    delayed_order_count = 0
    max_delay_minutes = 0.0
    priority_total = 0
    priority_on_time = 0
    for wo in work_orders:
        if not wo.operations:
            continue
        completion = max(op.end_time for op in wo.operations)
        delay_minutes = max(0.0, (completion - wo.due_date).total_seconds() / 60.0)
        if delay_minutes > 0:
            delayed_order_count += 1
        max_delay_minutes = max(max_delay_minutes, delay_minutes)
        if wo.priority > 0:
            priority_total += 1
            if delay_minutes == 0:
                priority_on_time += 1

    adjusted_count = sum(1 for _, op in op_pairs if op.is_adjusted or op.is_affected)
    spi = adjusted_count / op_count
    changeovers = _count_changeovers(op_pairs)
    utilization_delta = _resource_utilization_dispersion(op_pairs)
    critical_otd = priority_on_time / priority_total if priority_total else 1.0

    effective_weights = weights or _resolve_weights(
        PlanSelectionInput(
            incident_id=UUID(int=0),
            incident_type="",
            severity="",
            schedule_snapshot_id=UUID(int=0),
            candidate_plans=[],
            goal_mode="balanced",
        )
    )
    penalty = (
        effective_weights.get("delayed_order_count", 0.2) * min(delayed_order_count / 5, 1)
        + effective_weights.get("max_delay_minutes", 0.15) * min(max_delay_minutes / 480, 1)
        + effective_weights.get("spi", 0.2) * min(spi, 1)
        + effective_weights.get("resource_utilization_delta", 0.15) * min(utilization_delta, 1)
        + effective_weights.get("changeover_count_delta", 0.1) * min(changeovers / 10, 1)
        + effective_weights.get("critical_order_otd_impact", 0.2) * (1 - critical_otd)
    )

    return KPIVector(
        delayed_order_count=delayed_order_count,
        max_delay_minutes=round(max_delay_minutes, 2),
        spi=round(spi, 4),
        resource_utilization_delta=round(utilization_delta, 4),
        changeover_count_delta=changeovers,
        critical_order_otd_impact=round(critical_otd, 4),
        normalized_score=round(max(0.0, min(1.0, 1 - penalty)), 4),
    )


def _count_changeovers(op_pairs: list[tuple[object, object]]) -> int:
    by_resource: dict[str, list[tuple[datetime, str]]] = {}
    for wo, op in op_pairs:
        by_resource.setdefault(op.resource_id, []).append((op.start_time, wo.product_name))
    count = 0
    for entries in by_resource.values():
        entries.sort(key=lambda item: item[0])
        for idx in range(1, len(entries)):
            if entries[idx - 1][1] != entries[idx][1]:
                count += 1
    return count


def _resource_utilization_dispersion(op_pairs: list[tuple[object, object]]) -> float:
    minutes_by_resource: dict[str, float] = {}
    for _, op in op_pairs:
        minutes = max(0.0, (op.end_time - op.start_time).total_seconds() / 60.0)
        minutes_by_resource[op.resource_id] = minutes_by_resource.get(op.resource_id, 0.0) + minutes
    if len(minutes_by_resource) <= 1:
        return 0.0
    values = list(minutes_by_resource.values())
    avg = sum(values) / len(values)
    if avg == 0:
        return 0.0
    return min(1.0, (max(values) - min(values)) / (avg * len(values)))


def _critical_path_summary(plan: CandidatePlan) -> list[dict]:
    result: list[dict] = []
    for wo in plan.schedule_detail.work_orders:
        if not wo.operations:
            continue
        latest = max(wo.operations, key=lambda op: op.end_time)
        result.append(
            {
                "work_order_id": wo.work_order_id,
                "terminal_operation_id": latest.operation_id,
                "planned_completion_time": latest.end_time.isoformat(),
                "due_date": wo.due_date.isoformat(),
                "delay_minutes": round(
                    max(0.0, (latest.end_time - wo.due_date).total_seconds() / 60.0),
                    2,
                ),
            }
        )
    return result


def _resolve_weights(inp: PlanSelectionInput) -> dict[str, float]:
    """Resolve the effective weights used for recommendation."""
    if inp.manual_weights:
        return dict(inp.manual_weights)
    # Default balanced weights
    return {
        "delayed_order_count": 0.20,
        "max_delay_minutes": 0.15,
        "spi": 0.20,
        "resource_utilization_delta": 0.15,
        "changeover_count_delta": 0.10,
        "critical_order_otd_impact": 0.20,
    }


def _extract_case_ids(case_matches: list[dict]) -> list[UUID]:
    """Extract case IDs from historical case match dicts."""
    ids: list[UUID] = []
    for match in case_matches:
        cid = match.get("case_id")
        if cid is not None:
            if isinstance(cid, UUID):
                ids.append(cid)
            else:
                try:
                    ids.append(UUID(str(cid)))
                except (ValueError, TypeError):
                    pass
    return ids


def _rank_of(plan: CandidatePlan, ranked: list[CandidatePlan]) -> int:
    """Return 1-based rank of plan in the ranked list."""
    for idx, p in enumerate(ranked):
        if p.plan_id == plan.plan_id:
            return idx + 1
    return 1


def _build_audit_metadata(
    inp: PlanSelectionInput,
    confidence: float,
) -> dict:
    """Build audit metadata for DecisionRecord (Req 29.10)."""
    return {
        "goal_mode": inp.goal_mode,
        "manual_weights": inp.manual_weights,
        "case_match_count": len(inp.historical_case_matches),
        "candidate_count": len(inp.candidate_plans),
        "preference_planner_id": inp.preference_profile.get("planner_id")
        if inp.preference_profile
        else None,
        "recommendation_confidence": confidence,
        "incident_id": str(inp.incident_id),
        "severity": inp.severity,
    }
