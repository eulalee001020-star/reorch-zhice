# AI 增量 Agent 设计

这份文档回答一个更尖锐的问题：如果 ReOrch 默认 demo 关闭外部 LLM，而高风险链路又不让模型直接求解，那它的 AI 增量到底在哪里？

答案不是“让模型直接排产”。在高风险工业调度里，真正值得产品化的 AI 增量，是把现场里原本散落在告警文本、计划员经验、人工 override、解释沟通和复盘记录里的信息，变成可验证、可审计、可复用的决策资产。

因此，ReOrch 的 Agent 不负责最终求解。求解、硬约束、质量门、多目标评价和回写仍由确定性服务、优化器和人工确认控制。Agent 只负责五类更适合 AI 介入的工作：异常理解、规则候选、推荐解释、案例沉淀和偏好学习。

## 1. 总体分工

```text
原始异常 / MES 告警
-> 异常理解 Agent
-> 标准 Incident
-> 影响分析 / 求解器 / 质量门 / 多目标评价
-> 推荐解释 Agent
-> 计划员确认 / 拒绝 / override
-> 案例沉淀 Agent
-> 偏好学习 Agent
```

另一条并行资产链路来自人工经验：

```text
计划员规则、override 原因、失败样本
-> 规则候选 Agent
-> 待审核 constraint candidate
-> replay / shadow mode 验证
-> 通过后进入规则库或策略模板
```

这里有一个重要边界：五个 Agent 都可以用 LLM、小模型、规则分类器或混合方式实现。当前实现已把异常理解、规则候选和计划员反馈结构化接入可配置真实 LLM Agent；无 API Key 时自动回到确定性逻辑。影响分析、候选方案生成、质量门、确认和回写仍不交给 LLM，也不能宣称已经完成真实客户生产验证。

## 2. 异常理解 Agent

异常理解 Agent 解决的是“现场说法到系统事件”的问题。计划员可能输入“CNC-03 停了，急单要延期”，MES 可能只给出一条设备告警，维修人员可能补一句“预计 4 小时”。这些信息如果不能稳定变成标准 Incident，后面的影响分析和求解都没有可靠入口。

它的任务不是判断怎么排，而是把异常变成可以进入系统的结构化事实。

| 设计项 | 内容 |
| --- | --- |
| 触发时机 | 计划员手工输入、IoT/MES 告警接入、维修预计恢复时间更新 |
| 输入 | 原始异常文本、告警 payload、发生时间、车间/设备上下文、资源主数据 |
| 输出 | 标准 Incident JSON、字段置信度、风险提示、是否需要人工确认 |
| 允许能力 | 分类、字段抽取、同义词归一、时间/设备 ID 解析、缺失字段提示 |
| 禁止事项 | 不生成候选排程，不判断最终推荐，不绕过人工确认创建高风险事件 |

建议输出结构：

```json
{
  "incident_type": "equipment_failure",
  "resource_id": "M-03",
  "work_order_id": null,
  "occurred_at": "2026-05-27T09:20:00+08:00",
  "estimated_duration_minutes": 240,
  "severity": "high",
  "risk_hints": ["rush_order_delay", "bottleneck_resource"],
  "confidence": 0.86,
  "needs_manual_confirmation": false,
  "source_refs": ["raw_text", "resource_master:M-03"]
}
```

质量门：

- 设备 ID、异常类型、发生时间任一关键字段低置信时，只能进入人工确认。
- 当前 MVP 自动求解只支持设备故障类异常；物料延期、质量返工、插单可以先结构化，但不能伪装成已完整支持。
- 输出必须保留原始文本或告警 source ref，方便后续追溯。

评估指标：

- 结构化字段准确率。
- 人工修正率。
- 低置信异常拦截率。
- 错误自动建单次数，应为 0。
- 异常从输入到标准 Incident 的耗时。

当前状态：`app/services/agent_workflow.py` 中已有 `IncidentAgent`，通过规则、正则和结构化模型完成 MVP 级异常理解；`app/models/agent.py` 中已有 `IncidentUnderstandingOutput`。后续如果接入 LLM，应优先替换抽取/归一层，而不是放开求解权限。

## 3. 规则候选 Agent

规则候选 Agent 解决的是“隐性现场规则如何进入系统”的问题。制造现场经常存在这类规则：某台设备下午不能接急单、某类产品换线成本很高、某个班次缺某种技能、某个工序实际不能替代。它们未必在 ERP/MES/APS 主数据里，但会直接影响计划员是否采纳推荐方案。

