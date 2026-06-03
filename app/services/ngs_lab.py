"""NGS lab protected repair portfolio service."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.models.ngs import (
    NgsAgentTraceStep,
    NgsBatchReplayResponse,
    NgsEntity,
    NgsGateIssue,
    NgsImpactReport,
    NgsLabDemoResponse,
    NgsLabEvent,
    NgsLabSnapshot,
    NgsOperation,
    NgsPool,
    NgsQualityGateReport,
    NgsReagentLot,
    NgsRepairAction,
    NgsRepairCandidate,
    NgsReplayCaseResult,
    NgsResource,
    NgsResourceWindow,
    NgsRun,
    NgsSample,
)


REQUIRED_STAGES = (
    "receipt",
    "extraction",
    "library",
    "qc",
    "pooling",
    "sequencing",
    "analysis",
    "report",
)

DEFAULT_NGS_EXPERIMENT_PACKAGE = (
    Path(__file__).resolve().parents[2]
    / "demo"
    / "data"
    / "ngs_lab_experiment_package.json"
)


class NgsFeasibilityGateValidator:
    """Protected feasibility gates for NGS repair candidates."""

    def validate(
        self,
        *,
        snapshot: NgsLabSnapshot,
        candidate: NgsRepairCandidate,
    ) -> NgsQualityGateReport:
        blockers: list[NgsGateIssue] = []
        warnings: list[NgsGateIssue] = []
        operations = candidate.operations
        pools = candidate.pools
        runs = candidate.runs

        blockers.extend(_reference_closure(snapshot.samples, operations))
        blockers.extend(_precedence_issues(operations))
        blockers.extend(_qc_route_issues(operations))
        blockers.extend(_reagent_issues(snapshot.reagents, snapshot.samples, operations))
        blockers.extend(_hold_time_issues(snapshot.samples, operations))
        blockers.extend(_pool_run_issues(pools, runs))
        blockers.extend(_index_issues(pools))
        blockers.extend(_resource_calendar_issues(snapshot.resource_calendar, operations, runs))
        blockers.extend(_frozen_zone_issues(snapshot.operations, operations))
        blockers.extend(_zone_issues(snapshot.resources, operations))
        blockers.extend(_traceability_issues(candidate))

        burden_threshold = 4
        if candidate.rescue_burden >= burden_threshold:
            warnings.append(
                NgsGateIssue(
                    gate="rescue_burden",
                    severity="warning",
                    entity_type="candidate",
                    entity_id=candidate.candidate_id,
                    message=(
                        f"Rescue burden {candidate.rescue_burden} is high; "
                        "planner confirmation is required."
                    ),
                    source_refs=[f"candidate:{candidate.candidate_id}:repair_actions"],
                )
            )

        gate_summary = {
            "reference_closure": _gate_status(blockers, "reference_closure"),
            "precedence_dag": _gate_status(blockers, "precedence_dag"),
            "qc_route_safety": _gate_status(blockers, "qc_route_safety"),
            "reagent_validity": _gate_status(blockers, "reagent_validity"),
            "hold_time": _gate_status(blockers, "hold_time"),
            "pool_run": _gate_status(blockers, "pool_run"),
            "index_compatibility": _gate_status(blockers, "index_compatibility"),
            "resource_calendar": _gate_status(blockers, "resource_calendar"),
            "frozen_zone": _gate_status(blockers, "frozen_zone"),
            "zone_compatibility": _gate_status(blockers, "zone_compatibility"),
            "traceability": _gate_status(blockers, "traceability"),
        }
        return NgsQualityGateReport(
            candidate_id=candidate.candidate_id,
            pass_gate=not blockers,
            confidence_level="high" if not blockers and not warnings else "medium",
            hard_blockers=blockers,
            warnings=warnings,
            gate_summary=gate_summary,
        )


class NgsProtectedPortfolioService:
    """Generate and filter protected NGS repair candidates."""

    def run_demo(self) -> NgsLabDemoResponse:
        batch = self.run_batch_replay()
        if not batch.case_results:
            raise ValueError("NGS experiment package contains no replay cases.")
        return batch.case_results[0].response

    def run_batch_replay(
        self,
        package_path: str | Path | None = None,
        package_payload: dict[str, Any] | None = None,
        source_name: str = "uploaded_package",
    ) -> NgsBatchReplayResponse:
        if package_payload is not None:
            package = _validate_experiment_package(package_payload, source_name)
            source_path = source_name
        else:
            path = Path(package_path) if package_path is not None else DEFAULT_NGS_EXPERIMENT_PACKAGE
            package = _load_experiment_package(path)
            source_path = str(path)
        case_results = [
            self._run_replay_case(package, case, source_path)
            for case in package.get("cases", [])
        ]
        return NgsBatchReplayResponse(
            package_id=str(package.get("package_id", "ngs-experiment-package")),
            package_version=str(package.get("version", "unknown")),
            source_path=source_path,
            case_results=case_results,
            aggregate_metrics=_batch_metrics(case_results),
        )

    def _run_replay_case(
        self,
        package: dict[str, Any],
        case: dict[str, Any],
        source_path: str,
    ) -> NgsReplayCaseResult:
        snapshot = _build_demo_snapshot()
        _apply_snapshot_modifiers(snapshot, case.get("modifiers", {}))
        impact = _build_impact_report(snapshot)
        raw_candidates = _build_demo_candidates(snapshot)
        _apply_candidate_metric_overrides(raw_candidates, case.get("candidate_metric_overrides", {}))

        validator = NgsFeasibilityGateValidator()
        feasible: list[NgsRepairCandidate] = []
        rejected: list[NgsRepairCandidate] = []
        for candidate in raw_candidates:
            gate_report = validator.validate(snapshot=snapshot, candidate=candidate)
            candidate.gate_report = gate_report
            candidate.hard_feasible = gate_report.pass_gate
            candidate.soft_score = _soft_score(candidate)
            candidate.explanation = _candidate_explanation(candidate)
            if gate_report.pass_gate:
                feasible.append(candidate)
            else:
                rejected.append(candidate)

        feasible.sort(key=lambda item: item.soft_score, reverse=True)
        recommended = feasible[0] if feasible else None
        agent_trace = _build_agent_trace(snapshot, impact, raw_candidates, feasible, rejected, recommended)
        case_id = str(case.get("case_id", snapshot.snapshot_id))
        scenario_id = str(case.get("scenario_id", case_id))
        expected = case.get("expected", {})
        response = NgsLabDemoResponse(
            scenario_id=scenario_id,
            replay_case_id=case_id,
            source_package_id=str(package.get("package_id", "ngs-experiment-package")),
            snapshot=snapshot,
            impact_report=impact,
            feasible_candidates=feasible,
            rejected_candidates=rejected,
            recommended_candidate=recommended,
            agent_trace=agent_trace,
            audit_package={
                **_build_audit_package(snapshot, feasible, rejected, recommended),
                "source_package_id": package.get("package_id"),
                "source_path": source_path,
                "replay_case_id": case_id,
                "expected": expected,
            },
            runbook=[
                "Load public-safe NGS experiment package and run each replay case.",
                "Compile LIMS/run/QC/reagent events into NGS lab snapshot.",
                "Run protected hard gates before soft-score comparison.",
                "Reject infeasible candidates: reagent expiry, QC route, pool/run, index, frozen-zone.",
                "Rank only hard-feasible candidates by TAT, urgent delay, rescue burden, stability.",
                "Return recommendation for lab planner confirmation; no LIMS writeback is executed.",
            ],
        )
        failure_reasons = _replay_failure_reasons(response, expected)
        return NgsReplayCaseResult(
            case_id=case_id,
            scenario_id=scenario_id,
            description=case.get("description"),
            expected_recommended_strategy=expected.get("recommended_strategy"),
            pass_replay=not failure_reasons,
            failure_reasons=failure_reasons,
            response=response,
        )


def _load_experiment_package(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        package = json.load(handle)
    return _validate_experiment_package(package, str(path))


def _validate_experiment_package(
    package: dict[str, Any],
    source_name: str,
) -> dict[str, Any]:
    cases = package.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"Invalid NGS experiment package: {source_name}")
    return package


def _apply_snapshot_modifiers(
    snapshot: NgsLabSnapshot,
    modifiers: dict[str, Any],
) -> None:
    if not modifiers:
        return

    snapshot.snapshot_id = str(modifiers.get("snapshot_id") or snapshot.snapshot_id)
    base = snapshot.captured_at

    sample_priority = modifiers.get("sample_priority", {})
    if isinstance(sample_priority, dict):
        for sample in snapshot.samples:
            if sample.sample_id in sample_priority:
                sample.priority = str(sample_priority[sample.sample_id])

    qc_status = modifiers.get("qc_status", {})
    if isinstance(qc_status, dict):
        for operation in snapshot.operations:
            if operation.stage == "qc" and operation.sample_id in qc_status:
                operation.qc_status = str(qc_status[operation.sample_id])

    reagent_overrides = modifiers.get("reagents", {})
    if isinstance(reagent_overrides, dict):
        for lot in snapshot.reagents:
            override = reagent_overrides.get(lot.lot_id)
            if not isinstance(override, dict):
                continue
            if "quantity_available" in override:
                lot.quantity_available = int(override["quantity_available"])
            if "expires_after_hours" in override:
                lot.expires_at = base + timedelta(hours=float(override["expires_after_hours"]))
            if "open_stability_hours" in override:
                lot.open_stability_hours = float(override["open_stability_hours"])

    windows = modifiers.get("resource_calendar")
    if isinstance(windows, list):
        snapshot.resource_calendar = [
            NgsResourceWindow(
                resource_id=str(window["resource_id"]),
                window_start=base + timedelta(hours=float(window["start_hour"])),
                window_end=base + timedelta(hours=float(window["end_hour"])),
                reason=str(window.get("reason", "experiment_package_window")),
            )
            for window in windows
            if isinstance(window, dict)
            and {"resource_id", "start_hour", "end_hour"}.issubset(window)
        ]


def _apply_candidate_metric_overrides(
    candidates: list[NgsRepairCandidate],
    overrides: dict[str, Any],
) -> None:
    if not isinstance(overrides, dict):
        return
    for candidate in candidates:
        values = overrides.get(candidate.candidate_id)
        if not isinstance(values, dict):
            continue
        if "weighted_tardiness_minutes" in values:
            candidate.weighted_tardiness_minutes = int(values["weighted_tardiness_minutes"])
        if "urgent_tardiness_minutes" in values:
            candidate.urgent_tardiness_minutes = int(values["urgent_tardiness_minutes"])
        if "rescue_burden" in values:
            candidate.rescue_burden = int(values["rescue_burden"])
        if "schedule_stability" in values:
            candidate.schedule_stability = float(values["schedule_stability"])


def _replay_failure_reasons(
    response: NgsLabDemoResponse,
    expected: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    min_feasible = int(expected.get("min_feasible", 0) or 0)
    min_rejected = int(expected.get("min_rejected", 0) or 0)
    expected_strategy = expected.get("recommended_strategy")
    if len(response.feasible_candidates) < min_feasible:
        reasons.append(
            f"feasible_count {len(response.feasible_candidates)} < expected {min_feasible}"
        )
    if len(response.rejected_candidates) < min_rejected:
        reasons.append(
            f"rejected_count {len(response.rejected_candidates)} < expected {min_rejected}"
        )
    recommended_strategy = (
        response.recommended_candidate.strategy_type
        if response.recommended_candidate
        else None
    )
    if expected_strategy and recommended_strategy != expected_strategy:
        reasons.append(
            f"recommended_strategy {recommended_strategy} != expected {expected_strategy}"
        )
    return reasons


def _batch_metrics(case_results: list[NgsReplayCaseResult]) -> dict[str, Any]:
    recommended_distribution: dict[str, int] = {}
    for result in case_results:
        recommended = result.response.recommended_candidate
        strategy = recommended.strategy_type if recommended else "none"
        recommended_distribution[strategy] = recommended_distribution.get(strategy, 0) + 1

    case_count = len(case_results)
    pass_count = sum(1 for result in case_results if result.pass_replay)
    return {
        "case_count": case_count,
        "pass_count": pass_count,
        "pass_rate": round(pass_count / max(case_count, 1), 4),
        "feasible_total": sum(len(result.response.feasible_candidates) for result in case_results),
        "rejected_total": sum(len(result.response.rejected_candidates) for result in case_results),
        "recommended_strategy_distribution": recommended_distribution,
    }


def _reference_closure(
    samples: list[NgsSample],
    operations: list[NgsOperation],
) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    stages_by_sample: dict[str, set[str]] = {}
    for operation in operations:
        stages_by_sample.setdefault(operation.sample_id, set()).add(operation.stage)
    for sample in samples:
        missing = sorted(set(REQUIRED_STAGES) - stages_by_sample.get(sample.sample_id, set()))
        if missing:
            issues.append(
                _issue(
                    "reference_closure",
                    "sample",
                    sample.sample_id,
                    f"Missing required stages: {', '.join(missing)}.",
                    [f"sample:{sample.sample_id}", "required_stages:ngs_p0"],
                )
            )
    return issues


def _precedence_issues(operations: list[NgsOperation]) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    by_id = {operation.operation_id: operation for operation in operations}
    graph = {operation.operation_id: list(operation.predecessor_ids) for operation in operations}
    for operation in operations:
        for predecessor_id in operation.predecessor_ids:
            predecessor = by_id.get(predecessor_id)
            if predecessor is None:
                issues.append(
                    _issue(
                        "precedence_dag",
                        "operation",
                        operation.operation_id,
                        f"Unknown predecessor {predecessor_id}.",
                        [f"operation:{operation.operation_id}"],
                    )
                )
            elif predecessor.planned_end > operation.planned_start:
                issues.append(
                    _issue(
                        "precedence_dag",
                        "operation",
                        operation.operation_id,
                        f"Predecessor {predecessor_id} ends after this operation starts.",
                        [f"operation:{predecessor_id}", f"operation:{operation.operation_id}"],
                    )
                )
    if _has_cycle(graph):
        issues.append(
            _issue(
                "precedence_dag",
                "snapshot",
                "candidate_operations",
                "Operation dependency graph contains a cycle.",
                ["candidate:operations"],
            )
        )
    return issues


def _qc_route_issues(operations: list[NgsOperation]) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    downstream = {"pooling", "sequencing", "analysis", "report"}
    qc_by_sample = {
        operation.sample_id: operation
        for operation in operations
        if operation.stage == "qc"
    }
    for operation in operations:
        qc = qc_by_sample.get(operation.sample_id)
        if (
            operation.stage in downstream
            and qc is not None
            and qc.qc_status in {"fail", "borderline"}
        ):
            issues.append(
                _issue(
                    "qc_route_safety",
                    "sample",
                    operation.sample_id,
                    (
                        f"Downstream stage {operation.stage} is scheduled while "
                        f"QC status is {qc.qc_status}."
                    ),
                    [f"operation:{qc.operation_id}", f"operation:{operation.operation_id}"],
                )
            )
    return issues


def _reagent_issues(
    reagents: list[NgsReagentLot],
    samples: list[NgsSample],
    operations: list[NgsOperation],
) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    lots = {lot.lot_id: lot for lot in reagents}
    samples_by_id = {sample.sample_id: sample for sample in samples}
    usage: dict[str, int] = {}
    for operation in operations:
        if operation.reagent_lot_id is None:
            continue
        lot = lots.get(operation.reagent_lot_id)
        if lot is None:
            issues.append(
                _issue(
                    "reagent_validity",
                    "operation",
                    operation.operation_id,
                    f"Unknown reagent lot {operation.reagent_lot_id}.",
                    [f"operation:{operation.operation_id}"],
                )
            )
            continue
        usage[lot.lot_id] = usage.get(lot.lot_id, 0) + 1
        sample = samples_by_id.get(operation.sample_id)
        if sample and sample.assay not in lot.compatible_assays:
            issues.append(
                _issue(
                    "reagent_validity",
                    "reagent",
                    lot.lot_id,
                    f"Lot is not compatible with assay {sample.assay}.",
                    [f"reagent:{lot.lot_id}", f"sample:{operation.sample_id}"],
                )
            )
        if operation.planned_start >= lot.expires_at:
            issues.append(
                _issue(
                    "reagent_validity",
                    "reagent",
                    lot.lot_id,
                    "Operation starts after reagent expiry.",
                    [f"reagent:{lot.lot_id}", f"operation:{operation.operation_id}"],
                )
            )
        if lot.opened_at and lot.open_stability_hours is not None:
            open_until = lot.opened_at + timedelta(hours=lot.open_stability_hours)
            if operation.planned_start >= open_until:
                issues.append(
                    _issue(
                        "reagent_validity",
                        "reagent",
                        lot.lot_id,
                        "Operation starts after reagent open-stability window.",
                        [f"reagent:{lot.lot_id}", f"operation:{operation.operation_id}"],
                    )
                )
    for lot_id, count in usage.items():
        lot = lots[lot_id]
        if count > lot.quantity_available:
            issues.append(
                _issue(
                    "reagent_validity",
                    "reagent",
                    lot_id,
                    f"Lot quantity {lot.quantity_available} is below planned usage {count}.",
                    [f"reagent:{lot_id}"],
                )
            )
    return issues


def _hold_time_issues(
    samples: list[NgsSample],
    operations: list[NgsOperation],
) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    samples_by_id = {sample.sample_id: sample for sample in samples}
    by_sample_stage = {
        (operation.sample_id, operation.stage): operation for operation in operations
    }
    for sample in samples:
        if sample.max_hold_minutes is None:
            continue
        extraction = by_sample_stage.get((sample.sample_id, "extraction"))
        library = by_sample_stage.get((sample.sample_id, "library"))
        if extraction and library:
            hold_minutes = int((library.planned_start - extraction.planned_end).total_seconds() / 60)
            if hold_minutes > sample.max_hold_minutes:
                issues.append(
                    _issue(
                        "hold_time",
                        "sample",
                        sample.sample_id,
                        (
                            f"Extraction-to-library hold time {hold_minutes} min exceeds "
                            f"{sample.max_hold_minutes} min."
                        ),
                        [f"sample:{sample.sample_id}", f"operation:{library.operation_id}"],
                    )
                )
    return issues


def _pool_run_issues(
    pools: list[NgsPool],
    runs: list[NgsRun],
) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    runs_by_id = {run.run_id: run for run in runs}
    for pool in pools:
        if len(pool.sample_ids) > pool.max_members:
            issues.append(
                _issue(
                    "pool_run",
                    "pool",
                    pool.pool_id,
                    f"Pool member count {len(pool.sample_ids)} exceeds max {pool.max_members}.",
                    [f"pool:{pool.pool_id}"],
                )
            )
        if pool.run_id is None or pool.run_id not in runs_by_id:
            issues.append(
                _issue(
                    "pool_run",
                    "pool",
                    pool.pool_id,
                    "Pool is not assigned to a valid sequencing run.",
                    [f"pool:{pool.pool_id}"],
                )
            )
    for run in runs:
        if len(run.pool_ids) > run.capacity_pools:
            issues.append(
                _issue(
                    "pool_run",
                    "run",
                    run.run_id,
                    f"Run has {len(run.pool_ids)} pools but capacity is {run.capacity_pools}.",
                    [f"run:{run.run_id}"],
                )
            )
    return issues


def _index_issues(pools: list[NgsPool]) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    for pool in pools:
        if len(pool.index_ids) != len(set(pool.index_ids)):
            issues.append(
                _issue(
                    "index_compatibility",
                    "pool",
                    pool.pool_id,
                    "Duplicate index ids in pool.",
                    [f"pool:{pool.pool_id}:index_ids"],
                )
            )
        if len(pool.index_ids) != len(pool.sample_ids):
            issues.append(
                _issue(
                    "index_compatibility",
                    "pool",
                    pool.pool_id,
                    "Index count does not match pool sample count.",
                    [f"pool:{pool.pool_id}:index_ids"],
                )
            )
    return issues


def _resource_calendar_issues(
    windows: list[NgsResourceWindow],
    operations: list[NgsOperation],
    runs: list[NgsRun],
) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    for window in windows:
        for operation in operations:
            if operation.resource_id == window.resource_id and _overlaps(
                operation.planned_start,
                operation.planned_end,
                window.window_start,
                window.window_end,
            ):
                issues.append(
                    _issue(
                        "resource_calendar",
                        "operation",
                        operation.operation_id,
                        f"Operation overlaps unavailable resource window: {window.reason}.",
                        [f"resource:{window.resource_id}", f"operation:{operation.operation_id}"],
                    )
                )
        for run in runs:
            if run.resource_id == window.resource_id and _overlaps(
                run.scheduled_start,
                run.scheduled_end,
                window.window_start,
                window.window_end,
            ):
                issues.append(
                    _issue(
                        "resource_calendar",
                        "run",
                        run.run_id,
                        f"Run overlaps unavailable resource window: {window.reason}.",
                        [f"resource:{window.resource_id}", f"run:{run.run_id}"],
                    )
                )
    return issues


def _frozen_zone_issues(
    baseline: list[NgsOperation],
    candidate: list[NgsOperation],
) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    baseline_by_id = {operation.operation_id: operation for operation in baseline}
    for operation in candidate:
        original = baseline_by_id.get(operation.operation_id)
        if (
            original
            and original.frozen_flag
            and (
                original.planned_start != operation.planned_start
                or original.resource_id != operation.resource_id
            )
        ):
            issues.append(
                _issue(
                    "frozen_zone",
                    "operation",
                    operation.operation_id,
                    "Frozen operation was moved or reassigned.",
                    [f"baseline_operation:{operation.operation_id}"],
                )
            )
    return issues


def _zone_issues(
    resources: list[NgsResource],
    operations: list[NgsOperation],
) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    resources_by_id = {resource.resource_id: resource for resource in resources}
    for operation in operations:
        resource = resources_by_id.get(operation.resource_id)
        if (
            operation.zone
            and resource
            and resource.zone
            and operation.zone != resource.zone
        ):
            issues.append(
                _issue(
                    "zone_compatibility",
                    "operation",
                    operation.operation_id,
                    f"Operation zone {operation.zone} does not match resource zone {resource.zone}.",
                    [f"operation:{operation.operation_id}", f"resource:{resource.resource_id}"],
                )
            )
    return issues


def _traceability_issues(candidate: NgsRepairCandidate) -> list[NgsGateIssue]:
    issues: list[NgsGateIssue] = []
    for action in candidate.repair_actions:
        if not action.source_refs:
            issues.append(
                _issue(
                    "traceability",
                    "repair_action",
                    action.target_id,
                    "Repair action is missing source refs.",
                    [f"candidate:{candidate.candidate_id}"],
                )
            )
    return issues


def _build_demo_snapshot() -> NgsLabSnapshot:
    base = datetime(2026, 5, 12, 8, 0, tzinfo=timezone.utc)
    samples = [
        NgsSample(
            sample_id="S-001",
            assay="WGS",
            priority="routine",
            arrival_time=base,
            due_time=base + timedelta(hours=48),
            risk_class="standard",
            max_hold_minutes=480,
        ),
        NgsSample(
            sample_id="S-002",
            assay="WGS",
            priority="urgent_clinical",
            arrival_time=base + timedelta(minutes=30),
            due_time=base + timedelta(hours=20),
            risk_class="urgent",
            max_hold_minutes=360,
        ),
        NgsSample(
            sample_id="S-003",
            assay="RNA",
            priority="STAT",
            arrival_time=base + timedelta(minutes=15),
            due_time=base + timedelta(hours=18),
            risk_class="perishable",
            max_hold_minutes=180,
        ),
    ]
    return NgsLabSnapshot(
        snapshot_id="ngs-snapshot-001",
        captured_at=base,
        lab_id="NGS-LAB-01",
        samples=samples,
        entities=_entities(samples),
        operations=_baseline_operations(base),
        resources=[
            NgsResource(resource_id="EXTRACT-01", resource_type="instrument", capabilities=["extraction"], zone="pre_pcr"),
            NgsResource(resource_id="LIB-01", resource_type="instrument", capabilities=["library"], zone="pre_pcr"),
            NgsResource(resource_id="QC-01", resource_type="instrument", capabilities=["qc"], zone="pre_pcr"),
            NgsResource(resource_id="POOL-01", resource_type="operator_pool", capabilities=["pooling"], zone="post_pcr"),
            NgsResource(resource_id="SEQ-01", resource_type="sequencer", capabilities=["sequencing"], zone="post_pcr"),
            NgsResource(resource_id="SEQ-02", resource_type="sequencer", capabilities=["sequencing"], zone="post_pcr"),
            NgsResource(resource_id="BIOINFO-01", resource_type="compute", capabilities=["analysis"], zone=None),
        ],
        resource_calendar=[
            NgsResourceWindow(
                resource_id="SEQ-01",
                window_start=base + timedelta(hours=7),
                window_end=base + timedelta(hours=10),
                reason="sequencer_downtime",
            )
        ],
        reagents=[
            NgsReagentLot(
                lot_id="LIB-A",
                compatible_assays=["WGS", "RNA"],
                quantity_available=2,
                expires_at=base + timedelta(hours=8),
                opened_at=base,
                open_stability_hours=6,
            ),
            NgsReagentLot(
                lot_id="LIB-B",
                compatible_assays=["WGS", "RNA"],
                quantity_available=4,
                expires_at=base + timedelta(days=2),
                opened_at=base + timedelta(hours=4),
                open_stability_hours=24,
            ),
        ],
        pools=[NgsPool(pool_id="P-001", sample_ids=["S-001", "S-002", "S-003"], index_ids=["IDX-01", "IDX-02", "IDX-03"], max_members=4, run_id="RUN-001")],
        runs=[NgsRun(run_id="RUN-001", resource_id="SEQ-01", pool_ids=["P-001"], capacity_pools=1, scheduled_start=base + timedelta(hours=9), scheduled_end=base + timedelta(hours=17))],
        events=[
            NgsLabEvent(
                event_id="E-001",
                event_type="urgent_sample",
                observed_at=base + timedelta(minutes=30),
                target_id="S-002",
                description="Urgent clinical sample inserted into same-day workflow.",
            ),
            NgsLabEvent(
                event_id="E-002",
                event_type="sequencer_downtime",
                observed_at=base + timedelta(hours=6, minutes=30),
                target_id="SEQ-01",
                description="SEQ-01 unavailable from 15:00 to 18:00 UTC.",
            ),
            NgsLabEvent(
                event_id="E-003",
                event_type="qc_fail",
                observed_at=base + timedelta(hours=5),
                target_id="S-003",
                description="S-003 RNA library QC is borderline and needs repeat confirmation.",
            ),
            NgsLabEvent(
                event_id="E-004",
                event_type="reagent_open_stability",
                observed_at=base + timedelta(hours=6),
                target_id="LIB-A",
                description="LIB-A open-stability expires before late library prep can start.",
            ),
        ],
    )


def _baseline_operations(base: datetime) -> list[NgsOperation]:
    operations: list[NgsOperation] = []
    starts = {
        "S-001": base,
        "S-002": base + timedelta(minutes=30),
        "S-003": base + timedelta(minutes=15),
    }
    for sample_id, start in starts.items():
        operations.extend(_sample_ops(sample_id, start, qc_status="pass"))
    for operation in operations:
        if operation.operation_id == "S-003-QC":
            operation.qc_status = "borderline"
        if operation.operation_id == "S-001-RECEIPT":
            operation.frozen_flag = True
    return operations


def _sample_ops(sample_id: str, start: datetime, qc_status: str) -> list[NgsOperation]:
    stages = [
        ("RECEIPT", "receipt", 10, "EXTRACT-01", None, None, None, "pre_pcr"),
        ("EXTRACT", "extraction", 55, "EXTRACT-01", None, None, None, "pre_pcr"),
        ("LIB", "library", 90, "LIB-01", "LIB-A", None, None, "pre_pcr"),
        ("QC", "qc", 30, "QC-01", None, None, qc_status, "pre_pcr"),
        ("POOL", "pooling", 35, "POOL-01", None, "P-001", None, "post_pcr"),
        ("SEQ", "sequencing", 480, "SEQ-01", None, "P-001", None, "post_pcr"),
        ("ANALYSIS", "analysis", 120, "BIOINFO-01", None, None, None, None),
        ("REPORT", "report", 30, "BIOINFO-01", None, None, None, None),
    ]
    current = start
    ops: list[NgsOperation] = []
    previous_id: str | None = None
    for suffix, stage, duration, resource, reagent, pool, qc, zone in stages:
        operation_id = f"{sample_id}-{suffix}"
        op = NgsOperation(
            operation_id=operation_id,
            sample_id=sample_id,
            entity_id=f"{sample_id}-{stage}",
            stage=stage,
            duration_minutes=duration,
            eligible_resource_ids=[resource],
            predecessor_ids=[previous_id] if previous_id else [],
            planned_start=current,
            planned_end=current + timedelta(minutes=duration),
            resource_id=resource,
            reagent_lot_id=reagent,
            pool_id=pool,
            run_id="RUN-001" if stage == "sequencing" else None,
            index_id=f"IDX-0{sample_id[-1]}" if stage == "pooling" else None,
            qc_status=qc,
            zone=zone,
        )
        ops.append(op)
        previous_id = operation_id
        current = op.planned_end + timedelta(minutes=10)
    return ops


def _entities(samples: list[NgsSample]) -> list[NgsEntity]:
    entities: list[NgsEntity] = []
    for sample in samples:
        previous: str | None = None
        for entity_type in ("sample", "extract", "library", "pool", "run", "fastq", "analysis", "report"):
            entity_id = f"{sample.sample_id}-{entity_type}"
            entities.append(
                NgsEntity(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    sample_id=sample.sample_id,
                    parent_entity_ids=[previous] if previous else [],
                )
            )
            previous = entity_id
    return entities


def _build_impact_report(snapshot: NgsLabSnapshot) -> NgsImpactReport:
    return NgsImpactReport(
        impacted_samples=["S-002", "S-003"],
        impacted_entities=["S-002-library", "S-003-library", "P-001", "RUN-001"],
        impacted_pools=["P-001"],
        impacted_runs=["RUN-001"],
        tat_risk_samples=["S-002", "S-003"],
        event_summary=[f"{event.event_type}:{event.target_id}" for event in snapshot.events],
    )


def _build_demo_candidates(snapshot: NgsLabSnapshot) -> list[NgsRepairCandidate]:
    return [
        _dispatch_candidate(snapshot),
        _reagent_repair_candidate(snapshot),
        _event_local_repair_candidate(snapshot),
        _stage_first_candidate(snapshot),
    ]


def _dispatch_candidate(snapshot: NgsLabSnapshot) -> NgsRepairCandidate:
    operations = deepcopy(snapshot.operations)
    pools = deepcopy(snapshot.pools)
    runs = deepcopy(snapshot.runs)
    # Create deliberate hard-gate failures: duplicate index, QC borderline pushed
    # downstream, late LIB-A usage, and SEQ-01 downtime overlap.
    pools[0].index_ids = ["IDX-01", "IDX-02", "IDX-02"]
    return NgsRepairCandidate(
        candidate_id="ngs-cand-dispatch-urgent-first",
        strategy_type="dispatching_urgent_first",
        label="Urgent-first dispatch baseline",
        operations=operations,
        pools=pools,
        runs=runs,
        repair_actions=[
            NgsRepairAction(
                action_type="priority_rule",
                target_id="S-002",
                description="Move urgent sample ahead without protected rescue.",
                source_refs=["event:E-001", "rule:urgent_first"],
            )
        ],
        weighted_tardiness_minutes=220,
        urgent_tardiness_minutes=140,
        rescue_burden=1,
        schedule_stability=0.92,
    )


def _reagent_repair_candidate(snapshot: NgsLabSnapshot) -> NgsRepairCandidate:
    base = snapshot.captured_at
    operations = _repair_operations(snapshot, sequencing_resource="SEQ-02", use_lot="LIB-B")
    _set_qc_pass(operations, "S-003")
    pools = deepcopy(snapshot.pools)
    runs = [
        NgsRun(
            run_id="RUN-002",
            resource_id="SEQ-02",
            pool_ids=["P-001"],
            capacity_pools=1,
            scheduled_start=base + timedelta(hours=10),
            scheduled_end=base + timedelta(hours=18),
        )
    ]
    pools[0].run_id = "RUN-002"
    return NgsRepairCandidate(
        candidate_id="ngs-cand-reagent-run-rescue",
        strategy_type="reagent_repair",
        label="Substitute reagent lot and move sequencing run",
        operations=operations,
        pools=pools,
        runs=runs,
        repair_actions=[
            NgsRepairAction(
                action_type="lot_substitution",
                target_id="LIB-B",
                description="Use LIB-B for library steps after LIB-A open stability expires.",
                source_refs=["event:E-004", "reagent:LIB-B"],
            ),
            NgsRepairAction(
                action_type="run_move",
                target_id="RUN-002",
                description="Move pool P-001 from SEQ-01 to SEQ-02.",
                source_refs=["event:E-002", "resource:SEQ-02"],
            ),
            NgsRepairAction(
                action_type="qc_repeat_confirmed",
                target_id="S-003-QC",
                description="Repeat QC for S-003 before pooling.",
                source_refs=["event:E-003", "operation:S-003-QC"],
            ),
        ],
        weighted_tardiness_minutes=90,
        urgent_tardiness_minutes=20,
        rescue_burden=3,
        schedule_stability=0.74,
    )


def _event_local_repair_candidate(snapshot: NgsLabSnapshot) -> NgsRepairCandidate:
    base = snapshot.captured_at
    operations = _repair_operations(snapshot, sequencing_resource="SEQ-02", use_lot="LIB-B")
    _set_qc_pass(operations, "S-003")
    # Keep non-urgent work less disturbed by delaying S-001 analysis/report.
    for operation in operations:
        if operation.sample_id == "S-001" and operation.stage in {"analysis", "report"}:
            operation.planned_start += timedelta(hours=2)
            operation.planned_end += timedelta(hours=2)
    pools = deepcopy(snapshot.pools)
    pools[0].run_id = "RUN-LOCAL"
    runs = [
        NgsRun(
            run_id="RUN-LOCAL",
            resource_id="SEQ-02",
            pool_ids=["P-001"],
            capacity_pools=1,
            scheduled_start=base + timedelta(hours=10, minutes=30),
            scheduled_end=base + timedelta(hours=18, minutes=30),
        )
    ]
    return NgsRepairCandidate(
        candidate_id="ngs-cand-event-local",
        strategy_type="event_local_repair",
        label="Event-local repair around urgent sample and downtime",
        operations=operations,
        pools=pools,
        runs=runs,
        repair_actions=[
            NgsRepairAction(
                action_type="local_window_repair",
                target_id="S-002",
                description="Repair only operations around urgent sample, QC, and sequencing downtime.",
                source_refs=["event:E-001", "event:E-002", "event:E-003"],
            )
        ],
        weighted_tardiness_minutes=110,
        urgent_tardiness_minutes=35,
        rescue_burden=2,
        schedule_stability=0.86,
    )


def _stage_first_candidate(snapshot: NgsLabSnapshot) -> NgsRepairCandidate:
    base = snapshot.captured_at
    operations = _repair_operations(snapshot, sequencing_resource="SEQ-02", use_lot="LIB-B")
    _set_qc_pass(operations, "S-003")
    for operation in operations:
        if operation.stage == "analysis":
            operation.planned_start = max(operation.planned_start, base + timedelta(hours=18, minutes=30))
            operation.planned_end = operation.planned_start + timedelta(minutes=operation.duration_minutes)
        if operation.stage == "report":
            predecessor = next(
                item for item in operations if item.sample_id == operation.sample_id and item.stage == "analysis"
            )
            operation.planned_start = predecessor.planned_end + timedelta(minutes=10)
            operation.planned_end = operation.planned_start + timedelta(minutes=operation.duration_minutes)
    pools = deepcopy(snapshot.pools)
    pools[0].run_id = "RUN-STAGE"
    runs = [
        NgsRun(
            run_id="RUN-STAGE",
            resource_id="SEQ-02",
            pool_ids=["P-001"],
            capacity_pools=1,
            scheduled_start=base + timedelta(hours=10),
            scheduled_end=base + timedelta(hours=18),
        )
    ]
    return NgsRepairCandidate(
        candidate_id="ngs-cand-stage-first",
        strategy_type="stage_first_redistribution",
        label="Stage-first workload redistribution",
        operations=operations,
        pools=pools,
        runs=runs,
        repair_actions=[
            NgsRepairAction(
                action_type="stage_redistribution",
                target_id="analysis_stage",
                description="Balance library, sequencing, and analysis stages after hard feasibility repair.",
                source_refs=["portfolio:stage_first", "event:E-002"],
            ),
            NgsRepairAction(
                action_type="lot_substitution",
                target_id="LIB-B",
                description="Use stable reagent lot for late library steps.",
                source_refs=["event:E-004", "reagent:LIB-B"],
            ),
        ],
        weighted_tardiness_minutes=70,
        urgent_tardiness_minutes=25,
        rescue_burden=4,
        schedule_stability=0.68,
    )


def _repair_operations(
    snapshot: NgsLabSnapshot,
    *,
    sequencing_resource: str,
    use_lot: str,
) -> list[NgsOperation]:
    operations = deepcopy(snapshot.operations)
    by_sample = {sample.sample_id: sample for sample in snapshot.samples}
    for operation in operations:
        if operation.stage == "library":
            operation.reagent_lot_id = use_lot
        if operation.stage == "sequencing":
            operation.resource_id = sequencing_resource
            operation.run_id = "RUN-002"
        if operation.sample_id == "S-002" and operation.stage in {"library", "qc", "pooling"}:
            operation.planned_start -= timedelta(minutes=30)
            operation.planned_end -= timedelta(minutes=30)
        if by_sample[operation.sample_id].priority == "STAT" and operation.stage == "library":
            extraction = next(
                item for item in operations if item.sample_id == operation.sample_id and item.stage == "extraction"
            )
            operation.planned_start = extraction.planned_end + timedelta(minutes=30)
            operation.planned_end = operation.planned_start + timedelta(minutes=operation.duration_minutes)
    _repair_precedence(operations)
    return operations


def _repair_precedence(operations: list[NgsOperation]) -> None:
    by_id = {operation.operation_id: operation for operation in operations}
    changed = True
    while changed:
        changed = False
        for operation in operations:
            if not operation.predecessor_ids:
                continue
            latest_end = max(by_id[pred].planned_end for pred in operation.predecessor_ids if pred in by_id)
            min_start = latest_end + timedelta(minutes=10)
            if operation.planned_start < min_start:
                duration = operation.duration_minutes
                operation.planned_start = min_start
                operation.planned_end = min_start + timedelta(minutes=duration)
                changed = True


def _set_qc_pass(operations: list[NgsOperation], sample_id: str) -> None:
    for operation in operations:
        if operation.sample_id == sample_id and operation.stage == "qc":
            operation.qc_status = "pass"


def _soft_score(candidate: NgsRepairCandidate) -> float:
    if not candidate.gate_report or not candidate.gate_report.pass_gate:
        return -1_000_000.0
    return round(
        1000
        - candidate.weighted_tardiness_minutes * 1.8
        - candidate.urgent_tardiness_minutes * 3.0
        - candidate.rescue_burden * 25
        + candidate.schedule_stability * 120,
        2,
    )


def _candidate_explanation(candidate: NgsRepairCandidate) -> str:
    if candidate.gate_report and not candidate.gate_report.pass_gate:
        first = candidate.gate_report.hard_blockers[0]
        return f"Rejected by protected feasibility gate: {first.gate} - {first.message}"
    return (
        f"Hard-feasible candidate. WT={candidate.weighted_tardiness_minutes} min, "
        f"urgent tardiness={candidate.urgent_tardiness_minutes} min, "
        f"rescue burden={candidate.rescue_burden}, stability={candidate.schedule_stability:.2f}."
    )


def _build_audit_package(
    snapshot: NgsLabSnapshot,
    feasible: list[NgsRepairCandidate],
    rejected: list[NgsRepairCandidate],
    recommended: NgsRepairCandidate | None,
) -> dict:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "source_refs": [
            "snapshot:samples",
            "snapshot:entities",
            "snapshot:operations",
            "snapshot:reagents",
            "snapshot:pools",
            "snapshot:runs",
            "snapshot:events",
        ],
        "candidate_count": len(feasible) + len(rejected),
        "feasible_count": len(feasible),
        "rejected_count": len(rejected),
        "recommended_candidate_id": recommended.candidate_id if recommended else None,
        "planner_confirmation_required": True,
        "lims_writeback_executed": False,
    }


def _build_agent_trace(
    snapshot: NgsLabSnapshot,
    impact: NgsImpactReport,
    raw_candidates: list[NgsRepairCandidate],
    feasible: list[NgsRepairCandidate],
    rejected: list[NgsRepairCandidate],
    recommended: NgsRepairCandidate | None,
) -> list[NgsAgentTraceStep]:
    rejected_gates = sorted(
        {
            issue.gate
            for candidate in rejected
            if candidate.gate_report
            for issue in candidate.gate_report.hard_blockers
        }
    )
    feasible_ids = [candidate.candidate_id for candidate in feasible]
    return [
        NgsAgentTraceStep(
            agent_name="NGS Incident Agent",
            input_refs=[f"event:{event.event_id}" for event in snapshot.events],
            output_refs=[
                f"sample:{sample_id}" for sample_id in impact.impacted_samples
            ] + [f"run:{run_id}" for run_id in impact.impacted_runs],
            decision=(
                "标准化 urgent sample、sequencer downtime、QC borderline 和 reagent "
                "open-stability 事件，并限定只使用 observed_at 已发生的信息。"
            ),
            confidence=0.93,
            boundary="低置信或 future information 不进入候选生成。",
        ),
        NgsAgentTraceStep(
            agent_name="Constraint Evidence Agent",
            input_refs=[
                "snapshot:operations",
                "snapshot:reagents",
                "snapshot:pools",
                "snapshot:runs",
                "snapshot:resource_calendar",
            ],
            output_refs=[f"gate:{gate}" for gate in rejected_gates] or ["gate:all_pass"],
            decision="把试剂、QC、pool/run、index、resource calendar、frozen-zone 和 traceability 转成 hard gate evidence。",
            confidence=0.91,
            boundary="解释只能引用结构化 source refs，不用自然语言替代证据。",
        ),
        NgsAgentTraceStep(
            agent_name="Protected Portfolio Agent",
            input_refs=[f"candidate:{candidate.candidate_id}" for candidate in raw_candidates],
            output_refs=[f"candidate:{candidate_id}" for candidate_id in feasible_ids],
            decision=(
                f"生成 {len(raw_candidates)} 个候选方案，先过滤 hard-infeasible，"
                f"保留 {len(feasible)} 个可执行候选进入 soft-score 比较。"
            ),
            confidence=0.9,
            boundary="hard gate 未通过的候选不会推给计划员作为可执行方案。",
        ),
        NgsAgentTraceStep(
            agent_name="Explanation Agent",
            input_refs=[
                f"candidate:{recommended.candidate_id}" if recommended else "candidate:none",
                "gate_report:protected_feasibility",
            ],
            output_refs=["audit:recommendation_explanation"],
            decision=(
                recommended.explanation
                if recommended
                else "没有 hard-feasible 候选，系统退回人工判断。"
            ),
            confidence=0.88 if recommended else 0.72,
            boundary="只解释 hard gate、KPI、rescue burden 和仍需人工确认的残留风险。",
        ),
        NgsAgentTraceStep(
            agent_name="Case Memory Agent",
            input_refs=["planner_confirmation:pending", "execution_feedback:pending"],
            output_refs=["case_memory:pending_after_planner_decision"],
            decision="当前 demo 生成可复盘案例骨架；只有计划员确认和执行反馈返回后才沉淀为案例。",
            confidence=0.7,
            boundary="单个案例不能自动升级成硬规则。",
        ),
        NgsAgentTraceStep(
            agent_name="Preference Learning Agent",
            input_refs=["case_memory:pending_after_planner_decision"],
            output_refs=["preference_profile:not_updated"],
            decision="本次运行不更新排序偏好；需要多次 planner decision 后才做阈值和排序辅助。",
            confidence=0.62,
            boundary="只影响 soft ranking，不覆盖 hard feasibility gate。",
        ),
    ]


def _gate_status(blockers: list[NgsGateIssue], gate: str) -> str:
    return "block" if any(issue.gate == gate for issue in blockers) else "pass"


def _issue(
    gate: str,
    entity_type: str,
    entity_id: str,
    message: str,
    source_refs: list[str],
) -> NgsGateIssue:
    return NgsGateIssue(
        gate=gate,
        entity_type=entity_type,
        entity_id=entity_id,
        message=message,
        source_refs=source_refs,
    )


def _overlaps(
    start: datetime,
    end: datetime,
    other_start: datetime,
    other_end: datetime,
) -> bool:
    return start < other_end and end > other_start


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for parent in graph.get(node, []):
            if parent in graph and visit(parent):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)
