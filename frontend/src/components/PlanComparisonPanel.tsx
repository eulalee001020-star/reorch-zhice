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
  Typography,
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
import type { ComparisonMatrixRow, PlanQualityGateReport } from '@/types';
import { GanttChart } from '@/components/GanttChart';

const { Text } = Typography;

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

function gateTooltip(gate: PlanQualityGateReport): string {
  if (!gate.pass_gate) {
    return `阻断项 ${gate.hard_blockers.length} 个，策略：${gate.recommendation_policy}`;
  }
  if (gate.warnings.length > 0) {
    return gate.warnings.join('；');
  }
  return `置信度 ${gate.confidence_level}，策略：${gate.recommendation_policy}`;
}

function strategyTitle(strategyType?: string): { title: string; tag: string; color: string; desc: string } {
  const map: Record<string, { title: string; tag: string; color: string; desc: string }> = {
    wait_and_repair: {
      title: '冻结窗口局部右移',
      tag: '低扰动',
      color: 'gold',
      desc: '只移动故障资源下游受影响工序，保留未受影响订单和冻结区。',
    },
    local_repair: {
      title: '替代资源 + 队列重排序',
      tag: '系统建议',
      color: 'green',
      desc: '把关键路径工序分配到替代设备，并对瓶颈队列做交期优先与换型感知重排序。',
    },
    global_reschedule: {
      title: '滚动窗口大邻域重调度',
      tag: '备选',
      color: 'blue',
      desc: '对未来窗口执行大邻域搜索，允许跨资源重排但限制冻结区和交接班区。',
    },
  };
  return map[strategyType ?? ''] ?? {
    title: strategyType ?? '恢复候选方案',
    tag: '候选',
    color: 'default',
    desc: '基于当前异常快照生成的可比较恢复候选，需通过质量门并由计划员确认。',
  };
}

function signed(value?: number): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  const rounded = Math.round(value);
  return `${rounded > 0 ? '+' : ''}${rounded}`;
}

function metricClass(value?: number, lowerIsBetter = true): string {
  if (typeof value !== 'number' || value === 0) return 'good';
  return lowerIsBetter ? (value <= 0 ? 'good' : 'bad') : (value >= 0 ? 'good' : 'bad');
}

