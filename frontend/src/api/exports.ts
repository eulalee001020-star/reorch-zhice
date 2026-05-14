/**
 * Export API — call backend export endpoints for PDF and Excel.
 *
 * Requirements: 27.7
 */

import apiClient from './client';

export interface ExportResponse {
  filename: string;
  content_type: string;
  decision_record_id: string;
  content_preview: string;
  created_at: string;
}

export async function exportDecisionPdf(
  decisionRecordId: string,
): Promise<ExportResponse> {
  const res = await apiClient.get<ExportResponse>(
    `/decisions/${decisionRecordId}/export/pdf`,
  );
  return res.data;
}

export async function exportDecisionExcel(
  decisionRecordId: string,
): Promise<ExportResponse> {
  const res = await apiClient.get<ExportResponse>(
    `/decisions/${decisionRecordId}/export/excel`,
  );
  return res.data;
}
