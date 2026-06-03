# Demo 截图说明

这些截图来自本地运行的 ReOrch demo，用于快速展示产品界面和核心闭环。截图证明的是 sandbox / demo 级交互路径，不代表客户生产系统已上线。

| 文件 | 内容 |
| --- | --- |
| `01-login.png` | 登录与角色入口 |
| `02-decision-workbench.png` | 异常决策工作台、影响分析、Agent 调用链和推荐确认 |
| `03-plan-comparison.png` | Top-K 候选方案、质量门、KPI 对比和甘特图 |
| `04-evidence-center.png` | 证据中心、replay、失败样本、LLM eval、data readiness 和 CI 证据 |
| `05-data-readiness.png` | 数据就绪检查、缺字段阻断和停损规则 |
| `06-ngs-lab.png` | NGS Lab replay、hard gate、候选修复方案和实验室审计边界 |

截图生成环境：

```text
Backend: uvicorn app.main:app --host 127.0.0.1 --port 8000
Frontend: npm run dev -- --host 127.0.0.1 --port 3000
Browser: Playwright, 1440 x 980 viewport
```
