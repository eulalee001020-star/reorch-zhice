"""P0 Reality Harness for customer data onboarding.

This service composes the existing adapter mapping and data-readiness checks
into a stricter gate for historical replay and shadow mode.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence

from app.adapters.mapping_schema import (
    build_schedule_snapshot,
    map_incident,
    map_machine,
    map_operation,
    map_work_order,
)
from app.adapters.mapping_validator import (
    CanonicalDataset,
    MappingValidationIssue,
    MappingValidationReport,
    validate_customer_payloads,
)
from app.models.planning import DataReadinessReport, ReadinessIssue
from app.models.reality_harness import (
    P0RealityHarnessRequest,
    P0RealityHarnessResponse,
    RealityHarnessAuditStep,
    RealityHarnessPermission,
)
from app.models.schedule import ScheduleSnapshot
from app.services.data_readiness import DataReadinessService

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_P0_PACK_DIR = REPO_ROOT / "datasets" / "p0_reality_pack"


class P0RealityHarnessService:
    """Validate whether a customer data pack may enter replay or shadow mode."""

    def __init__(self, readiness: DataReadinessService | None = None) -> None:
        self._readiness = readiness or DataReadinessService()

    def assess(self, request: P0RealityHarnessRequest) -> P0RealityHarnessResponse:
        """Validate raw customer rows and derive a strict action ceiling."""
        mapping_report = validate_customer_payloads(
            raw_work_orders=request.raw_work_orders,
            raw_operations=request.raw_operations,
            raw_machines=request.raw_machines,
            raw_incidents=request.raw_incidents,
            profile=request.profile,
        )
        dataset = self._build_dataset_if_possible(request, mapping_report)
        snapshot: ScheduleSnapshot | None = None
        snapshot_readiness: DataReadinessReport | None = None
        if mapping_report.is_valid:
            snapshot = build_schedule_snapshot(
                workshop_id=request.workshop_id,
                work_orders=dataset.work_orders,
                operations=dataset.operations,
                machines=dataset.machines,
                captured_at=request.planning_start,
                source_system=request.source_system,
                raw_data={"incident_count": len(dataset.incidents)},
            )
            snapshot_readiness = self._readiness.assess_schedule_snapshot(snapshot)

        readiness_report = _merge_reports(mapping_report, snapshot_readiness)
        permission = _derive_permission(mapping_report, readiness_report)
        return P0RealityHarnessResponse(
            source_system=request.source_system,
            workshop_id=request.workshop_id,
            dataset=dataset,
            mapping_report=mapping_report,
            readiness_report=readiness_report,
            permission=permission,
            snapshot=snapshot if permission.level in {"replay_only", "shadow_ready"} else None,
            audit_steps=_audit_steps(mapping_report, readiness_report, permission, snapshot),
        )

    def load_sample_pack(
        self,
        pack_dir: Path = DEFAULT_P0_PACK_DIR,
        *,
        source_system: str = "p0_reality_pack_csv",
        workshop_id: str = "P0-REALITY-LINE",
    ) -> P0RealityHarnessRequest:
        """Load the checked-in P0 CSV pack into a harness request."""
        return P0RealityHarnessRequest(
            source_system=source_system,
            workshop_id=workshop_id,
            raw_work_orders=_read_csv(pack_dir / "erp_work_orders.csv"),
            raw_operations=_read_csv(pack_dir / "mes_operations.csv"),
            raw_machines=_read_csv(pack_dir / "aps_resources.csv"),
            raw_incidents=_read_csv(pack_dir / "mes_downtime_events.csv"),
        )

    def _build_dataset_if_possible(
        self,
        request: P0RealityHarnessRequest,
        mapping_report: MappingValidationReport,
    ) -> CanonicalDataset:
        if not mapping_report.is_valid:
            return CanonicalDataset()
        return CanonicalDataset(
            work_orders=[map_work_order(row, request.profile) for row in request.raw_work_orders],
            operations=[map_operation(row, request.profile) for row in request.raw_operations],
            machines=[map_machine(row, request.profile) for row in request.raw_machines],
            incidents=[map_incident(row, request.profile) for row in request.raw_incidents],
        )


def _merge_reports(
    mapping_report: MappingValidationReport,
    snapshot_readiness: DataReadinessReport | None,
) -> DataReadinessReport:
    mapping_issues = [_mapping_issue_to_readiness(issue) for issue in mapping_report.issues]
    blockers = [issue for issue in mapping_issues if issue.severity == "blocker"]
    warnings = [issue for issue in mapping_issues if issue.severity == "warning"]
    infos: list[ReadinessIssue] = []

    required_inputs = [
        "work_orders.work_order_id",
        "work_orders.due_time",
        "operations.operation_id",
        "operations.work_order_id",
        "operations.machine_id or eligible_machine_ids",
        "machines.machine_id",
        "machines.capabilities",
        "incidents.incident_id",
        "incidents.machine_id",
        "incidents.start_time",
        "timezone-aware timestamps",
        "machine_id crosswalk",
    ]
    if snapshot_readiness:
        blockers.extend(snapshot_readiness.blockers)
        warnings.extend(snapshot_readiness.warnings)
        infos.extend(snapshot_readiness.infos)
        required_inputs.extend(snapshot_readiness.required_inputs)

    blocker_codes = {issue.code for issue in blockers}
    warning_codes = {issue.code for issue in warnings}
    penalty = len(blocker_codes) * 0.25 + len(warning_codes) * 0.05
    readiness_score = max(0.0, round(1.0 - penalty, 4))
    recommendations = _recommendations(blockers, warnings, readiness_score)
    return DataReadinessReport(
        is_ready=not blockers,
        readiness_score=readiness_score,
        blockers=blockers,
        warnings=warnings,
        infos=infos,
        required_inputs=sorted(set(required_inputs)),
        recommendations=recommendations,
    )


def _mapping_issue_to_readiness(issue: MappingValidationIssue) -> ReadinessIssue:
    return ReadinessIssue(
        severity="blocker" if issue.severity == "error" else "warning",
        code=issue.code,
        message=issue.message,
        entity_type=issue.entity_type,
        entity_id=issue.entity_id,
    )


def _derive_permission(
    mapping_report: MappingValidationReport,
    readiness_report: DataReadinessReport,
) -> RealityHarnessPermission:
    warning_codes = {issue.code for issue in readiness_report.warnings}
    reasons: list[str] = []
    next_actions: list[str] = []

    if mapping_report.blocking_errors > 0 or readiness_report.blockers:
        reasons.append("Blocking mapping or snapshot-readiness errors exist.")
        next_actions.append("Fix required fields, reference integrity, and machine crosswalk before replay.")
        return RealityHarnessPermission(
            level="stop",
            reasons=reasons,
            required_next_actions=next_actions,
        )

    if readiness_report.readiness_score < 0.70:
        reasons.append("Readiness score is below 0.70.")
        next_actions.append("Run data repair and customer field confirmation; do not generate candidates.")
        return RealityHarnessPermission(
            level="repair_only",
            reasons=reasons,
            required_next_actions=next_actions,
        )

    if readiness_report.readiness_score < 0.85 or "timezone_missing" in warning_codes:
        if "timezone_missing" in warning_codes:
            reasons.append("Timestamp timezone coverage is incomplete.")
            next_actions.append("Ask customer to provide ISO8601 timestamps with timezone before shadow mode.")
        else:
            reasons.append("Readiness score supports replay, but not shadow mode.")
            next_actions.append("Resolve warnings that reduce explainability and ROI confidence.")
        return RealityHarnessPermission(
            level="replay_only",
            allow_candidate_generation=True,
            allow_historical_replay=True,
            reasons=reasons,
            required_next_actions=next_actions,
        )

    reasons.append("Readiness score >= 0.85 and no blocking errors.")
    next_actions.append("Proceed to historical replay or read-only shadow mode; keep writeback disabled.")
    return RealityHarnessPermission(
        level="shadow_ready",
        allow_candidate_generation=True,
        allow_historical_replay=True,
        allow_shadow_mode=True,
        allow_writeback=False,
        reasons=reasons,
        required_next_actions=next_actions,
    )


def _recommendations(
    blockers: Sequence[ReadinessIssue],
    warnings: Sequence[ReadinessIssue],
    readiness_score: float,
) -> list[str]:
    recommendations: list[str] = []
    if blockers:
        codes = sorted({issue.code for issue in blockers})
        recommendations.append(f"Resolve blockers before replay or solving: {', '.join(codes)}.")
    if warnings:
        recommendations.append("Warnings are allowed for replay only when evidence and customer context remain auditable.")
    if readiness_score >= 0.85 and not blockers:
        recommendations.append("Data may enter historical replay or shadow mode; production writeback remains disabled.")
    elif readiness_score >= 0.70 and not blockers:
        recommendations.append("Data may enter historical replay, but not shadow mode.")
    else:
        recommendations.append("Stay in data repair and mapping confirmation.")
    return recommendations


def _audit_steps(
    mapping_report: MappingValidationReport,
    readiness_report: DataReadinessReport,
    permission: RealityHarnessPermission,
    snapshot: ScheduleSnapshot | None,
) -> list[RealityHarnessAuditStep]:
    return [
        RealityHarnessAuditStep(
            step="canonical_mapping_validation",
            status="passed" if mapping_report.is_valid else "blocked",
            evidence={
                "blocking_errors": mapping_report.blocking_errors,
                "warnings": mapping_report.warnings,
                "total_records": mapping_report.total_records,
            },
        ),
        RealityHarnessAuditStep(
            step="snapshot_reconstruction",
            status="passed" if snapshot else "not_available",
            evidence={"snapshot_id": str(snapshot.snapshot_id) if snapshot else None},
        ),
        RealityHarnessAuditStep(
            step="permission_gate",
            status=permission.level,
            evidence={
                "readiness_score": readiness_report.readiness_score,
                "allow_historical_replay": permission.allow_historical_replay,
                "allow_shadow_mode": permission.allow_shadow_mode,
                "allow_writeback": permission.allow_writeback,
            },
        ),
    ]


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def validate_p0_sample_pack() -> P0RealityHarnessResponse:
    """Convenience entrypoint for smoke tests and docs."""
    service = P0RealityHarnessService()
    return service.assess(service.load_sample_pack())
