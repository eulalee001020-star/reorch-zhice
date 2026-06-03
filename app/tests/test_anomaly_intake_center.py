"""Tests for AnomalyIntakeCenter service.

Covers: field validation, source validation, severity classification,
deduplication, Kafka publishing, and unique incident_id generation.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ReportSource,
)
from app.models.incident import Incident, IncidentCreateRequest
from app.services.anomaly_intake_center import (
    ALLOWED_SOURCES,
    AnomalyIntakeCenter,
    IntakeSeverityClassifier,
    IntakeValidationError,
    SourceNotAllowedError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_request(**overrides: Any) -> IncidentCreateRequest:
    """Helper to build a valid IncidentCreateRequest with optional overrides."""
    defaults: dict[str, Any] = {
        "incident_type": IncidentType.EQUIPMENT_FAILURE,
        "occurred_at": datetime(2024, 6, 15, 8, 30, 0, tzinfo=timezone.utc),
        "resource_id": "CNC-001",
        "report_source": ReportSource.MES,
        "description": "Spindle overheat",
    }
    defaults.update(overrides)
    return IncidentCreateRequest(**defaults)


class FakeRedisClient:
    """In-memory Redis stand-in for testing."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> Any | None:
        raw = self._store.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._store[key] = json.dumps(value, default=str)

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None


class FakeKafkaProducer:
    """Records messages instead of sending to Kafka."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send(
        self,
        topic: str,
        value: Any,
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.messages.append({"topic": topic, "value": value, "key": key})


@pytest.fixture
def redis_client() -> FakeRedisClient:
    return FakeRedisClient()


@pytest.fixture
def kafka_producer() -> FakeKafkaProducer:
    return FakeKafkaProducer()


@pytest.fixture
def default_resource_provider():
    """Returns a resource info provider that yields 'general' defaults."""
    async def provider(resource_id: str) -> dict[str, Any]:
        return {
            "criticality": "general",
            "is_bottleneck": False,
            "has_redundancy": False,
            "active_work_order_count": 0,
        }
    return provider


def _make_center(
    redis: FakeRedisClient,
    kafka: FakeKafkaProducer,
    resource_provider=None,
) -> AnomalyIntakeCenter:
    return AnomalyIntakeCenter(
        redis_client=redis,
        kafka_producer=kafka,
        resource_info_provider=resource_provider,
    )


# ---------------------------------------------------------------------------
# IntakeSeverityClassifier tests (Req 1.4)
# ---------------------------------------------------------------------------

class TestIntakeSeverityClassifier:
    """Test the four-level severity classification rules."""

    def setup_method(self):
        self.classifier = IntakeSeverityClassifier()

    def test_p1_bottleneck(self):
        result = self.classifier.classify(
            resource_id="CNC-001",
            resource_criticality="general",
            is_bottleneck=True,
            has_redundancy=False,
            active_work_order_count=0,
        )
        assert result == IncidentSeverity.P1_CRITICAL

    def test_p1_high_risk_config(self):
        result = self.classifier.classify(
            resource_id="CNC-002",
            resource_criticality="high_risk_config",
            is_bottleneck=False,
            has_redundancy=False,
            active_work_order_count=1,
        )
        assert result == IncidentSeverity.P1_CRITICAL

    def test_p2_critical_with_3_or_more_orders(self):
        result = self.classifier.classify(
            resource_id="CNC-003",
            resource_criticality="critical",
            is_bottleneck=False,
            has_redundancy=False,
            active_work_order_count=3,
        )
        assert result == IncidentSeverity.P2_HIGH

    def test_p2_critical_with_5_orders(self):
        result = self.classifier.classify(
            resource_id="CNC-003",
            resource_criticality="critical",
            is_bottleneck=False,
            has_redundancy=False,
            active_work_order_count=5,
        )
        assert result == IncidentSeverity.P2_HIGH

    def test_p3_general_with_1_order(self):
        result = self.classifier.classify(
            resource_id="CNC-004",
            resource_criticality="general",
            is_bottleneck=False,
            has_redundancy=False,
            active_work_order_count=1,
        )
        assert result == IncidentSeverity.P3_MEDIUM

    def test_p3_general_with_2_orders(self):
        result = self.classifier.classify(
            resource_id="CNC-004",
            resource_criticality="general",
            is_bottleneck=False,
            has_redundancy=False,
            active_work_order_count=2,
        )
        assert result == IncidentSeverity.P3_MEDIUM

    def test_p4_non_critical_with_redundancy(self):
        result = self.classifier.classify(
            resource_id="CNC-005",
            resource_criticality="non_critical",
            is_bottleneck=False,
            has_redundancy=True,
            active_work_order_count=0,
        )
        assert result == IncidentSeverity.P4_LOW

    def test_default_fallback_to_p3(self):
        """Unmatched combinations fall back to P3-Medium."""
        result = self.classifier.classify(
            resource_id="CNC-006",
            resource_criticality="unknown",
            is_bottleneck=False,
            has_redundancy=False,
            active_work_order_count=10,
        )
        assert result == IncidentSeverity.P3_MEDIUM

    def test_critical_with_2_orders_falls_to_default(self):
        """critical + 2 orders doesn't match P2 (needs >=3)."""
        result = self.classifier.classify(
            resource_id="CNC-007",
            resource_criticality="critical",
            is_bottleneck=False,
            has_redundancy=False,
            active_work_order_count=2,
        )
        assert result == IncidentSeverity.P3_MEDIUM


