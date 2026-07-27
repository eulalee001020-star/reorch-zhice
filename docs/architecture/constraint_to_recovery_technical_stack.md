# Constraint-to-Recovery Technical Stack

版本：2026-07-04

## 一句话定义

ReOrch 的技术内核不是“AI 直接排产”，而是从真实数据、真实约束和真实异常出发，把异常恢复做成可审计、可回放、可门控的系统工程：

```text
Reality Data Layer
-> Decision Graph
-> Constraint Compiler
-> Incident-to-Impact Engine
-> Recovery Operator Portfolio
-> Evidence-Gated Solver
-> Replay / Shadow / Memory Loop
```

[补充] 这套技术栈解决“如何从真实约束生成可控恢复候选”。更长期的护城河应上升为 Recovery Policy Graph：把每次异常的上下文、候选策略、硬约束结果、计划员选择、驳回原因和执行结果沉淀成企业自己的恢复策略资产。详见 [recovery_policy_graph.md](recovery_policy_graph.md)。

## 1. Reality Data Layer

目标：先判断客户数据是否可排程，而不是脏数据下生成伪推荐。

当前实现：

- canonical schema: `schemas/canonical/`
- P0 CSV 样例包: `datasets/p0_reality_pack/`
- 字段 mapping 建议: `app/services/field_mapping_compiler.py`
- 数据闸门: `app/services/reality_harness.py`
- API:
  - `POST /api/v1/planning/reality-harness/assess`
  - `POST /api/v1/planning/reality-harness/sample-pack`
  - `POST /api/v1/planning/reality-harness/suggest-mapping`

核心规则：

| 条件 | 动作 |
| --- | --- |
| blocker > 0 | 禁止求解，只输出数据缺口 |
| readiness < 0.70 | 只做数据治理 |
| 0.70 <= readiness < 0.85 | 只允许 replay |
| readiness >= 0.85 且 blocker = 0 | 允许只读 shadow |

## 2. Decision Graph

目标：用图表达订单、工序、资源、前后依赖和异常影响范围，回答“哪些能动、哪些不能动、为什么”。

当前实现：

- 模型: `app/models/technical_kernel.py`
- 服务: `app/services/technical_kernel.py`
- API: `POST /api/v1/planning/technical-kernel/decision-graph`

当前算法：

```text
1. 从 ScheduleSnapshot 构建 work_order / operation / resource 节点。
2. 建立 contains_operation、assigned_to_resource、precedes 边。
3. 根据 incident.resource_id 和故障窗口识别直接受影响工序。
4. 沿 successor_ids / predecessor_ids 传播下游影响。
5. 剔除 freeze_operation_ids，得到 repairable_frontier。
6. 根据 required_capabilities 搜索 alternative_resources。
```

输出指标：

- `node_count`
- `edge_count`
- `affected_operation_count`
- `repairable_frontier_count`
- `alternative_resource_options`

## 3. Constraint Compiler

目标：把设备能力、资源日历、冻结窗口、换型规则和计划员经验编译成调度器可读输入。

当前实现：

- 模型: `app/models/constraint_calibration.py`
- 服务: `app/services/constraint_calibration.py`
- API: `POST /api/v1/planning/constraint-calibration/compile`

安全规则：

1. 显式标定条目必须 `approval_status=approved` 且 `approved_by` 存在。
2. AI 规则候选必须 `review_status=published_readonly` 且 `replay_passed=true`。
3. 无效时间窗、未知资源、冲突换型规则会产生 blocker。
4. blocked calibration 不返回 patched `InitialScheduleRequest`。

## 4. Incident-to-Impact Engine

目标：把异常转成影响范围和风险传播，而不是把异常文本直接交给求解器。

当前实现：

- 影响分析: `app/services/impact_analysis_engine.py`
- Incident Agent: `app/services/agent_workflow.py`
- API: `GET /api/v1/incidents/{incident_id}/impact-report`

当前算法：

