"""Stable Connector SDK protocol implemented by customer-system adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.integration_control import ConnectorManifest


class ConnectorHealth(ReOrchModel):
    healthy: bool
    checked_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    latency_ms: float = Field(ge=0.0)
    details: dict[str, Any] = Field(default_factory=dict)


class ConnectorRecord(ReOrchModel):
    entity_type: str
    entity_id: str
    occurred_at: datetime
    source_sequence: int = Field(ge=1)
    payload: dict[str, Any]
    lineage: dict[str, Any]


class ConnectorSnapshot(ReOrchModel):
    records: list[ConnectorRecord]
    captured_at: datetime
    snapshot_token: str


class ConnectorChangeBatch(ReOrchModel):
    records: list[ConnectorRecord]
    next_cursor: str
    has_more: bool


class TargetState(ReOrchModel):
    entity_type: str
    entity_id: str
    version: str
    payload: dict[str, Any]
    state_hash: str


class WritebackCommand(ReOrchModel):
    idempotency_key: str
    entity_type: str
    entity_id: str
    expected_version: str
    changes: dict[str, Any]
    target_environment: Literal["sandbox"] = "sandbox"


class WritebackReceipt(ReOrchModel):
    receipt_id: str
    idempotency_key: str
    status: Literal["applied", "rejected", "compensated"]
    entity_type: str
    entity_id: str
    previous_version: str
    target_version: str
    before_hash: str
    after_hash: str
    reason: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class ReconciliationResult(ReOrchModel):
    receipt_id: str
    matched: bool
    target_version: str
    target_hash: str
    reason: str | None = None


class OutboxRetryProbe(ReOrchModel):
    transient_failure_observed: bool
    retry_attempt_count: int = Field(ge=1)
    applied_count: int = Field(ge=0)
    final_receipt: WritebackReceipt


class EnterpriseConnector(ABC):
    """Connector contract; implementation code remains outside Agent control."""

    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> ConnectorHealth:
        raise NotImplementedError

    @abstractmethod
    def discover_schema(self) -> dict[str, dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def read_snapshot(self) -> ConnectorSnapshot:
        raise NotImplementedError

    @abstractmethod
    def read_changes(self, cursor: str | None, limit: int) -> ConnectorChangeBatch:
        raise NotImplementedError

    @abstractmethod
    def read_target(self, entity_type: str, entity_id: str) -> TargetState:
        raise NotImplementedError

    @abstractmethod
    def sandbox_write(self, command: WritebackCommand) -> WritebackReceipt:
        raise NotImplementedError

    @abstractmethod
    def get_receipt(self, idempotency_key: str) -> WritebackReceipt | None:
        raise NotImplementedError

    @abstractmethod
    def reconcile(self, receipt_id: str) -> ReconciliationResult:
        raise NotImplementedError

    @abstractmethod
    def compensate(self, receipt_id: str) -> WritebackReceipt:
        raise NotImplementedError

    @abstractmethod
    def probe_outbox_retry(self, command: WritebackCommand) -> OutboxRetryProbe:
        """Inject one transient failure, retry, and report actual apply count."""
        raise NotImplementedError
