"""Tests for the Impact Analysis & Strategy Selector API endpoints.

Validates: Requirements 2.6, 3.7, 18.4

Tests:
- POST /api/v1/schedule-snapshots — import snapshot
- GET  /api/v1/incidents/{incident_id}/impact-report — query impact report
- GET  /api/v1/incidents/{incident_id}/strategy — query strategy recommendation
- 404 handling for missing incidents
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
    """Clear all in-memory stores before each test."""
    _incident_store.clear()
    _snapshot_store.clear()
    _impact_report_cache.clear()
    _strategy_cache.clear()
    yield
    _incident_store.clear()
    _snapshot_store.clear()
    _impact_report_cache.clear()
    _strategy_cache.clear()


def _make_app():
    """Build a minimal FastAPI app for testing without Redis dependency."""
    from fastapi import FastAPI

    from app.api.analysis import router as analysis_router
    from app.api.incidents import router as incidents_router

    test_app = FastAPI()
    test_app.include_router(incidents_router)
    test_app.include_router(analysis_router)
    return test_app


def _seed_incident(**overrides: Any) -> Incident:
    """Create and store an Incident directly in the in-memory store."""
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
    """Create and store a ScheduleSnapshot in the in-memory store."""
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


# ---------------------------------------------------------------------------
# POST /api/v1/schedule-snapshots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_schedule_snapshot():
    """POST should store a snapshot and return 201."""
    app = _make_app()
    snapshot_id = str(uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/schedule-snapshots",
            json={
                "snapshot_id": snapshot_id,
                "captured_at": "2024-06-15T07:55:00Z",
                "workshop_id": "WS-01",
                "work_orders": [],
            },
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["snapshot_id"] == snapshot_id
    assert data["workshop_id"] == "WS-01"
    assert snapshot_id in _snapshot_store


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/impact-report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_impact_report_success():
    """GET impact-report should return analysis result for a valid incident."""
    incident = _seed_incident()
    _seed_snapshot()

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/impact-report"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["incident_id"] == str(incident.incident_id)
    assert "affected_work_orders" in data
    assert "delivery_risk_distribution" in data


@pytest.mark.asyncio
async def test_get_impact_report_cached():
    """GET impact-report should return cached result on second call."""
    incident = _seed_incident()
    _seed_snapshot()

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp1 = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/impact-report"
        )
        resp2 = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/impact-report"
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()


@pytest.mark.asyncio
async def test_get_impact_report_incident_not_found():
    """GET impact-report should return 404 for unknown incident."""
    app = _make_app()
    fake_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/incidents/{fake_id}/impact-report"
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_impact_report_degraded_mode():
    """GET impact-report should return degraded mode when no snapshot exists."""
    incident = _seed_incident()
    # No snapshot seeded

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/impact-report"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_degraded_mode"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}/strategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_strategy_success():
    """GET strategy should return a recommendation for a valid incident."""
    incident = _seed_incident()
    _seed_snapshot()

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/strategy"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "strategy_type" in data
    assert "confidence" in data
    assert "reasoning" in data
    assert data["strategy_type"] in [
        "wait_and_repair",
        "local_repair",
        "global_reschedule",
    ]


@pytest.mark.asyncio
async def test_get_strategy_with_custom_repair_time():
    """GET strategy should accept estimated_repair_time_minutes query param."""
    incident = _seed_incident()
    _seed_snapshot()

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/strategy",
            params={"estimated_repair_time_minutes": 5.0},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "strategy_type" in data


@pytest.mark.asyncio
async def test_get_strategy_incident_not_found():
    """GET strategy should return 404 for unknown incident."""
    app = _make_app()
    fake_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/v1/incidents/{fake_id}/strategy"
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_strategy_cached():
    """GET strategy should return cached result on second call."""
    incident = _seed_incident()
    _seed_snapshot()

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp1 = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/strategy"
        )
        resp2 = await client.get(
            f"/api/v1/incidents/{incident.incident_id}/strategy"
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()
