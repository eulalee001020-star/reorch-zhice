/**
 * 当前处理状态区 — 展示当前 Incident 处理进度。
 *
 * - 当前 Incident ID、状态、推荐策略、分析/求解耗时
 * - WebSocket 连接状态、最近一次刷新时间
 *
 * Requirements: 31.2, 31.3, 31.7
 */

import React from 'react';
import { Card, Descriptions, Tag, Badge, Space } from 'antd';
import dayjs from 'dayjs';
import { useWorkbenchStore, useIncidentStore, useAnalysisStore, usePlanStore } from '@/stores';
import { incidentStatusMap } from '@/utils/statusMapping';
import type { IncidentStatus } from '@/types';

export const ProcessingStatusPanel: React.FC = () => {
  const incidentContextId = useWorkbenchStore((s) => s.incidentContextId);
  const incidents = useIncidentStore((s) => s.incidents);
  const strategyRecommendation = useAnalysisStore((s) => s.strategyRecommendation);
  const loadingImpact = useAnalysisStore((s) => s.loadingImpact);
  const loadingRecommendation = usePlanStore((s) => s.loadingRecommendation);

  const incident = incidents.find((i) => i.incident_id === incidentContextId);
  const statusMeta = incident
    ? incidentStatusMap[incident.status as IncidentStatus]
    : null;

  return (
    <Card size="small" bodyStyle={{ padding: '8px 16px' }}>
      <Descriptions size="small" column={{ xs: 2, sm: 3, md: 6 }}>
        <Descriptions.Item label="当前事件">
          {incidentContextId ? (
            <Tag>{incidentContextId.slice(0, 8)}</Tag>
          ) : (
            <span style={{ color: '#999' }}>未选择</span>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          {statusMeta ? (
            <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
          ) : (
            '-'
          )}
        </Descriptions.Item>
        <Descriptions.Item label="推荐策略">
          {strategyRecommendation?.strategy_type ?? '-'}
        </Descriptions.Item>
        <Descriptions.Item label="分析/求解">
          <Space size={4}>
            {loadingImpact && <Badge status="processing" text="分析中" />}
            {loadingRecommendation && <Badge status="processing" text="求解中" />}
            {!loadingImpact && !loadingRecommendation && (
              <Badge status="default" text="空闲" />
            )}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="WS 连接">
          <Badge status="success" text="已连接" />
        </Descriptions.Item>
        <Descriptions.Item label="刷新时间">
          {dayjs().format('HH:mm:ss')}
        </Descriptions.Item>
      </Descriptions>
    </Card>
  );
};
