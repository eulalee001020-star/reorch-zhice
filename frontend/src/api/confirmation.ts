import apiClient from './client';
import type {
  ConfirmRequest,
  ConfirmResponse,
  DecisionRecord,
  ExecutionResult,
  WritebackStatusResponse,
} from '@/types';

export async function confirmPlan(data: ConfirmRequest): Promise<ConfirmResponse> {
  const res = await apiClient.post<ConfirmResponse>(
    `/incidents/${data.incident_id}/confirm`,
    data,
  );
  return res.data;
}

export async function getDecisionRecord(incidentId: string): Promise<DecisionRecord> {
  const res = await apiClient.get<DecisionRecord>(
    `/incidents/${incidentId}/decision-record`,
  );
  return res.data;
}

export async function getWritebackStatus(incidentId: string): Promise<WritebackStatusResponse> {
  const res = await apiClient.get<WritebackStatusResponse>(
    `/incidents/${incidentId}/writeback-status`,
  );
  return res.data;
}

export async function getExecutionResult(incidentId: string): Promise<ExecutionResult> {
  const res = await apiClient.get<ExecutionResult>(
    `/incidents/${incidentId}/execution-result`,
  );
  return res.data;
}
