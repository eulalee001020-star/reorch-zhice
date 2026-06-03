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

import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Input,
  InputNumber,
  Table,
  Tag,
  Select,
  Row,
  Col,
  Statistic,
  Space,
  DatePicker,
  message,
  Tabs,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useIncidentStore, useWorkbenchStore } from '@/stores';
import { switchIncident } from '@/stores';
import { createIncident, resetSandboxDemo, understandIncidentText } from '@/api';
import type { Incident } from '@/types';
import { IncidentSeverity, IncidentStatus, IncidentType, ReportSource } from '@/types';
import { incidentStatusMap } from '@/utils/statusMapping';

const { RangePicker } = DatePicker;
const { TextArea } = Input;

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
  const upsertIncident = useIncidentStore((s) => s.upsertIncident);
  const selectedId = useIncidentStore((s) => s.selectedIncidentId);
  const incidentContextId = useWorkbenchStore((s) => s.incidentContextId);
  const [agentText, setAgentText] = useState('');
  const [agentLoading, setAgentLoading] = useState(false);
  const [structuredLoading, setStructuredLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const [agentHint, setAgentHint] = useState<string | null>(null);
  const [structuredEvent, setStructuredEvent] = useState({
    resource_id: '',
    report_source: ReportSource.IOT,
    source_system: 'MES',
    criticality: 'general',
    is_bottleneck: false,
    has_redundancy: false,
    active_work_order_count: 1,
    description: '',
  });

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

  const handleAgentIntake = async () => {
    const text = agentText.trim();
    if (!text) {
      message.warning('请输入异常描述');
      return;
    }
    setAgentLoading(true);
    setAgentHint(null);
    try {
      const understood = await understandIncidentText({
        text,
        occurred_at: dayjs().toISOString(),
      });
      if (understood.requires_human_confirmation || !understood.incident_create_request) {
        setAgentHint(
          `${understood.incident_type}，置信度 ${(understood.confidence * 100).toFixed(0)}%。需人工确认后再进入求解。`,
        );
        return;
      }

      const incident = await createIncident(understood.incident_create_request);
      upsertIncident(incident);
      setAgentText('');
      await switchIncident(incident.incident_id);
      message.success('异常已创建并进入 Agent 决策流');
    } catch {
      message.error('AI 异常接入失败');
    } finally {
      setAgentLoading(false);
    }
  };

  const handleStructuredIntake = async () => {
    const resourceId = structuredEvent.resource_id.trim();
    if (!resourceId) {
      message.warning('请输入资源/设备 ID');
      return;
    }
    setStructuredLoading(true);
    setAgentHint(null);
    try {
      const incident = await createIncident({
        incident_type: IncidentType.EQUIPMENT_FAILURE,
        occurred_at: dayjs().toISOString(),
        resource_id: resourceId,
        report_source: structuredEvent.report_source,
        source_system: structuredEvent.source_system || 'structured_frontend',
        description: structuredEvent.description || `${resourceId} 设备异常`,
        raw_payload: {
          source_payload: {
            input_mode: 'structured_event_form',
          },
          resource_info: {
            criticality: structuredEvent.criticality,
            is_bottleneck: structuredEvent.is_bottleneck,
            has_redundancy: structuredEvent.has_redundancy,
            active_work_order_count: structuredEvent.active_work_order_count,
          },
        },
      });
      upsertIncident(incident);
      await switchIncident(incident.incident_id);
      message.success('结构化异常已接入并进入 Agent 决策流');
    } catch {
      message.error('结构化异常接入失败');
    } finally {
      setStructuredLoading(false);
    }
  };

  const handleLoadDemo = async () => {
    setDemoLoading(true);
    setAgentHint(null);
    try {
      const demo = await resetSandboxDemo();
      upsertIncident(demo.incident);
      await switchIncident(demo.incident.incident_id);
      message.success(
        `演示场景已加载：影响 ${demo.affected_work_order_count} 个工单 / ${demo.affected_operation_count} 道工序`,
      );
    } catch {
      message.error('演示场景加载失败');
    } finally {
      setDemoLoading(false);
    }
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

      <Tabs
        size="small"
        items={[
          {
            key: 'agent_text',
            label: 'AI 文本',
            children: (
              <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
                <TextArea
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  value={agentText}
                  onChange={(e) => setAgentText(e.target.value)}
                  placeholder="M2 设备下午坏了，估计要修三个小时"
                />
                <Button type="primary" loading={agentLoading} onClick={handleAgentIntake}>
                  AI 接入
                </Button>
              </Space.Compact>
            ),
          },
          {
            key: 'structured_event',
            label: 'MES/IoT',
            children: (
              <Space direction="vertical" size={6} style={{ width: '100%', marginBottom: 8 }}>
                <Space.Compact style={{ width: '100%' }}>
                  <Input
                    value={structuredEvent.resource_id}
                    onChange={(e) => setStructuredEvent((s) => ({ ...s, resource_id: e.target.value }))}
                    placeholder="设备/资源 ID，如 CNC-02"
                  />
                  <Select
                    value={structuredEvent.report_source}
                    style={{ width: 96 }}
                    onChange={(v) => setStructuredEvent((s) => ({ ...s, report_source: v }))}
                    options={[
                      { value: ReportSource.IOT, label: 'IoT' },
                      { value: ReportSource.MES, label: 'MES' },
                      { value: ReportSource.MANUAL, label: '人工' },
                    ]}
                  />
                </Space.Compact>
                <Input
                  value={structuredEvent.description}
                  onChange={(e) => setStructuredEvent((s) => ({ ...s, description: e.target.value }))}
                  placeholder="异常说明，可来自 MES/IoT 告警正文"
                />
                <Space wrap size={6}>
                  <Select
                    value={structuredEvent.criticality}
                    style={{ width: 120 }}
                    onChange={(v) => setStructuredEvent((s) => ({ ...s, criticality: v }))}
                    options={[
                      { value: 'high_risk_config', label: '高风险配置' },
                      { value: 'critical', label: '关键资源' },
                      { value: 'general', label: '一般资源' },
                      { value: 'non_critical', label: '非关键' },
                    ]}
                  />
                  <InputNumber
                    min={0}
                    max={999}
                    value={structuredEvent.active_work_order_count}
                    placeholder="活跃工单"
                    style={{ width: 110 }}
                    onChange={(v) => setStructuredEvent((s) => ({ ...s, active_work_order_count: Number(v ?? 0) }))}
                  />
                  <Checkbox
                    checked={structuredEvent.is_bottleneck}
                    onChange={(e) => setStructuredEvent((s) => ({ ...s, is_bottleneck: e.target.checked }))}
                  >
                    瓶颈
                  </Checkbox>
                  <Checkbox
                    checked={structuredEvent.has_redundancy}
                    onChange={(e) => setStructuredEvent((s) => ({ ...s, has_redundancy: e.target.checked }))}
                  >
                    冗余
                  </Checkbox>
                  <Button type="primary" loading={structuredLoading} onClick={handleStructuredIntake}>
                    事件接入
                  </Button>
                </Space>
              </Space>
            ),
          },
        ]}
      />
      <Button
        block
        size="small"
        loading={demoLoading}
        onClick={handleLoadDemo}
        style={{ marginBottom: 8 }}
      >
        加载演示场景
      </Button>
      {agentHint && (
        <Alert
          type="warning"
          showIcon
          message={agentHint}
          style={{ marginBottom: 8 }}
        />
      )}

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
