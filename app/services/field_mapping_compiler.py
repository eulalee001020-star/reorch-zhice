"""Conservative field-mapping suggestions for customer sample data.

This compiler is intentionally advisory. It proposes likely mappings from
headers but does not authorize replay or solving by itself.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.adapters.mapping_schema import AdapterMappingProfile, FieldMapping
from app.models.reality_harness import (
    FieldMappingCompileRequest,
    FieldMappingCompileResponse,
    FieldMappingSuggestion,
)

_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "work_order": {
        "work_order_id": ("work_order_id", "order_id", "order_no", "orderno", "wo_id", "workorder"),
        "product_id": ("product_id", "sku", "item_code", "material_id"),
        "product_name": ("product_name", "sku_name", "skuname", "item_name", "name"),
        "quantity": ("quantity", "qty", "order_qty"),
        "priority": ("priority", "priority_code", "prioritycode", "prio"),
        "due_time": ("due_time", "due_date", "due", "due_at", "dueat"),
        "status": ("status", "state"),
    },
    "operation": {
        "operation_id": ("operation_id", "op_id", "op_no", "opno", "routing_step_id"),
        "work_order_id": ("work_order_id", "order_id", "order_no", "orderno", "wo_id"),
        "sequence": ("sequence", "seq", "step_no", "step"),
        "required_capability": ("required_capability", "capability", "process_type"),
        "required_capabilities": ("required_capabilities", "capabilities", "skills"),
        "processing_time_min": ("processing_time_min", "duration_minutes", "minutes", "process_minutes"),
        "machine_id": ("machine_id", "resource_id", "equipment_id", "workcenter_id"),
        "eligible_machine_ids": ("eligible_machine_ids", "eligible_resource_ids", "machines", "resources"),
        "start_time": ("start_time", "start", "planned_start"),
        "end_time": ("end_time", "end", "planned_end"),
        "predecessors": ("predecessors", "predecessor_ids", "prev_ops"),
        "successors": ("successors", "successor_ids", "next_ops"),
    },
    "machine": {
        "machine_id": ("machine_id", "resource_id", "equipment_id", "id"),
        "name": ("name", "machine_name", "resource_name"),
        "capabilities": ("capabilities", "skills", "process_types"),
        "status": ("status", "state"),
        "is_bottleneck": ("is_bottleneck", "bottleneck"),
        "has_redundancy": ("has_redundancy", "redundancy"),
        "criticality": ("criticality", "critical_level", "importance"),
    },
    "incident": {
        "incident_id": ("incident_id", "event_id", "id"),
        "incident_type": ("incident_type", "type", "event_type"),
        "machine_id": ("machine_id", "resource_id", "equipment_id"),
        "start_time": ("start_time", "occurred_at", "event_time"),
        "severity": ("severity", "priority", "level"),
        "description": ("description", "desc", "remark"),
    },
}

_REQUIRED = {
    "work_order.work_order_id",
    "work_order.due_time",
    "operation.operation_id",
    "operation.work_order_id",
    "machine.machine_id",
    "incident.incident_id",
    "incident.incident_type",
    "incident.machine_id",
    "incident.start_time",
}


class FieldMappingCompiler:
    """Suggest adapter mapping fields from customer sample rows."""

    def compile(self, request: FieldMappingCompileRequest) -> FieldMappingCompileResponse:
        work_order_mapping, work_order_suggestions = _compile_entity(
            "work_order", _headers(request.raw_work_orders)
        )
        operation_mapping, operation_suggestions = _compile_entity(
            "operation", _headers(request.raw_operations)
        )
        machine_mapping, machine_suggestions = _compile_entity(
            "machine", _headers(request.raw_machines)
        )
        incident_mapping, incident_suggestions = _compile_entity(
            "incident", _headers(request.raw_incidents)
        )

        profile = AdapterMappingProfile(
            source_system=request.source_system,
            field_mapping=FieldMapping(
                work_order=work_order_mapping,
                operation=operation_mapping,
                machine=machine_mapping,
                incident=incident_mapping,
            ),
        )
        suggestions = [
            *work_order_suggestions,
            *operation_suggestions,
            *machine_suggestions,
            *incident_suggestions,
        ]
        mapped_required = {
            f"{item.entity_type}.{item.canonical_field}"
            for item in suggestions
            if item.source_field and item.confidence >= 0.8
        }
        return FieldMappingCompileResponse(
            source_system=request.source_system,
            profile=profile,
            suggestions=suggestions,
            unmapped_required_fields=sorted(_REQUIRED - mapped_required),
        )


def _compile_entity(
    entity_type: str,
    headers: set[str],
) -> tuple[dict[str, str], list[FieldMappingSuggestion]]:
    suggestions: list[FieldMappingSuggestion] = []
    mapping: dict[str, str] = {}
    normalized_headers = {_normalize(header): header for header in headers}
    for canonical_field, aliases in _ALIASES[entity_type].items():
        source_field, confidence, reason = _best_match(
            canonical_field, aliases, normalized_headers
        )
        if source_field:
            mapping[canonical_field] = source_field
        suggestions.append(
            FieldMappingSuggestion(
                entity_type=entity_type,
                canonical_field=canonical_field,
                source_field=source_field,
                confidence=confidence,
                reason=reason,
            )
        )
    return mapping, suggestions


def _best_match(
    canonical_field: str,
    aliases: Iterable[str],
    normalized_headers: dict[str, str],
) -> tuple[str | None, float, str]:
    canonical_norm = _normalize(canonical_field)
    if canonical_norm in normalized_headers:
        return normalized_headers[canonical_norm], 0.98, "Exact canonical field match."
    for alias in aliases:
        alias_norm = _normalize(alias)
        if alias_norm in normalized_headers:
            return normalized_headers[alias_norm], 0.9, f"Known alias match: {alias}."
    for header_norm, original in normalized_headers.items():
        if canonical_norm in header_norm or header_norm in canonical_norm:
            return original, 0.65, "Weak substring match; customer confirmation required."
    return None, 0.0, "No safe mapping suggestion."


def _headers(rows: list[dict]) -> set[str]:
    headers: set[str] = set()
    for row in rows:
        headers.update(str(key) for key in row)
    return headers


def _normalize(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())

