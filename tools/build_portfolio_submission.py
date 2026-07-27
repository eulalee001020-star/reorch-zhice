from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ARTIFACTS = ROOT / "portfolio_artifacts"
BUILD = DIST / "portfolio_submission_20260727"
PACKAGE = BUILD / "ReOrch_Zhice_AI_Portfolio_20260727"
DOCX_PATH = DIST / "ReOrch_智策_AI产品作品集_20260727.docx"
PDF_PATH = DIST / "ReOrch_智策_AI产品作品集_20260727.pdf"
ZIP_PATH = DIST / "ReOrch_智策_AI作品集材料包_20260727.zip"
SCREENSHOT = ROOT / "docs/assets/screenshots/00-online-demo.png"

CN_FONT = "Arial Unicode MS"
LATIN_FONT = "Calibri"
PDF_FONT = "PortfolioCJK"
BLUE = RGBColor(46, 116, 181)
DARK_BLUE = RGBColor(31, 77, 120)
BLACK = RGBColor(25, 31, 29)
MUTED = RGBColor(91, 101, 96)
GREEN = RGBColor(23, 107, 77)
LIGHT_FILL = "F2F4F7"
GREEN_FILL = "E2F1E9"
TABLE_WIDTH_DXA = 9360


POSITIONING = (
    "ReOrch 智策是位于 ERP / MES / APS 之上的工业异常恢复决策 Copilot。"
    "它不替代主系统，也不让大模型直接排产；系统把设备停机、急单、缺料和质量返工后的"
    "临场协调重构为可验证、可降级、可审计的人机协同决策闭环。"
)

WORKFLOW_OLD = "看系统与报表 -> 电话/群聊补信息 -> Excel 人工试排 -> 临场协调 -> 结果难追溯"
WORKFLOW_NEW = (
    "数据健康门 -> 影响子图 -> 约束可行 Top-K -> AI 证据解释 -> 质量门 -> "
    "人工确认 -> 受控执行草案 -> 结果与失败复盘"
)

AI_ROWS = [
    ["异常理解", "结构化自然语言与事件上下文，标记缺失信息", "schema、来源、时效与权限决定数据能否进入求解"],
    ["方案生成", "不直接生成生产排程", "SSGS、CP-SAT、分解和 anytime hybrid 生成并验证候选"],
    ["方案解释", "基于证据解释差异、风险和需要确认的事项", "KPI、硬约束与 feasibility certificate 不由 LLM 判断"],
    ["规则演进", "从 override 与失败样本提出规则候选", "review、replay、publish 状态机决定规则是否生效"],
    ["执行控制", "不连接生产写回", "双审批、短时 permit、幂等、sandbox certification 与审计控制"],
    ["异常降级", "说明不确定性与缺失证据", "超时、冲突、漂移或权限不足时 fail closed"],
]

EVIDENCE_ROWS = [
    ["自动化测试", "872 项", "领域模型、API、Agent、求解、质量门、审批、回写策略与运行时"],
    ["生产运行时数字孪生", "10 / 10 gates passed", "shadow、schema drift、OIDC/RBAC、备份恢复与观测路径"],
    ["集成控制面", "8 / 8 checks passed", "Connector 注册、版本、认证、隔离和失败关闭"],
    ["回写认证演练", "15 / 15 checks passed", "双审批、幂等、dry-run、回滚与审计；客户认证仍为 false"],
    ["三行业合成回放", "CNC / LED Fab / PCBA", "证据结构、ROI proxy、PoC 前检和 replay 方法"],
    ["可行性恢复", "writeback_authorized=false", "冲突诊断、受控约束放宽、Recovery Operator 与证书"],
]

FAILURE_ROWS = [
    ["数据缺失仍输出强建议", "Prompt 只约束格式，没有独立准入门", "增加 Data Health Gate、字段合同、source refs 与停止规则"],
    ["Proxy 被表述为生产事实", "事实、推断与建议未分层", "schema 增加 evidence type、confidence 与 uncertainty"],
    ["召回过期公告或案例", "检索命中与证据有效性混在同一步", "增加时效、版本和 source authority 校验"],
    ["规则候选被误认为已生效", "生成与发布状态未隔离", "建立 draft、review、replay、publish 生命周期"],
    ["不可行排程只返回失败", "缺少业务可执行的恢复路径", "增加冲突诊断、Recovery Operator、审批与 certificate"],
]

DELIVERY_ROWS = [
    ["行业调研", "市场/先进标准对标、金蝶定位、服务 AI 竞品迁移", "确定异常响应层切口与竞合边界"],
    ["用户需求", "计划员、生产、质检、设备、IT 角色与原/新流程", "把隐性经验转化为对象、状态、权限和决策节点"],
    ["PRD / 原型", "用户故事、页面流、异常态、权限、埋点、验收、互动 Demo", "形成研发可执行与可感知的产品定义"],
    ["项目推进", "需求、评审、研发、联调、灰度、风险、责任人与阶段门", "用 MVP delivery plan 管理交付节奏"],
    ["上线指标", "时效、Top-K 可行覆盖、采纳、业务代理、稳定性与风险", "区分模型、方案、产品、业务和治理指标"],
    ["创新输入", "Agent + solver + guardrail + human-in-the-loop Harness", "让概率型 AI 与确定性系统共同承担可审计闭环"],
]

