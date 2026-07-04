"""Tests for the P0 Reality Harness customer-data gate."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.planning import router as planning_router
from app.models.reality_harness import P0RealityHarnessRequest
from app.services.reality_harness import P0RealityHarnessService


def test_p0_sample_pack_is_shadow_ready_without_writeback() -> None:
    service = P0RealityHarnessService()
    response = service.assess(service.load_sample_pack())

    assert response.mapping_report.is_valid is True
    assert response.permission.level == "shadow_ready"
    assert response.permission.allow_historical_replay is True
    assert response.permission.allow_shadow_mode is True
    assert response.permission.allow_writeback is False
    assert response.snapshot is not None
    assert response.snapshot.workshop_id == "P0-REALITY-LINE"
    assert {step.step for step in response.audit_steps} == {
        "canonical_mapping_validation",
        "snapshot_reconstruction",
        "permission_gate",
    }


def test_unknown_machine_crosswalk_stops_before_snapshot() -> None:
    service = P0RealityHarnessService()
    request = service.load_sample_pack()
    request.raw_machines = [
        row for row in request.raw_machines if row["machine_id"] != "M-03"
    ]

    response = service.assess(request)
    codes = {issue.code for issue in response.readiness_report.blockers}

    assert response.permission.level == "stop"
    assert response.permission.allow_candidate_generation is False
    assert response.snapshot is None
    assert "unknown_machine_reference" in codes
    assert response.mapping_report.reference_integrity_errors >= 1


def test_timezone_warning_allows_replay_but_blocks_shadow() -> None:
    service = P0RealityHarnessService()
    request = P0RealityHarnessRequest(
        source_system="timezone-test",
        workshop_id="WS-TZ",
        planning_start=datetime(2026, 5, 14, 8, 0, tzinfo=timezone.utc),
        raw_work_orders=[
            {
                "work_order_id": "WO-TZ",
                "product_name": "Timezone test",
                "quantity": 1,
                "priority": "NORMAL",
                "due_time": "2026-05-14T20:00:00",
                "status": "released",
            }
        ],
        raw_operations=[
            {
                "operation_id": "OP-TZ",
                "work_order_id": "WO-TZ",
                "processing_time_min": 30,
                "machine_id": "M-TZ",
                "required_capability": "CNC",
                "required_capabilities": "CNC",
                "start_time": "2026-05-14T09:00:00",
                "end_time": "2026-05-14T09:30:00",
            }
        ],
        raw_machines=[
            {
                "machine_id": "M-TZ",
                "name": "Timezone Machine",
                "capabilities": "CNC",
                "status": "available",
            }
        ],
        raw_incidents=[
            {
                "incident_id": "INC-TZ",
                "type": "machine_down",
                "machine_id": "M-TZ",
                "start_time": "2026-05-14T09:15:00",
                "severity": "P2-High",
            }
        ],
    )

    response = service.assess(request)
    warning_codes = {issue.code for issue in response.readiness_report.warnings}

    assert response.mapping_report.is_valid is True
    assert "timezone_missing" in warning_codes
    assert response.permission.level == "replay_only"
    assert response.permission.allow_historical_replay is True
    assert response.permission.allow_shadow_mode is False
    assert response.permission.allow_writeback is False


@pytest.mark.asyncio
async def test_p0_reality_harness_sample_pack_api() -> None:
    test_app = FastAPI()
    test_app.include_router(planning_router)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/planning/reality-harness/sample-pack")

    assert response.status_code == 200
    data = response.json()
    assert data["permission"]["level"] == "shadow_ready"
    assert data["permission"]["allow_historical_replay"] is True
    assert data["permission"]["allow_shadow_mode"] is True
    assert data["permission"]["allow_writeback"] is False
    assert data["snapshot"]["workshop_id"] == "P0-REALITY-LINE"
