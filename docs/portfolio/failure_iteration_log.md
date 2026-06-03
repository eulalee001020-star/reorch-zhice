# 失败案例与迭代记录

## 1. 失败记录原则

工业 AI Copilot 的可信性来自失败处理，而不是来自完美演示。ReOrch 将失败分为数据问题、约束问题、策略问题、解释问题和组织流程问题，并把每类失败转化为产品迭代输入。

## 2. 失败案例 1：数据缺失时仍可能输出计划

| 项目 | 内容 |
| --- | --- |
| 失败现象 | 初版流程在异常字段不完整时，仍可能继续生成候选方案 |
| 风险 | 计划员可能误以为候选方案已经经过完整数据验证 |
| 归因 | 只检查了 incident schema，没有建立面向业务可用范围的 data readiness gate |
| 修改方案 | 增加 Data Readiness 入口、字段合同和停损规则；关键字段缺失时降级为人工检查清单 |
| 验证方式 | `data_readiness_stop_rules.md`、DataReadinessPage、mapping validation、demo validation |
| 剩余风险 | 客户现场字段命名、主键口径和历史版本仍需按 adapter contract 校验 |

## 3. 失败案例 2：Agent 解释可能过于自信

| 项目 | 内容 |
| --- | --- |
| 失败现象 | 早期解释文本强调推荐理由，但对质量门 warning、数据缺口和 solver 降级提示不够突出 |
| 风险 | 用户可能只看推荐结论，忽视扰动范围、执行复杂度或低置信原因 |
| 归因 | Explanation Agent 关注“可读性”，但解释 UI 对 risk_flags 和 fallback_reason 的呈现不够强 |
| 修改方案 | 在 Agent trace 中记录 `llm_used`、`fallback_reason`、source refs；前端候选表和推荐面板展示 quality gate 状态 |
| 验证方式 | `test_agent_workflow.py`、`llm_agent_offline_eval.md`、DecisionWorkbench 页面 |
| 剩余风险 | 真实客户场景中，风险阈值仍需基于历史异常和计划员反馈校准 |

## 4. 失败案例 3：规则候选可能被误认为硬约束

| 项目 | 内容 |
| --- | --- |
| 失败现象 | 自然语言规则转成 constraint candidate 后，容易被误解为已经生效的生产约束 |
| 风险 | 未验证规则可能与现场物料、人员、工装或质量规则冲突 |
| 归因 | 规则候选缺少审核状态、replay 状态和拒绝原因展示 |
| 修改方案 | 增加规则审核页面，区分 pending、approved、rejected、released；拒绝原因和 replay 结果进入记录 |
| 验证方式 | RuleCandidateReviewPage、agent workflow tests、failure case library |
| 剩余风险 | 客户现场硬约束发布仍需接入权限、版本和审批流程 |

## 5. 失败案例 4：NGS 特化场景需要更强 hard gate

| 项目 | 内容 |
| --- | --- |
| 失败现象 | 通用制造调度逻辑迁移到 NGS 实验室时，普通资源可用性检查不足以覆盖 hold-time、QC、index compatibility 等硬约束 |
| 风险 | 一个看似可排的计划可能违反实验室链路或审计要求 |
| 归因 | 行业对象和硬约束没有被明确建模 |
| 修改方案 | 增加 NGS data model、hard gate、protected repair portfolio、blocked candidates、NGS Lab 页面和 demo package |
| 验证方式 | `test_ngs_lab.py`、`ngs_lab_specialized_portfolio.md`、NgsLabPage |
| 剩余风险 | 当前 NGS package 是 synthetic / digital-twin-style 验证包，不等于真实 LIMS 生产验证 |

## 6. 迭代结论

这些失败说明 ReOrch 的产品重点不应是“更自动”，而应是“更可控”：任何低置信、数据缺口、质量门风险或权限缺失都应转化为降级、阻断、人工确认或审计记录。

下一阶段重点：

- 用客户只读数据验证 readiness score 和 source refs。
- 用 shadow mode 复核 Top-K 候选与计划员实际方案。
- 用真实 override 样本校准风险阈值和偏好画像。
- 将 audit package 从代理结构升级为正式导出物。
