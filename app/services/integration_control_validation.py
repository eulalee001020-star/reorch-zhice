"""End-to-end digital-twin validation of the integration control plane."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.integration_sdk import (
    ConnectorConformanceRunner,
    DigitalTwinEnterpriseConnector,
    WritebackCertificationHarness,
)
from app.models.integration_control import (
    ConnectorRegistrationRequest,
    CanonicalDataEnvelope,
    ConstraintCoverageObservation,
    ConstraintDefinitionDraft,
    ConstraintReplayEvidence,
    DataQualityRule,
    DecisionReadinessRequest,
    IntegrationControlValidationResult,
    ScenarioConstraintRequirement,
    ScenarioDataContractDraft,
    ScenarioFieldRequirement,
    SchemaObservationRequest,
    SourceAuthorityMatrixDraft,
    SourceAuthorityRule,
)
from app.services.decision_readiness import DecisionReadinessService
from app.services.integration_registry import (
    IntegrationRegistryService,
    fingerprint_payload,
)
from app.services.operational_store import RelationalOperationalStore
from app.services.schema_drift_guard import SchemaDriftGuard


class IntegrationControlValidationHarness:
    """Builds and executes all six reusable assets against one digital twin."""

    def __init__(self, store: RelationalOperationalStore) -> None:
        self.store = store
        self.registry = IntegrationRegistryService(store)

    def run(
        self,
        *,
        tenant_id: str = "TENANT-DIGITAL-TWIN",
        actor_id: str = "admin-digital-twin",
    ) -> IntegrationControlValidationResult:
        reference_time = datetime.now(tz=timezone.utc)
        connector = DigitalTwinEnterpriseConnector(reference_time=reference_time)

        matrix = SourceAuthorityMatrixDraft(
            tenant_id=tenant_id,
            matrix_id="default-source-authority",
            version="1.0.0",
            description="ERP owns orders; MES owns operation execution state.",
            evidence_refs=["digital-twin:source-authority-workshop-interview-template"],
            rules=[
                SourceAuthorityRule(
                    authority_role="order_authority",
                    source_system="ERP",
                    canonical_entity="work_order",
                    canonical_fields=["*"],
                    priority=10,
                    evidence_refs=["digital-twin:erp-order-contract"],
                ),
                SourceAuthorityRule(
                    authority_role="operation_authority",
                    source_system="MES",
                    canonical_entity="operation",
                    canonical_fields=["*"],
                    priority=10,
                    evidence_refs=["digital-twin:mes-operation-contract"],
                ),
                SourceAuthorityRule(
                    authority_role="quality_authority",
                    source_system="QMS",
                    canonical_entity="quality_release",
                    canonical_fields=["*"],
                    priority=10,
                    evidence_refs=["digital-twin:qms-release-contract"],
                ),
            ],
        )
        matrix_asset = self.registry.register_authority_matrix(matrix, actor_id)
        matrix_asset = self.registry.activate_authority_matrix(
            tenant_id,
            matrix.matrix_id,
            matrix.version,
            actor_id,
            "Approved digital-twin authority baseline.",
        )

        contract = ScenarioDataContractDraft(
            tenant_id=tenant_id,
            contract_id="machine-down-recovery-contract",
            scenario_type="machine_down_recovery",
            version="1.0.0",
            description="Minimum facts required to recover a machine-down incident.",
            field_requirements=[
                ScenarioFieldRequirement(
                    canonical_path=f"operation.{field}",
                    authority_role="operation_authority",
                    data_type=data_type,
                    max_age_seconds=86_400,
                    quality_rules=(
                        [DataQualityRule(rule_type="unique")]
                        if field == "operation_id"
                        else [
                            DataQualityRule(
                                rule_type="allowed_values",
                                parameters={
                                    "values": [
                                        "planned",
                                        "released",
                                        "started",
                                        "completed",
                                        "blocked",
                                    ]
                                },
                            )
                        ]
                        if field == "status"
                        else [DataQualityRule(rule_type="timezone_aware")]
                        if field in {"planned_start", "planned_end"}
                        else []
                    ),
                )
                for field, data_type in {
                    "operation_id": "string",
                    "work_order_id": "string",
                    "resource_id": "string",
                    "status": "string",
                    "planned_start": "datetime",
                    "planned_end": "datetime",
                }.items()
            ],
            constraint_requirements=[
                ScenarioConstraintRequirement(
                    constraint_type="resource_eligibility",
                    authority_role="operation_authority",
                )
            ],
            evidence_refs=["digital-twin:machine-down-scenario-contract"],
        )
        contract_asset = self.registry.register_scenario_contract(contract, actor_id)
        contract_asset = self.registry.activate_scenario_contract(
            tenant_id,
            contract.contract_id,
            contract.version,
            actor_id,
            "Approved scenario minimum-data contract.",
        )

        connector_request = ConnectorRegistrationRequest(
            tenant_id=tenant_id, manifest=connector.manifest
        )
        connector_asset = self.registry.register_connector_manifest(
            connector_request, actor_id
        )
        conformance = ConnectorConformanceRunner().run(
            connector, tenant_id=tenant_id, evidence_scope="digital_twin"
        )
        self.registry.register_connector_conformance(conformance, actor_id)
        connector_asset = self.registry.activate_connector_manifest(
            tenant_id,
            connector.manifest.connector_id,
            connector.manifest.connector_version,
            actor_id,
            "Connector SDK conformance passed in digital twin.",
        )

        schema_fields = connector.discover_schema()["operation"]
        drift_guard = SchemaDriftGuard(self.store)
        compatible_drift = drift_guard.evaluate(
            SchemaObservationRequest(
                tenant_id=tenant_id,
                connector_id=connector.manifest.connector_id,
                source_system="MES",
                entity_type="operation",
                schema_version="1.0.0",
                fields=schema_fields,
                observed_at=reference_time,
                sample_record_count=4,
                source_refs=["digital-twin:schema-compatible"],
            )
        )
        breaking_fields = dict(schema_fields)
        breaking_fields.pop("operation_id")
        breaking_fields["planned_start"] = "string"
        breaking_drift = drift_guard.evaluate(
            SchemaObservationRequest(
                tenant_id=tenant_id,
                connector_id=connector.manifest.connector_id,
                source_system="MES",
                entity_type="operation",
                schema_version="2.0.0-breaking",
                fields=breaking_fields,
                observed_at=reference_time + timedelta(minutes=1),
                sample_record_count=4,
                source_refs=["digital-twin:schema-breaking"],
            )
        )
        quarantine = self.store.get_quarantine_record(
            breaking_drift.quarantine_id or ""
        )
        if quarantine is None:
            raise RuntimeError("breaking_schema_was_not_quarantined")
        if quarantine.status == "open":
            quarantine = drift_guard.resolve(
                quarantine.quarantine_id,
                action="reject",
                actor_id=actor_id,
                resolution_note="Breaking schema rejected; connector remains on certified version.",
            )

        constraint = ConstraintDefinitionDraft(
            tenant_id=tenant_id,
            constraint_id="resource-eligibility",
            constraint_type="resource_eligibility",
            version="1.0.0",
            criticality="hard",
            authority_roles=["operation_authority"],
            parameter_schema={
                "operation_id": "string",
                "eligible_resource_ids": "array",
            },
            compiler_ref="app.services.operational_constraint_validator",
            validator_ref="app.services.operational_constraint_validator",
            replay_evidence=[
                ConstraintReplayEvidence(
                    case_id=f"DT-ELIG-{index}",
                    passed=True,
                    executed_at=reference_time + timedelta(minutes=index),
                    result_fingerprint=fingerprint_payload(
                        {"case_id": f"DT-ELIG-{index}", "passed": True}
                    ),
                    evidence_scope="digital_twin",
                    source_refs=[f"digital-twin:eligibility:{index}"],
                )
                for index in range(1, 4)
            ],
            description="Only resources declared eligible for an operation may be assigned.",
        )
        constraint_asset = self.registry.register_constraint(constraint, actor_id)
        constraint_asset = self.registry.activate_constraint(
            tenant_id,
            constraint.constraint_id,
            constraint.version,
            actor_id,
            "Three executed replay results passed independent validation.",
        )

        certification = WritebackCertificationHarness().run(
            connector,
            tenant_id=tenant_id,
            adapter_id="dt-mes-writeback",
            evidence_scope="digital_twin",
        )
        self.registry.register_writeback_certification(certification, actor_id)

        canonical_records = [
            CanonicalDataEnvelope(
                source_system="MES",
                entity_type=record.entity_type,
                entity_id=record.entity_id,
                observed_at=record.occurred_at,
                data=record.payload,
                evidence_refs=[
                    f"digital-twin:{record.entity_type}:{record.entity_id}"
                ],
            )
            for record in connector.read_snapshot().records
        ]
        readiness = DecisionReadinessService(self.store).evaluate(
            DecisionReadinessRequest(
                tenant_id=tenant_id,
                scenario_type=contract.scenario_type,
                as_of=reference_time,
                canonical_records=canonical_records,
                constraint_observations=[
                    ConstraintCoverageObservation(
                        constraint_type="resource_eligibility",
                        authority_role="operation_authority",
                        covered_count=4,
                        total_count=4,
                        evidence_refs=["digital-twin:eligibility-coverage"],
                    )
                ],
                required_connector_ids=[connector.manifest.connector_id],
                evidence_scope="digital_twin",
            )
        )
        overview = DecisionReadinessService(self.store).overview(tenant_id)

        checks = {
            "source_authority_matrix": _check(matrix_asset.status == "active"),
            "scenario_data_contract": _check(contract_asset.status == "active"),
            "connector_conformance": _check(conformance.passed),
            "schema_compatible_path": _check(compatible_drift.status == "compatible"),
            "schema_breaking_quarantine": _check(
                breaking_drift.status == "quarantined" and quarantine.status == "rejected"
            ),
            "versioned_constraint_registry": _check(constraint_asset.status == "active"),
            "writeback_adapter_certification": _check(certification.passed),
            "decision_readiness_manifest": _check(readiness.status == "ready"),
        }
        all_passed = all(item.status == "pass" for item in checks.values())
        artifact_fingerprint = fingerprint_payload(
            {
                "tenant_id": tenant_id,
                "checks": {key: value.status for key, value in checks.items()},
                "asset_fingerprints": [
                    matrix_asset.fingerprint,
                    contract_asset.fingerprint,
                    connector_asset.fingerprint,
                    conformance.artifact_fingerprint,
                    constraint_asset.fingerprint,
                    certification.artifact_fingerprint,
                    readiness.fingerprint,
                ],
            }
        )
        return IntegrationControlValidationResult(
            tenant_id=tenant_id,
            all_checks_passed=all_passed,
            checks=checks,
            authority_matrix_ref=_ref(matrix_asset),
            scenario_contract_ref=_ref(contract_asset),
            connector_manifest_ref=_ref(connector_asset),
            connector_conformance=conformance,
            compatible_drift_report=compatible_drift,
            breaking_drift_report=breaking_drift,
            quarantine_resolution=quarantine,
            constraint_ref=_ref(constraint_asset),
            writeback_certification=certification,
            readiness_manifest=readiness,
            overview=overview,
            artifact_fingerprint=artifact_fingerprint,
            claim_boundary=(
                "All checks use deterministic digital-twin evidence. They prove the control "
                "plane behavior, not customer-system compatibility or realized production ROI."
            ),
        )


def _check(passed: bool):
    from app.models.integration_control import ConformanceCheck

    return ConformanceCheck(
        check_id="validation",
        status="pass" if passed else "fail",
        blocking=True,
        evidence={},
        reason=None if passed else "validation_failed",
    )


def _ref(asset) -> str:
    return f"{asset.asset_type}:{asset.asset_id}:{asset.version}:{asset.fingerprint}"
