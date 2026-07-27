"""Durable solve queue with tenant quotas, leases, cancellation, and resume."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app.core.config import settings
from app.models.production_runtime import (
    SolveJobRecord,
    SolveJobSubmitRequest,
    SubproblemExecutionResult,
    TenantSolveQuota,
)
from app.services.decomposition_executor import DecompositionExecutor
from app.services.decision_readiness import DecisionReadinessService
from app.services.operational_store import RelationalOperationalStore


class DurableSolveQueue:
    """Relational queue shared by multiple workers."""

    def __init__(
        self,
        store: RelationalOperationalStore,
        *,
        default_quota: TenantSolveQuota | None = None,
    ) -> None:
        self.store = store
        self.default_quota = default_quota or TenantSolveQuota()
        self._quotas: dict[str, TenantSolveQuota] = {}

    def set_tenant_quota(self, tenant_id: str, quota: TenantSolveQuota) -> None:
        self._quotas[tenant_id] = quota

    def quota_for(self, tenant_id: str) -> TenantSolveQuota:
        return self._quotas.get(tenant_id, self.default_quota)

    def submit(self, request: SolveJobSubmitRequest) -> tuple[SolveJobRecord, bool]:
        if request.solve_request.tenant_id != request.tenant_id:
            raise ValueError("solve_request_tenant_mismatch")
        record = SolveJobRecord(
            tenant_id=request.tenant_id,
            idempotency_key=request.idempotency_key,
            priority=request.priority,
            solve_request=request.solve_request,
        )
        return self.store.submit_solve_job(record, self.quota_for(request.tenant_id))

    def claim(self, worker_id: str, lease_seconds: int = 30) -> SolveJobRecord | None:
        quota_by_tenant = dict(self._quotas)
        return self.store.claim_solve_job(worker_id, lease_seconds, quota_by_tenant)

    def cancel(self, job_id: str) -> SolveJobRecord | None:
        return self.store.request_job_cancel(job_id)

    def get(self, job_id: str) -> SolveJobRecord | None:
        return self.store.get_solve_job(job_id)

    def recover_expired(self) -> int:
        return self.store.recover_expired_leases()


@dataclass
class SolveWorkerResult:
    worker_id: str
    job: SolveJobRecord | None


class SolveJobWorker:
    """Execute one leased job while persisting subproblem checkpoints."""

    def __init__(
        self,
        queue: DurableSolveQueue,
        *,
        worker_id: str,
        executor: DecompositionExecutor | None = None,
        lease_seconds: int = 30,
    ) -> None:
        self.queue = queue
        self.worker_id = worker_id
        self.executor = executor or DecompositionExecutor()
        self.lease_seconds = max(3, lease_seconds)

    def run_once(self) -> SolveWorkerResult:
        job = self.queue.claim(self.worker_id, self.lease_seconds)
        if job is None:
            return SolveWorkerResult(worker_id=self.worker_id, job=None)

        completed_payloads = dict(
            (job.checkpoint or {}).get("completed_subproblems", {})
        )
        checkpoints: dict[str, SubproblemExecutionResult] = {}
        for subproblem_id, payload in completed_payloads.items():
            try:
                checkpoints[subproblem_id] = SubproblemExecutionResult.model_validate(payload)
            except Exception:
                continue

        stop_heartbeat = threading.Event()

        def heartbeat() -> None:
            interval = max(1.0, self.lease_seconds / 3)
            while not stop_heartbeat.wait(interval):
                if not self.queue.store.heartbeat_job(
                    job.job_id, self.worker_id, self.lease_seconds
                ):
                    return

        heartbeat_thread = threading.Thread(
            target=heartbeat,
            name=f"lease-{self.worker_id}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            if job.solve_request.readiness_manifest_id:
                DecisionReadinessService(self.queue.store).assert_ready_manifest(
                    job.tenant_id,
                    job.solve_request.readiness_manifest_id,
                    job.solve_request.scenario_type,
                )
            elif settings.app.env in {"staging", "production"}:
                raise ValueError("active_decision_readiness_manifest_required_at_execution")
            result = self.executor.execute(
                job.solve_request,
                cancel_check=lambda: self.queue.store.should_cancel_job(
                    job.job_id, self.worker_id
                ),
                checkpoint_results=checkpoints,
                checkpoint_callback=lambda item: self.queue.store.save_job_checkpoint(
                    job.job_id,
                    self.worker_id,
                    item.subproblem_id,
                    item.model_dump(mode="json"),
                ),
            )
            terminal = (
                "completed"
                if result.status == "feasible"
                else "cancelled"
                if result.status == "cancelled"
                else "failed"
            )
            finished = self.queue.store.finish_job(
                job.job_id,
                self.worker_id,
                status=terminal,
                result=result.model_dump(mode="json"),
                error=None if terminal == "completed" else ";".join(result.blockers),
            )
        except Exception as exc:
            finished = self.queue.store.finish_job(
                job.job_id,
                self.worker_id,
                status="failed",
                result=None,
                error=f"{type(exc).__name__}:{exc}",
            )
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=2)
        return SolveWorkerResult(worker_id=self.worker_id, job=finished)
