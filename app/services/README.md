# 服务层结构

服务按决策闭环的环节分包。每个包只放一类职责，包之间通过 `app.models` 里的数据结构交互。

| 包 | 职责 | 代表模块 |
| --- | --- | --- |
| `intake` | 异常接入、事件状态机、影响分析 | `anomaly_intake_center`、`impact_analysis_engine` |
| `data_gate` | 数据健康门、来源治理、接入预检 | `data_readiness`、`schema_drift_guard`、`reality_harness` |
| `constraints` | 约束定义、校验、校准、不可行归因 | `operational_constraint_validator`、`constraint_calibration` |
| `solver` | 候选方案生成：规则、SSGS、CP-SAT、分解与混合求解 | `cp_sat_scheduler`、`hybrid_solver`、`feasibility_restoration` |
| `recommendation` | 候选方案评价、质量门、解释 | `plan_recommendation_engine`、`plan_quality_gate` |
| `agent` | 受控 Agent 工作流、模型调用、可观测性 | `agent_workflow`、`llm_agent_client` |
| `governance` | 人工确认、审批、受控回写、鉴权 | `confirmation_module`、`writeback_module` |
| `evidence` | 证据台账、案例库、规则候选复盘 | `recovery_evidence_ledger`、`case_library` |
| `validation` | 回放、影子模式、数字孪生验证 | `replay_validation`、`digital_twin_runner` |
| `storage` | 持久化、运行态存储、备份 | `persistence`、`operational_store` |
| `ngs` | NGS 实验室特化场景 | `ngs_lab` |

一次异常的处理顺序与包的顺序一致：

```text
intake -> data_gate -> constraints -> solver -> recommendation -> agent
       -> governance -> evidence
```

`validation` 和 `storage` 为上面各环节提供回放验证与存储，不在主链路上。

约定：

- 模块用绝对路径导入，例如 `from app.services.solver.cp_sat_scheduler import ...`。
- 包的 `__init__.py` 只写一行说明，不做再导出，避免循环导入。
- 需要仓库根目录时用 `app.core.paths.REPO_ROOT`，不要自己数 `parents[n]`。
