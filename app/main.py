"""FastAPI application entry point.

Validates: Requirements 16.2, 16.5, 18.7
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.adapters.health_check import router as integration_health_router
from app.api.agents import router as agents_router
from app.api.analysis import router as analysis_router
from app.api.auth import router as auth_router
from app.api.cases import router as cases_router
from app.api.confirmation import router as confirmation_router
from app.api.demo import router as demo_router
from app.api.evidence import router as evidence_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.integration_control import router as integration_control_router
from app.api.ngs_lab import router as ngs_lab_router
from app.api.planning import router as planning_router
from app.api.production_runtime import router as production_runtime_router
from app.api.solver import router as solver_router
from app.api.ws import router as ws_router
from app.core.config import settings
from app.core.database import engine
from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle hook."""
    # ── startup ─────────────────────────────────────────────────
    logger.info(
        "Starting %s v%s [%s]",
        settings.app.name,
        settings.app.version,
        settings.app.env,
    )
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
async def readyz(response: Response) -> dict[str, bool | str]:
    """Readiness probe for critical state and persistence dependencies."""
    redis_ok = await redis_client.ping()
    database_ok = False
    try:
        async with asyncio.timeout(2.0):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False

    critical_ready = redis_ok and database_ok
    if settings.app.env in {"staging", "production"} and not critical_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "redis": redis_ok,
        "database": database_ok,
        "durable_persistence_required": settings.app.durable_persistence_required,
        "status": "ready" if critical_ready else "degraded",
    }


# ── Router registration ──────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(agents_router)
app.include_router(incidents_router)
app.include_router(integration_control_router)
app.include_router(analysis_router)
app.include_router(solver_router)
app.include_router(confirmation_router)
app.include_router(cases_router)
app.include_router(demo_router)
app.include_router(evidence_router)
app.include_router(ngs_lab_router)
app.include_router(planning_router)
app.include_router(production_runtime_router)
app.include_router(health_router)
app.include_router(ws_router)
app.include_router(integration_health_router)
