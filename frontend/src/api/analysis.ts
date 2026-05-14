import apiClient from './client';
import type { ImpactReport, ScheduleSnapshot, StrategyRecommendation } from '@/types';

export async function getImpactReport(incidentId: string): Promise<ImpactReport> {
  const res = await apiClient.get<ImpactReport>(`/incidents/${incidentId}/impact-report`);
  return res.data;
}

export async function getStrategy(incidentId: string): Promise<StrategyRecommendation> {
  const res = await apiClient.get<StrategyRecommendation>(`/incidents/${incidentId}/strategy`);
  return res.data;
}

export async function createScheduleSnapshot(
  data: Omit<ScheduleSnapshot, 'snapshot_id'>,
): Promise<ScheduleSnapshot> {
  const res = await apiClient.post<ScheduleSnapshot>('/schedule-snapshots', data);
  return res.data;
}
