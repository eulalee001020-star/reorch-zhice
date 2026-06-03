# MVP 交付计划与项目推进

## 1. 交付目标

ReOrch MVP 的交付目标是验证“异常发生后的 AI 决策辅助闭环”，而不是一次性完成生产系统替换。MVP 成功标准是：目标用户能在 sandbox / 只读数据环境中完成异常识别、影响分析、候选方案对比、质量门检查、人工确认和审计复盘。

## 2. 阶段计划

| 阶段 | 周期 | 关键工作 | 输出物 | 验收点 |
| --- | --- | --- | --- | --- |
| 需求调研 | W1 | 访谈计划员、生产主管、IT、质量/审计；梳理异常类型和现有流程 | 用户画像、痛点清单、流程图、数据清单 | 明确首个高频异常场景和不做范围 |
| PRD 与原型 | W1-W2 | 编写 PRD、页面流程、状态机、权限与异常状态；完成原型评审 | `prd_decision_workbench.md`、`prototype_logic.md` | 研发可按模块拆任务，业务能理解流程 |
| 数据与接口 | W2 | 建立 canonical model、adapter contract、readiness gate | 数据字段表、mapping validation、stop rules | 缺字段能阻断或降级，不误出强推荐 |
| AI / Solver 开发 | W2-W3 | 实现 Incident Intake、Strategy、Explanation、Case Memory、solver 和 quality gate | Agent workflow、Top-K 候选、quality gate | 高风险动作不由 LLM 自主决定 |
| 前后端开发 | W3-W4 | 工作台、规则审核、偏好画像、Evidence Center、NGS Lab | 可互动页面、API、Agent trace | 用户可走完整 demo flow |
| 联调与测试 | W4 | API 联调、前端 build、demo validation、guardrail cases | 测试报告、失败样本、修复记录 | 后端测试、前端构建、ZIP 检查通过 |
| 试用与灰度 | W5-W6 | 只读接入或 sandbox replay，收集采纳、驳回、override 和失败原因 | shadow report、指标看板、迭代 backlog | 形成下一轮阈值、权限和体验优化 |

## 3. 责任分工

| 角色 | 责任 |
| --- | --- |
| 产品负责人 | 行业调研、用户需求、PRD、原型评审、指标体系、试点范围控制 |
| 后端研发 | 领域模型、API、solver、quality gate、persistence、integration adapter |
| 前端研发 | 决策工作台、状态展示、候选方案对比、确认与审计页面 |
| AI / 算法 | Agent contract、Prompt、fallback、离线评测、失败样本归因 |
| 业务代表 | 异常场景确认、验收标准、试用反馈、override reason 标注 |
| IT / 集成 | 数据权限、接口、SSO/RBAC、日志、运维和回写演练 |

## 4. 风险清单

| 风险 | 影响 | 控制方式 |
| --- | --- | --- |
| 数据字段缺失或口径不一致 | 无法生成可信候选 | 先做 data readiness 和 adapter contract |
| 业务期望全自动接管 | 责任边界过高 | 坚持只读、shadow、人工确认、受控回写四阶段 |
| LLM 输出过度自信 | 用户忽视风险 | source refs、confidence、fallback reason、quality gate 前置展示 |
| 规则候选未经验证就生效 | 现场约束冲突 | pending / approved / rejected / released 状态机和 replay |
| 项目范围膨胀 | MVP 延期 | 限定 1 个车间、1 类异常、1 套只读数据源 |
| 指标不可采集 | 无法判断试点价值 | 在 PRD 阶段定义埋点和上线指标 |

## 5. 上线指标看板

| 指标 | 目标方向 | 采集方式 |
| --- | --- | --- |
| 异常到候选方案时间 | 缩短 | Incident timestamp、candidate generated timestamp |
| Top-K 可行覆盖率 | 提升 | quality gate pass/warn/block |
| 推荐采纳率 | 提升 | confirmation record |
| 人工 override 原因填写率 | 提升 | override form 和 CaseRecord |
| 数据就绪阻断率 | 下降但不强行绕过 | readiness report |
| 回写失败率 | 下降 | writeback audit |
| 审计完整率 | 接近 100% | DecisionRecord、AuditLog、AgentTrace |
| 失败样本复盘闭环率 | 提升 | failure case library |

## 6. 创新输入机制

创新不依赖一次性头脑风暴，而来自可持续输入：

- 行业调研：政策、主系统厂商、APS/MES/AI Copilot 案例和客户流程。
- 用户反馈：计划员采纳、驳回、微调、override reason 和访谈记录。
- 技术输入：Agent、RAG、tool calling、workflow、evaluation harness、guardrail 方案。
- 失败样本：数据缺失、低置信、硬约束冲突、解释不充分、权限越界。
- 迁移场景：从制造异常扩展到 NGS Lab，再抽象到服务工单、客服 Copilot 和质检 Agent。

## 7. 当前状态

当前仓库已完成 MVP 级 demo、后端 API、前端工作台、Agent workflow、质量门、失败样本、PDF/DOCX/ZIP 材料包和自动化验证。下一阶段更适合进入只读接入、shadow mode 和服务场景迁移 PRD，而不是继续堆叠概念文档。
