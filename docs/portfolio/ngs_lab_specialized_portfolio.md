# ReOrch NGS 实验室特化版

本文档不是要把 ReOrch 从通用异常调度系统改成只服务 NGS 实验室的单点工具，而是在保留原有通用异常决策架构的前提下，给出一个更有行业质感、更贴近实际研究场景的垂直版本：面向 NGS 实验室工作流的受控修复排程 Copilot。

这一版的依据来自 `ngs_lrsp_manuscript_package_20260527.zip` 中的 NGS-LRSP 论文，以及本地 `ngs_grouped_l2r_experiment_package` 中的数字孪生和 neutral benchmark 证据。结论需要保持保守：这些数据是 synthetic / digital-twin-style benchmark，不是医院或商业 LIMS 的真实导出，也不是生产部署证明。

## 1. 双层定位

ReOrch 的通用层仍然成立：它是一个面向高约束流程的异常响应与决策编排系统。制造车间版本处理设备、工单、工序、资源、交期和回写；NGS 实验室版本处理样本、实体链、实验步骤、仪器、试剂、pool/run、QC、报告 TAT 和实验室审计。

| 层级 | 保留什么 | NGS 版本替换什么 |
| --- | --- | --- |
| 通用产品内核 | Incident、ScheduleSnapshot、Operation、Resource、CandidatePlan、QualityGate、DecisionRecord | 领域对象、约束集合、异常类型、评价指标和解释语言 |
| 通用决策链路 | 异常接入 -> 影响分析 -> Top-K 候选 -> 质量门 -> 推荐解释 -> 人工确认 -> 回写/执行 -> 案例沉淀 | NGS-LRSP 的 feasibility-first repair workflow |
| 通用 AI 边界 | AI 负责理解、解释、规则候选、案例和偏好，不直接越权求解 | AI 不直接决定实验排程，只辅助约束提取、异常理解、解释和案例沉淀 |
| 通用商业边界 | 不替代 ERP/MES/APS/LIMS 主系统 | 不替代 LIMS、ELN、仪器控制软件或临床质量体系 |

这意味着项目定位不应停留在“异常调度 demo”，而应明确为：

> ReOrch 是一套可复用的高约束异常决策架构。NGS 实验室特化版说明它如何被领域化：在试剂、QC、hold-time、pool/run、traceability 和 frozen-zone 这些硬约束下，先恢复可执行性，再讨论优化。

## 2. NGS 实验室实际问题

NGS 实验室的排程不是普通 FJSP。一个样本会经过 sample、extract、library、normalized library、pool、sequencing run、FASTQ、analysis、report 等实体转换。每一步都可能有 QC gate、试剂 lot、开封稳定期、最大等待时间、仪器/人员/计算资源、污染分区、index 兼容和报告时限。

在真实实验室语境中，计划被打断通常不是单一“设备坏了”：

| 异常 | 典型影响 | 为什么不能只靠普通优先级规则 |
| --- | --- | --- |
| STAT / urgent clinical sample 插入 | TAT 风险、下游 pool/run 重组 | 需要判断是否打断已有批次、是否影响 index 和 run capacity |
| QC fail / borderline | 返工、复测、override、下游 chain 阻塞 | QC route 必须可追溯，不能直接把失败样本推进下游 |
| RNA / single-cell 稳定性压力 | hold-time 或 max-wait 逼近 | 不能只看交期，生物稳定窗口是硬约束 |
| 试剂 lot 不足、过期或开封超窗 | lot substitution、采购、延期 | 试剂有效性不能用 tardiness 罚分抵消 |
| Sequencer downtime / low-yield run | pool/run 重新组合、报告延迟 | 已开始或冻结的 run 不能被静默移动 |
| Bioinformatics pipeline failure | compute queue、重跑、报告签发延迟 | 计算与 review 也是实验室 TAT 的一部分 |
| Operator absence / calendar change | hands-on step 延迟 | 需要同时看人员授权、仪器日历和实验窗口 |

因此，NGS 特化版的第一切口不应写成泛泛的“实验室排程优化”，而应写成：

> 当 NGS 实验室出现 urgent sample、QC failure、reagent / hold-time risk、sequencer downtime 或 bioinformatics delay 时，帮助实验室计划员在不破坏硬约束和可追溯性的前提下生成可执行修复方案。

## 3. 从 ReOrch 到 NGS-LRSP 的对象映射

