# Source Notes

版本：2026-07-04

## 项目内部证据

| 证据 | 本地路径 |
| --- | --- |
| 项目总入口和功能清单 | `README.md` |
| 产品说明书 | `docs/product/reorch_product_overview.md` |
| 商业计划书 | `docs/business/reorch_business_plan.md` |
| 上线就绪评估 | `docs/validation/launch_readiness_assessment.md` |
| 实验室 replay 与采纳证据 | `docs/validation/lab_replay_acceptance_evidence.md` |
| LLM Agent 离线评测 | `docs/validation/llm_agent_offline_eval.md` |
| Data Readiness 停损规则 | `docs/integration/data_readiness_stop_rules.md` |
| P0 Reality Harness | `docs/validation/p0_reality_harness.md` |
| 约束标定验证 | `docs/validation/constraint_calibration.md` |
| Replay / Shadow 验证 | `docs/validation/replay_shadow_validation.md` |
| Shadow case 只读采集 | `docs/validation/shadow_mode_capture.md` |
| Agent 成本与可观测性 | `docs/validation/agent_observability_cost.md` |
| 数字孪生验证包 | `docs/validation/digital_twin_validation_pack.md` |
| Recovery Policy Graph 护城河架构 | `docs/architecture/recovery_policy_graph.md` |
| 大规模柔性作业车间试点能力包 | `docs/architecture/large_flexible_shop_pilot_capabilities.md` |
| Constraint-to-Recovery 技术栈 | `docs/architecture/constraint_to_recovery_technical_stack.md` |
| Constraint-to-Recovery 验证 | `docs/validation/constraint_to_recovery_kernel.md` |
| 前端截图 | `docs/assets/screenshots/` |
| 原始 BP | `investor_roadshow/source_materials/ReOrch_智策_原路演BP.pdf` |
| 完整 APS 能力路线 | `investor_roadshow/ReOrch_从异常重决策到完整排产系统能力清单_20260704.md` |
| 实验室采用与数字孪生复刻案例 | `investor_roadshow/ReOrch_智策_实验室采用与数字孪生复刻案例_20260704.md` |

## 市场和政策来源

| 来源 | 路演中使用方式 |
| --- | --- |
| 工信部等八部门《“人工智能+制造”专项行动实施意见》：https://www.nda.gov.cn/sjj/zwgk/zcfb/0112/20260107214358696030895_pc.html | 证明政策方向明确支持制造业 AI、工业智能体、排产调度、供应链管理、数据治理和安全治理 |
| IDC FutureScape 2026 中国制造业预测：https://www.idc.com/resource-center/blog/idc-futurescape-2026-%E5%8D%81%E5%A4%A7%E9%A2%84%E6%B5%8B%EF%BC%9A%E4%B8%AD%E5%9B%BD%E5%88%B6%E9%80%A0%E4%B8%9A%E8%BF%88%E5%90%91%E8%87%AA%E4%B8%BB%E5%8C%96%E8%BF%90%E8%90%A5%E7%9A%84%E5%8D%81/ | 证明 AI APS、IT/OT 融合 Agent、人机协同和自主化运营是 2026-2030 的制造业趋势 |
| 深圳市“人工智能+”先进制造业行动计划（2026-2027年）：https://gxj.sz.gov.cn/xxgk/xxgkml/qt/tzgg/content/post_12645602.html | 证明先进制造区域正在推动智能排程、动态产能规划、供应链风险预警、设备异常诊断和工业智能体 |
| IDC 2026 中国 ICT 市场趋势：https://www.idc.com/resource-center/blog/%E4%BB%8E2025%E5%B9%B4%E5%9B%BD%E6%B0%91%E7%BB%8F%E6%B5%8E%E8%BF%90%E8%A1%8C%E6%83%85%E5%86%B5%E7%9C%8B2026%E5%B9%B4%E5%B8%82%E5%9C%BA%E5%8F%98%E5%8C%96%E8%B6%8B%E5%8A%BF%EF%BC%9A%E4%BB%8E%E6%8A%95/ | 证明企业 IT 采购更关注价值优化、软件和 AI 应用、持续价值交付 |
| Fortune Business Insights Smart Manufacturing Market 2026-2034：https://www.fortunebusinessinsights.com/smart-manufacturing-market-103594 | 作为宽口径智能制造市场背景，不直接等同于 ReOrch 的可服务市场 |
| Deloitte 2026 Manufacturing Industry Outlook：https://www.deloitte.com/us/en/insights/industry/manufacturing-industrial-products/manufacturing-industry-outlook.html | 辅助判断制造企业在 2026 年继续加大智能制造和定向技术投资 |
| McKinsey State of AI 2025：https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai | 辅助判断企业 AI 正从试点走向规模化，但规模化仍需要管理、数据、技术和运营体系 |

## Claim Boundary

- 可以说：MVP 已完成，具备受控试用和历史 replay 基础。
- 可以说：产品定位是异常重决策操作层，不替代 ERP/MES/APS。
- 可以说：长期路线是从异常重决策切入，补齐完整 APS 能力后逐步减少客户对传统排产系统的依赖。
- 可以说：受控 replay case 证明系统能记录采纳、微调、驳回和失败原因。
- 可以说：Recovery Policy Graph 是长期护城河设计，下一阶段通过客户只读 replay、shadow mode 和执行反馈沉淀。
- 不应说：已经完成客户生产上线。
- 不应说：可以无人值守自动调度。
- 不应说：现有 replay 采纳率等于客户现场 ROI。
- 不应说：当前已经完成企业级 Recovery Policy Graph 商业验证。
- 不应说：所有 APS 都不能重排。
- 不应说：企业接入 ReOrch 后立刻不需要其他排产系统。
