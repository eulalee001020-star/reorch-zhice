import apiClient from './client';
import type { DispatchImpact } from '@/types';

/** Delivery outcome of each candidate plan. Resolves to null when there is
 *  no dispatch snapshot or no candidate plans yet. */
export async function getDispatchImpact(incidentId: string): Promise<DispatchImpact | null> {
  try {
    const { data } = await apiClient.get<DispatchImpact>(
      `/incidents/${incidentId}/dispatch-impact`,
    );
    return data;
  } catch {
    return null;
  }
}
