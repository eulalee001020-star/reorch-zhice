# Demo 截图说明

这些截图来自本地运行的 ReOrch demo，用于快速展示产品界面和核心闭环。截图证明的是 sandbox / demo 级交互路径，不代表客户生产系统已上线。

| 文件 | 内容 |
| --- | --- |
| `00-online-demo.png` | 独立在线 Demo 的异常队列、Top-K 候选、证据、质量门与人工确认首屏 |
| `01-login.png` | 登录与角色入口 |
| `02-decision-workbench.png` | 异常恢复决策层、影响分析、证据等级和计划员确认 |
| `03-plan-comparison.png` | 恢复策略组合、质量门、KPI 对比和甘特图 |
| `04-evidence-center.png` | Evidence Ladder、受控 replay、失败样本、离线评测和数据就绪证据 |
| `05-data-readiness.png` | DataGate 权限阶梯、readiness 检查和停损规则 |
| `06-ngs-lab.png` | NGS Lab replay、hard gate、候选修复方案和实验室审计边界 |

`00-online-demo.png` 来自独立作品集 Demo 的 1200 x 818 浏览器视口。其余截图来自完整本地栈：

```text
Backend: uvicorn app.main:app --host 127.0.0.1 --port 8000
Frontend: npm run dev -- --host 127.0.0.1 --port 3000
Browser: Playwright, 1440 x 980 viewport
```
