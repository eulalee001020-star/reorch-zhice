"""Tests for Incident and Schedule Pydantic models.

Covers JSON serialization/deserialization round-trip consistency,
field defaults, validation errors, and nested structure integrity.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.models.incident import Incident, IncidentCreateRequest
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
)
from app.models.schedule import (
    GanttDiffPayload,
    Operation,
    Resource,
    ScheduleDetail,
    ScheduleSnapshot,
    WorkOrder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
_DUE = datetime(2025, 1, 20, 18, 0, 0, tzinfo=timezone.utc)


def _make_incident(**overrides) -> Incident:
    defaults = dict(
        incident_type=IncidentType.EQUIPMENT_FAILURE,
        occurred_at=_NOW,
        resource_id="CNC-001",
        report_source=ReportSource.MES,
        severity=IncidentSeverity.P2_HIGH,
    )
    defaults.update(overrides)
    return Incident(**defaults)


def _make_operation(**overrides) -> Operation:
    defaults = dict(
        operation_id="OP-001",
        work_order_id="WO-001",
        resource_id="CNC-001",
        start_time=_NOW,
        end_time=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Operation(**defaults)


def _make_work_order(**overrides) -> WorkOrder:
    defaults = dict(
        work_order_id="WO-001",
        product_name="Widget-A",
        due_date=_DUE,
        operations=[_make_operation()],
        priority=1,
    )
    defaults.update(overrides)
    return WorkOrder(**defaults)


# ---------------------------------------------------------------------------
# IncidentCreateRequest
# ---------------------------------------------------------------------------


class TestIncidentCreateRequest:
    def test_minimal_creation(self):
        req = IncidentCreateRequest(
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            occurred_at=_NOW,
            resource_id="CNC-001",
            report_source=ReportSource.MES,
        )
        assert req.incident_type == IncidentType.EQUIPMENT_FAILURE.value
        assert req.description is None
        assert req.raw_payload is None

    def test_full_creation(self):
        req = IncidentCreateRequest(
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            occurred_at=_NOW,
            resource_id="CNC-001",
            report_source=ReportSource.IOT,
            description="Spindle overheating",
            raw_payload={"temp": 95.2},
        )
        assert req.description == "Spindle overheating"
        assert req.raw_payload == {"temp": 95.2}

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            IncidentCreateRequest(
                incident_type=IncidentType.EQUIPMENT_FAILURE,
                occurred_at=_NOW,
                # resource_id missing
                report_source=ReportSource.MES,
            )

    def test_json_round_trip(self):
        req = IncidentCreateRequest(
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            occurred_at=_NOW,
            resource_id="CNC-001",
            report_source=ReportSource.MANUAL,
            description="Manual report",
        )
        json_str = req.model_dump_json()
        restored = IncidentCreateRequest.model_validate_json(json_str)
        assert restored.model_dump() == req.model_dump()


# ---------------------------------------------------------------------------
# Incident
# ---------------------------------------------------------------------------


class TestIncident:
    def test_defaults(self):
        inc = _make_incident()
        assert isinstance(inc.incident_id, UUID)
        assert inc.status == IncidentStatus.PENDING_ANALYSIS.value
        assert inc.deduplicated_from == []
        assert isinstance(inc.created_at, datetime)

    def test_deduplicated_from(self):
        ids = [uuid4(), uuid4()]
        inc = _make_incident(deduplicated_from=ids)
        assert inc.deduplicated_from == ids

    def test_json_round_trip(self):
        inc = _make_incident(
            description="test",
            raw_payload={"key": "value"},
            deduplicated_from=[uuid4(), uuid4()],
        )
        json_str = inc.model_dump_json()
        restored = Incident.model_validate_json(json_str)
        assert restored.incident_id == inc.incident_id
        assert restored.deduplicated_from == inc.deduplicated_from
        assert restored.model_dump() == inc.model_dump()

    def test_invalid_json_returns_descriptive_error(self):
        with pytest.raises(ValidationError) as exc_info:
            Incident.model_validate_json('{"incident_type": "unknown_type"}')
        errors = exc_info.value.errors()
        assert len(errors) > 0

    def test_enum_values_serialized(self):
        inc = _make_incident()
        dumped = inc.model_dump()
        assert dumped["incident_type"] == "equipment_failure"
        assert dumped["report_source"] == "MES"
        assert dumped["severity"] == "P2-High"
        assert dumped["status"] == "pending_analysis"


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


class TestResource:
    def test_defaults(self):
        r = Resource(resource_id="CNC-001", name="CNC Machine 1")
        assert r.capabilities == []
        assert r.is_bottleneck is False
        assert r.has_redundancy is False
        assert r.criticality == "general"

    def test_json_round_trip(self):
        r = Resource(
            resource_id="CNC-001",
            name="CNC Machine 1",
            capabilities=["milling", "drilling"],
            is_bottleneck=True,
            criticality="critical",
        )
        restored = Resource.model_validate_json(r.model_dump_json())
        assert restored.model_dump() == r.model_dump()


# ---------------------------------------------------------------------------
# Operation
# ---------------------------------------------------------------------------


class TestOperation:
    def test_defaults(self):
        op = _make_operation()
        assert op.required_capabilities == []
        assert op.predecessor_ids == []
        assert op.successor_ids == []
        assert op.is_affected is False
        assert op.is_adjusted is False

    def test_json_round_trip(self):
        op = _make_operation(
            required_capabilities=["milling"],
            predecessor_ids=["OP-000"],
            successor_ids=["OP-002"],
            is_affected=True,
            is_adjusted=True,
        )
        restored = Operation.model_validate_json(op.model_dump_json())
        assert restored.model_dump() == op.model_dump()


# ---------------------------------------------------------------------------
# WorkOrder
# ---------------------------------------------------------------------------


class TestWorkOrder:
    def test_nested_operations(self):
        wo = _make_work_order()
        assert len(wo.operations) == 1
        assert wo.operations[0].operation_id == "OP-001"

    def test_json_round_trip(self):
        wo = _make_work_order()
        restored = WorkOrder.model_validate_json(wo.model_dump_json())
        assert restored.model_dump() == wo.model_dump()


# ---------------------------------------------------------------------------
# ScheduleDetail
# ---------------------------------------------------------------------------


class TestScheduleDetail:
    def test_empty_defaults(self):
        sd = ScheduleDetail()
        assert sd.work_orders == []
        assert sd.resources == []

    def test_nested_round_trip(self):
        sd = ScheduleDetail(
            work_orders=[_make_work_order()],
            resources=[
                Resource(resource_id="CNC-001", name="CNC Machine 1"),
            ],
        )
        restored = ScheduleDetail.model_validate_json(sd.model_dump_json())
        assert restored.model_dump() == sd.model_dump()


# ---------------------------------------------------------------------------
# ScheduleSnapshot
# ---------------------------------------------------------------------------


class TestScheduleSnapshot:
    def test_defaults(self):
        ss = ScheduleSnapshot(captured_at=_NOW, workshop_id="WS-01")
        assert isinstance(ss.snapshot_id, UUID)
        assert ss.work_orders == []
        assert ss.raw_data is None

    def test_json_round_trip(self):
        ss = ScheduleSnapshot(
            captured_at=_NOW,
            workshop_id="WS-01",
            work_orders=[_make_work_order()],
            raw_data={"source": "APS"},
        )
        restored = ScheduleSnapshot.model_validate_json(ss.model_dump_json())
        assert restored.snapshot_id == ss.snapshot_id
        assert restored.model_dump() == ss.model_dump()


# ---------------------------------------------------------------------------
# GanttDiffPayload
# ---------------------------------------------------------------------------


class TestGanttDiffPayload:
    def test_empty_defaults(self):
        g = GanttDiffPayload(
            baseline_snapshot_id="snap-1",
            candidate_plan_id="plan-1",
        )
        assert g.adjusted_operations == []
        assert g.time_shifts == []
        assert g.resource_switches == []
        assert g.critical_path_changes == []

    def test_json_round_trip(self):
        g = GanttDiffPayload(
            baseline_snapshot_id="snap-1",
            candidate_plan_id="plan-1",
            adjusted_operations=[{"op_id": "OP-001", "change": "rescheduled"}],
            time_shifts=[{"op_id": "OP-001", "delta_min": 30}],
            resource_switches=[{"op_id": "OP-002", "from": "CNC-001", "to": "CNC-002"}],
            critical_path_changes=[{"added": "OP-003"}],
        )
        restored = GanttDiffPayload.model_validate_json(g.model_dump_json())
        assert restored.model_dump() == g.model_dump()
