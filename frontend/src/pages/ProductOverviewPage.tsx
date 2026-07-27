import React from 'react';
import {
  Alert,
  Button,
  Col,
  Row,
  Space,
  Statistic,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import {
  AuditOutlined,
  BranchesOutlined,
  ClusterOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  NodeIndexOutlined,
  PlayCircleOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

interface ProductOverviewPageProps {
  onNavigate: (tab: string) => void;
}

const loopSteps = [
  { key: 'incident', no: '01', title: 'Incident', body: '设备故障、缺料、质量 hold、急单进入结构化事件流。' },
  { key: 'state', no: '02', title: 'State', body: '检索工单、物料、质量、人员、工装和资源当前状态。' },
  { key: 'constraints', no: '03', title: 'Constraints', body: '编译冻结区、资质、物料、优先级、换线和隐性规则。' },
  { key: 'options', no: '04', title: 'Options', body: '生成等待、替代资源、局部修复、插单等 Top-K 候选方案。' },
  { key: 'gate', no: '05', title: 'Gate', body: '硬约束过滤、质量门校验、风险解释和方案对比。' },
  { key: 'decision', no: '06', title: 'Decision + Feedback', body: '计划员确认、微调、驳回、Sandbox 预览与案例沉淀。' },
];

const wedgeSteps = [
  { title: '4-6 周 Design Partner PoC', body: '数据接入、场景框定、字段映射表、场景边界卡。' },
  { title: '历史异常 Replay', body: '对比计划员实际处理，形成历史 replay 报告和人工基线。' },
  { title: 'Read-only Shadow Mode', body: '实时接入、仅推荐，记录推荐、采纳、调整日志。' },
  { title: 'Sandbox Writeback Dry-run', body: '沙盒验证无生产影响，输出回写风险清单。' },
  { title: 'Sandbox 二次审批合同测试', body: '验证双人审批、短时许可和幂等；生产写回未开放。' },
  { title: '多车间 / 多异常扩展', body: '复制模板，扩展到 PCBA、半导体/光电等相邻场景。' },
];

const capabilityRows = [
  { icon: <SafetyCertificateOutlined />, title: 'DataGate', body: '字段映射、引用完整性、脱敏、权限和停损规则。', tab: 'readiness' },
  { icon: <NodeIndexOutlined />, title: 'Recovery Workbench', body: '异常接入、影响范围、局部子图求解、Top-K 取舍。', tab: 'workbench' },
  { icon: <BranchesOutlined />, title: 'Constraint Learning', body: '从反馈、驳回和微调记录抽取规则候选，先 replay 再只读发布。', tab: 'rules' },
  { icon: <AuditOutlined />, title: 'Evidence Center', body: '区分 demo、lab replay、benchmark、Design Partner 证据等级。', tab: 'evidence' },
];

const ProductOverviewPage: React.FC<ProductOverviewPageProps> = ({ onNavigate }) => {
  return (
    <div className="demo-page product-overview">
      <section className="overview-command">
        <div>
          <div className="hero-eyebrow">ReOrch 智策 · Production Exception Recovery Layer</div>
          <h1 className="hero-title">生产异常恢复决策工作台</h1>
          <div className="hero-subtitle">
            不替代 ERP、MES、APS；在主系统之上补上异常后的恢复决策层，把临场协商变成可计算、可比较、可确认、可复盘的工作流。
          </div>
          <Space wrap size={8} style={{ marginTop: 14 }}>
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => onNavigate('workbench')}>
              进入异常工作台
            </Button>
            <Button icon={<DatabaseOutlined />} onClick={() => onNavigate('readiness')}>
              检查数据就绪
            </Button>
            <Button icon={<ExperimentOutlined />} onClick={() => onNavigate('poc')}>
              查看 PoC 验收
            </Button>
          </Space>
        </div>
        <div className="command-metrics">
          <div className="metric-tile">
            <div className="metric-label">Main wedge</div>
            <div className="metric-value">CNC</div>
            <div className="metric-note">高混小批机加工设备故障恢复</div>
          </div>
          <div className="metric-tile">
            <div className="metric-label">Deployment path</div>
            <div className="metric-value">Replay</div>
            <div className="metric-note">先只读验证，再 shadow / dry-run</div>
          </div>
          <div className="metric-tile">
            <div className="metric-label">Execution boundary</div>
            <div className="metric-value">Sandbox</div>
            <div className="metric-note">双人审批；生产写回未开放</div>
          </div>
          <div className="metric-tile">
            <div className="metric-label">Current evidence</div>
            <div className="metric-value">Replay-ready</div>
            <div className="metric-note">真实车间 Design Partner = 0</div>
          </div>
        </div>
      </section>

      <Row gutter={[12, 12]}>
        <Col xs={24} xl={16}>
          <section className="product-panel">
            <div className="section-head">
              <div>
                <div className="hero-eyebrow">PRODUCT LOOP</div>
                <h2>六步异常恢复闭环</h2>
              </div>
              <Tag color="blue">Incident → Feedback</Tag>
            </div>
            <div className="closed-loop-grid">
              {loopSteps.map((step) => (
                <button
                  key={step.key}
                  className="loop-step"
                  type="button"
                  onClick={() => onNavigate(step.key === 'incident' || step.key === 'options' || step.key === 'gate' || step.key === 'decision' ? 'workbench' : 'readiness')}
                >
                  <span>{step.no}</span>
                  <strong>{step.title}</strong>
                  <Text>{step.body}</Text>
                </button>
              ))}
            </div>
          </section>
        </Col>
        <Col xs={24} xl={8}>
          <section className="product-panel">
            <div className="section-head">
              <div>
                <div className="hero-eyebrow">CATEGORY POSITIONING</div>
                <h2>三层系统边界</h2>
              </div>
              <ClusterOutlined />
            </div>
            <div className="layer-stack">
              <div className="layer-card human">
                <strong>HUMAN</strong>
                <span>计划员 · 车间班组 · 最终确认 · 反馈</span>
              </div>
              <div className="layer-arrow">↑</div>
              <div className="layer-card decision">
                <strong>ReOrch 决策层</strong>
                <span>异常 · 约束 · 候选 · 质量门 · 人工确认</span>
              </div>
              <div className="layer-arrow">↑ 只读接入</div>
              <div className="layer-card base">
                <strong>BASE</strong>
                <span>ERP · MES · APS · WMS · QMS</span>
              </div>
            </div>
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              message="系统卡位在 AI 副驾驶到 Agent 化异常决策工作流之间，默认保留人工决策权。"
            />
          </section>
        </Col>

        <Col xs={24} xl={10}>
          <section className="product-panel">
            <div className="section-head">
              <div>
                <div className="hero-eyebrow">ENGINEERING BOUNDARY</div>
                <h2>局部子图求解</h2>
              </div>
              <Tag color="green">目标：分钟级响应</Tag>
            </div>
            <div className="subgraph-flow">
              {['全厂计划', '异常影响范围', '受影响工单 / 资源', '局部恢复空间', '少量候选策略', 'Top-N 通过质量门方案'].map((item, index) => (
                <React.Fragment key={item}>
                  <div className={index === 5 ? 'subgraph-node output' : 'subgraph-node'}>{item}</div>
                  {index < 5 && <div className="subgraph-arrow">↓</div>}
                </React.Fragment>
              ))}
            </div>
            <div className="ai-boundary">
              <Tag color="purple">AI 异常理解</Tag>
              <Tag color="purple">规则候选</Tag>
              <Tag color="purple">解释学习</Tag>
              <Tag color="gold">确定性质量门</Tag>
              <Tag color="green">人工确认</Tag>
            </div>
          </section>
        </Col>

        <Col xs={24} xl={14}>
          <section className="product-panel">
            <div className="section-head">
              <div>
                <div className="hero-eyebrow">GO TO MARKET</div>
                <h2>Design Partner 到规模化阶梯</h2>
              </div>
              <Button size="small" onClick={() => onNavigate('poc')}>PoC 仪表盘</Button>
            </div>
            <Timeline
              className="wedge-timeline"
              items={wedgeSteps.map((item, index) => ({
                color: index < 3 ? 'blue' : index === 3 ? 'orange' : 'green',
                children: (
                  <div>
                    <strong>{String(index + 1).padStart(2, '0')} · {item.title}</strong>
                    <p>{item.body}</p>
                  </div>
                ),
              }))}
            />
          </section>
        </Col>

        {capabilityRows.map((item) => (
          <Col xs={24} md={12} xl={6} key={item.title}>
            <button className="capability-card" type="button" onClick={() => onNavigate(item.tab)}>
              <span className="capability-icon">{item.icon}</span>
              <strong>{item.title}</strong>
              <Text>{item.body}</Text>
            </button>
          </Col>
        ))}

        <Col xs={24}>
          <section className="product-panel validation-strip">
            <div>
              <div className="hero-eyebrow">VALIDATION</div>
              <h2>PoC 验收口径</h2>
              <Text>只把 replay、shadow、dry-run、人工确认、审计链中可复核的数据纳入证据中心。</Text>
            </div>
            <div className="validation-metrics">
              <Statistic title="目标：异常到方案时间" value="P95 ≤ 180s" />
              <Statistic title="目标：硬约束可行率" value="100%" />
              <Statistic title="目标：accept-or-adjust" value="≥ 60%" />
              <div>
                <Text type="secondary">当前客户证据</Text>
                <div style={{ marginTop: 6, fontWeight: 700 }}>0 个真实车间</div>
              </div>
            </div>
          </section>
        </Col>
      </Row>
    </div>
  );
};

export default ProductOverviewPage;
