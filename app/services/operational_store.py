"""Transactional relational store for the production runtime."""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import DateTime, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.db.operational_runtime import (
    CdcCheckpointRecord,
    CdcEventRecord,
    ExecutionReceiptRecordORM,
    IntegrationAssetRecordORM,
    IntegrationAuditRecordORM,
    IntegrationQuarantineRecordORM,
    OperationalBase,
    RuntimeEvidenceRecordORM,
    ShadowCaseRecordORM,
    SolveJobRecordORM,
)
from app.models.production_runtime import (
    CdcEvent,
    ExecutionReceipt,
    ShadowExecutionStatus,
    SolveJobRecord,
    TenantSolveQuota,
)
from app.models.integration_control import (
    IntegrationAuditEvent,
    QuarantineRecord,
    VersionedAssetRecord,
)


class RelationalOperationalStore:
    """Portable SQL store; PostgreSQL is used for multi-node deployments."""

    def __init__(self, database_url: str = "sqlite+pysqlite:///:memory:") -> None:
        kwargs: dict[str, Any] = {"future": True}
        if database_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if database_url.endswith(":memory:"):
                kwargs["poolclass"] = StaticPool
        self.engine = create_engine(database_url, **kwargs)
        OperationalBase.metadata.create_all(self.engine)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False, future=True)
        self._lock = threading.RLock()

    def session(self) -> Session:
        return self._sessions()

    def get_cdc_event(self, event_id: str) -> CdcEventRecord | None:
        with self.session() as session:
            return session.get(CdcEventRecord, event_id)

    def get_checkpoint(
        self, tenant_id: str, source_system: str, partition_key: str
    ) -> CdcCheckpointRecord | None:
        with self.session() as session:
            return session.scalar(
                select(CdcCheckpointRecord).where(
                    CdcCheckpointRecord.tenant_id == tenant_id,
                    CdcCheckpointRecord.source_system == source_system,
                    CdcCheckpointRecord.partition_key == partition_key,
                )
            )

    def pending_sequences(
        self, tenant_id: str, source_system: str, partition_key: str, after: int
    ) -> list[int]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(CdcEventRecord.sequence)
                    .where(
                        CdcEventRecord.tenant_id == tenant_id,
                        CdcEventRecord.source_system == source_system,
                        CdcEventRecord.partition_key == partition_key,
                        CdcEventRecord.sequence > after,
                        CdcEventRecord.committed.is_(False),
                    )
                    .order_by(CdcEventRecord.sequence)
                )
            )

    def apply_cdc_event(
        self,
        event: CdcEvent,
        checksum: str,
        checkpoint_token_factory,
    ) -> tuple[str, CdcCheckpointRecord, list[int], str | None]:
        now = datetime.now(tz=timezone.utc)
        with self._lock, self.session() as session, session.begin():
            existing = session.get(CdcEventRecord, event.event_id)
            checkpoint = session.scalar(
                select(CdcCheckpointRecord)
                .where(
                    CdcCheckpointRecord.tenant_id == event.tenant_id,
                    CdcCheckpointRecord.source_system == event.source_system,
                    CdcCheckpointRecord.partition_key == event.partition_key,
                )
                .with_for_update()
            )
            if checkpoint is None:
                checkpoint = CdcCheckpointRecord(
                    tenant_id=event.tenant_id,
                    source_system=event.source_system,
                    partition_key=event.partition_key,
                    committed_sequence=0,
                    watermark_at=None,
                    checkpoint_token=checkpoint_token_factory(
                        event.tenant_id, event.source_system, event.partition_key, 0, None
                    ),
                    updated_at=now,
                )
                session.add(checkpoint)
                session.flush()

            if existing is not None:
                status = "duplicate" if existing.checksum == checksum else "collision_rejected"
                reason = None if status == "duplicate" else "event_id_checksum_collision"
                gaps = _missing_sequences(
                    checkpoint.committed_sequence,
                    self._pending_sequences_in_session(
                        session, event.tenant_id, event.source_system, event.partition_key
                    ),
                )
                return status, checkpoint, gaps, reason

            sequence_existing = session.scalar(
                select(CdcEventRecord).where(
                    CdcEventRecord.tenant_id == event.tenant_id,
                    CdcEventRecord.source_system == event.source_system,
                    CdcEventRecord.partition_key == event.partition_key,
                    CdcEventRecord.sequence == event.sequence,
                )
            )
            if sequence_existing is not None:
                return "collision_rejected", checkpoint, [], "source_sequence_collision"
            if event.sequence <= checkpoint.committed_sequence:
                return "stale_rejected", checkpoint, [], "sequence_not_ahead_of_checkpoint"

            row = CdcEventRecord(
                event_id=event.event_id,
                tenant_id=event.tenant_id,
                source_system=event.source_system,
                partition_key=event.partition_key,
                sequence=event.sequence,
                occurred_at=event.occurred_at,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                operation=event.operation,
                payload=event.payload,
                schema_version=event.schema_version,
                checksum=checksum,
                committed=False,
                ingested_at=now,
            )
            session.add(row)
            session.flush()
            status = "gap_buffered"
            if event.sequence == checkpoint.committed_sequence + 1:
                status = "accepted"
                next_sequence = event.sequence
                watermark = event.occurred_at
                while True:
                    next_row = session.scalar(
                        select(CdcEventRecord).where(
                            CdcEventRecord.tenant_id == event.tenant_id,
                            CdcEventRecord.source_system == event.source_system,
                            CdcEventRecord.partition_key == event.partition_key,
                            CdcEventRecord.sequence == next_sequence,
                        )
                    )
                    if next_row is None:
                        break
                    next_row.committed = True
                    watermark = max(watermark, _aware(next_row.occurred_at))
                    checkpoint.committed_sequence = next_sequence
                    next_sequence += 1
                checkpoint.watermark_at = watermark
                checkpoint.updated_at = now
                checkpoint.checkpoint_token = checkpoint_token_factory(
                    event.tenant_id,
                    event.source_system,
                    event.partition_key,
                    checkpoint.committed_sequence,
                    checkpoint.watermark_at,
                )

            pending = self._pending_sequences_in_session(
                session, event.tenant_id, event.source_system, event.partition_key
            )
            gaps = _missing_sequences(checkpoint.committed_sequence, pending)
            return status, checkpoint, gaps, None

    @staticmethod
    def _pending_sequences_in_session(
        session: Session, tenant_id: str, source_system: str, partition_key: str
    ) -> list[int]:
        return list(
            session.scalars(
                select(CdcEventRecord.sequence)
                .where(
                    CdcEventRecord.tenant_id == tenant_id,
                    CdcEventRecord.source_system == source_system,
                    CdcEventRecord.partition_key == partition_key,
                    CdcEventRecord.committed.is_(False),
                )
                .order_by(CdcEventRecord.sequence)
            )
        )

    def list_checkpoints(
        self, tenant_id: str, sources: list[str], partition_key: str
    ) -> list[CdcCheckpointRecord]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(CdcCheckpointRecord).where(
                        CdcCheckpointRecord.tenant_id == tenant_id,
                        CdcCheckpointRecord.source_system.in_(sources),
                        CdcCheckpointRecord.partition_key == partition_key,
                    )
                )
            )

    def committed_events_as_of(
        self,
        tenant_id: str,
        sources: list[str],
        partition_key: str,
        as_of: datetime,
    ) -> list[CdcEventRecord]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(CdcEventRecord)
                    .where(
                        CdcEventRecord.tenant_id == tenant_id,
                        CdcEventRecord.source_system.in_(sources),
                        CdcEventRecord.partition_key == partition_key,
                        CdcEventRecord.committed.is_(True),
                        CdcEventRecord.occurred_at <= as_of,
                    )
                    .order_by(
                        CdcEventRecord.source_system,
                        CdcEventRecord.sequence,
                    )
                )
            )

    def submit_solve_job(
        self, record: SolveJobRecord, quota: TenantSolveQuota
    ) -> tuple[SolveJobRecord, bool]:
        with self._lock, self.session() as session, session.begin():
            existing = session.scalar(
                select(SolveJobRecordORM).where(
                    SolveJobRecordORM.tenant_id == record.tenant_id,
                    SolveJobRecordORM.idempotency_key == record.idempotency_key,
                )
            )
            if existing is not None:
                return _job_model(existing), False
            operation_count = sum(
                len(wo.operations) for wo in record.solve_request.snapshot.work_orders
            )
            if operation_count > quota.max_operations_per_job:
                raise ValueError("tenant_operation_quota_exceeded")
            queued = session.scalar(
                select(func.count())
                .select_from(SolveJobRecordORM)
                .where(
                    SolveJobRecordORM.tenant_id == record.tenant_id,
                    SolveJobRecordORM.status == "queued",
                )
            )
            if int(queued or 0) >= quota.max_queued_jobs:
                raise ValueError("tenant_queued_job_quota_exceeded")
            session.add(_job_orm(record))
            return record, True

    def claim_solve_job(
        self,
        worker_id: str,
        lease_seconds: int,
        quota_by_tenant: dict[str, TenantSolveQuota],
    ) -> SolveJobRecord | None:
        now = datetime.now(tz=timezone.utc)
        self.recover_expired_leases(now)
        with self._lock, self.session() as session, session.begin():
            candidates = list(
                session.scalars(
                    select(SolveJobRecordORM)
                    .where(SolveJobRecordORM.status == "queued")
                    .order_by(SolveJobRecordORM.priority, SolveJobRecordORM.created_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in candidates:
                quota = quota_by_tenant.get(row.tenant_id, TenantSolveQuota())
                running = session.scalar(
                    select(func.count())
                    .select_from(SolveJobRecordORM)
                    .where(
                        SolveJobRecordORM.tenant_id == row.tenant_id,
                        SolveJobRecordORM.status.in_(["running", "cancel_requested"]),
                    )
                )
                if int(running or 0) >= quota.max_running_jobs:
                    continue
                row.status = "running"
                row.attempt += 1
                row.lease_owner = worker_id
                row.heartbeat_at = now
                row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                row.updated_at = now
                session.flush()
                return _job_model(row)
        return None

    def heartbeat_job(self, job_id: str, worker_id: str, lease_seconds: int) -> bool:
        now = datetime.now(tz=timezone.utc)
        with self._lock, self.session() as session, session.begin():
            row = session.get(SolveJobRecordORM, job_id)
            if row is None or row.lease_owner != worker_id or row.status != "running":
                return False
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.updated_at = now
            return True

    def save_job_checkpoint(
        self, job_id: str, worker_id: str, subproblem_id: str, payload: dict[str, Any]
    ) -> bool:
        now = datetime.now(tz=timezone.utc)
        with self._lock, self.session() as session, session.begin():
            row = session.get(SolveJobRecordORM, job_id)
            if row is None or row.lease_owner != worker_id or row.status != "running":
                return False
            checkpoint = dict(row.checkpoint or {})
            completed = dict(checkpoint.get("completed_subproblems", {}))
            completed[subproblem_id] = payload
            checkpoint["completed_subproblems"] = completed
            checkpoint["updated_at"] = now.isoformat()
            row.checkpoint = checkpoint
            row.updated_at = now
            return True

    def request_job_cancel(self, job_id: str) -> SolveJobRecord | None:
        now = datetime.now(tz=timezone.utc)
        with self._lock, self.session() as session, session.begin():
            row = session.get(SolveJobRecordORM, job_id)
            if row is None:
                return None
            if row.status == "queued":
                row.status = "cancelled"
            elif row.status == "running":
                row.status = "cancel_requested"
            row.updated_at = now
            session.flush()
            return _job_model(row)

    def should_cancel_job(self, job_id: str, worker_id: str) -> bool:
        with self._lock, self.session() as session:
            row = session.get(SolveJobRecordORM, job_id)
            return row is None or row.lease_owner != worker_id or row.status == "cancel_requested"

    def finish_job(
        self,
        job_id: str,
        worker_id: str,
        *,
        status: str,
        result: dict[str, Any] | None,
        error: str | None = None,
    ) -> SolveJobRecord | None:
        now = datetime.now(tz=timezone.utc)
        with self._lock, self.session() as session, session.begin():
            row = session.get(SolveJobRecordORM, job_id)
            if row is None or row.lease_owner != worker_id:
                return None
            row.status = status
            row.result = result
            row.error = error
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = now
            session.flush()
            return _job_model(row)

    def recover_expired_leases(self, now: datetime | None = None) -> int:
        now = now or datetime.now(tz=timezone.utc)
        recovered = 0
        with self._lock, self.session() as session, session.begin():
            rows = list(
                session.scalars(
                    select(SolveJobRecordORM).where(
                        SolveJobRecordORM.status.in_(["running", "cancel_requested"]),
                        SolveJobRecordORM.lease_expires_at < now,
                    )
                )
            )
            for row in rows:
                row.status = "cancelled" if row.status == "cancel_requested" else "queued"
                row.lease_owner = None
                row.lease_expires_at = None
                row.updated_at = now
                recovered += 1
        return recovered

    def get_solve_job(self, job_id: str) -> SolveJobRecord | None:
        with self._lock, self.session() as session:
            row = session.get(SolveJobRecordORM, job_id)
            return _job_model(row) if row is not None else None

    def upsert_shadow_case(
        self,
        status: ShadowExecutionStatus,
        tenant_id: str,
        evidence_scope: str,
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        payload = status.model_dump(mode="json")
        with self._lock, self.session() as session, session.begin():
            row = session.get(ShadowCaseRecordORM, status.shadow_case_id)
            if row is None:
                session.add(
                    ShadowCaseRecordORM(
                        shadow_case_id=status.shadow_case_id,
                        tenant_id=tenant_id,
                        status=status.status,
                        evidence_scope=evidence_scope,
                        payload=payload,
                        evidence_fingerprint=status.evidence_fingerprint,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                row.status = status.status
                row.payload = payload
                row.evidence_fingerprint = status.evidence_fingerprint
                row.updated_at = now

    def get_shadow_case(self, shadow_case_id: str) -> ShadowExecutionStatus | None:
        with self.session() as session:
            row = session.get(ShadowCaseRecordORM, shadow_case_id)
            return ShadowExecutionStatus.model_validate(row.payload) if row else None

    def add_execution_receipt(self, receipt: ExecutionReceipt) -> bool:
        with self._lock, self.session() as session, session.begin():
            existing = session.scalar(
                select(ExecutionReceiptRecordORM).where(
                    ExecutionReceiptRecordORM.tenant_id == receipt.tenant_id,
                    ExecutionReceiptRecordORM.source_event_id == receipt.source_event_id,
                )
            )
            if existing:
                return False
            session.add(
                ExecutionReceiptRecordORM(
                    receipt_id=receipt.receipt_id,
                    tenant_id=receipt.tenant_id,
                    shadow_case_id=receipt.shadow_case_id,
                    source_event_id=receipt.source_event_id,
                    operation_id=receipt.operation_id,
                    event_type=receipt.event_type,
                    observed_at=receipt.observed_at,
                    payload=receipt.model_dump(mode="json"),
                )
            )
            return True

    def list_execution_receipts(self, shadow_case_id: str) -> list[ExecutionReceipt]:
        with self.session() as session:
            rows = list(
                session.scalars(
                    select(ExecutionReceiptRecordORM)
                    .where(ExecutionReceiptRecordORM.shadow_case_id == shadow_case_id)
                    .order_by(ExecutionReceiptRecordORM.observed_at)
                )
            )
            return [ExecutionReceipt.model_validate(row.payload) for row in rows]

    def put_evidence(
        self,
        *,
        evidence_id: str,
        tenant_id: str,
        evidence_type: str,
        evidence_scope: str,
        payload: dict[str, Any],
        fingerprint: str,
    ) -> None:
        with self._lock, self.session() as session, session.begin():
            row = session.get(RuntimeEvidenceRecordORM, evidence_id)
            if row is None:
                session.add(
                    RuntimeEvidenceRecordORM(
                        evidence_id=evidence_id,
                        tenant_id=tenant_id,
                        evidence_type=evidence_type,
                        evidence_scope=evidence_scope,
                        payload=payload,
                        fingerprint=fingerprint,
                        created_at=datetime.now(tz=timezone.utc),
                    )
                )
            elif row.fingerprint != fingerprint:
                raise ValueError("immutable_evidence_collision")

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with self.session() as session:
            row = session.get(RuntimeEvidenceRecordORM, evidence_id)
            if row is None:
                return None
            return {
                "evidence_id": row.evidence_id,
                "tenant_id": row.tenant_id,
                "evidence_type": row.evidence_type,
                "evidence_scope": row.evidence_scope,
                "payload": row.payload,
                "fingerprint": row.fingerprint,
                "created_at": row.created_at.isoformat(),
            }

    def put_integration_asset(
        self,
        *,
        tenant_id: str,
        asset_type: str,
        asset_id: str,
        scope_key: str,
        version: str,
        payload: dict[str, Any],
        fingerprint: str,
        created_by: str,
    ) -> tuple[VersionedAssetRecord, bool]:
        """Register one immutable asset version without activating it."""
        asset_key = _integration_asset_key(tenant_id, asset_type, asset_id, version)
        now = datetime.now(tz=timezone.utc)
        with self._lock, self.session() as session, session.begin():
            existing = session.get(IntegrationAssetRecordORM, asset_key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise ValueError("immutable_integration_asset_collision")
                return _integration_asset_model(existing), False
            row = IntegrationAssetRecordORM(
                asset_key=asset_key,
                tenant_id=tenant_id,
                asset_type=asset_type,
                asset_id=asset_id,
                scope_key=scope_key,
                version=version,
                status="draft",
                payload=payload,
                fingerprint=fingerprint,
                created_by=created_by,
                created_at=now,
            )
            session.add(row)
            session.flush()
            return _integration_asset_model(row), True

    def activate_integration_asset(
        self,
        *,
        tenant_id: str,
        asset_type: str,
        asset_id: str,
        version: str,
        approved_by: str,
        approval_note: str,
    ) -> VersionedAssetRecord | None:
        """Activate a version and retire the previous version in the same scope."""
        asset_key = _integration_asset_key(tenant_id, asset_type, asset_id, version)
        now = datetime.now(tz=timezone.utc)
        with self._lock, self.session() as session, session.begin():
            row = session.scalar(
                select(IntegrationAssetRecordORM)
                .where(IntegrationAssetRecordORM.asset_key == asset_key)
                .with_for_update()
            )
            if row is None:
                return None
            if row.status == "active":
                return _integration_asset_model(row)
            if row.status != "draft":
                raise ValueError("only_draft_integration_assets_can_be_activated")
            active_rows = list(
                session.scalars(
                    select(IntegrationAssetRecordORM)
                    .where(
                        IntegrationAssetRecordORM.tenant_id == tenant_id,
                        IntegrationAssetRecordORM.asset_type == asset_type,
                        IntegrationAssetRecordORM.scope_key == row.scope_key,
                        IntegrationAssetRecordORM.status == "active",
                    )
                    .with_for_update()
                )
            )
            for active in active_rows:
                active.status = "retired"
            row.status = "active"
            row.approved_by = approved_by
            row.approval_note = approval_note
            row.activated_at = now
            session.flush()
            return _integration_asset_model(row)

    def get_integration_asset(
        self, tenant_id: str, asset_type: str, asset_id: str, version: str
    ) -> VersionedAssetRecord | None:
        asset_key = _integration_asset_key(tenant_id, asset_type, asset_id, version)
        with self.session() as session:
            row = session.get(IntegrationAssetRecordORM, asset_key)
            return _integration_asset_model(row) if row else None

    def get_active_integration_asset(
        self, tenant_id: str, asset_type: str, scope_key: str
    ) -> VersionedAssetRecord | None:
        with self.session() as session:
            row = session.scalar(
                select(IntegrationAssetRecordORM).where(
                    IntegrationAssetRecordORM.tenant_id == tenant_id,
                    IntegrationAssetRecordORM.asset_type == asset_type,
                    IntegrationAssetRecordORM.scope_key == scope_key,
                    IntegrationAssetRecordORM.status == "active",
                )
            )
            return _integration_asset_model(row) if row else None

    def list_integration_assets(
        self,
        tenant_id: str,
        *,
        asset_type: str | None = None,
        status: str | None = None,
    ) -> list[VersionedAssetRecord]:
        with self.session() as session:
            query = select(IntegrationAssetRecordORM).where(
                IntegrationAssetRecordORM.tenant_id == tenant_id
            )
            if asset_type:
                query = query.where(IntegrationAssetRecordORM.asset_type == asset_type)
            if status:
                query = query.where(IntegrationAssetRecordORM.status == status)
            rows = list(
                session.scalars(
                    query.order_by(
                        IntegrationAssetRecordORM.asset_type,
                        IntegrationAssetRecordORM.scope_key,
                        IntegrationAssetRecordORM.created_at.desc(),
                    )
                )
            )
            return [_integration_asset_model(row) for row in rows]

    def put_quarantine_record(
        self,
        record: QuarantineRecord,
    ) -> tuple[QuarantineRecord, bool]:
        with self._lock, self.session() as session, session.begin():
            existing = session.scalar(
                select(IntegrationQuarantineRecordORM).where(
                    IntegrationQuarantineRecordORM.tenant_id == record.tenant_id,
                    IntegrationQuarantineRecordORM.connector_id == record.connector_id,
                    IntegrationQuarantineRecordORM.fingerprint == record.fingerprint,
                )
            )
            if existing is not None:
                return _quarantine_model(existing), False
            row = IntegrationQuarantineRecordORM(
                quarantine_id=record.quarantine_id,
                tenant_id=record.tenant_id,
                connector_id=record.connector_id,
                source_system=record.source_system,
                entity_type=record.entity_type,
                schema_version=record.schema_version,
                status=record.status,
                reason_codes=record.reason_codes,
                observation=record.observation,
                fingerprint=record.fingerprint,
                observed_at=record.observed_at,
            )
            session.add(row)
            session.flush()
            return _quarantine_model(row), True

    def list_quarantine_records(
        self, tenant_id: str, *, status: str | None = None
    ) -> list[QuarantineRecord]:
        with self.session() as session:
            query = select(IntegrationQuarantineRecordORM).where(
                IntegrationQuarantineRecordORM.tenant_id == tenant_id
            )
            if status:
                query = query.where(IntegrationQuarantineRecordORM.status == status)
            rows = list(
                session.scalars(
                    query.order_by(IntegrationQuarantineRecordORM.observed_at.desc())
                )
            )
            return [_quarantine_model(row) for row in rows]

    def get_quarantine_record(self, quarantine_id: str) -> QuarantineRecord | None:
        with self.session() as session:
            row = session.get(IntegrationQuarantineRecordORM, quarantine_id)
            return _quarantine_model(row) if row else None

    def resolve_quarantine_record(
        self,
        quarantine_id: str,
        *,
        status: str,
        resolved_by: str,
        resolution_note: str,
    ) -> QuarantineRecord | None:
        if status not in {"released", "rejected"}:
            raise ValueError("invalid_quarantine_resolution_status")
        with self._lock, self.session() as session, session.begin():
            row = session.scalar(
                select(IntegrationQuarantineRecordORM)
                .where(IntegrationQuarantineRecordORM.quarantine_id == quarantine_id)
                .with_for_update()
            )
            if row is None:
                return None
            if row.status != "open":
                raise ValueError("quarantine_record_is_already_resolved")
            row.status = status
            row.resolved_by = resolved_by
            row.resolution_note = resolution_note
            row.resolved_at = datetime.now(tz=timezone.utc)
            session.flush()
            return _quarantine_model(row)

    def append_integration_audit(
        self,
        *,
        tenant_id: str,
        action: str,
        actor_id: str,
        asset_type: str | None = None,
        asset_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> IntegrationAuditEvent:
        now = datetime.now(tz=timezone.utc)
        event_id = hashlib.sha256(
            f"{tenant_id}|{action}|{actor_id}|{now.isoformat()}".encode("utf-8")
        ).hexdigest()
        event = IntegrationAuditEvent(
            event_id=event_id,
            tenant_id=tenant_id,
            action=action,
            asset_type=asset_type,
            asset_id=asset_id,
            actor_id=actor_id,
            details=details or {},
            created_at=now,
        )
        with self._lock, self.session() as session, session.begin():
            session.add(
                IntegrationAuditRecordORM(
                    event_id=event.event_id,
                    tenant_id=event.tenant_id,
                    action=event.action,
                    asset_type=event.asset_type,
                    asset_id=event.asset_id,
                    actor_id=event.actor_id,
                    details=event.details,
                    created_at=event.created_at,
                )
            )
        return event

    def list_integration_audit(
        self, tenant_id: str, *, limit: int = 200
    ) -> list[IntegrationAuditEvent]:
        with self.session() as session:
            rows = list(
                session.scalars(
                    select(IntegrationAuditRecordORM)
                    .where(IntegrationAuditRecordORM.tenant_id == tenant_id)
                    .order_by(IntegrationAuditRecordORM.created_at.desc())
                    .limit(limit)
                )
            )
            return [
                IntegrationAuditEvent(
                    event_id=row.event_id,
                    tenant_id=row.tenant_id,
                    action=row.action,
                    asset_type=row.asset_type,
                    asset_id=row.asset_id,
                    actor_id=row.actor_id,
                    details=row.details,
                    created_at=_aware(row.created_at),
                )
                for row in rows
            ]

    def export_runtime_state(self) -> dict[str, list[dict[str, Any]]]:
        models = {
            "cdc_events": CdcEventRecord,
            "cdc_checkpoints": CdcCheckpointRecord,
            "solve_jobs": SolveJobRecordORM,
            "shadow_cases": ShadowCaseRecordORM,
            "execution_receipts": ExecutionReceiptRecordORM,
            "evidence_records": RuntimeEvidenceRecordORM,
            "integration_assets": IntegrationAssetRecordORM,
            "integration_quarantine": IntegrationQuarantineRecordORM,
            "integration_audit_events": IntegrationAuditRecordORM,
        }
        result: dict[str, list[dict[str, Any]]] = {}
        with self.session() as session:
            for name, model in models.items():
                rows = list(session.scalars(select(model)))
                result[name] = [
                    {column.name: _json_value(getattr(row, column.name)) for column in model.__table__.columns}
                    for row in rows
                ]
        return result

    def clear_runtime_state(self) -> None:
        with self._lock, self.session() as session, session.begin():
            for model in (
                IntegrationAuditRecordORM,
                IntegrationQuarantineRecordORM,
                IntegrationAssetRecordORM,
                ExecutionReceiptRecordORM,
                ShadowCaseRecordORM,
                RuntimeEvidenceRecordORM,
                SolveJobRecordORM,
                CdcEventRecord,
                CdcCheckpointRecord,
            ):
                session.query(model).delete()

    def import_runtime_state(
        self,
        state: dict[str, list[dict[str, Any]]],
        *,
        clear_existing: bool = True,
    ) -> None:
        models = {
            "cdc_events": CdcEventRecord,
            "cdc_checkpoints": CdcCheckpointRecord,
            "solve_jobs": SolveJobRecordORM,
            "shadow_cases": ShadowCaseRecordORM,
            "execution_receipts": ExecutionReceiptRecordORM,
            "evidence_records": RuntimeEvidenceRecordORM,
            "integration_assets": IntegrationAssetRecordORM,
            "integration_quarantine": IntegrationQuarantineRecordORM,
            "integration_audit_events": IntegrationAuditRecordORM,
        }
        with self._lock, self.session() as session, session.begin():
            if clear_existing:
                for model in (
                    IntegrationAuditRecordORM,
                    IntegrationQuarantineRecordORM,
                    IntegrationAssetRecordORM,
                    ExecutionReceiptRecordORM,
                    ShadowCaseRecordORM,
                    RuntimeEvidenceRecordORM,
                    SolveJobRecordORM,
                    CdcEventRecord,
                    CdcCheckpointRecord,
                ):
                    session.query(model).delete()
            for name, model in models.items():
                columns = {column.name: column for column in model.__table__.columns}
                for item in state.get(name, []):
                    values: dict[str, Any] = {}
                    for key, value in item.items():
                        column = columns.get(key)
                        if column is None:
                            continue
                        if value is not None and isinstance(column.type, DateTime):
                            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                        values[key] = value
                    session.add(model(**values))


def _job_orm(record: SolveJobRecord) -> SolveJobRecordORM:
    return SolveJobRecordORM(
        job_id=record.job_id,
        tenant_id=record.tenant_id,
        idempotency_key=record.idempotency_key,
        status=record.status,
        priority=record.priority,
        attempt=record.attempt,
        solve_request=record.solve_request.model_dump(mode="json"),
        result=record.result.model_dump(mode="json") if record.result else None,
        checkpoint=record.checkpoint,
        lease_owner=record.lease_owner,
        lease_expires_at=record.lease_expires_at,
        heartbeat_at=record.heartbeat_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        error=record.error,
    )


def _integration_asset_key(
    tenant_id: str, asset_type: str, asset_id: str, version: str
) -> str:
    return hashlib.sha256(
        f"{tenant_id}|{asset_type}|{asset_id}|{version}".encode("utf-8")
    ).hexdigest()


def _integration_asset_model(row: IntegrationAssetRecordORM) -> VersionedAssetRecord:
    return VersionedAssetRecord(
        tenant_id=row.tenant_id,
        asset_type=row.asset_type,
        asset_id=row.asset_id,
        scope_key=row.scope_key,
        version=row.version,
        status=row.status,
        payload=row.payload,
        fingerprint=row.fingerprint,
        created_by=row.created_by,
        approved_by=row.approved_by,
        created_at=_aware(row.created_at),
        activated_at=_aware(row.activated_at) if row.activated_at else None,
    )


def _quarantine_model(row: IntegrationQuarantineRecordORM) -> QuarantineRecord:
    return QuarantineRecord(
        quarantine_id=row.quarantine_id,
        tenant_id=row.tenant_id,
        connector_id=row.connector_id,
        source_system=row.source_system,
        entity_type=row.entity_type,
        schema_version=row.schema_version,
        status=row.status,
        reason_codes=list(row.reason_codes or []),
        observation=row.observation,
        fingerprint=row.fingerprint,
        observed_at=_aware(row.observed_at),
        resolved_at=_aware(row.resolved_at) if row.resolved_at else None,
        resolved_by=row.resolved_by,
        resolution_note=row.resolution_note,
    )


def _job_model(row: SolveJobRecordORM) -> SolveJobRecord:
    return SolveJobRecord(
        job_id=row.job_id,
        tenant_id=row.tenant_id,
        idempotency_key=row.idempotency_key,
        status=row.status,
        priority=row.priority,
        attempt=row.attempt,
        solve_request=row.solve_request,
        result=row.result,
        checkpoint=row.checkpoint or {},
        lease_owner=row.lease_owner,
        lease_expires_at=_aware(row.lease_expires_at) if row.lease_expires_at else None,
        heartbeat_at=_aware(row.heartbeat_at) if row.heartbeat_at else None,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
        error=row.error,
    )


def _missing_sequences(committed: int, pending: list[int]) -> list[int]:
    if not pending:
        return []
    pending_set = set(pending)
    return [
        sequence
        for sequence in range(committed + 1, max(pending) + 1)
        if sequence not in pending_set
    ][:100]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    return value
