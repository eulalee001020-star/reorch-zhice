"""Shadow learning policy for GNN/DRL-inspired solver control.

This module does not pretend a neural model has already been trained. It builds
graph-like features and deterministic policy actions that can be logged today
and later replaced by trained GNN/DQN/PPO models.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import NeighborhoodType, RuleCategory, StrategyType
from app.models.impact import ImpactReport
from app.models.schedule import ScheduleSnapshot
from app.services.machine_rank_service import MachineRank


@dataclass(frozen=True)
class GraphStateFeatures:
    node_count: int
    precedence_edge_count: int
    machine_conflict_edge_count: int
    alternative_resource_edge_count: int
    affected_ratio: float
    bottleneck_pressure: float


@dataclass(frozen=True)
class PolicyAction:
    recommended_rules: list[RuleCategory]
    recommended_neighborhoods: list[NeighborhoodType]
    search_budget_multiplier: float
    auto_acceptance_prior: float
    reasoning: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MultiAgentAdvice:
    operation_sequence_priority: list[str]
    machine_assignment_priority: dict[str, list[str]]
    warm_start_metadata: dict


@dataclass(frozen=True)
class LearningPolicyAdvice:
    graph_features: GraphStateFeatures
    policy_action: PolicyAction
    multi_agent_advice: MultiAgentAdvice
    mode: str = "deterministic_shadow_policy"


class LearningStrategyPolicy:
    """Produces solver-control advice from graph-like shop-floor features."""

    def advise(
        self,
        snapshot: ScheduleSnapshot,
        impact_report: ImpactReport,
        strategy_type: StrategyType,
        machine_ranks: list[MachineRank],
    ) -> LearningPolicyAdvice:
        features = self._build_graph_features(snapshot, impact_report, machine_ranks)
        action = self._choose_policy_action(features, strategy_type)
        multi_agent = self._multi_agent_advice(snapshot, impact_report, machine_ranks)
        return LearningPolicyAdvice(
            graph_features=features,
            policy_action=action,
            multi_agent_advice=multi_agent,
        )

    @staticmethod
    def _build_graph_features(
        snapshot: ScheduleSnapshot,
        impact_report: ImpactReport,
        machine_ranks: list[MachineRank],
    ) -> GraphStateFeatures:
        operations = [
            op
            for wo in snapshot.work_orders
            for op in wo.operations
        ]
        node_count = len(operations)
        precedence_edges = sum(len(op.predecessor_ids) + len(op.successor_ids) for op in operations) // 2
        by_resource: dict[str, int] = {}
        for op in operations:
            by_resource[op.resource_id] = by_resource.get(op.resource_id, 0) + 1
        conflict_edges = sum(max(0, count - 1) for count in by_resource.values())
        raw = snapshot.raw_data or {}
        alternative_edges = 0
        for wo in raw.get("work_orders", []):
            for op in wo.get("operations", []):
                alternative_edges += max(0, len(op.get("eligible_resources", [])) - 1)
        affected_ratio = len(impact_report.affected_operations) / max(1, node_count)
        bottleneck_pressure = machine_ranks[0].score if machine_ranks else 0.0
        return GraphStateFeatures(
            node_count=node_count,
            precedence_edge_count=precedence_edges,
            machine_conflict_edge_count=conflict_edges,
            alternative_resource_edge_count=alternative_edges,
            affected_ratio=round(affected_ratio, 4),
            bottleneck_pressure=round(bottleneck_pressure, 4),
        )

    @staticmethod
    def _choose_policy_action(
        features: GraphStateFeatures,
        strategy_type: StrategyType,
    ) -> PolicyAction:
        reasoning: list[str] = []
        if strategy_type == StrategyType.GLOBAL_RESCHEDULE or features.affected_ratio > 0.25:
            rules = [
                RuleCategory.DUE_DATE_PRIORITY,
                RuleCategory.BOTTLENECK_RESOURCE_PRIORITY,
                RuleCategory.CRITICAL_ORDER_PRIORITY,
            ]
            neighborhoods = [
                NeighborhoodType.BOTTLENECK_DEVICE,
                NeighborhoodType.DEVICE_REASSIGNMENT,
                NeighborhoodType.CRITICAL_PATH,
            ]
            budget_multiplier = 1.35
            reasoning.append("large_or_global_scope")
        elif features.bottleneck_pressure >= 0.65:
            rules = [
                RuleCategory.BOTTLENECK_RESOURCE_PRIORITY,
                RuleCategory.MINIMUM_SLACK_TIME,
            ]
            neighborhoods = [
                NeighborhoodType.BOTTLENECK_DEVICE,
                NeighborhoodType.SAME_DEVICE_SWAP,
            ]
            budget_multiplier = 1.15
            reasoning.append("bottleneck_pressure_high")
        else:
            rules = [
                RuleCategory.MINIMUM_SLACK_TIME,
                RuleCategory.SHORTEST_PROCESSING_TIME,
            ]
            neighborhoods = [
                NeighborhoodType.DELAYED_ORDER,
                NeighborhoodType.SAME_DEVICE_SWAP,
            ]
            budget_multiplier = 1.0
            reasoning.append("local_dynamic_repair")

        acceptance_prior = max(0.3, min(0.9, 0.75 - features.affected_ratio * 0.4))
        return PolicyAction(
            recommended_rules=rules,
            recommended_neighborhoods=neighborhoods,
            search_budget_multiplier=budget_multiplier,
            auto_acceptance_prior=round(acceptance_prior, 4),
            reasoning=reasoning,
        )

    @staticmethod
    def _multi_agent_advice(
        snapshot: ScheduleSnapshot,
        impact_report: ImpactReport,
        machine_ranks: list[MachineRank],
    ) -> MultiAgentAdvice:
        affected = {op.operation_id for op in impact_report.affected_operations}
        ordered_ops = sorted(
            [
                op
                for wo in snapshot.work_orders
                for op in wo.operations
            ],
            key=lambda op: (
                0 if op.operation_id in affected else 1,
                op.start_time,
            ),
        )
        raw = snapshot.raw_data or {}
        eligible_by_op: dict[str, list[str]] = {}
        for wo in raw.get("work_orders", []):
            for op in wo.get("operations", []):
                op_id = op.get("operation_id")
                if op_id:
                    eligible_by_op[str(op_id)] = [str(r) for r in op.get("eligible_resources", [])]
        machine_rank_order = [rank.resource_id for rank in machine_ranks]
        assignment_priority: dict[str, list[str]] = {}
        for op in ordered_ops:
            eligible = eligible_by_op.get(op.operation_id, [op.resource_id])
            assignment_priority[op.operation_id] = sorted(
                eligible,
                key=lambda r: machine_rank_order.index(r) if r in machine_rank_order else len(machine_rank_order),
            )
        return MultiAgentAdvice(
            operation_sequence_priority=[op.operation_id for op in ordered_ops],
            machine_assignment_priority=assignment_priority,
            warm_start_metadata={
                "operation_agent": "priority_by_affected_then_start_time",
                "machine_agent": "priority_by_machine_rank",
            },
        )

