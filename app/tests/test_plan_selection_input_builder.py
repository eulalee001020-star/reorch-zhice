"""Tests for PlanSelectionInputBuilder.

Validates: Requirements 30.1, 30.2, 30.3, 30.10
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.models.case import PreferenceProfile
from app.models.enums import (
    GoalMode,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
)
from app.models.evaluation import ComparisonMatrix, ComparisonMatrixRow, KPIVector
from app.models.incident import Incident
from app.models.recommendation import PlanSelectionInput
from app.models.schedule import ScheduleDetail
from app.models.solver import (
    CandidatePlan,
    ConstraintValidationReport,
    SolverChain,
    SolverMetadata,
)
from app.services.plan_selection_input_builder import PlanSelectionInputBuilder


# ── Fixtures ────────────────────────────────────────────────────────


def _make_incident(**overrides) -> Incident:
    defaults = dict(
        incident_id=uuid4(),
        incident_type=IncidentType.EQUIPMENT_FAILURE,
        occurred_at=datetime(2025, 1, 15, 8, 0, tzinfo=timezone.utc),
        resource_id="CNC-001",
        report_source=ReportSource.MES,
        severity=IncidentSeverity.P2_HIGH,
        status=IncidentStatus.ANALYZING,
    )
    defaults.update(overrides)
    return Incident(**defaults)


def _make_candidate(**overrides) -> CandidatePlan:
    defaults = dict(
        plan_id=uuid4(),
        strategy_type="local_repair",
        schedule_detail=ScheduleDetail(),
        gantt_version="v1",
        solver_chain=SolverChain(
            strategy_type="local_repair",
            rule_selection="due_date_priority",
            neighborhood_selection="critical_path",
            repair_policy="balanced",
            solver_name="cp_sat",
            key_parameters={},
            search_budget_seconds=30.0,
            constraint_validation_result="pass",
        ),
        feasibility_status="feasible",
        solver_metadata=SolverMetadata(
            solve_time_seconds=5.0,
            iteration_count=100,
        ),
        constraint_report=ConstraintValidationReport(
            is_feasible=True,
            checked_constraints=["equipment_capability"],
        ),
    )
    defaults.update(overrides)
    return CandidatePlan(**defaults)


def _make_preference(**overrides) -> PreferenceProfile:
    defaults = dict(
        planner_id="planner-A",
        strategy_preferences={"local_repair": 0.8, "global_reschedule": 0.2},
        updated_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return PreferenceProfile(**defaults)


# ── Tests ───────────────────────────────────────────────────────────


class TestPlanSelectionInputBuilder:
    """Unit tests for PlanSelectionInputBuilder.build()."""

    def test_build_returns_plan_selection_input(self):
        """build() returns a PlanSelectionInput instance."""
        incident = _make_incident()
        snap_id = uuid4()
        candidates = [_make_candidate()]

        result = PlanSelectionInputBuilder.build(
            incident=incident,
            snapshot_id=snap_id,
            candidates=candidates,
        )

        assert isinstance(result, PlanSelectionInput)

    def test_incident_fields_mapped(self):
        """Incident id, type, severity are correctly mapped."""
        incident = _make_incident(severity=IncidentSeverity.P1_CRITICAL)
        snap_id = uuid4()

        result = PlanSelectionInputBuilder.build(
            incident=incident,
            snapshot_id=snap_id,
            candidates=[_make_candidate()],
        )

        assert result.incident_id == incident.incident_id
        assert result.incident_type == IncidentType.EQUIPMENT_FAILURE.value
        assert result.severity == IncidentSeverity.P1_CRITICAL.value
        assert result.schedule_snapshot_id == snap_id

    def test_candidates_passed_through(self):
        """Candidate plans are included in the output."""
        c1 = _make_candidate()
        c2 = _make_candidate()

        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[c1, c2],
        )

        assert len(result.candidate_plans) == 2
        plan_ids = {p.plan_id for p in result.candidate_plans}
        assert c1.plan_id in plan_ids
        assert c2.plan_id in plan_ids

    def test_default_goal_mode_is_balanced(self):
        """Default goal_mode is 'balanced'."""
        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[_make_candidate()],
        )

        assert result.goal_mode == GoalMode.BALANCED.value

    def test_custom_goal_mode(self):
        """Custom GoalMode enum is correctly serialised."""
        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[_make_candidate()],
            goal_mode=GoalMode.DELIVERY_PRIORITY,
        )

        assert result.goal_mode == GoalMode.DELIVERY_PRIORITY.value

    def test_goal_mode_as_string(self):
        """Goal mode passed as raw string is preserved."""
        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[_make_candidate()],
            goal_mode="cost_priority",
        )

        assert result.goal_mode == "cost_priority"

    def test_preference_profile_serialised(self):
        """PreferenceProfile is serialised to dict."""
        pref = _make_preference()

        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[_make_candidate()],
            preference_profile=pref,
        )

        assert result.preference_profile["planner_id"] == "planner-A"
        assert "strategy_preferences" in result.preference_profile

    def test_no_preference_profile_gives_empty_dict(self):
        """Omitting preference_profile yields an empty dict."""
        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[_make_candidate()],
        )

        assert result.preference_profile == {}

    def test_case_matches_included(self):
        """Historical case matches are passed through."""
        matches = [{"case_id": str(uuid4()), "similarity": 0.85}]

        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[_make_candidate()],
            case_matches=matches,
        )

        assert len(result.historical_case_matches) == 1
        assert result.historical_case_matches[0]["similarity"] == 0.85

    def test_manual_weights_included(self):
        """Manual weights are passed through."""
        weights = {"delayed_order_count": 0.5, "spi": 0.5}

        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[_make_candidate()],
            manual_weights=weights,
        )

        assert result.manual_weights == weights

    def test_execution_constraints_included(self):
        """Execution constraints are passed through."""
        constraints = {"max_changeover": 5}

        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[_make_candidate()],
            execution_constraints=constraints,
        )

        assert result.execution_constraints == constraints

    def test_empty_candidates_allowed(self):
        """Building with zero candidates is valid."""
        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[],
        )

        assert result.candidate_plans == []

    def test_roundtrip_serialization(self):
        """PlanSelectionInput survives JSON round-trip (Req 30.9)."""
        result = PlanSelectionInputBuilder.build(
            incident=_make_incident(),
            snapshot_id=uuid4(),
            candidates=[_make_candidate()],
            goal_mode=GoalMode.STABILITY_PRIORITY,
            manual_weights={"spi": 1.0},
        )

        json_str = result.model_dump_json()
        restored = PlanSelectionInput.model_validate_json(json_str)

        assert restored.incident_id == result.incident_id
        assert restored.goal_mode == result.goal_mode
        assert restored.manual_weights == result.manual_weights
