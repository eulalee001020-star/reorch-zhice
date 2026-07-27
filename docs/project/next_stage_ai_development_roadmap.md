# ReOrch 下一阶段 AI 辅助开发路线图

版本：2026-07-04

## 路线原则

下一阶段不是直接堆完整 APS，而是先证明五件事：

1. 客户真实数据能读进来。
2. 客户真实约束能被校验和编译。
3. 历史异常能被 replay 证伪。
4. shadow mode 能只读并行运行。
5. AI 输出、成本、fallback 和 guardrail 能被审计。

## 8 个开发包状态

| Package | 目标 | 当前状态 |
| --- | --- | --- |
| 1. P0 Reality Harness | 真实数据接入、字段映射、质量门、样例包 | 已完成最小可运行版 |
| 2. Constraint Calibration | 设备能力、日历、冻结、换型规则标定 | 已完成最小可运行版 |
| 3. Replay Validation | 历史异常 Top-N、质量门、相似度评估 | 已完成最小可运行版 |
| 4. Shadow Mode Capture | 只读采集计划员反馈，不写回 | 已完成最小可运行版 |
| 5. Solver Policy Layer v2 | local/freeze/rolling/what-if 策略升级 | 部分已有，仍需 v2 强化 |
| 6. Quality Gate & Evidence | DataGate、ConstraintGate、EvidenceGate、ReplayGate | 部分已有，仍需统一 gate 编排 |
| 7. Sandbox Writeback | 人工确认 dry-run、幂等、失败审计 | 已有 mock/preview 基础，仍需 sandbox adapter |
| 8. Agent Observability | 模型调用、token、latency、fallback、成本 | 已完成最小可运行版 |
| 9. Constraint-to-Recovery Kernel | Decision Graph、恢复算子、Evidence Gates | 已完成最小可运行版 |

## 当前新增的 API

| API | 用途 |
| --- | --- |
| `POST /api/v1/planning/reality-harness/assess` | 运行 P0 客户数据闸门 |
| `POST /api/v1/planning/reality-harness/sample-pack` | 运行内置 P0 样例包 |
| `POST /api/v1/planning/reality-harness/suggest-mapping` | 生成保守字段 mapping 建议 |
| `POST /api/v1/planning/constraint-calibration/compile` | 编译已标定现场约束 |
| `POST /api/v1/planning/replay-validation/evaluate` | 评估历史 replay 与 shadow 可比性 |
| `POST /api/v1/planning/shadow-mode/capture` | 记录只读 shadow mode 计划员反馈 |
| `POST /api/v1/planning/agent-observability/summarize` | 汇总 Agent trace 成本和降级情况 |
| `POST /api/v1/planning/technical-kernel/decision-graph` | 构建生产状态决策图和可修复子图 |
| `POST /api/v1/planning/technical-kernel/recovery-operators` | 按异常影响选择恢复算子组合 |
| `POST /api/v1/planning/technical-kernel/evidence-gates` | 执行 Data/Constraint/Evidence/Replay/Writeback 门控 |

## 下一步优先级

1. 用真实客户数据替换 P0 样例包。
2. 将 constraint calibration 接入真实初始排程和异常重排路径。
3. 建立 replay case loader，批量运行 10-30 条历史异常。
4. 将 shadow capture 结果写入案例库和规则候选队列。
5. 强化统一 gate：DataGate、ConstraintGate、EvidenceGate、PolicyGate、ReplayGate、WritebackGate。
6. 做 sandbox writeback adapter，不进入生产写回。
7. 增加 Agent trace 持久化、查询和前端成本看板。

## 边界

已完成的是“客户 PoC 前的可信性地基”，不是完整 APS 替代。要让企业逐步不再使用其他排产系统，还必须补齐物料齐套、人员技能、工装夹具、外协、计划版本、生产发布、回滚、SLA、真实客户生产验证和第二客户复制。
