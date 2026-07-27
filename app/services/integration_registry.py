"""Versioned registries for enterprise integration governance assets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.models.integration_control import (
    ConnectorConformanceReport,
    ConnectorRegistrationRequest,
    ConstraintDefinitionDraft,
    ScenarioDataContractDraft,
    SourceAuthorityMatrixDraft,
    VersionedAssetRecord,
    WritebackCertificationReport,
)
from app.services.operational_store import RelationalOperationalStore


class IntegrationRegistryError(ValueError):
    """Raised when a governance asset cannot safely change lifecycle state."""


class IntegrationRegistryService:
    """Owns immutable registration, activation, retirement, and audit."""

    def __init__(self, store: RelationalOperationalStore) -> None:
        self.store = store

    def register_authority_matrix(
        self, draft: SourceAuthorityMatrixDraft, actor_id: str
    ) -> VersionedAssetRecord:
        self._validate_authority_matrix(draft)
        return self._register(
            tenant_id=draft.tenant_id,
            asset_type="source_authority_matrix",
            asset_id=draft.matrix_id,
            scope_key="tenant_default",
            version=draft.version,
            payload=draft.model_dump(mode="json"),
            actor_id=actor_id,
        )

    def activate_authority_matrix(
        self,
        tenant_id: str,
        matrix_id: str,
        version: str,
        actor_id: str,
        approval_note: str,
    ) -> VersionedAssetRecord:
        asset = self._required_asset(
            tenant_id, "source_authority_matrix", matrix_id, version
        )
        self._validate_authority_matrix(SourceAuthorityMatrixDraft.model_validate(asset.payload))
        return self._activate(asset, actor_id, approval_note)

    def register_scenario_contract(
        self, draft: ScenarioDataContractDraft, actor_id: str
    ) -> VersionedAssetRecord:
        return self._register(
            tenant_id=draft.tenant_id,
            asset_type="scenario_data_contract",
            asset_id=draft.contract_id,
            scope_key=draft.scenario_type,
            version=draft.version,
            payload=draft.model_dump(mode="json"),
            actor_id=actor_id,
        )

    def activate_scenario_contract(
        self,
        tenant_id: str,
        contract_id: str,
        version: str,
        actor_id: str,
        approval_note: str,
    ) -> VersionedAssetRecord:
        asset = self._required_asset(
            tenant_id, "scenario_data_contract", contract_id, version
        )
        contract = ScenarioDataContractDraft.model_validate(asset.payload)
        authority = self.store.get_active_integration_asset(
            tenant_id, "source_authority_matrix", "tenant_default"
        )
        if authority is None:
            raise IntegrationRegistryError("active_source_authority_matrix_required")
        matrix = SourceAuthorityMatrixDraft.model_validate(authority.payload)
        known_roles = {rule.authority_role for rule in matrix.rules}
        required_roles = {
            item.authority_role for item in contract.field_requirements
        } | {item.authority_role for item in contract.constraint_requirements}
        missing_roles = sorted(required_roles - known_roles)
        if missing_roles:
            raise IntegrationRegistryError(
                f"scenario_contract_unknown_authority_roles:{','.join(missing_roles)}"
            )
        return self._activate(asset, actor_id, approval_note)

    def register_connector_manifest(
        self, request: ConnectorRegistrationRequest, actor_id: str
    ) -> VersionedAssetRecord:
        manifest = request.manifest
        return self._register(
            tenant_id=request.tenant_id,
            asset_type="connector_manifest",
            asset_id=manifest.connector_id,
            scope_key=manifest.connector_id,
            version=manifest.connector_version,
            payload=request.model_dump(mode="json"),
            actor_id=actor_id,
        )

    def activate_connector_manifest(
        self,
        tenant_id: str,
        connector_id: str,
        version: str,
        actor_id: str,
        approval_note: str,
    ) -> VersionedAssetRecord:
        asset = self._required_asset(
            tenant_id, "connector_manifest", connector_id, version
        )
        report = self.store.get_active_integration_asset(
            tenant_id, "connector_conformance", connector_id
        )
        if report is None:
            raise IntegrationRegistryError("passing_connector_conformance_required")
        conformance = ConnectorConformanceReport.model_validate(report.payload)
        request = ConnectorRegistrationRequest.model_validate(asset.payload)
        if not conformance.passed:
            raise IntegrationRegistryError("connector_conformance_has_blocking_failures")
        if conformance.connector_version != request.manifest.connector_version:
            raise IntegrationRegistryError("connector_conformance_version_mismatch")
        return self._activate(asset, actor_id, approval_note)

    def register_connector_conformance(
        self, report: ConnectorConformanceReport, actor_id: str
    ) -> VersionedAssetRecord:
        if report.passed != all(
            check.status != "fail" for check in report.checks if check.blocking
        ):
            raise IntegrationRegistryError("connector_conformance_summary_is_inconsistent")
        expected_fingerprint = fingerprint_payload(
            {
                "tenant_id": report.tenant_id,
                "connector_id": report.connector_id,
                "connector_version": report.connector_version,
                "source_system": report.source_system,
                "evidence_scope": report.evidence_scope,
                "checks": [check.model_dump(mode="json") for check in report.checks],
                "passed": report.passed,
            }
        )
        if report.artifact_fingerprint != expected_fingerprint:
            raise IntegrationRegistryError("connector_conformance_fingerprint_mismatch")
        asset = self._register(
            tenant_id=report.tenant_id,
            asset_type="connector_conformance",
            asset_id=report.report_id,
            scope_key=report.connector_id,
            version=report.artifact_fingerprint[:16],
            payload=report.model_dump(mode="json"),
            actor_id=actor_id,
        )
        if report.passed:
            return self._activate(asset, actor_id, "Conformance harness passed.")
        return asset

    def register_constraint(
        self, draft: ConstraintDefinitionDraft, actor_id: str
    ) -> VersionedAssetRecord:
        return self._register(
            tenant_id=draft.tenant_id,
            asset_type="constraint_definition",
            asset_id=draft.constraint_id,
            scope_key=draft.constraint_type,
            version=draft.version,
            payload=draft.model_dump(mode="json"),
            actor_id=actor_id,
        )

    def activate_constraint(
        self,
        tenant_id: str,
        constraint_id: str,
        version: str,
        actor_id: str,
        approval_note: str,
    ) -> VersionedAssetRecord:
        asset = self._required_asset(
            tenant_id, "constraint_definition", constraint_id, version
        )
        definition = ConstraintDefinitionDraft.model_validate(asset.payload)
        if not definition.compiler_ref or not definition.validator_ref:
            raise IntegrationRegistryError("constraint_compiler_and_validator_required")
        successful_cases = {
            item.case_id
            for item in definition.replay_evidence
            if item.passed and item.result_fingerprint and item.source_refs
        }
        if len(successful_cases) < 3:
            raise IntegrationRegistryError(
                "constraint_activation_requires_three_executed_replay_results"
            )
        return self._activate(asset, actor_id, approval_note)

    def register_writeback_certification(
        self, report: WritebackCertificationReport, actor_id: str
    ) -> VersionedAssetRecord:
        if report.passed != all(
            check.status != "fail" for check in report.checks if check.blocking
        ):
            raise IntegrationRegistryError("writeback_certification_summary_is_inconsistent")
        if report.passed and report.valid_until <= datetime.now(tz=timezone.utc):
            raise IntegrationRegistryError("writeback_certification_is_already_expired")
        expected_fingerprint = fingerprint_payload(
            {
                "tenant_id": report.tenant_id,
                "profile": report.profile.model_dump(mode="json"),
                "executed_at": report.executed_at.isoformat(),
                "checks": [check.model_dump(mode="json") for check in report.checks],
                "passed": report.passed,
            }
        )
        if report.artifact_fingerprint != expected_fingerprint:
            raise IntegrationRegistryError("writeback_certification_fingerprint_mismatch")
        asset = self._register(
            tenant_id=report.tenant_id,
            asset_type="writeback_certification",
            asset_id=report.certification_id,
            scope_key=report.profile.adapter_id,
            version=report.artifact_fingerprint[:16],
            payload=report.model_dump(mode="json"),
            actor_id=actor_id,
        )
        if report.passed:
            return self._activate(asset, actor_id, "Certification harness passed.")
        return asset

    def assert_active_writeback_certification(
        self, tenant_id: str, adapter_id: str, certification_id: str | None = None
    ) -> WritebackCertificationReport:
        asset = self.store.get_active_integration_asset(
            tenant_id, "writeback_certification", adapter_id
        )
        if asset is None:
            raise IntegrationRegistryError("active_writeback_certification_required")
        report = WritebackCertificationReport.model_validate(asset.payload)
        if certification_id and report.certification_id != certification_id:
            raise IntegrationRegistryError("writeback_certification_id_mismatch")
        if not report.passed:
            raise IntegrationRegistryError("writeback_certification_failed")
        if report.valid_until <= datetime.now(tz=timezone.utc):
            raise IntegrationRegistryError("writeback_certification_expired")
        return report

    def list_assets(
        self,
        tenant_id: str,
        *,
        asset_type: str | None = None,
        status: str | None = None,
    ) -> list[VersionedAssetRecord]:
        return self.store.list_integration_assets(
            tenant_id, asset_type=asset_type, status=status
        )

    def _register(
        self,
        *,
        tenant_id: str,
        asset_type: str,
        asset_id: str,
        scope_key: str,
        version: str,
        payload: dict[str, Any],
        actor_id: str,
    ) -> VersionedAssetRecord:
        fingerprint = fingerprint_payload(payload)
        try:
            asset, created = self.store.put_integration_asset(
                tenant_id=tenant_id,
                asset_type=asset_type,
                asset_id=asset_id,
                scope_key=scope_key,
                version=version,
                payload=payload,
                fingerprint=fingerprint,
                created_by=actor_id,
            )
        except ValueError as exc:
            raise IntegrationRegistryError(str(exc)) from exc
        if created:
            self.store.append_integration_audit(
                tenant_id=tenant_id,
                action="asset_registered",
                actor_id=actor_id,
                asset_type=asset_type,
                asset_id=asset_id,
                details={"version": version, "fingerprint": fingerprint},
            )
        return asset

    def _activate(
        self, asset: VersionedAssetRecord, actor_id: str, approval_note: str
    ) -> VersionedAssetRecord:
        if actor_id in {"", "system"}:
            raise IntegrationRegistryError("asset_activation_requires_named_approver")
        try:
            activated = self.store.activate_integration_asset(
                tenant_id=asset.tenant_id,
                asset_type=asset.asset_type,
                asset_id=asset.asset_id,
                version=asset.version,
                approved_by=actor_id,
                approval_note=approval_note,
            )
        except ValueError as exc:
            raise IntegrationRegistryError(str(exc)) from exc
        if activated is None:
            raise IntegrationRegistryError("integration_asset_not_found")
        self.store.append_integration_audit(
            tenant_id=asset.tenant_id,
            action="asset_activated",
            actor_id=actor_id,
            asset_type=asset.asset_type,
            asset_id=asset.asset_id,
            details={
                "version": asset.version,
                "approval_note": approval_note,
                "fingerprint": asset.fingerprint,
            },
        )
        return activated

    def _required_asset(
        self, tenant_id: str, asset_type: str, asset_id: str, version: str
    ) -> VersionedAssetRecord:
        asset = self.store.get_integration_asset(
            tenant_id, asset_type, asset_id, version
        )
        if asset is None:
            raise IntegrationRegistryError("integration_asset_not_found")
        return asset

    @staticmethod
    def _validate_authority_matrix(draft: SourceAuthorityMatrixDraft) -> None:
        winners: dict[tuple[str, str, str], int] = {}
        for rule in draft.rules:
            if rule.writeback_allowed and rule.conflict_policy != "block":
                raise IntegrationRegistryError(
                    "writeback_authority_requires_block_conflict_policy"
                )
            for field in rule.canonical_fields:
                key = (rule.authority_role, rule.canonical_entity, field)
                previous = winners.get(key)
                if previous is not None and previous == rule.priority:
                    raise IntegrationRegistryError(
                        "authority_matrix_has_equal_priority_conflict:"
                        f"{rule.authority_role}.{rule.canonical_entity}.{field}"
                    )
                winners[key] = min(previous, rule.priority) if previous is not None else rule.priority


def fingerprint_payload(payload: Any) -> str:
    """Canonical SHA-256 used by every integration-control artifact."""
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
