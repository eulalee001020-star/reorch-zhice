"""Service-level tests for the enterprise integration control plane."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.db.operational_runtime import IntegrationAssetRecordORM
from app.models.integration_control import (
    CanonicalDataEnvelope,
    ConstraintCoverageObservation,
    ConstraintDefinitionDraft,
    DataFieldObservation,
    DecisionReadinessRequest,
    SourceAuthorityMatrixDraft,
    SourceAuthorityRule,
)
from app.services.decision_readiness import (
    DecisionReadinessError,
    DecisionReadinessService,
)
from app.services.integration_control_validation import (
    IntegrationControlValidationHarness,
)
from app.services.integration_registry import (
    IntegrationRegistryError,
    IntegrationRegistryService,
)
from app.services.operational_store import RelationalOperationalStore
from app.services.schema_drift_guard import SchemaDriftGuard
from app.models.integration_control import SchemaObservationRequest


TENANT = "TENANT-TEST"
ACTOR = "admin-test"
REFERENCE_TIME = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


def test_full_integration_control_digital_twin_passes() -> None:
    result = IntegrationControlValidationHarness(RelationalOperationalStore()).run(
        tenant_id=TENANT, actor_id=ACTOR
    )

    assert result.all_checks_passed is True
    assert len(result.checks) == 8
    assert result.readiness_manifest.status == "ready"
    assert result.compatible_drift_report.status == "compatible"
    assert result.breaking_drift_report.status == "quarantined"
    assert result.quarantine_resolution.status == "rejected"
    assert result.writeback_certification.passed is True
    assert len(result.writeback_certification.checks) == 15
    assert any(
        check.check_id == "transient_retry_single_apply"
        and check.status == "pass"
        for check in result.writeback_certification.checks
    )
    assert result.overview.production_writeback_certified is False


def test_asset_versions_are_immutable_and_activation_requires_named_admin() -> None:
    store = RelationalOperationalStore()
    registry = IntegrationRegistryService(store)
    draft = SourceAuthorityMatrixDraft(
        tenant_id=TENANT,
        matrix_id="authority",
        version="1.0.0",
        rules=[
            SourceAuthorityRule(
                authority_role="operation_authority",
                source_system="MES",
                canonical_entity="operation",
                canonical_fields=["*"],
            )
        ],
    )
    registry.register_authority_matrix(draft, ACTOR)

    with pytest.raises(IntegrationRegistryError, match="named_approver"):
        registry.activate_authority_matrix(
            TENANT, "authority", "1.0.0", "system", "System cannot approve."
        )

    changed = draft.model_copy(
        update={
            "rules": [
                draft.rules[0].model_copy(update={"source_system": "ERP"})
            ]
        }
    )
    with pytest.raises(IntegrationRegistryError, match="immutable_integration_asset_collision"):
        registry.register_authority_matrix(changed, ACTOR)


def test_equal_priority_authority_conflict_is_rejected() -> None:
    draft = SourceAuthorityMatrixDraft(
        tenant_id=TENANT,
        matrix_id="authority",
        version="1.0.0",
        rules=[
            SourceAuthorityRule(
                authority_role="operation_authority",
                source_system=source,
                canonical_entity="operation",
                canonical_fields=["status"],
                priority=10,
            )
            for source in ("MES-A", "MES-B")
        ],
    )

    with pytest.raises(IntegrationRegistryError, match="equal_priority_conflict"):
        IntegrationRegistryService(
            RelationalOperationalStore()
        ).register_authority_matrix(draft, ACTOR)


def test_constraint_activation_requires_three_executed_results() -> None:
    registry = IntegrationRegistryService(RelationalOperationalStore())
    draft = ConstraintDefinitionDraft(
        tenant_id=TENANT,
        constraint_id="material-ready",
        constraint_type="material_availability",
        version="1.0.0",
        criticality="hard",
        authority_roles=["material_authority"],
        compiler_ref="compiler",
        validator_ref="validator",
        replay_evidence=[],
        proposed_by_agent=True,
    )
    registry.register_constraint(draft, ACTOR)

    with pytest.raises(IntegrationRegistryError, match="three_executed_replay_results"):
        registry.activate_constraint(
            TENANT,
            draft.constraint_id,
            draft.version,
            ACTOR,
            "Agent candidate reviewed but evidence is missing.",
        )


def test_missing_hard_field_blocks_scenario_readiness() -> None:
    store = RelationalOperationalStore()
    result = IntegrationControlValidationHarness(store).run(
        tenant_id=TENANT, actor_id=ACTOR
    )
    observations = [
        DataFieldObservation(
            canonical_path=check.check_id.removeprefix("field:"),
            source_system="MES",
            authority_role="operation_authority",
            data_type=(
                "datetime"
                if check.check_id.endswith(("planned_start", "planned_end"))
                else "string"
            ),
            present_count=4,
            total_count=4,
            latest_observed_at=REFERENCE_TIME,
            evidence_refs=["test:field"],
        )
        for check in result.readiness_manifest.checks
        if check.check_id.startswith("field:")
        and not check.check_id.endswith("planned_end")
    ]

    blocked = DecisionReadinessService(store).evaluate(
        DecisionReadinessRequest(
            tenant_id=TENANT,
            scenario_type="machine_down_recovery",
            as_of=REFERENCE_TIME,
            field_observations=observations,
            constraint_observations=[],
            required_connector_ids=["dt-mes-connector"],
        )
    )

    assert blocked.status == "blocked"
    assert any("field:operation.planned_end" in gap for gap in blocked.hard_gaps)
    assert any("constraint:resource_eligibility" in gap for gap in blocked.hard_gaps)


def test_breaking_schema_observation_is_deduplicated_in_quarantine() -> None:
    store = RelationalOperationalStore()
    IntegrationControlValidationHarness(store).run(tenant_id=TENANT, actor_id=ACTOR)
    observation = SchemaObservationRequest(
        tenant_id=TENANT,
        connector_id="dt-mes-connector",
        source_system="MES",
        entity_type="operation",
        schema_version="3.0.0",
        fields={"operation_id": "integer"},
        observed_at=REFERENCE_TIME,
    )
    guard = SchemaDriftGuard(store)

    first = guard.evaluate(observation)
    second = guard.evaluate(observation)

    assert first.status == second.status == "quarantined"
    assert first.quarantine_id == second.quarantine_id


def test_readiness_manifest_tampering_is_detected() -> None:
    store = RelationalOperationalStore()
    result = IntegrationControlValidationHarness(store).run(
        tenant_id=TENANT, actor_id=ACTOR
    )
    with store.session() as session, session.begin():
        row = session.scalar(
            select(IntegrationAssetRecordORM).where(
                IntegrationAssetRecordORM.tenant_id == TENANT,
                IntegrationAssetRecordORM.asset_type == "decision_readiness_manifest",
                IntegrationAssetRecordORM.status == "active",
            )
        )
        assert row is not None
        payload = dict(row.payload)
        payload["expires_at"] = (datetime.now(tz=timezone.utc) + timedelta(days=30)).isoformat()
        row.payload = payload

    with pytest.raises(DecisionReadinessError, match="fingerprint_mismatch"):
        DecisionReadinessService(store).assert_ready_manifest(
            TENANT,
            result.readiness_manifest.manifest_id,
            "machine_down_recovery",
        )


def test_canonical_records_drive_quality_rules_without_caller_claims() -> None:
    store = RelationalOperationalStore()
    IntegrationControlValidationHarness(store).run(tenant_id=TENANT, actor_id=ACTOR)
    records = [
        CanonicalDataEnvelope(
            source_system="MES",
            entity_type="operation",
            entity_id=f"OP-{index}",
            observed_at=REFERENCE_TIME,
            data={
                "operation_id": "DUPLICATE-ID",
                "work_order_id": "WO-1",
                "resource_id": f"M-{index}",
                "status": "unknown_status",
                "planned_start": REFERENCE_TIME.isoformat(),
                "planned_end": (REFERENCE_TIME + timedelta(hours=1)).isoformat(),
            },
            evidence_refs=[f"test:record:{index}"],
        )
        for index in range(1, 3)
    ]

    manifest = DecisionReadinessService(store).evaluate(
        DecisionReadinessRequest(
            tenant_id=TENANT,
            scenario_type="machine_down_recovery",
            as_of=REFERENCE_TIME,
            canonical_records=records,
            constraint_observations=[
                ConstraintCoverageObservation(
                    constraint_type="resource_eligibility",
                    authority_role="operation_authority",
                    covered_count=2,
                    total_count=2,
                    evidence_refs=["test:constraint"],
                )
            ],
            required_connector_ids=["dt-mes-connector"],
        )
    )

    assert manifest.status == "blocked"
    assert any(
        "field:operation.operation_id" in gap and "quality_rules_failed" in gap
        for gap in manifest.hard_gaps
    )
    assert any(
        "field:operation.status" in gap and "quality_rules_failed" in gap
        for gap in manifest.hard_gaps
    )
