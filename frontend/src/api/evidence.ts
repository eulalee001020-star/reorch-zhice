import apiClient from './client';
import type { EvidenceCenterResponse } from '@/types';

export async function getEvidenceCenter(): Promise<EvidenceCenterResponse> {
  const { data } = await apiClient.get<EvidenceCenterResponse>('/evidence/center');
  return data;
}
