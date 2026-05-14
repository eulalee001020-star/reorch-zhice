"""Strategy-related Pydantic models for the ReOrch system.

Defines StrategyRecommendation, RuleSelectionResult, NeighborhoodConfig,
RepairPolicyConfig, and SolverChainConfig used across the Solver Policy
Layer (Rule_Selector, Neighborhood_Selector, Repair_Policy_Advisor,
Solver_Portfolio).
"""

from uuid import UUID

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.enums import (
    NeighborhoodType,
    RepairMode,
    RuleApplicableStage,
    RuleCategory,
    StrategyType,
)


class StrategyRecommendation(ReOrchModel):
    """Output of Strategy_Selector: high-level strategy with confidence."""

    strategy_type: StrategyType
    confidence: float  # 0-1
    key_factors: list[str] = Field(default_factory=list)
    historical_case_ids: list[UUID] = Field(default_factory=list)
    alternative_strategy: StrategyType | None = None  # provided when confidence < 0.5
    reasoning: str


class RuleSelectionResult(ReOrchModel):
    """Output of Rule_Selector: selected scheduling rule with metadata."""

    rule_name: str
    rule_category: RuleCategory
    applicable_stage: RuleApplicableStage
    confidence: float  # 0-1
    reasoning: str
    alternative_rule: str | None = None  # provided when confidence < 0.5


class NeighborhoodConfig(ReOrchModel):
    """Output of Neighborhood_Selector: LNS neighborhood configuration."""

    neighborhood_type: NeighborhoodType
    target_operation_ids: list[str] = Field(default_factory=list)
    intensity: float  # 0-1
    estimated_impact_scope: int
    reasoning: str


class RepairPolicyConfig(ReOrchModel):
    """Output of Repair_Policy_Advisor: repair strategy configuration."""

    repair_mode: RepairMode
    frozen_operation_ids: list[str] = Field(default_factory=list)
    allowed_perturbation_scope: list[str] = Field(default_factory=list)
    search_time_budget_seconds: float
    candidate_count_target: int
    fallback_condition: str
    fallback_mode: str


class SolverChainConfig(ReOrchModel):
    """Output of Solver_Portfolio: solver chain configuration."""

    primary_solver: str
    fallback_solver: str
    fallback_rule: str
    degradation_trigger: str
    max_timeout_seconds: float
