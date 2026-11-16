"""Versioned classification of constraints used by feasibility restoration."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.feasibility_restoration import RecoveryActionType


@dataclass(frozen=True)
class ConstraintAssumptionSpec:
    family: str
    category: str
    must_remain_satisfied: bool
    direct_relaxation: str
    recovery_action_types: tuple[RecoveryActionType, ...]


class ConstraintAssumptionRegistry:
    """Single source of truth for hard and policy-gated constraint families."""

    version = "1.0"

    def __init__(self) -> None:
        specs = [
            _hard("safety_interlock", "safety", ("safe_hold",)),
            _hard("qms_release", "quality", ("safe_hold",)),
            _hard("quality_hold", "quality", ("safe_hold",)),
            _hard("batch_genealogy", "quality", ("safe_hold",)),
            _hard("operation_precedence", "physics", ("defer_work_order", "safe_hold")),
            _hard(
                "equipment_capability",
                "physics",
                ("activate_outsourcing", "defer_work_order", "safe_hold"),
            ),
            _hard("schedule_integrity", "physics", ("safe_hold",)),
            _hard("source_authority", "governance", ("safe_hold",)),
            _hard(
                "material_availability",
                "physical_supply",
                (
                    "activate_substitute_material",
                    "activate_outsourcing",
                    "defer_work_order",
                    "safe_hold",
                ),
            ),
            _hard(
                "tooling_capacity",
                "physical_capacity",
                ("defer_work_order", "safe_hold"),
            ),
            _hard(
                "labor_skill_capacity",
                "qualified_capacity",
                ("open_overtime_window", "defer_work_order", "safe_hold"),
            ),
            _hard(
                "transport_amr_capacity",
                "physical_capacity",
                ("defer_work_order", "safe_hold"),
            ),
            _hard(
                "buffer_capacity",
                "physical_capacity",
                ("defer_work_order", "safe_hold"),
            ),
            _policy_gated(
                "planning_freeze",
                "planning_governance",
                ("release_planning_freeze", "defer_work_order", "safe_hold"),
            ),
            _policy_gated(
                "operation_deadline",
                "service_commitment",
                ("relax_operation_deadline", "defer_work_order", "safe_hold"),
            ),
            _policy_gated(
                "resource_calendar",
                "capacity_commitment",
                ("open_overtime_window", "defer_work_order", "safe_hold"),
            ),
            _policy_gated(
                "demand_commitment",
                "service_commitment",
                ("defer_work_order", "safe_hold"),
            ),
        ]
        self._specs = {item.family: item for item in specs}

    def get(self, family: str) -> ConstraintAssumptionSpec | None:
        return self._specs.get(family)

    def all(self) -> list[ConstraintAssumptionSpec]:
        return list(self._specs.values())

    def action_is_registered(
        self, family: str, action_type: RecoveryActionType
    ) -> bool:
        spec = self.get(family)
        return spec is not None and action_type in spec.recovery_action_types


def _hard(
    family: str,
    category: str,
    actions: tuple[RecoveryActionType, ...],
) -> ConstraintAssumptionSpec:
    return ConstraintAssumptionSpec(
        family=family,
        category=category,
        must_remain_satisfied=True,
        direct_relaxation="forbidden",
        recovery_action_types=actions,
    )


def _policy_gated(
    family: str,
    category: str,
    actions: tuple[RecoveryActionType, ...],
) -> ConstraintAssumptionSpec:
    return ConstraintAssumptionSpec(
        family=family,
        category=category,
        must_remain_satisfied=False,
        direct_relaxation="versioned_policy_and_approval_required",
        recovery_action_types=actions,
    )
