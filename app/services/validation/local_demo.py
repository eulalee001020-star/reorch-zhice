"""Walk the whole decision loop in-process, with no external services.

The API keeps its working state in memory when Postgres, Redis and Kafka are
absent, so one process is enough to show the loop end to end. The walks drive
the same HTTP routes the frontend calls, which makes them both the local demo
and a regression check that the dependency-free path keeps working.

Two scenarios are provided:

``equipment``
    A machine fails for four hours in the middle of the shift.
``material``
    A supplier slips an inbound order to the next morning; an approved
    substitute is in stock.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.adapters.csv_adapter import CSVAdapter
from app.core.paths import REPO_ROOT
from app.services.dispatch.planner import load_dispatch_snapshot
from app.services.supply.csv_loader import load_supply_snapshot

DEMO_DATA_DIR = REPO_ROOT / "demo" / "data"
DEMO_WORKSHOP = "DEMO-LINE-01"
API_PREFIX = "/api/v1"

MATERIAL_OPTION_LABELS = {
    "wait_for_supply": "等待到货",
    "approved_substitute": "使用已批准替代料",
}
SOLVER_LABELS = {"right_shift_baseline": "只顺延不调整"}


@dataclass
class CandidateSummary:
    """One candidate plan as the planner would compare it."""

    plan_id: str
    label: str
    is_baseline: bool
    feasible: bool
    delayed_orders: int | None
    max_delay_minutes: float | None
    moved_operations: int
    material_option: str | None = None

    def line(self, recommended_plan_id: str) -> str:
        mark = "推荐" if self.plan_id == recommended_plan_id else "    "
        delivery = (
            "未评价"
            if self.delayed_orders is None
            else f"延期工单 {self.delayed_orders} 张，最长延期 {self.max_delay_minutes:.0f} 分钟"
        )
        return f"  {mark}  {self.label:<14} {delivery}，调整 {self.moved_operations} 道工序"


@dataclass
class DemoResult:
    """What one walk through the loop produced."""

    scenario: str
    incident_id: str
    decision_time: str
    affected_work_orders: int
    affected_operations: int
    wait_total_delay_minutes: float
    risk_distribution: dict[str, int]
    upgraded_severity: str | None
    strategy_type: str
    candidates: list[CandidateSummary]
    recommended_plan_id: str
    reason_summary: str
    checked_constraints: list[str] = field(default_factory=list)
    violations: int = 0
    decision_record_id: str = ""
    supply_summary: list[str] = field(default_factory=list)
    dispatch_plans: list[dict[str, Any]] = field(default_factory=list)

    def dispatch_lines(self) -> list[str]:
        lines = []
        for plan in self.dispatch_plans:
            mark = "推荐" if plan["is_recommended"] else "    "
            held = len(plan["unserved_shipment_ids"])
            lines.append(
                f"    {mark}  {plan['label']:<14} 迟到 {plan['late_stop_count']} 票"
                f"（共 {plan['total_late_minutes']:.0f} 分钟），当班发不出 {held} 票，"
                f"用车 {plan['vehicles_used']} 辆，里程 {plan['total_distance_km']:.0f} km"
            )
        return lines

    @property
    def recommended(self) -> CandidateSummary:
        return next(c for c in self.candidates if c.plan_id == self.recommended_plan_id)

    @property
    def baseline(self) -> CandidateSummary | None:
        return next((c for c in self.candidates if c.is_baseline), None)

    def lines(self) -> list[str]:
        risk = self.risk_distribution
        lines = [
            f"异常事件      {self.incident_id}（决策时点 {self.decision_time}）",
            f"若只等待      {self.affected_work_orders} 张工单 / {self.affected_operations} 道工序受影响，"
            f"完工合计推迟 {self.wait_total_delay_minutes:.0f} 分钟；"
            f"超期 {risk.get('breach', 0)} 张，预警 {risk.get('warning', 0)} 张"
            + (f"；严重度升级为 {self.upgraded_severity}" if self.upgraded_severity else ""),
            *self.supply_summary,
            f"恢复策略      {self.strategy_type}",
            "候选方案",
            *[candidate.line(self.recommended_plan_id) for candidate in self.candidates],
            *(["发运影响", *self.dispatch_lines()] if self.dispatch_plans else []),
            f"推荐理由      {self.reason_summary}",
            f"确认前校验    {len(self.checked_constraints)} 类约束，违反 {self.violations} 项",
            f"决策记录      {self.decision_record_id}",
        ]
        return lines


def reset_in_memory_state() -> None:
    """Clear the API's in-memory working stores so a walk starts from nothing."""
    from app.api.analysis import _impact_report_cache, _snapshot_store, _strategy_cache
    from app.api.dispatch import _dispatch_store
    from app.api.incidents import _incident_store
    from app.api.solver import _candidate_plans_store, _plan_index, _recommendation_store
    from app.api.supply import _supply_store

    for store in (
        _incident_store,
        _snapshot_store,
        _impact_report_cache,
        _strategy_cache,
        _candidate_plans_store,
        _plan_index,
        _recommendation_store,
        _supply_store,
        _dispatch_store,
    ):
        store.clear()


