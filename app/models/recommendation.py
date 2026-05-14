"""Recommendation-related Pydantic models for the ReOrch system.

Defines PlanSelectionInput and PlanSelectionOutput used by the
Plan_Recommendation_Engine to drive recommendation decisions.
"""

from uuid import UUID

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.evaluation import ComparisonMatrix
from app.models.schedule import GanttDiffPayload
from app.models.solver import CandidatePlan


class PlanSelectionInput(ReOrchModel):
    """Unified input for Plan_Recommendation_Engine."""

    incident_id: UUID
    incident_type: str
    severity: str
    schedule_snapshot_id: UUID
    candidate_plans: list[CandidatePlan] = Field(default_factory=list)
    goal_mode: str
    preference_profile: dict = Field(default_factory=dict)
    historical_case_matches: list[dict] = Field(default_factory=list)
    manual_weights: dict[str, float] | None = None
    execution_constraints: dict | None = None


class PlanSelectionOutput(ReOrchModel):
    """Unified output from Plan_Recommendation_Engine."""

    recommended_plan_id: UUID
    recommended_rank: int
    top_scored_plan_id: UUID
    recommendation_confidence: float  # 0-1
    auto_preselected: bool
    ranked_plan_list: list[dict] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    reason_summary: str
    risk_flags: list[str] = Field(default_factory=list)
    comparison_matrix: ComparisonMatrix
    gantt_diff_payload: GanttDiffPayload
    goal_mode_used: str
    weights_used: dict[str, float] = Field(default_factory=dict)
    matched_case_ids: list[UUID] = Field(default_factory=list)
    alternative_plan_ids: list[UUID] = Field(default_factory=list)
    audit_metadata: dict = Field(default_factory=dict)
