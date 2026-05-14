"""Evaluation-related Pydantic models for the ReOrch system.

Defines KPIVector, ComparisonMatrixRow, and ComparisonMatrix used
by the Evaluation_Center for multi-objective scoring and ranking.
"""

from pydantic import Field

from app.models.base import ReOrchModel


class KPIVector(ReOrchModel):
    """Multi-dimensional KPI scores for a single CandidatePlan."""

    delayed_order_count: int
    max_delay_minutes: float
    spi: float  # Schedule Perturbation Index
    resource_utilization_delta: float
    changeover_count_delta: int
    critical_order_otd_impact: float
    normalized_score: float  # 0-1


class ComparisonMatrixRow(ReOrchModel):
    """One row in the comparison matrix, representing a single plan."""

    plan_id: str
    kpi_vector: KPIVector
    delta_vs_baseline: dict[str, float] = Field(default_factory=dict)
    is_score_close: bool  # True when score gap < 5%


class ComparisonMatrix(ReOrchModel):
    """Structured comparison matrix for all candidate plans."""

    rows: list[ComparisonMatrixRow] = Field(default_factory=list)
    normalization_method: str
    score_unit_descriptions: dict[str, str] = Field(default_factory=dict)
    baseline_snapshot_id: str
