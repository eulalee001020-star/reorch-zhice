from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.models.planning import (
    EnterpriseImportRequest,
    InitialScheduleRequest,
    PlanningOperationInput,
    PlanningMaterialRequirementInput,
    PlanningResourceInput,
    PlanningWorkOrderInput,
    ResourceCalendarWindowInput,
    ValueTrackingInput,
)
from app.services.digital_twin_runner import DigitalTwinRunner
from app.services.enterprise_integration import EnterpriseIntegrationService
from app.models.solver import ConstraintViolation
from app.services.data_readiness import DataReadinessService
from app.services.initial_scheduler import InitialScheduler
from app.services.plan_quality_gate import PlanQualityGate
from app.services.value_tracking import ValueTrackingService


def _make_initial_request() -> InitialScheduleRequest:
    start = datetime(2026, 5, 12, 8, tzinfo=timezone.utc)
    return InitialScheduleRequest(
        workshop_id="WS-01",
        planning_start=start,
        resources=[
            PlanningResourceInput(
                resource_id="CNC-01",
                capabilities=["milling"],
                is_bottleneck=True,
                cost_per_minute=2,
            ),
            PlanningResourceInput(
                resource_id="CNC-02",
                capabilities=["milling"],
                cost_per_minute=1,
            ),
            PlanningResourceInput(
                resource_id="ASM-01",
                capabilities=["assembly"],
                cost_per_minute=1,
            ),
        ],
        work_orders=[
            PlanningWorkOrderInput(
                work_order_id="WO-1",
                product_name="Part A",
                product_family="A",
                priority=2,
                due_date=start + timedelta(hours=8),
                operations=[
                    PlanningOperationInput(
                        operation_id="WO-1-10",
                        work_order_id="WO-1",
                        duration_minutes=120,
                        eligible_resource_ids=["CNC-01", "CNC-02"],
                        required_capabilities=["milling"],
                    ),
                    PlanningOperationInput(
                        operation_id="WO-1-20",
                        work_order_id="WO-1",
                        duration_minutes=90,
                        eligible_resource_ids=["ASM-01"],
                        required_capabilities=["assembly"],
                        predecessor_ids=["WO-1-10"],
                    ),
                ],
            ),
            PlanningWorkOrderInput(
                work_order_id="WO-2",
                product_name="Part B",
                product_family="B",
                priority=1,
                due_date=start + timedelta(hours=7),
                operations=[
                    PlanningOperationInput(
                        operation_id="WO-2-10",
                        work_order_id="WO-2",
                        duration_minutes=100,
                        eligible_resource_ids=["CNC-01", "CNC-02"],
                        required_capabilities=["milling"],
                    ),
                    PlanningOperationInput(
                        operation_id="WO-2-20",
                        work_order_id="WO-2",
                        duration_minutes=80,
                        eligible_resource_ids=["ASM-01"],
                        required_capabilities=["assembly"],
                        predecessor_ids=["WO-2-10"],
                    ),
                ],
            ),
        ],
        time_budget_seconds=3,
    )


def test_initial_scheduler_generates_multiple_feasible_options() -> None:
    response = asyncio.run(InitialScheduler().generate(_make_initial_request()))

    assert response.readiness_report.is_ready is True
    assert {option.goal_mode for option in response.options} == {
        "delivery_priority",
        "throughput_priority",
        "bottleneck_priority",
        "cost_priority",
        "balanced",
    }
    for option in response.options:
        assert option.candidate_plan.constraint_report.is_feasible is True
        assert option.kpis["operation_count"] == 4
        assert option.kpis["otd_rate"] >= 0


