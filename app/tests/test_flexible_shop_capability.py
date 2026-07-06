"""Tests for large-scale flexible shop capability package."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.planning import router as planning_router
from app.models.flexible_shop import (
    BenchmarkTarget,
    BufferConstraint,
    ChangeoverMatrixEntry,
    CounterfactualReplayMatrixRequest,
    DynamicIncidentScenario,
    DynamicReschedulingPlanRequest,
    FlexibleConstraintPack,
    FlexibleMachineGroup,
    FlexibleOperation,
    FlexibleOperationMode,
    FlexibleResource,
    FlexibleShopBenchmarkRequest,
    FlexibleShopCapabilityRequest,
    FlexibleShopContext,
    FlexibleWorkOrder,
    FlexibleWorkshop,
    FrozenZone,
    HistoricalRecoveryCase,
    MaterialConstraint,
    OutsourcingOption,
    PolicyOutcomeObservation,
    QualityHoldConstraint,
    SkillConstraint,
    ToolingConstraint,
    TransportConstraint,
    WipItem,
)
from app.services.flexible_shop_capability import (
    CounterfactualReplayMatrixService,
    DynamicReschedulingPlanner,
    FlexibleShopBenchmarkService,
    FlexibleShopCapabilityService,
)


def test_capability_assessment_covers_all_required_modules() -> None:
    context = _large_context()
    response = FlexibleShopCapabilityService().assess(
        FlexibleShopCapabilityRequest(
            context=context,
            incident_types_to_support=[
                "equipment_failure",
                "rush_order",
                "material_shortage",
                "quality_exception",
                "labor_absence",
                "tooling_conflict",
                "batch_rework",
            ],
            historical_replay_case_count=30,
            shadow_case_count=12,
            execution_feedback_case_count=5,
            sandbox_writeback_ready=True,
            approved_writeback_roles=["planner", "production_manager"],
        )
    )

    modules = {status.module: status for status in response.statuses}
    assert response.overall_status == "pilot_ready"
    assert set(modules) == {
        "data_model",
        "constraint_system",
        "solver_strategy",
        "dynamic_rescheduling",
        "performance_engineering",
        "data_integration",
        "writeback_safety",
        "recovery_policy_graph",
    }
    assert modules["data_model"].coverage_score == 1.0
    assert modules["constraint_system"].coverage_score == 1.0
    assert modules["writeback_safety"].blockers == []


def test_capability_assessment_blocks_without_core_integrations_and_writeback() -> None:
    context = _large_context()
    context.integration_sources = {"WMS": "mock"}
    response = FlexibleShopCapabilityService().assess(
        FlexibleShopCapabilityRequest(context=context)
    )

    modules = {status.module: status for status in response.statuses}
    assert response.overall_status == "blocked"
    assert "missing_erp_source" in modules["data_integration"].blockers
    assert "missing_mes_source" in modules["data_integration"].blockers
    assert "sandbox_writeback_not_ready" in modules["writeback_safety"].blockers


def test_dynamic_plan_routes_new_incident_types_to_policy_portfolios() -> None:
    context = _large_context(operation_multiplier=600)
    response = DynamicReschedulingPlanner().plan(
        DynamicReschedulingPlanRequest(
            context=context,
            incidents=[
                DynamicIncidentScenario(
                    incident_id="INC-MAT",
                    incident_type="material_shortage",
                    material_id="MAT-AL",
                ),
                DynamicIncidentScenario(
                    incident_id="INC-QA",
                    incident_type="quality_exception",
                    affected_operation_ids=["OP-1-20"],
                ),
                DynamicIncidentScenario(
                    incident_id="INC-TOOL",
                    incident_type="tooling_conflict",
                    tooling_id="FIX-01",
                ),
            ],
        )
    )

    by_id = {plan.incident_id: plan for plan in response.plans}
    assert "material_substitution" in by_id["INC-MAT"].recovery_policies
    assert "quality_hold_freeze" in by_id["INC-QA"].recovery_policies
    assert "tooling_reallocation" in by_id["INC-TOOL"].recovery_policies
    assert response.global_solver_strategy.decomposition_level in {
        "bottleneck_group",
        "workshop_and_bottleneck_group",
    }
    assert response.global_solver_strategy.use_lns is True


def test_synthetic_benchmark_returns_large_scale_strategy() -> None:
    response = FlexibleShopBenchmarkService().run(
        FlexibleShopBenchmarkRequest(
            targets=[
                BenchmarkTarget(operation_count=1000, resource_count=80),
                BenchmarkTarget(operation_count=5000, resource_count=250),
                BenchmarkTarget(operation_count=10000, resource_count=500, concurrent_incidents=3),
            ]
        )
    )

    by_ops = {result.operation_count: result for result in response.results}
    assert by_ops[1000].pass_shadow_threshold is True
    assert "rolling_window" in by_ops[5000].recommended_strategy
    assert "best-known-feasible" in " ".join(by_ops[10000].notes)


def test_counterfactual_replay_matrix_aggregates_policy_effectiveness() -> None:
    response = CounterfactualReplayMatrixService().build(
        CounterfactualReplayMatrixRequest(
            min_sample_count=2,
            cases=[
                _case("C1", "bottleneck_failure_slack_lt_4h", "local_repair", True, True, -60, 10),
                _case("C2", "bottleneck_failure_slack_lt_4h", "local_repair", True, True, -45, 12),
                _case("C3", "bottleneck_failure_slack_lt_4h", "global_reschedule", True, False, -80, 45),
                _case("C4", "bottleneck_failure_slack_lt_4h", "global_reschedule", True, False, -90, 52),
                _case("C5", "material_eta_unknown", "wait_and_shift", True, False, 20, 5),
            ],
        )
    )

    cells = {(cell.context_key, cell.policy_type): cell for cell in response.cells}
    local = cells[("bottleneck_failure_slack_lt_4h", "local_repair")]
    global_plan = cells[("bottleneck_failure_slack_lt_4h", "global_reschedule")]
    assert local.planner_acceptance_rate == 1.0
    assert global_plan.mean_perturbation_cost > local.mean_perturbation_cost
    assert "material_eta_unknown" in response.insufficient_contexts


@pytest.mark.asyncio
async def test_flexible_shop_planning_api_endpoints() -> None:
    test_app = FastAPI()
    test_app.include_router(planning_router)
    transport = ASGITransport(app=test_app)
    context = _large_context()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        capability = await client.post(
            "/api/v1/planning/flexible-shop/capability-assessment",
            json=FlexibleShopCapabilityRequest(
                context=context,
                historical_replay_case_count=10,
                shadow_case_count=10,
                sandbox_writeback_ready=True,
                approved_writeback_roles=["planner"],
            ).model_dump(mode="json"),
        )
        plan = await client.post(
            "/api/v1/planning/flexible-shop/dynamic-rescheduling-plan",
            json=DynamicReschedulingPlanRequest(
                context=context,
                incidents=[
                    DynamicIncidentScenario(
                        incident_id="INC-RUSH",
                        incident_type="rush_order",
                        work_order_id="WO-1",
                    )
                ],
            ).model_dump(mode="json"),
        )
        benchmark = await client.post(
            "/api/v1/planning/flexible-shop/synthetic-benchmark",
            json=FlexibleShopBenchmarkRequest().model_dump(mode="json"),
        )

    assert capability.status_code == 200
    assert plan.status_code == 200
    assert benchmark.status_code == 200
    assert "rush_insertion" in plan.json()["plans"][0]["recovery_policies"]
    assert len(benchmark.json()["results"]) == 3


def _large_context(operation_multiplier: int = 1) -> FlexibleShopContext:
    now = datetime(2026, 7, 6, 8, tzinfo=timezone.utc)
    operations: list[FlexibleOperation] = []
    for index in range(max(2, operation_multiplier)):
        work_order_id = f"WO-{index + 1}"
        operations.extend(
            [
                FlexibleOperation(
                    operation_id=f"OP-{index + 1}-10",
                    work_order_id=work_order_id,
                    route_id="R-A",
                    sequence_no=10,
                    batch_id=f"B-{index // 10}",
                    material_ids=["MAT-AL"],
                    wip_location_id="BUF-RAW",
                    modes=[
                        FlexibleOperationMode(
                            mode_id=f"M-{index + 1}-10-A",
                            resource_id="CNC-01",
                            machine_group_id="CNC-GRP",
                            processing_minutes=60,
                            required_capability_codes=["milling"],
                            required_skill_codes=["cnc_operator"],
                            required_tooling_ids=["FIX-01"],
                            transport_lane_id="LANE-RAW-CNC",
                        ),
                        FlexibleOperationMode(
                            mode_id=f"M-{index + 1}-10-B",
                            resource_id="CNC-02",
                            machine_group_id="CNC-GRP",
                            processing_minutes=75,
                            required_capability_codes=["milling"],
                            required_skill_codes=["cnc_operator"],
                            required_tooling_ids=["FIX-01"],
                            transport_lane_id="LANE-RAW-CNC",
                        ),
                    ],
                ),
                FlexibleOperation(
                    operation_id=f"OP-{index + 1}-20",
                    work_order_id=work_order_id,
                    route_id="R-A",
                    sequence_no=20,
                    batch_id=f"B-{index // 10}",
                    rework_of_operation_id="OP-1-10" if index == 0 else None,
                    predecessor_ids=[f"OP-{index + 1}-10"],
                    quality_state="hold" if index == 0 else "released",
                    wip_location_id="QC-QUEUE",
                    modes=[
                        FlexibleOperationMode(
                            mode_id=f"M-{index + 1}-20-QC",
                            resource_id="QC-01",
                            machine_group_id="QC-GRP",
                            processing_minutes=30,
                            required_capability_codes=["inspection"],
                            required_skill_codes=["qc_inspector"],
                        )
                    ],
                ),
            ]
        )
    work_orders = [
        FlexibleWorkOrder(
            work_order_id=f"WO-{index + 1}",
            product_family="A" if index % 2 == 0 else "B",
            due_date=now + timedelta(hours=24 + index),
            priority=index % 5,
            customer_tier="gold" if index % 7 == 0 else "standard",
            route_ids=["R-A", "R-B"],
            operations=operations[index * 2 : index * 2 + 2],
        )
        for index in range(max(2, operation_multiplier))
    ]
    return FlexibleShopContext(
        site_id="SITE-FJSP",
        captured_at=now,
        workshops=[
            FlexibleWorkshop(workshop_id="WS-1", name="Machining"),
            FlexibleWorkshop(workshop_id="WS-2", name="Inspection"),
        ],
        machine_groups=[
            FlexibleMachineGroup(
                group_id="CNC-GRP",
                workshop_id="WS-1",
                capability_codes=["milling"],
                is_bottleneck=True,
            ),
            FlexibleMachineGroup(
                group_id="QC-GRP",
                workshop_id="WS-2",
                capability_codes=["inspection"],
            ),
        ],
        resources=[
            FlexibleResource(
                resource_id="CNC-01",
                workshop_id="WS-1",
                machine_group_id="CNC-GRP",
                capability_codes=["milling"],
                skill_codes=["cnc_operator"],
                tooling_ids=["FIX-01"],
                is_bottleneck=True,
            ),
            FlexibleResource(
                resource_id="CNC-02",
                workshop_id="WS-1",
                machine_group_id="CNC-GRP",
                capability_codes=["milling"],
                skill_codes=["cnc_operator"],
                tooling_ids=["FIX-01"],
            ),
            FlexibleResource(
                resource_id="QC-01",
                workshop_id="WS-2",
                machine_group_id="QC-GRP",
                capability_codes=["inspection"],
                skill_codes=["qc_inspector"],
            ),
        ],
        work_orders=work_orders,
        wip_items=[
            WipItem(
                wip_id="WIP-1",
                work_order_id="WO-1",
                operation_id="OP-1-10",
                quantity=1,
                location_id="BUF-RAW",
            )
        ],
        frozen_zones=[
            FrozenZone(
                zone_id="FROZEN-1",
                operation_ids=["OP-1-10"],
                frozen_until=now + timedelta(hours=2),
                reason="already_released_to_floor",
            )
        ],
        constraints=FlexibleConstraintPack(
            materials=[
                MaterialConstraint(
                    material_id="MAT-AL",
                    available_quantity=100,
                    available_at=now,
                    substitute_material_ids=["MAT-AL-SUB"],
                )
            ],
            skills=[
                SkillConstraint(skill_code="cnc_operator", available_headcount=4),
                SkillConstraint(skill_code="qc_inspector", available_headcount=2),
            ],
            tooling=[ToolingConstraint(tooling_id="FIX-01", quantity=2, location_id="TOOL-ROOM")],
            changeovers=[
                ChangeoverMatrixEntry(
                    machine_group_id="CNC-GRP",
                    from_family="A",
                    to_family="B",
                    setup_minutes=25,
                    cost=300,
                )
            ],
            quality_holds=[
                QualityHoldConstraint(
                    entity_id="WO-1",
                    hold_reason="first_article_check",
                    blocked_operation_ids=["OP-1-20"],
                )
            ],
            outsourcing=[
                OutsourcingOption(
                    vendor_id="VENDOR-CNC",
                    capability_codes=["milling"],
                    lead_time_minutes=480,
                    capacity_per_day=8,
                )
            ],
            transport=[
                TransportConstraint(
                    lane_id="LANE-RAW-CNC",
                    from_location_id="BUF-RAW",
                    to_location_id="CNC-CELL",
                    transport_mode="AMR",
                    capacity=2,
                    eta_minutes=8,
                )
            ],
            buffers=[BufferConstraint(buffer_id="BUF-RAW", location_id="BUF-RAW", capacity=50, current_wip=10)],
        ),
        integration_sources={
            "ERP": "readonly_adapter",
            "MES": "readonly_adapter",
            "WMS": "readonly_adapter",
            "QMS": "readonly_adapter",
            "IoT": "event_adapter",
        },
    )


def _case(
    case_id: str,
    context_key: str,
    policy_type: str,
    hard_feasible: bool,
    accepted: bool,
    delay_delta: float,
    perturbation: float,
) -> HistoricalRecoveryCase:
    return HistoricalRecoveryCase(
        case_id=case_id,
        context_key=context_key,
        incident_type="equipment_failure",
        observations=[
            PolicyOutcomeObservation(
                policy_type=policy_type,
                hard_feasible=hard_feasible,
                accepted_by_planner=accepted,
                delay_delta_minutes=delay_delta,
                perturbation_cost=perturbation,
            )
        ],
    )
