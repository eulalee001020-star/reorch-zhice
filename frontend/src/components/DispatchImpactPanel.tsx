/**
 * 发运影响 — 每个候选方案下，当班的货能不能按时送到。
 *
 * 生产恢复方案改变的是完工时间，客户感受到的是到货时间。这里对原计划和
 * 每个候选方案分别排线，把迟到票数和当班发不出的票数并排列出来。
 * 没有发运数据时整块不显示。
 */

import React from 'react';
import { Card, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useIncidentStore, usePlanStore } from '@/stores';
import { getDispatchImpact } from '@/api/dispatch';
import type { DispatchPlan, VehicleRoute } from '@/types';

const { Text } = Typography;

function clock(value: string): string {
  const date = new Date(value);
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

function routeLine(route: VehicleRoute): string {
  const stops = route.stops
    .map((stop) => {
      const late = stop.late_minutes > 0 ? `（迟 ${Math.round(stop.late_minutes)} 分）` : '';
      return `${stop.customer} ${clock(stop.service_start)}${late}`;
    })
    .join(' → ');
  return `${route.vehicle_id}　${clock(route.depart_at)} 发车：${stops}`;
}

export const DispatchImpactPanel: React.FC = () => {
  const incidentId = useIncidentStore((s) => s.selectedIncidentId);
  const planCount = usePlanStore((s) => s.candidatePlans.length);
  const recommendedId = usePlanStore((s) => s.planSelectionOutput?.recommended_plan_id);
  const [plans, setPlans] = React.useState<DispatchPlan[]>([]);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    if (!incidentId || planCount === 0) {
      setPlans([]);
      return undefined;
    }
    setLoading(true);
    getDispatchImpact(incidentId).then((impact) => {
      if (cancelled) return;
      setPlans(impact?.plans ?? []);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [incidentId, planCount, recommendedId]);

  if (!loading && plans.length === 0) return null;

  const columns: ColumnsType<DispatchPlan> = [
    {
      title: '方案',
      dataIndex: 'label',
      render: (label: string, plan) => (
        <span>
          {label}
          {plan.is_recommended && (
            <Tag color="green" style={{ marginLeft: 8 }}>
              推荐
            </Tag>
          )}
        </span>
      ),
    },
    {
      title: '迟到',
      dataIndex: 'late_stop_count',
      render: (count: number, plan) =>
        count > 0 ? (
          <Text type="danger">
            {count} 票 / {Math.round(plan.total_late_minutes)} 分钟
          </Text>
        ) : (
          <Text type="success">无</Text>
        ),
    },
    {
      title: '当班发不出',
      dataIndex: 'unserved_shipment_ids',
      render: (ids: string[]) =>
        ids.length > 0 ? <Text type="danger">{ids.join('、')}</Text> : <Text type="success">无</Text>,
    },
    { title: '用车', dataIndex: 'vehicles_used', render: (n: number) => `${n} 辆` },
    {
      title: '里程',
      dataIndex: 'total_distance_km',
      render: (km: number) => `${Math.round(km)} km`,
    },
  ];

  return (
    <Card
      title="发运影响"
      size="small"
      data-testid="dispatch-impact-panel"
      extra={<Text type="secondary">每票货在对应工单完工后才能装车</Text>}
    >
      <Table<DispatchPlan>
        size="small"
        rowKey={(plan) => plan.source_plan_id ?? plan.label}
        loading={loading}
        pagination={false}
        columns={columns}
        dataSource={plans}
        expandable={{
          rowExpandable: (plan) => plan.routes.length > 0,
          expandedRowRender: (plan) => (
            <div>
              {plan.routes.map((route) => (
                <div key={route.vehicle_id} style={{ fontSize: 12, lineHeight: '22px' }}>
                  {routeLine(route)}
                </div>
              ))}
            </div>
          ),
        }}
      />
    </Card>
  );
};
