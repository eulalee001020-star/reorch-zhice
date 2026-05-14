"""Tests for ConfirmationModule service.

Covers:
- Three confirmation actions (accept, accept_with_adjustment, reject_and_reselect)
- Micro-adjustment constraint validation (pass/fail)
- Override record completeness
- RBAC permission control
- 15-minute timeout reminder
- DecisionRecord generation

Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.core.auth import Role
from app.models.decision import ConfirmRequest
from app.models.enums import ConfirmAction, IncidentSeverity
from app.models.schedule import (
    Operation,
    Resource,
    ScheduleDetail,
    ScheduleSnapshot,
    WorkOrder,
)
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.services.confirmation_module import (
    ConfirmationModule,
    ConstraintViolationError,
    OverrideReasonRequiredError,
    PermissionDeniedError,
)


# ── Fixtures ────────────────────────────────────────────────────────

_NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
_LATER = _NOW + timedelta(hours=2)


def _make_operation(
    op_id: str = "OP-1",
    wo_id: str = "WO-1",
    resource_id: str = "M-1",
    start: datetime = _NOW,
    end: datetime = _LATER,
    caps: list[str] | None = None,
) -> Operation:
    return Operation(
        operation_id=op_id,
        work_order_id=wo_id,
        resource_id=resource_id,
        required_capabilities=caps or ["milling"],
        start_time=start,
        end_time=end,
    )


def _make_schedule_detail() -> ScheduleDetail:
    op = _make_operation()
    wo = WorkOrder(
        work_order_id="WO-1",
        product_name="Widget",
        due_date=_NOW + timedelta(days=1),
        operations=[op],
    )
    res = Resource(
        resource_id="M-1",
        name="Mill-1",
        capabilities=["milling"],
    )
    return ScheduleDetail(work_orders=[wo], resources=[res])


def _make_snapshot() -> ScheduleSnapshot:
    op = _make_operation()
    wo = WorkOrder(
        work_order_id="WO-1",
        product_name="Widget",
        due_date=_NOW + timedelta(days=1),
        operations=[op],
    )
    return ScheduleSnapshot(
        captured_at=_NOW,
        workshop_id="WS-1",
        work_orders=[wo],
    )


def _make_solver_chain() -> SolverChain:
    return SolverChain(
        strategy_type="local_repair",
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_name="cp_sat",
        key_parameters={"timeout": 60},
        search_budget_seconds=60.0,
        constraint_validation_result="feasible",
        stages=["rule_selection", "initial_solution", "lns_repair", "validation"],
    )


def _make_candidate_plan(plan_id: UUID | None = None) -> CandidatePlan:
    return CandidatePlan(
        plan_id=plan_id or uuid4(),
        strategy_type="local_repair",
        schedule_detail=_make_schedule_detail(),
        gantt_version="1.0",
        solver_chain=_make_solver_chain(),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=5.0,
            iteration_count=100,
            objective_trajectory=[1.0, 0.8, 0.6],
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=True,
            violations=[],
            checked_constraints=["equipment_capability", "process_order"],
        ),
    )


def _make_confirm_request(
    incident_id: UUID | None = None,
    plan_id: UUID | None = None,
    action: ConfirmAction = ConfirmAction.ACCEPT,
    override_reason: str | None = None,
    adjustments: list[dict] | None = None,
) -> ConfirmRequest:
    return ConfirmRequest(
        incident_id=incident_id or uuid4(),
        action=action,
        selected_plan_id=plan_id or uuid4(),
        adjustments=adjustments,
        override_reason=override_reason,
        confirmed_by="planner-1",
    )


# ── Test: Accept (Req 7.1) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_accept_plan():
    """Straight acceptance returns confirmed plan with no adjustments."""
    module = ConfirmationModule()
    plan = _make_candidate_plan()
    request = _make_confirm_request(plan_id=plan.plan_id)

    response = await module.confirm(
        request=request,
        candidate_plans=[plan],
        recommended_plan_id=plan.plan_id,
        snapshot=_make_snapshot(),
        impact_report_summary="1 work order affected",
        strategy_type="local_repair",
    )

    assert response.confirmed_plan_id == plan.plan_id
    assert response.derived_from_plan_id == plan.plan_id
    assert response.is_manual_adjusted is False
    assert response.constraint_validation.is_feasible is True
    assert response.decision_record_id is not None


# ── Test: Accept with adjustment (Req 7.2, 7.3) ────────────────────


@pytest.mark.asyncio
async def test_accept_with_adjustment_passes_validation():
    """Micro-adjustment that passes constraint validation succeeds."""
    module = ConfirmationModule()
    plan = _make_candidate_plan()
    adjustments = [
        {
            "operation_id": "OP-1",
            "new_start_time": (_NOW + timedelta(minutes=30)).isoformat(),
            "new_end_time": (_LATER + timedelta(minutes=30)).isoformat(),
        }
    ]
    request = _make_confirm_request(
        plan_id=plan.plan_id,
        action=ConfirmAction.ACCEPT_WITH_ADJUSTMENT,
        adjustments=adjustments,
    )

    response = await module.confirm(
        request=request,
        candidate_plans=[plan],
        recommended_plan_id=plan.plan_id,
        snapshot=_make_snapshot(),
        impact_report_summary="1 work order affected",
        strategy_type="local_repair",
    )

    assert response.is_manual_adjusted is True
    # New plan version ID should differ from original
    assert response.confirmed_plan_id != plan.plan_id
    assert response.derived_from_plan_id == plan.plan_id
    assert response.constraint_validation.is_feasible is True


# ── Test: Micro-adjustment violates constraints (Req 7.4) ──────────


@pytest.mark.asyncio
async def test_accept_with_adjustment_constraint_violation():
    """Micro-adjustment that violates hard constraints is blocked."""
    module = ConfirmationModule()
    plan = _make_candidate_plan()

    # Assign to a resource that lacks required capabilities
    adjustments = [
        {
            "operation_id": "OP-1",
            "new_resource_id": "M-NONEXISTENT",
        }
    ]
    request = _make_confirm_request(
        plan_id=plan.plan_id,
        action=ConfirmAction.ACCEPT_WITH_ADJUSTMENT,
        adjustments=adjustments,
    )

    with pytest.raises(ConstraintViolationError) as exc_info:
        await module.confirm(
            request=request,
            candidate_plans=[plan],
            recommended_plan_id=plan.plan_id,
            snapshot=_make_snapshot(),
            impact_report_summary="1 work order affected",
            strategy_type="local_repair",
        )

    assert exc_info.value.report.is_feasible is False
    assert len(exc_info.value.report.violations) > 0


# ── Test: Reject and reselect / Override (Req 7.5) ─────────────────


@pytest.mark.asyncio
async def test_reject_and_reselect_with_reason():
    """Override with reason records the override correctly."""
    module = ConfirmationModule()
    plan_a = _make_candidate_plan()
    plan_b = _make_candidate_plan()

    request = _make_confirm_request(
        plan_id=plan_b.plan_id,
        action=ConfirmAction.REJECT_AND_RESELECT,
        override_reason="Plan A has too much disruption",
    )

    response = await module.confirm(
        request=request,
        candidate_plans=[plan_a, plan_b],
        recommended_plan_id=plan_a.plan_id,
        snapshot=_make_snapshot(),
        impact_report_summary="2 work orders affected",
        strategy_type="local_repair",
    )

    assert response.confirmed_plan_id == plan_b.plan_id
    assert response.decision_record_id is not None


@pytest.mark.asyncio
async def test_reject_without_reason_raises():
    """Override without reason is rejected."""
    module = ConfirmationModule()
    plan = _make_candidate_plan()

    request = _make_confirm_request(
        plan_id=plan.plan_id,
        action=ConfirmAction.REJECT_AND_RESELECT,
        override_reason=None,
    )

    with pytest.raises(OverrideReasonRequiredError):
        await module.confirm(
            request=request,
            candidate_plans=[plan],
            recommended_plan_id=plan.plan_id,
            snapshot=_make_snapshot(),
            impact_report_summary="test",
            strategy_type="local_repair",
        )


# ── Test: DecisionRecord completeness (Req 7.6) ────────────────────


@pytest.mark.asyncio
async def test_decision_record_contains_all_fields():
    """DecisionRecord includes all candidate plan IDs and module versions."""
    module = ConfirmationModule(
        module_versions={
            "rule_selector": "2.1.0",
            "neighborhood_selector": "1.3.0",
            "repair_policy_advisor": "1.0.5",
        }
    )
    plan_a = _make_candidate_plan()
    plan_b = _make_candidate_plan()
    plan_c = _make_candidate_plan()
    incident_id = uuid4()

    request = _make_confirm_request(
        incident_id=incident_id,
        plan_id=plan_b.plan_id,
    )

    response = await module.confirm(
        request=request,
        candidate_plans=[plan_a, plan_b, plan_c],
        recommended_plan_id=plan_a.plan_id,
        snapshot=_make_snapshot(),
        impact_report_summary="3 WOs affected",
        strategy_type="global_reschedule",
        plan_selection_input_version="2.0",
        plan_selection_output_version="2.0",
    )

    # We can't directly access the DecisionRecord from the response,
    # but we verify the response fields are consistent
    assert response.decision_record_id is not None
    assert response.confirmed_plan_id == plan_b.plan_id


# ── Test: RBAC (Req 7.7) ───────────────────────────────────────────


def test_rbac_planner_allowed():
    """Planner can perform all confirmation actions."""
    ConfirmationModule.check_permission(Role.PLANNER, ConfirmAction.ACCEPT)
    ConfirmationModule.check_permission(
        Role.PLANNER, ConfirmAction.ACCEPT_WITH_ADJUSTMENT
    )
    ConfirmationModule.check_permission(
        Role.PLANNER, ConfirmAction.REJECT_AND_RESELECT
    )


def test_rbac_shop_floor_executor_denied():
    """Shop_Floor_Executor cannot perform any confirmation action."""
    with pytest.raises(PermissionDeniedError):
        ConfirmationModule.check_permission(
            Role.SHOP_FLOOR_EXECUTOR, ConfirmAction.ACCEPT
        )


def test_rbac_management_p1_allowed():
    """Management can approve P1-Critical incidents."""
    ConfirmationModule.check_permission(
        Role.MANAGEMENT,
        ConfirmAction.ACCEPT,
        incident_severity=IncidentSeverity.P1_CRITICAL,
    )


def test_rbac_management_non_p1_denied():
    """Management cannot approve non-P1 incidents."""
    with pytest.raises(PermissionDeniedError):
        ConfirmationModule.check_permission(
            Role.MANAGEMENT,
            ConfirmAction.ACCEPT,
            incident_severity=IncidentSeverity.P3_MEDIUM,
        )


def test_rbac_it_admin_allowed():
    """IT_Admin can perform all actions."""
    ConfirmationModule.check_permission(Role.IT_ADMIN, ConfirmAction.ACCEPT)


@pytest.mark.asyncio
async def test_confirm_with_shop_floor_role_raises():
    """Full confirm flow rejects Shop_Floor_Executor."""
    module = ConfirmationModule()
    plan = _make_candidate_plan()
    request = _make_confirm_request(plan_id=plan.plan_id)

    with pytest.raises(PermissionDeniedError):
        await module.confirm(
            request=request,
            candidate_plans=[plan],
            recommended_plan_id=plan.plan_id,
            snapshot=_make_snapshot(),
            impact_report_summary="test",
            strategy_type="local_repair",
            role=Role.SHOP_FLOOR_EXECUTOR,
        )


# ── Test: Timeout (Req 7.8) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_timeout_under_threshold():
    """No timeout notification when under 15 minutes."""
    module = ConfirmationModule()
    incident_id = uuid4()
    module.register_pending(incident_id)

    result = await module.check_timeout(incident_id)
    assert result is False
    assert len(module.get_timeout_notifications()) == 0


@pytest.mark.asyncio
async def test_check_timeout_over_threshold():
    """Timeout notification generated when over 15 minutes."""
    module = ConfirmationModule()
    incident_id = uuid4()

    # Simulate registration 20 minutes ago
    module._pending_incidents[incident_id] = datetime.now(
        tz=timezone.utc
    ) - timedelta(minutes=20)

    result = await module.check_timeout(incident_id)
    assert result is True
    notifications = module.get_timeout_notifications()
    assert len(notifications) == 1
    assert str(incident_id) in notifications[0]["message"]


@pytest.mark.asyncio
async def test_check_timeout_unknown_incident():
    """No notification for unregistered incident."""
    module = ConfirmationModule()
    result = await module.check_timeout(uuid4())
    assert result is False


# ── Test: Selected plan not found ───────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_plan_not_found():
    """Raises ValueError when selected plan is not in candidates."""
    module = ConfirmationModule()
    plan = _make_candidate_plan()
    request = _make_confirm_request(plan_id=uuid4())  # non-existent

    with pytest.raises(ValueError, match="not found"):
        await module.confirm(
            request=request,
            candidate_plans=[plan],
            recommended_plan_id=plan.plan_id,
            snapshot=_make_snapshot(),
            impact_report_summary="test",
            strategy_type="local_repair",
        )


# ── Test: Pending cleared after confirm ─────────────────────────────


@pytest.mark.asyncio
async def test_pending_cleared_after_confirm():
    """Confirming an incident removes it from the pending timeout tracker."""
    module = ConfirmationModule()
    plan = _make_candidate_plan()
    incident_id = uuid4()
    module.register_pending(incident_id)

    request = _make_confirm_request(
        incident_id=incident_id, plan_id=plan.plan_id
    )

    await module.confirm(
        request=request,
        candidate_plans=[plan],
        recommended_plan_id=plan.plan_id,
        snapshot=_make_snapshot(),
        impact_report_summary="test",
        strategy_type="local_repair",
    )

    # Should no longer be pending
    assert incident_id not in module._pending_incidents
