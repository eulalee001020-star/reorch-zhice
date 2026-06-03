# PRD：异常决策工作台

## 1. 背景与目标

离散制造车间在设备故障、急单插入、物料延期、质量返工等异常发生后，计划员需要快速判断影响范围、比较重排方案、向现场解释取舍，并保留确认和复盘记录。现有 ERP/MES/APS 更偏主数据、执行和计划底座，异常发生后的协同决策仍高度依赖人工经验、电话沟通和临时表格。

异常决策工作台的目标是把异常处理流程产品化：将异常结构化、固定判断快照、生成 Top-K 候选方案、展示质量门和推荐理由，并在人工确认后进入受控回写和案例沉淀。

## 2. 用户角色

| 角色 | 目标 | 权限边界 |
| --- | --- | --- |
| 计划员 | 快速理解异常影响，选择可执行方案 | 可生成候选、确认方案、查看回写预览 |
| 生产主管 | 关注交付风险、扰动范围和资源协调 | 可查看影响、风险和执行状态 |
| IT/集成负责人 | 保证数据接入、权限、幂等和审计 | 配置 adapter、查看系统日志和回写记录 |
| 质量/审计角色 | 检查决策证据和操作留痕 | 只读查看 DecisionRecord、AuditLog、CaseRecord |

## 3. 用户故事

| 编号 | 用户故事 | 验收标准 |
| --- | --- | --- |
| US-01 | 计划员希望在异常发生后看到影响订单和受影响工序 | 工作台展示 incident、affected orders、delivery risk 和 source refs |
| US-02 | 计划员希望比较多个可行方案，而不是只看一个 AI 结论 | 至少展示 Top-K 候选、KPI、质量门状态和风险提示 |
| US-03 | 生产主管希望理解推荐方案为什么可执行 | 推荐解释必须绑定 KPI、质量门、受影响资源和不确定性说明 |
| US-04 | IT 负责人希望避免未经授权的生产回写 | 未确认、无权限或质量门 block 时不允许 writeback |
| US-05 | 审计角色希望事后复盘决策链路 | 确认、驳回、override、回写和执行反馈均可追踪 |

## 4. 功能范围

### 4.1 MVP 范围

- 异常列表与当前异常详情。
- 影响分析：受影响订单、工序、资源、延期风险。
- Top-K 候选方案对比。
- 质量门状态：pass / warn / block。
- 推荐解释：业务理由、风险、source refs。
- 人工确认：接受、驳回、override reason。
- 回写预览与 mock controlled writeback。
- Agent trace、DecisionRecord、CaseRecord。

### 4.2 暂不进入 MVP

- 无人值守自动调度。
- 全厂级主计划替换。
- 直接生产写权限。
- 未经客户数据授权的真实系统接入。
- 未经 replay / shadow mode 校准的自动规则发布。

## 5. 页面流程

```text
登录
-> 决策工作台
-> 选择异常
-> 查看影响分析
-> 生成 / 查看候选方案
-> 质量门与 KPI 对比
-> 推荐解释
-> 人工确认或驳回
-> 回写预览
-> 写入审计与案例库
```

## 6. 输入输出

| 模块 | 输入 | 输出 |
| --- | --- | --- |
| Incident Intake | 异常文本、资源、时间、持续时间、优先级 | 标准 Incident JSON、缺失字段、置信度 |
| Impact Analysis | Incident、排程快照、工单、工序、设备 | 受影响对象、延期风险、阻塞原因 |
| Candidate Solver | 影响报告、约束、策略偏好 | Top-K candidate plans |
| Quality Gate | 候选方案、硬约束、风险阈值 | pass / warn / block、原因 |
| Explanation | KPI、quality gate、source refs | 推荐理由、风险说明、人工检查项 |
| Confirmation | 方案、确认人、override reason | DecisionRecord、writeback preview、case record |

## 7. 异常状态

| 状态 | 触发条件 | 产品行为 |
| --- | --- | --- |
| 数据缺失 | resource_id、snapshot、operation refs 缺失 | 不生成强推荐，展示人工补齐清单 |
| 引用错误 | operation 指向不存在的 machine_id | 阻断影响分析或标记 blocking error |
| 质量门 warn | 方案可行但扰动过大或执行复杂 | 可推荐但必须突出 warning 和人工确认 |
| 质量门 block | 硬约束失败、资源冲突、工序顺序错误 | 不进入推荐，不允许回写 |
| LLM 超时 | Agent 调用超时或失败 | 使用 deterministic fallback，记录 fallback_reason |
| 回写失败 | mock/真实接口失败或幂等冲突 | 保留预览、错误原因和 retry/rollback 指引 |

## 8. 权限规则

| 动作 | Planner | Supervisor | Auditor | Admin |
| --- | --- | --- | --- | --- |
| 查看异常与候选 | 允许 | 允许 | 允许 | 允许 |
| 生成候选方案 | 允许 | 允许 | 只读 | 允许 |
| 确认方案 | 允许 | 允许 | 不允许 | 允许 |
| 回写预览 | 允许 | 允许 | 只读 | 允许 |
| 执行生产回写 | 仅受控试点开放 | 仅受控试点开放 | 不允许 | 允许配置 |
| 查看审计 | 允许 | 允许 | 允许 | 允许 |

## 9. 埋点与上线指标

| 指标 | 定义 | 用途 |
| --- | --- | --- |
| time_to_candidate | 异常进入到首个候选方案生成的时间 | 衡量决策辅助速度 |
| top_k_feasible_coverage | Top-K 中通过质量门的方案比例 | 衡量候选方案可用性 |
| planner_adoption | 推荐方案被接受或微调接受的比例 | 衡量产品采纳 |
| override_reason_rate | 人工修改原因填写率 | 发现隐性规则和知识缺口 |
| audit_completeness | 是否记录输入、输出、确认、回写和反馈 | 衡量审计闭环 |
| fallback_rate | LLM 或工具降级比例 | 监控稳定性和成本边界 |
| blocked_candidate_rate | 被质量门阻断的候选比例 | 监控数据与约束问题 |

## 10. AI 输出约束

- LLM 不判断最终可行性，候选方案可行性由 solver 和 quality gate 决定。
- 推荐解释必须引用 KPI、质量门状态和 source refs。
- 数据缺失、低置信、工具失败时必须显式降级。
- 不允许承诺生产收益或替代人工确认。
- 规则候选只能进入审核队列，不能直接发布为硬约束。

## 11. 验收标准

| 类别 | 标准 |
| --- | --- |
| 功能 | 能完成异常选择、影响分析、候选比较、推荐解释、人工确认和案例沉淀 |
| 数据 | demo sandbox 记录通过 schema、引用和 readiness 检查 |
| 风险 | block 状态不推荐、不回写；warn 状态强制展示风险 |
| 可追踪 | 每次确认、驳回和回写都生成可复核记录 |
| 前端 | 页面无阻塞 loading、无报错栈、关键状态可被业务用户理解 |
| 工程 | 后端测试、前端 build、demo validation 通过 |

## 12. 研发对齐说明

该 PRD 面向 MVP 和受控试用，不定义真实客户生产回写的最终权限模型。进入生产试点前，需要补充客户字段映射、SSO/RBAC、接口 SLA、回滚演练、审计导出格式和运维告警。
