"""Outbound dispatch models: shipments, vehicles, routes.

Dispatch sits downstream of the production schedule. A shipment cannot leave
before its work order is complete, so a recovery plan that changes completion
times also changes which deliveries can still be made on time.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from app.models.base import ReOrchModel


class DispatchStop(ReOrchModel):
    """One delivery. ``work_order_id`` ties its release to production."""

    shipment_id: str
    work_order_id: str | None = None
    customer: str
    x_km: float
    y_km: float
    demand: float = Field(default=1.0, ge=0)
    window_start: datetime
    window_end: datetime
    service_minutes: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def _window_is_ordered(self) -> DispatchStop:
        if self.window_end < self.window_start:
            raise ValueError(f"shipment {self.shipment_id}: window ends before it starts")
        return self


class DispatchVehicle(ReOrchModel):
    vehicle_id: str
    capacity: float = Field(gt=0)
    shift_start: datetime
    shift_end: datetime


class DispatchCostWeights(ReOrchModel):
    """Penalty rates divided by cost per km (all in kilometre-equivalents)."""

    late: float = Field(default=5.0, ge=0, allow_inf_nan=False)
    overtime: float = Field(default=5.0, ge=0, allow_inf_nan=False)
    vehicle: float = Field(default=50.0, ge=0, allow_inf_nan=False)
    unserved: float = Field(default=5000.0, ge=0, allow_inf_nan=False)


class DispatchSnapshot(ReOrchModel):
    """Shipments and vehicles for one dispatch horizon. Distances are planar."""

    dispatch_snapshot_id: UUID = Field(default_factory=uuid4)
    captured_at: datetime
    depot_x_km: float = 0.0
    depot_y_km: float = 0.0
    speed_kmh: float = Field(default=40.0, gt=0)
    loading_minutes: int = Field(default=0, ge=0)
    cost_weights: DispatchCostWeights = Field(default_factory=DispatchCostWeights)
    stops: list[DispatchStop] = Field(default_factory=list)
    vehicles: list[DispatchVehicle] = Field(default_factory=list)


class RouteStop(ReOrchModel):
    shipment_id: str
    customer: str
    arrival: datetime
    service_start: datetime
    departure: datetime
    wait_minutes: float = 0.0
    late_minutes: float = 0.0


class VehicleRoute(ReOrchModel):
    vehicle_id: str
    depart_at: datetime
    return_at: datetime
    distance_km: float
    load: float
    overtime_minutes: float = 0.0
    stops: list[RouteStop] = Field(default_factory=list)


class DispatchPlan(ReOrchModel):
    """Routes for one set of shipment release times."""

    label: str
    source_plan_id: str | None = None
    is_recommended: bool = False
    routes: list[VehicleRoute] = Field(default_factory=list)
    unserved_shipment_ids: list[str] = Field(default_factory=list)
    vehicles_used: int = 0
    total_distance_km: float = 0.0
    late_stop_count: int = 0
    total_late_minutes: float = 0.0
    overtime_minutes: float = 0.0
    on_time_rate: float = 1.0
    cost: float = 0.0
    held_back_shipment_ids: list[str] = Field(default_factory=list)


class DispatchImpact(ReOrchModel):
    """Delivery outcome of each candidate recovery plan, next to the original."""

    incident_id: UUID
    dispatch_snapshot_id: UUID
    plans: list[DispatchPlan] = Field(default_factory=list)
