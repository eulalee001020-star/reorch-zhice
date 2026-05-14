import apiClient from './client';
import type {
  CandidatePlan,
  DataReadinessReport,
  DigitalTwinRunResponse,
  EnterpriseImportRequest,
  EnterpriseImportResponse,
  InitialScheduleRequest,
  InitialScheduleResponse,
  PlanQualityGateResponse,
  ScheduleSnapshot,
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

export async function normalizeEnterpriseImport(
  request: EnterpriseImportRequest,
): Promise<EnterpriseImportResponse> {
  const { data } = await apiClient.post<EnterpriseImportResponse>(
    '/planning/import/erp-aps',
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
