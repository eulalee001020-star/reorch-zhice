"""CDC, queue, SSO, backup, and shadow runtime tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest

from app.models.production_runtime import (
    AsOfSnapshotRequest,
    CdcEvent,
    ExecutionReceipt,
    ReadOnlyShadowRunRequest,
    SolveJobSubmitRequest,
    TenantSolveQuota,
)
from app.services.cdc_consistency import CdcConsistencyService
from app.services.oidc_auth import OIDCTokenVerifier, OIDCVerificationError
from app.services.operational_store import RelationalOperationalStore
from app.services.production_digital_twin import ProductionDigitalTwinFactory
from app.services.runtime_backup import RuntimeBackupService
from app.services.shadow_execution import ReadOnlyShadowRunner
from app.services.solve_job_runtime import DurableSolveQueue, SolveJobWorker


NOW = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


def _event(source: str, sequence: int, *, event_id: str | None = None) -> CdcEvent:
    return CdcEvent(
        event_id=event_id or f"{source}-{sequence}",
        tenant_id="TENANT-1",
        source_system=source,
        sequence=sequence,
        occurred_at=NOW,
        entity_type="work_order",
        entity_id=f"WO-{sequence}",
        payload={"status": "released", "sequence": sequence},
    )


def test_cdc_gap_checkpoint_resume_and_cross_source_asof(tmp_path: Path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'runtime.db'}"
    first_service = CdcConsistencyService(RelationalOperationalStore(url))
    gap = first_service.ingest(_event("ERP", 2))
    assert gap.status == "gap_buffered"
    assert gap.gap_sequences == [1]

    resumed_service = CdcConsistencyService(RelationalOperationalStore(url))
    resumed = resumed_service.ingest(_event("ERP", 1))
    for source in ("MES", "QMS"):
        resumed_service.ingest(_event(source, 1))
    snapshot = resumed_service.materialize_as_of(
        AsOfSnapshotRequest(
            tenant_id="TENANT-1",
            required_sources=["ERP", "MES", "QMS"],
            as_of=NOW,
        )
    )

    assert resumed.committed_sequence == 2
    assert resumed.gap_sequences == []
    assert snapshot.status == "consistent"
    assert len(snapshot.entities["ERP"]) == 2


def test_cdc_rejects_checksum_mismatch_and_stale_asof() -> None:
    service = CdcConsistencyService(RelationalOperationalStore())
    bad = _event("ERP", 1).model_copy(update={"checksum": "bad"})
    assert service.ingest(bad).status == "checksum_rejected"
    service.ingest(_event("ERP", 1))
    response = service.materialize_as_of(
        AsOfSnapshotRequest(
            tenant_id="TENANT-1",
            required_sources=["ERP", "MES"],
            as_of=NOW,
        )
    )
    assert response.status == "blocked"
    assert "missing_source_checkpoint:MES" in response.blockers


def test_durable_queue_idempotency_quota_lease_and_completion() -> None:
    store = RelationalOperationalStore()
    queue = DurableSolveQueue(
        store,
        default_quota=TenantSolveQuota(
            max_queued_jobs=1,
            max_running_jobs=1,
            max_operations_per_job=200,
        ),
    )
    solve_request = ProductionDigitalTwinFactory().build_solve_request(
        120, tenant_id="digital-twin"
    )
    submit = SolveJobSubmitRequest(
        tenant_id="digital-twin",
        idempotency_key="job-1",
        solve_request=solve_request,
    )
    first, created = queue.submit(submit)
    same, duplicate_created = queue.submit(submit)
    with pytest.raises(ValueError, match="queued_job_quota"):
        queue.submit(submit.model_copy(update={"idempotency_key": "job-2"}))

    claimed = queue.claim("worker-a", lease_seconds=3)
    assert queue.claim("worker-b", lease_seconds=3) is None
    assert claimed is not None
    store.recover_expired_leases(datetime.now(tz=timezone.utc) + timedelta(seconds=5))
    completed = SolveJobWorker(queue, worker_id="worker-b").run_once().job

    assert created is True
    assert duplicate_created is False
    assert first.job_id == same.job_id
    assert completed is not None
    assert completed.status == "completed"


def test_oidc_signature_audience_role_and_tenant_mapping() -> None:
    secret = "test-oidc-secret"
    now = int(datetime.now(tz=timezone.utc).timestamp())
    verifier = OIDCTokenVerifier(
        issuer="https://idp.example",
        audience="reorch",
        algorithms=["HS256"],
        role_claim="realm.roles",
        tenant_claim="tenant.id",
        role_mapping={"planner": "Planner"},
        verification_key=secret,
    )
    claims = {
        "iss": "https://idp.example",
        "aud": "reorch",
        "sub": "user-1",
        "iat": now,
        "exp": now + 300,
        "realm": {"roles": ["planner"]},
        "tenant": {"id": "TENANT-1"},
    }
    principal = verifier.verify(jwt.encode(claims, secret, algorithm="HS256"))

    assert principal.role == "Planner"
    assert principal.tenant_id == "TENANT-1"
    with pytest.raises(OIDCVerificationError):
        verifier.verify(
            jwt.encode({**claims, "aud": "other"}, secret, algorithm="HS256")
        )


def test_runtime_backup_restore_detects_tamper(tmp_path: Path) -> None:
    source = RelationalOperationalStore()
    CdcConsistencyService(source).ingest(_event("ERP", 1))
    target = RelationalOperationalStore()
    path = tmp_path / "runtime-backup.json"
    service = RuntimeBackupService()
    drill = service.drill(source, target, path)

    assert drill["status"] == "passed"
    assert drill["restore_verified"] is True
    document = path.read_text(encoding="utf-8").replace("released", "tampered")
    path.write_text(document, encoding="utf-8")
    with pytest.raises(ValueError, match="checksum_mismatch"):
        service.restore_backup(RelationalOperationalStore(), path)


def test_readonly_shadow_closes_only_after_all_mes_receipts() -> None:
    store = RelationalOperationalStore()
    runner = ReadOnlyShadowRunner(store)
    solve_request = ProductionDigitalTwinFactory().build_solve_request(
        100, tenant_id="digital-twin", incident_count=3
    )
    shadow = runner.run(
        ReadOnlyShadowRunRequest(
            tenant_id="digital-twin",
            consistent_snapshot_ref="asof:1",
            solve_request=solve_request,
            source_refs=["cdc:asof:1"],
        )
    )
    shadow = runner.record_planner_decision(
        shadow.shadow_case_id,
        planner_baseline={"policy": "manual"},
        planner_decision={"decision_status": "accepted", "planner_id": "p1"},
    )
    planned = {
        op.operation_id: op
        for wo in shadow.solve_result.final_schedule.work_orders
        for op in wo.operations
    }
    receipts = [
        ExecutionReceipt(
            receipt_id=f"R-{index}",
            tenant_id="digital-twin",
            shadow_case_id=shadow.shadow_case_id,
            source_event_id=f"MES-{index}",
            operation_id=operation_id,
            event_type="completed",
            observed_at=planned[operation_id].end_time,
            actual_start=planned[operation_id].start_time,
            actual_end=planned[operation_id].end_time,
            actual_resource_id=planned[operation_id].resource_id,
        )
        for index, operation_id in enumerate(shadow.expected_terminal_operation_ids)
    ]
    partial = runner.ingest_receipts(shadow.shadow_case_id, receipts[:-1])
    closed = runner.ingest_receipts(shadow.shadow_case_id, receipts[-1:])

    assert partial.status == "awaiting_execution"
    assert closed.status == "execution_closed"
    assert closed.writeback_invocation_count == 0
    assert closed.execution_metrics["execution_outcome_complete"] is True
