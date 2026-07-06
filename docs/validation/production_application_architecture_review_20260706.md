# ReOrch Production Application Architecture Review

版本：2026-07-06

## 0. 结论

站在从未了解过项目的顶级架构师视角，ReOrch 现在已经从“异常重排 demo”推进到“可审计的异常恢复工程底座”：

- 已能把大规模柔性作业车间数据映射成可 replay 的排程快照。
- 已能在 60 台资源、80 个工单、517 道工序、30 个异常 case 上生成多种 solver-backed 恢复方案。
- 已能保留不可行策略作为证据，解释为什么不能直接执行。
- 已能用生产就绪门控区分 `replay_ready`、`shadow_ready`、`controlled_pilot_ready` 和 `production_ready`。

但结论必须保守：

> 当前系统可以进入只读 replay、客户数据接入评估和 shadow mode 准备；不能直接宣称已经完成无人值守生产上线。要进入真实生产应用，必须通过生产就绪门控，尤其是客户数据来源确认、计划员决策、执行结果、sandbox 回写、审计、回滚、权限、安全和性能压测。

## 1. 第一性原理复盘

生产异常恢复不是“重新排一张甘特图”。它的本质是：

```text
在真实状态不完整、硬约束复杂、目标冲突、责任可追溯的生产现场，
用最小扰动快速找到一个可执行、可解释、可审批、可回滚的恢复动作。
```

由此反推，系统必须同时满足 8 个条件：

| 条件 | 第一性原理解释 | ReOrch 对应实现 |
| --- | --- | --- |
| 真实状态 | 算法只能优化它能看见的状态 | P0 Reality Harness、canonical mapping、snapshot reconstruction |
| 真实约束 | 不可执行的最优解没有价值 | Constraint Calibration、Large FJSP constraint compiler |
| 多策略空间 | 单一“最优”无法覆盖业务取舍 | policy portfolio、multi-strategy replay |
| 可行性证明 | AI 解释不能替代排程可行性 | CP-SAT FJSP backend、quality gate、frozen-zone gate |
| 人审闭环 | 工业现场需要责任边界 | human confirmation、writeback preview、approval chain |
| 反事实验证 | 历史人工选择不等于最优 | counterfactual replay、policy effect matrix |
| 执行反馈 | 排程成功必须被现场结果验证 | execution feedback ingestion、policy graph update |
| 生产治理 | 写回错误会影响现场秩序 | sandbox、idempotency、rollback、compensation、audit |

[补充] 这意味着 ReOrch 的护城河不应表述为“我们会写复杂 APS 软件”，而应表述为：

```text
把企业异常现场的状态、约束、候选策略、计划员选择、人工干预原因、
反事实 replay 和执行结果沉淀成 Recovery Policy Graph。
```

## 2. 当前可证明能力

### 2.1 大规模 FJSP replay 实测

本轮使用本地数据包：

`/Users/lishuangjiang/Downloads/reorch_large_fjsp_public_anomaly_pack_v0_1.zip`

重要边界：该包 README 表明它是 public benchmark-derived anomaly injection pack。除非客户另行提供 provenance note，否则不能把它包装为真实客户生产证据。

| 指标 | 当前实测 |
| --- | --- |
| P0 permission | `shadow_ready`，但只代表 read-only replay/shadow 数据闸门 |
| P0 readiness score | `0.90` |
| canonical mapping | 687 / 687 records valid |
| snapshot | 80 work orders、517 operations、60 resources |
| flexible operation modes | 1,836 |
| frozen operations | 119 |
| incidents attempted | 30 |
| solved incidents | 30 / 30 |
| feasible solver-backed options | 71 |
| infeasible options retained as evidence | 43 |
| recommended local repair | 11 |
| recommended controlled frozen-zone release | 11 |
| recommended controlled global reschedule | 3 |
| CP-SAT local repair sample | feasible, `OPTIMAL`, 517-operation snapshot, 0.0238 s wall time |

第一轮直接求解只解决 19 / 30 个异常；剩余 11 个被下游冻结工序阻断。系统新增 `controlled_frozen_zone_release` 后，30 / 30 个异常均至少生成一个可行方案。该策略只释放同一工单内必要的冻结工序，并把 frozen changes 写入 KPI，因此属于审批候选，不属于自动回写。

