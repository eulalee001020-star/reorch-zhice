"""Production runtime API integration tests."""

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.production_runtime import SolveJobSubmitRequest
from app.services.operational_store import RelationalOperationalStore
from app.services.production_digital_twin import ProductionDigitalTwinFactory


@pytest.mark.asyncio
async def test_cdc_asof_and_durable_solve_job_api(monkeypatch) -> None:
    import app.api.production_runtime as runtime_api

    monkeypatch.setattr(runtime_api, "_store", RelationalOperationalStore())
    monkeypatch.setattr(runtime_api, "_queue", None)
    as_of = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for source in ("ERP", "MES", "QMS"):
            response = await client.post(
                "/api/v1/runtime/cdc/events",
                json={
                    "event_id": f"{source}-1",
                    "tenant_id": "TENANT-API",
                    "source_system": source,
                    "sequence": 1,
                    "occurred_at": as_of.isoformat(),
                    "entity_type": "state",
                    "entity_id": "1",
                    "payload": {"source": source},
                },
            )
            assert response.status_code == 200
        asof_response = await client.post(
            "/api/v1/runtime/cdc/as-of",
            json={
                "tenant_id": "TENANT-API",
                "required_sources": ["ERP", "MES", "QMS"],
                "as_of": as_of.isoformat(),
            },
        )

        solve_request = ProductionDigitalTwinFactory().build_solve_request(
            100, tenant_id="TENANT-API", incident_count=3
        )
        submit = SolveJobSubmitRequest(
            tenant_id="TENANT-API",
            idempotency_key="api-job-1",
            solve_request=solve_request,
        )
        submit_response = await client.post(
            "/api/v1/runtime/solve-jobs",
            json=submit.model_dump(mode="json"),
        )
        job_id = submit_response.json()["job"]["job_id"]
        worker_response = await client.post(
            "/api/v1/runtime/solve-workers/test-worker/run-once"
        )
        get_response = await client.get(f"/api/v1/runtime/solve-jobs/{job_id}")

    assert asof_response.status_code == 200
    assert asof_response.json()["status"] == "consistent"
    assert submit_response.status_code == 200
    assert submit_response.json()["created"] is True
    assert worker_response.status_code == 200
    assert worker_response.json()["status"] == "completed"
    assert get_response.json()["result"]["status"] == "feasible"


@pytest.mark.asyncio
async def test_blocked_asof_returns_conflict(monkeypatch) -> None:
    import app.api.production_runtime as runtime_api

    monkeypatch.setattr(runtime_api, "_store", RelationalOperationalStore())
    monkeypatch.setattr(runtime_api, "_queue", None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/runtime/cdc/as-of",
            json={
                "tenant_id": "TENANT-API",
                "required_sources": ["ERP", "MES", "QMS"],
                "as_of": "2026-07-12T08:00:00+00:00",
            },
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["status"] == "blocked"
    assert "missing_source_checkpoint:ERP" in detail["blockers"]
