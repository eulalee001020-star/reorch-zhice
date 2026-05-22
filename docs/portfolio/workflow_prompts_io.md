# AI 工作流、Prompt 与输入输出示例

本文档记录 ReOrch 智策如何把大模型能力嵌入可控工业决策流程。所有 Prompt 都服务于结构化、解释和审计，不用于绕过平台风控、安全检测或生产审批。

## 1. 工作流总览

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

核心原则：

```text
LLM/Agent 负责语义到结构、流程协同、解释和资产沉淀；
约束引擎、求解器、数字孪生、质量门和人工确认负责正确性与生产责任。
```

## 2. Agent 分工

| Agent | 输入 | 输出 | 禁止事项 |
| --- | --- | --- | --- |
| Incident Intake Agent | 自然语言异常、MES/IoT 告警 | 标准化 Incident JSON | 不直接决定最终方案 |
| Impact Analysis Agent | Incident + ScheduleSnapshot | 受影响工序、工单、资源、交期风险 | 不修改排程 |
| Constraint Compiler Agent | 现场规则文本、历史 override | constraint candidate | 不自动发布硬约束 |
| Strategy Agent | 影响分析、业务目标、资源状态 | 策略候选与理由 | 不跳过求解器 |
| Solver Tool Agent | 结构化 snapshot、策略、目标权重 | 候选方案与 KPI | 不伪造 KPI |
| Explanation Agent | Top-K 方案、KPI、质量门结果 | 面向计划员的解释 | 不隐藏失败原因 |
| Case Memory Agent | 决策记录、执行反馈 | 可检索案例 | 不把未验证案例当规则 |
| Audit Agent | 全链路事件 | 审计记录 | 不允许无审计写回 |

## 3. Prompt 模板

### 3.1 Incident Intake Prompt

用途：把自然语言异常或告警文本转成结构化事件。

```text
System:
你是制造业异常调度系统的 Incident Intake Agent。
你的任务是把用户输入转成标准 Incident JSON。
只能输出 JSON，不要给最终排程建议，不要绕过人工确认。
如果字段不确定，使用 null 并给出 needs_manual_confirmation=true。

User:
当前时间：{now}
车间上下文：{site_context}
原始异常文本：{raw_incident_text}

Output JSON schema:
{
  "incident_type": "machine_breakdown | material_delay | rush_order | quality_rework | due_date_change | unknown",
  "resource_id": "string | null",
  "work_order_id": "string | null",
  "occurred_at": "ISO-8601 | null",
  "estimated_duration_minutes": "number | null",
  "severity": "low | medium | high | critical",
  "risk_hints": ["string"],
  "needs_manual_confirmation": true
}
```

### 3.2 Constraint Compiler Prompt

用途：把计划员的自然语言规则转成待审核规则候选。

```text
System:
你是 Constraint Compiler Agent。
你只能生成 candidate，不允许把候选规则升级为 hard constraint。
每条候选必须包含来源文本、适用范围、置信度和人工审核状态。

User:
现场规则：{rule_text}
相关工序/设备/物料上下文：{context}

Output JSON schema:
{
  "candidates": [
    {
      "candidate_id": "string",
      "constraint_type": "resource_preference | forbidden_assignment | changeover | calendar | material | skill | quality",
      "scope": {"machine_ids": [], "operation_ids": [], "product_family": null},
      "source_text": "string",
      "compiled_rule": "string",
      "confidence": 0.0,
      "status": "pending_human_review",
      "risk_note": "string"
    }
  ]
}
```

### 3.3 Strategy Advisor Prompt

用途：基于影响分析和业务目标，建议候选策略。

```text
System:
你是 Strategy Agent。
你只能推荐策略路径和解释权衡，不得直接返回最终排程。
必须明确数据缺口、低置信度原因和需要计划员判断的点。

User:
异常：{incident_json}
影响分析：{impact_report}
业务目标：{goal_mode}
质量门摘要：{quality_gate_context}

Output JSON schema:
{
  "recommended_strategy": "wait_and_repair | local_repair | rolling_window_reschedule | global_reschedule",
  "alternatives": ["string"],
  "reasoning": {
    "delivery_risk": "string",
    "stability_risk": "string",
    "execution_complexity": "string",
    "data_confidence": "string"
  },
  "requires_solver": true,
  "requires_human_confirmation": true
}
```

### 3.4 Explanation Prompt

用途：把 Top-K 候选方案解释给计划员。

