"""Historical replay and shadow-mode validation models."""

from __future__ import annotations

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.planning import PlanQualityGateReport
from app.models.schedule import ScheduleDetail
from app.models.solver import CandidatePlan


class ReplayValidationRequest(ReOrchModel):
    """Evaluate candidate plans against a historical planner-accepted schedule."""

    historical_case_id: str
    accepted_schedule: ScheduleDetail
    candidate_plans: list[CandidatePlan] = Field(default_factory=list)
    top_n: int = Field(default=3, ge=1, le=8)
    time_tolerance_minutes: float = Field(default=30.0, ge=0.0)
    acceptance_threshold: float = Field(default=0.8, ge=0.0, le=1.0)


class ReplayCandidateScore(ReOrchModel):
    """Replay score for one candidate plan."""

    plan_id: str
    rank: int
    pass_quality_gate: bool
    recommendation_policy: str
    operation_count: int
    matched_operation_count: int
    resource_match_rate: float
    within_time_tolerance_rate: float
    average_start_deviation_minutes: float
    average_end_deviation_minutes: float
    schedule_similarity_score: float
    reasons: list[str] = Field(default_factory=list)
    quality_gate: PlanQualityGateReport


class ReplayValidationResponse(ReOrchModel):
    """Replay validation result for one historical case."""

    historical_case_id: str
    evaluated_plan_count: int
    top_n: int
    top_n_hit: bool
    best_plan_id: str | None = None
    best_similarity_score: float = 0.0
    shadow_readiness_level: str
    decision: str
    candidate_scores: list[ReplayCandidateScore] = Field(default_factory=list)
    required_next_actions: list[str] = Field(default_factory=list)
