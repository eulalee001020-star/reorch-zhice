"""IoT Event Intake Adapter — Kafka consumer for IoT platform anomaly events.

Validates: Requirements 1.1, 18.2

Consumes anomaly events from IoT platforms via Kafka and forwards
them to the Anomaly Intake Center for processing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Default Kafka topic for IoT events
IOT_EVENTS_TOPIC = "iot.anomaly.events"


class IoTEvent:
    """Parsed IoT anomaly event."""

    def __init__(
        self,
        event_id: str,
        resource_id: str,
        event_type: str,
        occurred_at: datetime,
        severity: str | None = None,
        description: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        self.event_id = event_id
        self.resource_id = resource_id
        self.event_type = event_type
        self.occurred_at = occurred_at
        self.severity = severity
        self.description = description
        self.raw_payload = raw_payload or {}


class IoTAdapter:
    """Adapter for consuming IoT platform anomaly events.

    In production, this wraps a KafkaConsumer for the IoT events topic.
    For MVP, provides an in-memory event intake interface.
    """

    def __init__(
        self,
        event_handler: Callable[[IoTEvent], Awaitable[None]] | None = None,
    ) -> None:
        self._available = True
        self._event_handler = event_handler
        self._received_events: list[IoTEvent] = []
        self._running = False
        self._base_url = settings.integration.iot_base_url
        self._api_key = settings.integration.iot_api_key
        self._timeout = settings.integration.request_timeout_seconds

    @property
    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    # ── Event intake (Req 1.1) ─────────────────────────────────────

    async def receive_event(self, raw_payload: dict[str, Any]) -> IoTEvent | None:
        """Parse and process a raw IoT event payload.

        Converts the raw payload to an IoTEvent and forwards it to
        the registered event handler (typically AnomalyIntakeCenter).
        """
        event = self._parse_event(raw_payload)
        if event is None:
            logger.warning("Failed to parse IoT event: %s", raw_payload)
            return None

        self._received_events.append(event)

        if self._event_handler is not None:
            await self._event_handler(event)

        logger.info(
            "IoT event received: %s resource=%s type=%s",
            event.event_id, event.resource_id, event.event_type,
        )
        return event

    # ── Customer intake / Kafka consumer control (Req 18.2) ─────────

    async def start_consuming(self) -> None:
        """Start consuming from IoT Kafka topic.

        PoC mode marks the adapter as running. With a configured customer HTTP
        endpoint, this performs a lightweight health pull so deployment errors
        surface early.
        """
        self._running = True
        if self._base_url:
            await self._fetch_json(settings.integration.iot_health_path)
        logger.info("IoT adapter started consuming from %s", IOT_EVENTS_TOPIC)

    async def stop_consuming(self) -> None:
        """Stop the Kafka consumer loop."""
        self._running = False
        logger.info("IoT adapter stopped consuming")

    # ── Health check ───────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        remote_ok: bool | None = None
        if self._base_url:
            try:
                await self._fetch_json(settings.integration.iot_health_path)
                remote_ok = True
            except Exception:
                remote_ok = False
        return {
            "system": "IoT",
            "available": self._available,
            "mode": "customer_http" if self._base_url else "local_poc",
            "remote_ok": remote_ok,
            "consuming": self._running,
            "events_received": len(self._received_events),
        }

    # ── Internal parsing ───────────────────────────────────────────

    @staticmethod
    def _parse_event(raw: dict[str, Any]) -> IoTEvent | None:
        """Parse raw IoT payload into an IoTEvent."""
        try:
            event_id = raw.get("event_id") or raw.get("id", "")
            resource_id = raw.get("resource_id") or raw.get("device_id", "")
            event_type = raw.get("event_type") or raw.get("type", "equipment_failure")
            occurred_at_raw = raw.get("occurred_at") or raw.get("timestamp")

            if not resource_id:
                return None

            if isinstance(occurred_at_raw, str):
                occurred_at = datetime.fromisoformat(occurred_at_raw)
            elif isinstance(occurred_at_raw, datetime):
                occurred_at = occurred_at_raw
            else:
                occurred_at = datetime.now(tz=timezone.utc)

            return IoTEvent(
                event_id=event_id,
                resource_id=resource_id,
                event_type=event_type,
                occurred_at=occurred_at,
                severity=raw.get("severity"),
                description=raw.get("description"),
                raw_payload=raw,
            )
        except Exception as exc:
            logger.error("Failed to parse IoT event: %s", exc)
            return None

    async def _fetch_json(self, path: str) -> Any:
        headers = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=headers,
        ) as client:
            response = await client.get(path)
        response.raise_for_status()
        return response.json()
