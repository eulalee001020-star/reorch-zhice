# 服务领域 AI 竞品与标杆能力分析

## 1. 定位

本页用于补充服务领域 AI 产品的方向级 benchmark，重点不是做供应商排名，而是从公开产品资料中提炼可迁移的产品机制：知识 grounding、人机协同、工单闭环、SLA 风险、质检复盘和上线指标。

ReOrch 的主场景仍是工业异常调度。本页只说明其底层产品方法如何迁移到服务 AI，不声明已经交付客服、工单或质检生产系统。

## 2. 公开产品参照

| 产品或方向 | 核心能力 | 可借鉴点 | ReOrch 可迁移能力 |
| --- | --- | --- | --- |
| AI 客服 Copilot | 回复建议、知识引用、会话摘要、转人工、坐席工作台内辅助 | AI 嵌入坐席工作流，由坐席确认后对外回复 | Human Confirmation、Evidence Stack、Audit Record |
| 自助服务 AI Agent | 基于知识库和业务数据自动回答常见问题，低置信或复杂问题升级人工 | 自动化与人工接管要共用同一套上下文和升级规则 | Guardrail、Fallback、Controlled Action |
| 智能工单 Agent | 分类、字段补全、优先级判断、派单建议、SLA 风险识别 | 工单不是单次问答，而是状态流转、责任分派和结果闭环 | Agent Workflow、State Machine、Data Readiness |
| 服务质检 Agent | 会话分析、风险标注、复核队列、失败样本沉淀 | 质检价值来自原因归类和持续改进，不只是一条打分结果 | Failure Case Library、Metric System、Case Memory |
| 客户成功 Copilot | 客户上下文汇总、风险提示、下一步动作建议、跟进记录 | AI 输出应绑定 CRM/服务数据和人工跟进动作 | Evidence Center、Planner Adoption、Outcome Log |

## 3. 代表性公开资料

| 参照 | 可提炼的产品机制 |
| --- | --- |
| [Zendesk Copilot](https://support.zendesk.com/hc/en-us/articles/5524125586330-About-Zendesk-Copilot) | 面向坐席的回复建议、知识和宏命令辅助，强调嵌入客服工作台 |
| [Intercom Fin AI Agent](https://www.intercom.com/help/en/articles/7837535-fin-ai-agent-faqs) | 基于支持内容和数据回答问题，并在需要时进入升级或接管流程 |
| [Salesforce Agentforce Service](https://help.salesforce.com/s/articleView?id=service.bots_service_asa_about.htm&language=en_US&type=5) | 面向服务场景的 AI Agent，强调服务任务和客户交互处理 |
| [ServiceNow SLA](https://www.servicenow.com/products/itsm/what-is-sla.html) | 服务流程需要围绕承诺、状态、责任和时限管理，不只是文本生成 |

## 4. 对 ReOrch 的迁移结论

| 服务 AI 设计问题 | ReOrch 的对应做法 |
| --- | --- |
| AI 如何避免脱离业务上下文 | 先通过 Data Readiness Gate 检查数据完整性，再进入 Agent workflow |
| AI 如何给出可采纳输出 | 输出绑定 source refs、KPI、quality gate 和人工检查项 |
| AI 如何处理低置信或缺数据 | 显式 fallback，不生成强建议，不越权执行 |
| 如何证明上线后有效 | 采集 adoption、fallback、blocked、rejected、audit completeness 等事件和指标 |
| 如何持续迭代 | 把驳回、override、失败样本和结果反馈沉淀到 Case Memory |

## 5. 产品判断

服务领域 AI 的趋势不是把大模型放在入口处自由聊天，而是把 AI 嵌入客服、工单、质检和客户成功的既有工作流：低风险动作可自动化，高风险动作必须有证据、权限、降级和人工确认。ReOrch 作品集体现的核心能力正是这套可迁移的 AI 产品框架。
