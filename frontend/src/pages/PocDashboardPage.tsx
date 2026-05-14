import React, { useState } from 'react';
import {
  Button,
  Card,
  Col,
  Form,
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
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Row gutter={[12, 12]}>
          <Col xs={24} lg={10}>
            <Card
              size="small"
              title="PoC 价值测算"
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
              title="PoC 验收项"
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
