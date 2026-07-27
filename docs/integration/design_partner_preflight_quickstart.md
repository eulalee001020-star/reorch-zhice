# Design Partner 数据与证据预检 Runbook

## 当前边界

这套流程用于把真实车间合作从“有兴趣”推进到可审计的 historical replay 或 read-only shadow。它不证明生产 ROI，也不授权生产写回。

当前工程状态是 `replay-ready`：客户数据通过 mapping、DataGate 和治理门后，可以立刻开始历史回放；只有补足现场案例、约束确认和工作流证据后，才进入只读 shadow。

## 合作方需要安排的角色

| 角色 | 必须确认的内容 |
| --- | --- |
| 生产负责人 | 试点车间、异常类型、业务损失和停止条件 |
| 计划员 | 当前决策流程、隐性规则、采纳/微调/驳回原因 |
| MES/APS/ERP 负责人 | 权威数据源、字段 mapping、ID crosswalk、导出方式 |
| 质量/工艺/仓储负责人 | 质量、物料、工装和放行硬约束 |
| IT/安全 | 数据使用、保留、访问控制、部署和删除范围 |
| 财务或经营负责人 | 延期、换线、加班和人工时间成本口径 |

缺少生产负责人、计划员或数据负责人中的任何一方，不应承诺进入 shadow。

## 客户数据包

```text
customer_pack/
├── work_orders.csv              # 或 erp_work_orders.csv
├── operations.csv               # 或 mes_operations.csv
├── machines.csv                 # 或 aps_resources.csv
├── incidents.csv                # 或 mes_downtime_events.csv
├── mapping_profile.json         # 必须由客户数据负责人确认
└── preflight_metadata.json      # 来源、授权、约束、案例、ROI 和工作流引用
```

`preflight_metadata.json` 中使用客户代号，不写客户全称。证据引用可以是受控目录路径、文档编号或客户工单编号；每项审批必须包含审批角色、证据引用和带时区的审批时间。预检只验证这些材料是否提交，不替代独立审计。

## 第一次运行：生成 mapping 草案

```bash
python tools/run_design_partner_preflight.py \
  --pack-dir /absolute/path/to/customer_pack
```

如果没有 `mapping_profile.json`，命令返回退出码 `2`，并生成：

```text
preflight_output/mapping_profile.draft.json
preflight_output/mapping_suggestions.json
```

草案不能直接用于 replay。客户 MES/APS/ERP 负责人确认字段、ID crosswalk、时区和权威来源后，才能保存为 `mapping_profile.json`。

如果缺少 `preflight_metadata.json`，命令会生成 `preflight_metadata.template.json` 并停止。

## 第二次运行：生成试点证据包

```bash
python tools/run_design_partner_preflight.py \
  --pack-dir /absolute/path/to/customer_pack \
  --output-dir /absolute/path/to/preflight_output
```

输出：

| 文件 | 用途 |
| --- | --- |
| `input_manifest.json` | 输入文件大小和 SHA-256，固定本次评估数据版本 |
| `data_fingerprint.txt` | canonical 数据指纹 |
| `design_partner_preflight.json` | 机器可读的 stage、证据门、ROI 和壁垒覆盖 |
| `design_partner_preflight.md` | 客户评审和项目周会报告 |

默认报告不复制原始车间行数据。只有在客户批准的隔离环境内，才使用 `--include-canonical-data` 生成 `canonical_dataset.private.json`。

退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 已达到 `replay_ready` 或 `shadow_ready` |
| `2` | 文件、metadata 或 mapping 合同不完整 |
| `3` | DataGate 或核心治理证据阻断，只能修复数据 |

## 当前硬门

| Stage | 必须满足 | 允许动作 |
| --- | --- | --- |
| `data_repair` | mapping、数据来源或核心授权仍有 blocker | 字段修复、mapping 复核、治理补证 |
| `replay_ready` | DataGate 允许 replay；数据使用、历史回放、保留和安全审批均有引用 | 历史 replay、离线 ROI baseline、Sandbox 指令预览 |
| `shadow_ready` | DataGate 允许 shadow；至少 10 个历史异常、5 个可审计案例、80% 约束确认、全部 hard constraint 确认、只读 shadow 授权和核心工作流证据 | 只读 shadow、计划员反馈采集 |

这些数量是当前工程门槛，不是跨行业通用结论。进入项目后可提高门槛，但不能绕过 mapping、授权、hard constraint 和审计要求。

## ROI 证据等级

