"""Tests for ARQ background task infrastructure.

Validates: Requirements 7.8, 8.5, 8.6, 18.5
"""

from __future__ import annotations

import pytest

from app.core.scheduler import (
    RetryConfig,
    RetryPolicy,
    TaskDefinition,
    TaskRegistry,
    get_redis_settings,
    get_worker_settings,
)


# ── RetryConfig ─────────────────────────────────────────────────────


class TestRetryConfig:
    def test_none_policy_returns_zero_delay(self) -> None:
        rc = RetryConfig(policy=RetryPolicy.NONE)
        assert rc.delay_for_attempt(0).total_seconds() == 0
        assert rc.delay_for_attempt(5).total_seconds() == 0

    def test_linear_policy_constant_delay(self) -> None:
        rc = RetryConfig(policy=RetryPolicy.LINEAR, max_retries=3, base_delay_seconds=10.0)
        assert rc.delay_for_attempt(0).total_seconds() == 10.0
        assert rc.delay_for_attempt(1).total_seconds() == 10.0
        assert rc.delay_for_attempt(2).total_seconds() == 10.0

    def test_linear_policy_stops_at_max(self) -> None:
        rc = RetryConfig(policy=RetryPolicy.LINEAR, max_retries=2, base_delay_seconds=5.0)
        assert rc.delay_for_attempt(2).total_seconds() == 0

    def test_exponential_policy_doubles(self) -> None:
        rc = RetryConfig(policy=RetryPolicy.EXPONENTIAL, max_retries=4, base_delay_seconds=5.0)
        assert rc.delay_for_attempt(0).total_seconds() == 5.0
        assert rc.delay_for_attempt(1).total_seconds() == 10.0
        assert rc.delay_for_attempt(2).total_seconds() == 20.0
        assert rc.delay_for_attempt(3).total_seconds() == 40.0

    def test_exponential_policy_stops_at_max(self) -> None:
        rc = RetryConfig(policy=RetryPolicy.EXPONENTIAL, max_retries=2, base_delay_seconds=5.0)
        assert rc.delay_for_attempt(2).total_seconds() == 0


# ── TaskRegistry ────────────────────────────────────────────────────


async def _dummy_task(ctx: dict, x: int) -> int:
    return x


class TestTaskRegistry:
    def test_register_and_get(self) -> None:
        reg = TaskRegistry()
        reg.register("my_task", _dummy_task)
        td = reg.get("my_task")
        assert td.name == "my_task"
        assert td.coroutine is _dummy_task
        assert td.retry_config.policy == RetryPolicy.NONE

    def test_register_with_retry_config(self) -> None:
        reg = TaskRegistry()
        rc = RetryConfig(policy=RetryPolicy.EXPONENTIAL, max_retries=3, base_delay_seconds=2.0)
        reg.register("retryable", _dummy_task, retry_config=rc, timeout_seconds=60)
        td = reg.get("retryable")
        assert td.retry_config.policy == RetryPolicy.EXPONENTIAL
        assert td.retry_config.max_retries == 3
        assert td.timeout_seconds == 60

    def test_duplicate_registration_raises(self) -> None:
        reg = TaskRegistry()
        reg.register("dup", _dummy_task)
        with pytest.raises(ValueError, match="already registered"):
            reg.register("dup", _dummy_task)

    def test_get_unknown_raises(self) -> None:
        reg = TaskRegistry()
        with pytest.raises(KeyError, match="not registered"):
            reg.get("nope")

    def test_all_tasks(self) -> None:
        reg = TaskRegistry()
        reg.register("a", _dummy_task)
        reg.register("b", _dummy_task)
        assert set(reg.all_tasks().keys()) == {"a", "b"}

    def test_functions_property(self) -> None:
        reg = TaskRegistry()
        reg.register("f1", _dummy_task)
        assert len(reg.functions) == 1
        assert reg.functions[0] is _dummy_task


# ── Worker settings ─────────────────────────────────────────────────


class TestWorkerSettings:
    def test_get_redis_settings_uses_config(self) -> None:
        rs = get_redis_settings()
        assert rs.host == "localhost"
        assert rs.port == 6379

    def test_get_worker_settings_structure(self) -> None:
        ws = get_worker_settings()
        assert "functions" in ws
        assert "cron_jobs" in ws
        assert "on_startup" in ws
        assert "on_shutdown" in ws
        assert "redis_settings" in ws
        # 3 regular functions
        func_names = [f.__name__ for f in ws["functions"]]
        assert "confirmation_timeout_reminder" in func_names
        assert "writeback_retry" in func_names
        assert "dead_letter_compensation" in func_names
        # 1 cron job (execution_progress_poll)
        assert len(ws["cron_jobs"]) == 1


# ── Task stubs importable ──────────────────────────────────────────


class TestTaskStubs:
    def test_all_task_stubs_importable(self) -> None:
        from app.core.tasks import (
            confirmation_timeout_reminder,
            dead_letter_compensation,
            execution_progress_poll,
            writeback_retry,
        )

        assert callable(confirmation_timeout_reminder)
        assert callable(writeback_retry)
        assert callable(execution_progress_poll)
        assert callable(dead_letter_compensation)
