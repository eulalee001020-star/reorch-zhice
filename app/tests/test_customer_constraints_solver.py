"""Customer non-equipment constraints wired into CP-SAT and replay."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.enums import DeliveryRiskLevel, StrategyType
from app.models.impact import AffectedOperation, AffectedWorkOrder, ImpactReport
from app.models.large_fjsp_replay import LargeFjspReplayRequest
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.services.cp_sat_scheduler import CpSatFjspScheduler
from app.services.customer_constraint_ingestion import CustomerConstraintIngestionService
from app.services.large_fjsp_replay import LargeFjspReplayService


NOW = datetime(2026, 7, 6, 8, 0, tzinfo=timezone.utc)


def test_customer_constraint_ingestion_attaches_solver_raw_data() -> None:
    snapshot = _snapshot()
    pack = CustomerConstraintIngestionService().build_pack(
        material_availability=[
            {
                "material_id": "MAT-1",
                "operation_ids": "OP-1|OP-2",
                "available_quantity": "10",
                "required_quantity": "2",
                "available_at": "2026-07-06T09:00:00+00:00",
            }
        ],
        quality_holds=[
            {"hold_id": "QH-1", "blocked_operation_ids": "OP-1", "status": "held"}
        ],
        tooling_calendar=[
            {"tooling_id": "FIX-1", "operation_ids": "OP-1;OP-2", "quantity": "1"}
        ],
        labor_skill_capacity=[
            {"skill_code": "cnc", "operation_ids": "OP-1,OP-2", "available_headcount": "1"}
        ],
        urgent_order_constraints=[
            {
                "rush_order_id": "RUSH-1",
                "work_order_id": "WO-2",
                "due_time": "2026-07-06T08:30:00+00:00",
                "customer_service_approved": True,
            }
        ],
    )

    enriched = CustomerConstraintIngestionService().attach_to_snapshot(snapshot, pack)

    assert enriched.raw_data is not None
    assert enriched.raw_data["material_availability"][0]["operation_ids"] == ["OP-1", "OP-2"]
    assert enriched.raw_data["quality_holds"][0]["blocked_operation_ids"] == ["OP-1"]
    assert enriched.raw_data["urgent_order_constraints"][0]["work_order_id"] == "WO-2"


def test_cp_sat_enforces_material_availability_release_time() -> None:
    snapshot = _snapshot(
        raw_overrides={
            "material_availability": [
                {
                    "material_id": "MAT-1",
                    "operation_ids": ["OP-1"],
                    "available_quantity": 1,
                    "required_quantity": 1,
                    "available_at": "2026-07-06T09:00:00+00:00",
                }
            ]
        }
    )

    result = CpSatFjspScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(["OP-1"]),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert result.is_feasible is True
    op = _op(result.schedule_detail, "OP-1")
    assert op.start_time >= NOW + timedelta(hours=1)


def test_cp_sat_freezes_unreleased_quality_hold_operation() -> None:
    snapshot = _snapshot(
        raw_overrides={
            "quality_holds": [
                {
                    "hold_id": "QH-1",
                    "blocked_operation_ids": ["OP-1"],
                    "status": "held",
                }
            ]
        }
    )

    result = CpSatFjspScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(["OP-1"], delay_minutes=45),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert result.is_feasible is True
    op = _op(result.schedule_detail, "OP-1")
    assert op.start_time == NOW
    assert op.end_time == NOW + timedelta(minutes=30)


def test_cp_sat_enforces_tooling_and_labor_capacity_no_overlap() -> None:
    snapshot = _snapshot(
        raw_overrides={
            "tooling_calendar": [
                {"tooling_id": "FIX-1", "operation_ids": ["OP-1", "OP-3"], "quantity": 1}
            ],
            "labor_skill_capacity": [
                {"skill_code": "cnc", "operation_ids": ["OP-1", "OP-3"], "available_headcount": 1}
            ],
        }
    )

    result = CpSatFjspScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(["OP-1", "OP-3"], delay_minutes=0),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1", "OP-3"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert result.is_feasible is True
    first = _op(result.schedule_detail, "OP-1")
    second = _op(result.schedule_detail, "OP-3")
    assert first.end_time <= second.start_time or second.end_time <= first.start_time


def test_urgent_order_constraint_allows_approved_rush_order_insertion() -> None:
    snapshot = _urgent_snapshot()

    result = CpSatFjspScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(["OP-RUSH"], delay_minutes=0, work_order_id="WO-RUSH"),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-RUSH"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert result.is_feasible is True
    rush = _op(result.schedule_detail, "OP-RUSH")
    normal = _op(result.schedule_detail, "OP-NORMAL")
    assert rush.start_time < normal.start_time
    assert rush.end_time <= NOW + timedelta(minutes=30)


def test_large_fjsp_replay_uses_portfolio_with_customer_constraint_tables() -> None:
    request = LargeFjspReplayRequest(
        source_system="customer_like_pack",
        workshop_id="WS-1",
        work_orders=[
            {
                "work_order_id": "WO-1",
                "product_family": "A",
                "quantity": "1",
                "priority": "1",
                "due_time": "2026-07-06T12:00:00",
            }
        ],
        operations=[
            {
                "operation_id": "OP-1",
                "work_order_id": "WO-1",
                "operation_seq": "1",
                "eligible_machines": "M1|M2",
                "standard_duration_min": "30",
                "precedence_prev_operation_id": "",
            }
        ],
        resources=[
            {
                "resource_id": "M1",
                "resource_type": "machine",
                "capability_group": "CNC",
                "status_at_snapshot": "available",
            },
            {
                "resource_id": "M2",
                "resource_type": "machine",
                "capability_group": "CNC",
                "status_at_snapshot": "available",
            },
        ],
        schedule_rows=[
            {
                "operation_id": "OP-1",
                "work_order_id": "WO-1",
                "assigned_resource_id": "M1",
                "planned_start": "2026-07-06T08:00:00",
                "planned_end": "2026-07-06T08:30:00",
                "frozen_flag": "False",
            }
        ],
        incidents=[
            {
                "case_id": "INC-1",
                "incident_type": "material_shortage",
                "occurred_at": "2026-07-06T08:00:00",
                "primary_resource_id": "M1",
                "primary_operation_id": "OP-1",
                "primary_work_order_id": "WO-1",
                "estimated_service_loss_min": "0",
                "severity": "P2",
            }
        ],
        material_availability=[
            {
                "material_id": "MAT-1",
                "operation_ids": ["OP-1"],
                "available_quantity": 1,
                "required_quantity": 1,
                "available_at": "2026-07-06T09:00:00+00:00",
            }
        ],
    )

    response = LargeFjspReplayService().run(request)

    assert response.solved_incident_count == 1
    assert response.results[0].recommended_policy is not None
    assert response.results[0].can_generate_executable_plan is True


def test_transport_batch_and_qms_release_are_encoded_in_schedule() -> None:
    release_at = NOW + timedelta(minutes=50)
    snapshot = _chain_snapshot(
        {
            "transport_lanes": [
                {
                    "lane_id": "AMR-1",
                    "predecessor_operation_id": "OP-1",
                    "successor_operation_id": "OP-2",
                    "capacity": 1,
                    "eta_minutes": 15,
                }
            ],
            "batch_genealogy": [
                {
                    "batch_id": "LOT-1",
                    "operation_ids": ["OP-2"],
                    "parent_operation_ids": ["OP-1"],
                    "quality_state": "released",
                    "release_at": release_at.isoformat(),
                    "source_ref": "QMS:LOT-1",
                }
            ],
            "qms_release_gates": [
                {
                    "gate_id": "FAI-1",
                    "operation_ids": ["OP-2"],
                    "status": "released",
                    "release_at": release_at.isoformat(),
                    "required_approvals": ["quality_manager"],
                    "approvals": ["quality_manager"],
                    "certificate_ref": "CERT-1",
                    "source_ref": "QMS:FAI-1",
                }
            ],
        }
    )

    result = CpSatFjspScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(["OP-1", "OP-2"]),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1", "OP-2"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert result.is_feasible is True
    first = _op(result.schedule_detail, "OP-1")
    second = _op(result.schedule_detail, "OP-2")
    assert second.start_time >= first.end_time + timedelta(minutes=15)
    assert second.start_time >= release_at
    assert "transport_amr_capacity" in result.solver_log["constraint_families"]
    assert "qms_release" in result.solver_log["constraint_families"]


def test_pending_qms_gate_fails_closed_before_solver() -> None:
    snapshot = _chain_snapshot(
        {
            "qms_release_gates": [
                {
                    "gate_id": "FAI-PENDING",
                    "operation_ids": ["OP-2"],
                    "status": "pending",
                    "required_approvals": ["quality_manager"],
                    "approvals": [],
                }
            ]
        }
    )

    result = CpSatFjspScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(["OP-2"]),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-2"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert result.is_feasible is False
    assert result.status_name == "GOVERNANCE_CONSTRAINT_BLOCKED"
    assert "qms_gate_not_released:FAI-PENDING" in result.solver_log["blockers"]


def test_material_shortage_requires_evidenced_substitute_approval() -> None:
    common = {
        "material_availability": [
            {
                "material_id": "MAT-A",
                "operation_ids": ["OP-1"],
                "available_quantity": 0,
                "required_quantity": 1,
            }
        ]
    }
    blocked = CpSatFjspScheduler().solve(
        snapshot=_snapshot(common),
        impact_report=_impact(["OP-1"]),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )
    approved_snapshot = _snapshot(
        {
            **common,
            "substitute_material_approvals": [
                {
                    "primary_material_id": "MAT-A",
                    "substitute_material_id": "MAT-A2",
                    "operation_ids": ["OP-1"],
                    "approval_status": "approved",
                    "available_quantity": 2,
                    "required_quantity": 1,
                    "available_at": (NOW + timedelta(minutes=20)).isoformat(),
                    "approved_by": "quality_manager",
                    "source_ref": "ERP:SUB-1",
                }
            ],
        }
    )
    approved = CpSatFjspScheduler().solve(
        snapshot=approved_snapshot,
        impact_report=_impact(["OP-1"]),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert blocked.is_feasible is False
    assert approved.is_feasible is True
    assert _op(approved.schedule_detail, "OP-1").start_time >= NOW + timedelta(minutes=20)
    assert approved.solver_log["approved_substitute_operations"] == ["OP-1"]


def test_approved_outsource_route_is_real_solver_alternative() -> None:
    snapshot = _snapshot(
        {
            "work_orders": [
                {
                    "work_order_id": "WO-1",
                    "operations": [
                        {
                            "operation_id": "OP-1",
                            "eligible_resources": ["M1"],
                            "raw_payload": {},
                        }
                    ],
                },
                {
                    "work_order_id": "WO-2",
                    "operations": [
                        {
                            "operation_id": "OP-3",
                            "eligible_resources": ["M2"],
                            "raw_payload": {},
                        }
                    ],
                },
            ],
            "resource_calendar": [
                {
                    "resource_id": "M1",
                    "window_start": NOW.isoformat(),
                    "window_end": (NOW + timedelta(hours=10)).isoformat(),
                    "availability_type": "unavailable",
                }
            ],
            "outsourcing_approvals": [
                {
                    "vendor_id": "V-CNC",
                    "operation_ids": ["OP-1"],
                    "lead_time_minutes": 60,
                    "capacity_per_day": 1,
                    "approval_status": "approved",
                    "approved_by": "production_manager",
                    "source_ref": "ERP:OUT-1",
                    "capability_codes": ["cnc"],
                }
            ],
        }
    )

    result = CpSatFjspScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(["OP-1"]),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert result.is_feasible is True
    assert _op(result.schedule_detail, "OP-1").resource_id == "OUTSOURCE:V-CNC"
    assert result.solver_log["selected_outsource_operations"] == ["OP-1"]


def test_full_buffer_plus_transport_lag_is_infeasible() -> None:
    snapshot = _chain_snapshot(
        {
            "transport_lanes": [
                {
                    "lane_id": "AMR-1",
                    "predecessor_operation_id": "OP-1",
                    "successor_operation_id": "OP-2",
                    "capacity": 1,
                    "eta_minutes": 10,
                }
            ],
            "buffer_flows": [
                {
                    "buffer_id": "BUF-1",
                    "predecessor_operation_id": "OP-1",
                    "successor_operation_id": "OP-2",
                    "capacity": 1,
                    "current_wip": 1,
                    "occupancy_quantity": 1,
                }
            ],
        }
    )

    result = CpSatFjspScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(["OP-1", "OP-2"]),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1", "OP-2"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert result.is_feasible is False


def _snapshot(raw_overrides: dict | None = None) -> ScheduleSnapshot:
    raw_data = {
        "resources": [
            {"resource_id": "M1", "capabilities": ["cnc"]},
            {"resource_id": "M2", "capabilities": ["cnc"]},
        ],
        "work_orders": [
            {
                "work_order_id": "WO-1",
                "operations": [
                    {
                        "operation_id": "OP-1",
                        "eligible_resources": ["M1", "M2"],
                        "raw_payload": {},
                    }
                ],
            },
            {
                "work_order_id": "WO-2",
                "operations": [
                    {
                        "operation_id": "OP-3",
                        "eligible_resources": ["M1", "M2"],
                        "raw_payload": {},
                    }
                ],
            },
        ],
    }
    raw_data.update(raw_overrides or {})
    return ScheduleSnapshot(
        captured_at=NOW,
        workshop_id="WS-1",
        raw_data=raw_data,
        work_orders=[
            WorkOrder(
                work_order_id="WO-1",
                product_name="A",
                due_date=NOW + timedelta(hours=4),
                priority=1,
                operations=[
                    Operation(
                        operation_id="OP-1",
                        work_order_id="WO-1",
                        resource_id="M1",
                        start_time=NOW,
                        end_time=NOW + timedelta(minutes=30),
                    )
                ],
            ),
            WorkOrder(
                work_order_id="WO-2",
                product_name="B",
                due_date=NOW + timedelta(hours=4),
                priority=1,
                operations=[
                    Operation(
                        operation_id="OP-3",
                        work_order_id="WO-2",
                        resource_id="M2",
                        start_time=NOW,
                        end_time=NOW + timedelta(minutes=30),
                    )
                ],
            ),
        ],
    )


def _chain_snapshot(raw_overrides: dict | None = None) -> ScheduleSnapshot:
    raw_data = {
        "resources": [
            {"resource_id": "M1", "name": "M1", "capabilities": ["cnc"]},
            {"resource_id": "M2", "name": "M2", "capabilities": ["inspection"]},
        ],
        "work_orders": [
            {
                "work_order_id": "WO-1",
                "operations": [
                    {
                        "operation_id": "OP-1",
                        "eligible_resources": ["M1"],
                        "raw_payload": {},
                    },
                    {
                        "operation_id": "OP-2",
                        "eligible_resources": ["M2"],
                        "raw_payload": {},
                    },
                ],
            }
        ],
    }
    raw_data.update(raw_overrides or {})
    return ScheduleSnapshot(
        captured_at=NOW,
        workshop_id="WS-1",
        raw_data=raw_data,
        work_orders=[
            WorkOrder(
                work_order_id="WO-1",
                product_name="A",
                due_date=NOW + timedelta(hours=4),
                priority=1,
                operations=[
                    Operation(
                        operation_id="OP-1",
                        work_order_id="WO-1",
                        resource_id="M1",
                        required_capabilities=["cnc"],
                        start_time=NOW,
                        end_time=NOW + timedelta(minutes=30),
                        successor_ids=["OP-2"],
                    ),
                    Operation(
                        operation_id="OP-2",
                        work_order_id="WO-1",
                        resource_id="M2",
                        required_capabilities=["inspection"],
                        start_time=NOW + timedelta(minutes=30),
                        end_time=NOW + timedelta(minutes=50),
                        predecessor_ids=["OP-1"],
                    ),
                ],
            )
        ],
    )


def _urgent_snapshot() -> ScheduleSnapshot:
    return ScheduleSnapshot(
        captured_at=NOW,
        workshop_id="WS-1",
        raw_data={
            "resources": [{"resource_id": "M1", "capabilities": ["cnc"]}],
            "work_orders": [
                {
                    "work_order_id": "WO-NORMAL",
                    "operations": [
                        {
                            "operation_id": "OP-NORMAL",
                            "eligible_resources": ["M1"],
                            "raw_payload": {},
                        }
                    ],
                },
                {
                    "work_order_id": "WO-RUSH",
                    "operations": [
                        {
                            "operation_id": "OP-RUSH",
                            "eligible_resources": ["M1"],
                            "raw_payload": {},
                        }
                    ],
                },
            ],
            "urgent_order_constraints": [
                {
                    "rush_order_id": "RUSH-1",
                    "work_order_id": "WO-RUSH",
                    "due_time": "2026-07-06T08:30:00+00:00",
                    "priority_boost": 10,
                    "displacement_cost_per_minute": 1,
                    "customer_service_approved": True,
                }
            ],
        },
        work_orders=[
            WorkOrder(
                work_order_id="WO-NORMAL",
                product_name="A",
                due_date=NOW + timedelta(hours=4),
                priority=1,
                operations=[
                    Operation(
                        operation_id="OP-NORMAL",
                        work_order_id="WO-NORMAL",
                        resource_id="M1",
                        start_time=NOW,
                        end_time=NOW + timedelta(minutes=30),
                    )
                ],
            ),
            WorkOrder(
                work_order_id="WO-RUSH",
                product_name="B",
                due_date=NOW + timedelta(minutes=30),
                priority=10,
                operations=[
                    Operation(
                        operation_id="OP-RUSH",
                        work_order_id="WO-RUSH",
                        resource_id="M1",
                        start_time=NOW + timedelta(minutes=30),
                        end_time=NOW + timedelta(minutes=60),
                    )
                ],
            ),
        ],
    )


def _impact(
    affected_op_ids: list[str],
    *,
    delay_minutes: float = 0,
    work_order_id: str = "WO-1",
) -> ImpactReport:
    affected = [
        AffectedOperation(
            operation_id=op_id,
            work_order_id=work_order_id,
            resource_id="M1",
            is_direct=True,
            estimated_delay_minutes=delay_minutes,
        )
        for op_id in affected_op_ids
    ]
    return ImpactReport(
        incident_id=uuid4(),
        schedule_snapshot_id=uuid4(),
        analysis_reference_time=NOW,
        affected_work_orders=[
            AffectedWorkOrder(
                work_order_id=work_order_id,
                product_name="A",
                due_date=NOW + timedelta(hours=4),
                delivery_risk_level=DeliveryRiskLevel.WARNING,
                remaining_buffer_minutes=60,
                affected_operations=affected,
            )
        ],
        affected_operations=affected,
        affected_resource_ids=["M1"],
        delivery_risk_distribution={DeliveryRiskLevel.WARNING: 1},
        estimated_total_delay_minutes=delay_minutes,
    )


def _op(schedule, operation_id: str) -> Operation:
    assert schedule is not None
    for work_order in schedule.work_orders:
        for operation in work_order.operations:
            if operation.operation_id == operation_id:
                return operation
    raise AssertionError(f"operation not found: {operation_id}")
