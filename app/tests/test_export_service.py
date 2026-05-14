"""Tests for ExportService.

Covers:
- export_pdf() generates PDF content with decision details
- export_excel() generates Excel content with ScheduleDetail
- Error handling for missing decision records

Validates: Requirements 27.7
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.decision import DecisionRecord
from app.models.schedule import (
    Operation,
    Resource,
    ScheduleDetail,
    WorkOrder,
)
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.services.export_service import ExportService

_NOW = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
_LATER = _NOW + timedelta(hours=2)


def _make_solver_chain() -> SolverChain:
    return SolverChain(
        strategy_type="local_repair",
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_name="cp_sat",
        key_parameters={"timeout": 60},
        search_budget_seconds=60.0,
        constraint_validation_result="feasible",
    )


def _make_plan() -> CandidatePlan:
    op = Operation(
        operation_id="OP-1",
        work_order_id="WO-1",
        resource_id="M-1",
        required_capabilities=["milling"],
        start_time=_NOW,
        end_time=_LATER,
    )
    wo = WorkOrder(
        work_order_id="WO-1",
        product_name="Widget",
        due_date=_NOW + timedelta(days=1),
        operations=[op],
    )
    res = Resource(resource_id="M-1", name="Mill-1", capabilities=["milling"])
    return CandidatePlan(
        plan_id=uuid4(),
        strategy_type="local_repair",
        schedule_detail=ScheduleDetail(work_orders=[wo], resources=[res]),
        gantt_version="1.0",
        solver_chain=_make_solver_chain(),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=5.0, iteration_count=100
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=True, violations=[], checked_constraints=[]
        ),
    )


def _make_record(plan_id=None) -> DecisionRecord:
    pid = plan_id or uuid4()
    return DecisionRecord(
        decision_record_id=uuid4(),
        incident_id=uuid4(),
        impact_report_summary="1 work order affected",
        strategy_type="local_repair",
        all_candidate_plan_ids=[pid],
        recommended_plan_id=pid,
        confirmed_plan_id=pid,
        derived_from_plan_id=pid,
        is_override=False,
        is_manual_adjusted=False,
        confirmed_by="planner-1",
        confirmed_at=_NOW,
        plan_selection_input_version="1.0",
        plan_selection_output_version="1.0",
        solver_chain=_make_solver_chain(),
        rule_selector_version="1.0.0",
        neighborhood_selector_version="1.0.0",
        repair_policy_advisor_version="1.0.0",
    )


# ── Test: PDF export ───────────────────────────────────────────────


def test_export_pdf_basic():
    """PDF export generates content with decision details."""
    service = ExportService()
    plan = _make_plan()
    record = _make_record(plan_id=plan.plan_id)
    service.register_decision(record, plan)

    result = service.export_pdf(record.decision_record_id)

    assert result.filename.endswith(".pdf")
    assert result.content_type == "application/pdf"
    assert len(result.content) > 0
    content_str = result.content.decode("utf-8")
    assert "Decision Record ID" in content_str
    assert str(record.decision_record_id) in content_str
    assert "Gantt Snapshot" in content_str


def test_export_pdf_without_plan():
    """PDF export works even without a confirmed plan."""
    service = ExportService()
    record = _make_record()
    service.register_decision(record)

    result = service.export_pdf(record.decision_record_id)

    assert len(result.content) > 0
    content_str = result.content.decode("utf-8")
    assert "Decision Record ID" in content_str
    # No gantt section without plan
    assert "Gantt Snapshot" not in content_str


def test_export_pdf_with_override():
    """PDF export includes override details when present."""
    service = ExportService()
    record = _make_record()
    record.is_override = True
    record.override_reason = "Too much disruption"
    service.register_decision(record)

    result = service.export_pdf(record.decision_record_id)

    content_str = result.content.decode("utf-8")
    assert "Override" in content_str
    assert "Too much disruption" in content_str


def test_export_pdf_not_found():
    """PDF export raises ValueError for unknown record."""
    service = ExportService()
    with pytest.raises(ValueError, match="not found"):
        service.export_pdf(uuid4())


# ── Test: Excel export ─────────────────────────────────────────────


def test_export_excel_basic():
    """Excel export generates content with ScheduleDetail."""
    service = ExportService()
    plan = _make_plan()
    record = _make_record(plan_id=plan.plan_id)
    service.register_decision(record, plan)

    result = service.export_excel(record.decision_record_id)

    assert result.filename.endswith(".xlsx")
    assert "spreadsheetml" in result.content_type
    assert len(result.content) > 0
    import json
    data = json.loads(result.content)
    assert "schedule_detail" in data
    assert "solver_chain" in data
    assert data["decision_record_id"] == str(record.decision_record_id)


def test_export_excel_without_plan():
    """Excel export works without a confirmed plan (no schedule_detail)."""
    service = ExportService()
    record = _make_record()
    service.register_decision(record)

    result = service.export_excel(record.decision_record_id)

    import json
    data = json.loads(result.content)
    assert "schedule_detail" not in data
    assert data["decision_record_id"] == str(record.decision_record_id)


def test_export_excel_not_found():
    """Excel export raises ValueError for unknown record."""
    service = ExportService()
    with pytest.raises(ValueError, match="not found"):
        service.export_excel(uuid4())
