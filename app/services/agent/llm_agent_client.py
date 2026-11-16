"""OpenAI-compatible JSON client for low-risk ReOrch Agent steps.

The client is intentionally optional. If no LLM key is configured, Agent steps
must keep using deterministic parsers and tools. High-risk scheduling,
quality-gate, recommendation, confirmation, and writeback steps should not use
this client.
"""

from __future__ import annotations

import asyncio
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
    attempt_count: int = 1


@dataclass
class _CircuitState:
    failure_count: int = 0
    opened_at: float | None = None


class LLMProviderUnavailable(RuntimeError):
    """Raised when the optional LLM provider is unavailable or circuit-open."""


_CIRCUITS: dict[str, _CircuitState] = {}


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
        circuit_key = f"{url}|{settings.llm.model}"
        circuit = _CIRCUITS.setdefault(circuit_key, _CircuitState())
        if _circuit_is_open(circuit):
            raise LLMProviderUnavailable("llm_circuit_open")

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
        payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if payload_bytes > settings.llm.max_payload_bytes:
            raise ValueError(
                f"llm_payload_too_large:{payload_bytes}>{settings.llm.max_payload_bytes}"
            )

        last_error: Exception | None = None
        for attempt in range(1, settings.llm.max_attempts + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=settings.llm.request_timeout_seconds
                ) as client:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    body = response.json()

                content = body["choices"][0]["message"]["content"]
                data = json.loads(content)
                if not isinstance(data, dict):
                    raise ValueError("llm_response_must_be_json_object")
                usage = body.get("usage") or {}
                _record_success(circuit)
                return LLMJsonResult(
                    data=data,
                    provider=settings.llm.provider,
                    model=settings.llm.model,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"),
                    attempt_count=attempt,
                )
            except Exception as exc:
                last_error = exc
                _record_failure(circuit)
                if attempt >= settings.llm.max_attempts or not _is_retryable(exc):
                    break
                await asyncio.sleep(
                    settings.llm.retry_backoff_seconds * (2 ** (attempt - 1))
                )

        raise LLMProviderUnavailable(
            f"llm_request_failed:{type(last_error).__name__ if last_error else 'unknown'}"
        ) from last_error


def _circuit_is_open(circuit: _CircuitState) -> bool:
    if circuit.opened_at is None:
        return False
    if time.monotonic() - circuit.opened_at >= settings.llm.circuit_reset_seconds:
        circuit.failure_count = 0
        circuit.opened_at = None
        return False
    return True


def _record_success(circuit: _CircuitState) -> None:
    circuit.failure_count = 0
    circuit.opened_at = None


def _record_failure(circuit: _CircuitState) -> None:
    circuit.failure_count += 1
    if circuit.failure_count >= settings.llm.circuit_failure_threshold:
        circuit.opened_at = time.monotonic()


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False