| ReOrch 通用对象 | NGS 特化对象 | 说明 |
| --- | --- | --- |
| Incident | DynamicEvent / LabIncident | urgent insertion、QC fail、downtime、reagent event、pipeline failure |
| WorkOrder | Sample / Case / Report commitment | 样本或临床 case 的最终 TAT 承诺 |
| Operation | Lab operation | receipt、extraction、QC、library prep、normalization、pooling、sequencing、analysis、review、report |
| Resource | Instrument / operator / compute | sequencer、QC instrument、automation station、operator pool、compute threads |
| Material | Reagent lot / index / flow-cell proxy | lot 兼容性、数量、expiry、open-stability、index uniqueness |
| Route | Multi-entity DAG | sample -> extract -> library -> pool -> run -> FASTQ -> analysis -> report |
| Due date | TAT / report due time | 普通样本、urgent clinical、STAT 样本权重不同 |
| Quality gate | Protected feasibility gate | 试剂、hold-time、QC route、pool/run、traceability、frozen-zone |
| CandidatePlan | Protected repair candidate | 只在 hard-feasible 后进入 soft-score 比较 |
| DecisionRecord | Lab decision audit | 记录 rescue action、override、风险提示和人工确认 |

NGS 版本的关键不是换一套名词，而是把“质量门”从普通排程可行性升级成实验室可执行性：试剂过期、traceability 断链、index 冲突、QC 路由错误、冻结区被移动，都不是“较差方案”，而是不可执行方案。

## 4. 产品形态

### 4.1 NGS Lab Repair Scheduling Copilot

建议对外命名为：

> ReOrch for NGS Lab Scheduling
> NGS 实验室异常修复排程 Copilot

它不替代 LIMS 或仪器软件，而是接在 LIMS / ELN / sequencer run logs / bioinformatics job logs 之上，做异常发生后的决策层。

### 4.2 核心用户

| 用户 | 关心的问题 |
| --- | --- |
| Lab manager | 今天是否能按 TAT 交付，哪些 urgent case 有风险 |
| Workflow coordinator | 插单、返工、downtime 后怎么重排 |
| Sequencing specialist | pool/run 是否可行，index/run capacity 是否安全 |
| Bioinformatics lead | pipeline queue 和 report review 是否成为瓶颈 |
| QA / compliance reviewer | 决策是否可追溯，是否破坏 QC 和 traceability |

### 4.3 典型工作流

```text
LIMS / run log / QC event / reagent event
-> NGS Incident Intake
-> Snapshot Compiler
-> Feasibility Gate Audit
-> Impact Analysis: sample / entity / pool / run / report TAT
-> Protected Repair Portfolio
-> Top-K feasible repair candidates
-> NGS-specific explanation and rescue burden
-> Lab planner confirmation
-> LIMS writeback preview / execution instruction / audit package
-> Case memory and threshold calibration
```

## 5. NGS 特化版 Agent 设计

| Agent | 输入 | 输出 | 能力边界 |
| --- | --- | --- | --- |
| NGS Incident Agent | QC note、instrument downtime、urgent sample、reagent event、pipeline failure | 标准化 LabIncident、影响实体、可观测时间点 | 低置信或 future information 不进入自动求解 |
| Constraint Evidence Agent | LIMS fields、reagent lot、pool/run、QC route、resource calendar | hard gate evidence、缺失字段、不可执行原因 | 不用自然语言替代结构化 source refs |
| Protected Portfolio Agent | snapshot、incident、hard gates、repair permissions | 可行候选集合、被拒候选原因、rescue actions | 不把 infeasible candidate 推给计划员 |
| Explanation Agent | Top-K KPI、hard gate report、rescue burden | 为什么可执行、为什么不选其他方案、哪些风险仍需人工确认 | 解释只能基于结构化证据 |
| Case Memory Agent | 采纳/驳回、override、执行反馈 | 可复盘案例、规则候选、阈值校准样本 | 单个案例不能自动升级成硬规则 |
| Preference Learning Agent | 多次 planner decision | 不同场景下的排序偏好和警戒阈值 | 只做排序辅助，不覆盖 hard feasibility |

## 6. 质量门

NGS 特化版要把质量门写得比制造版更硬，因为实验室场景里的不可执行风险通常不是成本问题，而是样本、质量和审计风险。

| Gate | 必须检查 |
| --- | --- |
| Reference closure | sample、extract、library、pool、run、analysis、report 链路闭合 |
| Precedence / DAG | 下游步骤不能早于上游步骤，依赖图不能有环 |
| QC route safety | fail、borderline、repeat、override 的路径合法 |
| Reagent validity | lot 兼容、数量、expiry、open-stability |
| Hold-time / max-wait | extraction-to-library、library-to-pool 等稳定窗口 |
| Pool / run feasibility | pool capacity、run capacity、read demand、lane/run grouping |
| Index compatibility | pool 内 index 唯一和兼容 |
| Resource calendar | 仪器、人员、compute queue、downtime、absence |
| Frozen-zone protection | 已开始、已承诺、临近执行窗口不能被静默移动 |
| Zone compatibility | pre-PCR/post-PCR、amplicon contamination 相关分区 |
| Traceability audit | 每个 repair action 能追溯到实体、事件和人工确认 |

