"""Integration Health Check — monitors external system connectivity.

Validates: Requirements 18.6

Provides a unified health check for all external system adapters
(MES, IoT, ERP/APS) and exposes GET /api/v1/health/integrations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/health", tags=["health"])

# ── In-memory adapter registry ─────────────────────────────────────

_adapters: dict[str, Any] = {}


def register_adapter(name: str, adapter: Any) -> None:
    """Register an adapter for health monitoring."""
    _adapters[name] = adapter


def get_registered_adapters() -> dict[str, Any]:
    return dict(_adapters)


# ── Health check logic ─────────────────────────────────────────────


async def check_all_integrations() -> dict[str, Any]:
    """Check health of all registered external system adapters."""
    results: dict[str, Any] = {}
    all_healthy = True

    for name, adapter in _adapters.items():
        try:
            if hasattr(adapter, "health_check"):
                status = await adapter.health_check()
            else:
                status = {
                    "system": name,
                    "available": getattr(adapter, "is_available", True),
                }
            results[name] = status
            if not status.get("available", True):
                all_healthy = False
        except Exception as exc:
            results[name] = {
                "system": name,
                "available": False,
                "error": str(exc),
            }
            all_healthy = False

    return {
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "integrations": results,
    }


# ── API endpoint (Req 18.6) ───────────────────────────────────────


@router.get("/integrations")
async def get_integration_health() -> dict[str, Any]:
    """GET /api/v1/health/integrations — external system health status."""
    return await check_all_integrations()
