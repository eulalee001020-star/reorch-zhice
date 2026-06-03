# 个人贡献说明

## 1. 贡献范围

ReOrch 智策的作品集价值在于完整闭环，而不是单个界面或单段 Prompt。项目覆盖问题定义、产品方案、Agent/Workflow、数据模型、前后端实现、测试、验证材料和公开作品集包装。

## 2. 产品设计贡献

| 贡献 | 内容 |
| --- | --- |
| 问题定义 | 将项目从“AI 排产”收敛为“异常响应层 + 经验资产层”，避免直接挑战 APS/MES 主系统 |
| 用户场景 | 定义计划员、生产主管、调度执行端、IT/集成、质量/审计角色的使用边界 |
| 工作流设计 | 设计 Incident Intake、Snapshot Lock、Impact、Strategy、Solver、Quality Gate、Explanation、Confirmation、Writeback、Case Memory |
| 原型逻辑 | 设计决策工作台、规则审核、偏好画像、数据就绪、Evidence Center、NGS Lab 的页面职责 |
| 指标体系 | 设计闭环率、time-to-candidate、Top-K feasible coverage、adoption、delay reduced、audit completeness 等指标 |
| 风险边界 | 明确不自动排产、不承诺生产上线、不绕过人工确认、不把 synthetic 验证当客户生产验证 |

## 3. AI 与技术方案贡献

| 贡献 | 内容 |
| --- | --- |
| Agent 边界 | 将 LLM 限定在语义理解、规则候选、推荐解释和反馈结构化，不负责最终可行性 |
| Prompt contract | 为 Incident Intake、Constraint Compiler、Strategy Advisor、Explanation、Case Memory 设计结构化输入输出 |
| Harness 设计 | 通过 schema、source refs、quality gate、fallback reason、audit record 和测试约束模型不确定性 |
| Evidence Layer | 将推荐解释绑定到工单、工序、设备、排程快照、质量门结果和历史案例 |
| NGS 特化 | 将通用异常决策内核迁移到 NGS Lab 的 sample、QC、reagent、hold-time、pool/run、index compatibility 场景 |

## 4. 工程实现贡献

| 层级 | 内容 |
| --- | --- |
| 后端 | FastAPI API、Agent workflow、Evidence Center、LLM Agent Client、NGS Lab service、quality gate 和测试 |
| 前端 | 决策工作台增强、规则审核、偏好画像、数据就绪、Evidence Center、NGS Lab 页面 |
| 数据 | demo sandbox、NGS experiment package、mapping validation、data readiness stop rules |
| 验证 | 后端测试、前端 build、demo validation、LLM offline eval、failure cases、lab replay evidence |
| 公开交付 | README 首屏、PDF/DOCX/ZIP 材料包、作品集文档索引和打包脚本 |

## 5. 关键取舍

| 取舍 | 理由 |
| --- | --- |
| 不做无人值守自动调度 | 工业现场有硬约束、权限和生产责任，必须保留人工确认 |
| 不把 LLM 放进求解和质量门 | 可行性判断需要确定性系统和可复核规则 |
| 不把单次案例升级为规则 | 现场规则需要审核、replay 和版本发布 |
| 先做只读/shadow，再做回写 | 降低客户现场试点风险，保留审计与回滚空间 |
| 保留 synthetic / digital-twin-style 边界 | 避免把代理验证包装成真实生产验证 |

## 6. 可复核成果

- 公开仓库 README 与作品集入口。
- 可互动 Docker Compose demo。
- 后端 API、前端页面、测试和 demo 数据。
- PDF/DOCX/ZIP 作品集材料包。
- 评测、失败样本、成本延迟边界和项目汇报材料。
