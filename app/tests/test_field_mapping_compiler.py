"""Tests for conservative customer field-mapping suggestions."""

from __future__ import annotations

from app.models.reality_harness import FieldMappingCompileRequest
from app.services.field_mapping_compiler import FieldMappingCompiler


def test_field_mapping_compiler_suggests_known_aliases() -> None:
    response = FieldMappingCompiler().compile(
        FieldMappingCompileRequest(
            source_system="customer_x",
            raw_work_orders=[
                {
                    "orderNo": "WO-1",
                    "skuName": "Part A",
                    "qty": 1,
                    "dueAt": "2026-05-14T20:00:00+08:00",
                }
            ],
            raw_operations=[
                {
                    "opNo": "OP-1",
                    "orderNo": "WO-1",
                    "minutes": 30,
                    "machines": ["M-1"],
                    "skills": ["CNC"],
                }
            ],
            raw_machines=[
                {
                    "id": "M-1",
                    "skills": ["CNC"],
                    "state": "available",
                }
            ],
            raw_incidents=[
                {
                    "event_id": "INC-1",
                    "event_type": "machine_down",
                    "equipment_id": "M-1",
                    "occurred_at": "2026-05-14T13:00:00+08:00",
                }
            ],
        )
    )

    assert response.profile.source_system == "customer_x"
    assert response.profile.field_mapping.work_order["work_order_id"] == "orderNo"
    assert response.profile.field_mapping.work_order["due_time"] == "dueAt"
    assert response.profile.field_mapping.operation["operation_id"] == "opNo"
    assert response.profile.field_mapping.operation["processing_time_min"] == "minutes"
    assert response.profile.field_mapping.machine["machine_id"] == "id"
    assert response.profile.field_mapping.incident["start_time"] == "occurred_at"
    assert response.unmapped_required_fields == []
    assert all(item.requires_human_confirmation for item in response.suggestions)


def test_field_mapping_compiler_does_not_hide_unmapped_required_fields() -> None:
    response = FieldMappingCompiler().compile(
        FieldMappingCompileRequest(
            raw_work_orders=[{"some_field": "WO-1"}],
            raw_operations=[],
            raw_machines=[],
            raw_incidents=[],
        )
    )

    assert "work_order.work_order_id" in response.unmapped_required_fields
    assert "operation.operation_id" in response.unmapped_required_fields
    assert "machine.machine_id" in response.unmapped_required_fields
