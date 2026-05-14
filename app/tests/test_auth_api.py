from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_login_and_me_roundtrip() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "planner", "password": "planner123"},
        )
        assert login_resp.status_code == 200
        api_key = login_resp.json()["api_key"]

        me_resp = await client.get("/api/v1/auth/me", headers={"X-API-Key": api_key})

    assert me_resp.status_code == 200
    assert me_resp.json()["user_id"] == "planner-1"
    assert me_resp.json()["role"] == "Planner"


@pytest.mark.asyncio
async def test_login_rejects_bad_credentials() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "planner", "password": "bad"},
        )

    assert resp.status_code == 401
