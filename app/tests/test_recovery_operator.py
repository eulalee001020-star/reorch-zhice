"""Tests for non-equipment recovery operators."""

from app.models.recovery_operator import (
    RecoveryOperatorReplayCase,
    RecoveryOperatorRequest,
)
from app.services.recovery_operator import NonEquipmentRecoveryOperatorService


def test_non_equipment_operators_cover_required_incident_types() -> None:
    service = NonEquipmentRecoveryOperatorService()

    cases = [
        RecoveryOperatorReplayCase(
            request=RecoveryOperatorRequest(
                case_id="MAT-1",
                incident_type="material_shortage",
                affected_operation_id="OP-1",
                context={
                    "material_id": "AL-7075",
                    "material_available_at": "2026-07-06T14:00:00+08:00",
                },
            ),
            manual_accepted_operator_id="material_wait_or_partial_release",
        ),
        RecoveryOperatorReplayCase(
            request=RecoveryOperatorRequest(
                case_id="URG-1",
                incident_type="urgent_order_insert",
                affected_operation_id="OP-2",
                context={
                    "rush_order_id": "WO-RUSH",
                    "due_time": "2026-07-06T18:00:00+08:00",
                    "candidate_displaced_work_order_id": "WO-LOW",
                    "customer_service_approval": True,
                },
            ),
            manual_accepted_operator_id="urgent_priority_swap",
        ),
        RecoveryOperatorReplayCase(
            request=RecoveryOperatorRequest(
                case_id="QH-1",
                incident_type="quality_hold",
                affected_operation_id="OP-3",
                context={"hold_id": "QH-88", "quality_owner": "qa-lead"},
            ),
            manual_accepted_operator_id="quality_hold_freeze_and_resequence",
        ),
        RecoveryOperatorReplayCase(
            request=RecoveryOperatorRequest(
                case_id="TOOL-1",
                incident_type="tooling_conflict",
                affected_operation_id="OP-4",
                context={
                    "tooling_id": "FIX-01",
                    "conflicting_operation_id": "OP-9",
                    "alternative_tooling_ids": ["FIX-01B"],
                },
            ),
            manual_accepted_operator_id="tooling_reallocation",
        ),
        RecoveryOperatorReplayCase(
            request=RecoveryOperatorRequest(
                case_id="LAB-1",
                incident_type="labor_shortage",
                affected_operation_id="OP-5",
                context={
                    "skill_code": "cnc_operator",
                    "required_headcount": 2,
                    "alternate_team_ids": ["TEAM-B"],
                },
            ),
            manual_accepted_operator_id="labor_skill_pool_reassignment",
        ),
    ]

    summary = service.replay_batch(cases)

    assert summary.replayed_case_count == 5
    assert summary.cases_with_gate_pass == 5
    assert summary.top_n_manual_coverage_count == 5
    assert summary.gate_pass_rate == 1.0
    assert summary.top_n_manual_coverage_rate == 1.0
    assert all(response.can_enter_planner_review for response in summary.responses)


def test_operator_gate_blocks_missing_required_evidence() -> None:
    response = NonEquipmentRecoveryOperatorService().run(
        RecoveryOperatorRequest(
            case_id="MAT-BLOCK",
            incident_type="material_shortage",
            affected_operation_id="OP-1",
            context={"material_id": "AL-7075"},
        )
    )

    assert response.can_enter_planner_review is False
    assert response.recommended_operator_id is None
    blockers = {
        blocker
        for candidate in response.candidates
        for blocker in candidate.gate_report.hard_blockers
    }
    assert "missing_material_recovery_evidence" in blockers
    assert "substitution_not_approved" in blockers
