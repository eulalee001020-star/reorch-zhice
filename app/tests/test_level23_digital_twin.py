"""Tests for Level 2/3 digital-twin replay rehearsal evaluator."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.planning import router as planning_router
from app.models.level23_digital_twin import Level23DigitalTwinReplayRequest
from app.services.level23_digital_twin import Level23DigitalTwinReplayEvaluator


def test_level23_digital_twin_evaluator_scores_rehearsal_pack() -> None:
    response = Level23DigitalTwinReplayEvaluator().evaluate(_request())

    assert response.rehearsal_level == "level_2_3_rehearsal_ready"
    assert response.readiness_score == 0.85
    assert response.linkage_metrics.affected_subgraph_ready_rate == 1.0
    assert response.replay_metrics.top1_exact_match_rate == 1.0
    assert response.replay_metrics.top3_manual_coverage_rate == 1.0
    assert response.execution_metrics.execution_success_rate == 1.0
    assert response.policy_summaries[0].confidence_level == "simulated_medium"
    assert response.production_readiness.decision == "replay_ready"
    assert "production_writeback" in response.production_readiness.blocked_actions
    assert any(
        status.table_name == "manual_outcomes"
        and "simulated_evidence_not_customer_proof" in status.notes
        for status in response.table_statuses
    )


def test_level23_digital_twin_blocks_when_required_tables_are_missing() -> None:
    request = _request()
    request.schedule_snapshot = []

    response = Level23DigitalTwinReplayEvaluator().evaluate(request)

    assert response.rehearsal_level == "blocked"
    schedule = next(
        status for status in response.table_statuses if status.table_name == "schedule_snapshot"
    )
    assert schedule.status == "blocker"


@pytest.mark.asyncio
async def test_level23_digital_twin_api() -> None:
    test_app = FastAPI()
    test_app.include_router(planning_router)
    transport = ASGITransport(app=test_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/planning/digital-twin/level2-3/evaluate",
            json=_request().model_dump(mode="json"),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["rehearsal_level"] == "level_2_3_rehearsal_ready"
    assert data["production_readiness"]["decision"] == "replay_ready"


def _request() -> Level23DigitalTwinReplayRequest:
    return Level23DigitalTwinReplayRequest(
        pack_id="level2_3_unit_pack",
        source_workbook_name="unit.xlsx",
        resources=[
            {"resource_id": "CNC-01", "resource_group": "CNC", "source_basis": "digital_twin"}
        ],
        work_orders=[
            {"work_order_id": "WO-1", "due_time": "2026-07-06 20:00:00"}
        ],
        operations=[
            {
                "operation_id": "OP-1",
                "work_order_id": "WO-1",
                "eligible_resources": "CNC-01",
                "standard_duration_min": 60,
            }
        ],
        routing_precedence=[
            {"operation_id": "OP-1", "work_order_id": "WO-1", "prev_operation_id": None}
        ],
        schedule_snapshot=[
            {
                "schedule_id": "SCH-1",
                "operation_id": "OP-1",
                "work_order_id": "WO-1",
                "resource_id": "CNC-01",
                "planned_start": "2026-07-06 08:00:00",
                "planned_end": "2026-07-06 09:00:00",
            }
        ],
        incidents=[
            {
                "incident_id": "INC-1",
                "incident_type": "machine_down",
                "linked_schedule_id": "SCH-1",
                "linked_operation_id": "OP-1",
                "linked_work_order_id": "WO-1",
            }
        ],
        candidate_plans=[
            {
                "candidate_plan_id": "CP-1",
                "incident_id": "INC-1",
                "strategy_type": "local_repair",
                "feasible_flag": "Y",
                "hard_violation_count": 0,
                "predicted_delay_min": 12,
                "solver_runtime_sec": 0.4,
            }
        ],
        replay_comparison=[
            {
                "incident_id": "INC-1",
                "manual_strategy": "local_repair",
                "system_top1_strategy": "local_repair",
                "top3_contains_manual_strategy": "Y",
                "delay_delta_system_minus_manual": -5,
                "perturbation_delta_system_minus_manual": 0.01,
                "hard_feasible_top1": "Y",
                "planner_review_needed": "Y",
            }
        ],
        manual_outcomes=[
            {
                "manual_outcome_id": "MO-1",
                "incident_id": "INC-1",
                "manual_strategy": "local_repair",
                "manual_expected_delay_min": 17,
                "override_reason": "protect_key_customer",
                "source_basis": "simulated_manual_outcome_for_replay_training",
            }
        ],
        execution_feedback=[
            {
                "feedback_id": "FB-1",
                "incident_id": "INC-1",
                "executed_strategy": "local_repair",
                "execution_success_flag": "Y",
                "actual_delay_min": 10,
                "secondary_incident_flag": "N",
                "planner_satisfaction_score": 4,
                "source_basis": "simulated_execution_feedback",
            }
        ],
        policy_effectiveness=[
            {
                "strategy_type": "local_repair",
                "candidate_count": 45,
                "feasible_rate": 1.0,
                "avg_predicted_delay_min": 12,
                "manual_selection_rate": 1.0,
                "execution_success_rate": 1.0,
                "avg_actual_delay_min": 10,
            }
        ],
        readiness_scorecard=[{"score": 0.85}],
    )
