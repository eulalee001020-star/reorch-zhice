"""Tests for the Layer 3 Solver API endpoints.

Validates: Requirements 27.1, 27.5, 29.1, 30.6, 30.8

Tests:
- POST /api/v1/incidents/{incident_id}/solve — trigger solving
- GET  /api/v1/incidents/{incident_id}/candidate-plans — list candidate plans
- GET  /api/v1/candidate-plans/{plan_id} — plan detail
- GET  /api/v1/candidate-plans/{plan_id}/gantt — gantt data
- POST /api/v1/incidents/{incident_id}/recommend — trigger recommendation
- GET  /api/v1/incidents/{incident_id}/recommendation — query recommendation
- 404 handling for missing data
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.analysis import (
    _impact_report_cache,
    _snapshot_store,
    _strategy_cache,
)
from app.api.incidents import _incident_store
from app.api.solver import (
    _candidate_plans_store,
    _plan_index,
    _recommendation_store,
)
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
    StrategyType,
)
from app.models.impact import AffectedOperation, AffectedWorkOrder, ImpactReport
from app.models.incident import Incident
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.models.strategy import StrategyRecommendation


@pytest.fixture(autouse=True)
def _clear_stores():
    """Clear all in-memory stores before each test."""
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
    """Build a minimal FastAPI app for testing without Redis dependency."""
    from fastapi import FastAPI

    from app.api.analysis import router as analysis_router
    from app.api.incidents import router as incidents_router
    from app.api.solver import router as solver_router

    test_app = FastAPI()
    test_app.include_router(incidents_router)
    test_app.include_router(analysis_router)
    test_app.include_router(solver_router)
    return test_app


def _seed_incident(**overrides: Any) -> Incident:
    """Create and store an Incident in the in-memory store."""
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


def _seed_snapshot(**overrides: Any) -> ScheduleSnapshot:
    """Create and store a ScheduleSnapshot."""
    defaults: dict[str, Any] = {
        "snapshot_id": uuid4(),
        "captured_at": datetime(2024, 6, 15, 7, 55, 0, tzinfo=timezone.utc),
        "workshop_id": "WS-01",
        "work_orders": [
            WorkOrder(
                work_order_id="WO-001",
                product_name="Product-A",
                due_date=datetime(2024, 6, 20, 18, 0, 0, tzinfo=timezone.utc),
                operations=[
                    Operation(
                        operation_id="OP-001",
                        work_order_id="WO-001",
                        resource_id="CNC-001",
                        start_time=datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc),
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
                priority=1,
            ),
        ],
    }
    defaults.update(overrides)
    snapshot = ScheduleSnapshot(**defaults)
    _snapshot_store[str(snapshot.snapshot_id)] = snapshot
    return snapshot


def _seed_impact_report(incident_id: str, snapshot_id: str) -> ImpactReport:
    """Create and cache an ImpactReport."""
    report = ImpactReport(
        incident_id=incident_id,
        schedule_snapshot_id=snapshot_id,
        analysis_reference_time=datetime(2024, 6, 15, 7, 55, 0, tzinfo=timezone.utc),
        affected_work_orders=[
            AffectedWorkOrder(
                work_order_id="WO-001",
                product_name="Product-A",
                due_date=datetime(2024, 6, 20, 18, 0, 0, tzinfo=timezone.utc),
                delivery_risk_level="warning",
                remaining_buffer_minutes=120.0,
                affected_operations=[
                    AffectedOperation(
                        operation_id="OP-001",
                        work_order_id="WO-001",
                        resource_id="CNC-001",
                        is_direct=True,
                        estimated_delay_minutes=30.0,
                    ),
                ],
            ),
        ],
        affected_operations=[
            AffectedOperation(
                operation_id="OP-001",
                work_order_id="WO-001",
                resource_id="CNC-001",
                is_direct=True,
                estimated_delay_minutes=30.0,
            ),
        ],
        affected_resource_ids=["CNC-001"],
        delivery_risk_distribution={"safe": 0, "warning": 1, "breach": 0},
        estimated_total_delay_minutes=30.0,
    )
    _impact_report_cache[incident_id] = report
    return report


def _seed_strategy(incident_id: str) -> StrategyRecommendation:
    """Create and cache a StrategyRecommendation."""
    strategy = StrategyRecommendation(
        strategy_type=StrategyType.LOCAL_REPAIR.value,
        confidence=0.85,
        key_factors=["affected_ratio_low", "no_breach_risk"],
        historical_case_ids=[],
        reasoning="局部修复：受影响工单比例低且无 Breach 风险",
    )
    _strategy_cache[incident_id] = strategy
    return strategy


def _seed_full_context():
    """Seed incident + snapshot + impact report + strategy for solve tests."""
    incident = _seed_incident()
    snapshot = _seed_snapshot()
    key = str(incident.incident_id)
    _seed_impact_report(key, str(snapshot.snapshot_id))
    _seed_strategy(key)
    return incident, snapshot


# ---------------------------------------------------------------------------
# POST /api/v1/incidents/{incident_id}/solve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solve_incident_success():
    """POST /solve should return candidate plans for a valid incident."""
    incident, snapshot = _seed_full_context()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/incidents/{incident.incident_id}/solve",
            json={},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Each plan should have key fields
    for plan in data:
        assert "plan_id" in plan
        assert "strategy_type" in plan
        assert "schedule_detail" in plan
        assert "solver_chain" in plan
        assert "feasibility_status" in plan


@pytest.mark.asyncio
async def test_solve_incident_not_found():
    """POST /solve should return 404 for unknown incident."""
    app = _make_app()
    fake_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/incidents/{fake_id}/solve",
            json={},
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_solve_missing_impact_report():
    """POST /solve should return 404 when impact report is missing."""
    incident = _seed_incident()
    _seed_snapshot()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/incidents/{incident.incident_id}/solve",
            json={},
        )

    assert resp.status_code == 404
    assert "impact report" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_solve_missing_strategy():
    """POST /solve should return 404 when strategy is missing."""
    incident = _seed_incident()
    snapshot = _seed_snapshot()
    _seed_impact_report(str(incident.incident_id), str(snapshot.snapshot_id))
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/incidents/{incident.incident_id}/solve",
            json={},
        )

    assert resp.status_code == 404
    assert "strategy" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/candidate-plans
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_candidate_plans_success():
    """GET /candidate-plans should return plans after solve."""
    incident, _ = _seed_full_context()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # First solve
        await client.post(
            f"/api/v1/incidents/{incident.incident_id}/solve",
            json={},
        )
        # Then list
        resp = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/candidate-plans"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_list_candidate_plans_not_found():
    """GET /candidate-plans should return 404 when no plans exist."""
    app = _make_app()
    fake_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/incidents/{fake_id}/candidate-plans"
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/candidate-plans/{plan_id} — plan detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_candidate_plan_detail():
    """GET /candidate-plans/{plan_id} should return plan with ScheduleDetail and SolverChain."""
    incident, _ = _seed_full_context()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        solve_resp = await client.post(
            f"/api/v1/incidents/{incident.incident_id}/solve",
            json={},
        )
        plans = solve_resp.json()
        plan_id = plans[0]["plan_id"]

        resp = await client.get(f"/api/v1/candidate-plans/{plan_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_id"] == plan_id
    assert "schedule_detail" in data
    assert "solver_chain" in data
    assert "work_orders" in data["schedule_detail"]


@pytest.mark.asyncio
async def test_get_candidate_plan_not_found():
    """GET /candidate-plans/{plan_id} should return 404 for unknown plan."""
    app = _make_app()
    fake_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/candidate-plans/{fake_id}")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/candidate-plans/{plan_id}/gantt — gantt data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_candidate_plan_gantt():
    """GET /candidate-plans/{plan_id}/gantt should return gantt data."""
    incident, _ = _seed_full_context()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        solve_resp = await client.post(
            f"/api/v1/incidents/{incident.incident_id}/solve",
            json={},
        )
        plans = solve_resp.json()
        plan_id = plans[0]["plan_id"]

        resp = await client.get(f"/api/v1/candidate-plans/{plan_id}/gantt")

    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_id"] == plan_id
    assert "schedule_detail" in data
    assert "gantt_version" in data
    assert "solver_chain" in data


@pytest.mark.asyncio
async def test_get_candidate_plan_gantt_not_found():
    """GET /candidate-plans/{plan_id}/gantt should return 404 for unknown plan."""
    app = _make_app()
    fake_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/candidate-plans/{fake_id}/gantt")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/incidents/{incident_id}/recommend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_plan_success():
    """POST /recommend should return PlanSelectionOutput after solve."""
    incident, _ = _seed_full_context()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # First solve
        await client.post(
            f"/api/v1/incidents/{incident.incident_id}/solve",
            json={},
        )
        # Then recommend
        resp = await client.post(
            f"/api/v1/incidents/{incident.incident_id}/recommend",
            json={"goal_mode": "balanced"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "recommended_plan_id" in data
    assert "recommendation_confidence" in data
    assert "auto_preselected" in data
    assert "comparison_matrix" in data
    assert "gantt_diff_payload" in data
    assert "alternative_plan_ids" in data


@pytest.mark.asyncio
async def test_recommend_with_manual_weights():
    """POST /recommend should accept manual_weights parameter."""
    incident, _ = _seed_full_context()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            f"/api/v1/incidents/{incident.incident_id}/solve",
            json={},
        )
        resp = await client.post(
            f"/api/v1/incidents/{incident.incident_id}/recommend",
            json={
                "goal_mode": "delivery_priority",
                "manual_weights": {"delivery": 0.5, "stability": 0.3, "cost": 0.2},
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["goal_mode_used"] == "delivery_priority"


@pytest.mark.asyncio
async def test_recommend_no_candidates():
    """POST /recommend should return 404 when no candidates exist."""
    incident = _seed_incident()
    _seed_snapshot()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/incidents/{incident.incident_id}/recommend",
            json={},
        )

    assert resp.status_code == 404
    assert "candidate plans" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_recommend_incident_not_found():
    """POST /recommend should return 404 for unknown incident."""
    app = _make_app()
    fake_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/incidents/{fake_id}/recommend",
            json={},
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/recommendation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recommendation_success():
    """GET /recommendation should return cached PlanSelectionOutput."""
    incident, _ = _seed_full_context()
    app = _make_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            f"/api/v1/incidents/{incident.incident_id}/solve",
            json={},
        )
        await client.post(
            f"/api/v1/incidents/{incident.incident_id}/recommend",
            json={},
        )
        resp = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/recommendation"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "recommended_plan_id" in data
    assert "recommendation_confidence" in data


@pytest.mark.asyncio
async def test_get_recommendation_not_found():
    """GET /recommendation should return 404 when no recommendation exists."""
    app = _make_app()
    fake_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/incidents/{fake_id}/recommendation"
        )

    assert resp.status_code == 404
