"""Vehicle routing with time windows, capacities and release times.

The problem is the classic VRPTW with two additions that recovery planning
needs:

* **Release times.** A shipment is only at the dock once its work order is
  complete. A vehicle leaves when the last shipment it carries is released.
* **Soft windows.** After a disruption some windows cannot be met at all. A
  late arrival is allowed and penalised, so the answer says how late instead
  of saying "infeasible".

Capacity is hard. Times are minutes from the horizon start; distances are
planar kilometres.

Cost, in kilometre-equivalents::

    distance_km
    + late_weight      * late minutes at customers
    + overtime_weight  * minutes a vehicle returns after its shift
    + vehicle_weight   * vehicles used
    + unserved_weight  * shipments left at the dock

The search is adaptive large neighbourhood search: remove a few shipments
(random, worst-placed, or related), reinsert them (cheapest or regret-2), and
accept by simulated annealing. Operator weights adapt to what has worked.
Runs are deterministic for a given seed.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from itertools import permutations


@dataclass(frozen=True)
class Node:
    key: str
    x: float
    y: float
    demand: float
    ready: float
    due: float
    service: float
    release: float = 0.0


@dataclass(frozen=True)
class Vehicle:
    key: str
    capacity: float
    start: float
    end: float


@dataclass(frozen=True)
class Weights:
    late: float = 5.0
    overtime: float = 5.0
    vehicle: float = 50.0
    unserved: float = 5000.0


@dataclass(frozen=True)
class Problem:
    nodes: tuple[Node, ...]
    vehicles: tuple[Vehicle, ...]
    depot: tuple[float, float] = (0.0, 0.0)
    speed_kmh: float = 40.0
    loading_minutes: float = 0.0
    weights: Weights = field(default_factory=Weights)

    def distance(self, a: int, b: int) -> float:
        """Kilometres between two points; -1 is the depot."""
        ax, ay = self.depot if a < 0 else (self.nodes[a].x, self.nodes[a].y)
        bx, by = self.depot if b < 0 else (self.nodes[b].x, self.nodes[b].y)
        return math.hypot(ax - bx, ay - by)

    def minutes(self, kilometres: float) -> float:
        return kilometres / self.speed_kmh * 60.0


@dataclass(frozen=True)
class StopTiming:
    node: int
    arrival: float
    service_start: float
    departure: float

    @property
    def wait(self) -> float:
        return self.service_start - self.arrival


@dataclass(frozen=True)
class RouteResult:
    distance: float
    late: float
    overtime: float
    load: float
    depart: float
    finish: float
    late_stops: int
    stops: tuple[StopTiming, ...]


@dataclass
class Solution:
    routes: list[list[int]]
    unassigned: list[int]
    cost: float

    def copy(self) -> Solution:
        return Solution([list(route) for route in self.routes], list(self.unassigned), self.cost)


def evaluate_route(problem: Problem, vehicle: Vehicle, sequence: list[int]) -> RouteResult:
    """Simulate one vehicle visiting ``sequence`` in order."""
    if not sequence:
        return RouteResult(0.0, 0.0, 0.0, 0.0, vehicle.start, vehicle.start, 0, ())
    nodes = problem.nodes
    depart = max(vehicle.start, max(nodes[i].release for i in sequence))
    depart += problem.loading_minutes
    clock, distance, late, late_stops, previous = depart, 0.0, 0.0, 0, -1
    timings: list[StopTiming] = []
    for index in sequence:
        node = nodes[index]
        leg = problem.distance(previous, index)
        distance += leg
        arrival = clock + problem.minutes(leg)
        service_start = max(arrival, node.ready)
        if service_start > node.due + 1e-9:
            late += service_start - node.due
            late_stops += 1
        clock = service_start + node.service
        timings.append(StopTiming(index, arrival, service_start, clock))
        previous = index
    leg = problem.distance(previous, -1)
    distance += leg
    finish = clock + problem.minutes(leg)
    return RouteResult(
        distance=distance,
        late=late,
        overtime=max(0.0, finish - vehicle.end),
        load=sum(nodes[i].demand for i in sequence),
        depart=depart,
        finish=finish,
        late_stops=late_stops,
        stops=tuple(timings),
    )


def route_cost(problem: Problem, vehicle: Vehicle, sequence: list[int]) -> float:
    if not sequence:
        return 0.0
    result = evaluate_route(problem, vehicle, sequence)
    if result.load > vehicle.capacity + 1e-9:
        return math.inf
    weights = problem.weights
    return (
        result.distance
        + weights.late * result.late
        + weights.overtime * result.overtime
        + weights.vehicle
    )


def solution_cost(problem: Problem, routes: list[list[int]], unassigned: list[int]) -> float:
    total = sum(
        route_cost(problem, vehicle, route)
        for vehicle, route in zip(problem.vehicles, routes, strict=True)
    )
    return total + problem.weights.unserved * len(unassigned)


# ── insertion ───────────────────────────────────────────────────────


def _insertions(
    problem: Problem, routes: list[list[int]], costs: list[float], node: int
) -> list[tuple[float, int, int]]:
    """Cheapest insertion of ``node`` into each route: ``(delta, route, position)``."""
    options: list[tuple[float, int, int]] = []
    demand = problem.nodes[node].demand
    for route_index, route in enumerate(routes):
        vehicle = problem.vehicles[route_index]
        if sum(problem.nodes[i].demand for i in route) + demand > vehicle.capacity + 1e-9:
            continue
        best: tuple[float, int] | None = None
        for position in range(len(route) + 1):
            trial = [*route[:position], node, *route[position:]]
            delta = route_cost(problem, vehicle, trial) - costs[route_index]
            if best is None or delta < best[0]:
                best = (delta, position)
        if best is not None and best[0] < math.inf:
            options.append((best[0], route_index, best[1]))
    options.sort()
    return options


def _repair(problem: Problem, solution: Solution, pool: list[int], *, regret: bool) -> None:
    """Reinsert ``pool``. With ``regret`` the shipment with most to lose goes first."""
    routes = solution.routes
    costs = [route_cost(problem, v, r) for v, r in zip(problem.vehicles, routes, strict=True)]
    pending = list(pool)
    while pending:
        chosen: tuple[float, int, tuple[float, int, int] | None] | None = None
        for node in pending:
            options = _insertions(problem, routes, costs, node)
            if not options:
                priority = math.inf  # nowhere to go: decide it first
                candidate = (priority, node, None)
            else:
                # Leaving a shipment at the dock is always an alternative.
                second = options[1][0] if len(options) > 1 else problem.weights.unserved
                priority = (second - options[0][0]) if regret else -options[0][0]
                candidate = (priority, node, options[0])
            if chosen is None or candidate[0] > chosen[0]:
                chosen = candidate
        assert chosen is not None
        _priority, node, option = chosen
        pending.remove(node)
        if option is None or option[0] >= problem.weights.unserved:
            solution.unassigned.append(node)
            continue
        _delta, route_index, position = option
        routes[route_index].insert(position, node)
        costs[route_index] = route_cost(problem, problem.vehicles[route_index], routes[route_index])


# ── removal ─────────────────────────────────────────────────────────


def _remove(solution: Solution, nodes: list[int]) -> None:
    targets = set(nodes)
    solution.routes = [[i for i in route if i not in targets] for route in solution.routes]
    solution.unassigned = [i for i in solution.unassigned if i not in targets]


def _random_removal(problem: Problem, solution: Solution, count: int, rng: random.Random):
    served = [i for route in solution.routes for i in route]
    return rng.sample(served, min(count, len(served)))


def _worst_removal(problem: Problem, solution: Solution, count: int, rng: random.Random):
    gains: list[tuple[float, int]] = []
    for vehicle, route in zip(problem.vehicles, solution.routes, strict=True):
        base = route_cost(problem, vehicle, route)
        for position, node in enumerate(route):
            without = route[:position] + route[position + 1 :]
            gains.append((base - route_cost(problem, vehicle, without), node))
    gains.sort(reverse=True)
    picked: list[int] = []
    while gains and len(picked) < count:
        # Bias towards the worst-placed without always taking the very worst.
        index = int(len(gains) * rng.random() ** 4)
        picked.append(gains.pop(index)[1])
    return picked


def _related_removal(problem: Problem, solution: Solution, count: int, rng: random.Random):
    served = [i for route in solution.routes for i in route]
    if not served:
        return []
    nodes = problem.nodes
    span = max(n.due for n in nodes) - min(n.ready for n in nodes) or 1.0
    reach = max(problem.distance(-1, i) for i in range(len(nodes))) * 2 or 1.0
    seed = rng.choice(served)

    def relatedness(other: int) -> float:
        return (
            problem.distance(seed, other) / reach + abs(nodes[seed].due - nodes[other].due) / span
        )

    ranked = sorted((i for i in served if i != seed), key=relatedness)
    return [seed, *ranked[: count - 1]]


_DESTROY = (_random_removal, _worst_removal, _related_removal)
_REPAIR = (False, True)  # cheapest, regret-2


def _initial(problem: Problem) -> Solution:
    solution = Solution([[] for _ in problem.vehicles], [], 0.0)
    order = sorted(range(len(problem.nodes)), key=lambda i: problem.nodes[i].due)
    _repair(problem, solution, order, regret=False)
    solution.cost = solution_cost(problem, solution.routes, solution.unassigned)
    return solution


def solve(problem: Problem, *, iterations: int = 1200, seed: int = 7) -> Solution:
    """Adaptive large neighbourhood search. Deterministic for a given seed."""
    if not problem.nodes:
        return Solution([[] for _ in problem.vehicles], [], 0.0)
    if not problem.vehicles:
        indices = list(range(len(problem.nodes)))
        return Solution([], indices, problem.weights.unserved * len(indices))

    rng = random.Random(seed)
    current = _initial(problem)
    best = current.copy()
    size = len(problem.nodes)
    max_remove = max(1, min(12, math.ceil(0.35 * size)))
    temperature = max(1e-6, 0.05 * current.cost / math.log(2))
    cooling = (0.002) ** (1.0 / max(1, iterations))
    destroy_weights = [1.0] * len(_DESTROY)
    repair_weights = [1.0] * len(_REPAIR)
    destroy_scores, destroy_uses = [0.0] * len(_DESTROY), [0] * len(_DESTROY)
    repair_scores, repair_uses = [0.0] * len(_REPAIR), [0] * len(_REPAIR)

    for step in range(1, iterations + 1):
        d = rng.choices(range(len(_DESTROY)), weights=destroy_weights)[0]
        r = rng.choices(range(len(_REPAIR)), weights=repair_weights)[0]
        candidate = current.copy()
        removed = _DESTROY[d](problem, candidate, rng.randint(1, max_remove), rng)
        pool = removed + candidate.unassigned
        _remove(candidate, pool)
        rng.shuffle(pool)
        _repair(problem, candidate, pool, regret=_REPAIR[r])
        candidate.cost = solution_cost(problem, candidate.routes, candidate.unassigned)

        reward = 0.0
        if candidate.cost < best.cost - 1e-9:
            best, current, reward = candidate.copy(), candidate, 3.0
        elif candidate.cost < current.cost - 1e-9:
            current, reward = candidate, 2.0
        elif rng.random() < math.exp(-(candidate.cost - current.cost) / temperature):
            current, reward = candidate, 1.0
        destroy_scores[d] += reward
        repair_scores[r] += reward
        destroy_uses[d] += 1
        repair_uses[r] += 1
        temperature *= cooling

        if step % 50 == 0:
            for weights, scores, uses in (
                (destroy_weights, destroy_scores, destroy_uses),
                (repair_weights, repair_scores, repair_uses),
            ):
                for index in range(len(weights)):
                    if uses[index]:
                        weights[index] = 0.8 * weights[index] + 0.2 * scores[index] / uses[index]
                    weights[index] = max(weights[index], 0.05)
                    scores[index], uses[index] = 0.0, 0
    return best


def solve_exact(problem: Problem) -> Solution:
    """Enumerate every assignment and order. Only for very small problems.

    Used to check the heuristic: on a handful of shipments it must find the
    same cost.
    """
    size = len(problem.nodes)
    if size > 8 or len(problem.vehicles) > 3:
        raise ValueError("exact enumeration is limited to 8 shipments and 3 vehicles")
    vehicles = problem.vehicles
    best = Solution([[] for _ in vehicles], list(range(size)), math.inf)

    def cuts(remaining: int, parts: int):
        if parts == 1:
            yield (remaining,)
            return
        for first in range(remaining + 1):
            for rest in cuts(remaining - first, parts - 1):
                yield (first, *rest)

    splits = list(cuts(size, len(vehicles)))
    for order in permutations(range(size)):
        for split in splits:
            routes: list[list[int]] = []
            start = 0
            for length in split:
                routes.append(list(order[start : start + length]))
                start += length
            cost = solution_cost(problem, routes, [])
            if cost < best.cost:
                best = Solution(routes, [], cost)
    return best
