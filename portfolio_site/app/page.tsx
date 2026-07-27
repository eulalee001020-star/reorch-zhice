"use client";

import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  Factory,
  FileSearch,
  GitBranch,
  History,
  Layers3,
  LockKeyhole,
  PanelLeft,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UserCheck,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";

type Incident = {
  id: string;
  code: string;
  title: string;
  line: string;
  severity: "P1" | "P2";
  status: string;
  time: string;
  impact: string;
  facts: string[];
};

type Plan = {
  id: string;
  label: string;
  strategy: string;
  delay: number;
  overtime: number;
  changes: number;
  score: number;
  risk: "低" | "中";
  rationale: string;
};

const incidents: Incident[] = [
  {
    id: "inc-1428",
    code: "INC-1428",
    title: "五轴加工中心突发停机",
    line: "精密加工一线",
    severity: "P1",
    status: "待决策",
    time: "09:18",
    impact: "6 个工单受影响，预计延期 11.4 小时",
    facts: ["设备 M-17 故障", "维修窗口约 4 小时", "订单 SO-8841 为高优先级"],
  },
  {
    id: "inc-1431",
    code: "INC-1431",
    title: "关键物料到货延期",
    line: "装配二线",
    severity: "P1",
    status: "评估中",
    time: "09:42",
    impact: "3 个订单存在 SLA 风险",
    facts: ["物料 RM-2207 延期 8 小时", "替代料库存 64 件", "质检放行尚未完成"],
  },
  {
    id: "inc-1435",
    code: "INC-1435",
    title: "质量返工插单",
    line: "终检工序",
    severity: "P2",
    status: "新建",
    time: "10:06",
    impact: "返工批次占用 2 个关键工位",
    facts: ["批次 LOT-392 需返工", "交付窗口剩余 19 小时", "需复核工艺路线"],
  },
];

const plansByIncident: Record<string, Plan[]> = {
  "inc-1428": [
    {
      id: "balanced",
      label: "方案 A",
      strategy: "均衡恢复",
      delay: 2.6,
      overtime: 1.5,
      changes: 8,
      score: 91,
      risk: "低",
      rationale: "转移两道关键工序并保留原班次结构，在交付与现场扰动之间取得平衡。",
    },
    {
      id: "delivery",
      label: "方案 B",
      strategy: "交付优先",
      delay: 1.2,
      overtime: 4.0,
      changes: 14,
      score: 86,
      risk: "中",
      rationale: "优先保障高价值订单，通过加班和跨线调度压缩延期，但现场变更较多。",
    },
    {
      id: "stable",
      label: "方案 C",
      strategy: "稳定优先",
      delay: 4.8,
      overtime: 0,
      changes: 4,
      score: 82,
      risk: "低",
      rationale: "最小化计划变更与加班，接受部分普通订单延期，执行稳定性更高。",
    },
  ],
  "inc-1431": [
    {
      id: "substitute",
      label: "方案 A",
      strategy: "替代料切换",
      delay: 1.8,
      overtime: 1.0,
      changes: 6,
      score: 88,
      risk: "中",
      rationale: "完成质检放行后切换替代料，并将剩余订单顺延到原料到货窗口。",
    },
    {
      id: "resequence",
      label: "方案 B",
      strategy: "工单重排",
      delay: 3.2,
      overtime: 0,
      changes: 5,
      score: 84,
      risk: "低",
      rationale: "先生产不依赖缺料的工单，减少在制品等待，不引入替代料质量风险。",
    },
    {
      id: "expedite",
      label: "方案 C",
      strategy: "加急补料",
      delay: 2.4,
      overtime: 2.5,
      changes: 9,
      score: 80,
      risk: "中",
      rationale: "触发供应商加急与晚班窗口，缩短缺料时间，但成本与到货波动更高。",
    },
  ],
  "inc-1435": [
    {
      id: "window",
      label: "方案 A",
      strategy: "窗口插入",
      delay: 2.1,
      overtime: 1.0,
      changes: 7,
      score: 89,
      risk: "低",
      rationale: "利用换线空档插入返工批次，锁定两项已确认订单不被二次扰动。",
    },
    {
      id: "parallel",
      label: "方案 B",
      strategy: "并行返工",
      delay: 1.3,
      overtime: 3.0,
      changes: 11,
      score: 85,
      risk: "中",
      rationale: "启用备用工位并安排复检加班，交付更快，但需要额外人员确认。",
    },
    {
      id: "batch",
      label: "方案 C",
      strategy: "批次合并",
      delay: 4.0,
      overtime: 0,
      changes: 3,
      score: 81,
      risk: "低",
      rationale: "与下一返工窗口合并处理，减少切换损失，但当前批次等待时间更长。",
    },
  ],
};

const traceSteps = [
  ["数据健康门", "行情时效、字段完整性与权限通过", "12 ms"],
  ["影响分析", "定位受影响工单、资源与交付窗口", "146 ms"],
  ["约束求解", "生成 3 个满足硬约束的候选方案", "1.8 s"],
  ["AI 解释", "基于证据生成差异摘要与风险说明", "684 ms"],
  ["质量门", "硬约束、权限与置信度检查通过", "28 ms"],
];

