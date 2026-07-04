import apiClient from './client';
import type {
  AgentTraceCostSummary,
  AgentTraceObserveRequest,
  CandidatePlan,
  CompiledConstraintCalibration,
  ConstraintCalibrationPack,
  DataReadinessReport,
  DecisionGraphBuildRequest,
  DecisionGraphBuildResponse,
  DigitalTwinRunResponse,
  EnterpriseImportRequest,
  EnterpriseImportResponse,
  EvidenceGateRequest,
  EvidenceGateResponse,
  InitialScheduleRequest,
  InitialScheduleResponse,
  P0RealityHarnessResponse,
  PlanQualityGateResponse,
  ReplayValidationRequest,
  ReplayValidationResponse,
  RecoveryOperatorRequest,
  RecoveryOperatorResponse,
  ScheduleSnapshot,
  ShadowCaseCaptureRequest,
  ShadowCaseCaptureResponse,
  ValueTrackingInput,
  ValueTrackingReport,
  WritebackPreviewResponse,
} from '@/types';

export async function assessInitialScheduleReadiness(
  request: InitialScheduleRequest,
): Promise<DataReadinessReport> {
  const { data } = await apiClient.post<DataReadinessReport>(
    '/planning/readiness/initial-schedule',
    request,
  );
  return data;
}

export async function assessSnapshotReadiness(
  snapshot: ScheduleSnapshot,
): Promise<DataReadinessReport> {
  const { data } = await apiClient.post<DataReadinessReport>(
    '/planning/readiness/snapshot',
    snapshot,
  );
  return data;
}

export async function generateInitialSchedules(
  request: InitialScheduleRequest,
): Promise<InitialScheduleResponse> {
  const { data } = await apiClient.post<InitialScheduleResponse>(
    '/planning/initial-schedules',
    request,
  );
  return data;
}

export async function runPlanQualityGate(
  candidatePlans: CandidatePlan[],
): Promise<PlanQualityGateResponse> {
  const { data } = await apiClient.post<PlanQualityGateResponse>(
    '/planning/quality-gate',
    { candidate_plans: candidatePlans },
  );
  return data;
}

export async function evaluateReplayValidation(
  request: ReplayValidationRequest,
): Promise<ReplayValidationResponse> {
  const { data } = await apiClient.post<ReplayValidationResponse>(
    '/planning/replay-validation/evaluate',
    request,
  );
  return data;
}

export async function captureShadowModeCase(
  request: ShadowCaseCaptureRequest,
): Promise<ShadowCaseCaptureResponse> {
  const { data } = await apiClient.post<ShadowCaseCaptureResponse>(
    '/planning/shadow-mode/capture',
    request,
  );
  return data;
}

export async function summarizeAgentObservability(
  request: AgentTraceObserveRequest,
): Promise<AgentTraceCostSummary> {
  const { data } = await apiClient.post<AgentTraceCostSummary>(
    '/planning/agent-observability/summarize',
    request,
  );
  return data;
}

export async function buildDecisionGraph(
  request: DecisionGraphBuildRequest,
): Promise<DecisionGraphBuildResponse> {
  const { data } = await apiClient.post<DecisionGraphBuildResponse>(
    '/planning/technical-kernel/decision-graph',
    request,
  );
  return data;
}

export async function selectRecoveryOperators(
  request: RecoveryOperatorRequest,
): Promise<RecoveryOperatorResponse> {
  const { data } = await apiClient.post<RecoveryOperatorResponse>(
    '/planning/technical-kernel/recovery-operators',
    request,
  );
  return data;
}

export async function evaluateEvidenceGates(
  request: EvidenceGateRequest,
): Promise<EvidenceGateResponse> {
  const { data } = await apiClient.post<EvidenceGateResponse>(
    '/planning/technical-kernel/evidence-gates',
    request,
  );
  return data;
}

export async function normalizeEnterpriseImport(
  request: EnterpriseImportRequest,
): Promise<EnterpriseImportResponse> {
  const { data } = await apiClient.post<EnterpriseImportResponse>(
    '/planning/import/erp-aps',
    request,
  );
  return data;
}

export async function runP0RealitySamplePack(): Promise<P0RealityHarnessResponse> {
  const { data } = await apiClient.post<P0RealityHarnessResponse>(
    '/planning/reality-harness/sample-pack',
  );
  return data;
}

export async function compileConstraintCalibration(
  request: ConstraintCalibrationPack,
): Promise<CompiledConstraintCalibration> {
  const { data } = await apiClient.post<CompiledConstraintCalibration>(
    '/planning/constraint-calibration/compile',
    request,
  );
  return data;
}

export async function buildWritebackPreview(
  candidatePlan: CandidatePlan,
  targetFormat = 'standard',
): Promise<WritebackPreviewResponse> {
  const { data } = await apiClient.post<WritebackPreviewResponse>(
    '/planning/writeback-preview',
    {
      candidate_plan: candidatePlan,
      target_format: targetFormat,
      only_adjusted_operations: true,
    },
  );
  return data;
}

export async function estimatePocValue(
  input: ValueTrackingInput,
): Promise<ValueTrackingReport> {
  const { data } = await apiClient.post<ValueTrackingReport>(
    '/planning/value-report',
    input,
  );
  return data;
}

export async function runDigitalTwinSample(): Promise<DigitalTwinRunResponse> {
  const { data } = await apiClient.post<DigitalTwinRunResponse>(
    '/planning/digital-twin/sample-run',
  );
  return data;
}
