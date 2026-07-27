# P0 Ulster MES Pack

Source: https://mdep.smdh.uk/en/dataset/ulster-university--manufacturing-operations-dataset

The publisher describes this as anonymized MES data covering product cycles,
operation durations, order due-date performance, and stoppages. The dataset is
licensed for non-commercial use.

At build time the official host did not resolve and the backing object store
required an expiring signed URL. No synthetic replacement has been inserted.
The pack therefore remains `acquisition_blocked` and fails the strict monitor.

Expected files under `raw/`:

- `product_cycle_anonymised.csv`
- `df_unit_level_cycle_downtime_anonymised.csv`
- `order_analysis_anonymised.csv`
- `stoppage_all_anonymised.csv`
- `Manufacturing Operations Documentation.pdf`

## Available fallback layers

`surrogate_sample/` starts from the existing local MES-shaped sample and adds
one explicitly labeled synthetic operation plus one explicitly labeled
synthetic downtime event to reach the required test shape:

- 3 work orders;
- 7 operations;
- 5 resources;
- 2 downtime events.

The original checked-in sample contains 6 operation records and 1 downtime
record. The added rows carry `provenance=synthetic_extension_to_required_shape`;
they are not presented as source MES records.

`digital_twin/` deterministically expands that small sample with seed
`20260713` into:

- 10,000 synthetic operations;
- 300 synthetic incidents;
- 10,000 synthetic CDC events;
- 10,000 synthetic terminal MES receipts.

This expansion is suitable for engineering stability, throughput, CDC ordering,
idempotency, checkpoint/restart, and receipt-state-machine tests. It is not real
anonymized MES data and cannot establish real Shadow, real ROI, customer
production reliability, or production writeback authorization.

## 缺失项与门禁结论

**仍然缺失**

- Ulster 官方 5 个脱敏 MES 原始文件仍全部缺失，状态继续为
  `acquisition_blocked`。
- 当前数字孪生由 3 工单、7 工序、5 资源、2 停机事件的小样本确定性扩展而来。
- 尚不能证明真实 MES 字段兼容、真实异常分布、真实计划员采纳、2–4 周
  Shadow、真实 ROI 或生产写回可靠性。

**门禁结果**

公开数据包验证结果是“4 个完整包通过，Ulster MES 严格门禁失败”。这不是
系统故障，而是正确的来源门禁：

| 门禁 | 结果 |
| --- | --- |
| 数字孪生工程一致性 | 通过 |
| 官方脱敏 MES 来源 | 失败 |
| 真实 MES 验证 | `false` |
| 真实 Shadow | `false` |
| 2–4 周真实 Shadow | `false` |
| 真实 ROI | `false` |
| 生产写回授权 | `false` |

## 客户准入材料排练包

`customer_admission_rehearsal/` 基于现有小样本生成了30条合成历史异常案例，
并配套 MES 数据字典、计划员采纳/微调/拒绝结果、执行终态回执、异常前快照
hash 和 source refs。

它用于验证真实客户数据到达后的映射、回放、证据关联和门禁流程。所有记录
均标注 `synthetic_customer_admission_rehearsal`；真实客户案例数仍为0，不能
据此声称完成真实客户 replay、计划员采纳验证、2–4周 Shadow 或真实 ROI。