BOUNDARIES = [
    "真实 Design Partner 案例数为 0，尚无客户生产数据、现场采纳率或财务确认 ROI。",
    "公开结果来自自动化测试、公开来源数据、合成回放与数字孪生演练。",
    "生产自动写回默认关闭；客户 Sandbox、权限、回滚、安全和现场验收必须独立完成。",
    "LLM 不负责生产事实、硬约束、排程可行性或最终执行责任。",
]


def set_run_font(
    run,
    size: float | None = None,
    bold: bool | None = None,
    color: RGBColor | None = None,
    italic: bool | None = None,
) -> None:
    run.font.name = LATIN_FONT
    run._element.rPr.rFonts.set(qn("w:ascii"), LATIN_FONT)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), LATIN_FONT)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
    run._element.rPr.rFonts.set(qn("w:cs"), CN_FONT)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color
    if italic is not None:
        run.italic = italic


def set_cell_margins(cell) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", 80), ("bottom", 80), ("start", 120), ("end", 120)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_cell_width(cell, width_dxa: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.first_child_found_in("w:tcW")
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width_dxa))
    tc_w.set(qn("w:type"), "dxa")


def shade_cell(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.first_child_found_in("w:shd")
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_text(cell, text: str, *, bold: bool = False, color: RGBColor | None = None) -> None:
    set_cell_margins(cell)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.08
    run = paragraph.add_run(text)
    set_run_font(run, size=9.2, bold=bold, color=color)


def add_field(paragraph, field: str) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = field
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instruction, separate, end])


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Inches(0.78)
    section.bottom_margin = Inches(0.72)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.32)
    section.footer_distance = Inches(0.32)

    normal = doc.styles["Normal"]
    normal.font.name = LATIN_FONT
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
    normal.font.size = Pt(11)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.10

    doc.settings.odd_and_even_pages_header_footer = False

    def populate_footer(footer) -> None:
        paragraph = footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        set_run_font(paragraph.add_run("ReOrch 智策  |  Page "), size=8.5, color=MUTED)
        add_field(paragraph, "PAGE")

    populate_footer(section.footer)


def add_title_block(doc: Document) -> None:
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(8)

    title = doc.add_paragraph()
    title.paragraph_format.space_after = Pt(4)
    set_run_font(title.add_run("ReOrch 智策"), size=27, bold=True, color=BLACK)

    subtitle = doc.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(14)
    set_run_font(subtitle.add_run("工业异常恢复决策 Copilot"), size=15, color=DARK_BLUE)

    metadata = [
        ("项目类型", "AI Native 产品 / Agent Workflow / 工业决策辅助"),
        ("产品状态", "MVP 已完成；replay-ready；生产写回默认关闭"),
        ("公开证据", "872 项自动化测试 + 合成回放 + 数字孪生 gates"),
        ("更新日期", "2026-07-27"),
        ("公开仓库", "github.com/eulalee001020-star/reorch-zhice"),
    ]
    for label, value in metadata:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(2)
        set_run_font(paragraph.add_run(f"{label}："), size=10.5, bold=True, color=BLACK)
        set_run_font(paragraph.add_run(value), size=10.5, color=BLACK)

    rule = doc.add_paragraph()
    rule.paragraph_format.space_before = Pt(8)
    rule.paragraph_format.space_after = Pt(12)
    p_pr = rule._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "14")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "176B4D")
    borders.append(bottom)
    p_pr.append(borders)

    callout = doc.add_table(rows=1, cols=1)
    callout.autofit = False
    set_cell_width(callout.cell(0, 0), TABLE_WIDTH_DXA)
    shade_cell(callout.cell(0, 0), GREEN_FILL)
    set_cell_text(callout.cell(0, 0), POSITIONING, bold=True, color=GREEN)
    doc.add_paragraph()


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.keep_with_next = True
    if level == 1:
        paragraph.paragraph_format.space_before = Pt(16)
        paragraph.paragraph_format.space_after = Pt(8)
        size, color = 16, BLUE
    elif level == 2:
        paragraph.paragraph_format.space_before = Pt(12)
        paragraph.paragraph_format.space_after = Pt(6)
        size, color = 13, BLUE
    else:
        paragraph.paragraph_format.space_before = Pt(8)
        paragraph.paragraph_format.space_after = Pt(4)
        size, color = 12, DARK_BLUE
    set_run_font(paragraph.add_run(text), size=size, bold=True, color=color)


