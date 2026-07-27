"""Production application readiness gate models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import ReOrchModel


EvidenceSource = Literal[
    "public_benchmark",
    "customer_desensitized",
    "customer_live_shadow",
    "customer_production",
]

ReadinessDecision = Literal[
    "production_ready",
    "controlled_pilot_ready",
    "shadow_ready",
    "replay_ready",
    "blocked",
]


class ProductionReadinessEvidence(ReOrchModel):
    """Evidence bundle used to decide which deployment level is allowed."""

    site_id: str
    evidence_source: EvidenceSource = "public_benchmark"
    real_customer_data: bool = False
    customer_provenance_confirmed: bool = False

    p0_permission_level: str = "blocked"
    p0_readiness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    snapshot_available: bool = False
    work_order_count: int = Field(default=0, ge=0)
    operation_count: int = Field(default=0, ge=0)
    resource_count: int = Field(default=0, ge=0)

    incident_count: int = Field(default=0, ge=0)
    solved_incident_count: int = Field(default=0, ge=0)
    feasible_option_count: int = Field(default=0, ge=0)
    infeasible_option_count: int = Field(default=0, ge=0)

    planner_decision_count: int = Field(default=0, ge=0)
    planner_override_reason_count: int = Field(default=0, ge=0)
    execution_outcome_count: int = Field(default=0, ge=0)
    strategy_effect_matrix_cell_count: int = Field(default=0, ge=0)
    high_confidence_policy_cell_count: int = Field(default=0, ge=0)

    sandbox_writeback_passed: bool = False
    approval_roles: list[str] = Field(default_factory=list)
    idempotency_ready: bool = False
    rollback_plan_ready: bool = False
    compensation_ready: bool = False
    audit_ready: bool = False

    ai_role_limited_to_explanation: bool = True
    quality_gate_enforced: bool = False
    human_confirmation_enforced: bool = False

    p95_solver_latency_ms: float | None = Field(default=None, ge=0.0)
    p95_gate_latency_ms: float | None = Field(default=None, ge=0.0)
    concurrent_incident_tested: int = Field(default=0, ge=0)
    performance_targets_tested: list[int] = Field(default_factory=list)

    security_review_passed: bool = False
    backup_restore_drill_passed: bool = False
    observability_alerting_ready: bool = False
    sso_rbac_ready: bool = False
    retention_policy_approved: bool = False


class ProductionReadinessCheck(ReOrchModel):
    module: str
    status: Literal["pass", "warning", "blocker"]
    evidence: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)


class ProductionReadinessResponse(ReOrchModel):
    site_id: str
    decision: ReadinessDecision
    checks: list[ProductionReadinessCheck]
    allowed_actions: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    production_blockers: list[str] = Field(default_factory=list)
    claim_boundary: str
