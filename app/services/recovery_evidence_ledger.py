"""Recovery evidence ledger for digital-twin proxies and customer facts."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from app.models.production_runtime import (
    DecompositionExecutionRequest,
    RecoveryEvidenceCase,
    RecoveryEvidenceLedger,
    RoiCostAssumptions,
    RuntimeIncident,
)
from app.services.decomposition_executor import DecompositionExecutor
from app.services.operational_store import RelationalOperationalStore
from app.services.production_digital_twin import ProductionDigitalTwinFactory


_INCIDENT_TYPES = [
    "equipment_failure",
    "rush_order",
    "material_shortage",
    "quality_exception",
    "labor_absence",
    "tooling_conflict",
    "batch_rework",
]


class RecoveryEvidenceLedgerService:
    def __init__(
        self,
        *,
        executor: DecompositionExecutor | None = None,
        store: RelationalOperationalStore | None = None,
    ) -> None:
        self._executor = executor or DecompositionExecutor()
        self._store = store

    def build_digital_twin_ledger(
        self,
        *,
        case_count: int = 30,
        assumptions: RoiCostAssumptions | None = None,
    ) -> RecoveryEvidenceLedger:
        if not 10 <= case_count <= 30:
            raise ValueError("digital_twin_evidence_case_count_must_be_10_to_30")
        assumptions = assumptions or RoiCostAssumptions()
        factory = ProductionDigitalTwinFactory()
        snapshot = factory.build_snapshot(max(160, case_count * 8))
        selectable = [wo.operations[0] for wo in snapshot.work_orders if wo.operations]
        cases: list[RecoveryEvidenceCase] = []
        for index in range(case_count):
            operation = selectable[index % len(selectable)]
            incident_type = _INCIDENT_TYPES[index % len(_INCIDENT_TYPES)]
            incident = RuntimeIncident(
                incident_id=f"DT-EVIDENCE-{index + 1:03d}",
                incident_type=incident_type,
                affected_operation_ids=[operation.operation_id],
                delay_minutes=1 + index % 3,
                resource_id=operation.resource_id,
                work_order_id=operation.work_order_id,
                severity="P1" if index % 10 == 0 else "P2",
                occurred_at=snapshot.captured_at + timedelta(minutes=index),
            )
            solve_request = DecompositionExecutionRequest(
                tenant_id="digital-twin",
                snapshot=snapshot,
                incidents=[incident],
                max_subproblem_operations=24,
                neighborhood_hops=2,
                max_parallelism=1,
                timeout_seconds=10,
            )
            solve = self._executor.execute(solve_request)
            baseline_delay = incident.delay_minutes * 4
            system_delay = _system_delay_minutes(snapshot, solve.final_schedule, operation.work_order_id)
            planner_minutes_before = 18 + index % 8
            planner_minutes_after = 5 + index % 3
            planner_baseline = {
                "policy": "manual_shift_and_resource_check",
                "predicted_delay_minutes": baseline_delay,
                "planner_minutes": planner_minutes_before,
                "baseline_ref": f"digital-twin:planner-baseline:{index + 1:03d}",
                "provenance": "deterministic_proxy",
            }
            system_recovery = {
                "solve_status": solve.status,
                "predicted_delay_minutes": system_delay,
                "planner_review_minutes": planner_minutes_after,
                "adjusted_operation_count": sum(
                    item.adjusted_operation_count for item in solve.subproblem_results
                ),
                "solve_elapsed_ms": round(solve.elapsed_ms, 3),
                "solve_fingerprint": solve.evidence_fingerprint,
            }
            planner_decision = {
                "decision_status": "accepted" if solve.status == "feasible" else "rejected",
                "planner_id": "digital-twin-planner",
                "decided_at": (
                    snapshot.captured_at + timedelta(minutes=index + 1)
                ).isoformat(),
                "override_reason": None,
                "provenance": "simulated",
            }
            execution_deviation = (index % 3) - 1
            execution_outcome = {
                "status": "completed" if solve.status == "feasible" else "blocked",
                "actual_delay_minutes": max(0.0, system_delay + execution_deviation),
                "source_event_ids": [f"DT-MES-{index + 1:03d}"],
                "quality_state": "released",
                "provenance": "digital_twin_execution",
            }
            roi = _proxy_roi(
                incident_type=incident_type,
                baseline_delay=baseline_delay,
                actual_delay=float(execution_outcome["actual_delay_minutes"]),
                planner_minutes_before=planner_minutes_before,
                planner_minutes_after=planner_minutes_after,
                assumptions=assumptions,
            )
            payload = {
                "incident": incident.model_dump(mode="json"),
                "planner_baseline": planner_baseline,
                "system_recovery": system_recovery,
                "planner_decision": planner_decision,
                "execution_outcome": execution_outcome,
                "roi": roi,
            }
            case = RecoveryEvidenceCase(
                case_id=f"DT-CASE-{index + 1:03d}",
                evidence_scope="digital_twin",
                source_refs=[
                    f"digital-twin:snapshot:{snapshot.snapshot_id}",
                    f"digital-twin:mes:DT-MES-{index + 1:03d}",
                    f"digital-twin:planner:{index + 1:03d}",
                ],
                incident=incident,
                planner_baseline=planner_baseline,
                system_recovery=system_recovery,
                planner_decision=planner_decision,
                execution_outcome=execution_outcome,
                assumptions=assumptions,
                roi=roi,
                evidence_fingerprint=_fingerprint(payload),
            )
            cases.append(case)
            self._persist_case(case)
        return self._build_ledger(cases, "digital_twin")

    def build_customer_ledger(
        self,
        rows: list[dict[str, Any]],
    ) -> RecoveryEvidenceLedger:
        cases: list[RecoveryEvidenceCase] = []
        for row in rows:
            values = dict(row)
            scope = str(values.pop("evidence_scope", "customer_historical"))
            values.pop("evidence_fingerprint", None)
            baseline = values.get("planner_baseline", {})
            outcome = values.get("execution_outcome", {})
            roi = dict(values.get("roi", {}) or {})
            if not roi and baseline.get("baseline_loss_amount") is not None and outcome.get(
                "actual_loss_amount"
            ) is not None:
                baseline_loss = float(baseline["baseline_loss_amount"])
                actual_loss = float(outcome["actual_loss_amount"])
                roi = {
                    "baseline_loss": baseline_loss,
                    "actual_loss": actual_loss,
                    "gross_benefit": round(max(0.0, baseline_loss - actual_loss), 2),
                    "currency": str(baseline.get("currency", "CNY")),
                    "is_proxy": False,
                }
                values["roi"] = roi
            payload = {
                key: values.get(key)
                for key in (
                    "incident",
                    "planner_baseline",
                    "system_recovery",
                    "planner_decision",
                    "execution_outcome",
                    "roi",
                )
            }
            case = RecoveryEvidenceCase(
                **values,
                evidence_scope=scope,
                evidence_fingerprint=_fingerprint(payload),
            )
            cases.append(case)
            self._persist_case(case)
        scope = cases[0].evidence_scope if cases else "customer_historical"
        return self._build_ledger(cases, scope)

    def _build_ledger(
        self,
        cases: list[RecoveryEvidenceCase],
        evidence_scope: str,
    ) -> RecoveryEvidenceLedger:
        blockers = _customer_evidence_blockers(cases)
        customer_gate = not blockers and evidence_scope != "digital_twin"
        aggregate = {
            "total_baseline_loss": round(
                sum(float(case.roi.get("baseline_loss", 0)) for case in cases), 2
            ),
            "total_actual_loss": round(
                sum(float(case.roi.get("actual_loss", 0)) for case in cases), 2
            ),
            "total_gross_benefit": round(
                sum(float(case.roi.get("gross_benefit", 0)) for case in cases), 2
            ),
            "average_benefit_per_case": round(
                sum(float(case.roi.get("gross_benefit", 0)) for case in cases)
                / max(1, len(cases)),
                2,
            ),
            "currency": "CNY",
        }
        payload = {
            "scope": evidence_scope,
            "case_fingerprints": [case.evidence_fingerprint for case in cases],
            "aggregate": aggregate,
            "blockers": blockers,
        }
        ledger = RecoveryEvidenceLedger(
            evidence_scope=evidence_scope,
            cases=cases,
            case_count=len(cases),
            planner_baseline_complete=all(bool(case.planner_baseline) for case in cases),
            execution_outcome_complete=all(bool(case.execution_outcome) for case in cases),
            roi_is_proxy=evidence_scope == "digital_twin",
            customer_evidence_gate_passed=customer_gate,
            aggregate_roi=aggregate,
            blockers=blockers,
            ledger_fingerprint=_fingerprint(payload),
            claim_boundary=(
                "Digital-twin ROI is an assumption-driven proxy and cannot prove customer ROI."
                if evidence_scope == "digital_twin"
                else "Customer ROI is accepted only when planner baseline, execution outcome, cost fields, and provenance all pass the evidence gate."
            ),
        )
        if self._store is not None:
            self._store.put_evidence(
                evidence_id=ledger.ledger_id,
                tenant_id="digital-twin" if evidence_scope == "digital_twin" else "customer",
                evidence_type="recovery_evidence_ledger",
                evidence_scope=evidence_scope,
                payload=ledger.model_dump(mode="json"),
                fingerprint=ledger.ledger_fingerprint,
            )
        return ledger

    def _persist_case(self, case: RecoveryEvidenceCase) -> None:
        if self._store is None:
            return
        self._store.put_evidence(
            evidence_id=case.case_id,
            tenant_id="digital-twin" if case.evidence_scope == "digital_twin" else "customer",
            evidence_type="recovery_evidence_case",
            evidence_scope=case.evidence_scope,
            payload=case.model_dump(mode="json"),
            fingerprint=case.evidence_fingerprint,
        )


def _system_delay_minutes(snapshot, schedule, work_order_id: str) -> float:
    if schedule is None:
        return 1_000_000.0
    baseline = {
        op.operation_id: op
        for wo in snapshot.work_orders
        for op in wo.operations
        if wo.work_order_id == work_order_id
    }
    recovered = {
        op.operation_id: op
        for wo in schedule.work_orders
        for op in wo.operations
        if wo.work_order_id == work_order_id
    }
    return round(
        sum(
            max(0.0, (recovered[op_id].end_time - op.end_time).total_seconds() / 60)
            for op_id, op in baseline.items()
            if op_id in recovered
        ),
        3,
    )


def _proxy_roi(
    *,
    incident_type: str,
    baseline_delay: float,
    actual_delay: float,
    planner_minutes_before: float,
    planner_minutes_after: float,
    assumptions: RoiCostAssumptions,
) -> dict[str, float | str | bool]:
    baseline_loss = baseline_delay * assumptions.delay_cost_per_minute
    actual_loss = actual_delay * assumptions.delay_cost_per_minute
    planner_saving = max(0.0, planner_minutes_before - planner_minutes_after) * (
        assumptions.planner_cost_per_minute
    )
    overtime_saving = max(0.0, baseline_delay - actual_delay) * 0.25 * (
        assumptions.overtime_cost_per_minute
    )
    avoided_scrap = (
        assumptions.scrap_cost_per_case * 0.2
        if incident_type in {"quality_exception", "batch_rework"}
        else 0.0
    )
    gross = max(0.0, baseline_loss - actual_loss) + planner_saving + overtime_saving + avoided_scrap
    return {
        "baseline_loss": round(baseline_loss, 2),
        "actual_loss": round(actual_loss, 2),
        "planner_time_benefit": round(planner_saving, 2),
        "overtime_benefit": round(overtime_saving, 2),
        "avoided_scrap_proxy": round(avoided_scrap, 2),
        "gross_benefit": round(gross, 2),
        "currency": "CNY",
        "is_proxy": True,
    }


def _customer_evidence_blockers(cases: list[RecoveryEvidenceCase]) -> list[str]:
    blockers: list[str] = []
    if cases and all(case.evidence_scope == "digital_twin" for case in cases):
        return [
            "real_customer_cases_required",
            "planner_baseline_and_mes_outcomes_must_come_from_customer_systems",
        ]
    if not 10 <= len(cases) <= 30:
        blockers.append("customer_case_count_must_be_10_to_30")
    if len({case.case_id for case in cases}) != len(cases):
        blockers.append("duplicate_customer_case_ids")
    if any(case.evidence_scope == "digital_twin" for case in cases):
        blockers.append("digital_twin_cases_do_not_pass_customer_evidence_gate")
    for case in cases:
        if any(ref.startswith("digital-twin:") for ref in case.source_refs):
            blockers.append(f"synthetic_source_ref:{case.case_id}")
        baseline = case.planner_baseline
        if not baseline.get("baseline_decision_ref") or not baseline.get(
            "provenance_confirmed"
        ):
            blockers.append(f"planner_baseline_provenance_missing:{case.case_id}")
        if baseline.get("baseline_loss_amount") is None:
            blockers.append(f"baseline_loss_missing:{case.case_id}")
        decision = case.planner_decision
        if not decision.get("planner_id") or not decision.get("decided_at"):
            blockers.append(f"planner_decision_evidence_missing:{case.case_id}")
        outcome = case.execution_outcome
        if not outcome.get("source_event_ids") or outcome.get("actual_loss_amount") is None:
            blockers.append(f"execution_outcome_evidence_missing:{case.case_id}")
    return sorted(set(blockers))


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()
