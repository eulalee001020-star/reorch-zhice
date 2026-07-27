import React, { useState } from 'react';
import {
  Button,
  Card,
  Col,
  Form,
  Alert,
  InputNumber,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CalculatorOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { estimatePocValue } from '@/api';
import type { ValueTrackingInput, ValueTrackingReport } from '@/types';

const { Text } = Typography;

const defaultInput: ValueTrackingInput = {
  incident_count: 20,
  baseline_decision_minutes: 90,
  actual_decision_minutes: 15,
  baseline_tardiness_minutes: 360,
  actual_tardiness_minutes: 160,
  baseline_changeovers: 10,
  actual_changeovers: 7,
  baseline_overtime_hours: 18,
  actual_overtime_hours: 8,
  planner_hourly_cost: 150,
  tardiness_cost_per_minute: 30,
  changeover_cost: 600,
  overtime_hourly_cost: 220,
};

interface AcceptanceRow {
  key: string;
  metric: string;
  target: string;
  status: string;
}

const acceptanceRows: AcceptanceRow[] = [
  { key: 'response', metric: '异常到方案时间', target: 'P95 <= 180 秒', status: '待现场校准' },
  { key: 'feasible', metric: '硬约束可行率', target: '确认前 100%', status: '系统闸门' },
  { key: 'adoption', metric: '方案采纳率', target: '首月 >= 60%', status: '待试运行' },
  { key: 'roi', metric: '首季 ROI', target: '覆盖系统投入', status: '待财务确认' },
  { key: 'asset', metric: '案例沉淀', target: '>= 20 条结构化案例', status: '待累计' },
];

const acceptanceColumns: ColumnsType<AcceptanceRow> = [
  { title: '指标', dataIndex: 'metric' },
  { title: '目标', dataIndex: 'target' },
  {
    title: '状态',
    dataIndex: 'status',
    render: (status: string) => <Tag color="blue">{status}</Tag>,
  },
];

const PocDashboardPage: React.FC = () => {
  const [form] = Form.useForm<ValueTrackingInput>();
  const [report, setReport] = useState<ValueTrackingReport | null>(null);
  const [loading, setLoading] = useState(false);

  const runEstimate = async () => {
    setLoading(true);
    try {
      const values = await form.validateFields();
      setReport(await estimatePocValue(values));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="demo-page">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div className="demo-hero">
          <Row gutter={[18, 18]} align="middle">
            <Col xs={24} lg={11}>
              <div className="hero-eyebrow">PoC assumption calculator</div>
              <h1 className="hero-title">把价值假设变成可验证的 PoC 指标</h1>
              <div className="hero-subtitle">
                当前测算基于输入假设，用于设计 Design Partner 验收；不能作为已验证客户 ROI 或生产收益承诺。
              </div>
            </Col>
            <Col xs={24} lg={13}>
              <div className="metric-strip">
                <div className="metric-tile">
                  <div className="metric-label">Validation sample</div>
                  <div className="metric-value">10-30</div>
                  <div className="metric-note">脱敏历史异常 / 客户</div>
                </div>
                <div className="metric-tile">
                  <div className="metric-label">Hard gate</div>
                  <div className="metric-value">0</div>
                  <div className="metric-note">关键硬约束违例</div>
                </div>
                <div className="metric-tile">
                  <div className="metric-label">Planner review</div>
                  <div className="metric-value">60%+</div>
                  <div className="metric-note">accept-or-adjust 目标</div>
                </div>
                <div className="metric-tile">
                  <div className="metric-label">Mode</div>
                  <div className="metric-value">Shadow</div>
                  <div className="metric-note">先并行验证</div>
                </div>
              </div>
            </Col>
          </Row>
        </div>

        <Row gutter={[12, 12]}>
          <Col xs={24} lg={10}>
            <Card
              size="small"
              title="PoC 假设测算"
              extra={
                <Button
                  type="primary"
                  icon={<CalculatorOutlined />}
                  loading={loading}
                  onClick={runEstimate}
                >
                  估算
                </Button>
              }
            >
              <Form form={form} initialValues={defaultInput} layout="vertical">
                <Row gutter={8}>
                  {Object.keys(defaultInput).map((key) => (
                    <Col span={12} key={key}>
                      <Form.Item
                        label={key}
                        name={key as keyof ValueTrackingInput}
                        rules={[{ required: true }]}
                      >
                        <InputNumber min={0} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                  ))}
                </Row>
              </Form>
            </Card>
          </Col>

          <Col xs={24} lg={14}>
            <Card size="small" title="验收仪表盘">
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="以下结果基于输入假设，进入客户现场后必须由历史 replay、shadow mode 和财务口径复核。"
              />
              <Row gutter={[12, 12]}>
                <Col xs={12} md={6}>
                  <Statistic
                    title="决策节约"
                    value={report?.saved_decision_minutes ?? 0}
                    suffix="分钟/次"
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="延期减少"
                    value={report?.reduced_tardiness_minutes ?? 0}
                    suffix="分钟/次"
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="换线减少"
                    value={report?.reduced_changeovers ?? 0}
                    suffix="次/次"
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="估算节约"
                    value={report?.estimated_savings ?? 0}
                    precision={0}
                    prefix="¥"
                  />
                </Col>
              </Row>
              <div style={{ marginTop: 16 }}>
                <Text type="secondary">{report?.payback_commentary ?? '等待测算'}</Text>
              </div>
              <div style={{ marginTop: 16 }}>
                <Progress
                  percent={report ? Math.min(100, Math.round(report.estimated_savings / 1000)) : 0}
                  status={report ? 'active' : 'normal'}
                />
              </div>
            </Card>

            <Card
              size="small"
              title="Design Partner 验收项"
              style={{ marginTop: 12 }}
              extra={<CheckCircleOutlined />}
            >
              <Table
                rowKey="key"
                columns={acceptanceColumns}
                dataSource={acceptanceRows}
                size="small"
                pagination={false}
              />
            </Card>
          </Col>
        </Row>
      </Space>
    </div>
  );
};

export default PocDashboardPage;