产品默认策略：

- `block`：任何 hard gate 失败，不能推荐为可执行方案。
- `warning`：可执行但 rescue burden 高、扰动大、TAT 风险残留，需要人工确认。
- `pass`：硬约束通过，但仍不自动写回 LIMS。

## 7. 候选方案和推荐逻辑

论文里的关键思想可以直接转成产品逻辑：不是先追求最小 tardiness，而是先恢复可执行性。

| 候选类型 | 产品含义 |
| --- | --- |
| Dispatching candidate | EDD、urgent-first、weighted due 等快速基线，用来解释普通规则为什么不够 |
| Reagent repair candidate | lot substitution、procurement、expiry/open-stability rescue |
| Calendar / hold-time rescue | 同时处理人员/仪器窗口和生物稳定性 |
| Event-local repair | 只对已观测异常附近的局部子图做修复 |
| RHP-ALNS candidate | 在 frozen / repair / flexible zone 内做 rolling-horizon destroy-repair |
| Stage-first workload redistribution | 针对长周期 neutral workload 的 stage-aware 平衡候选 |
| Full rescue diagnostic | 作为上界或 emergency comparator，不作为主要卖点 |

推荐层按以下顺序排序：

```text
hard feasibility
-> protected risk
-> weighted / urgent tardiness
-> rescue burden
-> schedule stability
-> planner preference
```

这比“算法推荐最优方案”更可信，因为它解释的是可执行性、风险和责任边界。

## 8. 已有实验数据能支撑什么

来自 `ngs_grouped_l2r_experiment_package` 的证据可以支撑“研究级产品原型”的可信度：

| 证据 | 当前数据 |
| --- | --- |
| 内部 digital-twin-style 场景 | 18 个场景，覆盖 routine、clinical urgent、RNA perishability、amplicon contamination、sequencer capacity、disrupted reactive |
| 内部样本和流程规模 | 1782 个 samples、30285 个 operations、13110 个 entities、318 个 pools、318 个 sequencing runs |
| 中性 synthetic benchmark | LAB_A--F 六类场景：Routine Mixed、High Throughput、Urgent Clinical Insertions、RNA Stability Pressure、Low Diversity Amplicon、Downtime And Rework |
| neutral benchmark 结构有效性 | 686 samples、11225 operation events、11145 dependencies、80 pools、80 sequencing runs、119 reagent lots |
| 普通规则失败证据 | fixed-lot EDD executable rate = 0，平均 hard gate violations = 1384.79 |
| 单一 rescue 不足 | procurement rescue EDD executable rate = 0，平均 hard gate violations = 900.75 |
| RHP-ALNS | feasible rate = 1.0，mean hard violations = 0，mean WT = 2.313e6 |
| stage-first augmented portfolio | final portfolio feasible rate = 1.0，mean hard violations = 0，mean WT 从 2.313e6 降至约 9.50e5 |

这些证据说明：NGS 特化版不是只替换了一套行业名词，而是把具体论文里的研究问题转成了产品版本、数据模型、质量门、可验证工作流和能力边界。

但必须明确：这些不是生产 ROI，不是客户真实采纳率，也不是临床上线证据。

## 9. NGS 版本的首期 MVP

为了避免再次变成“大而全实验室平台”，NGS 特化版的首期可以收敛为：

> NGS 实验室 urgent / QC / reagent / downtime 事件触发后，生成 hard-feasible 的修复候选方案，并解释 TAT 风险、rescue burden 和不可执行候选被拒原因。

### P0 输入

| 数据 | 最低要求 |
| --- | --- |
| samples | sample_id、arrival、assay、priority、due_time、risk_class |
| operations | stage、duration、eligible resource、release/due、qc_gate、frozen_flag |
| dependencies | predecessor、successor、min_lag、max_lag |
| resources | instrument/operator/compute、capacity、calendar、downtime |
| reagents | lot、compatible assay、quantity、expiry、open-stability |
| pools / runs | pool membership、index、run capacity、read demand |
| events | urgent insertion、QC fail、downtime、absence、reagent shortage、pipeline failure |

### P0 输出

