# 失败样本库

## 目的

失败样本库用于证明 ReOrch 不是只会展示成功 demo。对高风险 AI 产品来说，知道什么时候不推荐、不写回、退回人工，比只展示一个顺利流程更重要。

## 失败类型

| 类型 | 产品动作 | 原因 |
| --- | --- | --- |
| data_blocker | 不生成重排方案 | 关键字段缺失或引用断链，方案不可追溯 |
| hard_constraint_block | 不推荐为可执行方案 | 设备能力、工序顺序、资源日历等硬约束失败 |
| warning_requires_review | 允许进入候选但不自动预选 | 方案可行但扰动、风险或置信度较高 |
| planner_reject | 记录驳回和原因 | 计划员认为执行成本、组织流程或隐性约束不匹配 |
| llm_low_confidence | 进入人工确认 | Agent 抽取或解释置信度不足 |

## 样本

| Case | 触发条件 | 系统处理 | 失败归因 | 后续动作 |
| --- | --- | --- | --- | --- |
| F-001 | 工序缺少 predecessor，无法证明顺序关系 | readiness blocker | 数据问题 | 只输出字段缺口，不进入重排 |
| F-002 | 操作绑定未知设备 `CNC-99` | readiness blocker | 主数据映射问题 | 要求客户修复资源映射 |
| F-003 | 候选方案把 QC 未放行工序推进下游 | hard_constraint_block | 质量约束失败 | 方案不进入推荐列表 |
| F-004 | global_reschedule 延期减少但移动 40% 工序 | warning_requires_review | 扰动过大 | 只能作为对照方案，不能自动预选 |
| F-005 | 物料延期但缺少 `available_at` | data_blocker | 齐套时间缺失 | 不计入 ROI，转数据治理 |
| F-006 | 计划员驳回 Top-1，选择 Top-2 | planner_reject | 现场偏好少换线 | 进入 CaseLibrary 和偏好学习样本 |
| F-007 | 自然语言异常未提设备 ID | llm_low_confidence | 信息不足 | Incident Agent 要求人工补字段 |
| F-008 | LLM 生成规则候选但 scope 不明确 | llm_low_confidence | 规则范围不足 | 保持 pending_human_review，不发布规则 |

## 项目处理原则

ReOrch 对失败样本的处理原则是：

- 系统能把失败分成数据、约束、模型、策略和组织流程问题。
- 失败样本不会被算进 ROI 成功结论。
- 所有失败样本都能反哺字段清单、质量门、规则候选、偏好学习或客户试点边界。

当前边界：

- 这些样本来自受控验证和 replay，不等同于真实生产环境中的完整失败分布。
- 驳回案例不是单纯负面指标。真实现场里，合理驳回是补充隐性约束、校准偏好和完善流程的重要输入。
