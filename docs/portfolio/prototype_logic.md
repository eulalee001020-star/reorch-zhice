# 原型逻辑

## 1. 信息架构

```text
ReOrch 工作台
├─ 决策工作台
│  ├─ 异常输入 / 演示事件
│  ├─ 影响分析
│  ├─ Top-K 候选方案
│  ├─ 推荐解释
│  ├─ 人工确认
│  └─ 回写结果与案例沉淀
├─ 规则审核
│  ├─ 规则候选
│  ├─ 人工审核
│  ├─ replay 结果
│  └─ 发布 / 拒绝记录
├─ 偏好画像
│  ├─ 采纳、驳回、override 统计
│  ├─ 排序辅助权重
│  └─ 不自动修改全局目标的边界
├─ 数据就绪
│  ├─ JSON / CSV 导入
│  ├─ mapping 校验
│  ├─ readiness score
│  └─ 停损规则
├─ Evidence Center
│  ├─ source refs
│  ├─ audit package
│  └─ failure cases
└─ NGS Lab
   ├─ batch package replay
   ├─ hard gate
   ├─ protected repair portfolio
   └─ planner confirmation / override
```

## 2. 决策工作台主流程

| 步骤 | 页面状态 | 用户动作 | 系统响应 |
| --- | --- | --- | --- |
| 1 | 未选择异常 | 输入异常文本或加载 demo incident | 生成 Incident draft，并标记字段置信度 |
| 2 | Incident 已确认 | 点击影响分析 | 锁定排程快照，计算受影响工序、工单、资源和交期风险 |
| 3 | 影响分析完成 | 点击生成候选方案 | 调用策略选择、求解器和质量门，输出 Top-K 候选 |
| 4 | 候选方案可比较 | 查看推荐理由、KPI 和 Gantt diff | 展示交付风险、扰动、换线、资源切换、质量门状态 |
| 5 | 推荐方案待确认 | 接受、驳回或 override | 记录人工选择与原因 |
| 6 | 已确认 | 查看回写预览 | 权限、幂等、版本校验通过后 dry-run 或 mock writeback |
| 7 | 回写完成 | 查看案例库 | 写入 DecisionRecord、CaseRecord 和审计信息 |

## 3. 页面级原型逻辑

### 3.1 决策工作台

核心目标：让计划员在一个页面内完成“理解异常 -> 比较方案 -> 确认决策”。

关键组件：

- Incident Card：异常类型、资源、持续时间、严重度、置信度。
- Impact Panel：受影响工序、工单、交期风险、瓶颈资源。
- Candidate Plan Table：Top-K 方案、多目标评分、质量门标签。
- Gantt Diff：原计划与候选方案的差异。
- Recommendation Panel：推荐理由、风险、人工检查项。
- Confirmation Panel：接受、驳回、override、回写预览。
- Agent Trace：展示每一步的输入、输出、fallback reason 和 source refs。

### 3.2 规则审核

核心目标：让自然语言现场规则只能先成为 candidate，不能直接生效。

关键逻辑：

- 规则候选必须包含 source text、scope、constraint type、confidence、risk note。
- 候选状态包括 pending、approved、rejected、released。
- 发布前必须经过人工审核和 replay。
- 被拒绝规则必须保留拒绝原因，进入失败样本或训练样本。

### 3.3 偏好画像

核心目标：把人工确认和 override 变成排序辅助信号，而不是自动修改硬约束。

关键逻辑：

- 统计采纳、驳回、override、低置信介入次数。
- 分析计划员在交期、扰动、换线、执行复杂度之间的偏好。
- 只影响推荐排序和解释提示，不自动改变全局目标函数。
- 样本不足时只展示观察结果，不输出稳定偏好结论。

### 3.4 数据就绪

核心目标：在真实客户数据不足时主动降级，避免用不完整数据生成不可信推荐。

关键逻辑：

- 导入客户 JSON / CSV 后执行 schema、枚举、时间、引用完整性校验。
- readiness score 决定可用范围：block、manual checklist、shadow mode、controlled writeback。
- 缺失关键字段时不进入候选方案生成。
- 每个阻断原因需要对应字段合同和客户数据请求清单。

### 3.5 Evidence Center

核心目标：把“系统为什么这样推荐”从口头解释变成可复核证据。

关键逻辑：

- source refs 绑定工单、工序、设备、排程快照和质量门结果。
- audit package 聚合输入、输出、版本、人工确认、回写和执行反馈。
- failure cases 记录 block、warn、reject、override 的原因。
- 支持从一次推荐回溯到具体数据和判断步骤。

## 4. 关键状态与异常处理

| 状态 | 进入条件 | 页面行为 | 降级策略 |
| --- | --- | --- | --- |
| loading | 请求处理中 | 展示步骤级 loading，不阻塞其他已完成信息 | 超时后提示 retry 或 fallback |
| low_confidence | incident 或解释置信度低 | 不自动预选方案，突出人工确认项 | 转为人工检查清单 |
| data_not_ready | 关键字段缺失或引用错误 | 阻断求解和回写 | 显示 readiness 缺口 |
| quality_warn | 候选可行但风险高 | 可查看但需确认风险 | 强制人工确认 |
| quality_block | 硬约束失败 | 不进入推荐 | 进入失败样本库 |
| writeback_preview | 回写前校验通过 | 展示变更 diff 和幂等 key | 未确认不提交 |
| writeback_failed | mock 或真实回写失败 | 展示错误类型和回滚建议 | 保留审计与重试入口 |

## 5. 原型验证重点

| 验证问题 | 判断标准 |
| --- | --- |
| 计划员是否能快速看懂异常影响 | 影响分析能在业务语言中解释受影响订单、资源和交期 |
| 推荐是否可信 | 每个推荐方案都有 KPI、质量门、source refs 和人工检查项 |
| 是否避免越权 | 没有人工确认、权限校验和回写预览时不出现生产回写 |
| 失败是否可学习 | 驳回、block、override 能沉淀为失败样本、规则候选或偏好信号 |
| 是否适合客户现场试点 | 数据就绪、只读接入、shadow mode、审计包和回滚预案都有入口 |
