"""Contracts for deterministic infeasibility diagnosis and recovery."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from app.models.base import ReOrchModel
from app.models.enums import GoalMode, StrategyType
from app.models.impact import ImpactReport
from app.models.schedule import ScheduleDetail, ScheduleSnapshot


FailureClass = Literal[
    "feasible",
    "search_exhausted",
    "proven_infeasible",
    "data_or_governance_blocked",
    "model_invalid",
    "capacity_exhausted",
]

RecoveryActionType = Literal[
    "expand_repair_scope",
    "release_planning_freeze",
    "relax_operation_deadline",
    "open_overtime_window",
    "activate_outsourcing",
    "activate_substitute_material",
    "defer_work_order",
    "safe_hold",
]


class RecoveryActionRule(ReOrchModel):
    """One customer-owned rule controlling a recovery operator."""

    action_type: RecoveryActionType
    enabled: bool = True
    tier: int = Field(ge=0, le=4)
    penalty_cost: float = Field(default=0.0, ge=0.0)
    required_approval_roles: list[str] = Field(default_factory=list)
    auto_execute: bool = False
    max_uses_per_pack: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def validate_auto_execution_boundary(self) -> "RecoveryActionRule":
        if any(not role for role in self.required_approval_roles):
            raise ValueError("approval_roles_must_be_non_empty")
        if len(self.required_approval_roles) != len(
            {role.casefold() for role in self.required_approval_roles}
        ):
            raise ValueError("approval_roles_must_be_unique")
        if self.auto_execute and (self.tier != 0 or self.required_approval_roles):
            raise ValueError(
                "auto_execute_is_only_allowed_for_tier_0_without_human_approvals"
            )
        if self.tier > 0 and not self.required_approval_roles:
            raise ValueError("tier_1_to_4_recovery_actions_require_approval_roles")
        if self.action_type == "safe_hold" and self.tier != 0:
            raise ValueError("safe_hold_must_be_tier_0")
        return self


class RecoveryPolicy(ReOrchModel):
    """Versioned policy defining which feasibility changes are legal."""

    policy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    customer_owned: bool = False
    rules: list[RecoveryActionRule] = Field(min_length=1)
    max_actions_per_pack: int = Field(default=3, ge=1, le=8)
    max_search_trials: int = Field(default=32, ge=1, le=256)
    max_total_penalty_cost: float = Field(default=1_000_000.0, ge=0.0)

    @model_validator(mode="after")
    def validate_unique_rules(self) -> "RecoveryPolicy":
        action_types = [rule.action_type for rule in self.rules]
        if len(action_types) != len(set(action_types)):
            raise ValueError("recovery_policy_action_types_must_be_unique")
        return self


class RecoveryApprovalAttestation(ReOrchModel):
    """Auditable approval for one deterministic recovery action."""

    action_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    approver_id: str = Field(min_length=1)
    approver_role: str = Field(min_length=1)
    approved_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    expires_at: datetime | None = None
    source_ref: str = Field(min_length=1)
    signature: str | None = None


class FeasibilityRestorationRequest(ReOrchModel):
    """Request to diagnose and, when authorized, restore feasibility."""

    tenant_id: str
    snapshot: ScheduleSnapshot
    impact_report: ImpactReport
    strategy_type: StrategyType = StrategyType.LOCAL_REPAIR
    frozen_operation_ids: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=20.0, gt=0.0, le=600.0)
    goal_mode: GoalMode = GoalMode.BALANCED
    top_n: int = Field(default=3, ge=1, le=5)
    policy: RecoveryPolicy | None = None
    approvals: list[RecoveryApprovalAttestation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_snapshot_binding(self) -> "FeasibilityRestorationRequest":
        if self.impact_report.schedule_snapshot_id != self.snapshot.snapshot_id:
            raise ValueError("impact_report_snapshot_id_mismatch")
        if self.impact_report.analysis_reference_time != self.snapshot.captured_at:
            raise ValueError("impact_report_as_of_mismatch")
        operation_ids = {
            operation.operation_id
            for work_order in self.snapshot.work_orders
            for operation in work_order.operations
        }
        unknown_frozen = sorted(set(self.frozen_operation_ids) - operation_ids)
        if unknown_frozen:
            raise ValueError(
                f"unknown_frozen_operation_ids:{','.join(unknown_frozen)}"
            )
        return self


class FailureClassification(ReOrchModel):
    failure_class: FailureClass
    raw_solver_status: str
    proof_status: Literal["not_applicable", "proven", "not_proven"]
    blockers: list[str] = Field(default_factory=list)
    baseline_must_be_preserved: bool = True
    may_enter_relaxation_search: bool = False
    required_next_step: str


class ConflictConstraint(ReOrchModel):
    conflict_id: str
    constraint_family: str
    operation_ids: list[str] = Field(default_factory=list)
    work_order_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    hard_constraint: bool
    directly_relaxable: bool = False
    recovery_action_types: list[RecoveryActionType] = Field(default_factory=list)
    detail: str
    proof_method: str
    source_refs: list[str] = Field(default_factory=list)


class ConflictRefinementReport(ReOrchModel):
    constraint_registry_version: str = "1.0"
    core_status: Literal[
        "not_available",
        "observed_conflict_set",
        "proven_by_interval_bounds",
        "minimum_correction_set",
    ]
    conflicts: list[ConflictConstraint] = Field(default_factory=list)
    minimum_correction_action_ids: list[str] = Field(default_factory=list)
    optimality_proven: bool = False
    probe_count: int = Field(default=0, ge=0)
    explanation: str


class RecoveryAction(ReOrchModel):
    action_id: str
    action_type: RecoveryActionType
    constraint_family: str
    tier: int = Field(ge=0, le=4)
    penalty_cost: float = Field(ge=0.0)
    targets: dict[str, Any] = Field(default_factory=dict)
    description: str
    required_approval_roles: list[str] = Field(default_factory=list)
    approval_status: Literal["approved", "pending", "invalid"]
    approval_blockers: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    changes_effective_constraints: bool = True


class FeasibilityCertificate(ReOrchModel):
    original_snapshot_id: str
    effective_snapshot_fingerprint: str
    policy_id: str
    policy_version: str
    constraint_registry_version: str = "1.0"
    approved_action_ids: list[str] = Field(default_factory=list)
    approval_source_refs: list[str] = Field(default_factory=list)
    deferred_work_order_ids: list[str] = Field(default_factory=list)
    checked_hard_constraints: list[str] = Field(default_factory=list)
    hard_violation_count: int = Field(default=0, ge=0, le=0)
    solver_status: str
    schedule_fingerprint: str
    certificate_fingerprint: str
    writeback_authorized: Literal[False] = False
    issued_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class RecoveryPack(ReOrchModel):
    pack_id: str
    status: Literal["validated_feasible", "pending_approval"]
    actions: list[RecoveryAction] = Field(default_factory=list)
    lexicographic_rank: list[float] = Field(default_factory=list)
    maximum_tier: int = Field(ge=0, le=4)
    total_penalty_cost: float = Field(ge=0.0)
    deferred_priority_weight: int = Field(default=0, ge=0)
    solver_status: str
    preview_schedule: ScheduleDetail | None = None
    executable_schedule: ScheduleDetail | None = None
    feasibility_certificate: FeasibilityCertificate | None = None
    pending_approval_roles: list[str] = Field(default_factory=list)
    optimality_proven: bool = False

    @model_validator(mode="after")
    def validate_execution_gate(self) -> "RecoveryPack":
        if self.status == "validated_feasible" and (
            self.executable_schedule is None or self.feasibility_certificate is None
        ):
            raise ValueError("validated_feasible_pack_requires_schedule_and_certificate")
        if self.status == "pending_approval" and (
            self.executable_schedule is not None
            or self.feasibility_certificate is not None
        ):
            raise ValueError("pending_pack_cannot_expose_executable_schedule_or_certificate")
        return self


class SafeHoldDisposition(ReOrchModel):
    action_id: str
    affected_operation_ids: list[str] = Field(default_factory=list)
    reason: str
    executable_production_schedule: Literal[False] = False
    writeback_authorized: Literal[False] = False


class FeasibilityRestorationResponse(ReOrchModel):
    run_id: str
    tenant_id: str
    status: Literal[
        "already_feasible",
        "recovery_available",
        "pending_approval",
        "search_exhausted",
        "blocked",
        "safe_hold_only",
    ]
    classification: FailureClassification
    conflict_report: ConflictRefinementReport
    recovery_packs: list[RecoveryPack] = Field(default_factory=list)
    unavailable_actions: list[RecoveryAction] = Field(default_factory=list)
    recommended_pack_id: str | None = None
    executable_pack_ids: list[str] = Field(default_factory=list)
    planner_review_pack_ids: list[str] = Field(default_factory=list)
    safe_hold: SafeHoldDisposition
    search_trials: int = Field(default=0, ge=0)
    elapsed_ms: float = Field(ge=0.0)
    evidence_fingerprint: str
    writeback_allowed: Literal[False] = False
    claim_boundary: str
