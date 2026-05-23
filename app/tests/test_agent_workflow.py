"""Tests for the controlled Agent workflow API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.analysis import _impact_report_cache, _snapshot_store, _strategy_cache
from app.api.incidents import _incident_store
from app.api.solver import _candidate_plans_store, _plan_index, _recommendation_store
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
)
from app.models.incident import Incident
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder


@pytest.fixture(autouse=True)
def _clear_stores():
    _incident_store.clear()
    _snapshot_store.clear()
    _impact_report_cache.clear()
    _strategy_cache.clear()
    _candidate_plans_store.clear()
    _plan_index.clear()
    _recommendation_store.clear()
    yield
    _incident_store.clear()
    _snapshot_store.clear()
    _impact_report_cache.clear()
    _strategy_cache.clear()
    _candidate_plans_store.clear()
    _plan_index.clear()
    _recommendation_store.clear()


def _make_app():
    from fastapi import FastAPI

    from app.api.agents import router as agents_router

    test_app = FastAPI()
    test_app.include_router(agents_router)
    return test_app


def _seed_incident(**overrides: Any) -> Incident:
    defaults: dict[str, Any] = {
        "incident_id": uuid4(),
        "incident_type": IncidentType.EQUIPMENT_FAILURE.value,
        "occurred_at": datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc),
        "resource_id": "CNC-001",
        "report_source": ReportSource.MES.value,
        "severity": IncidentSeverity.P3_MEDIUM.value,
        "status": IncidentStatus.PENDING_ANALYSIS.value,
        "created_at": datetime.now(tz=timezone.utc),
    }
    defaults.update(overrides)
    incident = Incident(**defaults)
    _incident_store[str(incident.incident_id)] = incident
    return incident


def _seed_snapshot() -> ScheduleSnapshot:
    base_time = datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
    work_orders = [
        WorkOrder(
            work_order_id="WO-001",
            product_name="Product-A",
            due_date=datetime(2024, 6, 20, 18, 0, 0, tzinfo=timezone.utc),
            operations=[
                Operation(
                    operation_id="OP-001",
                    work_order_id="WO-001",
                    resource_id="CNC-001",
                    start_time=base_time,
                    end_time=datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
                    successor_ids=["OP-002"],
                ),
                Operation(
                    operation_id="OP-002",
                    work_order_id="WO-001",
                    resource_id="CNC-002",
                    start_time=datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
                    end_time=datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
                    predecessor_ids=["OP-001"],
                ),
            ],
            priority=3,
        ),
        WorkOrder(
            work_order_id="WO-002",
            product_name="Product-B",
            due_date=datetime(2024, 6, 21, 18, 0, 0, tzinfo=timezone.utc),
            operations=[
                Operation(
                    operation_id="OP-003",
                    work_order_id="WO-002",
                    resource_id="CNC-003",
                    start_time=datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc),
                    end_time=datetime(2024, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
                ),
            ],
            priority=1,
        ),
        WorkOrder(
            work_order_id="WO-003",
            product_name="Product-C",
            due_date=datetime(2024, 6, 22, 18, 0, 0, tzinfo=timezone.utc),
            operations=[
                Operation(
                    operation_id="OP-004",
                    work_order_id="WO-003",
                    resource_id="CNC-004",
                    start_time=datetime(2024, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
                    end_time=datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
                ),
            ],
            priority=0,
        ),
    ]
    snapshot = ScheduleSnapshot(
        snapshot_id=uuid4(),
        captured_at=datetime(2024, 6, 15, 7, 55, 0, tzinfo=timezone.utc),
        workshop_id="WS-01",
        source_system="aps",
        work_orders=work_orders,
    )
    _snapshot_store[str(snapshot.snapshot_id)] = snapshot
    return snapshot


@pytest.mark.asyncio
async def test_incident_agent_understands_machine_down_text():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/incident/understand",
            json={
                "text": "CNC-02 停了，估计要修三个小时，几个急单可能受影响。",
                "workshop_id": "WS-01",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["incident_type"] == "machine_down"
    assert data["resource_id"] == "CNC-02"
    assert data["estimated_duration_minutes"] == 180
    assert data["risk_hint"] == "urgent_order_delay"
    assert data["supported_by_solver"] is True
    assert data["requires_human_confirmation"] is False
    assert data["incident_create_request"]["incident_type"] == "equipment_failure"


@pytest.mark.asyncio
async def test_incident_agent_routes_unsupported_low_context_to_confirmation():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/incident/understand",
            json={"text": "物料还没到"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["incident_type"] == "material_shortage"
    assert data["supported_by_solver"] is False
    assert data["requires_human_confirmation"] is True
    assert data["incident_create_request"] is None


@pytest.mark.asyncio
async def test_agent_decision_flow_runs_tools_without_auto_writeback():
    incident = _seed_incident()
    _seed_snapshot()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/decision-flow",
            json={
                "incident_id": str(incident.incident_id),
                "estimated_repair_time_minutes": 60,
                "goal_mode": "balanced",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["impact_report"]["incident_id"] == str(incident.incident_id)
    assert data["strategy"]["strategy_type"] in {
        "wait_and_repair",
        "local_repair",
        "global_reschedule",
    }
    assert len(data["candidate_plans"]) >= 1
    assert len(data["quality_gates"]) == len(data["candidate_plans"])
    assert data["quality_gates"][0]["plan_id"] == data["candidate_plans"][0]["plan_id"]
    assert "recommendation_policy" in data["quality_gates"][0]
    assert data["comparison_matrix"] is not None
    assert data["recommendation"] is not None
    assert data["requires_human_confirmation"] is True

    trace_names = [step["agent_name"] for step in data["trace"]]
    assert "Impact Analysis Agent" in trace_names
    assert "Strategy Agent" in trace_names
    assert "Solver Tool / Solver Agent" in trace_names
    assert "Quality Gate Agent" in trace_names
    assert "Evaluation Agent" in trace_names
    assert "Confirmation Agent" in trace_names


@pytest.mark.asyncio
async def test_feedback_agent_structures_operator_override():
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/agents/feedback/structure",
            json={"override_text": "M4 operator unavailable after 16:00"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["override_reason"] == "operator_preference"
    assert "M4" in data["future_rule_candidate"]
    assert "16:00" in data["future_rule_candidate"]
    assert data["requires_human_review"] is False
