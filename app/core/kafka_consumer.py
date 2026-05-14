"""Async-friendly Kafka consumer base class with JSON deserialization.

Validates: Requirements 1.8, 18.2
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException, Message

from app.core.config import settings

logger = logging.getLogger(__name__)


def _deserialize_value(raw: bytes | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


class KafkaConsumer:
    """Async-friendly consumer base class with manual commit control.

    Subclass and override :meth:`handle_message` to process messages.

    Usage::

        class IncidentConsumer(KafkaConsumer):
            async def handle_message(self, topic, key, value, headers):
                print(value)

        consumer = IncidentConsumer(topics=["incidents.created"])
        await consumer.start()   # runs until stop() is called
        consumer.close()
    """

    def __init__(
        self,
        topics: list[str],
        group_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        base_config: dict[str, Any] = {
            "bootstrap.servers": settings.kafka.bootstrap_servers,
            "group.id": group_id or settings.kafka.group_id,
            "auto.offset.reset": settings.kafka.auto_offset_reset,
            "enable.auto.commit": settings.kafka.enable_auto_commit,
        }
        if config:
            base_config.update(config)

        self._consumer = Consumer(base_config)
        self._topics = topics
        self._running = False

    # ── abstract handler ────────────────────────────────────────────

    async def handle_message(
        self,
        topic: str,
        key: str | None,
        value: Any,
        headers: dict[str, str] | None,
    ) -> None:
        """Override this method to process each consumed message."""
        raise NotImplementedError

    # ── lifecycle ───────────────────────────────────────────────────

    async def start(self, poll_timeout: float = 1.0) -> None:
        """Subscribe and poll in a loop. Call :meth:`stop` to break."""
        self._consumer.subscribe(self._topics)
        self._running = True
        logger.info("Kafka consumer started for topics: %s", self._topics)

        loop = asyncio.get_running_loop()

        try:
            while self._running:
                msg: Message | None = await loop.run_in_executor(
                    None, self._consumer.poll, poll_timeout
                )
                if msg is None:
                    continue

                err = msg.error()
                if err is not None:
                    if err.code() == KafkaError._PARTITION_EOF:
                        logger.debug(
                            "Reached end of partition %s [%d] at offset %d",
                            msg.topic(),
                            msg.partition(),
                            msg.offset(),
                        )
                        continue
                    raise KafkaException(err)

                topic = msg.topic()
                key = msg.key().decode("utf-8") if msg.key() else None
                value = _deserialize_value(msg.value())
                headers = (
                    {k: v.decode("utf-8") for k, v in msg.headers()}
                    if msg.headers()
                    else None
                )

                try:
                    await self.handle_message(topic, key, value, headers)
                    self._consumer.commit(message=msg, asynchronous=False)
                except Exception:
                    logger.exception(
                        "Error handling message from %s [%d] offset %d",
                        topic,
                        msg.partition(),
                        msg.offset(),
                    )
                    # Do not commit — message will be redelivered
        finally:
            logger.info("Kafka consumer loop exiting for topics: %s", self._topics)

    def stop(self) -> None:
        """Signal the consumer loop to stop."""
        self._running = False

    def close(self) -> None:
        """Stop polling and release resources."""
        self.stop()
        self._consumer.close()