def test_initial_scheduler_respects_material_and_calendar_constraints() -> None:
    request = _make_initial_request()
    start = request.planning_start
    request.resource_calendar = [
        ResourceCalendarWindowInput(
            resource_id="CNC-02",
            window_start=start,
            window_end=start + timedelta(hours=3),
            availability_type="unavailable",
        )
    ]
    request.work_orders[0].operations[0].material_requirements = [
        PlanningMaterialRequirementInput(
            material_id="AL-6061",
            required_quantity=1,
            available_at=start + timedelta(hours=2),
            status="delayed",
        )
    ]
    response = asyncio.run(InitialScheduler().generate(request))
    plan = response.options[0].candidate_plan
    op = next(
        op
        for wo in plan.schedule_detail.work_orders
        for op in wo.operations
        if op.operation_id == "WO-1-10"
    )

    assert op.start_time >= start + timedelta(hours=2)
    if op.resource_id == "CNC-02":
        assert op.start_time >= start + timedelta(hours=3)


def test_data_readiness_blocks_incapable_resource() -> None:
    request = _make_initial_request()
    request.work_orders[0].operations[0].required_capabilities = ["turning"]

    report = DataReadinessService().assess_initial_schedule_request(request)

    assert report.is_ready is False
    assert "no_capable_eligible_resource" in {issue.code for issue in report.blockers}


def test_plan_quality_gate_blocks_infeasible_plan() -> None:
    response = asyncio.run(InitialScheduler().generate(_make_initial_request()))
    plan = response.options[0].candidate_plan
    plan.feasibility_status = "infeasible"
    plan.constraint_report.is_feasible = False
    plan.constraint_report.violations.append(
        ConstraintViolation(
            constraint_type="resource_mutual_exclusion",
            operation_id="WO-1-10",
            resource_id="CNC-01",
            detail="overlap",
        )
    )

    report = PlanQualityGate().evaluate(plan)

    assert report.pass_gate is False
    assert report.recommendation_policy == "do_not_recommend"


def test_value_tracking_estimates_savings() -> None:
    report = ValueTrackingService().estimate(
        ValueTrackingInput(
            incident_count=10,
            baseline_decision_minutes=90,
            actual_decision_minutes=20,
            baseline_tardiness_minutes=300,
            actual_tardiness_minutes=120,
            baseline_changeovers=8,
            actual_changeovers=5,
            baseline_overtime_hours=12,
            actual_overtime_hours=4,
            planner_hourly_cost=150,
            tardiness_cost_per_minute=20,
            changeover_cost=500,
            overtime_hourly_cost=200,
        )
    )

    assert report.saved_decision_minutes == 70
    assert report.reduced_tardiness_minutes == 180
    assert report.reduced_changeovers == 3
    assert report.estimated_savings > 0


def test_enterprise_import_normalizes_erp_aps_payload() -> None:
    start = datetime(2026, 5, 12, 8, tzinfo=timezone.utc)
    payload = {
        "resources": [
            {"resource_id": "M1", "capabilities": ["milling"]},
        ],
        "work_orders": [
            {
                "work_order_id": "WO-X",
                "product_name": "Part X",
                "product_family": "X",
                "due_date": (start + timedelta(hours=4)).isoformat(),
                "operations": [
                    {
                        "operation_id": "WO-X-10",
                        "work_order_id": "WO-X",
                        "duration_minutes": 60,
                        "eligible_resource_ids": ["M1"],
                        "required_capabilities": ["milling"],
                    }
                ],
            }
        ],
    }

    response = EnterpriseIntegrationService().normalize_initial_schedule(
        EnterpriseImportRequest(
            source_system="customer-aps",
            workshop_id="WS-X",
            planning_start=start,
            raw_payload=payload,
        )
    )

    assert response.readiness_report.is_ready is True
    assert response.initial_schedule_request.work_orders[0].work_order_id == "WO-X"


def test_digital_twin_sample_runs_end_to_end() -> None:
    response = asyncio.run(DigitalTwinRunner().run_sample())

    assert response.initial_schedule.readiness_report.is_ready is True
    assert len(response.initial_schedule.options) >= 3
    assert response.baseline_snapshot is not None
    assert response.impact_report is not None
    assert len(response.reschedule_candidates) >= 1
    assert response.writeback_preview is not None
    assert response.value_report is not None
