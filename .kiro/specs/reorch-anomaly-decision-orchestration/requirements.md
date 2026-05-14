# 需求文档：ReOrch 智策 — 异常重决策编排系统

## 简介

ReOrch 智策是一套 AI 驱动的异常重决策编排系统，定位于 ERP/MES/APS 之上的决策层。其核心目标不是替代排产系统，而是在工厂异常（MVP 阶段聚焦设备故障）发生时，基于实时生产上下文，快速识别影响范围、选择求解路径、生成多个可执行候选方案、支持人工确认与微调，并将决策经验沉淀为企业资产。

系统采用 AI Orchestration + Solver Policy Layer + OR Solver + Human-in-the-loop 混合决策架构，包含五层：AI 编排层、求解策略控制层、优化求解层、人机协同层、企业资产层。其中，求解策略控制层负责在高层业务策略确定后，独立决定规则选择、邻域选择与修复策略，不直接生成最终排程，而是为优化求解层提供可替换、可审计、可演进的求解控制策略。该设计确保系统未来能够在不改动核心求解器的前提下，逐步引入新的规则库、超启发式方法、学习型策略模块与实验性算法。

### MVP 范围

- 单车间、单异常类型（设备故障）
- 单目标模式默认：平衡优先
- 三类策略：等待修复 / 局部修复 / 全局重排
- Top-3 候选方案输出
- 人工确认 + Override 记录
- MES 回写
- 基础案例库

### 非目标（锁定）

- 不做全厂 APS 替代
- 不直接输出纯自然语言建议作为最终结果
- 不允许 LLM 绕过约束求解器直接生成排程
- MVP 不做跨工厂、跨供应商网络协同
- MVP 不追求全异常类型全覆盖

## 术语表

- **ReOrch_System**: ReOrch 智策系统整体，异常重决策编排系统
- **Incident（异常事件）**: 由外部系统（MES/IoT/人工）上报的生产异常，MVP 阶段限定为设备故障
- **Anomaly_Intake_Center（异常接入中心）**: 统一接入、标准化、去重、分级异常事件的模块
- **Impact_Analysis_Engine（影响范围分析引擎）**: 识别异常影响的工单、资源、工序、交期风险的模块
- **Strategy_Selector（策略选择器 / AI Orchestrator）**: 基于异常类型、影响范围、历史案例决定求解路径的 AI 编排模块
- **Hybrid_Solver（混合优化求解引擎）**: 使用启发式初解 + 局部搜索/LNS + 约束校验产出候选方案的求解模块
- **Evaluation_Center（多目标评估与排序中心）**: 对候选方案进行多维度评分、排序、对比展示的模块
- **Explainability_Layer（推荐理由与可解释性层）**: 负责生成推荐解释（Recommendation_Explanation）与求解链路解释（Solver_Chain_Explanation）的模块，用于说明为什么推荐该方案以及该方案如何被生成出来
- **Confirmation_Module（人工确认与 Override 机制）**: 支持人工审核、微调、Override 并记录决策的模块
- **Writeback_Module（执行回写与闭环追踪）**: 将确认方案同步回 MES/ERP/APS 并追踪执行结果的模块
- **Case_Library（案例库与偏好学习）**: 沉淀决策案例、模板化、持续更新偏好模型的模块
- **Planner（计划员）**: 主要用户角色，负责排产计划与异常响应决策
- **Shop_Floor_Executor（车间执行负责人）**: 主要用户角色，负责车间现场执行与反馈
- **Management（制造管理层）**: 主要用户角色，关注 KPI 与决策质量
- **WorkOrder（工单）**: 生产工单，包含工序、资源、物料、交期等信息
- **Operation（工序）**: 工单中的具体加工步骤
- **Resource（资源）**: 设备、人员等生产资源
- **ScheduleSnapshot（排程快照）**: 异常发生时刻的排程状态快照
- **CandidatePlan（候选方案）**: 求解引擎产出的可执行重排方案
- **DecisionRecord（决策记录）**: 人工确认/Override 的完整决策记录
- **CaseTemplate（案例模板）**: 从历史决策中提炼的可复用模板
- **PreferenceProfile（偏好画像）**: 基于历史决策行为学习的用户/企业偏好模型
- **Hard_Constraint（硬约束）**: 不可违反的约束条件（如设备能力、工艺顺序）
- **Soft_Constraint（软约束）**: 可权衡的优化目标（如交期偏差、换型次数）
- **Override**: 人工对 AI 推荐方案的修改或否决操作
- **LNS（大邻域搜索）**: Large Neighborhood Search，一种组合优化元启发式算法
- **SPI（Schedule Perturbation Index）**: 排程扰动指数，衡量重排对原计划的扰动程度
- **OTD（On-Time Delivery）**: 准时交付率
- **Solver_Policy_Layer（求解策略控制层）**: 位于 Strategy_Selector 与 Hybrid_Solver 之间的控制层，负责选择具体求解规则、邻域算子和修复策略，并支持独立封装、版本管理和替换扩展
- **Rule_Selector（规则选择器）**: 根据异常特征、影响范围、当前策略与历史案例，选择用于初解生成或局部修复的调度规则/优先级规则的模块
- **Neighborhood_Selector（邻域选择器）**: 根据当前解状态、异常类型、优化进展与扰动约束，动态选择局部搜索或 LNS 的邻域算子和搜索范围的模块
- **Repair_Policy_Advisor（修复策略顾问）**: 根据异常严重度、策略类型、求解预算与偏好约束，决定修复强度、冻结范围、搜索预算、候选方案数量目标和回退策略的模块
- **Solver_Portfolio（求解器组合）**: 针对不同高层策略场景维护的可执行求解链路集合，包含主求解器、备选求解器、兜底规则及降级机制
- **Solver_Chain（求解链路）**: 某一候选方案生成过程中实际执行的阶段化算法链路，例如"规则选择 → 初解生成 → 邻域选择 → LNS 修复 → 约束校验 → 多目标排序"
- **Gantt_View（甘特图视图）**: 用于展示原始排程、候选方案排程及其差异的可视化视图，支持按设备、工单和时间轴维度查看
- **Schedule_Detail（排程明细）**: 候选方案或最终确认方案对应的结构化排程数据，包含工单、工序、设备、开始结束时间、前后序关系和是否调整等信息
- **Plan_Recommendation_Engine（方案推荐引擎）**: 位于 Evaluation_Center 与 Confirmation_Module 之间的推荐决策模块，负责基于候选方案评分、业务目标模式、历史偏好、相似案例和执行约束，输出推荐方案、备选方案、推荐理由和推荐置信度
- **Plan_Selection_Input（方案选择输入对象）**: 用于驱动方案推荐引擎的统一输入数据结构，包含异常上下文、排程基线、候选方案集合、业务目标模式、偏好画像、历史案例和人工可调参数
- **Plan_Selection_Output（方案选择输出对象）**: 方案推荐引擎输出的统一结构化结果，包含推荐方案、备选方案、方案排名、推荐理由、风险提示、前端展示数据和审计信息
- **Decision_Workbench（决策工作台）**: 面向计划员的工作台式界面，用于在同一界面中完成异常查看、影响分析、候选方案比较、推荐理由查看和最终确认执行
- **Workbench_Layout（工作台布局）**: 前端页面的区块化布局规范，规定哪些信息必须同屏展示、哪些区块需联动刷新、哪些关键操作不得被拆散到多次跳转中
- **Goal_Mode（业务目标模式）**: 用于驱动方案评估与推荐的业务目标配置，包含交付优先、稳定优先、瓶颈优先、成本优先、平衡优先等模式
- **Auto_Preselection（自动预选）**: 当推荐置信度和执行可行性满足阈值时，系统自动将某一候选方案标记为默认选中方案的行为
- **Recommendation_Confidence（推荐置信度）**: 方案推荐引擎对当前推荐结果可信度的量化评分，取值范围为 0–1
- **Comparison_Matrix（方案对比矩阵）**: 用于前端展示候选方案多维度评分、差值、风险和 trade-off 的结构化矩阵数据
- **Gantt_Diff_Payload（甘特图差异载荷）**: 用于驱动前端差异甘特图渲染的结构化数据，包含原排程与候选方案之间的工序调整、时间偏移、资源切换和关键路径变化
- **Incident_Severity（异常严重等级）**: 用于描述异常事件本身的业务严重程度，分为 P1-Critical、P2-High、P3-Medium、P4-Low
- **Delivery_Risk_Level（交付风险等级）**: 用于描述受影响工单在当前排程与异常条件下的交付风险，分为 Safe、Warning、Breach
- **Recommendation_Explanation（推荐解释）**: 用于说明"为什么推荐该方案"的结构化解释对象，包含推荐原因、关键优势、主要风险及与备选方案的差异
- **Solver_Chain_Explanation（求解链路解释）**: 用于说明"该方案是如何被生成出来的"的结构化解释对象，包含规则选择、邻域选择、修复策略、求解器链路和关键参数说明

