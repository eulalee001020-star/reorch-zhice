"""Anomaly Intake Center — unified anomaly event intake, standardization,
deduplication, severity classification, and stream publishing.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.core.config import settings
from app.core.kafka_producer import KafkaProducer
from app.core.kafka_topics import TOPIC_INCIDENTS_CREATED
from app.core.redis_client import RedisClient
from app.models.enums import (
    IncidentSeverity,
    IncidentStatus,
    ReportSource,
)
from app.models.incident import Incident, IncidentCreateRequest

logger = logging.getLogger(__name__)

# Allowed report sources — events from unlisted sources are rejected (Req 1.6)
ALLOWED_SOURCES: set[str] = {s.value for s in ReportSource}

# Required fields for intake validation (Req 1.5)
_REQUIRED_FIELDS: list[str] = ["incident_type", "resource_id", "occurred_at"]

# Deduplication window in seconds (Req 1.3)
_DEDUP_WINDOW_SECONDS: int = 600  # 10 minutes

# Redis key prefix for deduplication tracking
_DEDUP_KEY_PREFIX: str = "aic:dedup:"


class IntakeSeverityClassifier:
    """Intake Severity classifier.

    Classifies based on resource criticality only — does not depend on
    downstream impact analysis results.

    P1-Critical: bottleneck device or high-risk configuration
    P2-High:     critical resource with ≥3 active work orders
    P3-Medium:   general resource with 1-2 active work orders
    P4-Low:      non-critical resource with redundancy backup
    """

    def classify(
        self,
        resource_id: str,
        resource_criticality: str,
        is_bottleneck: bool,
        has_redundancy: bool,
        active_work_order_count: int,
    ) -> IncidentSeverity:
        if is_bottleneck or resource_criticality == "high_risk_config":
            return IncidentSeverity.P1_CRITICAL
        if resource_criticality == "critical" and active_work_order_count >= 3:
            return IncidentSeverity.P2_HIGH
        if resource_criticality == "general" and 1 <= active_work_order_count <= 2:
            return IncidentSeverity.P3_MEDIUM
        if resource_criticality == "non_critical" and has_redundancy:
            return IncidentSeverity.P4_LOW
        return IncidentSeverity.P3_MEDIUM  # default fallback


class IntakeValidationError(Exception):
    """Raised when an incoming event fails intake validation."""

    def __init__(self, missing_fields: list[str] | None = None, reason: str | None = None):
        self.missing_fields = missing_fields or []
        self.reason = reason or "Validation failed"
        super().__init__(self.reason)


class SourceNotAllowedError(Exception):
    """Raised when the report source is not in the allowed sources list."""

    def __init__(self, source: str):
        self.source = source
        super().__init__(f"Report source not allowed: {source}")


class AnomalyIntakeCenter:
    """Anomaly Intake Center: receive, standardize, deduplicate,
    classify severity, and publish incidents.

    Dependencies:
    - RedisClient: for deduplication tracking (10-min window)
    - KafkaProducer: for publishing to ``incidents.created`` topic
    - IntakeSeverityClassifier: for severity classification
    - resource_info_provider: async callable returning resource metadata
    """

    def __init__(
        self,
        redis_client: RedisClient,
        kafka_producer: KafkaProducer,
        classifier: IntakeSeverityClassifier | None = None,
        resource_info_provider: Any = None,
    ) -> None:
        self._redis = redis_client
        self._kafka = kafka_producer
        self._classifier = classifier or IntakeSeverityClassifier()
        self._resource_info_provider = resource_info_provider

    # ── public API ──────────────────────────────────────────────────

    async def receive_event(self, request: IncidentCreateRequest) -> Incident:
        """Receive and standardize an anomaly event.

        1. Validate required fields (Req 1.5)
        2. Validate report source (Req 1.6)
        3. Classify severity (Req 1.4)
        4. Generate globally unique incident_id (Req 1.7)
        5. Deduplicate within 10-min window (Req 1.3)
        6. Publish to Kafka stream (Req 1.8)

        Returns the created (or deduplicated) Incident.
        """
        # --- Step 1: Validate required fields ---
        self._validate_required_fields(request)

        # --- Step 2: Validate report source ---
        self._validate_source(request.report_source)

        # --- Step 3: Classify severity ---
        resource_info = await self._get_resource_info(
            request.resource_id,
            request.raw_payload,
        )
        severity = self._classifier.classify(
            resource_id=request.resource_id,
            resource_criticality=resource_info.get("criticality", "general"),
            is_bottleneck=resource_info.get("is_bottleneck", False),
            has_redundancy=resource_info.get("has_redundancy", False),
            active_work_order_count=resource_info.get("active_work_order_count", 0),
        )
        raw_payload = dict(request.raw_payload or {})
        raw_payload["severity_evidence"] = _severity_evidence(
            resource_info=resource_info,
            severity=severity,
        )

        # --- Step 4: Create Incident with globally unique ID ---
        incident = Incident(
            incident_id=uuid4(),
            incident_type=request.incident_type,
            external_event_id=request.external_event_id,
            occurred_at=request.occurred_at,
            workshop_id=request.workshop_id,
            resource_id=request.resource_id,
            report_source=request.report_source,
            source_system=request.source_system,
            severity=severity,
            status=IncidentStatus.PENDING_ANALYSIS,
            description=request.description,
            idempotency_key=request.idempotency_key,
            raw_payload=raw_payload,
            created_at=datetime.now(tz=timezone.utc),
        )

        # --- Step 5: Deduplicate ---
        incident = await self.deduplicate(incident)

        # --- Step 6: Publish to stream ---
        await self.publish_to_stream(incident)

        return incident

    async def deduplicate(self, incident: Incident) -> Incident:
        """Deduplicate within a 10-minute window for the same resource.

        If a prior incident exists for the same resource_id within the window,
        the new event is merged into the existing one: the existing incident's
        ``deduplicated_from`` list gains the new incident's ID, and the
        existing incident is returned as the primary event.
        """
        dedup_key = f"{_DEDUP_KEY_PREFIX}{incident.resource_id}"

        existing_data = await self._redis.get(dedup_key)
        if existing_data is not None:
            # A primary incident already exists — merge into it
            primary = Incident.model_validate(existing_data)
            # Use the incident_id field; with use_enum_values it's already a string/UUID
            new_id = incident.incident_id
            if isinstance(new_id, str):
                new_id = UUID(new_id)
            if new_id not in [
                UUID(str(eid)) for eid in primary.deduplicated_from
            ]:
                primary.deduplicated_from.append(new_id)

            # Update Redis with the merged primary
            await self._redis.set(
                dedup_key,
                primary.model_dump(mode="json"),
                ttl=_DEDUP_WINDOW_SECONDS,
            )
            logger.info(
                "Deduplicated incident %s into primary %s for resource %s",
                incident.incident_id,
                primary.incident_id,
                incident.resource_id,
            )
            return primary

        # No existing incident — this becomes the primary
        await self._redis.set(
            dedup_key,
            incident.model_dump(mode="json"),
            ttl=_DEDUP_WINDOW_SECONDS,
        )
        return incident

    async def publish_to_stream(self, incident: Incident) -> None:
        """Publish an Incident to the Kafka ``incidents.created`` topic."""
        payload = incident.model_dump(mode="json")
        await self._kafka.send(
            topic=TOPIC_INCIDENTS_CREATED,
            value=payload,
            key=incident.resource_id,
        )
        logger.info(
            "Published incident %s to %s",
            incident.incident_id,
            TOPIC_INCIDENTS_CREATED,
        )

    # ── private helpers ─────────────────────────────────────────────

    @staticmethod
    def _validate_required_fields(request: IncidentCreateRequest) -> None:
        """Reject events missing required fields (Req 1.5)."""
        missing: list[str] = []
        for field_name in _REQUIRED_FIELDS:
            value = getattr(request, field_name, None)
            if value is None:
                missing.append(field_name)
        if missing:
            raise IntakeValidationError(
                missing_fields=missing,
                reason=f"Missing required fields: {', '.join(missing)}",
            )

    @staticmethod
    def _validate_source(source: str | ReportSource) -> None:
        """Reject events from unregistered sources and log audit (Req 1.6)."""
        source_value = source.value if isinstance(source, ReportSource) else str(source)
        if source_value not in ALLOWED_SOURCES:
            logger.warning(
                "SECURITY_AUDIT: Rejected event from unregistered source: %s",
                source_value,
            )
            raise SourceNotAllowedError(source_value)

    async def _get_resource_info(
        self,
        resource_id: str,
        raw_payload: dict | None = None,
    ) -> dict[str, Any]:
        """Retrieve resource metadata for severity classification.

        If a ``resource_info_provider`` callable was injected, delegate to it.
        Otherwise return sensible defaults so the service remains functional
        without an external resource registry.
        """
        if raw_payload and isinstance(raw_payload.get("resource_info"), dict):
            return _normalize_resource_info(raw_payload["resource_info"])
        if self._resource_info_provider is not None:
            return _normalize_resource_info(await self._resource_info_provider(resource_id))
        # Default: general resource, no bottleneck, no redundancy, 0 work orders
        return {
            "criticality": "general",
            "is_bottleneck": False,
            "has_redundancy": False,
            "active_work_order_count": 0,
        }


def _normalize_resource_info(resource_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "criticality": resource_info.get("criticality", "general"),
        "is_bottleneck": bool(resource_info.get("is_bottleneck", False)),
        "has_redundancy": bool(resource_info.get("has_redundancy", False)),
        "active_work_order_count": int(resource_info.get("active_work_order_count", 0) or 0),
    }


def _severity_evidence(
    *,
    resource_info: dict[str, Any],
    severity: IncidentSeverity,
) -> dict[str, Any]:
    criticality = resource_info.get("criticality", "general")
    is_bottleneck = bool(resource_info.get("is_bottleneck", False))
    has_redundancy = bool(resource_info.get("has_redundancy", False))
    active_count = int(resource_info.get("active_work_order_count", 0) or 0)

    if is_bottleneck or criticality == "high_risk_config":
        rule = "瓶颈设备或高风险配置 -> P1-Critical"
    elif criticality == "critical" and active_count >= 3:
        rule = "关键资源且活跃工单数 >= 3 -> P2-High"
    elif criticality == "general" and 1 <= active_count <= 2:
        rule = "一般资源且活跃工单数为 1-2 -> P3-Medium"
    elif criticality == "non_critical" and has_redundancy:
        rule = "非关键资源且有冗余备份 -> P4-Low"
    else:
        rule = "资源信息不足或未命中特定规则 -> P3-Medium 默认兜底"

    return {
        "classified_severity": severity.value if hasattr(severity, "value") else str(severity),
        "resource_criticality": criticality,
        "is_bottleneck": is_bottleneck,
        "has_redundancy": has_redundancy,
        "active_work_order_count": active_count,
        "classification_rule": rule,
    }
