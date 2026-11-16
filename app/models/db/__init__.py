"""SQLAlchemy ORM models for ReOrch 智策."""

from app.models.db.audit_logs import AuditLog
from app.models.db.candidate_plans import CandidatePlan
from app.models.db.case_records import CaseRecord
from app.models.db.case_templates import CaseTemplate
from app.models.db.decision_records import DecisionRecord
from app.models.db.entity_versions import EntityVersion
from app.models.db.execution_results import ExecutionResult
from app.models.db.impact_reports import ImpactReport
from app.models.db.incidents import Incident
from app.models.db.outbox_events import OutboxEvent
from app.models.db.preference_profiles import PreferenceProfile
from app.models.db.production_core import (
    MaterialRequirement,
    Operation,
    OperationAlternativeResource,
    OperationPrecedenceEdge,
    Resource,
    ResourceCalendar,
    ResourceCapability,
    WorkOrder,
    Workshop,
)
from app.models.db.schedule_fact import (
    CandidatePlanOperation,
    PlanRecommendation,
    ScheduleSnapshotOperation,
    SolverRun,
    WritebackJob,
)
from app.models.db.schedule_snapshots import ScheduleSnapshot
from app.models.db.solver_policy_versions import SolverPolicyVersion

__all__ = [
    "AuditLog",
    "CandidatePlan",
    "CandidatePlanOperation",
    "CaseRecord",
    "CaseTemplate",
    "DecisionRecord",
    "EntityVersion",
    "ExecutionResult",
    "ImpactReport",
    "Incident",
    "MaterialRequirement",
    "Operation",
    "OperationAlternativeResource",
    "OperationPrecedenceEdge",
    "OutboxEvent",
    "PlanRecommendation",
    "PreferenceProfile",
    "Resource",
    "ResourceCalendar",
    "ResourceCapability",
    "ScheduleSnapshot",
    "ScheduleSnapshotOperation",
    "SolverPolicyVersion",
    "SolverRun",
    "WorkOrder",
    "Workshop",
    "WritebackJob",
]
