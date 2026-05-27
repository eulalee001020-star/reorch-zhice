# 数字孪生验证包

## 目的

在客户生产现场验证完成前，ReOrch 先用内置数字孪生场景形成一组可复核的验证证据。它不替代客户现场验证，但可以先覆盖解释追溯、成本代理、历史 replay 代理、shadow mode 代理、阈值校准和审计包结构。

接口：`POST /api/v1/planning/digital-twin/sample-run`

内置场景：`reorch-poc-digital-twin-001`

## 样例结果

| 项目 | 数字孪生结果 |
| --- | --- |
| 初始调度方案 | 5 套 |
| 基准方案 | `balanced` |
| 车间工单 | 5 个 |
| 异常资源 | `CNC-02` |
| 维修估计 | 180 分钟 |
| 影响范围 | 5 个受影响工序 |
| 策略 | `wait_and_repair` |
| 策略置信度 | 0.75 |
| 重排候选 | 1 个 |
| 质量门 | pass，置信度 `medium` |
| 执行风险分 | 0.2462 |
| 风险标记 | `large_schedule_perturbation` |
| 回写预览 | 5 条 Siemens 格式指令 |
| 决策时间节省 | 82 分钟 |
| 延期减少 | 150 分钟 |
| 换线减少 | 3 次 |
| 加班减少 | 4 小时 |
| 单次异常价值估算 | 7385 元 |

## 六类证据如何补齐

| 原验证项 | 数字孪生补齐方式 | 当前口径 |
| --- | --- | --- |
| 解释层逐条 `source_refs` | `validation_evidence.source_refs` 输出 scenario、workshop、baseline snapshot、incident resource、affected work orders、affected operations、quality gate plan ids | 已有数字孪生级 source refs；客户现场需替换为真实数据对象 |
| 模型调用成本 telemetry | `validation_evidence.model_cost_proxy` 输出外部 LLM 调用数、估算 token、确定性步骤数、候选方案数、回写指令数 | MVP 当前外部 LLM 调用为 0；接入模型后沿该结构记录真实 token 和成本 |
| 历史异常 replay | `validation_evidence.replay_shadow_proxy` 用数字孪生基线和系统输出对比：90 分钟人工基线 vs 8 分钟系统决策 | 已形成 replay 代理指标；后续用合作实验室和客户历史异常替换 |
| shadow mode 数据 | 同一代理表记录节省时间、延期减少、换线减少、加班减少和价值估算 | 已能模拟 shadow 对比口径；现场 shadow mode 仍需与计划员并行运行 |
| 客户现场阈值校准 | `validation_evidence.threshold_calibration` 输出策略置信度、质量门置信度、推荐策略、执行风险分和风险标记 | 已有数字孪生阈值样本；客户阈值根据行业、订单优先级和成本口径调整 |
| 审计包导出 | `validation_evidence.audit_package_proxy` 列出输入、基准排程、异常、影响、策略、候选方案、质量门、仿真、回写预览、价值报告 | 已有审计包结构；生产试点前补正式导出格式和签名留痕 |

## 上线判断

数字孪生验证包可以支撑合作实验室试用、方案论证、只读接入前评估和客户试点前评估。它不能单独证明系统已经适合直接生产上线。

当前更准确的上线口径：

- 可以支持：实验室试用、内部演示、只读验证、历史 replay 代理验证、人工确认 dry-run。
- 有条件支持：客户 sandbox 回写演练和小范围 shadow mode。
- 暂不支持：无人值守自动调度、直接生产自动写回、未经过审计和回滚验收的现场上线。
