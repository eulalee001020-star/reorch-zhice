"""Planning API endpoints for initial scheduling and PoC readiness."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.models.planning import (
    DataReadinessReport,
    DigitalTwinRunResponse,
    EnterpriseImportRequest,
    EnterpriseImportResponse,
    InitialScheduleRequest,
    InitialScheduleResponse,
    PlanQualityGateRequest,
    PlanQualityGateResponse,
    ValueTrackingInput,
    ValueTrackingReport,
    WritebackPreviewRequest,
    WritebackPreviewResponse,
)
from app.models.schedule import ScheduleSnapshot
from app.services.data_readiness import DataReadinessService
from app.services.digital_twin_runner import DigitalTwinRunner
from app.services.enterprise_integration import EnterpriseIntegrationService
from app.services.initial_scheduler import InitialScheduler
from app.services.plan_quality_gate import PlanQualityGate
from app.services.value_tracking import ValueTrackingService

router = APIRouter(prefix="/api/v1/planning", tags=["planning"])


@router.post(
    "/readiness/initial-schedule",
    response_model=DataReadinessReport,
    summary="评估初始调度数据就绪度",
)
async def assess_initial_schedule_readiness(
    body: InitialScheduleRequest,
) -> DataReadinessReport:
    return DataReadinessService().assess_initial_schedule_request(body)


@router.post(
    "/readiness/snapshot",
    response_model=DataReadinessReport,
    summary="评估异常重排快照数据就绪度",
)
async def assess_snapshot_readiness(
    body: ScheduleSnapshot,
) -> DataReadinessReport:
    return DataReadinessService().assess_schedule_snapshot(body)


@router.post(
    "/initial-schedules",
    response_model=InitialScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="从零生成多套初始调度方案",
)
async def generate_initial_schedules(
    body: InitialScheduleRequest,
) -> InitialScheduleResponse:
    response = await InitialScheduler().generate(body)
    if not response.readiness_report.is_ready:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=response.readiness_report.model_dump(mode="json"),
        )
    return response


@router.post(
    "/import/erp-aps",
    response_model=EnterpriseImportResponse,
    summary="归一化 ERP/MES/APS 原始数据",
)
async def normalize_enterprise_import(
    body: EnterpriseImportRequest,
) -> EnterpriseImportResponse:
    return EnterpriseIntegrationService().normalize_initial_schedule(body)


@router.post(
    "/writeback-preview",
    response_model=WritebackPreviewResponse,
    summary="生成客户系统回写预览",
)
async def build_writeback_preview(
    body: WritebackPreviewRequest,
) -> WritebackPreviewResponse:
    return EnterpriseIntegrationService().build_writeback_preview(body)


@router.post(
    "/quality-gate",
    response_model=PlanQualityGateResponse,
    summary="执行候选方案可用性闸门",
)
async def run_quality_gate(
    body: PlanQualityGateRequest,
) -> PlanQualityGateResponse:
    gate = PlanQualityGate()
    return PlanQualityGateResponse(
        reports=[gate.evaluate(plan) for plan in body.candidate_plans]
    )


@router.post(
    "/value-report",
    response_model=ValueTrackingReport,
    summary="估算 PoC 前后价值与 ROI",
)
async def estimate_value(
    body: ValueTrackingInput,
) -> ValueTrackingReport:
    return ValueTrackingService().estimate(body)


@router.post(
    "/digital-twin/sample-run",
    response_model=DigitalTwinRunResponse,
    summary="运行内置数字孪生 PoC 样例",
)
async def run_digital_twin_sample() -> DigitalTwinRunResponse:
    return await DigitalTwinRunner().run_sample()
