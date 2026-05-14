import React, { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ApiOutlined, PlayCircleOutlined, ScheduleOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { generateInitialSchedules, runDigitalTwinSample } from '@/api';
import type {
  DigitalTwinRunResponse,
  InitialScheduleOption,
  InitialScheduleRequest,
} from '@/types';

const { Text } = Typography;

function buildSampleRequest(): InitialScheduleRequest {
  const start = dayjs('2026-05-12T08:00:00+08:00');
  return {
    workshop_id: 'WS-HMLV-01',
    planning_start: start.toISOString(),
    goal_modes: [
      'delivery_priority',
      'throughput_priority',
      'bottleneck_priority',
      'cost_priority',
      'balanced',
    ],
    max_solutions: 5,
    time_budget_seconds: 8,
    resources: [
      {
        resource_id: 'CNC-01',
        name: 'CNC Makino A51',
        capabilities: ['milling', 'drilling'],
        is_bottleneck: true,
        has_redundancy: false,
        criticality: 'bottleneck',
        cost_per_minute: 6,
      },
      {
        resource_id: 'CNC-02',
        name: 'CNC Brother S700',
        capabilities: ['milling', 'drilling'],
        is_bottleneck: false,
        has_redundancy: true,
        criticality: 'general',
        cost_per_minute: 4,
      },
      {
        resource_id: 'QC-01',
        name: 'CMM Inspection',
        capabilities: ['inspection'],
        is_bottleneck: false,
        has_redundancy: false,
        criticality: 'quality_gate',
        cost_per_minute: 5,
      },
    ],
    resource_calendar: [
      {
        resource_id: 'CNC-02',
        window_start: start.add(4, 'hour').toISOString(),
        window_end: start.add(5.5, 'hour').toISOString(),
        availability_type: 'unavailable',
        reason: 'tool calibration',
      },
    ],
    changeover_rules: [
      { from_product_family: 'A', to_product_family: 'B', setup_minutes: 20, cost: 500 },
      { from_product_family: 'B', to_product_family: 'A', setup_minutes: 20, cost: 500 },
      { from_product_family: 'A', to_product_family: 'C', setup_minutes: 35, cost: 700 },
      { from_product_family: 'C', to_product_family: 'A', setup_minutes: 35, cost: 700 },
    ],
    work_orders: [
      {
        work_order_id: 'WO-9001',
        product_name: 'Servo housing',
        product_family: 'A',
        priority: 3,
        due_date: start.add(10, 'hour').toISOString(),
        operations: [
          {
            operation_id: 'WO-9001-10',
            work_order_id: 'WO-9001',
            duration_minutes: 150,
            eligible_resource_ids: ['CNC-01', 'CNC-02'],
            required_capabilities: ['milling'],
            predecessor_ids: [],
            product_family: 'A',
            material_requirements: [
              {
                material_id: 'AL-6061',
                required_quantity: 1,
                available_at: start.toISOString(),
                status: 'available',
              },
            ],
          },
          {
            operation_id: 'WO-9001-20',
            work_order_id: 'WO-9001',
            duration_minutes: 70,
            eligible_resource_ids: ['QC-01'],
            required_capabilities: ['inspection'],
            predecessor_ids: ['WO-9001-10'],
            product_family: 'A',
            material_requirements: [],
          },
        ],
      },
      {
        work_order_id: 'WO-9002',
        product_name: 'Valve block urgent',
        product_family: 'C',
        priority: 4,
        due_date: start.add(8, 'hour').toISOString(),
        operations: [
          {
            operation_id: 'WO-9002-10',
            work_order_id: 'WO-9002',
            duration_minutes: 95,
            eligible_resource_ids: ['CNC-01', 'CNC-02'],
            required_capabilities: ['milling'],
            predecessor_ids: [],
            product_family: 'C',
            material_requirements: [
              {
                material_id: 'AL-7075',
                required_quantity: 1,
                available_at: start.add(1, 'hour').toISOString(),
                status: 'reserved',
              },
            ],
          },
          {
            operation_id: 'WO-9002-20',
            work_order_id: 'WO-9002',
            duration_minutes: 45,
            eligible_resource_ids: ['QC-01'],
            required_capabilities: ['inspection'],
            predecessor_ids: ['WO-9002-10'],
            product_family: 'C',
            material_requirements: [],
          },
        ],
      },
    ],
  };
}

const columns: ColumnsType<InitialScheduleOption> = [
  {
    title: '方案',
    dataIndex: 'label',
    render: (label: string, row) => (
      <Space direction="vertical" size={2}>
        <span>{label}</span>
        <Tag>{row.goal_mode}</Tag>
      </Space>
    ),
  },
  {
    title: 'OTD',
    dataIndex: ['kpis', 'otd_rate'],
    render: (v: number) => `${((v ?? 0) * 100).toFixed(1)}%`,
  },
  {
    title: '完工时间',
    dataIndex: ['kpis', 'makespan_minutes'],
    render: (v: number) => `${Number(v ?? 0).toFixed(0)} 分`,
  },
  {
    title: '延期',
    dataIndex: ['kpis', 'total_tardiness_minutes'],
    render: (v: number) => `${Number(v ?? 0).toFixed(0)} 分`,
  },
  {
    title: '换线',
    dataIndex: ['kpis', 'changeover_count'],
  },
  {
    title: '瓶颈利用',
    dataIndex: ['kpis', 'bottleneck_utilization'],
    render: (v: number) => `${((v ?? 0) * 100).toFixed(1)}%`,
  },
  {
    title: '资源成本',
    dataIndex: ['kpis', 'estimated_resource_cost'],
    render: (v: number) => Number(v ?? 0).toFixed(0),
  },
];

const InitialSchedulingPage: React.FC = () => {
  const sampleRequest = useMemo(() => buildSampleRequest(), []);
  const [loading, setLoading] = useState(false);
  const [options, setOptions] = useState<InitialScheduleOption[]>([]);
  const [readiness, setReadiness] = useState<string>('未运行');
  const [digitalTwin, setDigitalTwin] = useState<DigitalTwinRunResponse | null>(null);
  const [summary, setSummary] = useState({
    resources: sampleRequest.resources.length,
    workOrders: sampleRequest.work_orders.length,
    constraints: sampleRequest.changeover_rules.length + sampleRequest.resource_calendar.length,
  });
  const [error, setError] = useState<string | null>(null);

  const runInitial = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await generateInitialSchedules(sampleRequest);
      setOptions(response.options);
      setReadiness(
        `${response.readiness_report.readiness_score.toFixed(2)} / ${
          response.readiness_report.is_ready ? 'ready' : 'blocked'
        }`,
      );
      setSummary({
        resources: sampleRequest.resources.length,
        workOrders: sampleRequest.work_orders.length,
        constraints: sampleRequest.changeover_rules.length + sampleRequest.resource_calendar.length,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成失败');
    } finally {
      setLoading(false);
    }
  };

  const runTwin = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await runDigitalTwinSample();
      setDigitalTwin(response);
      setOptions(response.initial_schedule.options);
      setReadiness(
        `${response.initial_schedule.readiness_report.readiness_score.toFixed(2)} / ${
          response.initial_schedule.readiness_report.is_ready ? 'ready' : 'blocked'
        }`,
      );
      const raw = response.baseline_snapshot?.raw_data as
        | {
            resources?: unknown[];
            work_orders?: unknown[];
            resource_calendar?: unknown[];
            changeover_rules?: unknown[];
          }
        | undefined;
      setSummary({
        resources: raw?.resources?.length ?? 0,
        workOrders: raw?.work_orders?.length ?? 0,
        constraints:
          (raw?.resource_calendar?.length ?? 0) + (raw?.changeover_rules?.length ?? 0),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '数字孪生运行失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Card
          size="small"
          title="初始调度"
          extra={
            <Space>
              <Button icon={<ScheduleOutlined />} onClick={runInitial}>
                生成多方案
              </Button>
              <Button type="primary" icon={<PlayCircleOutlined />} onClick={runTwin}>
                运行数字孪生
              </Button>
            </Space>
          }
        >
          {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
          <Row gutter={[12, 12]}>
            <Col xs={12} md={6}>
              <Statistic title="数据就绪" value={readiness} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="资源" value={summary.resources} suffix="台/工位" />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="工单" value={summary.workOrders} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="约束" value={summary.constraints} />
            </Col>
          </Row>
        </Card>

        <Spin spinning={loading}>
          <Card size="small" title="方案列表">
            <Table
              rowKey={(row) => row.candidate_plan.plan_id}
              columns={columns}
              dataSource={options}
              size="small"
              pagination={false}
            />
          </Card>

          {digitalTwin && (
            <Card
              size="small"
              title="数字孪生结果"
              style={{ marginTop: 12 }}
              extra={<ApiOutlined />}
            >
              <Descriptions size="small" column={{ xs: 1, md: 3 }} bordered>
                <Descriptions.Item label="场景">{digitalTwin.scenario_id}</Descriptions.Item>
                <Descriptions.Item label="异常资源">
                  {String(digitalTwin.incident?.resource_id ?? '-')}
                </Descriptions.Item>
                <Descriptions.Item label="重排候选">
                  {digitalTwin.reschedule_candidates.length}
                </Descriptions.Item>
                <Descriptions.Item label="策略">
                  {String(digitalTwin.strategy?.strategy_type ?? '-')}
                </Descriptions.Item>
                <Descriptions.Item label="回写指令">
                  {digitalTwin.writeback_preview?.instruction_count ?? 0}
                </Descriptions.Item>
                <Descriptions.Item label="估算节约">
                  {digitalTwin.value_report?.estimated_savings ?? 0}
                </Descriptions.Item>
              </Descriptions>
              <div style={{ marginTop: 12 }}>
                <Text type="secondary">
                  {digitalTwin.quality_gates
                    .map((gate) => `${gate.plan_id.slice(0, 8)}: ${gate.confidence_level}`)
                    .join(' | ')}
                </Text>
              </div>
            </Card>
          )}
        </Spin>
      </Space>
    </div>
  );
};

export default InitialSchedulingPage;