def add_paragraph(doc: Document, text: str, *, bold_lead: str | None = None) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(6)
    paragraph.paragraph_format.line_spacing = 1.10
    if bold_lead and text.startswith(bold_lead):
        set_run_font(paragraph.add_run(bold_lead), size=11, bold=True, color=BLACK)
        set_run_font(paragraph.add_run(text[len(bold_lead) :]), size=11, color=BLACK)
    else:
        set_run_font(paragraph.add_run(text), size=11, color=BLACK)


def add_bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.left_indent = Inches(0.5)
        paragraph.paragraph_format.first_line_indent = Inches(-0.25)
        paragraph.paragraph_format.space_after = Pt(8)
        paragraph.paragraph_format.line_spacing = 1.167
        set_run_font(paragraph.add_run("• "), size=10.5, bold=True, color=GREEN)
        set_run_font(paragraph.add_run(item), size=10.5, color=BLACK)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], widths: list[int]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = False
    table.alignment = 0
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        set_cell_width(cell, widths[index])
        shade_cell(cell, LIGHT_FILL)
        set_cell_text(cell, header, bold=True, color=DARK_BLUE)
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            set_cell_width(cells[index], widths[index])
            set_cell_text(cells[index], value)
    for table_row in table.rows:
        tr_pr = table_row._tr.get_or_add_trPr()
        if tr_pr.find(qn("w:cantSplit")) is None:
            tr_pr.append(OxmlElement("w:cantSplit"))
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(2)


def add_screenshot(doc: Document) -> None:
    if not SCREENSHOT.exists():
        return
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(4)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.add_run().add_picture(str(SCREENSHOT), width=Inches(6.5))
    caption = doc.add_paragraph()
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption.paragraph_format.space_after = Pt(8)
    set_run_font(
        caption.add_run("图 1  在线 Demo：异常队列、Top-K 候选、证据、质量门与人工确认"),
        size=8.5,
        color=MUTED,
    )


