import apiClient from './client';
import type { KitReport, MrpResult, ReadinessReport, SupplierScore } from '@/types';

export interface KitReportParams {
  risk_adjusted?: boolean;
  allow_substitutes?: boolean;
}

export async function getKitReport(params?: KitReportParams): Promise<KitReport> {
  const { data } = await apiClient.get<KitReport>('/supply/kit-report', { params });
  return data;
}

export async function getSupplyReadiness(): Promise<ReadinessReport> {
  const { data } = await apiClient.get<ReadinessReport>('/supply/readiness');
  return data;
}

export async function getSupplierScores(): Promise<SupplierScore[]> {
  const { data } = await apiClient.get<SupplierScore[]>('/supply/suppliers');
  return data;
}

export async function getMrp(bucketCount = 3): Promise<MrpResult> {
  const { data } = await apiClient.get<MrpResult>('/supply/mrp', {
    params: { bucket_count: bucketCount },
  });
  return data;
}
