# Solver Strategy Architecture Memory

This document is the project-level memory for ReOrch's solver strategy.

## Core Positioning

ReOrch does not use a single solver for every dynamic scheduling event.
It uses a portfolio architecture:

- CP-SAT / PyJobShop is the detailed scheduling and feasibility core.
- Gurobi / MILP is the planning, capacity, material, cost, and energy optimization core.
- LNS and metaheuristics are the large-scale exploration core.
- GNN / DRL is the future policy brain for selecting rules, neighborhoods, budgets, and acceptance priors.
- Digital twin simulation is the execution-risk and continuous-learning feedback loop.

Learning policy must not bypass constraint solvers. It selects strategies and controls solver behavior; final schedules still pass hard-constraint validation.

## Strategy Selection Inputs

The strategy selector should score strategies using:

- affected_work_order_ratio
- affected_operation_ratio
- delivery_risk_level
- estimated_repair_time
- remaining_buffer
- machine_rank_score
- bottleneck_affected
- frozen_window_overlap
- alternative_resource_count
- material_availability
- time_budget
- data_quality_score
- incident_severity
- historical_case_similarity
- planner_preference

## Strategy Scores

Maintain explicit scores and choose the highest-scoring strategy:

- wait_score
- local_score
- global_score
- rolling_score
- metaheuristic_score
- gurobi_score
- fallback_score

If the top two scores differ by less than 0.1, run both strategies in parallel and show both to the planner.

## Initial Rule Mapping

| Condition | Strategy |
| --- | --- |
| Repair time is less than minimum remaining buffer, no breach, and non-bottleneck | Wait-and-Repair |
| Affected work orders <= 20%, no severe breach, and alternative resources exist | Local-Repair |
| Bottleneck resource affected but scope is controlled | Local-Repair + Bottleneck LNS |
| Breach exists or affected work orders > 20% | Global-Reschedule |
| Urgent order insertion impacts only the 24h window | Rolling Window + Local CP-SAT |
| Large order set or processing-time drift | Metaheuristic + CP-SAT refinement |
| Material, capacity, cost, or energy dominates | Gurobi coarse planning + CP-SAT detailed scheduling |
| Severe data gaps or solver timeout | Rule fallback + human confirmation |

## Learning Policy Roadmap

Early stage: collect training data, do not train production models yet.

Collect:

- incident features
- strategy choice
- selected rules
- selected neighborhoods
- solver portfolio path
- candidate plans
- human adoption / override
- execution result

Middle stage:

- train rule-selection model
- train neighborhood-selection model
- train budget-selection model
- predict plan adoption probability

Long stage:

- use GNN to encode shop-floor graph state
- use DRL to select dispatching actions
- use multi-agent policies for operation sequencing and machine assignment

Production guardrail:

- learning policy selects strategy and solver controls only
- CP-SAT / PyJobShop / MILP / validators still decide executable feasibility
- untrained policies run only in shadow mode

