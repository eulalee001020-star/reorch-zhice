"""Scenario-specific Decision Readiness Manifest evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.integration_control import (
    ConnectorConformanceReport,
    ConnectorRegistrationRequest,
    CanonicalDataEnvelope,
    ConstraintDefinitionDraft,
    DataFieldObservation,
    DecisionReadinessManifest,
    DecisionReadinessRequest,
    IntegrationControlOverview,
    ReadinessCheck,
    ScenarioDataContractDraft,
    SourceAuthorityMatrixDraft,
    VersionedAssetRecord,
    WritebackCertificationReport,
)
from app.services.integration_registry import fingerprint_payload
from app.services.operational_store import RelationalOperationalStore


class DecisionReadinessError(ValueError):
    """Raised when no governed scenario can be evaluated."""


class DecisionReadinessService:
    """Fail-closed gate between normalized data and solve/writeback workflows."""

    def __init__(self, store: RelationalOperationalStore) -> None:
        self.store = store

    def evaluate(self, request: DecisionReadinessRequest) -> DecisionReadinessManifest:
        matrix_asset = self.store.get_active_integration_asset(
            request.tenant_id, "source_authority_matrix", "tenant_default"
        )
        contract_asset = self.store.get_active_integration_asset(
            request.tenant_id, "scenario_data_contract", request.scenario_type
        )
        if matrix_asset is None:
            raise DecisionReadinessError("active_source_authority_matrix_required")
        if contract_asset is None:
            raise DecisionReadinessError("active_scenario_data_contract_required")

        matrix = SourceAuthorityMatrixDraft.model_validate(matrix_asset.payload)
        contract = ScenarioDataContractDraft.model_validate(contract_asset.payload)
        field_observations = {
            item.canonical_path: item for item in request.field_observations
        }
        field_observations.update(
            {
                item.canonical_path: item
                for item in _observations_from_records(
                    contract, request.canonical_records
                )
            }
        )
        constraint_observations = {
            item.constraint_type: item for item in request.constraint_observations
        }
        checks: list[ReadinessCheck] = []
        connector_refs: list[str] = []
        constraint_refs: list[str] = []
        expiry_candidates: list[datetime] = []

        for connector_id in request.required_connector_ids:
            manifest_asset = self.store.get_active_integration_asset(
                request.tenant_id, "connector_manifest", connector_id
            )
            conformance_asset = self.store.get_active_integration_asset(
                request.tenant_id, "connector_conformance", connector_id
            )
            reasons: list[str] = []
            if manifest_asset is None:
                reasons.append("active_manifest_missing")
            if conformance_asset is None:
                reasons.append("active_conformance_missing")
            if manifest_asset and conformance_asset:
                registration = ConnectorRegistrationRequest.model_validate(
                    manifest_asset.payload
                )
                conformance = ConnectorConformanceReport.model_validate(
                    conformance_asset.payload
                )
                if not conformance.passed:
                    reasons.append("conformance_failed")
                if (
                    registration.manifest.connector_version
                    != conformance.connector_version
                ):
                    reasons.append("conformance_version_mismatch")
                connector_refs.extend(
                    [
                        _asset_ref(manifest_asset),
                        _asset_ref(conformance_asset),
                    ]
                )
            checks.append(
                ReadinessCheck(
                    check_id=f"connector:{connector_id}",
                    status="pass" if not reasons else "fail",
                    criticality="hard",
                    message="connector_ready" if not reasons else ";".join(reasons),
                    evidence_refs=(
                        [_asset_ref(manifest_asset)] if manifest_asset else []
                    )
                    + ([_asset_ref(conformance_asset)] if conformance_asset else []),
                )
            )

        for requirement in contract.field_requirements:
            observation = field_observations.get(requirement.canonical_path)
            reasons: list[str] = []
            evidence_refs: list[str] = []
            authority = _resolve_authority(
                matrix,
                requirement.canonical_path,
                requirement.authority_role,
                request.as_of,
            )
            if authority is None:
                reasons.append("authority_resolution_missing")
            if observation is None:
                reasons.append("field_observation_missing")
            else:
                evidence_refs.extend(observation.evidence_refs)
                if authority and observation.source_system != authority.source_system:
                    reasons.append("observation_is_not_from_authoritative_source")
                if observation.authority_role != requirement.authority_role:
                    reasons.append("authority_role_mismatch")
                if not _compatible_type(requirement.data_type, observation.data_type):
                    reasons.append("data_type_mismatch")
                if observation.coverage < requirement.minimum_coverage:
                    reasons.append(
                        f"coverage_below_threshold:{observation.coverage:.4f}"
                    )
                if not observation.quality_passed:
                    reasons.append("quality_rules_failed")
                if requirement.max_age_seconds is not None:
                    if observation.latest_observed_at is None:
                        reasons.append("freshness_timestamp_missing")
                    else:
                        latest = _aware(observation.latest_observed_at)
                        expiry = latest + timedelta(seconds=requirement.max_age_seconds)
                        expiry_candidates.append(expiry)
                        if expiry < _aware(request.as_of):
                            reasons.append("freshness_threshold_exceeded")
            checks.append(
                ReadinessCheck(
                    check_id=f"field:{requirement.canonical_path}",
                    status="pass" if not reasons else "fail",
                    criticality=requirement.criticality,
                    message="field_ready" if not reasons else ";".join(reasons),
                    evidence_refs=evidence_refs,
                )
            )

        for requirement in contract.constraint_requirements:
            observation = constraint_observations.get(requirement.constraint_type)
            active_constraint = self.store.get_active_integration_asset(
                request.tenant_id,
                "constraint_definition",
                requirement.constraint_type,
            )
            reasons: list[str] = []
            evidence_refs: list[str] = []
            if active_constraint is None:
                reasons.append("active_constraint_version_missing")
            else:
                definition = ConstraintDefinitionDraft.model_validate(
                    active_constraint.payload
                )
                if requirement.authority_role not in definition.authority_roles:
                    reasons.append("constraint_authority_role_mismatch")
                constraint_refs.append(_asset_ref(active_constraint))
                evidence_refs.extend(
                    source_ref
                    for replay in definition.replay_evidence
                    for source_ref in replay.source_refs
                )
            if observation is None:
                reasons.append("constraint_coverage_observation_missing")
            else:
                evidence_refs.extend(observation.evidence_refs)
                if observation.authority_role != requirement.authority_role:
                    reasons.append("constraint_observation_authority_mismatch")
                if observation.coverage < requirement.minimum_coverage:
                    reasons.append(
                        f"constraint_coverage_below_threshold:{observation.coverage:.4f}"
                    )
            checks.append(
                ReadinessCheck(
                    check_id=f"constraint:{requirement.constraint_type}",
                    status="pass" if not reasons else "fail",
                    criticality=requirement.criticality,
                    message="constraint_ready" if not reasons else ";".join(reasons),
                    evidence_refs=sorted(set(evidence_refs)),
                )
            )

        hard_gaps = [
            f"{check.check_id}:{check.message}"
            for check in checks
            if check.status == "fail" and check.criticality == "hard"
        ]
        warnings = [
            f"{check.check_id}:{check.message}"
            for check in checks
            if check.status in {"fail", "warning"} and check.criticality == "soft"
        ]
        status = "blocked" if hard_gaps else "degraded" if warnings else "ready"
        evaluated_at = datetime.now(tz=timezone.utc)
        expires_at = min(expiry_candidates) if expiry_candidates else evaluated_at + timedelta(minutes=15)
        if expires_at <= evaluated_at and status != "blocked":
            status = "blocked"
            hard_gaps.append("manifest:freshness_window_already_expired")

        manifest_payload = {
            "tenant_id": request.tenant_id,
            "scenario_type": request.scenario_type,
            "status": status,
            "authority_matrix_ref": _asset_ref(matrix_asset),
            "data_contract_ref": _asset_ref(contract_asset),
            "connector_certification_refs": sorted(set(connector_refs)),
            "constraint_version_refs": sorted(set(constraint_refs)),
            "checks": [check.model_dump(mode="json") for check in checks],
            "hard_gaps": hard_gaps,
            "warnings": warnings,
            "evaluated_at": evaluated_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "evidence_scope": request.evidence_scope,
        }
        manifest = DecisionReadinessManifest(
            tenant_id=request.tenant_id,
            scenario_type=request.scenario_type,
            status=status,
            authority_matrix_ref=_asset_ref(matrix_asset),
            data_contract_ref=_asset_ref(contract_asset),
            connector_certification_refs=sorted(set(connector_refs)),
            constraint_version_refs=sorted(set(constraint_refs)),
            checks=checks,
            hard_gaps=hard_gaps,
            warnings=warnings,
            evaluated_at=evaluated_at,
            expires_at=expires_at,
            evidence_scope=request.evidence_scope,
            fingerprint=fingerprint_payload(manifest_payload),
            claim_boundary=(
                "Readiness is valid only for this scenario, evidence scope, asset versions, "
                "and freshness window. Missing hard facts fail closed and are never inferred by Agent."
            ),
        )
        self._persist_manifest(manifest)
        return manifest

    def assert_ready_manifest(
        self, tenant_id: str, manifest_id: str, scenario_type: str | None = None
    ) -> DecisionReadinessManifest:
        assets = self.store.list_integration_assets(
            tenant_id, asset_type="decision_readiness_manifest", status="active"
        )
        asset = next((item for item in assets if item.asset_id == manifest_id), None)
        if asset is None:
            raise DecisionReadinessError("active_readiness_manifest_not_found")
        manifest = DecisionReadinessManifest.model_validate(asset.payload)
        if (
            manifest.fingerprint != fingerprint_payload(_manifest_payload(manifest))
            or asset.fingerprint != manifest.fingerprint
        ):
            raise DecisionReadinessError("readiness_manifest_fingerprint_mismatch")
        if scenario_type and manifest.scenario_type != scenario_type:
            raise DecisionReadinessError("readiness_manifest_scenario_mismatch")
        if manifest.status != "ready":
            raise DecisionReadinessError("readiness_manifest_is_not_ready")
        if _aware(manifest.expires_at) <= datetime.now(tz=timezone.utc):
            raise DecisionReadinessError("readiness_manifest_has_expired")
        return manifest

    def overview(self, tenant_id: str) -> IntegrationControlOverview:
        assets = self.store.list_integration_assets(tenant_id)
        active_assets: dict[str, list[VersionedAssetRecord]] = {}
        for asset in assets:
            if asset.status == "active":
                active_assets.setdefault(asset.asset_type, []).append(asset)
        manifests = active_assets.get("decision_readiness_manifest", [])
        latest_manifest_asset = max(manifests, key=lambda item: item.created_at, default=None)
        latest_manifest = (
            DecisionReadinessManifest.model_validate(latest_manifest_asset.payload)
            if latest_manifest_asset
            else None
        )
        writeback_certified = False
        for asset in active_assets.get("writeback_certification", []):
            report = WritebackCertificationReport.model_validate(asset.payload)
            if (
                report.passed
                and report.evidence_scope == "customer_sandbox"
                and _aware(report.valid_until) > datetime.now(tz=timezone.utc)
            ):
                writeback_certified = True
                break
        return IntegrationControlOverview(
            tenant_id=tenant_id,
            active_assets=active_assets,
            draft_asset_count=sum(asset.status == "draft" for asset in assets),
            open_quarantine_count=len(
                self.store.list_quarantine_records(tenant_id, status="open")
            ),
            latest_readiness_manifest=latest_manifest,
            production_writeback_certified=writeback_certified,
            claim_boundary=(
                "Digital-twin assets prove technical gate behavior only. Customer sandbox "
                "certification and production evidence remain separate gates."
            ),
        )

    def _persist_manifest(self, manifest: DecisionReadinessManifest) -> None:
        payload = manifest.model_dump(mode="json")
        asset, _ = self.store.put_integration_asset(
            tenant_id=manifest.tenant_id,
            asset_type="decision_readiness_manifest",
            asset_id=manifest.manifest_id,
            scope_key=manifest.scenario_type,
            version=manifest.fingerprint[:16],
            payload=payload,
            fingerprint=manifest.fingerprint,
            created_by="deterministic_data_gate",
        )
        self.store.activate_integration_asset(
            tenant_id=manifest.tenant_id,
            asset_type=asset.asset_type,
            asset_id=asset.asset_id,
            version=asset.version,
            approved_by="deterministic_data_gate",
            approval_note="Deterministic scenario readiness evaluation completed.",
        )
        self.store.append_integration_audit(
            tenant_id=manifest.tenant_id,
            action="decision_readiness_evaluated",
            actor_id="deterministic_data_gate",
            asset_type="decision_readiness_manifest",
            asset_id=manifest.manifest_id,
            details={
                "status": manifest.status,
                "scenario_type": manifest.scenario_type,
                "hard_gap_count": len(manifest.hard_gaps),
                "fingerprint": manifest.fingerprint,
            },
        )


def _resolve_authority(
    matrix: SourceAuthorityMatrixDraft,
    canonical_path: str,
    authority_role: str,
    as_of: datetime,
):
    entity, _, field = canonical_path.partition(".")
    reference_time = _aware(as_of)
    candidates = [
        rule
        for rule in matrix.rules
        if rule.authority_role == authority_role
        and rule.canonical_entity in {entity, "*"}
        and (field in rule.canonical_fields or "*" in rule.canonical_fields)
        and (rule.valid_from is None or _aware(rule.valid_from) <= reference_time)
        and (rule.valid_until is None or reference_time < _aware(rule.valid_until))
    ]
    return min(candidates, key=lambda rule: rule.priority, default=None)


def _compatible_type(expected: str, observed: str) -> bool:
    aliases = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "double": "number",
        "timestamp": "datetime",
        "bool": "boolean",
        "dict": "object",
        "list": "array",
    }
    expected_type = aliases.get(expected.lower(), expected.lower())
    observed_type = aliases.get(observed.lower(), observed.lower())
    return expected_type == observed_type or (
        expected_type == "number" and observed_type == "integer"
    )


def _asset_ref(asset: VersionedAssetRecord) -> str:
    return f"{asset.asset_type}:{asset.asset_id}:{asset.version}:{asset.fingerprint}"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _observations_from_records(
    contract: ScenarioDataContractDraft,
    records: list[CanonicalDataEnvelope],
):
    observations = []
    for requirement in contract.field_requirements:
        entity_type, separator, field = requirement.canonical_path.partition(".")
        if not separator:
            continue
        entity_records = [item for item in records if item.entity_type == entity_type]
        if not entity_records:
            continue
        present_records = [
            item
            for item in entity_records
            if field in item.data
            and (requirement.nullable or item.data.get(field) is not None)
        ]
        values = [item.data.get(field) for item in present_records]
        non_null_values = [value for value in values if value is not None]
        types_valid = all(
            _value_matches_type(value, requirement.data_type)
            for value in non_null_values
        )
        sources = {item.source_system for item in present_records}
        quality_passed = types_valid and _quality_rules_pass(
            requirement.quality_rules,
            non_null_values,
            records,
        )
        observations.append(
            DataFieldObservation(
                canonical_path=requirement.canonical_path,
                source_system=next(iter(sources)) if len(sources) == 1 else "__mixed__",
                authority_role=requirement.authority_role,
                data_type=requirement.data_type if types_valid else "__invalid__",
                present_count=len(present_records),
                total_count=len(entity_records),
                latest_observed_at=max(
                    (_aware(item.observed_at) for item in entity_records), default=None
                ),
                quality_passed=quality_passed,
                evidence_refs=sorted(
                    {
                        ref
                        for item in entity_records
                        for ref in item.evidence_refs
                    }
                ),
            )
        )
    return observations


def _value_matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "datetime":
        return _as_datetime(value) is not None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return False


def _quality_rules_pass(rules, values: list[Any], records: list[CanonicalDataEnvelope]) -> bool:
    for rule in rules:
        if rule.rule_type == "allowed_values":
            allowed = set(rule.parameters.get("values", []))
            if not allowed or any(value not in allowed for value in values):
                return False
        elif rule.rule_type == "non_negative":
            if any(not isinstance(value, (int, float)) or value < 0 for value in values):
                return False
        elif rule.rule_type == "positive":
            if any(not isinstance(value, (int, float)) or value <= 0 for value in values):
                return False
        elif rule.rule_type == "timezone_aware":
            parsed = [_as_datetime(value) for value in values]
            if any(value is None or value.tzinfo is None for value in parsed):
                return False
        elif rule.rule_type == "unique":
            normalized = [fingerprint_payload(value) for value in values]
            if len(normalized) != len(set(normalized)):
                return False
        elif rule.rule_type == "reference_exists":
            target_path = str(rule.parameters.get("target_path", ""))
            target_entity, separator, target_field = target_path.partition(".")
            if not separator:
                return False
            target_values = {
                item.data.get(target_field)
                for item in records
                if item.entity_type == target_entity and target_field in item.data
            }
            if any(value not in target_values for value in values):
                return False
    return True


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _manifest_payload(manifest: DecisionReadinessManifest) -> dict:
    return {
        "tenant_id": manifest.tenant_id,
        "scenario_type": manifest.scenario_type,
        "status": manifest.status,
        "authority_matrix_ref": manifest.authority_matrix_ref,
        "data_contract_ref": manifest.data_contract_ref,
        "connector_certification_refs": manifest.connector_certification_refs,
        "constraint_version_refs": manifest.constraint_version_refs,
        "checks": [check.model_dump(mode="json") for check in manifest.checks],
        "hard_gaps": manifest.hard_gaps,
        "warnings": manifest.warnings,
        "evaluated_at": manifest.evaluated_at.isoformat(),
        "expires_at": manifest.expires_at.isoformat(),
        "evidence_scope": manifest.evidence_scope,
    }
