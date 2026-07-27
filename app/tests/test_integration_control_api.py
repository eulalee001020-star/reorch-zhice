"""API and runtime-gate tests for integration-control assets."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.production_runtime import SolveJobSubmitRequest
from app.services.integration_control_validation import (
    IntegrationControlValidationHarness,
)
from app.services.operational_store import RelationalOperationalStore
from app.services.production_digital_twin import ProductionDigitalTwinFactory


ADMIN_HEADERS = {"X-API-Key": "admin-key-001"}
PLANNER_HEADERS = {"X-API-Key": "planner-key-001"}


@pytest.mark.asyncio
async def test_admin_can_run_control_plane_validation_and_planner_cannot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.production_runtime as runtime_api

    monkeypatch.setattr(runtime_api, "_store", RelationalOperationalStore())
    monkeypatch.setattr(runtime_api, "_queue", None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.post(
            "/api/v1/integration-control/validation/digital-twin",
            json={"tenant_id": "default"},
            headers=PLANNER_HEADERS,
        )
        passed = await client.post(
            "/api/v1/integration-control/validation/digital-twin",
            json={"tenant_id": "default"},
            headers=ADMIN_HEADERS,
        )
        overview = await client.get(
            "/api/v1/integration-control/overview?tenant_id=default",
            headers=ADMIN_HEADERS,
        )

    assert denied.status_code == 403
    assert passed.status_code == 200
    assert passed.json()["all_checks_passed"] is True
    assert overview.status_code == 200
    assert overview.json()["latest_readiness_manifest"]["status"] == "ready"


@pytest.mark.asyncio
async def test_cdc_schema_drift_blocks_event_before_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.production_runtime as runtime_api

    store = RelationalOperationalStore()
    monkeypatch.setattr(runtime_api, "_store", store)
    monkeypatch.setattr(runtime_api, "_queue", None)
    IntegrationControlValidationHarness(store).run(
        tenant_id="default", actor_id="admin-test"
    )
    occurred_at = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc).isoformat()
    valid_schema = {
        "operation_id": "string",
        "work_order_id": "string",
        "resource_id": "string",
        "status": "string",
        "planned_start": "datetime",
        "planned_end": "datetime",
    }
    base = {
        "tenant_id": "default",
        "source_system": "MES",
        "partition_key": "schema-test",
        "occurred_at": occurred_at,
        "entity_type": "operation",
        "entity_id": "OP-1",
        "payload": {"status": "released"},
        "connector_id": "dt-mes-connector",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/api/v1/runtime/cdc/events",
            json={
                **base,
                "event_id": "schema-valid-1",
                "sequence": 1,
                "schema_fields": valid_schema,
            },
            headers=ADMIN_HEADERS,
        )
        blocked = await client.post(
            "/api/v1/runtime/cdc/events",
            json={
                **base,
                "event_id": "schema-breaking-2",
                "sequence": 2,
                "schema_version": "2.0",
                "schema_fields": {**valid_schema, "operation_id": "integer"},
            },
            headers=ADMIN_HEADERS,
        )

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["status"] == "quarantined"
    assert store.get_cdc_event("schema-breaking-2") is None


@pytest.mark.asyncio
async def test_solve_submission_accepts_current_readiness_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.production_runtime as runtime_api

    store = RelationalOperationalStore()
    monkeypatch.setattr(runtime_api, "_store", store)
    monkeypatch.setattr(runtime_api, "_queue", None)
    validation = IntegrationControlValidationHarness(store).run(
        tenant_id="default", actor_id="admin-test"
    )
    solve_request = ProductionDigitalTwinFactory().build_solve_request(
        100, tenant_id="default", incident_count=2
    )
    solve_request.scenario_type = "machine_down_recovery"
    solve_request.readiness_manifest_id = validation.readiness_manifest.manifest_id
    submit = SolveJobSubmitRequest(
        tenant_id="default",
        idempotency_key="governed-solve-1",
        solve_request=solve_request,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runtime/solve-jobs",
            json=submit.model_dump(mode="json"),
            headers=ADMIN_HEADERS,
        )

    assert response.status_code == 200
    assert response.json()["created"] is True
