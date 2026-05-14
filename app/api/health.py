"""System Health Monitoring API.

Validates: Requirements 16.7

Provides:
- GET /api/v1/health — system overall health status
- Module status, latency metrics, error rates
- Grafana dashboard template config
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from app.core.telemetry import telemetry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/health", tags=["health"])


# ── Module health registry ─────────────────────────────────────────

_module_statuses: dict[str, dict[str, Any]] = {}


def register_module_status(module_name: str, status: dict[str, Any]) -> None:
    """Register or update a module's health status."""
    _module_statuses[module_name] = {
        **status,
        "last_updated": datetime.now(tz=timezone.utc).isoformat(),
    }


def get_module_statuses() -> dict[str, dict[str, Any]]:
    return dict(_module_statuses)


# ── Health endpoint (Req 16.7) ─────────────────────────────────────

@router.get("")
async def system_health() -> dict[str, Any]:
    """GET /api/v1/health — system overall health status.

    Returns module statuses, latency metrics, and error rates.
    """
    modules = get_module_statuses()
    all_healthy = all(m.get("status") != "error" for m in modules.values())

    # Collect latency metrics from telemetry
    latency_metrics: dict[str, Any] = {}
    for span_name in [
        telemetry.SPAN_AIC, telemetry.SPAN_IAE, telemetry.SPAN_SS,
        telemetry.SPAN_SPL, telemetry.SPAN_HS, telemetry.SPAN_EC,
        telemetry.SPAN_PRE, telemetry.SPAN_EL, telemetry.SPAN_CM,
        telemetry.SPAN_WM, telemetry.SPAN_CL,
    ]:
        key = f"{span_name}_duration_ms:{{'service': '{telemetry._service_name}'}}"
        values = telemetry._histograms.get(key, [])
        if values:
            latency_metrics[span_name] = {
                "avg_ms": round(sum(values) / len(values), 2),
                "max_ms": round(max(values), 2),
                "count": len(values),
            }

    return {
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "version": "0.1.0",
        "modules": modules,
        "latency_metrics": latency_metrics,
    }


# ── Grafana dashboard template ─────────────────────────────────────

@router.get("/grafana-config")
async def grafana_dashboard_config() -> dict[str, Any]:
    """Return a Grafana dashboard template configuration."""
    return {
        "dashboard": {
            "title": "ReOrch System Health",
            "panels": [
                {
                    "title": "Module Latency (ms)",
                    "type": "graph",
                    "targets": [
                        {"expr": f"{name}_duration_ms", "legendFormat": name}
                        for name in [
                            "anomaly_intake_center", "impact_analysis_engine",
                            "strategy_selector", "hybrid_solver",
                            "evaluation_center", "plan_recommendation_engine",
                        ]
                    ],
                },
                {
                    "title": "Error Rate",
                    "type": "graph",
                    "targets": [
                        {"expr": "module_error_total", "legendFormat": "{{module}}"}
                    ],
                },
                {
                    "title": "Throughput (req/s)",
                    "type": "graph",
                    "targets": [
                        {"expr": "module_request_total", "legendFormat": "{{module}}"}
                    ],
                },
            ],
        },
    }


# ── Prometheus metrics endpoint ────────────────────────────────────

@router.get("/metrics")
async def prometheus_metrics() -> str:
    """Export metrics in Prometheus text format."""
    return telemetry.get_prometheus_metrics()
