/**
 * 影响范围分析区 — 异常详情 + 影响报告 + 策略推荐。
 *
 * - Incident info, impact report (affected WOs, risk levels, total delay)
 * - Strategy recommendation
 * - Progress indicator while analyzing
 * - Timeline of incident lifecycle
 * - "View candidate plans" button to switch view
 *
 * Requirements: 11.1-11.9
 */

import React from 'react';
import {
  Card,
  Descriptions,
  Table,
  Tag,
  Button,
  Timeline,
  Statistic,
  Row,
  Col,
  Spin,
  Alert,
  Space,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  useWorkbenchStore,
  useIncidentStore,
  useAnalysisStore,
  usePlanStore,
} from '@/stores';
import { transitionView, canEnterPlanSelection } from '@/stores';
import type { AffectedWorkOrder } from '@/types';
import { DeliveryRiskLevel, IncidentType } from '@/types';
import { incidentStatusMap } from '@/utils/statusMapping';
import type { IncidentStatus } from '@/types';

const riskColor: Record<string, string> = {
  [DeliveryRiskLevel.SAFE]: '#52c41a',
  [DeliveryRiskLevel.WARNING]: '#faad14',
  [DeliveryRiskLevel.BREACH]: '#ff4d4f',
};

const riskText: Record<string, string> = {
  [DeliveryRiskLevel.SAFE]: '安全',
  [DeliveryRiskLevel.WARNING]: '预警',
  [DeliveryRiskLevel.BREACH]: '违约',
};

const severityColor: Record<string, string> = {
  'P1-Critical': '#f5222d',
  'P2-High': '#fa541c',
  'P3-Medium': '#faad14',
  'P4-Low': '#52c41a',
};

const severitySourceText: Record<string, string> = {
  anomaly_intake_center: '接入中心',
  incident_payload: '上游事件',
};

const severityFactorText: Record<string, string> = {
  resource_id: '资源',
  report_source: '来源',
  classified_severity: '初始结果',
  resource_criticality: '资源关键性',
  is_bottleneck: '瓶颈',
  has_redundancy: '冗余',
  active_work_order_count: '活跃工单',
};

function formatSeverityFactor(value: unknown): string {
  if (typeof value === 'boolean') {
    return value ? '是' : '否';
  }
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  return String(value);
}