def build_docx() -> None:
    doc = Document()
    configure_document(doc)
    add_title_block(doc)

    add_heading(doc, "1. 场景与真实问题")
    add_paragraph(
        doc,
        "目标用户包括计划员、生产负责人、质量与设备角色，以及负责主系统接入和审计的 IT 团队。"
        "在已有 ERP、MES 与 APS 的企业中，异常后的跨系统协同仍经常依赖人工查询、电话确认、"
        "Excel 试排和个人经验。",
    )
    add_table(
        doc,
        ["问题", "业务影响", "产品判断"],
        [
            ["信息分散且时效不一致", "错误输入会放大后续排程风险", "先验证数据健康，再进入 AI 与求解"],
            ["方案只有结论，没有证据链", "计划员不敢采纳，事后难复盘", "Top-K 方案必须带来源、约束、差异与不确定性"],
            ["临场协调缺少明确责任边界", "越权修改、并发覆盖和回滚困难", "人工确认、双审批、幂等与审计进入主流程"],
            ["失败样本没有形成资产", "同类异常反复依赖个人经验", "沉淀 case、override、failure 与 rule candidate"],
        ],
        [2300, 2850, 4210],
    )
    add_screenshot(doc)

    add_heading(doc, "2. 用户流程重构")
    add_paragraph(doc, f"原流程：{WORKFLOW_OLD}")
    add_paragraph(doc, f"目标流程：{WORKFLOW_NEW}")
    add_bullets(
        doc,
        [
            "数据健康门把权限、时效、缺失、异常和 source authority 从隐性判断变成明确阶段门。",
            "求解器提供多个硬约束可行候选，避免把 LLM 的语言流畅度误当成排程正确性。",
            "AI 解释绑定结构化证据，低置信、证据不足和冲突状态会降级或转人工。",
            "确认、拒绝、override、执行结果和失败原因进入同一条审计台账。",
        ],
    )

    add_heading(doc, "3. 与 ERP / MES / APS 的差异")
    add_table(
        doc,
        ["维度", "主系统", "ReOrch"],
        [
            ["核心职责", "主数据、业务流程、生产执行与基准计划", "异常后的影响收敛、恢复候选、风险解释与责任闭环"],
            ["输入", "订单、BOM、工艺、库存、设备、基准计划", "异常事件、最新快照、现场约束、证据来源、审批策略"],
            ["方案", "规则、人工调整或单一优化结果", "约束求解 Top-K，显式比较延期、扰动、成本与执行复杂度"],
            ["AI", "通用问答、报表或流程助手", "受控 Agent 嵌入数据、求解、证据、确认和复盘工作流"],
            ["边界", "承担生产主系统职责", "不替代主系统，不在证据不足时给强结论，不自动越权写回"],
        ],
        [1500, 3730, 4130],
    )

    add_heading(doc, "4. AI Native 架构")
    add_paragraph(
        doc,
        "数据层（ERP / MES / APS / QMS / EAM） -> 数据健康门 -> 证据层与 canonical model -> "
        "影响子图与约束识别 -> SSGS / CP-SAT / Hybrid -> Top-K 候选 -> Agent 解释 -> "
        "质量门与权限门 -> 人工确认 -> 受控执行草案 -> 决策与结果台账。",
    )
    add_table(doc, ["环节", "AI / Agent", "确定性系统与治理"], AI_ROWS, [1700, 3260, 4400])
    add_paragraph(
        doc,
        "Harness 的核心是让每一步都有结构化输入输出、可调用工具、证据引用、最大执行范围、"
        "失败关闭条件和审计记录。大模型可被替换或降级，主决策责任链不随模型变化而失效。",
    )

    add_heading(doc, "5. PRD、原型与产品机制")
    add_table(
        doc,
        ["产品对象", "关键状态 / 机制", "可验证产出"],
        [
            ["Incident", "new / validated / blocked / assessing", "来源、时效、严重度、受影响对象与缺失字段"],
            ["Schedule Snapshot", "versioned / locked / stale", "基准计划、约束版本、source refs 与并发保护"],
            ["Candidate Plan", "feasible / reference-only / blocked", "KPI、硬约束报告、Gantt diff、风险与解释"],
            ["Quality Gate", "pass / warning / fail-closed", "数据、约束、权限、置信度与证据检查"],
            ["Decision Record", "accepted / adjusted / rejected", "确认人、理由、版本、审批与执行草案"],
            ["Evidence Ledger", "prediction / decision / outcome / failure", "回放、ROI proxy、失败归因与审计导出"],
        ],
        [1900, 3100, 4360],
    )
    add_bullets(
        doc,
        [
            "PRD 覆盖背景、角色、用户故事、功能范围、页面流、输入输出、异常态、权限、埋点与验收标准。",
            "在线 Demo 直接呈现异常选择、数据健康、三方案比较、Evidence / Trace 与人工确认。",
            "事件埋点包括 incident_selected、candidate_generated、plan_confirmed、plan_rejected 和 fallback_triggered。",
        ],
    )

    add_heading(doc, "6. 评测体系与公开结果")
    add_table(doc, ["证据", "公开结果", "可证明范围"], EVIDENCE_ROWS, [2050, 2250, 5060])
    add_paragraph(
        doc,
        "评测不只统计接口通过率，还覆盖数据缺失、证据不足、超时、硬约束冲突、低置信解释、"
        "越权写回、审批篡改、幂等、schema drift、备份恢复和客户证据门等失败路径。",
    )

    add_heading(doc, "7. 失败案例与迭代")
    add_table(doc, ["失败现象", "根因", "修改方案"], FAILURE_ROWS, [2600, 2920, 3840])
    add_paragraph(
        doc,
        "每个失败样本按“现象 -> 归因 -> 修改 -> 验证 -> 剩余风险”记录。失败不是展示材料的附注，"
        "而是 Prompt、schema、工具边界、状态机和质量门迭代的输入。",
    )

    add_heading(doc, "8. 项目推进、指标与个人贡献")
    add_table(doc, ["能力", "交付物", "证明重点"], DELIVERY_ROWS, [1700, 3920, 3740])
    add_paragraph(
        doc,
        "项目按“需求与假设 -> PRD / 原型 -> 技术内核 -> 前后端联调 -> 自动化评测 -> "
        "数字孪生演练 -> 上线就绪评估”推进。阶段门分别检查数据、可行性、治理、可观测性和客户证据。",
    )
    add_paragraph(
        doc,
        "指标体系：North Star 为受控异常决策时间；护栏包括硬约束可行率、Top-K feasible coverage、"
        "审计完整率、越权写回次数、fallback rate、P95 求解与 Agent 延迟。业务代理包括延期变化、"
        "扰动范围、计划员采纳和案例复用，但代理指标不等同于真实 ROI。",
    )
    add_paragraph(
        doc,
        "个人贡献：完成问题定义、竞品与主系统边界、用户流程、PRD、原型逻辑、Agent contract、"
        "质量门、核心工程实现、自动化测试、失败样本、数字孪生验证、材料整理与公开发布；"
        "同时明确哪些结论仍需 Design Partner 数据与现场验收。",
    )

    add_heading(doc, "9. 当前边界与下一阶段")
    add_bullets(doc, BOUNDARIES)
    add_table(
        doc,
        ["阶段", "进入条件", "主要验证"],
        [
            ["Replay-ready（当前）", "公开/合成数据、完整 schema、无生产写回", "工程行为、证据结构与失败关闭"],
            ["Shadow-ready", "10-30 个客户历史案例、来源签署、只读 Connector", "计划员基线、Top-K 覆盖、阈值校准"],
            ["Controlled-pilot-ready", "客户 Sandbox、双审批、回滚、安全与审计验收", "小范围受控执行与结果复盘"],
            ["Production acceptance", "客户 IdP、HA/DR、运维、数据授权、现场签字", "稳定性、组织流程、真实价值与责任边界"],
        ],
        [2050, 3820, 3490],
    )

    add_heading(doc, "10. 证据索引")
    add_bullets(
        doc,
        [
            "公开仓库：https://github.com/eulalee001020-star/reorch-zhice",
            "产品 PRD：docs/product/prd_decision_workbench.md",
            "业务流程与原型：docs/portfolio/business_process_flow.md；docs/portfolio/prototype_logic.md",
            "评测与失败：docs/portfolio/evaluation_guardrail_cases.md；docs/portfolio/failure_iteration_log.md",
            "运行时验证：docs/validation/production_runtime_completion_report_20260712.md",
            "可行性恢复：docs/validation/feasibility_restoration_validation_20260713.md",
            "个人贡献：docs/portfolio/personal_contribution.md",
        ],
    )

    doc.core_properties.title = "ReOrch 智策 AI 产品作品集"
    doc.core_properties.subject = "工业异常恢复决策 Copilot"
    doc.core_properties.author = "Shuangjiang Li"
    doc.core_properties.keywords = "Industrial AI, Agent, Scheduling, Decision Support, Portfolio"
    doc.core_properties.comments = ""
    doc.save(DOCX_PATH)


