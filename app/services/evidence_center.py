"""Evidence Center aggregation service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.evidence import EvidenceCenterResponse, EvidenceItem, EvidenceTable
from app.models.planning import (
    ChangeoverRuleInput,
    InitialScheduleRequest,
    PlanningMaterialRequirementInput,
    PlanningOperationInput,
    PlanningResourceInput,
    PlanningWorkOrderInput,
)
from app.services.data_readiness import DataReadinessService
from app.services.ngs_lab import NgsProtectedPortfolioService


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = REPO_ROOT / "docs" / "validation"


class EvidenceCenterService:
    """Build a reviewable evidence set from replay, docs, and live checks."""

    def build(self) -> EvidenceCenterResponse:
        items = [
            self._lab_replay_item(),
            self._failure_case_item(),
            self._llm_eval_item(),
            self._data_readiness_item(),
            self._quality_gate_item(),
            self._ci_validation_item(),
        ]
        return EvidenceCenterResponse(
            items=items,
            summary_counts=_summary_counts(items),
        )

    def _lab_replay_item(self) -> EvidenceItem:
        path = VALIDATION_DIR / "lab_replay_acceptance_evidence.md"
        markdown = _read_text(path)
        table = _extract_first_table_after(markdown, "Replay 样本表")
        metric_table = _extract_first_table_after(markdown, "初始样本统计")
        metrics = {
            row.get("指标", ""): row.get("当前样本", "")
            for row in (metric_table.rows if metric_table else [])
        }
        return EvidenceItem(
            evidence_id="lab_replay_acceptance",
            category="replay",
            title="实验室 replay 采纳/微调/驳回样本",
            status="controlled_replay",
            summary="记录受控实验室 replay 的采纳、微调、驳回和 ROI 纳入口径。",
            source_path=_rel(path),
            source_refs=["docs:lab_replay_acceptance_evidence"],
            metrics=metrics,
            table=table,
            limitations=[
                "不是客户生产现场采纳率。",
                "后续必须替换为客户只读历史异常 replay。",
            ],
        )

    def _failure_case_item(self) -> EvidenceItem:
        path = VALIDATION_DIR / "failure_case_library.md"
        markdown = _read_text(path)
        return EvidenceItem(
            evidence_id="failure_case_library",
            category="failure_samples",
            title="失败样本库",
            status="controlled_failure_set",
            summary="展示系统不推荐、不写回、退回人工和归因闭环的失败样本。",
            source_path=_rel(path),
            source_refs=["docs:failure_case_library"],
            table=_extract_first_table_after(markdown, "## 样本"),
            limitations=[
                "样本来自受控验证和 replay。",
                "不代表真实生产失败分布。",
            ],
        )

    def _llm_eval_item(self) -> EvidenceItem:
        path = VALIDATION_DIR / "llm_agent_offline_eval.md"
        markdown = _read_text(path)
        metric_table = _extract_first_table_after(markdown, "当前本地 baseline 结果")
        metrics = {
            row.get("指标", ""): row.get("结果", "")
            for row in (metric_table.rows if metric_table else [])
        }
        return EvidenceItem(
            evidence_id="llm_agent_offline_eval",
            category="llm_eval",
            title="LLM Agent 离线评测",
            status="fallback_baseline_available",
            summary="记录 Incident、Rule Candidate、Feedback Agent 的离线评测口径和 fallback baseline。",
            source_path=_rel(path),
            source_refs=["benchmark:scripts/run_llm_agent_offline_eval.py"],
            metrics=metrics,
            table=metric_table,
            limitations=[
                "未配置真实 LLM 时只能证明确定性兜底链路。",
                "真实模型效果需补 token、延迟、schema valid rate 和成本。",
            ],
        )

    def _data_readiness_item(self) -> EvidenceItem:
        ready = DataReadinessService().assess_initial_schedule_request(
            _readiness_sample_request(include_qc=True)
        )
        blocked = DataReadinessService().assess_initial_schedule_request(
            _readiness_sample_request(include_qc=False)
        )
        return EvidenceItem(
            evidence_id="data_readiness_sample",
            category="data_readiness",
            title="Data Readiness 样本评估",
            status="live_check",
            summary="用可运行样本和缺字段样本验证停损逻辑是否可见。",
            source_path="app/services/data_readiness.py",
            source_refs=["api:/api/v1/planning/readiness/initial-schedule"],
            metrics={
                "ready_score": ready.readiness_score,
                "ready_blockers": len(ready.blockers),
                "blocked_score": blocked.readiness_score,
                "blocked_blockers": len(blocked.blockers),
            },
            table=EvidenceTable(
                columns=["sample", "is_ready", "readiness_score", "blockers", "warnings"],
                rows=[
                    {
                        "sample": "ready",
                        "is_ready": str(ready.is_ready),
                        "readiness_score": str(ready.readiness_score),
                        "blockers": str(len(ready.blockers)),
                        "warnings": str(len(ready.warnings)),
                    },
                    {
                        "sample": "blocked",
                        "is_ready": str(blocked.is_ready),
                        "readiness_score": str(blocked.readiness_score),
                        "blockers": str(len(blocked.blockers)),
                        "warnings": str(len(blocked.warnings)),
                    },
                ],
            ),
            limitations=[
                "这是内置样本评估，不等于客户字段质量。",
                "客户试点必须接入真实只读数据后重跑。",
            ],
        )

    def _quality_gate_item(self) -> EvidenceItem:
        batch = NgsProtectedPortfolioService().run_batch_replay()
        rows = []
        for result in batch.case_results:
            recommended = result.response.recommended_candidate
            rows.append(
                {
                    "case_id": result.case_id,
                    "pass_replay": str(result.pass_replay),
                    "recommended": recommended.strategy_type if recommended else "-",
                    "feasible": str(len(result.response.feasible_candidates)),
                    "rejected": str(len(result.response.rejected_candidates)),
                    "failures": "; ".join(result.failure_reasons) or "-",
                }
            )
        return EvidenceItem(
            evidence_id="ngs_quality_gate_batch",
            category="quality_gate",
            title="NGS batch replay 质量门结果",
            status="live_batch_replay",
            summary="从 NGS 实验包读取多 case batch replay，验证 hard gate 过滤和推荐策略。",
            source_path=batch.source_path,
            source_refs=["api:/api/v1/ngs-lab/batch-replay"],
            metrics=batch.aggregate_metrics,
            table=EvidenceTable(
                columns=["case_id", "pass_replay", "recommended", "feasible", "rejected", "failures"],
                rows=rows,
            ),
            limitations=[
                "实验包是公开安全 synthetic replay。",
                "LIMS / run log / QC / reagent log 真实只读接入后需替换。",
            ],
        )

    def _ci_validation_item(self) -> EvidenceItem:
        path = VALIDATION_DIR / "ci_validation_summary.md"
        markdown = _read_text(path)
        return EvidenceItem(
            evidence_id="ci_quality_gate_summary",
            category="quality_gate",
            title="工程质量门与 CI 验证摘要",
            status="ci_success_snapshot",
            summary="记录后端测试、前端构建和 Compose smoke 的内部验证基线。",
            source_path=_rel(path),
            source_refs=["docs:ci_validation_summary"],
            table=_extract_first_table_after(markdown, "Test Results"),
            limitations=[
                "该摘要是文档中的 CI 快照。",
                "本地当前分支仍需运行最新测试确认。",
            ],
        )


def _readiness_sample_request(*, include_qc: bool) -> InitialScheduleRequest:
    start = datetime(2026, 5, 12, 8, 0, tzinfo=timezone.utc)
    resources = [
        PlanningResourceInput(
            resource_id="CNC-01",
            name="CNC bottleneck",
            capabilities=["milling", "drilling"],
            is_bottleneck=True,
            criticality="bottleneck",
            cost_per_minute=6,
        )
    ]
    if include_qc:
        resources.append(
            PlanningResourceInput(
                resource_id="QC-01",
                name="CMM Inspection",
                capabilities=["inspection"],
                criticality="quality_gate",
                cost_per_minute=5,
            )
        )
    return InitialScheduleRequest(
        workshop_id="WS-HMLV-01",
        planning_start=start,
        resources=resources,
        resource_calendar=[],
        changeover_rules=[
            ChangeoverRuleInput(
                from_product_family="A",
                to_product_family="B",
                setup_minutes=20,
                cost=500,
            )
        ],
        goal_modes=["balanced"],
        max_solutions=3,
        time_budget_seconds=6,
        work_orders=[
            PlanningWorkOrderInput(
                work_order_id="WO-DR-001",
                product_name="Urgent valve block",
                product_family="A",
                priority=4,
                due_date=start + timedelta(hours=8),
                operations=[
                    PlanningOperationInput(
                        operation_id="WO-DR-001-10",
                        work_order_id="WO-DR-001",
                        duration_minutes=120,
                        eligible_resource_ids=["CNC-01"],
                        required_capabilities=["milling"],
                        product_family="A",
                        material_requirements=[
                            PlanningMaterialRequirementInput(
                                material_id="AL-7075",
                                required_quantity=1,
                                available_at=start,
                                status="available",
                            )
                        ],
                    ),
                    PlanningOperationInput(
                        operation_id="WO-DR-001-20",
                        work_order_id="WO-DR-001",
                        duration_minutes=45,
                        eligible_resource_ids=["QC-01"],
                        required_capabilities=["inspection"],
                        predecessor_ids=["WO-DR-001-10"],
                        product_family="A",
                    ),
                ],
            )
        ],
    )


def _extract_first_table_after(markdown: str, heading: str) -> EvidenceTable | None:
    lines = markdown.splitlines()
    start_index = next(
        (index for index, line in enumerate(lines) if heading in line),
        -1,
    )
    if start_index < 0:
        return None
    table_lines: list[str] = []
    collecting = False
    for line in lines[start_index + 1 :]:
        if line.strip().startswith("|"):
            collecting = True
            table_lines.append(line)
            continue
        if collecting:
            break
    if len(table_lines) < 2:
        return None
    header = _split_table_row(table_lines[0])
    rows = []
    for line in table_lines[2:]:
        cells = _split_table_row(line)
        if len(cells) != len(header):
            break
        rows.append(dict(zip(header, cells)))
    return EvidenceTable(columns=header, rows=rows)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _summary_counts(items: list[EvidenceItem]) -> dict:
    by_category: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for item in items:
        by_category[item.category] = by_category.get(item.category, 0) + 1
        by_status[item.status] = by_status.get(item.status, 0) + 1
    return {
        "total": len(items),
        "by_category": by_category,
        "by_status": by_status,
    }
