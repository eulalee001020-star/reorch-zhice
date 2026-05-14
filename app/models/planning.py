"""Planning, readiness, quality-gate, and value-tracking models."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.schedule import ScheduleSnapshot
from app.models.solver import CandidatePlan, ConstraintViolation


class ReadinessIssue(ReOrchModel):
    """A single data readiness issue found before planning or rescheduling."""

    severity: str = Field(description="blocker | warning | info")
    code: str
    message: str
    entity_type: str | None = None
    entity_id: str | None = None


class DataReadinessReport(ReOrchModel):
    """Data readiness report for a planning or rescheduling run."""

    is_ready: bool
    readiness_score: float = Field(ge=0.0, le=1.0)
    blockers: list[ReadinessIssue] = Field(default_factory=list)
    warnings: list[ReadinessIssue] = Field(default_factory=list)
    infos: list[ReadinessIssue] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class PlanningResourceInput(ReOrchModel):
    """Resource definition for from-zero initial scheduling."""

    resource_id: str
    name: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    is_bottleneck: bool = False
    has_redundancy: bool = False
    criticality: str = "general"
    cost_per_minute: float = Field(default=1.0, ge=0.0)


class ResourceCalendarWindowInput(ReOrchModel):
    """Resource calendar window.

    PoC convention:
    - unavailable: blocks the resource in [window_start, window_end)
    - available: recorded for customer visibility; production-grade shift
      calendars can be converted to unavailable windows before scheduling.
    """

    resource_id: str
    window_start: datetime
    window_end: datetime
    availability_type: str = Field(default="unavailable")
    reason: str | None = None


class PlanningMaterialRequirementInput(ReOrchModel):
    """Material requirement for one operation."""

    material_id: str
    required_quantity: float = Field(gt=0.0)
    available_at: datetime | None = None
    status: str = "available"


class ChangeoverRuleInput(ReOrchModel):
    """Sequence-dependent setup/changeover rule."""

    from_product_family: str
    to_product_family: str
    setup_minutes: int = Field(ge=0)
    cost: float = Field(default=0.0, ge=0.0)
    resource_id: str | None = None


class PlanningOperationInput(ReOrchModel):
    """Operation definition for from-zero initial scheduling."""

    operation_id: str
    work_order_id: str
    duration_minutes: int = Field(gt=0)
    eligible_resource_ids: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    predecessor_ids: list[str] = Field(default_factory=list)
    release_time: datetime | None = None
    product_family: str | None = None
    material_requirements: list[PlanningMaterialRequirementInput] = Field(
        default_factory=list
    )


class PlanningWorkOrderInput(ReOrchModel):
    """Work order definition for from-zero initial scheduling."""

    work_order_id: str
    product_name: str
    due_date: datetime
    priority: int = Field(default=0, ge=0)
    product_family: str | None = None
    operations: list[PlanningOperationInput] = Field(default_factory=list)


class InitialScheduleRequest(ReOrchModel):
    """Request for generating multiple initial schedule options."""

    workshop_id: str
    planning_start: datetime
    resources: list[PlanningResourceInput] = Field(default_factory=list)
    resource_calendar: list[ResourceCalendarWindowInput] = Field(default_factory=list)
    changeover_rules: list[ChangeoverRuleInput] = Field(default_factory=list)
    work_orders: list[PlanningWorkOrderInput] = Field(default_factory=list)
    goal_modes: list[str] = Field(
        default_factory=lambda: [
            "delivery_priority",
            "throughput_priority",
            "bottleneck_priority",
            "cost_priority",
            "balanced",
        ]
    )
    max_solutions: int = Field(default=5, ge=1, le=8)
    time_budget_seconds: float = Field(default=10.0, gt=0.0, le=60.0)


class InitialScheduleOption(ReOrchModel):
    """One generated initial schedule option with objective explanation."""

    goal_mode: str
    label: str
    strengths: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    candidate_plan: CandidatePlan
    kpis: dict[str, float | int | str] = Field(default_factory=dict)


class InitialScheduleResponse(ReOrchModel):
    """Response for from-zero initial schedule generation."""

    workshop_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    readiness_report: DataReadinessReport
    options: list[InitialScheduleOption] = Field(default_factory=list)


class EnterpriseFieldMapping(ReOrchModel):
    """Best-effort field mapping for ERP/MES/APS payload normalization."""

    work_orders_path: str = "work_orders"
    resources_path: str = "resources"
    work_order_id: str = "work_order_id"
    product_name: str = "product_name"
    product_family: str = "product_family"
    due_date: str = "due_date"
    priority: str = "priority"
    operations: str = "operations"
    operation_id: str = "operation_id"
    duration_minutes: str = "duration_minutes"
    resource_id: str = "resource_id"
    eligible_resource_ids: str = "eligible_resource_ids"
    required_capabilities: str = "required_capabilities"
    predecessor_ids: str = "predecessor_ids"
    resource_capabilities: str = "capabilities"


class EnterpriseImportRequest(ReOrchModel):
    """Raw ERP/MES/APS import request with a lightweight mapping profile."""

    source_system: str
    workshop_id: str
    planning_start: datetime
    raw_payload: dict
    mapping: EnterpriseFieldMapping = Field(default_factory=EnterpriseFieldMapping)


class EnterpriseImportResponse(ReOrchModel):
    """Normalized import result for PoC data onboarding."""

    source_system: str
    readiness_report: DataReadinessReport
    initial_schedule_request: InitialScheduleRequest


class WritebackPreviewRequest(ReOrchModel):
    """Build target-system schedule-change instructions before actual writeback."""

    candidate_plan: CandidatePlan
    target_format: str = "standard"
    only_adjusted_operations: bool = True


class WritebackPreviewResponse(ReOrchModel):
    """Writeback instructions ready for customer-system adapter review."""

    target_format: str
    instruction_count: int
    instructions: list[dict] = Field(default_factory=list)


class PlanQualityGateReport(ReOrchModel):
    """Operational usability gate for a candidate plan."""

    plan_id: UUID
    pass_gate: bool
    confidence_level: str
    hard_blockers: list[ConstraintViolation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendation_policy: str


class PlanQualityGateRequest(ReOrchModel):
    """Batch quality-gate request for generated candidate plans."""

    candidate_plans: list[CandidatePlan] = Field(default_factory=list)
    baseline_snapshot: ScheduleSnapshot | None = None


class PlanQualityGateResponse(ReOrchModel):
    """Batch quality-gate response."""

    reports: list[PlanQualityGateReport] = Field(default_factory=list)


class ValueTrackingInput(ReOrchModel):
    """Before/after metrics used to estimate PoC value."""

    incident_count: int = Field(default=1, ge=0)
    baseline_decision_minutes: float = Field(default=0.0, ge=0.0)
    actual_decision_minutes: float = Field(default=0.0, ge=0.0)
    baseline_tardiness_minutes: float = Field(default=0.0, ge=0.0)
    actual_tardiness_minutes: float = Field(default=0.0, ge=0.0)
    baseline_changeovers: int = Field(default=0, ge=0)
    actual_changeovers: int = Field(default=0, ge=0)
    baseline_overtime_hours: float = Field(default=0.0, ge=0.0)
    actual_overtime_hours: float = Field(default=0.0, ge=0.0)
    planner_hourly_cost: float = Field(default=120.0, ge=0.0)
    tardiness_cost_per_minute: float = Field(default=0.0, ge=0.0)
    changeover_cost: float = Field(default=0.0, ge=0.0)
    overtime_hourly_cost: float = Field(default=0.0, ge=0.0)


class ValueTrackingReport(ReOrchModel):
    """Estimated value report for PoC acceptance and renewal discussions."""

    saved_decision_minutes: float
    reduced_tardiness_minutes: float
    reduced_changeovers: int
    reduced_overtime_hours: float
    estimated_savings: float
    savings_breakdown: dict[str, float] = Field(default_factory=dict)
    payback_commentary: str


class DigitalTwinRunResponse(ReOrchModel):
    """End-to-end sample run on a realistic single-workshop digital twin."""

    scenario_id: str
    initial_schedule: InitialScheduleResponse
    selected_initial_option: InitialScheduleOption | None = None
    baseline_snapshot: ScheduleSnapshot | None = None
    incident: dict | None = None
    impact_report: dict | None = None
    strategy: dict | None = None
    reschedule_candidates: list[CandidatePlan] = Field(default_factory=list)
    quality_gates: list[PlanQualityGateReport] = Field(default_factory=list)
    simulation_results: list[dict] = Field(default_factory=list)
    writeback_preview: WritebackPreviewResponse | None = None
    value_report: ValueTrackingReport | None = None
    runbook: list[str] = Field(default_factory=list)
