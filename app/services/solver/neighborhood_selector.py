"""Neighborhood_Selector service for the ReOrch Solver Policy Layer.

Dynamically selects LNS neighborhood operators and search scope based
on current solution state, affected operations, optimization progress,
remaining budget, strategy, and perturbation constraints.

Supports six neighborhood categories:
- CRITICAL_PATH (关键路径)
- BOTTLENECK_DEVICE (瓶颈设备)
- DELAYED_ORDER (延迟工单)
- SAME_DEVICE_SWAP (同设备交换)
- OPERATION_INSERT (工序插入)
- DEVICE_REASSIGNMENT (设备重分配)

Local-Repair: prefers local neighborhoods, blocks global expansion.
Invariance protection: unaffected operations excluded by default.
Stagnation escalation: switches to larger neighborhoods on no improvement.
Budget-aware: prefers low-cost neighborhoods near time limit.

Implemented as an independent module with clear input/output interface,
supporting standalone version management and replaceable implementations
(rule-driven / learning-driven) per Req 22.1, 22.3, 24.9.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from app.models.enums import NeighborhoodType, StrategyType
from app.models.solver import CandidatePlan
from app.models.strategy import NeighborhoodConfig, StrategyRecommendation

logger = logging.getLogger(__name__)

# ── Module version (Req 22.3 — standalone version management) ───────
MODULE_VERSION: str = "1.0.0"

# ── Thresholds ──────────────────────────────────────────────────────
_STAGNATION_ESCALATION_THRESHOLD: int = 5
_LOW_BUDGET_SECONDS: float = 10.0
_LOW_CONFIDENCE_THRESHOLD: float = 0.5


# ── Neighborhood cost estimates (relative, lower = cheaper) ─────────
_NEIGHBORHOOD_COST: dict[NeighborhoodType, float] = {
    NeighborhoodType.SAME_DEVICE_SWAP: 0.1,
    NeighborhoodType.OPERATION_INSERT: 0.2,
    NeighborhoodType.CRITICAL_PATH: 0.4,
    NeighborhoodType.DELAYED_ORDER: 0.3,
    NeighborhoodType.BOTTLENECK_DEVICE: 0.5,
    NeighborhoodType.DEVICE_REASSIGNMENT: 0.7,
}

# ── Neighborhoods classified as local vs global ─────────────────────
_LOCAL_NEIGHBORHOODS: frozenset[NeighborhoodType] = frozenset({
    NeighborhoodType.CRITICAL_PATH,
    NeighborhoodType.SAME_DEVICE_SWAP,
    NeighborhoodType.DELAYED_ORDER,
})

_GLOBAL_NEIGHBORHOODS: frozenset[NeighborhoodType] = frozenset({
    NeighborhoodType.BOTTLENECK_DEVICE,
    NeighborhoodType.OPERATION_INSERT,
    NeighborhoodType.DEVICE_REASSIGNMENT,
})

_LOW_COST_NEIGHBORHOODS: frozenset[NeighborhoodType] = frozenset({
    NeighborhoodType.SAME_DEVICE_SWAP,
    NeighborhoodType.OPERATION_INSERT,
})


@dataclass
class NeighborhoodScoringEntry:
    """Internal scoring entry for a candidate neighborhood."""

    neighborhood_type: NeighborhoodType
    score: float
    target_operation_ids: list[str] = field(default_factory=list)
    intensity: float = 0.5
    estimated_impact_scope: int = 0
    factors: list[str] = field(default_factory=list)


class NeighborhoodSelectorProtocol(Protocol):
    """Protocol for replaceable neighborhood selector implementations (Req 24.9)."""

    async def select_neighborhood(
        self,
        current_solution: CandidatePlan,
        affected_operation_ids: list[str],
        stagnation_count: int,
        remaining_budget_seconds: float,
        strategy: StrategyRecommendation,
        perturbation_constraint: float,
    ) -> list[NeighborhoodConfig]: ...



class NeighborhoodSelector:
    """Rule-driven neighborhood selector (Req 24.1–24.10).

    Accepts current_solution (CandidatePlan), affected_operation_ids,
    stagnation_count, remaining_budget_seconds, strategy
    (StrategyRecommendation), and perturbation_constraint.

    Returns list[NeighborhoodConfig].

    Key behaviours:
    - Local-Repair: prefer local neighborhoods, block global (Req 24.5)
    - Invariance protection: unaffected ops excluded (Req 24.10)
    - Stagnation escalation: larger neighborhoods on no improvement (Req 24.6)
    - Budget-aware: low-cost neighborhoods near time limit (Req 24.7)
    """

    async def select_neighborhood(
        self,
        current_solution: CandidatePlan,
        affected_operation_ids: list[str],
        stagnation_count: int,
        remaining_budget_seconds: float,
        strategy: StrategyRecommendation,
        perturbation_constraint: float,
    ) -> list[NeighborhoodConfig]:
        """Select neighborhood operators for the current LNS iteration.

        Returns one or more NeighborhoodConfig entries sorted by score.
        """
        strategy_type = self._resolve_strategy_type(strategy.strategy_type)
        affected_set = set(affected_operation_ids)

        # 1. Score all neighborhood types
        scored = self._score_neighborhoods(
            strategy_type=strategy_type,
            affected_operation_ids=affected_operation_ids,
            perturbation_constraint=perturbation_constraint,
        )

        # 2. Apply invariance protection (Req 24.10)
        scored = self._apply_invariance_protection(
            scored, affected_set, strategy_type,
        )

        # 3. Block global neighborhoods for Local-Repair (Req 24.5)
        scored = self._apply_local_repair_filter(scored, strategy_type, stagnation_count)

        # 4. Stagnation escalation (Req 24.6)
        scored = self._apply_stagnation_escalation(scored, stagnation_count)

        # 5. Budget-aware selection (Req 24.7)
        scored = self._apply_budget_preference(scored, remaining_budget_seconds)

        # 6. Sort by score descending
        scored.sort(key=lambda e: e.score, reverse=True)

        # 7. Build results
        results = self._build_results(scored)

        logger.info(
            "Neighborhood selection: %d neighborhood(s) selected "
            "(stagnation=%d, budget=%.1fs, strategy=%s, module v%s)",
            len(results),
            stagnation_count,
            remaining_budget_seconds,
            strategy_type.value,
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

    @staticmethod
    def _score_neighborhoods(
        strategy_type: StrategyType,
        affected_operation_ids: list[str],
        perturbation_constraint: float,
    ) -> list[NeighborhoodScoringEntry]:
        """Score each neighborhood type based on strategy and context (Req 24.2)."""
        entries: list[NeighborhoodScoringEntry] = []
        affected_count = len(affected_operation_ids)

        for nh_type in NeighborhoodType:
            score = 0.0
            factors: list[str] = []
            intensity = 0.5
            target_ops = list(affected_operation_ids)

            if strategy_type == StrategyType.WAIT_AND_REPAIR:
                # Conservative: only same_device_swap and delayed_order
                if nh_type == NeighborhoodType.SAME_DEVICE_SWAP:
                    score = 0.7
                    intensity = 0.3
                    factors.append("wait_and_repair favors same_device_swap")
                elif nh_type == NeighborhoodType.DELAYED_ORDER:
                    score = 0.5
                    intensity = 0.3
                    factors.append("delayed_order as secondary for wait strategy")
                else:
                    score = 0.1
                    factors.append("low priority for wait_and_repair")

            elif strategy_type == StrategyType.LOCAL_REPAIR:
                # Local neighborhoods preferred (Req 24.5)
                if nh_type == NeighborhoodType.CRITICAL_PATH:
                    score = 0.75
                    intensity = 0.5
                    factors.append("local_repair favors critical_path")
                elif nh_type == NeighborhoodType.SAME_DEVICE_SWAP:
                    score = 0.7
                    intensity = 0.4
                    factors.append("same_device_swap efficient for local repair")
                elif nh_type == NeighborhoodType.DELAYED_ORDER:
                    score = 0.65
                    intensity = 0.5
                    factors.append("delayed_order relevant for local repair")
                elif nh_type in _GLOBAL_NEIGHBORHOODS:
                    score = 0.0
                    factors.append("global neighborhood blocked for local_repair")

            elif strategy_type == StrategyType.GLOBAL_RESCHEDULE:
                # All neighborhoods available with higher intensity
                if nh_type == NeighborhoodType.DEVICE_REASSIGNMENT:
                    score = 0.75
                    intensity = 0.8
                    target_ops = []  # global scope
                    factors.append("global_reschedule favors device_reassignment")
                elif nh_type == NeighborhoodType.CRITICAL_PATH:
                    score = 0.7
                    intensity = 0.7
                    target_ops = []
                    factors.append("critical_path important for global reschedule")
                elif nh_type == NeighborhoodType.BOTTLENECK_DEVICE:
                    score = 0.65
                    intensity = 0.7
                    target_ops = []
                    factors.append("bottleneck_device relevant for global reschedule")
                elif nh_type == NeighborhoodType.OPERATION_INSERT:
                    score = 0.6
                    intensity = 0.6
                    target_ops = []
                    factors.append("operation_insert useful for global reschedule")
                elif nh_type == NeighborhoodType.SAME_DEVICE_SWAP:
                    score = 0.55
                    intensity = 0.5
                    target_ops = []
                    factors.append("same_device_swap as supplement for global")
                elif nh_type == NeighborhoodType.DELAYED_ORDER:
                    score = 0.5
                    intensity = 0.6
                    target_ops = []
                    factors.append("delayed_order as supplement for global")

            # Perturbation constraint adjustment
            if perturbation_constraint < 0.3 and nh_type in _GLOBAL_NEIGHBORHOODS:
                penalty = 0.2
                score = max(0.0, score - penalty)
                factors.append(f"tight_perturbation_penalty (-{penalty:.2f})")

            # Affected count boost for targeted neighborhoods
            if affected_count > 10 and nh_type == NeighborhoodType.BOTTLENECK_DEVICE:
                boost = 0.1
                score += boost
                factors.append(f"high_affected_ops_boost (+{boost:.2f})")

            estimated_scope = (
                affected_count if target_ops else affected_count * 3
            )

            entries.append(
                NeighborhoodScoringEntry(
                    neighborhood_type=nh_type,
                    score=score,
                    target_operation_ids=target_ops,
                    intensity=intensity,
                    estimated_impact_scope=estimated_scope,
                    factors=factors,
                )
            )

        return entries

    @staticmethod
    def _apply_invariance_protection(
        entries: list[NeighborhoodScoringEntry],
        affected_set: set[str],
        strategy_type: StrategyType,
    ) -> list[NeighborhoodScoringEntry]:
        """Enforce invariance protection: unaffected ops excluded (Req 24.10).

        For Local-Repair, target_operation_ids are restricted to affected
        operations only. Global-Reschedule may use broader scope.
        """
        if strategy_type == StrategyType.GLOBAL_RESCHEDULE:
            return entries

        for entry in entries:
            if entry.target_operation_ids:
                # Filter to only affected operations
                entry.target_operation_ids = [
                    op_id for op_id in entry.target_operation_ids
                    if op_id in affected_set
                ]
                entry.estimated_impact_scope = len(entry.target_operation_ids)
            if not entry.target_operation_ids and entry.score > 0:
                entry.factors.append("invariance_protection: scoped to affected ops")
                entry.target_operation_ids = list(affected_set)
                entry.estimated_impact_scope = len(affected_set)

        return entries

    @staticmethod
    def _apply_local_repair_filter(
        entries: list[NeighborhoodScoringEntry],
        strategy_type: StrategyType,
        stagnation_count: int,
    ) -> list[NeighborhoodScoringEntry]:
        """Block global neighborhoods for Local-Repair (Req 24.5).

        Only allows escalation to global neighborhoods when stagnation
        exceeds the escalation threshold (Req 24.6).
        """
        if strategy_type != StrategyType.LOCAL_REPAIR:
            return entries

        escalation_allowed = stagnation_count > _STAGNATION_ESCALATION_THRESHOLD

        for entry in entries:
            if entry.neighborhood_type in _GLOBAL_NEIGHBORHOODS:
                if not escalation_allowed:
                    entry.score = 0.0
                    entry.factors.append(
                        "blocked: global neighborhood not allowed for local_repair"
                    )
                else:
                    # Allow with a base score during escalation
                    entry.score = max(entry.score, 0.25)
                    entry.factors.append(
                        f"escalation_allowed: stagnation={stagnation_count} "
                        f"> threshold={_STAGNATION_ESCALATION_THRESHOLD}"
                    )

        return entries

    @staticmethod
    def _apply_stagnation_escalation(
        entries: list[NeighborhoodScoringEntry],
        stagnation_count: int,
    ) -> list[NeighborhoodScoringEntry]:
        """Escalate to larger/different neighborhoods on stagnation (Req 24.6).

        When stagnation exceeds threshold, boost broader neighborhoods
        and increase intensity.
        """
        if stagnation_count <= _STAGNATION_ESCALATION_THRESHOLD:
            return entries

        escalation_factor = min(
            0.2, 0.05 * (stagnation_count - _STAGNATION_ESCALATION_THRESHOLD)
        )

        for entry in entries:
            if entry.score > 0:
                # Boost broader neighborhoods more
                if entry.neighborhood_type in _GLOBAL_NEIGHBORHOODS:
                    boost = escalation_factor
                    entry.score += boost
                    entry.intensity = min(1.0, entry.intensity + 0.2)
                    entry.factors.append(
                        f"stagnation_escalation_boost (+{boost:.3f}, "
                        f"stagnation={stagnation_count})"
                    )
                else:
                    # Increase intensity for local neighborhoods too
                    entry.intensity = min(1.0, entry.intensity + 0.1)
                    entry.factors.append(
                        f"stagnation_intensity_increase (stagnation={stagnation_count})"
                    )

        return entries

    @staticmethod
    def _apply_budget_preference(
        entries: list[NeighborhoodScoringEntry],
        remaining_budget_seconds: float,
    ) -> list[NeighborhoodScoringEntry]:
        """Prefer low-cost neighborhoods when budget is low (Req 24.7)."""
        if remaining_budget_seconds >= _LOW_BUDGET_SECONDS:
            return entries

        budget_ratio = remaining_budget_seconds / _LOW_BUDGET_SECONDS

        for entry in entries:
            cost = _NEIGHBORHOOD_COST.get(entry.neighborhood_type, 0.5)
            if entry.neighborhood_type in _LOW_COST_NEIGHBORHOODS:
                boost = 0.15 * (1.0 - budget_ratio)
                entry.score += boost
                entry.factors.append(
                    f"low_budget_boost (+{boost:.3f}, "
                    f"remaining={remaining_budget_seconds:.1f}s)"
                )
            elif cost > 0.4:
                penalty = 0.2 * (1.0 - budget_ratio)
                entry.score = max(0.0, entry.score - penalty)
                entry.factors.append(
                    f"high_cost_budget_penalty (-{penalty:.3f}, "
                    f"remaining={remaining_budget_seconds:.1f}s)"
                )

        return entries

    @staticmethod
    def _build_results(
        scored: list[NeighborhoodScoringEntry],
    ) -> list[NeighborhoodConfig]:
        """Convert scored entries to NeighborhoodConfig list (Req 24.4).

        Filters out zero-score entries and builds structured output.
        """
        results: list[NeighborhoodConfig] = []

        for entry in scored:
            if entry.score <= 0:
                continue

            confidence = max(0.0, min(1.0, entry.score))

            reasoning = (
                f"Neighborhood '{entry.neighborhood_type.value}' selected. "
                f"Factors: {'; '.join(entry.factors) if entry.factors else 'default scoring'}. "
                f"Intensity: {entry.intensity:.2f}, "
                f"estimated scope: {entry.estimated_impact_scope} ops."
            )

            results.append(
                NeighborhoodConfig(
                    neighborhood_type=NeighborhoodType(entry.neighborhood_type),
                    target_operation_ids=entry.target_operation_ids,
                    intensity=round(entry.intensity, 4),
                    estimated_impact_scope=entry.estimated_impact_scope,
                    reasoning=reasoning,
                )
            )

        return results
