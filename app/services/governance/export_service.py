"""Export Service for the ReOrch system.

Implements PDF and Excel export for decision records.

Validates: Requirements 27.7

Key responsibilities:
- export_pdf(): Generate PDF with gantt snapshot, recommendation reason, key KPI
- export_excel(): Generate Excel with full ScheduleDetail
- For MVP, generates simple file content (not actual PDF/Excel rendering)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from app.models.decision import DecisionRecord
from app.models.solver import CandidatePlan

logger = logging.getLogger(__name__)


class ExportResult:
    """Result of an export operation."""

    def __init__(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        decision_record_id: str,
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self.content = content
        self.decision_record_id = decision_record_id
        self.created_at = datetime.now(tz=timezone.utc).isoformat()


class ExportService:
    """Export service for decision records.

    For MVP, generates simple text-based content representing
    PDF and Excel exports. In production, this would use libraries
    like reportlab (PDF) and openpyxl (Excel).

    Validates: Requirements 27.7
    """

    def __init__(self) -> None:
        # In-memory stores for MVP
        self._decision_records: dict[str, DecisionRecord] = {}
        self._confirmed_plans: dict[str, CandidatePlan] = {}

    def register_decision(
        self,
        decision_record: DecisionRecord,
        confirmed_plan: CandidatePlan | None = None,
    ) -> None:
        """Register a decision record and its confirmed plan for export."""
        key = str(decision_record.decision_record_id)
        self._decision_records[key] = decision_record
        if confirmed_plan:
            self._confirmed_plans[key] = confirmed_plan

    def export_pdf(self, decision_record_id: UUID) -> ExportResult:
        """Export decision record as PDF.

        MVP: Generates a text-based representation containing:
        - Gantt snapshot summary
        - Recommendation reason
        - Key KPI metrics

        Args:
            decision_record_id: The decision record to export.

        Returns:
            ExportResult with PDF content.

        Raises:
            ValueError: If decision record not found.
        """
        key = str(decision_record_id)
        record = self._decision_records.get(key)
        if record is None:
            raise ValueError(
                f"Decision record {decision_record_id} not found."
            )

        plan = self._confirmed_plans.get(key)

        # Build PDF content (MVP: text representation)
        lines = [
            "=" * 60,
            "ReOrch Decision Report (PDF)",
            "=" * 60,
            "",
            f"Decision Record ID: {record.decision_record_id}",
            f"Incident ID: {record.incident_id}",
            f"Strategy: {record.strategy_type}",
            f"Confirmed Plan: {record.confirmed_plan_id}",
            f"Confirmed By: {record.confirmed_by}",
            f"Confirmed At: {record.confirmed_at.isoformat()}",
            f"Is Override: {record.is_override}",
            f"Is Manual Adjusted: {record.is_manual_adjusted}",
            "",
            "--- Impact Summary ---",
            record.impact_report_summary,
            "",
            "--- Solver Chain ---",
            f"Rule Selector: v{record.rule_selector_version}",
            f"Neighborhood Selector: v{record.neighborhood_selector_version}",
            f"Repair Policy Advisor: v{record.repair_policy_advisor_version}",
            "",
        ]

        if record.is_override and record.override_reason:
            lines.extend([
                "--- Override ---",
                f"Reason: {record.override_reason}",
                f"Recommended Plan: {record.recommended_plan_id}",
                "",
            ])

        if plan:
            lines.extend([
                "--- Gantt Snapshot ---",
                f"Gantt Version: {plan.gantt_version}",
                f"Feasibility: {plan.feasibility_status}",
                f"Work Orders: {len(plan.schedule_detail.work_orders)}",
                "",
                "--- Key KPI ---",
                f"Solve Time: {plan.solver_metadata.solve_time_seconds}s",
                f"Iterations: {plan.solver_metadata.iteration_count}",
                "",
            ])

        lines.append("=" * 60)

        content = "\n".join(lines).encode("utf-8")
        filename = f"decision_{key[:8]}.pdf"

        logger.info("PDF export generated for decision %s", key)

        return ExportResult(
            filename=filename,
            content_type="application/pdf",
            content=content,
            decision_record_id=key,
        )

    def export_excel(self, decision_record_id: UUID) -> ExportResult:
        """Export decision record as Excel.

        MVP: Generates a JSON-based representation of the full
        ScheduleDetail. In production, this would use openpyxl.

        Args:
            decision_record_id: The decision record to export.

        Returns:
            ExportResult with Excel content.

        Raises:
            ValueError: If decision record not found.
        """
        key = str(decision_record_id)
        record = self._decision_records.get(key)
        if record is None:
            raise ValueError(
                f"Decision record {decision_record_id} not found."
            )

        plan = self._confirmed_plans.get(key)

        # Build Excel content (MVP: JSON representation of ScheduleDetail)
        export_data: dict = {
            "decision_record_id": str(record.decision_record_id),
            "incident_id": str(record.incident_id),
            "strategy_type": record.strategy_type,
            "confirmed_plan_id": str(record.confirmed_plan_id),
            "confirmed_by": record.confirmed_by,
            "confirmed_at": record.confirmed_at.isoformat(),
        }

        if plan:
            export_data["schedule_detail"] = plan.schedule_detail.model_dump(
                mode="json"
            )
            export_data["solver_chain"] = plan.solver_chain.model_dump(
                mode="json"
            )

        content = json.dumps(export_data, indent=2, default=str).encode("utf-8")
        filename = f"decision_{key[:8]}.xlsx"

        logger.info("Excel export generated for decision %s", key)

        return ExportResult(
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=content,
            decision_record_id=key,
        )
