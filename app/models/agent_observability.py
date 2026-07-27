"""Agent trace observability and cost models."""

from __future__ import annotations

from pydantic import Field

from app.models.agent import AgentTraceStep
from app.models.base import ReOrchModel


class AgentCostProfile(ReOrchModel):
    """Token pricing profile used for cost telemetry."""

    provider: str
    model_name: str
    input_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)
    output_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)


class AgentTraceObserveRequest(ReOrchModel):
    """Summarize one agent workflow trace."""

    run_id: str
    workflow_name: str
    trace: list[AgentTraceStep] = Field(default_factory=list)
    cost_profiles: list[AgentCostProfile] = Field(default_factory=list)
    cache_hit_count: int = Field(default=0, ge=0)


class AgentTraceCostSummary(ReOrchModel):
    """Cost, latency, and guardrail summary for a trace."""

    run_id: str
    workflow_name: str
    total_steps: int
    llm_steps: int
    deterministic_steps: int
    fallback_steps: int
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float
    average_latency_ms: float
    p95_latency_ms: float
    cache_hit_count: int
    guardrails: list[str] = Field(default_factory=list)
    fallback_reasons: list[str] = Field(default_factory=list)
    cost_reduction_recommendations: list[str] = Field(default_factory=list)
    decision_boundary: str = "Telemetry only; does not authorize production decisions."
