/**
 * KPI 仪表盘 — Core KPI metrics with trend indicators.
 *
 * - MTTD, MTTR-D, SPI, critical order OTD, changeover rate,
 *   AI adoption rate, Override rate, case reuse rate
 * - Time trend via Ant Design Statistic cards with simple trend indicators (MVP)
 * - KPI target values with deviation alerts (> 10%)
 * - Shown in incident overview and case library pages
 *
 * Requirements: 19.1, 19.2, 19.3, 19.4
 */

import React, { useState } from 'react';
import {
  Card,
  Row,
  Col,
  Statistic,
  Tag,
  Segmented,
  Tooltip,
  Typography,
} from 'antd';
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  WarningOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  DashboardOutlined,
  SwapOutlined,
  RobotOutlined,
  UndoOutlined,
  DatabaseOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

// ---------------------------------------------------------------------------
// KPI definitions with targets
// ---------------------------------------------------------------------------

interface KPIItem {
  key: string;
  title: string;
  icon: React.ReactNode;
  suffix: string;
  target: number;
  /** Current values by granularity */
  values: Record<string, { value: number; delta: number }>;
  /** Lower is better? */
  lowerBetter: boolean;
}

const kpiData: KPIItem[] = [
  {
    key: 'mttd',
    title: 'MTTD',
    icon: <ClockCircleOutlined />,
    suffix: '秒',
    target: 5,
    values: {
      day: { value: 3.8, delta: -0.5 },
      week: { value: 4.1, delta: -0.3 },
      month: { value: 4.5, delta: -0.2 },
    },
    lowerBetter: true,
  },
  {
    key: 'mttr_d',
    title: 'MTTR-D',
    icon: <ClockCircleOutlined />,
    suffix: '分钟',
    target: 10,
    values: {
      day: { value: 6.2, delta: -1.1 },
      week: { value: 7.5, delta: -0.8 },
      month: { value: 8.3, delta: -0.5 },
    },
    lowerBetter: true,
  },
  {
    key: 'spi',
    title: 'SPI',
    icon: <DashboardOutlined />,
    suffix: '',
    target: 0.15,
    values: {
      day: { value: 0.12, delta: -0.02 },
      week: { value: 0.14, delta: -0.01 },
      month: { value: 0.16, delta: 0.01 },
    },
    lowerBetter: true,
  },
  {
    key: 'otd',
    title: '关键工单 OTD',
    icon: <CheckCircleOutlined />,
    suffix: '%',
    target: 95,
    values: {
      day: { value: 96.5, delta: 1.2 },
      week: { value: 95.8, delta: 0.5 },
      month: { value: 94.2, delta: -0.3 },
    },
    lowerBetter: false,
  },
  {
    key: 'changeover',
    title: '换型次数变化率',
    icon: <SwapOutlined />,
    suffix: '%',
    target: 5,
    values: {
      day: { value: 3.2, delta: -0.8 },
      week: { value: 4.1, delta: -0.5 },
      month: { value: 5.5, delta: 0.3 },
    },
    lowerBetter: true,
  },
  {
    key: 'ai_adoption',
    title: 'AI 采纳率',
    icon: <RobotOutlined />,
    suffix: '%',
    target: 80,
    values: {
      day: { value: 82.0, delta: 3.0 },
      week: { value: 79.5, delta: 1.5 },
      month: { value: 78.0, delta: 2.0 },
    },
    lowerBetter: false,
  },
  {
    key: 'override_rate',
    title: 'Override 率',
    icon: <UndoOutlined />,
    suffix: '%',
    target: 15,
    values: {
      day: { value: 11.0, delta: -2.0 },
      week: { value: 13.5, delta: -1.0 },
      month: { value: 14.8, delta: -0.5 },
    },
    lowerBetter: true,
  },
  {
    key: 'case_reuse',
    title: '案例复用率',
    icon: <DatabaseOutlined />,
    suffix: '%',
    target: 30,
    values: {
      day: { value: 35.0, delta: 5.0 },
      week: { value: 32.0, delta: 3.0 },
      month: { value: 28.0, delta: 1.0 },
    },
    lowerBetter: false,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isDeviationAlert(kpi: KPIItem, granularity: string): boolean {
  const v = kpi.values[granularity];
  if (!v) return false;
  const deviation = Math.abs(v.value - kpi.target) / kpi.target;
  return deviation > 0.1;
}

function trendColor(delta: number, lowerBetter: boolean): string {
  if (delta === 0) return '#8c8c8c';
  const isGood = lowerBetter ? delta < 0 : delta > 0;
  return isGood ? '#52c41a' : '#ff4d4f';
}

function trendIcon(delta: number, lowerBetter: boolean): React.ReactNode {
  if (delta === 0) return null;
  const isGood = lowerBetter ? delta < 0 : delta > 0;
  return isGood ? <ArrowDownOutlined /> : <ArrowUpOutlined />;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const KPIDashboard: React.FC = () => {
  const [granularity, setGranularity] = useState<string>('day');

  return (
    <Card
      title="KPI 仪表盘"
      size="small"
      style={{ marginBottom: 16 }}
      extra={
        <Segmented
          size="small"
          options={[
            { label: '日', value: 'day' },
            { label: '周', value: 'week' },
            { label: '月', value: 'month' },
          ]}
          value={granularity}
          onChange={(v) => setGranularity(v as string)}
        />
      }
    >
      <Row gutter={[12, 12]}>
        {kpiData.map((kpi) => {
          const v = kpi.values[granularity] ?? { value: 0, delta: 0 };
          const alert = isDeviationAlert(kpi, granularity);
          const color = trendColor(v.delta, kpi.lowerBetter);

          return (
            <Col key={kpi.key} xs={12} sm={8} md={6} lg={6} xl={3}>
              <Tooltip
                title={`目标: ${kpi.target}${kpi.suffix}${alert ? ' ⚠️ 偏离 >10%' : ''}`}
              >
                <Card
                  size="small"
                  bordered
                  style={{
                    borderColor: alert ? '#ff4d4f' : undefined,
                    background: alert ? '#fff2f0' : undefined,
                  }}
                >
                  <Statistic
                    title={
                      <span>
                        {kpi.icon}{' '}
                        <span style={{ marginLeft: 4 }}>{kpi.title}</span>
                        {alert && (
                          <WarningOutlined
                            style={{ color: '#ff4d4f', marginLeft: 4 }}
                          />
                        )}
                      </span>
                    }
                    value={v.value}
                    suffix={kpi.suffix}
                    precision={kpi.suffix === '%' || kpi.suffix === '' ? 1 : 1}
                    valueStyle={{ fontSize: 20 }}
                  />
                  <div style={{ marginTop: 4 }}>
                    <Text style={{ color, fontSize: 12 }}>
                      {trendIcon(v.delta, kpi.lowerBetter)}{' '}
                      {v.delta > 0 ? '+' : ''}
                      {v.delta}
                      {kpi.suffix}
                    </Text>
                    {alert && (
                      <Tag color="error" style={{ marginLeft: 4, fontSize: 10 }}>
                        偏离
                      </Tag>
                    )}
                  </div>
                </Card>
              </Tooltip>
            </Col>
          );
        })}
      </Row>
    </Card>
  );
};
