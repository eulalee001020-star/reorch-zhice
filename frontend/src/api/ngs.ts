import apiClient from './client';
import type {
  NgsBatchReplayRequest,
  NgsBatchReplayResponse,
  NgsLabDemoResponse,
  NgsPlannerDecisionRecord,
  NgsPlannerDecisionRequest,
  NgsPlannerDecisionResponse,
} from '@/types';

export async function runNgsLabDemo(): Promise<NgsLabDemoResponse> {
  const { data } = await apiClient.post<NgsLabDemoResponse>('/ngs-lab/demo-run');
  return data;
}

export async function runNgsLabBatchReplay(
  request?: NgsBatchReplayRequest,
): Promise<NgsBatchReplayResponse> {
  const { data } = await apiClient.post<NgsBatchReplayResponse>('/ngs-lab/batch-replay', request);
  return data;
}

export async function recordNgsPlannerDecision(
  request: NgsPlannerDecisionRequest,
): Promise<NgsPlannerDecisionResponse> {
  const { data } = await apiClient.post<NgsPlannerDecisionResponse>(
    '/ngs-lab/planner-decisions',
    request,
  );
  return data;
}

export async function listNgsPlannerDecisions(params?: {
  package_id?: string;
  case_id?: string;
}): Promise<NgsPlannerDecisionRecord[]> {
  const { data } = await apiClient.get<NgsPlannerDecisionRecord[]>(
    '/ngs-lab/planner-decisions',
    { params },
  );
  return data;
}