## 需求

### 需求 1：异常事件统一接入与标准化

**用户故事：** 作为计划员，我希望系统能统一接入来自不同来源的异常事件并标准化处理，以便我能在一个入口快速感知所有异常。

#### 验收标准

1. WHEN 外部系统（MES、IoT 平台、人工上报）发送异常事件，THE Anomaly_Intake_Center SHALL 在 5 秒内完成事件接收并返回确认回执。
2. WHEN 异常事件被接收，THE Anomaly_Intake_Center SHALL 将事件转换为统一的 Incident 数据结构，包含异常类型、发生时间、关联资源 ID、上报来源、严重等级。
3. WHEN 在 10 分钟窗口内收到同一资源的重复异常事件，THE Anomaly_Intake_Center SHALL 对重复事件进行去重合并，仅保留一条主事件并关联所有原始事件 ID。
4. WHEN 异常事件被标准化后，THE Anomaly_Intake_Center SHALL 根据异常类型和影响资源的关键程度自动分配严重等级（P1-Critical / P2-High / P3-Medium / P4-Low）。
5. IF 异常事件缺少必要字段（异常类型、资源 ID、发生时间），THEN THE Anomaly_Intake_Center SHALL 拒绝该事件并返回包含缺失字段列表的错误响应。
6. IF 异常事件的上报来源未在系统注册的合法来源列表中，THEN THE Anomaly_Intake_Center SHALL 拒绝该事件并记录安全审计日志。
7. THE Anomaly_Intake_Center SHALL 为每个接收的 Incident 生成全局唯一的事件 ID。
8. WHEN Incident 被成功创建，THE Anomaly_Intake_Center SHALL 将 Incident 发布到事件流（Kafka/Redpanda）供下游模块消费。

### 需求 2：影响范围分析

**用户故事：** 作为计划员，我希望系统能在异常发生后自动识别受影响的工单、工序、资源和交期风险，以便我能快速了解异常的波及范围。

#### 验收标准

1. WHEN Impact_Analysis_Engine 接收到一个 Incident，THE Impact_Analysis_Engine SHALL 在 10 秒内完成影响范围分析并输出影响报告。
2. WHEN 进行影响范围分析时，THE Impact_Analysis_Engine SHALL 获取异常发生时刻的 ScheduleSnapshot 作为分析基准。
3. WHEN 设备故障类型的 Incident 被接收，THE Impact_Analysis_Engine SHALL 识别所有直接依赖该故障设备的 Operation 及其所属 WorkOrder。
4. WHEN 直接受影响的 Operation 被识别后，THE Impact_Analysis_Engine SHALL 沿工艺路线向下游传播，识别所有间接受影响的后续 Operation。
5. WHEN 影响范围被确定后，THE Impact_Analysis_Engine SHALL 计算每个受影响 WorkOrder 的 Delivery_Risk_Level（Safe / Warning / Breach），基于剩余工序时间、当前排程缓冲时间与交期的差值。
6. THE Impact_Analysis_Engine SHALL 输出结构化的影响报告，包含：受影响工单列表、受影响工序列表、受影响资源列表、交期风险分布、预估总延迟时间。
7. IF ScheduleSnapshot 数据不可用或不完整，THEN THE Impact_Analysis_Engine SHALL 标记分析结果为"降级模式"并在影响报告中注明数据缺失项。

### 需求 3：策略选择与求解路径决定

**用户故事：** 作为计划员，我希望系统能根据异常的类型和影响范围自动推荐合适的求解策略，以便我不需要从零开始思考应对方案。

#### 验收标准

1. WHEN Impact_Analysis_Engine 输出影响报告后，THE Strategy_Selector SHALL 在 10 秒内输出推荐的求解策略。
2. THE Strategy_Selector SHALL 从以下三类策略中选择：等待修复（Wait-and-Repair）、局部修复（Local-Repair）、全局重排（Global-Reschedule）。
3. WHEN 设备预计恢复时间小于受影响工序的总缓冲时间，THE Strategy_Selector SHALL 推荐"等待修复"策略。
4. WHEN 受影响工单数量不超过总在制工单的 20% 且无 Breach 级交付风险，THE Strategy_Selector SHALL 推荐"局部修复"策略。
5. WHEN 受影响工单数量超过总在制工单的 20% 或存在 Breach 级交付风险，THE Strategy_Selector SHALL 推荐"全局重排"策略。
6. WHEN 案例库中存在与当前异常相似度大于 0.8 的历史案例，THE Strategy_Selector SHALL 将历史案例的策略作为参考因素纳入策略选择。
7. THE Strategy_Selector SHALL 输出策略选择的结构化理由，包含：选择的策略类型、关键决策因子（影响范围、交期风险、历史案例匹配度）、置信度评分（0-1）。
8. IF Strategy_Selector 的置信度评分低于 0.5，THEN THE Strategy_Selector SHALL 同时输出排名前两位的策略供 Planner 人工选择。
9. THE Strategy_Selector SHALL 仅负责高层业务策略选择，不直接决定具体调度规则、邻域算子或修复强度；这些决策 SHALL 由 Solver_Policy_Layer 完成。
10. WHEN Strategy_Selector 输出高层策略后，THE ReOrch_System SHALL 将该策略作为输入传递给 Solver_Policy_Layer，用于后续求解控制决策。

### 需求 4：混合优化求解与候选方案生成

**用户故事：** 作为计划员，我希望系统能基于选定策略快速生成多个满足硬约束的候选方案，以便我能从中选择最合适的方案。

#### 验收标准

1. WHEN 求解策略被确定后，THE Hybrid_Solver SHALL 在 60 秒内生成至少 3 个候选方案（Top-3）。
2. THE Hybrid_Solver SHALL 确保所有候选方案满足全部 Hard_Constraint，包括：设备能力约束、工艺顺序约束、资源可用性约束、物料可用性约束。
3. WHEN 执行"等待修复"策略时，THE Hybrid_Solver SHALL 生成保持原排程不变仅调整受影响工序开始时间的方案。
4. WHEN 执行"局部修复"策略时，THE Hybrid_Solver SHALL 仅对受影响的工序及其直接下游工序进行重排，保持其余排程不变。
5. WHEN 执行"全局重排"策略时，THE Hybrid_Solver SHALL 对整个车间的排程进行重新优化。
6. THE Hybrid_Solver SHALL 使用启发式算法生成初始可行解，再通过局部搜索或 LNS 进行优化改进。
7. THE Hybrid_Solver SHALL 对每个 CandidatePlan 执行约束校验，校验通过后方可输出。
8. IF Hybrid_Solver 在 60 秒内无法生成 3 个满足硬约束的方案，THEN THE Hybrid_Solver SHALL 输出已生成的可行方案（至少 1 个）并标注"求解超时，方案数量不足"。
9. IF Hybrid_Solver 无法生成任何满足硬约束的方案，THEN THE Hybrid_Solver SHALL 返回不可行报告，列出无法满足的约束条件。
10. FOR ALL CandidatePlan，THE Hybrid_Solver SHALL 记录求解过程元数据：求解耗时、迭代次数、目标函数值变化轨迹。
11. BEFORE 执行初解生成或局部搜索，THE Hybrid_Solver SHALL 调用 Rule_Selector 获取当前场景的规则配置。
12. BEFORE 执行局部搜索或 LNS，THE Hybrid_Solver SHALL 调用 Neighborhood_Selector 获取本轮搜索邻域配置。
13. BEFORE 启动求解流程，THE Hybrid_Solver SHALL 调用 Repair_Policy_Advisor 获取修复策略配置，并按该配置执行求解。
14. THE Hybrid_Solver SHALL 支持根据 Solver_Portfolio 配置在主求解器、备选求解器和兜底规则之间切换。
15. IF 主求解器超时、失败或返回不可行结果，THEN THE Hybrid_Solver SHALL 按 Solver_Portfolio 的降级规则自动切换到备选求解链路，并记录降级原因。
16. THE Hybrid_Solver SHALL 为每个 CandidatePlan 记录完整的 Solver_Chain，并与求解过程元数据一起保存。

