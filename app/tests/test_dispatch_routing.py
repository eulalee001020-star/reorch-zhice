"""Routing solver: checked against enumeration and against OR-Tools routing."""

from __future__ import annotations

import math
import random

import pytest
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.services.dispatch.routing import (
    Node,
    Problem,
    Vehicle,
    Weights,
    evaluate_route,
    route_cost,
    solution_cost,
    solve,
    solve_exact,
)


def _random_problem(seed: int, size: int, vehicles: int, *, capacity: float = 10.0) -> Problem:
    rng = random.Random(seed)
    nodes = []
    for index in range(size):
        ready = rng.uniform(0, 240)
        nodes.append(
            Node(
                key=f"S{index}",
                x=rng.uniform(-20, 20),
                y=rng.uniform(-20, 20),
                demand=rng.choice([1, 2, 3]),
                ready=ready,
                due=ready + rng.uniform(60, 240),
                service=10,
                release=rng.choice([0, 0, 30, 90]),
            )
        )
    fleet = tuple(Vehicle(f"V{i}", capacity, 0, 600) for i in range(vehicles))
    return Problem(nodes=tuple(nodes), vehicles=fleet)


# ── route simulation ────────────────────────────────────────────────


def test_route_waits_for_the_window_and_counts_lateness() -> None:
    problem = Problem(
        nodes=(
            Node("early", 40, 0, 1, ready=120, due=180, service=10),
            Node("tight", 40, 30, 1, ready=0, due=100, service=10),
        ),
        vehicles=(Vehicle("V", 10, 0, 600),),
        speed_kmh=40,
    )
    result = evaluate_route(problem, problem.vehicles[0], [0, 1])
    first, second = result.stops
    # 40 km at 40 km/h is 60 minutes; the window opens at 120.
    assert (first.arrival, first.service_start, first.wait) == (60, 120, 60)
    # Leaves at 130, 30 km takes 45 minutes: arrives 175, which is 75 late.
    assert second.arrival == 175
    assert result.late == 75
    assert result.late_stops == 1
    assert result.distance == pytest.approx(40 + 30 + 50)


def test_vehicle_leaves_when_its_last_shipment_is_released() -> None:
    problem = Problem(
        nodes=(
            Node("ready", 10, 0, 1, ready=0, due=600, service=0),
            Node("late-release", 20, 0, 1, ready=0, due=600, service=0, release=200),
        ),
        vehicles=(Vehicle("V", 10, 30, 600),),
        loading_minutes=15,
    )
    assert evaluate_route(problem, problem.vehicles[0], [0]).depart == 45
    assert evaluate_route(problem, problem.vehicles[0], [0, 1]).depart == 215


def test_overloaded_route_has_no_cost() -> None:
    problem = Problem(
        nodes=(Node("a", 1, 0, 6, 0, 600, 0), Node("b", 2, 0, 6, 0, 600, 0)),
        vehicles=(Vehicle("V", 10, 0, 600),),
    )
    assert route_cost(problem, problem.vehicles[0], [0, 1]) == math.inf


# ── optimality on small problems ────────────────────────────────────


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_search_matches_enumeration_on_small_problems(seed: int) -> None:
    problem = _random_problem(seed, size=6, vehicles=2)
    exact = solve_exact(problem)
    found = solve(problem, iterations=400, seed=11)
    assert found.unassigned == []
    assert found.cost == pytest.approx(exact.cost, rel=1e-9)


def test_search_is_deterministic_for_a_seed() -> None:
    problem = _random_problem(21, size=20, vehicles=4)
    first = solve(problem, iterations=300, seed=5)
    second = solve(problem, iterations=300, seed=5)
    assert first.routes == second.routes
    assert first.cost == second.cost


def test_reported_cost_is_the_cost_of_the_returned_routes() -> None:
    problem = _random_problem(8, size=18, vehicles=4)
    found = solve(problem, iterations=300, seed=3)
    assert found.cost == pytest.approx(solution_cost(problem, found.routes, found.unassigned))
    served = [i for route in found.routes for i in route]
    assert sorted(served + found.unassigned) == list(range(18))


# ── behaviour ───────────────────────────────────────────────────────


