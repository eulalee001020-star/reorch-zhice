"""Public-safe sandbox demo endpoints.

The demo routes only use the small checked-in ``demo/data`` package. They do
not expose generated benchmark/customer-event packs and do not claim real
customer integration.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.adapters.csv_adapter import CSVAdapter
from app.adapters.mapping_validator import MappingValidationReport, validate_customer_payloads
from app.core.auth import CurrentUser, get_optional_current_user
from app.models.base import ReOrchModel
from app.models.enums import IncidentSeverity, IncidentStatus, IncidentType, ReportSource
from app.models.incident import Incident
from app.models.schedule import ScheduleSnapshot

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DATA_DIR = REPO_ROOT / "demo" / "data"
DEMO_INCIDENT_ID = UUID("11111111-1111-4111-8111-111111111111")
DEMO_SNAPSHOT_ID = UUID("22222222-2222-4222-8222-222222222222")
DEMO_OCCURRED_AT = datetime(2026, 5, 14, 13, 10, tzinfo=timezone(timedelta(hours=8)))


class DemoAuditStep(ReOrchModel):
    """Human-readable demo audit item."""

    step: str
    status: str
    actor: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class DemoSandboxResponse(ReOrchModel):
    """Stable response returned by the public sandbox reset endpoint."""

    scenario_id: str
    mode: str
    validation: MappingValidationReport
    incident: Incident
    snapshot: ScheduleSnapshot
    affected_operation_count: int
    affected_work_order_count: int
    audit_trail: list[DemoAuditStep] = Field(default_factory=list)
    recommended_frontend_path: list[str] = Field(default_factory=list)


@router.post(
    "/sandbox/reset",
    response_model=DemoSandboxResponse,
    summary="加载公开安全版 sandbox demo 场景",
    description=(
        "读取 demo/data 中的小型固定样例，执行 adapter-level validation，"
        "再把排程快照和 M-03 设备故障事件写入本地运行态，供前端一键演示。"
    ),
)
async def reset_sandbox_demo(
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> DemoSandboxResponse:
    raw = _load_demo_rows()
    validation = validate_customer_payloads(
        raw_work_orders=raw["work_orders"],
        raw_operations=raw["operations"],
        raw_machines=raw["machines"],
        raw_incidents=raw["incidents"],
    )
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=validation.model_dump(mode="json"),
        )

    _clear_runtime_state()

    adapter = CSVAdapter(DEMO_DATA_DIR)
    snapshot = await adapter.fetch_current_schedule(workshop_id="DEMO-LINE-01")
    snapshot = snapshot.model_copy(
        update={
            "snapshot_id": DEMO_SNAPSHOT_ID,
            "captured_at": DEMO_OCCURRED_AT,
            "created_by": current_user.user_id,
            "source_system": "sandbox_demo_csv",
        }
    )

    raw_incident = raw["incidents"][0]
    incident = Incident(
        incident_id=DEMO_INCIDENT_ID,
        incident_type=IncidentType.EQUIPMENT_FAILURE,
        external_event_id=raw_incident["incident_id"],
        occurred_at=datetime.fromisoformat(raw_incident["start_time"]),
        workshop_id="DEMO-LINE-01",
        resource_id=raw_incident["machine_id"],
        report_source=ReportSource.MES,
        source_system="sandbox_demo_csv",
        severity=IncidentSeverity.P2_HIGH,
        status=IncidentStatus.PENDING_ANALYSIS,
        description=raw_incident["description"],
        idempotency_key=f"demo:{raw_incident['incident_id']}",
        created_by=current_user.user_id,
        raw_payload=raw_incident,
    )
    affected = _affected_operations(raw["operations"], raw_incident)

    from app.api.analysis import _snapshot_store
    from app.api.incidents import _incident_store

    _snapshot_store[str(snapshot.snapshot_id)] = snapshot
    _incident_store[str(incident.incident_id)] = incident

    return DemoSandboxResponse(
        scenario_id="M03_MACHINE_DOWN_4H",
        mode="pending_human_confirmation",
        validation=validation,
        incident=incident,
        snapshot=snapshot,
        affected_operation_count=len(affected),
        affected_work_order_count=len({item["work_order_id"] for item in affected}),
        audit_trail=[
            DemoAuditStep(
                step="adapter_validation",
                status="passed",
                actor="MappingValidator",
                evidence={
                    "blocking_errors": validation.blocking_errors,
                    "warnings": validation.warnings,
                    "total_records": validation.total_records,
                },
            ),
            DemoAuditStep(
                step="snapshot_loaded",
                status="completed",
                actor="CSVAdapter",
                evidence={"snapshot_id": str(snapshot.snapshot_id)},
            ),
            DemoAuditStep(
                step="incident_loaded",
                status="completed",
                actor="DemoSandbox",
                evidence={"incident_id": str(incident.incident_id), "resource_id": incident.resource_id},
            ),
        ],
        recommended_frontend_path=[
            "登录 Planner 账号",
            "打开 决策工作台",
            "点击 加载演示场景",
            "查看 M-03 设备故障影响分析",
            "查看候选方案和推荐解释",
            "由计划员确认后再进入受控回写",
        ],
    )


def _clear_runtime_state() -> None:
    from app.api.analysis import _impact_report_cache, _snapshot_store, _strategy_cache
    from app.api.incidents import _incident_store
    from app.api.solver import _candidate_plans_store, _plan_index, _recommendation_store

    _incident_store.clear()
    _snapshot_store.clear()
    _impact_report_cache.clear()
    _strategy_cache.clear()
    _candidate_plans_store.clear()
    _plan_index.clear()
    _recommendation_store.clear()


def _load_demo_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        "work_orders": _read_csv(DEMO_DATA_DIR / "work_orders.csv"),
        "operations": _read_csv(DEMO_DATA_DIR / "operations.csv"),
        "machines": _read_csv(DEMO_DATA_DIR / "machines.csv"),
        "incidents": _read_csv(DEMO_DATA_DIR / "incidents.csv"),
    }


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _affected_operations(
    operations: list[dict[str, Any]],
    incident: dict[str, Any],
) -> list[dict[str, Any]]:
    machine_id = incident["machine_id"]
    start = datetime.fromisoformat(incident["start_time"])
    end = start + timedelta(hours=4)
    affected: list[dict[str, Any]] = []
    for operation in operations:
        if operation.get("machine_id") != machine_id:
            continue
        op_start = datetime.fromisoformat(operation["start_time"])
        op_end = datetime.fromisoformat(operation["end_time"])
        if op_start < end and op_end > start:
            affected.append(operation)
    return affected
