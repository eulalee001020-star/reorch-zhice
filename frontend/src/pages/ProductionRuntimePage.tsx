import React, { useState } from 'react';
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
  PlayCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { runProductionValidation } from '@/api';
import type {
  ProductionScaleResult,
  ProductionValidationRunResponse,
  RecoveryEvidenceCaseSummary,
} from '@/types';

const { Text } = Typography;

const checkLabels: Record<string, string> = {
  decomposition_and_joint_optimization: '分解与联合优化',
  operational_constraints: '生产约束',
  cdc_asof_consistency: 'CDC 与时点一致性',
  durable_queue_quota_ha: '队列、配额与 HA',
  sso_rbac: 'SSO 与 RBAC',
  shadow_execution_closure: 'Shadow 执行闭环',
  rule_candidate_replay: '规则 Replay',
  evidence_roi_ledger: '异常与 ROI 台账',
  backup_restore: '备份恢复',
  integration_control_plane: '企业接入治理',
};

function checkEvidence(key: string, row: Record<string, unknown>) {
  const tag = (label: string, color: string = 'blue') => <Tag color={color}>{label}</Tag>;
  switch (key) {
    case 'decomposition_and_joint_optimization':
      return <Space wrap>{tag('1k / 5k / 10k')}{tag('联合异常 verified', 'green')}{tag('并行 verified', 'green')}</Space>;
    case 'operational_constraints':
      return <Space wrap>{tag('全局约束 feasible', 'green')}{tag('QMS pending blocked', 'gold')}</Space>;
    case 'cdc_asof_consistency':
      return <Space wrap>{tag('gap → resume')}{tag('as-of consistent', 'green')}{tag('duplicate idempotent')}</Space>;
    case 'durable_queue_quota_ha':
      return <Space wrap>{tag('lease recovered', 'green')}{tag('checkpoint reused', 'green')}{tag('cancel verified')}</Space>;
    case 'sso_rbac':
      return <Space wrap>{tag('signature + audience', 'green')}{tag(String(row.role ?? 'role'))}{tag('客户 IdP 待接入', 'gold')}</Space>;
    case 'shadow_execution_closure':
      return <Space wrap>{tag('execution closed', 'green')}{tag(`${String(row.receipt_count ?? 0)} receipts`)}{tag('writeback 0', 'green')}</Space>;
    case 'rule_candidate_replay':
      return <Space wrap>{tag(`${String(row.passed_scenario_count ?? 0)} / ${String(row.executed_scenario_count ?? 0)} results`, 'green')}{tag('count-only rejected', 'green')}</Space>;
    case 'evidence_roi_ledger':
      return <Space wrap>{tag(`${String(row.case_count ?? 0)} cases`)}{tag('7 类异常')}{tag('客户证据门 OPEN', 'gold')}</Space>;
    case 'backup_restore':
      return <Space wrap>{tag('restore verified', 'green')}{tag('checksum verified', 'green')}</Space>;
    case 'integration_control_plane':
      return <Space wrap>{tag('6 assets active', 'green')}{tag('schema quarantine verified', 'green')}{tag('客户认证待完成', 'gold')}</Space>;
    default:
      return <Text type="secondary">-</Text>;
  }
}

