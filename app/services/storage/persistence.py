"""Best-effort database persistence helpers.

The current codebase still uses in-memory API stores for fast local MVP tests.
These helpers add a production migration path: when PostgreSQL is reachable,
API handlers can write/read durable records; when it is not reachable, callers
can keep the existing in-memory behavior.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select

from app.core.database import async_session_factory
from app.models.db.audit_logs import AuditLog as AuditLogORM
from app.models.db.candidate_plans import CandidatePlan as CandidatePlanORM
from app.models.db.decision_records import DecisionRecord as DecisionRecordORM
from app.models.db.entity_versions import EntityVersion as EntityVersionORM
from app.models.db.execution_results import ExecutionResult as ExecutionResultORM
from app.models.db.impact_reports import ImpactReport as ImpactReportORM
from app.models.db.incidents import Incident as IncidentORM
from app.models.db.schedule_fact import PlanRecommendation as PlanRecommendationORM
from app.models.db.schedule_fact import WritebackJob as WritebackJobORM
from app.models.db.schedule_snapshots import ScheduleSnapshot as ScheduleSnapshotORM
from app.models.decision import DecisionRecord
from app.models.case import CaseRecord, CaseTemplate, PreferenceProfile
from app.models.enums import WritebackStatus
from app.models.execution import ExecutionResult
from app.models.impact import ImpactReport
from app.models.incident import Incident
from app.models.recommendation import PlanSelectionOutput
from app.models.schedule import ScheduleSnapshot
from app.models.solver import CandidatePlan
from app.models.strategy import StrategyRecommendation

logger = logging.getLogger(__name__)


def _json(model_or_dict: Any) -> dict[str, Any]:
    if hasattr(model_or_dict, "model_dump"):
        return model_or_dict.model_dump(mode="json")
    return dict(model_or_dict)


async def persist_audit_log(
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    user_id: str | None = None,
    role: str | None = None,
    result: str = "success",
    request_id: str | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    """Persist an audit log row. Returns False if the DB is unavailable."""
    try:
        async with async_session_factory() as session:
            session.add(
                AuditLogORM(
                    user_id=user_id,
                    role=role,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    result=result,
                    request_id=request_id,
                    ip_address=ip_address,
                    details=details or {},
                    timestamp=datetime.now(tz=timezone.utc),
                )
            )
            await session.commit()
        return True
    except Exception as exc:
        logger.debug("Audit persistence skipped: %s", exc)
        return False


async def record_entity_version(
    *,
    entity_type: str,
    entity_id: str,
    data: dict[str, Any],
    changed_by: str | None = None,
    version_number: int | None = None,
) -> bool:
    """Persist a versioned entity snapshot when the DB is available."""
    try:
        async with async_session_factory() as session:
            if version_number is None:
                result = await session.execute(
                    select(func.max(EntityVersionORM.version_number)).where(
                        EntityVersionORM.entity_type == entity_type,
                        EntityVersionORM.entity_id == entity_id,
                    )
                )
                version_number = (result.scalar_one_or_none() or 0) + 1
            session.add(
                EntityVersionORM(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    version_number=version_number,
                    data=data,
                    changed_by=changed_by,
                )
            )
            await session.commit()
        return True
    except Exception as exc:
        logger.debug("Entity version persistence skipped: %s", exc)
        return False


async def fetch_latest_entity_version(
    *,
    entity_type: str,
    entity_id: str,
) -> dict[str, Any] | None:
    """Fetch the newest generic version payload for an entity."""
    try:
        async with async_session_factory() as session:
            stmt = (
                select(EntityVersionORM)
                .where(
                    EntityVersionORM.entity_type == entity_type,
                    EntityVersionORM.entity_id == entity_id,
                )
                .order_by(desc(EntityVersionORM.version_number))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            return dict(row.data) if row is not None else None
    except Exception as exc:
        logger.debug("Entity version fetch skipped: %s", exc)
        return None


async def list_latest_entity_versions(entity_type: str) -> list[dict[str, Any]] | None:
    """Fetch latest payloads for all entities of one type."""
    try:
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(EntityVersionORM)
                    .where(EntityVersionORM.entity_type == entity_type)
                    .order_by(
                        EntityVersionORM.entity_id,
                        desc(EntityVersionORM.version_number),
                    )
                )
            ).scalars().all()
            latest: dict[str, dict[str, Any]] = {}
            for row in rows:
                latest.setdefault(row.entity_id, dict(row.data))
            return list(latest.values())
    except Exception as exc:
        logger.debug("Entity version list skipped: %s", exc)
        return None


async def persist_incident(incident: Incident, *, user_id: str | None = None) -> bool:
    """Upsert an Incident into PostgreSQL when available."""
    payload = _json(incident)
    try:
        async with async_session_factory() as session:
            existing = await session.get(IncidentORM, incident.incident_id)
            if existing is None:
                session.add(
                    IncidentORM(
                        incident_id=incident.incident_id,
                        incident_type=str(incident.incident_type),
                        external_event_id=incident.external_event_id,
                        occurred_at=incident.occurred_at,
                        workshop_id=incident.workshop_id,
                        resource_id=incident.resource_id,
                        report_source=str(incident.report_source),
                        source_system=incident.source_system,
                        severity=str(incident.severity),
                        status=str(incident.status),
                        description=incident.description,
                        deduplicated_from=incident.deduplicated_from,
                        raw_payload=incident.raw_payload,
                        idempotency_key=incident.idempotency_key,
                        created_by=incident.created_by or user_id,
                    )
                )
            else:
                existing.status = str(incident.status)
                existing.severity = str(incident.severity)
                existing.description = incident.description
                existing.deduplicated_from = incident.deduplicated_from
                existing.raw_payload = incident.raw_payload
                existing.version += 1
            await session.commit()
        await record_entity_version(
            entity_type="incident",
            entity_id=str(incident.incident_id),
            data=payload,
            changed_by=user_id,
        )
        await persist_audit_log(
            action="incident_create",
            entity_type="incident",
            entity_id=str(incident.incident_id),
            user_id=user_id,
            details={"resource_id": incident.resource_id, "status": str(incident.status)},
        )
        return True
    except Exception as exc:
        logger.debug("Incident persistence skipped: %s", exc)
        return False


async def fetch_incident(incident_id: UUID) -> Incident | None:
    try:
        async with async_session_factory() as session:
            row = await session.get(IncidentORM, incident_id)
            if row is None:
                return None
            return Incident(
                incident_id=row.incident_id,
                incident_type=row.incident_type,
                external_event_id=row.external_event_id,
                occurred_at=row.occurred_at,
                workshop_id=row.workshop_id,
                resource_id=row.resource_id,
                report_source=row.report_source,
                source_system=row.source_system,
                severity=row.severity,
                status=row.status,
                description=row.description,
                deduplicated_from=row.deduplicated_from or [],
                created_at=row.created_at,
                idempotency_key=row.idempotency_key,
                created_by=row.created_by,
                raw_payload=row.raw_payload,
            )
    except Exception as exc:
        logger.debug("Incident fetch from DB skipped: %s", exc)
        return None


async def list_incidents_from_db(
    *,
    incident_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[Incident] | None:
    """Return incidents from DB, or None if DB is unavailable."""
    try:
        async with async_session_factory() as session:
            stmt = select(IncidentORM)
            if incident_type is not None:
                stmt = stmt.where(IncidentORM.incident_type == incident_type)
            if severity is not None:
                stmt = stmt.where(IncidentORM.severity == severity)
            if status is not None:
                stmt = stmt.where(IncidentORM.status == status)
            if start_time is not None:
                stmt = stmt.where(IncidentORM.occurred_at >= start_time)
            if end_time is not None:
                stmt = stmt.where(IncidentORM.occurred_at <= end_time)
            stmt = stmt.order_by(desc(IncidentORM.occurred_at)).limit(500)
            rows = (await session.execute(stmt)).scalars().all()
            return [
                Incident(
                    incident_id=row.incident_id,
                    incident_type=row.incident_type,
                    external_event_id=row.external_event_id,
                    occurred_at=row.occurred_at,
                    workshop_id=row.workshop_id,
                    resource_id=row.resource_id,
                    report_source=row.report_source,
                    source_system=row.source_system,
                    severity=row.severity,
                    status=row.status,
                    description=row.description,
                    deduplicated_from=row.deduplicated_from or [],
                    created_at=row.created_at,
                    idempotency_key=row.idempotency_key,
                    created_by=row.created_by,
                    raw_payload=row.raw_payload,
                )
                for row in rows
            ]
    except Exception as exc:
        logger.debug("Incident list from DB skipped: %s", exc)
        return None


async def assign_snapshot_version(snapshot: ScheduleSnapshot) -> ScheduleSnapshot:
    """Assign a workshop-local snapshot version using DB state when possible."""
    if snapshot.snapshot_version > 1:
        return snapshot
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(func.max(ScheduleSnapshotORM.snapshot_version)).where(
                    ScheduleSnapshotORM.workshop_id == snapshot.workshop_id
                )
            )
            snapshot.snapshot_version = (result.scalar_one_or_none() or 0) + 1
    except Exception:
        # Keep caller-provided default in local-only mode.
        pass
    return snapshot


async def persist_schedule_snapshot(
    snapshot: ScheduleSnapshot, *, user_id: str | None = None
) -> bool:
    """Upsert a ScheduleSnapshot and its immutable entity version."""
    payload = _json(snapshot)
    try:
        async with async_session_factory() as session:
            existing = await session.get(ScheduleSnapshotORM, snapshot.snapshot_id)
            if existing is None:
                session.add(
                    ScheduleSnapshotORM(
                        snapshot_id=snapshot.snapshot_id,
                        captured_at=snapshot.captured_at,
                        workshop_id=snapshot.workshop_id,
                        source_system=snapshot.source_system,
                        schema_version=snapshot.schema_version,
                        snapshot_version=snapshot.snapshot_version,
                        parent_snapshot_id=snapshot.parent_snapshot_id,
                        baseline_snapshot_id=snapshot.baseline_snapshot_id,
                        import_batch_id=snapshot.import_batch_id,
                        snapshot_hash=snapshot.snapshot_hash,
                        snapshot_data=payload,
                        is_active=snapshot.is_active,
                        created_by=snapshot.created_by or user_id,
                    )
                )
            await session.commit()
        await record_entity_version(
            entity_type="schedule_snapshot",
            entity_id=str(snapshot.snapshot_id),
            data=payload,
            changed_by=user_id,
            version_number=snapshot.snapshot_version,
        )
        await persist_audit_log(
            action="schedule_snapshot_import",
            entity_type="schedule_snapshot",
            entity_id=str(snapshot.snapshot_id),
            user_id=user_id,
            details={"workshop_id": snapshot.workshop_id, "version": snapshot.snapshot_version},
        )
        return True
    except Exception as exc:
        logger.debug("Schedule snapshot persistence skipped: %s", exc)
        return False


async def fetch_any_snapshot() -> ScheduleSnapshot | None:
    """Return the newest active snapshot from DB, or None if unavailable."""
    try:
        async with async_session_factory() as session:
            stmt = (
                select(ScheduleSnapshotORM)
                .where(ScheduleSnapshotORM.is_active.is_(True))
                .order_by(desc(ScheduleSnapshotORM.captured_at))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            if row is None:
                return None
            data = dict(row.snapshot_data)
            data.setdefault("snapshot_id", str(row.snapshot_id))
            data.setdefault("captured_at", row.captured_at.isoformat())
            data.setdefault("workshop_id", row.workshop_id)
            data.setdefault("source_system", row.source_system)
            data.setdefault("schema_version", row.schema_version)
            data.setdefault("snapshot_version", row.snapshot_version)
            return ScheduleSnapshot.model_validate(data)
    except Exception as exc:
        logger.debug("Schedule snapshot fetch from DB skipped: %s", exc)
        return None


async def fetch_snapshot(snapshot_id: UUID) -> ScheduleSnapshot | None:
    """Fetch a specific schedule snapshot from DB."""
    try:
        async with async_session_factory() as session:
            row = await session.get(ScheduleSnapshotORM, snapshot_id)
            if row is None:
                return None
            data = dict(row.snapshot_data)
            data.setdefault("snapshot_id", str(row.snapshot_id))
            data.setdefault("captured_at", row.captured_at.isoformat())
            data.setdefault("workshop_id", row.workshop_id)
            data.setdefault("source_system", row.source_system)
            data.setdefault("schema_version", row.schema_version)
            data.setdefault("snapshot_version", row.snapshot_version)
            return ScheduleSnapshot.model_validate(data)
    except Exception as exc:
        logger.debug("Schedule snapshot fetch by id skipped: %s", exc)
        return None


async def persist_impact_report(
    report: ImpactReport, *, user_id: str | None = None
) -> bool:
    """Persist an impact report as JSONB."""
    payload = _json(report)
    try:
        async with async_session_factory() as session:
            session.add(
                ImpactReportORM(
                    incident_id=report.incident_id,
                    snapshot_id=report.schedule_snapshot_id,
                    analysis_mode="degraded" if report.is_degraded_mode else "normal",
                    report_data=payload,
                    analysis_reference_time=report.analysis_reference_time,
                )
            )
            await session.commit()
        await record_entity_version(
            entity_type="impact_report",
            entity_id=str(report.incident_id),
            data=payload,
            changed_by=user_id,
        )
        return True
    except Exception as exc:
        logger.debug("Impact report persistence skipped: %s", exc)
        return False


async def fetch_impact_report(incident_id: UUID) -> ImpactReport | None:
    """Fetch the newest impact report for an incident."""
    try:
        async with async_session_factory() as session:
            stmt = (
                select(ImpactReportORM)
                .where(ImpactReportORM.incident_id == incident_id)
                .order_by(desc(ImpactReportORM.created_at))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            if row is None:
                return None
            return ImpactReport.model_validate(dict(row.report_data))
    except Exception as exc:
        logger.debug("Impact report fetch skipped: %s", exc)
        payload = await fetch_latest_entity_version(
            entity_type="impact_report",
            entity_id=str(incident_id),
        )
        return ImpactReport.model_validate(payload) if payload else None


async def persist_strategy_recommendation(
    incident_id: UUID,
    recommendation: StrategyRecommendation,
    *,
    user_id: str | None = None,
) -> bool:
    """Persist strategy recommendation in the generic version table."""
    return await record_entity_version(
        entity_type="strategy_recommendation",
        entity_id=str(incident_id),
        data=_json(recommendation),
        changed_by=user_id,
    )


async def fetch_strategy_recommendation(
    incident_id: UUID,
) -> StrategyRecommendation | None:
    payload = await fetch_latest_entity_version(
        entity_type="strategy_recommendation",
        entity_id=str(incident_id),
    )
    return StrategyRecommendation.model_validate(payload) if payload else None


async def persist_candidate_plans(
    incident_id: UUID,
    plans: list[CandidatePlan],
    *,
    baseline_snapshot_id: UUID | None = None,
    user_id: str | None = None,
) -> bool:
    """Upsert solver candidate plans."""
    try:
        async with async_session_factory() as session:
            for plan in plans:
                existing = await session.get(CandidatePlanORM, plan.plan_id)
                payload = _json(plan)
                values = {
                    "incident_id": incident_id,
                    "baseline_snapshot_id": baseline_snapshot_id,
                    "strategy_type": plan.strategy_type,
                    "schedule_detail": payload["schedule_detail"],
                    "solver_chain": payload["solver_chain"],
                    "feasibility_status": plan.feasibility_status,
                    "solver_metadata": payload["solver_metadata"],
                    "constraint_report": payload["constraint_report"],
                    "gantt_version": plan.gantt_version,
                }
                if existing is None:
                    session.add(CandidatePlanORM(plan_id=plan.plan_id, **values))
                else:
                    for attr, value in values.items():
                        setattr(existing, attr, value)
            await session.commit()
        for plan in plans:
            await record_entity_version(
                entity_type="candidate_plan",
                entity_id=str(plan.plan_id),
                data=_json(plan),
                changed_by=user_id,
            )
        return True
    except Exception as exc:
        logger.debug("Candidate plan persistence skipped: %s", exc)
        return False


def _candidate_from_row(row: CandidatePlanORM) -> CandidatePlan:
    data = {
        "plan_id": str(row.plan_id),
        "strategy_type": row.strategy_type,
        "schedule_detail": row.schedule_detail,
        "gantt_version": row.gantt_version or "1.0",
        "solver_chain": row.solver_chain,
        "feasibility_status": row.feasibility_status,
        "solver_metadata": row.solver_metadata or {
            "solve_time_seconds": 0.0,
            "iteration_count": 0,
            "objective_trajectory": [],
        },
        "constraint_report": row.constraint_report or {
            "is_feasible": row.feasibility_status != "infeasible",
            "violations": [],
            "checked_constraints": [],
        },
        "created_at": row.created_at.isoformat(),
    }
    return CandidatePlan.model_validate(data)


async def list_candidate_plans_from_db(incident_id: UUID) -> list[CandidatePlan] | None:
    """Return candidate plans for an incident, or None if DB is unavailable."""
    try:
        async with async_session_factory() as session:
            stmt = (
                select(CandidatePlanORM)
                .where(CandidatePlanORM.incident_id == incident_id)
                .order_by(CandidatePlanORM.created_at)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_candidate_from_row(row) for row in rows]
    except Exception as exc:
        logger.debug("Candidate plan list fetch skipped: %s", exc)
        return None


async def fetch_candidate_plan(plan_id: UUID) -> CandidatePlan | None:
    """Fetch one candidate plan by id."""
    try:
        async with async_session_factory() as session:
            row = await session.get(CandidatePlanORM, plan_id)
            return _candidate_from_row(row) if row is not None else None
    except Exception as exc:
        logger.debug("Candidate plan fetch skipped: %s", exc)
        payload = await fetch_latest_entity_version(
            entity_type="candidate_plan",
            entity_id=str(plan_id),
        )
        return CandidatePlan.model_validate(payload) if payload else None


async def persist_plan_recommendation(
    incident_id: UUID,
    output: PlanSelectionOutput,
    *,
    user_id: str | None = None,
) -> bool:
    """Persist the final recommendation output."""
    payload = _json(output)
    try:
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(PlanRecommendationORM).where(
                        PlanRecommendationORM.incident_id == incident_id,
                        PlanRecommendationORM.is_active.is_(True),
                    )
                )
            ).scalars().all()
            for row in rows:
                row.is_active = False
            session.add(
                PlanRecommendationORM(
                    incident_id=incident_id,
                    recommended_plan_id=output.recommended_plan_id,
                    top_scored_plan_id=output.top_scored_plan_id,
                    goal_mode=output.goal_mode_used,
                    confidence=Decimal(str(output.recommendation_confidence)),
                    recommendation_payload=payload,
                    is_active=True,
                )
            )
            await session.commit()
        await record_entity_version(
            entity_type="plan_recommendation",
            entity_id=str(incident_id),
            data=payload,
            changed_by=user_id,
        )
        return True
    except Exception as exc:
        logger.debug("Plan recommendation persistence skipped: %s", exc)
        return False


async def fetch_plan_recommendation(incident_id: UUID) -> PlanSelectionOutput | None:
    """Fetch active recommendation for an incident."""
    try:
        async with async_session_factory() as session:
            stmt = (
                select(PlanRecommendationORM)
                .where(
                    PlanRecommendationORM.incident_id == incident_id,
                    PlanRecommendationORM.is_active.is_(True),
                )
                .order_by(desc(PlanRecommendationORM.created_at))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            if row is not None:
                return PlanSelectionOutput.model_validate(dict(row.recommendation_payload))
    except Exception as exc:
        logger.debug("Plan recommendation fetch skipped: %s", exc)

    payload = await fetch_latest_entity_version(
        entity_type="plan_recommendation",
        entity_id=str(incident_id),
    )
    return PlanSelectionOutput.model_validate(payload) if payload else None


async def persist_decision_record(
    record: DecisionRecord, *, user_id: str | None = None
) -> bool:
    """Persist a planner decision record and full audit payload."""
    payload = _json(record)
    try:
        async with async_session_factory() as session:
            existing = await session.get(DecisionRecordORM, record.decision_record_id)
            values = {
                "incident_id": record.incident_id,
                "original_recommended_plan_id": record.recommended_plan_id,
                "confirmed_plan_id": record.confirmed_plan_id,
                "derived_from_plan_id": record.derived_from_plan_id,
                "is_manual_adjusted": record.is_manual_adjusted,
                "is_override": record.is_override,
                "override_reason": record.override_reason,
                "confirmed_by": record.confirmed_by,
                "confirmed_at": record.confirmed_at,
                "plan_selection_input": {
                    "impact_report_summary": record.impact_report_summary,
                    "all_candidate_plan_ids": [
                        str(plan_id) for plan_id in record.all_candidate_plan_ids
                    ],
                    "strategy_type": record.strategy_type,
                },
                "plan_selection_output": {"_decision_record_payload": payload},
                "module_versions": {
                    "rule_selector": record.rule_selector_version,
                    "neighborhood_selector": record.neighborhood_selector_version,
                    "repair_policy_advisor": record.repair_policy_advisor_version,
                    "plan_selection_input": record.plan_selection_input_version,
                    "plan_selection_output": record.plan_selection_output_version,
                    "solver_chain": payload["solver_chain"],
                },
            }
            if existing is None:
                session.add(
                    DecisionRecordORM(
                        decision_record_id=record.decision_record_id,
                        **values,
                    )
                )
            else:
                for attr, value in values.items():
                    setattr(existing, attr, value)
            await session.commit()
        await record_entity_version(
            entity_type="decision_record",
            entity_id=str(record.decision_record_id),
            data=payload,
            changed_by=user_id,
        )
        await record_entity_version(
            entity_type="decision_record_by_incident",
            entity_id=str(record.incident_id),
            data=payload,
            changed_by=user_id,
        )
        return True
    except Exception as exc:
        logger.debug("Decision record persistence skipped: %s", exc)
        return False


def _decision_from_payload(payload: dict[str, Any] | None) -> DecisionRecord | None:
    if not payload:
        return None
    if "_decision_record_payload" in payload:
        payload = payload["_decision_record_payload"]
    return DecisionRecord.model_validate(payload)


async def fetch_decision_record_by_incident(incident_id: UUID) -> DecisionRecord | None:
    try:
        async with async_session_factory() as session:
            stmt = (
                select(DecisionRecordORM)
                .where(DecisionRecordORM.incident_id == incident_id)
                .order_by(desc(DecisionRecordORM.confirmed_at))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            if row is not None:
                record = _decision_from_payload(row.plan_selection_output)
                if record is not None:
                    return record
    except Exception as exc:
        logger.debug("Decision record fetch by incident skipped: %s", exc)

    payload = await fetch_latest_entity_version(
        entity_type="decision_record_by_incident",
        entity_id=str(incident_id),
    )
    return DecisionRecord.model_validate(payload) if payload else None


async def fetch_decision_record_by_id(decision_record_id: UUID) -> DecisionRecord | None:
    try:
        async with async_session_factory() as session:
            row = await session.get(DecisionRecordORM, decision_record_id)
            if row is not None:
                record = _decision_from_payload(row.plan_selection_output)
                if record is not None:
                    return record
    except Exception as exc:
        logger.debug("Decision record fetch by id skipped: %s", exc)

    payload = await fetch_latest_entity_version(
        entity_type="decision_record",
        entity_id=str(decision_record_id),
    )
    return DecisionRecord.model_validate(payload) if payload else None


async def persist_writeback_job(
    *,
    incident_id: UUID,
    decision_record_id: UUID,
    confirmed_plan_id: UUID,
    target_system: str,
    status: WritebackStatus,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    retry_count: int = 0,
    next_retry_at: datetime | None = None,
) -> bool:
    """Create or update the latest writeback job for a decision."""
    try:
        async with async_session_factory() as session:
            stmt = (
                select(WritebackJobORM)
                .where(WritebackJobORM.decision_record_id == decision_record_id)
                .order_by(desc(WritebackJobORM.created_at))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            values = {
                "incident_id": incident_id,
                "decision_record_id": decision_record_id,
                "confirmed_plan_id": confirmed_plan_id,
                "target_system": target_system,
                "status": status.value,
                "retry_count": retry_count,
                "next_retry_at": next_retry_at,
                "request_payload": request_payload,
                "response_payload": response_payload,
                "error_message": error_message,
            }
            if row is None:
                session.add(WritebackJobORM(**values))
            else:
                for attr, value in values.items():
                    setattr(row, attr, value)
            await session.commit()
        return True
    except Exception as exc:
        logger.debug("Writeback job persistence skipped: %s", exc)
        return False


async def fetch_writeback_job_by_incident(incident_id: UUID) -> dict[str, Any] | None:
    """Fetch the latest writeback job as a JSON-friendly dict."""
    try:
        async with async_session_factory() as session:
            stmt = (
                select(WritebackJobORM)
                .where(WritebackJobORM.incident_id == incident_id)
                .order_by(desc(WritebackJobORM.created_at))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            if row is None:
                return None
            return {
                "writeback_job_id": str(row.writeback_job_id),
                "incident_id": str(row.incident_id),
                "decision_record_id": str(row.decision_record_id)
                if row.decision_record_id
                else None,
                "confirmed_plan_id": str(row.confirmed_plan_id),
                "target_system": row.target_system,
                "status": row.status,
                "retry_count": row.retry_count,
                "next_retry_at": row.next_retry_at.isoformat()
                if row.next_retry_at
                else None,
                "request_payload": row.request_payload,
                "response_payload": row.response_payload,
                "error_message": row.error_message,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
    except Exception as exc:
        logger.debug("Writeback job fetch skipped: %s", exc)
        return None


async def list_retryable_writeback_jobs(now: datetime | None = None) -> list[dict[str, Any]]:
    """List failed writeback jobs whose retry window is due."""
    due_at = now or datetime.now(tz=timezone.utc)
    try:
        async with async_session_factory() as session:
            stmt = (
                select(WritebackJobORM)
                .where(
                    WritebackJobORM.status.in_(
                        [WritebackStatus.FAILED.value, WritebackStatus.PARTIAL_SUCCESS.value]
                    ),
                    WritebackJobORM.retry_count < 3,
                )
                .order_by(WritebackJobORM.created_at)
            )
            rows = (await session.execute(stmt)).scalars().all()
            result = []
            for row in rows:
                if row.next_retry_at is not None and row.next_retry_at > due_at:
                    continue
                result.append(
                    {
                        "incident_id": str(row.incident_id),
                        "decision_record_id": str(row.decision_record_id)
                        if row.decision_record_id
                        else None,
                        "confirmed_plan_id": str(row.confirmed_plan_id),
                        "retry_count": row.retry_count,
                        "request_payload": row.request_payload,
                    }
                )
            return result
    except Exception as exc:
        logger.debug("Retryable writeback job list skipped: %s", exc)
        return []


async def persist_execution_result(result: ExecutionResult) -> bool:
    """Persist actual execution metrics."""
    try:
        async with async_session_factory() as session:
            session.add(
                ExecutionResultORM(
                    decision_record_id=result.decision_record_id,
                    actual_metrics=_json(result),
                )
            )
            await session.commit()
        await record_entity_version(
            entity_type="execution_result_by_incident",
            entity_id=str(result.incident_id),
            data=_json(result),
        )
        return True
    except Exception as exc:
        logger.debug("Execution result persistence skipped: %s", exc)
        return False


async def fetch_execution_result_by_incident(
    incident_id: UUID,
) -> ExecutionResult | None:
    payload = await fetch_latest_entity_version(
        entity_type="execution_result_by_incident",
        entity_id=str(incident_id),
    )
    return ExecutionResult.model_validate(payload) if payload else None


async def persist_case_record(case: CaseRecord, *, user_id: str | None = None) -> bool:
    return await record_entity_version(
        entity_type="case_record",
        entity_id=str(case.case_id),
        data=_json(case),
        changed_by=user_id,
    )


async def list_case_records_from_db(
    *,
    incident_type: str | None = None,
    strategy_type: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    is_override: bool | None = None,
) -> list[CaseRecord] | None:
    payloads = await list_latest_entity_versions("case_record")
    if payloads is None:
        return None
    cases = [CaseRecord.model_validate(payload) for payload in payloads]
    results: list[CaseRecord] = []
    for case in cases:
        if strategy_type and case.strategy_type != strategy_type:
            continue
        if incident_type and case.incident_features.get("incident_type") != incident_type:
            continue
        if time_from and case.created_at < time_from:
            continue
        if time_to and case.created_at > time_to:
            continue
        if is_override is not None and case.is_override != is_override:
            continue
        results.append(case)
    return sorted(results, key=lambda c: c.created_at, reverse=True)


async def fetch_case_record(case_id: UUID) -> CaseRecord | None:
    payload = await fetch_latest_entity_version(
        entity_type="case_record",
        entity_id=str(case_id),
    )
    return CaseRecord.model_validate(payload) if payload else None


async def persist_case_template(
    template: CaseTemplate, *, user_id: str | None = None
) -> bool:
    return await record_entity_version(
        entity_type="case_template",
        entity_id=str(template.template_id),
        data=_json(template),
        changed_by=user_id,
    )


async def list_case_templates_from_db(
    status: str | None = None,
) -> list[CaseTemplate] | None:
    payloads = await list_latest_entity_versions("case_template")
    if payloads is None:
        return None
    templates = [CaseTemplate.model_validate(payload) for payload in payloads]
    if status:
        templates = [template for template in templates if template.status == status]
    return sorted(templates, key=lambda t: t.created_at, reverse=True)


async def fetch_case_template(template_id: UUID) -> CaseTemplate | None:
    payload = await fetch_latest_entity_version(
        entity_type="case_template",
        entity_id=str(template_id),
    )
    return CaseTemplate.model_validate(payload) if payload else None


async def persist_preference_profile(
    profile: PreferenceProfile, *, user_id: str | None = None
) -> bool:
    return await record_entity_version(
        entity_type="preference_profile",
        entity_id=profile.planner_id,
        data=_json(profile),
        changed_by=user_id,
    )


async def fetch_preference_profile(planner_id: str) -> PreferenceProfile | None:
    payload = await fetch_latest_entity_version(
        entity_type="preference_profile",
        entity_id=planner_id,
    )
    return PreferenceProfile.model_validate(payload) if payload else None
