"""Large-scale flexible job shop readiness and recovery models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.base import ReOrchModel


IncidentCategory = Literal[
    "equipment_failure",
    "rush_order",
    "material_shortage",
    "quality_exception",
    "labor_absence",
    "tooling_conflict",
    "batch_rework",
]


class FlexibleWorkshop(ReOrchModel):
    workshop_id: str
    name: str | None = None
    timezone: str = "Asia/Shanghai"


class FlexibleMachineGroup(ReOrchModel):
    group_id: str
    workshop_id: str
    capability_codes: list[str] = Field(default_factory=list)
    is_bottleneck: bool = False


class FlexibleResource(ReOrchModel):
    resource_id: str
    workshop_id: str
    machine_group_id: str | None = None
    resource_type: str = "equipment"
    capability_codes: list[str] = Field(default_factory=list)
    skill_codes: list[str] = Field(default_factory=list)
    tooling_ids: list[str] = Field(default_factory=list)
    is_bottleneck: bool = False
    cost_per_minute: float = Field(default=1.0, ge=0.0)


class FlexibleOperationMode(ReOrchModel):
    mode_id: str
    resource_id: str | None = None
    machine_group_id: str | None = None
    processing_minutes: int = Field(gt=0)
    setup_minutes: int = Field(default=0, ge=0)
    required_capability_codes: list[str] = Field(default_factory=list)
    required_skill_codes: list[str] = Field(default_factory=list)
    required_tooling_ids: list[str] = Field(default_factory=list)
    transport_lane_id: str | None = None
    is_outsource: bool = False
    cost_per_unit: float = Field(default=0.0, ge=0.0)


class FlexibleOperation(ReOrchModel):
    operation_id: str
    work_order_id: str
    route_id: str
    sequence_no: int = Field(ge=0)
    quantity: float = Field(default=1.0, gt=0.0)
    status: str = "planned"
    batch_id: str | None = None
    rework_of_operation_id: str | None = None
    predecessor_ids: list[str] = Field(default_factory=list)
    successor_ids: list[str] = Field(default_factory=list)
    material_ids: list[str] = Field(default_factory=list)
    quality_state: str = "released"
    wip_location_id: str | None = None
    frozen_until: datetime | None = None
    modes: list[FlexibleOperationMode] = Field(default_factory=list)


class FlexibleWorkOrder(ReOrchModel):
    work_order_id: str
    product_family: str | None = None
    due_date: datetime
    priority: int = Field(default=0, ge=0)
    customer_tier: str | None = None
    route_ids: list[str] = Field(default_factory=list)
    operations: list[FlexibleOperation] = Field(default_factory=list)


class MaterialConstraint(ReOrchModel):
    material_id: str
    available_quantity: float = Field(ge=0.0)
    available_at: datetime | None = None
    substitute_material_ids: list[str] = Field(default_factory=list)
    quality_approved: bool = True


class SkillConstraint(ReOrchModel):
    skill_code: str
    available_headcount: int = Field(ge=0)
    workshop_id: str | None = None
    shift_id: str | None = None


class ToolingConstraint(ReOrchModel):
    tooling_id: str
    quantity: int = Field(ge=0)
    location_id: str | None = None
    available_at: datetime | None = None


class ChangeoverMatrixEntry(ReOrchModel):
    resource_id: str | None = None
    machine_group_id: str | None = None
    from_family: str
    to_family: str
    setup_minutes: int = Field(ge=0)
    cost: float = Field(default=0.0, ge=0.0)


class QualityHoldConstraint(ReOrchModel):
    entity_id: str
    entity_type: str = "work_order"
    hold_reason: str
    blocked_operation_ids: list[str] = Field(default_factory=list)
    release_gate: str = "quality_approval_required"


class OutsourcingOption(ReOrchModel):
    vendor_id: str
    capability_codes: list[str] = Field(default_factory=list)
    lead_time_minutes: int = Field(gt=0)
    capacity_per_day: float = Field(gt=0.0)
    approval_required: bool = True


class TransportConstraint(ReOrchModel):
    lane_id: str
    from_location_id: str
    to_location_id: str
    transport_mode: str = "manual"
    capacity: int = Field(default=1, gt=0)
    eta_minutes: int = Field(default=0, ge=0)


class BufferConstraint(ReOrchModel):
    buffer_id: str
    location_id: str
    capacity: int = Field(gt=0)
    current_wip: int = Field(default=0, ge=0)


class WipItem(ReOrchModel):
    wip_id: str
    work_order_id: str
    operation_id: str | None = None
    quantity: float = Field(gt=0.0)
    location_id: str
    status: str = "waiting"


class FrozenZone(ReOrchModel):
    zone_id: str
    operation_ids: list[str] = Field(default_factory=list)
    work_order_ids: list[str] = Field(default_factory=list)
    frozen_until: datetime
    reason: str


class FlexibleConstraintPack(ReOrchModel):
    materials: list[MaterialConstraint] = Field(default_factory=list)
    skills: list[SkillConstraint] = Field(default_factory=list)
    tooling: list[ToolingConstraint] = Field(default_factory=list)
    changeovers: list[ChangeoverMatrixEntry] = Field(default_factory=list)
    quality_holds: list[QualityHoldConstraint] = Field(default_factory=list)
    outsourcing: list[OutsourcingOption] = Field(default_factory=list)
    transport: list[TransportConstraint] = Field(default_factory=list)
    buffers: list[BufferConstraint] = Field(default_factory=list)


class FlexibleShopContext(ReOrchModel):
    site_id: str
    captured_at: datetime
    workshops: list[FlexibleWorkshop] = Field(default_factory=list)
    machine_groups: list[FlexibleMachineGroup] = Field(default_factory=list)
    resources: list[FlexibleResource] = Field(default_factory=list)
    work_orders: list[FlexibleWorkOrder] = Field(default_factory=list)
    wip_items: list[WipItem] = Field(default_factory=list)
    frozen_zones: list[FrozenZone] = Field(default_factory=list)
    constraints: FlexibleConstraintPack = Field(default_factory=FlexibleConstraintPack)
    integration_sources: dict[str, str] = Field(default_factory=dict)


class DynamicIncidentScenario(ReOrchModel):
    incident_id: str
    incident_type: IncidentCategory
    resource_id: str | None = None
    work_order_id: str | None = None
    material_id: str | None = None
    tooling_id: str | None = None
    affected_operation_ids: list[str] = Field(default_factory=list)
    severity: str = "medium"
    estimated_duration_minutes: int = Field(default=0, ge=0)
    description: str | None = None


class CapabilityStatus(ReOrchModel):
    module: str
    status: Literal["ready", "partial", "missing"]
    coverage_score: float = Field(ge=0.0, le=1.0)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class FlexibleShopCapabilityRequest(ReOrchModel):
    context: FlexibleShopContext
    incident_types_to_support: list[IncidentCategory] = Field(default_factory=list)
    historical_replay_case_count: int = Field(default=0, ge=0)
    shadow_case_count: int = Field(default=0, ge=0)
    execution_feedback_case_count: int = Field(default=0, ge=0)
    sandbox_writeback_ready: bool = False
    approved_writeback_roles: list[str] = Field(default_factory=list)
    benchmark_operation_targets: list[int] = Field(
        default_factory=lambda: [1000, 5000, 10000]
    )


class FlexibleShopCapabilityResponse(ReOrchModel):
    site_id: str
    overall_status: Literal["pilot_ready", "shadow_ready", "replay_only", "blocked"]
    statuses: list[CapabilityStatus]
    claim_boundary: str


class SolverStrategyPlan(ReOrchModel):
    decomposition_level: str
    bottleneck_first: bool
    rolling_window_minutes: int
    use_lns: bool
    use_alns_memory: bool
    warm_start: str
    timeout_seconds: float
    fallback_policy: str
    rationale: list[str] = Field(default_factory=list)


class DynamicReschedulingPlanRequest(ReOrchModel):
    context: FlexibleShopContext
    incidents: list[DynamicIncidentScenario]
    solve_timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)


class IncidentRecoveryPlan(ReOrchModel):
    incident_id: str
    incident_type: IncidentCategory
    context_fingerprint: dict[str, str | int | float | bool | list[str]]
    recovery_policies: list[str]
    required_constraints: list[str]
    required_gates: list[str]
    solver_strategy: SolverStrategyPlan
    blockers: list[str] = Field(default_factory=list)


class DynamicReschedulingPlanResponse(ReOrchModel):
    plans: list[IncidentRecoveryPlan]
    global_solver_strategy: SolverStrategyPlan
    claim_boundary: str


class BenchmarkTarget(ReOrchModel):
    operation_count: int = Field(gt=0)
    resource_count: int = Field(default=100, gt=0)
    concurrent_incidents: int = Field(default=1, gt=0)


class FlexibleShopBenchmarkRequest(ReOrchModel):
    targets: list[BenchmarkTarget] = Field(
        default_factory=lambda: [
            BenchmarkTarget(operation_count=1000, resource_count=80),
            BenchmarkTarget(operation_count=5000, resource_count=250),
            BenchmarkTarget(operation_count=10000, resource_count=500),
        ]
    )
    solve_timeout_seconds: float = Field(default=60.0, gt=0.0, le=600.0)


class BenchmarkResult(ReOrchModel):
    operation_count: int
    resource_count: int
    concurrent_incidents: int
    benchmark_mode: str
    p95_routing_latency_ms: float
    p95_gate_latency_ms: float
    recommended_solver_budget_seconds: float
    recommended_strategy: str
    pass_shadow_threshold: bool
    notes: list[str] = Field(default_factory=list)


class FlexibleShopBenchmarkResponse(ReOrchModel):
    generated_at: datetime
    results: list[BenchmarkResult]
    claim_boundary: str


class PolicyOutcomeObservation(ReOrchModel):
    policy_type: str
    hard_feasible: bool
    accepted_by_planner: bool = False
    delay_delta_minutes: float = 0.0
    perturbation_cost: float = 0.0
    setup_delta: int = 0
    execution_failed: bool = False
    sample_weight: float = Field(default=1.0, gt=0.0)


class HistoricalRecoveryCase(ReOrchModel):
    case_id: str
    context_key: str
    incident_type: IncidentCategory
    observations: list[PolicyOutcomeObservation] = Field(default_factory=list)


class CounterfactualReplayMatrixRequest(ReOrchModel):
    cases: list[HistoricalRecoveryCase] = Field(default_factory=list)
    min_sample_count: int = Field(default=3, ge=1)


class PolicyEffectivenessCell(ReOrchModel):
    context_key: str
    policy_type: str
    sample_count: int
    feasible_rate: float
    planner_acceptance_rate: float
    mean_delay_delta_minutes: float
    mean_perturbation_cost: float
    execution_failure_rate: float
    confidence_level: Literal["low", "medium", "high"]


class CounterfactualReplayMatrixResponse(ReOrchModel):
    cells: list[PolicyEffectivenessCell]
    insufficient_contexts: list[str] = Field(default_factory=list)
    claim_boundary: str
