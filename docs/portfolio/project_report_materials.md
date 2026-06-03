# 项目汇报材料

## 1. 汇报主线

```text
真实业务问题
-> 为什么适合 AI Copilot 而不是纯自动化
-> 系统方案与 Agent/Workflow
-> 原型与 Demo
-> 质量门与风险控制
-> 指标体系与验证证据
-> 当前边界与下一阶段计划
```

汇报目标不是证明“用了大模型”，而是证明项目具备 AI 产品经理所需的完整能力链路：业务判断、AI 取舍、系统设计、工程落地、评测体系、风险治理和商业验证。

## 2. 10 页汇报结构

| 页码 | 标题 | 核心内容 | 证据材料 |
| --- | --- | --- | --- |
| 1 | 项目一句话定位 | 工业异常调度决策 Copilot，不替代主系统，只补异常响应层 | `portfolio_brief.md` |
| 2 | 业务问题与用户需求 | 设备故障、急单、物料延迟、质量返工导致人工重排慢且不可追溯 | `business_process_flow.md`、`service_ai_role_fit.md` |
| 3 | 用户与场景 | 计划员、生产主管、调度执行端、IT/集成、质量审计 | `industrial_ai_copilot_solution.md` |
| 4 | PRD 与为什么用 AI | 用户故事、功能范围、异常状态、权限、AI 输出约束和 Agent 分工 | `prd_decision_workbench.md`、`workflow_prompts_io.md` |
| 5 | 系统方案 | Incident -> Impact -> Solver -> Quality Gate -> Confirmation -> Case Memory | `business_process_flow.md` |
| 6 | 原型逻辑 | 决策工作台、规则审核、偏好画像、数据就绪、Evidence Center、NGS Lab | `prototype_logic.md` |
| 7 | 可信性控制 | schema、source refs、hard gate、人工确认、审计、失败样本库 | `trust_quality_gate.md` |
| 8 | 指标体系 | 闭环率、time-to-candidate、Top-K feasible coverage、adoption、audit completeness | `metric_system.md` |
| 9 | 项目推进、评测与迭代 | 从需求到灰度的里程碑、Guardrail 用例、失败归因和修复方案 | `mvp_delivery_plan.md`、`evaluation_guardrail_cases.md`、`failure_iteration_log.md` |
| 10 | 结果、边界与迁移 | MVP 可受控试用；说明成本延迟边界、个人贡献和服务 AI 迁移 | `cost_latency_deployment_boundary.md`、`personal_contribution.md`、`service_ai_benchmark.md`、`service_ai_transfer_note.md` |

## 3. 三分钟汇报稿

```text
ReOrch 智策是一个工业异常调度决策 Copilot。
项目选择的不是“让大模型自动排产”这个高风险方向，
而是把 AI 放在异常发生后的受控决策流程中。

复杂制造现场真正难的是：设备故障、急单、物料延迟、质量返工发生后，
计划员要快速判断影响范围、比较多个方案、解释取舍，并确保回写安全。
传统 ERP/MES/APS 负责主数据和执行，但异常响应过程仍依赖人工经验。

ReOrch 的方案是：
先把异常结构化，再锁定排程快照，做影响分析，
然后生成 Top-K 候选方案，通过硬约束质量门和多目标评价，
最后由计划员确认后受控回写，并把决策和失败原因沉淀到案例库。

AI 的作用不是替代求解器或计划员，
而是负责异常理解、规则候选、推荐解释、案例沉淀和偏好学习。
可行性由求解器、质量门、数字孪生验证、人工确认和审计链路保障。

项目已经有可运行 demo、后端 API、前端工作台、Prompt 与输入输出样例、
失败样本库、指标体系和验证材料。
当前定位是 MVP 和受控试用，不宣称已经生产上线。
下一阶段会用客户只读数据进入 shadow mode，再验证受控回写和审计包。
```

## 4. 五分钟答辩问题

| 问题 | 回答要点 |
| --- | --- |
| 为什么不是直接做 AI 排产？ | 工业排程有硬约束和生产责任，AI 不应直接越权生成可执行计划；ReOrch 把 AI 放在语义、解释、规则候选和经验沉淀中 |
| 和 APS/MES 有什么区别？ | APS/MES 是主计划和执行底座，ReOrch 是异常响应层与经验资产层，不替代主系统 |
| 如何控制幻觉？ | 不让 LLM 自证正确；通过 schema、source refs、硬约束、质量门、人工确认和审计链路控制 |
| 如果计划员不采纳怎么办？ | 驳回和 override 是有价值数据，会进入失败归因、偏好画像或规则候选，不简单视为系统失败 |
| 当前验证到什么程度？ | MVP、demo、数字孪生 replay/shadow 代理和合作实验室初步试用；不宣称生产上线 |
| 成本如何控制？ | 能用规则、数据库和求解器完成的任务不交给 LLM；低风险 Agent 支持真实 LLM telemetry 和确定性降级 |
| 如何证明商业价值？ | 通过异常到候选时间、延期减少、扰动减少、人工采纳、审计完整度和估算价值分阶段验证 |

## 5. 项目汇报材料包

| 材料 | 用途 |
| --- | --- |
| `service_ai_role_fit.md` | 服务领域 AI 产品能力映射、行业调研、用户需求、PRD、项目推进、上线指标和创新输入 |
| `service_ai_benchmark.md` | 服务领域 AI 竞品与标杆能力分析 |
| `service_ai_transfer_note.md` | 客服 Copilot、工单 Agent、服务质检等场景迁移说明 |
| `prd_decision_workbench.md` | 标准 PRD 示例 |
| `mvp_delivery_plan.md` | MVP 交付计划、里程碑、风险和指标看板 |
| `industrial_ai_copilot_solution.md` | 方案说明、架构、AI 与确定性系统分工、交付阶段 |
| `business_process_flow.md` | 业务流程图、泳道图、状态机和关键决策节点 |
| `prototype_logic.md` | 信息架构、页面逻辑、状态与异常处理 |
| `metric_system.md` | North Star、分层指标、采集路径、失败样本指标 |
| `evaluation_guardrail_cases.md` | Guardrail 用例、通过标准、失败用例和验证结果 |
| `failure_iteration_log.md` | 失败现象、归因、修复方案、验证方式和剩余风险 |
| `cost_latency_deployment_boundary.md` | 成本分层、延迟控制、Agent 边界和 SaaS 化差距 |
| `personal_contribution.md` | 产品设计、AI 技术方案、工程实现和公开交付贡献 |
| `workflow_prompts_io.md` | Prompt、Agent 分工和输入输出示例 |
| `trust_quality_gate.md` | 可信性质量门、审计和兜底机制 |
| `project_status_assessment.md` | 当前状态、上线边界和下一阶段计划 |
