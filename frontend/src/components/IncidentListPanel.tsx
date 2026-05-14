/**
 * 异常事件列表区 — 异常总览台。
 *
 * - Sort by severity (P1>P2>P3>P4) then time
 * - Show: ID, type, resource, severity, status, time, elapsed
 * - Status badges with colors from statusMapping
 * - Filter: type, severity, status, time range
 * - Top stats: active count, pending confirmation, today processed, avg response time
 * - Click → load incident context
 *
 * Requirements: 10.1-10.11
 */

import React, { useEffect, useMemo } from 'react';
import {
  Card,
  Table,
  Tag,
  Select,
  Row,
  Col,
  Statistic,
  Space,
  DatePicker,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useIncidentStore, useWorkbenchStore } from '@/stores';
import { switchIncident } from '@/stores';
import type { Incident } from '@/types';
import { IncidentSeverity, IncidentStatus, IncidentType } from '@/types';
import { incidentStatusMap } from '@/utils/statusMapping';

const { RangePicker } = DatePicker;

const SEVERITY_ORDER: Record<string, number> = {
  [IncidentSeverity.P1_CRITICAL]: 0,
  [IncidentSeverity.P2_HIGH]: 1,
  [IncidentSeverity.P3_MEDIUM]: 2,
  [IncidentSeverity.P4_LOW]: 3,
};

const severityColor: Record<string, string> = {
  [IncidentSeverity.P1_CRITICAL]: '#f5222d',
  [IncidentSeverity.P2_HIGH]: '#fa8c16',
  [IncidentSeverity.P3_MEDIUM]: '#faad14',
  [IncidentSeverity.P4_LOW]: '#8c8c8c',
};

function elapsed(occurredAt: string): string {
  const diff = dayjs().diff(dayjs(occurredAt), 'minute');
  if (diff < 60) return `${diff}分钟`;
  if (diff < 1440) return `${Math.floor(diff / 60)}小时${diff % 60}分`;
  return `${Math.floor(diff / 1440)}天`;
}

