"""PlanSelectionInput assembler — builds the unified input object
for Plan_Recommendation_Engine from scattered domain fragments.

Ensures the recommendation service never directly assembles
fragmented fields; all assembly logic is centralised here.

Validates: Requirements 30.1, 30.2, 30.3, 30.10
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.models.case import PreferenceProfile
from app.models.enums import GoalMode
from app.models.incident import Incident
from app.models.recommendation import PlanSelectionInput
from app.models.solver import CandidatePlan

logger = logging.getLogger(__name__)


class PlanSelectionInputBuilder:
    """Assembles a ``PlanSelectionInput`` from domain fragments.

    This builder is the **single entry-point** for constructing the
    recommendation engine's input.  Downstream consumers (e.g.
    ``PlanRecommendationEngine``) receive a fully-formed object and
    never touch the individual pieces directly.
    """

    @staticmethod
    def build(
        incident: Incident,
        snapshot_id: UUID,
        candidates: list[CandidatePlan],
        goal_mode: GoalMode | str = GoalMode.BALANCED,
        preference_profile: PreferenceProfile | None = None,
        case_matches: list[dict] | None = None,
        manual_weights: dict[str, float] | None = None,
        execution_constraints: dict | None = None,
    ) -> PlanSelectionInput:
        """Build a ``PlanSelectionInput``.

        Parameters
        ----------
        incident:
            The current ``Incident`` being processed.
        snapshot_id:
            UUID of the baseline ``ScheduleSnapshot``.
        candidates:
            Candidate plans produced by ``HybridSolver``.
        goal_mode:
            Business objective mode (default: balanced).
        preference_profile:
            Planner's learned preference profile (optional).
        case_matches:
            Historical case matches from Case_Library (optional).
        manual_weights:
            Human-supplied dimension weights override (optional).
        execution_constraints:
            Additional execution constraints (optional).

        Returns
        -------
        PlanSelectionInput
            Fully assembled input ready for ``PlanRecommendationEngine``.
        """
        goal_mode_str = (
            goal_mode if isinstance(goal_mode, str) else goal_mode.value
        )

        pref_dict: dict = {}
        if preference_profile is not None:
            pref_dict = preference_profile.model_dump()

        return PlanSelectionInput(
            incident_id=incident.incident_id,
            incident_type=incident.incident_type,
            severity=incident.severity,
            schedule_snapshot_id=snapshot_id,
            candidate_plans=candidates,
            goal_mode=goal_mode_str,
            preference_profile=pref_dict,
            historical_case_matches=case_matches or [],
            manual_weights=manual_weights,
            execution_constraints=execution_constraints,
        )
