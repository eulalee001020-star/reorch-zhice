# 可信性质量门

ReOrch 的可信性设计不是让 LLM 自证正确，而是把模型输出放进外部验证链路。每一次异常决策至少经过结构校验、数据追溯、硬约束校验、业务风险暴露、置信度控制和审计留痕。

## 1. 当前落实状态

| 判断项 | 标准 | 当前状态 | 代码/产品证据 |
| --- | --- | --- | --- |
| 结构合法 | 输入输出必须符合 schema，枚举、时间、ID、必填字段合法 | 已实现 | Pydantic models、`MappingValidator`、demo validation |
| 数据可追溯 | 影响结论必须能回到 Incident、ScheduleSnapshot、工序、设备和工单 | 部分实现 | `AgentTraceStep`、`impact_report`、`snapshot_id`、`incident_id`；逐条解释引用仍需增强 |
| 硬约束 | 推荐前通过设备能力、工序顺序、资源互斥、物料可用、局部修复不变性等校验 | 已实现核心版 | `ConstraintValidator`、`HybridSolver`、`PlanRecommendationEngine` 过滤 infeasible plans |
| 业务风险 | 明确暴露延期、扰动、换线、执行复杂度、solver 降级和超时风险 | 部分实现 | `risk_flags`、`quality_gate.warnings`、推荐解释、前端风险提示 |
| 置信度 | 低置信度不自动预选，提示计划员对比候选方案 | 已实现 | `IncidentAgent.confidence`、`StrategyRecommendation.confidence`、`recommendation_confidence`、前端低置信度提示 |
| 审计 | 推荐、确认、覆盖、回写、执行反馈均可留痕 | 核心链路已实现，生产审计包需继续增强 | `DecisionRecord`、`audit_metadata`、`AgentTraceStep`、`audit_logs`、confirmation/writeback records |

结论：当前已经具备 PoC 级可信性质量门，足以支撑 sandbox demo、历史 replay 和 shadow mode。生产级版本还需要补强逐条解释引用、客户现场阈值、审计导出包和真实系统回写失败处置。

## 2. 质量门如何工作

```text
LLM/Agent 输出
-> Pydantic / mapping schema 校验
-> Incident + ScheduleSnapshot 绑定
-> ImpactAnalysisEngine 计算影响范围
-> HybridSolver 生成候选方案
-> ConstraintValidator 硬约束校验
-> PlanQualityGate 生成 pass/warning/block 策略
-> PlanRecommendationEngine 过滤与排序
-> ExplanationLayer 只解释已验证结果
-> Planner confirmation
-> DecisionRecord / Writeback audit
```

## 3. 硬约束标准

进入推荐和确认前，候选方案必须满足核心硬约束：

| 约束 | 当前校验 |
| --- | --- |
| 设备能力 | 工序所需能力必须被分配设备覆盖 |
| 工序顺序 | 前序工序结束时间不能晚于后序开始时间 |
| 资源互斥 | 同一设备同一时间不能有重叠工序 |
| 物料可用 | PoC 版做基础有效性检查，真实客户接入后接 BOM/库存/采购数据 |
| 局部修复不变性 | local repair 下非受影响工序不能被任意移动 |
| 微调复验 | 计划员调整后重新跑约束校验 |

硬约束失败时，方案不能作为推荐方案进入确认，只能展示失败原因。

## 4. 置信度与降级策略

| 情况 | 系统动作 |
| --- | --- |
| schema 不合法 | 阻断进入决策流 |
| 设备/工单/工序 ID 不存在 | 阻断或要求人工补充 |
| 没有排程快照 | 不允许生成伪方案 |
| 硬约束失败 | 不推荐，只展示不可行原因 |
| solver 超时或降级 | 作为 warning，禁止自动预选或要求人工确认 |
| 多方案分数接近 | 提示计划员比较 Top-2 |
| recommendation confidence < 0.5 | 不自动预选，前端提示低置信度 |
| confidence >= 阈值且无高风险 | 可以预选，但仍必须人工确认 |

## 5. 当前不足

| 缺口 | 为什么重要 | 后续补强 |
| --- | --- | --- |
| 逐条解释引用还不够细 | 面向客户 QA/IT 时，需要证明每句话来自哪条数据 | 给解释层增加 source_refs：工序、工单、设备、KPI、约束报告 |
| 业务风险阈值需要客户校准 | 换线、扰动、延期成本每家工厂不同 | 在 PoC 中用历史异常和计划员反馈校准阈值 |
| 质量门在异常工作台的展示还可更显性 | 当前前端展示了置信度和风险，但没有单独质量门面板 | 后续可在候选方案表增加 pass/warning/block 列 |
| 生产级审计导出仍需完善 | 客户 IT/质量部门通常需要可导出的审计包 | 增加 decision audit package：输入、输出、版本、确认、回写、执行反馈 |

## 6. 面向 PoC 的验收标准

| 指标 | 目标 |
| --- | --- |
| demo 数据 schema 校验 | blocking errors = 0 |
| 推荐前硬约束可行率 | 100% |
| 低置信度自动预选率 | 0% |
| 推荐/确认/回写审计记录 | 100% 留痕 |
| 计划员确认前生产写回 | 0 次 |
| shadow mode Top-N 覆盖人工策略 | 首期目标 60%+ |

这套质量门的核心作用是让 ReOrch 的 AI 输出可以被验证、被阻断、被降级和被追责，而不是依赖模型表述上的“自信”。