### 2.2 当前策略组合效果

| 策略 | 适用场景 | 当前工程状态 | 生产边界 |
| --- | --- | --- | --- |
| `wait_and_shift` | 维修等待、缺料等待 | solver-backed | 冻结区或交期紧张时易不可行 |
| `local_repair` | 局部设备故障、局部顺延 | solver-backed | 可能错过全局更优 |
| `alternative_machine_repair` | 有替代设备 | solver-backed | 依赖设备能力、换型、运输真实数据 |
| `partial_reassignment` | 产能下降、资源受限 | solver-backed | 可能留下下游瓶颈 |
| `priority_swap` | 插单、关键客户 | solver-backed | 必须业务审批 |
| `controlled_global_reschedule` | 局部修复失败 | solver-backed | 扰动大，必须更高等级审批 |
| `controlled_frozen_zone_release` | 冻结区导致不可行 | solver-backed | 不允许无人值守写回 |

[补充] 对投资人和客户可说：

> 系统已经能在大规模柔性作业车间快照上为多类异常生成多种可行恢复方案，并输出每种方案的扰动、资源切换、冻结区变更、求解状态和审批边界。

不可说：

> 已经证明客户 ROI、已完成生产上线、已允许自动调度写回。

## 3. 新增生产就绪门控

为防止把 replay 能力误用为生产上线能力，新增：

`POST /api/v1/planning/production-readiness/evaluate`

核心代码：

- `app/models/production_readiness.py`
- `app/services/production_readiness.py`
- `app/tests/test_production_readiness.py`

### 3.1 门控等级

| 等级 | 允许动作 | 禁止动作 |
| --- | --- | --- |
| `blocked` | data gap analysis | replay、shadow、writeback |
| `replay_ready` | read-only replay、counterfactual replay、多策略对比报告 | customer shadow、sandbox writeback、production writeback |
| `shadow_ready` | 客户只读 shadow、计划员评审、不写回 | 任何生产写回 |
| `controlled_pilot_ready` | sandbox writeback、人审受控写回 | 无人值守自动调度 |
| `production_ready` | 人审治理下的生产写回、策略学习优化 | 无人值守绕过质量门和审批 |

当前大规模 FJSP public pack 进入该门控后的结论是：

```text
decision = replay_ready
allowed = read_only_replay / counterfactual_replay / multi_strategy_tradeoff_report
blocked = customer_shadow_mode / sandbox_writeback / production_writeback / unattended_autonomous_dispatch
```

原因不是求解不行，而是证据等级不够：缺客户来源确认、计划员采纳/驳回、执行结果、sandbox 回写、安全和运维验收。

### 3.2 生产准入硬条件

完整 `production_ready` 必须同时满足：

| 模块 | 硬条件 |
| --- | --- |
| data foundation | snapshot 可重建，工单/工序/资源完整，P0 readiness >= 0.85 |
| multi-strategy recovery | 代表性异常都有至少一个可行方案或明确人工升级路径 |
| customer evidence | 真实客户数据，客户确认脱敏来源和字段含义 |
| policy learning loop | 至少 30 条计划员选择记录、10 条结构化 override 原因、30 条执行结果、3 个高置信策略矩阵 cell |
| writeback safety | sandbox dry-run、双人审批、幂等、回滚、补偿、审计全部通过 |
| AI governance | AI 不做硬约束和最终派工，质量门和人工确认强制启用 |
| performance | 1k/5k/10k 工序压测，P95 solver <= 60s，P95 gate <= 1s，并发异常 >= 3 |
| operations security | 安全评审、备份恢复演练、监控告警、SSO/RBAC、数据保留策略通过 |

[补充] 这套门控把“能做演示”和“能接生产责任”切开，是生产系统必须具备的工程防线。

## 4. 工程落地细节

### 4.1 数据接入

当前已经有两层数据接入：

1. `P0RealityHarnessService`
   - 输入 ERP/MES/APS 原始工单、工序、设备、异常记录。
   - 输出 canonical dataset、readiness score、permission level、snapshot。
   - 负责字段映射、引用完整性、时间格式、设备状态、ID crosswalk。

