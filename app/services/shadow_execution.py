"""Read-only shadow execution and MES receipt reconciliation."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from app.models.production_runtime import (
    ExecutionReceipt,
    ReadOnlyShadowRunRequest,
    ShadowExecutionStatus,
)
from app.services.decomposition_executor import DecompositionExecutor
from app.services.operational_store import RelationalOperationalStore


class ReadOnlyShadowRunner:
    """Generate advice and close evidence from observed MES events only."""

    def __init__(
        self,
        store: RelationalOperationalStore,
        executor: DecompositionExecutor | None = None,
    ) -> None:
        self._store = store
        self._executor = executor or DecompositionExecutor()

    def run(self, request: ReadOnlyShadowRunRequest) -> ShadowExecutionStatus:
        result = self._executor.execute(request.solve_request)
        shadow_case_id = f"shadow-{uuid4().hex}"
        expected = []
        if result.final_schedule:
            expected = [
                op.operation_id
                for wo in result.final_schedule.work_orders
                for op in wo.operations
                if op.is_adjusted or op.is_affected
            ]
        if not expected:
            expected = sorted(
                {
                    op_id
                    for incident in request.solve_request.incidents
                    for op_id in incident.affected_operation_ids
                }
            )
        status = "recommendation_ready" if result.status == "feasible" else "blocked"
        blockers = list(result.blockers)
        payload = {
            "shadow_case_id": shadow_case_id,
            "tenant_id": request.tenant_id,
            "evidence_scope": request.evidence_scope,
            "consistent_snapshot_ref": request.consistent_snapshot_ref,
            "source_refs": request.source_refs,
            "solve_fingerprint": result.evidence_fingerprint,
            "expected": expected,
            "status": status,
            "writeback_invocation_count": 0,
        }
        record = ShadowExecutionStatus(
            shadow_case_id=shadow_case_id,
            tenant_id=request.tenant_id,
            evidence_scope=request.evidence_scope,
            status=status,
            advisory_only=True,
            writeback_invocation_count=0,
            solve_result=result,
            expected_terminal_operation_ids=expected,
            blockers=blockers,
            evidence_fingerprint=_fingerprint(payload),
        )
        self._store.upsert_shadow_case(
            record, request.tenant_id, request.evidence_scope
        )
        return record

    def record_planner_decision(
        self,
        shadow_case_id: str,
        *,
        planner_baseline: dict[str, Any],
        planner_decision: dict[str, Any],
    ) -> ShadowExecutionStatus:
        record = self._require_case(shadow_case_id)
        if record.status == "blocked":
            raise ValueError("blocked_shadow_case_cannot_enter_execution")
        decision_status = str(planner_decision.get("decision_status", ""))
        if decision_status not in {"accepted", "adjusted", "rejected"}:
            raise ValueError("invalid_planner_shadow_decision")
        if decision_status in {"adjusted", "rejected"} and not (
            planner_decision.get("override_reason")
            or planner_decision.get("tweak_summary")
        ):
            raise ValueError("planner_override_reason_required")
        updated = record.model_copy(
            update={
                "status": "awaiting_execution",
                "planner_baseline": planner_baseline,
                "planner_decision": planner_decision,
                "evidence_fingerprint": _fingerprint(
                    {
                        "previous": record.evidence_fingerprint,
                        "planner_baseline": planner_baseline,
                        "planner_decision": planner_decision,
                    }
                ),
            },
            deep=True,
        )
        self._store.upsert_shadow_case(
            updated, updated.tenant_id, updated.evidence_scope
        )
        return updated

    def ingest_receipts(
        self,
        shadow_case_id: str,
        receipts: list[ExecutionReceipt],
    ) -> ShadowExecutionStatus:
        record = self._require_case(shadow_case_id)
        if record.status not in {"awaiting_execution", "execution_closed"}:
            raise ValueError("planner_decision_required_before_execution_receipts")
        for receipt in receipts:
            if receipt.shadow_case_id != shadow_case_id:
                raise ValueError("receipt_shadow_case_mismatch")
            if receipt.tenant_id != record.tenant_id:
                raise ValueError("receipt_tenant_mismatch")
            self._store.add_execution_receipt(receipt)
        all_receipts = self._store.list_execution_receipts(shadow_case_id)
        metrics = _execution_metrics(record, all_receipts)
        terminal_ids = {
            receipt.operation_id
            for receipt in all_receipts
            if receipt.event_type in {"completed", "rejected", "blocked", "rework"}
        }
        expected = set(record.expected_terminal_operation_ids)
        closed = bool(expected) and expected.issubset(terminal_ids)
        updated = record.model_copy(
            update={
                "status": "execution_closed" if closed else "awaiting_execution",
                "receipts": all_receipts,
                "execution_metrics": metrics,
                "evidence_fingerprint": _fingerprint(
                    {
                        "previous": record.evidence_fingerprint,
                        "receipt_ids": [item.receipt_id for item in all_receipts],
                        "metrics": metrics,
                        "closed": closed,
                    }
                ),
            },
            deep=True,
        )
        self._store.upsert_shadow_case(
            updated, updated.tenant_id, updated.evidence_scope
        )
        if closed:
            self._store.put_evidence(
                evidence_id=f"shadow-execution:{shadow_case_id}",
                tenant_id=updated.tenant_id,
                evidence_type="shadow_execution_closure",
                evidence_scope=updated.evidence_scope,
                payload=updated.model_dump(mode="json"),
                fingerprint=updated.evidence_fingerprint,
            )
        return updated

    def get(self, shadow_case_id: str) -> ShadowExecutionStatus | None:
        return self._store.get_shadow_case(shadow_case_id)

    def _require_case(self, shadow_case_id: str) -> ShadowExecutionStatus:
        record = self.get(shadow_case_id)
        if record is None:
            raise KeyError(f"shadow_case_not_found:{shadow_case_id}")
        return record


def _execution_metrics(
    record: ShadowExecutionStatus,
    receipts: list[ExecutionReceipt],
) -> dict[str, float | int | str | bool]:
    planned = {}
    if record.solve_result and record.solve_result.final_schedule:
        planned = {
            op.operation_id: op
            for wo in record.solve_result.final_schedule.work_orders
            for op in wo.operations
        }
    terminal = [
        item
        for item in receipts
        if item.event_type in {"completed", "rejected", "blocked", "rework"}
    ]
    completed = [item for item in terminal if item.event_type == "completed"]
    deviations: list[float] = []
    resource_matches = 0
    comparable_resources = 0
    for item in completed:
        planned_op = planned.get(item.operation_id)
        if planned_op and item.actual_end:
            deviations.append((item.actual_end - planned_op.end_time).total_seconds() / 60)
        if planned_op and item.actual_resource_id:
            comparable_resources += 1
            resource_matches += int(item.actual_resource_id == planned_op.resource_id)
    return {
        "receipt_count": len(receipts),
        "terminal_operation_count": len({item.operation_id for item in terminal}),
        "completed_operation_count": len({item.operation_id for item in completed}),
        "rejected_or_blocked_count": len(terminal) - len(completed),
        "average_end_deviation_minutes": (
            round(sum(deviations) / len(deviations), 3) if deviations else 0.0
        ),
        "resource_adherence_rate": (
            round(resource_matches / comparable_resources, 4)
            if comparable_resources
            else 0.0
        ),
        "execution_outcome_complete": bool(record.expected_terminal_operation_ids)
        and set(record.expected_terminal_operation_ids).issubset(
            {item.operation_id for item in terminal}
        ),
        "writeback_invocation_count": 0,
    }


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
