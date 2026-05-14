# 实施计划：ReOrch 智策 — 异常重决策编排系统

## 概述

基于五层架构（AI 编排层、求解策略控制层、优化求解层、人机协同层、企业资产层）逐层实现，每层完成后进行检查点验证。后端使用 Python 3.11+ / FastAPI，前端使用 React 18 + TypeScript 5 + Zustand + Ant Design 5。求解引擎使用 Google OR-Tools CP-SAT。

## Tasks

- [x] 1. 项目脚手架与共享基础设施
  - [x] 1.1 初始化后端项目结构与依赖
    - 创建 Python 项目根目录，配置 `pyproject.toml`（FastAPI, Pydantic, SQLAlchemy, asyncpg, redis, confluent-kafka, ortools, pgvector, opentelemetry-sdk）
    - 创建目录结构：`app/models/`, `app/services/`, `app/api/`, `app/adapters/`, `app/core/`, `app/tests/`
    - 配置 `app/core/config.py`（数据库连接、Redis、Kafka、环境变量）
    - _Requirements: 15, 16, 18_

  - [x] 1.2 创建数据库 Schema 与迁移脚本
    - 使用 Alembic 配置数据库迁移
    - 创建核心表：`incidents`, `schedule_snapshots`, `impact_reports`, `candidate_plans`, `decision_records`, `execution_results`, `case_records`, `case_templates`, `preference_profiles`, `audit_logs`, `solver_policy_versions`
    - 启用 pgvector 扩展，为 `case_records` 添加 `embedding_vector` 列
    - 定义 Incident 状态机约束（pending_analysis → analyzing → pending_confirmation → confirmed → executing → closed）
    - 创建版本历史表用于关键实体审计追溯
    - _Requirements: 17.1, 17.2, 17.3, 17.5, 9.1_

  - [x] 1.3 配置 Kafka 主题与消息基础设施
    - 创建 Kafka 主题：`incidents.created`, `impact.completed`, `strategy.selected`, `plans.generated`, `plans.confirmed`, `writeback.status`
    - 实现 `app/core/kafka_producer.py` 和 `app/core/kafka_consumer.py` 基础类
    - _Requirements: 1.8, 18.2_

  - [x] 1.4 配置 Redis 缓存与 API 网关基础
    - 实现 `app/core/redis_client.py`（连接池、缓存读写）
    - 配置 FastAPI 应用入口 `app/main.py`（CORS、中间件、路由注册）
    - 实现 RBAC 中间件（Planner / Shop_Floor_Executor / Management / IT_Admin 四种角色）
    - 实现 API Key 认证与速率限制中间件
    - _Requirements: 16.2, 16.5, 18.7_

  - [x] 1.4A 配置后台任务执行基础设施
    - 选型并集成后台任务/调度框架（APScheduler / Arq / Celery）
    - 支持以下任务类型：Incident 15 分钟未确认提醒、MES 回写失败重试、执行进度定时拉取（每 5 分钟）、死信队列补偿任务
    - 提供任务注册、重试策略、失败告警与可观测性埋点
    - _Requirements: 7.8, 8.5, 8.6, 18.5_

  - [x]* 1.5 编写基础设施层单元测试
    - 测试数据库连接与迁移
    - 测试 Kafka 生产/消费
    - 测试 Redis 缓存读写
    - 测试 RBAC 权限校验
    - _Requirements: 16.2, 18.7_

- [x] 2. 核心数据模型与枚举定义
  - [x] 2.1 实现共享枚举与基础数据模型
    - 创建 `app/models/enums.py`：IncidentSeverity, IncidentType, IncidentStatus, DeliveryRiskLevel, StrategyType, RepairMode, RuleCategory, NeighborhoodType, ConfirmAction, WritebackStatus, GoalMode, RuleApplicableStage, ReportSource
    - 创建 `app/models/base.py`：基础 Pydantic BaseModel 配置
    - _Requirements: 1.2, 2.5, 3.2_

  - [x] 2.2 实现 Incident 与 ScheduleSnapshot 数据模型
    - 创建 `app/models/incident.py`：IncidentCreateRequest, Incident（含全局唯一 incident_id、deduplicated_from 列表）
    - 创建 `app/models/schedule.py`：ScheduleSnapshot, ScheduleDetail（含 WorkOrder, Operation, Resource 嵌套结构）, GanttDiffPayload
    - 实现 JSON 序列化/反序列化与往返一致性校验
    - _Requirements: 1.2, 1.7, 2.2, 21.1, 21.2, 21.3, 27.5_

  - [x] 2.3 实现影响报告与策略相关数据模型
    - 创建 `app/models/impact.py`：AffectedOperation, AffectedWorkOrder, ImpactReport（含 analysis_reference_time = snapshot.captured_at）
    - 创建 `app/models/strategy.py`：StrategyRecommendation, RuleSelectionResult, NeighborhoodConfig, RepairPolicyConfig, SolverChainConfig
    - _Requirements: 2.6, 3.7, 23.4, 24.4, 25.2_

  - [x] 2.4 实现候选方案与评估相关数据模型
    - 创建 `app/models/solver.py`：SolverChain, SolverMetadata, ConstraintViolation, ConstraintValidationReport, CandidatePlan
    - 创建 `app/models/evaluation.py`：KPIVector, ComparisonMatrixRow, ComparisonMatrix（含 normalization_method, score_unit_descriptions）
    - 创建 `app/models/recommendation.py`：PlanSelectionInput, PlanSelectionOutput（含 alternative_plan_ids[], comparison_matrix, gantt_diff_payload, audit_metadata）
    - 创建 `app/models/explanation.py`：RecommendationExplanation, SolverChainExplanation
    - _Requirements: 4.10, 4.16, 5.1, 5.5, 5.7, 28.1, 28.2, 29.9, 30.1, 30.2, 30.3, 30.4, 30.5, 30.12, 30.13_

  - [x] 2.5 实现决策记录与案例库数据模型
    - 创建 `app/models/decision.py`：ConfirmRequest, ConfirmResponse（含 derived_from_plan_id）, DecisionRecord（含策略模块版本号、plan_selection_input/output 版本）
    - 创建 `app/models/case.py`：CaseRecord（含 embedding_vector）, CaseTemplate, PreferenceProfile
    - 创建 `app/models/execution.py`：ExecutionResult, WritebackStatus
    - _Requirements: 7.5, 7.6, 9.1, 9.5, 26.2_

  - [x] 2.6 编写数据模型序列化往返一致性测试
    - 测试 Incident, CandidatePlan, DecisionRecord, CaseTemplate, PlanSelectionInput, PlanSelectionOutput, ScheduleDetail, SolverChain 的 JSON 序列化→反序列化往返一致性
    - 测试反序列化非法 JSON 时返回描述性错误
    - _Requirements: 21.3, 21.4, 21.5, 30.9_

  - [x]* 2.7 编写 manual_weights 校验测试
    - 测试取值范围校验、总和约束校验、默认值回退机制
    - 测试非法输入时返回结构化错误并保持上一有效配置
    - _Requirements: 30.11_

