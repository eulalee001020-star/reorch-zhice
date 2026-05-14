"""Async-friendly Kafka producer wrapper with JSON serialization.

Validates: Requirements 1.8, 18.2
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from confluent_kafka import KafkaError, KafkaException, Producer

from app.core.config import settings

logger = logging.getLogger(__name__)


class _JSONEncoder(json.JSONEncoder):
    """Handle UUID, datetime, and other non-serializable types."""

    def default(self, o: Any) -> Any:
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def _serialize_value(value: Any) -> bytes:
    return json.dumps(value, cls=_JSONEncoder, ensure_ascii=False).encode("utf-8")


def _serialize_key(key: str | None) -> bytes | None:
    if key is None:
        return None
    return key.encode("utf-8")


class KafkaProducer:
    """Thin async-friendly wrapper around confluent-kafka Producer.

    Usage::

        producer = KafkaProducer()
        await producer.send("incidents.created", value={"id": "..."}, key="resource-1")
        await producer.flush()
        producer.close()
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        base_config: dict[str, Any] = {
            "bootstrap.servers": settings.kafka.bootstrap_servers,
        }
        if config:
            base_config.update(config)
        self._producer = Producer(base_config)
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── public API ──────────────────────────────────────────────────

    async def send(
        self,
        topic: str,
        value: Any,
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Produce a message and wait for delivery confirmation."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()

        def _on_delivery(err: KafkaError | None, msg: Any) -> None:
            if err is not None:
                loop.call_soon_threadsafe(future.set_exception, KafkaException(err))
            else:
                loop.call_soon_threadsafe(future.set_result, None)

        kafka_headers = (
            [(k, v.encode("utf-8")) for k, v in headers.items()] if headers else None
        )

        self._producer.produce(
            topic=topic,
            value=_serialize_value(value),
            key=_serialize_key(key),
            headers=kafka_headers,
            on_delivery=_on_delivery,
        )
        # Trigger delivery callbacks without blocking the event loop
        self._producer.poll(0)

        await future

    async def flush(self, timeout: float = 5.0) -> int:
        """Flush pending messages. Returns the number of messages still in queue."""
        remaining = self._producer.flush(timeout=timeout)
        if remaining > 0:
            logger.warning("Kafka producer flush: %d messages still in queue", remaining)
        return remaining

    def close(self) -> None:
        """Flush and release resources."""
        remaining = self._producer.flush(timeout=10.0)
        if remaining > 0:
            logger.warning(
                "Kafka producer closed with %d undelivered messages", remaining
            )
