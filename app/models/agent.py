"""Controlled agent workflow models for ReOrch."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.case import CaseRecord, PreferenceProfile
from app.models.decision import DecisionRecord
from app.models.evaluation import ComparisonMatrix
from app.models.execution import ExecutionResult
from app.models.explanation import RecommendationExplanation, SolverChainExplanation
from app.models.impact import ImpactReport
from app.models.incident import Incident, IncidentCreateRequest
from app.models.planning import PlanQualityGateReport
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
    llm_used: bool = False
    llm_provider: str | None = None
    model_name: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    fallback_reason: str | None = None
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
    quality_gates: list[PlanQualityGateReport] = Field(default_factory=list)
    comparison_matrix: ComparisonMatrix | None = None
    recommendation: PlanSelectionOutput | None = None
    recommendation_explanation: RecommendationExplanation | None = None
    solver_chain_explanation: SolverChainExplanation | None = None
    requires_human_confirmation: bool = True
    trace: list[AgentTraceStep] = Field(default_factory=list)


class ConstraintCandidate(ReOrchModel):
    """Auditable rule candidate produced from planner feedback or rule text."""

    candidate_id: str
    constraint_type: str
    scope: dict = Field(default_factory=dict)
    source_text: str
    compiled_rule: str
    confidence: float
    status: str = "pending_human_review"
    risk_note: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class RuleCandidateRequest(ReOrchModel):
    """Compile natural-language site rules into reviewable candidates."""

    rule_text: str
    context: dict = Field(default_factory=dict)
    source: str = "planner_feedback"
    incident_id: UUID | None = None
    decision_record_id: UUID | None = None


class RuleCandidateOutput(ReOrchModel):
    """Structured output from Rule Candidate Agent."""

    candidates: list[ConstraintCandidate] = Field(default_factory=list)
    requires_human_review: bool = True
    lifecycle_status: str = "candidate"
    trace: list[AgentTraceStep] = Field(default_factory=list)


class RuleCandidateReplayResult(ReOrchModel):
    """Replay result for one reviewed rule candidate."""

    pass_replay: bool
    checked_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    scenario_count: int = 0
    blocked_reason: str | None = None
    metrics: dict[str, float | int | str | bool] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class RuleCandidatePublicationRecord(ReOrchModel):
    """Read-only release record for a replay-passed candidate."""

    release_id: str
    candidate_id: str
    published_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    published_by: str
    release_note: str | None = None
    readonly: bool = True
    version: str = "rules-candidate-v1"


class RuleCandidateReviewRecord(ReOrchModel):
    """Human review lifecycle state for a constraint candidate."""

    candidate: ConstraintCandidate
    status: str = "pending_human_review"
    reviewer_id: str | None = None
    review_note: str | None = None
    reject_reason: str | None = None
    replay_result: RuleCandidateReplayResult | None = None
    published_record: RuleCandidatePublicationRecord | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class RuleCandidateListResponse(ReOrchModel):
    """Rule candidate review queue response."""

    records: list[RuleCandidateReviewRecord] = Field(default_factory=list)
    status_counts: dict[str, int] = Field(default_factory=dict)


class RuleCandidateReviewRequest(ReOrchModel):
    """Human review action for a rule candidate."""

    action: str
    reviewer_id: str = "planner-1"
    review_note: str | None = None
    reject_reason: str | None = None


class RuleCandidateReplayRequest(ReOrchModel):
    """Run deterministic replay checks for a reviewed rule candidate."""

    scenario_set: str = "lab_replay_acceptance"
    scenario_count: int = 3
    notes: list[str] = Field(default_factory=list)


class RuleCandidatePublishRequest(ReOrchModel):
    """Publish a replay-passed rule candidate as a read-only release record."""

    publisher_id: str = "planner-1"
    release_note: str | None = None


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
    rule_candidates: list[ConstraintCandidate] = Field(default_factory=list)
    confidence: float
    requires_human_review: bool
    decision_record_id: UUID | None = None
    incident_id: UUID | None = None
    trace: list[AgentTraceStep] = Field(default_factory=list)


class CaseMemoryRequest(ReOrchModel):
    """Archive a confirmed decision and execution result as a reusable case."""

    decision_record: DecisionRecord
    execution_result: ExecutionResult
    case_status: str = "pending_validation"
    tags: list[str] = Field(default_factory=list)


class CaseMemoryOutput(ReOrchModel):
    """Structured output from Case Memory Agent."""

    case_record: CaseRecord
    case_title: str
    incident_signature: str
    reusability: str
    status: str
    trace: list[AgentTraceStep] = Field(default_factory=list)


class PreferenceLearningRequest(ReOrchModel):
    """Learn planner preference signals from archived cases."""

    planner_id: str
    case_records: list[CaseRecord] = Field(default_factory=list)
    existing_profile: PreferenceProfile | None = None
    min_samples: int = 3


class PreferenceLearningOutput(ReOrchModel):
    """Structured output from Preference Learning Agent."""

    preference_profile: PreferenceProfile
    evidence_summary: list[str] = Field(default_factory=list)
    recommended_use: str = "observation_only"
    confidence: float
    requires_replay_validation: bool = True
    sample_count: int
    trace: list[AgentTraceStep] = Field(default_factory=list)


class PostDecisionLearningRequest(ReOrchModel):
    """Run the post-confirmation learning loop from one decision."""

    decision_record_id: UUID | None = None
    incident_id: UUID | None = None
    decision_record: DecisionRecord | None = None
    execution_result: ExecutionResult | None = None
    planner_id: str | None = None
    rule_text: str | None = None
    min_samples: int = 1


class PostDecisionLearningOutput(ReOrchModel):
    """Visible result of RuleCandidate -> CaseMemory -> PreferenceLearning."""

    rule_candidate_output: RuleCandidateOutput
    case_memory_output: CaseMemoryOutput
    preference_learning_output: PreferenceLearningOutput
    trace: list[AgentTraceStep] = Field(default_factory=list)
