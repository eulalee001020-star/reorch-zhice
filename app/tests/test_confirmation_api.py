"""Tests for Confirmation & Writeback API endpoints.

Covers:
- POST /api/v1/incidents/{incident_id}/confirm
- GET  /api/v1/incidents/{incident_id}/decision-record
- GET  /api/v1/incidents/{incident_id}/writeback-status
- GET  /api/v1/incidents/{incident_id}/execution-result
- GET  /api/v1/decisions/{decision_record_id}/export/pdf
- GET  /api/v1/decisions/{decision_record_id}/export/excel

Validates: Requirements 7.6, 8.3, 8.7, 27.7
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

_NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
_LATER = _NOW + timedelta(hours=2)


def _seed_incident_and_plans():
    """Seed in-memory stores with an incident, snapshot, plans, and recommendation."""
    from app.api.incidents import _incident_store
    from app.api.analysis import _snapshot_store, _impact_report_cache, _strategy_cache
    from app.api.solver import _candidate_plans_store, _plan_index, _recommendation_store
    from app.models.incident import Incident
    from app.models.enums import (
        IncidentSeverity,
        IncidentStatus,
        IncidentType,
        ReportSource,
        GoalMode,
    )
    from app.models.schedule import (
        Operation,
        Resource,
        ScheduleDetail,
        ScheduleSnapshot,
        WorkOrder,
        GanttDiffPayload,
    )
    from app.models.impact import AffectedWorkOrder, ImpactReport
    from app.models.strategy import StrategyRecommendation
    from app.models.solver import (
        CandidatePlan,
        ConstraintValidationReport,
        SolverChain,
        SolverMetadata,
    )
    from app.models.evaluation import ComparisonMatrix, ComparisonMatrixRow, KPIVector
    from app.models.recommendation import PlanSelectionOutput

    incident_id = uuid4()
    key = str(incident_id)

    # Incident
    incident = Incident(
        incident_id=incident_id,
        incident_type=IncidentType.EQUIPMENT_FAILURE,
        occurred_at=_NOW,
        resource_id="M-1",
        report_source=ReportSource.MES,
        severity=IncidentSeverity.P2_HIGH,
        status=IncidentStatus.PENDING_CONFIRMATION,
    )
    _incident_store[key] = incident

    # Snapshot
    op = Operation(
        operation_id="OP-1",
        work_order_id="WO-1",
        resource_id="M-1",
        required_capabilities=["milling"],
        start_time=_NOW,
        end_time=_LATER,
    )
    wo = WorkOrder(
        work_order_id="WO-1",
        product_name="Widget",
        due_date=_NOW + timedelta(days=1),
        operations=[op],
    )
    snapshot = ScheduleSnapshot(
        captured_at=_NOW,
        workshop_id="WS-1",
        work_orders=[wo],
    )
    _snapshot_store["WS-1"] = snapshot

    # Impact report
    impact = ImpactReport(
        incident_id=incident_id,
        schedule_snapshot_id=snapshot.snapshot_id,
        analysis_reference_time=_NOW,
        affected_work_orders=[
            AffectedWorkOrder(
                work_order_id="WO-1",
                product_name="Widget",
                due_date=_NOW + timedelta(days=1),
                delivery_risk_level="warning",
                remaining_buffer_minutes=120.0,
                affected_operations=[],
            )
        ],
        affected_operations=[],
        affected_resource_ids=["M-1"],
        delivery_risk_distribution={"warning": 1},
        estimated_total_delay_minutes=30.0,
    )
    _impact_report_cache[key] = impact

    # Strategy
    strategy = StrategyRecommendation(
        strategy_type="local_repair",
        confidence=0.85,
        key_factors=["limited scope"],
        historical_case_ids=[],
        reasoning="Local repair recommended",
    )
    _strategy_cache[key] = strategy

    # Candidate plans
    solver_chain = SolverChain(
        strategy_type="local_repair",
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_name="cp_sat",
        key_parameters={"timeout": 60},
        search_budget_seconds=60.0,
        constraint_validation_result="feasible",
    )
    res = Resource(resource_id="M-1", name="Mill-1", capabilities=["milling"])
    schedule = ScheduleDetail(work_orders=[wo], resources=[res])

    plan = CandidatePlan(
        plan_id=uuid4(),
        strategy_type="local_repair",
        schedule_detail=schedule,
        gantt_version="1.0",
        solver_chain=solver_chain,
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=5.0, iteration_count=100
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=True, violations=[], checked_constraints=[]
        ),
    )
    _candidate_plans_store[key] = [plan]
    _plan_index[str(plan.plan_id)] = plan

    # Recommendation
    kpi = KPIVector(
        delayed_order_count=0,
        max_delay_minutes=0.0,
        spi=0.1,
        resource_utilization_delta=0.02,
        changeover_count_delta=0,
        critical_order_otd_impact=0.0,
        normalized_score=0.85,
    )
    matrix = ComparisonMatrix(
        rows=[
            ComparisonMatrixRow(
                plan_id=str(plan.plan_id),
                kpi_vector=kpi,
                delta_vs_baseline={},
                is_score_close=False,
            )
        ],
        normalization_method="min_max",
        score_unit_descriptions={},
        baseline_snapshot_id=str(snapshot.snapshot_id),
    )
    gantt_diff = GanttDiffPayload(
        baseline_snapshot_id=str(snapshot.snapshot_id),
        candidate_plan_id=str(plan.plan_id),
        adjusted_operations=[],
        time_shifts=[],
        resource_switches=[],
        critical_path_changes=[],
    )
    recommendation = PlanSelectionOutput(
        recommended_plan_id=plan.plan_id,
        recommended_rank=1,
        top_scored_plan_id=plan.plan_id,
        recommendation_confidence=0.85,
        auto_preselected=True,
        ranked_plan_list=[],
        reason_codes=["best_score"],
        reason_summary="Best overall score",
        risk_flags=[],
        comparison_matrix=matrix,
        gantt_diff_payload=gantt_diff,
        goal_mode_used=GoalMode.BALANCED.value,
        weights_used={},
        matched_case_ids=[],
        alternative_plan_ids=[],
        audit_metadata={},
    )
    _recommendation_store[key] = recommendation

    return incident_id, plan.plan_id


# ── Test: POST /confirm ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_accept():
    """POST /confirm with accept action succeeds."""
    incident_id, plan_id = _seed_incident_and_plans()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/incidents/{incident_id}/confirm",
            json={
                "action": "accept",
                "selected_plan_id": str(plan_id),
                "confirmed_by": "planner-1",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["confirmed_plan_id"] == str(plan_id)
    assert data["is_manual_adjusted"] is False
    assert "decision_record_id" in data


# ── Test: POST /confirm with missing plans ─────────────────────────


@pytest.mark.asyncio
async def test_confirm_no_plans_404():
    """POST /confirm returns 404 when no candidate plans exist."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/incidents/{uuid4()}/confirm",
            json={
                "action": "accept",
                "selected_plan_id": str(uuid4()),
                "confirmed_by": "planner-1",
            },
        )

    assert resp.status_code == 404


