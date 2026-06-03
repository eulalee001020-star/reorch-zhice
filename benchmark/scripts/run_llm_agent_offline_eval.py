"""Offline evaluation for low-risk LLM Agent steps.

Run from repo root:
    python benchmark/scripts/run_llm_agent_offline_eval.py

With ``LLM_ENABLED=true`` and a configured OpenAI-compatible endpoint, the same
cases call the real LLM Agent path. Without those settings, the script measures
the deterministic fallback baseline and reports ``llm_call_count = 0``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.models.agent import (
    FeedbackStructuringRequest,
    IncidentUnderstandingRequest,
    RuleCandidateRequest,
)
from app.services.agent_workflow import FeedbackAgent, IncidentAgent, RuleCandidateAgent


INCIDENT_CASES = [
    {
        "text": "CNC-02 停了，预计三小时，急单有延期风险。",
        "expected_type": "machine_down",
        "expected_resource": "CNC-02",
    },
    {
        "text": "M-03 failure after 10:30, repair needs 90 minutes.",
        "expected_type": "machine_down",
        "expected_resource": "M-03",
    },
    {
        "text": "物料 AL-7075 还没到，WO-9002 不能开工。",
        "expected_type": "material_shortage",
        "expected_resource": None,
    },
    {
        "text": "客户加急插单，优先级最高。",
        "expected_type": "urgent_order_insert",
        "expected_resource": None,
    },
]

RULE_CASES = [
    {
        "text": "M4 operator unavailable after 16:00, urgent jobs should avoid it",
        "expected_type": "calendar",
    },
    {
        "text": "物料没齐套前不要释放 repaired plan",
        "expected_type": "material",
    },
    {
        "text": "QA hold 没放行前不要移动 OP-7",
        "expected_type": "quality",
    },
]

FEEDBACK_CASES = [
    {
        "text": "M4 operator unavailable after 16:00",
        "expected_reason": "operator_preference",
    },
    {
        "text": "这个方案物料没齐套，现场不会采纳",
        "expected_reason": "material_constraint",
    },
    {
        "text": "计划员觉得全局重排扰动太大",
        "expected_reason": "manual_business_judgment",
    },
]


async def main() -> None:
    incident_agent = IncidentAgent()
    rule_agent = RuleCandidateAgent()
    feedback_agent = FeedbackAgent()

    incident_correct = 0
    resource_correct = 0
    rule_correct = 0
    feedback_correct = 0
    trace_steps = []

    for case in INCIDENT_CASES:
        output = await incident_agent.understand_text(
            IncidentUnderstandingRequest(text=case["text"], workshop_id="WS-EVAL")
        )
        incident_correct += int(output.incident_type == case["expected_type"])
        resource_correct += int(output.resource_id == case["expected_resource"])
        trace_steps.extend(output.trace)

    for case in RULE_CASES:
        output = await rule_agent.compile_rules(
            RuleCandidateRequest(rule_text=case["text"], source="offline_eval")
        )
        actual = output.candidates[0].constraint_type if output.candidates else None
        rule_correct += int(actual == case["expected_type"])
        trace_steps.extend(output.trace)

    for case in FEEDBACK_CASES:
        output = await feedback_agent.structure_override(
            FeedbackStructuringRequest(override_text=case["text"], planner_id="planner-eval")
        )
        feedback_correct += int(output.override_reason == case["expected_reason"])
        trace_steps.extend(output.trace)

    llm_steps = [step for step in trace_steps if step.llm_used]
    result: dict[str, Any] = {
        "dataset": {
            "incident_cases": len(INCIDENT_CASES),
            "rule_cases": len(RULE_CASES),
            "feedback_cases": len(FEEDBACK_CASES),
        },
        "metrics": {
            "incident_type_accuracy": round(incident_correct / len(INCIDENT_CASES), 4),
            "incident_resource_accuracy": round(resource_correct / len(INCIDENT_CASES), 4),
            "rule_candidate_type_accuracy": round(rule_correct / len(RULE_CASES), 4),
            "feedback_reason_accuracy": round(feedback_correct / len(FEEDBACK_CASES), 4),
            "llm_call_count": len(llm_steps),
            "input_tokens": sum(step.input_tokens or 0 for step in llm_steps),
            "output_tokens": sum(step.output_tokens or 0 for step in llm_steps),
            "avg_llm_latency_ms": (
                round(sum(step.latency_ms or 0 for step in llm_steps) / len(llm_steps), 2)
                if llm_steps
                else 0
            ),
        },
        "boundary": (
            "No scheduling, quality-gate, confirmation, or writeback step is evaluated "
            "as an LLM task."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
