# AI Native 产品经理能力映射

## 1. 能力摘要

ReOrch 智策展示的是一个从真实业务问题出发的 AI 产品闭环：先定义高价值异常场景，再判断 AI 的适用边界，随后完成 Agent/Workflow、原型、系统架构、质量门、指标体系、演示数据、验证材料和上线边界设计。

项目适合展示 AI Native 产品经理在 ToB/SaaS 场景中的核心能力：场景理解、产品价值定义、技术边界判断、自动化工程意识、跨团队沟通、评测体系和商业化推进。

## 2. 与生产级 AI 应用相关的能力

| 能力维度 | 项目体现 | 证据材料 |
| --- | --- | --- |
| 场景理解与价值定义 | 选择工业异常重排作为高频、高损失、有人负责的业务事件；不把 AI 做成泛聊天入口 | `product_portfolio.md`、`industrial_ai_copilot_solution.md` |
| AI Native 产品设计 | 将异常理解、规则候选、推荐解释、案例沉淀和偏好学习拆为受控 Agent | `workflow_prompts_io.md`、`ai_increment_agent_design.md` |
| Harness 架构思维 | 用 schema、source refs、hard gate、fallback、audit、test、demo validation 管住模型不确定性 | `trust_quality_gate.md`、`metric_system.md` |
| 技术边界判断 | 明确 LLM 不负责最终排程、硬约束、质量门和回写；求解器与人工确认承担生产责任 | `industrial_ai_copilot_solution.md` |
| MVP 快速落地 | 已形成 FastAPI 后端、React 前端、Docker Compose、mock integration、demo 数据和测试 | README、`docs/demo/demo_validation_report.md` |
| 多方案对比 | 对比纯规则、传统 APS、人工试排、自由聊天式 Agent，并选择异常响应层切口 | `product_portfolio.md` |
| 指标与评测 | 覆盖模型层、方案层、产品层、业务层和风险层指标 | `metric_system.md` |
| 商业化推进 | 设计 Lab Trial -> Read-only Pilot -> Shadow Mode -> Controlled Writeback -> Production Scope | `industrial_ai_copilot_solution.md` |

## 3. 面向客户与研发的双语言表达

| 沟通对象 | 关注点 | 项目中的表达方式 |
| --- | --- | --- |
| 业务客户 | 异常处理是否更快、更稳、更可追溯 | 使用交期风险、扰动范围、换线成本、人工确认和案例沉淀解释价值 |
| 生产/运营负责人 | 是否影响现场执行稳定性 | 用质量门、回写预览、人工确认和回滚边界说明风险控制 |
| IT/集成负责人 | 是否能接入现有 ERP/MES/APS | 使用 canonical data model、adapter contract、data readiness 和只读接入路径说明实现 |
| 研发团队 | 如何拆模块、如何验证、如何降级 | 使用 Agent schema、API、状态机、quality gate、fallback reason 和测试用例对齐 |
| 管理层 | 是否值得试点和规模化 | 用 time-to-candidate、Top-K feasible coverage、adoption、delay reduced 和 audit completeness 评估 |

## 4. 大模型、RAG 与 Agent 的产品判断

| 技术 | 在项目中的定位 | 边界 |
| --- | --- | --- |
| LLM | 用于异常语义理解、规则候选、推荐解释、反馈结构化 | 不负责最终排程可行性、不绕过人工确认 |
| Agent | 负责工作流编排和工具调用，把复杂异常处理拆成可审计步骤 | 每一步有 schema、source refs、fallback reason 和审计记录 |
| RAG / Evidence Layer | 用于把解释和推荐绑定到工单、工序、设备、排程快照、质量门结果 | 不把检索结果当作自动决策依据 |
| 求解器 | 生成候选方案和多目标评价 | 与 LLM 解耦，优先保证硬约束可行 |
| 自动化 Harness | 用测试、demo validation、质量门、CI 和打包脚本支撑可复现交付 | 不用单次 demo 代替生产验收 |

## 5. 作品集完整闭环

```text
业务问题定义
-> 用户与场景拆解
-> AI 适用性判断
-> Agent/Workflow 设计
-> 原型逻辑
-> 工程实现
-> 指标体系
-> 失败样本库
-> Demo 与验证
-> 上线边界与商业化路线
```

对应材料：

- 工业 AI Copilot 方案说明：`industrial_ai_copilot_solution.md`
- 业务流程图：`business_process_flow.md`
- 原型逻辑：`prototype_logic.md`
- 指标体系：`metric_system.md`
- 项目汇报材料：`project_report_materials.md`
- 工作流、Prompt 与输入输出示例：`workflow_prompts_io.md`
- 可信性质量门：`trust_quality_gate.md`
- 失败样本库：`../validation/failure_case_library.md`

## 6. 不夸大的边界

- 不宣称已经服务真实亿级月活产品。
- 不宣称客户生产系统已经正式上线。
- 不宣称 LLM 可以绕过求解器、质量门和人工确认。
- 不把 synthetic / digital-twin-style 验证等同于客户生产数据。
- 不把“用了 AI”作为价值证明；价值证明来自效率、质量、业务结果和风险治理指标。
