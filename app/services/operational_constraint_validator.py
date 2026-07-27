"""Independent validation for customer operational constraint families."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.enums import StrategyType
from app.models.schedule import Operation, ScheduleDetail, ScheduleSnapshot
from app.models.solver import ConstraintValidationReport, ConstraintViolation
from app.services.constraint_validator import ConstraintValidator


class OperationalConstraintValidator:
    """Recompute operational constraints from the merged schedule."""

    def validate(
        self,
        schedule: ScheduleDetail,
        snapshot: ScheduleSnapshot,
        *,
        frozen_operation_ids: list[str] | None = None,
    ) -> ConstraintValidationReport:
        capability_map = self._capability_map(schedule, snapshot)
        base = ConstraintValidator().validate_constraints(
            schedule_detail=schedule,
            snapshot=snapshot,
            strategy_type=StrategyType.GLOBAL_RESCHEDULE,
            affected_op_ids=[],
            resource_capabilities=capability_map,
        )
        op_map = {
            op.operation_id: op for wo in schedule.work_orders for op in wo.operations
        }
        raw = snapshot.raw_data or {}
        checks = list(base.checked_constraints)
        checks.append("operation_precedence")
        violations = list(base.violations)

        checks.append("schedule_integrity")
        violations.extend(self._schedule_integrity_violations(schedule, snapshot))
        checks.append("resource_eligibility")
        violations.extend(self._resource_eligibility_violations(op_map, raw))
        checks.append("frozen_operations")
        violations.extend(
            self._frozen_operation_violations(
                op_map,
                snapshot,
                set(frozen_operation_ids or []),
            )
        )
        checks.append("resource_calendar")
        violations.extend(self._resource_calendar_violations(op_map, raw))
        checks.append("operation_release_deadline")
        violations.extend(self._operation_window_violations(op_map, raw))
        checks.append("quality_hold_release")
        violations.extend(self._quality_hold_violations(op_map, snapshot, raw))
        checks.append("sequence_dependent_changeover")
        violations.extend(self._changeover_violations(schedule, raw))
        checks.append("tooling_capacity")
        violations.extend(self._tooling_violations(op_map, raw))
        checks.append("labor_skill_capacity")
        violations.extend(self._labor_violations(op_map, raw))
        checks.append("transport_amr_capacity")
        violations.extend(self._transport_violations(op_map, raw))
        checks.append("buffer_capacity")
        violations.extend(self._buffer_violations(op_map, raw))
        checks.append("outsourcing_approval_capacity")
        violations.extend(self._outsourcing_violations(op_map, raw, snapshot.captured_at))
        checks.append("substitute_material_approval")
        violations.extend(self._material_violations(op_map, raw))
        checks.append("batch_genealogy")
        violations.extend(self._genealogy_violations(op_map, raw))
        checks.append("qms_release")
        violations.extend(self._qms_violations(op_map, raw))

        return ConstraintValidationReport(
            is_feasible=not violations,
            violations=violations,
            checked_constraints=list(dict.fromkeys(checks)),
        )

    @staticmethod
    def _capability_map(
        schedule: ScheduleDetail,
        snapshot: ScheduleSnapshot,
    ) -> dict[str, list[str]]:
        result = {
            resource.resource_id: list(resource.capabilities)
            for resource in schedule.resources
        }
        raw_resources = (snapshot.raw_data or {}).get("resources", []) or []
        for row in raw_resources:
            resource_id = str(row.get("resource_id", ""))
            if resource_id:
                result[resource_id] = [
                    str(item) for item in row.get("capabilities", []) or []
                ]
        if raw_resources:
            return result

        # Legacy snapshots without a resource master can only preserve their
        # baseline assignment. Production readiness gates require real master data.
        for work_order in snapshot.work_orders:
            for operation in work_order.operations:
                values = result.setdefault(operation.resource_id, [])
                for capability in operation.required_capabilities:
                    if capability not in values:
                        values.append(capability)
        return result

    @staticmethod
    def _schedule_integrity_violations(
        schedule: ScheduleDetail,
        snapshot: ScheduleSnapshot,
    ) -> list[ConstraintViolation]:
        expected = {
            op.operation_id for wo in snapshot.work_orders for op in wo.operations
        }
        observed_ids = [
            op.operation_id for wo in schedule.work_orders for op in wo.operations
        ]
        observed = set(observed_ids)
        violations: list[ConstraintViolation] = []
        for operation_id in sorted(expected - observed):
            violations.append(
                ConstraintViolation(
                    constraint_type="schedule_integrity",
                    operation_id=operation_id,
                    detail="Expected operation is missing from candidate schedule",
                )
            )
        for operation_id in sorted(observed - expected):
            violations.append(
                ConstraintViolation(
                    constraint_type="schedule_integrity",
                    operation_id=operation_id,
                    detail="Candidate contains an operation absent from the snapshot",
                )
            )
        seen: set[str] = set()
        for work_order in schedule.work_orders:
            for operation in work_order.operations:
                if operation.operation_id in seen:
                    violations.append(
                        _violation(
                            "schedule_integrity",
                            operation,
                            "Duplicate operation appears in candidate schedule",
                        )
                    )
                seen.add(operation.operation_id)
                if operation.end_time <= operation.start_time:
                    violations.append(
                        _violation(
                            "positive_operation_duration",
                            operation,
                            "Operation end_time must be later than start_time",
                        )
                    )
        return violations

    @staticmethod
    def _resource_eligibility_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        eligible: dict[str, set[str]] = {}
        for work_order in raw.get("work_orders", []) or []:
            for operation in work_order.get("operations", []) or []:
                operation_id = str(operation.get("operation_id", ""))
                if operation_id and operation.get("eligible_resources") is not None:
                    eligible[operation_id] = {
                        str(item)
                        for item in operation.get("eligible_resources", []) or []
                    }
        for row in raw.get("outsourcing_approvals", []) or []:
            if str(row.get("approval_status", "pending")).lower() != "approved":
                continue
            if not row.get("approved_by") or not row.get("source_ref"):
                continue
            resource_id = str(
                row.get("resource_id") or f"OUTSOURCE:{row.get('vendor_id', '')}"
            )
            for operation_id in row.get("operation_ids", []) or []:
                eligible.setdefault(str(operation_id), set()).add(resource_id)
        violations: list[ConstraintViolation] = []
        for operation_id, allowed in eligible.items():
            operation = op_map.get(operation_id)
            if operation is not None and operation.resource_id not in allowed:
                violations.append(
                    _violation(
                        "resource_eligibility",
                        operation,
                        f"Assigned resource is not eligible; allowed={sorted(allowed)}",
                    )
                )
        return violations

    @staticmethod
    def _frozen_operation_violations(
        op_map: dict[str, Operation],
        snapshot: ScheduleSnapshot,
        frozen_operation_ids: set[str],
    ) -> list[ConstraintViolation]:
        baseline = {
            op.operation_id: op for wo in snapshot.work_orders for op in wo.operations
        }
        violations: list[ConstraintViolation] = []
        for operation_id in sorted(frozen_operation_ids):
            operation = op_map.get(operation_id)
            original = baseline.get(operation_id)
            if operation is None or original is None:
                continue
            if (
                operation.start_time != original.start_time
                or operation.end_time != original.end_time
                or operation.resource_id != original.resource_id
            ):
                violations.append(
                    _violation(
                        "frozen_operation",
                        operation,
                        "Frozen operation differs from the supplied snapshot",
                    )
                )
        return violations

    @staticmethod
    def _resource_calendar_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []
        for row in raw.get("resource_calendar", []) or []:
            if row.get("availability_type", "unavailable") != "unavailable":
                continue
            resource_id = str(row.get("resource_id", ""))
            start = _datetime(row.get("window_start"))
            end = _datetime(row.get("window_end"))
            if not resource_id or start is None or end is None or end <= start:
                continue
            for operation in op_map.values():
                if (
                    operation.resource_id == resource_id
                    and operation.start_time < end
                    and operation.end_time > start
                ):
                    violations.append(
                        _violation(
                            "resource_calendar",
                            operation,
                            f"Operation overlaps unavailable window {start.isoformat()}..{end.isoformat()}",
                        )
                    )
        return violations

    @staticmethod
    def _operation_window_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []
        for row in raw.get("operation_release_constraints", []) or []:
            operation = op_map.get(str(row.get("operation_id", "")))
            release = _datetime(row.get("release_at"))
            if operation is not None and release and operation.start_time < release:
                violations.append(
                    _violation(
                        "operation_release",
                        operation,
                        "Operation starts before its release boundary",
                    )
                )
        for row in raw.get("operation_deadline_constraints", []) or []:
            operation = op_map.get(str(row.get("operation_id", "")))
            deadline = _datetime(row.get("deadline_at"))
            if operation is not None and deadline and operation.end_time > deadline:
                violations.append(
                    _violation(
                        "operation_deadline",
                        operation,
                        "Operation ends after its decomposition boundary deadline",
                    )
                )
        return violations

    @staticmethod
    def _quality_hold_violations(
        op_map: dict[str, Operation],
        snapshot: ScheduleSnapshot,
        raw: dict[str, Any],
    ) -> list[ConstraintViolation]:
        baseline = {
            op.operation_id: op for wo in snapshot.work_orders for op in wo.operations
        }
        violations: list[ConstraintViolation] = []
        for row in raw.get("quality_holds", []) or []:
            status = str(row.get("status", "held")).lower()
            release_at = _datetime(row.get("release_at"))
            for operation_id in row.get("blocked_operation_ids", []) or []:
                operation = op_map.get(str(operation_id))
                original = baseline.get(str(operation_id))
                if operation is None:
                    continue
                if status not in {"released", "cleared", "closed"}:
                    if original and (
                        operation.start_time != original.start_time
                        or operation.end_time != original.end_time
                        or operation.resource_id != original.resource_id
                    ):
                        violations.append(
                            _violation(
                                "quality_hold",
                                operation,
                                "Operation under an unreleased quality hold was modified",
                            )
                        )
                elif release_at and operation.start_time < release_at:
                    violations.append(
                        _violation(
                            "quality_hold_release",
                            operation,
                            "Operation starts before quality hold release time",
                        )
                    )
        return violations

    @staticmethod
    def _changeover_violations(
        schedule: ScheduleDetail, raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        setup: dict[tuple[str | None, str, str], int] = {}
        for row in raw.get("changeover_rules", []) or []:
            left = str(row.get("from_product_family", ""))
            right = str(row.get("to_product_family", ""))
            if not left or not right or left == right:
                continue
            raw_resource = row.get("resource_id")
            resource_id = str(raw_resource) if raw_resource else None
            key = (resource_id, left, right)
            setup[key] = max(setup.get(key, 0), int(row.get("setup_minutes", 0) or 0))
        if not setup:
            return []
        family_by_operation: dict[str, str] = {}
        for work_order in raw.get("work_orders", []) or []:
            family = str(work_order.get("product_family", "unknown"))
            for operation in work_order.get("operations", []) or []:
                if operation.get("operation_id"):
                    family_by_operation[str(operation["operation_id"])] = str(
                        operation.get("product_family", family)
                    )
        by_resource: dict[str, list[Operation]] = {}
        for work_order in schedule.work_orders:
            for operation in work_order.operations:
                by_resource.setdefault(operation.resource_id, []).append(operation)
        violations: list[ConstraintViolation] = []
        for resource_id, operations in by_resource.items():
            ordered = sorted(operations, key=lambda item: item.start_time)
            for previous, current in zip(ordered, ordered[1:]):
                previous_family = family_by_operation.get(previous.operation_id, "unknown")
                current_family = family_by_operation.get(current.operation_id, "unknown")
                required = setup.get(
                    (resource_id, previous_family, current_family),
                    setup.get((None, previous_family, current_family), 0),
                )
                if current.start_time < previous.end_time + _minutes(required):
                    violations.append(
                        _violation(
                            "sequence_dependent_changeover",
                            current,
                            f"Requires {required} setup minutes after {previous.operation_id}",
                        )
                    )
        return violations

    @staticmethod
    def _tooling_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        requirements: dict[str, set[str]] = {}
        capacity: dict[str, int] = {}
        unavailable: dict[str, list[tuple[datetime, datetime]]] = {}
        for work_order in raw.get("work_orders", []) or []:
            for operation in work_order.get("operations", []) or []:
                operation_id = str(operation.get("operation_id", ""))
                payload = operation.get("raw_payload", {}) or {}
                for tooling_id in _as_list(
                    payload.get("required_tooling_ids") or payload.get("tooling_ids")
                ):
                    requirements.setdefault(operation_id, set()).add(tooling_id)
        for row in raw.get("tooling_calendar", []) or []:
            tooling_id = str(row.get("tooling_id", ""))
            if not tooling_id:
                continue
            capacity[tooling_id] = max(
                capacity.get(tooling_id, 1), int(row.get("quantity", 1) or 0)
            )
            for operation_id in row.get("operation_ids", []) or []:
                requirements.setdefault(str(operation_id), set()).add(tooling_id)
            start = _datetime(row.get("unavailable_start"))
            end = _datetime(row.get("unavailable_end"))
            if start and end and end > start:
                unavailable.setdefault(tooling_id, []).append((start, end))
        return _secondary_capacity_violations(
            op_map,
            requirements,
            capacity,
            unavailable,
            "tooling_capacity",
        )

    @staticmethod
    def _labor_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        requirements: dict[str, set[str]] = {}
        rows_by_skill: dict[str, list[tuple[datetime, datetime, int]]] = {}
        maximum: dict[str, int] = {}
        for work_order in raw.get("work_orders", []) or []:
            for operation in work_order.get("operations", []) or []:
                operation_id = str(operation.get("operation_id", ""))
                payload = operation.get("raw_payload", {}) or {}
                for skill in _as_list(
                    payload.get("required_skill_codes") or payload.get("skill_codes")
                ):
                    requirements.setdefault(operation_id, set()).add(skill)
        for row in raw.get("labor_skill_capacity", []) or []:
            skill = str(row.get("skill_code", ""))
            if not skill:
                continue
            available = max(0, int(row.get("available_headcount", 0) or 0))
            maximum[skill] = max(maximum.get(skill, 1), available)
            for operation_id in row.get("operation_ids", []) or []:
                requirements.setdefault(str(operation_id), set()).add(skill)
            start = _datetime(row.get("window_start"))
            end = _datetime(row.get("window_end"))
            if start and end and end > start:
                rows_by_skill.setdefault(skill, []).append((start, end, available))

        for skills in requirements.values():
            for skill in skills:
                maximum.setdefault(skill, 1)

        violations: list[ConstraintViolation] = []
        for skill, max_capacity in maximum.items():
            intervals = [
                (operation.start_time, operation.end_time, operation.operation_id, 1)
                for operation_id, skills in requirements.items()
                if skill in skills and (operation := op_map.get(operation_id)) is not None
            ]
            for start, end, available in rows_by_skill.get(skill, []):
                blocked = max(0, max_capacity - available)
                if blocked:
                    intervals.append((start, end, f"capacity:{skill}", blocked))
            if _peak_usage(intervals) > max_capacity and intervals:
                operation = next(
                    (
                        op_map[operation_id]
                        for operation_id, skills in requirements.items()
                        if skill in skills and operation_id in op_map
                    ),
                    None,
                )
                if operation:
                    violations.append(
                        _violation(
                            "labor_skill_capacity",
                            operation,
                            f"Skill {skill} concurrent demand exceeds {max_capacity}",
                        )
                    )
        return violations

    @staticmethod
    def _transport_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []
        lanes: dict[str, list[tuple[datetime, datetime, str, int]]] = {}
        capacity_by_lane: dict[str, int] = {}
        for row in raw.get("transport_lanes", []) or []:
            pred = op_map.get(str(row.get("predecessor_operation_id", "")))
            succ = op_map.get(str(row.get("successor_operation_id", "")))
            if pred is None or succ is None:
                continue
            lane_id = str(row.get("lane_id", "unmapped"))
            eta = max(0, int(row.get("eta_minutes", 0) or 0))
            required_at = pred.end_time + _minutes(eta)
            if succ.start_time < required_at:
                violations.append(
                    _violation(
                        "transport_lag",
                        succ,
                        f"{lane_id} requires {eta} minutes after {pred.operation_id}",
                    )
                )
            lanes.setdefault(lane_id, []).append(
                (pred.end_time, required_at, succ.operation_id, 1)
            )
            capacity_by_lane[lane_id] = max(1, int(row.get("capacity", 1) or 1))
        for lane_id, intervals in lanes.items():
            peak = _peak_usage(intervals)
            if peak > capacity_by_lane[lane_id]:
                violations.append(
                    ConstraintViolation(
                        constraint_type="transport_capacity",
                        operation_id=intervals[0][2],
                        detail=(
                            f"Lane {lane_id} peak usage {peak} exceeds "
                            f"capacity {capacity_by_lane[lane_id]}"
                        ),
                    )
                )
        return violations

    @staticmethod
    def _buffer_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        groups: dict[str, dict[str, Any]] = {}
        for row in raw.get("buffer_flows", []) or []:
            pred = op_map.get(str(row.get("predecessor_operation_id", "")))
            succ = op_map.get(str(row.get("successor_operation_id", "")))
            if pred is None or succ is None:
                continue
            buffer_id = str(row.get("buffer_id", "unmapped"))
            item = groups.setdefault(
                buffer_id,
                {
                    "capacity": int(row.get("capacity", 1) or 1),
                    "current_wip": int(row.get("current_wip", 0) or 0),
                    "intervals": [],
                },
            )
            item["capacity"] = min(item["capacity"], int(row.get("capacity", 1) or 1))
            item["current_wip"] = max(
                item["current_wip"], int(row.get("current_wip", 0) or 0)
            )
            item["intervals"].append(
                (
                    pred.end_time,
                    succ.start_time,
                    succ.operation_id,
                    int(row.get("occupancy_quantity", 1) or 1),
                )
            )
        violations: list[ConstraintViolation] = []
        for buffer_id, item in groups.items():
            peak = int(item["current_wip"]) + _peak_usage(item["intervals"])
            if peak > int(item["capacity"]):
                violations.append(
                    ConstraintViolation(
                        constraint_type="buffer_capacity",
                        operation_id=item["intervals"][0][2],
                        detail=(
                            f"Buffer {buffer_id} peak WIP {peak} exceeds "
                            f"capacity {item['capacity']}"
                        ),
                    )
                )
        return violations

    @staticmethod
    def _outsourcing_violations(
        op_map: dict[str, Operation], raw: dict[str, Any], captured_at: datetime
    ) -> list[ConstraintViolation]:
        approved: dict[tuple[str, str], dict[str, Any]] = {}
        for row in raw.get("outsourcing_approvals", []) or []:
            if str(row.get("approval_status", "pending")).lower() != "approved":
                continue
            if not row.get("approved_by") or not row.get("source_ref"):
                continue
            expiry = _datetime(row.get("valid_until"))
            if expiry and expiry < captured_at:
                continue
            resource_id = str(
                row.get("resource_id") or f"OUTSOURCE:{row.get('vendor_id', '')}"
            )
            for op_id in row.get("operation_ids", []) or []:
                approved[(str(op_id), resource_id)] = row

        violations: list[ConstraintViolation] = []
        usage: dict[str, list[str]] = {}
        capacity: dict[str, int] = {}
        for op in op_map.values():
            if not op.resource_id.startswith("OUTSOURCE:"):
                continue
            row = approved.get((op.operation_id, op.resource_id))
            if row is None:
                violations.append(
                    _violation(
                        "outsourcing_approval",
                        op,
                        "Selected outsource route has no valid approval evidence",
                    )
                )
                continue
            usage.setdefault(op.resource_id, []).append(op.operation_id)
            capacity[op.resource_id] = min(
                capacity.get(op.resource_id, int(row.get("capacity_per_day", 1) or 1)),
                int(row.get("capacity_per_day", 1) or 1),
            )
        for resource_id, op_ids in usage.items():
            if len(op_ids) > capacity[resource_id]:
                violations.append(
                    ConstraintViolation(
                        constraint_type="outsourcing_capacity",
                        operation_id=op_ids[0],
                        resource_id=resource_id,
                        detail=(
                            f"Approved daily capacity {capacity[resource_id]} exceeded "
                            f"by {len(op_ids)} selected operations"
                        ),
                    )
                )
        return violations

    @staticmethod
    def _material_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        approved: dict[str, list[dict[str, Any]]] = {}
        for row in raw.get("substitute_material_approvals", []) or []:
            if str(row.get("approval_status", "pending")).lower() != "approved":
                continue
            if not row.get("approved_by") or not row.get("source_ref"):
                continue
            for op_id in row.get("operation_ids", []) or []:
                approved.setdefault(str(op_id), []).append(row)
        violations: list[ConstraintViolation] = []
        for row in raw.get("material_availability", []) or []:
            shortage = float(row.get("available_quantity", 0) or 0) < float(
                row.get("required_quantity", 1) or 1
            )
            for op_id in row.get("operation_ids", []) or []:
                op = op_map.get(str(op_id))
                if op is None:
                    continue
                candidates = approved.get(str(op_id), []) if shortage else [row]
                candidates = [
                    item
                    for item in candidates
                    if float(item.get("available_quantity", 0) or 0)
                    >= float(item.get("required_quantity", 1) or 1)
                ]
                if not candidates:
                    violations.append(
                        _violation(
                            "substitute_material_approval",
                            op,
                            "Primary shortage has no approved and available substitute",
                        )
                    )
                    continue
                available_times = [
                    value
                    for value in (_datetime(item.get("available_at")) for item in candidates)
                    if value is not None
                ]
                if available_times and op.start_time < min(available_times):
                    violations.append(
                        _violation(
                            "material_release_time",
                            op,
                            "Operation starts before material release time",
                        )
                    )
        return violations

    @staticmethod
    def _genealogy_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        violations: list[ConstraintViolation] = []
        for row in raw.get("batch_genealogy", []) or []:
            child_ops = [
                op_map[str(item)]
                for item in row.get("operation_ids", []) or []
                if str(item) in op_map
            ]
            state = str(row.get("quality_state", "released")).lower()
            release_at = _datetime(row.get("release_at"))
            if child_ops and state not in {"released", "cleared", "closed"}:
                violations.append(
                    _violation(
                        "batch_genealogy_release",
                        child_ops[0],
                        f"Batch {row.get('batch_id')} is {state}",
                    )
                )
            elif release_at:
                for child in child_ops:
                    if child.start_time < release_at:
                        violations.append(
                            _violation(
                                "batch_genealogy_release_time",
                                child,
                                "Operation starts before batch release time",
                            )
                        )
            parents = [
                op_map[str(item)]
                for item in row.get("parent_operation_ids", []) or []
                if str(item) in op_map
            ]
            if row.get("rework_required"):
                rework = op_map.get(str(row.get("rework_operation_id", "")))
                if rework is None:
                    if child_ops:
                        violations.append(
                            _violation(
                                "batch_rework_precedence",
                                child_ops[0],
                                "Rework required but no executable rework operation exists",
                            )
                        )
                else:
                    parents.append(rework)
            for child in child_ops:
                for parent in parents:
                    if parent.operation_id != child.operation_id and parent.end_time > child.start_time:
                        violations.append(
                            _violation(
                                "batch_genealogy_precedence",
                                child,
                                f"Parent/rework {parent.operation_id} ends after child starts",
                            )
                        )
        return violations

    @staticmethod
    def _qms_violations(
        op_map: dict[str, Operation], raw: dict[str, Any]
    ) -> list[ConstraintViolation]:
        batch_ops = {
            str(row.get("batch_id")): [str(item) for item in row.get("operation_ids", []) or []]
            for row in raw.get("batch_genealogy", []) or []
        }
        violations: list[ConstraintViolation] = []
        for row in raw.get("qms_release_gates", []) or []:
            op_ids = {str(item) for item in row.get("operation_ids", []) or []}
            for batch_id in row.get("batch_ids", []) or []:
                op_ids.update(batch_ops.get(str(batch_id), []))
            operations = [op_map[op_id] for op_id in op_ids if op_id in op_map]
            if not operations:
                continue
            gate_id = str(row.get("gate_id", "unknown"))
            status = str(row.get("status", "pending")).lower()
            required = {str(item) for item in row.get("required_approvals", []) or []}
            approvals = {str(item) for item in row.get("approvals", []) or []}
            release_at = _datetime(row.get("release_at"))
            reason = None
            if status not in {"released", "cleared", "closed"}:
                reason = f"QMS gate {gate_id} is {status}"
            elif not required.issubset(approvals):
                reason = f"QMS gate {gate_id} lacks required approvals"
            elif not row.get("certificate_ref") or not row.get("source_ref"):
                reason = f"QMS gate {gate_id} lacks certificate/source evidence"
            if reason:
                violations.append(_violation("qms_release", operations[0], reason))
                continue
            for op in operations:
                if release_at and op.start_time < release_at:
                    violations.append(
                        _violation(
                            "qms_release_time",
                            op,
                            f"Operation starts before QMS gate {gate_id} release",
                        )
                    )
        return violations


def _minutes(value: int):
    from datetime import timedelta

    return timedelta(minutes=value)


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _peak_usage(intervals: list[tuple[datetime, datetime, str, int]]) -> int:
    points: list[tuple[datetime, int, int]] = []
    for start, end, _, demand in intervals:
        if end <= start:
            continue
        points.append((start, 1, demand))
        points.append((end, 0, -demand))
    current = 0
    peak = 0
    for _, _, delta in sorted(points, key=lambda item: (item[0], item[1])):
        current += delta
        peak = max(peak, current)
    return peak


def _secondary_capacity_violations(
    op_map: dict[str, Operation],
    requirements: dict[str, set[str]],
    capacities: dict[str, int],
    unavailable: dict[str, list[tuple[datetime, datetime]]],
    constraint_type: str,
) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []
    resource_ids = {
        resource_id for values in requirements.values() for resource_id in values
    }
    for resource_id in sorted(resource_ids):
        capacity = max(0, capacities.get(resource_id, 1))
        intervals = [
            (operation.start_time, operation.end_time, operation.operation_id, 1)
            for operation_id, required in requirements.items()
            if resource_id in required
            and (operation := op_map.get(operation_id)) is not None
        ]
        for start, end in unavailable.get(resource_id, []):
            intervals.append((start, end, f"unavailable:{resource_id}", capacity))
        peak = _peak_usage(intervals)
        if peak <= capacity:
            continue
        operation = next(
            (
                op_map[operation_id]
                for operation_id, required in requirements.items()
                if resource_id in required and operation_id in op_map
            ),
            None,
        )
        if operation is not None:
            violations.append(
                _violation(
                    constraint_type,
                    operation,
                    f"{resource_id} concurrent demand {peak} exceeds capacity {capacity}",
                )
            )
    return violations


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _violation(
    constraint_type: str, operation: Operation, detail: str
) -> ConstraintViolation:
    return ConstraintViolation(
        constraint_type=constraint_type,
        operation_id=operation.operation_id,
        resource_id=operation.resource_id,
        detail=detail,
    )