| 输出 | 产品价值 |
| --- | --- |
| Impact report | 哪些 sample/entity/pool/run/report TAT 受影响 |
| Top-K repair candidates | 展示 dispatch baseline、reagent/run rescue、event-local repair、stage-first redistribution 等可比较路径 |
| Hard gate report | 哪些方案被拒，为什么不可执行 |
| Rescue burden | 采购、换 lot、延长日历、hold-time rescue、移动 operation 的代价 |
| Recommendation explanation | 为什么推荐这个方案，残留风险是什么 |
| Audit package | 计划员确认、override、source refs、回写预览和复盘案例 |

## 10. 系统结构

ReOrch 采用“双版本架构”：

```text
ReOrch Core
  通用高约束异常决策内核
  适用于制造、实验室、供应链等需要安全修复决策的场景

ReOrch Manufacturing
  当前可互动 demo
  瓶颈设备故障 -> 影响分析 -> Top-K -> 质量门 -> 人工确认

ReOrch NGS Lab
  论文驱动的垂直特化版
  NGS-LRSP -> protected repair portfolio -> hard feasibility first
```

这样既保留了广泛应用潜力，又避免“什么都做”的不可信。项目形成两层能力：

- 抽象能力：能把不同高约束业务抽象成通用决策架构。
- 落地能力：能用 NGS 这种具体、复杂、约束密集的场景做垂直化重构。

### 10.1 当前已接入的 P0 系统能力

| 能力 | 当前实现 |
| --- | --- |
| NGS domain adapter | `app/models/ngs.py` 定义 samples、entities、operations、resources、reagents、pools、runs、events、gate report、repair candidate、agent trace |
| Protected hard gate | `app/services/ngs_lab.py` 检查 reference closure、DAG、QC route、reagent、hold-time、pool/run、index、resource calendar、frozen-zone、zone compatibility、traceability |
| Protected portfolio | 同一服务生成 dispatch baseline、reagent/run rescue、event-local repair、stage-first redistribution，并只让 hard-feasible 候选进入 soft-score 排序 |
| NGS API | `POST /api/v1/ngs-lab/demo-run` 返回 impact report、feasible candidates、rejected candidates、recommended candidate、audit package 和 agent trace |
| 前端入口 | `NGS Lab` 页面直接调用 API，展示 Top-K 可执行候选、被拒候选、质量门、影响范围、审计状态和 Agent trace |
| 回写边界 | 当前只输出 LIMS writeback preview / audit package 语义，不执行自动回写 |

## 11. 不应宣称的内容

| 不应宣称 | 更准确表达 |
| --- | --- |
| 已在真实 NGS 实验室生产上线 | 基于 NGS-LRSP 论文和 synthetic benchmark 的特化原型设计 |
| 能替代 LIMS / ELN / sequencer software | 作为异常修复排程和审计决策层，读取并回写主系统 |
| RHP-ALNS 是全局最优求解器 | RHP-ALNS 是 protected portfolio 内的候选生成组件 |
| stage-first 一定适合所有 NGS 场景 | 目前在 LAB_A--F neutral synthetic scenarios 改善明显，仍需外部 replay |
| 合成 benchmark 等同真实客户数据 | 合成数据可支撑算法和产品结构验证，客户现场仍需 shadow replay |

## 12. 后续验证路线

1. 用现有实验包生成一个公开安全的 miniature demo dataset，不直接把本地完整实验包公开进作品集。
2. 将更多 LAB_A--F synthetic scenarios 接入 `demo-run` 或批量 replay 脚本，检查不同异常组合下的 hard gate 覆盖。
3. 增加 near-real lab shadow replay：只读接入 LIMS / run log / QC / reagent log，不自动写回。
4. 记录 lab planner 对 Top-K 候选的采纳、微调、驳回和原因，区分数据问题、约束问题、模型问题和流程问题。
5. 在 controlled dry-run 中验证 audit package、回写预览、人工确认和回滚流程。

## 13. 最终判断

NGS 特化版显著增强了 ReOrch 的专业深度。制造版本证明系统能跑端到端异常决策 demo；NGS 版本证明同一套异常决策内核可以迁移到论文级、高约束、强审计的实验室场景。在真实高风险场景里，AI 产品的核心不是“更自由地自动决策”，而是把语义理解、候选生成、质量门、解释、审计和人工责任组织成一个可验证闭环。

准确定位不是“ReOrch 现在要转型做 NGS”，而是：

> ReOrch 是一个通用高约束异常决策内核。制造调度是第一个可互动 demo，NGS 实验室是一个基于论文和实验数据重构的深度垂直版本，用来说明该内核如何迁移到更严苛的科学实验工作流。
