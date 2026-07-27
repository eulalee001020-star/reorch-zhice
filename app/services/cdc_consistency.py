"""Gap-aware CDC ingestion and cross-system as-of materialization."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.models.production_runtime import (
    AsOfSnapshotRequest,
    AsOfSnapshotResponse,
    CdcEvent,
    CdcIngestResult,
    SourceWatermark,
)
from app.services.operational_store import RelationalOperationalStore


class CdcConsistencyService:
    """Commit only contiguous source sequences and fail closed on stale cuts."""

    def __init__(self, store: RelationalOperationalStore) -> None:
        self._store = store

    def ingest(self, event: CdcEvent) -> CdcIngestResult:
        checksum = _event_checksum(event)
        if event.checksum and event.checksum != checksum:
            checkpoint = self._store.get_checkpoint(
                event.tenant_id, event.source_system, event.partition_key
            )
            committed = checkpoint.committed_sequence if checkpoint else 0
            watermark = _aware(checkpoint.watermark_at) if checkpoint and checkpoint.watermark_at else None
            return CdcIngestResult(
                event_id=event.event_id,
                status="checksum_rejected",
                committed_sequence=committed,
                watermark_at=watermark,
                gap_sequences=[],
                checkpoint_token=(
                    checkpoint.checkpoint_token
                    if checkpoint
                    else _checkpoint_token(
                        event.tenant_id,
                        event.source_system,
                        event.partition_key,
                        0,
                        None,
                    )
                ),
                reason="payload_checksum_mismatch",
            )
        status, checkpoint, gaps, reason = self._store.apply_cdc_event(
            event, checksum, _checkpoint_token
        )
        return CdcIngestResult(
            event_id=event.event_id,
            status=status,
            committed_sequence=checkpoint.committed_sequence,
            watermark_at=_aware(checkpoint.watermark_at) if checkpoint.watermark_at else None,
            gap_sequences=gaps,
            checkpoint_token=checkpoint.checkpoint_token,
            reason=reason,
        )

    def watermark(
        self, tenant_id: str, source_system: str, partition_key: str = "default"
    ) -> SourceWatermark:
        row = self._store.get_checkpoint(tenant_id, source_system, partition_key)
        if row is None:
            return SourceWatermark(
                tenant_id=tenant_id,
                source_system=source_system,
                partition_key=partition_key,
                committed_sequence=0,
                watermark_at=None,
                checkpoint_token=_checkpoint_token(
                    tenant_id, source_system, partition_key, 0, None
                ),
                gap_sequences=[],
            )
        pending = self._store.pending_sequences(
            tenant_id, source_system, partition_key, row.committed_sequence
        )
        return SourceWatermark(
            tenant_id=tenant_id,
            source_system=source_system,
            partition_key=partition_key,
            committed_sequence=row.committed_sequence,
            watermark_at=_aware(row.watermark_at) if row.watermark_at else None,
            checkpoint_token=row.checkpoint_token,
            gap_sequences=_missing_sequences(row.committed_sequence, pending),
        )

    def materialize_as_of(
        self, request: AsOfSnapshotRequest
    ) -> AsOfSnapshotResponse:
        watermarks = [
            self.watermark(request.tenant_id, source, request.partition_key)
            for source in request.required_sources
        ]
        blockers: list[str] = []
        for watermark in watermarks:
            if watermark.committed_sequence == 0 or watermark.watermark_at is None:
                blockers.append(f"missing_source_checkpoint:{watermark.source_system}")
            elif watermark.watermark_at < request.as_of:
                lag = int((request.as_of - watermark.watermark_at).total_seconds())
                blockers.append(f"source_watermark_stale:{watermark.source_system}:{lag}s")
            if watermark.gap_sequences:
                blockers.append(
                    f"source_sequence_gap:{watermark.source_system}:"
                    + ",".join(str(item) for item in watermark.gap_sequences[:10])
                )
        available_times = [item.watermark_at for item in watermarks if item.watermark_at]
        if len(available_times) == len(watermarks) and available_times:
            skew = int((max(available_times) - min(available_times)).total_seconds())
            if skew > request.max_source_skew_seconds:
                blockers.append(f"cross_source_watermark_skew:{skew}s")

        entities: dict[str, dict[str, Any]] = {}
        if not blockers:
            rows = self._store.committed_events_as_of(
                request.tenant_id,
                request.required_sources,
                request.partition_key,
                request.as_of,
            )
            for row in rows:
                source_entities = entities.setdefault(row.source_system, {})
                entity_key = f"{row.entity_type}:{row.entity_id}"
                if row.operation == "delete":
                    source_entities.pop(entity_key, None)
                else:
                    source_entities[entity_key] = {
                        "payload": row.payload,
                        "source_sequence": row.sequence,
                        "occurred_at": _aware(row.occurred_at).isoformat(),
                        "event_id": row.event_id,
                        "checksum": row.checksum,
                    }
            for source in request.required_sources:
                entities.setdefault(source, {})

        fingerprint = _fingerprint(
            {
                "tenant_id": request.tenant_id,
                "as_of": request.as_of.isoformat(),
                "watermarks": [item.model_dump(mode="json") for item in watermarks],
                "entities": entities,
                "blockers": blockers,
            }
        )
        return AsOfSnapshotResponse(
            status="blocked" if blockers else "consistent",
            tenant_id=request.tenant_id,
            as_of=request.as_of,
            source_watermarks=watermarks,
            entities=entities,
            blockers=blockers,
            snapshot_fingerprint=fingerprint,
            claim_boundary=(
                "The snapshot is complete only through contiguous committed source "
                "sequences and the requested as-of cut; later events are excluded."
            ),
        )


def _event_checksum(event: CdcEvent) -> str:
    payload = event.model_dump(mode="json", exclude={"checksum"})
    return _fingerprint(payload)


def _checkpoint_token(
    tenant_id: str,
    source_system: str,
    partition_key: str,
    sequence: int,
    watermark_at: datetime | None,
) -> str:
    return _fingerprint(
        {
            "tenant_id": tenant_id,
            "source_system": source_system,
            "partition_key": partition_key,
            "sequence": sequence,
            "watermark_at": watermark_at.isoformat() if watermark_at else None,
        }
    )


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _missing_sequences(committed: int, pending: list[int]) -> list[int]:
    if not pending:
        return []
    pending_set = set(pending)
    return [
        number
        for number in range(committed + 1, max(pending) + 1)
        if number not in pending_set
    ][:100]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
