import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

const artifactRequire = createRequire(
  "/var/folders/xl/rf7c74ws2_72nq5j110hx1180000gn/T/codex-presentations/reorch-technical-stack/tmp/package.json",
);
const { Presentation, PresentationFile } = artifactRequire("@oai/artifact-tool");

const OUT_DIR = "/Users/lishuangjiang/ai助理/智策/investor_roadshow";
const FINAL_PPTX = path.join(OUT_DIR, "ReOrch_智策_技术实现补充Deck_20260704.pptx");
const QA_DIR = path.join(OUT_DIR, "technical_stack_qa");

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

function textbox(slide, text, position, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontSize: style.fontSize ?? 22,
    bold: style.bold ?? false,
    color: style.color ?? "111827",
    alignment: style.alignment ?? "left",
  };
  return shape;
}

function rect(slide, position, fill = "F9FAFB", line = "D1D5DB") {
  return slide.shapes.add({
    geometry: "roundRect",
    position,
    fill,
    line: { style: "solid", fill: line, width: 1 },
    borderRadius: "rounded-lg",
  });
}

function chip(slide, text, left, top, width, fill = "F3F4F6") {
  rect(slide, { left, top, width, height: 42 }, fill, "D1D5DB");
  textbox(slide, text, { left: left + 12, top: top + 9, width: width - 24, height: 24 }, {
    fontSize: 16,
    bold: true,
    color: "111827",
    alignment: "center",
  });
}

function header(slide, title, subtitle) {
  textbox(slide, "REORCH TECHNICAL STACK", { left: 64, top: 42, width: 420, height: 28 }, {
    fontSize: 13,
    bold: true,
    color: "6B7280",
  });
  textbox(slide, title, { left: 64, top: 78, width: 920, height: 62 }, {
    fontSize: 34,
    bold: true,
    color: "111827",
  });
  if (subtitle) {
    textbox(slide, subtitle, { left: 66, top: 142, width: 900, height: 36 }, {
      fontSize: 17,
      color: "4B5563",
    });
  }
}

function footer(slide, page) {
  textbox(slide, `2026-07-04 · 技术实现补充 · ${page}`, { left: 64, top: 674, width: 480, height: 22 }, {
    fontSize: 12,
    color: "6B7280",
  });
}

function addSlide1(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = "FFFFFF";
  textbox(slide, "ReOrch 的技术内核不是 AI 排产", { left: 72, top: 86, width: 840, height: 68 }, {
    fontSize: 42,
    bold: true,
    color: "111827",
  });
  textbox(slide, "它是从真实约束到异常恢复的 Constraint-to-Recovery Kernel。", { left: 74, top: 168, width: 820, height: 38 }, {
    fontSize: 22,
    color: "374151",
  });
  const layers = [
    "真实数据",
    "生产状态图",
    "约束编译",
    "影响分析",
    "恢复算子",
    "证据门控",
    "回放记忆",
  ];
  layers.forEach((label, index) => chip(slide, label, 74 + index * 158, 300, 132, index === 4 ? "FFF1E8" : "F9FAFB"));
  textbox(slide, "核心判断：先还原现场，再表达约束，再生成候选，最后用质量门、回放和人工确认决定能不能用。", { left: 124, top: 420, width: 930, height: 64 }, {
    fontSize: 24,
    bold: true,
    color: "111827",
    alignment: "center",
  });
  footer(slide, "01");
}

function addSlide2(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = "FFFFFF";
  header(slide, "7 层技术栈把异常恢复拆成可验证流程", "每一层都有输入、输出、阻断条件和审计证据。");
  const items = [
    ["Reality Data", "字段映射、数据质量、快照重建"],
    ["Decision Graph", "订单、工序、资源、依赖和异常图"],
    ["Constraint Compiler", "设备、日历、冻结、换型、经验规则"],
    ["Impact Engine", "影响范围、下游风险、可修复子图"],
    ["Recovery Operators", "等待、替代设备、插入、滚动窗口"],
    ["Evidence-Gated Solver", "CP-SAT、启发式、质量门和 source refs"],
    ["Replay / Shadow", "历史复盘、只读并行、经验沉淀"],
  ];
  items.forEach(([title, body], index) => {
    const left = 72 + (index % 2) * 560;
    const top = 212 + Math.floor(index / 2) * 104;
    rect(slide, { left, top, width: 504, height: 76 }, index === 4 ? "FFF7ED" : "F9FAFB");
    textbox(slide, title, { left: left + 20, top: top + 14, width: 180, height: 24 }, {
      fontSize: 18,
      bold: true,
      color: "111827",
    });
    textbox(slide, body, { left: left + 210, top: top + 15, width: 260, height: 46 }, {
      fontSize: 16,
      color: "374151",
    });
  });
  footer(slide, "02");
}

