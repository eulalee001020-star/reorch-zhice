# Recovery Policy Graph

版本：2026-07-04

## 一句话定义

ReOrch 的长期护城河不是单个求解算法，而是企业级 Recovery Policy Graph：

> 它记录每一次异常的上下文、候选策略、硬约束结果、计划员选择、驳回原因和执行结果，并通过反事实 replay 与 shadow mode 持续学习“在什么情况下，哪种恢复策略对这家企业最有效”。

这意味着 ReOrch 不是帮企业算一次重排，而是在长期学习这家企业如何恢复生产秩序。

## 1. 第一性原理

生产异常恢复的本质不是“重新排一张表”，而是：

```text
在动态变化、约束不完整、资源有限、目标冲突、责任需要追溯的环境里，
快速选择一个可执行、可解释、可接受的恢复动作。
```

真正稀缺的不是通用算法，而是 5 类决策上下文：

| 上下文 | 内容 | 价值 |
| --- | --- | --- |
| 真实状态上下文 | 工单、工序、设备、物料、人员、日历、冻结区、质量状态 | 还原异常发生时企业到底处在什么状态 |
| 真实约束上下文 | 硬约束、软偏好、隐性规则、临时例外 | 决定哪些方案不可执行，哪些只是代价较高 |
| 异常传播上下文 | 受影响工序、订单、客户、后续资源和瓶颈 | 判断修复范围和扰动边界 |
| 组织偏好上下文 | 交付、稳定、成本、换线、加班、客户等级之间的取舍 | 让推荐从通用最优变成企业可接受 |
| 历史决策上下文 | 过去怎么处理、为什么采纳或驳回、执行结果如何 | 形成可复用的恢复策略资产 |

[补充] 如果只讲“我们有多个模型”，护城河很薄；如果能持续沉淀上述 5 类上下文，并把它们变成策略选择和排序能力，护城河才会变厚。

## 2. 三层策略智能

### 2.1 Problem-to-Solver Routing

ReOrch 不把所有异常都交给同一个模型，而是先识别问题结构，再选择求解路径。

| 场景 | 不应默认使用 | 更适合的路径 |
| --- | --- | --- |
| 小范围设备故障 | 全局重排 | local repair / wait-and-shift |
| 急单插入 | 静态计划规则 | insertion / priority swap / what-if |
| 缺料 | 纯设备排程 | material-aware repair |
| 质量 hold | 普通顺延 | quality-gated freeze / rework routing |
| 大范围扰动 | 简单启发式 | rolling window / CP-SAT / LNS |
| 数据缺失 | 强行求解 | readiness report / manual repair |

第一层壁垒：把业务问题路由到正确的问题结构、算子和求解策略。

### 2.2 Recovery Policy Portfolio

每次异常，ReOrch 不输出一个单点“最优解”，而是构造覆盖不同业务取舍的恢复策略组合。

典型策略：

```text
保交付方案
保稳定方案
保成本方案
保瓶颈方案
保关键客户方案
保低扰动方案
保质量安全方案
人工介入方案
```

候选策略由明确 recovery operator 生成：

```text
wait-and-shift
local repair
alternative resource reassignment
priority swap
batch split / merge
material substitution
overtime what-if
outsourcing what-if
rolling window repair
controlled global reschedule
manual escalation
```

第二层壁垒：系统化枚举企业真实会考虑的恢复动作，并显性化每个动作的代价、风险和适用边界。

### 2.3 Contextual Policy Learning

ReOrch 学习的不是“历史上哪个方案被选得多”，而是：

```text
在什么上下文下，
哪类恢复策略更可能被企业采纳，
更可能满足硬约束，
更可能降低交期风险，
更可能减少扰动，
更符合这家企业的组织偏好。
```

第三层壁垒：形成每家企业自己的 Recovery Policy Fingerprint。

它回答的问题包括：

- 这家企业遇到设备故障时更愿意局部修复还是等待。
- 关键客户和成本冲突时如何取舍。
- 冻结窗口到底多硬。
- 计划员能接受多大扰动。
- 哪些设备理论可替代但现场不愿使用。
- 哪些隐性规则在系统里没有，但反复被人工 override。

## 3. 图谱结构