def test_shipment_that_fits_no_vehicle_is_left_unserved() -> None:
    problem = Problem(
        nodes=(Node("big", 5, 0, 50, 0, 600, 0), Node("ok", 5, 5, 1, 0, 600, 0)),
        vehicles=(Vehicle("V", 10, 0, 600),),
    )
    found = solve(problem, iterations=50)
    assert found.unassigned == [0]
    assert found.routes == [[1]]


def test_late_release_is_carried_separately_when_that_is_cheaper() -> None:
    """One shipment is released hours late. Holding the whole truck for it
    would make the other deliveries late, so it travels on its own."""
    nodes = (
        *tuple(Node(f"S{i}", 10 + i, 0, 1, ready=0, due=120, service=5) for i in range(4)),
        Node("held", 12, 3, 1, ready=0, due=600, service=5, release=300),
    )
    problem = Problem(nodes=nodes, vehicles=(Vehicle("A", 10, 0, 900), Vehicle("B", 10, 0, 900)))
    found = solve(problem, iterations=300)
    route_of_held = next(route for route in found.routes if 4 in route)
    assert route_of_held == [4]
    for vehicle, route in zip(problem.vehicles, found.routes, strict=True):
        assert evaluate_route(problem, vehicle, route).late == 0


def test_no_vehicles_leaves_everything_at_the_dock() -> None:
    problem = Problem(nodes=(Node("a", 1, 1, 1, 0, 10, 0),), vehicles=())
    found = solve(problem)
    assert found.unassigned == [0]
    assert found.cost == Weights().unserved


# ── cross-check against an independent solver ───────────────────────


def _ortools_distance(problem: Problem, time_limit_seconds: int = 2) -> float | None:
    """Total distance from OR-Tools routing with hard windows and no release times."""
    size = len(problem.nodes)
    scale = 100
    manager = pywrapcp.RoutingIndexManager(size + 1, len(problem.vehicles), 0)
    routing = pywrapcp.RoutingModel(manager)

    def point(index: int) -> int:
        return manager.IndexToNode(index) - 1

    def distance(a: int, b: int) -> int:
        return round(problem.distance(point(a), point(b)) * scale)

    def travel_time(a: int, b: int) -> int:
        origin = point(a)
        service = problem.nodes[origin].service if origin >= 0 else 0
        return round((problem.minutes(problem.distance(origin, point(b))) + service) * scale)

    def demand(a: int) -> int:
        origin = point(a)
        return round(problem.nodes[origin].demand) if origin >= 0 else 0

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(distance))
    routing.AddDimension(
        routing.RegisterTransitCallback(travel_time), 10_000 * scale, 10_000 * scale, False, "Time"
    )
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(demand),
        0,
        [round(v.capacity) for v in problem.vehicles],
        True,
        "Load",
    )
    time_dimension = routing.GetDimensionOrDie("Time")
    for index, node in enumerate(problem.nodes):
        time_dimension.CumulVar(manager.NodeToIndex(index + 1)).SetRange(
            round(node.ready * scale), round(node.due * scale)
        )
    for vehicle in range(len(problem.vehicles)):
        routing.SetFixedCostOfVehicle(round(problem.weights.vehicle * scale), vehicle)
    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    parameters.time_limit.FromSeconds(time_limit_seconds)
    solution = routing.SolveWithParameters(parameters)
    return solution.ObjectiveValue() / scale if solution else None


@pytest.mark.parametrize("seed", [31, 32])
def test_search_is_competitive_with_ortools_routing(seed: int) -> None:
    """Same instance, hard windows, no release times: an independent solver
    with a two-second budget should not beat the search by more than 3 %."""
    base = _random_problem(seed, size=25, vehicles=6, capacity=12)
    problem = Problem(
        nodes=tuple(
            Node(n.key, n.x, n.y, n.demand, n.ready, n.due + 200, n.service) for n in base.nodes
        ),
        vehicles=base.vehicles,
    )
    reference = _ortools_distance(problem)
    assert reference is not None
    found = solve(problem, iterations=1500, seed=9)
    assert found.unassigned == []
    late = sum(
        evaluate_route(problem, v, r).late
        for v, r in zip(problem.vehicles, found.routes, strict=True)
    )
    assert late == 0
    assert found.cost <= reference * 1.03
