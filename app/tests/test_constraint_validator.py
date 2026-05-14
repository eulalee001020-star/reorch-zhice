"""Tests for the standalone ConstraintValidator module.

Covers:
- Equipment capability constraint (Req 20.1)
- Process order constraint (Req 20.2)
- Resource mutual exclusion constraint (Req 20.3)
- Material availability constraint (Req 20.4)
- Local-repair invariance (Req 20.5)
- Microadjustment re-validation (Req 20.6)
- ConstraintValidationReport output structure (Req 20.7)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.enums import StrategyType
from app.models.schedule import (
    Operation,
    Resource,
    ScheduleDetail,
    ScheduleSnapshot,
    WorkOrder,
)
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.services.constraint_validator import ConstraintValidator

NOW = datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc)


# ── Helpers ─────────────────────────────────────────────────────────


def _op(
    op_id: str,
    wo_id: str = "wo-1",
    resource_id: str = "machine-A",
    start_offset_h: float = 0,
    duration_h: float = 1,
    predecessors: list[str] | None = None,
    successors: list[str] | None = None,
    required_caps: list[str] | None = None,
    is_affected: bool = False,
    is_adjusted: bool = False,
) -> Operation:
    return Operation(
        operation_id=op_id,
        work_order_id=wo_id,
        resource_id=resource_id,
        start_time=NOW + timedelta(hours=start_offset_h),
        end_time=NOW + timedelta(hours=start_offset_h + duration_h),
        predecessor_ids=predecessors or [],
        successor_ids=successors or [],
        required_capabilities=required_caps or [],
        is_affected=is_affected,
        is_adjusted=is_adjusted,
    )


def _schedule(
    ops: list[Operation],
    resources: list[Resource] | None = None,
) -> ScheduleDetail:
    # Group ops by work_order_id
    wo_map: dict[str, list[Operation]] = {}
    for op in ops:
        wo_map.setdefault(op.work_order_id, []).append(op)
    work_orders = [
        WorkOrder(
            work_order_id=wo_id,
            product_name=f"Product-{wo_id}",
            due_date=NOW + timedelta(days=5),
            operations=wo_ops,
        )
        for wo_id, wo_ops in wo_map.items()
    ]
    return ScheduleDetail(
        work_orders=work_orders,
        resources=resources or [],
    )


def _snapshot_from_schedule(schedule: ScheduleDetail) -> ScheduleSnapshot:
    return ScheduleSnapshot(
        snapshot_id=uuid4(),
        captured_at=NOW,
        workshop_id="workshop-1",
        work_orders=[wo.model_copy(deep=True) for wo in schedule.work_orders],
    )


def _make_candidate_plan(
    schedule: ScheduleDetail,
    strategy_type: str = "local_repair",
) -> CandidatePlan:
    return CandidatePlan(
        plan_id=uuid4(),
        strategy_type=strategy_type,
        schedule_detail=schedule,
        gantt_version="1.0",
        solver_chain=SolverChain(
            strategy_type=strategy_type,
            rule_selection="test",
            neighborhood_selection="test",
            repair_policy="balanced",
            solver_name="test",
            key_parameters={},
            search_budget_seconds=30.0,
            constraint_validation_result="feasible",
        ),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=1.0,
            iteration_count=5,
            objective_trajectory=[100.0, 90.0],
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=True, violations=[], checked_constraints=[]
        ),
    )


# ── Tests ───────────────────────────────────────────────────────────


class TestEquipmentCapability:
    """Req 20.1: op.required_capabilities ⊆ assigned resource capabilities."""

    def test_passes_when_capabilities_match(self):
        ops = [
            _op("op-1", required_caps=["cutting"]),
        ]
        resources = [Resource(resource_id="machine-A", name="A", capabilities=["cutting", "welding"])]
        sched = _schedule(ops, resources)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.LOCAL_REPAIR, [])

        assert report.is_feasible
        assert "equipment_capability" in report.checked_constraints

    def test_fails_when_capability_missing(self):
        ops = [
            _op("op-1", required_caps=["cutting", "painting"]),
        ]
        resources = [Resource(resource_id="machine-A", name="A", capabilities=["cutting"])]
        sched = _schedule(ops, resources)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.LOCAL_REPAIR, [])

        assert not report.is_feasible
        assert any(v.constraint_type == "equipment_capability" for v in report.violations)
        violation = next(v for v in report.violations if v.constraint_type == "equipment_capability")
        assert "painting" in violation.detail

    def test_passes_when_no_required_capabilities(self):
        ops = [_op("op-1", required_caps=[])]
        resources = [Resource(resource_id="machine-A", name="A", capabilities=[])]
        sched = _schedule(ops, resources)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.LOCAL_REPAIR, [])

        assert report.is_feasible

    def test_uses_override_capabilities(self):
        ops = [_op("op-1", required_caps=["cutting"])]
        sched = _schedule(ops, resources=[])
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        # Without override, no resource caps → violation
        report_fail = validator.validate_constraints(sched, snap, StrategyType.LOCAL_REPAIR, [])
        assert any(v.constraint_type == "equipment_capability" for v in report_fail.violations)

        # With override providing the capability → passes
        report_pass = validator.validate_constraints(
            sched, snap, StrategyType.LOCAL_REPAIR, [],
            resource_capabilities={"machine-A": ["cutting"]},
        )
        cap_violations = [v for v in report_pass.violations if v.constraint_type == "equipment_capability"]
        assert len(cap_violations) == 0


class TestProcessOrder:
    """Req 20.2: predecessor end_time ≤ successor start_time."""

    def test_passes_valid_order(self):
        ops = [
            _op("op-1", start_offset_h=0, duration_h=1, successors=["op-2"]),
            _op("op-2", start_offset_h=1, duration_h=1, predecessors=["op-1"], resource_id="machine-B"),
        ]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.GLOBAL_RESCHEDULE, [])

        order_violations = [v for v in report.violations if v.constraint_type == "process_order"]
        assert len(order_violations) == 0

    def test_fails_when_predecessor_overlaps_successor(self):
        ops = [
            _op("op-1", start_offset_h=0, duration_h=2, successors=["op-2"]),
            _op("op-2", start_offset_h=1, duration_h=1, predecessors=["op-1"], resource_id="machine-B"),
        ]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.GLOBAL_RESCHEDULE, [])

        order_violations = [v for v in report.violations if v.constraint_type == "process_order"]
        assert len(order_violations) == 1
        assert "op-1" in order_violations[0].detail


class TestResourceMutualExclusion:
    """Req 20.3: no overlapping ops on same resource at same time."""

    def test_passes_no_overlap(self):
        ops = [
            _op("op-1", resource_id="machine-A", start_offset_h=0, duration_h=1),
            _op("op-2", resource_id="machine-A", start_offset_h=1, duration_h=1, wo_id="wo-2"),
        ]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.GLOBAL_RESCHEDULE, [])

        excl_violations = [v for v in report.violations if v.constraint_type == "resource_mutual_exclusion"]
        assert len(excl_violations) == 0

    def test_fails_when_ops_overlap_on_same_resource(self):
        ops = [
            _op("op-1", resource_id="machine-A", start_offset_h=0, duration_h=2),
            _op("op-2", resource_id="machine-A", start_offset_h=1, duration_h=1, wo_id="wo-2"),
        ]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.GLOBAL_RESCHEDULE, [])

        excl_violations = [v for v in report.violations if v.constraint_type == "resource_mutual_exclusion"]
        assert len(excl_violations) == 1

    def test_different_resources_no_conflict(self):
        ops = [
            _op("op-1", resource_id="machine-A", start_offset_h=0, duration_h=2),
            _op("op-2", resource_id="machine-B", start_offset_h=0, duration_h=2, wo_id="wo-2"),
        ]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.GLOBAL_RESCHEDULE, [])

        excl_violations = [v for v in report.violations if v.constraint_type == "resource_mutual_exclusion"]
        assert len(excl_violations) == 0


class TestMaterialAvailability:
    """Req 20.4 (MVP): start_time > epoch 0."""

    def test_passes_normal_start_time(self):
        ops = [_op("op-1", start_offset_h=1)]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.GLOBAL_RESCHEDULE, [])

        mat_violations = [v for v in report.violations if v.constraint_type == "material_availability"]
        assert len(mat_violations) == 0

    def test_fails_epoch_zero_start_time(self):
        op = Operation(
            operation_id="op-bad",
            work_order_id="wo-1",
            resource_id="machine-A",
            start_time=datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(1970, 1, 1, 1, 0, 0, tzinfo=timezone.utc),
        )
        sched = _schedule([op])
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(sched, snap, StrategyType.GLOBAL_RESCHEDULE, [])

        mat_violations = [v for v in report.violations if v.constraint_type == "material_availability"]
        assert len(mat_violations) == 1


class TestLocalRepairInvariance:
    """Req 20.5: unaffected ops must match snapshot exactly."""

    def test_passes_when_unaffected_ops_unchanged(self):
        ops = [
            _op("op-1", start_offset_h=0, is_affected=True, is_adjusted=True),
            _op("op-2", resource_id="machine-B", start_offset_h=1),
        ]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(
            sched, snap, StrategyType.LOCAL_REPAIR, ["op-1"]
        )

        inv_violations = [v for v in report.violations if v.constraint_type == "local_repair_invariance"]
        assert len(inv_violations) == 0

    def test_fails_when_unaffected_op_modified(self):
        ops_original = [
            _op("op-1", start_offset_h=0, is_affected=True, is_adjusted=True),
            _op("op-2", resource_id="machine-B", start_offset_h=1),
        ]
        snap = _snapshot_from_schedule(_schedule(ops_original))

        # Modify op-2 (unaffected) in the new schedule
        ops_modified = [
            _op("op-1", start_offset_h=0, is_affected=True, is_adjusted=True),
            _op("op-2", resource_id="machine-B", start_offset_h=2),  # shifted
        ]
        sched = _schedule(ops_modified)
        validator = ConstraintValidator()

        report = validator.validate_constraints(
            sched, snap, StrategyType.LOCAL_REPAIR, ["op-1"]
        )

        inv_violations = [v for v in report.violations if v.constraint_type == "local_repair_invariance"]
        assert len(inv_violations) == 1
        assert "op-2" in inv_violations[0].detail

    def test_skipped_for_global_reschedule(self):
        ops_original = [
            _op("op-1", start_offset_h=0),
            _op("op-2", resource_id="machine-B", start_offset_h=1),
        ]
        snap = _snapshot_from_schedule(_schedule(ops_original))

        ops_modified = [
            _op("op-1", start_offset_h=0),
            _op("op-2", resource_id="machine-B", start_offset_h=3),
        ]
        sched = _schedule(ops_modified)
        validator = ConstraintValidator()

        report = validator.validate_constraints(
            sched, snap, StrategyType.GLOBAL_RESCHEDULE, ["op-1"]
        )

        assert "local_repair_invariance" not in report.checked_constraints

    def test_detects_resource_change_on_unaffected_op(self):
        ops_original = [
            _op("op-1", start_offset_h=0, is_affected=True, is_adjusted=True),
            _op("op-2", resource_id="machine-B", start_offset_h=1),
        ]
        snap = _snapshot_from_schedule(_schedule(ops_original))

        ops_modified = [
            _op("op-1", start_offset_h=0, is_affected=True, is_adjusted=True),
            _op("op-2", resource_id="machine-C", start_offset_h=1),  # resource changed
        ]
        sched = _schedule(ops_modified)
        validator = ConstraintValidator()

        report = validator.validate_constraints(
            sched, snap, StrategyType.LOCAL_REPAIR, ["op-1"]
        )

        inv_violations = [v for v in report.violations if v.constraint_type == "local_repair_invariance"]
        assert len(inv_violations) == 1


class TestValidateMicroadjustment:
    """Req 20.6: re-run all constraints on adjusted schedule."""

    def test_passes_valid_microadjustment(self):
        ops = [
            _op("op-1", start_offset_h=0, is_affected=True, is_adjusted=True),
            _op("op-2", resource_id="machine-B", start_offset_h=1),
        ]
        resources = [
            Resource(resource_id="machine-A", name="A", capabilities=[]),
            Resource(resource_id="machine-B", name="B", capabilities=[]),
        ]
        sched = _schedule(ops, resources)
        snap = _snapshot_from_schedule(sched)
        original_plan = _make_candidate_plan(sched)

        # Adjusted schedule is identical → should pass
        adjusted = sched.model_copy(deep=True)
        validator = ConstraintValidator()

        report = validator.validate_microadjustment(original_plan, adjusted, snap)

        assert report.is_feasible
        assert len(report.checked_constraints) >= 4  # all constraint types checked

    def test_fails_microadjustment_with_violation(self):
        ops = [
            _op("op-1", start_offset_h=0, duration_h=1, successors=["op-2"],
                 is_affected=True, is_adjusted=True),
            _op("op-2", start_offset_h=1, duration_h=1, predecessors=["op-1"],
                 resource_id="machine-B"),
        ]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        original_plan = _make_candidate_plan(sched)

        # Create adjusted schedule with process order violation
        adjusted_ops = [
            _op("op-1", start_offset_h=0, duration_h=3, successors=["op-2"],
                 is_affected=True, is_adjusted=True),
            _op("op-2", start_offset_h=1, duration_h=1, predecessors=["op-1"],
                 resource_id="machine-B"),
        ]
        adjusted = _schedule(adjusted_ops)
        validator = ConstraintValidator()

        report = validator.validate_microadjustment(original_plan, adjusted, snap)

        assert not report.is_feasible
        assert any(v.constraint_type == "process_order" for v in report.violations)


class TestReportStructure:
    """Req 20.7: ConstraintValidationReport output structure."""

    def test_report_has_required_fields(self):
        ops = [_op("op-1")]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(
            sched, snap, StrategyType.GLOBAL_RESCHEDULE, []
        )

        assert isinstance(report, ConstraintValidationReport)
        assert isinstance(report.is_feasible, bool)
        assert isinstance(report.violations, list)
        assert isinstance(report.checked_constraints, list)

    def test_all_core_constraints_checked_for_local_repair(self):
        ops = [_op("op-1")]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(
            sched, snap, StrategyType.LOCAL_REPAIR, []
        )

        expected = {
            "equipment_capability",
            "process_order",
            "resource_mutual_exclusion",
            "material_availability",
            "local_repair_invariance",
        }
        assert expected == set(report.checked_constraints)

    def test_four_constraints_checked_for_non_local_repair(self):
        ops = [_op("op-1")]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(
            sched, snap, StrategyType.GLOBAL_RESCHEDULE, []
        )

        expected = {
            "equipment_capability",
            "process_order",
            "resource_mutual_exclusion",
            "material_availability",
        }
        assert expected == set(report.checked_constraints)

    def test_strategy_type_string_accepted(self):
        ops = [_op("op-1")]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(
            sched, snap, "local_repair", []
        )

        assert "local_repair_invariance" in report.checked_constraints

    def test_multiple_violations_reported(self):
        # Two ops on same resource overlapping + process order violation
        ops = [
            _op("op-1", resource_id="machine-A", start_offset_h=0, duration_h=3,
                 successors=["op-2"]),
            _op("op-2", resource_id="machine-A", start_offset_h=1, duration_h=1,
                 predecessors=["op-1"], wo_id="wo-2"),
        ]
        sched = _schedule(ops)
        snap = _snapshot_from_schedule(sched)
        validator = ConstraintValidator()

        report = validator.validate_constraints(
            sched, snap, StrategyType.GLOBAL_RESCHEDULE, []
        )

        assert not report.is_feasible
        types = {v.constraint_type for v in report.violations}
        assert "process_order" in types
        assert "resource_mutual_exclusion" in types