| 等级 | 可以说什么 | 不能说什么 |
| --- | --- | --- |
| `none` | 尚未形成 ROI 证据 | 不能给客户收益数字 |
| `replay_counterfactual` | 历史回放中的反事实估算 | 不能称为已实现节约 |
| `shadow_observed` | 决策时间和计划员行为的观察结果 | 运营收益仍是估算 |
| `execution_measured` | 有执行结果引用的案例级实测 | 未经财务确认不能称正式 ROI |
| `finance_validated_execution` | 财务确认的案例级 ROI | 不能外推到未观察异常、其他车间或其他客户 |

ROI 台账必须逐异常保留 baseline、ReOrch 输出、计划员决定和执行结果引用。不能用平均假设覆盖缺失数据，也不能把 synthetic replay 写成客户 ROI。

所有差值都保留正负号，ReOrch 结果变差时必须显示负收益。`roi_ratio` 使用净 ROI 公式：`(执行实测收益 - PoC 成本) / PoC 成本`，不是收益/成本倍数。

## 10 个工作日启动顺序

| 时间 | 交付物 | Go/No-Go |
| --- | --- | --- |
| Day 0-1 | 试点范围、数据使用/保留/安全审批、客户代号 | 未签范围则停止取数 |
| Day 1-2 | CSV 样例、mapping 草案、ID crosswalk | mapping 未确认则不 replay |
| Day 3 | DataGate、输入 manifest、数据指纹 | blocker > 0 则回到修复 |
| Day 4-6 | 首批历史异常 replay、约束访谈和引用台账 | hard constraint 未确认则不 shadow |
| Day 7-8 | 计划员逐案采纳/微调/驳回评审 | 无决策引用则不算采纳证据 |
| Day 9 | ROI baseline 和成本口径评审 | 无执行闭环则只标 replay estimate |
| Day 10 | Stage 评审和下一阶段 SOW | 生产写回保持关闭 |

## 壁垒沉淀规则

- 客户私有资产：mapping profile、Recovery Policy Graph、现场约束、案例和执行反馈，只服务该客户并形成续费与迁移成本。
- 可跨客户复用：不含客户标识的异常类型、Recovery Operator、约束模板、adapter 模板、部署和验收方法。
- 原始数据、客户规则和客户案例默认不得跨客户共享。
- “证据覆盖分”只表示材料完整度，不表示算法效果、商业价值或市场壁垒已经形成。

## 数据接口 Agent 的当前实现

当前的数据接入流程可以作为一个受控 Data Interface Agent 使用，但 Agent 只负责协调，不拥有事实决定权：

1. 读取客户 CSV/JSON 样例并生成字段 mapping 建议。
2. 在 mapping 未经客户确认时停止，不把猜测字段送入求解器。
3. 使用确定性 schema、枚举、时区、唯一 ID 和引用完整性校验构建 canonical dataset。
4. 将不合格数据降级到 `data_repair`，输出具体修复任务。
5. 对输入文件和 canonical 数据生成指纹，固定 replay 的数据版本。
6. 只把通过治理门的数据交给 historical replay 或 read-only shadow。

Agent 不允许补造缺失生产事实、自动批准 mapping、修改硬约束、越权调用 MES 或把客户数据复制到其他客户。

## 找到合作方后仍需现场完成的工程项

以下内容无法在没有客户系统和数据时预先声称完成：

- ERP/MES/APS 的厂商版本、API/数据库/文件协议和真实字段 mapping。
- 客户网络、证书、密钥托管、IP 白名单和单点登录。
- 客户数据量下的吞吐、延迟、断点续传、增量同步和故障恢复压测。
- 客户侧监控、备份、日志保留、灾备和运维责任人。
- Sandbox endpoint 的幂等、超时、错误码、补偿和回滚合同测试。
- 真实计划员工作流、约束 owner、审批矩阵和执行结果闭环。

因此“合作后马上投入使用”的准确含义是：首批数据在 mapping 和治理通过后可立即进入历史 replay；不是拿到数据当天直接连接生产 MES 并自动执行。

## 写回边界

方案确认不会自动触碰 MES。当前只支持：

1. 生成 Sandbox dry-run 指令预览。
2. 在 API Key 强制开启、不同人员二次审批、Sandbox endpoint、短时签名许可和稳定 idempotency key 均满足时，进行受控 Sandbox 合同测试。
3. 生产写回和无人值守执行在代码层保持禁止。

详细规则见 [writeback_safety_protocol.md](writeback_safety_protocol.md)。
