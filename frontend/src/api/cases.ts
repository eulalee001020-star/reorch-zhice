import apiClient from './client';
import type { CaseRecord, CaseTemplate, PreferenceProfile } from '@/types';

export interface ListCasesParams {
  incident_type?: string;
  strategy_type?: string;
  start_time?: string;
  end_time?: string;
  execution_result?: string;
}

export async function listCases(params?: ListCasesParams): Promise<CaseRecord[]> {
  const res = await apiClient.get<CaseRecord[]>('/cases', { params });
  return res.data;
}

export async function getCase(caseId: string): Promise<CaseRecord> {
  const res = await apiClient.get<CaseRecord>(`/cases/${caseId}`);
  return res.data;
}

export async function listTemplates(): Promise<CaseTemplate[]> {
  const res = await apiClient.get<CaseTemplate[]>('/case-templates');
  return res.data;
}

export async function createTemplate(
  data: Omit<CaseTemplate, 'template_id' | 'reference_count' | 'adoption_rate' | 'created_at'>,
): Promise<CaseTemplate> {
  const res = await apiClient.post<CaseTemplate>('/case-templates', data);
  return res.data;
}

export async function editTemplate(
  templateId: string,
  data: Partial<CaseTemplate>,
): Promise<CaseTemplate> {
  const res = await apiClient.put<CaseTemplate>(`/case-templates/${templateId}`, data);
  return res.data;
}

export async function publishTemplate(templateId: string): Promise<CaseTemplate> {
  const res = await apiClient.post<CaseTemplate>(`/case-templates/${templateId}/publish`);
  return res.data;
}

export async function getPreferenceProfile(plannerId: string): Promise<PreferenceProfile> {
  const res = await apiClient.get<PreferenceProfile>(
    `/planners/${plannerId}/preference-profile`,
  );
  return res.data;
}