### 需求 5：多目标评估与方案排序

**用户故事：** 作为计划员，我希望系统能从多个维度对候选方案进行评分和排序，以便我能直观地比较不同方案的优劣。

#### 验收标准

1. WHEN CandidatePlan 列表被生成后，THE Evaluation_Center SHALL 对每个方案计算以下维度的评分：交期影响（延迟工单数、最大延迟时间）、排程扰动（SPI）、资源利用率变化、换型次数变化、关键工单 OTD 影响。
2. THE Evaluation_Center SHALL 基于"平衡优先"默认目标模式对候选方案进行综合评分与排序，输出评分排名结果，不直接决定最终推荐方案。
3. THE Evaluation_Center SHALL 为每个评分维度提供与原排程（ScheduleSnapshot）的对比差值。
4. WHEN 两个候选方案的综合评分差值小于 5%，THE Evaluation_Center SHALL 将两者标记为"评分接近"，提示 Planner 需关注细分维度差异。
5. THE Evaluation_Center SHALL 输出结构化的方案对比矩阵，每行为一个候选方案，每列为一个评分维度。
6. IF 某个评分维度的数据不可用，THEN THE Evaluation_Center SHALL 在对比矩阵中标注"数据缺失"并排除该维度参与综合排序。
7. THE Evaluation_Center SHALL 为 Comparison_Matrix 中的所有评分字段定义统一的归一化尺度、计算公式和单位说明，并确保"评分接近（差值 < 5%）"的判定基于同一归一化评分体系。

### 需求 6：推荐理由与可解释性

**用户故事：** 作为计划员，我希望系统能为每个推荐方案提供清晰的结构化理由，以便我能理解 AI 的推荐逻辑并做出有信心的决策。

#### 验收标准

1. WHEN Plan_Recommendation_Engine 输出最终推荐方案后，THE Explainability_Layer SHALL 为推荐方案生成 Recommendation_Explanation，并为备选方案生成简要对比说明。
2. THE Explainability_Layer SHALL 在推荐理由中包含以下要素：推荐该方案的核心原因（不超过 3 条）、该方案相比其他方案的关键优势、该方案的主要风险或权衡点。
3. THE Explainability_Layer SHALL 使用业务术语（工单号、设备名、交期日期）而非纯技术术语生成推荐理由。
4. WHEN 历史案例被用于策略选择时，THE Explainability_Layer SHALL 在推荐理由中引用相关历史案例的 ID 和结果。
5. THE Explainability_Layer SHALL 为每个候选方案生成简要摘要（不超过 200 字），概述方案的核心调整内容和预期效果。
6. THE Explainability_Layer SHALL 确保推荐解释以结构化数据对象输出，并支持面向前端展示的自然语言渲染；系统内部不得仅保存不可解析的纯文本段落作为最终推荐结果。

### 需求 7：人工确认与 Override 机制

**用户故事：** 作为计划员，我希望能对 AI 推荐的方案进行审核、微调或否决，并且系统能完整记录我的决策过程，以便保持人对最终决策的控制权。

#### 验收标准

1. WHEN 候选方案和推荐理由被展示后，THE Confirmation_Module SHALL 提供"确认采纳"、"微调后采纳"、"否决并选择其他方案"三种操作选项。
2. WHEN Planner 选择"微调后采纳"时，THE Confirmation_Module SHALL 允许 Planner 对方案中的具体工序进行手动调整（调整设备分配、调整开始时间）。
3. WHEN Planner 对方案进行微调后，THE Hybrid_Solver SHALL 对微调后的方案重新执行 Hard_Constraint 校验，校验通过后方可确认。
4. IF Planner 的微调导致 Hard_Constraint 违反，THEN THE Confirmation_Module SHALL 提示具体违反的约束条件并阻止确认。
5. WHEN Planner 否决 AI 推荐并选择其他方案或手动方案时，THE Confirmation_Module SHALL 将该操作记录为 Override，包含：Override 原因（Planner 填写）、原推荐方案 ID、实际选择方案 ID、Override 时间。
6. THE Confirmation_Module SHALL 为每次决策生成完整的 DecisionRecord，包含：Incident ID、影响报告摘要、策略选择、所有候选方案 ID、推荐方案 ID、最终确认方案 ID、是否 Override、确认人、确认时间。
7. THE Confirmation_Module SHALL 基于角色权限控制操作范围：Planner 可确认/微调/否决，Shop_Floor_Executor 仅可查看，Management 可查看和审批 P1 级异常的决策。
8. WHEN 一个 Incident 的决策超过 15 分钟未被确认，THE Confirmation_Module SHALL 向 Planner 和其直属上级发送超时提醒通知。

### 需求 8：执行回写与闭环追踪

**用户故事：** 作为车间执行负责人，我希望确认后的方案能自动同步到 MES 系统并追踪执行结果，以便车间能按新计划执行且管理层能看到闭环效果。

#### 验收标准

1. WHEN 方案被 Planner 确认后，THE Writeback_Module SHALL 将确认方案的排程变更指令回写到 MES 系统。
2. THE Writeback_Module SHALL 在回写前将指令转换为目标 MES 系统的数据格式。
3. WHEN 回写完成后，THE Writeback_Module SHALL 记录回写状态（成功 / 部分成功 / 失败）及每条指令的回写结果。
4. IF 回写过程中某条指令失败，THEN THE Writeback_Module SHALL 标记该指令为失败，继续执行其余指令，并在回写报告中汇总失败项。
5. WHEN 回写成功后，THE Writeback_Module SHALL 启动执行追踪，定期（每 5 分钟）从 MES 获取实际执行进度与确认方案进行对比。
6. WHEN 实际执行进度与确认方案的偏差超过 10%，THE Writeback_Module SHALL 生成偏差告警并通知 Planner。
7. WHEN Incident 关联的所有受影响工单执行完毕，THE Writeback_Module SHALL 生成 ExecutionResult，包含：实际完成时间 vs 计划完成时间、实际 OTD、实际资源利用率。
8. THE Writeback_Module SHALL 将 ExecutionResult 关联回原始 DecisionRecord，形成完整的决策闭环。

### 需求 9：案例沉淀与偏好学习

**用户故事：** 作为制造管理层，我希望系统能将每次异常决策沉淀为可复用的案例，并学习计划员的偏好，以便系统的推荐质量持续提升。

#### 验收标准

