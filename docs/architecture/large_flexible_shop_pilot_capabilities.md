# 大规模柔性作业车间试点能力包

版本：2026-07-06

## 目的

本文说明 ReOrch 为大规模高混柔性作业车间新增的试点能力。目标不是宣称已经完成客户生产上线，而是把系统从“单车间异常恢复 MVP”补强为可支撑真实客户进入只读 replay、shadow mode 和 sandbox writeback dry-run 的工程底座。

## 新增 API

| API | 作用 | 边界 |
| --- | --- | --- |
| `POST /api/v1/planning/flexible-shop/capability-assessment` | 对八大补强模块做就绪度评估 | 评估结构就绪度，不证明客户 ROI |
| `POST /api/v1/planning/flexible-shop/dynamic-rescheduling-plan` | 按异常类型生成恢复策略组合和求解策略 | 输出策略计划，不自动写回 |
| `POST /api/v1/planning/flexible-shop/synthetic-benchmark` | 生成 1k/5k/10k 工序级合成基准代理结果 | 衡量 routing/gating 规模代理，不替代真实求解压测 |
| `POST /api/v1/planning/flexible-shop/counterfactual-replay-matrix` | 汇总反事实 replay 样本为策略效果矩阵 | 低样本 cell 不能用于自动决策 |

## 八大补强模块

| 模块 | 新增能力 | 当前边界 |
| --- | --- | --- |
| 数据模型 | `FlexibleShopContext` 表达多车间、设备组、替代加工模式、批次、返工、WIP、冻结区 | 仍需客户真实主数据填充 |
| 约束体系 | `FlexibleConstraintPack` 覆盖物料、技能、工装、换型、质量 hold、外协、运输/AMR、缓冲区 | 仍需现场标定和审批 |
| 求解器策略 | `SolverStrategyPlan` 输出 bottleneck-first、rolling window、LNS/ALNS、warm start、timeout feasible 策略 | 尚未证明客户 10k 工序真实求解 P95 |
| 动态重调度 | 支持设备故障、插单、缺料、质量异常、人员缺勤、工装冲突、批量返工的策略路由 | 各异常类型仍需客户 replay 校准 |
| 性能工程 | 合成 1k/5k/10k routing/gating benchmark proxy | 不是生产求解 benchmark |
| 数据接入 | 评估 ERP/MES/WMS/QMS/IoT 来源齐备性 | 真实增量同步和数据血缘仍需客户系统接入 |
| 回写安全 | 评估 sandbox、审批角色、幂等、回滚、补偿、权限、审计 | 未完成客户生产写回验收 |
| 策略图谱 | 反事实 replay 聚合为 `PolicyEffectivenessCell` | 需要真实历史异常、shadow 决策和执行反馈形成高置信矩阵 |

## 动态异常与恢复策略

| 异常 | 策略组合 |
| --- | --- |
| 设备故障 | wait-and-shift、local repair、alternative resource、rolling window、controlled global reschedule |
| 插单 | rush insertion、priority swap、overtime what-if、outsourcing what-if、manual escalation |
| 缺料 | material substitution、resequence unblocked operations、procurement ETA repair、alternative BOM route |
| 质量异常 | quality hold freeze、rework routing、quarantine and resequence、downstream release |
| 人员缺勤 | skill reassignment、shift swap、overtime approval、manual escalation |
| 工装冲突 | tooling reallocation、setup delay repair、alternative tooling route |
| 批量返工 | batch split、rework route insertion、capacity rebalance、controlled global reschedule |

## 试点进入门槛

进入大规模柔性车间客户试点前，至少需要满足：

1. ERP/MES 只读数据源存在，字段映射能重建基准排程快照。
2. 物料、工装、人员、质量和运输约束至少有样本级字段。
3. 至少 10-30 条真实历史异常可 replay。
4. shadow mode 能记录计划员采纳、微调、驳回和原因。
5. 反事实 replay 能在同一异常快照下比较多种恢复策略。
6. sandbox writeback 已有人审、幂等、回滚、审计方案。
7. 1k/5k/10k 客户快照压测完成 P95 求解时延记录。

## Claim Boundary

可以说：

- 系统已新增大规模柔性作业车间试点能力包。
- 当前能评估八大补强模块是否具备 replay / shadow / pilot 条件。
- 当前能为七类动态异常生成策略组合和大规模求解策略计划。
- 当前能用合成基准代理检查 routing/gating 的规模路径。
- 当前能把反事实 replay 样本汇总成策略效果矩阵。

不能说：

- 已完成真实客户大规模柔性车间生产上线。
- 已证明 10k 工序真实求解 P95 满足生产 SLA。
- 已完成 ERP/MES/WMS/QMS/IoT 的客户现场双向集成。
- 已形成高置信 Recovery Policy Graph。
- 已允许无人值守自动写回。
