"""Solver-related Pydantic models for the ReOrch system.

Defines SolverChain, SolverMetadata, ConstraintViolation,
ConstraintValidationReport, and CandidatePlan used by the
Hybrid_Solver and downstream evaluation/recommendation layers.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.schedule import ScheduleDetail


class SolverChain(ReOrchModel):
    """Actual algorithm chain executed to produce a CandidatePlan."""

    strategy_type: str
    rule_selection: str
    neighborhood_selection: str
    repair_policy: str
    solver_name: str
    key_parameters: dict
    search_budget_seconds: float
    constraint_validation_result: str
    stages: list[str] = Field(default_factory=list)


class SolverMetadata(ReOrchModel):
    """Solver execution metadata recorded for each CandidatePlan."""

    solve_time_seconds: float
    iteration_count: int
    objective_trajectory: list[float] = Field(default_factory=list)
    degradation_occurred: bool = False
    degradation_reason: str | None = None


class ConstraintViolation(ReOrchModel):
    """A single constraint violation found during validation."""

    constraint_type: str
    operation_id: str
    resource_id: str | None = None
    detail: str


class ConstraintValidationReport(ReOrchModel):
    """Result of constraint validation for a CandidatePlan."""

    is_feasible: bool
    violations: list[ConstraintViolation] = Field(default_factory=list)
    checked_constraints: list[str] = Field(default_factory=list)


class CandidatePlan(ReOrchModel):
    """A candidate re-scheduling plan produced by Hybrid_Solver."""

    plan_id: UUID = Field(default_factory=uuid4)
    strategy_type: str
    schedule_detail: ScheduleDetail
    gantt_version: str
    solver_chain: SolverChain
    feasibility_status: str  # "feasible" | "infeasible" | "timeout_partial"
    solver_metadata: SolverMetadata
    constraint_report: ConstraintValidationReport
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