1. WHEN ExecutionResult 生成后，THE Case_Library SHALL 自动创建一条案例记录，包含：Incident 特征、影响范围、选择的策略、确认的方案、执行结果、是否 Override。
2. WHEN 案例记录数量超过 10 条且存在相似模式，THE Case_Library SHALL 提示 Management 将相似案例归纳为 CaseTemplate。
3. THE Case_Library SHALL 支持基于异常特征（异常类型、影响范围大小、交期风险等级）的相似案例检索，返回相似度评分排序的结果列表。
4. WHEN 新的 DecisionRecord 包含 Override 操作时，THE Case_Library SHALL 将 Override 信息纳入 PreferenceProfile 更新，调整对应场景下的策略权重。
5. THE Case_Library SHALL 维护每个 Planner 的 PreferenceProfile，记录其在不同异常场景下的策略偏好和微调模式。
6. WHEN Strategy_Selector 进行策略选择时，THE Case_Library SHALL 提供当前 Planner 的 PreferenceProfile 和匹配的历史案例作为输入。
7. WHEN Rule_Selector、Neighborhood_Selector 或 Repair_Policy_Advisor 执行策略决策时，THE Case_Library SHALL 提供相关历史案例、偏好画像和效果统计作为输入参考。
8. THE Case_Library SHALL 支持 Management 对 CaseTemplate 进行审核、编辑和发布，发布后的模板可被 Strategy_Selector 引用。
9. THE Case_Library SHALL 记录每个 CaseTemplate 的引用次数和引用后的采纳率，作为模板质量评估指标。
10. THE Case_Library SHALL 记录"异常特征—高层策略—规则选择—邻域选择—修复策略—执行结果"的完整链路，用于后续策略模块训练与评估。
11. THE Case_Library SHALL 统计不同规则、不同邻域算子和不同修复策略在相似场景下的效果表现，作为 Solver_Policy_Layer 后续选择依据。
12. WHEN 某类策略模块组合在特定场景下持续取得更高采纳率或更优 KPI，THE Case_Library SHALL 支持将其推荐为默认求解配置模板。

### 需求 10：异常总览台（UI）

**用户故事：** 作为计划员，我希望有一个统一的异常总览界面，以便我能一目了然地看到当前所有异常的状态和优先级。

#### 验收标准

1. THE ReOrch_System SHALL 提供异常总览台页面，展示所有活跃 Incident 的列表视图。
2. THE 异常总览台 SHALL 按严重等级（P1 > P2 > P3 > P4）和发生时间排序展示 Incident。
3. THE 异常总览台 SHALL 为每个 Incident 展示：事件 ID、异常类型、关联资源、严重等级、当前状态（待分析 / 分析中 / 待确认 / 已确认 / 执行中 / 已关闭）、发生时间、已耗时。
4. WHEN Planner 点击某个 Incident，THE Decision_Workbench SHALL 在当前工作台上下文中加载该 Incident 的异常详情、影响分析、候选方案和确认区内容；在移动端或窄屏模式下，可退化为跳转到详情视图。
5. THE 异常总览台 SHALL 提供按异常类型、严重等级、状态、时间范围的筛选功能。
6. THE 异常总览台 SHALL 在页面顶部展示关键统计指标：活跃异常数、待确认方案数、今日已处理数、平均响应时间。
7. WHILE 异常总览台处于打开状态，THE ReOrch_System SHALL 通过 WebSocket 实时推送新 Incident 和状态变更，无需手动刷新。
8. THE 异常总览台 SHALL 在 95 分位响应时间内 2 秒内完成页面加载和数据渲染。
9. THE 异常总览台 SHALL 作为 Decision_Workbench 的左侧异常事件列表区存在，并支持与中部分析区和右侧确认区联动。
10. WHEN Planner 在异常总览台中切换当前 Incident，THE 影响范围分析区、候选方案比较区和人工确认执行区 SHALL 同步刷新为对应 Incident 的上下文。
11. THE 异常总览台 SHALL 显示当前正在处理的 Incident 高亮状态，并明确区分"未处理""处理中""待确认""已确认"等状态。

### 需求 11：异常详情区（UI）

**用户故事：** 作为计划员，我希望能查看单个异常的完整详情，包括影响范围分析结果和策略推荐，以便我能深入了解异常情况。

#### 验收标准

1. WHEN Planner 进入异常详情区，THE ReOrch_System SHALL 展示 Incident 的完整信息：异常类型、发生时间、关联资源详情、上报来源、严重等级、当前状态。
2. THE 异常详情区 SHALL 展示 Impact_Analysis_Engine 输出的影响报告：受影响工单列表（含工单号、产品、交期、风险等级）、受影响工序甘特图、受影响资源列表、预估总延迟时间。
3. THE 异常详情区 SHALL 展示 Strategy_Selector 的推荐策略及结构化理由。
4. WHEN 影响分析尚未完成时，THE 异常详情区 SHALL 展示分析进度指示器，并在分析完成后自动刷新展示结果。
5. THE 异常详情区 SHALL 提供"查看候选方案"操作，切换工作台焦点至候选方案比较区，并保持当前 Incident 上下文不变。
6. THE 异常详情区 SHALL 展示该 Incident 的时间线，记录从接入到当前状态的所有关键节点和耗时。
7. THE 异常详情区 SHALL 在桌面端默认作为 Decision_Workbench 中部上方的影响分析区存在，而非必须跳转到独立详情页后才能查看。
8. THE 异常详情区 SHALL 与候选方案比较区共享当前 Incident 上下文，保证影响报告、风险等级和推荐路径同步一致。
9. THE 异常详情区 SHALL 支持直接进入候选方案查看状态，不得要求用户必须经过多次跳转才能进入方案决策流程。

### 需求 12：候选方案比较区（UI）

**用户故事：** 作为计划员，我希望能在一个页面上直观对比多个候选方案的各项指标，以便我能快速选出最优方案。

#### 验收标准

1. THE 候选方案比较区 SHALL 以表格形式展示所有候选方案的多维度评分对比矩阵。
2. THE 候选方案比较区 SHALL 为每个评分维度提供与原排程的对比差值，正向变化标绿、负向变化标红。
3. THE 候选方案比较区 SHALL 提供甘特图视图，支持在原排程和各候选方案之间切换对比。
4. WHEN Planner 选中两个方案时，THE 候选方案比较区 SHALL 高亮显示两个方案之间的差异工序。
5. THE 候选方案比较区 SHALL 为评分接近的方案（差值 < 5%）显示"评分接近"标识。
6. WHEN Planner 在候选方案比较区选定方案后，THE Decision_Workbench SHALL 在右侧确认执行区同步加载该方案的推荐理由、风险提示和确认操作。
7. THE 候选方案比较区 SHALL 消费 Plan_Selection_Output 中的 comparison_matrix 作为标准数据源，不得由前端重新计算推荐排序。
8. THE 候选方案比较区 SHALL 在候选方案卡片及对比矩阵中明确区分以下状态：评分第一、AI 推荐、自动预选、人工已选择。
9. THE 候选方案比较区 SHALL 支持展示每个候选方案的 Solver_Chain 摘要、主要 trade-off 和执行风险。
10. THE 候选方案比较区 SHALL 支持通过 gantt_diff_payload 渲染差异甘特图，并高亮当前推荐方案与原排程之间的主要变化。
11. WHEN Planner 切换 Goal_Mode 或人工调整权重时，THE 候选方案比较区 SHALL 重新请求 Plan_Selection_Output 并刷新方案排序与推荐状态。

### 需求 13：推荐与确认区（UI）

**用户故事：** 作为计划员，我希望在确认方案前能看到完整的推荐理由，并能进行微调操作，以便我能做出充分知情的决策。

#### 验收标准

1. THE 推荐与确认区 SHALL 展示选定方案的完整推荐理由（核心原因、关键优势、风险权衡点）。
2. THE 推荐与确认区 SHALL 展示选定方案的详细排程甘特图，支持缩放和拖拽查看。
3. THE 推荐与确认区 SHALL 提供"确认采纳"、"微调后采纳"、"返回重选"三个操作按钮。
4. WHEN Planner 选择"微调后采纳"时，THE 推荐与确认区 SHALL 进入编辑模式，允许拖拽调整工序的设备分配和开始时间。
5. WHEN Planner 完成微调并点击确认时，THE 推荐与确认区 SHALL 实时展示约束校验结果，校验通过后启用最终确认按钮。
6. WHEN Planner 否决推荐方案时，THE 推荐与确认区 SHALL 弹出 Override 原因填写对话框，原因为必填项。
7. WHEN 方案被最终确认后，THE 推荐与确认区 SHALL 展示确认成功状态和回写进度。
8. THE 推荐与确认区 SHALL 消费 Plan_Selection_Output 中的推荐理由、风险提示、推荐置信度和备选方案摘要，不得由前端自行拼接推荐逻辑。
9. THE 推荐与确认区 SHALL 明确展示以下信息：推荐方案 ID、推荐置信度、是否自动预选、核心推荐原因、主要风险与权衡点。
10. IF 推荐置信度低于预设阈值，THEN THE 推荐与确认区 SHALL 取消默认自动选中，并提示 Planner 重点比较前两名方案。
11. THE 推荐与确认区 SHALL 支持展示"为什么不是另一个方案"的对比摘要，用于辅助人工 Override 决策。
12. THE 推荐与确认区 SHALL 在桌面端默认作为 Decision_Workbench 右侧确认执行区存在，并与中部候选方案区保持实时联动。

