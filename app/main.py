"""FastAPI application entry point.

Validates: Requirements 16.2, 16.5, 18.7
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle hook."""
    # ── startup ─────────────────────────────────────────────────
    logger.info("Starting %s v%s [%s]", settings.app.name, settings.app.version, settings.app.env)
    await redis_client.connect()
    logger.info("Redis ready")

    yield

    # ── shutdown ────────────────────────────────────────────────
    await redis_client.close()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    debug=settings.app.debug,
    lifespan=lifespan,
)

# ── CORS ────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check (always available, no auth) ────────────────────────

@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz() -> dict[str, bool | str]:
    """Readiness probe — checks Redis connectivity."""
    redis_ok = await redis_client.ping()
    return {"redis": redis_ok, "status": "ready" if redis_ok else "degraded"}


# ── Router registration ──────────────────────────────────────────────
from app.api.incidents import router as incidents_router
from app.api.auth import router as auth_router
from app.api.analysis import router as analysis_router
from app.api.solver import router as solver_router
from app.api.confirmation import router as confirmation_router
from app.api.cases import router as cases_router
from app.api.planning import router as planning_router
from app.api.health import router as health_router
from app.api.ws import router as ws_router
from app.adapters.health_check import router as integration_health_router

app.include_router(auth_router)
app.include_router(incidents_router)
app.include_router(analysis_router)
app.include_router(solver_router)
app.include_router(confirmation_router)
app.include_router(cases_router)
app.include_router(planning_router)
app.include_router(health_router)
app.include_router(ws_router)
app.include_router(integration_health_router)