export const PlanComparisonPanel: React.FC = () => {
  const incidentContextId = useWorkbenchStore((s) => s.incidentContextId);
  const planSelectionOutput = usePlanStore((s) => s.planSelectionOutput);
  const selectedPlanId = usePlanStore((s) => s.selectedPlanId);
  const setSelectedPlanId = usePlanStore((s) => s.setSelectedPlanId);
  const goalMode = usePlanStore((s) => s.goalMode);
  const loadingRecommendation = usePlanStore((s) => s.loadingRecommendation);
  const candidatePlans = usePlanStore((s) => s.candidatePlans);
  const qualityGates = usePlanStore((s) => s.qualityGates);
  const matrix = planSelectionOutput?.comparison_matrix;
  const qualityGateByPlan = React.useMemo(
    () => new Map(qualityGates.map((gate) => [gate.plan_id, gate])),
    [qualityGates],
  );

  if (!incidentContextId) {
    return (
      <Card title="候选方案比较" size="small">
        <Alert message="请先选择异常事件" type="info" showIcon />
      </Card>
    );
  }

  const qualityGateTag = (planId: string) => {
    const gate = qualityGateByPlan.get(planId);
    if (!gate) {
      return <Tag color="default">质量门未校验</Tag>;
    }

    const tooltip = gateTooltip(gate);
    if (!gate.pass_gate) {
      return (
        <Tooltip title={tooltip}>
          <Tag color="red">质量门阻断</Tag>
        </Tooltip>
      );
    }

    const color = gate.confidence_level === 'high'
      ? 'green'
      : gate.confidence_level === 'medium'
        ? 'orange'
        : 'volcano';
    const label = gate.confidence_level === 'high'
      ? '质量门通过'
      : gate.confidence_level === 'medium'
        ? '质量门预警'
        : '仅供参考';

    return (
      <Tooltip title={tooltip}>
        <Tag color={color}>{label}</Tag>
      </Tooltip>
    );
  };

  const planTag = (planId: string) => {
    const tags: React.ReactNode[] = [];
    tags.push(<React.Fragment key="gate">{qualityGateTag(planId)}</React.Fragment>);
    if (planSelectionOutput) {
      if (planId === planSelectionOutput.top_scored_plan_id) {
        tags.push(<Tag key="top" color="gold">评分第一</Tag>);
      }
      if (planId === planSelectionOutput.recommended_plan_id) {
        tags.push(<Tag key="rec" color="blue">系统建议</Tag>);
      }
      if (planSelectionOutput.auto_preselected && planId === planSelectionOutput.recommended_plan_id) {
        tags.push(<Tag key="auto" color="cyan">待确认默认</Tag>);
      }
    }
    if (planId === selectedPlanId) {
      tags.push(<Tag key="sel" color="green">已选择</Tag>);
    }
    return <Space size={2} wrap>{tags}</Space>;
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

  const rankedRows = matrix?.rows.slice(0, 3) ?? [];
  const activePlanId = selectedPlanId ?? planSelectionOutput?.recommended_plan_id ?? rankedRows[0]?.plan_id;
  const activeGate = activePlanId ? qualityGateByPlan.get(activePlanId) : undefined;
  const activeRow = rankedRows.find((row) => row.plan_id === activePlanId) ?? matrix?.rows.find((row) => row.plan_id === activePlanId);

  return (
    <Card
      title="质量门后 Top-K 恢复方案"
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
          <div className="plan-card-grid">
            {rankedRows.map((row, index) => {
              const plan = candidatePlans.find((item) => item.plan_id === row.plan_id);
              const title = strategyTitle(plan?.strategy_type ?? plan?.solver_chain.strategy_type);
              const gate = qualityGateByPlan.get(row.plan_id);
              const delayDelta = row.delta_vs_baseline.max_delay_minutes;
              const changedOps = Math.abs(Math.round(row.delta_vs_baseline.changeover_count_delta ?? row.kpi_vector.changeover_count_delta ?? 0));
              const solveTime = typeof plan?.solver_metadata.solve_time_seconds === 'number'
                ? `${Math.max(1, Math.round(plan.solver_metadata.solve_time_seconds))} 秒`
                : '-';
              const hardViolations = gate?.hard_blockers.length ?? 0;
              return (
                <div
                  key={row.plan_id}
                  className={row.plan_id === activePlanId ? 'recovery-plan-card active' : 'recovery-plan-card'}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedPlanId(row.plan_id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      setSelectedPlanId(row.plan_id);
                    }
                  }}
                >
                  <div className="plan-rank">{index + 1}</div>
                  <div className="plan-main">
                    <h3>
                      {title.title}
                      <Tag color={title.color}>{title.tag}</Tag>
                      {planTag(row.plan_id)}
                    </h3>
                    <p>{title.desc}</p>
                    <div className="plan-checks">
                      <span className="plan-check">目标评分 {row.kpi_vector.normalized_score?.toFixed(2) ?? '-'}</span>
                      <span className="plan-check">{plan?.solver_chain.solver_name ?? 'solver chain'}</span>
                      <span className="plan-check">{gate?.recommendation_policy ?? 'quality gate pending'}</span>
                    </div>
                  </div>
                  <div className="plan-metrics">
                    <div className="plan-metric">
                      <label>最大延期变化</label>
                      <strong className={metricClass(delayDelta)}>{signed(delayDelta)} 分钟</strong>
                    </div>
                    <div className="plan-metric">
                      <label>换型 / 扰动</label>
                      <strong className={changedOps > 100 ? 'warn' : 'good'}>{changedOps}</strong>
                    </div>
                    <div className="plan-metric">
                      <label>求解时间</label>
                      <strong className="good">{solveTime}</strong>
                    </div>
                    <div className="plan-metric">
                      <label>硬约束违例</label>
                      <strong className={hardViolations > 0 ? 'bad' : 'good'}>{hardViolations}</strong>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="gate-summary-panel">
            <h3>质量门与推荐解释</h3>
            <div className="gate-summary-grid">
              <div className="gate-row-card">
                <span>当前方案</span>
                <strong>{activePlanId ? activePlanId.slice(0, 8) : '-'}</strong>
              </div>
              <div className="gate-row-card">
                <span>硬约束</span>
                <strong>{activeGate ? (activeGate.pass_gate ? '通过' : '阻断') : '未校验'}</strong>
              </div>
              <div className="gate-row-card">
                <span>置信度</span>
                <strong>{activeGate?.confidence_level ?? '-'}</strong>
              </div>
              <div className="gate-row-card">
                <span>综合评分</span>
                <strong>{activeRow?.kpi_vector.normalized_score?.toFixed(2) ?? '-'}</strong>
              </div>
            </div>
            <Text type="secondary">
              {planSelectionOutput?.reason_summary ?? '所有候选方案在同一异常快照下比较，系统只置顶建议项，最终由计划员确认。'}
            </Text>
          </div>

          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 10 }}
            message={
              <Space wrap size={[6, 6]}>
                <span>策略组合进入同一质量门：</span>
                <Tag>等待维修</Tag>
                <Tag>局部修复</Tag>
                <Tag>全局重排</Tag>
                <span>最终由计划员确认，不自动写回。</span>
              </Space>
            }
          />
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
