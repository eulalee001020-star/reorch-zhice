"""Background task definitions for the ARQ worker.

Validates: Requirements 7.8, 8.5, 8.6, 18.5

Each coroutine follows the ARQ convention: first positional arg is ``ctx``
(a dict injected by the worker).  Actual business logic will be filled in
by later tasks (9.1 for confirmation timeout, 9.2 for writeback retry and
execution tracking).  These are intentionally minimal stubs that log and
return so the infrastructure can be validated end-to-end.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── 1. Incident 15-minute confirmation timeout reminder ─────────────
# Requirement 7.8: 15 分钟未确认提醒
# Enqueued with _defer_by=timedelta(minutes=15) when an Incident enters
# ``pending_confirmation`` status.  The worker fires this job; if the
# Incident is still unconfirmed it sends a notification.


async def confirmation_timeout_reminder(ctx: dict[str, Any], incident_id: str) -> None:
    """Check whether *incident_id* has been confirmed; notify if not.

    Stub — full implementation in task 9.1.
    """
    logger.info(
        "confirmation_timeout_reminder: checking incident %s",
        incident_id,
    )
    # TODO(task-9.1): query Incident status; if still pending_confirmation,
    # send notification to Planner + direct supervisor.


# ── 2. MES writeback failure retry ──────────────────────────────────
# Requirement 8.4 / 18.5: 回写失败重试（最多 3 次，指数退避）
# Enqueued when a writeback instruction fails.  ARQ's built-in retry
# mechanism handles back-off; this coroutine re-attempts the write.


async def writeback_retry(
    ctx: dict[str, Any],
    decision_record_id: str,
    instruction_ids: list[str] | None = None,
) -> None:
    """Retry failed MES writeback instructions for *decision_record_id*.

    Stub — full implementation in task 9.2.
    """
    logger.info(
        "writeback_retry: retrying writeback for decision %s (instructions=%s)",
        decision_record_id,
        instruction_ids,
    )
    # TODO(task-9.2): load failed instructions, convert to MES format,
    # attempt writeback, update status.  On repeated failure, emit alert.


# ── 3. Execution progress polling (cron — every 5 minutes) ──────────
# Requirement 8.5: 每 5 分钟从 MES 获取实际执行进度
# Registered as an ARQ cron job in scheduler.get_worker_settings().


async def execution_progress_poll(ctx: dict[str, Any]) -> None:
    """Poll MES for execution progress of all active confirmed plans.

    Stub — full implementation in task 9.2.
    """
    logger.info("execution_progress_poll: polling MES for active plans")
    # TODO(task-9.2): query active Incidents in ``executing`` status,
    # fetch progress from MES adapter, compare with confirmed plan,
    # generate deviation alert if > 10%.


# ── 4. Dead-letter queue compensation ───────────────────────────────
# Requirement 18.5: 死信队列补偿任务
# Picks up messages that could not be processed by normal consumers
# (e.g. Kafka consumer failures) and re-processes or alerts.


async def dead_letter_compensation(
    ctx: dict[str, Any],
    topic: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Re-process a message that ended up in the dead-letter queue.

    Stub — full implementation in a later task.
    """
    logger.info(
        "dead_letter_compensation: reprocessing message from topic=%s",
        topic,
    )
    # TODO: deserialise payload, route to the appropriate handler,
    # record outcome.  After max retries, emit failure alert.