### 需求 14：案例库与模板管理页（UI）

**用户故事：** 作为制造管理层，我希望能浏览和管理历史决策案例与模板，以便我能监督决策质量并推动最佳实践的沉淀。

#### 验收标准

1. THE 案例库页面 SHALL 展示所有历史案例的列表，支持按异常类型、策略类型、时间范围、执行结果筛选。
2. THE 案例库页面 SHALL 为每个案例展示：Incident 摘要、选择的策略、是否 Override、执行结果评分、案例创建时间。
3. WHEN Management 点击某个案例时，THE 案例库页面 SHALL 展示案例的完整详情，包括影响报告、候选方案、决策记录、执行结果。
4. THE 案例库页面 SHALL 提供 CaseTemplate 管理区域，展示所有已发布和草稿状态的模板。
5. WHEN Management 创建或编辑 CaseTemplate 时，THE 案例库页面 SHALL 提供模板编辑表单，包含：模板名称、适用异常类型、推荐策略、关键参数阈值。
6. THE 案例库页面 SHALL 展示每个 CaseTemplate 的使用统计：引用次数、采纳率、平均执行效果评分。
7. THE 案例库页面 SHALL 展示系统级偏好学习统计：AI 推荐采纳率趋势、Override 率趋势、平均响应时间趋势。

### 需求 15：非功能性需求 — 性能

**用户故事：** 作为计划员，我希望系统在异常发生后能快速响应，以便我能在分钟级时间内完成从异常识别到方案确认的全流程。

#### 验收标准

1. WHEN 外部系统发送异常事件，THE Anomaly_Intake_Center SHALL 在 5 秒内完成事件接收和标准化处理。
2. WHEN Incident 被创建后，THE ReOrch_System SHALL 在 20 秒内完成影响范围分析与高层策略选择，并输出首个建议策略路径。
3. WHEN 求解策略被确定后，THE Hybrid_Solver SHALL 在 60 秒内输出 Top-3 候选方案。
4. THE ReOrch_System 的所有 UI 页面 SHALL 在 95 分位响应时间内 2 秒内完成加载。
5. WHILE 系统处于高负载状态（同时处理 10 个以上活跃 Incident），THE ReOrch_System SHALL 维持上述性能指标不降级超过 20%。

### 需求 16：非功能性需求 — 可用性与安全

**用户故事：** 作为 IT 工程师，我希望系统具备高可用性和严格的安全控制，以便满足工业生产环境的稳定性和数据安全要求。

#### 验收标准

1. THE ReOrch_System SHALL 提供 99.9% 的服务可用性（SLA）。
2. THE ReOrch_System SHALL 实施基于角色的访问控制（RBAC），区分 Planner、Shop_Floor_Executor、Management、IT_Admin 四种角色的权限。
3. THE ReOrch_System SHALL 对所有用户操作（登录、方案确认、Override、模板发布）记录审计日志，包含操作人、操作时间、操作内容、操作结果。
4. THE ReOrch_System SHALL 确保工业生产数据在本地环境内处理和存储，禁止未经授权的数据外传。
5. THE ReOrch_System SHALL 对所有外部系统接口（MES、IoT、ERP）使用加密通信（TLS 1.2+）。
6. IF ReOrch_System 的核心服务发生故障，THEN THE ReOrch_System SHALL 在 30 秒内完成故障转移，确保服务连续性。
7. THE ReOrch_System SHALL 提供系统健康监控仪表盘，展示各模块的运行状态、延迟指标、错误率。
8. THE ReOrch_System SHALL 集成 OpenTelemetry 进行分布式链路追踪，支持异常处理全流程的性能分析。

### 需求 17：非功能性需求 — 数据完整性与一致性

**用户故事：** 作为计划员，我希望系统的数据始终保持一致和完整，以便我能信任系统提供的分析结果和方案。

#### 验收标准

1. THE ReOrch_System SHALL 确保 Incident 从创建到关闭的状态流转遵循预定义的状态机（待分析 → 分析中 → 待确认 → 已确认 → 执行中 → 已关闭），禁止非法状态跳转。
2. THE ReOrch_System SHALL 确保每个 DecisionRecord 与其关联的 Incident、CandidatePlan、ExecutionResult 之间的引用完整性。
3. WHEN ScheduleSnapshot 被创建后，THE ReOrch_System SHALL 确保该快照在整个决策流程中保持不可变，任何排程变更不影响已创建的快照。
4. IF 数据库事务在决策流程中失败，THEN THE ReOrch_System SHALL 回滚到一致状态并通知相关用户。
5. THE ReOrch_System SHALL 对所有关键数据实体（Incident、DecisionRecord、CaseTemplate、Plan_Selection_Output、Schedule_Detail、Solver_Chain）维护版本历史，支持审计追溯。

### 需求 18：系统集成与数据接入

**用户故事：** 作为 IT 工程师，我希望系统提供标准化的集成接口，以便能与现有的 MES、ERP、APS 系统对接。

#### 验收标准

1. THE ReOrch_System SHALL 提供 RESTful API 接口供外部系统推送异常事件，API 遵循 OpenAPI 3.0 规范。
2. THE ReOrch_System SHALL 提供 Kafka/Redpanda 消息队列接口作为异常事件的异步接入通道。
3. THE ReOrch_System SHALL 提供 MES 回写适配器接口，支持通过配置适配不同 MES 系统的数据格式。
4. THE ReOrch_System SHALL 提供排程数据导入接口，支持从 APS 系统导入当前排程作为 ScheduleSnapshot。
5. IF 外部系统接口不可用，THEN THE ReOrch_System SHALL 将待发送数据缓存到本地队列，在接口恢复后自动重试（最多 3 次，间隔指数退避）。
6. THE ReOrch_System SHALL 提供集成健康检查端点，监控所有外部系统连接的可用性状态。
7. THE ReOrch_System SHALL 对所有 API 接口实施速率限制和认证鉴权（API Key 或 OAuth 2.0）。

### 需求 19：核心业务度量与 KPI 追踪

**用户故事：** 作为制造管理层，我希望系统能追踪关键业务指标，以便我能量化异常重决策系统的价值。

#### 验收标准

1. THE ReOrch_System SHALL 持续计算并展示以下 KPI：MTTD（平均异常检测时间）、MTTR-D（平均异常决策时间，从异常接入到方案确认）、SPI（排程扰动指数）、关键工单 OTD（准时交付率）、换型次数变化率、AI 推荐采纳率、Override 率、案例复用率。
2. THE ReOrch_System SHALL 提供 KPI 的时间趋势图，支持按日、周、月粒度查看。
3. THE ReOrch_System SHALL 支持 KPI 目标值设定，WHEN 实际值偏离目标值超过 10%，THE ReOrch_System SHALL 生成告警。
4. THE ReOrch_System SHALL 在异常总览台和案例库页面展示关键 KPI 摘要。

### 需求 20：约束校验的正确性保证

**用户故事：** 作为计划员，我希望系统生成的所有候选方案都经过严格的约束校验，以便我能信任方案的可执行性。

#### 验收标准