def register_pdf_font() -> None:
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            pdfmetrics.registerFont(TTFont(PDF_FONT, str(candidate)))
            return
    raise FileNotFoundError("No CJK-capable font found for PDF generation.")


def pdf_styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "Title",
            fontName=PDF_FONT,
            fontSize=25,
            leading=30,
            textColor=colors.HexColor("#191F1D"),
            spaceAfter=4,
            wordWrap="CJK",
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            fontName=PDF_FONT,
            fontSize=14,
            leading=19,
            textColor=colors.HexColor("#1F4D78"),
            spaceAfter=12,
            wordWrap="CJK",
        ),
        "meta": ParagraphStyle(
            "Meta",
            fontName=PDF_FONT,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#4F5A55"),
            spaceAfter=2,
            wordWrap="CJK",
        ),
        "h1": ParagraphStyle(
            "H1",
            fontName=PDF_FONT,
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#2E74B5"),
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=True,
            wordWrap="CJK",
        ),
        "body": ParagraphStyle(
            "Body",
            fontName=PDF_FONT,
            fontSize=9.3,
            leading=13,
            textColor=colors.HexColor("#191F1D"),
            spaceAfter=6,
            wordWrap="CJK",
        ),
        "callout": ParagraphStyle(
            "Callout",
            fontName=PDF_FONT,
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#176B4D"),
            wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            fontName=PDF_FONT,
            fontSize=9,
            leading=13,
            leftIndent=10,
            spaceAfter=4,
            wordWrap="CJK",
        ),
        "table": ParagraphStyle(
            "TableBody",
            fontName=PDF_FONT,
            fontSize=7.7,
            leading=10.2,
            textColor=colors.HexColor("#191F1D"),
            wordWrap="CJK",
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            fontName=PDF_FONT,
            fontSize=7.8,
            leading=10.2,
            textColor=colors.HexColor("#1F4D78"),
            wordWrap="CJK",
        ),
        "caption": ParagraphStyle(
            "Caption",
            fontName=PDF_FONT,
            fontSize=7.5,
            leading=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#5B6560"),
            spaceAfter=8,
            wordWrap="CJK",
        ),
    }


def pdf_table(
    story,
    styles,
    headers: list[str],
    rows: list[list[str]],
    widths: list[float],
) -> None:
    data = [[Paragraph(header, styles["table_header"]) for header in headers]]
    data.extend([[Paragraph(value, styles["table"]) for value in row] for row in rows])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CAD2CD")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([table, Spacer(1, 5)])


def pdf_bullets(story, styles, items: list[str]) -> None:
    story.append(
        ListFlowable(
            [ListItem(Paragraph(item, styles["bullet"])) for item in items],
            bulletType="bullet",
            leftIndent=13,
            bulletFontName=PDF_FONT,
            bulletFontSize=7,
            spaceAfter=4,
        )
    )


def on_pdf_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(PDF_FONT, 7.5)
    canvas.setFillColor(colors.HexColor("#5B6560"))
    canvas.drawString(inch, 10.45 * inch, "REORCH / INDUSTRIAL AI COPILOT")
    canvas.drawRightString(7.5 * inch, 10.45 * inch, "PUBLIC PORTFOLIO")
    canvas.setStrokeColor(colors.HexColor("#D9DFDB"))
    canvas.line(inch, 10.32 * inch, 7.5 * inch, 10.32 * inch)
    canvas.drawRightString(7.5 * inch, 0.42 * inch, f"ReOrch 智策  |  {doc.page}")
    canvas.restoreState()


