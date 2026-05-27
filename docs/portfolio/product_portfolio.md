# ReOrch 智策产品作品集

项目：ReOrch 智策  
定位：制造业异常调度决策 Copilot  

## 1. 项目摘要

ReOrch 智策解决的是复杂离散制造中“计划被现场异常打断后，如何快速形成可信、可执行、可追溯的新方案”的问题。系统不把大模型包装成万能排产器，而是用 AI 组织异常理解、影响分析、策略解释、规则候选和经验沉淀，再由确定性求解器、质量门、数字孪生和计划员确认保证生产责任。

当前进度：MVP 已完成，正在合作实验室进行初步试用和验证。现阶段目标是验证流程可用性、数据适配、约束覆盖、计划员接受度和风险提示效果；后续会根据试用反馈继续完善。

材料索引：

| 要求 | 对应材料 |
| --- | --- |
| GitHub 链接 | 本仓库首页 README |
| 可互动 demo | `docker compose up --build` 后访问 `http://localhost:3000` |
| 工作流说明 | [workflow_prompts_io.md](workflow_prompts_io.md) |
| Prompt 说明 | [workflow_prompts_io.md](workflow_prompts_io.md) 第 3 节 |
| 输入输出效果示意 | [workflow_prompts_io.md](workflow_prompts_io.md) 第 4 节 |
| AI PM 能力自查 | [ai_pm_portfolio_self_check.md](ai_pm_portfolio_self_check.md) |
| 市场需求说明 | [market_benchmark.md](market_benchmark.md) |
| 验收与验证证据 | `pytest -q`、`frontend build`、`docs/demo/demo_validation_report.md`、`docs/validation/digital_twin_validation_pack.md`、合作实验室试用反馈 |

## 2. 为什么选择这个场景

复杂制造企业常见现状不是“没有系统”，而是 ERP/MES/APS/Excel/微信群/电话共同存在。ERP/MES 擅长记录和执行，APS 擅长基准排程，但现场异常发生后的跨角色决策闭环往往仍依赖少数计划员经验。

高频异常包括：

- 设备故障或维修超时。
- 插单、急单和交期变化。
- 物料延期或齐套风险。
- 质量返工。
- 瓶颈资源冲突。
- 换线、夹具、刀具、人员技能等现场隐性约束。

项目的关键判断是把产品切口收窄到“异常响应层”，而不是直接挑战成熟 APS 的全厂级计划能力。这样更符合 B 端产品从实验室试用、单车间验证、单异常高频痛点逐步推进的落地规律。

### 2.1 用户与场景拆解

| 维度 | 内容 |
| --- | --- |
| 核心用户 | 计划员、生产主管、车间调度、IT/系统集成负责人 |
| 使用频率 | 设备故障、维修超时、插单、物料延迟等异常发生时触发 |
| 输入信息 | 异常事件、排程快照、工单、工序、设备、日历、物料、预计恢复时间 |
| 期望输出 | 影响范围、候选方案、交付/扰动/换线/风险指标、推荐理由、回写预览 |
| 决策点 | 是否等待维修、局部修复、滚动窗口重排或全局重排 |
| 风险点 | 硬约束不可行、延期误判、过度扰动、越权回写、解释不可追溯 |
| 成功标准 | 异常到方案时间下降、确认前硬约束可行率 100%、计划员采纳率提升、审计可追溯 |

### 2.2 为什么使用 AI

| 替代方案 | 局限 | ReOrch 的取舍 |
| --- | --- | --- |
| 纯规则系统 | 适合固定规则，但难以覆盖现场异常表达、隐性偏好和复杂取舍解释 | 用规则和求解器保证可行性，用 AI 处理语义理解、解释和经验沉淀 |
| 传统 APS 重排 | 强在基准排程和优化，但异常协同、解释、人工 override 沉淀通常较弱 | 不替代 APS，而是在其上做异常响应层 |
| Excel/人工试排 | 灵活但慢、不可追溯，依赖少数计划员经验 | 将异常决策流程产品化，保留人工确认 |
| 自由聊天式 Agent | 输出不可控，难以承担生产责任 | 采用受控 Workflow，所有高风险动作经过质量门和人工确认 |

AI 的增量价值不是“自动排产”，而是把模糊异常输入转成结构化决策上下文，把多目标取舍解释给计划员，并把人工选择和 override 原因沉淀成可复用案例资产。

