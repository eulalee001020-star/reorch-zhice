"""Read-only shadow mode capture models."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.solver import CandidatePlan


class PlannerShadowDecision(ReOrchModel):
    """Planner decision captured during read-only shadow comparison."""

    decision_status: str
    selected_plan_id: str | None = None
    decided_by: str = "planner-1"
    decided_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    override_reason: str | None = None
    tweak_summary: str | None = None


class ShadowCaseCaptureRequest(ReOrchModel):
    """Capture one advisory-only shadow-mode case."""

    incident_payload: dict
    schedule_snapshot_id: str
    candidate_plans: list[CandidatePlan] = Field(default_factory=list)
    planner_decision: PlannerShadowDecision
    impact_report: dict | None = None
    recommendation_explanation: dict | None = None
    execution_outcome: dict | None = None
    source_refs: list[str] = Field(default_factory=list)
    advisory_only: bool = True


class ShadowCaseCaptureResponse(ReOrchModel):
    """Stored shadow case with safety and feedback status."""

    shadow_case_id: str = Field(default_factory=lambda: f"shadow-{uuid4()}")
    captured_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    advisory_only: bool
    writeback_blocked: bool
    feedback_capture_complete: bool
    rule_candidate_recommended: bool
    decision_status: str
    selected_plan_id: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    audit_bundle: dict = Field(default_factory=dict)
