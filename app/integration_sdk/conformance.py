"""Executable conformance suite for Connector SDK implementations."""

from __future__ import annotations

from datetime import timezone

from app.integration_sdk.base import EnterpriseConnector
from app.models.integration_control import (
    ConformanceCheck,
    ConnectorConformanceReport,
)
from app.services.integration_registry import fingerprint_payload


class ConnectorConformanceRunner:
    """Runs deterministic read-path tests against a concrete connector."""

    def run(
        self,
        connector: EnterpriseConnector,
        *,
        tenant_id: str,
        evidence_scope: str = "digital_twin",
    ) -> ConnectorConformanceReport:
        manifest = connector.manifest
        checks: list[ConformanceCheck] = []

        health = connector.health()
        checks.append(
            _check(
                "health_probe",
                health.healthy,
                evidence={"latency_ms": health.latency_ms, **health.details},
            )
        )

        discovered = connector.discover_schema()
        expected = {
            entity: {
                field: schema.data_type for field, schema in entity_schema.fields.items()
            }
            for entity, entity_schema in manifest.entity_schemas.items()
        }
        checks.append(
            _check(
                "schema_discovery",
                discovered == expected,
                evidence={"expected": expected, "discovered": discovered},
                reason="discovered_schema_does_not_match_manifest",
            )
        )

        snapshot_one = connector.read_snapshot()
        snapshot_two = connector.read_snapshot()
        first_fingerprint = fingerprint_payload(snapshot_one.model_dump(mode="json"))
        second_fingerprint = fingerprint_payload(snapshot_two.model_dump(mode="json"))
        checks.append(
            _check(
                "idempotent_snapshot_read",
                manifest.idempotent_reads and first_fingerprint == second_fingerprint,
                evidence={
                    "first_fingerprint": first_fingerprint,
                    "second_fingerprint": second_fingerprint,
                },
                reason="snapshot_read_is_not_idempotent",
            )
        )

        lineage_missing = [
            f"{record.entity_type}:{record.entity_id}"
            for record in snapshot_one.records
            if any(not record.lineage.get(field) for field in manifest.lineage_fields)
        ]
        checks.append(
            _check(
                "record_lineage",
                not lineage_missing,
                evidence={"missing_records": lineage_missing},
                reason="required_lineage_fields_are_missing",
            )
        )

        invalid_timestamps = [
            f"{record.entity_type}:{record.entity_id}"
            for record in snapshot_one.records
            if record.occurred_at.tzinfo is None
            or record.occurred_at.utcoffset() != timezone.utc.utcoffset(record.occurred_at)
        ]
        checks.append(
            _check(
                "utc_timestamp_semantics",
                not invalid_timestamps,
                evidence={"invalid_records": invalid_timestamps},
                reason="timestamps_are_not_utc",
            )
        )

        batch_one = connector.read_changes(None, 2)
        batch_one_replayed = connector.read_changes(None, 2)
        batch_two = connector.read_changes(batch_one.next_cursor, 2)
        replay_equal = fingerprint_payload(batch_one.model_dump(mode="json")) == fingerprint_payload(
            batch_one_replayed.model_dump(mode="json")
        )
        first_ids = {(item.entity_type, item.entity_id) for item in batch_one.records}
        second_ids = {(item.entity_type, item.entity_id) for item in batch_two.records}
        checks.append(
            _check(
                "checkpoint_resume",
                manifest.incremental_cursor and replay_equal and not (first_ids & second_ids),
                evidence={
                    "first_cursor": batch_one.next_cursor,
                    "second_cursor": batch_two.next_cursor,
                    "duplicate_ids": sorted(first_ids & second_ids),
                },
                reason="incremental_cursor_is_not_restart_safe",
            )
        )

        source_sequences = [item.source_sequence for item in snapshot_one.records]
        checks.append(
            _check(
                "source_sequence_uniqueness",
                len(source_sequences) == len(set(source_sequences)),
                evidence={"record_count": len(source_sequences)},
                reason="source_sequences_are_not_unique",
            )
        )

        required_capabilities = {
            "health_check",
            "schema_discovery",
            "snapshot_read",
            "incremental_read",
        }
        missing_capabilities = sorted(required_capabilities - set(manifest.capabilities))
        checks.append(
            _check(
                "required_capabilities",
                not missing_capabilities,
                evidence={"missing": missing_capabilities},
                reason="connector_capabilities_are_incomplete",
            )
        )

        passed = all(check.status != "fail" for check in checks if check.blocking)
        report_payload = {
            "tenant_id": tenant_id,
            "connector_id": manifest.connector_id,
            "connector_version": manifest.connector_version,
            "source_system": manifest.source_system,
            "evidence_scope": evidence_scope,
            "checks": [check.model_dump(mode="json") for check in checks],
            "passed": passed,
        }
        return ConnectorConformanceReport(
            tenant_id=tenant_id,
            connector_id=manifest.connector_id,
            connector_version=manifest.connector_version,
            source_system=manifest.source_system,
            evidence_scope=evidence_scope,
            checks=checks,
            passed=passed,
            artifact_fingerprint=fingerprint_payload(report_payload),
            claim_boundary=(
                "This report certifies the tested Connector SDK read contract and restart "
                "semantics only; it does not certify production writeback."
            ),
        )


def _check(
    check_id: str,
    passed: bool,
    *,
    evidence: dict,
    reason: str | None = None,
) -> ConformanceCheck:
    return ConformanceCheck(
        check_id=check_id,
        status="pass" if passed else "fail",
        blocking=True,
        evidence=evidence,
        reason=None if passed else reason,
    )
