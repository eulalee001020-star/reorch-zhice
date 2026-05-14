"""Tests for Incident State Machine.

Validates: Requirements 17.1
"""

import pytest

from app.models.enums import IncidentStatus
from app.services.incident_state_machine import (
    IllegalStateTransitionError,
    IncidentStateMachine,
    LEGAL_TRANSITIONS,
    STATE_ORDER,
    validate_transition,
)


class TestIncidentStateMachine:
    """Test legal and illegal state transitions."""

    def test_initial_state_is_pending_analysis(self) -> None:
        sm = IncidentStateMachine()
        assert sm.status == IncidentStatus.PENDING_ANALYSIS

    def test_full_happy_path(self) -> None:
        """Walk through the entire legal state sequence."""
        sm = IncidentStateMachine()
        sm.transition(IncidentStatus.ANALYZING)
        assert sm.status == IncidentStatus.ANALYZING

        sm.transition(IncidentStatus.PENDING_CONFIRMATION)
        assert sm.status == IncidentStatus.PENDING_CONFIRMATION

        sm.transition(IncidentStatus.CONFIRMED)
        assert sm.status == IncidentStatus.CONFIRMED

        sm.transition(IncidentStatus.EXECUTING)
        assert sm.status == IncidentStatus.EXECUTING

        sm.transition(IncidentStatus.CLOSED)
        assert sm.status == IncidentStatus.CLOSED

    def test_illegal_skip_transition_raises(self) -> None:
        """Skipping a state should raise IllegalStateTransitionError."""
        sm = IncidentStateMachine()
        with pytest.raises(IllegalStateTransitionError) as exc_info:
            sm.transition(IncidentStatus.CONFIRMED)
        assert exc_info.value.current == IncidentStatus.PENDING_ANALYSIS
        assert exc_info.value.target == IncidentStatus.CONFIRMED

    def test_backward_transition_raises(self) -> None:
        """Going backward should raise."""
        sm = IncidentStateMachine()
        sm.transition(IncidentStatus.ANALYZING)
        with pytest.raises(IllegalStateTransitionError):
            sm.transition(IncidentStatus.PENDING_ANALYSIS)

    def test_self_transition_raises(self) -> None:
        """Transitioning to the same state should raise."""
        sm = IncidentStateMachine()
        with pytest.raises(IllegalStateTransitionError):
            sm.transition(IncidentStatus.PENDING_ANALYSIS)

    def test_closed_is_terminal(self) -> None:
        """No transitions allowed from CLOSED."""
        sm = IncidentStateMachine(initial_status=IncidentStatus.CLOSED)
        assert sm.is_terminal()
        for target in IncidentStatus:
            assert not sm.can_transition(target)

    def test_can_transition_returns_correct_values(self) -> None:
        sm = IncidentStateMachine()
        assert sm.can_transition(IncidentStatus.ANALYZING)
        assert not sm.can_transition(IncidentStatus.CLOSED)

    def test_get_allowed_transitions(self) -> None:
        sm = IncidentStateMachine()
        allowed = sm.get_allowed_transitions()
        assert allowed == {IncidentStatus.ANALYZING}

    def test_transition_history_recorded(self) -> None:
        sm = IncidentStateMachine()
        sm.transition(IncidentStatus.ANALYZING)
        sm.transition(IncidentStatus.PENDING_CONFIRMATION)
        history = sm.transition_history
        assert len(history) == 2
        assert history[0] == (IncidentStatus.PENDING_ANALYSIS, IncidentStatus.ANALYZING)
        assert history[1] == (IncidentStatus.ANALYZING, IncidentStatus.PENDING_CONFIRMATION)

    def test_all_legal_transitions_covered(self) -> None:
        """Every consecutive pair in STATE_ORDER should be a legal transition."""
        for i in range(len(STATE_ORDER) - 1):
            current = STATE_ORDER[i]
            next_state = STATE_ORDER[i + 1]
            assert next_state in LEGAL_TRANSITIONS[current], (
                f"Expected {current.value} → {next_state.value} to be legal"
            )

    def test_all_non_consecutive_transitions_illegal(self) -> None:
        """Skipping states should be illegal."""
        for i in range(len(STATE_ORDER)):
            for j in range(len(STATE_ORDER)):
                if j == i + 1:
                    continue  # legal
                current = STATE_ORDER[i]
                target = STATE_ORDER[j]
                assert target not in LEGAL_TRANSITIONS.get(current, set()), (
                    f"Expected {current.value} → {target.value} to be illegal"
                )

    def test_validate_transition_standalone(self) -> None:
        validate_transition(IncidentStatus.PENDING_ANALYSIS, IncidentStatus.ANALYZING)
        with pytest.raises(IllegalStateTransitionError):
            validate_transition(IncidentStatus.PENDING_ANALYSIS, IncidentStatus.CLOSED)

    def test_reset(self) -> None:
        sm = IncidentStateMachine()
        sm.transition(IncidentStatus.ANALYZING)
        sm.reset()
        assert sm.status == IncidentStatus.PENDING_ANALYSIS
        assert sm.transition_history == []
