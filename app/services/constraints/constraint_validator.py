"""Standalone constraint validation module for the ReOrch system.

Extracts constraint validation logic from HybridSolver into a reusable
service that can be called independently (e.g., by Confirmation_Module
for microadjustment validation).

Validates:
- Equipment capability constraints (Req 20.1)
- Process order constraints (Req 20.2)
- Resource mutual exclusion constraints (Req 20.3)
- Material availability constraints (Req 20.4, simplified MVP)
- Local-repair invariance (Req 20.5)
- Microadjustment re-validation (Req 20.6)
- Structured ConstraintValidationReport output (Req 20.7)
"""

from __future__ import annotations

from app.models.enums import StrategyType
from app.models.schedule import (
    Operation,
    Resource,
    ScheduleDetail,
    ScheduleSnapshot,
)
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    ConstraintViolation,
)


class ConstraintValidator:
    """Reusable constraint validator for candidate plans and microadjustments."""

    def validate_constraints(
        self,
        schedule_detail: ScheduleDetail,
        snapshot: ScheduleSnapshot,
        strategy_type: StrategyType | str,
        affected_op_ids: list[str],
        resource_capabilities: dict[str, list[str]] | None = None,
    ) -> ConstraintValidationReport:
        """Run all hard-constraint checks on a schedule.

        Args:
            schedule_detail: The schedule to validate.
            snapshot: The baseline ScheduleSnapshot for invariance checks.
            strategy_type: The strategy used (affects which checks run).
            affected_op_ids: IDs of operations affected by the anomaly.
            resource_capabilities: Optional mapping of resource_id -> capability
                list. When ``None``, capabilities are read from
                ``schedule_detail.resources``.

        Returns:
            ConstraintValidationReport with feasibility status, violations,
            and list of checked constraints.
        """
        strategy = self._resolve_strategy(strategy_type)
        violations: list[ConstraintViolation] = []
        checked: list[str] = []

        # Build lookups
        op_map = self._build_op_map(schedule_detail)
        cap_map = self._build_capability_map(schedule_detail, resource_capabilities)

        # 1. Equipment capability (Req 20.1)
        checked.append("equipment_capability")
        violations.extend(self._check_equipment_capability(op_map, cap_map))

        # 2. Process order (Req 20.2)
        checked.append("process_order")
        violations.extend(self._check_process_order(schedule_detail, op_map))

        # 3. Resource mutual exclusion (Req 20.3)
        checked.append("resource_mutual_exclusion")
        violations.extend(self._check_resource_exclusion(schedule_detail))

        # 4. Material availability – simplified MVP (Req 20.4)
        checked.append("material_availability")
        violations.extend(self._check_material_availability(schedule_detail))

        # 5. Local-repair invariance (Req 20.5)
        if strategy == StrategyType.LOCAL_REPAIR:
            checked.append("local_repair_invariance")
            violations.extend(
                self._check_local_repair_invariance(
                    op_map, snapshot, affected_op_ids
                )
            )

        return ConstraintValidationReport(
            is_feasible=len(violations) == 0,
            violations=violations,
            checked_constraints=checked,
        )

    def validate_microadjustment(
        self,
        original_plan: CandidatePlan,
        adjusted_schedule: ScheduleDetail,
        snapshot: ScheduleSnapshot,
    ) -> ConstraintValidationReport:
        """Re-run all constraints on a Planner-adjusted schedule (Req 20.6).

        Uses the original plan's strategy type and affected operation IDs
        to determine which checks to apply.
        """
        strategy_type = original_plan.strategy_type
        # Derive affected op IDs from the original plan's adjusted ops
        affected_op_ids: list[str] = []
        for wo in original_plan.schedule_detail.work_orders:
            for op in wo.operations:
                if op.is_affected or op.is_adjusted:
                    affected_op_ids.append(op.operation_id)

        return self.validate_constraints(
            schedule_detail=adjusted_schedule,
            snapshot=snapshot,
            strategy_type=strategy_type,
            affected_op_ids=affected_op_ids,
        )

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _resolve_strategy(value: StrategyType | str) -> StrategyType:
        if isinstance(value, StrategyType):
            return value
        try:
            return StrategyType(value)
        except ValueError:
            for member in StrategyType:
                if member.name.lower() == str(value).lower():
                    return member
            return StrategyType.LOCAL_REPAIR

    @staticmethod
    def _build_op_map(schedule: ScheduleDetail) -> dict[str, Operation]:
        op_map: dict[str, Operation] = {}
        for wo in schedule.work_orders:
            for op in wo.operations:
                op_map[op.operation_id] = op
        return op_map

    @staticmethod
    def _build_capability_map(
        schedule: ScheduleDetail,
        override: dict[str, list[str]] | None,
    ) -> dict[str, list[str]]:
        if override is not None:
            return override
        cap_map: dict[str, list[str]] = {}
        for res in schedule.resources:
            cap_map[res.resource_id] = list(res.capabilities)
        return cap_map

    # ── Individual constraint checks ────────────────────────────────

    @staticmethod
    def _check_equipment_capability(
        op_map: dict[str, Operation],
        cap_map: dict[str, list[str]],
    ) -> list[ConstraintViolation]:
        """Req 20.1: op.required_capabilities ⊆ assigned resource capabilities."""
        violations: list[ConstraintViolation] = []
        for op in op_map.values():
            if not op.required_capabilities:
                continue
            resource_caps = set(cap_map.get(op.resource_id, []))
            missing = set(op.required_capabilities) - resource_caps
            if missing:
                violations.append(
                    ConstraintViolation(
                        constraint_type="equipment_capability",
                        operation_id=op.operation_id,
                        resource_id=op.resource_id,
                        detail=(
                            f"Operation '{op.operation_id}' requires capabilities "
                            f"{sorted(missing)} not provided by resource "
                            f"'{op.resource_id}' (has {sorted(resource_caps)})"
                        ),
                    )
                )
        return violations

    @staticmethod
    def _check_process_order(
        schedule: ScheduleDetail,
        op_map: dict[str, Operation],
    ) -> list[ConstraintViolation]:
        """Req 20.2: predecessor end_time ≤ successor start_time."""
        violations: list[ConstraintViolation] = []
        for wo in schedule.work_orders:
            for op in wo.operations:
                for pred_id in op.predecessor_ids:
                    pred = op_map.get(pred_id)
                    if pred and pred.end_time > op.start_time:
                        violations.append(
                            ConstraintViolation(
                                constraint_type="process_order",
                                operation_id=op.operation_id,
                                resource_id=op.resource_id,
                                detail=(
                                    f"Predecessor '{pred_id}' ends at "
                                    f"{pred.end_time} but successor "
                                    f"'{op.operation_id}' starts at "
                                    f"{op.start_time}"
                                ),
                            )
                        )
        return violations

    @staticmethod
    def _check_resource_exclusion(
        schedule: ScheduleDetail,
    ) -> list[ConstraintViolation]:
        """Req 20.3: no overlapping ops on same resource at same time."""
        violations: list[ConstraintViolation] = []
        resource_ops: dict[str, list[Operation]] = {}
        for wo in schedule.work_orders:
            for op in wo.operations:
                resource_ops.setdefault(op.resource_id, []).append(op)

        for resource_id, ops in resource_ops.items():
            sorted_ops = sorted(ops, key=lambda o: o.start_time)
            for i in range(len(sorted_ops) - 1):
                if sorted_ops[i].end_time > sorted_ops[i + 1].start_time:
                    violations.append(
                        ConstraintViolation(
                            constraint_type="resource_mutual_exclusion",
                            operation_id=sorted_ops[i + 1].operation_id,
                            resource_id=resource_id,
                            detail=(
                                f"Operation '{sorted_ops[i].operation_id}' on "
                                f"resource '{resource_id}' ends at "
                                f"{sorted_ops[i].end_time} overlapping with "
                                f"'{sorted_ops[i + 1].operation_id}' starting "
                                f"at {sorted_ops[i + 1].start_time}"
                            ),
                        )
                    )
        return violations

    @staticmethod
    def _check_material_availability(
        schedule: ScheduleDetail,
    ) -> list[ConstraintViolation]:
        """Req 20.4 (simplified MVP): check that start_time > epoch 0.

        A real implementation would verify BOM availability against
        inventory/procurement data. For MVP we simply ensure every
        operation has a positive start time (not at Unix epoch).
        """
        violations: list[ConstraintViolation] = []
        for wo in schedule.work_orders:
            for op in wo.operations:
                if op.start_time.timestamp() <= 0:
                    violations.append(
                        ConstraintViolation(
                            constraint_type="material_availability",
                            operation_id=op.operation_id,
                            resource_id=op.resource_id,
                            detail=(
                                f"Operation '{op.operation_id}' has start_time "
                                f"{op.start_time} at or before epoch 0, "
                                f"material availability cannot be guaranteed"
                            ),
                        )
                    )
        return violations

    @staticmethod
    def _check_local_repair_invariance(
        op_map: dict[str, Operation],
        snapshot: ScheduleSnapshot,
        affected_op_ids: list[str],
    ) -> list[ConstraintViolation]:
        """Req 20.5: unaffected ops must match snapshot exactly."""
        violations: list[ConstraintViolation] = []
        affected_set = set(affected_op_ids)

        snapshot_op_map: dict[str, Operation] = {}
        for wo in snapshot.work_orders:
            for op in wo.operations:
                snapshot_op_map[op.operation_id] = op

        for op_id, op in op_map.items():
            if op_id in affected_set or op.is_adjusted:
                continue
            snap_op = snapshot_op_map.get(op_id)
            if snap_op is None:
                continue
            if (
                op.start_time != snap_op.start_time
                or op.end_time != snap_op.end_time
                or op.resource_id != snap_op.resource_id
            ):
                violations.append(
                    ConstraintViolation(
                        constraint_type="local_repair_invariance",
                        operation_id=op_id,
                        resource_id=op.resource_id,
                        detail=(
                            f"Unaffected operation '{op_id}' was modified: "
                            f"start {snap_op.start_time}→{op.start_time}, "
                            f"end {snap_op.end_time}→{op.end_time}, "
                            f"resource {snap_op.resource_id}→{op.resource_id}"
                        ),
                    )
                )
        return violations
