"""Tests for WritebackModule service.

Covers:
- writeback_to_mes() with all success, partial failure, total failure
- Writeback status recording (success / partial_success / failed)
- track_execution() with deviation alerting
- ExecutionResult generation and DecisionRecord linking

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.models.decision import DecisionRecord
from app.models.enums import WritebackStatus
from app.models.schedule import (
    Operation,
    Resource,
    ScheduleDetail,
    WorkOrder,
)
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.services.writeback_module import (
    MESAdapter,
    WritebackModule,
)


# ── Fixtures ────────────────────────────────────────────────────────

_NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
_LATER = _NOW + timedelta(hours=2)


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
    op = Operation(
        operation_id="OP-1",
        work_order_id="WO-1",
        resource_id="M-1",
        required_capabilities=["milling"],
        start_time=_NOW,
        end_time=_LATER,
    )
    wo = WorkOrder(
        work_order_id="WO-1",
        product_name="Widget",
        due_date=_NOW + timedelta(days=1),
        operations=[op],
    )
    res = Resource(resource_id="M-1", name="Mill-1", capabilities=["milling"])
    schedule = ScheduleDetail(work_orders=[wo], resources=[res])

    return CandidatePlan(
        plan_id=plan_id or uuid4(),
        strategy_type="local_repair",
        schedule_detail=schedule,
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
            checked_constraints=["equipment_capability"],
        ),
    )


def _make_decision_record(
    incident_id: UUID | None = None,
    plan_id: UUID | None = None,
) -> DecisionRecord:
    iid = incident_id or uuid4()
    pid = plan_id or uuid4()
    return DecisionRecord(
        decision_record_id=uuid4(),
        incident_id=iid,
        impact_report_summary="1 work order affected",
        strategy_type="local_repair",
        all_candidate_plan_ids=[pid],
        recommended_plan_id=pid,
        confirmed_plan_id=pid,
        derived_from_plan_id=pid,
        is_override=False,
        is_manual_adjusted=False,
        confirmed_by="planner-1",
        confirmed_at=_NOW,
        plan_selection_input_version="1.0",
        plan_selection_output_version="1.0",
        solver_chain=_make_solver_chain(),
        rule_selector_version="1.0.0",
        neighborhood_selector_version="1.0.0",
        repair_policy_advisor_version="1.0.0",
    )


# ── Test: Writeback all success (Req 8.1, 8.3) ────────────────────


@pytest.mark.asyncio
async def test_writeback_all_success():
    """All MES instructions succeed → status = success."""
    module = WritebackModule()
    plan = _make_candidate_plan()
    record = _make_decision_record(plan_id=plan.plan_id)

    status = await module.writeback_to_mes(plan, record)

    assert status == WritebackStatus.SUCCESS
    assert module.get_writeback_status(record.incident_id) == WritebackStatus.SUCCESS
    report = module.get_writeback_report(record.incident_id)
    assert report is not None
    assert report.total_instructions == 1
    assert report.success_count == 1
    assert report.failed_count == 0


# ── Test: Writeback partial failure (Req 8.4) ─────────────────────


@pytest.mark.asyncio
async def test_writeback_partial_failure():
    """Some instructions fail → status = partial_success."""
    # Create plan with 2 operations
    op1 = Operation(
        operation_id="OP-1",
        work_order_id="WO-1",
        resource_id="M-1",
        required_capabilities=["milling"],
        start_time=_NOW,
        end_time=_LATER,
    )
    op2 = Operation(
        operation_id="OP-2",
        work_order_id="WO-1",
        resource_id="M-2",
        required_capabilities=["turning"],
        start_time=_LATER,
        end_time=_LATER + timedelta(hours=1),
    )
    wo = WorkOrder(
        work_order_id="WO-1",
        product_name="Widget",
        due_date=_NOW + timedelta(days=1),
        operations=[op1, op2],
    )
    schedule = ScheduleDetail(
        work_orders=[wo],
        resources=[
            Resource(resource_id="M-1", name="Mill-1", capabilities=["milling"]),
            Resource(resource_id="M-2", name="Lathe-1", capabilities=["turning"]),
        ],
    )
    plan = CandidatePlan(
        plan_id=uuid4(),
        strategy_type="local_repair",
        schedule_detail=schedule,
        gantt_version="1.0",
        solver_chain=_make_solver_chain(),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=5.0, iteration_count=100
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=True, violations=[], checked_constraints=[]
        ),
    )

    # Configure MES adapter to fail one instruction
    adapter = MESAdapter()
    adapter.set_fail_ids({"MES-OP-2"})
    module = WritebackModule(mes_adapter=adapter)
    record = _make_decision_record(plan_id=plan.plan_id)

    status = await module.writeback_to_mes(plan, record)

    assert status == WritebackStatus.PARTIAL_SUCCESS
    report = module.get_writeback_report(record.incident_id)
    assert report is not None
    assert report.total_instructions == 2
    assert report.success_count == 1
    assert report.failed_count == 1
    assert len(report.failed_instructions) == 1
    assert report.failed_instructions[0]["operation_id"] == "OP-2"


# ── Test: Writeback total failure (Req 8.3) ────────────────────────


@pytest.mark.asyncio
async def test_writeback_total_failure():
    """All instructions fail → status = failed."""
    adapter = MESAdapter()
    adapter.set_fail_ids({"MES-OP-1"})
    module = WritebackModule(mes_adapter=adapter)
    plan = _make_candidate_plan()
    record = _make_decision_record(plan_id=plan.plan_id)

    status = await module.writeback_to_mes(plan, record)

    assert status == WritebackStatus.FAILED
    report = module.get_writeback_report(record.incident_id)
    assert report is not None
    assert report.failed_count == 1
    assert report.success_count == 0


# ── Test: Empty plan writeback ─────────────────────────────────────


@pytest.mark.asyncio
async def test_writeback_empty_plan():
    """Plan with no operations → status = success (nothing to write)."""
    module = WritebackModule()
    schedule = ScheduleDetail(work_orders=[], resources=[])
    plan = CandidatePlan(
        plan_id=uuid4(),
        strategy_type="local_repair",
        schedule_detail=schedule,
        gantt_version="1.0",
        solver_chain=_make_solver_chain(),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=1.0, iteration_count=10
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=True, violations=[], checked_constraints=[]
        ),
    )
    record = _make_decision_record(plan_id=plan.plan_id)

    status = await module.writeback_to_mes(plan, record)
    assert status == WritebackStatus.SUCCESS


# ── Test: Track execution (Req 8.5, 8.7, 8.8) ────────────────────


@pytest.mark.asyncio
async def test_track_execution_generates_result():
    """track_execution generates ExecutionResult linked to DecisionRecord."""
    module = WritebackModule()
    plan = _make_candidate_plan()
    incident_id = uuid4()
    record = _make_decision_record(
        incident_id=incident_id, plan_id=plan.plan_id
    )

    # First writeback
    await module.writeback_to_mes(plan, record)

    # Then track
    result = await module.track_execution(incident_id)

    assert result.incident_id == incident_id
    assert result.decision_record_id == record.decision_record_id
    assert result.actual_otd >= 0.0
    assert result.deviation_percentage >= 0.0

    # Verify stored
    stored = module.get_execution_result(incident_id)
    assert stored is not None
    assert stored.incident_id == incident_id


# ── Test: Track execution without decision record ──────────────────


@pytest.mark.asyncio
async def test_track_execution_no_record_raises():
    """track_execution raises ValueError if no decision record exists."""
    module = WritebackModule()

    with pytest.raises(ValueError, match="No decision record"):
        await module.track_execution(uuid4())


# ── Test: Writeback status query ───────────────────────────────────


@pytest.mark.asyncio
async def test_get_writeback_status_none():
    """Returns None for unknown incident."""
    module = WritebackModule()
    assert module.get_writeback_status(uuid4()) is None


@pytest.mark.asyncio
async def test_get_execution_result_none():
    """Returns None for unknown incident."""
    module = WritebackModule()
    assert module.get_execution_result(uuid4()) is None
