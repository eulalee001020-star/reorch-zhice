"""Strategy Selector — high-level strategy selection based on impact report,
historical cases, and planner preference profile.

Selects among three strategy types:
- Wait-and-Repair: estimated repair time < total buffer of affected operations
- Local-Repair: affected work orders ≤ 20% of total AND no Breach risk
- Global-Reschedule: affected work orders > 20% of total OR Breach risk exists

Does NOT decide specific scheduling rules, neighborhood operators, or repair
intensity — those are delegated to the Solver_Policy_Layer.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.models.case import CaseRecord, PreferenceProfile
from app.models.enums import DeliveryRiskLevel, StrategyType
from app.models.impact import ImpactReport
from app.models.strategy import StrategyRecommendation

logger = logging.getLogger(__name__)

# Threshold for affected work order ratio triggering Global-Reschedule (Req 3.4, 3.5)
_AFFECTED_RATIO_THRESHOLD: float = 0.20

# Minimum similarity score for a historical case to be considered (Req 3.6)
_CASE_SIMILARITY_THRESHOLD: float = 0.8

# Confidence threshold below which an alternative strategy is provided (Req 3.8)
_LOW_CONFIDENCE_THRESHOLD: float = 0.5

# Base confidence values for each rule-match path
_BASE_CONFIDENCE_WAIT: float = 0.75
_BASE_CONFIDENCE_LOCAL: float = 0.70
_BASE_CONFIDENCE_GLOBAL: float = 0.65

# Maximum boost from historical case match
_CASE_BOOST_MAX: float = 0.15

# Maximum boost from preference profile alignment
_PREFERENCE_BOOST_MAX: float = 0.05


class StrategySelector:
    """High-level strategy selector (AI Orchestrator).

    Responsible only for choosing Wait-and-Repair / Local-Repair /
    Global-Reschedule.  Does not decide concrete rules, neighborhoods,
    or repair intensity (Req 3.9).
    """

    async def select_strategy(
        self,
        impact_report: ImpactReport,
        similar_cases: list[CaseRecord],
        preference_profile: PreferenceProfile,
        total_active_work_orders: int,
        estimated_repair_time_minutes: float,
    ) -> StrategyRecommendation:
        """Select a high-level strategy within 10 seconds (Req 3.1).

        Decision logic:
        1. Wait-and-Repair if repair time < total buffer (Req 3.3)
        2. Local-Repair if affected ≤ 20% AND no Breach (Req 3.4)
        3. Global-Reschedule if affected > 20% OR Breach exists (Req 3.5)
        """
        # --- Compute decision factors ---
        total_buffer = self._total_buffer_minutes(impact_report)
        affected_count = len(impact_report.affected_work_orders)
        has_breach = self._has_breach_risk(impact_report)
        affected_ratio = (
            affected_count / total_active_work_orders
            if total_active_work_orders > 0
            else 1.0
        )

        # --- Rank strategies (Req 3.2) ---
        scored: list[tuple[StrategyType, float, list[str]]] = []

        # Wait-and-Repair (Req 3.3)
        wait_factors: list[str] = []
        wait_score = 0.0
        if estimated_repair_time_minutes < total_buffer:
            wait_score = _BASE_CONFIDENCE_WAIT
            wait_factors.append(
                f"estimated_repair_time ({estimated_repair_time_minutes:.1f}min) "
                f"< total_buffer ({total_buffer:.1f}min)"
            )
        scored.append((StrategyType.WAIT_AND_REPAIR, wait_score, wait_factors))

        # Local-Repair (Req 3.4)
        local_factors: list[str] = []
        local_score = 0.0
        if affected_ratio <= _AFFECTED_RATIO_THRESHOLD and not has_breach:
            local_score = _BASE_CONFIDENCE_LOCAL
            local_factors.append(
                f"affected_ratio ({affected_ratio:.1%}) ≤ 20%"
            )
            local_factors.append("no Breach risk in delivery_risk_distribution")
        scored.append((StrategyType.LOCAL_REPAIR, local_score, local_factors))

        # Global-Reschedule (Req 3.5)
        global_factors: list[str] = []
        global_score = 0.0
        if affected_ratio > _AFFECTED_RATIO_THRESHOLD or has_breach:
            global_score = _BASE_CONFIDENCE_GLOBAL
            if affected_ratio > _AFFECTED_RATIO_THRESHOLD:
                global_factors.append(
                    f"affected_ratio ({affected_ratio:.1%}) > 20%"
                )
            if has_breach:
                global_factors.append("Breach risk detected in delivery_risk_distribution")
        scored.append((StrategyType.GLOBAL_RESCHEDULE, global_score, global_factors))

        # --- Historical case boost (Req 3.6) ---
        relevant_cases = self._filter_relevant_cases(similar_cases)
        case_ids: list[UUID] = []
        case_strategy_votes: dict[StrategyType, int] = {}
        for case in relevant_cases:
            cid = case.case_id
            if isinstance(cid, str):
                cid = UUID(cid)
            case_ids.append(cid)
            st = self._parse_strategy_type(case.strategy_type)
            if st is not None:
                case_strategy_votes[st] = case_strategy_votes.get(st, 0) + 1

        if case_strategy_votes:
            most_voted = max(case_strategy_votes, key=lambda k: case_strategy_votes[k])
            vote_ratio = case_strategy_votes[most_voted] / len(relevant_cases)
            boost = vote_ratio * _CASE_BOOST_MAX
            scored = [
                (st, score + boost, factors + [f"historical_case_boost (+{boost:.2f})"])
                if st == most_voted and score > 0
                else (st, score, factors)
                for st, score, factors in scored
            ]

        # --- Preference profile boost (Req 3.6 implicit) ---
        scored = self._apply_preference_boost(scored, preference_profile)

        # --- Sort by score descending ---
        scored.sort(key=lambda x: x[1], reverse=True)

        best_strategy, best_confidence, best_factors = scored[0]

        # Clamp confidence to [0, 1]
        best_confidence = max(0.0, min(1.0, best_confidence))

        # --- Build alternative if low confidence (Req 3.8) ---
        alternative: StrategyType | None = None
        if best_confidence < _LOW_CONFIDENCE_THRESHOLD and len(scored) > 1:
            alternative = scored[1][0]

        # --- Build reasoning string (Req 3.7) ---
        reasoning = self._build_reasoning(
            best_strategy,
            best_factors,
            affected_ratio,
            has_breach,
            estimated_repair_time_minutes,
            total_buffer,
            relevant_cases,
            best_confidence,
            alternative,
        )

        recommendation = StrategyRecommendation(
            strategy_type=best_strategy,
            confidence=round(best_confidence, 4),
            key_factors=best_factors,
            historical_case_ids=case_ids,
            alternative_strategy=alternative,
            reasoning=reasoning,
        )

        logger.info(
            "Strategy selected for incident %s: %s (confidence=%.2f)",
            impact_report.incident_id,
            best_strategy,
            best_confidence,
        )

        return recommendation

    # ── private helpers ─────────────────────────────────────────────

    @staticmethod
    def _total_buffer_minutes(report: ImpactReport) -> float:
        """Sum remaining_buffer_minutes across all affected work orders."""
        return sum(
            wo.remaining_buffer_minutes
            for wo in report.affected_work_orders
        )

    @staticmethod
    def _has_breach_risk(report: ImpactReport) -> bool:
        """Check if any Breach-level delivery risk exists."""
        breach_key = DeliveryRiskLevel.BREACH
        # With use_enum_values the key may be the string value
        for key, count in report.delivery_risk_distribution.items():
            key_val = key.value if hasattr(key, "value") else str(key)
            if key_val == DeliveryRiskLevel.BREACH and count > 0:
                return True
        return False

    @staticmethod
    def _filter_relevant_cases(
        cases: list[CaseRecord],
    ) -> list[CaseRecord]:
        """Return cases with similarity > 0.8 threshold (Req 3.6).

        The caller is expected to pass pre-filtered cases from the
        Case_Library, but we apply the threshold defensively here as well.
        Cases are assumed to already carry a similarity score in their
        ``impact_scope`` dict under the key ``similarity``.
        """
        relevant: list[CaseRecord] = []
        for case in cases:
            sim = case.impact_scope.get("similarity", 1.0)
            if sim >= _CASE_SIMILARITY_THRESHOLD:
                relevant.append(case)
        return relevant

    @staticmethod
    def _parse_strategy_type(value: str) -> StrategyType | None:
        """Safely parse a strategy type string."""
        try:
            return StrategyType(value)
        except ValueError:
            return None

    @staticmethod
    def _apply_preference_boost(
        scored: list[tuple[StrategyType, float, list[str]]],
        profile: PreferenceProfile,
    ) -> list[tuple[StrategyType, float, list[str]]]:
        """Apply a small confidence boost based on planner preference weights."""
        if not profile.strategy_preferences:
            return scored

        result: list[tuple[StrategyType, float, list[str]]] = []
        for st, score, factors in scored:
            st_value = st.value if hasattr(st, "value") else str(st)
            pref_weight = profile.strategy_preferences.get(st_value, 0.0)
            if pref_weight > 0 and score > 0:
                boost = min(pref_weight * _PREFERENCE_BOOST_MAX, _PREFERENCE_BOOST_MAX)
                result.append((
                    st,
                    score + boost,
                    factors + [f"preference_boost (+{boost:.3f})"],
                ))
            else:
                result.append((st, score, factors))
        return result

    @staticmethod
    def _build_reasoning(
        strategy: StrategyType,
        factors: list[str],
        affected_ratio: float,
        has_breach: bool,
        repair_time: float,
        total_buffer: float,
        relevant_cases: list[CaseRecord],
        confidence: float,
        alternative: StrategyType | None,
    ) -> str:
        """Build a human-readable reasoning string (Req 3.7)."""
        parts: list[str] = [
            f"Selected strategy: {strategy.value if hasattr(strategy, 'value') else strategy}.",
        ]

        parts.append(
            f"Affected work order ratio: {affected_ratio:.1%}; "
            f"Breach risk: {'yes' if has_breach else 'no'}; "
            f"Estimated repair time: {repair_time:.1f}min; "
            f"Total buffer: {total_buffer:.1f}min."
        )

        if relevant_cases:
            parts.append(
                f"{len(relevant_cases)} historical case(s) with similarity > 0.8 "
                f"referenced as decision factor."
            )

        parts.append(f"Confidence: {confidence:.2f}.")

        if alternative is not None:
            alt_val = alternative.value if hasattr(alternative, "value") else alternative
            parts.append(
                f"Low confidence — alternative strategy provided: {alt_val}."
            )

        return " ".join(parts)
