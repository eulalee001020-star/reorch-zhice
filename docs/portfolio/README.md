# AI 产品作品集文档架构

本目录用于展示 ReOrch 智策的产品判断、AI 适用性、系统设计、工程落地、可信性控制、评测证据和商业价值。文档组织目标不是罗列功能，而是证明一个 AI 产品从问题定义到受控验证的完整决策链路。

## 1. 主线材料

| 文档 | 证明重点 |
| --- | --- |
| [product_portfolio.md](product_portfolio.md) | 项目总览：真实问题、用户场景、为什么使用 AI、方案设计、评测与结果 |
| [project_capability_evidence.md](project_capability_evidence.md) | 项目能力证据、适用边界和后续迭代说明 |

## 2. 系统设计材料

| 文档 | 证明重点 |
| --- | --- |
| [workflow_prompts_io.md](workflow_prompts_io.md) | Agent/Workflow 设计、Prompt 结构、输入输出示例和人机协作边界 |
| [trust_quality_gate.md](trust_quality_gate.md) | LLM 输出可信性、硬约束、质量门、置信度、审计和兜底机制 |

## 3. 验证与状态材料

| 文档 | 证明重点 |
| --- | --- |
| [project_status_assessment.md](project_status_assessment.md) | 当前 MVP 状态、成本控制、商业化价值、上线边界和后续计划 |
| [../validation/digital_twin_validation_pack.md](../validation/digital_twin_validation_pack.md) | 数字孪生验证证据：source refs、成本代理、replay/shadow 代理、阈值和审计包 |

## 4. 市场与演示材料

| 文档 | 证明重点 |
| --- | --- |
| [market_benchmark.md](market_benchmark.md) | 市场需求、行业对标、竞争格局、试点路径和商业假设 |
| [../demo/customer_demo_walkthrough.md](../demo/customer_demo_walkthrough.md) | 可互动 demo 的演示路径和操作流程 |

## 推荐阅读路径

```text
product_portfolio.md
-> project_capability_evidence.md
-> workflow_prompts_io.md
-> trust_quality_gate.md
-> project_status_assessment.md
-> ../validation/digital_twin_validation_pack.md
-> market_benchmark.md
-> ../demo/customer_demo_walkthrough.md
```
