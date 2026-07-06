"""Tests for customer data mapping validation."""

from __future__ import annotations

from datetime import datetime, timezone

from app.adapters.mapping_schema import (
    CanonicalMachine,
    CanonicalOperation,
    CanonicalWorkOrder,
    build_schedule_snapshot,
)
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


def test_customer_payload_validation_accepts_pipe_delimited_alternatives_and_degraded_machine() -> None:
    report = validate_customer_payloads(
        raw_work_orders=[
            {
                "work_order_id": "WO-FJSP",
                "product_name": "Large FJSP job",
                "due_time": "2026-07-05T18:00:00+00:00",
                "status": "released",
            }
        ],
        raw_operations=[
            {
                "operation_id": "OP-FJSP",
                "work_order_id": "WO-FJSP",
                "required_capability": "CNC",
                "processing_time_min": 30,
                "machine_id": "M01",
                "eligible_machine_ids": "M01|M02",
                "start_time": "2026-07-05T08:00:00+00:00",
                "end_time": "2026-07-05T08:30:00+00:00",
            }
        ],
        raw_machines=[
            {
                "machine_id": "M01",
                "capabilities": "CNC",
                "status": "available",
            },
            {
                "machine_id": "M02",
                "capabilities": "CNC",
                "status": "degraded",
            },
        ],
    )

    assert report.is_valid is True
    assert report.blocking_errors == 0


def test_schedule_snapshot_preserves_eligible_resources_for_fjsp_solver() -> None:
    snapshot = build_schedule_snapshot(
        workshop_id="WS-FJSP",
        captured_at=datetime(2026, 7, 5, 8, tzinfo=timezone.utc),
        work_orders=[
            CanonicalWorkOrder(
                work_order_id="WO-FJSP",
                product_name="Large FJSP job",
                due_time=datetime(2026, 7, 5, 18, tzinfo=timezone.utc),
            )
        ],
        operations=[
            CanonicalOperation(
                operation_id="OP-FJSP",
                work_order_id="WO-FJSP",
                machine_id="M01",
                eligible_machine_ids=["M01", "M02"],
                processing_time_min=30,
            )
        ],
        machines=[
            CanonicalMachine(machine_id="M01", capabilities=["CNC"]),
            CanonicalMachine(machine_id="M02", capabilities=["CNC"]),
        ],
    )

    raw_op = snapshot.raw_data["work_orders"][0]["operations"][0]
    assert raw_op["eligible_resources"] == ["M01", "M02"]
    assert snapshot.raw_data["resources"][0]["resource_id"] == "M01"


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