function addSlide3(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = "FFFFFF";
  header(slide, "Decision Graph 先确定哪些能动", "甘特图展示结果，Decision Graph 解释影响边界和可修复子图。");
  const nodes = [
    ["订单", 108, 250],
    ["工单", 278, 250],
    ["OP10", 448, 210],
    ["OP20", 448, 306],
    ["设备 A", 650, 210],
    ["设备 B", 650, 306],
    ["异常", 844, 210],
    ["冻结", 844, 306],
  ];
  nodes.forEach(([label, left, top]) => {
    rect(slide, { left, top, width: 120, height: 52 }, label === "异常" ? "FEE2E2" : label === "冻结" ? "E5E7EB" : "F9FAFB");
    textbox(slide, label, { left: left + 12, top: top + 15, width: 96, height: 22 }, {
      fontSize: 18,
      bold: true,
      alignment: "center",
    });
  });
  [
    [232, 260],
    [402, 236],
    [402, 332],
    [574, 236],
    [574, 332],
    [772, 236],
    [772, 332],
  ].forEach(([left, top]) => {
    textbox(slide, "→", { left, top, width: 40, height: 28 }, {
      fontSize: 24,
      bold: true,
      color: "9CA3AF",
      alignment: "center",
    });
  });
  textbox(slide, "当前实现已能从 ScheduleSnapshot 构建工单、工序、资源节点，沿 predecessor / successor 传播影响，并输出 repairable frontier 与替代资源。", { left: 118, top: 446, width: 960, height: 72 }, {
    fontSize: 22,
    bold: true,
    alignment: "center",
  });
  footer(slide, "03");
}

function addSlide4(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = "FFFFFF";
  header(slide, "恢复算子库让系统不盲目全局重排", "不同异常调用不同 operator，再交给启发式、CP-SAT、LNS 或 what-if 做候选。");
  const rows = [
    ["设备故障", "wait / alternative machine / local insertion / rolling window", "交期、扰动、换线、资源切换"],
    ["缺料", "substitute lot / ETA shift / pull-forward unblocked ops", "齐套、库存、下游阻断"],
    ["插单", "direct insertion / priority swap / overtime what-if", "新单承诺、挤出订单、加班成本"],
    ["质量 Hold", "insert rework routing / delay hold-dependent ops", "质量门、返工资源、客户风险"],
  ];
  textbox(slide, "异常类型", { left: 84, top: 214, width: 170, height: 24 }, { fontSize: 16, bold: true });
  textbox(slide, "恢复算子", { left: 292, top: 214, width: 430, height: 24 }, { fontSize: 16, bold: true });
  textbox(slide, "关键指标", { left: 814, top: 214, width: 270, height: 24 }, { fontSize: 16, bold: true });
  rows.forEach((row, index) => {
    const top = 252 + index * 86;
    rect(slide, { left: 72, top, width: 1060, height: 64 }, index === 0 ? "FFF7ED" : "F9FAFB");
    textbox(slide, row[0], { left: 94, top: top + 17, width: 150, height: 24 }, { fontSize: 17, bold: true });
    textbox(slide, row[1], { left: 292, top: top + 14, width: 448, height: 34 }, { fontSize: 15, color: "374151" });
    textbox(slide, row[2], { left: 814, top: top + 14, width: 270, height: 34 }, { fontSize: 15, color: "374151" });
  });
  footer(slide, "04");
}

