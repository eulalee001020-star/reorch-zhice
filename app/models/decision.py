"""Decision-related Pydantic models for the ReOrch system.

Defines ConfirmRequest, ConfirmResponse, and DecisionRecord used
by the Confirmation_Module to capture human confirmation actions,
micro-adjustments, overrides, and the full decision audit trail.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.enums import ConfirmAction
from app.models.solver import ConstraintValidationReport, SolverChain


class ConfirmRequest(ReOrchModel):
    """Payload sent by a Planner to confirm, adjust, or override a plan."""

    incident_id: UUID
    action: ConfirmAction
    selected_plan_id: UUID
    adjustments: list[dict] | None = None  # micro-adjustment content
    override_reason: str | None = None  # required when action is reject_and_reselect
    confirmed_by: str


class ConfirmResponse(ReOrchModel):
    """Response after a plan confirmation, including constraint validation.

    When a plan is micro-adjusted a new plan version is created;
    ``derived_from_plan_id`` links back to the original plan.
    """

    confirmed_plan_id: UUID
    derived_from_plan_id: UUID  # original plan ID
    is_manual_adjusted: bool
    constraint_validation: ConstraintValidationReport
    decision_record_id: UUID


class DecisionRecord(ReOrchModel):
    """Complete audit record for a single decision cycle.

    Captures the full context: incident, impact summary, strategy,
    all candidate plans, recommendation, confirmation, override info,
    and the versions of every Solver Policy Layer module involved.
    """

    decision_record_id: UUID
    incident_id: UUID
    impact_report_summary: str
    strategy_type: str
    all_candidate_plan_ids: list[UUID] = Field(default_factory=list)
    recommended_plan_id: UUID
    confirmed_plan_id: UUID
    derived_from_plan_id: UUID  # links to original plan when adjusted
    is_override: bool
    is_manual_adjusted: bool
    override_reason: str | None = None
    confirmed_by: str
    confirmed_at: datetime
    plan_selection_input_version: str
    plan_selection_output_version: str
    solver_chain: SolverChain
    rule_selector_version: str
    neighborhood_selector_version: str
    repair_policy_advisor_version: str