# ---------------------------------------------------------------------------
# Source validation tests (Req 1.6)
# ---------------------------------------------------------------------------

class TestSourceValidation:
    def test_allowed_sources_match_enum(self):
        assert ALLOWED_SOURCES == {"MES", "IoT", "manual"}

    def test_valid_source_accepted(self):
        """No exception for valid sources."""
        AnomalyIntakeCenter._validate_source(ReportSource.MES)
        AnomalyIntakeCenter._validate_source(ReportSource.IOT)
        AnomalyIntakeCenter._validate_source(ReportSource.MANUAL)

    def test_invalid_source_rejected(self):
        with pytest.raises(SourceNotAllowedError) as exc_info:
            AnomalyIntakeCenter._validate_source("UNKNOWN_SYSTEM")
        assert "UNKNOWN_SYSTEM" in str(exc_info.value)


# ---------------------------------------------------------------------------
# receive_event tests (Req 1.1, 1.2, 1.5, 1.7)
# ---------------------------------------------------------------------------

class TestReceiveEvent:
    @pytest.mark.asyncio
    async def test_successful_receive(self, redis_client, kafka_producer):
        center = _make_center(redis_client, kafka_producer)
        request = _make_request()

        incident = await center.receive_event(request)

        assert isinstance(incident.incident_id, (UUID, str))
        assert incident.resource_id == "CNC-001"
        assert incident.status in (
            IncidentStatus.PENDING_ANALYSIS,
            IncidentStatus.PENDING_ANALYSIS.value,
        )
        # Kafka message published
        assert len(kafka_producer.messages) == 1
        assert kafka_producer.messages[0]["topic"] == "incidents.created"

    @pytest.mark.asyncio
    async def test_unique_incident_ids(self, redis_client, kafka_producer):
        """Each call generates a globally unique incident_id (Req 1.7)."""
        center = _make_center(redis_client, kafka_producer)
        # Use different resources to avoid dedup
        r1 = _make_request(resource_id="R-001")
        r2 = _make_request(resource_id="R-002")

        i1 = await center.receive_event(r1)
        i2 = await center.receive_event(r2)

        assert str(i1.incident_id) != str(i2.incident_id)

    @pytest.mark.asyncio
    async def test_severity_classification_via_provider(self, redis_client, kafka_producer):
        """Severity is classified using resource info (Req 1.4)."""
        async def bottleneck_provider(resource_id: str):
            return {
                "criticality": "general",
                "is_bottleneck": True,
                "has_redundancy": False,
                "active_work_order_count": 0,
            }

        center = _make_center(redis_client, kafka_producer, bottleneck_provider)
        incident = await center.receive_event(_make_request())

        assert incident.severity in (
            IncidentSeverity.P1_CRITICAL,
            IncidentSeverity.P1_CRITICAL.value,
        )

    @pytest.mark.asyncio
    async def test_raw_payload_resource_info_creates_severity_evidence(
        self,
        redis_client,
        kafka_producer,
    ):
        """Structured frontend/MES input records why severity was assigned."""
        center = _make_center(redis_client, kafka_producer)
        incident = await center.receive_event(
            _make_request(
                raw_payload={
                    "resource_info": {
                        "criticality": "critical",
                        "is_bottleneck": False,
                        "has_redundancy": False,
                        "active_work_order_count": 3,
                    }
                }
            )
        )

        assert incident.severity in (
            IncidentSeverity.P2_HIGH,
            IncidentSeverity.P2_HIGH.value,
        )
        evidence = incident.raw_payload["severity_evidence"]
        assert evidence["classified_severity"] == IncidentSeverity.P2_HIGH.value
        assert evidence["resource_criticality"] == "critical"
        assert evidence["active_work_order_count"] == 3
        assert "P2-High" in evidence["classification_rule"]

    @pytest.mark.asyncio
    async def test_incident_has_correct_fields(self, redis_client, kafka_producer):
        """Created Incident contains all standardized fields (Req 1.2)."""
        center = _make_center(redis_client, kafka_producer)
        request = _make_request(description="Motor failure")
        incident = await center.receive_event(request)

        assert incident.incident_type in (
            IncidentType.EQUIPMENT_FAILURE,
            IncidentType.EQUIPMENT_FAILURE.value,
        )
        assert incident.resource_id == "CNC-001"
        assert incident.description == "Motor failure"
        assert incident.report_source in (
            ReportSource.MES,
            ReportSource.MES.value,
        )
        assert incident.severity is not None


