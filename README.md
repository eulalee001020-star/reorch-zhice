# ReOrch 智策 - 工业异常调度决策 Copilot

ReOrch 智策是一个面向离散制造车间的 AI 调度决策 MVP：当设备故障、插单、物料延期、质量返工等异常发生后，系统帮助计划员完成影响分析、策略选择、候选方案生成、多目标评估、人工确认、安全回写和案例沉淀。

项目已完成 MVP 开发，当前正在合作实验室做初步试用和验证。后续会根据试用数据、计划员反馈、异常 replay 结果和系统集成情况继续完善。

## 作品集入口

| 材料 | 用途 |
| --- | --- |
| [产品作品集总览](docs/portfolio/product_portfolio.md) | 快速理解项目价值、产品判断和落地证据 |
| [AI 工作流、Prompt 与输入输出示例](docs/portfolio/workflow_prompts_io.md) | 展示 Agent/Workflow 设计、结构化输出、解释与审计样例 |
| [项目能力证据](docs/portfolio/project_capability_evidence.md) | 展示业务判断、AI 适用性、系统设计、工程落地、风险控制和价值验证 |
| [可信性质量门](docs/portfolio/trust_quality_gate.md) | 展示如何判断 LLM 输出是否可信、可行、可审计 |
| [项目状态评估](docs/portfolio/project_status_assessment.md) | 汇总可信性、成本控制、商业价值、上线边界和后续计划 |
| [上线就绪评估](docs/validation/launch_readiness_assessment.md) | 说明当前能支持的上线范围、不能直接生产上线的原因和进入下一阶段的条件 |
| [数字孪生验证包](docs/validation/digital_twin_validation_pack.md) | 用数字孪生结果补齐 source refs、成本代理、replay/shadow 代理、阈值和审计包结构 |
| [市场需求与行业先进标准对标](docs/portfolio/market_benchmark.md) | 说明市场切口、行业对标、竞争格局和试点路径 |
| [客户演示路径](docs/demo/customer_demo_walkthrough.md) | 端到端演示流程与操作说明 |
| [系统蓝图](docs/product/poc_system_blueprint.md) | 展示 PoC 系统边界、AI 职责和工业现场安全闸门 |

## 一句话定位

不是“让大模型直接自动排产”，而是把 AI 放在可控的异常决策流程中：LLM/Agent 负责异常理解、规则候选、策略解释和经验沉淀；约束引擎、求解器、数字孪生、质量门和计划员确认负责正确性与生产责任。

## 三类关键产品判断

| 问题 | ReOrch 的处理方式 |
| --- | --- |
| 为什么上 AI，而不是纯规则/传统 APS/人工试排 | AI 只用于异常语义理解、策略解释、规则候选和经验沉淀；排程可行性仍由求解器、规则和质量门负责 |
| LLM 用什么模型才够，如何降本增效 | MVP 核心链路外部 LLM 调用为 0；后续按任务分层，小模型处理抽取/分类，中等模型处理解释，高风险求解和质量门不用 LLM |
| LLM 结果如何判断能不能用 | 不让 LLM 自证正确；所有输出必须经过 schema、source refs、硬约束、质量门、数字孪生风险评估、审计和人工确认 |

## 当前状态与上线判断

| 维度 | 当前判断 |
| --- | --- |
| 开发进度 | MVP 已完成，具备端到端异常决策闭环和可互动 demo |
| 验证阶段 | 正在合作实验室进行初步试用和验证 |
| 当前可支持 | 实验室试用、内部演示、只读数据验证、数字孪生 replay/shadow 代理验证、人工确认 dry-run |
| 暂不建议 | 直接接入客户生产环境并开放自动写回或无人值守调度 |
| 下一步 | 用数字孪生验证包先行覆盖 source refs、成本代理、replay/shadow 代理、阈值和审计包结构，再结合实验室反馈迭代 |

结论：当前足够支持受控试用和小范围验证，不足以直接作为生产系统上线。若要进入客户现场上线，应先完成只读接入、shadow mode、人工确认回写演练、回滚预案和审计验收。

