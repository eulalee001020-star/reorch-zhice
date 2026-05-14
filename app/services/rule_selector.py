"""Rule_Selector service for the ReOrch Solver Policy Layer.

Selects scheduling rules based on incident characteristics, impact
report, high-level strategy, preference profile, and historical cases.

Supports five rule categories:
- DUE_DATE_PRIORITY (交期优先)
- SHORTEST_PROCESSING_TIME (最短加工时间)
- MINIMUM_SLACK_TIME (最小松弛时间)
- BOTTLENECK_RESOURCE_PRIORITY (瓶颈资源优先)
- CRITICAL_ORDER_PRIORITY (关键工单优先)

Implemented as an independent module with clear input/output interface,
supporting standalone version management (Req 22.1, 22.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.models.case import CaseRecord, PreferenceProfile
from app.models.enums import (
    DeliveryRiskLevel,
    RuleApplicableStage,
    RuleCategory,
    StrategyType,
)
from app.models.impact import ImpactReport
from app.models.incident import Incident
from app.models.strategy import RuleSelectionResult, StrategyRecommendation

logger = logging.getLogger(__name__)

# ── Module version (Req 22.3 — standalone version management) ───────
MODULE_VERSION: str = "1.0.0"

# ── Thresholds ──────────────────────────────────────────────────────
_CASE_SIMILARITY_THRESHOLD: float = 0.8
_LOW_CONFIDENCE_THRESHOLD: float = 0.5
_CASE_BOOST_MAX: float = 0.15
_PREFERENCE_BOOST_MAX: float = 0.05

# ── Base confidence scores per strategy→rule mapping ────────────────
_BASE_CONFIDENCE: float = 0.7



@dataclass
class RuleConstraint:
    """Configuration constraint that limits a rule to specific contexts.

    Supports restricting rules to specific workshops, incident types,
    or strategy modes (Req 23.10).
    """

    rule_category: RuleCategory
    allowed_workshops: list[str] | None = None
    allowed_incident_types: list[str] | None = None
    allowed_strategy_types: list[StrategyType] | None = None


@dataclass
class RuleScoringEntry:
    """Internal scoring entry for a candidate rule."""

    rule_category: RuleCategory
    rule_name: str
    applicable_stage: RuleApplicableStage
    score: float
    factors: list[str] = field(default_factory=list)


# ── Default rule definitions ────────────────────────────────────────

_RULE_DEFINITIONS: dict[RuleCategory, dict] = {
    RuleCategory.DUE_DATE_PRIORITY: {
        "name": "due_date_priority_rule",
        "stage": RuleApplicableStage.INITIAL_SOLUTION,
    },
    RuleCategory.SHORTEST_PROCESSING_TIME: {
        "name": "shortest_processing_time_rule",
        "stage": RuleApplicableStage.INITIAL_SOLUTION,
    },
    RuleCategory.MINIMUM_SLACK_TIME: {
        "name": "minimum_slack_time_rule",
        "stage": RuleApplicableStage.REPAIR,
    },
    RuleCategory.BOTTLENECK_RESOURCE_PRIORITY: {
        "name": "bottleneck_resource_priority_rule",
        "stage": RuleApplicableStage.REPAIR,
    },
    RuleCategory.CRITICAL_ORDER_PRIORITY: {
        "name": "critical_order_priority_rule",
        "stage": RuleApplicableStage.INITIAL_SOLUTION,
    },
}


class RuleSelector:
    """Rule selector: chooses scheduling rules for the current scenario.

    Accepts Incident, ImpactReport, StrategyRecommendation,
    PreferenceProfile, and list[CaseRecord] as inputs.
    Outputs list[RuleSelectionResult] (Req 23.3, 23.4).

    Supports rule-based, scoring-model, and learning-based
    replaceable implementations (Req 23.8).
    """

    def __init__(
        self,
        constraints: list[RuleConstraint] | None = None,
    ) -> None:
        self._constraints = constraints or []

    async def select_rules(
        self,
        incident: Incident,
        impact_report: ImpactReport,
        strategy: StrategyRecommendation,
        preference_profile: PreferenceProfile,
        similar_cases: list[CaseRecord],
    ) -> list[RuleSelectionResult]:
        """Select scheduling rules within 3 seconds (Req 23.1).

        Decision logic:
        1. Score each rule category based on strategy type mapping
        2. Boost scores from breach risk / affected operation count
        3. Apply historical case boost (Req 23.5)
        4. Apply preference boost
        5. Filter by configuration constraints (Req 23.10)
        6. Return sorted results; low confidence → top-2 (Req 23.6)
        """
        strategy_type = self._resolve_strategy_type(strategy.strategy_type)

        # --- Score all rule categories ---
        scored = self._score_rules(
            strategy_type=strategy_type,
            impact_report=impact_report,
            incident=incident,
        )

        # --- Historical case boost (Req 23.5) ---
        relevant_cases = self._filter_relevant_cases(similar_cases)
        scored = self._apply_case_boost(scored, relevant_cases)

        # --- Preference boost ---
        scored = self._apply_preference_boost(scored, preference_profile)

        # --- Filter by constraints (Req 23.10) ---
        scored = self._apply_constraints(
            scored,
            incident=incident,
            strategy_type=strategy_type,
        )

        # --- Sort by score descending ---
        scored.sort(key=lambda e: e.score, reverse=True)

        # --- Build results (Req 23.4, 23.6, 23.9) ---
        results = self._build_results(scored)

        logger.info(
            "Rule selection for incident %s: %d rule(s) selected (module v%s)",
            incident.incident_id,
            len(results),
            MODULE_VERSION,
        )

        return results

    # ── Private helpers ─────────────────────────────────────────────

    @staticmethod
    def _resolve_strategy_type(value: str | StrategyType) -> StrategyType:
        """Safely resolve a strategy type value."""
        if isinstance(value, StrategyType):
            return value
        try:
            return StrategyType(value)
        except ValueError:
            return StrategyType.LOCAL_REPAIR

    def _score_rules(
        self,
        strategy_type: StrategyType,
        impact_report: ImpactReport,
        incident: Incident,
    ) -> list[RuleScoringEntry]:
        """Score each rule category based on strategy and impact context."""
        entries: list[RuleScoringEntry] = []
        has_breach = self._has_breach_risk(impact_report)
        affected_op_count = len(impact_report.affected_operations)

        for category, defn in _RULE_DEFINITIONS.items():
            score = 0.0
            factors: list[str] = []

            # Strategy-based scoring (Req 23.2)
            score, factors = self._strategy_score(
                category, strategy_type, has_breach, affected_op_count,
            )

            entries.append(
                RuleScoringEntry(
                    rule_category=category,
                    rule_name=defn["name"],
                    applicable_stage=defn["stage"],
                    score=score,
                    factors=factors,
                )
            )

        return entries

    @staticmethod
    def _strategy_score(
        category: RuleCategory,
        strategy_type: StrategyType,
        has_breach: bool,
        affected_op_count: int,
    ) -> tuple[float, list[str]]:
        """Compute base score for a rule category given the strategy context."""
        score = 0.0
        factors: list[str] = []

        # Wait-and-Repair → due_date_priority (Req 23.2)
        if strategy_type == StrategyType.WAIT_AND_REPAIR:
            if category == RuleCategory.DUE_DATE_PRIORITY:
                score = _BASE_CONFIDENCE
                factors.append("wait_and_repair strategy favors due_date_priority")
            elif category == RuleCategory.MINIMUM_SLACK_TIME:
                score = 0.4
                factors.append("slack_time useful as secondary for wait strategy")

        # Local-Repair → slack / bottleneck (Req 23.2)
        elif strategy_type == StrategyType.LOCAL_REPAIR:
            if category == RuleCategory.MINIMUM_SLACK_TIME:
                score = _BASE_CONFIDENCE
                factors.append("local_repair strategy favors minimum_slack_time")
            elif category == RuleCategory.BOTTLENECK_RESOURCE_PRIORITY:
                score = 0.65
                factors.append("bottleneck_resource useful for local repair")
            elif category == RuleCategory.SHORTEST_PROCESSING_TIME:
                score = 0.45
                factors.append("SPT as secondary for local repair")

        # Global-Reschedule → due_date / critical_order (Req 23.2)
        elif strategy_type == StrategyType.GLOBAL_RESCHEDULE:
            if category == RuleCategory.DUE_DATE_PRIORITY:
                score = _BASE_CONFIDENCE
                factors.append("global_reschedule strategy favors due_date_priority")
            elif category == RuleCategory.CRITICAL_ORDER_PRIORITY:
                score = 0.65
                factors.append("critical_order important for global reschedule")
            elif category == RuleCategory.BOTTLENECK_RESOURCE_PRIORITY:
                score = 0.5
                factors.append("bottleneck_resource relevant for global reschedule")

        # Breach risk boost
        if has_breach and category in (
            RuleCategory.DUE_DATE_PRIORITY,
            RuleCategory.CRITICAL_ORDER_PRIORITY,
        ):
            boost = 0.1
            score += boost
            factors.append(f"breach_risk_boost (+{boost:.2f})")

        # High affected operation count boost
        if affected_op_count > 5 and category == RuleCategory.BOTTLENECK_RESOURCE_PRIORITY:
            boost = 0.08
            score += boost
            factors.append(f"high_affected_ops_boost (+{boost:.2f})")

        return score, factors

    @staticmethod
    def _has_breach_risk(report: ImpactReport) -> bool:
        """Check if any Breach-level delivery risk exists."""
        for key, count in report.delivery_risk_distribution.items():
            key_val = key.value if hasattr(key, "value") else str(key)
            if key_val == DeliveryRiskLevel.BREACH and count > 0:
                return True
        return False

    @staticmethod
    def _filter_relevant_cases(
        cases: list[CaseRecord],
    ) -> list[CaseRecord]:
        """Return cases with similarity > 0.8 (Req 23.5)."""
        relevant: list[CaseRecord] = []
        for case in cases:
            sim = case.impact_scope.get("similarity", 1.0)
            if sim >= _CASE_SIMILARITY_THRESHOLD:
                relevant.append(case)
        return relevant

    @staticmethod
    def _apply_case_boost(
        entries: list[RuleScoringEntry],
        relevant_cases: list[CaseRecord],
    ) -> list[RuleScoringEntry]:
        """Boost rules that were successfully used in similar cases (Req 23.5)."""
        if not relevant_cases:
            return entries

        # Count rule category votes from historical cases
        rule_votes: dict[str, int] = {}
        for case in relevant_cases:
            rule_sel = case.rule_selection
            if rule_sel:
                rule_votes[rule_sel] = rule_votes.get(rule_sel, 0) + 1

        if not rule_votes:
            return entries

        total_cases = len(relevant_cases)
        for entry in entries:
            vote_count = rule_votes.get(entry.rule_category.value, 0)
            if vote_count > 0 and entry.score > 0:
                vote_ratio = vote_count / total_cases
                boost = vote_ratio * _CASE_BOOST_MAX
                entry.score += boost
                entry.factors.append(
                    f"historical_case_boost (+{boost:.3f}, "
                    f"{vote_count}/{total_cases} cases)"
                )

        return entries

    @staticmethod
    def _apply_preference_boost(
        entries: list[RuleScoringEntry],
        profile: PreferenceProfile,
    ) -> list[RuleScoringEntry]:
        """Apply small confidence boost from planner preference weights."""
        if not profile.strategy_preferences:
            return entries

        for entry in entries:
            pref_weight = profile.strategy_preferences.get(
                entry.rule_category.value, 0.0
            )
            if pref_weight > 0 and entry.score > 0:
                boost = min(pref_weight * _PREFERENCE_BOOST_MAX, _PREFERENCE_BOOST_MAX)
                entry.score += boost
                entry.factors.append(f"preference_boost (+{boost:.3f})")

        return entries

    def _apply_constraints(
        self,
        entries: list[RuleScoringEntry],
        incident: Incident,
        strategy_type: StrategyType,
    ) -> list[RuleScoringEntry]:
        """Filter out rules that are not allowed by configuration constraints (Req 23.10)."""
        if not self._constraints:
            return entries

        # Build a set of blocked categories
        blocked: set[RuleCategory] = set()
        incident_type_val = (
            incident.incident_type.value
            if hasattr(incident.incident_type, "value")
            else str(incident.incident_type)
        )

        for constraint in self._constraints:
            cat = constraint.rule_category

            # Check incident type restriction
            if (
                constraint.allowed_incident_types is not None
                and incident_type_val not in constraint.allowed_incident_types
            ):
                blocked.add(cat)
                continue

            # Check strategy type restriction
            if constraint.allowed_strategy_types is not None:
                if strategy_type not in constraint.allowed_strategy_types:
                    blocked.add(cat)
                    continue

        return [e for e in entries if e.rule_category not in blocked]

    @staticmethod
    def _build_results(
        scored: list[RuleScoringEntry],
    ) -> list[RuleSelectionResult]:
        """Convert scored entries to RuleSelectionResult list (Req 23.4, 23.6)."""
        if not scored:
            return []

        results: list[RuleSelectionResult] = []
        best_confidence = max(0.0, min(1.0, scored[0].score)) if scored else 0.0

        # If best confidence < 0.5, output top-2 (Req 23.6)
        output_count = 2 if best_confidence < _LOW_CONFIDENCE_THRESHOLD else 1
        output_count = min(output_count, len(scored))

        for i in range(output_count):
            entry = scored[i]
            confidence = max(0.0, min(1.0, entry.score))

            # Determine alternative rule (Req 23.6)
            alternative: str | None = None
            if confidence < _LOW_CONFIDENCE_THRESHOLD and i == 0 and len(scored) > 1:
                alternative = scored[1].rule_name

            reasoning = (
                f"Rule '{entry.rule_name}' ({entry.rule_category.value}) selected. "
                f"Factors: {'; '.join(entry.factors) if entry.factors else 'default scoring'}. "
                f"Confidence: {confidence:.2f}."
            )
            if alternative:
                reasoning += f" Alternative: {alternative}."

            results.append(
                RuleSelectionResult(
                    rule_name=entry.rule_name,
                    rule_category=entry.rule_category,
                    applicable_stage=entry.applicable_stage,
                    confidence=round(confidence, 4),
                    reasoning=reasoning,
                    alternative_rule=alternative,
                )
            )

        return results
