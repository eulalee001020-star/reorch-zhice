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

## Agent Workflow Boundary

ReOrch should not be described as many agents freely chatting with each other. The architecture is a controlled workflow coordinated by an orchestrator.

```text
Orchestrator
  ├── Incident Agent
  ├── Impact Analysis Agent
  ├── Strategy Agent
  ├── Solver Tool / Solver Agent
  ├── Evaluation Agent
  ├── Explanation Agent
  ├── Confirmation Agent
  └── Feedback Agent
```

Agent 不是每一步都用 LLM。ReOrch 的设计里，LLM 主要负责理解、推荐、解释和总结；涉及约束、排程、指标计算、写回这些高风险动作，必须由确定性工具、规则引擎或优化器完成。

核心原则：Agent 负责组织流程，不负责绕过约束。

| Agent | 输入 | 输出 | 是否允许自由生成 |
| --- | --- | --- | --- |
| Incident Agent | 报警文本 / MES 事件 | 标准 Incident JSON | 低自由度 |
| Impact Analysis Agent | Incident + ScheduleSnapshot | 影响范围报告 | 不应自由生成，主要调用计算工具 |
| Strategy Agent | 影响报告 + 策略规则 | 推荐策略 | 中等自由度，但需规则约束 |
| Solver Tool / Solver Agent | 策略 + 调度数据 | Top-N 可行方案 | 不能自由生成，必须调用算法 |
| Evaluation Agent | 候选方案 | 指标对比表 | 不能自由生成，必须计算 |
| Explanation Agent | 指标 + 方案变化 | 自然语言解释 | 可自由表达，但不能改数据 |
| Confirmation Agent | 用户操作 | DecisionRecord | 不自由生成 |
| Feedback Agent | 执行结果 + 决策记录 | case library | 中等自由度，用于总结归因 |

Guardrail:

- Incident Agent 可以解析自然语言和补全字段，但必须输出置信度。
- Impact Analysis Agent、Solver Tool、Evaluation Agent、Confirmation Agent 不能伪造数据。
- Strategy Agent 可以生成建议文本，但其判断依据必须来自影响工序数、受影响订单数、downtime、slack、priority、可替代机器数量和当前设备负载等结构化字段。
- Explanation Agent 只能解释现有方案和指标，不得改变方案排序或隐藏风险。
- Feedback Agent 可以总结人工 override 原因，但新增规则必须先作为候选规则沉淀，不能直接上线。

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
