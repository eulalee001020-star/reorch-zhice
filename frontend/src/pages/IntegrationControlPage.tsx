import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  getIntegrationControlOverview,
  listIntegrationAssets,
  listIntegrationAudit,
  listIntegrationQuarantine,
  runIntegrationControlValidation,
} from '@/api';
import { useAuthStore } from '@/stores';
import type {
  IntegrationAuditEvent,
  IntegrationControlOverview,
  IntegrationControlValidationResult,
  IntegrationQuarantineRecord,
  VersionedIntegrationAsset,
} from '@/types';

const { Text, Title } = Typography;

const assetLabels: Record<string, string> = {
  source_authority_matrix: 'Source Authority Matrix',
  scenario_data_contract: 'Scenario Data Contract Registry',
  connector_manifest: 'Connector SDK Manifest',
  connector_conformance: 'Connector Conformance',
  constraint_definition: 'Versioned Constraint Registry',
  writeback_certification: 'Writeback Adapter Certification',
  decision_readiness_manifest: 'Decision Readiness Manifest',
};

interface CapabilityRow {
  key: string;
  asset: string;
  status: 'active' | 'blocked' | 'open';
  version: string;
  evidence: string;
}

const IntegrationControlPage: React.FC = () => {
  const { message } = AntdApp.useApp();
  const user = useAuthStore((state) => state.user);
  const [overview, setOverview] = useState<IntegrationControlOverview | null>(null);
  const [assets, setAssets] = useState<VersionedIntegrationAsset[]>([]);
  const [quarantine, setQuarantine] = useState<IntegrationQuarantineRecord[]>([]);
  const [audit, setAudit] = useState<IntegrationAuditEvent[]>([]);
  const [validation, setValidation] = useState<IntegrationControlValidationResult | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    const [overviewResult, assetResult, quarantineResult, auditResult] = await Promise.all([
      getIntegrationControlOverview(),
      listIntegrationAssets(),
      listIntegrationQuarantine(),
      listIntegrationAudit(),
    ]);
    setOverview(overviewResult);
    setAssets(assetResult);
    setQuarantine(quarantineResult);
    setAudit(auditResult);
  }, []);

  useEffect(() => {
    refresh().catch(() => message.error('接入治理数据加载失败'));
  }, [message, refresh]);

  const runValidation = async () => {
    setLoading(true);
    try {
      const result = await runIntegrationControlValidation();
      setValidation(result);
      await refresh();
      message.success('接入控制平面验收完成');
    } catch {
      message.error('仅 IT_Admin 可运行接入控制平面验收');
    } finally {
      setLoading(false);
    }
  };

  const activeByType = overview?.active_assets ?? {};
  const activeCount = Object.values(activeByType).reduce((sum, rows) => sum + rows.length, 0);
  const readiness = overview?.latest_readiness_manifest;
  const capabilityRows = useMemo<CapabilityRow[]>(() => {
    const active = (type: string) => activeByType[type]?.[0];
    const connectorReady = active('connector_manifest') && active('connector_conformance');
    const latestQuarantine = quarantine[0];
    const writebackScope = String(
      active('writeback_certification')?.payload.evidence_scope ?? '未认证',
    );
    return [
      {
        key: 'authority',
        asset: 'Source Authority Matrix',
        status: active('source_authority_matrix') ? 'active' : 'blocked',
        version: active('source_authority_matrix')?.version ?? '-',
        evidence: active('source_authority_matrix')?.fingerprint ?? '未激活',
      },
      {
        key: 'contract',
        asset: 'Scenario Data Contract Registry',
        status: active('scenario_data_contract') ? 'active' : 'blocked',
        version: active('scenario_data_contract')?.version ?? '-',
        evidence: active('scenario_data_contract')?.scope_key ?? '未激活',
      },
      {
        key: 'connector',
        asset: 'Connector SDK + Conformance Test',
        status: connectorReady ? 'active' : 'blocked',
        version: active('connector_manifest')?.version ?? '-',
        evidence: active('connector_conformance')?.fingerprint ?? '未认证',
      },
      {
        key: 'drift',
        asset: 'Schema Drift + Quarantine',
        status: overview?.open_quarantine_count ? 'open' : 'active',
        version: latestQuarantine?.schema_version ?? 'runtime',
        evidence: latestQuarantine?.fingerprint ?? '持续监测',
      },
      {
        key: 'constraint',
        asset: 'Versioned Constraint Registry',
        status: active('constraint_definition') ? 'active' : 'blocked',
        version: active('constraint_definition')?.version ?? '-',
        evidence: active('constraint_definition')?.fingerprint ?? '未激活',
      },
      {
        key: 'writeback',
        asset: 'Writeback Adapter Certification Pack',
        status: active('writeback_certification') ? 'active' : 'blocked',
        version: active('writeback_certification')?.version ?? '-',
        evidence: writebackScope,
      },
    ];
  }, [activeByType, overview?.open_quarantine_count, quarantine]);

  const capabilityColumns: ColumnsType<CapabilityRow> = [
    { title: '可复用资产', dataIndex: 'asset', width: 270 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: CapabilityRow['status']) => (
        <Tag color={value === 'active' ? 'green' : value === 'open' ? 'gold' : 'red'}>
          {value}
        </Tag>
      ),
    },
    { title: '版本', dataIndex: 'version', width: 130 },
    {
      title: '证据 / 范围',
      dataIndex: 'evidence',
      render: (value: string) => <Text className="mono-wrap">{value}</Text>,
    },
  ];

  return (
    <div className="integration-control-page">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div className="page-toolbar">
          <div>
            <Title level={3} style={{ margin: 0 }}>接入治理</Title>
            <Text type="secondary">Integration Control Plane</Text>
          </div>
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => refresh()}>刷新</Button>
            <Button
              type="primary"
              icon={<SafetyCertificateOutlined />}
              loading={loading}
              disabled={user?.role !== 'IT_Admin'}
              onClick={runValidation}
              title="IT_Admin"
            >
              运行验收
            </Button>
          </Space>
        </div>

        <Row gutter={[12, 12]}>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="Active assets" value={activeCount} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic
                title="Decision readiness"
                value={readiness?.status.toUpperCase() ?? '-'}
                prefix={readiness?.status === 'ready' ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                valueStyle={{ color: readiness?.status === 'ready' ? '#16803a' : '#ad6800' }}
              />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="Open quarantine" value={overview?.open_quarantine_count ?? 0} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic
                title="Customer writeback cert"
                value={overview?.production_writeback_certified ? 'PASS' : 'OPEN'}
                valueStyle={{ color: overview?.production_writeback_certified ? '#16803a' : '#ad6800' }}
              />
            </Card>
          </Col>
        </Row>

        <Tabs
          defaultActiveKey="assets"
          items={[
            {
              key: 'assets',
              label: '资产总览',
              children: (
                <Table
                  rowKey="key"
                  size="small"
                  pagination={false}
                  columns={capabilityColumns}
                  dataSource={capabilityRows}
                  scroll={{ x: 760 }}
                />
              ),
            },
            {
              key: 'readiness',
              label: 'Decision Readiness',
              children: readiness ? (
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <Descriptions bordered size="small" column={1}>
                    <Descriptions.Item label="Scenario">{readiness.scenario_type}</Descriptions.Item>
                    <Descriptions.Item label="Manifest">
                      <Text copyable>{readiness.manifest_id}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="Expires">
                      {dayjs(readiness.expires_at).format('YYYY-MM-DD HH:mm:ss')}
                    </Descriptions.Item>
                    <Descriptions.Item label="Evidence scope">{readiness.evidence_scope}</Descriptions.Item>
                  </Descriptions>
                  <Table
                    rowKey="check_id"
                    size="small"
                    pagination={false}
                    dataSource={readiness.checks}
                    columns={[
                      { title: '检查', dataIndex: 'check_id', width: 260 },
                      {
                        title: '等级',
                        dataIndex: 'criticality',
                        width: 90,
                        render: (value: string) => <Tag color={value === 'hard' ? 'red' : 'gold'}>{value}</Tag>,
                      },
                      {
                        title: '状态',
                        dataIndex: 'status',
                        width: 90,
                        render: (value: string) => <Tag color={value === 'pass' ? 'green' : 'red'}>{value}</Tag>,
                      },
                      { title: '结果', dataIndex: 'message' },
                    ]}
                    scroll={{ x: 760 }}
                  />
                </Space>
              ) : <Text type="secondary">尚无有效 manifest</Text>,
            },
            {
              key: 'registry',
              label: '版本注册表',
              children: (
                <Table
                  rowKey={(row) => `${row.asset_type}:${row.asset_id}:${row.version}`}
                  size="small"
                  dataSource={assets}
                  pagination={{ pageSize: 10 }}
                  columns={[
                    { title: '类型', dataIndex: 'asset_type', width: 220, render: (value: string) => assetLabels[value] ?? value },
                    { title: 'Asset ID', dataIndex: 'asset_id', width: 220 },
                    { title: '版本', dataIndex: 'version', width: 120 },
                    { title: '状态', dataIndex: 'status', width: 90, render: (value: string) => <Tag color={value === 'active' ? 'green' : 'default'}>{value}</Tag> },
                    { title: '审批人', dataIndex: 'approved_by', width: 130, render: (value?: string) => value ?? '-' },
                    { title: '指纹', dataIndex: 'fingerprint', render: (value: string) => <Text className="mono-wrap">{value}</Text> },
                  ]}
                  scroll={{ x: 980 }}
                />
              ),
            },
            {
              key: 'quarantine',
              label: '隔离队列',
              children: (
                <Table
                  rowKey="quarantine_id"
                  size="small"
                  dataSource={quarantine}
                  pagination={{ pageSize: 10 }}
                  columns={[
                    { title: 'Connector', dataIndex: 'connector_id', width: 190 },
                    { title: 'Entity', dataIndex: 'entity_type', width: 120 },
                    { title: 'Schema', dataIndex: 'schema_version', width: 150 },
                    { title: '状态', dataIndex: 'status', width: 100, render: (value: string) => <Tag color={value === 'open' ? 'red' : value === 'released' ? 'green' : 'default'}>{value}</Tag> },
                    { title: '原因', dataIndex: 'reason_codes', render: (values: string[]) => <Space wrap>{values.map((value) => <Tag key={value}>{value}</Tag>)}</Space> },
                    { title: '观测时间', dataIndex: 'observed_at', width: 170, render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm:ss') },
                  ]}
                  scroll={{ x: 920 }}
                />
              ),
            },
            {
              key: 'audit',
              label: '审计',
              children: (
                <Table
                  rowKey="event_id"
                  size="small"
                  dataSource={audit}
                  pagination={{ pageSize: 10 }}
                  columns={[
                    { title: '时间', dataIndex: 'created_at', width: 170, render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm:ss') },
                    { title: '动作', dataIndex: 'action', width: 230 },
                    { title: '资产', dataIndex: 'asset_type', width: 210, render: (value?: string) => value ? assetLabels[value] ?? value : '-' },
                    { title: 'Actor', dataIndex: 'actor_id', width: 150 },
                    { title: 'Asset ID', dataIndex: 'asset_id', render: (value?: string) => value ?? '-' },
                  ]}
                  scroll={{ x: 900 }}
                />
              ),
            },
          ]}
        />

        <Alert
          type={validation?.all_checks_passed ? 'success' : 'warning'}
          showIcon
          message={validation?.all_checks_passed ? '数字孪生接入治理门通过' : '客户接入证据门仍开放'}
          description={
            validation?.all_checks_passed
              ? '已验证六项资产的技术闭环；当前证据范围仍为 digital_twin。'
              : '需由 IT_Admin 导入并激活客户权威来源、场景合同、Connector conformance 与 Sandbox 回写认证。'
          }
        />
      </Space>
    </div>
  );
};

export default IntegrationControlPage;
