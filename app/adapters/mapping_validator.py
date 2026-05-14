"""Validation utilities for customer adapter field mapping.

The validator checks whether ERP/MES/APS payloads have been mapped into a
safe canonical dataset before ReOrch runs impact analysis, solving, or
writeback. It does not repair schedules or infer missing production facts.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Literal, TypeVar

from pydantic import Field

from app.adapters.mapping_schema import (
    AdapterMappingProfile,
    CanonicalIncident,
    CanonicalMachine,
    CanonicalOperation,
    CanonicalWorkOrder,
    map_incident,
    map_machine,
    map_operation,
    map_work_order,
)
from app.models.base import ReOrchModel
from app.models.enums import IncidentSeverity, IncidentType

Severity = Literal["error", "warning"]
T = TypeVar("T")

_ALLOWED_WORK_ORDER_STATUSES = {
    "released",
    "in_progress",
    "completed",
    "cancelled",
    "on_hold",
    "planned",
}
_ALLOWED_MACHINE_STATUSES = {
    "available",
    "down",
    "maintenance",
    "offline",
    "unavailable",
    "busy",
}
_ALLOWED_INCIDENT_TYPES = {
    "machine_down",
    "material_shortage",
    "urgent_order_insert",
    "capacity_degradation",
    IncidentType.EQUIPMENT_FAILURE.value,
}
_ALLOWED_SEVERITIES = {item.value for item in IncidentSeverity} | {
    "P1",
    "P2",
    "P3",
    "P4",
}


class CanonicalDataset(ReOrchModel):
    """Canonical adapter output to validate before downstream processing."""

    work_orders: list[CanonicalWorkOrder] = Field(default_factory=list)
    operations: list[CanonicalOperation] = Field(default_factory=list)
    machines: list[CanonicalMachine] = Field(default_factory=list)
    incidents: list[CanonicalIncident] = Field(default_factory=list)


class MappingValidationIssue(ReOrchModel):
    """Single validation issue found in customer integration data."""

    code: str
    category: str
    severity: Severity
    entity_type: str
    entity_id: str | None = None
    field: str | None = None
    message: str


class MappingValidationReport(ReOrchModel):
    """Summary report for adapter mapping and canonical dataset quality."""

    total_records: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    missing_required_fields: int = 0
    enum_errors: int = 0
    time_parse_errors: int = 0
    reference_integrity_errors: int = 0
    blocking_errors: int = 0
    warnings: int = 0
    issues: list[MappingValidationIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True when no blocking issue was found."""
        return self.blocking_errors == 0


def validate_customer_payloads(
    *,
    raw_work_orders: Sequence[dict[str, Any]],
    raw_operations: Sequence[dict[str, Any]],
    raw_machines: Sequence[dict[str, Any]],
    raw_incidents: Sequence[dict[str, Any]] | None = None,
    profile: AdapterMappingProfile | None = None,
) -> MappingValidationReport:
    """Map raw customer payloads and validate the resulting canonical dataset."""
    mapping_profile = profile or AdapterMappingProfile()
    issues: list[MappingValidationIssue] = []

    work_orders = _map_raw_rows(
        "work_order",
        raw_work_orders,
        mapping_profile,
        issues,
        map_work_order,
    )
    operations = _map_raw_rows(
        "operation",
        raw_operations,
        mapping_profile,
        issues,
        map_operation,
    )
    machines = _map_raw_rows(
        "machine",
        raw_machines,
        mapping_profile,
        issues,
        map_machine,
    )
    incidents = _map_raw_rows(
        "incident",
        raw_incidents or [],
        mapping_profile,
        issues,
        map_incident,
    )

    return validate_canonical_dataset(
        CanonicalDataset(
            work_orders=work_orders,
            operations=operations,
            machines=machines,
            incidents=incidents,
        ),
        initial_issues=issues,
        total_records_override=(
            len(raw_work_orders)
            + len(raw_operations)
            + len(raw_machines)
            + len(raw_incidents or [])
        ),
    )