- [x] 3. 检查点 — 基础设施与数据模型验证
  - 确保所有测试通过，数据库迁移可执行，Kafka 主题可创建，数据模型序列化正确。如有问题请向用户确认。

- [x] 4. Layer 1 — AI 编排层服务实现
  - [x] 4.1 实现 Anomaly_Intake_Center 服务
    - 创建 `app/services/anomaly_intake_center.py`
    - 实现 `receive_event()`：接收异常事件，校验必要字段（incident_type, resource_id, occurred_at），缺失时拒绝并返回缺失字段列表
    - 实现 `IntakeSeverityClassifier.classify()`：基于资源关键程度的四级分级（P1 瓶颈/高风险 → P2 关键+≥3工单 → P3 一般+1-2工单 → P4 非关键+冗余）
    - 实现 `deduplicate()`：10 分钟窗口内同一资源去重合并，保留主事件并关联原始事件 ID
    - 实现 `publish_to_stream()`：发布 Incident 到 Kafka `incidents.created` 主题
    - 校验上报来源合法性，非法来源拒绝并记录安全审计日志
    - 生成全局唯一 incident_id
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 4.2 实现 Anomaly_Intake_Center API 端点
    - 创建 `app/api/incidents.py`
    - POST `/api/v1/incidents` — 接收异常事件（OpenAPI 3.0 规范）
    - GET `/api/v1/incidents` — 查询异常列表（支持筛选：类型、严重等级、状态、时间范围）
    - GET `/api/v1/incidents/{incident_id}` — 查询异常详情
    - _Requirements: 1.1, 10.5, 18.1_

  - [x]* 4.3 编写 Anomaly_Intake_Center 单元测试
    - 测试字段校验（缺失字段拒绝、非法来源拒绝）
    - 测试 Intake Severity 分级逻辑（四级分级规则覆盖）
    - 测试去重合并逻辑（10 分钟窗口、同一资源）
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 4.4 实现 Impact_Analysis_Engine 服务
    - 创建 `app/services/impact_analysis_engine.py`
    - 实现 `analyze()`：获取 ScheduleSnapshot，设置 `analysis_reference_time = snapshot.captured_at`
    - 实现直接影响识别：识别所有依赖故障设备的 Operation 及其 WorkOrder
    - 实现 `_propagate_downstream()`：沿工艺路线向下游传播，识别间接受影响工序
    - 实现 `_calculate_delivery_risk()`：基于 analysis_reference_time 计算每个 WorkOrder 的 Delivery_Risk_Level（Safe/Warning/Breach）
    - 实现 `_maybe_upgrade_severity()`：若发现 Breach 风险，升级 Incident severity（仅升级不降级）
    - 输出结构化 ImpactReport（含受影响工单/工序/资源列表、交期风险分布、预估总延迟）
    - ScheduleSnapshot 不可用时标记降级模式
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x]* 4.5 编写 Impact_Analysis_Engine 单元测试
    - 测试直接影响识别与下游传播
    - 测试 Delivery_Risk_Level 计算（基于 analysis_reference_time）
    - 测试 severity 升级逻辑（仅升级不降级）
    - 测试降级模式标记
    - _Requirements: 2.3, 2.4, 2.5, 2.7_

  - [x] 4.6 实现 Strategy_Selector 服务
    - 创建 `app/services/strategy_selector.py`
    - 实现 `select_strategy()`：基于影响报告、相似案例、偏好画像选择三类策略
    - 等待修复条件：设备预计恢复时间 < 受影响工序总缓冲时间
    - 局部修复条件：受影响工单 ≤ 总在制工单 20% 且无 Breach 风险
    - 全局重排条件：受影响工单 > 20% 或存在 Breach 风险
    - 相似度 > 0.8 的历史案例作为参考因素
    - 输出结构化理由（策略类型、关键决策因子、置信度）
    - 置信度 < 0.5 时同时输出排名前两位策略
    - 仅负责高层策略选择，不决定具体规则/邻域/修复强度
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

  - [x]* 4.7 编写 Strategy_Selector 单元测试
    - 测试三类策略选择条件覆盖
    - 测试历史案例参考逻辑
    - 测试低置信度时输出备选策略
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.8_

  - [x] 4.8 实现 Impact_Analysis 与 Strategy_Selector API 端点
    - 创建 `app/api/analysis.py`
    - GET `/api/v1/incidents/{incident_id}/impact-report` — 查询影响报告
    - GET `/api/v1/incidents/{incident_id}/strategy` — 查询策略推荐
    - POST `/api/v1/schedule-snapshots` — 导入排程快照（APS 数据导入）
    - _Requirements: 2.6, 3.7, 18.4_

- [x] 5. 检查点 — Layer 1 AI 编排层验证
  - 确保异常接入、影响分析、策略选择全链路可运行。确保所有测试通过，如有问题请向用户确认。