## 3. 产品能力矩阵

| 能力 | 项目体现 | 证据 |
| --- | --- | --- |
| AI 应用产品定义 | 把大模型能力放入可控工作流，明确 Agent、Workflow、求解器和人工确认边界 | `docs/product/poc_system_blueprint.md` |
| 真实业务洞察 | 选择复杂离散制造异常重排作为首批场景，并收敛到单车间、单异常 MVP 验证 | `docs/business/reorch_business_plan.md` |
| 产品规划能力 | Lab Trial -> Pilot -> Convert -> Expand，先完成实验室验证，再推进客户试点 | `docs/business/reorch_business_plan.md` |
| 数据与指标意识 | 异常到方案时间、硬约束可行率、数字孪生 replay/shadow 代理、延期减少、扰动降低、ROI | `frontend/src/pages/PocDashboardPage.tsx` |
| Agent/Workflow 设计 | Incident Intake、Impact、Strategy、Solver、Explanation、Case Memory、Audit 分工 | [workflow_prompts_io.md](workflow_prompts_io.md) |
| 工程落地意识 | FastAPI + React + Docker Compose + CI + mock integration + sandbox demo | 根目录 README 与 `.github/workflows/ci.yml` |
| 安全治理意识 | schema 校验、硬约束质量门、置信度降级、人工确认、幂等、审计 | [trust_quality_gate.md](trust_quality_gate.md) |
| 商业判断 | 不夸大“AI 自动排产”，先用数字孪生和实验室试用验证价值，再推进客户现场试点 | [market_benchmark.md](market_benchmark.md) |

## 4. 产品设计原则

### 4.1 AI 做什么

- 把自然语言异常、MES 告警、维修估计转成结构化 Incident。
- 根据排程快照识别受影响工序、工单、资源和交付风险。
- 生成策略候选：等待维修、局部修复、滚动窗口重排、全局重排。
- 将自然语言规则转成待审核 constraint candidate。
- 解释 Top-K 候选方案的交付、扰动、换线和执行风险。
- 把计划员选择、override 原因和执行反馈沉淀为案例资产。

### 4.2 AI 不做什么

- 不直接生成最终生产计划。
- 不绕过硬约束校验。
- 不绕过计划员确认直接写回 MES/APS。
- 不把未验证案例直接升级为硬规则。
- 不把 sandbox、实验室试用或 synthetic benchmark 宣称为客户生产系统正式上线。

在工业场景，可信 AI 产品的关键不是“让模型更自主”，而是让模型在正确的责任边界内提高协同效率和解释效率。

### 4.3 可信性质量门

ReOrch 不依赖 LLM 自我判断结果是否正确，而是设置外部质量门：

| 判断项 | 标准 |
| --- | --- |
| 结构合法 | schema、枚举、时间、ID、必填字段通过校验 |
| 数据可追溯 | 影响结论能回到 Incident、ScheduleSnapshot、工序、设备和工单 |
| 硬约束 | 推荐前 100% 通过设备能力、工序顺序、资源互斥等核心校验 |
| 业务风险 | 明确暴露延期、扰动、换线、solver 降级和执行复杂度 |
| 置信度 | 低置信度不自动预选，必须提示人工确认 |
| 审计 | 推荐、确认、覆盖、回写和执行反馈均留痕 |

详细实现状态见 [trust_quality_gate.md](trust_quality_gate.md)。

## 5. Demo 讲解路径

1. 登录 `planner / planner123`。
2. 打开“决策工作台”。
3. 点击“加载演示场景”。
4. 说明场景：`M-03` CNC 单元突发故障，预计停机 4 小时，急单存在延期风险。
5. 展示影响分析：受影响工序、工单、资源、交期风险。
6. 展示候选方案：等待维修、局部修复、滚动窗口重排、全局重排。
7. 展示多目标评价：延期、扰动、换线、资源切换、可行性、置信度。
8. 展示推荐解释：为什么推荐方案在交付和执行稳定性之间更均衡。
9. 点击确认采纳，展示 mock MES/APS 受控回写。
10. 打开案例库，展示决策记录和经验沉淀。

## 6. 可快速验证的证据