def validate_canonical_dataset(
    dataset: CanonicalDataset,
    *,
    initial_issues: Sequence[MappingValidationIssue] | None = None,
    total_records_override: int | None = None,
) -> MappingValidationReport:
    """Validate canonical objects emitted by CSV, REST, mock, or customer adapters."""
    issues = list(initial_issues or [])
    work_order_ids = _check_unique_ids(
        "work_order",
        dataset.work_orders,
        lambda item: item.work_order_id,
        issues,
    )
    machine_ids = _check_unique_ids(
        "machine",
        dataset.machines,
        lambda item: item.machine_id,
        issues,
    )
    operation_ids = _check_unique_ids(
        "operation",
        dataset.operations,
        lambda item: item.operation_id,
        issues,
    )
    _check_unique_ids(
        "incident",
        dataset.incidents,
        lambda item: item.incident_id,
        issues,
    )

    machines_by_id = {machine.machine_id: machine for machine in dataset.machines}
    operations_by_work_order: dict[str, list[CanonicalOperation]] = {}
    for operation in dataset.operations:
        operations_by_work_order.setdefault(operation.work_order_id, []).append(operation)

    for work_order in dataset.work_orders:
        _check_required(
            issues,
            "work_order",
            work_order.work_order_id,
            "work_order_id",
            work_order.work_order_id,
        )
        _check_required(
            issues,
            "work_order",
            work_order.work_order_id,
            "product_name",
            work_order.product_name,
        )
        if work_order.quantity <= 0:
            _add_issue(
                issues,
                "quantity_not_positive",
                "value_range",
                "error",
                "work_order",
                work_order.work_order_id,
                "quantity",
                "Work order quantity must be greater than 0.",
            )
        _check_enum(
            issues,
            "work_order",
            work_order.work_order_id,
            "status",
            work_order.status,
            _ALLOWED_WORK_ORDER_STATUSES,
        )
        _check_timezone(
            issues,
            "work_order",
            work_order.work_order_id,
            "due_time",
            work_order.due_time,
        )
        order_ops = operations_by_work_order.get(work_order.work_order_id, [])
        if order_ops:
            latest_end = max(
                (op.end_time for op in order_ops if op.end_time is not None),
                default=None,
            )
            if latest_end and work_order.due_time < latest_end:
                _add_issue(
                    issues,
                    "due_time_before_scheduled_end",
                    "business_warning",
                    "warning",
                    "work_order",
                    work_order.work_order_id,
                    "due_time",
                    "Due time is earlier than the latest scheduled operation end.",
                )

    for machine in dataset.machines:
        _check_required(
            issues,
            "machine",
            machine.machine_id,
            "machine_id",
            machine.machine_id,
        )
        _check_enum(
            issues,
            "machine",
            machine.machine_id,
            "status",
            machine.status,
            _ALLOWED_MACHINE_STATUSES,
        )
        if not machine.capabilities:
            _add_issue(
                issues,
                "missing_machine_capabilities",
                "data_completeness",
                "warning",
                "machine",
                machine.machine_id,
                "capabilities",
                "Machine has no capability mapping; solver eligibility may be incomplete.",
            )

    for operation in dataset.operations:
        _check_required(
            issues,
            "operation",
            operation.operation_id,
            "operation_id",
            operation.operation_id,
        )
        _check_required(
            issues,
            "operation",
            operation.operation_id,
            "work_order_id",
            operation.work_order_id,
        )
        if operation.processing_time_min <= 0:
            _add_issue(
                issues,
                "processing_time_not_positive",
                "value_range",
                "error",
                "operation",
                operation.operation_id,
                "processing_time_min",
                "Processing time must be greater than 0 minutes.",
            )
        if operation.work_order_id not in work_order_ids:
            _add_issue(
                issues,
                "unknown_work_order_reference",
                "reference_integrity",
                "error",
                "operation",
                operation.operation_id,
                "work_order_id",
                f"Operation references unknown work order {operation.work_order_id!r}.",
            )
        for predecessor_id in operation.predecessors:
            if predecessor_id not in operation_ids:
                _add_issue(
                    issues,
                    "unknown_predecessor_reference",
                    "reference_integrity",
                    "error",
                    "operation",
                    operation.operation_id,
                    "predecessors",
                    f"Operation references unknown predecessor {predecessor_id!r}.",
                )
        for successor_id in operation.successors:
            if successor_id not in operation_ids:
                _add_issue(
                    issues,
                    "unknown_successor_reference",
                    "reference_integrity",
                    "error",
                    "operation",
                    operation.operation_id,
                    "successors",
                    f"Operation references unknown successor {successor_id!r}.",
                )
        _check_operation_time_range(issues, operation)
        _check_machine_references(issues, operation, machine_ids, machines_by_id)

    for incident in dataset.incidents:
        _check_required(
            issues,
            "incident",
            incident.incident_id,
            "incident_id",
            incident.incident_id,
        )
        _check_enum(
            issues,
            "incident",
            incident.incident_id,
            "incident_type",
            incident.incident_type,
            _ALLOWED_INCIDENT_TYPES,
        )
        _check_enum(
            issues,
            "incident",
            incident.incident_id,
            "severity",
            incident.severity,
            _ALLOWED_SEVERITIES,
        )
        _check_timezone(
            issues,
            "incident",
            incident.incident_id,
            "start_time",
            incident.start_time,
        )
        if incident.machine_id not in machine_ids:
            _add_issue(
                issues,
                "unknown_incident_machine_reference",
                "reference_integrity",
                "error",
                "incident",
                incident.incident_id,
                "machine_id",
                f"Incident references unknown machine {incident.machine_id!r}.",
            )

    total_records = total_records_override
    if total_records is None:
        total_records = (
            len(dataset.work_orders)
            + len(dataset.operations)
            + len(dataset.machines)
            + len(dataset.incidents)
        )
    return _build_report(total_records, issues)


