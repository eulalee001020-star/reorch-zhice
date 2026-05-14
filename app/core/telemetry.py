"""OpenTelemetry distributed tracing, metrics, and logging configuration.

Validates: Requirements 16.8

Configures:
- OpenTelemetry SDK (traces, metrics, logs)
- Spans for the full anomaly processing flow
- Prometheus metrics export
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Span representation (in-memory for MVP) ────────────────────────

@dataclass
class Span:
    """In-memory span for tracing."""
    trace_id: str
    span_id: str
    name: str
    service_name: str
    start_time: float
    end_time: float | None = None
    status: str = "OK"
    attributes: dict[str, Any] = field(default_factory=dict)
    parent_span_id: str | None = None

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000


# ── Metrics store (in-memory for MVP) ──────────────────────────────

@dataclass
class MetricPoint:
    """A single metric data point."""
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(tz=timezone.utc).isoformat()


class TelemetryManager:
    """In-memory OpenTelemetry-compatible telemetry manager.

    For MVP, stores traces and metrics in memory.
    In production, replace with real OTel SDK exporters.
    """

    # Span names for the full anomaly processing flow
    SPAN_AIC = "anomaly_intake_center"
    SPAN_IAE = "impact_analysis_engine"
    SPAN_SS = "strategy_selector"
    SPAN_SPL = "solver_policy_layer"
    SPAN_HS = "hybrid_solver"
    SPAN_EC = "evaluation_center"
    SPAN_PRE = "plan_recommendation_engine"
    SPAN_EL = "explainability_layer"
    SPAN_CM = "confirmation_module"
    SPAN_WM = "writeback_module"
    SPAN_CL = "case_library"

    def __init__(self) -> None:
        self._spans: list[Span] = []
        self._metrics: list[MetricPoint] = []
        self._counters: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._span_counter = 0
        self._trace_counter = 0
        self._service_name = settings.app.otel_service_name

    # ── Tracing ────────────────────────────────────────────────────

    def _next_span_id(self) -> str:
        self._span_counter += 1
        return f"span-{self._span_counter:06d}"

    def _next_trace_id(self) -> str:
        self._trace_counter += 1
        return f"trace-{self._trace_counter:06d}"

    @contextmanager
    def start_span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Generator[Span, None, None]:
        """Context manager that creates and records a span."""
        tid = trace_id or self._next_trace_id()
        span = Span(
            trace_id=tid,
            span_id=self._next_span_id(),
            name=name,
            service_name=self._service_name,
            start_time=time.monotonic(),
            attributes=attributes or {},
            parent_span_id=parent_span_id,
        )
        try:
            yield span
            span.status = "OK"
        except Exception as exc:
            span.status = f"ERROR: {type(exc).__name__}"
            raise
        finally:
            span.end_time = time.monotonic()
            self._spans.append(span)
            # Record latency metric
            self.record_histogram(
                f"{name}_duration_ms", span.duration_ms, {"service": self._service_name}
            )

    # ── Metrics ────────────────────────────────────────────────────

    def increment_counter(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment a counter metric."""
        key = f"{name}:{labels}" if labels else name
        self._counters[key] = self._counters.get(key, 0.0) + value
        self._metrics.append(MetricPoint(name=name, value=self._counters[key], labels=labels or {}))

    def record_histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record a histogram observation."""
        key = f"{name}:{labels}" if labels else name
        self._histograms.setdefault(key, []).append(value)
        self._metrics.append(MetricPoint(name=name, value=value, labels=labels or {}))

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set a gauge metric value."""
        self._metrics.append(MetricPoint(name=name, value=value, labels=labels or {}))

    # ── Query ──────────────────────────────────────────────────────

    def get_spans(self, trace_id: str | None = None, limit: int = 100) -> list[Span]:
        """Get recorded spans, optionally filtered by trace_id."""
        spans = self._spans
        if trace_id:
            spans = [s for s in spans if s.trace_id == trace_id]
        return spans[-limit:]

    def get_metrics(self, name: str | None = None, limit: int = 100) -> list[MetricPoint]:
        """Get recorded metrics, optionally filtered by name."""
        metrics = self._metrics
        if name:
            metrics = [m for m in metrics if m.name == name]
        return metrics[-limit:]

    def get_counter(self, name: str) -> float:
        """Get current counter value."""
        return self._counters.get(name, 0.0)

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus text format."""
        lines: list[str] = []
        for key, value in self._counters.items():
            name = key.split(":")[0]
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")
        for key, values in self._histograms.items():
            name = key.split(":")[0]
            if values:
                lines.append(f"# TYPE {name} histogram")
                lines.append(f"{name}_count {len(values)}")
                lines.append(f"{name}_sum {sum(values):.2f}")
        return "\n".join(lines)


# Module-level singleton
telemetry = TelemetryManager()
