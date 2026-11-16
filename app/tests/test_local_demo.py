"""The dependency-free demo path must keep working end to end."""

from __future__ import annotations

import httpx
import pytest

from app.main import app
from app.services.validation.local_demo import reset_in_memory_state, walk


@pytest.fixture(autouse=True)
def _isolated_state():
    reset_in_memory_state()
    yield
    reset_in_memory_state()


@pytest.mark.asyncio
async def test_local_demo_walks_the_whole_loop() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://local-demo",
        headers={"X-API-Key": "planner-key-001"},
        timeout=300,
    ) as client:
        result = await walk(client)

    assert result.affected_work_orders > 0
    assert result.candidate_count >= 1
    assert result.feasible_candidates >= 1
    assert result.violations == 0
    assert result.checked_constraints
    assert result.decision_record_id
    assert len(result.lines()) == 8
