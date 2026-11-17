"""Recovery context, right-shift baseline and baseline-based impact analysis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import DeliveryRiskLevel, IncidentSeverity, IncidentStatus, IncidentType
from app.models.incident import Incident
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.services.intake.impact_analysis_engine import ImpactAnalysisEngine
from app.services.intake.recovery_context import (
    apply_recovery_context,
    build_recovery_context,
    incident_duration_minutes,
)
from app.services.intake.recovery_planning import PreparedRecovery, baseline_candidate
from app.services.intake.right_shift import right_shift

T0 = datetime(2026, 5, 14, 8, 0, tzinfo=UTC)


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def _op(op_id, wo, resource, start, hours, preds=()) -> Operation:
    return Operation(
        operation_id=op_id,
        work_order_id=wo,
        resource_id=resource,
        start_time=at(start),
        end_time=at(start + hours),
        predecessor_ids=list(preds),
    )


def _snapshot() -> ScheduleSnapshot:
    """Two machines. M-A runs A1, B1, C1 back to back; M-B finishes each order."""
    return ScheduleSnapshot(
        captured_at=at(2),
        workshop_id="W",
        work_orders=[
            WorkOrder(
                work_order_id="A",
                product_name="a",
                due_date=at(5),
                priority=1,
                operations=[_op("A1", "A", "M-A", 0, 1), _op("A2", "A", "M-B", 1, 1, ["A1"])],
            ),
            WorkOrder(
                work_order_id="B",
                product_name="b",
                due_date=at(6),
                priority=1,
                operations=[_op("B1", "B", "M-A", 1.5, 1), _op("B2", "B", "M-B", 3, 1, ["B1"])],
            ),
            WorkOrder(
                work_order_id="C",
                product_name="c",
                due_date=at(12),
                priority=1,
                operations=[_op("C1", "C", "M-A", 3, 1), _op("C2", "C", "M-B", 4, 1, ["C1"])],
            ),
        ],
    )


def _incident(occurred: float, *, minutes: int | None = 120, description: str = "") -> Incident:
    payload = {"estimated_duration_minutes": minutes} if minutes is not None else None
    return Incident(
        incident_type=IncidentType.EQUIPMENT_FAILURE,
        occurred_at=at(occurred),
        resource_id="M-A",
        report_source="MES",
        description=description,
        severity=IncidentSeverity.P3_MEDIUM,
        status=IncidentStatus.PENDING_ANALYSIS,
        raw_payload=payload,
    )


# ── duration ────────────────────────────────────────────────────────


def test_duration_prefers_payload_then_description() -> None:
    assert incident_duration_minutes(_incident(2, minutes=90)) == 90
    assert (
        incident_duration_minutes(_incident(2, minutes=None, description="预计维修 3 小时")) == 180
    )
    assert incident_duration_minutes(_incident(2, minutes=None, description="停了")) is None


# ── context ─────────────────────────────────────────────────────────


def test_history_is_frozen_and_the_running_job_on_the_failed_machine_is_interrupted() -> None:
    context = build_recovery_context(_incident(2), _snapshot())
    assert context is not None
    # A1 finished, A2 started at hour 1 on the healthy machine: both history.
    assert context.frozen_operation_ids == ["A1", "A2"]
    # B1 was running on M-A when it failed at hour 2.
    assert context.interrupted_operation_ids == ["B1"]
    window = context.resource_windows[0]
    assert window["resource_id"] == "M-A"
    assert window["availability_type"] == "unavailable"
    assert window["window_start"] == at(2).isoformat()
    assert window["window_end"] == at(4).isoformat()
    released = {row["operation_id"] for row in context.release_rows}
    assert released == {"B1", "B2", "C1", "C2"}


def test_unknown_repair_time_gives_no_window_and_says_so() -> None:
    context = build_recovery_context(_incident(2, minutes=None), _snapshot())
    assert context is not None
    assert context.resource_windows == []
    assert context.interrupted_operation_ids == []
    assert context.notes == ["repair_time_unknown:no_resource_window"]


def test_no_context_when_nothing_is_left_to_replan() -> None:
    assert build_recovery_context(_incident(48), _snapshot()) is None


def test_applied_snapshot_carries_rows_and_keeps_source_rows() -> None:
    snapshot = _snapshot()
    snapshot.raw_data = {"resource_calendar": [{"resource_id": "M-B", "kept": True}]}
    context = build_recovery_context(_incident(2), snapshot)
    applied = apply_recovery_context(snapshot, context)
    assert applied.raw_data["resource_calendar"][0] == {"resource_id": "M-B", "kept": True}
    assert applied.raw_data["resource_calendar"][1]["resource_id"] == "M-A"
    assert applied.raw_data["recovery_context"]["decision_time"] == at(2).isoformat()
    assert snapshot.raw_data == {"resource_calendar": [{"resource_id": "M-B", "kept": True}]}


# ── right shift ─────────────────────────────────────────────────────


def _shift(occurred: float = 2):
    snapshot = _snapshot()
    context = build_recovery_context(_incident(occurred), snapshot)
    return right_shift(
        snapshot,
        decision_time=context.decision_time,
        resource_windows=context.windows_by_resource(),
        material_release=context.material_release_by_operation(),
        frozen_operation_ids=set(context.frozen_operation_ids),
    )


def test_right_shift_pushes_only_as_far_as_forced() -> None:
    shifted = _shift()
    assert shifted["A1"].cause == "history" and shifted["A1"].delay_minutes == 0
    # B1 restarts when the machine is back at hour 4.
    assert shifted["B1"].new_start == at(4)
    assert shifted["B1"].cause == "resource_window"
    # B2 follows its predecessor: 5 instead of 3.
    assert shifted["B2"].new_start == at(5)
    assert shifted["B2"].cause == "predecessor"
    # C1 queues behind B1 on the same machine.
    assert shifted["C1"].new_start == at(5)
    assert shifted["C1"].cause == "resource_queue"
    assert shifted["C2"].new_start == at(6)


def test_right_shift_respects_material_release() -> None:
    snapshot = _snapshot()
    shifted = right_shift(
        snapshot,
        decision_time=at(0),
        resource_windows={},
        material_release={"C1": at(7), "B1": None},
        frozen_operation_ids=set(),
    )
    assert shifted["C1"].new_start == at(7)
    assert shifted["C1"].cause == "material"
    assert shifted["B1"].cause == "unresolved_material"
    assert shifted["B1"].new_start == at(5)  # end of the current plan


# ── impact against the baseline ─────────────────────────────────────


@pytest.mark.asyncio
async def test_impact_counts_each_work_order_once_and_grades_risk() -> None:
    snapshot = _snapshot()
    incident = _incident(2)
    context = build_recovery_context(incident, snapshot)
    report = await ImpactAnalysisEngine().analyze_recovery(incident, snapshot, context)

    by_wo = {wo.work_order_id: wo for wo in report.affected_work_orders}
    assert set(by_wo) == {"B", "C"}
    # B: planned done at 4, now 6, due 6 -> on the edge, buffer 0 < delay 120.
    assert by_wo["B"].delivery_risk_level == DeliveryRiskLevel.WARNING
    assert by_wo["B"].remaining_buffer_minutes == 0
    # C: planned done at 5, now 7, due 12 -> plenty of slack left.
    assert by_wo["C"].delivery_risk_level == DeliveryRiskLevel.SAFE
    assert report.estimated_total_delay_minutes == 240
    assert report.analysis_reference_time == at(2)
    direct = [op.operation_id for op in report.affected_operations if op.is_direct]
    assert direct == ["B1"]


@pytest.mark.asyncio
async def test_breach_when_waiting_passes_the_due_date() -> None:
    snapshot = _snapshot()
    incident = _incident(2, minutes=240)
    context = build_recovery_context(incident, snapshot)
    report = await ImpactAnalysisEngine().analyze_recovery(incident, snapshot, context)
    by_wo = {wo.work_order_id: wo for wo in report.affected_work_orders}
    assert by_wo["B"].delivery_risk_level == DeliveryRiskLevel.BREACH


# ── baseline candidate ──────────────────────────────────────────────


def test_baseline_candidate_is_feasible_and_keeps_machines() -> None:
    snapshot = _snapshot()
    context = build_recovery_context(_incident(2), snapshot)
    prepared = PreparedRecovery(context=context, snapshot=apply_recovery_context(snapshot, context))
    plan = baseline_candidate(prepared)
    assert plan is not None
    assert plan.feasibility_status == "feasible"
    assert plan.solver_chain.solver_name == "right_shift_baseline"
    original = {op.operation_id: op for wo in snapshot.work_orders for op in wo.operations}
    for work_order in plan.schedule_detail.work_orders:
        for operation in work_order.operations:
            assert operation.resource_id == original[operation.operation_id].resource_id
            assert operation.start_time >= original[operation.operation_id].start_time
