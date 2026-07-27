"""Tests for reusable large-FJSP anomaly replay service."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.planning import router as planning_router
from app.models.large_fjsp_replay import LargeFjspReplayRequest
from app.services.large_fjsp_replay import LargeFjspReplayService


def test_large_fjsp_replay_generates_multiple_solver_backed_options() -> None:
    response = LargeFjspReplayService().run(_request())

    assert response.permission_level == "shadow_ready"
    assert response.snapshot_available is True
    assert response.work_order_count == 2
    assert response.operation_count == 4
    assert response.solved_incident_count == 2
    assert response.feasible_option_count >= 4

    first = response.results[0]
    assert first.can_generate_executable_plan is True
    assert first.recommended_policy is not None
    assert {option.solver_strategy for option in first.options} >= {
        "wait_and_repair",
        "local_repair",
        "global_reschedule",
    }
    assert all(option.decision_boundary for option in first.options)


def test_large_fjsp_replay_blocks_when_affected_operation_is_missing() -> None:
    request = _request()
    request.incidents[0]["primary_operation_id"] = "OP-MISSING"

    response = LargeFjspReplayService().run(request)

    first = response.results[0]
    assert first.can_generate_executable_plan is False
    assert "affected_operation_not_found_in_snapshot" in first.remaining_gaps
    assert response.results[1].can_generate_executable_plan is True


def test_large_fjsp_replay_uses_controlled_frozen_release_when_frozen_successor_blocks_repair() -> None:
    request = _request()
    for row in request.schedule_rows:
        if row["operation_id"] == "WO-1-OP2":
            row["frozen_flag"] = "True"
    request.max_incidents = 1

    response = LargeFjspReplayService().run(request)

    first = response.results[0]
    release = next(
        option
        for option in first.options
        if option.policy_type == "controlled_frozen_zone_release"
    )
    assert release.feasibility_status == "feasible"
    assert release.kpi.frozen_change_count >= 1
    assert "not eligible for autonomous writeback" in " ".join(release.cons)


@pytest.mark.asyncio
async def test_large_fjsp_replay_api() -> None:
    test_app = FastAPI()
    test_app.include_router(planning_router)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/planning/flexible-shop/large-fjsp/replay",
            json=_request().model_dump(mode="json"),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["solved_incident_count"] == 2
    assert data["results"][0]["options"]


def _request() -> LargeFjspReplayRequest:
    return LargeFjspReplayRequest(
        source_system="test_large_fjsp_pack",
        workshop_id="WS-LARGE-FJSP",
        work_orders=[
            {
                "work_order_id": "WO-1",
                "product_family": "A",
                "quantity": "1",
                "priority": "P1",
                "due_time": "2026-07-06T20:00:00",
            },
            {
                "work_order_id": "WO-2",
                "product_family": "B",
                "quantity": "1",
                "priority": "P2",
                "due_time": "2026-07-06T22:00:00",
            },
        ],
        operations=[
            {
                "operation_id": "WO-1-OP1",
                "work_order_id": "WO-1",
                "operation_seq": "1",
                "eligible_machines": "M01|M02",
                "standard_duration_min": "30",
                "precedence_prev_operation_id": "",
            },
            {
                "operation_id": "WO-1-OP2",
                "work_order_id": "WO-1",
                "operation_seq": "2",
                "eligible_machines": "M02|M03",
                "standard_duration_min": "40",
                "precedence_prev_operation_id": "WO-1-OP1",
            },
            {
                "operation_id": "WO-2-OP1",
                "work_order_id": "WO-2",
                "operation_seq": "1",
                "eligible_machines": "M01|M03",
                "standard_duration_min": "35",
                "precedence_prev_operation_id": "",
            },
            {
                "operation_id": "WO-2-OP2",
                "work_order_id": "WO-2",
                "operation_seq": "2",
                "eligible_machines": "M02|M03",
                "standard_duration_min": "25",
                "precedence_prev_operation_id": "WO-2-OP1",
            },
        ],
        resources=[
            {
                "resource_id": "M01",
                "resource_type": "machine",
                "capability_group": "CNC",
                "status_at_snapshot": "available",
            },
            {
                "resource_id": "M02",
                "resource_type": "machine",
                "capability_group": "CNC",
                "status_at_snapshot": "degraded",
            },
            {
                "resource_id": "M03",
                "resource_type": "machine",
                "capability_group": "CNC",
                "status_at_snapshot": "available",
            },
        ],
        schedule_rows=[
            {
                "operation_id": "WO-1-OP1",
                "work_order_id": "WO-1",
                "assigned_resource_id": "M01",
                "planned_start": "2026-07-06T08:00:00",
                "planned_end": "2026-07-06T08:30:00",
                "frozen_flag": "False",
            },
            {
                "operation_id": "WO-1-OP2",
                "work_order_id": "WO-1",
                "assigned_resource_id": "M02",
                "planned_start": "2026-07-06T08:30:00",
                "planned_end": "2026-07-06T09:10:00",
                "frozen_flag": "False",
            },
            {
                "operation_id": "WO-2-OP1",
                "work_order_id": "WO-2",
                "assigned_resource_id": "M01",
                "planned_start": "2026-07-06T08:30:00",
                "planned_end": "2026-07-06T09:05:00",
                "frozen_flag": "False",
            },
            {
                "operation_id": "WO-2-OP2",
                "work_order_id": "WO-2",
                "assigned_resource_id": "M03",
                "planned_start": "2026-07-06T09:05:00",
                "planned_end": "2026-07-06T09:30:00",
                "frozen_flag": "False",
            },
        ],
        incidents=[
            {
                "case_id": "INC-1",
                "incident_type": "machine_down",
                "occurred_at": "2026-07-06T08:10:00",
                "primary_resource_id": "M01",
                "primary_operation_id": "WO-1-OP1",
                "primary_work_order_id": "WO-1",
                "estimated_service_loss_min": "45",
                "severity": "P2",
                "manual_decision_placeholder": "missing_public_benchmark",
                "execution_outcome_placeholder": "missing_public_benchmark",
            },
            {
                "case_id": "INC-2",
                "incident_type": "setup_overrun",
                "occurred_at": "2026-07-06T08:40:00",
                "primary_resource_id": "M02",
                "primary_operation_id": "WO-1-OP2",
                "primary_work_order_id": "WO-1",
                "estimated_service_loss_min": "20",
                "severity": "P3",
                "manual_decision_placeholder": "missing_public_benchmark",
                "execution_outcome_placeholder": "missing_public_benchmark",
            },
        ],
    )
