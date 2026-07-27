"""Historical replay and shadow-mode validation service."""

from __future__ import annotations

from datetime import datetime

from app.models.replay_validation import (
    ReplayCandidateScore,
    ReplayValidationRequest,
    ReplayValidationResponse,
)
from app.models.schedule import Operation, ScheduleDetail
from app.models.solver import CandidatePlan
from app.services.plan_quality_gate import PlanQualityGate


class ReplayValidationService:
    """Compare candidate plans with historical planner-accepted schedules."""

    def __init__(self, quality_gate: PlanQualityGate | None = None) -> None:
        self._quality_gate = quality_gate or PlanQualityGate()

    def evaluate(self, request: ReplayValidationRequest) -> ReplayValidationResponse:
        accepted_ops = _operation_index(request.accepted_schedule)
        candidate_scores = [
            self._score_candidate(index + 1, plan, accepted_ops, request)
            for index, plan in enumerate(request.candidate_plans[: request.top_n])
        ]
        best = max(
            candidate_scores,
            key=lambda score: score.schedule_similarity_score,
            default=None,
        )
        top_n_hit = bool(
            best
            and best.pass_quality_gate
            and best.schedule_similarity_score >= request.acceptance_threshold
        )
        return ReplayValidationResponse(
            historical_case_id=request.historical_case_id,
            evaluated_plan_count=len(candidate_scores),
            top_n=request.top_n,
            top_n_hit=top_n_hit,
            best_plan_id=best.plan_id if best else None,
            best_similarity_score=best.schedule_similarity_score if best else 0.0,
            shadow_readiness_level=_readiness_level(candidate_scores, top_n_hit),
            decision=_decision(candidate_scores, top_n_hit),
            candidate_scores=candidate_scores,
            required_next_actions=_next_actions(candidate_scores, top_n_hit),
        )

    def _score_candidate(
        self,
        rank: int,
        plan: CandidatePlan,
        accepted_ops: dict[str, Operation],
        request: ReplayValidationRequest,
    ) -> ReplayCandidateScore:
        gate = self._quality_gate.evaluate(plan)
        candidate_ops = _operation_index(plan.schedule_detail)
        shared_ids = sorted(set(accepted_ops) & set(candidate_ops))
        operation_count = len(accepted_ops)
        resource_matches = 0
        time_tolerant = 0
        start_deviations: list[float] = []
        end_deviations: list[float] = []

        for op_id in shared_ids:
            accepted = accepted_ops[op_id]
            candidate = candidate_ops[op_id]
            if accepted.resource_id == candidate.resource_id:
                resource_matches += 1
            start_delta = _minutes_delta(accepted.start_time, candidate.start_time)
            end_delta = _minutes_delta(accepted.end_time, candidate.end_time)
            start_deviations.append(start_delta)
            end_deviations.append(end_delta)
            if (
                start_delta <= request.time_tolerance_minutes
                and end_delta <= request.time_tolerance_minutes
            ):
                time_tolerant += 1

        matched_count = len(shared_ids)
        resource_rate = _rate(resource_matches, operation_count)
        time_rate = _rate(time_tolerant, operation_count)
        coverage_rate = _rate(matched_count, operation_count)
        similarity = round((resource_rate * 0.4 + time_rate * 0.4 + coverage_rate * 0.2), 4)
        reasons = _score_reasons(
            gate.pass_gate,
            resource_rate,
            time_rate,
            coverage_rate,
            request.acceptance_threshold,
        )
        return ReplayCandidateScore(
            plan_id=str(plan.plan_id),
            rank=rank,
            pass_quality_gate=gate.pass_gate,
            recommendation_policy=gate.recommendation_policy,
            operation_count=operation_count,
            matched_operation_count=matched_count,
            resource_match_rate=resource_rate,
            within_time_tolerance_rate=time_rate,
            average_start_deviation_minutes=_average(start_deviations),
            average_end_deviation_minutes=_average(end_deviations),
            schedule_similarity_score=similarity,
            reasons=reasons,
            quality_gate=gate,
        )


def _operation_index(schedule: ScheduleDetail) -> dict[str, Operation]:
    return {
        operation.operation_id: operation
        for work_order in schedule.work_orders
        for operation in work_order.operations
    }


def _minutes_delta(left: datetime, right: datetime) -> float:
    return abs((right - left).total_seconds()) / 60.0


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _score_reasons(
    pass_gate: bool,
    resource_rate: float,
    time_rate: float,
    coverage_rate: float,
    threshold: float,
) -> list[str]:
    reasons: list[str] = []
    if not pass_gate:
        reasons.append("quality_gate_blocked")
    if coverage_rate < threshold:
        reasons.append("operation_coverage_below_threshold")
    if resource_rate < threshold:
        reasons.append("resource_match_below_threshold")
    if time_rate < threshold:
        reasons.append("time_tolerance_below_threshold")
    if not reasons:
        reasons.append("matches_historical_acceptance_envelope")
    return reasons


def _readiness_level(
    scores: list[ReplayCandidateScore],
    top_n_hit: bool,
) -> str:
    if not scores:
        return "blocked"
    if not any(score.pass_quality_gate for score in scores):
        return "blocked"
    if not top_n_hit:
        return "watch_only"
    best = max(score.schedule_similarity_score for score in scores)
    if best >= 0.9:
        return "shadow_comparable"
    return "candidate_shadow"


def _decision(
    scores: list[ReplayCandidateScore],
    top_n_hit: bool,
) -> str:
    if not scores:
        return "do_not_enter_shadow_mode"
    if not any(score.pass_quality_gate for score in scores):
        return "fix_constraints_before_replay"
    if top_n_hit:
        return "eligible_for_read_only_shadow_comparison"
    return "continue_historical_replay"


def _next_actions(
    scores: list[ReplayCandidateScore],
    top_n_hit: bool,
) -> list[str]:
    if not scores:
        return ["Provide candidate plans generated from the same historical case."]
    if not any(score.pass_quality_gate for score in scores):
        return ["Fix hard constraint blockers before comparing acceptance quality."]
    if not top_n_hit:
        return [
            "Review missing operations, resource mismatches, and time deviations with planners.",
            "Add or repair calibrated constraints, then replay the same case again.",
        ]
    return [
        "Run additional historical cases before shadow mode.",
        "Keep results read-only and compare against planner decisions.",
    ]
