"""Case library Pydantic models for the ReOrch system.

Defines CaseRecord, CaseTemplate, and PreferenceProfile used by
the Case_Library (Enterprise Asset Layer) for decision case
archival, template management, and planner preference learning.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.execution import ExecutionResult
from app.models.solver import SolverChain


class CaseRecord(ReOrchModel):
    """A single archived decision case with full traceability.

    Records the complete chain: incident features → strategy →
    rule selection → neighborhood selection → repair policy →
    execution result.  ``embedding_vector`` stores the pgvector
    embedding for similarity retrieval.
    """

    case_id: UUID
    incident_features: dict
    impact_scope: dict
    strategy_type: str
    confirmed_plan_summary: str
    execution_result: ExecutionResult | None = None
    is_override: bool
    override_reason: str | None = None
    rule_selection: str
    neighborhood_selection: str
    repair_policy: str
    solver_chain: SolverChain
    created_at: datetime
    embedding_vector: list[float] | None = None  # pgvector


class CaseTemplate(ReOrchModel):
    """Reusable template distilled from historical decision cases."""

    template_id: UUID
    template_name: str
    applicable_incident_types: list[str] = Field(default_factory=list)
    recommended_strategy: str
    key_parameter_thresholds: dict = Field(default_factory=dict)
    status: str  # "draft" | "published"
    reference_count: int = 0
    adoption_rate: float = 0.0
    created_by: str
    created_at: datetime


class PreferenceProfile(ReOrchModel):
    """Learned preference profile for a single Planner.

    Tracks strategy preferences, micro-adjustment patterns, and
    override history to inform future recommendations.
    """

    planner_id: str
    strategy_preferences: dict[str, float] = Field(default_factory=dict)
    adjustment_patterns: list[dict] = Field(default_factory=list)
    override_history: list[dict] = Field(default_factory=list)
    updated_at: datetime