它的任务不是发布硬约束，而是把自然语言经验变成待审核的 constraint candidate。

| 设计项 | 内容 |
| --- | --- |
| 触发时机 | 计划员 override、推荐被拒绝、实验室/客户复盘、失败 replay 归因 |
| 输入 | 规则文本、override 原因、相关工序/设备/物料上下文、历史案例 |
| 输出 | 候选规则、适用范围、来源文本、置信度、风险说明、审核状态 |
| 允许能力 | 规则类型识别、适用范围抽取、冲突提示、测试样例生成 |
| 禁止事项 | 不自动变成 hard constraint，不直接改求解器权重，不覆盖主数据 |

建议输出结构：

```json
{
  "candidates": [
    {
      "candidate_id": "constraint_candidate_001",
      "constraint_type": "calendar",
      "scope": {
        "machine_ids": ["M-04"],
        "operation_ids": [],
        "product_family": null
      },
      "source_text": "M4 这班 16:00 以后没人，急单不要往上排",
      "compiled_rule": "avoid assigning urgent jobs to M-04 after 16:00",
      "confidence": 0.78,
      "status": "pending_human_review",
      "risk_note": "需要确认这是临时班次限制还是长期规则"
    }
  ]
}
```

规则生命周期：

```text
candidate
-> planner / process owner review
-> historical replay
-> shadow mode observation
-> soft rule
-> evidence enough 后再考虑 hard rule
```

质量门：

- 没有来源文本的规则不能入库。
- 适用范围不清的规则只能保持 `pending_human_review`。
- 与现有硬约束冲突时不能发布，只能生成冲突报告。
- 单次 override 不能直接升级为全局规则。

评估指标：

- 候选规则人工通过率。
- replay 后的误伤率。
- 同类 override 重复发生率是否下降。
- 候选规则导致的求解不可行次数。

当前状态：`RuleCandidateAgent` 已在 `app/services/agent_workflow.py` 落地，`/api/v1/agents/rules/compile` 可以把规则文本转成 `ConstraintCandidate`，并强制保持 `pending_human_review`。`FeedbackAgent` 也已接入规则候选输出，override 原因不会直接修改生产约束。

## 4. 推荐解释 Agent

推荐解释 Agent 解决的是“为什么这个方案值得计划员看”的问题。工业调度不是只比一个分数。计划员需要知道推荐方案减少了多少延期、增加了多少扰动、换线是否可接受、风险是否来自数据缺失、质量门为什么给 warning。

它的任务不是美化答案，而是把不可变的方案、KPI、质量门和 source refs 翻译成计划员可判断的业务语言。

| 设计项 | 内容 |
| --- | --- |
| 触发时机 | Top-K 候选方案通过质量门后，进入人工确认前 |
| 输入 | 候选方案、KPI 对比、质量门结果、受影响订单、相似案例、source refs |
| 输出 | 推荐摘要、取舍解释、风险提示、人工检查项、引用来源 |
| 允许能力 | 解释、摘要、对比、风险翻译、不同角色视角表达 |
| 禁止事项 | 不修改 KPI，不隐藏 warning，不把低置信结果说成确定结论 |

建议输出结构：

```json
{
  "recommended_plan_id": "plan_local_repair_02",
  "planner_summary": "该方案优先保住急单交付，同时把调整范围限制在瓶颈设备附近。",
  "why_this_plan": [
    "延期风险低于等待维修方案",
    "扰动范围小于全局重排方案",
    "质量门未发现硬约束阻断"
  ],
  "tradeoffs": [
    "需要调整 5 道工序",
    "换线次数增加 1 次"
  ],
  "risks": [
    "物料齐套数据仍来自 demo/mock 数据，现场试点需替换为真实接口"
  ],
  "manual_checks": [
    "确认 M-04 16:00 后是否可用",
    "确认急单 WO-102 是否允许局部插队"
  ],
  "source_refs": ["incident:M-03", "quality_gate:plan_local_repair_02"],
  "confidence": 0.81
}
```

质量门：

- 没有 source refs 的解释不能作为正式推荐解释。
- 解释必须覆盖关键负面信息：warning、block 原因、数据缺口、执行复杂度。
- 解释不得新增系统没有计算过的 KPI。
- 多方案差距很小时，必须提示“需要计划员权衡”，而不是强行制造确定性。

评估指标：

- 解释 source ref 覆盖率。
- 解释与结构化 KPI 的一致率。
- 计划员有用性评分。
- 解释后人工确认耗时是否下降。
- 因解释误导导致的拒绝或返工次数。

