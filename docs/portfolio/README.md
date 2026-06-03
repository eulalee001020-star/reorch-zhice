# AI 产品作品集文档架构

本目录用于展示 ReOrch 智策的产品判断、AI 适用性、系统设计、工程落地、可信性控制、评测证据和商业价值。文档组织目标不是罗列功能，而是证明一个 AI 产品从问题定义到受控验证的完整决策链路。

## 1. 主线材料

| 文档 | 证明重点 |
| --- | --- |
| [portfolio_brief.md](portfolio_brief.md) | 一页式项目概览：定位、业务问题、AI 能力证据、工作流、验证证据和边界 |
| [service_ai_role_fit.md](service_ai_role_fit.md) | 服务领域 AI 产品能力映射：行业调研、用户需求、PRD、项目推进、上线指标和创新输入 |
| [service_ai_benchmark.md](service_ai_benchmark.md) | 服务领域 AI 竞品与标杆能力分析：客服 Copilot、工单 Agent、服务质检和客户成功 Copilot 的可迁移设计点 |
| [service_ai_transfer_note.md](service_ai_transfer_note.md) | 服务领域 AI 迁移说明：客服 Copilot、工单 Agent、服务质检等场景迁移 |
| [../product/prd_decision_workbench.md](../product/prd_decision_workbench.md) | 标准 PRD 示例：背景、用户故事、范围、页面流程、输入输出、权限、埋点和验收标准 |
| [../project/mvp_delivery_plan.md](../project/mvp_delivery_plan.md) | MVP 交付计划：需求调研、PRD、原型、开发、联调、灰度、指标看板和风险清单 |
| [portfolio_proof_matrix.md](portfolio_proof_matrix.md) | 作品集证明材料矩阵：真实问题、流程重构、架构、评测、失败、成本、贡献 |
| [ai_native_pm_capability_map.md](ai_native_pm_capability_map.md) | AI Native 产品经理能力映射：场景理解、Agent/RAG、Harness、ToB/SaaS、指标评测和跨团队沟通 |
| [industrial_ai_copilot_solution.md](industrial_ai_copilot_solution.md) | 工业 AI Copilot 方案说明：方案定位、目标用户、系统架构、AI/确定性系统分工、数据边界和交付阶段 |
| [business_process_flow.md](business_process_flow.md) | 业务流程图：当前业务问题流、目标业务流、泳道图、关键决策节点和异常处理状态机 |
| [prototype_logic.md](prototype_logic.md) | 原型逻辑：工作台信息架构、页面逻辑、状态处理、降级策略和验证重点 |
| [metric_system.md](metric_system.md) | 指标体系：North Star、模型/方案/产品/业务/风险分层指标、采集路径和失败样本指标 |
| [evaluation_guardrail_cases.md](evaluation_guardrail_cases.md) | 评测与 Guardrail 用例：数据缺失、证据不足、硬约束失败、越权回写、低置信解释等测试类型 |
| [failure_iteration_log.md](failure_iteration_log.md) | 失败案例与迭代记录：失败现象、归因、修复方案、验证方式和剩余风险 |
| [cost_latency_deployment_boundary.md](cost_latency_deployment_boundary.md) | 成本、延迟与部署边界：模型调用边界、延迟控制、Agent 执行范围和 SaaS 化差距 |
| [personal_contribution.md](personal_contribution.md) | 个人贡献说明：问题定义、产品设计、AI 技术方案、工程实现、验证和公开交付 |
| [project_report_materials.md](project_report_materials.md) | 项目汇报材料：10 页汇报结构、三分钟汇报稿、答辩问题和材料包索引 |
| [product_portfolio.md](product_portfolio.md) | 项目总览：真实问题、用户场景、为什么使用 AI、方案设计、评测与结果 |
| [../product/reorch_product_overview.md](../product/reorch_product_overview.md) | 产品说明书：定位、目标用户、端到端闭环、数据门槛、系统边界和上线条件 |
| [ngs_lab_specialized_portfolio.md](ngs_lab_specialized_portfolio.md) | NGS 实验室特化版：把通用异常决策内核迁移到 NGS-LRSP 修复排程场景，并对应到后端 API、前端页面、质量门和 Agent trace |
| [project_capability_evidence.md](project_capability_evidence.md) | 项目能力证据、适用边界和后续迭代说明 |

