"""Tests for Case Library & Template Management API endpoints.

Covers:
- GET  /api/v1/cases
- GET  /api/v1/cases/{case_id}
- GET  /api/v1/case-templates
- POST /api/v1/case-templates
- PUT  /api/v1/case-templates/{template_id}
- POST /api/v1/case-templates/{template_id}/publish
- GET  /api/v1/planners/{planner_id}/preference-profile

Validates: Requirements 9.3, 9.8, 14.1, 14.4
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ── Helpers ────────────────────────────────────────────────────────


def _reset_stores():
    """Reset in-memory stores between tests."""
    from app.api.cases import _case_library, _template_manager

    _case_library._case_store.clear()
    _case_library._preference_store.clear()
    _template_manager._template_store.clear()


async def _seed_case():
    """Seed a case record via the CaseLibrary service."""
    from app.api.cases import _case_library
    from app.models.decision import DecisionRecord
    from app.models.execution import ExecutionResult
    from app.models.solver import SolverChain

    dr = DecisionRecord(
        decision_record_id=uuid4(),
        incident_id=uuid4(),
        impact_report_summary="2 work orders affected",
        strategy_type="local_repair",
        all_candidate_plan_ids=[uuid4()],
        recommended_plan_id=uuid4(),
        confirmed_plan_id=uuid4(),
        derived_from_plan_id=uuid4(),
        is_override=False,
        is_manual_adjusted=False,
        confirmed_by="planner-1",
        confirmed_at=datetime.now(tz=timezone.utc),
        plan_selection_input_version="1.0",
        plan_selection_output_version="1.0",
        solver_chain=SolverChain(
            strategy_type="local_repair",
            rule_selection="due_date_priority",
            neighborhood_selection="critical_path",
            repair_policy="balanced",
            solver_name="cp_sat",
            key_parameters={"timeout": 60},
            search_budget_seconds=60.0,
            constraint_validation_result="feasible",
        ),
        rule_selector_version="1.0.0",
        neighborhood_selector_version="1.0.0",
        repair_policy_advisor_version="1.0.0",
    )
    er = ExecutionResult(
        incident_id=dr.incident_id,
        decision_record_id=dr.decision_record_id,
        actual_completion_times={},
        planned_completion_times={},
        actual_otd=0.95,
        actual_resource_utilization=0.80,
        deviation_percentage=5.0,
    )
    case = await _case_library.create_case(dr, er)
    return case


# ── GET /api/v1/cases ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_cases_empty():
    """GET /cases returns empty list when no cases exist."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/cases")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_cases_with_data():
    """GET /cases returns seeded cases."""
    _reset_stores()
    await _seed_case()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/cases")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["strategy_type"] == "local_repair"


@pytest.mark.asyncio
async def test_list_cases_filter_strategy():
    """GET /cases?strategy_type= filters correctly."""
    _reset_stores()
    await _seed_case()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/cases?strategy_type=global_reschedule")

    assert resp.status_code == 200
    assert resp.json() == []


# ── GET /api/v1/cases/{case_id} ───────────────────────────────────


@pytest.mark.asyncio
async def test_get_case_detail():
    """GET /cases/{case_id} returns case detail."""
    _reset_stores()
    case = await _seed_case()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/cases/{case.case_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == str(case.case_id)


@pytest.mark.asyncio
async def test_get_case_not_found():
    """GET /cases/{case_id} returns 404 for unknown case."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/cases/{uuid4()}")

    assert resp.status_code == 404


# ── POST /api/v1/case-templates ────────────────────────────────────


@pytest.mark.asyncio
async def test_create_template():
    """POST /case-templates creates a draft template."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/case-templates",
            json={
                "template_name": "Test Template",
                "applicable_incident_types": ["equipment_failure"],
                "recommended_strategy": "local_repair",
                "key_parameter_thresholds": {"max_ratio": 0.2},
                "created_by": "manager-1",
            },
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "draft"
    assert data["template_name"] == "Test Template"


# ── GET /api/v1/case-templates ─────────────────────────────────────


@pytest.mark.asyncio
async def test_list_templates():
    """GET /case-templates returns all templates."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create two templates
        await client.post(
            "/api/v1/case-templates",
            json={
                "template_name": "T1",
                "recommended_strategy": "local_repair",
                "created_by": "mgr",
            },
        )
        await client.post(
            "/api/v1/case-templates",
            json={
                "template_name": "T2",
                "recommended_strategy": "global_reschedule",
                "created_by": "mgr",
            },
        )

        resp = await client.get("/api/v1/case-templates")

    assert resp.status_code == 200
    assert len(resp.json()) == 2


# ── PUT /api/v1/case-templates/{template_id} ──────────────────────


@pytest.mark.asyncio
async def test_edit_template():
    """PUT /case-templates/{id} edits a draft template."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/api/v1/case-templates",
            json={
                "template_name": "Original",
                "recommended_strategy": "local_repair",
                "created_by": "mgr",
            },
        )
        template_id = create_resp.json()["template_id"]

        resp = await client.put(
            f"/api/v1/case-templates/{template_id}",
            json={"template_name": "Updated"},
        )

    assert resp.status_code == 200
    assert resp.json()["template_name"] == "Updated"


@pytest.mark.asyncio
async def test_edit_published_template_400():
    """PUT /case-templates/{id} returns 400 for published template."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/api/v1/case-templates",
            json={
                "template_name": "T",
                "recommended_strategy": "local_repair",
                "created_by": "mgr",
            },
        )
        template_id = create_resp.json()["template_id"]

        await client.post(f"/api/v1/case-templates/{template_id}/publish")

        resp = await client.put(
            f"/api/v1/case-templates/{template_id}",
            json={"template_name": "Should Fail"},
        )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_edit_nonexistent_template_404():
    """PUT /case-templates/{id} returns 404 for unknown template."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/case-templates/{uuid4()}",
            json={"template_name": "Nope"},
        )

    assert resp.status_code == 404


# ── POST /api/v1/case-templates/{template_id}/publish ─────────────


@pytest.mark.asyncio
async def test_publish_template():
    """POST /case-templates/{id}/publish publishes template."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/api/v1/case-templates",
            json={
                "template_name": "T",
                "recommended_strategy": "local_repair",
                "created_by": "mgr",
            },
        )
        template_id = create_resp.json()["template_id"]

        resp = await client.post(f"/api/v1/case-templates/{template_id}/publish")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "published"


@pytest.mark.asyncio
async def test_publish_nonexistent_404():
    """POST /case-templates/{id}/publish returns 404 for unknown template."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/v1/case-templates/{uuid4()}/publish")

    assert resp.status_code == 404


# ── GET /api/v1/planners/{planner_id}/preference-profile ──────────


@pytest.mark.asyncio
async def test_get_preference_profile():
    """GET /planners/{id}/preference-profile returns default profile."""
    _reset_stores()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/planners/planner-1/preference-profile")

    assert resp.status_code == 200
    data = resp.json()
    assert data["planner_id"] == "planner-1"
    assert "strategy_preferences" in data
    assert len(data["strategy_preferences"]) == 3