当前状态：`ExplanationAgent` 和 `ExplainabilityLayer` 已存在，能基于候选方案和 `ComparisonMatrix` 生成解释。后续重点不是写更华丽的文案，而是让解释绑定更完整的 source refs、质量门证据和失败原因。

## 5. 案例沉淀 Agent

案例沉淀 Agent 解决的是“每次决策之后系统有没有变聪明”的问题。如果一次异常处理只停留在推荐和确认，产品价值会停在单次效率提升；如果能把异常特征、方案取舍、人工选择、执行结果和 override 原因沉淀下来，系统才会形成长期资产。

它的任务不是把历史案例当成真理，而是把决策过程整理成可检索、可复盘、可再验证的案例。

| 设计项 | 内容 |
| --- | --- |
| 触发时机 | 计划员确认方案、拒绝推荐、发生人工 override、执行反馈回流 |
| 输入 | Incident、影响分析、候选方案、推荐结果、确认记录、执行反馈、实际 KPI |
| 输出 | CaseRecord、案例标签、相似检索特征、执行结果、可复用程度 |
| 允许能力 | 归因摘要、标签提取、案例标题生成、相似检索特征生成 |
| 禁止事项 | 不把未验证案例发布成规则，不把失败案例隐藏，不覆盖审计记录 |

建议输出结构：

```json
{
  "case_title": "M-03 停机导致急单延期风险的局部重排",
  "incident_signature": "equipment_failure:bottleneck:M-03:rush_order_delay",
  "selected_strategy": "local_repair",
  "confirmed_plan_summary": "局部调整瓶颈设备后续 5 道工序，保住急单交付",
  "override_reason": null,
  "actual_outcome": {
    "delay_minutes_reduced": 150,
    "changeover_delta": 1,
    "execution_status": "pending_lab_validation"
  },
  "reusability": "similar_bottleneck_downtime_cases",
  "status": "validated_in_digital_twin"
}
```

质量门：

- 没有执行反馈的案例只能标记为待验证，不能作为策略成功证据。
- 被计划员拒绝的推荐也要沉淀，因为它们比成功 demo 更能暴露约束遗漏。
- 案例必须保留版本、数据来源、确认人、时间和回写状态。

[补充] 公开作品集或对外演示时，案例层还要做脱敏：客户名、工单号、设备号、产线和产能数据都应支持替换为 synthetic ID，避免把真实生产信息误当 demo 资产公开。

评估指标：

- 决策记录到案例的覆盖率。
- 相似案例命中率。
- 相似案例被引用后的采纳率。
- 失败案例占比和归因完整度。
- 案例复用后是否减少同类人工 override。

当前状态：`CaseMemoryAgent` 已在 `app/services/agent_workflow.py` 落地，`/api/v1/agents/case-memory/archive` 可以把 `DecisionRecord` 和 `ExecutionResult` 归档为 `CaseRecord`。MVP 仍以 in-memory 或基础持久化为主，下一步应补 pgvector 检索质量、执行结果回流和案例版本治理。

## 6. 偏好学习 Agent

偏好学习 Agent 解决的是“系统如何理解计划员真实取舍”的问题。同样一个异常，有的车间宁愿多换线也要保交付，有的车间宁愿晚一点也要少扰动，有的计划员会避开某些难执行组合。这些偏好不应该被模型拍脑袋学习，也不应该被一次 override 放大成规则。

它的任务是从足够多的确认、拒绝、override 和执行结果里，提出可解释的偏好画像和权重建议。

| 设计项 | 内容 |
| --- | --- |
| 触发时机 | 每次 override 后、累计足够案例后、试点阶段周期性复盘前 |
| 输入 | CaseRecord、override_history、候选方案 KPI、最终采纳方案、实际执行结果 |
| 输出 | PreferenceProfile、权重调整建议、证据摘要、置信度、replay 影响 |
| 允许能力 | 聚类、偏好归因、权重建议、异常模式发现、复盘摘要 |
| 禁止事项 | 不自动改全局求解目标，不用单个计划员偏好覆盖组织流程，不学习明显错误执行 |

建议输出结构：

```json
{
  "planner_id": "planner_01",
  "strategy_preferences": {
    "delivery_priority": 0.46,
    "schedule_stability": 0.34,
    "changeover_cost": 0.20
  },
  "evidence_summary": [
    "最近 20 次设备故障场景中，计划员 14 次选择扰动更小的方案",
    "当急单延期风险超过 2 小时时，计划员更倾向于接受局部换线"
  ],
  "recommended_use": "ranking_tiebreaker_only",
  "confidence": 0.72,
  "requires_replay_validation": true
}
```

