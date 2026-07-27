import apiClient from './client';
import type {
  IntegrationAuditEvent,
  IntegrationControlOverview,
  IntegrationControlValidationResult,
  IntegrationQuarantineRecord,
  VersionedIntegrationAsset,
} from '@/types';

export async function getIntegrationControlOverview(
  tenantId = 'default',
): Promise<IntegrationControlOverview> {
  const { data } = await apiClient.get<IntegrationControlOverview>(
    '/integration-control/overview',
    { params: { tenant_id: tenantId } },
  );
  return data;
}

export async function listIntegrationAssets(
  tenantId = 'default',
): Promise<VersionedIntegrationAsset[]> {
  const { data } = await apiClient.get<VersionedIntegrationAsset[]>(
    '/integration-control/assets',
    { params: { tenant_id: tenantId } },
  );
  return data;
}

export async function listIntegrationQuarantine(
  tenantId = 'default',
): Promise<IntegrationQuarantineRecord[]> {
  const { data } = await apiClient.get<IntegrationQuarantineRecord[]>(
    '/integration-control/quarantine',
    { params: { tenant_id: tenantId } },
  );
  return data;
}

export async function listIntegrationAudit(
  tenantId = 'default',
): Promise<IntegrationAuditEvent[]> {
  const { data } = await apiClient.get<IntegrationAuditEvent[]>(
    '/integration-control/audit',
    { params: { tenant_id: tenantId, limit: 200 } },
  );
  return data;
}

export async function runIntegrationControlValidation(
  tenantId = 'default',
): Promise<IntegrationControlValidationResult> {
  const { data } = await apiClient.post<IntegrationControlValidationResult>(
    '/integration-control/validation/digital-twin',
    { tenant_id: tenantId },
  );
  return data;
}
