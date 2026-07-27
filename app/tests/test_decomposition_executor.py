"""Executable decomposition and digital-twin scale tests."""

from app.services.decomposition_executor import DecompositionExecutor
from app.services.production_digital_twin import ProductionDigitalTwinFactory


def test_joint_incidents_are_solved_together_and_independent_groups_run_parallel() -> None:
    request = ProductionDigitalTwinFactory().build_solve_request(
        200, incident_count=5, max_parallelism=2
    )

    response = DecompositionExecutor().execute(request)

    assert response.status == "feasible"
    assert any(len(group) == 2 for group in response.joint_incident_groups)
    assert response.observed_parallelism == 2
    assert response.violations == []
    assert response.final_schedule is not None
    assert "qms_release" in response.checked_constraints
    for result in response.subproblem_results:
        assert result.solver_metadata["validated_incumbent"] is True
        assert result.solver_metadata["algorithm_path"][0] == "constraint_aware_ssgs"
        assert "independent_constraint_validation" in result.solver_metadata[
            "algorithm_path"
        ]
        assert result.solver_metadata["time_to_first_feasible_ms"] >= 0
        assert result.solver_metadata["pareto_front_size"] >= 1
        assert result.solver_metadata["pareto_front"]
        assert result.solver_metadata["cp_sat_hint_applied"] is True
        assert result.solver_metadata["cp_sat_hinted_operation_count"] > 0


def test_checkpointed_subproblem_is_reused_on_resume() -> None:
    request = ProductionDigitalTwinFactory().build_solve_request(160, incident_count=4)
    executor = DecompositionExecutor()
    first = executor.execute(request)
    checkpoint = first.subproblem_results[0]

    resumed = executor.execute(
        request,
        checkpoint_results={checkpoint.subproblem_id: checkpoint},
    )

    assert resumed.status == "feasible"
    assert any(item.status == "checkpoint_reused" for item in resumed.subproblem_results)
    assert resumed.violations == []


def test_cancel_before_solve_returns_no_schedule() -> None:
    request = ProductionDigitalTwinFactory().build_solve_request(100)

    response = DecompositionExecutor().execute(request, cancel_check=lambda: True)

    assert response.status == "cancelled"
    assert response.final_schedule is None
    assert response.blockers == ["cancelled_before_solve"]


def test_1k_5k_10k_operation_digital_twin_scale_gate() -> None:
    factory = ProductionDigitalTwinFactory()
    executor = DecompositionExecutor()

    for operation_count in (1000, 5000, 10000):
        response = executor.execute(
            factory.build_solve_request(operation_count, incident_count=5)
        )
        assert response.operation_count == operation_count
        assert response.status == "feasible"
        assert response.observed_parallelism == 2
        assert response.violations == []
        assert response.evidence_fingerprint
