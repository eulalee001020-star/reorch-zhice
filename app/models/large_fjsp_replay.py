"""Large FJSP anomaly replay and rescheduling models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import ReOrchModel


class LargeFjspReplayRequest(ReOrchModel):
    """An anonymized large-FJSP pack normalized from CSV/API rows."""

    source_system: str = "large_fjsp_pack"
    workshop_id: str = "LARGE-FJSP"
    work_orders: list[dict] = Field(default_factory=list)
    operations: list[dict] = Field(default_factory=list)
    resources: list[dict] = Field(default_factory=list)
    schedule_rows: list[dict] = Field(default_factory=list)
    incidents: list[dict] = Field(default_factory=list)
    timezone_suffix: str = "+00:00"
    max_incidents: int = Field(default=30, gt=0, le=200)
    cp_sat_timeout_seconds: float = Field(default=5.0, gt=0.0, le=60.0)
    include_global_reschedule: bool = True
    freeze_snapshot_operations: bool = True


class LargeFjspStrategyKpi(ReOrchModel):
    adjusted_operation_count: int = 0
    resource_switch_count: int = 0
    total_start_shift_minutes: float = 0.0
    max_start_shift_minutes: float = 0.0
    affected_completion_delta_minutes: float = 0.0
    total_tardiness_delta_minutes: float = 0.0
    frozen_change_count: int = 0


class LargeFjspStrategyOption(ReOrchModel):
    policy_type: str
    solver_strategy: Literal[
        "wait_and_repair",
        "local_repair",
        "global_reschedule",
        "reference_only",
    ]
    feasibility_status: Literal["feasible", "infeasible", "blocked"]
    solver_status: str
    objective_value: float | None = None
    solve_time_seconds: float = 0.0
    variable_operation_count: int = 0
    kpi: LargeFjspStrategyKpi
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    decision_boundary: str


class LargeFjspIncidentReplayResult(ReOrchModel):
    case_id: str
    source_incident_type: str
    normalized_incident_type: str
    affected_operation_id: str | None = None
    affected_work_order_id: str | None = None
    estimated_service_loss_minutes: float = 0.0
    options: list[LargeFjspStrategyOption] = Field(default_factory=list)
    recommended_policy: str | None = None
    recommendation_reason: str | None = None
    can_generate_executable_plan: bool = False
    remaining_gaps: list[str] = Field(default_factory=list)


class LargeFjspReplayResponse(ReOrchModel):
    source_system: str
    workshop_id: str
    permission_level: str
    readiness_score: float
    snapshot_available: bool
    work_order_count: int
    operation_count: int
    resource_count: int
    incident_count: int
    solved_incident_count: int
    feasible_option_count: int
    results: list[LargeFjspIncidentReplayResult] = Field(default_factory=list)
    global_gaps: list[str] = Field(default_factory=list)
    claim_boundary: str
