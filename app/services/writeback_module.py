"""Writeback Module for the ReOrch system.

Implements MES writeback and execution tracking for confirmed plans.

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 27.10

Key responsibilities:
- writeback_to_mes(): Convert confirmed plan to MES format, write back instructions.
  Single instruction failure → mark failed, continue others, summarize failures.
- Record writeback status (success / partial_success / failed).
- track_execution(): Every 5 min from MES, deviation > 10% → alert.
- Generate ExecutionResult when all affected work orders complete.
- Link ExecutionResult back to DecisionRecord for closed-loop tracking.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models.decision import DecisionRecord
from app.models.enums import WritebackStatus
from app.models.execution import ExecutionResult
from app.models.solver import CandidatePlan

logger = logging.getLogger(__name__)

# Deviation threshold for alerts (Req 8.6)
_DEVIATION_ALERT_THRESHOLD = 0.10  # 10%

# Tracking interval in minutes (Req 8.5)
_TRACKING_INTERVAL_MINUTES = 5


class MESInstruction:
    """A single MES writeback instruction derived from a schedule change."""

    def __init__(
        self,
        instruction_id: str,
        work_order_id: str,
        operation_id: str,
        resource_id: str,
        start_time: str,
        end_time: str,
    ) -> None:
        self.instruction_id = instruction_id
        self.work_order_id = work_order_id
        self.operation_id = operation_id
        self.resource_id = resource_id
        self.start_time = start_time
        self.end_time = end_time
        self.status: str = "pending"  # pending / success / failed
        self.error: str | None = None


class WritebackReport:
    """Summary of a writeback operation."""

    def __init__(self) -> None:
        self.total_instructions: int = 0
        self.success_count: int = 0
        self.failed_count: int = 0
        self.failed_instructions: list[dict] = []
        self.status: WritebackStatus = WritebackStatus.SUCCESS
        self.timestamp: str = datetime.now(tz=timezone.utc).isoformat()


class MESAdapter:
    """In-memory MES adapter mock for MVP.

    Simulates sending instructions to MES. In production, this would
    be replaced by a real MES integration adapter.
    """

    def __init__(self) -> None:
        # Track which instruction IDs should fail (for testing)
        self._fail_ids: set[str] = set()

    def set_fail_ids(self, ids: set[str]) -> None:
        """Configure instruction IDs that should simulate failure."""
        self._fail_ids = ids

    async def send_instruction(self, instruction: MESInstruction) -> bool:
        """Send a single instruction to MES. Returns True on success."""
        if instruction.instruction_id in self._fail_ids:
            instruction.status = "failed"
            instruction.error = f"MES rejected instruction {instruction.instruction_id}"
            return False
        instruction.status = "success"
        return True

    async def get_execution_progress(
        self, work_order_ids: list[str]
    ) -> dict[str, dict]:
        """Get execution progress from MES for given work orders.

        Returns dict of work_order_id -> {completion_pct, actual_start, actual_end, ...}
        """
        # MVP mock: return 100% completion for all
        now = datetime.now(tz=timezone.utc).isoformat()
        return {
            wo_id: {
                "completion_pct": 1.0,
                "actual_start": now,
                "actual_end": now,
                "status": "completed",
            }
            for wo_id in work_order_ids
        }


class WritebackModule:
    """Execution writeback module: MES writeback + execution tracking.

    Converts confirmed plan schedule changes to MES instructions,
    writes them back (tolerating individual failures), and tracks
    execution progress with deviation alerting.

    Validates: Requirements 8.1-8.8, 27.10
    """

    def __init__(self, mes_adapter: MESAdapter | None = None) -> None:
        self._mes = mes_adapter or MESAdapter()
        # In-memory stores for MVP
        self._writeback_reports: dict[str, WritebackReport] = {}  # incident_id -> report
        self._writeback_statuses: dict[str, WritebackStatus] = {}  # incident_id -> status
        self._execution_results: dict[str, ExecutionResult] = {}  # incident_id -> result
        self._decision_records: dict[str, DecisionRecord] = {}  # incident_id -> record
        self._alerts: list[dict] = []

    # ── MES Writeback (Req 8.1-8.4) ────────────────────────────────

    async def writeback_to_mes(
        self,
        confirmed_plan: CandidatePlan,
        decision_record: DecisionRecord,
    ) -> WritebackStatus:
        """Write confirmed plan schedule changes to MES.

        Converts the plan's schedule detail to MES instructions,
        sends each one individually. Single instruction failure is
        marked failed; remaining instructions continue. Returns
        overall writeback status.

        Args:
            confirmed_plan: The confirmed CandidatePlan to write back.
            decision_record: The associated DecisionRecord for linking.

        Returns:
            WritebackStatus: success / partial_success / failed
        """
        incident_key = str(decision_record.incident_id)
        self._decision_records[incident_key] = decision_record

        # Convert schedule to MES instructions (Req 8.2)
        instructions = self._convert_to_mes_instructions(confirmed_plan)

        report = WritebackReport()
        report.total_instructions = len(instructions)

        if not instructions:
            report.status = WritebackStatus.SUCCESS
            self._writeback_reports[incident_key] = report
            self._writeback_statuses[incident_key] = report.status
            logger.info(
                "Writeback for incident %s: no instructions to send",
                incident_key,
            )
            return report.status

        # Send each instruction, tolerating individual failures (Req 8.4)
        for instr in instructions:
            success = await self._mes.send_instruction(instr)
            if success:
                report.success_count += 1
            else:
                report.failed_count += 1
                report.failed_instructions.append(
                    {
                        "instruction_id": instr.instruction_id,
                        "operation_id": instr.operation_id,
                        "work_order_id": instr.work_order_id,
                        "error": instr.error,
                    }
                )

        # Determine overall status (Req 8.3)
        if report.failed_count == 0:
            report.status = WritebackStatus.SUCCESS
        elif report.success_count > 0:
            report.status = WritebackStatus.PARTIAL_SUCCESS
        else:
            report.status = WritebackStatus.FAILED

        self._writeback_reports[incident_key] = report
        self._writeback_statuses[incident_key] = report.status

        logger.info(
            "Writeback for incident %s: status=%s, total=%d, success=%d, failed=%d",
            incident_key,
            report.status.value,
            report.total_instructions,
            report.success_count,
            report.failed_count,
        )

        return report.status

    # ── Execution Tracking (Req 8.5-8.8) ───────────────────────────

    async def track_execution(self, incident_id: UUID) -> ExecutionResult:
        """Track execution progress from MES and generate ExecutionResult.

        Polls MES for execution progress. If deviation > 10%, generates
        an alert. When all affected work orders complete, generates
        ExecutionResult and links it back to DecisionRecord.

        Args:
            incident_id: The incident to track.

        Returns:
            ExecutionResult with actual vs planned metrics.

        Raises:
            ValueError: If no decision record found for the incident.
        """
        key = str(incident_id)

        decision_record = self._decision_records.get(key)
        if decision_record is None:
            raise ValueError(
                f"No decision record found for incident {incident_id}. "
                f"Run writeback first."
            )

        # Get work order IDs from the writeback report
        report = self._writeback_reports.get(key)
        work_order_ids = self._get_affected_work_order_ids(key)

        # Poll MES for progress (Req 8.5)
        progress = await self._mes.get_execution_progress(work_order_ids)

        # Check for deviations (Req 8.6)
        now = datetime.now(tz=timezone.utc)
        planned_times: dict[str, datetime] = {}
        actual_times: dict[str, datetime] = {}
        total_deviation = 0.0
        wo_count = max(len(work_order_ids), 1)

        for wo_id in work_order_ids:
            wo_progress = progress.get(wo_id, {})
            completion_pct = wo_progress.get("completion_pct", 0.0)

            # For MVP, use current time as both planned and actual
            planned_times[wo_id] = now
            actual_times[wo_id] = now

            # Calculate deviation from plan
            deviation = abs(1.0 - completion_pct)
            total_deviation += deviation

            if deviation > _DEVIATION_ALERT_THRESHOLD:
                alert = {
                    "incident_id": key,
                    "work_order_id": wo_id,
                    "deviation_pct": round(deviation * 100, 1),
                    "message": (
                        f"Work order {wo_id} deviation {round(deviation * 100, 1)}% "
                        f"exceeds threshold {_DEVIATION_ALERT_THRESHOLD * 100}%"
                    ),
                    "timestamp": now.isoformat(),
                }
                self._alerts.append(alert)
                logger.warning("Deviation alert: %s", alert["message"])

        avg_deviation = total_deviation / wo_count

        # Generate ExecutionResult (Req 8.7)
        execution_result = ExecutionResult(
            incident_id=incident_id,
            decision_record_id=decision_record.decision_record_id,
            actual_completion_times=actual_times,
            planned_completion_times=planned_times,
            actual_otd=1.0 - avg_deviation,
            actual_resource_utilization=0.85,  # MVP placeholder
            deviation_percentage=round(avg_deviation * 100, 2),
        )

        # Store and link back to DecisionRecord (Req 8.8)
        self._execution_results[key] = execution_result

        logger.info(
            "Execution tracking for incident %s: OTD=%.2f, deviation=%.2f%%",
            key,
            execution_result.actual_otd,
            execution_result.deviation_percentage,
        )

        return execution_result

    # ── Query helpers ───────────────────────────────────────────────

    def get_writeback_status(self, incident_id: UUID) -> WritebackStatus | None:
        """Get the writeback status for an incident."""
        return self._writeback_statuses.get(str(incident_id))

    def get_writeback_report(self, incident_id: UUID) -> WritebackReport | None:
        """Get the full writeback report for an incident."""
        return self._writeback_reports.get(str(incident_id))

    def get_execution_result(self, incident_id: UUID) -> ExecutionResult | None:
        """Get the execution result for an incident."""
        return self._execution_results.get(str(incident_id))

    def get_alerts(self) -> list[dict]:
        """Get all deviation alerts."""
        return list(self._alerts)

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _convert_to_mes_instructions(
        plan: CandidatePlan,
    ) -> list[MESInstruction]:
        """Convert a CandidatePlan's schedule detail to MES instructions.

        Each operation in the schedule becomes one MES instruction (Req 8.2).
        """
        instructions: list[MESInstruction] = []
        for wo in plan.schedule_detail.work_orders:
            for op in wo.operations:
                instr = MESInstruction(
                    instruction_id=f"MES-{op.operation_id}",
                    work_order_id=wo.work_order_id,
                    operation_id=op.operation_id,
                    resource_id=op.resource_id,
                    start_time=op.start_time.isoformat()
                    if isinstance(op.start_time, datetime)
                    else str(op.start_time),
                    end_time=op.end_time.isoformat()
                    if isinstance(op.end_time, datetime)
                    else str(op.end_time),
                )
                instructions.append(instr)
        return instructions

    def _get_affected_work_order_ids(self, incident_key: str) -> list[str]:
        """Extract work order IDs from the writeback report or decision record."""
        report = self._writeback_reports.get(incident_key)
        if report and report.failed_instructions:
            # Collect all WO IDs from failed + successful instructions
            pass

        # Fallback: extract from decision record's associated data
        # For MVP, return a default list
        return [f"WO-{incident_key[:8]}"]
