# 业务流程图

## 1. 当前业务问题流

```mermaid
flowchart LR
  A["现场异常发生"] --> B["计划员收集信息"]
  B --> C["电话 / 群消息 / Excel 试排"]
  C --> D["人工判断影响范围"]
  D --> E["手工比较等待维修、局部调整、全局重排"]
  E --> F["向生产主管解释取舍"]
  F --> G["人工下发调整"]
  G --> H["执行反馈分散记录"]
  H --> I["经验留在个人或零散文档"]
```

当前流程的问题不是单点效率低，而是决策链路不可复用：异常信息非结构化、影响范围难追溯、方案比较依赖个人经验、失败原因没有沉淀，后续类似异常仍需重新判断。

## 2. ReOrch 目标业务流

```mermaid
flowchart LR
  A["异常事件"] --> B["Incident Intake"]
  B --> C["排程快照锁定"]
  C --> D["影响分析"]
  D --> E["策略候选"]
  E --> F["Top-K 候选方案"]
  F --> G["质量门与多目标评价"]
  G --> H["推荐解释"]
  H --> I["计划员确认 / 驳回 / 微调"]
  I --> J["受控回写"]
  I --> K["案例沉淀"]
  J --> L["执行反馈"]
  L --> K
  K --> M["偏好画像 / 规则候选"]
  M --> E
```

目标流程的关键变化是把“个人经验判断”转成“结构化决策记录”：每次异常处理都保留输入、影响、候选、质量门、人工确认、回写结果和执行反馈。

## 3. 端到端泳道图

```mermaid
sequenceDiagram
  participant Planner as 计划员
  participant Copilot as ReOrch Copilot
  participant Data as ERP/MES/APS 数据层
  participant Solver as 求解器/质量门
  participant Audit as 审计与案例库

  Planner->>Copilot: 输入异常或选择演示事件
  Copilot->>Copilot: Incident Intake / 字段结构化
  Copilot->>Data: 读取排程快照、工单、资源、日历
  Data-->>Copilot: 返回 canonical data model
  Copilot->>Copilot: Data Readiness 与 source refs 校验
  Copilot->>Solver: 发送 snapshot、策略、目标权重
  Solver-->>Copilot: Top-K 候选方案与质量门结果
  Copilot->>Planner: 展示影响分析、候选比较、推荐解释
  Planner->>Copilot: 确认、驳回或 override
  Copilot->>Data: 受控回写或 dry-run preview
  Copilot->>Audit: 写入 DecisionRecord、AuditLog、CaseRecord
```

## 4. 关键决策节点

| 节点 | 输入 | 输出 | 风险控制 |
| --- | --- | --- | --- |
| 异常结构化 | 自然语言、MES/IoT 告警、人工选择 | Incident JSON | 不确定字段标记低置信，进入人工确认 |
| 快照锁定 | 当前排程、资源、工单、日历 | ScheduleSnapshot | 记录版本，避免基于变化中的计划做判断 |
| 影响分析 | Incident + Snapshot | 受影响工序、工单、资源、交期风险 | 结论绑定 source refs |
| 策略选择 | 影响范围、业务目标、约束状态 | wait/local/rolling/global 等策略候选 | 只推荐策略，不直接修改计划 |
| 候选生成 | 策略、约束、目标权重 | Top-K candidate plans | 由求解器生成，LLM 不伪造 KPI |
| 质量门 | 候选方案、硬约束、风险阈值 | pass/warn/block | block 不进入推荐 |
| 人工确认 | 候选、解释、质量门、回写预览 | accept/reject/override | 无确认不回写 |
| 案例沉淀 | 决策记录、执行反馈 | CaseRecord、规则候选、偏好信号 | 单次案例不直接成为硬规则 |

## 5. 业务角色责任

| 角色 | 主要动作 | 系统支持 |
| --- | --- | --- |
| 计划员 | 确认异常、比较候选、选择方案、解释 override | 工作台、推荐解释、人工确认、案例库 |
| 生产主管 | 判断交期风险、资源扰动、执行复杂度 | 影响分析、KPI 矩阵、风险标记 |
| 调度执行端 | 执行确认后的计划调整 | 受控回写、回写预览、幂等记录 |
| IT/集成负责人 | 维护数据映射、接口、权限和审计 | adapter contract、readiness gate、audit package |
| 质量/审计 | 复核决策依据和异常处理记录 | source refs、DecisionRecord、AuditLog |

## 6. 异常处理状态机

```mermaid
stateDiagram-v2
  [*] --> DraftIncident
  DraftIncident --> DataReady: 字段与快照校验通过
  DraftIncident --> NeedManualInput: 关键字段缺失
  NeedManualInput --> DataReady: 人工补齐
  DataReady --> Impacted
  Impacted --> CandidateGenerated
  CandidateGenerated --> QualityBlocked: 硬约束失败
  CandidateGenerated --> AwaitingConfirmation: 质量门通过或预警
  QualityBlocked --> ManualDecision
  AwaitingConfirmation --> Accepted
  AwaitingConfirmation --> Rejected
  AwaitingConfirmation --> Overridden
  Accepted --> WritebackPreview
  WritebackPreview --> WrittenBack: 权限/幂等/预览通过
  WrittenBack --> CaseRecorded
  Rejected --> CaseRecorded
  Overridden --> CaseRecorded
  ManualDecision --> CaseRecorded
  CaseRecorded --> [*]
```
