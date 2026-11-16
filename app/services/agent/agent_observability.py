"""Agent trace observability and cost estimation."""

from __future__ import annotations

from app.models.agent import AgentTraceStep
from app.models.agent_observability import (
    AgentCostProfile,
    AgentTraceCostSummary,
    AgentTraceObserveRequest,
)


class AgentObservabilityService:
    """Summarize LLM usage without changing workflow permissions."""

    def summarize(self, request: AgentTraceObserveRequest) -> AgentTraceCostSummary:
        profiles = {
            (profile.provider, profile.model_name): profile
            for profile in request.cost_profiles
        }
        llm_steps = [step for step in request.trace if step.llm_used]
        deterministic_steps = [step for step in request.trace if not step.llm_used]
        fallback_steps = [step for step in request.trace if step.fallback_reason]
        total_input_tokens = sum(step.input_tokens or 0 for step in request.trace)
        total_output_tokens = sum(step.output_tokens or 0 for step in request.trace)
        estimated_cost = sum(_step_cost(step, profiles) for step in llm_steps)
        latencies = [step.latency_ms for step in request.trace if step.latency_ms is not None]
        guardrails = sorted({step.guardrail for step in request.trace if step.guardrail})
        fallback_reasons = sorted(
            {step.fallback_reason for step in fallback_steps if step.fallback_reason}
        )

        return AgentTraceCostSummary(
            run_id=request.run_id,
            workflow_name=request.workflow_name,
            total_steps=len(request.trace),
            llm_steps=len(llm_steps),
            deterministic_steps=len(deterministic_steps),
            fallback_steps=len(fallback_steps),
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            estimated_cost_usd=round(estimated_cost, 6),
            average_latency_ms=_average(latencies),
            p95_latency_ms=_percentile(latencies, 0.95),
            cache_hit_count=request.cache_hit_count,
            guardrails=guardrails,
            fallback_reasons=fallback_reasons,
            cost_reduction_recommendations=_recommendations(
                request.trace,
                len(llm_steps),
                len(fallback_steps),
                request.cache_hit_count,
            ),
        )


def _step_cost(
    step: AgentTraceStep,
    profiles: dict[tuple[str | None, str | None], AgentCostProfile],
) -> float:
    profile = profiles.get((step.llm_provider, step.model_name))
    if not profile:
        return 0.0
    input_cost = ((step.input_tokens or 0) / 1_000_000) * profile.input_cost_per_million_tokens
    output_cost = ((step.output_tokens or 0) / 1_000_000) * profile.output_cost_per_million_tokens
    return input_cost + output_cost


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return round(ordered[index], 4)


def _recommendations(
    trace: list[AgentTraceStep],
    llm_count: int,
    fallback_count: int,
    cache_hit_count: int,
) -> list[str]:
    recommendations: list[str] = []
    if llm_count == 0:
        recommendations.append("Keep deterministic path as default; no LLM cost observed.")
    if llm_count > 0 and cache_hit_count == 0:
        recommendations.append("Add cache for repeated explanations, routing, and rule-candidate prompts.")
    if fallback_count:
        recommendations.append("Review fallback reasons before increasing model autonomy.")
    high_latency = [step for step in trace if (step.latency_ms or 0) > 3000]
    if high_latency:
        recommendations.append("Route low-risk tasks to smaller or local models when latency exceeds 3s.")
    high_token = [step for step in trace if (step.input_tokens or 0) + (step.output_tokens or 0) > 4000]
    if high_token:
        recommendations.append("Trim prompt context and use source-ref retrieval instead of full-history prompts.")
    if not recommendations:
        recommendations.append("Current trace is within configured cost and latency hygiene.")
    return recommendations
