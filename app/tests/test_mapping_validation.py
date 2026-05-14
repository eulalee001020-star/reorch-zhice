"""Tests for customer data mapping validation."""

from __future__ import annotations

from app.adapters.mapping_validator import validate_customer_payloads


def test_customer_payload_validation_accepts_clean_dataset() -> None:
    report = validate_customer_payloads(
        raw_work_orders=[
            {
                "work_order_id": "WO-001",
                "product_name": "PCR Kit",
                "quantity": 100,
                "priority": "HIGH",
                "due_time": "2026-05-15T18:00:00+00:00",
                "status": "released",
            }
        ],
        raw_operations=[
            {
                "operation_id": "OP-001",
                "work_order_id": "WO-001",
                "sequence": 10,
                "required_capability": "PCR",
                "processing_time_min": 45,
                "machine_id": "M-PCR-01",
                "start_time": "2026-05-14T10:00:00+00:00",
                "end_time": "2026-05-14T10:45:00+00:00",
            }
        ],
        raw_machines=[
            {
                "machine_id": "M-PCR-01",
                "name": "PCR Line 01",
                "capabilities": ["PCR"],
                "status": "available",
            }
        ],
        raw_incidents=[
            {
                "incident_id": "INC-001",
                "type": "machine_down",
                "machine_id": "M-PCR-01",
                "start_time": "2026-05-14T11:00:00+00:00",
                "severity": "P2-High",
            }
        ],
    )

    assert report.is_valid is True
    assert report.total_records == 4
    assert report.blocking_errors == 0


def test_customer_payload_validation_reports_mapping_and_reference_errors() -> None:
    report = validate_customer_payloads(
        raw_work_orders=[
            {
                "work_order_id": "WO-001",
                "product_name": "PCR Kit",
                "due_time": "not-a-date",
                "status": "released",
            },
            {
                "work_order_id": "WO-002",
                "product_name": "PCR Kit",
                "status": "released",
            },
        ],
        raw_operations=[
            {
                "operation_id": "OP-001",
                "work_order_id": "WO-MISSING",
                "processing_time_min": 30,
                "machine_id": "M-MISSING",
                "predecessors": "OP-MISSING",
            }
        ],
        raw_machines=[
            {
                "machine_id": "M-PCR-01",
                "capabilities": ["PCR"],
                "status": "available",
            }
        ],
        raw_incidents=[
            {
                "incident_id": "INC-001",
                "type": "unknown_type",
                "machine_id": "M-MISSING",
                "start_time": "2026-05-14T11:00:00+00:00",
                "severity": "P9",
            }
        ],
    )

    codes = {issue.code for issue in report.issues}
    assert report.is_valid is False
    assert report.time_parse_errors == 1
    assert report.missing_required_fields == 1
    assert report.reference_integrity_errors >= 3
    assert report.enum_errors >= 2
    assert "unknown_machine_reference" in codes
    assert "unknown_work_order_reference" in codes


def test_customer_payload_validation_reports_duplicate_and_capability_mismatch() -> None:
    report = validate_customer_payloads(
        raw_work_orders=[
            {
                "work_order_id": "WO-001",
                "product_name": "PCR Kit",
                "due_time": "2026-05-15T18:00:00+00:00",
                "status": "released",
            },
            {
                "work_order_id": "WO-001",
                "product_name": "PCR Kit Duplicate",
                "due_time": "2026-05-15T18:00:00+00:00",
                "status": "released",
            },
        ],
        raw_operations=[
            {
                "operation_id": "OP-001",
                "work_order_id": "WO-001",
                "required_capability": "PCR",
                "processing_time_min": 30,
                "machine_id": "M-CNC-01",
            }
        ],
        raw_machines=[
            {
                "machine_id": "M-CNC-01",
                "capabilities": ["CNC"],
                "status": "available",
            }
        ],
    )

    codes = {issue.code for issue in report.issues}
    assert report.is_valid is False
    assert "duplicate_id" in codes
    assert "capability_mismatch" in codes
