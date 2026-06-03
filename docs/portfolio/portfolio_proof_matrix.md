# 作品集证明材料矩阵

## 1. 证明目标

ReOrch 智策不是用来展示“使用了 AI”的功能清单，而是用来证明一个 AI Native 产品从问题定义到受控验证的完整闭环：

```text
真实问题
-> 用户流程重构
-> 产品架构
-> Agent / Prompt / Tool 设计
-> 质量门与风险控制
-> 测试与失败样本
-> 成本、延迟、部署边界
-> 个人主导贡献
```

## 2. 项目背景与真实问题

| 维度 | 内容 |
| --- | --- |
| 目标用户 | 计划员、生产主管、车间调度、IT/系统集成负责人、质量/审计角色 |
| 原始痛点 | 异常发生后依赖电话、群消息、Excel 和个人经验临时协调，影响范围难追踪，方案比较不可复盘 |
| 高频事件 | 设备故障、急单插入、物料延迟、质量返工、瓶颈资源冲突 |
| 决策风险 | 硬约束不可行、延期误判、过度扰动、越权回写、解释不可追溯 |
| 为什么值得做 | 异常高频、高风险、高认知负担，且每次处理结果都可沉淀为经验资产 |
| 为什么不是普通看板 | 普通看板只能展示状态，不能形成候选方案、质量门、推荐解释、人工确认和审计闭环 |

核心问题不是“让 AI 自动排产”，而是解决高压、高约束环境下的异常决策纪律问题：数据是否可信、证据是否充分、方案是否可执行、人工确认是否留痕、事后是否可复盘。

## 3. 用户流程：原流程 vs AI 辅助流程

| 原流程 | AI 辅助流程 |
| --- | --- |
| 现场异常发生 | Incident Intake 将异常结构化 |
| 计划员查排程、问车间、找历史经验 | Data Readiness + Snapshot Lock 固定判断上下文 |
| 通过 Excel 或 APS 手动试排多个方案 | Hybrid Solver 生成 Top-K 候选 |
| 口头解释为什么选某个方案 | Recommendation Explanation 绑定 KPI、质量门和 source refs |
| 临场确认并通知执行 | Human Confirmation + Controlled Writeback |
| 执行反馈零散保留 | DecisionRecord、AuditLog、CaseRecord 沉淀为经验资产 |

```text
原流程：
异常发生 -> 查数据 -> 问现场 -> 手工试排 -> 主观选择 -> 通知执行 -> 复盘困难

新流程：
数据健康检查 -> 快照锁定 -> 影响分析 -> 候选方案 -> 风险边界 -> 推荐解释
-> 人工确认 -> 受控回写 -> 执行反馈 -> 案例沉淀
```

## 4. 产品架构证明

```text
数据层：
工单 / 工序 / 设备 / 日历 / 排程快照 / 异常 / 执行反馈
  ↓
数据健康门：
schema、枚举、时间、引用完整性、source refs、readiness score
  ↓
证据层：
结构化影响分析 + 质量门 + 历史案例 + failure cases
  ↓
Agent 工作流：
异常理解 -> 策略建议 -> 规则候选 -> 推荐解释 -> 反馈结构化
  ↓
Guardrail：
不自动排产、不越权回写、低置信降级、质量门阻断、人工确认
  ↓
输出层：
Top-K 候选方案 / 风险提示 / 推荐理由 / 回写预览 / 不确定性说明
  ↓
日志层：
Agent trace / DecisionRecord / AuditLog / CaseRecord / ExecutionFeedback
```

## 5. 证明材料索引

| 证明问题 | 对应材料 |
| --- | --- |
| 为什么做这个项目 | `product_portfolio.md`、`industrial_ai_copilot_solution.md` |
| 用户流程如何被重构 | `business_process_flow.md`、`prototype_logic.md` |
| 系统架构是否落地 | README、`app/`、`frontend/src/`、`demo/` |
| Agent 和 Prompt 如何设计 | `workflow_prompts_io.md`、`ai_increment_agent_design.md` |
| 如何控制模型不确定性 | `trust_quality_gate.md`、`evaluation_guardrail_cases.md` |
| 评测和验证如何做 | `metric_system.md`、`demo_validation_report.md`、`llm_agent_offline_eval.md` |
| 有哪些失败与迭代 | `failure_iteration_log.md`、`failure_case_library.md` |
| 成本、延迟和部署边界 | `cost_latency_deployment_boundary.md` |
| 个人贡献是什么 | `personal_contribution.md` |

## 6. 当前结论

ReOrch 当前证明的是一个 production-minded 的 AI 决策辅助框架：它已经具备可运行 demo、后端 API、前端工作台、Agent trace、质量门、失败样本、指标体系和公开材料包。

当前不宣称已经完成客户生产上线，也不宣称可以无人值守自动调度。下一阶段应使用客户只读数据进入 shadow mode，进一步验证 Top-K 覆盖、人工采纳、失败归因、审计包和受控回写演练。
