"""Tests for shadow-mode capture and agent observability."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.planning import router as planning_router
from app.models.agent import AgentTraceStep
from app.models.agent_observability import AgentCostProfile, AgentTraceObserveRequest
from app.models.schedule import Operation, Resource, ScheduleDetail, WorkOrder
from app.models.shadow_mode import PlannerShadowDecision, ShadowCaseCaptureRequest
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.services.agent_observability import AgentObservabilityService
from app.services.shadow_mode import ShadowModeService


def test_shadow_capture_is_advisory_only_and_blocks_writeback() -> None:
    plan = _candidate_plan()
    request = ShadowCaseCaptureRequest(
        incident_payload={"incident_id": "INC-1", "type": "machine_down"},
        schedule_snapshot_id="snapshot-1",
        candidate_plans=[plan],
        planner_decision=PlannerShadowDecision(
            decision_status="tweaked",
            selected_plan_id=str(plan.plan_id),
            override_reason="Planner kept a frozen customer order unchanged.",
        ),
        source_refs=["snapshot-1", "planner-feedback-1"],
    )

    response = ShadowModeService().capture(request)

    assert response.advisory_only is True
    assert response.writeback_blocked is True
    assert response.feedback_capture_complete is True
    assert response.rule_candidate_recommended is True
    assert response.audit_bundle["writeback_command_created"] is False


def test_agent_observability_estimates_cost_and_recommends_cache() -> None:
    request = AgentTraceObserveRequest(
        run_id="run-1",
        workflow_name="incident_decision",
        trace=[
            AgentTraceStep(
                agent_name="IncidentAgent",
                input_summary="machine down text",
                output_summary="structured incident",
                freedom_level="schema_only",
                llm_allowed=True,
                llm_used=True,
                llm_provider="fake",
                model_name="small-json",
                latency_ms=1200,
                input_tokens=1000,
                output_tokens=500,
                deterministic_tools=["schema_validator"],
                guardrail="human_confirmation_required",
            ),
            AgentTraceStep(
                agent_name="SolverAgent",
                input_summary="incident",
                output_summary="candidate plans",
                freedom_level="deterministic_tool_only",
                llm_allowed=False,
                llm_used=False,
                latency_ms=240,
                fallback_reason="llm_not_allowed_for_solver",
                deterministic_tools=["cp_sat"],
                guardrail="solver_and_quality_gate_required",
            ),
        ],
        cost_profiles=[
            AgentCostProfile(
                provider="fake",
                model_name="small-json",
                input_cost_per_million_tokens=1.0,
                output_cost_per_million_tokens=2.0,
            )
        ],
    )

    summary = AgentObservabilityService().summarize(request)

    assert summary.llm_steps == 1
    assert summary.deterministic_steps == 1
    assert summary.fallback_steps == 1
    assert summary.total_input_tokens == 1000
    assert summary.total_output_tokens == 500
    assert summary.estimated_cost_usd == 0.002
    assert "Telemetry only" in summary.decision_boundary
    assert any("cache" in item.lower() for item in summary.cost_reduction_recommendations)


@pytest.mark.asyncio
async def test_shadow_and_observability_api() -> None:
    test_app = FastAPI()
    test_app.include_router(planning_router)
    transport = ASGITransport(app=test_app)
    plan = _candidate_plan()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        shadow_response = await client.post(
            "/api/v1/planning/shadow-mode/capture",
            json={
                "incident_payload": {"incident_id": "INC-API"},
                "schedule_snapshot_id": "snapshot-api",
                "candidate_plans": [plan.model_dump(mode="json")],
                "planner_decision": {
                    "decision_status": "accepted",
                    "selected_plan_id": str(plan.plan_id),
                    "decided_by": "planner-1",
                },
                "source_refs": ["snapshot-api"],
            },
        )
        observability_response = await client.post(
            "/api/v1/planning/agent-observability/summarize",
            json={
                "run_id": "run-api",
                "workflow_name": "feedback",
                "trace": [
                    {
                        "agent_name": "FeedbackAgent",
                        "input_summary": "planner note",
                        "output_summary": "override reason",
                        "freedom_level": "schema_only",
                        "llm_allowed": True,
                        "llm_used": False,
                        "fallback_reason": "provider_not_configured",
                        "deterministic_tools": ["keyword_parser"],
                        "guardrail": "pending_human_review",
                    }
                ],
            },
        )

    assert shadow_response.status_code == 200
    assert shadow_response.json()["writeback_blocked"] is True
    assert observability_response.status_code == 200
    assert observability_response.json()["fallback_steps"] == 1


def _candidate_plan() -> CandidatePlan:
    start = datetime(2026, 5, 12, 8, tzinfo=timezone.utc)
    schedule = ScheduleDetail(
        resources=[
            Resource(
                resource_id="CNC-01",
                name="CNC-01",
                capabilities=["milling"],
            )
        ],
        work_orders=[
            WorkOrder(
                work_order_id="WO-1",
                product_name="Part A",
                due_date=start + timedelta(hours=8),
                operations=[
                    Operation(
                        operation_id="OP-10",
                        work_order_id="WO-1",
                        resource_id="CNC-01",
                        start_time=start,
                        end_time=start + timedelta(hours=1),
                    )
                ],
            )
        ],
    )
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
            search_budget_seconds=5,
            constraint_validation_result="feasible",
            stages=["constraint_check", "quality_gate"],
        ),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(solve_time_seconds=1.0, iteration_count=5),
        constraint_report=ConstraintValidationReport(
            is_feasible=True,
            checked_constraints=[
                "resource_mutex",
                "operation_precedence",
                "resource_capability",
            ],
        ),
    )
