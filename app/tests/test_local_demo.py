"""The dependency-free demo path must keep working end to end.

Besides walking the loop, these tests check the physical facts a recovery
plan has to respect. A plan that schedules work on a machine while it is down,
rewrites work that already happened, or starts an operation before its
material is usable is wrong no matter how good its score looks.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio

from app.main import app
from app.services.validation.local_demo import reset_in_memory_state, walk, walk_material


@pytest.fixture(autouse=True)
def _isolated_state():
    reset_in_memory_state()
    yield
    reset_in_memory_state()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://local-demo",
        headers={"X-API-Key": "planner-key-001"},
        timeout=300,
    ) as http:
        yield http


def _stored(incident_id: str):
    from app.api.analysis import _snapshot_store
    from app.api.incidents import _incident_store
    from app.api.solver import _candidate_plans_store

    snapshot = next(iter(_snapshot_store.values()))
    return _incident_store[incident_id], snapshot, _candidate_plans_store[incident_id]


def _assert_history_untouched(snapshot, plans, decision_time: datetime) -> None:
    original = {op.operation_id: op for wo in snapshot.work_orders for op in wo.operations}
    for plan in plans:
        for work_order in plan.schedule_detail.work_orders:
            for operation in work_order.operations:
                before = original[operation.operation_id]
                if before.end_time <= decision_time:
                    assert operation.start_time == before.start_time, operation.operation_id
                    assert operation.resource_id == before.resource_id, operation.operation_id
                elif operation.start_time != before.start_time:
                    assert operation.start_time >= decision_time, operation.operation_id


@pytest.mark.asyncio
async def test_equipment_scenario_respects_the_outage(client) -> None:
    result = await walk(client)
    incident, snapshot, plans = _stored(result.incident_id)

    assert result.violations == 0
    assert result.checked_constraints
    assert result.decision_record_id
    assert all(plan.feasibility_status == "feasible" for plan in plans)

    down_from = incident.occurred_at
    down_until = down_from + timedelta(minutes=240)
    for plan in plans:
        for work_order in plan.schedule_detail.work_orders:
            for operation in work_order.operations:
                if operation.resource_id != incident.resource_id:
                    continue
                overlaps = operation.start_time < down_until and operation.end_time > down_from
                assert not overlaps, f"{operation.operation_id} runs on the failed machine"
    _assert_history_untouched(snapshot, plans, down_from)


@pytest.mark.asyncio
async def test_equipment_replan_beats_waiting(client) -> None:
    result = await walk(client)
    assert result.strategy_type == "global_reschedule"
    assert result.risk_distribution["breach"] >= 1
    baseline = result.baseline
    assert baseline is not None and baseline.delayed_orders >= 1
    assert not result.recommended.is_baseline
    assert result.recommended.delayed_orders < baseline.delayed_orders


@pytest.mark.asyncio
async def test_material_scenario_offers_wait_and_substitute(client) -> None:
    result = await walk_material(client)
    incident, snapshot, plans = _stored(result.incident_id)

    options = {c.material_option for c in result.candidates if not c.is_baseline}
    assert options == {"wait_for_supply", "approved_substitute"}
    assert result.recommended.material_option == "approved_substitute"
    assert result.recommended.delayed_orders == 0
    assert result.baseline is not None and result.baseline.delayed_orders >= 1
    assert result.violations == 0
    assert len(result.supply_summary) == 2
    _assert_history_untouched(snapshot, plans, incident.occurred_at)


@pytest.mark.asyncio
async def test_material_wait_plan_does_not_start_before_the_new_arrival(client) -> None:
    result = await walk_material(client)
    _incident, _snapshot, plans = _stored(result.incident_id)
    # New promise 2026-05-15 09:00 plus 60 minutes of incoming inspection.
    usable_at = datetime.fromisoformat("2026-05-15T10:00:00+08:00")
    waiting = [
        plan
        for plan in plans
        if plan.solver_chain.key_parameters.get("material_option") == "wait_for_supply"
    ]
    assert waiting
    for plan in waiting:
        assembly = next(
            operation
            for work_order in plan.schedule_detail.work_orders
            for operation in work_order.operations
            if operation.operation_id == "OP-DEMO-006-30"
        )
        assert assembly.start_time >= usable_at