## 可互动 Demo

本地完整 demo 使用 Docker Compose 启动后端、前端、PostgreSQL/pgvector、Redis、Redpanda 和 mock ERP/MES/APS 集成服务。

```bash
cp .env.example .env
docker compose up --build
```

打开：

```text
http://localhost:3000
```

演示账号：

```text
planner / planner123
```

推荐演示路径：

```text
登录 -> 决策工作台 -> 加载演示场景 -> 影响分析 -> 候选方案
-> 推荐解释 -> 人工确认 -> mock MES 回写 -> 案例库沉淀
```

如果不方便启动外部体验，可以直接查看：

- [AI 工作流、Prompt 与输入输出示例](docs/portfolio/workflow_prompts_io.md)
- [Demo Validation Report](docs/demo/demo_validation_report.md)
- [Frontend Demo Path](docs/demo/frontend_demo_path.md)

## 端到端流程

```mermaid
flowchart LR
  Incident["异常事件"] --> Intake["Incident Intake Agent"]
  Intake --> Snapshot["排程快照"]
  Snapshot --> Impact["影响分析"]
  Impact --> Strategy["策略建议"]
  Strategy --> Solver["混合求解器"]
  Solver --> Gate["方案质量门"]
  Gate --> Eval["多目标评价"]
  Eval --> Explain["推荐解释"]
  Explain --> Confirm["计划员确认"]
  Confirm --> Writeback["受控回写"]
  Confirm --> Case["案例沉淀"]
  Writeback --> Feedback["执行反馈"]
  Feedback --> Case
```

## 核心能力

| 能力 | 项目体现 |
| --- | --- |
| AI 产品定义 | 明确把 ReOrch 定位为“异常响应层 + 经验资产层”，不是重型 APS 替代品 |
| Agent/Workflow 设计 | 受控多 Agent 流程，所有高风险动作都有结构化输入输出、工具边界和人工确认 |
| 工业数据建模 | WorkOrder、Operation、Machine、ScheduleSnapshot、Incident、DecisionRecord 等 canonical model |
| 多目标决策 | 交付风险、扰动范围、换线、资源切换、可行性、置信度和执行复杂度统一评估 |
| 安全与治理 | schema 校验、数据追溯、硬约束质量门、置信度降级、人工确认、幂等回写、审计记录 |
| 商业化试点 | 离散制造 PoC 数据模板、验收指标、ROI 测算、4-6 周落地路径 |
| 工程落地 | FastAPI、React、Ant Design、OR-Tools、Docker Compose、CI 与自动化测试 |

## 验证命令

```bash
pytest -q
cd frontend && npm run build
make demo-validate
```

当前公开分支验证：

```text
706 passed
frontend production build passed
demo data validation passed
```

## 项目结构

```text
app/          FastAPI 后端、领域模型、Agent 工作流、求解器、确认和回写模块
frontend/     React + Ant Design 前端工作台
demo/         固定 sandbox 演示数据和 demo reset/seed 脚本
benchmark/    异常重排 benchmark、客户样例包、回放和训练数据生成脚本
docs/         产品、商业、集成、试点、验证和 portfolio 文档
.github/      CI: backend tests、frontend build、compose smoke
```

## 技术栈

- Backend: FastAPI, Pydantic v2, SQLAlchemy, PostgreSQL/pgvector, Redis, Redpanda/Kafka, OR-Tools
- Frontend: React, TypeScript, Ant Design, Zustand, Vite
- AI/product workflow: controlled Agent orchestration, prompt-to-structure, rule candidate generation, explainability, case memory
- Deployment: Docker Compose, GitHub Actions smoke validation

## 非宣传边界

本项目证明的是 MVP 已完成、可互动 demo 可运行、核心异常决策闭环可验证，并已进入合作实验室初步试用。它不等同于客户生产系统正式上线，也不能宣称大模型可以绕过求解器、质量门或计划员审批直接修改生产计划。
