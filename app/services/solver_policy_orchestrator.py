"""Solver_Policy_Layer orchestrator for the ReOrch system.

Provides a unified SolverPolicyBundle that Hybrid_Solver consumes as
its single strategy control object.  Coordinates Rule_Selector,
Repair_Policy_Advisor, Solver_Portfolio, and exposes a runtime
interface for Neighborhood_Selector so Hybrid_Solver can dynamically
request neighborhood configs during LNS iterations.

Key design decisions (Req 22.2, 22.9, 22.10, 4.11, 4.12, 4.13):
- Hybrid_Solver depends ONLY on SolverPolicyBundle, never on
  individual selectors directly.
- Neighborhood selection is exposed as a callable on the bundle so
  the solver can invoke it per-iteration at runtime.
- Every build records the unified Layer 2 version and call chain.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.case import CaseRecord, PreferenceProfile
from app.models.enums import IncidentSeverity, StrategyType
from app.models.impact import ImpactReport
from app.models.incident import Incident
from app.models.solver import CandidatePlan
from app.models.strategy import (
    NeighborhoodConfig,
    RepairPolicyConfig,
    RuleSelectionResult,
    SolverChainConfig,
    StrategyRecommendation,
)
from app.services.neighborhood_selector import (
    MODULE_VERSION as NS_VERSION,
    NeighborhoodSelector,
)
from app.services.repair_policy_advisor import (
    MODULE_VERSION as RPA_VERSION,
    RepairPolicyAdvisor,
)
from app.services.rule_selector import (
    MODULE_VERSION as RS_VERSION,
    RuleSelector,
)
from app.services.solver_portfolio import (
    MODULE_VERSION as SP_VERSION,
    SolverPortfolio,
)

logger = logging.getLogger(__name__)

# ── Orchestrator module version ─────────────────────────────────────
MODULE_VERSION: str = "1.0.0"


# ── Type alias for the runtime neighborhood callback ────────────────
NeighborhoodCallback = Callable[
    [
        CandidatePlan,   # current_solution
        list[str],       # affected_operation_ids
        int,             # stagnation_count
        float,           # remaining_budget_seconds
        StrategyRecommendation,  # strategy
        float,           # perturbation_constraint
    ],
    Awaitable[list[NeighborhoodConfig]],
]


class ModuleVersionInfo(ReOrchModel):
    """Version snapshot of each Layer 2 sub-module at build time."""

    rule_selector_version: str
    neighborhood_selector_version: str
    repair_policy_advisor_version: str
    solver_portfolio_version: str
    orchestrator_version: str
    built_at: datetime


class SolverPolicyBundle(ReOrchModel):
    """Unified strategy control object consumed by Hybrid_Solver.

    Bundles all Layer 2 outputs so the solver never depends on
    individual selectors directly (Req 22.2, 22.10).

    ``get_neighborhood_config`` is NOT serialised — it is a runtime
    callable that Hybrid_Solver invokes during each LNS iteration
    to dynamically obtain neighborhood configurations.
    """

    model_config = {"arbitrary_types_allowed": True}

    rules: list[RuleSelectionResult] = Field(default_factory=list)
    repair_config: RepairPolicyConfig
    solver_chain_config: SolverChainConfig
    strategy: StrategyRecommendation
    version_info: ModuleVersionInfo

    # Runtime callback — excluded from serialisation
    get_neighborhood_config: NeighborhoodCallback | None = Field(
        default=None, exclude=True,
    )


class SolverPolicyOrchestrator:
    """Layer 2 orchestrator: builds a unified SolverPolicyBundle.

    Coordinates:
    - RuleSelector.select_rules()          (Req 4.11)
    - RepairPolicyAdvisor.advise()         (Req 4.13)
    - SolverPortfolio.get_chain_config()   (Req 22.9)
    - NeighborhoodSelector (runtime ref)   (Req 4.12)

    Records unified version info and call chain (Req 22.2).
    """

    def __init__(
        self,
        rule_selector: RuleSelector | None = None,
        neighborhood_selector: NeighborhoodSelector | None = None,
        repair_policy_advisor: RepairPolicyAdvisor | None = None,
        solver_portfolio: SolverPortfolio | None = None,
    ) -> None:
        self._rule_selector = rule_selector or RuleSelector()
        self._neighborhood_selector = neighborhood_selector or NeighborhoodSelector()
        self._repair_policy_advisor = repair_policy_advisor or RepairPolicyAdvisor()
        self._solver_portfolio = solver_portfolio or SolverPortfolio()

    async def build_solver_policy(
        self,
        incident: Incident,
        impact_report: ImpactReport,
        strategy: StrategyRecommendation,
        preference_profile: PreferenceProfile,
        similar_cases: list[CaseRecord],
    ) -> SolverPolicyBundle:
        """Assemble a unified SolverPolicyBundle for Hybrid_Solver.

        Steps:
        1. Call RuleSelector.select_rules()
        2. Call RepairPolicyAdvisor.advise()
        3. Load SolverPortfolio.get_chain_config()
        4. Bind NeighborhoodSelector as a runtime callback
        5. Record version info and return bundle
        """
        # 1. Rule selection (Req 4.11)
        rules = await self._rule_selector.select_rules(
            incident=incident,
            impact_report=impact_report,
            strategy=strategy,
            preference_profile=preference_profile,
            similar_cases=similar_cases,
        )

        # 2. Repair policy (Req 4.13)
        repair_config = await self._repair_policy_advisor.advise(
            strategy=strategy,
            impact_report=impact_report,
            incident_severity=incident.severity,
        )

        # 3. Solver chain config (Req 22.9)
        solver_chain_config = self._solver_portfolio.get_chain_config(
            strategy_type=strategy.strategy_type,
        )

        # 4. Bind neighborhood selector as runtime callback (Req 4.12)
        ns = self._neighborhood_selector

        async def _neighborhood_callback(
            current_solution: CandidatePlan,
            affected_operation_ids: list[str],
            stagnation_count: int,
            remaining_budget_seconds: float,
            cb_strategy: StrategyRecommendation,
            perturbation_constraint: float,
        ) -> list[NeighborhoodConfig]:
            return await ns.select_neighborhood(
                current_solution=current_solution,
                affected_operation_ids=affected_operation_ids,
                stagnation_count=stagnation_count,
                remaining_budget_seconds=remaining_budget_seconds,
                strategy=cb_strategy,
                perturbation_constraint=perturbation_constraint,
            )

        # 5. Version info (Req 22.2)
        version_info = ModuleVersionInfo(
            rule_selector_version=RS_VERSION,
            neighborhood_selector_version=NS_VERSION,
            repair_policy_advisor_version=RPA_VERSION,
            solver_portfolio_version=SP_VERSION,
            orchestrator_version=MODULE_VERSION,
            built_at=datetime.now(tz=timezone.utc),
        )

        bundle = SolverPolicyBundle(
            rules=rules,
            repair_config=repair_config,
            solver_chain_config=solver_chain_config,
            strategy=strategy,
            version_info=version_info,
            get_neighborhood_config=_neighborhood_callback,
        )

        logger.info(
            "SolverPolicyBundle built: %d rule(s), repair_mode=%s, "
            "primary_solver=%s, versions={rs=%s, ns=%s, rpa=%s, sp=%s, orch=%s}",
            len(rules),
            repair_config.repair_mode,
            solver_chain_config.primary_solver,
            RS_VERSION,
            NS_VERSION,
            RPA_VERSION,
            SP_VERSION,
            MODULE_VERSION,
        )

        return bundle