# ── Test: GET /decision-record ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_decision_record():
    """GET /decision-record returns the record after confirmation."""
    incident_id, plan_id = _seed_incident_and_plans()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First confirm
        await client.post(
            f"/api/v1/incidents/{incident_id}/confirm",
            json={
                "action": "accept",
                "selected_plan_id": str(plan_id),
                "confirmed_by": "planner-1",
            },
        )

        # Then query
        resp = await client.get(
            f"/api/v1/incidents/{incident_id}/decision-record"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["incident_id"] == str(incident_id)
    assert data["confirmed_plan_id"] == str(plan_id)


# ── Test: GET /decision-record 404 ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_decision_record_404():
    """GET /decision-record returns 404 for unknown incident."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/incidents/{uuid4()}/decision-record"
        )

    assert resp.status_code == 404


# ── Test: GET /writeback-status ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_writeback_status():
    """GET /writeback-status returns status after confirmation."""
    incident_id, plan_id = _seed_incident_and_plans()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            f"/api/v1/incidents/{incident_id}/confirm",
            json={
                "action": "accept",
                "selected_plan_id": str(plan_id),
                "confirmed_by": "planner-1",
            },
        )

        resp = await client.get(
            f"/api/v1/incidents/{incident_id}/writeback-status"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"


# ── Test: GET /writeback-status 404 ────────────────────────────────


@pytest.mark.asyncio
async def test_get_writeback_status_404():
    """GET /writeback-status returns 404 for unknown incident."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/incidents/{uuid4()}/writeback-status"
        )

    assert resp.status_code == 404


# ── Test: GET /execution-result 404 ────────────────────────────────


@pytest.mark.asyncio
async def test_get_execution_result_404():
    """GET /execution-result returns 404 for unknown incident."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/incidents/{uuid4()}/execution-result"
        )

    assert resp.status_code == 404
