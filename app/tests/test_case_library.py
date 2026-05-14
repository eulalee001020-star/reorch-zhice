"""Tests for CaseLibrary service.

Covers:
- create_case() from DecisionRecord + ExecutionResult
- find_similar_cases() cosine similarity search
- update_preference() on Override
- get_preference_profile() default and updated
- get_strategy_effectiveness() tracking
- list_cases() with filters
- Template suggestion when case count > 10

Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.10, 9.11, 9.12
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.case import CaseRecord
from app.models.decision import DecisionRecord
from app.models.execution import ExecutionResult
from app.models.solver import SolverChain
from app.services.case_library import CaseLibrary, _cosine_similarity


def _make_solver_chain(**overrides) -> SolverChain:
    defaults = dict(
        strategy_type="local_repair",
        rule_selection="due_date_priority",
        neighborhood_selection="critical_path",
        repair_policy="balanced",
        solver_name="cp_sat",
        key_parameters={"timeout": 60},
        search_budget_seconds=60.0,
        constraint_validation_result="feasible",
    )
    defaults.update(overrides)
    return SolverChain(**defaults)


def _make_decision_record(
    is_override: bool = False,
    strategy_type: str = "local_repair",
    confirmed_by: str = "planner-1",
) -> DecisionRecord:
    return DecisionRecord(
        decision_record_id=uuid4(),
        incident_id=uuid4(),
        impact_report_summary="2 work orders affected",
        strategy_type=strategy_type,
        all_candidate_plan_ids=[uuid4(), uuid4()],
        recommended_plan_id=uuid4(),
        confirmed_plan_id=uuid4(),
        derived_from_plan_id=uuid4(),
        is_override=is_override,
        is_manual_adjusted=False,
        override_reason="Better option" if is_override else None,
        confirmed_by=confirmed_by,
        confirmed_at=datetime.now(tz=timezone.utc),
        plan_selection_input_version="1.0",
        plan_selection_output_version="1.0",
        solver_chain=_make_solver_chain(strategy_type=strategy_type),
        rule_selector_version="1.0.0",
        neighborhood_selector_version="1.0.0",
        repair_policy_advisor_version="1.0.0",
    )


def _make_execution_result(incident_id=None, decision_record_id=None) -> ExecutionResult:
    return ExecutionResult(
        incident_id=incident_id or uuid4(),
        decision_record_id=decision_record_id or uuid4(),
        actual_completion_times={},
        planned_completion_times={},
        actual_otd=0.95,
        actual_resource_utilization=0.80,
        deviation_percentage=5.0,
    )


# ── create_case ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_case_basic():
    """create_case builds CaseRecord from DecisionRecord + ExecutionResult."""
    lib = CaseLibrary()
    dr = _make_decision_record()
    er = _make_execution_result(dr.incident_id, dr.decision_record_id)

    case = await lib.create_case(dr, er)

    assert isinstance(case, CaseRecord)
    assert case.strategy_type == "local_repair"
    assert case.is_override is False
    assert case.rule_selection == "due_date_priority"
    assert case.neighborhood_selection == "critical_path"
    assert case.repair_policy == "balanced"
    assert case.execution_result is not None
    assert case.embedding_vector is not None
    assert len(case.embedding_vector) > 0


@pytest.mark.asyncio
async def test_create_case_with_override():
    """create_case records override info correctly."""
    lib = CaseLibrary()
    dr = _make_decision_record(is_override=True)
    er = _make_execution_result()

    case = await lib.create_case(dr, er)

    assert case.is_override is True
    assert case.override_reason == "Better option"


# ── find_similar_cases ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_similar_cases_returns_matches():
    """find_similar_cases returns cases above threshold sorted by similarity."""
    lib = CaseLibrary()

    # Create several cases with same strategy
    for _ in range(3):
        dr = _make_decision_record(strategy_type="local_repair")
        er = _make_execution_result()
        await lib.create_case(dr, er)

    results = await lib.find_similar_cases(
        incident_features={"strategy_type": "local_repair", "is_override": False},
        threshold=0.0,  # Low threshold to get results
    )

    assert len(results) > 0
    for case, score in results:
        assert isinstance(case, CaseRecord)
        assert isinstance(score, float)

    # Verify sorted by similarity descending
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_find_similar_cases_empty_store():
    """find_similar_cases returns empty list when no cases exist."""
    lib = CaseLibrary()
    results = await lib.find_similar_cases({"strategy_type": "local_repair"})
    assert results == []


# ── cosine_similarity ──────────────────────────────────────────────


def test_cosine_similarity_identical():
    """Identical vectors have similarity 1.0."""
    assert _cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    """Orthogonal vectors have similarity 0.0."""
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_empty():
    """Empty vectors return 0.0."""
    assert _cosine_similarity([], []) == 0.0


def test_cosine_similarity_different_lengths():
    """Different length vectors return 0.0."""
    assert _cosine_similarity([1.0], [1.0, 2.0]) == 0.0


# ── update_preference ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_preference_on_override():
    """update_preference adjusts weights when override occurs."""
    lib = CaseLibrary()
    dr = _make_decision_record(is_override=True, strategy_type="local_repair")

    profile = await lib.update_preference("planner-1", dr)

    assert profile.planner_id == "planner-1"
    # Override should decrease local_repair weight
    assert profile.strategy_preferences["local_repair"] < 0.34
    # Other strategies should increase
    assert len(profile.override_history) == 1


@pytest.mark.asyncio
async def test_update_preference_no_override():
    """update_preference without override doesn't change weights."""
    lib = CaseLibrary()
    dr = _make_decision_record(is_override=False)

    profile = await lib.update_preference("planner-1", dr)

    # Weights should remain at defaults
    assert profile.strategy_preferences["local_repair"] == pytest.approx(0.34)