1. FOR ALL CandidatePlan，THE Hybrid_Solver SHALL 验证所有工序的设备分配满足设备能力约束（工序所需能力 ⊆ 分配设备的能力集合）。
2. FOR ALL CandidatePlan，THE Hybrid_Solver SHALL 验证所有工序的执行顺序满足工艺路线约束（前序工序完成时间 ≤ 后序工序开始时间）。
3. FOR ALL CandidatePlan，THE Hybrid_Solver SHALL 验证同一设备在同一时间段内不存在工序重叠（资源互斥约束）。
4. FOR ALL CandidatePlan，THE Hybrid_Solver SHALL 验证所有工序的物料需求在工序开始时间前可满足（物料可用性约束）。
5. FOR ALL CandidatePlan 中的"局部修复"方案，THE Hybrid_Solver SHALL 验证未受影响的工序保持与 ScheduleSnapshot 中的排程一致（局部修复不变性）。
6. WHEN Planner 对方案进行微调后，THE Hybrid_Solver SHALL 对微调后的完整方案重新执行上述全部约束校验。
7. FOR ALL 约束校验结果，THE Hybrid_Solver SHALL 输出校验报告，列出每条约束的校验状态（通过/违反）和违反详情。

### 需求 21：Incident 数据结构的序列化与反序列化

**用户故事：** 作为 IT 工程师，我希望 Incident 数据能在系统内外可靠地序列化和反序列化，以便数据在不同模块和外部系统间传输时保持完整性。

#### 验收标准

1. THE ReOrch_System SHALL 支持将 Incident 对象序列化为 JSON 格式。
2. THE ReOrch_System SHALL 支持将 JSON 格式的数据反序列化为 Incident 对象。
3. FOR ALL 合法的 Incident 对象，序列化后再反序列化 SHALL 产生与原始对象等价的 Incident 对象（往返一致性）。
4. WHEN 反序列化遇到不合法的 JSON 数据时，THE ReOrch_System SHALL 返回包含具体错误位置和原因的描述性错误。
5. THE ReOrch_System SHALL 对 CandidatePlan、DecisionRecord、CaseTemplate、Plan_Selection_Input、Plan_Selection_Output、Schedule_Detail 和 Solver_Chain 等核心数据实体同样满足上述序列化、反序列化和往返一致性要求。

### 需求 22：求解策略控制层的独立封装

**用户故事：** 作为系统架构师，我希望规则选择器、邻域选择器和修复策略顾问被独立封装为可替换模块，以便系统未来能在不改动核心求解器的前提下持续升级算法能力。

#### 验收标准

1. THE ReOrch_System SHALL 将 Rule_Selector、Neighborhood_Selector、Repair_Policy_Advisor 设计为独立模块，不得将其逻辑硬编码在 Hybrid_Solver 内部流程中。
2. THE Solver_Policy_Layer SHALL 位于 Strategy_Selector 与 Hybrid_Solver 之间，接收高层策略并输出求解控制决策。
3. EACH 模块 SHALL 提供明确的输入输出接口定义，支持单独测试、单独版本管理与单独替换。
4. THE ReOrch_System SHALL 支持通过配置方式指定不同异常场景下所使用的 Rule_Selector、Neighborhood_Selector 和 Repair_Policy_Advisor 实现版本。
5. WHEN 任一策略模块升级时，THE ReOrch_System SHALL 无需修改 Hybrid_Solver 核心代码即可完成集成。
6. THE ReOrch_System SHALL 为每次求解记录所调用的策略模块名称、版本号、关键参数与调用结果。
7. IF 某策略模块调用失败，THEN THE ReOrch_System SHALL 自动切换到预定义的兜底规则版本，并记录降级日志。
8. THE ReOrch_System SHALL 支持对策略模块进行灰度发布、A/B 测试与回滚。
9. THE Solver_Policy_Layer SHALL 维护 Solver_Portfolio，用于管理不同高层策略对应的主求解器、备选求解器和降级规则。
10. THE Solver_Policy_Layer SHALL 保证高层业务策略选择与底层求解执行解耦，使策略模块可持续演进而不影响主求解链路稳定性。

### 需求 23：规则选择器（Rule_Selector）

**用户故事：** 作为系统架构师，我希望系统能独立选择用于初解生成或局部修复的调度规则，以便后续能逐步从规则法升级到学习型策略而不影响主求解流程。

#### 验收标准

1. WHEN Strategy_Selector 输出高层策略后，THE Rule_Selector SHALL 在 3 秒内输出用于该次求解的规则候选列表。
2. THE Rule_Selector SHALL 支持为不同场景选择不同的规则类型，包括但不限于：交期优先、最短加工时间优先、最小松弛时间优先、瓶颈资源优先、关键工单优先。
3. THE Rule_Selector SHALL 接收以下输入：Incident 特征、影响报告、ScheduleSnapshot 摘要、当前高层策略、PreferenceProfile、匹配历史案例。
4. THE Rule_Selector SHALL 输出结构化结果，包含：规则名称、规则类别、适用阶段（初解/修复）、置信度、推荐原因。
5. WHEN 存在与当前场景相似度大于 0.8 的历史案例时，THE Rule_Selector SHALL 将历史案例中成功采用的规则作为参考因素。
6. IF Rule_Selector 的置信度低于 0.5，THEN THE Rule_Selector SHALL 同时输出排名前两位的规则供后续模块选择。
7. THE ReOrch_System SHALL 记录每次规则选择与最终执行效果之间的关联，用于后续规则效果评估与替换。
8. THE Rule_Selector SHALL 支持规则式实现、打分模型实现和学习型实现三种可替换模式。
9. THE Rule_Selector SHALL 输出的规则选择结果必须为结构化数据，不得仅以自然语言说明代替。
10. THE Rule_Selector SHALL 支持通过配置限制某些规则仅在指定车间、指定异常类型或指定策略模式下生效。

### 需求 24：邻域选择器（Neighborhood_Selector）

**用户故事：** 作为系统架构师，我希望系统能独立决定局部搜索和 LNS 的邻域范围与算子类型，以便系统未来能灵活扩展不同搜索策略。

#### 验收标准

1. WHEN Hybrid_Solver 进入局部搜索或 LNS 阶段时，THE Neighborhood_Selector SHALL 输出本轮搜索应使用的邻域算子与作用范围。
2. THE Neighborhood_Selector SHALL 支持以下邻域类别：关键路径邻域、瓶颈设备邻域、延迟工单邻域、同设备交换邻域、工序插入邻域、设备重分配邻域。
3. THE Neighborhood_Selector SHALL 接收以下输入：当前候选解、受影响工序集合、未改善迭代次数、剩余求解预算、当前高层策略、扰动约束。
4. THE Neighborhood_Selector SHALL 输出结构化结果，包含：邻域名称、目标工序集合、邻域强度、预计影响范围、选择理由。
5. WHEN 当前策略为 Local-Repair，THE Neighborhood_Selector SHALL 优先选择受影响工序及其直接下游范围内的局部邻域，禁止默认扩展到全局未受影响区域。
6. WHEN 连续若干轮搜索未产生改进时，THE Neighborhood_Selector SHALL 支持切换到更大范围或不同类型的邻域。
7. IF 当前解已接近求解时间上限，THEN THE Neighborhood_Selector SHALL 优先选择计算开销更低的邻域算子。
8. THE ReOrch_System SHALL 记录每次邻域选择、使用次数、平均改进幅度与最终采纳效果。
9. THE Neighborhood_Selector SHALL 支持规则驱动实现和学习驱动实现的独立替换。
10. FOR Local-Repair 场景，THE Neighborhood_Selector SHALL 支持"不变性保护"，确保未受影响的工序默认不进入邻域搜索范围，除非被显式解冻。

### 需求 25：修复策略顾问（Repair_Policy_Advisor）

**用户故事：** 作为系统架构师，我希望系统能独立决定修复过程中的强度、冻结范围、搜索预算和回退策略，以便系统在不同异常场景下稳定运行并可持续演进。

#### 验收标准

