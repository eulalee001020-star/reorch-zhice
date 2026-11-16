"""Experiment Manager — Grayscale Release & A/B Testing Framework.

Validates: Requirements 26.3, 26.4, 26.5, 26.6, 26.7

Features:
- Grayscale versions for specific workshops/incident types/user groups
- A/B testing: compare solve time, feasibility rate, SPI, adoption rate, Override rate
- Auto-rollback when new version degrades feasibility or MTTR-D beyond threshold
- Module-level runtime monitoring (call count, avg latency, failure rate, effectiveness)
- Offline replay of historical incidents for retrospective analysis
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"


class ExperimentVariant(str, Enum):
    CONTROL = "control"
    TREATMENT = "treatment"


@dataclass
class TrafficRule:
    """Defines which traffic goes to the treatment variant."""
    workshop_ids: list[str] = field(default_factory=list)
    incident_types: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)
    percentage: float = 0.0  # 0-100, percentage of matching traffic


@dataclass
class RollbackThreshold:
    """Thresholds that trigger auto-rollback."""
    min_feasibility_rate: float = 0.8  # below this → rollback
    max_mttr_d_increase_pct: float = 20.0  # MTTR-D increase > this % → rollback
    min_sample_size: int = 10  # minimum samples before evaluating


@dataclass
class VariantMetrics:
    """Collected metrics for a variant."""
    call_count: int = 0
    total_solve_time_ms: float = 0.0
    feasible_count: int = 0
    total_spi: float = 0.0
    adoption_count: int = 0
    override_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_solve_time_ms(self) -> float:
        return self.total_solve_time_ms / max(self.call_count, 1)

    @property
    def feasibility_rate(self) -> float:
        return self.feasible_count / max(self.call_count, 1)

    @property
    def avg_spi(self) -> float:
        return self.total_spi / max(self.feasible_count, 1)

    @property
    def adoption_rate(self) -> float:
        return self.adoption_count / max(self.call_count, 1)

    @property
    def override_rate(self) -> float:
        return self.override_count / max(self.call_count, 1)

    @property
    def failure_rate(self) -> float:
        return self.failure_count / max(self.call_count, 1)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(self.call_count, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_count": self.call_count,
            "avg_solve_time_ms": round(self.avg_solve_time_ms, 2),
            "feasibility_rate": round(self.feasibility_rate, 4),
            "avg_spi": round(self.avg_spi, 4),
            "adoption_rate": round(self.adoption_rate, 4),
            "override_rate": round(self.override_rate, 4),
            "failure_rate": round(self.failure_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }


@dataclass
class Experiment:
    """An A/B test experiment."""
    experiment_id: str
    name: str
    description: str
    module_name: str
    control_version: str
    treatment_version: str
    traffic_rule: TrafficRule
    rollback_threshold: RollbackThreshold
    status: ExperimentStatus = ExperimentStatus.DRAFT
    created_at: str = ""
    control_metrics: VariantMetrics = field(default_factory=VariantMetrics)
    treatment_metrics: VariantMetrics = field(default_factory=VariantMetrics)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(tz=timezone.utc).isoformat()


@dataclass
class ReplayResult:
    """Result of replaying a historical incident."""
    incident_id: str
    variant: str
    version: str
    solve_time_ms: float
    feasible: bool
    spi: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ExperimentManager:
    """Manages grayscale releases and A/B tests for strategy modules."""

    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}
        self._replay_results: list[ReplayResult] = []

    # ── Experiment CRUD ────────────────────────────────────────────

    def create_experiment(
        self,
        name: str,
        description: str,
        module_name: str,
        control_version: str,
        treatment_version: str,
        traffic_rule: TrafficRule | None = None,
        rollback_threshold: RollbackThreshold | None = None,
    ) -> Experiment:
        exp = Experiment(
            experiment_id=str(uuid4())[:8],
            name=name,
            description=description,
            module_name=module_name,
            control_version=control_version,
            treatment_version=treatment_version,
            traffic_rule=traffic_rule or TrafficRule(),
            rollback_threshold=rollback_threshold or RollbackThreshold(),
        )
        self._experiments[exp.experiment_id] = exp
        logger.info("Experiment created: %s (%s)", exp.experiment_id, name)
        return exp

    def start_experiment(self, experiment_id: str) -> Experiment:
        exp = self._get_experiment(experiment_id)
        exp.status = ExperimentStatus.RUNNING
        logger.info("Experiment started: %s", experiment_id)
        return exp

    def pause_experiment(self, experiment_id: str) -> Experiment:
        exp = self._get_experiment(experiment_id)
        exp.status = ExperimentStatus.PAUSED
        return exp

    def complete_experiment(self, experiment_id: str) -> Experiment:
        exp = self._get_experiment(experiment_id)
        exp.status = ExperimentStatus.COMPLETED
        return exp

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        return self._experiments.get(experiment_id)

    def list_experiments(self, status: ExperimentStatus | None = None) -> list[Experiment]:
        exps = list(self._experiments.values())
        if status:
            exps = [e for e in exps if e.status == status]
        return exps

    # ── Variant resolution (Req 26.3) ─────────────────────────────

    def resolve_variant(
        self,
        module_name: str,
        workshop_id: str | None = None,
        incident_type: str | None = None,
        user_id: str | None = None,
    ) -> tuple[str, str]:
        """Resolve which variant (version) to use for a given context.

        Returns (variant_name, version_string).
        """
        for exp in self._experiments.values():
            if exp.status != ExperimentStatus.RUNNING:
                continue
            if exp.module_name != module_name:
                continue

            rule = exp.traffic_rule
            matches = True
            if rule.workshop_ids and workshop_id and workshop_id not in rule.workshop_ids:
                matches = False
            if rule.incident_types and incident_type and incident_type not in rule.incident_types:
                matches = False
            if rule.user_ids and user_id and user_id not in rule.user_ids:
                matches = False

            if matches:
                return ExperimentVariant.TREATMENT.value, exp.treatment_version

        # No matching experiment → use control/default
        return ExperimentVariant.CONTROL.value, ""

    # ── Metrics recording (Req 26.6) ──────────────────────────────

    def record_result(
        self,
        experiment_id: str,
        variant: str,
        solve_time_ms: float,
        feasible: bool,
        spi: float | None = None,
        adopted: bool = False,
        overridden: bool = False,
        failed: bool = False,
        latency_ms: float = 0.0,
    ) -> None:
        exp = self._get_experiment(experiment_id)
        metrics = exp.treatment_metrics if variant == ExperimentVariant.TREATMENT.value else exp.control_metrics

        metrics.call_count += 1
        metrics.total_solve_time_ms += solve_time_ms
        metrics.total_latency_ms += latency_ms
        if feasible:
            metrics.feasible_count += 1
        if spi is not None:
            metrics.total_spi += spi
        if adopted:
            metrics.adoption_count += 1
        if overridden:
            metrics.override_count += 1
        if failed:
            metrics.failure_count += 1

        # Check auto-rollback (Req 26.5)
        self._check_auto_rollback(exp)

    # ── Auto-rollback (Req 26.5) ──────────────────────────────────

    def _check_auto_rollback(self, exp: Experiment) -> None:
        """Auto-rollback if treatment degrades beyond thresholds."""
        t = exp.treatment_metrics
        threshold = exp.rollback_threshold

        if t.call_count < threshold.min_sample_size:
            return

        if t.feasibility_rate < threshold.min_feasibility_rate:
            logger.warning(
                "Auto-rollback experiment %s: feasibility_rate %.2f < %.2f",
                exp.experiment_id, t.feasibility_rate, threshold.min_feasibility_rate,
            )
            exp.status = ExperimentStatus.ROLLED_BACK
            return

        c = exp.control_metrics
        if c.call_count >= threshold.min_sample_size and c.avg_solve_time_ms > 0:
            mttr_increase_pct = ((t.avg_solve_time_ms - c.avg_solve_time_ms) / c.avg_solve_time_ms) * 100
            if mttr_increase_pct > threshold.max_mttr_d_increase_pct:
                logger.warning(
                    "Auto-rollback experiment %s: MTTR-D increase %.1f%% > %.1f%%",
                    exp.experiment_id, mttr_increase_pct, threshold.max_mttr_d_increase_pct,
                )
                exp.status = ExperimentStatus.ROLLED_BACK

    # ── Offline replay (Req 26.7) ─────────────────────────────────

    def replay_incident(
        self,
        incident_id: str,
        variant: str,
        version: str,
        solve_time_ms: float,
        feasible: bool,
        spi: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> ReplayResult:
        """Record a replay result for retrospective analysis."""
        result = ReplayResult(
            incident_id=incident_id,
            variant=variant,
            version=version,
            solve_time_ms=solve_time_ms,
            feasible=feasible,
            spi=spi,
            details=details or {},
        )
        self._replay_results.append(result)
        return result

    def get_replay_results(self, incident_id: str | None = None) -> list[ReplayResult]:
        if incident_id:
            return [r for r in self._replay_results if r.incident_id == incident_id]
        return list(self._replay_results)

    # ── Comparison report (Req 26.4) ──────────────────────────────

    def get_comparison_report(self, experiment_id: str) -> dict[str, Any]:
        """Generate A/B comparison report."""
        exp = self._get_experiment(experiment_id)
        return {
            "experiment_id": exp.experiment_id,
            "name": exp.name,
            "module": exp.module_name,
            "status": exp.status.value,
            "control": {
                "version": exp.control_version,
                "metrics": exp.control_metrics.to_dict(),
            },
            "treatment": {
                "version": exp.treatment_version,
                "metrics": exp.treatment_metrics.to_dict(),
            },
        }

    # ── Internal ───────────────────────────────────────────────────

    def _get_experiment(self, experiment_id: str) -> Experiment:
        exp = self._experiments.get(experiment_id)
        if exp is None:
            raise ValueError(f"Experiment not found: {experiment_id}")
        return exp


# Module-level singleton
experiment_manager = ExperimentManager()
