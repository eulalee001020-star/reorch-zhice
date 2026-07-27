"""Level 2/3 digital-twin replay rehearsal models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.production_readiness import ProductionReadinessResponse

TwinRowValue = str | int | float | bool | None
TwinRow = dict[str, TwinRowValue]


class Level23DigitalTwinReplayRequest(ReOrchModel):
    """Workbook-like Level 2/3 digital-twin data pack represented as rows."""

    pack_id: str = "level2_3_digital_twin_v0_2"
    source_workbook_name: str | None = None
    resources: list[TwinRow] = Field(default_factory=list)
    work_orders: list[TwinRow] = Field(default_factory=list)
    operations: list[TwinRow] = Field(default_factory=list)
    routing_precedence: list[TwinRow] = Field(default_factory=list)
    schedule_snapshot: list[TwinRow] = Field(default_factory=list)
    constraints: list[TwinRow] = Field(default_factory=list)
    material_inventory: list[TwinRow] = Field(default_factory=list)
    incidents: list[TwinRow] = Field(default_factory=list)
    manual_outcomes: list[TwinRow] = Field(default_factory=list)
    execution_feedback: list[TwinRow] = Field(default_factory=list)
    candidate_plans: list[TwinRow] = Field(default_factory=list)
    replay_comparison: list[TwinRow] = Field(default_factory=list)
    policy_effectiveness: list[TwinRow] = Field(default_factory=list)
    readiness_scorecard: list[TwinRow] = Field(default_factory=list)


class Level23TableStatus(ReOrchModel):
    table_name: str
    row_count: int = Field(ge=0)
    required: bool = True
    status: Literal["pass", "warning", "blocker"]
    notes: list[str] = Field(default_factory=list)


class Level23LinkageMetrics(ReOrchModel):
    incident_count: int = 0
    incident_to_schedule_link_count: int = 0
    incident_to_operation_link_count: int = 0
    incident_to_work_order_link_count: int = 0
    incident_with_candidate_count: int = 0
    affected_subgraph_ready_count: int = 0
    affected_subgraph_ready_rate: float = 0.0


class Level23ReplayMetrics(ReOrchModel):
    incident_count: int = 0
    candidate_plan_count: int = 0
    feasible_candidate_count: int = 0
    simulated_manual_outcome_count: int = 0
    simulated_execution_feedback_count: int = 0
    top1_exact_match_count: int = 0
    top1_exact_match_rate: float = 0.0
    top3_manual_coverage_count: int = 0
    top3_manual_coverage_rate: float = 0.0
    hard_feasible_top1_count: int = 0
    hard_feasible_top1_rate: float = 0.0
    planner_review_needed_count: int = 0
    planner_review_needed_rate: float = 0.0
    average_delay_delta_system_minus_manual: float = 0.0
    average_perturbation_delta_system_minus_manual: float = 0.0


class Level23ExecutionMetrics(ReOrchModel):
    execution_success_count: int = 0
    execution_success_rate: float = 0.0
    secondary_incident_count: int = 0
    secondary_incident_rate: float = 0.0
    average_actual_delay_min: float = 0.0
    average_planner_satisfaction_score: float = 0.0


class Level23PolicySummary(ReOrchModel):
    strategy_type: str
    candidate_count: int = 0
    feasible_rate: float = 0.0
    manual_selection_rate: float = 0.0
    execution_success_rate: float = 0.0
    average_predicted_delay_min: float = 0.0
    average_actual_delay_min: float = 0.0
    confidence_level: Literal["simulated_low", "simulated_medium"]
    source_boundary: str


class Level23DigitalTwinReplayResponse(ReOrchModel):
    pack_id: str
    source_workbook_name: str | None = None
    rehearsal_level: Literal[
        "blocked",
        "level_2_schedule_bridge_ready",
        "level_2_3_rehearsal_ready",
    ]
    readiness_score: float = Field(ge=0.0, le=1.0)
    table_statuses: list[Level23TableStatus]
    linkage_metrics: Level23LinkageMetrics
    replay_metrics: Level23ReplayMetrics
    execution_metrics: Level23ExecutionMetrics
    policy_summaries: list[Level23PolicySummary]
    production_readiness: ProductionReadinessResponse
    next_actions: list[str] = Field(default_factory=list)
    claim_boundary: str
