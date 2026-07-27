"""End-to-end digital-twin validation for production runtime capabilities."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt

from app.models.agent import ConstraintCandidate, RuleCandidateReplayRequest
from app.models.enums import StrategyType
from app.models.feasibility_restoration import (
    FeasibilityRestorationRequest,
    RecoveryApprovalAttestation,
)
from app.models.impact import AffectedOperation, ImpactReport
from app.models.production_runtime import (
    AsOfSnapshotRequest,
    CdcEvent,
    DecompositionExecutionRequest,
    ExecutionReceipt,
    ProductionValidationRunResponse,
    ReadOnlyShadowRunRequest,
    RuntimeIncident,
    SolveJobSubmitRequest,
    TenantSolveQuota,
)
from app.services.cdc_consistency import CdcConsistencyService
from app.services.decomposition_executor import DecompositionExecutor
from app.services.feasibility_restoration import (
    FeasibilityRestorationEngine,
    conservative_default_recovery_policy,
)
from app.services.integration_control_validation import (
    IntegrationControlValidationHarness,
)
from app.services.oidc_auth import OIDCTokenVerifier, OIDCVerificationError
from app.services.operational_store import RelationalOperationalStore
from app.services.production_digital_twin import ProductionDigitalTwinFactory
from app.services.recovery_evidence_ledger import RecoveryEvidenceLedgerService
from app.services.rule_candidate_replay import RuleCandidateReplayService
from app.services.runtime_backup import RuntimeBackupService
from app.services.shadow_execution import ReadOnlyShadowRunner
from app.services.solve_job_runtime import DurableSolveQueue, SolveJobWorker


class ProductionValidationHarness:
    """Exercise every technical path using deterministic non-customer data."""

    def run(self, *, scale_repetitions: int = 5) -> ProductionValidationRunResponse:
        if not 1 <= scale_repetitions <= 20:
            raise ValueError("scale_repetitions_must_be_1_to_20")
        checks: dict[str, dict[str, Any]] = {}
        factory = ProductionDigitalTwinFactory()
        executor = DecompositionExecutor()

        scale_results = self._run_scale_gate(
            factory, executor, repetitions=scale_repetitions
        )
        checks["decomposition_and_joint_optimization"] = {
            "status": "pass"
            if all(item["all_runs_feasible"] for item in scale_results)
            else "fail",
            "targets": [item["operation_count"] for item in scale_results],
            "joint_incident_group_verified": all(
                item["joint_incident_group_verified"] for item in scale_results
            ),
            "parallel_execution_verified": all(
                item["max_observed_parallelism"] >= 2 for item in scale_results
            ),
        }
        checks["anytime_hybrid_solver"] = {
            "status": "pass"
            if all(
                item["all_incumbents_validated"]
                and item["warm_start_verified"]
                and item["min_pareto_front_size"] >= 1
                and item["alns_attempt_count"] > 0
                and item["p95_first_feasible_ms"] <= 2000
                for item in scale_results
            )
            else "fail",
            "p95_first_feasible_ms_by_scale": {
                str(item["operation_count"]): item["p95_first_feasible_ms"]
                for item in scale_results
            },
            "warm_start_verified": all(
                item["warm_start_verified"] for item in scale_results
            ),
            "all_incumbents_validated": all(
                item["all_incumbents_validated"] for item in scale_results
            ),
            "pareto_front_verified": all(
                item["min_pareto_front_size"] >= 1 for item in scale_results
            ),
            "alns_repair_verified": all(
                item["alns_attempt_count"] > 0 for item in scale_results
            ),
            "first_feasible_target_ms": 2000,
        }

        checks["operational_constraints"] = self._run_constraint_gate(factory, executor)
        checks["feasibility_restoration"] = self._run_feasibility_restoration_gate(
            factory
        )

        with tempfile.TemporaryDirectory(prefix="reorch-production-validation-") as temp_dir:
            database_url = f"sqlite+pysqlite:///{Path(temp_dir) / 'runtime.db'}"
            store = RelationalOperationalStore(database_url)
            checks["cdc_asof_consistency"] = self._run_cdc_gate(store)
            checks["durable_queue_quota_ha"] = self._run_queue_gate(store, factory, executor)
            checks["sso_rbac"] = self._run_sso_gate()
            checks["shadow_execution_closure"] = self._run_shadow_gate(
                store, factory
            )
            checks["rule_candidate_replay"] = self._run_rule_replay_gate()
            integration_control = IntegrationControlValidationHarness(store).run(
                tenant_id="digital-twin",
                actor_id="digital-twin-it-admin",
            )
            checks["integration_control_plane"] = {
                "status": "pass" if integration_control.all_checks_passed else "fail",
                "asset_check_count": len(integration_control.checks),
                "readiness_status": integration_control.readiness_manifest.status,
                "schema_breaking_status": integration_control.breaking_drift_report.status,
                "quarantine_resolution": integration_control.quarantine_resolution.status,
                "connector_conformance_passed": integration_control.connector_conformance.passed,
                "writeback_certification_passed": (
                    integration_control.writeback_certification.passed
                ),
                "customer_writeback_certified": (
                    integration_control.overview.production_writeback_certified
                ),
                "artifact_fingerprint": integration_control.artifact_fingerprint,
            }
            ledger = RecoveryEvidenceLedgerService(
                executor=executor, store=store
            ).build_digital_twin_ledger(case_count=30)
            checks["evidence_roi_ledger"] = {
                "status": "pass"
                if ledger.case_count == 30
                and ledger.planner_baseline_complete
                and ledger.execution_outcome_complete
                and ledger.roi_is_proxy
                and not ledger.customer_evidence_gate_passed
                else "fail",
                "case_count": ledger.case_count,
                "incident_types": sorted(
                    {case.incident.incident_type for case in ledger.cases}
                ),
                "customer_evidence_gate_passed": ledger.customer_evidence_gate_passed,
                "blockers": ledger.blockers,
                "aggregate_roi": ledger.aggregate_roi,
            }
            target = RelationalOperationalStore()
            drill = RuntimeBackupService().drill(
                store, target, Path(temp_dir) / "runtime-backup.json"
            )
            checks["backup_restore"] = {
                **drill,
                "drill_status": drill["status"],
                "status": "pass" if drill["restore_verified"] else "fail",
            }

        technical_pass = all(item.get("status") == "pass" for item in checks.values())
        blockers = list(ledger.blockers)
        payload = {
            "checks": checks,
            "scale_results": scale_results,
            "ledger_fingerprint": ledger.ledger_fingerprint,
            "technical_pass": technical_pass,
            "customer_gate": ledger.customer_evidence_gate_passed,
        }
        return ProductionValidationRunResponse(
            checks=checks,
            scale_results=scale_results,
            evidence_ledger=ledger,
            all_digital_twin_checks_passed=technical_pass,
            customer_evidence_gate_passed=ledger.customer_evidence_gate_passed,
            blockers=blockers,
            artifact_fingerprint=_fingerprint(payload),
            claim_boundary=(
                "All passing checks use deterministic digital-twin data and validate "
                "technical behavior only. Real customer shadow, SSO acceptance, HA "
                "infrastructure, connector certification, writeback certification, and "
                "realized ROI remain external acceptance gates."
            ),
        )

    @staticmethod
    def _run_scale_gate(factory, executor, *, repetitions: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for operation_count in (1000, 5000, 10000):
            request = factory.build_solve_request(operation_count, incident_count=5)
            elapsed: list[float] = []
            fingerprints: list[str] = []
            statuses: list[str] = []
            observed: list[int] = []
            joint_verified: list[bool] = []
            violation_counts: list[int] = []
            first_feasible: list[float] = []
            validated_incumbents: list[bool] = []
            warm_start_hints: list[bool] = []
            pareto_front_sizes: list[int] = []
            alns_attempts: list[int] = []
            for _ in range(repetitions):
                started = time.perf_counter()
                response = executor.execute(request)
                elapsed.append((time.perf_counter() - started) * 1000)
                fingerprints.append(response.evidence_fingerprint)
                statuses.append(response.status)
                observed.append(response.observed_parallelism)
                violation_counts.append(len(response.violations))
                joint_verified.append(
                    any(len(group) >= 2 for group in response.joint_incident_groups)
                )
                for subproblem in response.subproblem_results:
                    metadata = subproblem.solver_metadata
                    if metadata.get("time_to_first_feasible_ms") is not None:
                        first_feasible.append(
                            float(metadata["time_to_first_feasible_ms"])
                        )
                    validated_incumbents.append(
                        bool(metadata.get("validated_incumbent"))
                    )
                    warm_start_hints.append(
                        bool(metadata.get("cp_sat_hint_applied"))
                    )
                    pareto_front_sizes.append(
                        int(metadata.get("pareto_front_size", 0))
                    )
                    alns_attempts.append(int(metadata.get("alns_attempts", 0)))
            ordered = sorted(elapsed)
            p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
            ordered_first_feasible = sorted(first_feasible)
            first_feasible_p95_index = max(
                0,
                math.ceil(0.95 * len(ordered_first_feasible)) - 1,
            )
            results.append(
                {
                    "operation_count": operation_count,
                    "repetitions": repetitions,
                    "all_runs_feasible": all(status == "feasible" for status in statuses),
                    "p50_elapsed_ms": round(ordered[len(ordered) // 2], 3),
                    "p95_elapsed_ms": round(ordered[p95_index], 3),
                    "max_observed_parallelism": max(observed),
                    "max_global_violation_count": max(violation_counts),
                    "joint_incident_group_verified": all(joint_verified),
                    "subproblem_limit": request.max_subproblem_operations,
                    "p95_first_feasible_ms": round(
                        ordered_first_feasible[first_feasible_p95_index], 3
                    )
                    if ordered_first_feasible
                    else float("inf"),
                    "all_incumbents_validated": bool(validated_incumbents)
                    and all(validated_incumbents),
                    "warm_start_verified": bool(warm_start_hints)
                    and all(warm_start_hints),
                    "min_pareto_front_size": min(pareto_front_sizes)
                    if pareto_front_sizes
                    else 0,
                    "alns_attempt_count": sum(alns_attempts),
                    "evidence_fingerprints": fingerprints,
                    "evidence_scope": "digital_twin",
                }
            )
        return results

    @staticmethod
    def _run_constraint_gate(factory, executor) -> dict[str, Any]:
        snapshot = factory.build_snapshot(80)
        first, second = snapshot.work_orders[0].operations[:2]
        raw = dict(snapshot.raw_data or {})
        raw.update(
            {
                "transport_lanes": [
                    {
                        "lane_id": "DT-AMR-1",
                        "predecessor_operation_id": first.operation_id,
                        "successor_operation_id": second.operation_id,
                        "capacity": 1,
                        "eta_minutes": 1,
                    }
                ],
                "buffer_flows": [
                    {
                        "buffer_id": "DT-BUF-1",
                        "predecessor_operation_id": first.operation_id,
                        "successor_operation_id": second.operation_id,
                        "capacity": 4,
                        "current_wip": 0,
                        "occupancy_quantity": 1,
                    }
                ],
                "material_availability": [
                    {
                        "material_id": "DT-MAT-1",
                        "operation_ids": [first.operation_id],
                        "available_quantity": 0,
                        "required_quantity": 1,
                    }
                ],
                "substitute_material_approvals": [
                    {
                        "primary_material_id": "DT-MAT-1",
                        "substitute_material_id": "DT-MAT-2",
                        "operation_ids": [first.operation_id],
                        "approval_status": "approved",
                        "available_quantity": 10,
                        "required_quantity": 1,
                        "available_at": snapshot.captured_at.isoformat(),
                        "approved_by": "digital-twin-quality",
                        "source_ref": "digital-twin:qms:substitute",
                    }
                ],
                "outsourcing_approvals": [
                    {
                        "vendor_id": "DT-VENDOR",
                        "operation_ids": [first.operation_id],
                        "lead_time_minutes": 30,
                        "capacity_per_day": 2,
                        "approval_status": "approved",
                        "approved_by": "digital-twin-manager",
                        "source_ref": "digital-twin:erp:outsource",
                        "capability_codes": ["flex_process"],
                    }
                ],
                "batch_genealogy": [
                    {
                        "batch_id": "DT-LOT-1",
                        "operation_ids": [second.operation_id],
                        "parent_operation_ids": [first.operation_id],
                        "quality_state": "released",
                        "release_at": snapshot.captured_at.isoformat(),
                        "source_ref": "digital-twin:qms:lot",
                    }
                ],
                "qms_release_gates": [
                    {
                        "gate_id": "DT-QMS-1",
                        "operation_ids": [second.operation_id],
                        "status": "released",
                        "release_at": snapshot.captured_at.isoformat(),
                        "required_approvals": ["quality_manager"],
                        "approvals": ["quality_manager"],
                        "certificate_ref": "DT-CERT-1",
                        "source_ref": "digital-twin:qms:gate",
                    }
                ],
            }
        )
        snapshot = snapshot.model_copy(update={"raw_data": raw}, deep=True)
        incident = RuntimeIncident(
            incident_id="DT-CONSTRAINT-1",
            incident_type="quality_exception",
            affected_operation_ids=[first.operation_id],
            delay_minutes=1,
            resource_id=first.resource_id,
            work_order_id=first.work_order_id,
        )
        request = DecompositionExecutionRequest(
            tenant_id="digital-twin",
            snapshot=snapshot,
            incidents=[incident],
            max_subproblem_operations=24,
            max_parallelism=1,
        )
        feasible = executor.execute(request)
        blocked_raw = dict(raw)
        blocked_raw["qms_release_gates"] = [
            {**raw["qms_release_gates"][0], "status": "pending", "approvals": []}
        ]
        blocked = executor.execute(
            request.model_copy(
                update={
                    "snapshot": snapshot.model_copy(
                        update={"raw_data": blocked_raw}, deep=True
                    )
                },
                deep=True,
            )
        )
        required_checks = {
            "transport_amr_capacity",
            "buffer_capacity",
            "outsourcing_approval_capacity",
            "substitute_material_approval",
            "batch_genealogy",
            "qms_release",
        }
        return {
            "status": "pass"
            if feasible.status == "feasible"
            and required_checks.issubset(set(feasible.checked_constraints))
            and blocked.status == "blocked"
            else "fail",
            "feasible_status": feasible.status,
            "pending_qms_status": blocked.status,
            "checked_constraints": feasible.checked_constraints,
            "required_checks": sorted(required_checks),
            "fail_closed_blockers": blocked.blockers,
        }

    @staticmethod
    def _run_feasibility_restoration_gate(factory) -> dict[str, Any]:
        snapshot = factory.build_snapshot(24)
        operation = snapshot.work_orders[0].operations[0]
        raw = copy.deepcopy(snapshot.raw_data or {})
        raw["operation_release_constraints"] = [
            {
                "operation_id": operation.operation_id,
                "release_at": (snapshot.captured_at + timedelta(minutes=30)).isoformat(),
                "source_ref": "digital-twin:mes:release",
            }
        ]
        raw["operation_deadline_constraints"] = [
            {
                "operation_id": operation.operation_id,
                "deadline_at": (snapshot.captured_at + timedelta(minutes=31)).isoformat(),
                "relaxable": True,
                "source_ref": "digital-twin:aps:deadline",
            }
        ]
        snapshot = snapshot.model_copy(update={"raw_data": raw}, deep=True)
        affected = AffectedOperation(
            operation_id=operation.operation_id,
            work_order_id=operation.work_order_id,
            resource_id=operation.resource_id,
            is_direct=True,
            estimated_delay_minutes=0,
        )
        impact = ImpactReport(
            incident_id=uuid4(),
            schedule_snapshot_id=snapshot.snapshot_id,
            analysis_reference_time=snapshot.captured_at,
            affected_operations=[affected],
            affected_resource_ids=[operation.resource_id],
        )
        policy = conservative_default_recovery_policy()
        request = FeasibilityRestorationRequest(
            tenant_id="digital-twin",
            snapshot=snapshot,
            impact_report=impact,
            strategy_type=StrategyType.GLOBAL_RESCHEDULE,
            timeout_seconds=10,
            policy=policy,
        )
        engine = FeasibilityRestorationEngine()
        pending = engine.evaluate(request)
        deadline_action = next(
            action
            for pack in pending.recovery_packs
            for action in pack.actions
            if action.action_type == "relax_operation_deadline"
        )
        approvals = [
            RecoveryApprovalAttestation(
                action_id=deadline_action.action_id,
                policy_id=policy.policy_id,
                policy_version=policy.version,
                approver_id=f"digital-twin-{role}",
                approver_role=role,
                source_ref=f"digital-twin:approval:{role}",
            )
            for role in deadline_action.required_approval_roles
        ]
        approved = engine.evaluate(
            request.model_copy(update={"approvals": approvals})
        )

        blocked_raw = copy.deepcopy(raw)
        blocked_raw["qms_release_gates"] = [
            {
                "gate_id": "DT-RESTORE-QMS",
                "operation_ids": [operation.operation_id],
                "status": "pending",
                "source_ref": "digital-twin:qms:gate",
            }
        ]
        blocked_snapshot = snapshot.model_copy(
            update={"raw_data": blocked_raw}, deep=True
        )
        blocked = engine.evaluate(
            request.model_copy(
                update={
                    "snapshot": blocked_snapshot,
                    "impact_report": impact.model_copy(
                        update={"schedule_snapshot_id": blocked_snapshot.snapshot_id}
                    ),
                },
                deep=True,
            )
        )
        certificate = (
            approved.recovery_packs[0].feasibility_certificate
            if approved.recovery_packs
            else None
        )
        passed = (
            pending.status == "pending_approval"
            and all(
                pack.executable_schedule is None for pack in pending.recovery_packs
            )
            and approved.status == "recovery_available"
            and certificate is not None
            and certificate.hard_violation_count == 0
            and not certificate.writeback_authorized
            and blocked.status == "blocked"
            and blocked.classification.failure_class
            == "data_or_governance_blocked"
            and not blocked.recovery_packs
        )
        return {
            "status": "pass" if passed else "fail",
            "pending_pack_count": len(pending.recovery_packs),
            "approved_certificate_fingerprint": (
                certificate.certificate_fingerprint if certificate else None
            ),
            "approved_hard_violation_count": (
                certificate.hard_violation_count if certificate else None
            ),
            "writeback_authorized": (
                certificate.writeback_authorized if certificate else None
            ),
            "qms_block_status": blocked.status,
            "qms_relaxation_search_entered": bool(blocked.recovery_packs),
        }

    @staticmethod
    def _run_cdc_gate(store: RelationalOperationalStore) -> dict[str, Any]:
        service = CdcConsistencyService(store)
        as_of = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)

        def event(source: str, sequence: int) -> CdcEvent:
            return CdcEvent(
                event_id=f"{source}-{sequence}",
                tenant_id="digital-twin",
                source_system=source,
                sequence=sequence,
                occurred_at=as_of,
                entity_type="schedule_state",
                entity_id=f"{source}-{sequence}",
                payload={"sequence": sequence, "source": source},
            )

        gap = service.ingest(event("ERP", 2))
        resumed = service.ingest(event("ERP", 1))
        for source in ("MES", "QMS"):
            service.ingest(event(source, 1))
        snapshot = service.materialize_as_of(
            AsOfSnapshotRequest(
                tenant_id="digital-twin",
                required_sources=["ERP", "MES", "QMS"],
                as_of=as_of,
            )
        )
        duplicate = service.ingest(event("ERP", 1))
        return {
            "status": "pass"
            if gap.status == "gap_buffered"
            and resumed.committed_sequence == 2
            and snapshot.status == "consistent"
            and duplicate.status == "duplicate"
            else "fail",
            "gap_status": gap.status,
            "resumed_sequence": resumed.committed_sequence,
            "asof_status": snapshot.status,
            "duplicate_status": duplicate.status,
            "snapshot_fingerprint": snapshot.snapshot_fingerprint,
        }

    @staticmethod
    def _run_queue_gate(store, factory, executor) -> dict[str, Any]:
        queue = DurableSolveQueue(
            store,
            default_quota=TenantSolveQuota(
                max_queued_jobs=10,
                max_running_jobs=1,
                max_operations_per_job=1000,
            ),
        )
        solve_request = factory.build_solve_request(
            200, tenant_id="digital-twin", incident_count=5
        )
        submit = SolveJobSubmitRequest(
            tenant_id="digital-twin",
            idempotency_key="validation-job-1",
            solve_request=solve_request,
        )
        first, created = queue.submit(submit)
        same, duplicate_created = queue.submit(submit)
        completed = SolveJobWorker(queue, worker_id="worker-a").run_once().job

        resume_job, _ = queue.submit(
            submit.model_copy(update={"idempotency_key": "validation-job-resume"})
        )
        lease = queue.claim("worker-crashed", lease_seconds=3)
        exclusive = queue.claim("worker-b") is None
        actual = executor.execute(solve_request)
        checkpoint_saved = False
        if lease and actual.subproblem_results:
            item = actual.subproblem_results[0]
            checkpoint_saved = store.save_job_checkpoint(
                lease.job_id,
                "worker-crashed",
                item.subproblem_id,
                item.model_dump(mode="json"),
            )
        recovered = store.recover_expired_leases(
            datetime.now(tz=timezone.utc) + timedelta(seconds=5)
        )
        resumed = SolveJobWorker(queue, worker_id="worker-b").run_once().job
        reused = bool(
            resumed
            and resumed.result
            and any(
                item.status == "checkpoint_reused"
                for item in resumed.result.subproblem_results
            )
        )
        cancelled_job, _ = queue.submit(
            submit.model_copy(update={"idempotency_key": "validation-job-cancel"})
        )
        cancelled = queue.cancel(cancelled_job.job_id)
        return {
            "status": "pass"
            if created
            and not duplicate_created
            and first.job_id == same.job_id
            and completed
            and completed.status == "completed"
            and exclusive
            and checkpoint_saved
            and recovered >= 1
            and resumed
            and resumed.status == "completed"
            and reused
            and cancelled
            and cancelled.status == "cancelled"
            else "fail",
            "idempotency_verified": first.job_id == same.job_id,
            "completed_status": completed.status if completed else None,
            "exclusive_lease_verified": exclusive,
            "expired_lease_recovered": recovered,
            "checkpoint_reused": reused,
            "queued_cancel_status": cancelled.status if cancelled else None,
            "tenant_max_running": 1,
        }

    @staticmethod
    def _run_sso_gate() -> dict[str, Any]:
        now = int(time.time())
        secret = "digital-twin-oidc-verification-secret"
        verifier = OIDCTokenVerifier(
            issuer="https://idp.digital-twin.example",
            audience="reorch",
            algorithms=["HS256"],
            role_claim="roles",
            tenant_claim="tenant_id",
            role_mapping={"planner": "Planner"},
            verification_key=secret,
        )
        claims = {
            "iss": "https://idp.digital-twin.example",
            "aud": "reorch",
            "sub": "planner-1",
            "iat": now,
            "exp": now + 300,
            "roles": ["planner"],
            "tenant_id": "digital-twin",
            "preferred_username": "planner",
        }
        token = jwt.encode(claims, secret, algorithm="HS256")
        principal = verifier.verify(token)
        rejected = False
        try:
            verifier.verify(
                jwt.encode({**claims, "aud": "wrong"}, secret, algorithm="HS256")
            )
        except OIDCVerificationError:
            rejected = True
        return {
            "status": "pass"
            if principal.role == "Planner"
            and principal.tenant_id == "digital-twin"
            and rejected
            else "fail",
            "signature_verified": True,
            "issuer_audience_verified": rejected,
            "role": principal.role,
            "tenant_id": principal.tenant_id,
            "customer_idp_configured": False,
        }

    @staticmethod
    def _run_shadow_gate(store, factory) -> dict[str, Any]:
        runner = ReadOnlyShadowRunner(store)
        solve_request = factory.build_solve_request(
            120, tenant_id="digital-twin", incident_count=3
        )
        shadow = runner.run(
            ReadOnlyShadowRunRequest(
                tenant_id="digital-twin",
                evidence_scope="digital_twin",
                consistent_snapshot_ref="cdc-asof:digital-twin",
                solve_request=solve_request,
                source_refs=["digital-twin:cdc:asof"],
            )
        )
        shadow = runner.record_planner_decision(
            shadow.shadow_case_id,
            planner_baseline={
                "policy": "manual_shift",
                "predicted_delay_minutes": 15,
            },
            planner_decision={
                "decision_status": "accepted",
                "planner_id": "digital-twin-planner",
            },
        )
        planned = {
            op.operation_id: op
            for wo in shadow.solve_result.final_schedule.work_orders
            for op in wo.operations
        }
        receipts = []
        for index, operation_id in enumerate(shadow.expected_terminal_operation_ids):
            operation = planned[operation_id]
            receipts.append(
                ExecutionReceipt(
                    receipt_id=f"DT-RECEIPT-{index + 1:03d}",
                    tenant_id="digital-twin",
                    shadow_case_id=shadow.shadow_case_id,
                    source_event_id=f"DT-MES-RECEIPT-{index + 1:03d}",
                    operation_id=operation_id,
                    event_type="completed",
                    observed_at=operation.end_time + timedelta(minutes=1),
                    actual_start=operation.start_time,
                    actual_end=operation.end_time + timedelta(minutes=1),
                    actual_resource_id=operation.resource_id,
                    actual_quantity=1,
                    quality_state="released",
                )
            )
        closed = runner.ingest_receipts(shadow.shadow_case_id, receipts)
        return {
            "status": "pass"
            if closed.status == "execution_closed"
            and closed.writeback_invocation_count == 0
            and closed.execution_metrics.get("execution_outcome_complete") is True
            else "fail",
            "shadow_status": closed.status,
            "writeback_invocation_count": closed.writeback_invocation_count,
            "receipt_count": len(closed.receipts),
            "execution_metrics": closed.execution_metrics,
            "evidence_fingerprint": closed.evidence_fingerprint,
        }

    @staticmethod
    def _run_rule_replay_gate() -> dict[str, Any]:
        candidate = ConstraintCandidate(
            candidate_id="DT-RULE-1",
            constraint_type="calendar",
            scope={"machine_ids": ["M4"]},
            source_text="M4 unavailable after 16:00",
            compiled_rule="avoid M4 after 16:00",
            confidence=0.9,
            source_refs=["digital-twin:planner:rule"],
        )
        scenarios = [
            {
                "scenario_id": "after-cutoff",
                "evidence_scope": "digital_twin",
                "snapshot_ref": "dt:rule:1",
                "source_refs": ["dt:mes:1"],
                "facts": {"machine_id": "M4", "operation_start_time": "17:00"},
                "expected_outcome": "avoid",
            },
            {
                "scenario_id": "before-cutoff",
                "evidence_scope": "digital_twin",
                "snapshot_ref": "dt:rule:2",
                "source_refs": ["dt:mes:2"],
                "facts": {"machine_id": "M4", "operation_start_time": "15:00"},
                "expected_outcome": "allow",
            },
            {
                "scenario_id": "other-machine",
                "evidence_scope": "digital_twin",
                "snapshot_ref": "dt:rule:3",
                "source_refs": ["dt:mes:3"],
                "facts": {"machine_id": "M5", "operation_start_time": "17:00"},
                "expected_outcome": "allow",
            },
        ]
        service = RuleCandidateReplayService()
        result = service.run(
            candidate,
            RuleCandidateReplayRequest(
                scenario_set="digital_twin_rule_gate", scenarios=scenarios
            ),
        )
        count_only = service.run(
            candidate,
            RuleCandidateReplayRequest(scenario_count=999),
        )
        return {
            "status": "pass"
            if result.pass_replay
            and len(result.scenario_results) == 3
            and all(item.result_fingerprint for item in result.scenario_results)
            and not count_only.pass_replay
            and count_only.scenario_count == 0
            else "fail",
            "executed_scenario_count": result.scenario_count,
            "passed_scenario_count": result.metrics["passed_scenario_count"],
            "count_only_request_passed": count_only.pass_replay,
            "result_fingerprints": [
                item.result_fingerprint for item in result.scenario_results
            ],
        }


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()
