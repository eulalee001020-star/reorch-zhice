"""Tests for P0 constraint calibration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.planning import router as planning_router
from app.models.agent import ConstraintCandidate
from app.models.constraint_calibration import (
    ChangeoverCalibration,
    ConstraintCalibrationPack,
    MachineCapabilityCalibration,
    ResourceCalendarCalibration,
    ReviewedConstraintCandidateInput,
)
from app.models.planning import (
    InitialScheduleRequest,
    PlanningResourceInput,
    PlanningWorkOrderInput,
)
from app.services.constraint_calibration import ConstraintCalibrationService


def test_approved_constraints_compile_into_initial_request() -> None:
    start = datetime(2026, 5, 12, 8, tzinfo=timezone.utc)
    pack = ConstraintCalibrationPack(
        workshop_id="WS-01",
        base_request=_base_request(start),
        machine_capabilities=[
            MachineCapabilityCalibration(
                resource_id="CNC-01",
                capabilities=["milling", "fine boring"],
                approved_by="planner-1",
                source_refs=["site-interview:line-a"],
            )
        ],
        resource_calendars=[
            ResourceCalendarCalibration(
                resource_id="CNC-01",
                window_start=start + timedelta(hours=3),
                window_end=start + timedelta(hours=4),
                reason="Preventive maintenance",
                approved_by="planner-1",
            )
        ],
        changeovers=[
            ChangeoverCalibration(
                from_product_family="A",
                to_product_family="B",
                setup_minutes=25,
                resource_id="CNC-01",
                approved_by="planner-1",
            )
        ],
    )

    compiled = ConstraintCalibrationService().compile(pack)

    assert compiled.blocked is False
    assert compiled.applied_constraint_count == 3
    assert compiled.resource_capabilities["CNC-01"] == ["fine boring", "milling"]
    assert len(compiled.resource_calendar) == 1
    assert compiled.resource_calendar[0].reason == "Preventive maintenance"
    assert len(compiled.changeover_rules) == 1
    assert compiled.initial_schedule_request is not None
    patched = compiled.initial_schedule_request
    cnc = next(resource for resource in patched.resources if resource.resource_id == "CNC-01")
    assert cnc.capabilities == ["fine boring", "milling"]
    assert patched.resource_calendar[0].resource_id == "CNC-01"
    assert patched.changeover_rules[0].setup_minutes == 25


def test_unpublished_ai_candidate_is_not_active_constraint() -> None:
    candidate = ConstraintCandidate(
        candidate_id="cand-001",
        constraint_type="changeover",
        scope={
            "from_product_family": "A",
            "to_product_family": "B",
            "setup_minutes": 45,
            "resource_id": "CNC-01",
        },
        source_text="A to B setup is usually 45 minutes.",
        compiled_rule="changeover(A,B,CNC-01)=45",
        confidence=0.82,
        status="pending_human_review",
    )
    pack = ConstraintCalibrationPack(
        workshop_id="WS-01",
        rule_candidates=[
            ReviewedConstraintCandidateInput(
                candidate=candidate,
                review_status="approved",
                replay_passed=False,
                reviewer_id="planner-1",
            )
        ],
    )

    compiled = ConstraintCalibrationService().compile(pack)

    assert compiled.blocked is False
    assert compiled.omitted_candidate_count == 1
    assert compiled.changeover_rules == []
    assert {conflict.code for conflict in compiled.conflicts} == {
        "rule_candidate_not_active"
    }


def test_invalid_or_unknown_constraints_block_scheduler_patch() -> None:
    start = datetime(2026, 5, 12, 8, tzinfo=timezone.utc)
    pack = ConstraintCalibrationPack(
        workshop_id="WS-01",
        base_request=_base_request(start),
        machine_capabilities=[
            MachineCapabilityCalibration(
                resource_id="UNKNOWN",
                capabilities=["milling"],
                approved_by="planner-1",
            )
        ],
        resource_calendars=[
            ResourceCalendarCalibration(
                resource_id="CNC-01",
                window_start=start + timedelta(hours=4),
                window_end=start + timedelta(hours=3),
                approved_by="planner-1",
            )
        ],
        changeovers=[
            ChangeoverCalibration(
                from_product_family="A",
                to_product_family="B",
                setup_minutes=10,
                resource_id="CNC-01",
                approved_by="planner-1",
            ),
            ChangeoverCalibration(
                from_product_family="A",
                to_product_family="B",
                setup_minutes=30,
                resource_id="CNC-01",
                approved_by="planner-1",
            ),
        ],
    )

    compiled = ConstraintCalibrationService().compile(pack)
    codes = {conflict.code for conflict in compiled.conflicts}

    assert compiled.blocked is True
    assert compiled.initial_schedule_request is None
    assert "invalid_calendar_window" in codes
    assert "capability_unknown_resource" in codes
    assert "conflicting_changeover_rule" in codes


@pytest.mark.asyncio
async def test_constraint_calibration_compile_api() -> None:
    start = datetime(2026, 5, 12, 8, tzinfo=timezone.utc)
    test_app = FastAPI()
    test_app.include_router(planning_router)
    transport = ASGITransport(app=test_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/planning/constraint-calibration/compile",
            json={
                "workshop_id": "WS-01",
                "base_request": _base_request(start).model_dump(mode="json"),
                "resource_calendars": [
                    {
                        "resource_id": "CNC-01",
                        "window_start": (start + timedelta(hours=1)).isoformat(),
                        "window_end": (start + timedelta(hours=2)).isoformat(),
                        "approved_by": "planner-1",
                    }
                ],
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is False
    assert data["resource_calendar"][0]["resource_id"] == "CNC-01"
    assert data["initial_schedule_request"]["resource_calendar"][0]["resource_id"] == "CNC-01"


def _base_request(start: datetime) -> InitialScheduleRequest:
    return InitialScheduleRequest(
        workshop_id="WS-01",
        planning_start=start,
        resources=[
            PlanningResourceInput(
                resource_id="CNC-01",
                capabilities=["milling"],
                is_bottleneck=True,
            )
        ],
        work_orders=[
            PlanningWorkOrderInput(
                work_order_id="WO-1",
                product_name="Part A",
                product_family="A",
                due_date=start + timedelta(hours=8),
            )
        ],
    )