- [x] 6. Layer 2 — 求解策略控制层服务实现
  - [x] 6.1 实现 Rule_Selector 服务
    - 创建 `app/services/rule_selector.py`
    - 实现 `select_rules()`：接收 Incident 特征、影响报告、高层策略、偏好画像、历史案例
    - 支持五类规则：交期优先、最短加工时间、最小松弛时间、瓶颈资源优先、关键工单优先
    - 输出结构化结果（规则名称、类别、适用阶段、置信度、推荐原因）
    - 相似度 > 0.8 的历史案例中成功规则作为参考
    - 置信度 < 0.5 时输出排名前两位规则
    - 支持通过配置限制规则在指定车间/异常类型/策略模式下生效
    - 实现为独立模块，提供明确输入输出接口，支持单独版本管理
    - _Requirements: 22.1, 22.3, 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.8, 23.9, 23.10_

  - [x] 6.2 实现 Neighborhood_Selector 服务
    - 创建 `app/services/neighborhood_selector.py`
    - 实现 `select_neighborhood()`：接收当前解、受影响工序、停滞次数、剩余预算、策略、扰动约束
    - 支持六类邻域：关键路径、瓶颈设备、延迟工单、同设备交换、工序插入、设备重分配
    - Local-Repair 时优先局部邻域，禁止默认扩展到全局
    - 实现"不变性保护"：未受影响工序默认不进入搜索范围
    - 连续无改进时支持切换更大范围邻域
    - 接近时间上限时优先选择低计算开销邻域
    - 实现为独立模块，支持规则驱动和学习驱动两种可替换实现
    - _Requirements: 22.1, 22.3, 24.1, 24.2, 24.3, 24.4, 24.5, 24.6, 24.7, 24.9, 24.10_

  - [x] 6.3 实现 Repair_Policy_Advisor 服务
    - 创建 `app/services/repair_policy_advisor.py`
    - 实现 `advise()`：接收高层策略、影响报告、异常严重度
    - 输出 RepairPolicyConfig：修复模式、冻结范围、允许扰动范围、搜索时间预算、候选解数量目标、回退条件
    - Wait-and-Repair → 保守修复 + 冻结所有未受影响工序
    - Local-Repair → 平衡修复 + 限制在受影响工序及直接下游
    - Global-Reschedule → 激进修复 + 允许更大范围 + 提升预算
    - 支持按车间/异常类型/目标模式配置默认修复策略模板
    - 实现为独立模块，支持单独版本管理与替换
    - _Requirements: 22.1, 22.3, 25.1, 25.2, 25.3, 25.4, 25.5, 25.6, 25.7, 25.8, 25.10_

  - [x] 6.4 实现 Solver_Policy_Layer 总控服务
    - 创建 `app/services/solver_policy_orchestrator.py`
    - 实现 `build_solver_policy()`：接收 Incident、ImpactReport、StrategyType、PreferenceProfile、CaseMatch[]
    - 调用 Rule_Selector、Repair_Policy_Advisor、加载 Solver_Portfolio，输出统一 SolverPolicyBundle；对于 Neighborhood_Selector，Solver_Policy_Orchestrator SHALL 提供运行时调用接口，使 Hybrid_Solver 能在迭代过程中动态请求邻域配置
    - 确保 Hybrid_Solver 只消费一个统一策略控制对象，而不是分别依赖多个选择器
    - 记录 Layer 2 统一版本与调用链路
    - _Requirements: 22.2, 22.9, 22.10, 4.11, 4.12, 4.13_

  - [x] 6.5 实现 Solver_Portfolio 服务
    - 创建 `app/services/solver_portfolio.py`
    - 实现 `get_chain_config()`：根据策略类型返回主求解器、备选求解器、兜底规则、降级触发条件
    - 支持版本化管理和配置变更审计日志
    - _Requirements: 22.9, 22.10, 4.14, 4.15_

  - [x]* 6.6 编写 Solver_Policy_Layer 单元测试
    - 测试 SolverPolicyOrchestrator 统一输出 SolverPolicyBundle
    - 测试 Rule_Selector 五类规则选择逻辑
    - 测试 Neighborhood_Selector 六类邻域选择与不变性保护
    - 测试 Repair_Policy_Advisor 三种策略对应的修复配置
    - 测试 Solver_Portfolio 降级切换逻辑
    - _Requirements: 23.2, 24.2, 24.5, 24.10, 25.4, 25.5, 25.6_

  - [x] 6.7 实现策略模块版本治理基础
    - 创建 `app/services/module_version_registry.py`
    - 为 Rule_Selector、Neighborhood_Selector、Repair_Policy_Advisor 维护独立版本号
    - 记录每次求解调用的策略模块名称、版本号、关键参数与调用结果
    - 支持通过配置指定不同场景下使用的模块实现版本
    - 模块调用失败时自动切换到预定义兜底规则版本并记录降级日志
    - _Requirements: 22.4, 22.5, 22.6, 22.7, 26.1, 26.2_