2. `RealDataIntegrationService`
   - 校验 ERP/MES/WMS/QMS/IoT 数据源合同。
   - 检查增量键、ID namespace、lineage fields、freshness、sample count。
   - 输出是否可进入 `ingestion_ready` / `shadow_ready`。

[补充] 进入客户现场前必须补：

- 每个字段的 source system、source table/API、updated_at、source_record_id。
- ERP 工单、MES 工序、WMS 物料、QMS hold、IoT 设备状态之间的 ID crosswalk。
- 增量同步失败后的补偿策略。
- 数据血缘导出包，供客户 IT 和质量负责人审查。

### 4.2 约束编译

当前 `LargeFjspConstraintCompiler` 已覆盖：

- alternative resource / operation modes
- operation precedence
- resource no-overlap
- material availability
- skill availability
- tooling capacity
- changeover matrix
- quality hold
- outsourcing option
- transport / AMR lag
- buffer capacity
- WIP and frozen zones

[补充] 现场落地时，约束要分成三类：

| 类型 | 例子 | 系统处理 |
| --- | --- | --- |
| 硬约束 | 工序前后关系、设备不可用、质量 hold、物料未齐套 | 不满足则不可推荐 |
| 软约束 | 换型成本、扰动最小、关键客户优先 | 进入目标函数和排序 |
| 隐性约束 | 某设备理论可用但现场不愿用、某计划员偏好稳定 | 从 override reason 和执行反馈学习 |

### 4.3 求解与重调度

当前求解路径是：

```text
incident
-> impact report
-> policy portfolio
-> CP-SAT FJSP solve
-> KPI comparison
-> recommendation ranking
-> planner review boundary
```

已有分解策略：

- incident neighborhood
- bottleneck group
- rolling window
- local repair
- controlled global reschedule
- timeout feasible fallback
- controlled frozen-zone release

[补充] 大规模客户上线前必须完成：

- 真实 1k/5k/10k 工序快照 P95 求解时延。
- 不同异常并发数量下的队列和超时策略。
- warm start 来自原排程或上一次可行解。
- infeasible 结果的可解释 blocker 输出。
- 超时仍返回 best-known-feasible 或 manual escalation。

### 4.4 AI 使用边界

AI 应放在低风险层：

- 异常描述理解。
- 字段映射建议。
- 策略路由解释。
- 规则候选生成。
- 计划员 override reason 结构化。
- 报告和审计包摘要。

AI 不应直接负责：

- 硬约束判定。
- 最终可行性证明。
- 自动派工。
- 跳过质量门。
- 跳过审批和回滚机制。

[补充] 生产使用时，每个 AI 输出必须绑定：

```text
source_refs + model_version + prompt_version + fallback_reason + human_confirmed_by
```

## 5. 当前投入生产应用的正确方式

如果“生产应用”指直接替换客户现有排产系统并自动写回，当前不应承诺。

如果“生产应用”指在真实客户环境中进入受控、人审、可审计的异常恢复辅助流程，则建议按下面 SOP 推进。

### 5.1 第 0 阶段：客户数据预接入

时间：1-2 周

目标：

- 拿到脱敏工单、工序、设备、排程快照、异常日志。
- 跑 P0 Reality Harness。
- 输出字段映射和数据缺口报告。

验收：

- blocking errors = 0。
- P0 readiness >= 0.85。
- 可重建基准 schedule snapshot。

### 5.2 第 1 阶段：历史 replay

时间：2-4 周

目标：

- 选 10-30 条历史异常。
- 对每条异常跑多策略 replay。
- 输出方案对比、不可行原因、人工复核记录。

验收：

- 代表性异常 100% 有可行方案或人工升级路径。
- 每个推荐方案都有硬约束结果、KPI、扰动边界和审批边界。

### 5.3 第 2 阶段：shadow mode

时间：4-8 周

目标：

- 系统只读并行，不写回。
- 记录计划员采纳、微调、驳回、override reason。
- 用执行结果校准策略矩阵。

验收：

- 至少 30 条计划员决策。
- 至少 30 条执行结果。
- 策略效果矩阵开始出现高置信 cell。

### 5.4 第 3 阶段：受控生产试点

时间：8-12 周

目标：