const ProductionRuntimePage: React.FC = () => {
  const { message } = AntdApp.useApp();
  const [result, setResult] = useState<ProductionValidationRunResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const runValidation = async () => {
    setLoading(true);
    try {
      const response = await runProductionValidation({ scale_repetitions: 3 });
      setResult(response);
      message.success('数字孪生验收完成');
    } catch {
      message.error('数字孪生验收失败');
    } finally {
      setLoading(false);
    }
  };

  const checkRows = result
    ? Object.entries(result.checks).map(([key, value]) => ({ key, ...value }))
    : [];

  const scaleColumns: ColumnsType<ProductionScaleResult> = [
    { title: '工序', dataIndex: 'operation_count', width: 100 },
    { title: '重复', dataIndex: 'repetitions', width: 80 },
    {
      title: '结果',
      dataIndex: 'all_runs_feasible',
      width: 100,
      render: (value: boolean) => (
        <Tag color={value ? 'green' : 'red'}>{value ? 'feasible' : 'failed'}</Tag>
      ),
    },
    {
      title: 'P50',
      dataIndex: 'p50_elapsed_ms',
      render: (value: number) => `${value.toFixed(1)} ms`,
    },
    {
      title: 'P95',
      dataIndex: 'p95_elapsed_ms',
      render: (value: number) => `${value.toFixed(1)} ms`,
    },
    { title: '并行度', dataIndex: 'max_observed_parallelism', width: 90 },
    { title: '合并违规', dataIndex: 'max_global_violation_count', width: 100 },
    {
      title: '联合异常',
      dataIndex: 'joint_incident_group_verified',
      width: 110,
      render: (value: boolean) => (value ? 'verified' : 'missing'),
    },
  ];

  const caseColumns: ColumnsType<RecoveryEvidenceCaseSummary> = [
    { title: 'Case', dataIndex: 'case_id', width: 150 },
    {
      title: '异常',
      render: (_, row) => row.incident.incident_type,
      width: 170,
    },
    {
      title: '决策',
      render: (_, row) => String(row.planner_decision.decision_status ?? '-'),
      width: 100,
    },
    {
      title: '执行',
      render: (_, row) => String(row.execution_outcome.status ?? '-'),
      width: 100,
    },
    {
      title: '收益代理',
      render: (_, row) => `¥${Number(row.roi.gross_benefit ?? 0).toFixed(2)}`,
      width: 120,
    },
    {
      title: '证据指纹',
      render: (_, row) => (
        <Text copyable={{ text: row.evidence_fingerprint }}>
          {row.evidence_fingerprint.slice(0, 12)}
        </Text>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div className="page-toolbar">
          <div>
            <Typography.Title level={3} style={{ margin: 0 }}>生产运行</Typography.Title>
            <Text type="secondary">Production runtime validation</Text>
          </div>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={loading}
            onClick={runValidation}
          >
            运行验收
          </Button>
        </div>

        <Row gutter={[12, 12]}>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic
                title="技术门"
                value={result?.all_digital_twin_checks_passed ? 'PASS' : result ? 'FAIL' : '-'}
                prefix={result?.all_digital_twin_checks_passed ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                valueStyle={{ color: result?.all_digital_twin_checks_passed ? '#16803a' : undefined }}
              />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="验收项" value={result ? Object.keys(result.checks).length : 0} suffix="/ 10" />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="异常证据" value={result?.evidence_ledger.case_count ?? 0} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic
                title="客户证据门"
                value={result?.customer_evidence_gate_passed ? 'PASS' : 'OPEN'}
                valueStyle={{ color: result?.customer_evidence_gate_passed ? '#16803a' : '#ad6800' }}
              />
            </Card>
          </Col>
        </Row>

        <Tabs
          defaultActiveKey="checks"
          items={[
            {
              key: 'checks',
              label: '验收矩阵',
              children: (
                <Table
                  rowKey="key"
                  size="small"
                  pagination={false}
                  dataSource={checkRows}
                  columns={[
                    {
                      title: '能力',
                      dataIndex: 'key',
                      width: 180,
                      render: (value: string) => checkLabels[value] ?? value,
                    },
                    {
                      title: '状态',
                      dataIndex: 'status',
                      width: 110,
                      render: (value: unknown) => (
                        <Tag color={value === 'pass' ? 'green' : 'red'}>{String(value)}</Tag>
                      ),
                    },
                    {
                      title: '证据',
                      width: 450,
                      render: (_, row) => checkEvidence(String(row.key), row),
                    },
                  ]}
                  scroll={{ x: 740 }}
                  locale={{ emptyText: '尚未运行' }}
                />
              ),
            },
            {
              key: 'scale',
              label: '规模负载',
              children: (
                <Table
                  rowKey="operation_count"
                  size="small"
                  pagination={false}
                  columns={scaleColumns}
                  dataSource={result?.scale_results ?? []}
                  scroll={{ x: 900 }}
                  locale={{ emptyText: '尚未运行' }}
                />
              ),
            },
            {
              key: 'evidence',
              label: '异常证据',
              children: (
                <Table
                  rowKey="case_id"
                  size="small"
                  columns={caseColumns}
                  dataSource={result?.evidence_ledger.cases ?? []}
                  pagination={{ pageSize: 8 }}
                  scroll={{ x: 850 }}
                  locale={{ emptyText: '尚未运行' }}
                />
              ),
            },
            {
              key: 'audit',
              label: '审计',
              children: result ? (
                <Descriptions bordered size="small" column={1}>
                  <Descriptions.Item label="Run">{result.run_id}</Descriptions.Item>
                  <Descriptions.Item label="生成时间">
                    {dayjs(result.generated_at).format('YYYY-MM-DD HH:mm:ss')}
                  </Descriptions.Item>
                  <Descriptions.Item label="范围">{result.evidence_scope}</Descriptions.Item>
                  <Descriptions.Item label="Artifact">
                    <Text copyable>{result.artifact_fingerprint}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="Ledger">
                    <Text copyable>{result.evidence_ledger.ledger_fingerprint}</Text>
                  </Descriptions.Item>
                </Descriptions>
              ) : <Text type="secondary">尚未运行</Text>,
            },
          ]}
        />

        {result && (
          <Alert
            type={result.customer_evidence_gate_passed ? 'success' : 'warning'}
            showIcon
            message={result.customer_evidence_gate_passed ? '客户证据门通过' : '客户证据门未通过'}
            description={
              result.customer_evidence_gate_passed
                ? '客户历史基线、计划员决策、执行回执与损失台账已通过证据校验。'
                : '当前 10 项仅证明数字孪生技术闭环；真实客户 Shadow、客户 IdP、HA/灾备验收和已实现 ROI 仍未完成。'
            }
          />
        )}
      </Space>
    </div>
  );
};

export default ProductionRuntimePage;
