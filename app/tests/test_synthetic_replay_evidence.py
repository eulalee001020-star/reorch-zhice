"""Tests for synthetic replay evidence pack evaluator."""

from app.models.synthetic_replay_evidence import SyntheticScenarioPack
from app.services.synthetic_replay_evidence import SyntheticReplayEvidenceEvaluator


def test_synthetic_replay_evidence_scores_roi_proxy_but_blocks_solver_replay() -> None:
    scenario = SyntheticScenarioPack(
        scenario_id="CNC_AUTO_FJSP",
        historical_anomaly_cases=[
            {"incident_id": f"INC-{idx:02d}"} for idx in range(10)
        ],
        planner_decisions=[
            {
                "incident_id": f"INC-{idx:02d}",
                "planner_action": "accepted" if idx < 8 else "rejected",
            }
            for idx in range(10)
        ],
        execution_feedback=[
            {
                "incident_id": f"INC-{idx:02d}",
                "candidate_generation_time_min": 5,
                "manual_baseline_decision_time_min": 55,
                "delay_before_min": 120,
                "delay_after_min": 40,
                "planner_trial_count_before": 7,
                "planner_trial_count_after": 2,
                "audit_complete": True,
                "secondary_anomaly": idx == 0,
            }
            for idx in range(10)
        ],
        hidden_rules_freeze_logic=[{"rule_id": "RULE-1"}],
        counterfactual_policy_matrix=[
            {"confidence_level": "medium"},
            {"confidence_level": "low"},
        ],
        data_readiness_report=[{"readiness_score": 0.86}],
    )

    response = SyntheticReplayEvidenceEvaluator().evaluate(
        pack_id="three_industry_synthetic_v0_1",
        scenarios=[scenario],
    )

    metric = response.scenario_metrics[0]
    assert metric.evidence_level == "synthetic_shadow_ready"
    assert metric.average_decision_time_saved_min == 50
    assert metric.average_delay_reduction_min == 80
    assert metric.audit_complete_rate == 1.0
    assert metric.secondary_anomaly_rate == 0.1
    assert metric.can_run_solver_replay is False
    assert response.can_run_solver_replay is False
    assert "work_orders" in response.required_next_tables_for_solver


def test_synthetic_replay_evidence_blocks_when_decisions_are_missing() -> None:
    scenario = SyntheticScenarioPack(
        scenario_id="BAD",
        historical_anomaly_cases=[
            {"incident_id": f"INC-{idx:02d}"} for idx in range(10)
        ],
        execution_feedback=[{"incident_id": "INC-01"}],
    )

    response = SyntheticReplayEvidenceEvaluator().evaluate(
        pack_id="bad",
        scenarios=[scenario],
    )

    metric = response.scenario_metrics[0]
    assert metric.evidence_level == "blocked"
    assert "missing_planner_decisions" in metric.blockers