- 在客户 sandbox 完成回写 dry-run。
- 双人审批后对低风险异常做受控写回。
- 每次写回都有幂等键、回滚方案、补偿步骤和审计包。

验收：

- sandbox writeback passed。
- no duplicate writeback。
- partial failure 可补偿。
- 审计包可导出。

### 5.5 第 4 阶段：生产扩展

时间：12 周以后

目标：

- 扩大异常类型、车间范围和数据源。
- 接入 IoT/RFID/AMR/数字孪生执行反馈。
- 从 Recovery Policy Graph 反哺策略排序。

验收：

- 1k/5k/10k 客户真实快照 P95 达标。
- 高置信策略矩阵持续增长。
- 推荐排序能被计划员稳定接受并解释。

## 6. 产品演进路线

| 阶段 | 产品形态 | 关键能力 | 护城河沉淀 |
| --- | --- | --- | --- |
| P0 | Data Readiness + Replay | 数据映射、快照重建、历史异常 replay | 真实状态还原能力 |
| P1 | Shadow Recovery Copilot | 多策略候选、质量门、人审、计划员反馈 | 计划员偏好和隐性约束 |
| P2 | Controlled Writeback | sandbox、审批、幂等、回滚、审计 | 可治理生产闭环 |
| P3 | Recovery Policy Graph | 反事实 replay、策略矩阵、执行反馈 | 企业专属恢复策略资产 |
| P4 | Physical Recovery Brain | IoT/RFID/AMR/数字孪生执行状态闭环 | 连接数字计划与物理执行 |

[补充] P4 不能提前包装成已完成。它是合理路线，但当前应表述为未来扩展：ReOrch 不做机器人本体，而是作为异常恢复决策层，向 AMR、IoT、RFID 和数字孪生提供可审批的恢复指令。

## 7. 投资人与客户表达

推荐表达：

> ReOrch 已完成大规模柔性作业车间异常恢复的工程底座，能从真实排程快照中重建工单、工序、资源、替代设备和冻结区约束，并对设备故障、缺料、插单、质量异常等扰动生成多种可行恢复方案。当前已在 60 资源、80 工单、517 工序、30 异常的 benchmark-derived pack 上实现 30/30 case 至少一个可行方案。系统新增生产就绪门控，确保只有在客户数据来源、计划员反馈、执行结果、sandbox 回写、审计和安全全部达标后，才允许进入生产写回。

不推荐表达：

> 已经客户生产上线、已证明 ROI、已替代所有 APS、已支持无人值守自动调度。

## 8. 当前缺口清单

| 缺口 | 为什么重要 | 完成标准 |
| --- | --- | --- |
| 客户数据 provenance | 区分 benchmark 和真实客户证据 | 客户确认脱敏来源、字段含义、时间窗口 |
| 计划员选择样本 | Recovery Policy Graph 的核心资产 | >= 30 条 accept/adjust/reject |
| override reason | 学习隐性约束 | >= 10 条结构化原因 |
| 执行结果 | 验证方案是否真的落地 | >= 30 条 MES/IoT/QMS 结果 |
| sandbox writeback | 防止生产写回风险 | 幂等、回滚、补偿、审计通过 |
| 客户性能压测 | 证明可支撑现场规模 | 1k/5k/10k P95 记录 |
| 安全运维 | 生产系统责任边界 | SSO/RBAC、备份恢复、告警、数据保留通过 |

## 9. 最终判断

当前 ReOrch 不是“只停留在 demo”的状态，因为它已经具备：

- 真实数据接入合同和 P0 gate。
- 大规模 FJSP 约束模型。
- 多策略 solver-backed replay。
- 反事实 replay 与策略矩阵。
- 回写安全门。
- 执行反馈入口。
- 生产就绪机器门控。

但它也还不是“可以无人值守生产上线”的状态。最专业、最有利、也最经得起尽调的路线是：

```text
现在：replay_ready
下一步：客户真实只读数据 -> shadow_ready
再下一步：sandbox + 审批 + 审计 -> controlled_pilot_ready
最终：计划员反馈 + 执行结果 + 安全运维 + 性能 SLA -> production_ready
```

这条路线既能支持当前进入企业受控应用，又不会把工程证据包装成超出事实的商业结论。
