"""MES Writeback Adapter — schedule change instruction format conversion,
retry mechanism, and local queue caching.

Validates: Requirements 8.2, 18.3, 18.5

Key capabilities:
- Convert schedule change instructions to different MES data formats
- Retry mechanism: max 3 times with exponential backoff
- Cache to local queue when MES unavailable, auto-retry on recovery
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Retry config
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0  # exponential: 1s, 2s, 4s


class MESFormat(str, Enum):
    """Supported MES data formats."""
    STANDARD = "standard"
    SIEMENS = "siemens"
    ROCKWELL = "rockwell"
    CUSTOM_JSON = "custom_json"


@dataclass
class MESInstruction:
    """A single schedule change instruction for MES."""
    instruction_id: str
    work_order_id: str
    operation_id: str
    resource_id: str
    start_time: str
    end_time: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MESWritebackResult:
    """Result of a single MES writeback attempt."""
    instruction_id: str
    success: bool
    error: str | None = None
    attempts: int = 0
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(tz=timezone.utc).isoformat()


class MESAdapter:
    """Adapter for writing schedule changes back to MES systems.

    Features:
    - Format conversion for different MES systems
    - Retry with exponential backoff (max 3 attempts)
    - Local queue caching when MES is unavailable
    - Auto-retry queued instructions on recovery
    """

    def __init__(self, mes_format: MESFormat = MESFormat.STANDARD) -> None:
        self._format = mes_format
        self._available = True
        self._local_queue: deque[MESInstruction] = deque()
        self._results: dict[str, MESWritebackResult] = {}
        # For testing: IDs that should simulate failure
        self._fail_ids: set[str] = set()

    @property
    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    def set_fail_ids(self, ids: set[str]) -> None:
        self._fail_ids = ids

    @property
    def queue_size(self) -> int:
        return len(self._local_queue)

    # ── Format conversion (Req 8.2) ────────────────────────────────

    def convert_instruction(self, instruction: MESInstruction) -> dict[str, Any]:
        """Convert instruction to target MES format."""
        if self._format == MESFormat.SIEMENS:
            return self._to_siemens_format(instruction)
        elif self._format == MESFormat.ROCKWELL:
            return self._to_rockwell_format(instruction)
        elif self._format == MESFormat.CUSTOM_JSON:
            return self._to_custom_json(instruction)
        return self._to_standard_format(instruction)

    @staticmethod
    def _to_standard_format(instr: MESInstruction) -> dict[str, Any]:
        return {
            "id": instr.instruction_id,
            "workOrder": instr.work_order_id,
            "operation": instr.operation_id,
            "resource": instr.resource_id,
            "startTime": instr.start_time,
            "endTime": instr.end_time,
        }

    @staticmethod
    def _to_siemens_format(instr: MESInstruction) -> dict[str, Any]:
        return {
            "OrderNumber": instr.work_order_id,
            "OperationNumber": instr.operation_id,
            "WorkCenter": instr.resource_id,
            "PlannedStart": instr.start_time,
            "PlannedEnd": instr.end_time,
            "InstructionRef": instr.instruction_id,
        }

    @staticmethod
    def _to_rockwell_format(instr: MESInstruction) -> dict[str, Any]:
        return {
            "wo_id": instr.work_order_id,
            "op_id": instr.operation_id,
            "equipment_id": instr.resource_id,
            "scheduled_start": instr.start_time,
            "scheduled_end": instr.end_time,
            "ref": instr.instruction_id,
        }

    @staticmethod
    def _to_custom_json(instr: MESInstruction) -> dict[str, Any]:
        return {
            "instruction": instr.instruction_id,
            "wo": instr.work_order_id,
            "op": instr.operation_id,
            "res": instr.resource_id,
            "start": instr.start_time,
            "end": instr.end_time,
            "meta": instr.metadata,
        }

    # ── Send with retry (Req 18.3, 18.5) ──────────────────────────

    async def send_instruction(self, instruction: MESInstruction) -> MESWritebackResult:
        """Send a single instruction to MES with retry and queue fallback.

        - Up to MAX_RETRIES attempts with exponential backoff
        - If MES unavailable, cache to local queue for later retry
        """
        if not self._available:
            self._local_queue.append(instruction)
            result = MESWritebackResult(
                instruction_id=instruction.instruction_id,
                success=False,
                error="MES unavailable — queued for retry",
                attempts=0,
            )
            self._results[instruction.instruction_id] = result
            logger.warning("MES unavailable, queued instruction %s", instruction.instruction_id)
            return result

        return await self._send_with_retry(instruction)

    async def _send_with_retry(self, instruction: MESInstruction) -> MESWritebackResult:
        """Attempt to send with exponential backoff retry."""
        last_error: str | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                success = await self._do_send(instruction)
                if success:
                    result = MESWritebackResult(
                        instruction_id=instruction.instruction_id,
                        success=True,
                        attempts=attempt,
                    )
                    self._results[instruction.instruction_id] = result
                    return result
                last_error = f"MES rejected instruction {instruction.instruction_id}"
            except Exception as exc:
                last_error = str(exc)

            if attempt < MAX_RETRIES:
                backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.info(
                    "Retry %d/%d for instruction %s in %.1fs",
                    attempt, MAX_RETRIES, instruction.instruction_id, backoff,
                )
                await asyncio.sleep(backoff)

        # All retries exhausted
        result = MESWritebackResult(
            instruction_id=instruction.instruction_id,
            success=False,
            error=last_error,
            attempts=MAX_RETRIES,
        )
        self._results[instruction.instruction_id] = result
        logger.error(
            "All %d retries exhausted for instruction %s: %s",
            MAX_RETRIES, instruction.instruction_id, last_error,
        )
        return result

    async def _do_send(self, instruction: MESInstruction) -> bool:
        """Simulate sending to MES. Override in production."""
        if instruction.instruction_id in self._fail_ids:
            return False
        return True

    # ── Queue recovery (Req 18.5) ──────────────────────────────────

    async def retry_queued(self) -> list[MESWritebackResult]:
        """Retry all queued instructions. Call when MES recovers."""
        results: list[MESWritebackResult] = []
        retry_items = list(self._local_queue)
        self._local_queue.clear()

        for instruction in retry_items:
            result = await self._send_with_retry(instruction)
            results.append(result)
            if not result.success:
                # Re-queue if still failing
                self._local_queue.append(instruction)

        logger.info(
            "Queue retry complete: %d processed, %d re-queued",
            len(results), len(self._local_queue),
        )
        return results

    # ── Health check ───────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """Check MES connectivity status."""
        return {
            "system": "MES",
            "available": self._available,
            "queue_size": len(self._local_queue),
            "format": self._format.value,
        }