function addSlide5(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = "FFFFFF";
  header(slide, "Evidence Gates 决定方案能不能进入业务", "求解器给出候选，不等于系统可以推荐、解释、shadow 或写回。");
  const gates = [
    ["DataGate", "blocker > 0 禁止求解"],
    ["Constraint", "硬约束失败禁止推荐"],
    ["EvidenceGate", "缺 source refs 只能参考"],
    ["ReplayGate", "Top-N 不命中不进 shadow"],
    ["PolicyGate", "低置信只给风险提示"],
    ["Writeback", "未人工确认禁止写回"],
  ];
  gates.forEach(([title, body], index) => {
    const left = 92 + index * 178;
    rect(slide, { left, top: 260, width: 146, height: 156 }, index === 5 ? "FEE2E2" : "F9FAFB");
    textbox(slide, title, { left: left + 10, top: 282, width: 126, height: 24 }, {
      fontSize: 17,
      bold: true,
      alignment: "center",
    });
    textbox(slide, body, { left: left + 14, top: 326, width: 118, height: 62 }, {
      fontSize: 15,
      color: "374151",
      alignment: "center",
    });
  });
  textbox(slide, "当前已实现统一 EvidenceGateService：把候选方案分成禁止推荐、仅供参考、可正式解释、可 shadow、可人工确认后写回。", { left: 122, top: 488, width: 930, height: 58 }, {
    fontSize: 22,
    bold: true,
    alignment: "center",
  });
  footer(slide, "05");
}

function addSlide6(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = "FFFFFF";
  header(slide, "差异不在模型，而在异常恢复闭环", "ReOrch 把 APS、启发式、LLM 各自强项放进受控系统，而不是让其中一个单独接管。");
  const rows = [
    ["传统 APS", "完整计划排程", "ReOrch 从异常恢复、replay 和 shadow 切入"],
    ["纯启发式", "速度快", "ReOrch 有 operator portfolio 和 constraint gate"],
    ["纯 LLM Agent", "语义理解强", "ReOrch 不让 LLM 负责硬约束和最终排程"],
    ["BI / RPA", "可视化和固定流程", "ReOrch 生成可行候选并沉淀经验资产"],
  ];
  rows.forEach((row, index) => {
    const top = 220 + index * 92;
    rect(slide, { left: 78, top, width: 1020, height: 68 }, "F9FAFB");
    textbox(slide, row[0], { left: 104, top: top + 20, width: 160, height: 24 }, { fontSize: 18, bold: true });
    textbox(slide, row[1], { left: 332, top: top + 20, width: 220, height: 24 }, { fontSize: 16, color: "374151" });
    textbox(slide, row[2], { left: 620, top: top + 16, width: 420, height: 34 }, { fontSize: 16, color: "111827", bold: true });
  });
  footer(slide, "06");
}

function addSlide7(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = "FFFFFF";
  header(slide, "当前已落地的是可信性地基，不是完整 APS 替代", "这让路演从概念进入系统工程，但仍保留生产上线前的边界。");
  const done = [
    "Decision Graph API",
    "Recovery Operator API",
    "Evidence Gates API",
    "P0 Reality Harness",
    "Constraint Calibration",
    "Replay / Shadow / Agent Cost",
  ];
  done.forEach((item, index) => chip(slide, item, 100 + (index % 3) * 340, 232 + Math.floor(index / 3) * 90, 260, index < 3 ? "FFF7ED" : "F9FAFB"));
  textbox(slide, "下一步补证据：真实客户 10-30 条历史异常 replay、2-4 周 shadow、sandbox dry-run writeback、物料/质量/人员/工装/外协约束。", { left: 110, top: 466, width: 960, height: 72 }, {
    fontSize: 23,
    bold: true,
    alignment: "center",
  });
  footer(slide, "07");
}

async function main() {
  await fs.mkdir(QA_DIR, { recursive: true });
  const presentation = Presentation.create({
    slideSize: { width: 1280, height: 720 },
  });
  [
    addSlide1,
    addSlide2,
    addSlide3,
    addSlide4,
    addSlide5,
    addSlide6,
    addSlide7,
  ].forEach((builder) => builder(presentation));

  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `technical-stack-slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(path.join(QA_DIR, `${stem}.png`), await presentation.export({ slide, format: "png", scale: 1 }));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(QA_DIR, `${stem}.layout.json`), await layout.text());
  }
  await writeBlob(path.join(QA_DIR, "technical_stack_montage.webp"), await presentation.export({
    format: "webp",
    montage: true,
    scale: 1,
  }));
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(FINAL_PPTX);
  console.log(FINAL_PPTX);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
