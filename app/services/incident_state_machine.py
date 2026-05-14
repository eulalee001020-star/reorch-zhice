"""Incident State Machine — enforces legal state transitions.

Validates: Requirements 17.1

Legal transitions:
  pending_analysis → analyzing
  analyzing → pending_confirmation
  pending_confirmation → confirmed
  confirmed → executing
  executing → closed

Any other transition raises IllegalStateTransitionError.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.enums import IncidentStatus

logger = logging.getLogger(__name__)


class IllegalStateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, current: IncidentStatus, target: IncidentStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Illegal state transition: {current.value} → {target.value}"
        )


# Legal transitions: current_state → set of allowed next states
LEGAL_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.PENDING_ANALYSIS: {IncidentStatus.ANALYZING},
    IncidentStatus.ANALYZING: {IncidentStatus.PENDING_CONFIRMATION},
    IncidentStatus.PENDING_CONFIRMATION: {IncidentStatus.CONFIRMED},
    IncidentStatus.CONFIRMED: {IncidentStatus.EXECUTING},
    IncidentStatus.EXECUTING: {IncidentStatus.CLOSED},
    IncidentStatus.CLOSED: set(),  # terminal state
}

# Ordered state sequence for reference
STATE_ORDER: list[IncidentStatus] = [
    IncidentStatus.PENDING_ANALYSIS,
    IncidentStatus.ANALYZING,
    IncidentStatus.PENDING_CONFIRMATION,
    IncidentStatus.CONFIRMED,
    IncidentStatus.EXECUTING,
    IncidentStatus.CLOSED,
]


class IncidentStateMachine:
    """Enforces legal Incident state transitions.

    Tracks current state and only allows transitions defined in
    LEGAL_TRANSITIONS. Raises IllegalStateTransitionError on violation.
    """

    def __init__(self, initial_status: IncidentStatus = IncidentStatus.PENDING_ANALYSIS) -> None:
        self._status = initial_status
        self._history: list[tuple[IncidentStatus, IncidentStatus]] = []

    @property
    def status(self) -> IncidentStatus:
        return self._status

    @property
    def transition_history(self) -> list[tuple[IncidentStatus, IncidentStatus]]:
        return list(self._history)

    def can_transition(self, target: IncidentStatus) -> bool:
        """Check if transition to target state is legal."""
        allowed = LEGAL_TRANSITIONS.get(self._status, set())
        return target in allowed

    def transition(self, target: IncidentStatus) -> IncidentStatus:
        """Transition to target state.

        Raises IllegalStateTransitionError if the transition is not legal.
        Returns the new state.
        """
        if not self.can_transition(target):
            raise IllegalStateTransitionError(self._status, target)

        old = self._status
        self._status = target
        self._history.append((old, target))
        logger.info("Incident state transition: %s → %s", old.value, target.value)
        return self._status

    def get_allowed_transitions(self) -> set[IncidentStatus]:
        """Return the set of states reachable from current state."""
        return LEGAL_TRANSITIONS.get(self._status, set()).copy()

    def is_terminal(self) -> bool:
        """Check if current state is terminal (no further transitions)."""
        return len(self.get_allowed_transitions()) == 0

    def reset(self, status: IncidentStatus = IncidentStatus.PENDING_ANALYSIS) -> None:
        """Reset the state machine (for testing)."""
        self._status = status
        self._history.clear()


def validate_transition(current: IncidentStatus, target: IncidentStatus) -> None:
    """Standalone validation function — raises on illegal transition."""
    allowed = LEGAL_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise IllegalStateTransitionError(current, target)