export const ImpactAnalysisPanel: React.FC = () => {
  const incidentContextId = useWorkbenchStore((s) => s.incidentContextId);
  const incidents = useIncidentStore((s) => s.incidents);
  const impactReport = useAnalysisStore((s) => s.impactReport);
  const strategyRec = useAnalysisStore((s) => s.strategyRecommendation);
  const loadingImpact = useAnalysisStore((s) => s.loadingImpact);
  const loadingStrategy = useAnalysisStore((s) => s.loadingStrategy);
  const candidatePlans = usePlanStore((s) => s.candidatePlans);

  const incident = incidents.find((i) => i.incident_id === incidentContextId);

  if (!incidentContextId || !incident) {
    return (
      <Card title="影响范围分析" size="small">
        <Alert message="请从左侧选择一个异常事件" type="info" showIcon />
      </Card>
    );
  }

  const statusMeta = incidentStatusMap[incident.status as IncidentStatus];

  const woColumns: ColumnsType<AffectedWorkOrder> = [
    { title: '工单号', dataIndex: 'work_order_id', width: 100 },
    { title: '产品', dataIndex: 'product_name', width: 100, ellipsis: true },
    {
      title: '交期',
      dataIndex: 'due_date',
      width: 100,
      render: (d: string) => dayjs(d).format('MM-DD HH:mm'),
    },
    {
      title: '风险',
      dataIndex: 'delivery_risk_level',
      width: 70,
      render: (r: DeliveryRiskLevel) => (
        <Tag color={riskColor[r]}>{riskText[r] ?? r}</Tag>
      ),
    },
    {
      title: '缓冲(分)',
      dataIndex: 'remaining_buffer_minutes',
      width: 80,
      render: (v: number) => Math.round(v),
    },
  ];

  const canSwitch = canEnterPlanSelection();
  const severityExplanation = impactReport?.severity_explanation ?? null;
  const severityFactors = severityExplanation
    ? Object.entries(severityExplanation.factors).filter(
        ([, value]) => value !== null && value !== undefined && value !== '',
      )
    : [];

  return (
    <Card
      title="影响范围分析"
      size="small"
      extra={
        <Button
          type="primary"
          size="small"
          disabled={!canSwitch}
          onClick={() => transitionView('multi_plan_selection')}
        >
          查看候选方案 →
        </Button>
      }
    >
      {/* Incident info */}
      <Descriptions size="small" column={3} bordered style={{ marginBottom: 12 }}>
        <Descriptions.Item label="异常类型">
          {incident.incident_type === IncidentType.EQUIPMENT_FAILURE ? '设备故障' : incident.incident_type}
        </Descriptions.Item>
        <Descriptions.Item label="发生时间">
          {dayjs(incident.occurred_at).format('YYYY-MM-DD HH:mm')}
        </Descriptions.Item>
        <Descriptions.Item label="资源">{incident.resource_id}</Descriptions.Item>
        <Descriptions.Item label="严重等级">
          <Tag color={severityColor[incident.severity] ?? '#faad14'}>{incident.severity}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          {statusMeta ? <Tag color={statusMeta.color}>{statusMeta.text}</Tag> : incident.status}
        </Descriptions.Item>
        <Descriptions.Item label="来源">{incident.report_source}</Descriptions.Item>
      </Descriptions>

      {/* Impact report */}
      {loadingImpact ? (
        <Spin tip="影响分析中...">
          <div style={{ height: 100 }} />
        </Spin>
      ) : impactReport ? (
        <>
          <Row gutter={12} style={{ marginBottom: 12 }}>
            <Col span={6}>
              <Statistic
                title="受影响工单"
                value={impactReport.affected_work_orders.length}
                valueStyle={{ fontSize: 18 }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="受影响工序"
                value={impactReport.affected_operations.length}
                valueStyle={{ fontSize: 18 }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="预估总延迟"
                value={Math.round(impactReport.estimated_total_delay_minutes)}
                suffix="分钟"
                valueStyle={{ fontSize: 18 }}
              />
            </Col>
            <Col span={6}>
              <Space direction="vertical" size={0}>
                {Object.entries(impactReport.delivery_risk_distribution).map(
                  ([level, count]) => (
                    <Tag key={level} color={riskColor[level]}>
                      {riskText[level] ?? level}: {count}
                    </Tag>
                  ),
                )}
              </Space>
            </Col>
          </Row>

          {impactReport.severity_upgraded && (
            <Alert
              message={`严重等级已升级至 ${impactReport.upgraded_severity}`}
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
            />
          )}

          {severityExplanation && (
            <div
              style={{
                border: '1px solid #f0f0f0',
                borderRadius: 6,
                padding: 12,
                marginBottom: 12,
                background: '#fafafa',
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 8 }}>严重等级依据</div>
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="初始等级">
                  <Tag color={severityColor[severityExplanation.initial_severity]}>
                    {severityExplanation.initial_severity}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="生效等级">
                  <Tag color={severityColor[severityExplanation.effective_severity]}>
                    {severityExplanation.effective_severity}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="依据来源">
                  {severitySourceText[severityExplanation.source] ?? severityExplanation.source}
                </Descriptions.Item>
                <Descriptions.Item label="Breach 工单">
                  {severityExplanation.breach_work_order_count}
                </Descriptions.Item>
                <Descriptions.Item label="初始分级规则" span={2}>
                  {severityExplanation.classification_rule}
                </Descriptions.Item>
                {severityExplanation.upgrade_rule && (
                  <Descriptions.Item label="升级规则" span={2}>
                    {severityExplanation.upgrade_rule}
                  </Descriptions.Item>
                )}
                {severityExplanation.upgrade_reason && (
                  <Descriptions.Item label="影响分析结论" span={2}>
                    {severityExplanation.upgrade_reason}
                  </Descriptions.Item>
                )}
              </Descriptions>
              {severityFactors.length > 0 && (
                <Space wrap size={[4, 4]} style={{ marginTop: 8 }}>
                  {severityFactors.map(([key, value]) => (
                    <Tag key={key}>
                      {severityFactorText[key] ?? key}: {formatSeverityFactor(value)}
                    </Tag>
                  ))}
                </Space>
              )}
            </div>
          )}

          <Table<AffectedWorkOrder>
            dataSource={impactReport.affected_work_orders}
            columns={woColumns}
            rowKey="work_order_id"
            size="small"
            pagination={false}
            scroll={{ y: 200 }}
          />
        </>
      ) : null}

      {/* Strategy recommendation */}
      {loadingStrategy ? (
        <Spin tip="策略分析中..." style={{ marginTop: 12 }}>
          <div style={{ height: 60 }} />
        </Spin>
      ) : strategyRec ? (
        <Card
          type="inner"
          size="small"
          title="策略推荐"
          style={{ marginTop: 12 }}
        >
          <Descriptions size="small" column={2}>
            <Descriptions.Item label="策略类型">
              <Tag color="#1677ff">{strategyRec.strategy_type}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="置信度">
              {(strategyRec.confidence * 100).toFixed(0)}%
            </Descriptions.Item>
          </Descriptions>
          <div style={{ marginTop: 4, fontSize: 13, color: '#666' }}>
            {strategyRec.reasoning}
          </div>
        </Card>
      ) : null}

      {/* Incident timeline */}
      <Card type="inner" size="small" title="事件时间线" style={{ marginTop: 12 }}>
        <Timeline
          items={[
            {
              color: 'blue',
              children: `异常发生 ${dayjs(incident.occurred_at).format('HH:mm:ss')}`,
            },
            {
              color: 'blue',
              children: `系统接入 ${dayjs(incident.created_at).format('HH:mm:ss')}`,
            },
            ...(impactReport
              ? [{ color: 'green' as const, children: '影响分析完成' }]
              : []),
            ...(strategyRec
              ? [{ color: 'green' as const, children: `策略推荐: ${strategyRec.strategy_type}` }]
              : []),
            ...(candidatePlans.length > 0
              ? [{ color: 'green' as const, children: `已生成 ${candidatePlans.length} 个候选方案` }]
              : []),
          ]}
        />
      </Card>
    </Card>
  );
};
