"""Reliability tests for the optional low-risk LLM client."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services.llm_agent_client import (
    LLMAgentClient,
    LLMProviderUnavailable,
    _CIRCUITS,
)


@pytest.fixture(autouse=True)
def _reset_llm_circuits():
    _CIRCUITS.clear()
    yield
    _CIRCUITS.clear()


@pytest.mark.asyncio
async def test_llm_client_retries_transient_network_failure(monkeypatch):
    calls = 0

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ConnectError(
                    "temporary network failure",
                    request=httpx.Request("POST", url),
                )
            return _SuccessfulResponse()

    monkeypatch.setattr("app.services.llm_agent_client.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(settings.llm, "enabled", True)
    monkeypatch.setattr(settings.llm, "api_key", "test-key")
    monkeypatch.setattr(settings.llm, "max_attempts", 2)
    monkeypatch.setattr(settings.llm, "retry_backoff_seconds", 0.0)

    result = await LLMAgentClient().complete_json(
        agent_name="test-agent",
        system_prompt="Return one field.",
        user_payload={"input": "test"},
    )

    assert result is not None
    assert result.data == {"status": "ok"}
    assert result.attempt_count == 2
    assert calls == 2


@pytest.mark.asyncio
async def test_llm_client_opens_circuit_after_repeated_failure(monkeypatch):
    calls = 0

    class FailingClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout(
                "provider timeout",
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(
        "app.services.llm_agent_client.httpx.AsyncClient", FailingClient
    )
    monkeypatch.setattr(settings.llm, "enabled", True)
    monkeypatch.setattr(settings.llm, "api_key", "test-key")
    monkeypatch.setattr(settings.llm, "max_attempts", 1)
    monkeypatch.setattr(settings.llm, "circuit_failure_threshold", 1)

    with pytest.raises(LLMProviderUnavailable, match="llm_request_failed"):
        await LLMAgentClient().complete_json(
            agent_name="test-agent",
            system_prompt="Return one field.",
            user_payload={"input": "test"},
        )
    with pytest.raises(LLMProviderUnavailable, match="llm_circuit_open"):
        await LLMAgentClient().complete_json(
            agent_name="test-agent",
            system_prompt="Return one field.",
            user_payload={"input": "test"},
        )

    assert calls == 1


class _SuccessfulResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": '{"status":"ok"}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }
