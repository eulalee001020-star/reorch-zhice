# Agent Observability and Cost

## Purpose

Industrial AI must explain why each model call happened, how much it cost, how
long it took, whether fallback occurred, and which guardrail constrained the
result. Cost telemetry is evidence, not permission to automate.

## Implemented Scope

| Item | Implementation |
| --- | --- |
| Observability models | `app/models/agent_observability.py` |
| Cost summary service | `app/services/agent_observability.py` |
| API endpoint | `POST /api/v1/planning/agent-observability/summarize` |
| Frontend API/types | `frontend/src/api/planning.ts`, `frontend/src/types/models.ts` |
| Tests | `app/tests/test_shadow_observability.py` |

## Metrics

| Metric | Meaning |
| --- | --- |
| `llm_steps` | Number of trace steps that used an LLM |
| `deterministic_steps` | Number of trace steps handled without an LLM |
| `fallback_steps` | Number of trace steps with fallback reasons |
| `estimated_cost_usd` | Token-cost estimate using supplied pricing profiles |
| `p95_latency_ms` | P95 latency across recorded steps |
| `guardrails` | Guardrails that constrained the workflow |

## Cost Controls

- Keep deterministic paths as default for solver, quality gate, confirmation,
  and writeback.
- Cache repeated explanation, routing, and rule-candidate prompts.
- Route low-risk tasks to smaller or local models when latency exceeds 3s.
- Trim prompt context and use source-ref retrieval instead of full-history
  prompts.
- Review fallback reasons before increasing model autonomy.

## Claim Boundary

This module estimates AI usage cost and latency from agent traces. Unknown
model pricing is treated as zero until a pricing profile is supplied, so cost
numbers are telemetry estimates, not accounting records.
