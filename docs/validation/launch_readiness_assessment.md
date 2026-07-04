# 上线就绪评估

## 当前状态

ReOrch 智策已经完成 MVP 开发，具备异常接入、影响分析、策略选择、候选方案生成、质量门、多目标评估、人工确认、mock 回写和案例沉淀的端到端闭环。当前阶段是在合作实验室进行初步试用和验证，重点收集真实使用反馈、数据适配问题、约束遗漏、推荐可接受度和操作流程问题。

数字孪生验证包已先行覆盖 source refs、成本代理、replay/shadow 代理、阈值样本和审计包结构，详见 [digital_twin_validation_pack.md](digital_twin_validation_pack.md)。

当前新增了三类硬证据入口：[lab_replay_acceptance_evidence.md](lab_replay_acceptance_evidence.md) 记录实验室 replay 的采纳、微调和驳回样本；[failure_case_library.md](failure_case_library.md) 记录系统不推荐、不写回和退回人工的失败样本；[llm_agent_offline_eval.md](llm_agent_offline_eval.md) 记录真实 LLM Agent 的离线评测路径。它们仍属于受控验证证据，不能替代客户生产现场验收。

新增 P0 Reality Harness 作为客户数据进入 replay / shadow 前的工程闸门，详见 [p0_reality_harness.md](p0_reality_harness.md)。它将原始 ERP/MES/APS 行数据映射成 canonical dataset，检查字段、引用、时区和 machine crosswalk，并输出 `stop`、`repair_only`、`replay_only` 或 `shadow_ready` 权限。P0 阶段仍不允许生产写回。

新增 Constraint Calibration 作为 P0 数据闸门之后的现场约束标定层，详见 [constraint_calibration.md](constraint_calibration.md)。它把人工确认的设备能力、资源日历、换型规则和冻结窗口编译成调度器可读输入；AI 规则候选必须发布为只读规则且 replay 通过，才允许进入编译流程。

新增 Replay and Shadow Validation 作为历史异常复盘与 shadow mode 前的量化证据层，详见 [replay_shadow_validation.md](replay_shadow_validation.md)。它评估 Top-N 候选方案是否通过质量门、是否覆盖历史人工接受方案、资源分配和时间偏差是否进入阈值区间。

新增 Shadow Mode Capture 和 Agent Observability 作为现场试点运行证据层，详见 [shadow_mode_capture.md](shadow_mode_capture.md) 和 [agent_observability_cost.md](agent_observability_cost.md)。前者确保 shadow case 只读记录、不产生回写；后者统计模型调用、token、latency、fallback 和成本建议。

新增 Constraint-to-Recovery Kernel 作为技术实现主线，详见 [constraint_to_recovery_kernel.md](constraint_to_recovery_kernel.md) 和 [constraint_to_recovery_technical_stack.md](../architecture/constraint_to_recovery_technical_stack.md)。它把 ScheduleSnapshot 和 Incident 转成 Decision Graph，选择恢复算子，并用 Evidence Gates 决定能否求解、推荐、解释、shadow 或写回。

## 是否足够支持上线

结论：当前足够支持受控试用和小范围验证，但不建议直接作为客户生产系统上线。

| 上线范围 | 当前判断 | 原因 |
| --- | --- | --- |
| 实验室试用 | 可以支持 | MVP 功能闭环完整，demo 数据和核心测试已通过 |
| 内部演示 / 方案评估 | 可以支持 | 可互动前端、工作流、质量门和验证材料已经具备 |
| 只读接入验证 | 可以作为下一步推进 | 需要验证客户字段映射、数据质量和接口稳定性 |
| 历史异常 replay | 可以作为下一阶段重点 | 数字孪生已给出 replay 代理指标，后续用真实历史异常复核 Top-N 覆盖率、方案可行率和响应时间 |
| shadow mode | 可以在只读接入后推进 | 数字孪生已给出 shadow 代理指标，客户现场可与人工决策并行对比 |
| 人工确认 dry-run 回写 | 有条件支持 | 需要客户 sandbox、权限、幂等和回滚演练 |
| 生产自动写回 | 暂不支持 | 数字孪生已形成审计包结构，但仍需异常回滚、SLA、权限隔离和现场验收 |
| 无人值守自动调度 | 不支持 | 工业调度责任边界要求计划员确认和质量门兜底 |

## 进入生产试点前必须满足

| 条件 | 验收口径 |
| --- | --- |
| 数据接入 | 客户工单、工序、设备、日历、排程快照、异常日志完成字段映射，blocking errors = 0 |
| 约束覆盖 | 客户核心硬约束已建模，约束标定无 blocker，确认前方案硬约束可行率 100% |
| 历史 replay | 至少覆盖 10-30 条历史异常，Top-N 命中、相似度、质量门通过率达到约定目标 |
| shadow mode | 与计划员并行运行一段时间，记录采纳、覆盖、误判、低置信、人工 override 和 advisory-only 审计包 |
| 回写安全 | 先在客户 sandbox 完成 dry-run，具备幂等、防重复提交、失败回滚和人工审批 |
| 审计追溯 | 每次推荐能导出输入、输出、版本、质量门、确认人、回写记录和执行反馈 |
| 部署运维 | 日志、监控、告警、权限、备份、恢复、SLA 和数据安全策略完成验收 |

## 后续完善方向

1. 基于合作实验室反馈修正交互流程、风险提示和计划员确认路径。
2. 将数字孪生 `source_refs` 机制迁移到客户现场数据，让每个关键结论能追溯到工单、工序、设备、KPI 或约束报告。
3. 在低风险 Agent 中启用真实 LLM 路由并跑离线评测，记录每次 Agent step 的模型、token、成本、latency、缓存命中和降级原因。
4. 扩展客户现场约束，包括物料齐套、人员技能、工装夹具、维护窗口和质量返工。
5. 将数字孪生审计包结构升级为生产试点审计包，支持 IT、质量和业务负责人复核。
