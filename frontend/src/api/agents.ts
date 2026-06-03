import apiClient from './client';
import type {
  AgentDecisionFlowRequest,
  AgentDecisionFlowResponse,
  CaseMemoryOutput,
  CaseMemoryRequest,
  FeedbackStructuringOutput,
  FeedbackStructuringRequest,
  IncidentUnderstandingOutput,
  IncidentUnderstandingRequest,
  PostDecisionLearningOutput,
  PostDecisionLearningRequest,
  PreferenceLearningOutput,
  PreferenceLearningRequest,
  RuleCandidateListResponse,
  RuleCandidateOutput,
  RuleCandidatePublishRequest,
  RuleCandidateRequest,
  RuleCandidateReplayRequest,
  RuleCandidateReviewRecord,
  RuleCandidateReviewRequest,
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

export async function compileRuleCandidates(
  data: RuleCandidateRequest,
): Promise<RuleCandidateOutput> {
  const res = await apiClient.post<RuleCandidateOutput>('/agents/rules/compile', data);
  return res.data;
}

export async function listRuleCandidateReviews(status?: string): Promise<RuleCandidateListResponse> {
  const res = await apiClient.get<RuleCandidateListResponse>('/agents/rules/candidates', {
    params: status ? { status } : undefined,
  });
  return res.data;
}

export async function reviewRuleCandidate(
  candidateId: string,
  data: RuleCandidateReviewRequest,
): Promise<RuleCandidateReviewRecord> {
  const res = await apiClient.post<RuleCandidateReviewRecord>(
    `/agents/rules/candidates/${candidateId}/review`,
    data,
  );
  return res.data;
}

export async function replayRuleCandidate(
  candidateId: string,
  data: RuleCandidateReplayRequest = {},
): Promise<RuleCandidateReviewRecord> {
  const res = await apiClient.post<RuleCandidateReviewRecord>(
    `/agents/rules/candidates/${candidateId}/replay`,
    data,
  );
  return res.data;
}

export async function publishRuleCandidate(
  candidateId: string,
  data: RuleCandidatePublishRequest = {},
): Promise<RuleCandidateReviewRecord> {
  const res = await apiClient.post<RuleCandidateReviewRecord>(
    `/agents/rules/candidates/${candidateId}/publish`,
    data,
  );
  return res.data;
}

export async function archiveCaseMemory(
  data: CaseMemoryRequest,
): Promise<CaseMemoryOutput> {
  const res = await apiClient.post<CaseMemoryOutput>('/agents/case-memory/archive', data);
  return res.data;
}

export async function learnPreference(
  data: PreferenceLearningRequest,
): Promise<PreferenceLearningOutput> {
  const res = await apiClient.post<PreferenceLearningOutput>('/agents/preference/learn', data);
  return res.data;
}

export async function runPostDecisionLearning(
  data: PostDecisionLearningRequest,
): Promise<PostDecisionLearningOutput> {
  const res = await apiClient.post<PostDecisionLearningOutput>('/agents/post-decision-learning', data);
  return res.data;
}
