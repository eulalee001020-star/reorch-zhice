"""Async Redis client with connection pool, TTL support, and cache helpers.

Validates: Requirements 16.2, 16.5
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Async Redis client wrapping redis.asyncio with connection pooling.

    Usage::

        client = RedisClient()
        await client.connect()
        await client.set("key", {"data": 1}, ttl=60)
        val = await client.get("key")
        await client.close()
    """

    def __init__(self) -> None:
        self._pool: aioredis.ConnectionPool | None = None
        self._redis: aioredis.Redis | None = None

    # ── lifecycle ───────────────────────────────────────────────────

    async def connect(self) -> None:
        """Create connection pool and Redis instance."""
        self._pool = aioredis.ConnectionPool.from_url(
            settings.redis.url,
            max_connections=settings.redis.max_connections,
            decode_responses=True,
        )
        self._redis = aioredis.Redis(connection_pool=self._pool)
        logger.info("Redis connected: %s", settings.redis.url)

    async def close(self) -> None:
        """Gracefully close the Redis connection pool."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        if self._pool is not None:
            await self._pool.disconnect()
            self._pool = None
        logger.info("Redis connection closed")

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("RedisClient is not connected. Call connect() first.")
        return self._redis

    # ── cache helpers ───────────────────────────────────────────────

    async def get(self, key: str) -> Any | None:
        """Get a JSON-deserialized value by key. Returns None if missing."""
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | timedelta | None = None,
    ) -> None:
        """Set a JSON-serialized value with optional TTL (seconds or timedelta)."""
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        if ttl is not None:
            await self.redis.set(key, serialized, ex=ttl)
        else:
            await self.redis.set(key, serialized)

    async def delete(self, key: str) -> bool:
        """Delete a key. Returns True if the key existed."""
        result = await self.redis.delete(key)
        return result > 0

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        result = await self.redis.exists(key)
        return result > 0

    async def ping(self) -> bool:
        """Health check — returns True if Redis is reachable."""
        try:
            return await self.redis.ping()
        except Exception:
            return False


# Module-level singleton
redis_client = RedisClient()
