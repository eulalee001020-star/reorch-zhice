"""Case Library — enterprise asset layer for decision case archival,
similarity retrieval, preference learning, and template suggestion.

Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.10, 9.11, 9.12

Provides:
- create_case(): auto-create CaseRecord from DecisionRecord + ExecutionResult
- find_similar_cases(): cosine similarity search (threshold 0.8)
- update_preference(): update PreferenceProfile on Override
- get_preference_profile(): retrieve planner preference profile
- suggest_template(): suggest CaseTemplate when case count > 10 with similar patterns
- get_strategy_effectiveness(): track rule/neighborhood/repair strategy effectiveness
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models.case import CaseRecord, CaseTemplate, PreferenceProfile
from app.models.decision import DecisionRecord
from app.models.execution import ExecutionResult

logger = logging.getLogger(__name__)

# Similarity threshold for case retrieval (Req 9.3)
_SIMILARITY_THRESHOLD: float = 0.8

# Minimum case count before suggesting template (Req 9.2)
_TEMPLATE_SUGGESTION_THRESHOLD: int = 10

# Default strategy weights for new PreferenceProfile
_DEFAULT_STRATEGY_WEIGHTS: dict[str, float] = {
    "wait_and_repair": 0.33,
    "local_repair": 0.34,
    "global_reschedule": 0.33,
}

# Override weight adjustment factor
_OVERRIDE_WEIGHT_ADJUSTMENT: float = 0.05


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _build_feature_vector(incident_features: dict) -> list[float]:
    """Build a simple feature vector from incident features for MVP similarity.

    Extracts numeric features from the incident_features dict.
    """
    keys = sorted(incident_features.keys())
    vector: list[float] = []
    for key in keys:
        val = incident_features.get(key)
        if isinstance(val, (int, float)):
            vector.append(float(val))
        elif isinstance(val, bool):
            vector.append(1.0 if val else 0.0)
        elif isinstance(val, str):
            vector.append(float(hash(val) % 1000) / 1000.0)
    return vector if vector else [0.0]


class CaseLibrary:
    """Case Library service for enterprise asset layer.

    Uses in-memory stores for MVP. Production would use PostgreSQL + pgvector.
    """

    def __init__(self) -> None:
        self._case_store: dict[str, CaseRecord] = {}
        self._preference_store: dict[str, PreferenceProfile] = {}

    # ── Case creation (Req 9.1, 9.10) ──────────────────────────────

    async def create_case(
        self,
        decision_record: DecisionRecord,
        execution_result: ExecutionResult,
    ) -> CaseRecord:
        """Auto-create a case record from DecisionRecord + ExecutionResult.

        Records the full chain: incident → strategy → rule → neighborhood →
        repair → execution result (Req 9.10).
        """
        case = CaseRecord(
            case_id=uuid4(),
            incident_features={
                "incident_id": str(decision_record.incident_id),
                "strategy_type": decision_record.strategy_type,
                "impact_summary": decision_record.impact_report_summary,
            },
            impact_scope={
                "all_candidate_plan_ids": [
                    str(pid) for pid in decision_record.all_candidate_plan_ids
                ],
                "recommended_plan_id": str(decision_record.recommended_plan_id),
            },
            strategy_type=decision_record.strategy_type,
            confirmed_plan_summary=(
                f"Plan {decision_record.confirmed_plan_id} confirmed by "
                f"{decision_record.confirmed_by}"
            ),
            execution_result=execution_result,
            is_override=decision_record.is_override,
            override_reason=decision_record.override_reason,
            rule_selection=decision_record.solver_chain.rule_selection,
            neighborhood_selection=decision_record.solver_chain.neighborhood_selection,
            repair_policy=decision_record.solver_chain.repair_policy,
            solver_chain=decision_record.solver_chain,
            created_at=datetime.now(tz=timezone.utc),
            embedding_vector=_build_feature_vector({
                "strategy_type": decision_record.strategy_type,
                "is_override": decision_record.is_override,
            }),
        )

        self._case_store[str(case.case_id)] = case
        from app.services.persistence import persist_case_record

        await persist_case_record(case, user_id=decision_record.confirmed_by)

        logger.info(
            "Case created: %s for incident %s (override=%s)",
            case.case_id,
            decision_record.incident_id,
            case.is_override,
        )

        # Check template suggestion (Req 9.2)
        suggestion = self._check_template_suggestion(case)
        if suggestion:
            logger.info(
                "Template suggestion: %d similar cases found for strategy '%s'. "
                "Consider creating a CaseTemplate.",
                suggestion["similar_count"],
                suggestion["strategy_type"],
            )

        return case

    # ── Similarity search (Req 9.3) ────────────────────────────────

    async def find_similar_cases(
        self,
        incident_features: dict,
        top_k: int = 5,
        threshold: float = _SIMILARITY_THRESHOLD,
    ) -> list[tuple[CaseRecord, float]]:
        """Find similar cases using cosine similarity on feature vectors.

        MVP: simple feature-based similarity. Production: pgvector.
        Returns list of (CaseRecord, similarity_score) sorted by similarity desc.
        """
        query_vector = _build_feature_vector(incident_features)
        scored: list[tuple[CaseRecord, float]] = []

        for case in self._case_store.values():
            case_vector = case.embedding_vector or _build_feature_vector(
                case.incident_features
            )
            sim = _cosine_similarity(query_vector, case_vector)
            if sim >= threshold:
                scored.append((case, round(sim, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # ── Preference update (Req 9.4, 9.5) ──────────────────────────

    async def update_preference(
        self,
        planner_id: str,
        decision_record: DecisionRecord,
    ) -> PreferenceProfile:
        """Update PreferenceProfile when an Override occurs.

        Adjusts strategy weights based on the override action (Req 9.4).
        Maintains per-planner preference profile (Req 9.5).
        """
        profile = self._get_or_create_profile(planner_id)

        if decision_record.is_override:
            # Record override in history
            profile.override_history.append({
                "incident_id": str(decision_record.incident_id),
                "original_strategy": decision_record.strategy_type,
                "override_reason": decision_record.override_reason,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            })

            # Decrease weight for the overridden strategy, increase others
            overridden = decision_record.strategy_type
            for strategy in profile.strategy_preferences:
                if strategy == overridden:
                    profile.strategy_preferences[strategy] = max(
                        0.0,
                        profile.strategy_preferences[strategy]
                        - _OVERRIDE_WEIGHT_ADJUSTMENT,
                    )
                else:
                    profile.strategy_preferences[strategy] = min(
                        1.0,
                        profile.strategy_preferences[strategy]
                        + _OVERRIDE_WEIGHT_ADJUSTMENT / 2,
                    )

        if decision_record.is_manual_adjusted:
            profile.adjustment_patterns.append({
                "incident_id": str(decision_record.incident_id),
                "strategy_type": decision_record.strategy_type,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            })

        profile.updated_at = datetime.now(tz=timezone.utc)
        self._preference_store[planner_id] = profile

        logger.info(
            "Preference updated for planner %s: weights=%s",
            planner_id,
            profile.strategy_preferences,
        )

        return profile

    # ── Preference retrieval (Req 9.5, 9.6) ───────────────────────

    def get_preference_profile(self, planner_id: str) -> PreferenceProfile:
        """Retrieve a planner's preference profile."""
        return self._get_or_create_profile(planner_id)

    # ── Strategy effectiveness tracking (Req 9.11, 9.12) ──────────

    def get_strategy_effectiveness(self) -> dict[str, dict]:
        """Compute effectiveness stats for rule/neighborhood/repair combinations.

        Returns stats grouped by strategy_type with counts and override rates.
        """
        stats: dict[str, dict] = {}

        for case in self._case_store.values():
            key = case.strategy_type
            if key not in stats:
                stats[key] = {
                    "total": 0,
                    "overrides": 0,
                    "rules": {},
                    "neighborhoods": {},
                    "repair_policies": {},
                }

            entry = stats[key]
            entry["total"] += 1
            if case.is_override:
                entry["overrides"] += 1

            # Track rule effectiveness
            rule = case.rule_selection
            if rule not in entry["rules"]:
                entry["rules"][rule] = {"count": 0, "overrides": 0}
            entry["rules"][rule]["count"] += 1
            if case.is_override:
                entry["rules"][rule]["overrides"] += 1

            # Track neighborhood effectiveness
            nbr = case.neighborhood_selection
            if nbr not in entry["neighborhoods"]:
                entry["neighborhoods"][nbr] = {"count": 0, "overrides": 0}
            entry["neighborhoods"][nbr]["count"] += 1
            if case.is_override:
                entry["neighborhoods"][nbr]["overrides"] += 1

            # Track repair policy effectiveness
            rp = case.repair_policy
            if rp not in entry["repair_policies"]:
                entry["repair_policies"][rp] = {"count": 0, "overrides": 0}
            entry["repair_policies"][rp]["count"] += 1
            if case.is_override:
                entry["repair_policies"][rp]["overrides"] += 1

        # Compute adoption rates
        for key, entry in stats.items():
            total = entry["total"]
            entry["adoption_rate"] = (
                (total - entry["overrides"]) / total if total > 0 else 0.0
            )

        return stats

    # ── Case listing ───────────────────────────────────────────────

    def list_cases(
        self,
        incident_type: str | None = None,
        strategy_type: str | None = None,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        is_override: bool | None = None,
    ) -> list[CaseRecord]:
        """List cases with optional filters."""
        results: list[CaseRecord] = []
        for case in self._case_store.values():
            if strategy_type and case.strategy_type != strategy_type:
                continue
            if incident_type:
                case_type = case.incident_features.get("incident_type")
                if case_type and case_type != incident_type:
                    continue
            if time_from and case.created_at < time_from:
                continue
            if time_to and case.created_at > time_to:
                continue
            if is_override is not None and case.is_override != is_override:
                continue
            results.append(case)
        return sorted(results, key=lambda c: c.created_at, reverse=True)

    def get_case(self, case_id: UUID) -> CaseRecord | None:
        """Get a single case by ID."""
        return self._case_store.get(str(case_id))

    # ── Private helpers ────────────────────────────────────────────

    def _get_or_create_profile(self, planner_id: str) -> PreferenceProfile:
        """Get existing profile or create a new one with default weights."""
        if planner_id in self._preference_store:
            return self._preference_store[planner_id]

        profile = PreferenceProfile(
            planner_id=planner_id,
            strategy_preferences=dict(_DEFAULT_STRATEGY_WEIGHTS),
            adjustment_patterns=[],
            override_history=[],
            updated_at=datetime.now(tz=timezone.utc),
        )
        self._preference_store[planner_id] = profile
        return profile

    def _check_template_suggestion(
        self, new_case: CaseRecord
    ) -> dict | None:
        """Check if case count > 10 with similar patterns → suggest template (Req 9.2)."""
        same_strategy = [
            c
            for c in self._case_store.values()
            if c.strategy_type == new_case.strategy_type
        ]

        if len(same_strategy) > _TEMPLATE_SUGGESTION_THRESHOLD:
            return {
                "strategy_type": new_case.strategy_type,
                "similar_count": len(same_strategy),
                "suggestion": "Consider creating a CaseTemplate for this pattern.",
            }
        return None
