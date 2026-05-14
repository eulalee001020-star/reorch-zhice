"""Confirmation Module for the ReOrch system.

Implements human-in-the-loop confirmation, micro-adjustment, and override
workflows for candidate plans.

Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8

Key responsibilities:
- confirm(): Accept, accept-with-adjustment, or reject-and-reselect plans
- Micro-adjustment creates a new plan version (derived_from_plan_id links original)
- Hard constraint violations block confirmation
- Override records reason, original recommended plan, actual selected plan, time
- Generates complete DecisionRecord with all candidate plan IDs, strategy module versions
- RBAC: Planner confirm/adjust/reject, Shop_Floor_Executor view-only, Management approve P1
- check_timeout(): 15-minute timeout reminder for unconfirmed incidents
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.core.auth import Role
from app.models.decision import ConfirmRequest, ConfirmResponse, DecisionRecord
from app.models.enums import ConfirmAction, IncidentSeverity
from app.models.schedule import ScheduleDetail, ScheduleSnapshot
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
)
from app.services.constraint_validator import ConstraintValidator

logger = logging.getLogger(__name__)

# Timeout threshold in minutes (Req 7.8)
_CONFIRMATION_TIMEOUT_MINUTES = 15


class PermissionDeniedError(Exception):
    """Raised when a user lacks the required role for an operation."""


class ConstraintViolationError(Exception):
    """Raised when a micro-adjusted plan violates hard constraints."""

    def __init__(self, report: ConstraintValidationReport) -> None:
        self.report = report
        violations_summary = "; ".join(v.detail for v in report.violations)
        super().__init__(f"Hard constraint violations: {violations_summary}")


class OverrideReasonRequiredError(Exception):
    """Raised when reject_and_reselect is used without providing a reason."""


class ConfirmationModule:
    """Human confirmation module: accept / micro-adjust / override.

    Micro-adjustment creates a new plan version linked via
    ``derived_from_plan_id``.

    RBAC:
    - Planner: confirm / micro-adjust / reject
    - Shop_Floor_Executor: view only
    - Management: view + approve P1

    15-minute timeout reminder (Req 7.8).
    """

    def __init__(
        self,
        constraint_validator: ConstraintValidator | None = None,
        module_versions: dict[str, str] | None = None,
    ) -> None:
        self._validator = constraint_validator or ConstraintValidator()
        # Strategy module versions for DecisionRecord
        self._module_versions = module_versions or {
            "rule_selector": "1.0.0",
            "neighborhood_selector": "1.0.0",
            "repair_policy_advisor": "1.0.0",
        }
        # In-memory stores for MVP
        self._pending_incidents: dict[UUID, datetime] = {}
        self._timeout_notifications: list[dict] = []

    # ── RBAC enforcement (Req 7.7) ──────────────────────────────────

    @staticmethod
    def check_permission(
        role: Role | str,
        action: ConfirmAction,
        incident_severity: IncidentSeverity | str | None = None,
    ) -> None:
        """Verify the user role is allowed to perform the given action.

        Raises PermissionDeniedError if not permitted.
        """
        role_val = role.value if isinstance(role, Role) else role

        # Shop_Floor_Executor can only view (no confirm actions)
        if role_val == Role.SHOP_FLOOR_EXECUTOR.value:
            raise PermissionDeniedError(
                f"Role '{role_val}' can only view, not perform '{action}' actions."
            )

        # Management can only approve P1 incidents
        if role_val == Role.MANAGEMENT.value:
            sev_val = (
                incident_severity.value
                if isinstance(incident_severity, IncidentSeverity)
                else incident_severity
            )
            if sev_val != IncidentSeverity.P1_CRITICAL.value:
                raise PermissionDeniedError(
                    f"Role '{role_val}' can only approve P1-Critical incidents, "
                    f"not severity '{sev_val}'."
                )

        # Planner and IT_Admin can do everything — no restriction
        if role_val not in (
            Role.PLANNER.value,
            Role.IT_ADMIN.value,
            Role.MANAGEMENT.value,
        ):
            raise PermissionDeniedError(
                f"Role '{role_val}' is not permitted to perform confirmation actions."
            )

    # ── Core confirm flow (Req 7.1-7.6) ────────────────────────────

    async def confirm(
        self,
        request: ConfirmRequest,
        candidate_plans: list[CandidatePlan],
        recommended_plan_id: UUID,
        snapshot: ScheduleSnapshot,
        impact_report_summary: str,
        strategy_type: str,
        role: Role | str = Role.PLANNER,
        incident_severity: IncidentSeverity | str | None = None,
        plan_selection_input_version: str = "1.0",
        plan_selection_output_version: str = "1.0",
    ) -> ConfirmResponse:
        """Process a confirmation request.

        Args:
            request: The confirmation payload from the Planner.
            candidate_plans: All candidate plans for this incident.
            recommended_plan_id: The AI-recommended plan ID.
            snapshot: The baseline ScheduleSnapshot for constraint checks.
            impact_report_summary: Summary text for the DecisionRecord.
            strategy_type: The strategy used (e.g. "local_repair").
            role: The user's role for RBAC checks.
            incident_severity: Severity of the incident (needed for Management approval).
            plan_selection_input_version: Version of PlanSelectionInput.
            plan_selection_output_version: Version of PlanSelectionOutput.

        Returns:
            ConfirmResponse with confirmed plan, constraint report, and decision record.

        Raises:
            PermissionDeniedError: If the user role is not allowed.
            ConstraintViolationError: If micro-adjustment violates hard constraints.
            OverrideReasonRequiredError: If reject without reason.
            ValueError: If selected plan not found.
        """
        # RBAC check
        self.check_permission(role, request.action, incident_severity)

        # Find the selected plan
        plan_map = {p.plan_id: p for p in candidate_plans}
        selected_plan = plan_map.get(request.selected_plan_id)
        if selected_plan is None:
            raise ValueError(
                f"Selected plan '{request.selected_plan_id}' not found "
                f"in candidate plans."
            )

        confirmed_plan_id = selected_plan.plan_id
        derived_from_plan_id = selected_plan.plan_id
        is_manual_adjusted = False
        is_override = False
        override_reason: str | None = None
        constraint_report: ConstraintValidationReport

        if request.action == ConfirmAction.ACCEPT:
            # Straight acceptance — use existing constraint report
            constraint_report = selected_plan.constraint_report

        elif request.action == ConfirmAction.ACCEPT_WITH_ADJUSTMENT:
            # Micro-adjustment: create new plan version (Req 7.2, 7.3)
            is_manual_adjusted = True
            derived_from_plan_id = selected_plan.plan_id

            adjusted_schedule = self._apply_adjustments(
                selected_plan.schedule_detail, request.adjustments or []
            )

            # Re-validate constraints (Req 7.3, 7.4)
            constraint_report = self._validator.validate_microadjustment(
                original_plan=selected_plan,
                adjusted_schedule=adjusted_schedule,
                snapshot=snapshot,
            )

            if not constraint_report.is_feasible:
                raise ConstraintViolationError(constraint_report)

            # New plan version ID
            confirmed_plan_id = uuid4()

        elif request.action == ConfirmAction.REJECT_AND_RESELECT:
            # Override (Req 7.5)
            if not request.override_reason:
                raise OverrideReasonRequiredError(
                    "Override reason is required when rejecting and reselecting."
                )
            is_override = True
            override_reason = request.override_reason
            constraint_report = selected_plan.constraint_report

        else:
            raise ValueError(f"Unknown confirm action: {request.action}")

        # Build DecisionRecord (Req 7.6)
        decision_record = self._build_decision_record(
            request=request,
            candidate_plans=candidate_plans,
            recommended_plan_id=recommended_plan_id,
            confirmed_plan_id=confirmed_plan_id,
            derived_from_plan_id=derived_from_plan_id,
            is_override=is_override,
            is_manual_adjusted=is_manual_adjusted,
            override_reason=override_reason,
            impact_report_summary=impact_report_summary,
            strategy_type=strategy_type,
            selected_plan=selected_plan,
            plan_selection_input_version=plan_selection_input_version,
            plan_selection_output_version=plan_selection_output_version,
        )

        # Remove from pending (timeout tracking)
        self._pending_incidents.pop(request.incident_id, None)

        return ConfirmResponse(
            confirmed_plan_id=confirmed_plan_id,
            derived_from_plan_id=derived_from_plan_id,
            is_manual_adjusted=is_manual_adjusted,
            constraint_validation=constraint_report,
            decision_record_id=decision_record.decision_record_id,
        )

    # ── Timeout check (Req 7.8) ────────────────────────────────────

    def register_pending(self, incident_id: UUID) -> None:
        """Register an incident as pending confirmation for timeout tracking."""
        self._pending_incidents[incident_id] = datetime.now(tz=timezone.utc)

    async def check_timeout(self, incident_id: UUID) -> bool:
        """Check if an incident has exceeded the 15-minute confirmation window.

        Returns True if a timeout notification was generated.
        """
        pending_since = self._pending_incidents.get(incident_id)
        if pending_since is None:
            return False

        now = datetime.now(tz=timezone.utc)
        elapsed_minutes = (now - pending_since).total_seconds() / 60.0

        if elapsed_minutes >= _CONFIRMATION_TIMEOUT_MINUTES:
            notification = {
                "incident_id": str(incident_id),
                "elapsed_minutes": round(elapsed_minutes, 1),
                "message": (
                    f"Incident {incident_id} has been pending confirmation "
                    f"for {round(elapsed_minutes, 1)} minutes "
                    f"(threshold: {_CONFIRMATION_TIMEOUT_MINUTES} min). "
                    f"Please confirm or escalate."
                ),
                "timestamp": now.isoformat(),
            }
            self._timeout_notifications.append(notification)
            logger.warning(
                "Timeout reminder: incident %s pending for %.1f minutes",
                incident_id,
                elapsed_minutes,
            )
            return True

        return False

    def get_timeout_notifications(self) -> list[dict]:
        """Return all timeout notifications (for testing / inspection)."""
        return list(self._timeout_notifications)

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _apply_adjustments(
        schedule: ScheduleDetail, adjustments: list[dict]
    ) -> ScheduleDetail:
        """Apply micro-adjustments to a schedule, returning a new copy.

        Each adjustment dict may contain:
        - operation_id: str
        - new_resource_id: str (optional)
        - new_start_time: str/datetime (optional)
        - new_end_time: str/datetime (optional)
        """
        data = schedule.model_dump()
        adj_map: dict[str, dict] = {}
        for adj in adjustments:
            op_id = adj.get("operation_id")
            if op_id:
                adj_map[op_id] = adj

        for wo in data.get("work_orders", []):
            for op in wo.get("operations", []):
                adj = adj_map.get(op["operation_id"])
                if adj:
                    if "new_resource_id" in adj:
                        op["resource_id"] = adj["new_resource_id"]
                    if "new_start_time" in adj:
                        op["start_time"] = adj["new_start_time"]
                    if "new_end_time" in adj:
                        op["end_time"] = adj["new_end_time"]
                    op["is_adjusted"] = True

        return ScheduleDetail.model_validate(data)

    def _build_decision_record(
        self,
        request: ConfirmRequest,
        candidate_plans: list[CandidatePlan],
        recommended_plan_id: UUID,
        confirmed_plan_id: UUID,
        derived_from_plan_id: UUID,
        is_override: bool,
        is_manual_adjusted: bool,
        override_reason: str | None,
        impact_report_summary: str,
        strategy_type: str,
        selected_plan: CandidatePlan,
        plan_selection_input_version: str,
        plan_selection_output_version: str,
    ) -> DecisionRecord:
        """Build a complete DecisionRecord (Req 7.6)."""
        return DecisionRecord(
            decision_record_id=uuid4(),
            incident_id=request.incident_id,
            impact_report_summary=impact_report_summary,
            strategy_type=strategy_type,
            all_candidate_plan_ids=[p.plan_id for p in candidate_plans],
            recommended_plan_id=recommended_plan_id,
            confirmed_plan_id=confirmed_plan_id,
            derived_from_plan_id=derived_from_plan_id,
            is_override=is_override,
            is_manual_adjusted=is_manual_adjusted,
            override_reason=override_reason,
            confirmed_by=request.confirmed_by,
            confirmed_at=datetime.now(tz=timezone.utc),
            plan_selection_input_version=plan_selection_input_version,
            plan_selection_output_version=plan_selection_output_version,
            solver_chain=selected_plan.solver_chain,
            rule_selector_version=self._module_versions.get(
                "rule_selector", "unknown"
            ),
            neighborhood_selector_version=self._module_versions.get(
                "neighborhood_selector", "unknown"
            ),
            repair_policy_advisor_version=self._module_versions.get(
                "repair_policy_advisor", "unknown"
            ),
        )