- [x] 7. Layer 3 — 优化求解层服务实现
  - [x] 7.1 实现 Hybrid_Solver 核心求解引擎
    - 创建 `app/services/hybrid_solver.py`
    - 实现 `solve()`：调用 Solver_Policy_Layer 获取统一求解控制配置（SolverPolicyBundle）→ 执行启发式初解生成 → LNS 优化 → 约束校验 → 输出 Top-3 CandidatePlan
    - Hybrid_Solver 在 LNS / 局部搜索迭代过程中 SHALL 通过 Solver_Policy_Layer 的运行时接口动态获取邻域配置，而非仅在求解开始时读取一次固定邻域设置
    - 使用 Google OR-Tools CP-SAT 作为约束求解器
    - 等待修复策略：仅调整受影响工序开始时间
    - 局部修复策略：仅重排受影响工序及直接下游
    - 全局重排策略：对整个车间排程重新优化
    - 60 秒超时控制，超时输出已有可行方案并标注"求解超时"
    - 无可行方案时返回不可行报告（列出无法满足的约束）
    - 支持 Solver_Portfolio 降级切换（主求解器失败 → 备选 → 兜底规则）
    - 为每个 CandidatePlan 记录完整 SolverChain 和 SolverMetadata
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13, 4.14, 4.15, 4.16_

  - [x] 7.2 实现 Constraint_Validator 约束校验模块
    - 创建 `app/services/constraint_validator.py`
    - 实现 `validate_constraints()`：设备能力约束、工艺顺序约束、资源互斥约束、物料可用性约束
    - 实现局部修复不变性校验：未受影响工序保持与 ScheduleSnapshot 一致
    - 实现 `validate_microadjustment()`：对 Planner 微调后的方案重新执行全部约束校验
    - 输出 ConstraintValidationReport（每条约束的校验状态与违反详情）
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7_

  - [x] 7.3 编写约束校验属性测试
    - 测试设备能力约束：工序所需能力 ⊆ 分配设备能力集合
    - 测试工艺顺序约束：前序完成时间 ≤ 后序开始时间
    - 测试资源互斥约束：同一设备同一时间段无工序重叠
    - 测试局部修复不变性：未受影响工序与 ScheduleSnapshot 一致
    - _Requirements: 20.1, 20.2, 20.3, 20.5_

  - [x] 7.4 实现 Evaluation_Center 多目标评估服务
    - 创建 `app/services/evaluation_center.py`
    - 实现 `evaluate()`：对候选方案计算六维评分（交期影响、SPI、资源利用率变化、换型次数变化、关键工单 OTD、归一化综合评分）
    - 基于"平衡优先"默认 GoalMode 进行综合评分与排序
    - 为每个维度提供与 ScheduleSnapshot 的对比差值
    - 综合评分差值 < 5% 标记为"评分接近"
    - 数据不可用维度标注"数据缺失"并排除参与排序
    - 输出 ComparisonMatrix（含归一化方法、评分单位说明）
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 7.4A 实现 PlanSelectionInput 组装器
    - 创建 `app/services/plan_selection_input_builder.py`
    - 将 EvaluationOutput、CandidatePlan[]、GoalMode、PreferenceProfile、CaseMatch[]、manual_weights 统一组装为 PlanSelectionInput
    - 保证 recommendation service 不直接拼装碎片字段
    - _Requirements: 30.1, 30.2, 30.3, 30.10_

  - [x] 7.5 实现 Plan_Recommendation_Engine 方案推荐服务
    - 创建 `app/services/plan_recommendation_engine.py`
    - 实现 `recommend()`：接收 PlanSelectionInput，5 秒内输出 PlanSelectionOutput
    - 推荐前筛选：剔除不满足硬约束/执行约束/关键业务门槛的方案
    - 推荐排序：输出 1 个推荐方案 + 至少 1 个备选方案
    - 区分"综合评分第一"和"最终 AI 推荐"
    - 计算 Recommendation_Confidence（0-1）
    - 置信度 ≥ 阈值且无高风险告警时执行 Auto_Preselection
    - 置信度 < 0.5 时不自动预选，输出前两名供人工选择
    - 输出结构化推荐理由（推荐方案 ID、核心原因、相对优势、主要风险、与备选差异）
    - 将 GoalMode、权重参数、案例引用、偏好摘要写入 DecisionRecord
    - 支持按车间/异常类型/目标模式配置置信度阈值和 Auto_Preselection 阈值
    - _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5, 29.6, 29.7, 29.8, 29.9, 29.10, 29.11, 29.12_

  - [x] 7.6 实现 Explainability_Layer 可解释性服务
    - 创建 `app/services/explainability_layer.py`
    - 实现 `explain_recommendation()`：生成 RecommendationExplanation（核心原因≤3条、关键优势、主要风险、与备选对比）
    - 实现 `explain_solver_chain()`：生成 SolverChainExplanation（算法类别、适用场景、链路原因、阶段化说明）
    - 使用业务术语（工单号、设备名、交期日期）
    - 历史案例被引用时在理由中引用案例 ID 和结果
    - 为每个候选方案生成简要摘要（≤200 字）
    - 输出结构化数据对象，支持前端自然语言渲染
    - 区分"方案生成链路"和"方案排序链路"
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 28.1, 28.2, 28.3, 28.7, 28.8, 28.9_

  - [x] 7.7 实现 Layer 3 API 端点
    - 创建 `app/api/solver.py`
    - POST `/api/v1/incidents/{incident_id}/solve` — 触发求解
    - GET `/api/v1/incidents/{incident_id}/candidate-plans` — 查询候选方案列表
    - GET `/api/v1/candidate-plans/{plan_id}` — 查询方案详情（含 ScheduleDetail, SolverChain）
    - GET `/api/v1/candidate-plans/{plan_id}/gantt` — 查询方案甘特图数据
    - POST `/api/v1/incidents/{incident_id}/recommend` — 触发推荐（支持 GoalMode 和 manual_weights 参数）
    - GET `/api/v1/incidents/{incident_id}/recommendation` — 查询 PlanSelectionOutput
    - _Requirements: 27.1, 27.5, 29.1, 30.6, 30.8_

  - [x] 7.8 编写 Evaluation_Center 与 Plan_Recommendation_Engine 单元测试
    - 测试六维评分计算与归一化
    - 测试"评分接近"标记逻辑（差值 < 5%）
    - 测试推荐排序与 Auto_Preselection 逻辑
    - 测试低置信度时不自动预选
    - _Requirements: 5.1, 5.4, 29.7, 29.8_

- [x] 8. 检查点 — Layer 2 + Layer 3 求解链路验证
  - 确保策略控制层→求解引擎→评估→推荐→解释全链路可运行。确保所有测试通过，如有问题请向用户确认。

