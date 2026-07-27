"""Contracts for governed enterprise data access and controlled writeback."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from app.models.base import ReOrchModel


AssetStatus = Literal["draft", "active", "retired"]
Criticality = Literal["hard", "soft"]
CheckStatus = Literal["pass", "fail", "warning"]


class VersionedAssetRecord(ReOrchModel):
    """Persisted immutable payload plus mutable lifecycle metadata."""

    tenant_id: str
    asset_type: str
    asset_id: str
    scope_key: str
    version: str
    status: AssetStatus = "draft"
    payload: dict[str, Any]
    fingerprint: str
    created_by: str
    approved_by: str | None = None
    created_at: datetime
    activated_at: datetime | None = None


class AssetActivationRequest(ReOrchModel):
    approval_note: str = Field(min_length=8, max_length=1000)


class SourceAuthorityRule(ReOrchModel):
    """Names the authoritative source for one canonical field family."""

    authority_role: str
    source_system: str
    canonical_entity: str
    canonical_fields: list[str] = Field(min_length=1)
    priority: int = Field(default=100, ge=0, le=10_000)
    read_mode: Literal["snapshot", "cdc", "hybrid"] = "hybrid"
    conflict_policy: Literal["block", "priority", "latest_timestamp"] = "block"
    writeback_allowed: bool = False
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("canonical_fields")
    @classmethod
    def unique_fields(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("canonical_fields_must_be_unique")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> SourceAuthorityRule:
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError("authority_validity_window_is_invalid")
        return self


class SourceAuthorityMatrixDraft(ReOrchModel):
    tenant_id: str
    matrix_id: str
    version: str
    rules: list[SourceAuthorityRule] = Field(min_length=1)
    description: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class DataQualityRule(ReOrchModel):
    rule_type: Literal[
        "allowed_values",
        "non_negative",
        "positive",
        "timezone_aware",
        "reference_exists",
        "unique",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioFieldRequirement(ReOrchModel):
    canonical_path: str
    authority_role: str
    data_type: Literal[
        "string", "integer", "number", "boolean", "datetime", "object", "array"
    ]
    criticality: Criticality = "hard"
    nullable: bool = False
    minimum_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    max_age_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    quality_rules: list[DataQualityRule] = Field(default_factory=list)
    description: str = ""


class ScenarioConstraintRequirement(ReOrchModel):
    constraint_type: str
    authority_role: str
    criticality: Criticality = "hard"
    minimum_coverage: float = Field(default=1.0, ge=0.0, le=1.0)


class ScenarioDataContractDraft(ReOrchModel):
    tenant_id: str
    contract_id: str
    scenario_type: str
    version: str
    field_requirements: list[ScenarioFieldRequirement] = Field(min_length=1)
    constraint_requirements: list[ScenarioConstraintRequirement] = Field(
        default_factory=list
    )
    description: str = ""
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_requirements(self) -> ScenarioDataContractDraft:
        paths = [item.canonical_path for item in self.field_requirements]
        if len(paths) != len(set(paths)):
            raise ValueError("scenario_contract_field_paths_must_be_unique")
        constraints = [item.constraint_type for item in self.constraint_requirements]
        if len(constraints) != len(set(constraints)):
            raise ValueError("scenario_contract_constraints_must_be_unique")
        return self


class ConnectorFieldSchema(ReOrchModel):
    data_type: Literal[
        "string", "integer", "number", "boolean", "datetime", "object", "array"
    ]
    required: bool = True
    nullable: bool = False


class ConnectorEntitySchema(ReOrchModel):
    fields: dict[str, ConnectorFieldSchema] = Field(min_length=1)


class ConnectorManifest(ReOrchModel):
    connector_id: str
    source_system: str
    connector_version: str
    sdk_version: str = "1.0"
    target_environment: Literal["readonly", "sandbox", "production"] = "readonly"
    capabilities: list[str] = Field(min_length=1)
    entity_schemas: dict[str, ConnectorEntitySchema] = Field(min_length=1)
    lineage_fields: list[str] = Field(
        default_factory=lambda: ["source_system", "source_record_id", "observed_at"]
    )
    timestamp_semantics: Literal["utc", "offset_aware"] = "utc"
    incremental_cursor: bool = True
    idempotent_reads: bool = True
    idempotent_writes: bool = False
    compare_and_swap: bool = False
    durable_outbox: bool = False
    execution_receipts: bool = False
    reconciliation: bool = False
    compensation: bool = False


class ConnectorRegistrationRequest(ReOrchModel):
    tenant_id: str
    manifest: ConnectorManifest


class ConformanceCheck(ReOrchModel):
    check_id: str
    status: CheckStatus
    blocking: bool
    evidence: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class ConnectorConformanceReport(ReOrchModel):
    report_id: str = Field(default_factory=lambda: f"connector-conf-{uuid4().hex}")
    tenant_id: str
    connector_id: str
    connector_version: str
    source_system: str
    evidence_scope: Literal["digital_twin", "customer_sandbox", "customer_production"]
    executed_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    checks: list[ConformanceCheck]
    passed: bool
    artifact_fingerprint: str
    claim_boundary: str


class SchemaObservationRequest(ReOrchModel):
    tenant_id: str
    connector_id: str
    source_system: str
    entity_type: str
    schema_version: str
    fields: dict[str, str] = Field(min_length=1)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    sample_record_count: int = Field(default=1, ge=1)
    source_refs: list[str] = Field(default_factory=list)


class SchemaDriftChange(ReOrchModel):
    change_type: Literal["field_added", "field_removed", "type_changed"]
    field: str
    expected_type: str | None = None
    observed_type: str | None = None
    severity: Literal["info", "warning", "blocker"]


class SchemaDriftReport(ReOrchModel):
    report_id: str = Field(default_factory=lambda: f"drift-{uuid4().hex}")
    tenant_id: str
    connector_id: str
    entity_type: str
    schema_version: str
    status: Literal["compatible", "quarantined"]
    changes: list[SchemaDriftChange] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    quarantine_id: str | None = None
    fingerprint: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class QuarantineRecord(ReOrchModel):
    quarantine_id: str
    tenant_id: str
    connector_id: str
    source_system: str
    entity_type: str
    schema_version: str
    status: Literal["open", "released", "rejected"]
    reason_codes: list[str]
    observation: dict[str, Any]
    fingerprint: str
    observed_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None


class QuarantineResolutionRequest(ReOrchModel):
    action: Literal["release", "reject"]
    resolution_note: str = Field(min_length=8, max_length=1000)


class ConstraintReplayEvidence(ReOrchModel):
    case_id: str
    passed: bool
    executed_at: datetime
    result_fingerprint: str
    evidence_scope: Literal["digital_twin", "customer_historical", "customer_shadow"]
    source_refs: list[str] = Field(min_length=1)


class ConstraintDefinitionDraft(ReOrchModel):
    tenant_id: str
    constraint_id: str
    constraint_type: str
    version: str
    criticality: Criticality
    authority_roles: list[str] = Field(min_length=1)
    parameter_schema: dict[str, str] = Field(default_factory=dict)
    compiler_ref: str
    validator_ref: str
    replay_evidence: list[ConstraintReplayEvidence] = Field(default_factory=list)
    proposed_by_agent: bool = False
    description: str = ""


class WritebackAdapterProfile(ReOrchModel):
    adapter_id: str
    connector_id: str
    adapter_version: str
    source_system: str
    target_environment: Literal["sandbox"] = "sandbox"
    command_types: list[str] = Field(min_length=1)
    permission_scopes: list[str] = Field(min_length=1)
    max_batch_size: int = Field(default=100, ge=1, le=100_000)
    max_requests_per_minute: int = Field(default=60, ge=1, le=100_000)


class WritebackCertificationReport(ReOrchModel):
    certification_id: str = Field(default_factory=lambda: f"wb-cert-{uuid4().hex}")
    tenant_id: str
    profile: WritebackAdapterProfile
    evidence_scope: Literal["digital_twin", "customer_sandbox"]
    executed_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    valid_until: datetime
    checks: list[ConformanceCheck]
    passed: bool
    artifact_fingerprint: str
    claim_boundary: str


class DataFieldObservation(ReOrchModel):
    canonical_path: str
    source_system: str
    authority_role: str
    data_type: str
    present_count: int = Field(ge=0)
    total_count: int = Field(gt=0)
    latest_observed_at: datetime | None = None
    quality_passed: bool = True
    evidence_refs: list[str] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.present_count / self.total_count


class CanonicalDataEnvelope(ReOrchModel):
    """One normalized record with source and time lineage for deterministic DataGate."""

    source_system: str
    entity_type: str
    entity_id: str
    observed_at: datetime
    data: dict[str, Any]
    evidence_refs: list[str] = Field(min_length=1)


class ConstraintCoverageObservation(ReOrchModel):
    constraint_type: str
    authority_role: str
    covered_count: int = Field(ge=0)
    total_count: int = Field(gt=0)
    evidence_refs: list[str] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.covered_count / self.total_count


class DecisionReadinessRequest(ReOrchModel):
    tenant_id: str
    scenario_type: str
    as_of: datetime
    field_observations: list[DataFieldObservation] = Field(default_factory=list)
    canonical_records: list[CanonicalDataEnvelope] = Field(default_factory=list)
    constraint_observations: list[ConstraintCoverageObservation] = Field(
        default_factory=list
    )
    required_connector_ids: list[str] = Field(default_factory=list)
    evidence_scope: Literal[
        "digital_twin", "customer_historical", "customer_shadow", "customer_production"
    ] = "digital_twin"

    @model_validator(mode="after")
    def require_data_evidence(self) -> DecisionReadinessRequest:
        if not self.field_observations and not self.canonical_records:
            raise ValueError("field_observations_or_canonical_records_required")
        return self


class ReadinessCheck(ReOrchModel):
    check_id: str
    status: CheckStatus
    criticality: Criticality
    message: str
    evidence_refs: list[str] = Field(default_factory=list)


class DecisionReadinessManifest(ReOrchModel):
    manifest_id: str = Field(default_factory=lambda: f"readiness-{uuid4().hex}")
    tenant_id: str
    scenario_type: str
    status: Literal["ready", "degraded", "blocked"]
    authority_matrix_ref: str
    data_contract_ref: str
    connector_certification_refs: list[str]
    constraint_version_refs: list[str]
    checks: list[ReadinessCheck]
    hard_gaps: list[str]
    warnings: list[str]
    evaluated_at: datetime
    expires_at: datetime
    evidence_scope: str
    fingerprint: str
    claim_boundary: str


class IntegrationAuditEvent(ReOrchModel):
    event_id: str
    tenant_id: str
    action: str
    asset_type: str | None = None
    asset_id: str | None = None
    actor_id: str
    details: dict[str, Any]
    created_at: datetime


class IntegrationControlOverview(ReOrchModel):
    tenant_id: str
    active_assets: dict[str, list[VersionedAssetRecord]]
    draft_asset_count: int
    open_quarantine_count: int
    latest_readiness_manifest: DecisionReadinessManifest | None = None
    production_writeback_certified: bool
    claim_boundary: str


class IntegrationControlValidationResult(ReOrchModel):
    run_id: str = Field(default_factory=lambda: f"integration-run-{uuid4().hex}")
    tenant_id: str
    all_checks_passed: bool
    checks: dict[str, ConformanceCheck]
    authority_matrix_ref: str
    scenario_contract_ref: str
    connector_manifest_ref: str
    connector_conformance: ConnectorConformanceReport
    compatible_drift_report: SchemaDriftReport
    breaking_drift_report: SchemaDriftReport
    quarantine_resolution: QuarantineRecord
    constraint_ref: str
    writeback_certification: WritebackCertificationReport
    readiness_manifest: DecisionReadinessManifest
    overview: IntegrationControlOverview
    artifact_fingerprint: str
    claim_boundary: str


class IntegrationControlValidationRequest(ReOrchModel):
    tenant_id: str = "default"
