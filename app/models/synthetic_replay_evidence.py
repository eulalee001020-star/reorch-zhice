"""Synthetic replay evidence pack models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.base import ReOrchModel


SyntheticReplayRow = dict[str, str | int | float | bool | None]


class SyntheticScenarioPack(ReOrchModel):
    scenario_id: str
    scenario_summary: SyntheticReplayRow = Field(default_factory=dict)
    historical_anomaly_cases: list[SyntheticReplayRow] = Field(default_factory=list)
    planner_decisions: list[SyntheticReplayRow] = Field(default_factory=list)
    execution_feedback: list[SyntheticReplayRow] = Field(default_factory=list)
    hidden_rules_freeze_logic: list[SyntheticReplayRow] = Field(default_factory=list)
    counterfactual_policy_matrix: list[SyntheticReplayRow] = Field(default_factory=list)
    field_mapping: list[SyntheticReplayRow] = Field(default_factory=list)
    data_readiness_report: list[SyntheticReplayRow] = Field(default_factory=list)


class SyntheticScenarioEvidenceMetrics(ReOrchModel):
    scenario_id: str
    evidence_level: Literal["synthetic_shadow_ready", "synthetic_replay_ready", "blocked"]
    incident_count: int = 0
    planner_decision_count: int = 0
    execution_feedback_count: int = 0
    hidden_rule_count: int = 0
    policy_matrix_cell_count: int = 0
    matched_decision_rate: float = 0.0
    matched_feedback_rate: float = 0.0
    planner_accept_or_tweak_rate: float = 0.0
    reference_or_reject_rate: float = 0.0
    average_candidate_generation_time_min: float = 0.0
    average_manual_baseline_decision_time_min: float = 0.0
    average_decision_time_saved_min: float = 0.0
    average_delay_reduction_min: float = 0.0
    average_trial_reduction: float = 0.0
    audit_complete_rate: float = 0.0
    secondary_anomaly_rate: float = 0.0
    medium_or_high_confidence_policy_cells: int = 0
    readiness_score: float = 0.0
    can_run_solver_replay: bool = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SyntheticReplayEvidenceResponse(ReOrchModel):
    pack_id: str
    scenario_metrics: list[SyntheticScenarioEvidenceMetrics]
    total_incident_count: int = 0
    total_planner_decision_count: int = 0
    total_execution_feedback_count: int = 0
    can_run_solver_replay: bool = False
    required_next_tables_for_solver: list[str] = Field(default_factory=list)
    claim_boundary: str