- [x] 9. Layer 4 — 人机协同层服务实现
  - [x] 9.1 实现 Confirmation_Module 人工确认服务
    - 创建 `app/services/confirmation_module.py`
    - 实现 `confirm()`：支持三种操作（确认采纳、微调后采纳、否决并重选）
    - 微调时创建新方案版本（derived_from_plan_id 链接原始方案），调用 Constraint_Validator 重新校验
    - 硬约束违反时阻止确认并提示具体违反条件
    - 否决时记录 Override（原因必填、原推荐方案 ID、实际选择方案 ID、时间）
    - 生成完整 DecisionRecord（含所有候选方案 ID、策略模块版本号、PlanSelectionInput/Output 版本）
    - 实现 RBAC：Planner 确认/微调/否决，Shop_Floor_Executor 仅查看，Management 审批 P1
    - 实现 `check_timeout()`：15 分钟未确认发送超时提醒
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [x] 9.2 实现 Writeback_Module 执行回写服务
    - 创建 `app/services/writeback_module.py`
    - 实现 `writeback_to_mes()`：将确认方案排程变更指令回写 MES，回写前转换为目标 MES 数据格式
    - 单条指令失败时标记失败、继续执行其余指令、汇总失败项
    - 记录回写状态（成功/部分成功/失败）
    - 实现 `track_execution()`：每 5 分钟从 MES 获取执行进度，偏差 > 10% 生成告警
    - 所有受影响工单执行完毕时生成 ExecutionResult（实际 vs 计划完成时间、OTD、资源利用率）
    - 将 ExecutionResult 关联回 DecisionRecord 形成闭环
    - 将最终甘特图版本号与排程明细版本号关联到 DecisionRecord
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 27.10_

  - [x] 9.3 实现 Confirmation 与 Writeback API 端点
    - 创建 `app/api/confirmation.py`
    - POST `/api/v1/incidents/{incident_id}/confirm` — 确认/微调/否决方案
    - GET `/api/v1/incidents/{incident_id}/decision-record` — 查询决策记录
    - GET `/api/v1/incidents/{incident_id}/writeback-status` — 查询回写状态
    - GET `/api/v1/incidents/{incident_id}/execution-result` — 查询执行结果
    - _Requirements: 7.6, 8.3, 8.7_

  - [x] 9.4 编写 Confirmation_Module 单元测试
    - 测试三种确认操作流程
    - 测试微调后约束校验（通过/违反）
    - 测试 Override 记录完整性
    - 测试 RBAC 权限控制
    - 测试 15 分钟超时提醒
    - _Requirements: 7.1, 7.3, 7.4, 7.5, 7.7, 7.8_

  - [x] 9.5 实现方案导出服务
    - 创建 `app/services/export_service.py`
    - 实现导出 PDF（含甘特图快照、推荐理由、关键 KPI）
    - 实现导出 Excel（含完整 ScheduleDetail）
    - 创建导出接口：GET `/api/v1/decisions/{decision_record_id}/export/pdf` 和 `/export/excel`
    - 导出文件写入 Object Storage 或临时下载目录
    - 权限控制：仅相关 Planner / Management 可导出
    - _Requirements: 27.7_

- [x] 10. Layer 5 — 企业资产层服务实现
  - [x] 10.1 实现 Case_Library 案例库服务
    - 创建 `app/services/case_library.py`
    - 实现 `create_case()`：ExecutionResult 生成后自动创建案例记录（含完整链路：异常特征→策略→规则→邻域→修复→执行结果）
    - 实现 `find_similar_cases()`：基于 pgvector 相似度检索（阈值 0.8），返回相似度评分排序列表
    - 实现 `update_preference()`：Override 时更新 PreferenceProfile 策略权重
    - 维护每个 Planner 的 PreferenceProfile（策略偏好、微调模式、Override 历史）
    - 案例数 > 10 且存在相似模式时提示归纳 CaseTemplate
    - 统计不同规则/邻域/修复策略在相似场景下的效果表现
    - 持续高采纳率组合推荐为默认求解配置模板
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.10, 9.11, 9.12_

  - [x] 10.2 实现 CaseTemplate 管理服务
    - 创建 `app/services/case_template_manager.py`
    - 支持 Management 审核、编辑、发布 CaseTemplate
    - 记录引用次数和采纳率
    - 发布后的模板可被 Strategy_Selector 引用
    - _Requirements: 9.8, 9.9_

  - [x] 10.3 实现 Case_Library API 端点
    - 创建 `app/api/cases.py`
    - GET `/api/v1/cases` — 查询案例列表（支持按异常类型、策略类型、时间范围、执行结果筛选）
    - GET `/api/v1/cases/{case_id}` — 查询案例详情
    - GET `/api/v1/case-templates` — 查询模板列表
    - POST `/api/v1/case-templates` — 创建模板
    - PUT `/api/v1/case-templates/{template_id}` — 编辑模板
    - POST `/api/v1/case-templates/{template_id}/publish` — 发布模板
    - GET `/api/v1/planners/{planner_id}/preference-profile` — 查询偏好画像
    - _Requirements: 9.3, 9.8, 14.1, 14.4_

  - [x]* 10.4 编写 Case_Library 单元测试
    - 测试 pgvector 相似度检索（阈值过滤、排序）
    - 测试 PreferenceProfile 更新逻辑
    - 测试 CaseTemplate 发布与引用统计
    - _Requirements: 9.3, 9.4, 9.9_

- [x] 11. 检查点 — 后端全链路验证
  - 确保 Layer 1→2→3→4→5 全链路可运行：异常接入→影响分析→策略选择→求解控制→求解→评估→推荐→解释→确认→回写→案例沉淀。确保所有测试通过，如有问题请向用户确认。

