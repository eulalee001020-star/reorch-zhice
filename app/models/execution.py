"""Execution-related Pydantic models for the ReOrch system.

Defines ExecutionResult for tracking actual vs planned execution
outcomes, and re-exports WritebackStatus from enums for convenience.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.base import ReOrchModel
from app.models.enums import WritebackStatus

# Re-export for convenience so consumers can do:
#   from app.models.execution import WritebackStatus
__all__ = ["ExecutionResult", "WritebackStatus"]


class ExecutionResult(ReOrchModel):
    """Actual execution outcome linked back to a DecisionRecord.

    Captures planned vs actual completion times, OTD, resource
    utilisation, and deviation percentage for closed-loop tracking.
    """

    incident_id: UUID
    decision_record_id: UUID
    actual_completion_times: dict[str, datetime] = Field(default_factory=dict)
    planned_completion_times: dict[str, datetime] = Field(default_factory=dict)
    actual_otd: float
    actual_resource_utilization: float
    deviation_percentage: float
