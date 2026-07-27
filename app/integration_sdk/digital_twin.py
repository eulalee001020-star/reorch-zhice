"""Deterministic Connector SDK implementation used for acceptance testing."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from app.integration_sdk.base import (
    ConnectorChangeBatch,
    ConnectorHealth,
    ConnectorRecord,
    ConnectorSnapshot,
    EnterpriseConnector,
    OutboxRetryProbe,
    ReconciliationResult,
    TargetState,
    WritebackCommand,
    WritebackReceipt,
)
from app.models.integration_control import (
    ConnectorEntitySchema,
    ConnectorFieldSchema,
    ConnectorManifest,
)
from app.services.integration_registry import fingerprint_payload


class DigitalTwinEnterpriseConnector(EnterpriseConnector):
    """In-memory ERP/MES-shaped connector with real CAS/idempotency behavior."""

    def __init__(
        self,
        connector_id: str = "dt-mes-connector",
        *,
        reference_time: datetime | None = None,
    ) -> None:
        self._manifest = ConnectorManifest(
            connector_id=connector_id,
            source_system="MES",
            connector_version="1.0.0",
            target_environment="sandbox",
            capabilities=[
                "health_check",
                "schema_discovery",
                "snapshot_read",
                "incremental_read",
                "sandbox_write",
                "receipt_read",
                "reconciliation",
                "compensation",
            ],
            entity_schemas={
                "operation": ConnectorEntitySchema(
                    fields={
                        "operation_id": ConnectorFieldSchema(data_type="string"),
                        "work_order_id": ConnectorFieldSchema(data_type="string"),
                        "resource_id": ConnectorFieldSchema(data_type="string"),
                        "status": ConnectorFieldSchema(data_type="string"),
                        "planned_start": ConnectorFieldSchema(data_type="datetime"),
                        "planned_end": ConnectorFieldSchema(data_type="datetime"),
                    }
                )
            },
            idempotent_writes=True,
            compare_and_swap=True,
            durable_outbox=True,
            execution_receipts=True,
            reconciliation=True,
            compensation=True,
        )
        occurred_at = reference_time or datetime(
            2026, 7, 12, 8, 0, tzinfo=timezone.utc
        )
        self._records = [
            ConnectorRecord(
                entity_type="operation",
                entity_id=f"OP-{index}",
                occurred_at=occurred_at,
                source_sequence=index,
                payload={
                    "operation_id": f"OP-{index}",
                    "work_order_id": f"WO-{(index + 1) // 2}",
                    "resource_id": f"M-{index}",
                    "status": "released",
                    "planned_start": occurred_at.isoformat(),
                    "planned_end": occurred_at.replace(hour=9).isoformat(),
                },
                lineage={
                    "source_system": "MES",
                    "source_record_id": f"MES-OP-{index}",
                    "observed_at": occurred_at.isoformat(),
                },
            )
            for index in range(1, 5)
        ]
        self._targets: dict[tuple[str, str], dict] = {
            (record.entity_type, record.entity_id): {
                "version": "1",
                "payload": deepcopy(record.payload),
            }
            for record in self._records
        }
        self._receipts: dict[str, WritebackReceipt] = {}
        self._receipt_before: dict[str, dict] = {}
        self._apply_counts: dict[str, int] = {}

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(healthy=True, latency_ms=1.2, details={"mode": "digital_twin"})

    def discover_schema(self) -> dict[str, dict[str, str]]:
        return {
            entity: {field: schema.data_type for field, schema in item.fields.items()}
            for entity, item in self._manifest.entity_schemas.items()
        }

    def read_snapshot(self) -> ConnectorSnapshot:
        return ConnectorSnapshot(
            records=deepcopy(self._records),
            captured_at=self._records[0].occurred_at,
            snapshot_token="dt-snapshot-v1",
        )

    def read_changes(self, cursor: str | None, limit: int) -> ConnectorChangeBatch:
        offset = int(cursor or "0")
        records = deepcopy(self._records[offset : offset + limit])
        next_offset = offset + len(records)
        return ConnectorChangeBatch(
            records=records,
            next_cursor=str(next_offset),
            has_more=next_offset < len(self._records),
        )

    def read_target(self, entity_type: str, entity_id: str) -> TargetState:
        key = (entity_type, entity_id)
        if key not in self._targets:
            raise KeyError("target_entity_not_found")
        target = self._targets[key]
        payload = deepcopy(target["payload"])
        return TargetState(
            entity_type=entity_type,
            entity_id=entity_id,
            version=str(target["version"]),
            payload=payload,
            state_hash=fingerprint_payload(payload),
        )

    def sandbox_write(self, command: WritebackCommand) -> WritebackReceipt:
        existing = self._receipts.get(command.idempotency_key)
        if existing is not None:
            return existing
        before = self.read_target(command.entity_type, command.entity_id)
        if command.expected_version != before.version:
            receipt = WritebackReceipt(
                receipt_id=f"dt-receipt-{uuid4().hex}",
                idempotency_key=command.idempotency_key,
                status="rejected",
                entity_type=command.entity_type,
                entity_id=command.entity_id,
                previous_version=before.version,
                target_version=before.version,
                before_hash=before.state_hash,
                after_hash=before.state_hash,
                reason="compare_and_swap_version_conflict",
            )
            self._receipts[command.idempotency_key] = receipt
            return receipt

        key = (command.entity_type, command.entity_id)
        self._receipt_before[command.idempotency_key] = {
            "version": before.version,
            "payload": deepcopy(before.payload),
        }
        updated = {**before.payload, **deepcopy(command.changes)}
        target_version = str(int(before.version) + 1)
        self._targets[key] = {"version": target_version, "payload": updated}
        receipt = WritebackReceipt(
            receipt_id=f"dt-receipt-{uuid4().hex}",
            idempotency_key=command.idempotency_key,
            status="applied",
            entity_type=command.entity_type,
            entity_id=command.entity_id,
            previous_version=before.version,
            target_version=target_version,
            before_hash=before.state_hash,
            after_hash=fingerprint_payload(updated),
        )
        self._receipts[command.idempotency_key] = receipt
        self._apply_counts[command.idempotency_key] = 1
        return receipt

    def get_receipt(self, idempotency_key: str) -> WritebackReceipt | None:
        return self._receipts.get(idempotency_key)

    def reconcile(self, receipt_id: str) -> ReconciliationResult:
        receipt = next(
            (item for item in self._receipts.values() if item.receipt_id == receipt_id),
            None,
        )
        if receipt is None:
            raise KeyError("receipt_not_found")
        target = self.read_target(receipt.entity_type, receipt.entity_id)
        return ReconciliationResult(
            receipt_id=receipt_id,
            matched=(
                receipt.status == "applied"
                and target.version == receipt.target_version
                and target.state_hash == receipt.after_hash
            ),
            target_version=target.version,
            target_hash=target.state_hash,
            reason=None if target.state_hash == receipt.after_hash else "target_state_mismatch",
        )

    def compensate(self, receipt_id: str) -> WritebackReceipt:
        receipt = next(
            (item for item in self._receipts.values() if item.receipt_id == receipt_id),
            None,
        )
        if receipt is None or receipt.status != "applied":
            raise ValueError("only_applied_receipts_can_be_compensated")
        before = self._receipt_before[receipt.idempotency_key]
        target = self.read_target(receipt.entity_type, receipt.entity_id)
        if target.version != receipt.target_version:
            raise ValueError("compensation_compare_and_swap_conflict")
        restored_version = str(int(target.version) + 1)
        self._targets[(receipt.entity_type, receipt.entity_id)] = {
            "version": restored_version,
            "payload": deepcopy(before["payload"]),
        }
        return WritebackReceipt(
            receipt_id=f"dt-comp-{uuid4().hex}",
            idempotency_key=f"compensate:{receipt.idempotency_key}",
            status="compensated",
            entity_type=receipt.entity_type,
            entity_id=receipt.entity_id,
            previous_version=target.version,
            target_version=restored_version,
            before_hash=target.state_hash,
            after_hash=fingerprint_payload(before["payload"]),
        )

    def probe_outbox_retry(self, command: WritebackCommand) -> OutboxRetryProbe:
        """Model one transport failure before the durable retry succeeds."""
        transient_failure_observed = True
        receipt = self.sandbox_write(command)
        replay = self.sandbox_write(command)
        return OutboxRetryProbe(
            transient_failure_observed=transient_failure_observed,
            retry_attempt_count=2,
            applied_count=self._apply_counts.get(command.idempotency_key, 0),
            final_receipt=replay if replay.receipt_id == receipt.receipt_id else receipt,
        )
