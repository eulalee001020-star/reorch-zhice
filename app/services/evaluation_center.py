"""Evaluation Center — multi-objective scoring, ranking, and comparison
of candidate re-scheduling plans against the baseline schedule snapshot.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.models.enums import GoalMode
from app.models.evaluation import ComparisonMatrix, ComparisonMatrixRow, KPIVector
from app.models.schedule import Operation, ScheduleSnapshot, WorkOrder
from app.models.solver import CandidatePlan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GoalMode → dimension weights
# ---------------------------------------------------------------------------

_GOAL_WEIGHTS: dict[str, dict[str, float]] = {
    GoalMode.BALANCED.value: {
        "delayed_order_count": 0.20,
        "max_delay_minutes": 0.15,
        "spi": 0.20,
        "resource_utilization_delta": 0.15,
        "changeover_count_delta": 0.10,
        "critical_order_otd_impact": 0.20,
    },
    GoalMode.DELIVERY_PRIORITY.value: {
        "delayed_order_count": 0.30,
        "max_delay_minutes": 0.25,
        "spi": 0.05,
        "resource_utilization_delta": 0.05,
        "changeover_count_delta": 0.05,
        "critical_order_otd_impact": 0.30,
    },
    GoalMode.STABILITY_PRIORITY.value: {
        "delayed_order_count": 0.10,
        "max_delay_minutes": 0.10,
        "spi": 0.35,
        "resource_utilization_delta": 0.15,
        "changeover_count_delta": 0.20,
        "critical_order_otd_impact": 0.10,
    },
    GoalMode.BOTTLENECK_PRIORITY.value: {
        "delayed_order_count": 0.10,
        "max_delay_minutes": 0.10,
        "spi": 0.15,
        "resource_utilization_delta": 0.30,
        "changeover_count_delta": 0.15,
        "critical_order_otd_impact": 0.20,
    },
    GoalMode.COST_PRIORITY.value: {
        "delayed_order_count": 0.10,
        "max_delay_minutes": 0.10,
        "spi": 0.15,
        "resource_utilization_delta": 0.20,
        "changeover_count_delta": 0.30,
        "critical_order_otd_impact": 0.15,
    },
}

# Score unit descriptions (Req 5.7)
_SCORE_UNIT_DESCRIPTIONS: dict[str, str] = {
    "delayed_order_count": "Number of work orders whose completion exceeds due date (lower is better)",
    "max_delay_minutes": "Maximum delay in minutes across all work orders (lower is better)",
    "spi": "Schedule Perturbation Index — fraction of operations adjusted vs baseline (lower is better, 0-1)",
    "resource_utilization_delta": "Change in average resource utilization vs baseline (higher is better, can be negative)",
    "changeover_count_delta": "Change in total resource changeover count vs baseline (lower is better)",
    "critical_order_otd_impact": "Fraction of critical work orders meeting due date (higher is better, 0-1)",
    "normalized_score": "Weighted composite score (0-1, higher is better)",
}

# Sentinel for missing data
_MISSING = float("nan")

# Threshold for "score close" flag (Req 5.4)
_SCORE_CLOSE_THRESHOLD = 0.05


class EvaluationCenter:
    """Multi-objective evaluation center.

    Scores, ranks, and compares candidate plans against the baseline
    ``ScheduleSnapshot``.  Does **not** decide the final recommendation —
    that is the responsibility of ``PlanRecommendationEngine``.
    """

    async def evaluate(
        self,
        candidates: list[CandidatePlan],
        snapshot: ScheduleSnapshot,
        goal_mode: GoalMode | str = GoalMode.BALANCED,
    ) -> ComparisonMatrix:
        """Evaluate candidate plans and return a ``ComparisonMatrix``.

        Parameters
        ----------
        candidates:
            List of ``CandidatePlan`` objects produced by ``HybridSolver``.
        snapshot:
            The baseline ``ScheduleSnapshot`` captured at anomaly time.
        goal_mode:
            Business objective mode driving weight allocation.
        """
        goal_mode_str = goal_mode if isinstance(goal_mode, str) else goal_mode.value
        weights = _GOAL_WEIGHTS.get(goal_mode_str, _GOAL_WEIGHTS[GoalMode.BALANCED.value])

        # Pre-compute baseline metrics from the snapshot
        baseline = _compute_baseline_metrics(snapshot)

        rows: list[ComparisonMatrixRow] = []
        for plan in candidates:
            kpi = _compute_kpi_vector(plan, snapshot, baseline, weights)
            delta = _compute_delta(kpi, baseline)
            rows.append(
                ComparisonMatrixRow(
                    plan_id=str(plan.plan_id),
                    kpi_vector=kpi,
                    delta_vs_baseline=delta,
                    is_score_close=False,  # set below after ranking
                )
            )

        # Sort by normalized_score descending (higher is better) — Req 5.2
        rows.sort(key=lambda r: r.kpi_vector.normalized_score, reverse=True)

        # Mark "score close" rows (Req 5.4)
        if rows:
            top_score = rows[0].kpi_vector.normalized_score
            for row in rows:
                gap = abs(top_score - row.kpi_vector.normalized_score)
                row.is_score_close = gap < _SCORE_CLOSE_THRESHOLD

        snapshot_id = str(snapshot.snapshot_id) if snapshot.snapshot_id else ""

        return ComparisonMatrix(
            rows=rows,
            normalization_method="min-max per dimension, weighted sum",
            score_unit_descriptions=dict(_SCORE_UNIT_DESCRIPTIONS),
            baseline_snapshot_id=snapshot_id,
        )


# ── Baseline metrics ────────────────────────────────────────────────

class _BaselineMetrics:
    """Pre-computed metrics from the ScheduleSnapshot."""

    __slots__ = (
        "delayed_order_count",
        "max_delay_minutes",
        "resource_utilization",
        "changeover_count",
        "critical_otd",
        "total_ops",
    )

    def __init__(self) -> None:
        self.delayed_order_count: int = 0
        self.max_delay_minutes: float = 0.0
        self.resource_utilization: float = 0.0
        self.changeover_count: int = 0
        self.critical_otd: float = 1.0
        self.total_ops: int = 0


def _compute_baseline_metrics(snapshot: ScheduleSnapshot) -> _BaselineMetrics:
    m = _BaselineMetrics()
    if not snapshot.work_orders:
        return m

    m.total_ops = sum(len(wo.operations) for wo in snapshot.work_orders)
    m.delayed_order_count = _count_delayed_orders(snapshot.work_orders)
    m.max_delay_minutes = _max_delay(snapshot.work_orders)
    m.resource_utilization = _resource_utilization(snapshot)
    m.changeover_count = _changeover_count(snapshot)
    m.critical_otd = _critical_otd(snapshot.work_orders)
    return m


# ── KPI computation ─────────────────────────────────────────────────

def _compute_kpi_vector(
    plan: CandidatePlan,
    snapshot: ScheduleSnapshot,
    baseline: _BaselineMetrics,
    weights: dict[str, float],
) -> KPIVector:
    """Compute the six-dimensional KPI vector for a single plan."""
    sd = plan.schedule_detail
    work_orders = sd.work_orders if sd else []

    delayed = _count_delayed_orders(work_orders)
    max_del = _max_delay(work_orders)
    spi = _spi(plan, snapshot)
    res_util = _resource_utilization_from_detail(sd) if sd else 0.0
    res_delta = res_util - baseline.resource_utilization
    chg_count = _changeover_count_from_detail(sd) if sd else 0
    chg_delta = chg_count - baseline.changeover_count
    crit_otd = _critical_otd(work_orders)

    # Normalized score (Req 5.7) — weighted sum of per-dimension scores
    norm = _normalized_score(
        delayed, max_del, spi, res_delta, chg_delta, crit_otd, weights
    )

    return KPIVector(
        delayed_order_count=delayed,
        max_delay_minutes=max_del,
        spi=spi,
        resource_utilization_delta=round(res_delta, 4),
        changeover_count_delta=chg_delta,
        critical_order_otd_impact=round(crit_otd, 4),
        normalized_score=round(norm, 4),
    )


def _normalized_score(
    delayed: int,
    max_delay: float,
    spi: float,
    res_delta: float,
    chg_delta: int,
    crit_otd: float,
    weights: dict[str, float],
) -> float:
    """Compute a 0-1 normalized composite score.

    Each dimension is mapped to a 0-1 sub-score where 1 = best.
    """
    # delayed_order_count: 0 is best → score = 1/(1+count)
    s_delayed = 1.0 / (1.0 + delayed)

    # max_delay_minutes: 0 is best → score = 1/(1+delay/60)
    s_max_delay = 1.0 / (1.0 + max(max_delay, 0.0) / 60.0)

    # spi: 0 is best (no perturbation) → score = 1 - spi
    s_spi = max(0.0, 1.0 - spi)

    # resource_utilization_delta: higher is better → sigmoid-like mapping
    # delta in [-1, 1]; map to [0, 1] via (delta + 1) / 2
    s_res = min(1.0, max(0.0, (res_delta + 1.0) / 2.0))

    # changeover_count_delta: lower (more negative) is better
    # map via 1/(1+max(delta,0))
    s_chg = 1.0 / (1.0 + max(chg_delta, 0))

    # critical_order_otd: already 0-1, higher is better
    s_otd = max(0.0, min(1.0, crit_otd))

    score = (
        weights.get("delayed_order_count", 0) * s_delayed
        + weights.get("max_delay_minutes", 0) * s_max_delay
        + weights.get("spi", 0) * s_spi
        + weights.get("resource_utilization_delta", 0) * s_res
        + weights.get("changeover_count_delta", 0) * s_chg
        + weights.get("critical_order_otd_impact", 0) * s_otd
    )
    return min(1.0, max(0.0, score))


# ── Delta computation ───────────────────────────────────────────────

def _compute_delta(kpi: KPIVector, baseline: _BaselineMetrics) -> dict[str, float]:
    """Compute per-dimension delta vs baseline (Req 5.3).

    Positive delta means the plan value is *higher* than baseline.
    """
    return {
        "delayed_order_count": float(kpi.delayed_order_count - baseline.delayed_order_count),
        "max_delay_minutes": round(kpi.max_delay_minutes - baseline.max_delay_minutes, 2),
        "spi": round(kpi.spi, 4),  # baseline SPI is 0 by definition
        "resource_utilization_delta": round(kpi.resource_utilization_delta, 4),
        "changeover_count_delta": float(kpi.changeover_count_delta),
        "critical_order_otd_impact": round(
            kpi.critical_order_otd_impact - baseline.critical_otd, 4
        ),
    }


# ── Metric helpers ──────────────────────────────────────────────────

def _count_delayed_orders(work_orders: list[WorkOrder]) -> int:
    """Count work orders whose last operation ends after due_date."""
    count = 0
    for wo in work_orders:
        if not wo.operations:
            continue
        latest_end = max(op.end_time for op in wo.operations)
        if latest_end > wo.due_date:
            count += 1
    return count


def _max_delay(work_orders: list[WorkOrder]) -> float:
    """Maximum delay in minutes across all work orders."""
    worst = 0.0
    for wo in work_orders:
        if not wo.operations:
            continue
        latest_end = max(op.end_time for op in wo.operations)
        delay_min = (latest_end - wo.due_date).total_seconds() / 60.0
        if delay_min > worst:
            worst = delay_min
    return max(worst, 0.0)


def _spi(plan: CandidatePlan, snapshot: ScheduleSnapshot) -> float:
    """Schedule Perturbation Index — fraction of operations adjusted.

    SPI = (number of operations whose start/end/resource changed) / total ops.
    """
    if not snapshot.work_orders:
        return 0.0

    baseline_ops: dict[str, Operation] = {}
    for wo in snapshot.work_orders:
        for op in wo.operations:
            baseline_ops[op.operation_id] = op

    total = len(baseline_ops)
    if total == 0:
        return 0.0

    sd = plan.schedule_detail
    if not sd or not sd.work_orders:
        return 1.0  # all operations missing → full perturbation

    adjusted = 0
    plan_ops: dict[str, Operation] = {}
    for wo in sd.work_orders:
        for op in wo.operations:
            plan_ops[op.operation_id] = op

    for op_id, base_op in baseline_ops.items():
        plan_op = plan_ops.get(op_id)
        if plan_op is None:
            adjusted += 1
            continue
        if (
            plan_op.start_time != base_op.start_time
            or plan_op.end_time != base_op.end_time
            or plan_op.resource_id != base_op.resource_id
        ):
            adjusted += 1

    return round(adjusted / total, 4)


def _resource_utilization(snapshot: ScheduleSnapshot) -> float:
    """Compute average resource utilization from a ScheduleSnapshot.

    Utilization = fraction of time each resource is busy across all ops.
    Returns average across all resources.
    """
    if not snapshot.work_orders:
        return 0.0

    resource_busy: dict[str, float] = {}
    resource_span: dict[str, tuple[float, float]] = {}

    for wo in snapshot.work_orders:
        for op in wo.operations:
            rid = op.resource_id
            dur = (op.end_time - op.start_time).total_seconds()
            resource_busy[rid] = resource_busy.get(rid, 0.0) + dur
            st = op.start_time.timestamp()
            et = op.end_time.timestamp()
            if rid not in resource_span:
                resource_span[rid] = (st, et)
            else:
                prev = resource_span[rid]
                resource_span[rid] = (min(prev[0], st), max(prev[1], et))

    if not resource_busy:
        return 0.0

    utils: list[float] = []
    for rid, busy in resource_busy.items():
        span = resource_span.get(rid)
        if span and (span[1] - span[0]) > 0:
            utils.append(busy / (span[1] - span[0]))
        else:
            utils.append(0.0)

    return sum(utils) / len(utils) if utils else 0.0


def _resource_utilization_from_detail(sd) -> float:
    """Compute average resource utilization from a ScheduleDetail."""
    if not sd or not sd.work_orders:
        return 0.0

    resource_busy: dict[str, float] = {}
    resource_span: dict[str, tuple[float, float]] = {}

    for wo in sd.work_orders:
        for op in wo.operations:
            rid = op.resource_id
            dur = (op.end_time - op.start_time).total_seconds()
            resource_busy[rid] = resource_busy.get(rid, 0.0) + dur
            st = op.start_time.timestamp()
            et = op.end_time.timestamp()
            if rid not in resource_span:
                resource_span[rid] = (st, et)
            else:
                prev = resource_span[rid]
                resource_span[rid] = (min(prev[0], st), max(prev[1], et))

    if not resource_busy:
        return 0.0

    utils: list[float] = []
    for rid, busy in resource_busy.items():
        span = resource_span.get(rid)
        if span and (span[1] - span[0]) > 0:
            utils.append(busy / (span[1] - span[0]))
        else:
            utils.append(0.0)

    return sum(utils) / len(utils) if utils else 0.0


def _changeover_count(snapshot: ScheduleSnapshot) -> int:
    """Count resource changeovers in a ScheduleSnapshot.

    A changeover occurs when consecutive operations on the same resource
    belong to different work orders.
    """
    return _count_changeovers_from_work_orders(snapshot.work_orders)


def _changeover_count_from_detail(sd) -> int:
    """Count resource changeovers from a ScheduleDetail."""
    if not sd or not sd.work_orders:
        return 0
    return _count_changeovers_from_work_orders(sd.work_orders)


def _count_changeovers_from_work_orders(work_orders: list[WorkOrder]) -> int:
    """Shared changeover counting logic."""
    # Group operations by resource, sorted by start_time
    resource_ops: dict[str, list[Operation]] = {}
    for wo in work_orders:
        for op in wo.operations:
            resource_ops.setdefault(op.resource_id, []).append(op)

    changeovers = 0
    for rid, ops in resource_ops.items():
        sorted_ops = sorted(ops, key=lambda o: o.start_time)
        for i in range(1, len(sorted_ops)):
            if sorted_ops[i].work_order_id != sorted_ops[i - 1].work_order_id:
                changeovers += 1

    return changeovers


def _critical_otd(work_orders: list[WorkOrder]) -> float:
    """Fraction of critical work orders (priority > 0) meeting their due date.

    If no critical orders exist, returns 1.0 (perfect OTD).
    """
    critical = [wo for wo in work_orders if wo.priority > 0]
    if not critical:
        return 1.0

    on_time = 0
    for wo in critical:
        if not wo.operations:
            on_time += 1
            continue
        latest_end = max(op.end_time for op in wo.operations)
        if latest_end <= wo.due_date:
            on_time += 1

    return on_time / len(critical)