def build_pdf() -> None:
    register_pdf_font()
    styles = pdf_styles()
    document = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=0.78 * inch,
        bottomMargin=0.65 * inch,
        title="ReOrch 智策 AI 产品作品集",
        author="Shuangjiang Li",
    )
    story = [
        Spacer(1, 8),
        Paragraph("ReOrch 智策", styles["title"]),
        Paragraph("工业异常恢复决策 Copilot", styles["subtitle"]),
        Paragraph("<b>项目类型：</b> AI Native 产品 / Agent Workflow / 工业决策辅助", styles["meta"]),
        Paragraph("<b>产品状态：</b> MVP 已完成；replay-ready；生产写回默认关闭", styles["meta"]),
        Paragraph("<b>公开证据：</b> 872 项自动化测试 + 合成回放 + 数字孪生 gates", styles["meta"]),
        Paragraph("<b>更新日期：</b> 2026-07-27", styles["meta"]),
        Paragraph("<b>公开仓库：</b> github.com/eulalee001020-star/reorch-zhice", styles["meta"]),
        Spacer(1, 9),
        Table(
            [[Paragraph(POSITIONING, styles["callout"])]],
            colWidths=[6.5 * inch],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E2F1E9")),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#9FC9B4")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ]
            ),
        ),
        Paragraph("1. 场景与真实问题", styles["h1"]),
        Paragraph(
            "目标用户包括计划员、生产负责人、质量与设备角色，以及负责主系统接入和审计的 IT 团队。"
            "在已有 ERP、MES 与 APS 的企业中，异常后的跨系统协同仍经常依赖人工查询、电话确认、"
            "Excel 试排和个人经验。",
            styles["body"],
        ),
    ]
    pdf_table(
        story,
        styles,
        ["问题", "业务影响", "产品判断"],
        [
            ["信息分散且时效不一致", "错误输入会放大后续排程风险", "先验证数据健康，再进入 AI 与求解"],
            ["方案只有结论，没有证据链", "计划员不敢采纳，事后难复盘", "Top-K 必须带来源、约束、差异与不确定性"],
            ["临场协调缺少责任边界", "越权、并发覆盖和回滚困难", "人工确认、双审批、幂等与审计进入主流程"],
            ["失败样本没有形成资产", "同类异常反复依赖个人经验", "沉淀 case、override、failure 与 rule candidate"],
        ],
        [1.55 * inch, 1.8 * inch, 3.15 * inch],
    )
    if SCREENSHOT.exists():
        screenshot = Image(str(SCREENSHOT))
        aspect_ratio = screenshot.imageHeight / screenshot.imageWidth
        screenshot.drawWidth = 6.5 * inch
        screenshot.drawHeight = aspect_ratio * screenshot.drawWidth
        story.extend(
            [
                screenshot,
                Paragraph(
                    "图 1  在线 Demo：异常队列、Top-K 候选、证据、质量门与人工确认",
                    styles["caption"],
                ),
            ]
        )

    story.extend(
        [
            Paragraph("2. 用户流程重构", styles["h1"]),
            Paragraph(f"<b>原流程：</b>{WORKFLOW_OLD}", styles["body"]),
            Paragraph(f"<b>目标流程：</b>{WORKFLOW_NEW}", styles["body"]),
        ]
    )
    pdf_bullets(
        story,
        styles,
        [
            "数据健康门把权限、时效、缺失、异常和 source authority 变成明确阶段门。",
            "求解器提供多个硬约束可行候选，避免把语言流畅度误当成排程正确性。",
            "AI 解释绑定证据，低置信、证据不足和冲突状态会降级或转人工。",
            "确认、拒绝、override、执行结果和失败原因进入同一条审计台账。",
        ],
    )
    story.append(Paragraph("3. 与 ERP / MES / APS 的差异", styles["h1"]))
    pdf_table(
        story,
        styles,
        ["维度", "主系统", "ReOrch"],
        [
            ["核心职责", "主数据、流程、生产执行与基准计划", "异常后的影响收敛、恢复候选、风险解释与责任闭环"],
            ["输入", "订单、BOM、工艺、库存、设备、基准计划", "异常、最新快照、现场约束、证据来源与审批策略"],
            ["方案", "规则、人工调整或单一优化结果", "约束求解 Top-K，比较延期、扰动、成本与执行复杂度"],
            ["AI", "通用问答、报表或流程助手", "受控 Agent 嵌入数据、求解、证据、确认和复盘"],
            ["边界", "承担生产主系统职责", "不替代主系统，不在证据不足时给强结论，不越权写回"],
        ],
        [0.95 * inch, 2.6 * inch, 2.95 * inch],
    )

    story.extend(
        [
            PageBreak(),
            Paragraph("4. AI Native 架构", styles["h1"]),
            Paragraph(
                "数据层 -> 数据健康门 -> 证据层与 canonical model -> 影响子图与约束识别 -> "
                "SSGS / CP-SAT / Hybrid -> Top-K 候选 -> Agent 解释 -> 质量门与权限门 -> "
                "人工确认 -> 受控执行草案 -> 决策与结果台账。",
                styles["body"],
            ),
        ]
    )
    pdf_table(
        story,
        styles,
        ["环节", "AI / Agent", "确定性系统与治理"],
        AI_ROWS,
        [1.1 * inch, 2.2 * inch, 3.2 * inch],
    )
    story.append(
        Paragraph(
            "Harness 让每一步都有结构化输入输出、可调用工具、证据引用、最大执行范围、失败关闭条件和审计记录。"
            "模型可被替换或降级，主决策责任链不随模型变化而失效。",
            styles["body"],
        )
    )

    story.append(Paragraph("5. PRD、原型与产品机制", styles["h1"]))
    pdf_table(
        story,
        styles,
        ["产品对象", "关键状态 / 机制", "可验证产出"],
        [
            ["Incident", "new / validated / blocked / assessing", "来源、时效、严重度、受影响对象与缺失字段"],
            ["Snapshot", "versioned / locked / stale", "基准计划、约束版本、source refs 与并发保护"],
            ["Candidate", "feasible / reference-only / blocked", "KPI、硬约束报告、Gantt diff、风险与解释"],
            ["Quality Gate", "pass / warning / fail-closed", "数据、约束、权限、置信度与证据检查"],
            ["Decision", "accepted / adjusted / rejected", "确认人、理由、版本、审批与执行草案"],
            ["Ledger", "prediction / decision / outcome / failure", "回放、ROI proxy、失败归因与审计导出"],
        ],
        [1.15 * inch, 2.3 * inch, 3.05 * inch],
    )
    pdf_bullets(
        story,
        styles,
        [
            "PRD 覆盖背景、角色、用户故事、范围、页面流、异常态、权限、埋点与验收标准。",
            "在线 Demo 呈现异常选择、数据健康、三方案比较、Evidence / Trace 与人工确认。",
            "埋点包括 incident_selected、candidate_generated、plan_confirmed、plan_rejected、fallback_triggered。",
        ],
    )

    story.append(Paragraph("6. 评测体系与公开结果", styles["h1"]))
    pdf_table(
        story,
        styles,
        ["证据", "公开结果", "可证明范围"],
        EVIDENCE_ROWS,
        [1.45 * inch, 1.6 * inch, 3.45 * inch],
    )
    story.append(
        Paragraph(
            "评测覆盖数据缺失、证据不足、超时、硬约束冲突、低置信解释、越权写回、审批篡改、"
            "幂等、schema drift、备份恢复和客户证据门等失败路径。",
            styles["body"],
        )
    )

    story.append(Paragraph("7. 失败案例与迭代", styles["h1"]))
    pdf_table(
        story,
        styles,
        ["失败现象", "根因", "修改方案"],
        FAILURE_ROWS,
        [1.8 * inch, 2.0 * inch, 2.7 * inch],
    )
    story.append(
        Paragraph(
            "失败样本按“现象 -> 归因 -> 修改 -> 验证 -> 剩余风险”记录，并直接驱动 Prompt、schema、"
            "工具边界、状态机和质量门迭代。",
            styles["body"],
        )
    )

    story.extend([PageBreak(), Paragraph("8. 项目推进、指标与个人贡献", styles["h1"])])
    pdf_table(
        story,
        styles,
        ["能力", "交付物", "证明重点"],
        DELIVERY_ROWS,
        [1.15 * inch, 2.75 * inch, 2.6 * inch],
    )
    story.extend(
        [
            Paragraph(
                "项目按“需求与假设 -> PRD / 原型 -> 技术内核 -> 前后端联调 -> 自动化评测 -> "
                "数字孪生演练 -> 上线就绪评估”推进。阶段门检查数据、可行性、治理、可观测性和客户证据。",
                styles["body"],
            ),
            Paragraph(
                "<b>指标体系：</b>North Star 为受控异常决策时间；护栏包括硬约束可行率、Top-K feasible coverage、"
                "审计完整率、越权写回次数、fallback rate、P95 求解与 Agent 延迟。业务代理包括延期变化、"
                "扰动范围、计划员采纳和案例复用，但代理指标不等同于真实 ROI。",
                styles["body"],
            ),
            Paragraph(
                "<b>个人贡献：</b>完成问题定义、竞品与主系统边界、用户流程、PRD、原型逻辑、Agent contract、"
                "质量门、核心工程实现、自动化测试、失败样本、数字孪生验证、材料整理与公开发布；"
                "同时明确仍需 Design Partner 数据与现场验收的结论。",
                styles["body"],
            ),
            Paragraph("9. 当前边界与下一阶段", styles["h1"]),
        ]
    )
    pdf_bullets(story, styles, BOUNDARIES)
    pdf_table(
        story,
        styles,
        ["阶段", "进入条件", "主要验证"],
        [
            ["Replay-ready（当前）", "公开/合成数据、完整 schema、无生产写回", "工程行为、证据结构与失败关闭"],
            ["Shadow-ready", "10-30 个客户历史案例、来源签署、只读 Connector", "计划员基线、Top-K 覆盖、阈值校准"],
            ["Controlled-pilot-ready", "客户 Sandbox、双审批、回滚、安全与审计验收", "小范围受控执行与结果复盘"],
            ["Production acceptance", "客户 IdP、HA/DR、运维、数据授权、现场签字", "稳定性、真实价值与责任边界"],
        ],
        [1.45 * inch, 2.85 * inch, 2.2 * inch],
    )
    story.append(Paragraph("10. 证据索引", styles["h1"]))
    pdf_bullets(
        story,
        styles,
        [
            "公开仓库：https://github.com/eulalee001020-star/reorch-zhice",
            "PRD：docs/product/prd_decision_workbench.md",
            "流程与原型：docs/portfolio/business_process_flow.md；docs/portfolio/prototype_logic.md",
            "评测与失败：docs/portfolio/evaluation_guardrail_cases.md；docs/portfolio/failure_iteration_log.md",
            "运行时验证：docs/validation/production_runtime_completion_report_20260712.md",
            "可行性恢复：docs/validation/feasibility_restoration_validation_20260713.md",
            "个人贡献：docs/portfolio/personal_contribution.md",
        ],
    )

    document.build(story, onFirstPage=on_pdf_page, onLaterPages=on_pdf_page)


