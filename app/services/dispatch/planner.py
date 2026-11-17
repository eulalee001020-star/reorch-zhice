"""Plan outbound routes for a given set of work order completion times."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from app.models.dispatch import (
    DispatchPlan,
    DispatchSnapshot,
    DispatchStop,
    DispatchVehicle,
    RouteStop,
    VehicleRoute,
)
from app.models.schedule import WorkOrder
from app.services.dispatch.routing import (
    Node,
    Problem,
    Vehicle,
    evaluate_route,
    solve,
)


def completion_by_work_order(work_orders: list[WorkOrder]) -> dict[str, datetime]:
    """When each work order's last operation ends."""
    return {
        work_order.work_order_id: max(op.end_time for op in work_order.operations)
        for work_order in work_orders
        if work_order.operations
    }


def _minutes(moment: datetime, origin: datetime) -> float:
    return (moment - origin).total_seconds() / 60.0


def build_problem(snapshot: DispatchSnapshot, completions: dict[str, datetime]) -> Problem:
    """Express the snapshot in minutes from its capture time.

    A shipment tied to a work order is released when that work order
    completes. One with no work order, or whose work order is not in the
    schedule, is taken to be in finished-goods stock already.
    """
    origin = snapshot.captured_at
    nodes = []
    for stop in snapshot.stops:
        done = completions.get(stop.work_order_id) if stop.work_order_id else None
        nodes.append(
            Node(
                key=stop.shipment_id,
                x=stop.x_km,
                y=stop.y_km,
                demand=stop.demand,
                ready=_minutes(stop.window_start, origin),
                due=_minutes(stop.window_end, origin),
                service=float(stop.service_minutes),
                release=max(0.0, _minutes(done, origin)) if done else 0.0,
            )
        )
    vehicles = tuple(
        Vehicle(
            key=vehicle.vehicle_id,
            capacity=vehicle.capacity,
            start=_minutes(vehicle.shift_start, origin),
            end=_minutes(vehicle.shift_end, origin),
        )
        for vehicle in snapshot.vehicles
    )
    return Problem(
        nodes=tuple(nodes),
        vehicles=vehicles,
        depot=(snapshot.depot_x_km, snapshot.depot_y_km),
        speed_kmh=snapshot.speed_kmh,
        loading_minutes=float(snapshot.loading_minutes),
    )


def plan_dispatch(
    snapshot: DispatchSnapshot,
    completions: dict[str, datetime],
    *,
    label: str,
    source_plan_id: str | None = None,
    is_recommended: bool = False,
    iterations: int = 1200,
    seed: int = 7,
) -> DispatchPlan:
    """Route the snapshot's shipments given when each one is released."""
    problem = build_problem(snapshot, completions)
    solution = solve(problem, iterations=iterations, seed=seed)
    origin = snapshot.captured_at

    def moment(minutes: float) -> datetime:
        return origin + timedelta(minutes=minutes)

    routes: list[VehicleRoute] = []
    late_stops = 0
    total_late = total_distance = total_overtime = 0.0
    for vehicle, sequence in zip(problem.vehicles, solution.routes, strict=True):
        if not sequence:
            continue
        result = evaluate_route(problem, vehicle, sequence)
        stops = []
        for timing in result.stops:
            stop = snapshot.stops[timing.node]
            late = max(0.0, timing.service_start - problem.nodes[timing.node].due)
            stops.append(
                RouteStop(
                    shipment_id=stop.shipment_id,
                    customer=stop.customer,
                    arrival=moment(timing.arrival),
                    service_start=moment(timing.service_start),
                    departure=moment(timing.departure),
                    wait_minutes=round(timing.wait, 1),
                    late_minutes=round(late, 1),
                )
            )
        routes.append(
            VehicleRoute(
                vehicle_id=vehicle.key,
                depart_at=moment(result.depart),
                return_at=moment(result.finish),
                distance_km=round(result.distance, 2),
                load=result.load,
                overtime_minutes=round(result.overtime, 1),
                stops=stops,
            )
        )
        late_stops += result.late_stops
        total_late += result.late
        total_distance += result.distance
        total_overtime += result.overtime

    served = sum(len(route.stops) for route in routes)
    total = len(snapshot.stops)
    return DispatchPlan(
        label=label,
        source_plan_id=source_plan_id,
        is_recommended=is_recommended,
        routes=routes,
        unserved_shipment_ids=[snapshot.stops[i].shipment_id for i in sorted(solution.unassigned)],
        vehicles_used=len(routes),
        total_distance_km=round(total_distance, 2),
        late_stop_count=late_stops,
        total_late_minutes=round(total_late, 1),
        overtime_minutes=round(total_overtime, 1),
        on_time_rate=round((served - late_stops) / total, 4) if total else 1.0,
        cost=round(solution.cost, 2),
    )


def load_dispatch_snapshot(
    directory: Path,
    *,
    captured_at: datetime,
    speed_kmh: float = 40.0,
    loading_minutes: int = 15,
) -> DispatchSnapshot:
    """Read ``shipments.csv`` and ``vehicles.csv`` from ``directory``."""

    def rows(name: str) -> list[dict[str, str]]:
        path = directory / name
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    return DispatchSnapshot(
        captured_at=captured_at,
        speed_kmh=speed_kmh,
        loading_minutes=loading_minutes,
        stops=[
            DispatchStop(
                shipment_id=row["shipment_id"],
                work_order_id=row.get("work_order_id") or None,
                customer=row["customer"],
                x_km=float(row["x_km"]),
                y_km=float(row["y_km"]),
                demand=float(row["demand"]),
                window_start=datetime.fromisoformat(row["window_start"]),
                window_end=datetime.fromisoformat(row["window_end"]),
                service_minutes=int(row.get("service_minutes") or 10),
            )
            for row in rows("shipments.csv")
        ],
        vehicles=[
            DispatchVehicle(
                vehicle_id=row["vehicle_id"],
                capacity=float(row["capacity"]),
                shift_start=datetime.fromisoformat(row["shift_start"]),
                shift_end=datetime.fromisoformat(row["shift_end"]),
            )
            for row in rows("vehicles.csv")
        ],
    )