质量门：

- 样本量不足时只能输出观察，不输出权重建议。
- 偏好只能作为推荐排序的辅助信号，不能越过硬约束、质量门和业务策略。
- 个人偏好、班组偏好和工厂流程规则要分开，不能混成一个全局模型。
- 每次偏好调整都要能通过历史 replay 说明它是否改善了采纳率和风险。

[补充] 偏好学习还需要防止“学习坏习惯”。如果历史 override 来自数据质量差、组织流程绕行或临时救火，系统应把它归为流程/数据问题，而不是沉淀成推荐偏好。

评估指标：

- 推荐 Top-N 覆盖计划员最终选择的比例。
- 偏好画像被计划员认可的比例。
- 使用偏好后 override 率是否下降。
- replay 中延期、扰动、换线风险是否恶化。
- 偏好建议被撤回或人工纠正的次数。

当前状态：`PreferenceLearningAgent` 已在 `app/services/agent_workflow.py` 落地，`/api/v1/agents/preference/learn` 可以基于案例库生成 `PreferenceProfile`、证据摘要和 `ranking_tiebreaker_only` 建议。下一步仍应把偏好学习放在离线/准实时资产层：先跑历史 replay，再进入 shadow mode，最后只作为推荐排序的辅助因子。

## 7. 五个 Agent 与确定性模块的边界

| 模块 | 是否 AI Agent | 原因 |
| --- | --- | --- |
| 异常理解 | 是 | 处理自然语言、告警噪声、字段缺失和风险提示 |
| 规则候选 | 是 | 把人工经验结构化成待审核资产 |
| 推荐解释 | 是 | 把多目标 KPI、质量门和 source refs 翻译成业务语言 |
| 案例沉淀 | 是 | 把决策链路、反馈和归因整理成可检索案例 |
| 偏好学习 | 是 | 从多次选择和 override 中学习稳定取舍 |
| 影响分析 | 否 | 必须基于排程快照、工序、资源和交期确定性计算 |
| 候选方案生成 | 否 | 必须由求解器、启发式或 OR 工具生成，不能由 LLM 编造 |
| 质量门 | 否 | 必须外部校验硬约束、风险、置信度和可追溯性 |
| 多目标评价 | 否 | 必须基于可计算 KPI 排序 |
| 生产回写 | 否 | 必须经过权限、幂等、审计和人工确认 |

这也是 ReOrch 面对金蝶、APS、MES/MOM 等主系统时的边界：ReOrch 不替代主系统，不争夺生产主数据和执行系统控制权，而是在异常发生后的理解、解释、经验资产和偏好辅助上补一层更轻的决策能力。

## 8. 当前 MVP 到下一阶段的落点

| Agent | 当前已有 | 下一步补强 |
| --- | --- | --- |
| 异常理解 Agent | `IncidentAgent`、结构化输出、低置信人工确认 | 接入真实 MES/IoT 告警样本，评估字段抽取准确率 |
| 规则候选 Agent | `RuleCandidateAgent`、`ConstraintCandidate`、`/api/v1/agents/rules/compile`、`FeedbackAgent.rule_candidates` | 审核流 UI、replay 结果、规则版本 |
| 推荐解释 Agent | `ExplanationAgent`、`ExplainabilityLayer`、质量门解释 | 更严格的 source refs、失败原因解释、计划员评分回流 |
| 案例沉淀 Agent | `CaseMemoryAgent`、`CaseRecord`、`CaseLibrary`、`/api/v1/agents/case-memory/archive` | pgvector 检索、执行反馈回流、失败案例归因 |
| 偏好学习 Agent | `PreferenceLearningAgent`、`PreferenceProfile`、`/api/v1/agents/preference/learn` | 历史样本聚合、replay 验证、shadow mode 下的排序辅助 |

因此，对外更准确的表达是：

```text
ReOrch 当前已经把 AI 应该进入的五个位置、输入输出、质量门和责任边界设计清楚，
并在 MVP 中用确定性实现和结构化模型跑通核心闭环。
它还不能宣称真实 LLM 已在客户生产链路稳定运行；
下一阶段应在合作实验室和客户 shadow mode 中验证这些 Agent 的准确率、采纳率和资产复用价值。
```
