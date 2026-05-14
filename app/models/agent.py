"""Controlled agent workflow models for ReOrch."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.evaluation import ComparisonMatrix
from app.models.explanation import RecommendationExplanation, SolverChainExplanation
from app.models.impact import ImpactReport
from app.models.incident import Incident, IncidentCreateRequest
from app.models.recommendation import PlanSelectionOutput
from app.models.solver import CandidatePlan
from app.models.strategy import StrategyRecommendation


class AgentTraceStep(ReOrchModel):
    """One auditable step in the controlled agent workflow."""

    agent_name: str
    input_summary: str
    output_summary: str
    freedom_level: str
    llm_allowed: bool
    deterministic_tools: list[str] = Field(default_factory=list)
    guardrail: str


class IncidentUnderstandingRequest(ReOrchModel):
    """Natural-language incident understanding request."""

    text: str
    occurred_at: datetime | None = None
    workshop_id: str | None = None
    report_source: str = "manual"
    source_system: str | None = "agent_text_intake"


class IncidentUnderstandingOutput(ReOrchModel):
    """Structured output from Incident Agent."""

    incident_type: str
    resource_id: str | None = None
    estimated_duration_minutes: int | None = None
    risk_hint: str | None = None
    confidence: float
    requires_human_confirmation: bool
    supported_by_solver: bool
    unsupported_reason: str | None = None
    normalized_fields: dict = Field(default_factory=dict)
    incident_create_request: IncidentCreateRequest | None = None
    trace: list[AgentTraceStep] = Field(default_factory=list)


class AgentDecisionFlowRequest(ReOrchModel):
    """Run the controlled incident decision workflow from an existing Incident."""

    incident_id: UUID
    estimated_repair_time_minutes: float = 60.0
    goal_mode: str = "balanced"
    manual_weights: dict[str, float] | None = None
    auto_solve: bool = True
    auto_recommend: bool = True
    planner_id: str = "default"


class AgentDecisionFlowResponse(ReOrchModel):
    """End-to-end controlled workflow output."""

    incident: Incident
    impact_report: ImpactReport
    strategy: StrategyRecommendation
    candidate_plans: list[CandidatePlan] = Field(default_factory=list)
    comparison_matrix: ComparisonMatrix | None = None
    recommendation: PlanSelectionOutput | None = None
    recommendation_explanation: RecommendationExplanation | None = None
    solver_chain_explanation: SolverChainExplanation | None = None
    requires_human_confirmation: bool = True
    trace: list[AgentTraceStep] = Field(default_factory=list)


class FeedbackStructuringRequest(ReOrchModel):
    """Structure a planner override or post-execution feedback note."""

    override_text: str
    decision_record_id: UUID | None = None
    incident_id: UUID | None = None
    planner_id: str | None = None


class FeedbackStructuringOutput(ReOrchModel):
    """Structured feedback asset candidate produced by Feedback Agent."""

    override_reason: str
    reason_detail: str
    future_rule_candidate: str | None = None
    confidence: float
    requires_human_review: bool
    decision_record_id: UUID | None = None
    incident_id: UUID | None = None
    trace: list[AgentTraceStep] = Field(default_factory=list)
