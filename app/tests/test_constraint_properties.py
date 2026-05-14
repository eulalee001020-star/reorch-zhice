"""Property-based tests for ConstraintValidator using Hypothesis.

Validates:
- Equipment capability constraint (Req 20.1)
- Process order constraint (Req 20.2)
- Resource mutual exclusion constraint (Req 20.3)
- Local-repair invariance (Req 20.5)

**Validates: Requirements 20.1, 20.2, 20.3, 20.5**
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import hypothesis.strategies as st
from hypothesis import given, settings

from app.models.enums import StrategyType
from app.models.schedule import (
    Operation,
    Resource,
    ScheduleDetail,
    ScheduleSnapshot,
    WorkOrder,
)
from app.services.constraint_validator import ConstraintValidator

# ── Constants ───────────────────────────────────────────────────────

BASE_TIME = datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
CAPABILITIES_POOL = ["cutting", "welding", "painting", "drilling", "milling"]
RESOURCE_IDS = ["machine-A", "machine-B", "machine-C"]

validator = ConstraintValidator()


# ── Strategies ──────────────────────────────────────────────────────


@st.composite
def capability_subset_strategy(draw):
    """Draw a non-empty subset of capabilities from the pool."""
    return draw(
        st.lists(st.sampled_from(CAPABILITIES_POOL), min_size=1, max_size=3, unique=True)
    )


@st.composite
def valid_capability_schedule(draw):
    """Generate a schedule where every op's required_capabilities ⊆ resource capabilities.

    Returns (ScheduleDetail, resource_capabilities_map).
    """
    n_ops = draw(st.integers(min_value=1, max_value=5))
    ops = []
    resources_map: dict[str, list[str]] = {}

    for i in range(n_ops):
        res_id = draw(st.sampled_from(RESOURCE_IDS))
        # Ensure resource has some capabilities
        if res_id not in resources_map:
            resources_map[res_id] = draw(capability_subset_strategy())
        res_caps = resources_map[res_id]
        # Required caps are a subset of resource caps
        req_caps = draw(
            st.lists(st.sampled_from(res_caps), min_size=0, max_size=len(res_caps), unique=True)
        )
        start_h = draw(st.floats(min_value=0, max_value=20, allow_nan=False, allow_infinity=False))
        dur_h = draw(st.floats(min_value=0.5, max_value=4, allow_nan=False, allow_infinity=False))
        ops.append(
            Operation(
                operation_id=f"op-{i}",
                work_order_id=f"wo-{i}",
                resource_id=res_id,
                start_time=BASE_TIME + timedelta(hours=start_h),
                end_time=BASE_TIME + timedelta(hours=start_h + dur_h),
                required_capabilities=req_caps,
            )
        )

    resources = [
        Resource(resource_id=rid, name=rid, capabilities=caps)
        for rid, caps in resources_map.items()
    ]
    schedule = ScheduleDetail(
        work_orders=[
            WorkOrder(
                work_order_id=op.work_order_id,
                product_name=f"P-{op.work_order_id}",
                due_date=BASE_TIME + timedelta(days=5),
                operations=[op],
            )
            for op in ops
        ],
        resources=resources,
    )
    return schedule, resources_map


@st.composite
def invalid_capability_schedule(draw):
    """Generate a schedule where at least one op has a capability NOT in its resource.

    Returns (ScheduleDetail, resource_capabilities_map).
    """
    n_ops = draw(st.integers(min_value=1, max_value=5))
    ops = []
    resources_map: dict[str, list[str]] = {}

    # Pick which op will have the violation
    violating_idx = draw(st.integers(min_value=0, max_value=n_ops - 1))

    for i in range(n_ops):
        res_id = draw(st.sampled_from(RESOURCE_IDS))
        if res_id not in resources_map:
            resources_map[res_id] = draw(capability_subset_strategy())
        res_caps = resources_map[res_id]

        if i == violating_idx:
            # Pick a capability NOT in the resource
            missing_caps = [c for c in CAPABILITIES_POOL if c not in res_caps]
            if not missing_caps:
                # All caps are in resource; remove one from resource to create gap
                removed = res_caps.pop()
                missing_caps = [removed]
                resources_map[res_id] = res_caps
            extra_cap = draw(st.sampled_from(missing_caps))
            req_caps = [extra_cap]
        else:
            req_caps = draw(
                st.lists(st.sampled_from(res_caps), min_size=0, max_size=len(res_caps), unique=True)
            ) if res_caps else []

        start_h = draw(st.floats(min_value=0, max_value=20, allow_nan=False, allow_infinity=False))
        dur_h = draw(st.floats(min_value=0.5, max_value=4, allow_nan=False, allow_infinity=False))
        ops.append(
            Operation(
                operation_id=f"op-{i}",
                work_order_id=f"wo-{i}",
                resource_id=res_id,
                start_time=BASE_TIME + timedelta(hours=start_h),
                end_time=BASE_TIME + timedelta(hours=start_h + dur_h),
                required_capabilities=req_caps,
            )
        )

    resources = [
        Resource(resource_id=rid, name=rid, capabilities=caps)
        for rid, caps in resources_map.items()
    ]
    schedule = ScheduleDetail(
        work_orders=[
            WorkOrder(
                work_order_id=op.work_order_id,
                product_name=f"P-{op.work_order_id}",
                due_date=BASE_TIME + timedelta(days=5),
                operations=[op],
            )
            for op in ops
        ],
        resources=resources,
    )
    return schedule, resources_map


@st.composite
def valid_process_order_schedule(draw):
    """Generate a schedule where all predecessor end_times <= successor start_times."""
    n_ops = draw(st.integers(min_value=2, max_value=5))
    ops = []
    current_time = 0.0

    for i in range(n_ops):
        dur_h = draw(st.floats(min_value=0.5, max_value=2, allow_nan=False, allow_infinity=False))
        gap = draw(st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False))
        start_h = current_time + gap
        end_h = start_h + dur_h

        preds = [f"op-{i-1}"] if i > 0 else []
        succs = [f"op-{i+1}"] if i < n_ops - 1 else []

        ops.append(
            Operation(
                operation_id=f"op-{i}",
                work_order_id="wo-chain",
                resource_id=RESOURCE_IDS[i % len(RESOURCE_IDS)],
                start_time=BASE_TIME + timedelta(hours=start_h),
                end_time=BASE_TIME + timedelta(hours=end_h),
                predecessor_ids=preds,
                successor_ids=succs,
            )
        )
        current_time = end_h  # next op starts after this one ends

    schedule = ScheduleDetail(
        work_orders=[
            WorkOrder(
                work_order_id="wo-chain",
                product_name="P-chain",
                due_date=BASE_TIME + timedelta(days=5),
                operations=ops,
            )
        ],
    )
    return schedule


@st.composite
def invalid_process_order_schedule(draw):
    """Generate a schedule where at least one predecessor ends after its successor starts."""
    n_ops = draw(st.integers(min_value=2, max_value=5))
    ops = []
    current_time = 0.0

    # Pick which transition will violate
    violating_transition = draw(st.integers(min_value=0, max_value=n_ops - 2))

    for i in range(n_ops):
        dur_h = draw(st.floats(min_value=0.5, max_value=2, allow_nan=False, allow_infinity=False))

        if i == violating_transition + 1:
            # Force overlap: start before predecessor ends
            overlap = draw(st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False))
            start_h = current_time - overlap
        else:
            gap = draw(st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False))
            start_h = current_time + gap

        end_h = start_h + dur_h
        preds = [f"op-{i-1}"] if i > 0 else []
        succs = [f"op-{i+1}"] if i < n_ops - 1 else []

        ops.append(
            Operation(
                operation_id=f"op-{i}",
                work_order_id="wo-chain",
                resource_id=RESOURCE_IDS[i % len(RESOURCE_IDS)],
                start_time=BASE_TIME + timedelta(hours=start_h),
                end_time=BASE_TIME + timedelta(hours=end_h),
                predecessor_ids=preds,
                successor_ids=succs,
            )
        )
        current_time = end_h

    schedule = ScheduleDetail(
        work_orders=[
            WorkOrder(
                work_order_id="wo-chain",
                product_name="P-chain",
                due_date=BASE_TIME + timedelta(days=5),
                operations=ops,
            )
        ],
    )
    return schedule


@st.composite
def non_overlapping_resource_schedule(draw):
    """Generate a schedule where no two ops on the same resource overlap in time."""
    n_ops = draw(st.integers(min_value=2, max_value=5))
    # Assign all ops to the same resource to make the property meaningful
    res_id = "machine-A"
    ops = []
    current_time = 0.0

    for i in range(n_ops):
        gap = draw(st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False))
        dur_h = draw(st.floats(min_value=0.5, max_value=2, allow_nan=False, allow_infinity=False))
        start_h = current_time + gap
        end_h = start_h + dur_h

        ops.append(
            Operation(
                operation_id=f"op-{i}",
                work_order_id=f"wo-{i}",
                resource_id=res_id,
                start_time=BASE_TIME + timedelta(hours=start_h),
                end_time=BASE_TIME + timedelta(hours=end_h),
            )
        )
        current_time = end_h

    schedule = ScheduleDetail(
        work_orders=[
            WorkOrder(
                work_order_id=op.work_order_id,
                product_name=f"P-{op.work_order_id}",
                due_date=BASE_TIME + timedelta(days=5),
                operations=[op],
            )
            for op in ops
        ],
    )
    return schedule


@st.composite
def overlapping_resource_schedule(draw):
    """Generate a schedule where two ops on the same resource overlap."""
    res_id = "machine-A"
    # First op
    start1 = draw(st.floats(min_value=0, max_value=10, allow_nan=False, allow_infinity=False))
    dur1 = draw(st.floats(min_value=1, max_value=4, allow_nan=False, allow_infinity=False))
    end1 = start1 + dur1

    # Second op overlaps: starts before first ends
    overlap = draw(st.floats(min_value=0.1, max_value=dur1 - 0.01, allow_nan=False, allow_infinity=False))
    start2 = end1 - overlap
    dur2 = draw(st.floats(min_value=0.5, max_value=2, allow_nan=False, allow_infinity=False))
    end2 = start2 + dur2

    op1 = Operation(
        operation_id="op-0",
        work_order_id="wo-0",
        resource_id=res_id,
        start_time=BASE_TIME + timedelta(hours=start1),
        end_time=BASE_TIME + timedelta(hours=end1),
    )
    op2 = Operation(
        operation_id="op-1",
        work_order_id="wo-1",
        resource_id=res_id,
        start_time=BASE_TIME + timedelta(hours=start2),
        end_time=BASE_TIME + timedelta(hours=end2),
    )

    schedule = ScheduleDetail(
        work_orders=[
            WorkOrder(
                work_order_id="wo-0",
                product_name="P-0",
                due_date=BASE_TIME + timedelta(days=5),
                operations=[op1],
            ),
            WorkOrder(
                work_order_id="wo-1",
                product_name="P-1",
                due_date=BASE_TIME + timedelta(days=5),
                operations=[op2],
            ),
        ],
    )
    return schedule


@st.composite
def local_repair_invariant_schedule(draw):
    """Generate a LOCAL_REPAIR schedule where unaffected ops match the snapshot exactly.

    Returns (schedule, snapshot, affected_op_ids).
    """
    n_affected = draw(st.integers(min_value=1, max_value=2))
    n_unaffected = draw(st.integers(min_value=1, max_value=3))
    ops = []
    affected_ids = []

    current_time = 0.0
    for i in range(n_affected + n_unaffected):
        dur_h = draw(st.floats(min_value=0.5, max_value=2, allow_nan=False, allow_infinity=False))
        gap = draw(st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False))
        start_h = current_time + gap
        end_h = start_h + dur_h
        is_affected = i < n_affected

        op = Operation(
            operation_id=f"op-{i}",
            work_order_id=f"wo-{i}",
            resource_id=RESOURCE_IDS[i % len(RESOURCE_IDS)],
            start_time=BASE_TIME + timedelta(hours=start_h),
            end_time=BASE_TIME + timedelta(hours=end_h),
            is_affected=is_affected,
            is_adjusted=is_affected,
        )
        ops.append(op)
        if is_affected:
            affected_ids.append(op.operation_id)
        current_time = end_h

    schedule = ScheduleDetail(
        work_orders=[
            WorkOrder(
                work_order_id=op.work_order_id,
                product_name=f"P-{op.work_order_id}",
                due_date=BASE_TIME + timedelta(days=5),
                operations=[op],
            )
            for op in ops
        ],
    )
    # Snapshot matches the schedule exactly
    snapshot = ScheduleSnapshot(
        snapshot_id=uuid4(),
        captured_at=BASE_TIME,
        workshop_id="workshop-1",
        work_orders=[wo.model_copy(deep=True) for wo in schedule.work_orders],
    )
    return schedule, snapshot, affected_ids


# ── Helpers ─────────────────────────────────────────────────────────


def _make_snapshot(schedule: ScheduleDetail) -> ScheduleSnapshot:
    return ScheduleSnapshot(
        snapshot_id=uuid4(),
        captured_at=BASE_TIME,
        workshop_id="workshop-1",
        work_orders=[wo.model_copy(deep=True) for wo in schedule.work_orders],
    )


# ── Property Tests ──────────────────────────────────────────────────


class TestEquipmentCapabilityProperty:
    """**Validates: Requirements 20.1**"""

    @given(data=valid_capability_schedule())
    @settings(max_examples=50, deadline=None)
    def test_no_violations_when_caps_subset(self, data):
        """For any schedule where required_capabilities ⊆ resource capabilities,
        the validator reports no equipment_capability violations."""
        schedule, res_map = data
        snapshot = _make_snapshot(schedule)

        report = validator.validate_constraints(
            schedule, snapshot, StrategyType.GLOBAL_RESCHEDULE, []
        )

        cap_violations = [v for v in report.violations if v.constraint_type == "equipment_capability"]
        assert len(cap_violations) == 0, f"Unexpected violations: {cap_violations}"

    @given(data=invalid_capability_schedule())
    @settings(max_examples=50, deadline=None)
    def test_violations_when_cap_missing(self, data):
        """For any schedule where at least one op has a capability NOT in its resource,
        the validator reports at least one equipment_capability violation."""
        schedule, res_map = data
        snapshot = _make_snapshot(schedule)

        report = validator.validate_constraints(
            schedule, snapshot, StrategyType.GLOBAL_RESCHEDULE, []
        )

        cap_violations = [v for v in report.violations if v.constraint_type == "equipment_capability"]
        assert len(cap_violations) >= 1, "Expected at least one equipment_capability violation"


class TestProcessOrderProperty:
    """**Validates: Requirements 20.2**"""

    @given(data=valid_process_order_schedule())
    @settings(max_examples=50, deadline=None)
    def test_no_violations_when_order_respected(self, data):
        """For any schedule where all predecessor end_times <= successor start_times,
        the validator reports no process_order violations."""
        schedule = data
        snapshot = _make_snapshot(schedule)

        report = validator.validate_constraints(
            schedule, snapshot, StrategyType.GLOBAL_RESCHEDULE, []
        )

        order_violations = [v for v in report.violations if v.constraint_type == "process_order"]
        assert len(order_violations) == 0, f"Unexpected violations: {order_violations}"

    @given(data=invalid_process_order_schedule())
    @settings(max_examples=50, deadline=None)
    def test_violations_when_order_broken(self, data):
        """For any schedule where at least one predecessor ends after its successor starts,
        the validator reports at least one process_order violation."""
        schedule = data
        snapshot = _make_snapshot(schedule)

        report = validator.validate_constraints(
            schedule, snapshot, StrategyType.GLOBAL_RESCHEDULE, []
        )

        order_violations = [v for v in report.violations if v.constraint_type == "process_order"]
        assert len(order_violations) >= 1, "Expected at least one process_order violation"


class TestResourceMutualExclusionProperty:
    """**Validates: Requirements 20.3**"""

    @given(data=non_overlapping_resource_schedule())
    @settings(max_examples=50, deadline=None)
    def test_no_violations_when_no_overlap(self, data):
        """For any schedule where no two ops on the same resource overlap in time,
        the validator reports no resource_mutual_exclusion violations."""
        schedule = data
        snapshot = _make_snapshot(schedule)

        report = validator.validate_constraints(
            schedule, snapshot, StrategyType.GLOBAL_RESCHEDULE, []
        )

        excl_violations = [v for v in report.violations if v.constraint_type == "resource_mutual_exclusion"]
        assert len(excl_violations) == 0, f"Unexpected violations: {excl_violations}"

    @given(data=overlapping_resource_schedule())
    @settings(max_examples=50, deadline=None)
    def test_violations_when_overlap(self, data):
        """For any schedule where two ops on the same resource overlap,
        the validator reports at least one resource_mutual_exclusion violation."""
        schedule = data
        snapshot = _make_snapshot(schedule)

        report = validator.validate_constraints(
            schedule, snapshot, StrategyType.GLOBAL_RESCHEDULE, []
        )

        excl_violations = [v for v in report.violations if v.constraint_type == "resource_mutual_exclusion"]
        assert len(excl_violations) >= 1, "Expected at least one resource_mutual_exclusion violation"


class TestLocalRepairInvarianceProperty:
    """**Validates: Requirements 20.5**"""

    @given(data=local_repair_invariant_schedule())
    @settings(max_examples=50, deadline=None)
    def test_no_violations_when_unaffected_match_snapshot(self, data):
        """For any LOCAL_REPAIR schedule where unaffected ops match the snapshot exactly,
        the validator reports no local_repair_invariance violations."""
        schedule, snapshot, affected_ids = data

        report = validator.validate_constraints(
            schedule, snapshot, StrategyType.LOCAL_REPAIR, affected_ids
        )

        inv_violations = [v for v in report.violations if v.constraint_type == "local_repair_invariance"]
        assert len(inv_violations) == 0, f"Unexpected violations: {inv_violations}"
