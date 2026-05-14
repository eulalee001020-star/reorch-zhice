import apiClient from './client';
import type {
  AgentDecisionFlowRequest,
  AgentDecisionFlowResponse,
  FeedbackStructuringOutput,
  FeedbackStructuringRequest,
  IncidentUnderstandingOutput,
  IncidentUnderstandingRequest,
} from '@/types';

export async function understandIncidentText(
  data: IncidentUnderstandingRequest,
): Promise<IncidentUnderstandingOutput> {
  const res = await apiClient.post<IncidentUnderstandingOutput>('/agents/incident/understand', data);
  return res.data;
}

export async function runAgentDecisionFlow(
  data: AgentDecisionFlowRequest,
): Promise<AgentDecisionFlowResponse> {
  const res = await apiClient.post<AgentDecisionFlowResponse>('/agents/decision-flow', data);
  return res.data;
}

export async function structureFeedback(
  data: FeedbackStructuringRequest,
): Promise<FeedbackStructuringOutput> {
  const res = await apiClient.post<FeedbackStructuringOutput>('/agents/feedback/structure', data);
  return res.data;
}
