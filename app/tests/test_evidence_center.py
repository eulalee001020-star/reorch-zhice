"""Tests for Evidence Center aggregation."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.services.evidence_center import EvidenceCenterService


def test_evidence_center_contains_required_evidence_categories():
    response = EvidenceCenterService().build()
    categories = {item.category for item in response.items}

    assert {
        "replay",
        "failure_samples",
        "llm_eval",
        "data_readiness",
        "quality_gate",
    }.issubset(categories)
    assert response.summary_counts["total"] >= 5
    quality_gate = next(item for item in response.items if item.evidence_id == "ngs_quality_gate_batch")
    assert quality_gate.metrics["case_count"] == 3
    assert quality_gate.table is not None


@pytest.mark.asyncio
async def test_evidence_center_api_returns_viewable_items():
    from fastapi import FastAPI

    from app.api.evidence import router

    test_app = FastAPI()
    test_app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/v1/evidence/center")

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary_counts"]["total"] >= 5
    assert any(item["category"] == "llm_eval" for item in data["items"])
