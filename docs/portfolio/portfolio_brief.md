# ReOrch 智策 AI 产品作品集摘要

项目：ReOrch 智策
定位：工业异常调度决策 Copilot
日期：2026-06-03

## 1. 项目定位

ReOrch 智策面向复杂离散制造中的异常调度决策：当设备故障、插单、物料延期、质量返工等事件打断原计划后，系统帮助计划员完成影响分析、策略选择、Top-K 候选方案比较、质量门校验、推荐解释、人工确认、受控回写和案例沉淀。

项目的核心判断不是让大模型直接自动排产，而是把 AI 放在可控工作流中。LLM/Agent 负责异常理解、规则候选、推荐解释、案例沉淀和偏好学习；求解器、硬约束、数字孪生验证、质量门、人工确认和审计链路负责生产责任。

## 2. 业务问题

复杂制造企业通常已经有 ERP、MES、APS 和现场 Excel/人工沟通流程，但异常发生后的重排决策仍高度依赖计划员经验。设备故障、急单插入、物料延迟、质量返工和瓶颈资源冲突会同时影响交期、扰动范围、换线成本和执行风险。

ReOrch 的产品切口不是替换主系统，而是在主系统之上补“异常响应层”和“经验资产层”：把异常发生后的判断链路结构化、可解释化、可审计化，并让人工确认后的决策沉淀为可复用案例。

## 3. AI 能力证据

| 能力 | 项目证据 |
| --- | --- |
| AI 产品定义 | 将 AI 限定在语义理解、解释、规则候选和经验沉淀；不替代 APS/MES/LIMS 主系统 |
| Agent/Workflow | Incident Intake、Constraint Compiler、Strategy Advisor、Explanation、Case Memory 等受控 Agent |
| 系统设计 | Incident -> Impact -> Solver -> Quality Gate -> Recommendation -> Confirmation -> Writeback -> Case Memory |
| 评测与质量门 | schema、source refs、硬约束、风险阈值、数字孪生 replay、失败样本库和人工确认 |
| 工程落地 | FastAPI、React、OR-Tools、Docker Compose、mock integration、测试和 CI 验证材料 |
| 商业判断 | 先实验室试用和只读/shadow 验证，再进入客户现场；不宣称已生产上线 |

## 4. 工作流与演示

```text
Incident Intake
-> Snapshot Lock
-> Impact Analysis
-> Strategy Advice
-> Candidate Plan Generation
-> Quality Gate
-> Multi-objective Evaluation
-> Recommendation Explanation
-> Human Confirmation
-> Controlled Writeback
-> Case Memory
```

本地互动 demo 可通过 Docker Compose 启动：

```bash
cp .env.example .env
docker compose up --build
```

访问 `http://localhost:3000`，演示账号为 `planner / planner123`。

核心演示路径：

```text
登录
-> 决策工作台
-> 加载演示场景
-> 影响分析
-> Top-K 候选方案
-> 推荐解释
-> 人工确认
-> 受控回写
-> 案例库
```

NGS 特化版路径：

```text
登录
-> NGS Lab
-> batch package replay
-> hard gate
-> planner confirmation / override
```

## 5. 验证证据

| 证据 | 当前状态 |
| --- | --- |
| 后端测试 | `pytest -q` 已覆盖核心模型、API、Agent workflow、质量门和 demo sandbox |
| 前端构建 | React + TypeScript + Vite production build 已通过 |
| Demo 数据 | 69 条 sandbox 记录，0 blocking error |
| 数字孪生验证 | 已给出 source refs、replay/shadow 代理、风险分、阈值和审计包结构 |
| 失败样本库 | 明确不推荐、不自动写回、退回人工判断的条件 |
| LLM Agent 离线评测 | 默认确定性降级可复现；真实 LLM Agent 支持模型、token、latency 和降级原因记录 |

## 6. 关键边界

- 当前项目证明的是 MVP、受控试用和 demo 级闭环，不等于客户生产系统正式上线。
- 默认 demo 可在无外部 LLM API Key 的情况下复现；真实 LLM Agent 是可配置路径。
- 系统不支持无人值守自动调度；生产回写必须经过人工确认、权限校验、回写预览和审计。
- 数字孪生、synthetic package 和实验室 replay 是验证代理，不能替代客户现场数据、财务口径和上线验收。

## 7. 材料索引

```text
README.md                                    项目首页与作品集入口
docs/portfolio/product_portfolio.md          产品作品集总览
docs/portfolio/ai_native_pm_capability_map.md AI Native 产品经理能力映射
docs/portfolio/industrial_ai_copilot_solution.md 工业 AI Copilot 方案说明
docs/portfolio/business_process_flow.md      业务流程图
docs/portfolio/prototype_logic.md            原型逻辑
docs/portfolio/metric_system.md              指标体系
docs/portfolio/project_report_materials.md   项目汇报材料
docs/portfolio/workflow_prompts_io.md        工作流、Prompt 与输入输出示例
docs/portfolio/ai_increment_agent_design.md  AI 增量 Agent 设计
docs/portfolio/trust_quality_gate.md         可信性质量门
docs/validation/                             数字孪生、replay、失败样本、LLM 离线评测
docs/demo/                                   可互动 demo 操作路径和验证报告
app/                                         FastAPI 后端、Agent workflow、求解器、质量门
frontend/src/                                React 前端工作台
demo/                                        sandbox 演示数据与重置脚本
benchmark/                                   benchmark、验收标准和离线评测脚本
```
