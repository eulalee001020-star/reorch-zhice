# 项目能力证据

## 1. 项目定位

ReOrch 智策以复杂离散制造中的异常调度决策为切入点，展示从业务问题识别、AI 适用性判断、系统方案设计、模型不确定性控制、工程实现到价值验证的完整链路。

当前项目采用一个深度业务场景展开，而不是拆分成多个浅层功能展示。核心证据包括受控 Agent 工作流、质量门、数字孪生验证包、可互动 demo、自动化测试和上线边界评估。

## 2. 决策能力证据

| 能力 | 当前证据 | 结论 |
| --- | --- | --- |
| 业务问题判断 | 从离散制造异常重排切入，用户包括计划员、生产主管、车间调度和系统集成负责人 | 具备明确业务场景 |
| AI 适用性判断 | AI 负责异常理解、规则候选、推荐解释、案例沉淀和偏好学习；求解和约束由确定性系统负责 | 边界清晰 |
| 系统方案设计 | 端到端流程覆盖 Incident、Impact、Strategy、Solver、Quality Gate、Confirm、Writeback、Case | 闭环完整 |
| 模型不确定性控制 | schema、source refs、硬约束、质量门、置信度、人机确认、审计 | 有兜底机制 |
| 工程落地 | FastAPI、React、OR-Tools、Docker Compose、CI、demo API、数字孪生接口 | 可运行可验证 |
| 价值验证 | 数字孪生给出决策时间节省、延期减少、换线减少和估算价值 | 已有代理验证结果 |

## 3. 能力映射

| 能力维度 | 项目体现 | 状态 |
| --- | --- | --- |
| 大模型理解 | 明确模型只处理语义、解释、规则候选，不负责最终可行性判断 | 已体现 |
| Agent/Workflow | Incident、Impact、Strategy、Solver、Quality Gate、Explanation、Confirmation 分工清楚 | 已体现 |
| 上下文管理 | 通过 Incident、Snapshot、ImpactReport、CandidatePlan 传递状态 | 已体现 |
| 评测能力 | 后端测试、前端构建、demo validation、digital twin validation evidence | 已体现 |
| 风险控制 | 幻觉、硬约束、回写、权限、审计、上线边界均有控制机制 | 已体现 |
| 工程协作 | API、类型模型、测试、CI、Docker、mock integration | 已体现 |
| 商业判断 | ROI、节省时间、延期减少、试点路径、上线判断 | 已体现 |
| RAG/多模态/微调 | 当前项目主线不依赖这些能力 | 不作为本项目证明重点 |

## 4. 结构完整性

| 模块 | 当前材料 | 说明 |
| --- | --- | --- |
| 项目背景 | [product_portfolio.md](product_portfolio.md) | 说明用户、场景和异常调度痛点 |
| 用户与场景 | [product_portfolio.md](product_portfolio.md) | 包含角色、输入、输出、决策点、风险点和成功标准 |
| AI 适用性 | [product_portfolio.md](product_portfolio.md) | 对比纯规则、传统 APS、人工试排和自由 Agent |
| 系统方案 | [workflow_prompts_io.md](workflow_prompts_io.md) | 展示 Agent/Workflow、Prompt 和输入输出 |
| 可信机制 | [trust_quality_gate.md](trust_quality_gate.md) | 展示 schema、source refs、硬约束、质量门和审计 |
| 验证证据 | [../validation/digital_twin_validation_pack.md](../validation/digital_twin_validation_pack.md) | 展示数字孪生 replay/shadow 代理和审计包结构 |
| 商业判断 | [market_benchmark.md](market_benchmark.md) | 展示市场切口、试点路径和商业假设 |

## 5. 后续完善

| 优先级 | 工作 | 目的 |
| --- | --- | --- |
| P0 | 沉淀合作实验室失败样本库 | 形成真实迭代依据 |
| P0 | 用实验室反馈复核用户场景表 | 将角色、频率、严重度和成功标准从假设升级为验证结果 |
| P1 | 将数字孪生指标替换为实验室试用指标 | 提高价值证明的可信度 |
| P1 | 完善 token telemetry | 接入真实模型后记录模型、token、成本和 latency |
| P2 | 视需要补充独立 RAG 或文档智能项目 | 扩展作品集覆盖面 |
