"""Tests for Kafka infrastructure: topics, producer, consumer."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.kafka_topics import (
    ALL_TOPICS,
    TOPIC_IMPACT_COMPLETED,
    TOPIC_INCIDENTS_CREATED,
    TOPIC_PLANS_CONFIRMED,
    TOPIC_PLANS_GENERATED,
    TOPIC_STRATEGY_SELECTED,
    TOPIC_WRITEBACK_STATUS,
    ensure_topics,
)
from app.core.kafka_producer import KafkaProducer, _JSONEncoder, _serialize_value
from app.core.kafka_consumer import KafkaConsumer, _deserialize_value


# ── Topic constants ─────────────────────────────────────────────────


class TestTopicConstants:
    def test_all_six_topics_defined(self) -> None:
        assert len(ALL_TOPICS) == 6

    def test_topic_names(self) -> None:
        assert TOPIC_INCIDENTS_CREATED == "incidents.created"
        assert TOPIC_IMPACT_COMPLETED == "impact.completed"
        assert TOPIC_STRATEGY_SELECTED == "strategy.selected"
        assert TOPIC_PLANS_GENERATED == "plans.generated"
        assert TOPIC_PLANS_CONFIRMED == "plans.confirmed"
        assert TOPIC_WRITEBACK_STATUS == "writeback.status"

    def test_all_topics_list_matches_individual_constants(self) -> None:
        expected = {
            "incidents.created",
            "impact.completed",
            "strategy.selected",
            "plans.generated",
            "plans.confirmed",
            "writeback.status",
        }
        assert set(ALL_TOPICS) == expected


# ── JSON serialization ──────────────────────────────────────────────


class TestJSONSerialization:
    def test_serialize_uuid(self) -> None:
        uid = uuid4()
        result = json.loads(_serialize_value({"id": uid}))
        assert result["id"] == str(uid)

    def test_serialize_datetime(self) -> None:
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = json.loads(_serialize_value({"ts": dt}))
        assert result["ts"] == "2024-01-15T10:30:00"

    def test_serialize_plain_dict(self) -> None:
        data = {"key": "value", "num": 42}
        result = json.loads(_serialize_value(data))
        assert result == data

    def test_serialize_nested(self) -> None:
        uid = uuid4()
        data = {"incident": {"id": uid, "items": [1, 2, 3]}}
        result = json.loads(_serialize_value(data))
        assert result["incident"]["id"] == str(uid)
        assert result["incident"]["items"] == [1, 2, 3]


# ── Deserialization ─────────────────────────────────────────────────


class TestDeserialization:
    def test_deserialize_none(self) -> None:
        assert _deserialize_value(None) is None

    def test_deserialize_dict(self) -> None:
        raw = json.dumps({"a": 1}).encode("utf-8")
        assert _deserialize_value(raw) == {"a": 1}

    def test_deserialize_list(self) -> None:
        raw = json.dumps([1, 2, 3]).encode("utf-8")
        assert _deserialize_value(raw) == [1, 2, 3]

    def test_deserialize_unicode(self) -> None:
        raw = json.dumps({"name": "设备故障"}).encode("utf-8")
        assert _deserialize_value(raw) == {"name": "设备故障"}


# ── ensure_topics ───────────────────────────────────────────────────


class TestEnsureTopics:
    @patch("app.core.kafka_topics.AdminClient")
    def test_all_topics_already_exist(self, mock_admin_cls: MagicMock) -> None:
        mock_admin = MagicMock()
        mock_admin_cls.return_value = mock_admin

        # Simulate all topics already existing
        mock_metadata = MagicMock()
        mock_metadata.topics = {t: MagicMock() for t in ALL_TOPICS}
        mock_admin.list_topics.return_value = mock_metadata

        result = ensure_topics()

        assert all(v is False for v in result.values())
        assert set(result.keys()) == set(ALL_TOPICS)
        mock_admin.create_topics.assert_not_called()

    @patch("app.core.kafka_topics.AdminClient")
    def test_creates_missing_topics(self, mock_admin_cls: MagicMock) -> None:
        mock_admin = MagicMock()
        mock_admin_cls.return_value = mock_admin

        # Only 2 topics exist
        mock_metadata = MagicMock()
        mock_metadata.topics = {
            "incidents.created": MagicMock(),
            "impact.completed": MagicMock(),
        }
        mock_admin.list_topics.return_value = mock_metadata

        # Mock create_topics futures
        missing = set(ALL_TOPICS) - {"incidents.created", "impact.completed"}
        futures = {}
        for t in missing:
            f = MagicMock()
            f.result.return_value = None
            futures[t] = f
        mock_admin.create_topics.return_value = futures

        result = ensure_topics()

        assert result["incidents.created"] is False
        assert result["impact.completed"] is False
        for t in missing:
            assert result[t] is True


# ── KafkaProducer ───────────────────────────────────────────────────


class TestKafkaProducer:
    @patch("app.core.kafka_producer.Producer")
    def test_producer_init(self, mock_producer_cls: MagicMock) -> None:
        producer = KafkaProducer()
        mock_producer_cls.assert_called_once()
        config = mock_producer_cls.call_args[0][0]
        assert "bootstrap.servers" in config

    @patch("app.core.kafka_producer.Producer")
    def test_close_flushes(self, mock_producer_cls: MagicMock) -> None:
        mock_inner = MagicMock()
        mock_inner.flush.return_value = 0
        mock_producer_cls.return_value = mock_inner

        producer = KafkaProducer()
        producer.close()

        mock_inner.flush.assert_called_once()


# ── KafkaConsumer ───────────────────────────────────────────────────


class TestKafkaConsumer:
    def test_handle_message_not_implemented(self) -> None:
        consumer = KafkaConsumer.__new__(KafkaConsumer)
        with pytest.raises(NotImplementedError):
            asyncio.get_event_loop().run_until_complete(
                consumer.handle_message("topic", None, {}, None)
            )

    @patch("app.core.kafka_consumer.Consumer")
    def test_stop_sets_flag(self, mock_consumer_cls: MagicMock) -> None:
        consumer = KafkaConsumer(topics=["test"])
        assert consumer._running is False
        consumer._running = True
        consumer.stop()
        assert consumer._running is False

    @patch("app.core.kafka_consumer.Consumer")
    def test_close_calls_inner_close(self, mock_consumer_cls: MagicMock) -> None:
        mock_inner = MagicMock()
        mock_consumer_cls.return_value = mock_inner

        consumer = KafkaConsumer(topics=["test"])
        consumer.close()

        mock_inner.close.assert_called_once()