# ---------------------------------------------------------------------------
# Deduplication tests (Req 1.3)
# ---------------------------------------------------------------------------

class TestDeduplication:
    @pytest.mark.asyncio
    async def test_first_event_becomes_primary(self, redis_client, kafka_producer):
        center = _make_center(redis_client, kafka_producer)
        incident = Incident(
            incident_id=uuid4(),
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            occurred_at=datetime.now(tz=timezone.utc),
            resource_id="CNC-010",
            report_source=ReportSource.MES,
            severity=IncidentSeverity.P3_MEDIUM,
        )

        result = await center.deduplicate(incident)
        assert str(result.incident_id) == str(incident.incident_id)
        assert result.deduplicated_from == []

    @pytest.mark.asyncio
    async def test_duplicate_merged_into_primary(self, redis_client, kafka_producer):
        center = _make_center(redis_client, kafka_producer)
        primary_id = uuid4()
        dup_id = uuid4()

        primary = Incident(
            incident_id=primary_id,
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            occurred_at=datetime.now(tz=timezone.utc),
            resource_id="CNC-010",
            report_source=ReportSource.MES,
            severity=IncidentSeverity.P3_MEDIUM,
        )
        duplicate = Incident(
            incident_id=dup_id,
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            occurred_at=datetime.now(tz=timezone.utc),
            resource_id="CNC-010",
            report_source=ReportSource.IOT,
            severity=IncidentSeverity.P3_MEDIUM,
        )

        # First event sets the primary
        await center.deduplicate(primary)
        # Second event for same resource merges
        result = await center.deduplicate(duplicate)

        assert str(result.incident_id) == str(primary_id)
        dedup_ids = [str(uid) for uid in result.deduplicated_from]
        assert str(dup_id) in dedup_ids

    @pytest.mark.asyncio
    async def test_different_resources_not_deduplicated(self, redis_client, kafka_producer):
        center = _make_center(redis_client, kafka_producer)
        i1 = Incident(
            incident_id=uuid4(),
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            occurred_at=datetime.now(tz=timezone.utc),
            resource_id="CNC-A",
            report_source=ReportSource.MES,
            severity=IncidentSeverity.P3_MEDIUM,
        )
        i2 = Incident(
            incident_id=uuid4(),
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            occurred_at=datetime.now(tz=timezone.utc),
            resource_id="CNC-B",
            report_source=ReportSource.MES,
            severity=IncidentSeverity.P3_MEDIUM,
        )

        r1 = await center.deduplicate(i1)
        r2 = await center.deduplicate(i2)

        assert str(r1.incident_id) == str(i1.incident_id)
        assert str(r2.incident_id) == str(i2.incident_id)


# ---------------------------------------------------------------------------
# Publish to stream tests (Req 1.8)
# ---------------------------------------------------------------------------

class TestPublishToStream:
    @pytest.mark.asyncio
    async def test_publish_sends_to_kafka(self, redis_client, kafka_producer):
        center = _make_center(redis_client, kafka_producer)
        incident = Incident(
            incident_id=uuid4(),
            incident_type=IncidentType.EQUIPMENT_FAILURE,
            occurred_at=datetime.now(tz=timezone.utc),
            resource_id="CNC-020",
            report_source=ReportSource.MES,
            severity=IncidentSeverity.P2_HIGH,
        )

        await center.publish_to_stream(incident)

        assert len(kafka_producer.messages) == 1
        msg = kafka_producer.messages[0]
        assert msg["topic"] == "incidents.created"
        assert msg["key"] == "CNC-020"
        assert "incident_id" in msg["value"]
