"""Canonical adapter models and field mapping helpers.

External ERP/MES/APS payloads may use customer-specific field names. This
module defines the stable ReOrch-side contract that adapters must output
before data enters planning, incident intake, or writeback workflows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.enums import IncidentSeverity
from app.models.schedule import Operation, Resource, ScheduleSnapshot, WorkOrder


class CanonicalWorkOrder(ReOrchModel):
    """Customer-independent work order shape used by adapters."""

    work_order_id: str
    product_id: str | None = None
    product_name: str
    quantity: float = 1.0
    priority: int = 0
    due_time: datetime
    status: str = "released"
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class CanonicalOperation(ReOrchModel):
    """Customer-independent operation / routing step."""

    operation_id: str
    work_order_id: str
    sequence: int = 0
    required_capability: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    processing_time_min: int = Field(default=1, gt=0)
    machine_id: str | None = None
    eligible_machine_ids: list[str] = Field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    predecessors: list[str] = Field(default_factory=list)
    successors: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class CanonicalMachine(ReOrchModel):
    """Customer-independent machine/resource shape."""

    machine_id: str
    name: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    status: str = "available"
    calendar: list[dict[str, Any]] = Field(default_factory=list)
    is_bottleneck: bool = False
    has_redundancy: bool = False
    criticality: str = "general"
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class CanonicalIncident(ReOrchModel):
    """Customer-independent incident shape before ReOrch intake conversion."""

    incident_id: str
    incident_type: str
    machine_id: str
    start_time: datetime
    severity: str = IncidentSeverity.P3_MEDIUM.value
    description: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class RescheduleWritebackPlan(ReOrchModel):
    """Adapter-level writeback command after human confirmation."""

    plan_id: str
    decision_record_id: str | None = None
    idempotency_key: str
    instructions: list[dict[str, Any]] = Field(default_factory=list)
    confirmed_by: str | None = None


class FieldMapping(ReOrchModel):
    """Field names used by one customer payload family."""

    work_order: dict[str, str] = Field(
        default_factory=lambda: {
            "work_order_id": "work_order_id",
            "product_id": "product_id",
            "product_name": "product_name",
            "quantity": "quantity",
            "priority": "priority",
            "due_time": "due_time",
            "status": "status",
        }
    )
    operation: dict[str, str] = Field(
        default_factory=lambda: {
            "operation_id": "operation_id",
            "work_order_id": "work_order_id",
            "sequence": "sequence",
            "required_capability": "required_capability",
            "required_capabilities": "required_capabilities",
            "processing_time_min": "processing_time_min",
            "machine_id": "machine_id",
            "eligible_machine_ids": "eligible_machine_ids",
            "start_time": "start_time",
            "end_time": "end_time",
            "predecessors": "predecessors",
            "successors": "successors",
        }
    )
    machine: dict[str, str] = Field(
        default_factory=lambda: {
            "machine_id": "machine_id",
            "name": "name",
            "capabilities": "capabilities",
            "status": "status",
            "calendar": "calendar",
            "is_bottleneck": "is_bottleneck",
            "has_redundancy": "has_redundancy",
            "criticality": "criticality",
        }
    )
    incident: dict[str, str] = Field(
        default_factory=lambda: {
            "incident_id": "incident_id",
            "incident_type": "type",
            "machine_id": "machine_id",
            "start_time": "start_time",
            "severity": "severity",
            "description": "description",
        }
    )


class AdapterMappingProfile(ReOrchModel):
    """Paths and fields needed to normalize one external system."""

    source_system: str = "generic"
    work_orders_path: str = "work_orders"
    operations_path: str = "operations"
    machines_path: str = "machines"
    current_schedule_path: str = "current_schedule"
    incidents_path: str = "incidents"
    field_mapping: FieldMapping = Field(default_factory=FieldMapping)


class AdapterMappingIssue(ReOrchModel):
    """Non-fatal mapping issue captured for audit and customer debugging."""

    entity_type: str
    entity_id: str | None = None
    field: str | None = None
    message: str
    severity: str = "warning"


def map_work_order(raw: dict[str, Any], profile: AdapterMappingProfile) -> CanonicalWorkOrder:
    fields = profile.field_mapping.work_order
    work_order_id = str(_get(raw, fields["work_order_id"], raw.get("id", "")))
    product_name = str(_get(raw, fields["product_name"], _get(raw, fields.get("product_id", ""), work_order_id)))
    return CanonicalWorkOrder(
        work_order_id=work_order_id,
        product_id=_optional_str(_get(raw, fields.get("product_id", ""), None)),
        product_name=product_name,
        quantity=float(_get(raw, fields.get("quantity", ""), 1.0) or 1.0),
        priority=_normalize_priority(_get(raw, fields.get("priority", ""), 0)),
        due_time=_parse_datetime(_get(raw, fields["due_time"], raw.get("due_date"))),
        status=str(_get(raw, fields.get("status", ""), "released")),
        raw_payload=raw,
    )


def map_operation(
    raw: dict[str, Any],
    profile: AdapterMappingProfile,
    *,
    parent_work_order_id: str | None = None,
) -> CanonicalOperation:
    fields = profile.field_mapping.operation
    required_capability = _optional_str(_get(raw, fields.get("required_capability", ""), None))
    required_capabilities = _as_str_list(
        _get(raw, fields.get("required_capabilities", ""), [])
    )
    if required_capability and required_capability not in required_capabilities:
        required_capabilities.append(required_capability)

    machine_id = _optional_str(_get(raw, fields.get("machine_id", ""), None))
    eligible_machine_ids = _as_str_list(
        _get(raw, fields.get("eligible_machine_ids", ""), [])
    )
    if machine_id and machine_id not in eligible_machine_ids:
        eligible_machine_ids.append(machine_id)

    start_time = _parse_optional_datetime(_get(raw, fields.get("start_time", ""), None))
    end_time = _parse_optional_datetime(_get(raw, fields.get("end_time", ""), None))
    duration_raw = _get(raw, fields.get("processing_time_min", ""), None)
    if duration_raw is None and start_time and end_time:
        duration = max(1, int((end_time - start_time).total_seconds() // 60))
    else:
        duration = int(float(duration_raw or 1))

    return CanonicalOperation(
        operation_id=str(_get(raw, fields["operation_id"], raw.get("id", ""))),
        work_order_id=str(_get(raw, fields.get("work_order_id", ""), parent_work_order_id or "")),
        sequence=int(float(_get(raw, fields.get("sequence", ""), 0) or 0)),
        required_capability=required_capability,
        required_capabilities=required_capabilities,
        processing_time_min=max(1, duration),
        machine_id=machine_id,
        eligible_machine_ids=eligible_machine_ids,
        start_time=start_time,
        end_time=end_time,
        predecessors=_as_str_list(_get(raw, fields.get("predecessors", ""), [])),
        successors=_as_str_list(_get(raw, fields.get("successors", ""), [])),
        raw_payload=raw,
    )


def map_machine(raw: dict[str, Any], profile: AdapterMappingProfile) -> CanonicalMachine:
    fields = profile.field_mapping.machine
    machine_id = str(_get(raw, fields["machine_id"], raw.get("resource_id", raw.get("id", ""))))
    return CanonicalMachine(
        machine_id=machine_id,
        name=_optional_str(_get(raw, fields.get("name", ""), machine_id)),
        capabilities=_as_str_list(_get(raw, fields.get("capabilities", ""), [])),
        status=str(_get(raw, fields.get("status", ""), "available")),
        calendar=_as_dict_list(_get(raw, fields.get("calendar", ""), [])),
        is_bottleneck=bool(_get(raw, fields.get("is_bottleneck", ""), False)),
        has_redundancy=bool(_get(raw, fields.get("has_redundancy", ""), False)),
        criticality=str(_get(raw, fields.get("criticality", ""), "general")),
        raw_payload=raw,
    )


def map_incident(raw: dict[str, Any], profile: AdapterMappingProfile) -> CanonicalIncident:
    fields = profile.field_mapping.incident
    incident_id = str(_get(raw, fields["incident_id"], raw.get("id", "")))
    return CanonicalIncident(
        incident_id=incident_id,
        incident_type=str(_get(raw, fields["incident_type"], raw.get("incident_type", "machine_down"))),
        machine_id=str(_get(raw, fields["machine_id"], raw.get("resource_id", ""))),
        start_time=_parse_datetime(_get(raw, fields["start_time"], raw.get("occurred_at"))),
        severity=str(_get(raw, fields.get("severity", ""), IncidentSeverity.P3_MEDIUM.value)),
        description=_optional_str(_get(raw, fields.get("description", ""), None)),
        raw_payload=raw,
    )


def build_schedule_snapshot(
    *,
    workshop_id: str,
    work_orders: list[CanonicalWorkOrder],
    operations: list[CanonicalOperation],
    machines: list[CanonicalMachine],
    captured_at: datetime | None = None,
    source_system: str | None = None,
    raw_data: dict[str, Any] | None = None,
) -> ScheduleSnapshot:
    """Convert canonical adapter objects into the ReOrch schedule model."""
    reference_time = captured_at or datetime.now(tz=timezone.utc)
    ops_by_order: dict[str, list[CanonicalOperation]] = {}
    for operation in operations:
        ops_by_order.setdefault(operation.work_order_id, []).append(operation)

    schedule_work_orders: list[WorkOrder] = []
    for work_order in work_orders:
        cursor = reference_time
        schedule_ops: list[Operation] = []
        ordered_ops = sorted(
            ops_by_order.get(work_order.work_order_id, []),
            key=lambda item: (item.sequence, item.operation_id),
        )
        for op in ordered_ops:
            start = op.start_time or cursor
            end = op.end_time or (start + timedelta(minutes=op.processing_time_min))
            cursor = end
            schedule_ops.append(
                Operation(
                    operation_id=op.operation_id,
                    work_order_id=op.work_order_id,
                    resource_id=op.machine_id or (op.eligible_machine_ids[0] if op.eligible_machine_ids else ""),
                    required_capabilities=op.required_capabilities,
                    start_time=start,
                    end_time=end,
                    predecessor_ids=op.predecessors,
                    successor_ids=op.successors,
                )
            )
        schedule_work_orders.append(
            WorkOrder(
                work_order_id=work_order.work_order_id,
                product_name=work_order.product_name,
                due_date=work_order.due_time,
                operations=schedule_ops,
                priority=work_order.priority,
            )
        )

    return ScheduleSnapshot(
        captured_at=reference_time,
        workshop_id=workshop_id,
        source_system=source_system,
        work_orders=schedule_work_orders,
        raw_data={
            "machines": [machine.model_dump(mode="json") for machine in machines],
            **(raw_data or {}),
        },
    )


def extract_payload_list(payload: Any, path: str) -> list[dict[str, Any]]:
    """Extract a list from a nested payload path."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    value = _get_path(payload, path, [])
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _get(payload: dict[str, Any], key: str, default: Any = None) -> Any:
    if not key:
        return default
    if "." in key:
        return _get_path(payload, key, default)
    return payload.get(key, default)


def _get_path(payload: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = payload
    for segment in path.split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(segment)
        if current is None:
            return default
    return current


def _parse_datetime(value: Any) -> datetime:
    parsed = _parse_optional_datetime(value)
    if parsed is None:
        raise ValueError(f"Cannot parse datetime from {value!r}")
    return parsed


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _as_str_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and item != ""]
    return [str(value)]


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _normalize_priority(value: Any) -> int:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"urgent", "critical", "high", "p1"}:
            return 3
        if normalized in {"medium", "normal", "p2"}:
            return 1
        if normalized in {"low", "p3"}:
            return 0
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
