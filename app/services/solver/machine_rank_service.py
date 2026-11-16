"""MachineRank-style resource importance scoring for dynamic FJSP.

Inspired by recent DFJSP research that ranks machines before selecting
dispatching rules. This implementation is deterministic and production-safe:
it does not require a trained neural model, but it exposes stable features
that can later feed a D3QN/GNN policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models.impact import ImpactReport
from app.models.schedule import Operation, ScheduleSnapshot


@dataclass(frozen=True)
class MachineRank:
    resource_id: str
    score: float
    load_minutes: float
    affected_operation_count: int
    bottleneck_hint: bool
    due_risk_score: float
    factors: list[str] = field(default_factory=list)


class MachineRankService:
    """Ranks resources by criticality for repair and LNS neighborhood selection."""

    def rank(
        self,
        snapshot: ScheduleSnapshot,
        impact_report: ImpactReport,
    ) -> list[MachineRank]:
        load_by_resource: dict[str, float] = {}
        ops_by_resource: dict[str, list[Operation]] = {}
        for wo in snapshot.work_orders:
            for op in wo.operations:
                duration = max(0.0, (op.end_time - op.start_time).total_seconds() / 60)
                load_by_resource[op.resource_id] = load_by_resource.get(op.resource_id, 0.0) + duration
                ops_by_resource.setdefault(op.resource_id, []).append(op)

        affected_by_resource: dict[str, int] = {}
        for affected in impact_report.affected_operations:
            affected_by_resource[affected.resource_id] = affected_by_resource.get(affected.resource_id, 0) + 1

        bottleneck_resources = self._bottleneck_resources(snapshot)
        reference_time = impact_report.analysis_reference_time
        ranks: list[MachineRank] = []
        max_load = max(load_by_resource.values(), default=1.0)

        for resource_id, load in load_by_resource.items():
            factors: list[str] = []
            normalized_load = load / max_load if max_load else 0.0
            affected_count = affected_by_resource.get(resource_id, 0)
            affected_score = min(1.0, affected_count / 5)
            bottleneck_hint = resource_id in bottleneck_resources
            bottleneck_score = 1.0 if bottleneck_hint else 0.0
            due_risk = self._due_risk_score(snapshot, ops_by_resource.get(resource_id, []), reference_time)

            score = (
                0.40 * normalized_load
                + 0.25 * affected_score
                + 0.25 * bottleneck_score
                + 0.10 * due_risk
            )
            if normalized_load >= 0.8:
                factors.append("high_resource_load")
            if affected_count:
                factors.append("directly_affected_resource")
            if bottleneck_hint:
                factors.append("bottleneck_hint")
            if due_risk >= 0.5:
                factors.append("near_due_work_orders")

            ranks.append(
                MachineRank(
                    resource_id=resource_id,
                    score=round(score, 4),
                    load_minutes=round(load, 2),
                    affected_operation_count=affected_count,
                    bottleneck_hint=bottleneck_hint,
                    due_risk_score=round(due_risk, 4),
                    factors=factors,
                )
            )

        ranks.sort(key=lambda item: item.score, reverse=True)
        return ranks

    @staticmethod
    def _bottleneck_resources(snapshot: ScheduleSnapshot) -> set[str]:
        raw = snapshot.raw_data or {}
        bottlenecks: set[str] = set()
        for res in raw.get("resources", []):
            if res.get("is_bottleneck") or res.get("criticality") in {"critical", "high_risk_config"}:
                resource_id = res.get("resource_id")
                if resource_id:
                    bottlenecks.add(str(resource_id))
        return bottlenecks

    @staticmethod
    def _due_risk_score(
        snapshot: ScheduleSnapshot,
        resource_ops: list[Operation],
        reference_time: datetime,
    ) -> float:
        if not resource_ops:
            return 0.0
        work_order_ids = {op.work_order_id for op in resource_ops}
        scores: list[float] = []
        for wo in snapshot.work_orders:
            if wo.work_order_id not in work_order_ids:
                continue
            hours_to_due = max(0.0, (wo.due_date - reference_time).total_seconds() / 3600)
            if hours_to_due <= 4:
                scores.append(1.0)
            elif hours_to_due <= 24:
                scores.append(0.6)
            elif hours_to_due <= 72:
                scores.append(0.3)
            else:
                scores.append(0.0)
        return max(scores, default=0.0)

