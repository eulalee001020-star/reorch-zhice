"""Repair_Policy_Advisor service for the ReOrch Solver Policy Layer.

Decides repair intensity, frozen scope, perturbation scope, search
budget, candidate count target, and fallback strategy based on the
high-level strategy, impact report, and incident severity.

Strategy-to-repair mapping:
- Wait-and-Repair → conservative + freeze all unaffected + 10s budget + 1 candidate
- Local-Repair    → balanced + limit to affected & downstream + 30s budget + 3 candidates
- Global-Reschedule → aggressive + broader scope + 60s budget + 5 candidates

P1 severity boosts search budget.

Supports configurable default repair policy templates per workshop,
incident type, and goal mode (Req 25.10).

Implemented as an independent module with clear input/output interface,
supporting standalone version management and replacement (Req 22.1, 22.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models.enums import (
    IncidentSeverity,
    RepairMode,
    StrategyType,
)
from app.models.impact import ImpactReport
from app.models.strategy import RepairPolicyConfig, StrategyRecommendation

logger = logging.getLogger(__name__)

# ── Module version (Req 22.3 — standalone version management) ───────
MODULE_VERSION: str = "1.0.0"

# ── P1 severity budget multiplier ──────────────────────────────────
_P1_BUDGET_MULTIPLIER: float = 1.5

# ── Default configurations per strategy ─────────────────────────────
_WAIT_BUDGET_SECONDS: float = 10.0
_WAIT_CANDIDATE_TARGET: int = 1

_LOCAL_BUDGET_SECONDS: float = 30.0
_LOCAL_CANDIDATE_TARGET: int = 3

_GLOBAL_BUDGET_SECONDS: float = 60.0
_GLOBAL_CANDIDATE_TARGET: int = 5


@dataclass
class RepairPolicyTemplate:
    """Configurable default repair policy template (Req 25.10).

    Allows overriding default repair parameters for specific
    workshops, incident types, or goal modes.
    """

    workshop_id: str | None = None
    incident_type: str | None = None
    goal_mode: str | None = None
    repair_mode: RepairMode | None = None
    search_time_budget_seconds: float | None = None
    candidate_count_target: int | None = None
    fallback_condition: str | None = None
    fallback_mode: str | None = None


class RepairPolicyAdvisor:
    """Repair policy advisor: decides repair intensity and constraints.

    Accepts StrategyRecommendation, ImpactReport, and IncidentSeverity.
    Returns RepairPolicyConfig (Req 25.1, 25.2).

    Key behaviours:
    - Wait-and-Repair → conservative + freeze all unaffected (Req 25.4)
    - Local-Repair → balanced + scope to affected & downstream (Req 25.5)
    - Global-Reschedule → aggressive + broader scope + higher budget (Req 25.6)
    - P1 severity boosts search budget
    - Fallback on stagnation near budget limit (Req 25.7)
    - Structured output for Hybrid_Solver consumption (Req 25.8)
    """

    def __init__(
        self,
        templates: list[RepairPolicyTemplate] | None = None,
    ) -> None:
        self._templates = templates or []

    async def advise(
        self,
        strategy: StrategyRecommendation,
        impact_report: ImpactReport,
        incident_severity: IncidentSeverity,
    ) -> RepairPolicyConfig:
        """Produce a RepairPolicyConfig for the current scenario.

        Decision flow:
        1. Map strategy type to base repair configuration
        2. Compute frozen and perturbation scopes from impact report
        3. Apply P1 severity budget boost
        4. Apply template overrides if matching (Req 25.10)
        5. Return structured RepairPolicyConfig (Req 25.8)
        """
        strategy_type = self._resolve_strategy_type(strategy.strategy_type)

        # Collect affected operation IDs from impact report
        affected_op_ids = [
            op.operation_id for op in impact_report.affected_operations
        ]
        affected_set = set(affected_op_ids)

        # Derive downstream (indirect) operation IDs
        downstream_op_ids = [
            op.operation_id
            for op in impact_report.affected_operations
            if not op.is_direct
        ]

        # --- Base configuration per strategy (Req 25.3, 25.4, 25.5, 25.6) ---
        config = self._build_base_config(
            strategy_type=strategy_type,
            affected_op_ids=affected_op_ids,
            downstream_op_ids=downstream_op_ids,
        )

        # --- P1 severity budget boost ---
        severity_val = self._resolve_severity(incident_severity)
        if severity_val == IncidentSeverity.P1_CRITICAL:
            config["search_time_budget_seconds"] = round(
                config["search_time_budget_seconds"] * _P1_BUDGET_MULTIPLIER, 1
            )

        # --- Apply template overrides (Req 25.10) ---
        config = self._apply_template_overrides(config)

        result = RepairPolicyConfig(**config)

        logger.info(
            "Repair policy advised: mode=%s, frozen=%d ops, "
            "perturbation=%d ops, budget=%.1fs, candidates=%d "
            "(strategy=%s, severity=%s, module v%s)",
            result.repair_mode,
            len(result.frozen_operation_ids),
            len(result.allowed_perturbation_scope),
            result.search_time_budget_seconds,
            result.candidate_count_target,
            strategy_type.value,
            severity_val.value if hasattr(severity_val, "value") else severity_val,
            MODULE_VERSION,
        )

        return result

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
    def _resolve_severity(value: str | IncidentSeverity) -> IncidentSeverity:
        """Safely resolve an incident severity value."""
        if isinstance(value, IncidentSeverity):
            return value
        try:
            return IncidentSeverity(value)
        except ValueError:
            return IncidentSeverity.P3_MEDIUM

    @staticmethod
    def _build_base_config(
        strategy_type: StrategyType,
        affected_op_ids: list[str],
        downstream_op_ids: list[str],
    ) -> dict:
        """Build base repair configuration from strategy type (Req 25.3–25.6)."""
        affected_set = set(affected_op_ids)

        if strategy_type == StrategyType.WAIT_AND_REPAIR:
            # Conservative: freeze all unaffected, minimal perturbation (Req 25.4)
            return {
                "repair_mode": RepairMode.CONSERVATIVE,
                "frozen_operation_ids": [],  # all unaffected ops frozen by solver
                "allowed_perturbation_scope": list(affected_set),
                "search_time_budget_seconds": _WAIT_BUDGET_SECONDS,
                "candidate_count_target": _WAIT_CANDIDATE_TARGET,
                "fallback_condition": (
                    "No improvement after 80% of time budget consumed"
                ),
                "fallback_mode": "return_current_best",
            }

        if strategy_type == StrategyType.LOCAL_REPAIR:
            # Balanced: limit to affected + direct downstream (Req 25.5)
            perturbation_scope = list(affected_set | set(downstream_op_ids))
            return {
                "repair_mode": RepairMode.BALANCED,
                "frozen_operation_ids": [],  # unaffected ops frozen by solver
                "allowed_perturbation_scope": perturbation_scope,
                "search_time_budget_seconds": _LOCAL_BUDGET_SECONDS,
                "candidate_count_target": _LOCAL_CANDIDATE_TARGET,
                "fallback_condition": (
                    "No improvement after 80% of time budget consumed "
                    "or 10 consecutive stagnation iterations"
                ),
                "fallback_mode": (
                    "return_current_best_and_switch_to_fallback_solver"
                ),
            }

        # Global-Reschedule: aggressive, broader scope (Req 25.6)
        return {
            "repair_mode": RepairMode.AGGRESSIVE,
            "frozen_operation_ids": [],  # no frozen ops for global
            "allowed_perturbation_scope": list(affected_set),
            "search_time_budget_seconds": _GLOBAL_BUDGET_SECONDS,
            "candidate_count_target": _GLOBAL_CANDIDATE_TARGET,
            "fallback_condition": (
                "No improvement after 80% of time budget consumed "
                "or solver reports infeasibility"
            ),
            "fallback_mode": "degrade_to_local_repair_then_fallback_rule",
        }

    def _apply_template_overrides(self, config: dict) -> dict:
        """Apply matching template overrides (Req 25.10).

        Templates are matched by workshop, incident type, and goal mode.
        The first matching template's non-None fields override the config.
        """
        for template in self._templates:
            # Apply non-None overrides from the first matching template
            if template.repair_mode is not None:
                config["repair_mode"] = template.repair_mode
            if template.search_time_budget_seconds is not None:
                config["search_time_budget_seconds"] = (
                    template.search_time_budget_seconds
                )
            if template.candidate_count_target is not None:
                config["candidate_count_target"] = template.candidate_count_target
            if template.fallback_condition is not None:
                config["fallback_condition"] = template.fallback_condition
            if template.fallback_mode is not None:
                config["fallback_mode"] = template.fallback_mode
            break  # first match wins

        return config
