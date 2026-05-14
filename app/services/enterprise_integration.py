"""Enterprise ERP/MES/APS normalization and writeback-preview adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.adapters.mes_adapter import MESAdapter, MESFormat, MESInstruction
from app.models.planning import (
    EnterpriseImportRequest,
    EnterpriseImportResponse,
    InitialScheduleRequest,
    PlanningOperationInput,
    PlanningResourceInput,
    PlanningWorkOrderInput,
    WritebackPreviewRequest,
    WritebackPreviewResponse,
)
from app.services.data_readiness import DataReadinessService


class EnterpriseIntegrationService:
    """Normalizes common ERP/MES/APS payloads into ReOrch planning inputs."""

    def __init__(self, readiness: DataReadinessService | None = None) -> None:
        self._readiness = readiness or DataReadinessService()

    def normalize_initial_schedule(
        self,
        request: EnterpriseImportRequest,
    ) -> EnterpriseImportResponse:
        mapping = request.mapping
        raw = request.raw_payload
        resources_payload = _get_path(raw, mapping.resources_path, [])
        work_orders_payload = _get_path(raw, mapping.work_orders_path, [])

        resources = [
            PlanningResourceInput(
                resource_id=str(_get(raw_res, "resource_id", raw_res.get("id", ""))),
                name=_get(raw_res, "name", None),
                capabilities=list(_get(raw_res, mapping.resource_capabilities, [])),
                is_bottleneck=bool(_get(raw_res, "is_bottleneck", False)),
                has_redundancy=bool(_get(raw_res, "has_redundancy", False)),
                criticality=str(_get(raw_res, "criticality", "general")),
                cost_per_minute=float(_get(raw_res, "cost_per_minute", 1.0) or 1.0),
            )
            for raw_res in resources_payload
        ]

        work_orders: list[PlanningWorkOrderInput] = []
        for raw_wo in work_orders_payload:
            wo_id = str(_get(raw_wo, mapping.work_order_id, ""))
            family = _get(raw_wo, mapping.product_family, None)
            operations: list[PlanningOperationInput] = []
            for raw_op in _get(raw_wo, mapping.operations, []):
                duration = _get(raw_op, mapping.duration_minutes, None)
                if duration is None and _get(raw_op, "start_time", None) and _get(raw_op, "end_time", None):
                    duration = _minutes_between(
                        _parse_dt(_get(raw_op, "start_time")),
                        _parse_dt(_get(raw_op, "end_time")),
                    )
                eligible = _get(raw_op, mapping.eligible_resource_ids, None)
                if eligible is None:
                    resource_id = _get(raw_op, mapping.resource_id, None)
                    eligible = [resource_id] if resource_id else []
                operations.append(
                    PlanningOperationInput(
                        operation_id=str(_get(raw_op, mapping.operation_id, "")),
                        work_order_id=str(_get(raw_op, mapping.work_order_id, wo_id)),
                        duration_minutes=int(duration or 1),
                        eligible_resource_ids=[str(r) for r in eligible],
                        required_capabilities=[
                            str(c) for c in _get(raw_op, mapping.required_capabilities, [])
                        ],
                        predecessor_ids=[
                            str(p) for p in _get(raw_op, mapping.predecessor_ids, [])
                        ],
                        product_family=str(_get(raw_op, mapping.product_family, family or "unknown")),
                    )
                )

            work_orders.append(
                PlanningWorkOrderInput(
                    work_order_id=wo_id,
                    product_name=str(_get(raw_wo, mapping.product_name, wo_id)),
                    product_family=str(family) if family else None,
                    due_date=_parse_dt(_get(raw_wo, mapping.due_date)),
                    priority=int(_get(raw_wo, mapping.priority, 0) or 0),
                    operations=operations,
                )
            )

        initial_request = InitialScheduleRequest(
            workshop_id=request.workshop_id,
            planning_start=request.planning_start,
            resources=resources,
            work_orders=work_orders,
        )
        readiness_report = self._readiness.assess_initial_schedule_request(initial_request)
        return EnterpriseImportResponse(
            source_system=request.source_system,
            readiness_report=readiness_report,
            initial_schedule_request=initial_request,
        )

    def build_writeback_preview(
        self,
        request: WritebackPreviewRequest,
    ) -> WritebackPreviewResponse:
        target_format = _resolve_mes_format(request.target_format)
        adapter = MESAdapter(mes_format=target_format)
        instructions: list[dict[str, Any]] = []

        for wo in request.candidate_plan.schedule_detail.work_orders:
            for op in wo.operations:
                if request.only_adjusted_operations and not (op.is_adjusted or op.is_affected):
                    continue
                instruction = MESInstruction(
                    instruction_id=f"{request.candidate_plan.plan_id}:{op.operation_id}",
                    work_order_id=wo.work_order_id,
                    operation_id=op.operation_id,
                    resource_id=op.resource_id,
                    start_time=op.start_time.isoformat(),
                    end_time=op.end_time.isoformat(),
                    metadata={
                        "plan_id": str(request.candidate_plan.plan_id),
                        "strategy_type": request.candidate_plan.strategy_type,
                    },
                )
                instructions.append(adapter.convert_instruction(instruction))

        return WritebackPreviewResponse(
            target_format=target_format.value,
            instruction_count=len(instructions),
            instructions=instructions,
        )


def _get(payload: dict[str, Any], key: str, default: Any = None) -> Any:
    return payload.get(key, default)


def _get_path(payload: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = payload
    for segment in path.split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(segment)
        if current is None:
            return default
    return current


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Cannot parse datetime from {value!r}")


def _minutes_between(start: datetime, end: datetime) -> int:
    return max(1, int((end - start).total_seconds() // 60))


def _resolve_mes_format(value: str) -> MESFormat:
    try:
        return MESFormat(value)
    except ValueError:
        return MESFormat.STANDARD
