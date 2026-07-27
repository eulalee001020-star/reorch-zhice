"""Design Partner onboarding, evidence, governance, and ROI models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.reality_harness import P0RealityHarnessRequest, P0RealityHarnessResponse

EvidenceScope = Literal["customer_provided", "synthetic_sample"]
CheckStatus = Literal["passed", "warning", "blocked", "not_provided"]
PreflightStage = Literal["data_repair", "replay_ready", "shadow_ready"]
ConstraintStatus = Literal["draft", "customer_confirmed", "replay_validated"]
EvaluationMode = Literal[
    "historical_replay",
    "read_only_shadow",
    "controlled_execution",
]
PlannerOutcome = Literal["accepted", "adjusted", "rejected", "not_reviewed"]
ApprovalType = Literal[
    "data_use",
    "historical_replay",
    "read_only_shadow",
    "retention",
    "security_review",
    "sandbox_writeback",
    "finance_validation",
]
RoiEvidenceLevel = Literal[
    "none",
    "replay_counterfactual",
    "shadow_observed",
    "execution_measured",
    "finance_validated_execution",
]
MoatStatus = Literal["nascent", "building", "validated"]


class DataProvenanceEvidence(ReOrchModel):
    """Traceability and ownership evidence for one customer data export."""

    dataset_name: str
    source_systems: list[str] = Field(default_factory=list)
    exported_at: datetime | None = None
    data_window_start: datetime | None = None
    data_window_end: datetime | None = None
    data_owner_role: str | None = None
    data_owner_approved: bool = False
    replay_authorized: bool = False
    desensitized: bool = False
    provenance_ref: str | None = None
    mapping_profile_ref: str | None = None
    mapping_approved_by: str | None = None
    adapter_template_ref: str | None = None
    adapter_template_contains_customer_identifiers: bool = True


class ConstraintAttestation(ReOrchModel):
    """One source-backed workshop rule translated into a candidate constraint."""

    constraint_id: str
    category: Literal[
        "material",
        "quality",
        "tooling",
        "personnel",
        "calendar",
        "sequence",
        "freeze_window",
        "changeover",
        "planner_policy",
        "other",
    ]
    enforcement: Literal["hard", "soft", "preference"]
    status: ConstraintStatus = "draft"
    owner_role: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    reusable_template_ref: str | None = None
    reusable_template_contains_customer_identifiers: bool = True


class GovernanceApproval(ReOrchModel):
    """Customer approval record; a boolean without a reference is not sufficient."""

    approval_type: ApprovalType
    approved: bool = False
    approver_role: str | None = None
    evidence_ref: str | None = None
    scope: str | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = None


class CaseMetrics(ReOrchModel):
    """Comparable per-incident metrics; absent values are not treated as zero."""

    decision_minutes: float | None = Field(default=None, ge=0.0)
    tardiness_minutes: float | None = Field(default=None, ge=0.0)
    changeovers: int | None = Field(default=None, ge=0)
    overtime_hours: float | None = Field(default=None, ge=0.0)


class RecoveryCaseEvidence(ReOrchModel):
    """Replay, shadow, or execution evidence for one abnormal event."""

    case_id: str
    incident_type: str
    evaluation_mode: EvaluationMode
    recovery_operator_ids: list[str] = Field(default_factory=list)
    compared_plan_ids: list[str] = Field(default_factory=list)
    selected_plan_id: str | None = None
    planner_outcome: PlannerOutcome = "not_reviewed"
    baseline_metrics: CaseMetrics = Field(default_factory=CaseMetrics)
    reorch_metrics: CaseMetrics = Field(default_factory=CaseMetrics)
    baseline_source_ref: str | None = None
    reorch_output_ref: str | None = None
    planner_decision_ref: str | None = None
    execution_result_ref: str | None = None
    customer_validated_by: str | None = None
    deidentified_case_pattern_ref: str | None = None
    case_pattern_contains_customer_identifiers: bool = True


class RoiCostModel(ReOrchModel):
    """Customer cost assumptions used to translate deltas into money."""

    currency: str = "CNY"
    planner_hourly_cost: float = Field(default=0.0, ge=0.0)
    tardiness_cost_per_minute: float = Field(default=0.0, ge=0.0)
    changeover_cost: float = Field(default=0.0, ge=0.0)
    overtime_hourly_cost: float = Field(default=0.0, ge=0.0)
    poc_cost: float = Field(default=0.0, ge=0.0)
    cost_source_ref: str | None = None
    finance_confirmed_by: str | None = None


class WorkflowEvidence(ReOrchModel):
    """References proving that the decision workflow can be operated and audited."""

    planner_confirmation_ref: str | None = None
    approval_matrix_ref: str | None = None
    audit_export_ref: str | None = None
    rollback_runbook_ref: str | None = None
    sandbox_contract_test_ref: str | None = None
    deployment_template_ref: str | None = None
    deployment_template_contains_customer_identifiers: bool = True


class DesignPartnerPreflightRequest(ReOrchModel):
    """All evidence submitted for one customer workshop onboarding decision."""

    evidence_scope: EvidenceScope
    customer_ref: str = Field(min_length=3)
    site_id: str = Field(min_length=1)
    reality_request: P0RealityHarnessRequest
    provenance: DataProvenanceEvidence
    constraints: list[ConstraintAttestation] = Field(default_factory=list)
    governance_approvals: list[GovernanceApproval] = Field(default_factory=list)
    recovery_cases: list[RecoveryCaseEvidence] = Field(default_factory=list)
    roi_cost_model: RoiCostModel = Field(default_factory=RoiCostModel)
    workflow_evidence: WorkflowEvidence = Field(default_factory=WorkflowEvidence)


class EvidenceCheck(ReOrchModel):
    """Auditable gate result with its evidence and corrective action."""

    check_id: str
    category: str
    status: CheckStatus
    finding: str
    evidence_refs: list[str] = Field(default_factory=list)
    required_action: str | None = None


class RoiEvidenceSummary(ReOrchModel):
    """Evidence-bounded ROI ledger; no extrapolation across unobserved incidents."""

    currency: str
    evidence_level: RoiEvidenceLevel
    submitted_case_count: int
    eligible_case_count: int
    excluded_case_ids: list[str] = Field(default_factory=list)
    measured_deltas: dict[str, float] = Field(default_factory=dict)
    estimated_case_savings: float = 0.0
    realized_case_savings: float = 0.0
    savings_breakdown: dict[str, float] = Field(default_factory=dict)
    finance_validated: bool = False
    roi_ratio: float | None = Field(
        default=None,
        description="Net ROI: (realized case savings - PoC cost) / PoC cost.",
    )
    evidence_refs: list[str] = Field(default_factory=list)
    claim_allowed: str


class MoatLayerAssessment(ReOrchModel):
    """Coverage assessment for one moat layer, not a performance score."""

    layer: Literal[
        "data_integration",
        "constraint_translation",
        "validation_assets",
        "workflow_embedding",
    ]
    evidence_coverage_score: float = Field(ge=0.0, le=100.0)
    status: MoatStatus
    customer_private_asset_count: int = 0
    reusable_deidentified_asset_count: int = 0
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class DesignPartnerPreflightResponse(ReOrchModel):
    """Deterministic onboarding result and the highest safe trial stage."""

    preflight_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    evidence_scope: EvidenceScope
    customer_ref: str
    site_id: str
    workshop_id: str
    data_fingerprint: str
    stage: PreflightStage
    reality_harness: P0RealityHarnessResponse
    checks: list[EvidenceCheck] = Field(default_factory=list)
    roi_summary: RoiEvidenceSummary
    moat_layers: list[MoatLayerAssessment] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    required_next_actions: list[str] = Field(default_factory=list)
    generated_deliverables: list[str] = Field(default_factory=list)
    claim_boundary: str
