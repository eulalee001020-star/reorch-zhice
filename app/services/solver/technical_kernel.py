"""Constraint-to-Recovery technical kernel services."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.enums import IncidentType
from app.models.schedule import Operation, Resource, ScheduleSnapshot
from app.models.technical_kernel import (
    DecisionGraph,
    DecisionGraphBuildRequest,
    DecisionGraphBuildResponse,
    DecisionGraphEdge,
    DecisionGraphNode,
    EvidenceGateFinding,
    EvidenceGateRequest,
    EvidenceGateResponse,
    RecoveryOperatorRecommendation,
    RecoveryOperatorRequest,
    RecoveryOperatorResponse,
)


class DecisionGraphService:
    """Build an auditable production-state graph from a schedule snapshot."""

    def build(self, request: DecisionGraphBuildRequest) -> DecisionGraphBuildResponse:
        snapshot = request.snapshot
        graph = DecisionGraph(
            snapshot_id=str(snapshot.snapshot_id),
            workshop_id=snapshot.workshop_id,
        )
        resource_map = _resource_map(snapshot)
        operation_map = _operation_map(snapshot)
        successor_map = _successor_map(operation_map)

        for resource in _resources(snapshot):
            graph.nodes.append(
                DecisionGraphNode(
                    node_id=f"resource:{resource.resource_id}",
                    node_type="resource",
                    label=resource.name or resource.resource_id,
                    attributes={
                        "capabilities": resource.capabilities,
                        "is_bottleneck": resource.is_bottleneck,
                        "criticality": resource.criticality,
                    },
                )
            )

        for work_order in snapshot.work_orders:
            graph.nodes.append(
                DecisionGraphNode(
                    node_id=f"work_order:{work_order.work_order_id}",
                    node_type="work_order",
                    label=work_order.product_name,
                    attributes={
                        "due_date": work_order.due_date.isoformat(),
                        "priority": work_order.priority,
                    },
                )
            )
            for operation in work_order.operations:
                graph.nodes.append(_operation_node(operation))
                graph.edges.append(
                    DecisionGraphEdge(
                        source_id=f"work_order:{work_order.work_order_id}",
                        target_id=f"operation:{operation.operation_id}",
                        edge_type="contains_operation",
                    )
                )
                graph.edges.append(
                    DecisionGraphEdge(
                        source_id=f"operation:{operation.operation_id}",
                        target_id=f"resource:{operation.resource_id}",
                        edge_type="assigned_to_resource",
                    )
                )
                for predecessor_id in operation.predecessor_ids:
                    graph.edges.append(
                        DecisionGraphEdge(
                            source_id=f"operation:{predecessor_id}",
                            target_id=f"operation:{operation.operation_id}",
                            edge_type="precedes",
                        )
                    )

        directly_affected = _directly_affected_operations(request, operation_map)
        downstream = _collect_downstream(directly_affected, successor_map)
        affected = sorted(set(directly_affected) | set(downstream))
        frozen = set(request.freeze_operation_ids) | _freeze_ids_from_snapshot(snapshot)
        repairable = sorted(op_id for op_id in affected if op_id not in frozen)
        alternatives = {
            op_id: _alternative_resources(operation_map[op_id], resource_map)
            for op_id in repairable
            if op_id in operation_map
        }
        metrics: dict[str, int | float | str] = {
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "affected_operation_count": len(affected),
            "repairable_frontier_count": len(repairable),
            "alternative_resource_options": sum(
                len(values) for values in alternatives.values()
            ),
        }
        return DecisionGraphBuildResponse(
            graph=graph,
            affected_operation_ids=affected,
            downstream_operation_ids=downstream,
            repairable_frontier_ids=repairable,
            alternative_resources=alternatives,
            metrics=metrics,
        )


class RecoveryOperatorPortfolioService:
    """Select recovery operators before solving."""

    def select(self, request: RecoveryOperatorRequest) -> RecoveryOperatorResponse:
        affected_count = len(request.decision_graph.affected_operation_ids)
        alternative_count = sum(
            len(values)
            for values in request.decision_graph.alternative_resources.values()
        )
        scope = _repair_scope(affected_count, alternative_count)
        candidates = _operator_candidates(
            incident_type=str(request.incident.incident_type),
            scope=scope,
            affected_count=affected_count,
            alternative_count=alternative_count,
        )
        allowed = set(request.allowed_operator_types)
        selected: list[RecoveryOperatorRecommendation] = []
        rejected: list[str] = []
        for operator in candidates:
            if allowed and operator.operator_type not in allowed:
                rejected.append(operator.operator_type)
                continue
            selected.append(operator)
            if len(selected) >= request.max_operator_count:
                break
        for rank, operator in enumerate(selected, start=1):
            operator.rank = rank
        return RecoveryOperatorResponse(
            incident_id=str(request.incident.incident_id),
            repair_scope=scope,
            recommendations=selected,
            rejected_operator_types=sorted(set(rejected)),
        )


class EvidenceGateService:
    """Merge data, constraint, evidence, policy, replay, and writeback gates."""

    def evaluate(self, request: EvidenceGateRequest) -> EvidenceGateResponse:
        findings: list[EvidenceGateFinding] = []
        allow_solve = _data_gate(request, findings)
        constraint_pass = _constraint_gate(request, findings)
        evidence_pass = _evidence_gate(request, findings)
        replay_pass = _replay_gate(request, findings)
        policy_pass = _policy_gate(request, findings)
        writeback_pass = _writeback_gate(request, findings)

        allow_recommendation = allow_solve and constraint_pass and policy_pass
        allow_formal_explanation = allow_recommendation and evidence_pass
        allow_shadow = allow_formal_explanation and replay_pass
        allow_writeback = allow_shadow and writeback_pass
        overall = "pass" if allow_recommendation else "blocked"
        if allow_recommendation and not allow_formal_explanation:
            overall = "reference_only"
        if allow_formal_explanation and not allow_writeback:
            overall = "human_confirmed_readonly"
        return EvidenceGateResponse(
            allow_solve=allow_solve,
            allow_recommendation=allow_recommendation,
            allow_formal_explanation=allow_formal_explanation,
            allow_shadow=allow_shadow,
            allow_writeback=allow_writeback,
            overall_status=overall,
            findings=findings,
            recommendation_policy=_recommendation_policy(
                allow_recommendation,
                allow_formal_explanation,
                allow_shadow,
                allow_writeback,
            ),
        )


def _resources(snapshot: ScheduleSnapshot) -> list[Resource]:
    raw_resources = (snapshot.raw_data or {}).get("resources")
    if isinstance(raw_resources, list):
        resources: list[Resource] = []
        for row in raw_resources:
            if isinstance(row, Resource):
                resources.append(row)
            elif isinstance(row, dict) and row.get("resource_id"):
                resources.append(Resource(**row))
        if resources:
            return resources
    resource_ids = sorted(
        {
            operation.resource_id
            for work_order in snapshot.work_orders
            for operation in work_order.operations
        }
    )
    return [
        Resource(resource_id=resource_id, name=resource_id, capabilities=[])
        for resource_id in resource_ids
    ]


def _resource_map(snapshot: ScheduleSnapshot) -> dict[str, Resource]:
    return {resource.resource_id: resource for resource in _resources(snapshot)}


def _operation_map(snapshot: ScheduleSnapshot) -> dict[str, Operation]:
    return {
        operation.operation_id: operation
        for work_order in snapshot.work_orders
        for operation in work_order.operations
    }


def _successor_map(operation_map: dict[str, Operation]) -> dict[str, list[str]]:
    successors: dict[str, set[str]] = {op_id: set() for op_id in operation_map}
    for operation in operation_map.values():
        for successor_id in operation.successor_ids:
            successors.setdefault(operation.operation_id, set()).add(successor_id)
        for predecessor_id in operation.predecessor_ids:
            successors.setdefault(predecessor_id, set()).add(operation.operation_id)
    return {op_id: sorted(values) for op_id, values in successors.items()}


def _operation_node(operation: Operation) -> DecisionGraphNode:
    return DecisionGraphNode(
        node_id=f"operation:{operation.operation_id}",
        node_type="operation",
        label=operation.operation_id,
        attributes={
            "work_order_id": operation.work_order_id,
            "resource_id": operation.resource_id,
            "required_capabilities": operation.required_capabilities,
            "start_time": operation.start_time.isoformat(),
            "end_time": operation.end_time.isoformat(),
            "is_affected": operation.is_affected,
            "is_adjusted": operation.is_adjusted,
        },
    )


def _directly_affected_operations(
    request: DecisionGraphBuildRequest,
    operation_map: dict[str, Operation],
) -> list[str]:
    if request.incident is None:
        return sorted(
            op_id for op_id, operation in operation_map.items() if operation.is_affected
        )
    incident = request.incident
    duration = 0
    if incident.raw_payload and incident.raw_payload.get("estimated_duration_minutes"):
        duration = int(incident.raw_payload["estimated_duration_minutes"])
    start = incident.occurred_at
    end = start + timedelta(minutes=max(duration, 1))
    affected: list[str] = []
    for operation in operation_map.values():
        if operation.resource_id != incident.resource_id:
            continue
        if _overlaps(operation.start_time, operation.end_time, start, end):
            affected.append(operation.operation_id)
    return sorted(affected)


def _collect_downstream(
    seed_ids: list[str],
    successor_map: dict[str, list[str]],
) -> list[str]:
    visited = set(seed_ids)
    downstream: list[str] = []
    queue = list(seed_ids)
    while queue:
        current = queue.pop(0)
        for successor_id in successor_map.get(current, []):
            if successor_id in visited:
                continue
            visited.add(successor_id)
            downstream.append(successor_id)
            queue.append(successor_id)
    return downstream


def _freeze_ids_from_snapshot(snapshot: ScheduleSnapshot) -> set[str]:
    raw = snapshot.raw_data or {}
    freeze_windows = raw.get("freeze_windows") or []
    frozen: set[str] = set()
    if isinstance(freeze_windows, list):
        for window in freeze_windows:
            if isinstance(window, dict) and window.get("operation_id"):
                frozen.add(str(window["operation_id"]))
    return frozen


def _alternative_resources(
    operation: Operation,
    resource_map: dict[str, Resource],
) -> list[str]:
    if not operation.required_capabilities:
        return [
            resource_id
            for resource_id in sorted(resource_map)
            if resource_id != operation.resource_id
        ]
    required = set(operation.required_capabilities)
    return sorted(
        resource.resource_id
        for resource in resource_map.values()
        if resource.resource_id != operation.resource_id
        and required.issubset(set(resource.capabilities))
    )


def _overlaps(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> bool:
    return left_start < right_end and right_start < left_end


def _repair_scope(affected_count: int, alternative_count: int) -> str:
    if affected_count == 0:
        return "observe_only"
    if affected_count <= 2 and alternative_count:
        return "local"
    if affected_count <= 6:
        return "rolling_window"
    return "controlled_global"


def _operator_candidates(
    *,
    incident_type: str,
    scope: str,
    affected_count: int,
    alternative_count: int,
) -> list[RecoveryOperatorRecommendation]:
    common = [
        _operator(
            "wait_and_shift",
            "Wait and shift affected operations",
            "minimal_perturbation",
            "heuristic_then_constraint_check",
            scope,
            [
                "Affects a bounded operation set.",
                "Keeps the plan stable when delay is tolerable.",
            ],
            ["DataGate", "ConstraintGate", "PolicyGate"],
            [
                "urgent_order_delay_min",
                "changed_operation_count",
                "total_tardiness_delta",
            ],
        )
    ]
    if incident_type == IncidentType.EQUIPMENT_FAILURE.value:
        if alternative_count:
            common.append(
                _operator(
                    "alternative_machine_repair",
                    "Move affected work to capable alternative resources",
                    "resource_reallocation",
                    "local_search_cp_sat",
                    scope,
                    ["Alternative resources exist for repairable operations."],
                    ["DataGate", "ConstraintGate", "EvidenceGate"],
                    [
                        "resource_switch_count",
                        "setup_change_delta",
                        "repair_latency_seconds",
                    ],
                )
            )
        common.extend(
            [
                _operator(
                    "local_insertion",
                    "Repair affected subgraph with local insertion",
                    "sequence_repair",
                    "cp_sat_lns",
                    scope,
                    [
                        f"{affected_count} affected operations can be isolated as a subgraph."
                    ],
                    ["ConstraintGate", "QualityGate"],
                    [
                        "changed_operation_count",
                        "perturbation_delta",
                        "hard_constraint_violation_count",
                    ],
                ),
                _operator(
                    "rolling_window_repair",
                    "Repair a bounded rolling window",
                    "scope_control",
                    "cp_sat_with_timeout_fallback",
                    "rolling_window",
                    ["Impact may propagate beyond the direct operation window."],
                    ["SnapshotGate", "ConstraintGate", "PolicyGate"],
                    ["time_to_candidate_seconds", "delay_delta", "best_known_feasible"],
                ),
            ]
        )
    else:
        common.append(
            _operator(
                "manual_policy_route",
                "Route unsupported incident to policy review",
                "decision_support",
                "deterministic_guardrail",
                "manual_review",
                ["Incident type is not yet mapped to a specialized operator."],
                ["DataGate", "HumanReviewGate"],
                ["unsupported_reason", "manual_review_required"],
            )
        )
    if scope == "controlled_global":
        common.append(
            _operator(
                "controlled_global_reschedule",
                "Controlled global reschedule with strict quality gates",
                "global_reschedule",
                "cp_sat_with_feasible_fallback",
                scope,
                ["Local and rolling-window repair may be insufficient."],
                ["DataGate", "ConstraintGate", "EvidenceGate", "WritebackGate"],
                [
                    "objective_gap",
                    "solve_time_seconds",
                    "hard_constraint_violation_count",
                ],
            )
        )
    return common


def _operator(
    operator_type: str,
    label: str,
    algorithm_family: str,
    solver_backend: str,
    scope: str,
    why_selected: list[str],
    required_gates: list[str],
    expected_metrics: list[str],
) -> RecoveryOperatorRecommendation:
    return RecoveryOperatorRecommendation(
        operator_type=operator_type,
        label=label,
        algorithm_family=algorithm_family,
        solver_backend=solver_backend,
        scope=scope,
        rank=0,
        why_selected=why_selected,
        required_gates=required_gates,
        expected_metrics=expected_metrics,
    )


def _data_gate(
    request: EvidenceGateRequest,
    findings: list[EvidenceGateFinding],
) -> bool:
    if request.data_readiness is None:
        findings.append(
            _finding(
                "DataGate",
                "fail",
                "blocker",
                "No data readiness report supplied; solving is not allowed.",
            )
        )
        return False
    if request.data_readiness.blockers:
        findings.append(
            _finding(
                "DataGate",
                "fail",
                "blocker",
                "Data blockers exist; solving is not allowed.",
            )
        )
        return False
    findings.append(_finding("DataGate", "pass", "info", "No data blockers found."))
    return True


def _constraint_gate(
    request: EvidenceGateRequest,
    findings: list[EvidenceGateFinding],
) -> bool:
    plans = request.candidate_plans
    if not plans:
        findings.append(
            _finding(
                "ConstraintGate", "fail", "blocker", "No candidate plans supplied."
            )
        )
        return False
    if any(not plan.constraint_report.is_feasible for plan in plans):
        findings.append(
            _finding(
                "ConstraintGate",
                "fail",
                "blocker",
                "At least one candidate has hard constraint violations.",
            )
        )
        return False
    findings.append(
        _finding(
            "ConstraintGate",
            "pass",
            "info",
            "All supplied candidates are hard-feasible.",
        )
    )
    return True


def _evidence_gate(
    request: EvidenceGateRequest,
    findings: list[EvidenceGateFinding],
) -> bool:
    if not request.source_refs:
        findings.append(
            _finding(
                "EvidenceGate", "fail", "warning", "Source references are missing."
            )
        )
        return False
    findings.append(
        _finding(
            "EvidenceGate",
            "pass",
            "info",
            "Source references are present.",
            request.source_refs,
        )
    )
    return True


def _replay_gate(
    request: EvidenceGateRequest,
    findings: list[EvidenceGateFinding],
) -> bool:
    if request.replay_validation is None:
        findings.append(
            _finding(
                "ReplayGate",
                "fail",
                "warning",
                "Replay validation is not supplied; shadow mode is not allowed.",
            )
        )
        return False
    if not request.replay_validation.top_n_hit:
        findings.append(
            _finding(
                "ReplayGate",
                "fail",
                "warning",
                "Replay Top-N did not meet the acceptance threshold.",
            )
        )
        return False
    findings.append(
        _finding("ReplayGate", "pass", "info", "Replay Top-N hit is valid.")
    )
    return True


def _policy_gate(
    request: EvidenceGateRequest,
    findings: list[EvidenceGateFinding],
) -> bool:
    if not request.quality_gates:
        findings.append(
            _finding(
                "PolicyGate",
                "fail",
                "blocker",
                "No quality-gate reports supplied; recommendation is not allowed.",
            )
        )
        return False
    if any(not gate.pass_gate for gate in request.quality_gates):
        findings.append(
            _finding(
                "PolicyGate",
                "fail",
                "blocker",
                "A quality gate blocked recommendation.",
            )
        )
        return False
    findings.append(
        _finding(
            "PolicyGate",
            "pass",
            "info",
            "Quality gates allow planner-facing recommendation.",
        )
    )
    return True


def _writeback_gate(
    request: EvidenceGateRequest,
    findings: list[EvidenceGateFinding],
) -> bool:
    if not request.planner_confirmed:
        findings.append(
            _finding(
                "WritebackGate",
                "fail",
                "warning",
                "Planner confirmation is required before writeback.",
            )
        )
        return False
    if request.shadow_capture and request.shadow_capture.writeback_blocked:
        findings.append(
            _finding(
                "WritebackGate",
                "fail",
                "warning",
                "Shadow mode explicitly blocks writeback.",
            )
        )
        return False
    if not request.sandbox_dry_run_passed:
        findings.append(
            _finding(
                "WritebackGate",
                "fail",
                "blocker",
                "A successful sandbox dry-run is required before controlled writeback.",
            )
        )
        return False
    if len(set(request.approval_refs)) < 2:
        findings.append(
            _finding(
                "WritebackGate",
                "fail",
                "blocker",
                "Two distinct approval references are required before controlled writeback.",
            )
        )
        return False
    if not request.writeback_authorization_ref:
        findings.append(
            _finding(
                "WritebackGate",
                "fail",
                "blocker",
                "A short-lived writeback authorization reference is required.",
            )
        )
        return False
    findings.append(
        _finding(
            "WritebackGate",
            "pass",
            "info",
            "Planner confirmation, sandbox evidence, dual approval, and authorization are present.",
            [request.writeback_authorization_ref, *request.approval_refs],
        )
    )
    return True


def _finding(
    gate: str,
    status: str,
    severity: str,
    message: str,
    source_refs: list[str] | None = None,
) -> EvidenceGateFinding:
    return EvidenceGateFinding(
        gate_name=gate,
        status=status,
        severity=severity,
        message=message,
        source_refs=source_refs or [],
    )


def _recommendation_policy(
    allow_recommendation: bool,
    allow_formal_explanation: bool,
    allow_shadow: bool,
    allow_writeback: bool,
) -> str:
    if allow_writeback:
        return "writeback_allowed_after_human_confirmation"
    if allow_shadow:
        return "read_only_shadow_allowed"
    if allow_formal_explanation:
        return "recommend_with_source_refs_and_planner_confirmation"
    if allow_recommendation:
        return "show_as_reference_only"
    return "do_not_recommend"
