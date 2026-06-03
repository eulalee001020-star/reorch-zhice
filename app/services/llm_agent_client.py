"""OpenAI-compatible JSON client for low-risk ReOrch Agent steps.

The client is intentionally optional. If no LLM key is configured, Agent steps
must keep using deterministic parsers and tools. High-risk scheduling,
quality-gate, recommendation, confirmation, and writeback steps should not use
this client.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


@dataclass(frozen=True)
class LLMJsonResult:
    """Structured JSON response and telemetry from an LLM Agent call."""

    data: dict[str, Any]
    provider: str
    model: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMAgentClient:
    """Minimal OpenAI-compatible JSON completion client."""

    def is_enabled(self) -> bool:
        return bool(settings.llm.enabled and settings.llm.api_key)

    async def complete_json(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> LLMJsonResult | None:
        if not self.is_enabled():
            return None

        started = time.perf_counter()
        url = settings.llm.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.llm.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.llm.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        system_prompt
                        + "\nReturn only a compact JSON object. Do not include markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            "metadata": {"agent_name": agent_name},
        }

        async with httpx.AsyncClient(timeout=settings.llm.request_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()

        content = body["choices"][0]["message"]["content"]
        data = json.loads(content)
        usage = body.get("usage") or {}
        return LLMJsonResult(
            data=data,
            provider=settings.llm.provider,
            model=settings.llm.model,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
