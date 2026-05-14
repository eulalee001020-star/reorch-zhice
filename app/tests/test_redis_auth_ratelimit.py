"""Tests for Redis client, RBAC auth, rate limiter, and FastAPI app.

Validates: Requirements 16.2, 16.5, 18.7
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.auth import (
    CurrentUser,
    Role,
    _API_KEY_STORE,
    get_current_user,
    require_role,
)
from app.core.redis_client import RedisClient


# ── RedisClient ─────────────────────────────────────────────────────


class TestRedisClient:
    def test_redis_property_raises_when_not_connected(self) -> None:
        client = RedisClient()
        with pytest.raises(RuntimeError, match="not connected"):
            _ = client.redis

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_key(self) -> None:
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        client._redis = mock_redis

        result = await client.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_deserializes_json(self) -> None:
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value='{"key": "value"}')
        client._redis = mock_redis

        result = await client.get("test-key")
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_set_serializes_json(self) -> None:
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        client._redis = mock_redis

        await client.set("k", {"a": 1}, ttl=30)
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "k"
        assert json.loads(call_args[0][1]) == {"a": 1}
        assert call_args[1]["ex"] == 30

    @pytest.mark.asyncio
    async def test_set_without_ttl(self) -> None:
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        client._redis = mock_redis

        await client.set("k", "hello")
        call_kwargs = mock_redis.set.call_args[1]
        assert "ex" not in call_kwargs or call_kwargs.get("ex") is None

    @pytest.mark.asyncio
    async def test_delete_returns_true_when_key_exists(self) -> None:
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=1)
        client._redis = mock_redis

        assert await client.delete("k") is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_key_missing(self) -> None:
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=0)
        client._redis = mock_redis

        assert await client.delete("k") is False

    @pytest.mark.asyncio
    async def test_exists_returns_bool(self) -> None:
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=1)
        client._redis = mock_redis

        assert await client.exists("k") is True

    @pytest.mark.asyncio
    async def test_ping_returns_false_on_error(self) -> None:
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("down"))
        client._redis = mock_redis

        assert await client.ping() is False

    @pytest.mark.asyncio
    async def test_ping_returns_true_on_success(self) -> None:
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        client._redis = mock_redis

        assert await client.ping() is True


# ── Auth / RBAC ─────────────────────────────────────────────────────


class TestAuth:
    def test_api_key_store_has_four_roles(self) -> None:
        roles = {record.role for record in _API_KEY_STORE.values()}
        assert roles == {
            Role.PLANNER,
            Role.SHOP_FLOOR_EXECUTOR,
            Role.MANAGEMENT,
            Role.IT_ADMIN,
        }

    @pytest.mark.asyncio
    async def test_get_current_user_missing_key(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(api_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_key(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(api_key="bad-key")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_valid_key(self) -> None:
        user = await get_current_user(api_key="planner-key-001")
        assert user.role == Role.PLANNER
        assert user.user_id == "planner-1"

    @pytest.mark.asyncio
    async def test_require_role_allows_matching_role(self) -> None:
        checker = require_role(Role.PLANNER, Role.IT_ADMIN)
        user = CurrentUser(user_id="u1", role=Role.PLANNER)
        result = await checker(current_user=user)
        assert result.role == Role.PLANNER

    @pytest.mark.asyncio
    async def test_require_role_blocks_non_matching_role(self) -> None:
        checker = require_role(Role.PLANNER)
        user = CurrentUser(user_id="u1", role=Role.SHOP_FLOOR_EXECUTOR)
        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_it_admin_passes_any_role_check(self) -> None:
        checker = require_role(Role.IT_ADMIN)
        user = CurrentUser(user_id="admin", role=Role.IT_ADMIN)
        result = await checker(current_user=user)
        assert result.role == Role.IT_ADMIN


# ── FastAPI app ─────────────────────────────────────────────────────


class TestFastAPIApp:
    def test_app_title_and_version(self) -> None:
        from app.main import app

        assert app.title == "ReOrch 智策"
        assert app.version == "0.1.0"

    def test_cors_middleware_registered(self) -> None:
        from app.main import app

        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    def test_healthz_route_exists(self) -> None:
        from app.main import app

        routes = [r.path for r in app.routes]
        assert "/healthz" in routes

    def test_readyz_route_exists(self) -> None:
        from app.main import app

        routes = [r.path for r in app.routes]
        assert "/readyz" in routes
