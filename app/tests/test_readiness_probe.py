"""Readiness probe tests for production dependency gates."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_readyz_reports_database_and_redis(monkeypatch):
    async def redis_ready():
        return True

    monkeypatch.setattr("app.main.redis_client.ping", redis_ready)
    monkeypatch.setattr("app.main.engine", _HealthyEngine())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["redis"] is True
    assert response.json()["database"] is True
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_readyz_returns_503_in_production_when_database_is_down(monkeypatch):
    async def redis_ready():
        return True

    monkeypatch.setattr("app.main.redis_client.ping", redis_ready)
    monkeypatch.setattr("app.main.engine", _FailingEngine())
    monkeypatch.setattr(settings.app, "env", "production")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["database"] is False
    assert response.json()["status"] == "degraded"


class _HealthyConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement):
        return None


class _HealthyEngine:
    def connect(self):
        return _HealthyConnection()


class _FailingConnection:
    async def __aenter__(self):
        raise ConnectionError("database unavailable")

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FailingEngine:
    def connect(self):
        return _FailingConnection()
