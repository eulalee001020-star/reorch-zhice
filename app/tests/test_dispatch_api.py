"""Dispatch planner and API: release times follow production, and the
delivery outcome of each recovery plan is reported next to the original."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio

from app.main import app
from app.models.dispatch import DispatchSnapshot, DispatchStop, DispatchVehicle
from app.services.dispatch.planner import build_problem, plan_dispatch
from app.services.validation.local_demo import reset_in_memory_state, walk, walk_material

T0 = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def _snapshot() -> DispatchSnapshot:
    return DispatchSnapshot(
        captured_at=T0,
        speed_kmh=60,
        stops=[
            DispatchStop(
                shipment_id="S1",
                work_order_id="WO-1",
                customer="甲",
                x_km=30,
                y_km=0,
                demand=2,
                window_start=at(1),
                window_end=at(3),
            ),
            DispatchStop(
                shipment_id="S2",
                customer="乙",
                x_km=0,
                y_km=30,
                demand=2,
                window_start=at(0),
                window_end=at(8),
            ),
        ],
        vehicles=[DispatchVehicle(vehicle_id="V1", capacity=5, shift_start=T0, shift_end=at(10))],
    )


@pytest.fixture(autouse=True)
def _isolated_state():
    reset_in_memory_state()
    yield
    reset_in_memory_state()


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://dispatch",
        headers={"X-API-Key": "planner-key-001"},
        timeout=300,
    ) as http:
        yield http


# ── planner ─────────────────────────────────────────────────────────


def test_release_follows_work_order_completion() -> None:
    problem = build_problem(_snapshot(), {"WO-1": at(2), "WO-unrelated": at(9)})
    assert [node.release for node in problem.nodes] == [120.0, 0.0]


def test_on_time_when_production_is_on_time() -> None:
    plan = plan_dispatch(_snapshot(), {"WO-1": at(0.5)}, label="原计划", iterations=200)
    assert plan.late_stop_count == 0
    assert plan.unserved_shipment_ids == []
    assert plan.on_time_rate == 1.0
    assert plan.vehicles_used == 1


def test_late_production_makes_the_delivery_late_by_the_same_amount() -> None:
    """S1 is 30 minutes away and its window closes at hour 3. Released at
    hour 4 it arrives at 4:30, which is 90 minutes late."""
    plan = plan_dispatch(_snapshot(), {"WO-1": at(4)}, label="只顺延", iterations=200)
    late = [stop for route in plan.routes for stop in route.stops if stop.late_minutes > 0]
    assert [stop.shipment_id for stop in late] == ["S1"]
    assert late[0].late_minutes == 90
    assert plan.late_stop_count == 1
    assert plan.on_time_rate == 0.5


def test_plan_reports_wall_clock_times() -> None:
    plan = plan_dispatch(_snapshot(), {"WO-1": at(0)}, label="x", iterations=200)
    route = plan.routes[0]
    assert route.depart_at >= T0
    assert route.return_at > route.depart_at
    assert all(stop.arrival <= stop.service_start <= stop.departure for stop in route.stops)


# ── API ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_needs_a_dispatch_snapshot(client) -> None:
    response = await client.get("/api/v1/dispatch/plan")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_shipment_ids_are_rejected(client) -> None:
    body = _snapshot().model_dump(mode="json")
    body["stops"][1]["shipment_id"] = "S1"
    response = await client.post("/api/v1/dispatch/snapshots", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_window_that_ends_before_it_starts_is_rejected(client) -> None:
    body = _snapshot().model_dump(mode="json")
    body["stops"][0]["window_end"] = at(0).isoformat()
    response = await client.post("/api/v1/dispatch/snapshots", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_equipment_replan_keeps_deliveries_that_waiting_would_miss(client) -> None:
    result = await walk(client)
    plans = {plan["label"]: plan for plan in result.dispatch_plans}
    assert plans["原计划"]["late_stop_count"] == 0
    assert plans["只顺延不调整"]["late_stop_count"] >= 1
    recommended = next(plan for plan in result.dispatch_plans if plan["is_recommended"])
    assert recommended["late_stop_count"] == 0
    assert recommended["unserved_shipment_ids"] == []
    assert any(line.startswith("发运影响") for line in result.lines())


@pytest.mark.asyncio
async def test_material_wait_leaves_a_shipment_at_the_dock(client) -> None:
    result = await walk_material(client)
    plans = {plan["label"]: plan for plan in result.dispatch_plans}
    assert plans["重排·等待到货"]["unserved_shipment_ids"] == ["SH-006"]
    assert plans["重排·使用已批准替代料"]["unserved_shipment_ids"] == []
    assert plans["重排·使用已批准替代料"]["is_recommended"]


@pytest.mark.asyncio
async def test_dispatch_impact_needs_candidate_plans(client) -> None:
    await client.post("/api/v1/dispatch/snapshots", json=_snapshot().model_dump(mode="json"))
    from app.services.validation.local_demo import seed

    incident_id = await seed(client)
    response = await client.get(f"/api/v1/incidents/{incident_id}/dispatch-impact")
    assert response.status_code == 404
