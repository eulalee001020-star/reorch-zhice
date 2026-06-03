# 成本、延迟与部署边界

## 1. 设计原则

ReOrch 的成本与延迟控制原则是：能用规则、数据库、求解器和缓存稳定完成的任务，不交给 LLM；必须使用 LLM 的任务，只放在低风险、可降级、可审计的 Agent 步骤中。

## 2. 模块成本分层

| 模块 | 默认策略 | LLM 使用 | 成本控制 |
| --- | --- | --- | --- |
| 数据导入与 mapping | schema / adapter / deterministic validation | 不使用 | 本地校验、失败即阻断 |
| 异常结构化 | 规则降级 + 可配置 LLM Agent | 可选 | 只传异常文本和必要上下文 |
| 影响分析 | deterministic impact engine | 不使用 | 基于 snapshot 和 canonical model |
| 候选方案生成 | hybrid solver / repair portfolio | 不使用 | 求解器与启发式组合 |
| 质量门 | hard gate / risk threshold | 不使用 | pass/warn/block 明确输出 |
| 推荐解释 | 模板 + 可配置 LLM 润色 | 可选 | 必须绑定 KPI、source refs 和 quality gate |
| 反馈结构化 | 规则标签 + 可配置 LLM | 可选 | 只抽取 override reason，不自动改规则 |
| 案例沉淀 | DecisionRecord / CaseRecord | 可选 | 未审核案例不升级为硬规则 |

## 3. 延迟控制

| 环节 | 延迟风险 | 控制方式 |
| --- | --- | --- |
| 数据读取 | 客户系统接口慢或字段缺失 | 只读快照、缓存、readiness gate |
| Agent 调用 | LLM 响应慢或失败 | 最大步数、timeout、fallback reason |
| 求解器 | 大规模排程求解耗时 | 局部修复、滚动窗口、Top-K 限制 |
| 前端展示 | 多面板同时加载 | 分步骤状态展示，不阻塞已完成信息 |
| 回写 | 权限、幂等和接口失败 | 先 preview，再 controlled writeback |

## 4. Agent 执行边界

| 边界 | 当前设计 |
| --- | --- |
| 最大执行范围 | 只处理异常决策链路，不接管全厂级主计划 |
| 高风险动作 | 候选方案生成、质量门、确认和回写不用 LLM 自主决定 |
| 数据超时 | 降级到人工检查清单或只读影响说明 |
| 工具失败 | 记录 fallback reason 和 audit event |
| 低置信输出 | 不自动预选方案，不进入受控回写 |
| 人工确认 | 任何生产回写前必须存在确认记录 |

## 5. 从本地 MVP 到 SaaS 化的差距

| 能力 | 当前状态 | SaaS 化差距 |
| --- | --- | --- |
| 身份与权限 | demo 账号与基础权限 | SSO、RBAC、租户隔离、审计授权 |
| 数据接入 | mock ERP/MES/APS、adapter contract | 客户真实接口、字段血缘、版本管理 |
| 可用性 | 本地 Docker Compose 和 CI smoke | 多环境部署、监控告警、灾备与回滚 |
| 模型调用 | 可配置 LLM + deterministic fallback | 成本配额、模型路由、token 账单、SLA |
| 审计 | DecisionRecord、AuditLog、audit package proxy | 正式审计包导出、签名、留存策略 |
| 验证 | demo validation、单元测试、digital-twin-style replay | 客户历史异常 replay、shadow mode、验收报告 |

## 6. 生产边界

当前 MVP 的重点是验证决策辅助闭环，不假设已经满足真实工业生产环境的全部合规、稳定性、数据授权和运维要求。

进入客户生产范围前，至少需要完成：

- 只读接入真实工单、工序、设备、日历和排程快照。
- 历史异常 replay 与 shadow mode 对比。
- 权限、幂等、回写预览和回滚演练。
- 风险阈值、质量门和人工确认流程验收。
- 审计包导出、版本留痕和运维告警。
