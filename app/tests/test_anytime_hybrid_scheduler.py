"""Production algorithm tests for heuristic-first anytime rescheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.enums import DeliveryRiskLevel, StrategyType
from app.models.impact import AffectedOperation, AffectedWorkOrder, ImpactReport
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.services.anytime_hybrid_scheduler import AnytimeHybridScheduler
from app.services.constraint_aware_ssgs import (
    ConstraintAwareSsgsScheduler,
    HeuristicScheduleResult,
)
from app.services.cp_sat_scheduler import CpSatFjspScheduler, CpSatScheduleResult


NOW = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


def test_constraint_aware_ssgs_builds_valid_material_and_calendar_aware_solution() -> None:
    snapshot = _snapshot()
    result = ConstraintAwareSsgsScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
    )

    assert result.is_feasible is True
    assert result.schedule_detail is not None
    first = _operation(result.schedule_detail, "OP-1")
    second = _operation(result.schedule_detail, "OP-2")
    assert first.resource_id == "M2"
    assert first.start_time >= NOW + timedelta(minutes=45)
    assert second.start_time >= first.end_time
    assert "resource_calendar" in result.checked_constraints
    assert "material_availability" in result.checked_constraints


def test_cp_sat_uses_ssgs_warm_start_and_reports_optimality_metadata() -> None:
    snapshot = _snapshot()
    heuristic = ConstraintAwareSsgsScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
    )
    assert heuristic.schedule_detail is not None

    result = CpSatFjspScheduler().solve(
        snapshot=snapshot,
        impact_report=_impact(),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
        timeout_seconds=2,
        initial_solution=heuristic.schedule_detail,
        goal_mode="stability_priority",
    )

    assert result.is_feasible is True
    assert result.hint_applied is True
    assert result.hinted_operation_count == 2
    assert result.best_objective_bound is not None
    assert result.relative_gap is not None
    assert result.relative_gap >= 0
    assert result.solver_log["goal_mode"] == "stability_priority"
    assert result.solver_log["objective_weights"]["shift"] == 8


def test_anytime_solver_returns_validated_heuristic_when_cp_sat_cannot_finish() -> None:
    scheduler = AnytimeHybridScheduler(cp_sat_scheduler=_AlwaysTimeoutCpSat())
    result = scheduler.solve(
        snapshot=_snapshot(),
        impact_report=_impact(),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
        timeout_seconds=1,
    )

    assert result.is_feasible is True
    assert result.status_name == "HEURISTIC_FEASIBLE"
    assert result.schedule_detail is not None
    assert result.solver_log["validated_incumbent"] is True
    assert result.solver_log["incumbent_source"] == "constraint_aware_ssgs"
    assert result.solver_log["algorithm_path"][0] == "constraint_aware_ssgs"


def test_anytime_solver_fails_closed_when_neither_backend_has_valid_solution() -> None:
    snapshot = _snapshot()
    snapshot.raw_data["material_availability"] = [
        {
            "material_id": "MAT-BLOCKED",
            "operation_ids": ["OP-1"],
            "available_quantity": 0,
            "required_quantity": 1,
        }
    ]
    result = AnytimeHybridScheduler(cp_sat_scheduler=_AlwaysTimeoutCpSat()).solve(
        snapshot=snapshot,
        impact_report=_impact(),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
        timeout_seconds=1,
    )

    assert result.is_feasible is False
    assert result.schedule_detail is None
    assert result.status_name == "NO_VALIDATED_INCUMBENT"


def test_anytime_solver_can_recover_when_heuristic_budget_is_exhausted() -> None:
    result = AnytimeHybridScheduler(
        heuristic_scheduler=_AlwaysTimeoutHeuristic(),
        max_alns_iterations=0,
    ).solve(
        snapshot=_snapshot(),
        impact_report=_impact(),
        strategy_type=StrategyType.GLOBAL_RESCHEDULE,
        affected_op_ids=["OP-1"],
        frozen_operation_ids=[],
        timeout_seconds=2,
    )

    assert result.is_feasible is True
    assert result.solver_log["incumbent_source"] == "cp_sat"
    assert result.solver_log["heuristic_status"] == "HEURISTIC_TIMEOUT"
    assert result.solver_log["cp_sat_hint_applied"] is False


class _AlwaysTimeoutCpSat:
    def solve(self, **_: object) -> CpSatScheduleResult:
        return CpSatScheduleResult(
            schedule_detail=None,
            status_name="UNKNOWN",
            is_feasible=False,
        )


class _AlwaysTimeoutHeuristic:
    def solve(self, **_: object) -> HeuristicScheduleResult:
        return HeuristicScheduleResult(
            schedule_detail=None,
            status_name="HEURISTIC_TIMEOUT",
            is_feasible=False,
            blockers=["heuristic_time_budget_exhausted"],
        )


def _snapshot() -> ScheduleSnapshot:
    return ScheduleSnapshot(
        captured_at=NOW,
        workshop_id="WS-HYBRID",
        raw_data={
            "resources": [
                {"resource_id": "M1", "name": "M1", "capabilities": ["cnc"]},
                {"resource_id": "M2", "name": "M2", "capabilities": ["cnc"]},
            ],
            "work_orders": [
                {
                    "work_order_id": "WO-1",
                    "product_family": "A",
                    "operations": [
                        {
                            "operation_id": "OP-1",
                            "eligible_resources": ["M1", "M2"],
                            "product_family": "A",
                            "raw_payload": {},
                        },
                        {
                            "operation_id": "OP-2",
                            "eligible_resources": ["M1", "M2"],
                            "product_family": "A",
                            "raw_payload": {},
                        },
                    ],
                }
            ],
            "resource_calendar": [
                {
                    "resource_id": "M1",
                    "window_start": NOW.isoformat(),
                    "window_end": (NOW + timedelta(hours=2)).isoformat(),
                    "availability_type": "unavailable",
                }
            ],
            "material_availability": [
                {
                    "material_id": "MAT-1",
                    "operation_ids": ["OP-1"],
                    "available_quantity": 1,
                    "required_quantity": 1,
                    "available_at": (NOW + timedelta(minutes=45)).isoformat(),
                }
            ],
        },
        work_orders=[
            WorkOrder(
                work_order_id="WO-1",
                product_name="A",
                due_date=NOW + timedelta(hours=4),
                priority=3,
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
                        resource_id="M1",
                        required_capabilities=["cnc"],
                        start_time=NOW + timedelta(minutes=30),
                        end_time=NOW + timedelta(minutes=60),
                        predecessor_ids=["OP-1"],
                    ),
                ],
            )
        ],
    )


def _impact() -> ImpactReport:
    return ImpactReport(
        incident_id=uuid4(),
        schedule_snapshot_id=uuid4(),
        analysis_reference_time=NOW,
        affected_work_orders=[
            AffectedWorkOrder(
                work_order_id="WO-1",
                product_name="A",
                due_date=NOW + timedelta(hours=4),
                remaining_buffer_minutes=30,
                delivery_risk_level=DeliveryRiskLevel.WARNING,
            )
        ],
        affected_operations=[
            AffectedOperation(
                operation_id="OP-1",
                work_order_id="WO-1",
                resource_id="M1",
                is_direct=True,
                estimated_delay_minutes=10,
            )
        ],
    )


def _operation(schedule, operation_id: str) -> Operation:
    return next(
        op
        for wo in schedule.work_orders
        for op in wo.operations
        if op.operation_id == operation_id
    )
