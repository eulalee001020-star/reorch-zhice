"""Explanation-related Pydantic models for the ReOrch system.

Defines RecommendationExplanation and SolverChainExplanation used
by the Explainability_Layer to provide structured, human-readable
reasoning for recommendations and solver chain decisions.
"""

from pydantic import Field

from app.models.base import ReOrchModel


class RecommendationExplanation(ReOrchModel):
    """Structured explanation for why a plan was recommended."""

    core_reasons: list[str] = Field(default_factory=list)  # ≤ 3
    key_advantages: list[str] = Field(default_factory=list)
    main_risks: list[str] = Field(default_factory=list)
    comparison_with_alternatives: list[dict] = Field(default_factory=list)
    summary: str  # ≤ 200 chars
    referenced_case_ids: list[str] = Field(default_factory=list)


class SolverChainExplanation(ReOrchModel):
    """Structured explanation for how a plan was generated."""

    algorithm_category: str
    applicable_scenario: str
    chain_reason: str
    optimization_objectives: list[str] = Field(default_factory=list)
    computation_time_seconds: float
    stages: list[str] = Field(default_factory=list)
    frozen_constraints: list[str] | None = None