- [x] 12. 前端 — 项目脚手架与共享基础
  - [x] 12.1 初始化前端项目结构
    - 使用 Vite + React 18 + TypeScript 5 初始化项目
    - 安装依赖：Zustand, Ant Design 5, AntV G2/G6, axios, dayjs
    - 创建目录结构：`src/api/`, `src/stores/`, `src/components/`, `src/pages/`, `src/types/`, `src/hooks/`, `src/utils/`
    - 配置 API 客户端（axios 实例、拦截器、错误处理）
    - 配置 WebSocket 客户端（用于实时推送）
    - _Requirements: 10.7, 15.4_

  - [x] 12.2 定义前端 TypeScript 类型与 API 接口
    - 创建 `src/types/` 下所有核心类型定义（对齐后端 Pydantic 模型）
    - Incident, ImpactReport, StrategyRecommendation, CandidatePlan, PlanSelectionOutput, ComparisonMatrix, DecisionRecord, CaseRecord, CaseTemplate 等
    - 创建 `src/api/` 下所有 API 调用函数
    - _Requirements: 30.6_

  - [x] 12.2A 定义前后端共享状态映射契约
    - 明确 IncidentStatus、WritebackStatus、ConfirmAction、GoalMode 的前后端一一映射
    - 提供统一的状态文案、颜色、图标映射表
    - 确保前端不自行发明额外状态名
    - _Requirements: 10.3, 13.9, 17.1_

  - [x] 12.3 实现 Zustand 状态管理
    - 创建 `src/stores/incidentStore.ts`：当前选中 Incident、Incident 列表、筛选条件
    - 创建 `src/stores/analysisStore.ts`：ImpactReport、StrategyRecommendation
    - 创建 `src/stores/planStore.ts`：CandidatePlan 列表、PlanSelectionOutput、当前选中方案、GoalMode
    - 创建 `src/stores/confirmStore.ts`：确认状态、微调数据、Override 原因
    - 创建 `src/stores/workbenchStore.ts`：当前工作视图（Incident_Analysis_View / Multi_Plan_Selection_View）、Incident 上下文共享
    - 实现视图切换时保持 Incident 上下文不丢失
    - _Requirements: 31.11, 10.10_

  - [x] 12.4 实现工作台状态机与上下文重置规则
    - 创建 `src/stores/workbenchStateMachine.ts`
    - 定义默认状态：`incident_analysis`
    - 仅当 ImpactReport 和 candidate_plans 就绪时，允许切换到 `multi_plan_selection`
    - 切换 Incident 时清空：selectedPlanId、manualWeights、autoPreselected、adjustmentDraft
    - GoalMode 切换后，强制刷新 PlanSelectionOutput
    - 推荐结果刷新后，重新计算自动预选与右侧确认区状态
    - _Requirements: 10.10, 11.8, 12.11, 13.12, 31.3, 31.4, 31.11_

- [x] 13. 前端 — Decision_Workbench 工作台实现
  - [x] 13.1 实现 Decision_Workbench 主布局
    - 创建 `src/pages/DecisionWorkbench.tsx`
    - 实现工作台式多区块同屏布局（非独立 CRUD 页面拼接）
    - 五个同屏区块：异常事件列表区、当前处理状态区、影响范围分析区、候选方案比较区、人工确认执行区
    - 支持两种主工作状态切换：Incident_Analysis_View 和 Multi_Plan_Selection_View
    - 桌面端默认多区块同屏，不退化为串行信息流
    - 响应式适配（移动端/窄屏可退化为分步视图但保持 Incident 上下文）
    - _Requirements: 31.1, 31.2, 31.3, 31.5, 31.9, 31.10, 31.11_

  - [x] 13.2 实现异常事件列表区（异常总览台）
    - 创建 `src/components/IncidentListPanel.tsx`
    - 按严重等级（P1>P2>P3>P4）和发生时间排序
    - 每个 Incident 展示：事件 ID、异常类型、关联资源、严重等级、状态、发生时间、已耗时
    - 状态区分：未处理/处理中/待确认/已确认，当前处理 Incident 高亮
    - 筛选功能：异常类型、严重等级、状态、时间范围
    - 顶部统计指标：活跃异常数、待确认方案数、今日已处理数、平均响应时间
    - 点击 Incident 时联动加载详情/影响分析/候选方案/确认区
    - WebSocket 实时推送新 Incident 和状态变更
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.9, 10.10, 10.11_

  - [x] 13.2A 实现当前处理状态区
    - 创建 `src/components/ProcessingStatusPanel.tsx`
    - 展示：当前 Incident ID、当前状态（analyzing / pending_confirmation / confirmed / executing）、当前推荐策略、分析/求解耗时、WebSocket 连接状态、最近一次刷新时间
    - 与 IncidentContext 联动刷新
    - _Requirements: 31.2, 31.3, 31.7_

  - [x] 13.3 实现影响范围分析区（异常详情区）
    - 创建 `src/components/ImpactAnalysisPanel.tsx`
    - 展示 Incident 完整信息（异常类型、发生时间、资源详情、来源、严重等级、状态）
    - 展示影响报告：受影响工单列表（工单号、产品、交期、风险等级）、受影响工序甘特图、资源列表、预估总延迟
    - 展示策略推荐及结构化理由
    - 分析未完成时展示进度指示器，完成后自动刷新
    - 展示 Incident 时间线（接入→当前状态的关键节点和耗时）
    - 提供"查看候选方案"操作切换到方案比较区
    - 桌面端默认作为中部上方影响分析区，无需跳转独立详情页
    - 与候选方案比较区共享 Incident 上下文
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9_

  - [x] 13.4 实现候选方案比较区
    - 创建 `src/components/PlanComparisonPanel.tsx`
    - 消费 PlanSelectionOutput.comparison_matrix 作为标准数据源（不由前端重新计算排序）
    - 表格展示多维度评分对比矩阵，正向变化标绿、负向变化标红
    - 方案卡片区分四种状态：评分第一、AI 推荐、自动预选、人工已选择
    - 评分接近方案（差值 < 5%）显示"评分接近"标识
    - 选中两个方案时高亮差异工序
    - 展示每个方案的 Solver_Chain 摘要、主要 trade-off、执行风险
    - 选定方案后右侧确认区同步加载推荐理由/风险/确认操作
    - GoalMode 切换或权重调整时重新请求 PlanSelectionOutput 并刷新
    - _Requirements: 12.1, 12.2, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.11, 31.4_

  - [x] 13.5 实现甘特图组件（先进行技术选型验证：AntV G2 / dhtmlx-gantt / 自定义虚拟化 Canvas 方案）
    - 创建 `src/components/GanttChart.tsx`
    - 完成 500+ 工序、差异高亮、三视角切换、拖拽缩放的 PoC 验证后，冻结最终 gantt 技术方案
    - 支持按设备视角、工单视角、时间轴视角切换
    - 支持原排程与候选方案切换对比
    - 消费 gantt_diff_payload 渲染差异甘特图：高亮重排工序、设备切换、时间偏移、关键路径变化
    - 支持缩放和拖拽查看
    - 支持 500+ 工序场景，95 分位 3 秒内首屏加载
    - 数据缺失时标注缺失项并输出可用部分
    - _Requirements: 12.3, 12.10, 13.2, 27.1, 27.2, 27.3, 27.4, 27.6, 27.8, 27.9_

  - [x] 13.6 实现推荐与确认区
    - 创建 `src/components/ConfirmationPanel.tsx`
    - 消费 PlanSelectionOutput 展示：推荐方案 ID、推荐置信度、是否自动预选、核心推荐原因、主要风险与权衡点
    - 展示完整推荐理由（核心原因、关键优势、风险权衡点）
    - 展示"为什么不是另一个方案"对比摘要
    - 低置信度时取消默认自动选中，提示比较前两名
    - 三个操作按钮：确认采纳、微调后采纳、返回重选
    - 微调模式：允许拖拽调整工序设备分配和开始时间
    - 微调后实时展示约束校验结果，通过后启用最终确认按钮
    - 否决时弹出 Override 原因填写对话框（必填）
    - 确认后展示成功状态和回写进度
    - 桌面端默认作为右侧确认执行区，与中部候选方案区实时联动
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 13.10, 13.11, 13.12, 31.4, 31.7_

  - [x] 13.7 实现历史案例参考与偏好画像展示
    - 在 Decision_Workbench 中展示历史案例参考、偏好画像摘要和人工微调参数
    - 这些元素不得被完全隐藏在二级页面之后
    - _Requirements: 31.6_