def _map_raw_rows(
    entity_type: str,
    rows: Sequence[dict[str, Any]],
    profile: AdapterMappingProfile,
    issues: list[MappingValidationIssue],
    mapper: Callable[[dict[str, Any], AdapterMappingProfile], T],
) -> list[T]:
    mapped: list[T] = []
    for index, row in enumerate(rows):
        entity_id = _raw_entity_id(entity_type, row, profile) or f"row-{index}"
        if _has_missing_raw_required_fields(entity_type, row, profile, issues, entity_id):
            continue
        try:
            mapped.append(mapper(row, profile))
        except Exception as exc:
            code = "time_parse_error" if _looks_like_time_error(exc) else "mapping_error"
            category = "time_format" if code == "time_parse_error" else "mapping"
            _add_issue(
                issues,
                code,
                category,
                "error",
                entity_type,
                entity_id,
                None,
                f"Cannot map customer payload: {exc}",
            )
    return mapped


def _has_missing_raw_required_fields(
    entity_type: str,
    row: dict[str, Any],
    profile: AdapterMappingProfile,
    issues: list[MappingValidationIssue],
    entity_id: str,
) -> bool:
    fields_by_entity = {
        "work_order": ("work_order_id", "due_time"),
        "operation": ("operation_id", "work_order_id"),
        "machine": ("machine_id",),
        "incident": ("incident_id", "incident_type", "machine_id", "start_time"),
    }
    missing = False
    mapping = getattr(profile.field_mapping, entity_type)
    for canonical_field in fields_by_entity[entity_type]:
        source_field = mapping.get(canonical_field, "")
        if _is_missing(_raw_get(row, source_field)):
            missing = True
            _add_issue(
                issues,
                "missing_required_field",
                "required_field",
                "error",
                entity_type,
                entity_id,
                canonical_field,
                f"Required canonical field {canonical_field!r} is missing from source field {source_field!r}.",
            )
    return missing


def _check_unique_ids(
    entity_type: str,
    items: Sequence[T],
    get_id: Callable[[T], str],
    issues: list[MappingValidationIssue],
) -> set[str]:
    seen: set[str] = set()
    for item in items:
        item_id = get_id(item)
        if _is_missing(item_id):
            continue
        if item_id in seen:
            _add_issue(
                issues,
                "duplicate_id",
                "identity",
                "error",
                entity_type,
                item_id,
                None,
                f"Duplicate {entity_type} id {item_id!r}.",
            )
        seen.add(item_id)
    return seen


def _check_required(
    issues: list[MappingValidationIssue],
    entity_type: str,
    entity_id: str | None,
    field: str,
    value: Any,
) -> None:
    if _is_missing(value):
        _add_issue(
            issues,
            "missing_required_field",
            "required_field",
            "error",
            entity_type,
            entity_id,
            field,
            f"Required field {field!r} is empty.",
        )


def _check_enum(
    issues: list[MappingValidationIssue],
    entity_type: str,
    entity_id: str | None,
    field: str,
    value: str,
    allowed_values: set[str],
) -> None:
    if value not in allowed_values:
        _add_issue(
            issues,
            "enum_error",
            "enum",
            "error",
            entity_type,
            entity_id,
            field,
            f"Value {value!r} is not in allowed values: {sorted(allowed_values)}.",
        )