1. WHEN 高层策略被确定后，THE Repair_Policy_Advisor SHALL 输出本次求解的修复策略配置。
2. THE Repair_Policy_Advisor SHALL 至少决定以下内容：修复模式、冻结范围、允许扰动范围、搜索时间预算、候选解数量目标、回退条件。
3. THE Repair_Policy_Advisor SHALL 支持以下修复模式：保守修复、平衡修复、激进修复。
4. WHEN 当前策略为 Wait-and-Repair，THE Repair_Policy_Advisor SHALL 优先采用最小扰动修复配置，并冻结所有未受影响工序。
5. WHEN 当前策略为 Local-Repair，THE Repair_Policy_Advisor SHALL 默认限制修复范围在受影响工序及其直接下游范围内，并设置局部求解预算。
6. WHEN 当前策略为 Global-Reschedule，THE Repair_Policy_Advisor SHALL 允许更大范围的排程调整，并提升求解预算上限。
7. IF 求解过程中检测到连续无改进且时间预算接近上限，THEN THE Repair_Policy_Advisor SHALL 触发回退策略，输出当前最优可行解或切换到兜底求解模式。
8. THE Repair_Policy_Advisor SHALL 输出结构化配置结果，供 Hybrid_Solver 直接消费，不得仅以自然语言方式表达。
9. THE ReOrch_System SHALL 保存每次修复策略配置、实际执行结果与最终 KPI 表现，用于后续策略优化。
10. THE Repair_Policy_Advisor SHALL 支持按车间、异常类型和业务目标模式配置不同默认修复策略模板。

### 需求 26：策略模块的版本治理与实验机制

**用户故事：** 作为 IT 工程师和算法负责人，我希望系统能对规则选择器、邻域选择器和修复策略顾问进行版本治理和实验管理，以便安全上线新算法。

#### 验收标准

1. THE ReOrch_System SHALL 为 Rule_Selector、Neighborhood_Selector、Repair_Policy_Advisor 维护独立版本号。
2. THE ReOrch_System SHALL 记录每个 DecisionRecord 所关联的三个策略模块版本。
3. THE ReOrch_System SHALL 支持为特定车间、特定异常类型或特定用户组启用灰度版本。
4. THE ReOrch_System SHALL 支持对不同策略模块版本进行 A/B 测试，并比较求解时间、可行率、SPI、AI 推荐采纳率、Override 率。
5. IF 新版本策略模块导致可行率下降或 MTTR-D 恶化超过预设阈值，THEN THE ReOrch_System SHALL 自动回滚至上一稳定版本。
6. THE ReOrch_System SHALL 提供策略模块级别的运行监控，展示调用次数、平均耗时、失败率与效果指标。
7. THE ReOrch_System SHALL 支持离线回放历史 Incident，对不同策略模块版本进行效果复盘。
8. THE ReOrch_System SHALL 支持对 Solver_Portfolio 配置进行版本化管理，并记录每次配置变更的审计日志。

### 需求 27：优化结果的甘特图与可执行排程明细输出

**用户故事：** 作为计划员，我希望系统在每次生成候选方案后，能够同时输出甘特图和结构化排程明细，以便我不仅看到方案评分，还能直接理解每个工单、工序、设备的具体排程安排。

#### 验收标准

1. WHEN Hybrid_Solver 生成任一 CandidatePlan，THE ReOrch_System SHALL 同时生成该方案对应的 Gantt_View。
2. THE Gantt_View SHALL 至少展示以下元素：WorkOrder、Operation、分配设备、计划开始时间、计划结束时间、工序状态、关键路径标记。
3. THE Gantt_View SHALL 支持按设备视角、工单视角、时间轴视角切换。
4. WHEN 候选方案与 ScheduleSnapshot 对比时，THE Gantt_View SHALL 以高亮方式标识被重排的工序、设备切换、开始时间偏移和结束时间偏移。
5. THE ReOrch_System SHALL 为每个 CandidatePlan 输出结构化的 Schedule_Detail，包含：工单号、工序号、设备 ID、开始时间、结束时间、前序工序、后续工序、是否受异常影响、是否被调整。
6. WHEN Planner 选择两个方案进行对比时，THE ReOrch_System SHALL 生成差异甘特图，突出显示新增延迟、资源冲突消除、换型次数变化与关键订单路径变化。
7. THE ReOrch_System SHALL 支持将最终确认方案导出为 PDF 与 Excel，其中 PDF 包含甘特图快照，Excel 包含完整排程明细。
8. IF 某方案因数据缺失无法生成完整甘特图，THEN THE ReOrch_System SHALL 明确标注缺失数据项，并仍输出可用部分的排程明细。
9. THE 甘特图渲染 SHALL 支持 500+ 工序场景，且在 95 分位条件下于 3 秒内完成首屏可视化加载。
10. WHEN 最终方案被确认后，THE Writeback_Module SHALL 将最终甘特图版本号与排程明细版本号关联到 DecisionRecord，用于审计追溯。

### 需求 28：方案级求解链路解释与算法出处追踪

**用户故事：** 作为计划员和管理层，我希望系统不仅给出候选方案，还能说明每个方案是通过什么求解链路生成的、为何采用这种算法组合，以便我理解系统的推荐逻辑并建立信任。

#### 验收标准

1. WHEN Hybrid_Solver 输出任一 CandidatePlan，THE ReOrch_System SHALL 记录该方案对应的 Solver_Chain 元数据。
2. THE Solver_Chain 元数据 SHALL 至少包含：高层策略类型、规则选择结果、邻域选择结果、修复策略配置、具体求解器名称、关键参数、求解预算、约束校验结果。
3. THE ReOrch_System SHALL 为每个方案展示"求解链路说明卡"，包含：算法类别、适用场景、采用该链路的原因、主要优化目标、计算耗时。
4. WHEN 当前异常属于 Wait-and-Repair 策略，THE ReOrch_System SHALL 优先展示基于时间偏移修复与约束校验的链路说明。
5. WHEN 当前异常属于 Local-Repair 策略，THE ReOrch_System SHALL 展示局部邻域搜索或 LNS 修复的链路说明，并明确未受影响区域的冻结约束。
6. WHEN 当前异常属于 Global-Reschedule 策略，THE ReOrch_System SHALL 展示全局重排算法说明，并列出全局目标函数与主要约束类别。
7. THE ReOrch_System SHALL 区分"方案生成链路"和"方案排序链路"，不得将排序模型误表述为排程生成算法。
8. IF 某方案由多阶段混合算法生成，THEN THE ReOrch_System SHALL 展示阶段化链路，例如："规则选择 → 初解生成 → 邻域选择 → LNS 修复 → 约束校验 → 多目标排序"。
9. THE Explainability_Layer SHALL 使用 Solver_Chain_Explanation 结构化对象输出求解链路解释，禁止仅以"AI 推荐"作为算法说明。
10. THE DecisionRecord SHALL 保存最终确认方案的完整 Solver_Chain，用于复盘、A/B 测试与后续模型评估。

### 需求 29：方案推荐引擎（Plan_Recommendation_Engine）

**用户故事：** 作为计划员，我希望系统能在多个候选方案中自动给出最值得优先考虑的推荐方案，并说明为什么推荐该方案，以便我能在高压场景下更快做出高质量决策。

#### 验收标准

1. WHEN Evaluation_Center 完成候选方案评分后，THE Plan_Recommendation_Engine SHALL 在 5 秒内输出推荐方案。
2. THE Plan_Recommendation_Engine SHALL 基于以下输入进行推荐：候选方案评分结果、Goal_Mode、PreferenceProfile、相似历史案例、执行约束、风险提示和人工微调参数。
3. THE Plan_Recommendation_Engine SHALL 对所有候选方案执行推荐前筛选，剔除不满足硬约束、执行约束或关键业务门槛的方案。
4. THE Plan_Recommendation_Engine SHALL 对剩余候选方案进行推荐排序，并输出 1 个推荐方案和至少 1 个备选方案。
5. THE Plan_Recommendation_Engine SHALL 区分"综合评分第一"和"最终 AI 推荐"两个概念，允许在历史偏好、执行稳定性或风险约束影响下，推荐结果不同于纯评分第一方案。
6. THE Plan_Recommendation_Engine SHALL 输出 Recommendation_Confidence，取值范围为 0–1。
7. WHEN Recommendation_Confidence 大于等于预设阈值且推荐方案无高风险执行告警时，THE Plan_Recommendation_Engine SHALL 支持对该方案执行 Auto_Preselection。
8. IF Recommendation_Confidence 小于 0.5，THEN THE Plan_Recommendation_Engine SHALL 不执行自动预选，并同时输出前两名候选方案供 Planner 人工选择。
9. THE Plan_Recommendation_Engine SHALL 输出结构化推荐理由，包含：推荐方案 ID、核心推荐原因、相对优势、主要风险、与备选方案的关键差异。
10. THE Plan_Recommendation_Engine SHALL 将推荐使用的 Goal_Mode、权重参数、历史案例引用、偏好画像摘要和约束条件写入 DecisionRecord，用于后续审计和复盘。
11. THE Plan_Recommendation_Engine SHALL 在推荐结果中显式输出备选方案集合，并至少包含 alternative_plan_ids[]。
12. THE ReOrch_System SHALL 支持按车间、异常类型和业务目标模式配置 Recommendation_Confidence 阈值、Auto_Preselection 阈值和高风险执行告警阈值，并对阈值变更进行审计记录。

