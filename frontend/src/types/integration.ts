export interface IntegrationConformanceCheck {
  check_id: string;
  status: 'pass' | 'fail' | 'warning';
  blocking: boolean;
  evidence: Record<string, unknown>;
  reason?: string | null;
}

export interface VersionedIntegrationAsset {
  tenant_id: string;
  asset_type: string;
  asset_id: string;
  scope_key: string;
  version: string;
  status: 'draft' | 'active' | 'retired';
  payload: Record<string, unknown>;
  fingerprint: string;
  created_by: string;
  approved_by?: string | null;
  created_at: string;
  activated_at?: string | null;
}

export interface DecisionReadinessCheck {
  check_id: string;
  status: 'pass' | 'fail' | 'warning';
  criticality: 'hard' | 'soft';
  message: string;
  evidence_refs: string[];
}

export interface DecisionReadinessManifest {
  manifest_id: string;
  tenant_id: string;
  scenario_type: string;
  status: 'ready' | 'degraded' | 'blocked';
  authority_matrix_ref: string;
  data_contract_ref: string;
  connector_certification_refs: string[];
  constraint_version_refs: string[];
  checks: DecisionReadinessCheck[];
  hard_gaps: string[];
  warnings: string[];
  evaluated_at: string;
  expires_at: string;
  evidence_scope: string;
  fingerprint: string;
  claim_boundary: string;
}

export interface IntegrationControlOverview {
  tenant_id: string;
  active_assets: Record<string, VersionedIntegrationAsset[]>;
  draft_asset_count: number;
  open_quarantine_count: number;
  latest_readiness_manifest?: DecisionReadinessManifest | null;
  production_writeback_certified: boolean;
  claim_boundary: string;
}

export interface IntegrationQuarantineRecord {
  quarantine_id: string;
  tenant_id: string;
  connector_id: string;
  source_system: string;
  entity_type: string;
  schema_version: string;
  status: 'open' | 'released' | 'rejected';
  reason_codes: string[];
  observation: Record<string, unknown>;
  fingerprint: string;
  observed_at: string;
  resolved_at?: string | null;
  resolved_by?: string | null;
  resolution_note?: string | null;
}

export interface IntegrationAuditEvent {
  event_id: string;
  tenant_id: string;
  action: string;
  asset_type?: string | null;
  asset_id?: string | null;
  actor_id: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ConnectorConformanceReport {
  report_id: string;
  connector_id: string;
  connector_version: string;
  evidence_scope: string;
  checks: IntegrationConformanceCheck[];
  passed: boolean;
  artifact_fingerprint: string;
}

export interface WritebackCertificationReport {
  certification_id: string;
  evidence_scope: string;
  valid_until: string;
  checks: IntegrationConformanceCheck[];
  passed: boolean;
  artifact_fingerprint: string;
}

export interface SchemaDriftReport {
  report_id: string;
  schema_version: string;
  status: 'compatible' | 'quarantined';
  blockers: string[];
  quarantine_id?: string | null;
  fingerprint: string;
}

export interface IntegrationControlValidationResult {
  run_id: string;
  tenant_id: string;
  all_checks_passed: boolean;
  checks: Record<string, IntegrationConformanceCheck>;
  authority_matrix_ref: string;
  scenario_contract_ref: string;
  connector_manifest_ref: string;
  connector_conformance: ConnectorConformanceReport;
  compatible_drift_report: SchemaDriftReport;
  breaking_drift_report: SchemaDriftReport;
  quarantine_resolution: IntegrationQuarantineRecord;
  constraint_ref: string;
  writeback_certification: WritebackCertificationReport;
  readiness_manifest: DecisionReadinessManifest;
  overview: IntegrationControlOverview;
  artifact_fingerprint: string;
  claim_boundary: string;
}
