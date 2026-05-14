"""Tests for Idempotency Control.

Validates: Requirements 1.3, 7.6, 8.1, 17.2
"""

import pytest

from app.services.idempotency import (
    IdempotencyRecord,
    IdempotencyStore,
    check_idempotency,
    compute_request_hash,
    idempotency_store,
    record_idempotency,
)


class TestIdempotencyStore:
    """Test the in-memory idempotency store."""

    def setup_method(self) -> None:
        self.store = IdempotencyStore()

    def test_empty_store_returns_none(self) -> None:
        assert self.store.get("nonexistent") is None

    def test_set_and_get(self) -> None:
        record = IdempotencyRecord(
            key="key-1",
            status_code=201,
            response_body={"id": "incident-1"},
        )
        self.store.set("key-1", record)
        result = self.store.get("key-1")
        assert result is not None
        assert result.key == "key-1"
        assert result.status_code == 201
        assert result.response_body == {"id": "incident-1"}

    def test_exists(self) -> None:
        assert not self.store.exists("key-1")
        self.store.set("key-1", IdempotencyRecord(key="key-1", status_code=200, response_body={}))
        assert self.store.exists("key-1")

    def test_duplicate_key_returns_same_result(self) -> None:
        """Core idempotency: same key → same result."""
        record = IdempotencyRecord(
            key="create-incident-abc",
            status_code=201,
            response_body={"incident_id": "abc-123", "status": "created"},
        )
        self.store.set("create-incident-abc", record)

        # Second request with same key
        existing = self.store.get("create-incident-abc")
        assert existing is not None
        assert existing.response_body["incident_id"] == "abc-123"
        assert existing.status_code == 201

    def test_different_keys_independent(self) -> None:
        self.store.set("key-1", IdempotencyRecord(key="key-1", status_code=201, response_body={"id": "1"}))
        self.store.set("key-2", IdempotencyRecord(key="key-2", status_code=201, response_body={"id": "2"}))
        assert self.store.get("key-1").response_body["id"] == "1"
        assert self.store.get("key-2").response_body["id"] == "2"

    def test_clear(self) -> None:
        self.store.set("key-1", IdempotencyRecord(key="key-1", status_code=200, response_body={}))
        assert self.store.size == 1
        self.store.clear()
        assert self.store.size == 0

    def test_size(self) -> None:
        assert self.store.size == 0
        self.store.set("a", IdempotencyRecord(key="a", status_code=200, response_body={}))
        self.store.set("b", IdempotencyRecord(key="b", status_code=200, response_body={}))
        assert self.store.size == 2


class TestComputeRequestHash:
    """Test request body hashing for conflict detection."""

    def test_same_body_same_hash(self) -> None:
        body = {"incident_type": "equipment_failure", "resource_id": "R-001"}
        assert compute_request_hash(body) == compute_request_hash(body)

    def test_different_body_different_hash(self) -> None:
        body1 = {"incident_type": "equipment_failure", "resource_id": "R-001"}
        body2 = {"incident_type": "equipment_failure", "resource_id": "R-002"}
        assert compute_request_hash(body1) != compute_request_hash(body2)

    def test_key_order_independent(self) -> None:
        body1 = {"a": 1, "b": 2}
        body2 = {"b": 2, "a": 1}
        assert compute_request_hash(body1) == compute_request_hash(body2)


class TestModuleLevelFunctions:
    """Test the module-level convenience functions."""

    def setup_method(self) -> None:
        idempotency_store.clear()

    def test_record_and_check(self) -> None:
        assert check_idempotency("test-key") is None
        record_idempotency("test-key", 201, {"created": True}, {"body": "data"})
        result = check_idempotency("test-key")
        assert result is not None
        assert result.status_code == 201
        assert result.response_body == {"created": True}

    def test_incident_creation_idempotency(self) -> None:
        """Simulate idempotent incident creation."""
        key = "incident-create-abc"
        body = {"incident_type": "equipment_failure", "resource_id": "R-001"}
        response = {"incident_id": "inc-001", "status": "pending_analysis"}

        # First request
        existing = check_idempotency(key)
        assert existing is None
        record_idempotency(key, 201, response, body)

        # Duplicate request
        existing = check_idempotency(key)
        assert existing is not None
        assert existing.response_body["incident_id"] == "inc-001"

    def test_plan_confirmation_idempotency(self) -> None:
        """Simulate idempotent plan confirmation."""
        key = "confirm-plan-xyz"
        response = {"confirmed_plan_id": "plan-001", "decision_record_id": "dr-001"}

        record_idempotency(key, 200, response)
        existing = check_idempotency(key)
        assert existing is not None
        assert existing.response_body["confirmed_plan_id"] == "plan-001"

    def test_mes_writeback_idempotency(self) -> None:
        """Simulate idempotent MES writeback."""
        key = "writeback-inc-001"
        response = {"status": "success", "instructions_sent": 5}

        record_idempotency(key, 200, response)
        existing = check_idempotency(key)
        assert existing is not None
        assert existing.response_body["status"] == "success"
