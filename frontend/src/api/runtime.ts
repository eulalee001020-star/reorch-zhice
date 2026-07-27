import apiClient from './client';
import type {
  ProductionValidationRunRequest,
  ProductionValidationRunResponse,
} from '@/types';

export async function runProductionValidation(
  request: ProductionValidationRunRequest = {},
): Promise<ProductionValidationRunResponse> {
  const { data } = await apiClient.post<ProductionValidationRunResponse>(
    '/runtime/validation/digital-twin',
    request,
  );
  return data;
}
