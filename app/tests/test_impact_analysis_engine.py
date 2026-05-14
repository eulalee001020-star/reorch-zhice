"""Unit tests for Impact_Analysis_Engine service.

Covers: direct impact identification, downstream propagation,
delivery risk calculation, severity upgrade logic, and degraded mode.
Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.enums import (
    DeliveryRiskLevel,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
)
from app.models.incident import Incident
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.services.impact_analysis_engine import ImpactAnalysisEngine


# ── helpers ──────────────────────────────────────────────────────────

def _make_incident(
    resource_id: str = "machine-A",
    severity: IncidentSeverity = IncidentSeverity.P3_MEDIUM,
) -> Incident:
    return Incident(
        incident_id=uuid4(),
        incident_type=IncidentType.EQUIPMENT_FAILURE,
        occurred_at=datetime(2025, 1, 10, 8, 0, tzinfo=timezone.utc),
        resource_id=resource_id,
        report_source=ReportSource.MES,
        severity=severity,
    )


def _make_snapshot(
    captured_at: datetime,
    work_orders: list[WorkOrder] | None = None,
) -> ScheduleSnapshot:
    return ScheduleSnapshot(
        snapshot_id=uuid4(),
        captured_at=captured_at,
        workshop_id="workshop-1",
        work_orders=work_orders or [],
    )


def _ts(hours: float = 0, minutes: float = 0) -> datetime:
    """Shortcut: offset from a base time of 2025-01-10 08:00 UTC."""
    base = datetime(2025, 1, 10, 8, 0, tzinfo=timezone.utc)
    return base + timedelta(hours=hours, minutes=minutes)


# ── fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def engine() -> ImpactAnalysisEngine:
    return ImpactAnalysisEngine()


@pytest.fixture
def simple_snapshot() -> ScheduleSnapshot:
    """Snapshot with one work order, two operations on machine-A, one on machine-B."""
    ops = [
        Operation(
            operation_id="op-1",
            work_order_id="wo-1",
            resource_id="machine-A",
            start_time=_ts(0),
            end_time=_ts(1),
            successor_ids=["op-2"],
        ),
        Operation(
            operation_id="op-2",
            work_order_id="wo-1",
            resource_id="machine-B",
            start_time=_ts(1),
            end_time=_ts(2),
            predecessor_ids=["op-1"],
            successor_ids=["op-3"],
        ),
        Operation(
            operation_id="op-3",
            work_order_id="wo-1",
            resource_id="machine-A",
            start_time=_ts(2),
            end_time=_ts(3),
            predecessor_ids=["op-2"],
        ),
    ]
    wo = WorkOrder(
        work_order_id="wo-1",
        product_name="Product-X",
        due_date=_ts(5),  # plenty of buffer
        operations=ops,
    )
    return _make_snapshot(captured_at=_ts(0), work_orders=[wo])


# ── Tests: direct impact identification (Req 2.3) ───────────────────

@pytest.mark.asyncio
async def test_direct_impact_identification(engine, simple_snapshot):
    """Operations on the faulty resource are flagged as directly affected."""
    incident = _make_incident(resource_id="machine-A")
    report = await engine.analyze(incident, simple_snapshot)

    direct = [op for op in report.affected_operations if op.is_direct]
    assert len(direct) == 2
    direct_ids = {op.operation_id for op in direct}
    assert direct_ids == {"op-1", "op-3"}


# ── Tests: downstream propagation (Req 2.4) ─────────────────────────

@pytest.mark.asyncio
async def test_downstream_propagation(engine, simple_snapshot):
    """Successors of directly affected ops are flagged as indirect."""
    incident = _make_incident(resource_id="machine-A")
    report = await engine.analyze(incident, simple_snapshot)

    indirect = [op for op in report.affected_operations if not op.is_direct]
    # op-1 → op-2 (indirect), op-2 → op-3 (already direct, skip)
    assert len(indirect) == 1
    assert indirect[0].operation_id == "op-2"


# ── Tests: delivery risk calculation (Req 2.5) ──────────────────────

@pytest.mark.asyncio
async def test_delivery_risk_safe(engine):
    """Work order with large buffer → Safe."""
    ops = [
        Operation(
            operation_id="op-s1",
            work_order_id="wo-safe",
            resource_id="machine-A",
            start_time=_ts(0),
            end_time=_ts(1),
        ),
    ]
    wo = WorkOrder(
        work_order_id="wo-safe",
        product_name="Safe-Product",
        due_date=_ts(10),  # 10h from base, only 1h processing
        operations=ops,
    )
    snapshot = _make_snapshot(captured_at=_ts(0), work_orders=[wo])
    incident = _make_incident(resource_id="machine-A")
    report = await engine.analyze(incident, snapshot)

    assert len(report.affected_work_orders) == 1
    assert report.affected_work_orders[0].delivery_risk_level == DeliveryRiskLevel.SAFE


@pytest.mark.asyncio
async def test_delivery_risk_breach(engine):
    """Work order with no buffer → Breach."""
    ops = [
        Operation(
            operation_id="op-b1",
            work_order_id="wo-breach",
            resource_id="machine-A",
            start_time=_ts(0),
            end_time=_ts(2),
        ),
    ]
    wo = WorkOrder(
        work_order_id="wo-breach",
        product_name="Breach-Product",
        due_date=_ts(1),  # due before op finishes
        operations=ops,
    )
    snapshot = _make_snapshot(captured_at=_ts(0), work_orders=[wo])
    incident = _make_incident(resource_id="machine-A")
    report = await engine.analyze(incident, snapshot)

    assert len(report.affected_work_orders) == 1
    assert report.affected_work_orders[0].delivery_risk_level == DeliveryRiskLevel.BREACH


@pytest.mark.asyncio
async def test_delivery_risk_warning(engine):
    """Work order with tight buffer → Warning."""
    ops = [
        Operation(
            operation_id="op-w1",
            work_order_id="wo-warn",
            resource_id="machine-A",
            start_time=_ts(0),
            end_time=_ts(1),  # 60 min processing
        ),
    ]
    # buffer = due - (ref + remaining) = 90 - 60 = 30 min
    # estimated_delay = 60 min (full op duration)
    # 0 < buffer(30) <= delay(60) → Warning
    wo = WorkOrder(
        work_order_id="wo-warn",
        product_name="Warn-Product",
        due_date=_ts(0, minutes=90),
        operations=ops,
    )
    snapshot = _make_snapshot(captured_at=_ts(0), work_orders=[wo])
    incident = _make_incident(resource_id="machine-A")
    report = await engine.analyze(incident, snapshot)

    assert len(report.affected_work_orders) == 1
    assert report.affected_work_orders[0].delivery_risk_level == DeliveryRiskLevel.WARNING


# ── Tests: severity upgrade (Req 2.5 design) ────────────────────────

@pytest.mark.asyncio
async def test_severity_upgrade_on_breach(engine):
    """Breach risk triggers severity upgrade P3 → P2."""
    ops = [
        Operation(
            operation_id="op-u1",
            work_order_id="wo-u",
            resource_id="machine-A",
            start_time=_ts(0),
            end_time=_ts(2),
        ),
    ]
    wo = WorkOrder(
        work_order_id="wo-u",
        product_name="Urgent",
        due_date=_ts(0, minutes=30),  # way before op ends
        operations=ops,
    )
    snapshot = _make_snapshot(captured_at=_ts(0), work_orders=[wo])
    incident = _make_incident(resource_id="machine-A", severity=IncidentSeverity.P3_MEDIUM)
    report = await engine.analyze(incident, snapshot)

    assert report.severity_upgraded is True
    assert report.upgraded_severity == IncidentSeverity.P2_HIGH


@pytest.mark.asyncio
async def test_severity_no_downgrade(engine):
    """P1 stays P1 even with Breach — never downgrade."""
    ops = [
        Operation(
            operation_id="op-nd1",
            work_order_id="wo-nd",
            resource_id="machine-A",
            start_time=_ts(0),
            end_time=_ts(2),
        ),
    ]
    wo = WorkOrder(
        work_order_id="wo-nd",
        product_name="Critical",
        due_date=_ts(0, minutes=30),
        operations=ops,
    )
    snapshot = _make_snapshot(captured_at=_ts(0), work_orders=[wo])
    incident = _make_incident(resource_id="machine-A", severity=IncidentSeverity.P1_CRITICAL)
    report = await engine.analyze(incident, snapshot)

    # P1 stays P1 — severity_upgraded should be False
    assert report.severity_upgraded is False


@pytest.mark.asyncio
async def test_no_severity_upgrade_without_breach(engine):
    """No Breach risk → no severity upgrade."""
    # Create a snapshot with plenty of buffer so risk is Safe
    ops = [
        Operation(
            operation_id="op-safe1",
            work_order_id="wo-safe",
            resource_id="machine-A",
            start_time=_ts(0),
            end_time=_ts(1),
        ),
    ]
    wo = WorkOrder(
        work_order_id="wo-safe",
        product_name="Safe-Product",
        due_date=_ts(24),  # 24h buffer, only 1h processing → Safe
        operations=ops,
    )
    snapshot = _make_snapshot(captured_at=_ts(0), work_orders=[wo])
    incident = _make_incident(resource_id="machine-A", severity=IncidentSeverity.P4_LOW)
    report = await engine.analyze(incident, snapshot)

    assert report.severity_upgraded is False
    assert report.upgraded_severity is None


# ── Tests: degraded mode (Req 2.7) ──────────────────────────────────

@pytest.mark.asyncio
async def test_degraded_mode_none_snapshot(engine):
    """None snapshot → degraded mode."""
    incident = _make_incident()
    report = await engine.analyze(incident, None)

    assert report.is_degraded_mode is True
    assert "not available" in report.degraded_reason


@pytest.mark.asyncio
async def test_degraded_mode_empty_work_orders(engine):
    """Snapshot with no work orders → degraded mode."""
    incident = _make_incident()
    snapshot = _make_snapshot(captured_at=_ts(0), work_orders=[])
    report = await engine.analyze(incident, snapshot)

    assert report.is_degraded_mode is True
    assert "no work orders" in report.degraded_reason


# ── Tests: structured output (Req 2.6) ──────────────────────────────

@pytest.mark.asyncio
async def test_impact_report_structure(engine, simple_snapshot):
    """Report contains all required structured fields."""
    incident = _make_incident(resource_id="machine-A")
    report = await engine.analyze(incident, simple_snapshot)

    assert report.incident_id == incident.incident_id
    assert report.schedule_snapshot_id == simple_snapshot.snapshot_id
    assert report.analysis_reference_time == simple_snapshot.captured_at
    assert len(report.affected_work_orders) > 0
    assert len(report.affected_operations) > 0
    assert len(report.affected_resource_ids) > 0
    assert isinstance(report.delivery_risk_distribution, dict)
    assert report.estimated_total_delay_minutes >= 0
    assert report.is_degraded_mode is False


@pytest.mark.asyncio
async def test_analysis_reference_time_equals_captured_at(engine, simple_snapshot):
    """analysis_reference_time must equal snapshot.captured_at (Req 2.2)."""
    incident = _make_incident(resource_id="machine-A")
    report = await engine.analyze(incident, simple_snapshot)
    assert report.analysis_reference_time == simple_snapshot.captured_at


@pytest.mark.asyncio
async def test_no_affected_ops_when_resource_not_in_snapshot(engine, simple_snapshot):
    """Incident for a resource not in the snapshot → no affected ops."""
    incident = _make_incident(resource_id="machine-Z")
    report = await engine.analyze(incident, simple_snapshot)

    assert len(report.affected_operations) == 0
    assert len(report.affected_work_orders) == 0
    assert report.estimated_total_delay_minutes == 0.0