def _first_row(path: Path) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8") as handle:
        return dict(next(csv.DictReader(handle)))


async def _call(client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> Any:
    response = await client.request(method, f"{API_PREFIX}{path}", **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
    return response.json()


async def _seed_schedule(client: httpx.AsyncClient, data_dir: Path, captured_at: datetime) -> None:
    snapshot = await CSVAdapter(data_dir).fetch_current_schedule(workshop_id=DEMO_WORKSHOP)
    # The demo schedule is dated; capture it at the incident time so that
    # "already started" and "still to do" mean what they would on the day.
    snapshot.captured_at = captured_at
    await _call(client, "POST", "/schedule-snapshots", json=snapshot.model_dump(mode="json"))


async def _seed_supply(client: httpx.AsyncClient, data_dir: Path, captured_at: datetime) -> None:
    supply = load_supply_snapshot(
        data_dir / "supply",
        captured_at=captured_at,
        work_orders_csv=data_dir / "work_orders.csv",
        workshop_id=DEMO_WORKSHOP,
    )
    await _call(client, "POST", "/supply/snapshots", json=supply.model_dump(mode="json"))


async def _seed_dispatch(client: httpx.AsyncClient, data_dir: Path, captured_at: datetime) -> None:
    dispatch = load_dispatch_snapshot(data_dir / "dispatch", captured_at=captured_at)
    if dispatch.stops:
        await _call(client, "POST", "/dispatch/snapshots", json=dispatch.model_dump(mode="json"))


async def seed(client: httpx.AsyncClient, data_dir: Path = DEMO_DATA_DIR) -> str:
    """Post the demo schedule and the machine-down incident; return the incident id."""
    row = _first_row(data_dir / "incidents.csv")
    occurred_at = datetime.fromisoformat(row["start_time"])
    await _seed_schedule(client, data_dir, occurred_at)
    await _seed_dispatch(client, data_dir, occurred_at)
    created = await _call(
        client,
        "POST",
        "/incidents",
        json={
            "incident_type": "equipment_failure",
            "external_event_id": row["incident_id"],
            "occurred_at": row["start_time"],
            "workshop_id": DEMO_WORKSHOP,
            "resource_id": row["machine_id"],
            "report_source": "MES",
            "source_system": "sandbox_demo",
            "description": row["description"],
            "idempotency_key": f"demo:{row['incident_id']}",
            "raw_payload": row,
        },
    )
    return str(created["incident_id"])


async def seed_material(client: httpx.AsyncClient, data_dir: Path = DEMO_DATA_DIR) -> str:
    """Post the demo schedule, supply snapshot and the supplier-delay incident."""
    row = _first_row(data_dir / "supply" / "material_incident.csv")
    occurred_at = datetime.fromisoformat(row["occurred_at"])
    await _seed_schedule(client, data_dir, occurred_at)
    await _seed_supply(client, data_dir, occurred_at)
    await _seed_dispatch(client, data_dir, occurred_at)
    created = await _call(
        client,
        "POST",
        "/incidents",
        json={
            "incident_type": "material_shortage",
            "external_event_id": row["incident_id"],
            "occurred_at": row["occurred_at"],
            "workshop_id": DEMO_WORKSHOP,
            "resource_id": row["item_id"],
            "report_source": "manual",
            "source_system": "sandbox_demo",
            "description": row["description"],
            "idempotency_key": f"demo:{row['incident_id']}",
            "raw_payload": {key: value for key, value in row.items() if value != ""},
        },
    )
    return str(created["incident_id"])


def _summarise_candidates(plans: list[dict], recommendation: dict) -> list[CandidateSummary]:
    kpis = {
        str(row["plan_id"]): row["kpi_vector"]
        for row in recommendation["comparison_matrix"]["rows"]
    }
    summaries: list[CandidateSummary] = []
    for plan in plans:
        plan_id = str(plan["plan_id"])
        chain = plan["solver_chain"]
        option = chain["key_parameters"].get("material_option")
        solver = chain["solver_name"]
        is_baseline = solver == "right_shift_baseline"
        label = SOLVER_LABELS.get(solver, "重排")
        if option and not is_baseline:
            label = f"重排·{MATERIAL_OPTION_LABELS.get(option, option)}"
        moved = sum(
            1
            for work_order in plan["schedule_detail"]["work_orders"]
            for operation in work_order["operations"]
            if operation.get("is_adjusted")
        )
        kpi = kpis.get(plan_id)
        summaries.append(
            CandidateSummary(
                plan_id=plan_id,
                label=label,
                is_baseline=is_baseline,
                feasible=plan["feasibility_status"] == "feasible",
                delayed_orders=kpi["delayed_order_count"] if kpi else None,
                max_delay_minutes=kpi["max_delay_minutes"] if kpi else None,
                moved_operations=moved,
                material_option=option,
            )
        )
    return summaries


async def _walk_incident(
    client: httpx.AsyncClient,
    scenario: str,
    incident_id: str,
    supply_summary: list[str],
) -> DemoResult:
    base = f"/incidents/{incident_id}"
    impact = await _call(client, "GET", f"{base}/impact-report")
    strategy = await _call(client, "GET", f"{base}/strategy")
    plans = await _call(client, "POST", f"{base}/solve", json={})
    recommendation = await _call(client, "POST", f"{base}/recommend", json={})

    plan_id = str(recommendation["recommended_plan_id"])
    from app.api.dispatch import current_dispatch

    dispatch_plans: list[dict[str, Any]] = []
    if current_dispatch() is not None:
        dispatch_plans = (await _call(client, "GET", f"{base}/dispatch-impact"))["plans"]
    confirmed = await _call(
        client,
        "POST",
        f"{base}/confirm",
        json={"action": "accept", "selected_plan_id": plan_id},
    )
    record = await _call(client, "GET", f"{base}/decision-record")

    validation = confirmed["constraint_validation"]
    return DemoResult(
        scenario=scenario,
        incident_id=incident_id,
        decision_time=impact["analysis_reference_time"],
        affected_work_orders=len(impact["affected_work_orders"]),
        affected_operations=len(impact["affected_operations"]),
        wait_total_delay_minutes=impact["estimated_total_delay_minutes"],
        risk_distribution=impact["delivery_risk_distribution"],
        upgraded_severity=impact.get("upgraded_severity"),
        strategy_type=strategy["strategy_type"],
        candidates=_summarise_candidates(plans, recommendation),
        recommended_plan_id=plan_id,
        reason_summary=recommendation["reason_summary"],
        checked_constraints=list(validation["checked_constraints"]),
        violations=len(validation["violations"]),
        decision_record_id=str(record["decision_record_id"]),
        supply_summary=supply_summary,
        dispatch_plans=dispatch_plans,
    )


async def walk(client: httpx.AsyncClient, data_dir: Path = DEMO_DATA_DIR) -> DemoResult:
    """Machine failure: seed, analyse, solve, recommend and confirm."""
    incident_id = await seed(client, data_dir)
    return await _walk_incident(client, "equipment", incident_id, [])


async def walk_material(client: httpx.AsyncClient, data_dir: Path = DEMO_DATA_DIR) -> DemoResult:
    """Supplier delay: the same loop, with kit status deciding what must move."""
    incident_id = await seed_material(client, data_dir)
    kit = await _call(client, "GET", "/supply/kit-report")
    readiness = await _call(client, "GET", "/supply/readiness")
    impact = await _call(client, "GET", f"/incidents/{incident_id}/material-impact")
    substitutes = [rule["substitute_item_id"] for rule in impact["approved_substitutes"]]
    supply_summary = [
        f"事发前齐套    {len(kit['operations'])} 道待开工工序，按时齐套率 {kit['on_time_kit_rate']:.0%}；"
        f"已到货未可用 {readiness['arrived_not_usable_count']} 行，"
        f"未关闭缺项 {readiness['open_gap_count']} 项（无责任人 {readiness['unowned_gap_count']} 项）",
        f"供应异常后    新增等料工序 {len(impact['newly_late_operation_ids'])} 道，"
        f"无料可用 {len(impact['newly_unresolved_operation_ids'])} 道；"
        f"已批准替代料：{'、'.join(substitutes) if substitutes else '无'}",
    ]
    return await _walk_incident(client, "material", incident_id, supply_summary)
