import apiClient from './client';
import type { Incident, ScheduleSnapshot } from '@/types';

export interface DemoAuditStep {
  step: string;
  status: string;
  actor: string;
  evidence: Record<string, unknown>;
}

export interface DemoSandboxResponse {
  scenario_id: string;
  mode: string;
  validation: Record<string, unknown>;
  incident: Incident;
  snapshot: ScheduleSnapshot;
  affected_operation_count: number;
  affected_work_order_count: number;
  audit_trail: DemoAuditStep[];
  recommended_frontend_path: string[];
}

export async function resetSandboxDemo(): Promise<DemoSandboxResponse> {
  const res = await apiClient.post<DemoSandboxResponse>('/demo/sandbox/reset');
  return res.data;
}
