"""Kafka topic name constants and topic creation utility.

Validates: Requirements 1.8, 18.2
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from confluent_kafka.admin import AdminClient, NewTopic

from app.core.config import settings

if TYPE_CHECKING:
    from confluent_kafka.admin import TopicMetadata

logger = logging.getLogger(__name__)

# ── Topic name constants ────────────────────────────────────────────
TOPIC_INCIDENTS_CREATED: str = settings.kafka.topic_incidents_created
TOPIC_IMPACT_COMPLETED: str = settings.kafka.topic_impact_completed
TOPIC_STRATEGY_SELECTED: str = settings.kafka.topic_strategy_selected
TOPIC_PLANS_GENERATED: str = settings.kafka.topic_plans_generated
TOPIC_PLANS_CONFIRMED: str = settings.kafka.topic_plans_confirmed
TOPIC_WRITEBACK_STATUS: str = settings.kafka.topic_writeback_status

ALL_TOPICS: list[str] = [
    TOPIC_INCIDENTS_CREATED,
    TOPIC_IMPACT_COMPLETED,
    TOPIC_STRATEGY_SELECTED,
    TOPIC_PLANS_GENERATED,
    TOPIC_PLANS_CONFIRMED,
    TOPIC_WRITEBACK_STATUS,
]


def ensure_topics(
    *,
    num_partitions: int = 3,
    replication_factor: int = 1,
    timeout_seconds: float = 10.0,
) -> dict[str, bool]:
    """Create all required topics if they do not already exist.

    Returns a mapping of topic name → created (True) or already existed (False).
    """
    admin = AdminClient({"bootstrap.servers": settings.kafka.bootstrap_servers})

    cluster_metadata = admin.list_topics(timeout=timeout_seconds)
    existing: set[str] = set(cluster_metadata.topics.keys())

    to_create: list[NewTopic] = [
        NewTopic(topic, num_partitions=num_partitions, replication_factor=replication_factor)
        for topic in ALL_TOPICS
        if topic not in existing
    ]

    result: dict[str, bool] = {}

    if not to_create:
        logger.info("All Kafka topics already exist.")
        for topic in ALL_TOPICS:
            result[topic] = False
        return result

    futures = admin.create_topics(to_create, request_timeout=timeout_seconds)

    for topic_name, future in futures.items():
        try:
            future.result()  # blocks until topic is created or error
            logger.info("Created Kafka topic: %s", topic_name)
            result[topic_name] = True
        except Exception as exc:
            logger.error("Failed to create topic %s: %s", topic_name, exc)
            raise

    # Mark pre-existing topics
    for topic in ALL_TOPICS:
        if topic not in result:
            result[topic] = False

    return result