```text
System:
你是 Explanation Agent。
请用业务语言解释候选方案，不要夸大确定性。
必须说明交付收益、扰动代价、换线/资源切换、硬约束状态和人工确认事项。

User:
候选方案：{candidate_plans}
多目标评分：{evaluation_matrix}
质量门结果：{quality_gate_results}
相似历史案例：{similar_cases}

Output JSON schema:
{
  "recommended_plan_id": "string",
  "planner_summary": "string",
  "why_this_plan": ["string"],
  "tradeoffs": ["string"],
  "risks": ["string"],
  "manual_checks": ["string"],
  "confidence": 0.0
}
```

### 3.5 Case Memory Prompt

用途：把一次异常处理沉淀为可复用案例。

```text
System:
你是 Case Memory Agent。
请把确认后的决策、override 原因、执行反馈和 KPI 结果归档为结构化案例。
不得把单次案例直接写成全局规则。

User:
决策记录：{decision_record}
执行反馈：{execution_feedback}
最终 KPI：{actual_metrics}

Output JSON schema:
{
  "case_title": "string",
  "incident_signature": "string",
  "chosen_strategy": "string",
  "planner_override_reason": "string | null",
  "actual_outcome": "string",
  "reusable_lessons": ["string"],
  "eligible_for_rule_candidate": false
}
```

## 4. 输入输出示例

### 4.1 异常输入

```text
M-03 突然停机，维修说预计 4 小时恢复。
今天下午有两个 OEM 急单走 M-03 的 CNC 工序，最好不要影响今晚发货。
```

### 4.2 Incident Intake 输出

```json
{
  "incident_type": "machine_breakdown",
  "resource_id": "M-03",
  "work_order_id": null,
  "occurred_at": "2026-05-14T13:10:00+08:00",
  "estimated_duration_minutes": 240,
  "severity": "high",
  "risk_hints": [
    "urgent_order_delay",
    "cnc_bottleneck_capacity_loss",
    "same_day_shipping_risk"
  ],
  "needs_manual_confirmation": true
}
```

### 4.3 影响分析输出示意

```json
{
  "affected_machine": "M-03",
  "affected_operation_count": 4,
  "affected_work_order_count": 4,
  "risk_summary": {
    "urgent_orders_at_risk": 2,
    "estimated_capacity_loss_minutes": 240,
    "downstream_risk": "CMM and packaging windows may shift after CNC delay"
  }
}
```

### 4.4 候选方案输出示意

| Plan | 策略 | 交付风险 | 扰动 | 换线/切换 | 质量门 |
| --- | --- | ---: | ---: | ---: | --- |
| P1 | 等待维修 | 高 | 低 | 0 | 通过但延期风险高 |
| P2 | 局部修复 | 中 | 中 | 2 | 通过 |
| P3 | 滚动窗口重排 | 低 | 中 | 3 | 通过 |
| P4 | 全局重排 | 低 | 高 | 7 | 通过但执行复杂 |

### 4.5 推荐解释输出示意

```json
{
  "recommended_plan_id": "P3",
  "planner_summary": "建议采用滚动窗口重排：优先保护今晚发货急单，同时把调整范围限制在受影响 CNC 工序及其下游窗口。",
  "why_this_plan": [
    "比等待维修降低急单延期风险",
    "比全局重排减少跨车间扰动",
    "候选设备能力匹配，硬约束校验通过"
  ],
  "tradeoffs": [
    "需要 3 次资源切换，M-02 与 M-04 的负载会升高",
    "部分非急单完工时间后移，但未超过交付阈值"
  ],
  "risks": [
    "如果 M-03 维修超过 4 小时，需要再次触发重排",
    "M-04 需要确认夹具状态"
  ],
  "manual_checks": [
    "确认 M-04 当前夹具可用",
    "确认急单今晚发货窗口是否仍为 22:00"
  ],
  "confidence": 0.82
}
```

## 5. 评估指标

| 指标 | 含义 | 目标 |
| --- | --- | --- |
| 异常到方案时间 | 从事件进入到可解释 Top-K 方案生成 | PoC 第 95 百分位不超过 180 秒 |
| 硬约束可行率 | 推荐前通过工序顺序、资源能力、时间重叠等校验 | 100% |
| 方案采纳率 | 计划员采纳或轻微修改后采纳比例 | 首月不低于 60% |
| Top-N 包含人工方案 | 历史 replay 中候选方案覆盖人工近似选择 | 持续提升 |
| 扰动控制 | 被移动工序、换线和资源切换 | 与客户 baseline 对比下降 |
| 审计完整率 | 推荐、确认、override、回写和执行反馈是否留痕 | 100% |

## 6. 安全边界

- 生产计划写回必须经过计划员确认。
- 低置信度、多方案接近、数据缺失或硬约束失败时，系统降级为建议或阻断推荐。
- Prompt 输出不能作为事实来源，必须进入结构化校验、求解器、质量门和审计链路。
- 真实客户上线从只读接入和 shadow mode 开始，不直接开生产写权限。