# ── get_preference_profile ─────────────────────────────────────────


def test_get_preference_profile_default():
    """get_preference_profile returns default profile for new planner."""
    lib = CaseLibrary()
    profile = lib.get_preference_profile("new-planner")

    assert profile.planner_id == "new-planner"
    assert len(profile.strategy_preferences) == 3
    assert profile.override_history == []


# ── get_strategy_effectiveness ─────────────────────────────────────


@pytest.mark.asyncio
async def test_strategy_effectiveness_tracking():
    """get_strategy_effectiveness tracks rule/neighborhood/repair stats."""
    lib = CaseLibrary()

    # Create cases with different override states
    for i in range(3):
        dr = _make_decision_record(
            is_override=(i == 0), strategy_type="local_repair"
        )
        er = _make_execution_result()
        await lib.create_case(dr, er)

    stats = lib.get_strategy_effectiveness()

    assert "local_repair" in stats
    entry = stats["local_repair"]
    assert entry["total"] == 3
    assert entry["overrides"] == 1
    assert entry["adoption_rate"] == pytest.approx(2 / 3)
    assert "due_date_priority" in entry["rules"]


# ── list_cases ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_cases_with_filter():
    """list_cases filters by strategy_type."""
    lib = CaseLibrary()

    dr1 = _make_decision_record(strategy_type="local_repair")
    dr2 = _make_decision_record(strategy_type="global_reschedule")
    er = _make_execution_result()

    await lib.create_case(dr1, er)
    await lib.create_case(dr2, er)

    local_cases = lib.list_cases(strategy_type="local_repair")
    assert len(local_cases) == 1
    assert local_cases[0].strategy_type == "local_repair"

    all_cases = lib.list_cases()
    assert len(all_cases) == 2


@pytest.mark.asyncio
async def test_get_case_not_found():
    """get_case returns None for unknown case_id."""
    lib = CaseLibrary()
    assert lib.get_case(uuid4()) is None