### 需求 30：方案选择输入输出对象（Plan_Selection_Input / Plan_Selection_Output）

**用户故事：** 作为系统架构师，我希望方案推荐过程使用统一的输入输出对象，以便后端模块解耦、前端展示一致、审计追踪完整。

#### 验收标准

1. THE ReOrch_System SHALL 定义统一的 Plan_Selection_Input 数据结构，作为 Plan_Recommendation_Engine 的标准输入。
2. THE Plan_Selection_Input SHALL 至少包含以下字段：incident_id、incident_type、severity、schedule_snapshot_id、candidate_plans[]、goal_mode、preference_profile、historical_case_matches[]、manual_weights、execution_constraints。
3. FOR ALL candidate_plans[] in Plan_Selection_Input，THE ReOrch_System SHALL 确保每个候选方案至少包含：plan_id、strategy_type、kpi_vector、schedule_detail、gantt_version、solver_chain、feasibility_status。
4. THE ReOrch_System SHALL 定义统一的 Plan_Selection_Output 数据结构，作为 Plan_Recommendation_Engine 的标准输出。
5. THE Plan_Selection_Output SHALL 至少包含以下字段：recommended_plan_id、recommended_rank、top_scored_plan_id、recommendation_confidence、auto_preselected、ranked_plan_list[]、reason_codes[]、reason_summary、risk_flags[]、comparison_matrix、gantt_diff_payload、goal_mode_used、weights_used、matched_case_ids[]、audit_metadata。
6. THE ReOrch_System SHALL 确保 Plan_Selection_Output 可直接供前端候选方案比较区与推荐与确认区消费，无需前端拼装推荐逻辑。
7. THE Plan_Selection_Output SHALL 明确区分以下对象：推荐方案、备选方案、纯评分排序结果、人工最终确认方案。
8. IF 前端调整了 Goal_Mode 或人工微调权重，THEN THE ReOrch_System SHALL 重新生成 Plan_Selection_Output，并更新推荐方案与对比矩阵。
9. THE ReOrch_System SHALL 为 Plan_Selection_Input 与 Plan_Selection_Output 提供 JSON 序列化与反序列化能力，并满足往返一致性要求。
10. THE DecisionRecord SHALL 关联完整版本的 Plan_Selection_Input 和 Plan_Selection_Output，用于事后复盘与模型评估。
11. FOR ALL manual_weights，THE ReOrch_System SHALL 校验其取值范围、总和约束和默认值回退机制；当输入不合法时，系统 SHALL 返回结构化错误并保持上一有效权重配置。
12. THE Plan_Selection_Output SHALL 显式包含 alternative_plan_ids[]，用于标识推荐方案之外的备选方案集合。
13. THE ReOrch_System SHALL 为 comparison_matrix 和 ranked_plan_list[] 中的评分字段输出统一的尺度说明、单位说明和归一化依据，以支持前端一致渲染和解释。

### 需求 31：工作台式前端布局与原型对齐约束

**用户故事：** 作为产品经理和计划员，我希望前端页面严格围绕异常重决策工作流设计为工作台式界面，并尽量对齐 BP 原型中的关键信息布局，以便在高压场景下减少跳转和信息分散。

#### 验收标准

1. THE ReOrch_System SHALL 将异常处理主流程设计为 Decision_Workbench，而非仅由多个独立 CRUD 页面拼接实现。
2. THE Decision_Workbench SHALL 至少包含以下五个同屏区块：异常事件列表区、当前处理状态区、影响范围分析区、候选方案比较区、人工确认执行区。
3. THE Decision_Workbench SHALL 支持在同一界面中完成以下操作：查看异常详情、查看影响报告、比较候选方案、查看推荐理由、调整目标模式、确认执行方案。
4. THE 候选方案比较区 SHALL 与人工确认执行区保持联动，WHEN Planner 切换候选方案时，THE 推荐理由、风险提示、甘特图差异和确认按钮状态 SHALL 同步刷新。
5. THE Decision_Workbench SHALL 在 Multi_Plan_Selection_View 中支持左侧展示 Goal_Mode 配置区，在中部展示候选方案卡片区，在右侧展示推荐理由与确认区；在 Incident_Analysis_View 中，左侧应优先展示异常事件列表区。
6. THE Decision_Workbench SHALL 支持展示历史案例参考、偏好画像摘要和人工微调参数，且这些元素不得被完全隐藏在二级页面之后。
7. THE ReOrch_System SHALL 保证关键决策路径中的核心信息同屏可见，包括：当前异常、推荐方案、推荐理由、主要 trade-off、确认入口。
8. THE ReOrch_System SHALL 避免将"方案比较"和"方案确认"拆分为超过 2 次页面跳转；关键推荐信息不得仅存在于弹窗深层级中。
9. THE ReOrch_System SHALL 为工作台布局提供响应式适配，但在桌面端默认使用多区块同屏布局，不得退化为串行信息流页面。
10. THE ReOrch_System SHALL 将需求 10–13 定义的前端页面解释为对 Decision_Workbench 的逻辑视图划分，而非彼此完全割裂的独立产品模块。
11. THE Decision_Workbench SHALL 支持至少两种主工作状态：(a) Incident_Analysis_View：用于异常队列查看、影响分析和初步策略判断；(b) Multi_Plan_Selection_View：用于目标模式切换、候选方案比较、推荐理由查看和确认执行。两种主工作状态应共享同一 Incident 上下文，并允许在不丢失上下文的前提下切换。

## 补充说明

为确保异常重决策流程在高压制造场景下具备可执行性、可解释性与可操作性，系统 SHALL 将"候选方案评分""推荐方案确定""人工确认执行"定义为三个独立但连续的决策步骤，并通过统一的 Plan_Selection_Input / Output 对象和 Decision_Workbench 工作台布局实现后端解耦、前端联动与全过程审计追踪。

### 职责边界说明

为避免评分、推荐、解释三个模块职责重叠，系统 SHALL 明确区分以下职责：

- **Evaluation_Center** 负责候选方案的多目标评分、归一化和排序，不直接决定最终推荐方案；
- **Plan_Recommendation_Engine** 负责基于评分结果、业务目标模式、偏好画像、历史案例和执行约束确定最终推荐方案与备选方案；
- **Explainability_Layer** 负责生成推荐解释（Recommendation_Explanation）与求解链路解释（Solver_Chain_Explanation），不负责评分或推荐决策本身。

前端 SHALL 同时区分"评分第一""AI 推荐""自动预选""人工最终确认"四种状态，不得将其混为同一个标签。

### 原型对齐说明

需求 10–13 所定义的前端界面 SHALL 以 Decision_Workbench 为统一交互容器，优先采用与 BP 原型一致的工作台式布局：

- 左侧为异常事件列表与目标模式配置区；
- 中部为影响分析与候选方案比较区；
- 右侧为推荐理由、人工微调与确认执行区。

在桌面端，关键决策信息 SHOULD 优先同屏呈现；在移动端或窄屏模式下，可退化为分步视图，但不得丢失 Incident 上下文与推荐链路信息。