## 2. 系统设计材料

| 文档 | 证明重点 |
| --- | --- |
| [workflow_prompts_io.md](workflow_prompts_io.md) | Agent/Workflow 设计、Prompt 结构、输入输出示例和人机协作边界 |
| [ai_increment_agent_design.md](ai_increment_agent_design.md) | 将异常理解、规则候选、推荐解释、案例沉淀和偏好学习拆成独立 Agent，说明输入输出、质量门和能力边界 |
| [trust_quality_gate.md](trust_quality_gate.md) | LLM 输出可信性、硬约束、质量门、置信度、审计和兜底机制 |

## 3. 验证与状态材料

| 文档 | 证明重点 |
| --- | --- |
| [project_status_assessment.md](project_status_assessment.md) | 当前 MVP 状态、成本控制、商业化价值、上线边界和后续计划 |
| [../validation/digital_twin_validation_pack.md](../validation/digital_twin_validation_pack.md) | 数字孪生验证证据：source refs、成本代理、replay/shadow 代理、阈值和审计包 |
| [../validation/lab_replay_acceptance_evidence.md](../validation/lab_replay_acceptance_evidence.md) | 实验室 replay 的采纳、微调、驳回和失败归因样本 |
| [../validation/failure_case_library.md](../validation/failure_case_library.md) | 失败样本库：说明系统何时不推荐、不写回、退回人工 |
| [../validation/llm_agent_offline_eval.md](../validation/llm_agent_offline_eval.md) | 真实 LLM Agent 接入路径、离线评测指标和确定性降级边界 |

## 4. 市场与演示材料

| 文档 | 证明重点 |
| --- | --- |
| [market_benchmark.md](market_benchmark.md) | 市场需求、行业对标、竞争格局、试点路径和商业假设 |
| [kingdee_positioning_note.md](kingdee_positioning_note.md) | 以金蝶为现实参照，说明 ReOrch 的补位、首期场景、价值验证和能力边界 |
| [../integration/data_readiness_stop_rules.md](../integration/data_readiness_stop_rules.md) | 客户数据接入停损线、产品降级策略和最低字段合同 |
| [../demo/customer_demo_walkthrough.md](../demo/customer_demo_walkthrough.md) | 可互动 demo 的演示路径和操作流程 |

## 推荐阅读路径

```text
portfolio_brief.md
-> service_ai_role_fit.md
-> service_ai_benchmark.md
-> service_ai_transfer_note.md
-> ../product/prd_decision_workbench.md
-> ../project/mvp_delivery_plan.md
-> portfolio_proof_matrix.md
-> ai_native_pm_capability_map.md
-> industrial_ai_copilot_solution.md
-> business_process_flow.md
-> prototype_logic.md
-> metric_system.md
-> evaluation_guardrail_cases.md
-> failure_iteration_log.md
-> cost_latency_deployment_boundary.md
-> personal_contribution.md
-> project_report_materials.md
-> product_portfolio.md
-> ../product/reorch_product_overview.md
-> ngs_lab_specialized_portfolio.md
-> project_capability_evidence.md
-> workflow_prompts_io.md
-> ai_increment_agent_design.md
-> trust_quality_gate.md
-> project_status_assessment.md
-> ../validation/digital_twin_validation_pack.md
-> ../validation/lab_replay_acceptance_evidence.md
-> ../validation/failure_case_library.md
-> ../validation/llm_agent_offline_eval.md
-> ../integration/data_readiness_stop_rules.md
-> market_benchmark.md
-> kingdee_positioning_note.md
-> ../demo/customer_demo_walkthrough.md
```
