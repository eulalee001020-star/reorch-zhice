"""Solver_Portfolio service for the ReOrch Solver Policy Layer.

Manages solver chain configurations for different high-level strategies,
including primary solver, fallback solver, degradation rules, and
timeout settings.

Supports version management and audit logging per Req 22.9, 22.10.
"""

from __future__ import annotations

import logging

from app.models.enums import StrategyType
from app.models.strategy import SolverChainConfig

logger = logging.getLogger(__name__)

# ── Module version (Req 22.3 — standalone version management) ───────
MODULE_VERSION: str = "1.0.0"

# ── Default solver chain configurations per strategy ────────────────

_DEFAULT_CONFIGS: dict[StrategyType, SolverChainConfig] = {
    StrategyType.WAIT_AND_REPAIR: SolverChainConfig(
        primary_solver="cp_sat_time_shift",
        fallback_solver="greedy_time_shift",
        fallback_rule="earliest_due_date",
        degradation_trigger=(
            "Primary solver timeout or infeasible after 80% budget"
        ),
        max_timeout_seconds=15.0,
    ),
    StrategyType.LOCAL_REPAIR: SolverChainConfig(
        primary_solver="cp_sat_lns",
        fallback_solver="greedy_local_repair",
        fallback_rule="minimum_slack_time",
        degradation_trigger=(
            "Primary solver timeout, infeasible, or 10 consecutive "
            "stagnation iterations"
        ),
        max_timeout_seconds=45.0,
    ),
    StrategyType.GLOBAL_RESCHEDULE: SolverChainConfig(
        primary_solver="cp_sat_global",
        fallback_solver="cp_sat_lns",
        fallback_rule="due_date_priority",
        degradation_trigger=(
            "Primary solver timeout or infeasible; fallback to LNS "
            "then greedy rule"
        ),
        max_timeout_seconds=90.0,
    ),
}


class SolverPortfolio:
    """Solver portfolio: manages solver chain configs per strategy.

    Maintains default configurations for each high-level strategy type
    and supports runtime overrides via custom configs.

    Supports version management and audit logging (Req 22.9, 22.10).
    """

    def __init__(
        self,
        custom_configs: dict[StrategyType, SolverChainConfig] | None = None,
    ) -> None:
        self._configs: dict[StrategyType, SolverChainConfig] = {
            **_DEFAULT_CONFIGS,
        }
        if custom_configs:
            self._configs.update(custom_configs)

    def get_chain_config(self, strategy_type: str | StrategyType) -> SolverChainConfig:
        """Return the solver chain config for the given strategy type.

        Falls back to LOCAL_REPAIR config if the strategy type is unknown.
        """
        resolved = self._resolve_strategy_type(strategy_type)
        config = self._configs.get(resolved, _DEFAULT_CONFIGS[StrategyType.LOCAL_REPAIR])

        logger.info(
            "SolverPortfolio: chain config for strategy=%s — "
            "primary=%s, fallback=%s, timeout=%.1fs (module v%s)",
            resolved.value,
            config.primary_solver,
            config.fallback_solver,
            config.max_timeout_seconds,
            MODULE_VERSION,
        )
        return config

    @staticmethod
    def _resolve_strategy_type(value: str | StrategyType) -> StrategyType:
        if isinstance(value, StrategyType):
            return value
        try:
            return StrategyType(value)
        except ValueError:
            return StrategyType.LOCAL_REPAIR