- [x] 14. 前端 — 案例库与 KPI 页面
  - [x] 14.1 实现案例库与模板管理页
    - 创建 `src/pages/CaseLibraryPage.tsx`
    - 案例列表：支持按异常类型、策略类型、时间范围、执行结果筛选
    - 每个案例展示：Incident 摘要、策略、是否 Override、执行结果评分、创建时间
    - 案例详情：影响报告、候选方案、决策记录、执行结果
    - CaseTemplate 管理区域：已发布和草稿模板列表
    - 模板编辑表单：名称、适用异常类型、推荐策略、关键参数阈值
    - 模板使用统计：引用次数、采纳率、平均执行效果评分
    - 系统级偏好学习统计：AI 推荐采纳率趋势、Override 率趋势、平均响应时间趋势
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7_

  - [x] 14.2 实现 KPI 仪表盘
    - 创建 `src/components/KPIDashboard.tsx`
    - 展示核心 KPI：MTTD、MTTR-D、SPI、关键工单 OTD、换型次数变化率、AI 推荐采纳率、Override 率、案例复用率
    - 时间趋势图（日/周/月粒度）
    - KPI 目标值设定与偏离告警（偏离 > 10%）
    - 在异常总览台和案例库页面展示 KPI 摘要
    - _Requirements: 19.1, 19.2, 19.3, 19.4_

  - [x] 14.3 前端接入方案导出接口
    - 在 Decision_Workbench 确认区和案例详情页添加"导出 PDF"和"导出 Excel"按钮
    - 调用后端导出 API，展示下载进度
    - _Requirements: 27.7_

- [x] 15. 检查点 — 前端全功能验证
  - 确保 Decision_Workbench 两种视图可切换，异常列表→影响分析→方案比较→确认执行全流程可操作。确保所有测试通过，如有问题请向用户确认。

- [x] 16. 系统集成适配器
  - [x] 16.1 实现 MES 回写适配器
    - 创建 `app/adapters/mes_adapter.py`
    - 实现排程变更指令格式转换（适配不同 MES 系统数据格式）
    - 实现回写重试机制（最多 3 次，指数退避）
    - 接口不可用时缓存到本地队列，恢复后自动重试
    - _Requirements: 8.2, 18.3, 18.5_

  - [x] 16.2 实现 ERP/APS 数据导入适配器
    - 创建 `app/adapters/erp_adapter.py`
    - 实现排程数据导入接口（从 APS 导入 ScheduleSnapshot）
    - 实现资源/工单/工序主数据同步
    - _Requirements: 18.4_

  - [x] 16.3 实现 IoT 事件接入适配器
    - 创建 `app/adapters/iot_adapter.py`
    - 实现 IoT 平台异常事件接入（Kafka 消费）
    - _Requirements: 1.1, 18.2_

  - [x] 16.4 实现集成健康检查
    - 创建 `app/adapters/health_check.py`
    - 监控所有外部系统连接可用性（MES、IoT、ERP/APS）
    - 提供健康检查端点 GET `/api/v1/health/integrations`
    - _Requirements: 18.6_

  - [x] 16.5 实现 WebSocket 实时推送服务
    - 创建 `app/api/ws.py`
    - 实现 WSS `/api/v1/ws/incidents`
    - 推送事件类型：incident_created, incident_updated, impact_report_ready, strategy_selected, plans_generated, recommendation_updated, writeback_status_changed
    - 基于 JWT / Session 做连接鉴权
    - 支持按用户角色 / 车间范围过滤事件
    - 提供断线重连后的最近事件补偿机制
    - _Requirements: 10.7, 15.4, 31.3_

