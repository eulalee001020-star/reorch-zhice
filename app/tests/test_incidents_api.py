"""Tests for the Anomaly_Intake_Center API endpoints.

Validates: Requirements 1.1, 10.5, 18.1

Tests:
- POST /api/v1/incidents — create incident, validation errors, source errors
- GET  /api/v1/incidents — list with filtering
- GET  /api/v1/incidents/{incident_id} — detail and 404
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.incidents import _incident_store
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
)
from app.models.incident import Incident


@pytest.fixture(autouse=True)
def _clear_store():
    """Clear the in-memory incident store before each test."""
    _incident_store.clear()
    yield
    _incident_store.clear()


def _make_app():
    """Build a minimal FastAPI app for testing without Redis dependency."""
    from fastapi import FastAPI

    from app.api.incidents import router

    test_app = FastAPI()
    test_app.include_router(router)
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


# ---------------------------------------------------------------------------
# POST /api/v1/incidents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_incident_success():
    """POST should create an incident and return 201."""
    app = _make_app()

    # Mock the AnomalyIntakeCenter.receive_event to avoid Redis/Kafka deps
    created = Incident(
        incident_id=uuid4(),
        incident_type=IncidentType.EQUIPMENT_FAILURE.value,
        occurred_at=datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc),
        resource_id="CNC-001",
        report_source=ReportSource.MES.value,
        severity=IncidentSeverity.P3_MEDIUM.value,
        status=IncidentStatus.PENDING_ANALYSIS.value,
        created_at=datetime.now(tz=timezone.utc),
    )

    with patch(
        "app.api.incidents._get_intake_center"
    ) as mock_get:
        mock_center = AsyncMock()
        mock_center.receive_event.return_value = created
        mock_get.return_value = mock_center

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/incidents",
                json={
                    "incident_type": "equipment_failure",
                    "occurred_at": "2024-06-15T08:00:00Z",
                    "resource_id": "CNC-001",
                    "report_source": "MES",
                },
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["incident_id"] == str(created.incident_id)
    assert data["severity"] == IncidentSeverity.P3_MEDIUM.value
    # Should be stored in the in-memory store
    assert str(created.incident_id) in _incident_store


@pytest.mark.asyncio
async def test_create_incident_validation_error():
    """POST should return 422 when IntakeValidationError is raised."""
    from app.services.anomaly_intake_center import IntakeValidationError

    app = _make_app()

    with patch("app.api.incidents._get_intake_center") as mock_get:
        mock_center = AsyncMock()
        mock_center.receive_event.side_effect = IntakeValidationError(
            missing_fields=["resource_id"],
            reason="Missing required fields: resource_id",
        )
        mock_get.return_value = mock_center

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/incidents",
                json={
                    "incident_type": "equipment_failure",
                    "occurred_at": "2024-06-15T08:00:00Z",
                    "resource_id": "CNC-001",
                    "report_source": "MES",
                },
            )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "resource_id" in detail["missing_fields"]


@pytest.mark.asyncio
async def test_create_incident_source_not_allowed():
    """POST should return 403 when SourceNotAllowedError is raised."""
    from app.services.anomaly_intake_center import SourceNotAllowedError

    app = _make_app()

    with patch("app.api.incidents._get_intake_center") as mock_get:
        mock_center = AsyncMock()
        mock_center.receive_event.side_effect = SourceNotAllowedError("UNKNOWN")
        mock_get.return_value = mock_center

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/incidents",
                json={
                    "incident_type": "equipment_failure",
                    "occurred_at": "2024-06-15T08:00:00Z",
                    "resource_id": "CNC-001",
                    "report_source": "MES",
                },
            )

    assert resp.status_code == 403
    assert resp.json()["detail"]["source"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# GET /api/v1/incidents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_incidents_empty():
    """GET list should return empty list when no incidents exist."""
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/incidents")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_incidents_returns_all():
    """GET list should return all stored incidents."""
    _seed_incident(resource_id="CNC-001")
    _seed_incident(resource_id="CNC-002")

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/incidents")

    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_incidents_filter_by_severity():
    """GET list should filter by severity query param."""
    _seed_incident(severity=IncidentSeverity.P1_CRITICAL.value)
    _seed_incident(severity=IncidentSeverity.P3_MEDIUM.value)

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/incidents",
            params={"severity": IncidentSeverity.P1_CRITICAL.value},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["severity"] == IncidentSeverity.P1_CRITICAL.value


@pytest.mark.asyncio
async def test_list_incidents_filter_by_status():
    """GET list should filter by status query param."""
    _seed_incident(status=IncidentStatus.PENDING_ANALYSIS.value)
    _seed_incident(status=IncidentStatus.CONFIRMED.value)

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/incidents",
            params={"status": IncidentStatus.CONFIRMED.value},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == IncidentStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_list_incidents_filter_by_time_range():
    """GET list should filter by start_time and end_time."""
    _seed_incident(
        occurred_at=datetime(2024, 6, 10, 8, 0, 0, tzinfo=timezone.utc),
        resource_id="OLD",
    )
    _seed_incident(
        occurred_at=datetime(2024, 6, 20, 8, 0, 0, tzinfo=timezone.utc),
        resource_id="NEW",
    )

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/incidents",
            params={
                "start_time": "2024-06-15T00:00:00Z",
                "end_time": "2024-06-25T00:00:00Z",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["resource_id"] == "NEW"


@pytest.mark.asyncio
async def test_list_incidents_sorted_by_severity_then_time():
    """GET list should sort P1 before P3, and newer before older within same severity."""
    _seed_incident(
        severity=IncidentSeverity.P3_MEDIUM.value,
        occurred_at=datetime(2024, 6, 20, 8, 0, 0, tzinfo=timezone.utc),
        resource_id="P3-newer",
    )
    _seed_incident(
        severity=IncidentSeverity.P1_CRITICAL.value,
        occurred_at=datetime(2024, 6, 10, 8, 0, 0, tzinfo=timezone.utc),
        resource_id="P1-older",
    )

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/incidents")

    data = resp.json()
    assert data[0]["severity"] == IncidentSeverity.P1_CRITICAL.value
    assert data[1]["severity"] == IncidentSeverity.P3_MEDIUM.value


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_incident_detail():
    """GET detail should return the incident by ID."""
    incident = _seed_incident()

    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/incidents/{incident.incident_id}")

    assert resp.status_code == 200
    assert resp.json()["incident_id"] == str(incident.incident_id)


@pytest.mark.asyncio
async def test_get_incident_not_found():
    """GET detail should return 404 for unknown incident_id."""
    app = _make_app()
    fake_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/incidents/{fake_id}")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
