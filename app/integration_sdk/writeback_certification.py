"""Executable certification pack for sandbox writeback adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.integration_sdk.base import EnterpriseConnector, WritebackCommand
from app.models.integration_control import (
    ConformanceCheck,
    WritebackAdapterProfile,
    WritebackCertificationReport,
)
from app.services.integration_registry import fingerprint_payload


class WritebackCertificationHarness:
    """Verifies reread, CAS, idempotency, receipt, reconcile, and compensation."""

    def run(
        self,
        connector: EnterpriseConnector,
        *,
        tenant_id: str,
        adapter_id: str,
        evidence_scope: str = "digital_twin",
    ) -> WritebackCertificationReport:
        manifest = connector.manifest
        profile = WritebackAdapterProfile(
            adapter_id=adapter_id,
            connector_id=manifest.connector_id,
            adapter_version=manifest.connector_version,
            source_system=manifest.source_system,
            command_types=["reschedule_operation"],
            permission_scopes=["schedule:read", "schedule:sandbox_write"],
        )
        checks = [
            _feature_check("sandbox_target", manifest.target_environment == "sandbox"),
            _feature_check("idempotency_declared", manifest.idempotent_writes),
            _feature_check("compare_and_swap_declared", manifest.compare_and_swap),
            _feature_check("durable_outbox_declared", manifest.durable_outbox),
            _feature_check("execution_receipts_declared", manifest.execution_receipts),
            _feature_check("reconciliation_declared", manifest.reconciliation),
            _feature_check("compensation_declared", manifest.compensation),
        ]

        outbox_before = connector.read_target("operation", "OP-2")
        outbox_probe = connector.probe_outbox_retry(
            WritebackCommand(
                idempotency_key=f"cert-outbox:{uuid4().hex}",
                entity_type="operation",
                entity_id="OP-2",
                expected_version=outbox_before.version,
                changes={"status": "outbox_retried"},
            )
        )
        checks.append(
            _runtime_check(
                "transient_retry_single_apply",
                outbox_probe.transient_failure_observed
                and outbox_probe.retry_attempt_count >= 2
                and outbox_probe.applied_count == 1
                and outbox_probe.final_receipt.status == "applied",
                outbox_probe.model_dump(mode="json"),
            )
        )
        connector.compensate(outbox_probe.final_receipt.receipt_id)
        outbox_restored = connector.read_target("operation", "OP-2")
        checks.append(
            _runtime_check(
                "outbox_probe_compensated",
                outbox_restored.state_hash == outbox_before.state_hash,
                {
                    "restored_hash": outbox_restored.state_hash,
                    "expected_hash": outbox_before.state_hash,
                },
            )
        )

        before = connector.read_target("operation", "OP-1")
        idempotency_key = f"cert:{uuid4().hex}"
        command = WritebackCommand(
            idempotency_key=idempotency_key,
            entity_type="operation",
            entity_id="OP-1",
            expected_version=before.version,
            changes={"resource_id": "M-CERT", "status": "rescheduled"},
        )
        first_receipt = connector.sandbox_write(command)
        replay_receipt = connector.sandbox_write(command)
        after = connector.read_target("operation", "OP-1")
        checks.append(
            _runtime_check(
                "read_before_write_and_apply",
                first_receipt.status == "applied"
                and first_receipt.before_hash == before.state_hash
                and after.state_hash == first_receipt.after_hash,
                {
                    "before_version": before.version,
                    "target_version": after.version,
                    "receipt_id": first_receipt.receipt_id,
                },
            )
        )
        checks.append(
            _runtime_check(
                "duplicate_write_idempotency",
                replay_receipt.receipt_id == first_receipt.receipt_id,
                {"receipt_id": replay_receipt.receipt_id},
            )
        )

        stale_receipt = connector.sandbox_write(
            WritebackCommand(
                idempotency_key=f"cert-stale:{uuid4().hex}",
                entity_type="operation",
                entity_id="OP-1",
                expected_version=before.version,
                changes={"status": "should_not_apply"},
            )
        )
        checks.append(
            _runtime_check(
                "stale_compare_and_swap_rejected",
                stale_receipt.status == "rejected"
                and stale_receipt.reason == "compare_and_swap_version_conflict",
                {"reason": stale_receipt.reason},
            )
        )

        persisted_receipt = connector.get_receipt(idempotency_key)
        checks.append(
            _runtime_check(
                "receipt_correlation",
                persisted_receipt is not None
                and persisted_receipt.receipt_id == first_receipt.receipt_id,
                {"idempotency_key": idempotency_key},
            )
        )

        reconciliation = connector.reconcile(first_receipt.receipt_id)
        checks.append(
            _runtime_check(
                "post_write_reconciliation",
                reconciliation.matched,
                reconciliation.model_dump(mode="json"),
            )
        )

        compensation = connector.compensate(first_receipt.receipt_id)
        restored = connector.read_target("operation", "OP-1")
        checks.append(
            _runtime_check(
                "compensation_restores_business_state",
                compensation.status == "compensated"
                and restored.state_hash == before.state_hash,
                {
                    "compensation_receipt_id": compensation.receipt_id,
                    "restored_hash": restored.state_hash,
                    "expected_hash": before.state_hash,
                },
            )
        )

        passed = all(check.status != "fail" for check in checks if check.blocking)
        executed_at = datetime.now(tz=timezone.utc)
        payload = {
            "tenant_id": tenant_id,
            "profile": profile.model_dump(mode="json"),
            "executed_at": executed_at.isoformat(),
            "checks": [check.model_dump(mode="json") for check in checks],
            "passed": passed,
        }
        return WritebackCertificationReport(
            tenant_id=tenant_id,
            profile=profile,
            evidence_scope=evidence_scope,
            executed_at=executed_at,
            valid_until=executed_at + timedelta(days=90),
            checks=checks,
            passed=passed,
            artifact_fingerprint=fingerprint_payload(payload),
            claim_boundary=(
                "Certification is limited to the tested adapter version and sandbox target. "
                "Each write still requires a fresh readiness manifest, human approval, and "
                "a short-lived execution permit."
            ),
        )


def _feature_check(check_id: str, passed: bool) -> ConformanceCheck:
    return _runtime_check(check_id, passed, {"declared": passed})


def _runtime_check(check_id: str, passed: bool, evidence: dict) -> ConformanceCheck:
    return ConformanceCheck(
        check_id=check_id,
        status="pass" if passed else "fail",
        blocking=True,
        evidence=evidence,
        reason=None if passed else f"{check_id}_failed",
    )
