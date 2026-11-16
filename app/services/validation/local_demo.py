"""Walk the whole decision loop in-process, with no external services.

The API keeps its working state in memory when Postgres, Redis and Kafka are
absent, so one process is enough to show the loop end to end. ``walk`` drives
the same HTTP routes the frontend calls, which makes it both the local demo
and a regression check that the dependency-free path keeps working.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.adapters.csv_adapter import CSVAdapter
from app.core.paths import REPO_ROOT

DEMO_DATA_DIR = REPO_ROOT / "demo" / "data"
DEMO_WORKSHOP = "DEMO-LINE-01"
API_PREFIX = "/api/v1"


@dataclass
class DemoResult:
    """What one walk through the loop produced."""

    incident_id: str
    affected_work_orders: int
    affected_operations: int
    upgraded_severity: str | None
    strategy_type: str
    strategy_reasoning: str
    candidate_count: int
    feasible_candidates: int
    recommended_plan_id: str
    recommended_solver: str
    reason_summary: str
    checked_constraints: list[str] = field(default_factory=list)
    violations: int = 0
    decision_record_id: str = ""

    def lines(self) -> list[str]:
        return [
            f"异常事件      {self.incident_id}",
            f"影响范围      {self.affected_work_orders} 张工单 / {self.affected_operations} 道工序"
            + (f"，严重度升级为 {self.upgraded_severity}" if self.upgraded_severity else ""),
            f"恢复策略      {self.strategy_type}",
            f"候选方案      {self.candidate_count} 个，其中 {self.feasible_candidates} 个满足全部硬约束",
            f"推荐方案      {self.recommended_plan_id}（{self.recommended_solver}）",
            f"推荐理由      {self.reason_summary}",
            f"确认前校验    {len(self.checked_constraints)} 类约束，违反 {self.violations} 项",
            f"决策记录      {self.decision_record_id}",
        ]


def _first_incident_row(data_dir: Path) -> dict[str, Any]:
    with (data_dir / "incidents.csv").open(newline="", encoding="utf-8") as handle:
        return dict(next(csv.DictReader(handle)))


async def _call(client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> Any:
    response = await client.request(method, f"{API_PREFIX}{path}", **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
    return response.json()


def reset_in_memory_state() -> None:
    """Clear the API's in-memory working stores so a walk starts from nothing."""
    from app.api.analysis import _impact_report_cache, _snapshot_store, _strategy_cache
    from app.api.incidents import _incident_store
    from app.api.solver import _candidate_plans_store, _plan_index, _recommendation_store

    for store in (
        _incident_store,
        _snapshot_store,
        _impact_report_cache,
        _strategy_cache,
        _candidate_plans_store,
        _plan_index,
        _recommendation_store,
    ):
        store.clear()


async def seed(client: httpx.AsyncClient, data_dir: Path = DEMO_DATA_DIR) -> str:
    """Post the demo schedule snapshot and incident; return the incident id."""
    snapshot = await CSVAdapter(data_dir).fetch_current_schedule(workshop_id=DEMO_WORKSHOP)
    await _call(client, "POST", "/schedule-snapshots", json=snapshot.model_dump(mode="json"))
    row = _first_incident_row(data_dir)
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


async def walk(client: httpx.AsyncClient, data_dir: Path = DEMO_DATA_DIR) -> DemoResult:
    """Seed, analyse, solve, recommend and confirm one incident."""
    incident_id = await seed(client, data_dir)
    base = f"/incidents/{incident_id}"

    impact = await _call(client, "GET", f"{base}/impact-report")
    strategy = await _call(client, "GET", f"{base}/strategy")
    plans = await _call(client, "POST", f"{base}/solve", json={})
    recommendation = await _call(client, "POST", f"{base}/recommend", json={})

    plan_id = str(recommendation["recommended_plan_id"])
    chosen = next(plan for plan in plans if str(plan["plan_id"]) == plan_id)
    confirmed = await _call(
        client,
        "POST",
        f"{base}/confirm",
        json={"action": "accept", "selected_plan_id": plan_id},
    )
    record = await _call(client, "GET", f"{base}/decision-record")

    validation = confirmed["constraint_validation"]
    return DemoResult(
        incident_id=incident_id,
        affected_work_orders=len(impact["affected_work_orders"]),
        affected_operations=len(impact["affected_operations"]),
        upgraded_severity=impact.get("upgraded_severity"),
        strategy_type=strategy["strategy_type"],
        strategy_reasoning=strategy.get("reasoning", ""),
        candidate_count=len(plans),
        feasible_candidates=sum(1 for plan in plans if plan["feasibility_status"] == "feasible"),
        recommended_plan_id=plan_id,
        recommended_solver=chosen["solver_chain"].get("solver_name", ""),
        reason_summary=recommendation["reason_summary"],
        checked_constraints=list(validation["checked_constraints"]),
        violations=len(validation["violations"]),
        decision_record_id=str(record["decision_record_id"]),
    )
