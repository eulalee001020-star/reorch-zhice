"""Data readiness checks for initial scheduling and anomaly rescheduling."""

from __future__ import annotations

from app.models.planning import (
    DataReadinessReport,
    InitialScheduleRequest,
    ReadinessIssue,
)
from app.models.schedule import ScheduleSnapshot


_INITIAL_REQUIRED_INPUTS = [
    "resources.resource_id",
    "resources.capabilities",
    "work_orders.work_order_id",
    "work_orders.due_date",
    "operations.operation_id",
    "operations.duration_minutes",
    "operations.eligible_resource_ids",
    "operations.predecessor_ids",
    "operations.material_requirements.available_at",
    "resource_calendar.unavailable_windows",
    "changeover_rules.product_family_setup",
]

_RESCHEDULE_REQUIRED_INPUTS = [
    "snapshot.work_orders",
    "operations.operation_id",
    "operations.resource_id",
    "operations.start_time",
    "operations.end_time",
    "operations.predecessor_ids",
    "operations.successor_ids",
]


class DataReadinessService:
    """Validates whether customer data is usable for PoC planning runs."""

    def assess_initial_schedule_request(
        self, request: InitialScheduleRequest
    ) -> DataReadinessReport:
        issues: list[ReadinessIssue] = []

        resource_ids = [r.resource_id for r in request.resources]
        resource_set = set(resource_ids)
        capability_by_resource = {
            r.resource_id: set(r.capabilities) for r in request.resources
        }

        if not request.resources:
            issues.append(_blocker("missing_resources", "No resources provided."))
        if not request.work_orders:
            issues.append(_blocker("missing_work_orders", "No work orders provided."))

        issues.extend(_duplicate_issues(resource_ids, "resource", "resource_id"))

        operation_ids: list[str] = []
        predecessor_edges: dict[str, list[str]] = {}
        operation_to_work_order: dict[str, str] = {}

        for wo in request.work_orders:
            if wo.due_date <= request.planning_start:
                issues.append(
                    _warning(
                        "due_date_before_planning_start",
                        "Work order due date is not later than planning_start.",
                        "work_order",
                        wo.work_order_id,
                    )
                )
            if not wo.operations:
                issues.append(
                    _blocker(
                        "work_order_has_no_operations",
                        "Work order has no operations.",
                        "work_order",
                        wo.work_order_id,
                    )
                )
            if not wo.product_family:
                issues.append(
                    _warning(
                        "missing_product_family",
                        "Product family is missing; changeover-aware scoring will be approximate.",
                        "work_order",
                        wo.work_order_id,
                    )
                )

            for op in wo.operations:
                operation_ids.append(op.operation_id)
                operation_to_work_order[op.operation_id] = wo.work_order_id
                predecessor_edges[op.operation_id] = list(op.predecessor_ids)

                if op.work_order_id != wo.work_order_id:
                    issues.append(
                        _blocker(
                            "operation_work_order_mismatch",
                            "Operation work_order_id does not match parent work order.",
                            "operation",
                            op.operation_id,
                        )
                    )
                if not op.eligible_resource_ids:
                    issues.append(
                        _blocker(
                            "missing_eligible_resources",
                            "Operation has no eligible resources.",
                            "operation",
                            op.operation_id,
                        )
                    )
                for rid in op.eligible_resource_ids:
                    if rid not in resource_set:
                        issues.append(
                            _blocker(
                                "unknown_eligible_resource",
                                f"Eligible resource '{rid}' is not defined.",
                                "operation",
                                op.operation_id,
                            )
                        )
                for rid in op.eligible_resource_ids:
                    missing_caps = set(op.required_capabilities) - capability_by_resource.get(rid, set())
                    if missing_caps:
                        issues.append(
                            _warning(
                                "resource_capability_gap",
                                (
                                    f"Resource '{rid}' is missing required capabilities "
                                    f"{sorted(missing_caps)}."
                                ),
                                "operation",
                                op.operation_id,
                            )
                        )
                if op.required_capabilities and op.eligible_resource_ids:
                    has_capable_resource = any(
                        set(op.required_capabilities).issubset(capability_by_resource.get(rid, set()))
                        for rid in op.eligible_resource_ids
                    )
                    if not has_capable_resource:
                        issues.append(
                            _blocker(
                                "no_capable_eligible_resource",
                                "No eligible resource satisfies all required capabilities.",
                                "operation",
                                op.operation_id,
                            )
                        )
                for mat in op.material_requirements:
                    if mat.status not in {"available", "reserved", "delayed", "unknown"}:
                        issues.append(
                            _warning(
                                "unknown_material_status",
                                f"Material '{mat.material_id}' has non-standard status '{mat.status}'.",
                                "operation",
                                op.operation_id,
                            )
                        )
                    if mat.status == "delayed" and mat.available_at is None:
                        issues.append(
                            _blocker(
                                "delayed_material_missing_available_at",
                                f"Delayed material '{mat.material_id}' must provide available_at.",
                                "operation",
                                op.operation_id,
                            )
                        )

        issues.extend(_duplicate_issues(operation_ids, "operation", "operation_id"))

        op_set = set(operation_ids)
        for op_id, preds in predecessor_edges.items():
            for pred in preds:
                if pred not in op_set:
                    issues.append(
                        _blocker(
                            "unknown_predecessor",
                            f"Predecessor '{pred}' is not defined.",
                            "operation",
                            op_id,
                        )
                    )
                elif operation_to_work_order.get(pred) != operation_to_work_order.get(op_id):
                    issues.append(
                        _warning(
                            "cross_work_order_precedence",
                            f"Predecessor '{pred}' belongs to another work order.",
                            "operation",
                            op_id,
                        )
                    )

        cycle_nodes = _find_cycle_nodes(predecessor_edges)
        for op_id in cycle_nodes:
            issues.append(
                _blocker(
                    "precedence_cycle",
                    "Operation participates in a precedence cycle.",
                    "operation",
                    op_id,
                )
            )

        if request.resources and not any(r.is_bottleneck for r in request.resources):
            issues.append(
                _warning(
                    "no_bottleneck_marked",
                    "No bottleneck resource marked; bottleneck-priority option will use generic load balance.",
                )
            )

        for window in request.resource_calendar:
            if window.resource_id not in resource_set:
                issues.append(
                    _blocker(
                        "calendar_unknown_resource",
                        f"Calendar window references unknown resource '{window.resource_id}'.",
                        "resource",
                        window.resource_id,
                    )
                )
            if window.window_end <= window.window_start:
                issues.append(
                    _blocker(
                        "invalid_calendar_window",
                        "Calendar window_end must be later than window_start.",
                        "resource",
                        window.resource_id,
                    )
                )

        known_families = {
            wo.product_family
            for wo in request.work_orders
            if wo.product_family
        } | {
            op.product_family
            for wo in request.work_orders
            for op in wo.operations
            if op.product_family
        }
        for rule in request.changeover_rules:
            if rule.resource_id and rule.resource_id not in resource_set:
                issues.append(
                    _blocker(
                        "changeover_unknown_resource",
                        f"Changeover rule references unknown resource '{rule.resource_id}'.",
                        "resource",
                        rule.resource_id,
                    )
                )
            if rule.from_product_family not in known_families or rule.to_product_family not in known_families:
                issues.append(
                    _warning(
                        "changeover_family_not_in_orders",
                        "Changeover rule references a product family not present in current orders.",
                    )
                )

        return _build_report(issues, _INITIAL_REQUIRED_INPUTS)

    def assess_schedule_snapshot(self, snapshot: ScheduleSnapshot) -> DataReadinessReport:
        issues: list[ReadinessIssue] = []

        if not snapshot.work_orders:
            issues.append(_blocker("snapshot_has_no_work_orders", "Schedule snapshot has no work orders."))

        operation_ids: list[str] = []
        for wo in snapshot.work_orders:
            if not wo.operations:
                issues.append(
                    _warning(
                        "snapshot_work_order_has_no_operations",
                        "Work order has no operations in snapshot.",
                        "work_order",
                        wo.work_order_id,
                    )
                )
            for op in wo.operations:
                operation_ids.append(op.operation_id)
                if op.end_time <= op.start_time:
                    issues.append(
                        _blocker(
                            "invalid_operation_time_window",
                            "Operation end_time must be later than start_time.",
                            "operation",
                            op.operation_id,
                        )
                    )
                if not op.resource_id:
                    issues.append(
                        _blocker(
                            "missing_resource_assignment",
                            "Operation has no resource assignment.",
                            "operation",
                            op.operation_id,
                        )
                    )

        issues.extend(_duplicate_issues(operation_ids, "operation", "operation_id"))
        return _build_report(issues, _RESCHEDULE_REQUIRED_INPUTS)