def should_skip(path: Path) -> bool:
    ignored = {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".hypothesis",
        ".git",
        ".venv",
        ".wrangler",
        ".playwright-cli",
        "node_modules",
        "dist",
        "build",
        "htmlcov",
        "runtime",
        "output",
        "outputs",
    }
    if set(path.parts) & ignored:
        return True
    return path.suffix in {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db"}


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        if should_skip(path):
            continue
        relative = path.relative_to(src)
        target = dst / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            copy_file(path, target)


def package_readme() -> str:
    return """# ReOrch 智策 - AI 产品作品集材料包

ReOrch 是位于 ERP / MES / APS 之上的工业异常恢复决策 Copilot。材料包包含
PDF / DOCX 项目说明、PRD、业务流程、原型逻辑、指标、评测、失败迭代、
核心工程代码、测试、验证报告与独立互动 Demo 源码。

## 入口

- `ReOrch_智策_AI产品作品集_20260727.pdf`
- `ReOrch_智策_AI产品作品集_20260727.docx`
- `README.md`
- `docs/product/prd_decision_workbench.md`
- `docs/portfolio/business_process_flow.md`
- `docs/portfolio/prototype_logic.md`
- `docs/portfolio/metric_system.md`
- `docs/portfolio/evaluation_guardrail_cases.md`
- `docs/portfolio/failure_iteration_log.md`
- `docs/validation/production_runtime_completion_report_20260712.md`
- `portfolio_site/`

## 证据边界

- 当前公开证据来自自动化测试、公开来源数据、合成回放与数字孪生演练。
- 真实 Design Partner 案例数为 0，尚无客户生产数据或财务确认 ROI。
- 生产写回默认关闭，LLM 不负责硬约束、排程可行性或最终执行责任。
"""


def build_package() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    PACKAGE.mkdir(parents=True, exist_ok=True)

    for name in [
        "README.md",
        "LICENSE",
        "SECURITY.md",
        "CHANGELOG.md",
        ".env.example",
        "docker-compose.yml",
        "Dockerfile",
        "Makefile",
        "pyproject.toml",
        "uv.lock",
        "alembic.ini",
    ]:
        source = ROOT / name
        if source.exists():
            copy_file(source, PACKAGE / name)

    for artifact in [DOCX_PATH, PDF_PATH]:
        copy_file(artifact, PACKAGE / artifact.name)

    for directory in [
        "app",
        "alembic",
        "docs",
        "demo",
        "benchmark",
        "datasets/customer_evidence_pack",
        "datasets/integration_control_pack",
        ".github/workflows",
        "frontend/src",
        "tools",
    ]:
        source = ROOT / directory
        if source.exists():
            copy_tree(source, PACKAGE / directory)

    for name in [
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/index.html",
        "frontend/vite.config.ts",
        "frontend/tsconfig.json",
        "frontend/nginx.conf",
        "frontend/Dockerfile",
    ]:
        source = ROOT / name
        if source.exists():
            copy_file(source, PACKAGE / name)

    for directory in ["app", "public", "tests"]:
        source = ROOT / "portfolio_site" / directory
        if source.exists():
            copy_tree(source, PACKAGE / "portfolio_site" / directory)
    for name in [
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "next.config.ts",
        "vite.config.ts",
        "postcss.config.mjs",
        "eslint.config.mjs",
    ]:
        source = ROOT / "portfolio_site" / name
        if source.exists():
            copy_file(source, PACKAGE / "portfolio_site" / name)

    (PACKAGE / "PORTFOLIO_README.md").write_text(package_readme(), encoding="utf-8")


def build_zip() -> None:
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in PACKAGE.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(BUILD))


def main() -> None:
    DIST.mkdir(exist_ok=True)
    ARTIFACTS.mkdir(exist_ok=True)
    for path in ARTIFACTS.glob("ReOrch_智策_AI*20260603.*"):
        path.unlink()
    build_docx()
    build_pdf()
    build_package()
    build_zip()
    for artifact in [DOCX_PATH, PDF_PATH, ZIP_PATH]:
        copy_file(artifact, ARTIFACTS / artifact.name)
    print(DOCX_PATH)
    print(PDF_PATH)
    print(ZIP_PATH)


if __name__ == "__main__":
    main()
