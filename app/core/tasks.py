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
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

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
    from app.models.enums import IncidentStatus
    from app.services.persistence import (
        fetch_decision_record_by_incident,
        fetch_incident,
        persist_audit_log,
    )

    incident = await fetch_incident(UUID(incident_id))
    decision = await fetch_decision_record_by_incident(UUID(incident_id))
    if (
        incident is not None
        and incident.status == IncidentStatus.PENDING_CONFIRMATION.value
        and decision is None
    ):
        await persist_audit_log(
            action="confirmation_timeout_reminder",
            entity_type="incident",
            entity_id=incident_id,
            result="pending",
            details={"message": "Incident has not been confirmed within SLA."},
        )
        logger.warning("confirmation_timeout_reminder: incident %s still pending", incident_id)
        return
    logger.info("confirmation_timeout_reminder: incident %s already handled", incident_id)


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
    from app.models.enums import WritebackStatus
    from app.services.persistence import (
        fetch_decision_record_by_id,
        fetch_writeback_job_by_incident,
        persist_writeback_job,
    )
    from app.services.writeback_module import MESAdapter, MESInstruction

    record = await fetch_decision_record_by_id(UUID(decision_record_id))
    if record is None:
        logger.warning("writeback_retry: decision %s not found", decision_record_id)
        return

    job = await fetch_writeback_job_by_incident(record.incident_id)
    if job is None:
        logger.warning("writeback_retry: no writeback job for decision %s", decision_record_id)
        return

    payload = job.get("request_payload") or {}
    instructions = payload.get("instructions", [])
    if instruction_ids:
        instructions = [
            item for item in instructions if item.get("instruction_id") in set(instruction_ids)
        ]

    adapter = MESAdapter()
    success_count = 0
    failed: list[dict[str, Any]] = []
    for item in instructions:
        instruction = MESInstruction(
            instruction_id=item["instruction_id"],
            work_order_id=item["work_order_id"],
            operation_id=item["operation_id"],
            resource_id=item["resource_id"],
            start_time=item["start_time"],
            end_time=item["end_time"],
        )
        ok = await adapter.send_instruction(instruction)
        if ok:
            success_count += 1
        else:
            failed.append({**item, "error": instruction.error})

    status = (
        WritebackStatus.SUCCESS
        if not failed
        else WritebackStatus.PARTIAL_SUCCESS
        if success_count > 0
        else WritebackStatus.FAILED
    )
    retry_count = int(job.get("retry_count") or 0) + 1
    await persist_writeback_job(
        incident_id=record.incident_id,
        decision_record_id=record.decision_record_id,
        confirmed_plan_id=record.confirmed_plan_id,
        target_system=job.get("target_system") or "MES",
        status=status,
        request_payload=payload,
        response_payload={
            "total_instructions": len(instructions),
            "success_count": success_count,
            "failed_count": len(failed),
            "failed_instructions": failed,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        },
        error_message="; ".join(str(item.get("error")) for item in failed) if failed else None,
        retry_count=retry_count,
        next_retry_at=datetime.now(tz=timezone.utc) + timedelta(minutes=2**retry_count)
        if failed and retry_count < 3
        else None,
    )
    logger.info(
        "writeback_retry: decision=%s status=%s success=%d failed=%d",
        decision_record_id,
        status.value,
        success_count,
        len(failed),
    )


# ── 3. Execution progress polling (cron — every 5 minutes) ──────────
# Requirement 8.5: 每 5 分钟从 MES 获取实际执行进度
# Registered as an ARQ cron job in scheduler.get_worker_settings().


async def execution_progress_poll(ctx: dict[str, Any]) -> None:
    """Poll MES for execution progress of all active confirmed plans.

    Stub — full implementation in task 9.2.
    """
    from app.services.persistence import list_retryable_writeback_jobs

    retryable = await list_retryable_writeback_jobs()
    for job in retryable:
        decision_record_id = job.get("decision_record_id")
        if decision_record_id:
            await writeback_retry(ctx, decision_record_id)
    logger.info(
        "execution_progress_poll: processed %d retryable writeback job(s)",
        len(retryable),
    )


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
    from app.services.persistence import record_entity_version

    logger.info("dead_letter_compensation: recording message from topic=%s", topic)
    await record_entity_version(
        entity_type="dead_letter_message",
        entity_id=f"{topic}:{datetime.now(tz=timezone.utc).timestamp()}",
        data={"topic": topic, "payload": payload or {}, "status": "recorded"},
    )