Recovery Policy Graph 不是普通知识图谱，而是异常恢复决策图谱。

### 3.1 节点

| 节点 | 含义 |
| --- | --- |
| Incident | 设备故障、缺料、插单、质量 hold、产能下降 |
| Context | 订单紧急度、设备负荷、物料状态、冻结窗口、客户优先级 |
| Constraint | 设备能力、工艺路线、换线、日历、物料、质量、人员、工装 |
| Policy | 等待顺延、局部修复、替代设备、插单、加班、外协、全局重排 |
| CandidatePlan | 某个策略生成的具体候选计划 |
| Decision | 计划员采纳、微调、驳回、人工 override |
| Outcome | 交期、扰动、换线、成本、执行失败、返工、二次异常 |

### 3.2 边

| 边 | 含义 |
| --- | --- |
| `Incident -> affects -> Context` | 异常影响哪些订单、资源和工序 |
| `Context -> activates -> Constraint` | 某个上下文触发哪些约束 |
| `Constraint -> blocks / allows -> Policy` | 某个约束阻断或允许某类恢复策略 |
| `Policy -> produces -> CandidatePlan` | 某个策略生成某类候选方案 |
| `Decision -> selects / rejects -> Policy` | 企业选择或拒绝某类策略 |
| `Outcome -> validates / invalidates -> Policy` | 执行结果反向验证策略有效性 |

图谱越用越强，因为每次异常都会补充新的事实：

```text
这类异常在这个车间影响哪些工序。
这个计划员为什么拒绝全局重排。
这个客户为什么优先级更高。
这个设备为什么理论可替代但实际不建议用。
这个方案为什么硬约束可行但现场执行失败。
```

## 4. 护城河飞轮

```text
真实异常进入
-> 构建上下文指纹
-> 多策略候选生成
-> 硬约束与质量门过滤
-> 计划员选择 / 微调 / 驳回
-> 执行结果回收
-> 形成企业 Recovery Policy Fingerprint
-> 下次推荐更准确、更个性化、更可解释
```

关键不是单次推荐，而是每一个客户越用，系统越懂这个客户；每一个行业模板越多，进入下一家同类客户越快。

## 5. 策略效果矩阵

Recovery Policy Graph 最终应沉淀为 Policy Effectiveness Matrix。

行是异常上下文：

```text
设备故障 + 瓶颈设备 + 急单 + 替代设备有限
设备故障 + 非瓶颈设备 + slack 充足
缺料 + 可替代料 + 质量风险低
缺料 + 不可替代 + ETA 不确定
插单 + 高优客户 + 当前负荷高
插单 + 普通客户 + 当前负荷低
质量 hold + 可返工
质量 hold + 不可返工
```

列是恢复策略：

```text
wait-and-shift
local repair
alternative resource reassignment
priority swap
overtime
outsourcing
batch split
rolling window repair
global reschedule
manual escalation
```

单元格记录：

```text
feasible rate
planner acceptance rate
actual delay reduction
perturbation cost
setup increase
execution failure rate
confidence interval
sample count
```

示例表达：

> 在该客户过去 38 次类似异常中，瓶颈设备故障且急单 slack < 4 小时时，local repair + alternative resource 的 Top-3 覆盖人工策略比例最高；全局重排虽然降低延期，但平均扰动增加 2.6 倍，计划员采纳率低。

这类结论必须来自真实 replay / shadow / execution feedback，不能用 demo 数据外推。

## 6. 反事实回放

历史人工选择不能直接等同于最优策略。过去计划员选择等待维修且最终没有延期，可能只是因为当天 slack 充足或维修提前完成。

因此 ReOrch 需要 Counterfactual Replay：

```text
在同一个历史异常快照下，
同时模拟 wait、local repair、global reschedule、overtime 等方案，
再比较它们在相同上下文下的结果。
```

它把系统从“学习历史人工选择”升级为“评估当时本可以采取的多个行动”。

推荐对外口径：

> ReOrch 不只学习企业过去怎么做，而是在历史异常快照中重建当时可选策略空间，用 no-future-information replay 比较不同恢复策略的可行性和代价，从而形成每个企业自己的异常恢复策略矩阵。

## 7. 产品模块落地

