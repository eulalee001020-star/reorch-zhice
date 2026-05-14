/**
 * 候选方案比较区 — 消费 PlanSelectionOutput.comparison_matrix。
 *
 * - Table with multi-dimension scores, green/red delta coloring
 * - Plan cards: top-scored, AI recommended, auto-preselected, human-selected states
 * - "Score close" badge when < 5%
 * - Solver chain summary per plan
 * - GoalMode selector triggers refresh
 *
 * Requirements: 12.1-12.11, 31.4
 */

import React from 'react';
import {
  Card,
  Table,
  Tag,
  Select,
  Badge,
  Space,
  Spin,
  Alert,
  Button,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  useWorkbenchStore,
  usePlanStore,
  changeGoalMode,
} from '@/stores';
import { transitionView } from '@/stores';
import { GoalMode } from '@/types';
import { goalModeMap } from '@/utils/statusMapping';
import type { ComparisonMatrixRow } from '@/types';
import { GanttChart } from '@/components/GanttChart';

const KPI_LABELS: Record<string, string> = {
  delayed_order_count: '延迟工单数',
  max_delay_minutes: '最大延迟(分)',
  spi: 'SPI',
  resource_utilization_delta: '资源利用率Δ',
  changeover_count_delta: '换型次数Δ',
  critical_order_otd_impact: '关键工单OTD',
  normalized_score: '综合评分',
};

function deltaColor(value: number, key: string): string {
  // For normalized_score, higher is better; for delays, lower is better
  const higherIsBetter = key === 'normalized_score' || key === 'resource_utilization_delta';
  if (value === 0) return '#666';
  if (higherIsBetter) return value > 0 ? '#52c41a' : '#ff4d4f';
  return value < 0 ? '#52c41a' : '#ff4d4f';
}

export const PlanComparisonPanel: React.FC = () => {
  const incidentContextId = useWorkbenchStore((s) => s.incidentContextId);
  const planSelectionOutput = usePlanStore((s) => s.planSelectionOutput);
  const selectedPlanId = usePlanStore((s) => s.selectedPlanId);
  const setSelectedPlanId = usePlanStore((s) => s.setSelectedPlanId);
  const goalMode = usePlanStore((s) => s.goalMode);
  const loadingRecommendation = usePlanStore((s) => s.loadingRecommendation);
  const candidatePlans = usePlanStore((s) => s.candidatePlans);

  if (!incidentContextId) {
    return (
      <Card title="候选方案比较" size="small">
        <Alert message="请先选择异常事件" type="info" showIcon />
      </Card>
    );
  }

  const matrix = planSelectionOutput?.comparison_matrix;

  const planTag = (planId: string) => {
    const tags: React.ReactNode[] = [];
    if (planSelectionOutput) {
      if (planId === planSelectionOutput.top_scored_plan_id) {
        tags.push(<Tag key="top" color="gold">评分第一</Tag>);
      }
      if (planId === planSelectionOutput.recommended_plan_id) {
        tags.push(<Tag key="rec" color="blue">AI 推荐</Tag>);
      }
      if (planSelectionOutput.auto_preselected && planId === planSelectionOutput.recommended_plan_id) {
        tags.push(<Tag key="auto" color="cyan">自动预选</Tag>);
      }
    }
    if (planId === selectedPlanId) {
      tags.push(<Tag key="sel" color="green">已选择</Tag>);
    }
    return <Space size={2}>{tags}</Space>;
  };

  const columns: ColumnsType<ComparisonMatrixRow> = [
    {
      title: '方案',
      dataIndex: 'plan_id',
      width: 160,
      fixed: 'left',
      render: (id: string, row: ComparisonMatrixRow) => (
        <Space direction="vertical" size={2}>
          <span style={{ fontFamily: 'monospace' }}>{id.slice(0, 8)}</span>
          {planTag(id)}
          {row.is_score_close && (
            <Badge count="评分接近" style={{ backgroundColor: '#faad14' }} />
          )}
        </Space>
      ),
    },
    ...Object.keys(KPI_LABELS).map((key) => ({
      title: KPI_LABELS[key],
      dataIndex: ['kpi_vector', key],
      width: 110,
      render: (val: number, row: ComparisonMatrixRow) => {
        const delta = row.delta_vs_baseline[key];
        return (
          <Tooltip title={delta !== undefined ? `Δ ${delta >= 0 ? '+' : ''}${delta.toFixed(2)}` : ''}>
            <span>
              {typeof val === 'number' ? val.toFixed(2) : '-'}
              {delta !== undefined && delta !== 0 && (
                <span style={{ color: deltaColor(delta, key), fontSize: 11, marginLeft: 4 }}>
                  {delta >= 0 ? '↑' : '↓'}
                </span>
              )}
            </span>
          </Tooltip>
        );
      },
    })),
  ];

  // Solver chain summary per plan
  const solverSummary = (planId: string) => {
    const plan = candidatePlans.find((p) => p.plan_id === planId);
    if (!plan) return null;
    const chain = plan.solver_chain;
    return (
      <span style={{ fontSize: 11, color: '#888' }}>
        {chain.strategy_type} → {chain.solver_name} ({chain.stages.join(' → ')})
      </span>
    );
  };

  return (
    <Card
      title="候选方案比较"
      size="small"
      extra={
        <Space>
          <Button size="small" onClick={() => transitionView('incident_analysis')}>
            ← 返回分析
          </Button>
          <Select
            size="small"
            style={{ width: 130 }}
            value={goalMode}
            onChange={(mode) => {
              if (incidentContextId) changeGoalMode(incidentContextId, mode);
            }}
            options={Object.values(GoalMode).map((m) => ({
              value: m,
              label: goalModeMap[m]?.text ?? m,
            }))}
          />
        </Space>
      }
    >
      {loadingRecommendation ? (
        <Spin tip="推荐计算中...">
          <div style={{ height: 200 }} />
        </Spin>
      ) : matrix ? (
        <>
          <Table<ComparisonMatrixRow>
            dataSource={matrix.rows}
            columns={columns}
            rowKey="plan_id"
            size="small"
            pagination={false}
            scroll={{ x: 900 }}
            rowClassName={(row) =>
              row.plan_id === selectedPlanId ? 'ant-table-row-selected' : ''
            }
            onRow={(row) => ({
              onClick: () => setSelectedPlanId(row.plan_id),
              style: { cursor: 'pointer' },
            })}
          />

          {/* Solver chain summaries */}
          <div style={{ marginTop: 8 }}>
            {matrix.rows.map((row) => (
              <div key={row.plan_id} style={{ marginBottom: 4 }}>
                <Tag>{row.plan_id.slice(0, 8)}</Tag>
                {solverSummary(row.plan_id)}
              </div>
            ))}
          </div>

          {/* Gantt diff for selected plan */}
          {selectedPlanId && planSelectionOutput?.gantt_diff_payload && (
            <div style={{ marginTop: 12 }}>
              <GanttChart
                ganttDiff={planSelectionOutput.gantt_diff_payload}
                candidatePlans={candidatePlans}
                selectedPlanId={selectedPlanId}
              />
            </div>
          )}
        </>
      ) : (
        <Alert message="暂无推荐结果，请先完成影响分析和求解" type="info" showIcon />
      )}
    </Card>
  );
};
