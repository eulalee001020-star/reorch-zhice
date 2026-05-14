"""Impact Analysis Engine — identifies affected work orders, operations,
resources, and delivery risks when an anomaly occurs.

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from app.models.enums import DeliveryRiskLevel, IncidentSeverity
from app.models.impact import (
    AffectedOperation,
    AffectedWorkOrder,
    ImpactReport,
)
from app.models.incident import Incident
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder

logger = logging.getLogger(__name__)

# Severity upgrade map: only upgrade, never downgrade (Req 2.5 / design)
_SEVERITY_UPGRADE: dict[str, str] = {
    IncidentSeverity.P4_LOW.value: IncidentSeverity.P3_MEDIUM.value,
    IncidentSeverity.P3_MEDIUM.value: IncidentSeverity.P2_HIGH.value,
    IncidentSeverity.P2_HIGH.value: IncidentSeverity.P1_CRITICAL.value,
    IncidentSeverity.P1_CRITICAL.value: IncidentSeverity.P1_CRITICAL.value,
}


class ImpactAnalysisEngine:
    """Impact Analysis Engine.

    ``analysis_reference_time = schedule_snapshot.captured_at`` ensures
    reproducible time-based calculations.

    MAY upgrade incident severity when Breach-level delivery risk is found.
    """

    async def analyze(
        self,
        incident: Incident,
        snapshot: ScheduleSnapshot | None,
    ) -> ImpactReport:
        """Perform impact analysis and return a structured ImpactReport.

        If *snapshot* is ``None`` or contains no work orders the report is
        produced in **degraded mode** (Req 2.7).
        """
        incident_id = self._to_uuid(incident.incident_id)

        # --- Degraded mode check (Req 2.7) ---
        if snapshot is None or not snapshot.work_orders:
            reason = (
                "ScheduleSnapshot is not available"
                if snapshot is None
                else "ScheduleSnapshot contains no work orders"
            )
            logger.warning(
                "Impact analysis for incident %s running in degraded mode: %s",
                incident_id,
                reason,
            )
            return ImpactReport(
                incident_id=incident_id,
                schedule_snapshot_id=self._to_uuid(
                    snapshot.snapshot_id if snapshot else UUID(int=0)
                ),
                analysis_reference_time=datetime.min,
                is_degraded_mode=True,
                degraded_reason=reason,
            )

        snapshot_id = self._to_uuid(snapshot.snapshot_id)
        analysis_reference_time: datetime = snapshot.captured_at

        resource_id = incident.resource_id

        # --- Step 1: Identify directly affected operations (Req 2.3) ---
        direct_ops: list[AffectedOperation] = []
        op_index: dict[str, Operation] = {}

        for wo in snapshot.work_orders:
            for op in wo.operations:
                op_index[op.operation_id] = op
                if op.resource_id == resource_id:
                    remaining = self._remaining_minutes(op, analysis_reference_time)
                    direct_ops.append(
                        AffectedOperation(
                            operation_id=op.operation_id,
                            work_order_id=op.work_order_id,
                            resource_id=op.resource_id,
                            is_direct=True,
                            estimated_delay_minutes=remaining,
                        )
                    )

        # --- Step 2: Downstream propagation (Req 2.4) ---
        downstream_ops = self._propagate_downstream(direct_ops, snapshot, op_index)

        all_affected_ops = direct_ops + downstream_ops

        # --- Step 3: Build affected work orders with delivery risk (Req 2.5) ---
        wo_map: dict[str, WorkOrder] = {
            wo.work_order_id: wo for wo in snapshot.work_orders
        }
        ops_by_wo: dict[str, list[AffectedOperation]] = {}
        for aop in all_affected_ops:
            ops_by_wo.setdefault(aop.work_order_id, []).append(aop)

        affected_work_orders: list[AffectedWorkOrder] = []
        for wo_id, aops in ops_by_wo.items():
            wo = wo_map.get(wo_id)
            if wo is None:
                continue
            risk = self._calculate_delivery_risk(wo, aops, analysis_reference_time)
            total_delay = sum(a.estimated_delay_minutes for a in aops)
            buffer = self._buffer_minutes(wo, analysis_reference_time, total_delay)
            affected_work_orders.append(
                AffectedWorkOrder(
                    work_order_id=wo.work_order_id,
                    product_name=wo.product_name,
                    due_date=wo.due_date,
                    delivery_risk_level=risk,
                    remaining_buffer_minutes=buffer,
                    affected_operations=aops,
                )
            )

        # --- Step 4: Aggregate metrics (Req 2.6) ---
        affected_resource_ids = sorted(
            {aop.resource_id for aop in all_affected_ops}
        )
        risk_dist: dict[DeliveryRiskLevel, int] = {
            DeliveryRiskLevel.SAFE: 0,
            DeliveryRiskLevel.WARNING: 0,
            DeliveryRiskLevel.BREACH: 0,
        }
        for awo in affected_work_orders:
            risk_dist[awo.delivery_risk_level] = (
                risk_dist.get(awo.delivery_risk_level, 0) + 1
            )

        estimated_total_delay = sum(
            a.estimated_delay_minutes for a in all_affected_ops
        )

        report = ImpactReport(
            incident_id=incident_id,
            schedule_snapshot_id=snapshot_id,
            analysis_reference_time=analysis_reference_time,
            affected_work_orders=affected_work_orders,
            affected_operations=all_affected_ops,
            affected_resource_ids=affected_resource_ids,
            delivery_risk_distribution=risk_dist,
            estimated_total_delay_minutes=estimated_total_delay,
        )

        # --- Step 5: Maybe upgrade severity (Req 2.5 / design) ---
        report = self._maybe_upgrade_severity(incident, report)

        return report

    # ── downstream propagation ──────────────────────────────────────

    def _propagate_downstream(
        self,
        direct_ops: list[AffectedOperation],
        snapshot: ScheduleSnapshot,
        op_index: dict[str, Operation],
    ) -> list[AffectedOperation]:
        """Follow successor_ids from directly affected operations to identify
        indirectly affected downstream operations (Req 2.4)."""
        visited: set[str] = {aop.operation_id for aop in direct_ops}
        queue: list[str] = []

        # Seed the queue with successors of direct ops
        for aop in direct_ops:
            src_op = op_index.get(aop.operation_id)
            if src_op:
                for sid in src_op.successor_ids:
                    if sid not in visited:
                        queue.append(sid)

        downstream: list[AffectedOperation] = []

        while queue:
            op_id = queue.pop(0)
            if op_id in visited:
                continue
            visited.add(op_id)

            op = op_index.get(op_id)
            if op is None:
                continue

            # Estimate delay as the remaining processing time of this op
            delay = self._remaining_minutes(op, snapshot.captured_at)
            downstream.append(
                AffectedOperation(
                    operation_id=op.operation_id,
                    work_order_id=op.work_order_id,
                    resource_id=op.resource_id,
                    is_direct=False,
                    estimated_delay_minutes=delay,
                )
            )

            # Continue propagation to further successors
            for sid in op.successor_ids:
                if sid not in visited:
                    queue.append(sid)

        return downstream

    # ── delivery risk calculation ───────────────────────────────────

    def _calculate_delivery_risk(
        self,
        work_order: WorkOrder,
        affected_ops: list[AffectedOperation],
        reference_time: datetime,
    ) -> DeliveryRiskLevel:
        """Calculate delivery risk for a work order (Req 2.5).

        Buffer = due_date - (reference_time + remaining_processing_time)
        - Safe:    buffer > estimated_delay
        - Warning: 0 < buffer <= estimated_delay
        - Breach:  buffer <= 0 or estimated_delay > buffer
        """
        estimated_delay = sum(a.estimated_delay_minutes for a in affected_ops)
        remaining_processing = self._total_remaining_processing(
            work_order, reference_time
        )
        buffer = self._buffer_minutes(work_order, reference_time, remaining_processing)

        if buffer <= 0:
            return DeliveryRiskLevel.BREACH
        if buffer > estimated_delay:
            return DeliveryRiskLevel.SAFE
        # 0 < buffer <= estimated_delay → Warning
        return DeliveryRiskLevel.WARNING

    # ── severity upgrade ────────────────────────────────────────────

    def _maybe_upgrade_severity(
        self,
        incident: Incident,
        report: ImpactReport,
    ) -> ImpactReport:
        """Upgrade incident severity if any work order has Breach risk.

        Only upgrades, never downgrades:
        P4 → P3, P3 → P2, P2 → P1, P1 stays P1.
        """
        has_breach = report.delivery_risk_distribution.get(
            DeliveryRiskLevel.BREACH, 0
        ) > 0

        if not has_breach:
            return report

        current_severity = (
            incident.severity
            if isinstance(incident.severity, str)
            else incident.severity.value
        )
        upgraded = _SEVERITY_UPGRADE.get(current_severity, current_severity)

        if upgraded != current_severity:
            report.severity_upgraded = True
            report.upgraded_severity = IncidentSeverity(upgraded)
            logger.info(
                "Severity upgraded for incident %s: %s → %s",
                report.incident_id,
                current_severity,
                upgraded,
            )
        else:
            # P1 stays P1 — still flag that breach was detected
            report.severity_upgraded = False

        return report

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _remaining_minutes(op: Operation, reference_time: datetime) -> float:
        """Remaining processing minutes for an operation relative to reference_time."""
        end = op.end_time
        start = op.start_time

        # If the operation hasn't started yet relative to reference_time,
        # the full duration is the delay estimate.
        if reference_time <= start:
            return (end - start).total_seconds() / 60.0

        # If already past end_time, no remaining time
        if reference_time >= end:
            return 0.0

        # Partially completed
        return (end - reference_time).total_seconds() / 60.0

    @staticmethod
    def _total_remaining_processing(
        work_order: WorkOrder, reference_time: datetime
    ) -> float:
        """Sum of remaining processing minutes for all operations in a work order."""
        total = 0.0
        for op in work_order.operations:
            if reference_time < op.end_time:
                start = max(reference_time, op.start_time)
                total += (op.end_time - start).total_seconds() / 60.0
        return total

    @staticmethod
    def _buffer_minutes(
        work_order: WorkOrder,
        reference_time: datetime,
        remaining_processing: float,
    ) -> float:
        """Buffer = due_date - (reference_time + remaining_processing_time) in minutes."""
        due_delta = (work_order.due_date - reference_time).total_seconds() / 60.0
        return due_delta - remaining_processing

    @staticmethod
    def _to_uuid(value: UUID | str) -> UUID:
        """Ensure a value is a UUID instance."""
        if isinstance(value, UUID):
            return value
        return UUID(str(value))
