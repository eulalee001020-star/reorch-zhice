"""Tests for historical replay validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.planning import router as planning_router
from app.models.replay_validation import ReplayValidationRequest
from app.models.schedule import Operation, Resource, ScheduleDetail, WorkOrder
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    ConstraintViolation,
    SolverChain,
    SolverMetadata,
)
from app.services.replay_validation import ReplayValidationService


def test_replay_validation_hits_historical_acceptance_envelope() -> None:
    start = datetime(2026, 5, 12, 8, tzinfo=timezone.utc)
    accepted = _schedule(start, resource_id="CNC-01")
    plan = _candidate_plan(_schedule(start + timedelta(minutes=5), resource_id="CNC-01"))
    request = ReplayValidationRequest(
        historical_case_id="hist-001",
        accepted_schedule=accepted,
        candidate_plans=[plan],
        time_tolerance_minutes=15,
        acceptance_threshold=0.8,
    )

    response = ReplayValidationService().evaluate(request)

    assert response.top_n_hit is True
    assert response.shadow_readiness_level == "shadow_comparable"
    assert response.decision == "eligible_for_read_only_shadow_comparison"
    assert response.best_plan_id == str(plan.plan_id)
    assert response.candidate_scores[0].resource_match_rate == 1.0
    assert response.candidate_scores[0].within_time_tolerance_rate == 1.0
    assert response.candidate_scores[0].pass_quality_gate is True


def test_replay_validation_blocks_when_quality_gate_fails() -> None:
    start = datetime(2026, 5, 12, 8, tzinfo=timezone.utc)
    accepted = _schedule(start, resource_id="CNC-01")
    plan = _candidate_plan(
        _schedule(start, resource_id="CNC-01"),
        feasible=False,
    )
    request = ReplayValidationRequest(
        historical_case_id="hist-002",
        accepted_schedule=accepted,
        candidate_plans=[plan],
    )

    response = ReplayValidationService().evaluate(request)

    assert response.top_n_hit is False
    assert response.shadow_readiness_level == "blocked"
    assert response.decision == "fix_constraints_before_replay"
    assert response.candidate_scores[0].schedule_similarity_score == 1.0
    assert response.candidate_scores[0].pass_quality_gate is False
    assert "quality_gate_blocked" in response.candidate_scores[0].reasons


@pytest.mark.asyncio
async def test_replay_validation_api() -> None:
    start = datetime(2026, 5, 12, 8, tzinfo=timezone.utc)
    accepted = _schedule(start, resource_id="CNC-01")
    plan = _candidate_plan(_schedule(start + timedelta(minutes=5), resource_id="CNC-01"))
    test_app = FastAPI()
    test_app.include_router(planning_router)
    transport = ASGITransport(app=test_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/planning/replay-validation/evaluate",
            json={
                "historical_case_id": "hist-api",
                "accepted_schedule": accepted.model_dump(mode="json"),
                "candidate_plans": [plan.model_dump(mode="json")],
                "time_tolerance_minutes": 15,
                "acceptance_threshold": 0.8,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["top_n_hit"] is True
    assert data["candidate_scores"][0]["pass_quality_gate"] is True


def _schedule(start: datetime, *, resource_id: str) -> ScheduleDetail:
    return ScheduleDetail(
        resources=[
            Resource(
                resource_id=resource_id,
                name=resource_id,
                capabilities=["milling"],
                is_bottleneck=True,
            )
        ],
        work_orders=[
            WorkOrder(
                work_order_id="WO-1",
                product_name="Part A",
                due_date=start + timedelta(hours=8),
                priority=1,
                operations=[
                    Operation(
                        operation_id="OP-10",
                        work_order_id="WO-1",
                        resource_id=resource_id,
                        start_time=start,
                        end_time=start + timedelta(hours=1),
                    ),
                    Operation(
                        operation_id="OP-20",
                        work_order_id="WO-1",
                        resource_id=resource_id,
                        start_time=start + timedelta(hours=1),
                        end_time=start + timedelta(hours=2),
                        predecessor_ids=["OP-10"],
                    ),
                ],
            )
        ],
    )


def _candidate_plan(
    schedule: ScheduleDetail,
    *,
    feasible: bool = True,
) -> CandidatePlan:
    violations = [] if feasible else [
        ConstraintViolation(
            constraint_type="resource_mutex",
            operation_id="OP-10",
            resource_id="CNC-01",
            detail="Overlap detected.",
        )
    ]
    return CandidatePlan(
        strategy_type="repair",
        schedule_detail=schedule,
        gantt_version="v1",
        solver_chain=SolverChain(
            strategy_type="repair",
            rule_selection="validated_rules",
            neighborhood_selection="local",
            repair_policy="freeze_unaffected",
            solver_name="cp_sat",
            key_parameters={},
            search_budget_seconds=5.0,
            constraint_validation_result="feasible" if feasible else "infeasible",
            stages=["constraint_check", "local_repair", "quality_gate"],
        ),
        feasibility_status="feasible" if feasible else "infeasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=1.2,
            iteration_count=10,
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=feasible,
            violations=violations,
            checked_constraints=[
                "resource_mutex",
                "operation_precedence",
                "resource_capability",
            ],
        ),
    )
