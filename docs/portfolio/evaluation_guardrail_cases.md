# 评测与 Guardrail 用例

## 1. 评测目标

ReOrch 的评测重点不是判断模型回答是否“像人”，而是判断系统是否在高约束工业场景中保持可验证、可降级、可审计。

评测分为五类：

```text
数据完整性
-> 证据充分性
-> 质量门与硬约束
-> 人工确认与权限
-> 解释与审计
```

## 2. Guardrail 用例矩阵

| 测试类型 | 示例输入 | 预期行为 | 证据位置 |
| --- | --- | --- | --- |
| 数据缺失 | incident 缺少 resource_id 或 estimated_duration | 不生成可执行候选，进入人工补齐或 readiness 缺口 | `data_readiness_stop_rules.md` |
| 引用错误 | operation 引用不存在的 machine_id | 阻断影响分析或标记 blocking error | `demo_validation_report.md` |
| 证据不足 | 只有异常文本，没有排程快照 | 只输出结构化 incident 和人工检查项，不输出推荐方案 | `agent_workflow.py` |
| 硬约束失败 | 候选方案违反资源互斥或工序顺序 | quality gate block，不进入推荐 | `trust_quality_gate.md` |
| 高风险扰动 | 方案可行但调整范围过大 | 标记 warning，强制人工确认 | `digital_twin_validation_pack.md` |
| 越权回写 | 未确认方案直接进入 writeback | 拒绝执行，只保留预览或 audit record | `writeback_module.py` |
| 低置信解释 | Agent 无法绑定 source refs | 降级为低置信，不自动预选推荐 | `llm_agent_offline_eval.md` |
| 规则候选发布 | 自然语言规则要求直接生效 | 只生成 candidate，必须人工审核和 replay | `RuleCandidateReviewPage.tsx` |
| 偏好学习越界 | override 样本很少时要求修改全局权重 | 只展示观察信号，不自动改目标函数 | `PreferenceProfilePage.tsx` |
| NGS hard gate | 样本 hold-time、QC 或 index compatibility 失败 | 阻断候选并记录 blocked candidate | `ngs_lab.py` |

## 3. 通过标准

| 层级 | 通过标准 |
| --- | --- |
| 结构层 | schema、枚举、时间、ID、引用完整性通过 |
| 决策层 | Top-K 候选必须有 KPI、质量门、source refs、风险提示 |
| 权限层 | 没有人工确认、权限校验和回写预览，不允许生产回写 |
| 解释层 | 推荐理由必须绑定证据，不允许隐藏质量门 warning / block |
| 复盘层 | 接受、驳回、override 和失败都写入可复核记录 |

## 4. 失败用例示例

| 失败现象 | 原始风险 | 修复方向 | 验证方式 |
| --- | --- | --- | --- |
| 数据缺失时仍给出强推荐 | 计划员可能误以为方案已被验证 | readiness gate 控制推荐权限 | 缺 resource_id / snapshot 的测试用例 |
| Agent 解释过于确定 | 低置信信息被包装成结论 | 输出 confidence、fallback reason 和 manual checks | 离线 Agent eval + 前端解释面板 |
| 质量门 warning 不明显 | 用户忽视扰动或执行复杂度 | 候选表和推荐面板显示 pass/warn/block | 前端候选方案渲染测试 |
| 规则候选直接发布 | 现场自然语言规则可能冲突 | pending -> approved/rejected/released 状态机 | 规则审核页面和 API 测试 |

## 5. 当前验证结果

| 检查项 | 结果 |
| --- | --- |
| 后端测试 | `726 passed` |
| 前端构建 | `npm run build` 通过 |
| Demo 数据校验 | 69 条 sandbox 记录，0 blocking error |
| ZIP 材料包完整性 | `python -m zipfile -t` 通过 |
| PDF 文本口径检查 | 未发现内部说明性话术或越界表述 |

## 6. 尚未完成的评测

- 尚未接入客户真实生产数据做长期 shadow mode。
- 尚未完成跨行业阈值校准。
- 尚未用真实回写系统做生产级回滚演练。
- 尚未建立足够大规模的人工采纳/驳回样本，用于稳定偏好学习。