```text
1. 定位 incident.resource_id 对应的直接受影响工序。
2. 沿 successor_ids 做下游传播。
3. 聚合到 affected_work_orders。
4. 根据 due_date、remaining processing、estimated delay 判断 delivery risk。
5. 必要时升级 severity，但不降级。
```

## 5. Recovery Operator Portfolio

目标：不要笼统说“智能重排”，而是按异常类型和影响范围选择恢复算子。

当前实现：

- 模型: `RecoveryOperatorRequest`, `RecoveryOperatorRecommendation`
- 服务: `RecoveryOperatorPortfolioService`
- API: `POST /api/v1/planning/technical-kernel/recovery-operators`

当前支持的算子：

| 算子 | 算法族 | 后端 |
| --- | --- | --- |
| `wait_and_shift` | minimal perturbation | heuristic then constraint check |
| `alternative_machine_repair` | resource reallocation | local search + CP-SAT |
| `local_insertion` | sequence repair | CP-SAT LNS |
| `rolling_window_repair` | scope control | CP-SAT with timeout fallback |
| `controlled_global_reschedule` | global reschedule | CP-SAT with feasible fallback |
| `manual_policy_route` | unsupported incident guardrail | deterministic guardrail |

设备故障路径：

```text
故障窗口
-> 受影响工序
-> 下游风险
-> 替代设备可行性
-> wait / alternative machine / local insertion / rolling window
-> 必要时 controlled global reschedule
```

## 6. Evidence-Gated Solver

目标：求解不是黑箱，候选方案必须通过数据、约束、证据、策略、回写门。

当前实现：

- 质量门: `app/services/plan_quality_gate.py`
- 证据门合并: `EvidenceGateService`
- API: `POST /api/v1/planning/technical-kernel/evidence-gates`

当前 gates：

| Gate | 规则 |
| --- | --- |
| DataGate | data readiness 有 blocker 则禁止求解 |
| ConstraintGate | 候选方案 hard constraint 不可行则禁止推荐 |
| EvidenceGate | source refs 缺失则只能 reference only |
| ReplayGate | replay Top-N 未命中则不进入 shadow |
| PolicyGate | quality gate fail 则不推荐 |
| WritebackGate | 未人工确认或 shadow block 则禁止写回 |

输出策略：

- `do_not_recommend`
- `show_as_reference_only`
- `recommend_with_source_refs_and_planner_confirmation`
- `read_only_shadow_allowed`
- `writeback_allowed_after_human_confirmation`

## 7. Replay / Shadow / Memory Loop

目标：用历史 replay 和 shadow mode 验证系统，而不是只演示 demo。

当前实现：

- Replay validation: `app/services/replay_validation.py`
- Shadow capture: `app/services/shadow_mode.py`
- Agent observability: `app/services/agent_observability.py`
- API:
  - `POST /api/v1/planning/replay-validation/evaluate`
  - `POST /api/v1/planning/shadow-mode/capture`
  - `POST /api/v1/planning/agent-observability/summarize`

## 和 APS / 启发式 / LLM Agent 的区别

| 对比对象 | 对方强项 | ReOrch 差异 |
| --- | --- | --- |
| 传统 APS | 完整计划与有限产能排程 | 从异常恢复切入，先 replay/shadow 验证，再进入回写 |
| 纯启发式 | 快速生成局部解 | ReOrch 有 operator portfolio、constraint gate 和 evidence gate |
| 纯 LLM Agent | 语义理解和表达 | LLM 不负责硬约束、最终排程、确认和写回 |
| BI/RPA | 看见异常或自动执行固定流程 | ReOrch 生成可行候选、解释影响边界、沉淀经验资产 |

## 当前边界

已落地的是 Constraint-to-Recovery Kernel 的最小可运行版本。它证明了“数据 -> 图 -> 约束 -> 算子 -> 门控 -> replay/shadow”的系统工程路径，但还不能声称已经完成完整 APS 替代。下一步需要补物料、质量、人员、工装、外协、多车间和真实客户生产发布验证。
