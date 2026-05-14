import apiClient from './client';
import type {
  CandidatePlan,
  GanttDiffPayload,
  PlanSelectionOutput,
} from '@/types';

export async function solveIncident(incidentId: string): Promise<void> {
  await apiClient.post(`/incidents/${incidentId}/solve`);
}

export async function listCandidatePlans(incidentId: string): Promise<CandidatePlan[]> {
  const res = await apiClient.get<CandidatePlan[]>(`/incidents/${incidentId}/candidate-plans`);
  return res.data;
}

export async function getCandidatePlan(planId: string): Promise<CandidatePlan> {
  const res = await apiClient.get<CandidatePlan>(`/candidate-plans/${planId}`);
  return res.data;
}

export async function getCandidatePlanGantt(planId: string): Promise<GanttDiffPayload> {
  const res = await apiClient.get<GanttDiffPayload>(`/candidate-plans/${planId}/gantt`);
  return res.data;
}

export interface RecommendParams {
  goal_mode?: string;
  manual_weights?: Record<string, number>;
}

export async function recommendPlan(
  incidentId: string,
  params?: RecommendParams,
): Promise<PlanSelectionOutput> {
  const res = await apiClient.post<PlanSelectionOutput>(
    `/incidents/${incidentId}/recommend`,
    params,
  );
  return res.data;
}

export async function getRecommendation(incidentId: string): Promise<PlanSelectionOutput> {
  const res = await apiClient.get<PlanSelectionOutput>(
    `/incidents/${incidentId}/recommendation`,
  );
  return res.data;
}
