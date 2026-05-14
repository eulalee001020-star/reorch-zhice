"""Best-effort database persistence helpers.

The current codebase still uses in-memory API stores for fast local MVP tests.
These helpers add a production migration path: when PostgreSQL is reachable,
API handlers can write/read durable records; when it is not reachable, callers
can keep the existing in-memory behavior.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select

from app.core.database import async_session_factory
from app.models.db.audit_logs import AuditLog as AuditLogORM
from app.models.db.entity_versions import EntityVersion as EntityVersionORM
from app.models.db.incidents import Incident as IncidentORM
from app.models.db.schedule_snapshots import ScheduleSnapshot as ScheduleSnapshotORM
from app.models.incident import Incident
from app.models.schedule import ScheduleSnapshot

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