- [x] 17. 可观测性与监控
  - [x] 17.1 集成 OpenTelemetry 分布式链路追踪
    - 配置 OpenTelemetry SDK（traces, metrics, logs）
    - 为异常处理全流程添加 span（AIC→IAE→SS→SPL→HS→EC→PRE→EL→CM→WM→CL）
    - 配置 Prometheus 指标导出
    - _Requirements: 16.8_

  - [x] 17.2 实现系统健康监控
    - 创建 `app/api/health.py`
    - GET `/api/v1/health` — 系统整体健康状态
    - 各模块运行状态、延迟指标、错误率
    - 配置 Grafana 仪表盘模板（各模块延迟、错误率、吞吐量）
    - _Requirements: 16.7_

  - [x] 17.3 实现审计日志系统
    - 创建 `app/core/audit_logger.py`
    - 记录所有用户操作：登录、方案确认、Override、模板发布
    - 包含操作人、操作时间、操作内容、操作结果
    - 记录策略模块版本变更、Solver_Portfolio 配置变更审计日志
    - _Requirements: 16.3, 26.8_

- [x] 18. Incident 状态机与数据一致性
  - [x] 18.1 实现 Incident 状态机
    - 创建 `app/services/incident_state_machine.py`
    - 定义合法状态流转：pending_analysis → analyzing → pending_confirmation → confirmed → executing → closed
    - 禁止非法状态跳转，违反时抛出异常
    - _Requirements: 17.1_

  - [x] 18.2 实现 ScheduleSnapshot 不可变性保证
    - 快照创建后在整个决策流程中保持不可变
    - 排程变更不影响已创建快照
    - _Requirements: 17.3_

  - [x] 18.3 实现数据库事务与回滚机制
    - 决策流程中事务失败时回滚到一致状态并通知用户
    - 确保 DecisionRecord 与关联实体的引用完整性
    - _Requirements: 17.2, 17.4_

  - [x] 18.4 实现关键写接口幂等性控制
    - 为 Incident 创建、方案确认、MES 回写引入幂等键（Idempotency-Key header）
    - 重复请求返回相同结果，不重复创建实体或重复执行回写
    - _Requirements: 1.3, 7.6, 8.1, 17.2_

- [x] 19. 策略模块灰度发布与 A/B 测试基础
  - [x] 19.1 实现灰度发布与 A/B 测试框架
    - 创建 `app/services/experiment_manager.py`
    - 支持为特定车间/异常类型/用户组启用灰度版本
    - 支持 A/B 测试：比较求解时间、可行率、SPI、采纳率、Override 率
    - 新版本导致可行率下降或 MTTR-D 恶化超阈值时自动回滚
    - 支持策略模块级运行监控（调用次数、平均耗时、失败率、效果指标）
    - 支持离线回放历史 Incident 进行效果复盘
    - _Requirements: 26.3, 26.4, 26.5, 26.6, 26.7_

- [x] 20. 检查点 — 系统集成与非功能性验证
  - 确保外部系统适配器可连接，OpenTelemetry 链路追踪正常，状态机约束生效，审计日志记录完整。确保所有测试通过，如有问题请向用户确认。

- [x] 21. 端到端集成测试
  - [x] 21.1 编写异常接入→影响分析→策略选择集成测试
    - 模拟 MES 上报设备故障事件
    - 验证 Incident 创建、Intake Severity 分级、影响分析、severity 升级、策略选择全链路
    - 验证 Kafka 事件发布与消费
    - _Requirements: 1.1, 1.8, 2.1, 3.1_

  - [x] 21.2 编写求解→评估→推荐→解释集成测试
    - 模拟策略选择后触发求解
    - 验证 Solver_Policy_Layer 配置传递、Hybrid_Solver 求解、约束校验、评估排序、推荐输出、解释生成
    - 验证 PlanSelectionInput → PlanSelectionOutput 完整流程
    - _Requirements: 4.1, 5.1, 29.1, 6.1_

  - [x] 21.3 编写确认→回写→案例沉淀集成测试
    - 模拟 Planner 确认方案（含微调和 Override 场景）
    - 验证 DecisionRecord 生成、MES 回写、ExecutionResult 生成、案例创建、偏好更新
    - _Requirements: 7.1, 8.1, 9.1_

  - [x] 21.4 编写前后端联调集成测试
    - 验证 Decision_Workbench 两种视图切换
    - 验证 Incident 选择→影响分析→方案比较→确认执行前后端联动
    - 验证 GoalMode 切换时 PlanSelectionOutput 刷新
    - 验证 WebSocket 实时推送
    - _Requirements: 31.3, 31.4, 31.11, 10.7, 12.11_

- [x] 22. 最终检查点 — 全系统验证
  - 确保所有测试通过，全链路端到端可运行。如有问题请向用户确认。

## Notes

- 标记 `*` 的任务为可选任务，可跳过以加速 MVP 交付；2.6（序列化测试）、7.3（约束校验测试）、9.4（确认模块测试）、21.1-21.3（核心 E2E）为必须任务
- `impact_reports` 表作为正式持久化对象存储 ImpactReport JSONB，关联 incident_id 和 snapshot_id
- 每个任务引用了具体的需求编号以确保可追溯性
- 检查点任务确保增量验证，及早发现问题
- 后端使用 Python 3.11+ / FastAPI，前端使用 React 18 + TypeScript 5
- 求解引擎使用 Google OR-Tools CP-SAT
- 所有时间计算基于 `schedule_snapshot.captured_at`，确保可复现性
- 微调方案通过 `derived_from_plan_id` 链接原始方案，创建新版本
- PlanSelectionInput 是推荐引擎的唯一输入对象，通过 PlanSelectionInputBuilder 统一组装
- Solver_Policy_Layer 通过 SolverPolicyOrchestrator 统一输出 SolverPolicyBundle，Hybrid_Solver 不直接依赖各选择器
- Solver_Policy_Layer 各模块独立版本管理，支持热替换
