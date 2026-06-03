# 指标体系

## 1. 指标设计原则

ReOrch 的指标体系不以“模型看起来聪明”为目标，而以“异常决策是否更快、更稳、更可追溯”为目标。指标分为五层：模型与结构层、方案质量层、产品使用层、业务价值层、风险治理层。

## 2. North Star Metric

```text
受控异常决策闭环率 =
在目标异常范围内，完成影响分析、候选比较、质量门、人工确认和审计记录的事件数
/ 目标异常事件总数
```

该指标避免单纯追求自动化率。工业场景中，更重要的是让高风险决策进入可解释、可验证、可追责的闭环。

## 3. 指标分层

| 层级 | 指标 | 定义 | 目标意义 |
| --- | --- | --- | --- |
| 模型与结构层 | Incident schema 通过率 | 结构化异常通过 schema 的比例 | 衡量语义到结构是否稳定 |
| 模型与结构层 | source refs 覆盖率 | 核心结论绑定数据来源的比例 | 防止无依据解释 |
| 模型与结构层 | fallback rate | LLM 或 Agent 降级到规则/人工的比例 | 衡量模型边界和成本控制 |
| 方案质量层 | hard constraint pass rate | 候选方案通过硬约束质量门的比例 | 保证推荐不违反工业约束 |
| 方案质量层 | Top-K feasible coverage | Top-K 中至少一个可执行方案的比例 | 衡量求解与策略组合质量 |
| 方案质量层 | risk warning precision | warning 是否对应真实执行风险 | 校准风险阈值 |
| 产品使用层 | time-to-candidate | 异常确认到候选方案生成耗时 | 衡量决策效率 |
| 产品使用层 | planner adoption rate | 推荐方案被采纳的比例 | 衡量产品可用性 |
| 产品使用层 | override reason coverage | override 是否被结构化记录 | 衡量经验沉淀能力 |
| 业务价值层 | delay minutes reduced | 相对人工基线减少的延期分钟数 | 衡量交付价值 |
| 业务价值层 | disturbance reduced | 被调整工序、换线、资源切换减少量 | 衡量执行稳定性 |
| 业务价值层 | estimated value per incident | 单次异常估算价值 | 支撑 ROI 测算 |
| 风险治理层 | unauthorized writeback count | 未授权或未确认回写次数 | 必须为 0 |
| 风险治理层 | audit completeness | 决策记录、确认、回写、执行反馈完整度 | 衡量可追溯性 |
| 风险治理层 | block reason closure rate | 质量门阻断原因被复盘或修复的比例 | 衡量持续改进 |

## 4. 阶段性指标目标

| 阶段 | 重点指标 | 目标 |
| --- | --- | --- |
| Lab Trial | time-to-candidate、source refs 覆盖率、人工反馈完整率 | 验证工作流是否能被计划员理解和使用 |
| Read-only Pilot | data readiness score、Top-K feasible coverage、failure reason coverage | 验证真实数据是否支持 shadow mode |
| Shadow Mode | planner adoption rate、override reason coverage、delay minutes reduced | 比较系统候选与计划员实际方案 |
| Controlled Writeback | unauthorized writeback count、audit completeness、rollback readiness | 验证受控回写和审计安全 |
| Production Scope | 闭环率、业务价值、风险事件、运维稳定性 | 支撑小范围上线和扩展 |

## 5. 指标采集路径

| 数据来源 | 采集字段 | 用途 |
| --- | --- | --- |
| IncidentRecord | incident_type、resource_id、severity、confidence | 异常分类、结构化稳定性 |
| ScheduleSnapshot | snapshot_version、operations、machines、work_orders | 影响分析和 source refs |
| CandidatePlan | plan_id、strategy、kpi、quality_gate_result | 方案质量和 Top-K 覆盖 |
| DecisionRecord | accepted/rejected/override、reason、user_id、timestamp | 采纳率、override 归因、审计 |
| WritebackRecord | idempotency_key、status、diff、error_type | 回写安全和失败复盘 |
| ExecutionFeedback | actual_delay、actual_disturbance、repair_duration | 业务结果和阈值校准 |
| AgentTraceStep | llm_used、model、latency、token、fallback_reason | 成本、延迟、模型边界 |

## 6. 示例指标看板

| 指标组 | 看板呈现 | 产品判断 |
| --- | --- | --- |
| 数据就绪 | readiness score、缺失字段、阻断原因 | 是否允许进入候选方案生成 |
| 决策效率 | 平均 time-to-candidate、P95 耗时 | 是否比人工试排更快 |
| 方案质量 | hard gate pass、Top-K feasible coverage、risk score | 是否能稳定生成可执行方案 |
| 人工反馈 | adoption、reject、override、manual check | 推荐是否被计划员认可 |
| 业务价值 | 延期减少、扰动减少、估算价值 | 是否具备试点 ROI |
| 风险治理 | 未授权回写、审计完整度、block closure | 是否满足生产安全边界 |

## 7. 失败样本指标

失败样本不只记录“系统没做好”，而要分成可行动类别：

| 类别 | 典型原因 | 后续动作 |
| --- | --- | --- |
| 数据问题 | 字段缺失、ID 不一致、时间解析失败 | 补字段合同、改 adapter、降低可用范围 |
| 约束问题 | 工装、人员、物料、质量规则未覆盖 | 增加约束模型和 replay |
| 策略问题 | 推荐策略与现场偏好不一致 | 调整权重、记录 override、校准偏好画像 |
| 解释问题 | 推荐理由未覆盖关键风险 | 补 source refs 和 explanation template |
| 组织流程问题 | 需要额外审批或跨部门确认 | 增加审批节点和审计字段 |

## 8. 不能使用的虚高指标

- 不以“自动化率”作为主指标，因为工业场景高风险动作必须保留人工确认。
- 不以“LLM 调用次数”证明 AI 能力，因为高风险求解、质量门和回写不应依赖 LLM。
- 不用 sandbox 采纳率替代客户生产采纳率。
- 不把数字孪生估算价值直接等同于财务确认 ROI。
