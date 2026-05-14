"""Tests for the OR-Tools CP-SAT FJSP scheduling backend."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.enums import DeliveryRiskLevel, StrategyType
from app.models.impact import AffectedOperation, AffectedWorkOrder, ImpactReport
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.services.cp_sat_scheduler import CpSatFjspScheduler


NOW = datetime(2026, 5, 7, 8, 0, 0, tzinfo=timezone.utc)


def _snapshot_with_alternative_machine() -> ScheduleSnapshot:
    return ScheduleSnapshot(
        snapshot_id=uuid4(),
        captured_at=NOW,
        workshop_id="WS-CP",
        raw_data={
            "resources": [
                {
                    "resource_id": "machine-A",
                    "name": "Machine A",
                    "capabilities": ["milling"],
                },
                {
                    "resource_id": "machine-B",
                    "name": "Machine B",
                    "capabilities": ["milling"],
                },
            ],
            "work_orders": [
                {
                    "work_order_id": "wo-affected",
                    "operations": [
                        {
                            "operation_id": "op-affected",
                            "eligible_resources": ["machine-A", "machine-B"],
                        }
                    ],
                }
            ],
        },
        work_orders=[
            WorkOrder(
                work_order_id="wo-affected",
                product_name="Affected",
                due_date=NOW + timedelta(hours=8),
                priority=2,
                operations=[
                    Operation(
                        operation_id="op-affected",
                        work_order_id="wo-affected",
                        resource_id="machine-A",
                        required_capabilities=["milling"],
                        start_time=NOW,
                        end_time=NOW + timedelta(hours=2),
                    ),
                ],
            ),
            WorkOrder(
                work_order_id="wo-fixed",
                product_name="Fixed",
                due_date=NOW + timedelta(hours=8),
                priority=1,
                operations=[
                    Operation(
                        operation_id="op-fixed",
                        work_order_id="wo-fixed",
                        resource_id="machine-A",
                        required_capabilities=["milling"],
                        start_time=NOW + timedelta(minutes=30),
                        end_time=NOW + timedelta(hours=3),
                    ),
                ],
            ),
        ],
    )


def _impact(op_id: str = "op-affected", delay: float = 30.0) -> ImpactReport:
    affected = [
        AffectedOperation(
            operation_id=op_id,
            work_order_id="wo-affected",
            resource_id="machine-A",
            is_direct=True,
            estimated_delay_minutes=delay,
        )
    ]
    return ImpactReport(
        incident_id=uuid4(),
        schedule_snapshot_id=uuid4(),
        analysis_reference_time=NOW,
        affected_operations=affected,
        affected_work_orders=[
            AffectedWorkOrder(
                work_order_id="wo-affected",
                product_name="Affected",
                due_date=NOW + timedelta(hours=8),
                delivery_risk_level=DeliveryRiskLevel.WARNING,
                remaining_buffer_minutes=120,
                affected_operations=affected,
            )
        ],
        affected_resource_ids=["machine-A"],
        delivery_risk_distribution={DeliveryRiskLevel.WARNING: 1},
        estimated_total_delay_minutes=delay,
    )


def test_cp_sat_switches_to_alternative_resource_to_avoid_overlap():
    scheduler = CpSatFjspScheduler()
    snapshot = _snapshot_with_alternative_machine()

    result = scheduler.solve(
        snapshot=snapshot,
        impact_report=_impact(delay=30),
        strategy_type=StrategyType.LOCAL_REPAIR,
        affected_op_ids=["op-affected"],
        frozen_operation_ids=[],
        timeout_seconds=5,
    )

    assert result.is_feasible is True
    assert result.schedule_detail is not None
    affected = next(
        op
        for wo in result.schedule_detail.work_orders
        for op in wo.operations
        if op.operation_id == "op-affected"
    )
    fixed = next(
        op
        for wo in result.schedule_detail.work_orders
        for op in wo.operations
        if op.operation_id == "op-fixed"
    )

    assert affected.resource_id == "machine-B"
    assert affected.start_time >= NOW + timedelta(minutes=30)
    assert fixed.resource_id == "machine-A"
    assert fixed.start_time == NOW + timedelta(minutes=30)


def test_cp_sat_respects_frozen_operations():
    scheduler = CpSatFjspScheduler()
    snapshot = _snapshot_with_alternative_machine()

    result = scheduler.solve(
        snapshot=snapshot,
        impact_report=_impact(op_id="op-fixed", delay=60),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["op-fixed"],
        frozen_operation_ids=["op-fixed"],
        timeout_seconds=5,
    )

    assert result.is_feasible is True
    assert result.schedule_detail is not None
    frozen = next(
        op
        for wo in result.schedule_detail.work_orders
        for op in wo.operations
        if op.operation_id == "op-fixed"
    )
    assert frozen.resource_id == "machine-A"
    assert frozen.start_time == NOW + timedelta(minutes=30)
    assert frozen.end_time == NOW + timedelta(hours=3)