| 模块 | 输入 | 输出 | 回答的问题 |
| --- | --- | --- | --- |
| Scenario Profiler | incident + snapshot + constraint state | context fingerprint、similarity cluster、repair scope | 这次异常属于哪类问题 |
| Solver Router | context fingerprint | local repair / rolling window / material repair / CP-SAT / heuristic / manual escalation | 该调用哪类模型和算子 |
| Policy Portfolio Generator | problem structure + constraints | 保交期、保稳定、保成本、保瓶颈、人工介入等候选方案 | 有哪些业务取舍 |
| Counterfactual Replay Engine | 历史异常快照 | 多策略对照结果 | 如果当时选其他策略会怎样 |
| Preference Learning Layer | planner choice + override reason + outcome | enterprise preference profile、policy ranking adjustment | 这家企业真正偏好什么 |
| Policy Memory | case + strategy + decision + outcome | case retrieval、template recommendation、rule candidate | 下次类似异常如何复用经验 |

## 8. 和现有系统的差异

| 对比对象 | 对方强项 | ReOrch 的差异 |
| --- | --- | --- |
| 传统 APS | 初始排程、有限产能、计划优化、全局规则配置 | 专门学习异常发生后的恢复策略、人工偏好和执行反馈 |
| 单一算法 | 某类问题上快或效果好 | 先识别问题结构，再选择 solver / operator / policy portfolio |
| 通用 LLM | 理解、总结、解释 | 不负责硬约束、最终排程、确认和回写，只做语义和经验结构化 |
| 咨询 / 实施公司 | 梳理流程和规则 | 把咨询式知识变成持续 replay、shadow 和策略学习闭环 |

ReOrch 的目标不是证明“APS 不能重排”，而是证明“异常恢复策略资产”在传统主系统之上有增量价值。

## 9. NGS 垂直验证的位置

NGS 论文和 NGS Lab demo 应放在 Recovery Policy Graph 的垂直验证层：

> NGS Lab 是 ReOrch 的高约束压力测试场。它证明 Constraint-to-Recovery Kernel 可以迁移到试剂有效期、hold-time、QC route、pool/run capacity、sequencer downtime、traceability 和 frozen-zone 共同约束的实验室异常恢复场景。

正确证据等级：

| 可以说 | 不应说 |
| --- | --- |
| NGS 是高约束垂直验证案例 | 已完成 NGS 商业部署 |
| 论文证明 schema transfer、hard gate、protected selection 的方法可行 | 已证明真实临床 TAT 或生产 ROI |
| NGS 帮助说明内核可迁移到更严格的科学实验工作流 | 已替代 LIMS / ELN / 仪器软件 |

这能增强专业深度，但不能被包装成商业牵引。

## 10. 当前实现和缺口

| 能力 | 当前状态 | 下一步 |
| --- | --- | --- |
| Reality Data Layer | 已有 P0 Reality Harness 和 sample pack | 接真实客户字段血缘和数据版本 |
| Decision Graph | 已有最小可运行实现 | 增加物料、质量、人员、工装和多车间节点 |
| Recovery Operator Portfolio | 已有设备故障路径算子 | 扩展缺料、插单、质量 hold、人员不足、外协 |
| Replay / Shadow | 已有 replay validation 和 advisory shadow capture | 增加多策略 counterfactual replay |
| Preference Profile | 已有偏好画像和 feedback agent 雏形 | 从点击/选择升级为 context-aware policy learning |
| Policy Memory | 已有案例沉淀和失败样本库 | 增加策略效果矩阵、样本量和置信区间 |

## 11. Claim Boundary

可以说：

- ReOrch 的长期护城河是企业异常恢复策略图谱。
- 当前已经具备 Constraint-to-Recovery Kernel 的最小可运行基础。
- 实验室 replay、数字孪生和 NGS 垂直验证能支撑方法可行性和产品结构验证。
- 下一阶段要通过真实客户只读 replay、shadow mode 和执行反馈沉淀 Recovery Policy Fingerprint。

不能说：

- 当前已经完成企业级策略图谱商业验证。
- 历史 replay 可以直接证明真实 ROI。
- 计划员历史选择等于最优策略。
- NGS 论文等于 NGS 实验室商业落地。
- 企业接入 ReOrch 后立即不需要其他排产系统。
