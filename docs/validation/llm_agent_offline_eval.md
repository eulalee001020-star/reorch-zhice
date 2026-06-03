# LLM Agent 离线评测

## 当前实现状态

ReOrch 现在不再只能说“外部 LLM 调用为 0”。更准确的状态是：

- 默认 demo：外部 LLM 调用关闭，保证本地可复现、低成本、可控。
- 可配置真实 LLM Agent：`Incident Agent`、`Rule Candidate Agent`、`Feedback Agent` 已接入 OpenAI-compatible JSON 调用路径。
- 仍不使用 LLM 的模块：影响分析、候选方案生成、质量门、推荐排序、人工确认和回写。

配置方式：

```bash
export LLM_ENABLED=true
export LLM_API_KEY=...
export LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
export LLM_MODEL=your-small-agent-model
```

离线评测命令：

```bash
python benchmark/scripts/run_llm_agent_offline_eval.py
```

## 评测任务

| Agent | 任务 | 指标 | 失败处理 |
| --- | --- | --- | --- |
| Incident Agent | 异常文本 -> 结构化 Incident | incident type accuracy、resource accuracy、duration accuracy | 低置信或不支持类型进入人工确认 |
| Rule Candidate Agent | 计划员规则 -> pending constraint candidate | constraint type accuracy、scope completeness、human-review pass rate | 不发布硬规则，只进入人工审核 |
| Feedback Agent | override 文本 -> 驳回原因和候选规则 | reason accuracy、future rule usefulness | 单个反馈不能修改求解器 |

## 种子数据集

当前脚本内置 10 条种子样本：

| 类型 | 数量 |
| --- | --- |
| Incident understanding | 4 |
| Rule candidate | 3 |
| Feedback structuring | 3 |

这只是最小评测集。进入公开使用或客户试点前，应扩展到至少 50 条：

- 20 条异常理解。
- 15 条规则候选。
- 15 条计划员 override / 驳回原因。

## 结果口径

在未配置真实 LLM 时，脚本输出的是确定性 fallback baseline，`llm_call_count = 0`。这不能证明真实 LLM 增量，只能证明评测框架和兜底链路可运行。

当前本地 baseline 结果：

| 指标 | 结果 |
| --- | --- |
| incident type accuracy | 1.0000 |
| incident resource accuracy | 1.0000 |
| rule candidate type accuracy | 1.0000 |
| feedback reason accuracy | 1.0000 |
| llm_call_count | 0 |
| input_tokens / output_tokens | 0 / 0 |
| avg_llm_latency_ms | 0 |

解释：这组结果来自确定性 fallback 的小样本种子集，只能证明当前样本下兜底链路稳定，不能作为真实 LLM 效果结论。

配置真实模型后，结果应补齐：

| 指标 | 最低可接受线 |
| --- | --- |
| incident type accuracy | >= 90% |
| resource extraction accuracy | >= 85% |
| rule candidate type accuracy | >= 80% |
| feedback reason accuracy | >= 80% |
| schema valid rate | 100% |
| source_refs coverage | 100% |
| P95 latency | <= 3 秒 |
| 单次 Agent 成本 | 按供应商 token 价格记录，不使用估算替代 |

## PM 结论

这个评测补的是“AI 产品性”的证据，而不是把排程责任交给模型。只要 LLM 输出不能通过 schema、source refs、质量门和人工确认，就不能影响生产计划。
