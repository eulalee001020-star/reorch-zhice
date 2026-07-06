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
from app.models.flexible_shop import (
    CounterfactualReplayMatrixRequest,
    CounterfactualReplayMatrixResponse,
    CounterfactualReplayRunRequest,
    CounterfactualReplayRunResponse,
    DecompositionSolveRequest,
    DecompositionSolveResponse,
    DynamicReschedulingPlanRequest,
    DynamicReschedulingPlanResponse,
    ExecutionFeedbackIngestionRequest,
    ExecutionFeedbackIngestionResponse,
    FlexibleShopBenchmarkRequest,
    FlexibleShopBenchmarkResponse,
    FlexibleShopCapabilityRequest,
    FlexibleShopCapabilityResponse,
    LargeFjspConstraintModelRequest,
    LargeFjspConstraintModelResponse,
    MultiIncidentRecoveryRequest,
    MultiIncidentRecoveryResponse,
    ProductionWritebackSafetyRequest,
    ProductionWritebackSafetyResponse,
    RealDataIntegrationRequest,
    RealDataIntegrationResponse,
)
from app.models.large_fjsp_replay import (
    LargeFjspReplayRequest,
    LargeFjspReplayResponse,
)
from app.models.level23_digital_twin import (
    Level23DigitalTwinReplayRequest,
    Level23DigitalTwinReplayResponse,
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
from app.models.production_readiness import (
    ProductionReadinessEvidence,
    ProductionReadinessResponse,
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
from app.models.technical_kernel import (
    DecisionGraphBuildRequest,
    DecisionGraphBuildResponse,
    EvidenceGateRequest,
    EvidenceGateResponse,
    RecoveryOperatorRequest,
    RecoveryOperatorResponse,
)
from app.services.agent_observability import AgentObservabilityService
from app.services.constraint_calibration import ConstraintCalibrationService
from app.services.data_readiness import DataReadinessService
from app.services.digital_twin_runner import DigitalTwinRunner
from app.services.enterprise_integration import EnterpriseIntegrationService
from app.services.field_mapping_compiler import FieldMappingCompiler
from app.services.flexible_shop_capability import (
    CounterfactualReplayMatrixService,
    CounterfactualReplayRunner,
    DecompositionDynamicSolver,
    DynamicReschedulingPlanner,
    ExecutionFeedbackService,
    FlexibleShopBenchmarkService,
    FlexibleShopCapabilityService,
    LargeFjspConstraintCompiler,
    MultiIncidentRecoveryStrategyService,
    ProductionWritebackSafetyService,
    RealDataIntegrationService,
)
from app.services.initial_scheduler import InitialScheduler
from app.services.large_fjsp_replay import LargeFjspReplayService
from app.services.level23_digital_twin import Level23DigitalTwinReplayEvaluator
from app.services.plan_quality_gate import PlanQualityGate
from app.services.production_readiness import ProductionReadinessGate
from app.services.reality_harness import P0RealityHarnessService
from app.services.replay_validation import ReplayValidationService
from app.services.shadow_mode import ShadowModeService
from app.services.technical_kernel import (
    DecisionGraphService,
    EvidenceGateService,
    RecoveryOperatorPortfolioService,
)
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
    "/technical-kernel/decision-graph",
    response_model=DecisionGraphBuildResponse,
    summary="构建生产状态决策图",
)
async def build_decision_graph(
    body: DecisionGraphBuildRequest,
) -> DecisionGraphBuildResponse:
    return DecisionGraphService().build(body)


@router.post(
    "/technical-kernel/recovery-operators",
    response_model=RecoveryOperatorResponse,
    summary="选择异常恢复算子组合",
)
async def select_recovery_operators(
    body: RecoveryOperatorRequest,
) -> RecoveryOperatorResponse:
    return RecoveryOperatorPortfolioService().select(body)


@router.post(
    "/technical-kernel/evidence-gates",
    response_model=EvidenceGateResponse,
    summary="执行证据门控求解策略",
)
async def evaluate_evidence_gates(
    body: EvidenceGateRequest,
) -> EvidenceGateResponse:
    return EvidenceGateService().evaluate(body)


@router.post(
    "/flexible-shop/capability-assessment",
    response_model=FlexibleShopCapabilityResponse,
    summary="评估大规模柔性作业车间补强就绪度",
)
async def assess_flexible_shop_capability(
    body: FlexibleShopCapabilityRequest,
) -> FlexibleShopCapabilityResponse:
    return FlexibleShopCapabilityService().assess(body)


@router.post(
    "/flexible-shop/real-data-integration",
    response_model=RealDataIntegrationResponse,
    summary="评估真实 ERP/MES/WMS/QMS/IoT 数据接入合同",
)
async def assess_flexible_shop_real_data_integration(
    body: RealDataIntegrationRequest,
) -> RealDataIntegrationResponse:
    return RealDataIntegrationService().assess(body)


@router.post(
    "/flexible-shop/constraint-model",
    response_model=LargeFjspConstraintModelResponse,
    summary="编译大规模 FJSP 约束模型",
)
async def compile_large_fjsp_constraint_model(
    body: LargeFjspConstraintModelRequest,
) -> LargeFjspConstraintModelResponse:
    return LargeFjspConstraintCompiler().compile(body)


@router.post(
    "/flexible-shop/decomposition-solve-route",
    response_model=DecompositionSolveResponse,
    summary="生成分解式动态重调度求解路线",
)
async def plan_flexible_shop_decomposition_solve_route(
    body: DecompositionSolveRequest,
) -> DecompositionSolveResponse:
    return DecompositionDynamicSolver().plan(body)


@router.post(
    "/flexible-shop/dynamic-rescheduling-plan",
    response_model=DynamicReschedulingPlanResponse,
    summary="生成大规模柔性作业车间动态重调度策略计划",
)
async def plan_flexible_shop_dynamic_rescheduling(
    body: DynamicReschedulingPlanRequest,
) -> DynamicReschedulingPlanResponse:
    return DynamicReschedulingPlanner().plan(body)


@router.post(
    "/flexible-shop/multi-incident-recovery",
    response_model=MultiIncidentRecoveryResponse,
    summary="生成多异常类型恢复策略候选",
)
async def build_flexible_shop_multi_incident_recovery(
    body: MultiIncidentRecoveryRequest,
) -> MultiIncidentRecoveryResponse:
    return MultiIncidentRecoveryStrategyService().build(body)


@router.post(
    "/flexible-shop/synthetic-benchmark",
    response_model=FlexibleShopBenchmarkResponse,
    summary="运行大规模柔性作业车间合成基准代理",
)
async def run_flexible_shop_synthetic_benchmark(
    body: FlexibleShopBenchmarkRequest,
) -> FlexibleShopBenchmarkResponse:
    return FlexibleShopBenchmarkService().run(body)


@router.post(
    "/flexible-shop/counterfactual-replay-matrix",
    response_model=CounterfactualReplayMatrixResponse,
    summary="生成反事实 replay 策略效果矩阵",
)
async def build_counterfactual_replay_matrix(
    body: CounterfactualReplayMatrixRequest,
) -> CounterfactualReplayMatrixResponse:
    return CounterfactualReplayMatrixService().build(body)


@router.post(
    "/flexible-shop/counterfactual-replay-run",
    response_model=CounterfactualReplayRunResponse,
    summary="运行反事实 replay 并生成策略效果矩阵",
)
async def run_counterfactual_replay(
    body: CounterfactualReplayRunRequest,
) -> CounterfactualReplayRunResponse:
    return CounterfactualReplayRunner().run(body)


@router.post(
    "/flexible-shop/writeback-safety-gate",
    response_model=ProductionWritebackSafetyResponse,
    summary="执行生产回写安全门控",
)
async def evaluate_flexible_shop_writeback_safety(
    body: ProductionWritebackSafetyRequest,
) -> ProductionWritebackSafetyResponse:
    return ProductionWritebackSafetyService().evaluate(body)


@router.post(
    "/flexible-shop/execution-feedback",
    response_model=ExecutionFeedbackIngestionResponse,
    summary="接收现场执行反馈并生成策略图谱更新",
)
async def ingest_flexible_shop_execution_feedback(
    body: ExecutionFeedbackIngestionRequest,
) -> ExecutionFeedbackIngestionResponse:
    return ExecutionFeedbackService().ingest(body)


@router.post(
    "/flexible-shop/large-fjsp/replay",
    response_model=LargeFjspReplayResponse,
    summary="运行大规模 FJSP 异常多策略重调度 replay",
)
async def run_large_fjsp_replay(
    body: LargeFjspReplayRequest,
) -> LargeFjspReplayResponse:
    return LargeFjspReplayService().run(body)


@router.post(
    "/production-readiness/evaluate",
    response_model=ProductionReadinessResponse,
    summary="评估当前证据可进入的最高生产应用等级",
)
async def evaluate_production_readiness(
    body: ProductionReadinessEvidence,
) -> ProductionReadinessResponse:
    return ProductionReadinessGate().evaluate(body)


@router.post(
    "/digital-twin/level2-3/evaluate",
    response_model=Level23DigitalTwinReplayResponse,
    summary="评估 Level 2/3 数字孪生 replay 演练数据包",
)
async def evaluate_level23_digital_twin_pack(
    body: Level23DigitalTwinReplayRequest,
) -> Level23DigitalTwinReplayResponse:
    return Level23DigitalTwinReplayEvaluator().evaluate(body)


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
