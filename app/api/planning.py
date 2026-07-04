"""Planning API endpoints for initial scheduling and PoC readiness."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.models.agent_observability import (
    AgentTraceCostSummary,
    AgentTraceObserveRequest,
)
from app.models.constraint_calibration import (
    CompiledConstraintCalibration,
    ConstraintCalibrationPack,
)
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
from app.models.reality_harness import (
    FieldMappingCompileRequest,
    FieldMappingCompileResponse,
    P0RealityHarnessRequest,
    P0RealityHarnessResponse,
)
from app.models.replay_validation import (
    ReplayValidationRequest,
    ReplayValidationResponse,
)
from app.models.schedule import ScheduleSnapshot
from app.models.shadow_mode import (
    ShadowCaseCaptureRequest,
    ShadowCaseCaptureResponse,
)
from app.services.agent_observability import AgentObservabilityService
from app.services.constraint_calibration import ConstraintCalibrationService
from app.services.data_readiness import DataReadinessService
from app.services.digital_twin_runner import DigitalTwinRunner
from app.services.enterprise_integration import EnterpriseIntegrationService
from app.services.field_mapping_compiler import FieldMappingCompiler
from app.services.initial_scheduler import InitialScheduler
from app.services.plan_quality_gate import PlanQualityGate
from app.services.reality_harness import P0RealityHarnessService
from app.services.replay_validation import ReplayValidationService
from app.services.shadow_mode import ShadowModeService
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
    "/reality-harness/assess",
    response_model=P0RealityHarnessResponse,
    summary="运行 P0 Reality Harness 客户数据闸门",
)
async def assess_p0_reality_harness(
    body: P0RealityHarnessRequest,
) -> P0RealityHarnessResponse:
    return P0RealityHarnessService().assess(body)


@router.post(
    "/reality-harness/sample-pack",
    response_model=P0RealityHarnessResponse,
    summary="运行内置 P0 Reality Harness 样例包",
)
async def run_p0_reality_sample_pack() -> P0RealityHarnessResponse:
    service = P0RealityHarnessService()
    return service.assess(service.load_sample_pack())


@router.post(
    "/reality-harness/suggest-mapping",
    response_model=FieldMappingCompileResponse,
    summary="根据客户样例字段生成保守 mapping 建议",
)
async def suggest_reality_harness_mapping(
    body: FieldMappingCompileRequest,
) -> FieldMappingCompileResponse:
    return FieldMappingCompiler().compile(body)


@router.post(
    "/constraint-calibration/compile",
    response_model=CompiledConstraintCalibration,
    summary="编译已标定的现场约束",
)
async def compile_constraint_calibration(
    body: ConstraintCalibrationPack,
) -> CompiledConstraintCalibration:
    return ConstraintCalibrationService().compile(body)


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
    "/replay-validation/evaluate",
    response_model=ReplayValidationResponse,
    summary="评估历史 replay 与 shadow 可比性",
)
async def evaluate_replay_validation(
    body: ReplayValidationRequest,
) -> ReplayValidationResponse:
    return ReplayValidationService().evaluate(body)


@router.post(
    "/shadow-mode/capture",
    response_model=ShadowCaseCaptureResponse,
    summary="记录只读 shadow mode 计划员反馈",
)
async def capture_shadow_mode_case(
    body: ShadowCaseCaptureRequest,
) -> ShadowCaseCaptureResponse:
    return ShadowModeService().capture(body)


@router.post(
    "/agent-observability/summarize",
    response_model=AgentTraceCostSummary,
    summary="统计 Agent trace 成本、延迟和降级情况",
)
async def summarize_agent_observability(
    body: AgentTraceObserveRequest,
) -> AgentTraceCostSummary:
    return AgentObservabilityService().summarize(body)


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