def _check_timezone(
    issues: list[MappingValidationIssue],
    entity_type: str,
    entity_id: str,
    field: str,
    value: datetime,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        _add_issue(
            issues,
            "timezone_missing",
            "time_format",
            "warning",
            entity_type,
            entity_id,
            field,
            "Datetime has no timezone; customer integration should use ISO8601 with timezone.",
        )


def _check_operation_time_range(
    issues: list[MappingValidationIssue],
    operation: CanonicalOperation,
) -> None:
    if operation.start_time is None or operation.end_time is None:
        return
    _check_timezone(
        issues,
        "operation",
        operation.operation_id,
        "start_time",
        operation.start_time,
    )
    _check_timezone(
        issues,
        "operation",
        operation.operation_id,
        "end_time",
        operation.end_time,
    )
    if operation.end_time <= operation.start_time:
        _add_issue(
            issues,
            "invalid_time_range",
            "time_format",
            "error",
            "operation",
            operation.operation_id,
            "end_time",
            "Operation end_time must be later than start_time.",
        )


def _check_machine_references(
    issues: list[MappingValidationIssue],
    operation: CanonicalOperation,
    machine_ids: set[str],
    machines_by_id: dict[str, CanonicalMachine],
) -> None:
    referenced_machine_ids = set(operation.eligible_machine_ids)
    if operation.machine_id:
        referenced_machine_ids.add(operation.machine_id)
    for machine_id in sorted(referenced_machine_ids):
        if machine_id not in machine_ids:
            _add_issue(
                issues,
                "unknown_machine_reference",
                "reference_integrity",
                "error",
                "operation",
                operation.operation_id,
                "machine_id",
                f"Operation references unknown machine {machine_id!r}.",
            )
    if not operation.machine_id or operation.machine_id not in machines_by_id:
        return
    required_capabilities = set(operation.required_capabilities)
    if not required_capabilities:
        _add_issue(
            issues,
            "missing_operation_capabilities",
            "data_completeness",
            "warning",
            "operation",
            operation.operation_id,
            "required_capabilities",
            "Operation has no required capability mapping.",
        )
        return
    machine_capabilities = set(machines_by_id[operation.machine_id].capabilities)
    missing = sorted(required_capabilities - machine_capabilities)
    if missing:
        _add_issue(
            issues,
            "capability_mismatch",
            "reference_integrity",
            "error",
            "operation",
            operation.operation_id,
            "required_capabilities",
            f"Assigned machine {operation.machine_id!r} lacks capabilities: {missing}.",
        )


def _build_report(
    total_records: int,
    issues: Sequence[MappingValidationIssue],
) -> MappingValidationReport:
    blocking_errors = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    invalid_entities = {
        _issue_entity_key(issue)
        for issue in issues
        if issue.severity == "error"
    }
    invalid_records = min(total_records, len(invalid_entities))
    return MappingValidationReport(
        total_records=total_records,
        valid_records=max(0, total_records - invalid_records),
        invalid_records=invalid_records,
        missing_required_fields=sum(1 for issue in issues if issue.code == "missing_required_field"),
        enum_errors=sum(1 for issue in issues if issue.code == "enum_error"),
        time_parse_errors=sum(1 for issue in issues if issue.code == "time_parse_error"),
        reference_integrity_errors=sum(
            1 for issue in issues if issue.category == "reference_integrity"
        ),
        blocking_errors=blocking_errors,
        warnings=warning_count,
        issues=list(issues),
    )


def _add_issue(
    issues: list[MappingValidationIssue],
    code: str,
    category: str,
    severity: Severity,
    entity_type: str,
    entity_id: str | None,
    field: str | None,
    message: str,
) -> None:
    issues.append(
        MappingValidationIssue(
            code=code,
            category=category,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            field=field,
            message=message,
        )
    )


def _raw_entity_id(
    entity_type: str,
    row: dict[str, Any],
    profile: AdapterMappingProfile,
) -> str | None:
    mapping = getattr(profile.field_mapping, entity_type)
    id_field = {
        "work_order": "work_order_id",
        "operation": "operation_id",
        "machine": "machine_id",
        "incident": "incident_id",
    }[entity_type]
    value = _raw_get(row, mapping.get(id_field, ""))
    if _is_missing(value):
        value = row.get("id")
    return None if _is_missing(value) else str(value)


def _raw_get(row: dict[str, Any], path: str) -> Any:
    if not path:
        return None
    current: Any = row
    for segment in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _issue_entity_key(issue: MappingValidationIssue) -> str:
    return f"{issue.entity_type}:{issue.entity_id or issue.field or issue.code}"


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def _looks_like_time_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "datetime" in message or "isoformat" in message or "invalid iso" in message