| 证据 | 当前状态 |
| --- | --- |
| 后端测试 | `pytest -q`: 706 passed |
| 前端构建 | `npm run build` 通过 |
| Demo 数据校验 | 69 条记录，0 blocking error |
| Sandbox 数据 | 12 个工单、48 道工序、8 台设备、1 个核心异常 |
| 数字孪生验证 | 5 套初始方案、5 个受影响工序、1 个可行重排方案、风险分 0.2462、单次价值估算 7385 元 |
| 实验室验证 | MVP 已进入合作实验室初步试用 |
| 安全边界 | 人工确认前不回写，生产接入从只读和 shadow mode 开始 |
| 上线判断 | 当前支持受控试用和验证，不建议直接生产上线 |

## 6.1 评测与迭代

| 层级 | 指标 | 当前证据 |
| --- | --- | --- |
| 模型/结构层 | schema 通过率、结构化输出稳定性、source refs 覆盖 | Pydantic、TypeScript types、`validation_evidence.source_refs` |
| 方案层 | 硬约束可行率、质量门结果、执行风险分 | `PlanQualityGate`、数字孪生风险分 0.2462 |
| 产品层 | 异常到方案时间、人工确认率、低置信人工介入率 | 数字孪生代理：90 分钟人工基线 vs 8 分钟系统决策 |
| 业务层 | 延期减少、换线减少、加班减少、估算价值 | 数字孪生代理：延期减少 150 分钟、换线减少 3 次、估算价值 7385 元 |
| 风险层 | 越权回写、硬约束失败、审计缺失、回滚缺失 | 人工确认、mock writeback、`audit_package_proxy` |

当前暴露的典型失败/边界样本：

| 样本 | 现象 | 处理 |
| --- | --- | --- |
| 数字孪生重排扰动较大 | `large_schedule_perturbation`，质量门置信度为 `medium` | 不自动写回，要求计划员确认 |
| 约束覆盖有限 | 质量门 warning：constraint coverage limited | 在合作实验室验证物料、人员、工装夹具等现场约束 |
| 生产上线边界 | MVP 可受控试用，但不适合无人值守自动调度 | 上线就绪评估要求只读接入、shadow mode、回滚和审计验收 |

## 7. 三分钟项目介绍

可以这样介绍：

```text
ReOrch 智策不是一个“AI 排产聊天机器人”，而是工业异常调度的受控决策 Copilot。
复杂制造企业真正痛的是计划执行中持续被设备故障、插单、物料和返工打断，
计划员要在交付、扰动、换线、瓶颈和加班之间做权衡。

我的产品方案是把异常发生后的流程产品化：
先锁定排程快照，再做影响分析，再生成多策略候选方案，
再通过硬约束质量门和多目标指标评估，最后由计划员确认后受控回写。
AI 负责异常理解、规则候选、解释和案例沉淀，不直接越权改生产计划。

项目里有可运行前端 demo、后端 API、Docker Compose、测试、MVP 数据模板、
prompt 工作流和实验室验证路径，展示从问题定义到受控验证的完整闭环。
```

## 8. 后续迭代路线

| 阶段 | 目标 | 成功标准 |
| --- | --- | --- |
| P0 | MVP 完成与合作实验室试用 | 10-30 分钟内生成可解释候选方案，收集试用反馈 |
| P1 | 数字孪生 replay/shadow 代理 + 合作实验室复核 | Top-N 覆盖、低风险场景采纳率和计划员反馈可量化 |
| P2 | 客户现场受控试点 | 只读接入、人工确认 dry-run、审计包和回滚预案齐备 |
| P3 | 生产小范围上线 | 全链路审计、幂等、防重复提交、失败回滚和运维验收齐备 |

## 9. 参考对标

- 阿里云 Model Studio 将应用分为 Agent、Workflow 和高代码应用，并指出需要固定、可重复、明确输入输出时应使用 Workflow 思路：[阿里云百炼应用类型介绍](https://help.aliyun.com/zh/model-studio/application-introduction)。
- 阿里云英文文档同样强调 Workflow 更适合 deterministic control 和 auditable steps：[Model Studio application overview](https://www.alibabacloud.com/help/en/model-studio/application-introduction)。
- 工信部等六部门 2025 年智能工厂梯度培育行动明确把基础级、先进级、卓越级、领航级作为智能工厂升级路径，并要求卓越级/领航级探索或深度应用人工智能技术：[工信部通知](https://www.miit.gov.cn/zwgk/zcwj/wjfb/tz/art/2025/art_57f2e7f7bdfd4bf1bd52e4fbdcd6d69e.html)。
