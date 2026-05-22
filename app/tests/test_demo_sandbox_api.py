from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.analysis import _impact_report_cache, _snapshot_store, _strategy_cache
from app.api.demo import router as demo_router
from app.api.incidents import _incident_store
from app.api.solver import _candidate_plans_store, _plan_index, _recommendation_store


@pytest.fixture(autouse=True)
def _clear_demo_stores():
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


@pytest.mark.asyncio
async def test_reset_sandbox_demo_loads_valid_public_scenario() -> None:
    test_app = FastAPI()
    test_app.include_router(demo_router)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/demo/sandbox/reset")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["scenario_id"] == "M03_MACHINE_DOWN_4H"
    assert payload["validation"]["blocking_errors"] == 0
    assert payload["affected_operation_count"] == 4
    assert payload["affected_work_order_count"] == 4
    assert payload["incident"]["resource_id"] == "M-03"
    assert len(_incident_store) == 1
    assert len(_snapshot_store) == 1
