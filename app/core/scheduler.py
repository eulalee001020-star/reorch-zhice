"""ARQ-based background task scheduler with task registry, retry policies, and observability.

Validates: Requirements 7.8, 8.5, 8.6, 18.5

Uses Redis (already in our stack) as the queue backend via ARQ — lightweight,
async-native, and a natural fit for the FastAPI / asyncio runtime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Any, Callable, Coroutine

from arq import cron as arq_cron
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Retry policies ──────────────────────────────────────────────────


class RetryPolicy(str, Enum):
    """Pre-defined retry strategies for background tasks."""

    NONE = "none"
    LINEAR = "linear"  # fixed interval
    EXPONENTIAL = "exponential"  # exponential back-off


@dataclass(frozen=True)
class RetryConfig:
    """Retry configuration attached to a registered task."""

    policy: RetryPolicy = RetryPolicy.NONE
    max_retries: int = 0
    base_delay_seconds: float = 5.0

    def delay_for_attempt(self, attempt: int) -> timedelta:
        """Return the delay before the *next* retry given the current attempt number."""
        if self.policy == RetryPolicy.NONE or attempt >= self.max_retries:
            return timedelta(seconds=0)
        if self.policy == RetryPolicy.LINEAR:
            return timedelta(seconds=self.base_delay_seconds)
        # EXPONENTIAL: 5s, 10s, 20s, …
        return timedelta(seconds=self.base_delay_seconds * (2 ** attempt))


# ── Task registration ───────────────────────────────────────────────


@dataclass
class TaskDefinition:
    """Metadata for a registered background task."""

    name: str
    coroutine: Callable[..., Coroutine[Any, Any, Any]]
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    timeout_seconds: int = 300  # per-job timeout


class TaskRegistry:
    """Central registry for all background tasks.

    Tasks are registered at import-time and later fed into the ARQ worker
    configuration via :func:`get_worker_settings`.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskDefinition] = {}

    # ── public API ──────────────────────────────────────────────

    def register(
        self,
        name: str,
        coroutine: Callable[..., Coroutine[Any, Any, Any]],
        retry_config: RetryConfig | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        if name in self._tasks:
            raise ValueError(f"Task '{name}' is already registered")
        self._tasks[name] = TaskDefinition(
            name=name,
            coroutine=coroutine,
            retry_config=retry_config or RetryConfig(),
            timeout_seconds=timeout_seconds,
        )
        logger.info("Registered background task: %s", name)

    def get(self, name: str) -> TaskDefinition:
        try:
            return self._tasks[name]
        except KeyError:
            raise KeyError(f"Task '{name}' is not registered") from None

    def all_tasks(self) -> dict[str, TaskDefinition]:
        return dict(self._tasks)

    @property
    def functions(self) -> list[Callable[..., Coroutine[Any, Any, Any]]]:
        """Return the raw coroutines for ARQ ``functions`` config."""
        return [td.coroutine for td in self._tasks.values()]


# Module-level singleton
task_registry = TaskRegistry()


# ── ARQ worker helpers ──────────────────────────────────────────────


def get_redis_settings() -> RedisSettings:
    """Build ARQ ``RedisSettings`` from application config."""
    return RedisSettings(
        host=settings.redis.host,
        port=settings.redis.port,
        database=settings.redis.db,
        password=settings.redis.password,
    )


async def on_startup(ctx: dict[str, Any]) -> None:
    """ARQ worker startup hook — initialise shared resources."""
    logger.info("ARQ worker starting up")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """ARQ worker shutdown hook — clean up shared resources."""
    logger.info("ARQ worker shutting down")


async def on_job_start(ctx: dict[str, Any]) -> None:
    """Called before each job executes — observability entry point."""
    job_name = ctx.get("job_name", "unknown")
    job_id = ctx.get("job_id", "unknown")
    logger.info("Job started: %s (id=%s)", job_name, job_id)


async def on_job_end(ctx: dict[str, Any]) -> None:
    """Called after each job completes — observability exit point."""
    job_name = ctx.get("job_name", "unknown")
    job_id = ctx.get("job_id", "unknown")
    success = ctx.get("result") is not None
    logger.info("Job ended: %s (id=%s, success=%s)", job_name, job_id, success)


# ── Cron schedule definitions ───────────────────────────────────────
# Actual task coroutines live in app/core/tasks.py; we import them lazily
# inside ``get_worker_settings`` to avoid circular imports.


def get_worker_settings() -> dict[str, Any]:
    """Return the full ARQ ``WorkerSettings``-compatible dict.

    Used by the worker entrypoint after resolving lazy task imports.
    """
    # Lazy import so tasks module can freely import from the rest of the app.
    from app.core.tasks import (  # noqa: WPS433
        confirmation_timeout_reminder,
        dead_letter_compensation,
        execution_progress_poll,
        writeback_retry,
    )

    return {
        "functions": [
            confirmation_timeout_reminder,
            writeback_retry,
            dead_letter_compensation,
        ],
        "cron_jobs": [
            arq_cron(
                execution_progress_poll,
                minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            ),
        ],
        "on_startup": on_startup,
        "on_shutdown": on_shutdown,
        "on_job_start": on_job_start,
        "on_job_end": on_job_end,
        "redis_settings": get_redis_settings(),
        "max_jobs": 10,
        "job_timeout": 300,
        "retry_jobs": True,
        "allow_abort_jobs": True,
    }


# ── Enqueue helper ──────────────────────────────────────────────────


async def enqueue_task(
    redis: ArqRedis,
    task_name: str,
    *args: Any,
    _defer_by: timedelta | None = None,
    **kwargs: Any,
) -> str | None:
    """Enqueue a task by name with optional deferral.

    Returns the ARQ job id, or ``None`` if the task could not be enqueued.
    """
    try:
        job = await redis.enqueue_job(
            task_name,
            *args,
            _defer_by=_defer_by,
            **kwargs,
        )
        if job is None:
            logger.warning("Task %s was not enqueued (duplicate or queue full)", task_name)
            return None
        logger.info("Enqueued task %s → job %s", task_name, job.job_id)
        return job.job_id
    except Exception:
        logger.exception("Failed to enqueue task %s", task_name)
        return None
