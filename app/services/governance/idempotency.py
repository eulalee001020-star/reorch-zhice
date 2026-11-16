"""Idempotency Control for critical write interfaces.

Validates: Requirements 1.3, 7.6, 8.1, 17.2

Provides Idempotency-Key header support for:
- Incident creation
- Plan confirmation
- MES writeback

Duplicate requests return the same result without re-creating entities.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import Request, Response

logger = logging.getLogger(__name__)

# Header name
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"

# TTL for idempotency keys (24 hours in seconds)
IDEMPOTENCY_TTL_SECONDS = 86400


@dataclass
class IdempotencyRecord:
    """Stored result for an idempotency key."""
    key: str
    status_code: int
    response_body: Any
    created_at: str = ""
    request_hash: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(tz=timezone.utc).isoformat()


class IdempotencyStore:
    """In-memory idempotency store for MVP.

    In production, use Redis with TTL for distributed idempotency.
    """

    def __init__(self) -> None:
        self._store: dict[str, IdempotencyRecord] = {}

    def get(self, key: str) -> IdempotencyRecord | None:
        """Look up a stored result by idempotency key."""
        return self._store.get(key)

    def set(self, key: str, record: IdempotencyRecord) -> None:
        """Store a result for an idempotency key."""
        self._store[key] = record
        logger.debug("Idempotency key stored: %s", key)

    def exists(self, key: str) -> bool:
        """Check if an idempotency key exists."""
        return key in self._store

    def clear(self) -> None:
        """Clear all stored keys (for testing)."""
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


# Module-level singleton
idempotency_store = IdempotencyStore()


def compute_request_hash(body: Any) -> str:
    """Compute a hash of the request body for conflict detection."""
    serialized = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def get_idempotency_key(request: Request) -> str | None:
    """Extract the Idempotency-Key header from a request."""
    return request.headers.get(IDEMPOTENCY_KEY_HEADER)


def check_idempotency(key: str) -> IdempotencyRecord | None:
    """Check if a request with this key has already been processed.

    Returns the stored record if found, None otherwise.
    """
    return idempotency_store.get(key)


def record_idempotency(key: str, status_code: int, response_body: Any, request_body: Any = None) -> None:
    """Record the result of a request for idempotency.

    Future requests with the same key will return this result.
    """
    request_hash = compute_request_hash(request_body) if request_body else ""
    record = IdempotencyRecord(
        key=key,
        status_code=status_code,
        response_body=response_body,
        request_hash=request_hash,
    )
    idempotency_store.set(key, record)