def _blocker(
    code: str,
    message: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> ReadinessIssue:
    return ReadinessIssue(
        severity="blocker",
        code=code,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def _warning(
    code: str,
    message: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> ReadinessIssue:
    return ReadinessIssue(
        severity="warning",
        code=code,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def _duplicate_issues(values: list[str], entity_type: str, field_name: str) -> list[ReadinessIssue]:
    result: list[ReadinessIssue] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    for value in sorted(duplicates):
        result.append(
            _blocker(
                f"duplicate_{field_name}",
                f"Duplicate {field_name}: {value}.",
                entity_type,
                value,
            )
        )
    return result


def _find_cycle_nodes(edges: dict[str, list[str]]) -> set[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            if node in stack:
                cycle_nodes.update(stack[stack.index(node):])
            return
        visiting.add(node)
        stack.append(node)
        for pred in edges.get(node, []):
            if pred in edges:
                visit(pred, stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in edges:
        visit(node, [])
    return cycle_nodes


def _build_report(
    issues: list[ReadinessIssue],
    required_inputs: list[str],
) -> DataReadinessReport:
    blockers = [issue for issue in issues if issue.severity == "blocker"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    infos = [issue for issue in issues if issue.severity == "info"]

    penalty = len(blockers) * 0.25 + len(warnings) * 0.05
    readiness_score = max(0.0, round(1.0 - penalty, 4))

    recommendations: list[str] = []
    if blockers:
        codes = sorted({issue.code for issue in blockers})
        recommendations.append(f"Resolve blocking data issues first: {', '.join(codes)}.")
    if warnings:
        recommendations.append("Warnings can be accepted for PoC, but they reduce plan explainability and ROI confidence.")
    if not blockers:
        recommendations.append("Data is ready for a PoC planning run.")

    return DataReadinessReport(
        is_ready=not blockers,
        readiness_score=readiness_score,
        blockers=blockers,
        warnings=warnings,
        infos=infos,
        required_inputs=required_inputs,
        recommendations=recommendations,
    )
