"""Fail-closed schema drift detection and quarantine workflow."""

from __future__ import annotations

from uuid import uuid4

from app.models.integration_control import (
    ConnectorRegistrationRequest,
    QuarantineRecord,
    SchemaDriftChange,
    SchemaDriftReport,
    SchemaObservationRequest,
)
from app.services.integration_registry import fingerprint_payload
from app.services.operational_store import RelationalOperationalStore


class SchemaDriftError(ValueError):
    """Raised when a quarantined observation cannot be released."""


class SchemaDriftGuard:
    """Compares observations with the active connector contract before ingestion."""

    def __init__(self, store: RelationalOperationalStore) -> None:
        self.store = store

    def evaluate(self, observation: SchemaObservationRequest) -> SchemaDriftReport:
        asset = self.store.get_active_integration_asset(
            observation.tenant_id, "connector_manifest", observation.connector_id
        )
        changes: list[SchemaDriftChange] = []
        blockers: list[str] = []
        if asset is None:
            blockers.append("active_connector_manifest_missing")
        else:
            registration = ConnectorRegistrationRequest.model_validate(asset.payload)
            manifest = registration.manifest
            if manifest.source_system != observation.source_system:
                blockers.append("source_system_does_not_match_connector_manifest")
            expected_entity = manifest.entity_schemas.get(observation.entity_type)
            if expected_entity is None:
                blockers.append("entity_type_not_declared_by_connector_manifest")
            else:
                expected_fields = expected_entity.fields
                for field, schema in expected_fields.items():
                    observed_type = observation.fields.get(field)
                    if observed_type is None:
                        severity = "blocker" if schema.required else "warning"
                        changes.append(
                            SchemaDriftChange(
                                change_type="field_removed",
                                field=field,
                                expected_type=schema.data_type,
                                severity=severity,
                            )
                        )
                        if schema.required:
                            blockers.append(f"required_field_missing:{field}")
                    elif not _compatible_types(schema.data_type, observed_type):
                        changes.append(
                            SchemaDriftChange(
                                change_type="type_changed",
                                field=field,
                                expected_type=schema.data_type,
                                observed_type=_normalize_type(observed_type),
                                severity="blocker",
                            )
                        )
                        blockers.append(f"incompatible_field_type:{field}")
                for field, observed_type in observation.fields.items():
                    if field not in expected_fields:
                        changes.append(
                            SchemaDriftChange(
                                change_type="field_added",
                                field=field,
                                observed_type=_normalize_type(observed_type),
                                severity="info",
                            )
                        )

        fingerprint = fingerprint_payload(
            {
                "observation": observation.model_dump(mode="json"),
                "active_manifest_fingerprint": asset.fingerprint if asset else None,
                "changes": [item.model_dump(mode="json") for item in changes],
                "blockers": blockers,
            }
        )
        quarantine_id = None
        if blockers:
            record = QuarantineRecord(
                quarantine_id=f"quarantine-{uuid4().hex}",
                tenant_id=observation.tenant_id,
                connector_id=observation.connector_id,
                source_system=observation.source_system,
                entity_type=observation.entity_type,
                schema_version=observation.schema_version,
                status="open",
                reason_codes=blockers,
                observation=observation.model_dump(mode="json"),
                fingerprint=fingerprint,
                observed_at=observation.observed_at,
            )
            persisted, created = self.store.put_quarantine_record(record)
            quarantine_id = persisted.quarantine_id
            if created:
                self.store.append_integration_audit(
                    tenant_id=observation.tenant_id,
                    action="schema_observation_quarantined",
                    actor_id="schema_drift_guard",
                    asset_type="connector_manifest",
                    asset_id=observation.connector_id,
                    details={
                        "quarantine_id": quarantine_id,
                        "entity_type": observation.entity_type,
                        "blockers": blockers,
                        "fingerprint": fingerprint,
                    },
                )
        return SchemaDriftReport(
            tenant_id=observation.tenant_id,
            connector_id=observation.connector_id,
            entity_type=observation.entity_type,
            schema_version=observation.schema_version,
            status="quarantined" if blockers else "compatible",
            changes=changes,
            blockers=blockers,
            quarantine_id=quarantine_id,
            fingerprint=fingerprint,
        )

    def resolve(
        self,
        quarantine_id: str,
        *,
        action: str,
        actor_id: str,
        resolution_note: str,
    ) -> QuarantineRecord:
        record = self.store.get_quarantine_record(quarantine_id)
        if record is None:
            raise SchemaDriftError("quarantine_record_not_found")
        if actor_id in {"", "system"}:
            raise SchemaDriftError("quarantine_resolution_requires_named_approver")
        if action == "release":
            report = self.evaluate(SchemaObservationRequest.model_validate(record.observation))
            if report.status != "compatible":
                raise SchemaDriftError(
                    "quarantine_release_requires_compatible_active_connector_manifest"
                )
            target_status = "released"
        elif action == "reject":
            target_status = "rejected"
        else:
            raise SchemaDriftError("invalid_quarantine_resolution_action")
        try:
            resolved = self.store.resolve_quarantine_record(
                quarantine_id,
                status=target_status,
                resolved_by=actor_id,
                resolution_note=resolution_note,
            )
        except ValueError as exc:
            raise SchemaDriftError(str(exc)) from exc
        if resolved is None:
            raise SchemaDriftError("quarantine_record_not_found")
        self.store.append_integration_audit(
            tenant_id=record.tenant_id,
            action=f"schema_quarantine_{target_status}",
            actor_id=actor_id,
            asset_type="schema_quarantine",
            asset_id=quarantine_id,
            details={"resolution_note": resolution_note},
        )
        return resolved


def _normalize_type(value: str) -> str:
    aliases = {
        "str": "string",
        "varchar": "string",
        "text": "string",
        "int": "integer",
        "int32": "integer",
        "int64": "integer",
        "float": "number",
        "double": "number",
        "decimal": "number",
        "bool": "boolean",
        "timestamp": "datetime",
        "timestamp_tz": "datetime",
        "dict": "object",
        "list": "array",
    }
    normalized = value.strip().lower()
    return aliases.get(normalized, normalized)


def _compatible_types(expected: str, observed: str) -> bool:
    expected_type = _normalize_type(expected)
    observed_type = _normalize_type(observed)
    return expected_type == observed_type or (
        expected_type == "number" and observed_type == "integer"
    )