export default function Home() {
  const [selectedIncidentId, setSelectedIncidentId] = useState(incidents[0].id);
  const [selectedPlanId, setSelectedPlanId] = useState("balanced");
  const [activeTab, setActiveTab] = useState<"evidence" | "trace">("evidence");
  const [confirmed, setConfirmed] = useState(false);
  const [notice, setNotice] = useState("");

  const incident = useMemo(
    () => incidents.find((item) => item.id === selectedIncidentId) ?? incidents[0],
    [selectedIncidentId],
  );
  const plans = plansByIncident[selectedIncidentId];
  const plan = plans.find((item) => item.id === selectedPlanId) ?? plans[0];

  function selectIncident(id: string) {
    setSelectedIncidentId(id);
    setSelectedPlanId(plansByIncident[id][0].id);
    setConfirmed(false);
    setNotice("");
  }

  function runRefresh() {
    setNotice("运行结果已刷新：3 个可行候选，质量门通过。");
    window.setTimeout(() => setNotice(""), 2800);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Factory size={19} />
          </span>
          <span>
            <strong>ReOrch 智策</strong>
            <small>异常恢复决策工作台</small>
          </span>
        </div>
        <nav className="primary-nav" aria-label="主导航">
          <button className="nav-item active" type="button">
            <PanelLeft size={16} /> 决策工作台
          </button>
          <button className="nav-item" type="button">
            <Database size={16} /> 数据与证据
          </button>
          <button className="nav-item" type="button">
            <History size={16} /> 审计记录
          </button>
        </nav>
        <div className="system-status">
          <span className="status-dot" />
          演示环境
          <a
            href="https://github.com/eulalee001020-star/reorch-zhice"
            target="_blank"
            rel="noreferrer"
          >
            查看仓库 <ArrowRight size={14} />
          </a>
        </div>
      </header>

      <section className="context-bar">
        <div>
          <span className="eyebrow">华南示范工厂 · 今日班次</span>
          <strong>异常恢复队列</strong>
        </div>
        <div className="context-metrics">
          <span><AlertTriangle size={15} /> 待处理 <b>3</b></span>
          <span><Clock3 size={15} /> 平均响应 <b>7.4 min</b></span>
          <span><ShieldCheck size={15} /> 受控回写 <b>关闭</b></span>
        </div>
        <button className="icon-button" type="button" onClick={runRefresh} title="重新运行分析" aria-label="重新运行分析">
          <RefreshCw size={17} />
        </button>
      </section>

      {notice && <div className="toast"><CheckCircle2 size={16} />{notice}</div>}

      <div className="workbench">
        <aside className="incident-panel" aria-label="异常列表">
          <div className="panel-heading">
            <span>异常事件</span>
            <span className="count">3</span>
          </div>
          <div className="incident-list">
            {incidents.map((item) => (
              <button
                type="button"
                className={`incident-item ${item.id === selectedIncidentId ? "selected" : ""}`}
                key={item.id}
                onClick={() => selectIncident(item.id)}
              >
                <span className={`severity ${item.severity.toLowerCase()}`}>{item.severity}</span>
                <span className="incident-copy">
                  <span className="incident-meta">{item.code} · {item.time}</span>
                  <strong>{item.title}</strong>
                  <span>{item.line}</span>
                </span>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
          <div className="queue-health">
            <div>
              <span>数据接入</span>
              <strong>5 / 5</strong>
            </div>
            <div className="health-line"><span /></div>
            <small>ERP · MES · APS · QMS · EAM</small>
          </div>
        </aside>

        <section className="decision-canvas">
          <div className="incident-header">
            <div>
              <div className="title-row">
                <span className={`severity ${incident.severity.toLowerCase()}`}>{incident.severity}</span>
                <span className="incident-code">{incident.code}</span>
                <span className="state-badge"><CircleDot size={12} />{incident.status}</span>
              </div>
              <h1>{incident.title}</h1>
              <p>{incident.impact}</p>
            </div>
            <div className="gate-summary">
              <span><ShieldCheck size={18} />质量门</span>
              <strong>通过</strong>
              <small>8 / 8 项检查</small>
            </div>
          </div>

          <div className="fact-strip">
            {incident.facts.map((fact, index) => (
              <span key={fact}><b>0{index + 1}</b>{fact}</span>
            ))}
          </div>

          <div className="section-title">
            <div>
              <span className="eyebrow">Constraint-aware planning</span>
              <h2>候选恢复方案</h2>
            </div>
            <span className="generation-note"><Sparkles size={15} />规则与求解器生成，AI 负责解释</span>
          </div>

          <div className="plan-grid">
            {plans.map((item) => (
              <button
                type="button"
                className={`plan-card ${item.id === plan.id ? "selected" : ""}`}
                key={item.id}
                onClick={() => {
                  setSelectedPlanId(item.id);
                  setConfirmed(false);
                }}
              >
                <span className="plan-card-head">
                  <span>
                    <small>{item.label}</small>
                    <strong>{item.strategy}</strong>
                  </span>
                  {item.id === plan.id && <CheckCircle2 size={18} />}
                </span>
                <span className="score-row">
                  <b>{item.score}</b>
                  <span>综合评分</span>
                  <i className={item.risk === "低" ? "risk-low" : "risk-mid"}>{item.risk}风险</i>
                </span>
                <span className="metric-row">
                  <span><b>{item.delay}h</b>预计延期</span>
                  <span><b>{item.overtime}h</b>加班</span>
                  <span><b>{item.changes}</b>计划变更</span>
                </span>
                <span className="mini-bars" aria-label="方案指标概览">
                  <i style={{ width: `${Math.max(18, 100 - item.delay * 12)}%` }} />
                  <i style={{ width: `${Math.max(12, 100 - item.overtime * 16)}%` }} />
                  <i style={{ width: `${Math.max(16, 100 - item.changes * 4)}%` }} />
                </span>
              </button>
            ))}
          </div>

          <div className="plan-detail">
            <div className="detail-head">
              <span><Layers3 size={17} />{plan.label} · {plan.strategy}</span>
              <span className="confidence">解释置信度 0.86</span>
            </div>
            <p>{plan.rationale}</p>
            <div className="timeline">
              <div><span>09:25</span><b>冻结受影响工单</b><small>锁定当前快照，避免并发覆盖</small></div>
              <div><span>09:35</span><b>执行资源重分配</b><small>需要计划员与班组长确认</small></div>
              <div><span>13:30</span><b>恢复原设备工序</b><small>维修完成后重新评估</small></div>
            </div>
          </div>
        </section>

        <aside className="evidence-panel">
          <div className="tab-list" role="tablist" aria-label="证据与运行轨迹">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "evidence"}
              className={activeTab === "evidence" ? "active" : ""}
              onClick={() => setActiveTab("evidence")}
            >
              <FileSearch size={15} />证据
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "trace"}
              className={activeTab === "trace" ? "active" : ""}
              onClick={() => setActiveTab("trace")}
            >
              <GitBranch size={15} />Trace
            </button>
          </div>

          {activeTab === "evidence" ? (
            <div className="evidence-content">
              <div className="readiness">
                <div>
                  <Database size={18} />
                  <span><strong>数据健康门</strong><small>最近同步 10:07:18</small></span>
                </div>
                <span className="pass"><Check size={13} />通过</span>
              </div>
              <ul className="check-list">
                <li><Check size={14} /><span>排程快照</span><b>完整</b></li>
                <li><Check size={14} /><span>设备状态</span><b>12s 前</b></li>
                <li><Check size={14} /><span>物料库存</span><b>已校验</b></li>
                <li><Check size={14} /><span>人员与班次</span><b>完整</b></li>
              </ul>
              <div className="source-block">
                <span className="source-title">关键证据</span>
                <button type="button">
                  <span className="source-icon mes">M</span>
                  <span><strong>MES 设备事件</strong><small>M-17 / ERROR-083 · 09:18</small></span>
                  <ChevronRight size={15} />
                </button>
                <button type="button">
                  <span className="source-icon aps">A</span>
                  <span><strong>APS 排程快照</strong><small>snapshot-v184 · 09:17</small></span>
                  <ChevronRight size={15} />
                </button>
                <button type="button">
                  <span className="source-icon eam">E</span>
                  <span><strong>EAM 维修评估</strong><small>预计修复 4h ± 45min</small></span>
                  <ChevronRight size={15} />
                </button>
              </div>
              <div className="boundary-note">
                <LockKeyhole size={17} />
                <span><strong>执行边界</strong><small>演示环境不连接生产系统，不执行自动回写。</small></span>
              </div>
            </div>
          ) : (
            <div className="trace-content">
              {traceSteps.map(([name, detail, duration], index) => (
                <div className="trace-step" key={name}>
                  <span className="trace-index">{index + 1}</span>
                  <span><strong>{name}</strong><small>{detail}</small></span>
                  <b>{duration}</b>
                </div>
              ))}
              <div className="trace-total">
                <Activity size={16} />
                <span>总耗时</span>
                <strong>2.67 s</strong>
              </div>
            </div>
          )}

          <div className={`approval-box ${confirmed ? "confirmed" : ""}`}>
            <div>
              <UserCheck size={19} />
              <span><strong>{confirmed ? "已记录人工确认" : "等待人工确认"}</strong><small>{confirmed ? `${plan.label} 已进入受控执行队列` : "确认后仅生成执行草案"}</small></span>
            </div>
            {confirmed ? (
              <button className="secondary-button" type="button" onClick={() => setConfirmed(false)}>
                <X size={15} />撤销确认
              </button>
            ) : (
              <button className="primary-button" type="button" onClick={() => setConfirmed(true)}>
                <Check size={15} />确认 {plan.label}
              </button>
            )}
          </div>
        </aside>
      </div>
      <footer>
        <span>ReOrch Portfolio Demo · 合成数据</span>
        <span>规则/求解器负责事实与约束，LLM 负责解释与交互</span>
      </footer>
    </main>
  );
}