export const IncidentListPanel: React.FC = () => {
  const incidents = useIncidentStore((s) => s.incidents);
  const loading = useIncidentStore((s) => s.loading);
  const filters = useIncidentStore((s) => s.filters);
  const setFilters = useIncidentStore((s) => s.setFilters);
  const fetchIncidents = useIncidentStore((s) => s.fetchIncidents);
  const selectedId = useIncidentStore((s) => s.selectedIncidentId);
  const incidentContextId = useWorkbenchStore((s) => s.incidentContextId);

  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  // Sort: severity then time descending
  const sorted = useMemo(() => {
    return [...incidents].sort((a, b) => {
      const sa = SEVERITY_ORDER[a.severity] ?? 9;
      const sb = SEVERITY_ORDER[b.severity] ?? 9;
      if (sa !== sb) return sa - sb;
      return dayjs(b.occurred_at).valueOf() - dayjs(a.occurred_at).valueOf();
    });
  }, [incidents]);

  // Top stats
  const stats = useMemo(() => {
    const active = incidents.filter(
      (i) =>
        i.status !== IncidentStatus.CLOSED &&
        i.status !== IncidentStatus.CONFIRMED,
    ).length;
    const pending = incidents.filter(
      (i) => i.status === IncidentStatus.PENDING_CONFIRMATION,
    ).length;
    const todayProcessed = incidents.filter(
      (i) =>
        i.status === IncidentStatus.CLOSED &&
        dayjs(i.created_at).isSame(dayjs(), 'day'),
    ).length;
    const withTimes = incidents.filter(
      (i) => i.status === IncidentStatus.CONFIRMED || i.status === IncidentStatus.CLOSED,
    );
    const avgResponse =
      withTimes.length > 0
        ? Math.round(
            withTimes.reduce(
              (sum, i) => sum + dayjs(i.created_at).diff(dayjs(i.occurred_at), 'minute'),
              0,
            ) / withTimes.length,
          )
        : 0;
    return { active, pending, todayProcessed, avgResponse };
  }, [incidents]);

  const handleRowClick = (record: Incident) => {
    switchIncident(record.incident_id);
  };

  const columns: ColumnsType<Incident> = [
    {
      title: 'ID',
      dataIndex: 'incident_id',
      width: 80,
      render: (id: string) => id.slice(0, 8),
    },
    {
      title: '类型',
      dataIndex: 'incident_type',
      width: 80,
      render: (t: IncidentType) => (t === IncidentType.EQUIPMENT_FAILURE ? '设备故障' : t),
    },
    {
      title: '资源',
      dataIndex: 'resource_id',
      width: 80,
      ellipsis: true,
    },
    {
      title: '等级',
      dataIndex: 'severity',
      width: 80,
      render: (s: IncidentSeverity) => (
        <Tag color={severityColor[s]}>{s}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: IncidentStatus) => {
        const meta = incidentStatusMap[s];
        return meta ? <Tag color={meta.color}>{meta.text}</Tag> : s;
      },
    },
    {
      title: '已耗时',
      dataIndex: 'occurred_at',
      width: 80,
      render: (t: string) => elapsed(t),
    },
  ];

  return (
    <Card
      title="异常事件列表"
      size="small"
      style={{ height: '100%' }}
      bodyStyle={{ padding: 8 }}
    >
      {/* Stats row */}
      <Row gutter={8} style={{ marginBottom: 8 }}>
        <Col span={6}><Statistic title="活跃" value={stats.active} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={6}><Statistic title="待确认" value={stats.pending} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={6}><Statistic title="今日处理" value={stats.todayProcessed} valueStyle={{ fontSize: 16 }} /></Col>
        <Col span={6}><Statistic title="平均响应" value={`${stats.avgResponse}m`} valueStyle={{ fontSize: 16 }} /></Col>
      </Row>

      {/* Filters */}
      <Space wrap size={4} style={{ marginBottom: 8 }}>
        <Select
          placeholder="类型"
          allowClear
          size="small"
          style={{ width: 100 }}
          value={filters.incident_type}
          onChange={(v) => { setFilters({ ...filters, incident_type: v }); fetchIncidents(); }}
          options={[{ value: 'equipment_failure', label: '设备故障' }]}
        />
        <Select
          placeholder="等级"
          allowClear
          size="small"
          style={{ width: 100 }}
          value={filters.severity}
          onChange={(v) => { setFilters({ ...filters, severity: v }); fetchIncidents(); }}
          options={Object.values(IncidentSeverity).map((s) => ({ value: s, label: s }))}
        />
        <Select
          placeholder="状态"
          allowClear
          size="small"
          style={{ width: 100 }}
          value={filters.status}
          onChange={(v) => { setFilters({ ...filters, status: v }); fetchIncidents(); }}
          options={Object.values(IncidentStatus).map((s) => ({
            value: s,
            label: incidentStatusMap[s]?.text ?? s,
          }))}
        />
        <RangePicker
          size="small"
          style={{ width: 200 }}
          onChange={(dates) => {
            setFilters({
              ...filters,
              start_time: dates?.[0]?.toISOString(),
              end_time: dates?.[1]?.toISOString(),
            });
            fetchIncidents();
          }}
        />
      </Space>

      <Table<Incident>
        dataSource={sorted}
        columns={columns}
        rowKey="incident_id"
        size="small"
        loading={loading}
        pagination={{ pageSize: 20, size: 'small', showSizeChanger: false }}
        scroll={{ y: 400 }}
        rowClassName={(record) =>
          record.incident_id === (incidentContextId ?? selectedId)
            ? 'ant-table-row-selected'
            : ''
        }
        onRow={(record) => ({
          onClick: () => handleRowClick(record),
          style: { cursor: 'pointer' },
        })}
      />
    </Card>
  );
};
