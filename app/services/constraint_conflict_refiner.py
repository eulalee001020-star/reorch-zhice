"""Bounded deterministic conflict extraction for infeasible schedules."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from app.models.feasibility_restoration import (
    ConflictConstraint,
    ConflictRefinementReport,
    FailureClassification,
)
from app.models.impact import ImpactReport
from app.models.schedule import Operation, ScheduleSnapshot
from app.models.solver import ConstraintViolation
from app.services.constraint_assumption_registry import ConstraintAssumptionRegistry


class ConstraintConflictRefiner:
    """Extract auditable conflict sets without relaxing production constraints."""

    def __init__(
        self, registry: ConstraintAssumptionRegistry | None = None
    ) -> None:
        self._registry = registry or ConstraintAssumptionRegistry()

    def refine(
        self,
        *,
        snapshot: ScheduleSnapshot,
        impact_report: ImpactReport,
        frozen_operation_ids: list[str],
        classification: FailureClassification,
        independent_violations: list[ConstraintViolation] | None = None,
    ) -> ConflictRefinementReport:
        raw = snapshot.raw_data or {}
        operations = {
            operation.operation_id: operation
            for work_order in snapshot.work_orders
            for operation in work_order.operations
        }
        raw_operations = _raw_operations(raw)
        conflicts: list[ConflictConstraint] = []
        proven_by_bounds = False

        conflicts.extend(_governance_conflicts(classification.blockers))
        conflicts.extend(_source_state_conflicts(raw, operations))

        delay_by_operation = {
            item.operation_id: max(0.0, item.estimated_delay_minutes)
            for item in impact_report.affected_operations
        }
        quality_frozen = {
            str(operation_id)
            for row in raw.get("quality_holds", []) or []
            if str(row.get("status", "held")).lower()
            not in {"released", "cleared", "closed"}
            for operation_id in row.get("blocked_operation_ids", []) or []
        }
        frozen = set(frozen_operation_ids) | {
            str(item) for item in raw.get("frozen_operation_ids", []) or []
        }
        for operation_id in sorted(frozen & set(delay_by_operation)):
            if delay_by_operation[operation_id] <= 0:
                continue
            operation = operations.get(operation_id)
            if operation is None:
                continue
            raw_operation = raw_operations.get(operation_id, {})
            status = str(raw_operation.get("status", "unknown")).lower()
            planning_freeze = (
                operation_id not in quality_frozen
                and status in {"planned", "queued", "released", "scheduled"}
            )
            if not planning_freeze:
                continue
            conflicts.append(
                _conflict(
                    family="frozen_incident_operation",
                    operation_ids=[operation_id],
                    work_order_ids=[operation.work_order_id],
                    resource_ids=[operation.resource_id],
                    hard=False,
                    relaxable=True,
                    actions=["release_planning_freeze", "defer_work_order", "safe_hold"],
                    detail=(
                        "The operation is frozen at its baseline time while the incident "
                        f"requires a {delay_by_operation[operation_id]:g}-minute displacement."
                    ),
                    proof_method="contradictory_fixed_and_incident_time_bounds",
                    source_refs=_refs(raw_operation),
                )
            )
            proven_by_bounds = True

        for operation in operations.values():
            interval_conflict = _operation_interval_conflict(
                operation,
                raw_operations.get(operation.operation_id, {}),
                raw,
                delay_by_operation.get(operation.operation_id, 0.0),
            )
            if interval_conflict is not None:
                conflicts.append(interval_conflict)
                proven_by_bounds = True

        conflicts.extend(_resource_capability_conflicts(snapshot, raw_operations))
        for violation in independent_violations or []:
            conflicts.append(
                _conflict(
                    family=violation.constraint_type,
                    operation_ids=[violation.operation_id],
                    resource_ids=[violation.resource_id]
                    if violation.resource_id
                    else [],
                    hard=True,
                    relaxable=False,
                    actions=["safe_hold"],
                    detail=violation.detail,
                    proof_method="independent_constraint_validator",
                )
            )

        conflicts = _deduplicate(conflicts)
        if proven_by_bounds:
            core_status = "proven_by_interval_bounds"
            explanation = (
                "At least one contradiction is proven from fixed, release, incident, "
                "duration, or deadline bounds. Other independent conflicts may still exist."
            )
        elif conflicts:
            core_status = "observed_conflict_set"
            explanation = (
                "The report contains deterministic source-state or validator conflicts; "
                "it is not claimed to be the unique irreducible conflict core."
            )
        else:
            core_status = "not_available"
            explanation = (
                "No bounded conflict proof was extracted. Preserve the baseline and do not "
                "treat an UNKNOWN or timeout status as proven infeasibility."
            )
        return ConflictRefinementReport(
            constraint_registry_version=self._registry.version,
            core_status=core_status,
            conflicts=conflicts,
            explanation=explanation,
        )


def _operation_interval_conflict(
    operation: Operation,
    raw_operation: dict[str, Any],
    raw: dict[str, Any],
    incident_delay_minutes: float,
) -> ConflictConstraint | None:
    operation_id = operation.operation_id
    earliest = operation.start_time + timedelta(minutes=max(0.0, incident_delay_minutes))
    sources = _refs(raw_operation)
    cause_names: list[str] = []

    for row in raw.get("operation_release_constraints", []) or []:
        if str(row.get("operation_id", "")) != operation_id:
            continue
        release = _datetime(row.get("release_at"))
        if release and release > earliest:
            earliest = release
            cause_names.append("operation_release")
        sources.extend(_refs(row))

    shortage = False
    substitute_release: datetime | None = None
    for row in raw.get("material_availability", []) or []:
        if operation_id not in {
            str(item) for item in row.get("operation_ids", []) or []
        }:
            continue
        if float(row.get("available_quantity", 0) or 0) < float(
            row.get("required_quantity", 1) or 1
        ):
            shortage = True
        available_at = _datetime(row.get("available_at"))
        if available_at and available_at > earliest:
            earliest = available_at
            cause_names.append("material_release")
        sources.extend(_refs(row))
    if shortage:
        approved_substitutes = [
            row
            for row in raw.get("substitute_material_approvals", []) or []
            if operation_id
            in {str(item) for item in row.get("operation_ids", []) or []}
            and str(row.get("approval_status", "pending")).lower() == "approved"
            and row.get("approved_by")
            and row.get("source_ref")
            and float(row.get("available_quantity", 0) or 0)
            >= float(row.get("required_quantity", 1) or 1)
        ]
        if not approved_substitutes:
            return _conflict(
                family="material_availability",
                operation_ids=[operation_id],
                work_order_ids=[operation.work_order_id],
                resource_ids=[operation.resource_id],
                hard=True,
                relaxable=False,
                actions=[
                    "activate_substitute_material",
                    "activate_outsourcing",
                    "defer_work_order",
                    "safe_hold",
                ],
                detail="Required material quantity is unavailable and no approved substitute covers it.",
                proof_method="source_quantity_bound",
                source_refs=sources,
            )
        substitute_dates = [
            value
            for value in (_datetime(row.get("available_at")) for row in approved_substitutes)
            if value is not None
        ]
        if substitute_dates:
            substitute_release = min(substitute_dates)
            earliest = max(earliest, substitute_release)
            cause_names.append("approved_substitute_release")

    deadline_rows = [
        (deadline, row)
        for row in raw.get("operation_deadline_constraints", []) or []
        for deadline in [_datetime(row.get("deadline_at"))]
        if str(row.get("operation_id", "")) == operation_id
        and deadline is not None
    ]
    if not deadline_rows:
        return None
    deadline, deadline_row = min(deadline_rows, key=lambda item: item[0])
    sources.extend(_refs(deadline_row))
    duration = max(1, int((operation.end_time - operation.start_time).total_seconds() // 60))
    processing = raw_operation.get("processing_minutes_by_resource", {}) or {}
    if isinstance(processing, dict):
        values = [int(value) for value in processing.values() if int(value) > 0]
        if values:
            duration = min(values)
    earliest_end = earliest + timedelta(minutes=duration)
    if earliest_end <= deadline:
        return None
    relaxable = bool(deadline_row.get("relaxable"))
    actions = ["defer_work_order", "safe_hold"]
    if relaxable:
        actions.insert(0, "relax_operation_deadline")
    actions.insert(0, "activate_outsourcing")
    return _conflict(
        family="operation_time_window",
        operation_ids=[operation_id],
        work_order_ids=[operation.work_order_id],
        resource_ids=[operation.resource_id],
        hard=not relaxable,
        relaxable=relaxable,
        actions=actions,
        detail=(
            f"Earliest possible end {earliest_end.isoformat()} exceeds deadline "
            f"{deadline.isoformat()}; causes={sorted(set(cause_names)) or ['baseline_or_incident_bound']}."
        ),
        proof_method="interval_bound_proof",
        source_refs=sources,
    )


def _source_state_conflicts(
    raw: dict[str, Any], operations: dict[str, Operation]
) -> list[ConflictConstraint]:
    result: list[ConflictConstraint] = []
    for row in raw.get("buffer_flows", []) or []:
        if int(row.get("current_wip", 0) or 0) <= int(row.get("capacity", 0) or 0):
            continue
        operation_ids = [
            str(row.get("predecessor_operation_id", "")),
            str(row.get("successor_operation_id", "")),
        ]
        result.append(
            _conflict(
                family="buffer_capacity",
                operation_ids=[item for item in operation_ids if item],
                hard=True,
                relaxable=False,
                actions=["defer_work_order", "safe_hold"],
                detail="Current WIP already exceeds the governed physical buffer capacity.",
                proof_method="source_capacity_bound",
                source_refs=_refs(row),
            )
        )
    for row in raw.get("qms_release_gates", []) or []:
        status = str(row.get("status", "pending")).lower()
        required = {str(item) for item in row.get("required_approvals", []) or []}
        approvals = {str(item) for item in row.get("approvals", []) or []}
        evidence_missing = not row.get("certificate_ref") or not row.get("source_ref")
        if status in {"released", "cleared", "closed"} and required.issubset(
            approvals
        ) and not evidence_missing:
            continue
        result.append(
            _conflict(
                family="qms_release",
                operation_ids=[str(item) for item in row.get("operation_ids", []) or []],
                hard=True,
                relaxable=False,
                actions=["safe_hold"],
                detail="QMS release, required approvals, or governed release evidence is missing.",
                proof_method="governed_source_state",
                source_refs=_refs(row),
            )
        )
    for row in raw.get("batch_genealogy", []) or []:
        if str(row.get("quality_state", "released")).lower() in {
            "released",
            "cleared",
            "closed",
        } and not (row.get("rework_required") and not row.get("rework_operation_id")):
            continue
        result.append(
            _conflict(
                family="batch_genealogy",
                operation_ids=[str(item) for item in row.get("operation_ids", []) or []],
                hard=True,
                relaxable=False,
                actions=["safe_hold"],
                detail="Batch is not quality-released or required rework lineage is incomplete.",
                proof_method="governed_source_state",
                source_refs=_refs(row),
            )
        )
    return result


def _resource_capability_conflicts(
    snapshot: ScheduleSnapshot,
    raw_operations: dict[str, dict[str, Any]],
) -> list[ConflictConstraint]:
    raw = snapshot.raw_data or {}
    capabilities = {
        str(row.get("resource_id", "")): {
            str(item) for item in row.get("capabilities", []) or []
        }
        for row in raw.get("resources", []) or []
        if row.get("resource_id")
    }
    if not capabilities:
        return []
    result: list[ConflictConstraint] = []
    for work_order in snapshot.work_orders:
        for operation in work_order.operations:
            raw_operation = raw_operations.get(operation.operation_id, {})
            eligible = {
                str(item)
                for item in raw_operation.get("eligible_resources", []) or []
            } or {operation.resource_id}
            required = set(operation.required_capabilities)
            qualified = [
                resource_id
                for resource_id in eligible
                if resource_id in capabilities
                and required.issubset(capabilities[resource_id])
            ]
            if qualified:
                continue
            result.append(
                _conflict(
                    family="equipment_capability",
                    operation_ids=[operation.operation_id],
                    work_order_ids=[operation.work_order_id],
                    resource_ids=sorted(eligible),
                    hard=True,
                    relaxable=False,
                    actions=["activate_outsourcing", "defer_work_order", "safe_hold"],
                    detail="No eligible resource satisfies all required operation capabilities.",
                    proof_method="resource_master_capability_set",
                    source_refs=_refs(raw_operation),
                )
            )
    return result


def _governance_conflicts(blockers: list[str]) -> list[ConflictConstraint]:
    result: list[ConflictConstraint] = []
    for blocker in blockers:
        normalized = blocker.lower()
        family = None
        if "qms" in normalized:
            family = "qms_release"
        elif "batch" in normalized or "rework" in normalized:
            family = "batch_genealogy"
        elif "buffer" in normalized:
            family = "buffer_capacity"
        elif "quality" in normalized:
            family = "quality_hold"
        if family is None:
            continue
        result.append(
            _conflict(
                family=family,
                hard=True,
                relaxable=False,
                actions=["safe_hold"],
                detail=blocker,
                proof_method="solver_governance_blocker",
            )
        )
    return result


def _conflict(
    *,
    family: str,
    hard: bool,
    relaxable: bool,
    actions: list[str],
    detail: str,
    proof_method: str,
    operation_ids: list[str] | None = None,
    work_order_ids: list[str] | None = None,
    resource_ids: list[str] | None = None,
    source_refs: list[str] | None = None,
) -> ConflictConstraint:
    payload = "|".join(
        [family, *(operation_ids or []), *(work_order_ids or []), detail]
    )
    return ConflictConstraint(
        conflict_id=f"conflict-{hashlib.sha256(payload.encode()).hexdigest()[:16]}",
        constraint_family=family,
        operation_ids=sorted(set(operation_ids or [])),
        work_order_ids=sorted(set(work_order_ids or [])),
        resource_ids=sorted(set(resource_ids or [])),
        hard_constraint=hard,
        directly_relaxable=relaxable,
        recovery_action_types=actions,
        detail=detail,
        proof_method=proof_method,
        source_refs=sorted(set(source_refs or [])),
    )


def _deduplicate(conflicts: list[ConflictConstraint]) -> list[ConflictConstraint]:
    by_scope: dict[tuple[object, ...], ConflictConstraint] = {}
    for item in conflicts:
        key = (
            item.constraint_family,
            tuple(item.operation_ids),
            tuple(item.work_order_ids),
            tuple(item.resource_ids),
        )
        by_scope.setdefault(key, item)
    return sorted(by_scope.values(), key=lambda item: item.conflict_id)


def _raw_operations(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(operation["operation_id"]): operation
        for work_order in raw.get("work_orders", []) or []
        for operation in work_order.get("operations", []) or []
        if operation.get("operation_id")
    }


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _refs(row: dict[str, Any]) -> list[str]:
    return [
        str(value)
        for key in ("source_ref", "certificate_ref", "constraint_id", "hold_id")
        for value in [row.get(key)]
        if value
    ]
