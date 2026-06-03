import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  StopOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  listNgsPlannerDecisions,
  recordNgsPlannerDecision,
  runNgsLabBatchReplay,
} from '@/api';
import type {
  NgsAgentTraceStep,
  NgsBatchReplayResponse,
  NgsGateIssue,
  NgsLabDemoResponse,
  NgsPlannerDecisionRecord,
  NgsRepairCandidate,
  NgsReplayCaseResult,
} from '@/types';

const { Text } = Typography;

const uploadedPackageTemplate = JSON.stringify(
  {
    package_id: 'uploaded-ngs-package',
    version: 'v-test',
    cases: [
      {
        case_id: 'LAB_UPLOAD',
        scenario_id: 'uploaded_reagent_scenario',
        description: 'Uploaded single-case replay package',
        expected: {
          min_feasible: 1,
          min_rejected: 1,
          recommended_strategy: 'reagent_repair',
        },
      },
    ],
  },
  null,
  2,
);

function gateColor(status?: string): string {
  if (status === 'block') {
    return 'red';
  }
  if (status === 'warning') {
    return 'orange';
  }
  return 'green';
}

function issueColor(issue: NgsGateIssue): string {
  return issue.severity === 'blocker' ? 'red' : 'orange';
}

const NgsLabPage: React.FC = () => {
  const [batch, setBatch] = useState<NgsBatchReplayResponse | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [packageText, setPackageText] = useState(uploadedPackageTemplate);
  const [selectedDecisionCandidateId, setSelectedDecisionCandidateId] = useState<string | null>(null);
  const [plannerReason, setPlannerReason] = useState('');
  const [decisions, setDecisions] = useState<NgsPlannerDecisionRecord[]>([]);
  const [decisionLoading, setDecisionLoading] = useState(false);

  const run = async (payload?: Record<string, unknown>, sourceName?: string) => {
    setLoading(true);
    try {
      const nextBatch = await runNgsLabBatchReplay(
        payload ? { package_payload: payload, source_name: sourceName ?? 'uploaded_ngs_package.json' } : undefined,
      );
      setBatch(nextBatch);
      setSelectedCaseId(nextBatch.case_results[0]?.case_id ?? null);
      setDecisions(await listNgsPlannerDecisions({ package_id: nextBatch.package_id }));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void run();
  }, []);

  const selectedCase = useMemo<NgsReplayCaseResult | null>(() => {
    if (!batch?.case_results.length) return null;
    return (
      batch.case_results.find((item) => item.case_id === selectedCaseId) ??
      batch.case_results[0]
    );
  }, [batch, selectedCaseId]);
  const data: NgsLabDemoResponse | null = selectedCase?.response ?? null;
  const recommended = data?.recommended_candidate ?? null;
  const recommendedGateRows = useMemo(
    () => Object.entries(recommended?.gate_report?.gate_summary ?? {}),
    [recommended],
  );

  useEffect(() => {
    setSelectedDecisionCandidateId(recommended?.candidate_id ?? null);
    setPlannerReason('');
  }, [recommended?.candidate_id, selectedCaseId]);

  const runUploadedPackage = async () => {
    try {
      const payload = JSON.parse(packageText) as Record<string, unknown>;
      await run(payload, 'uploaded_ngs_package.json');
      message.success('已读取上传实验包并完成 batch replay');
    } catch {
      message.error('实验包 JSON 无法解析或不符合 cases 结构');
    }
  };

  const submitPlannerDecision = async (action: 'confirm' | 'reject' | 'override') => {
    if (!batch || !selectedCase) return;
    if (action === 'confirm' && !recommended?.candidate_id) {
      message.warning('没有推荐候选，不能确认');
      return;
    }
    if (action !== 'confirm' && !plannerReason.trim()) {
      message.warning('驳回或 override 必须填写原因');
      return;
    }
    setDecisionLoading(true);
    try {
      const response = await recordNgsPlannerDecision({
        package_id: batch.package_id,
        case_id: selectedCase.case_id,
        action,
        selected_candidate_id:
          action === 'reject'
            ? null
            : action === 'confirm'
              ? recommended?.candidate_id
              : selectedDecisionCandidateId,
        planner_id: 'planner-1',
        reason: action === 'reject' ? plannerReason : null,
        override_reason: action === 'override' ? plannerReason : null,
      });
      setDecisions(response.records);
      setPlannerReason('');
      message.success('已记录计划员决策，未执行 LIMS 写回');
    } catch {
      message.error('记录计划员决策失败');
    } finally {
      setDecisionLoading(false);
    }
  };

  const feasibleColumns: ColumnsType<NgsRepairCandidate> = [
    {
      title: '候选方案',
      dataIndex: 'label',
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{row.label}</Text>
          <Text type="secondary">{row.strategy_type}</Text>
        </Space>
      ),
    },
    {
      title: 'Hard gate',
      width: 120,
      render: (_, row) => (
        <Tag color={row.hard_feasible ? 'green' : 'red'}>
          {row.hard_feasible ? 'pass' : 'block'}
        </Tag>
      ),
    },
    { title: 'Soft score', dataIndex: 'soft_score', width: 120 },
    { title: 'WT', dataIndex: 'weighted_tardiness_minutes', width: 90 },
    { title: 'Urgent TAT', dataIndex: 'urgent_tardiness_minutes', width: 120 },
    { title: 'Rescue burden', dataIndex: 'rescue_burden', width: 130 },
    {
      title: '说明',
      dataIndex: 'explanation',
      render: (value: string) => <Text type="secondary">{value}</Text>,
    },
  ];

  const batchColumns: ColumnsType<NgsReplayCaseResult> = [
    {
      title: 'Replay case',
      dataIndex: 'case_id',
      width: 110,
      render: (value: string, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary">{row.scenario_id}</Text>
        </Space>
      ),
    },
    {
      title: '结果',
      width: 100,
      render: (_, row) => (
        <Tag color={row.pass_replay ? 'green' : 'red'}>
          {row.pass_replay ? 'pass' : 'fail'}
        </Tag>
      ),
    },
    {
      title: '推荐策略',
      render: (_, row) => row.response.recommended_candidate?.strategy_type ?? '-',
    },
    {
      title: '期望策略',
      dataIndex: 'expected_recommended_strategy',
      render: (value?: string | null) => value ?? '-',
    },
    {
      title: 'Feasible / Rejected',
      width: 150,
      render: (_, row) =>
        `${row.response.feasible_candidates.length} / ${row.response.rejected_candidates.length}`,
    },
  ];

  const rejectedColumns: ColumnsType<NgsRepairCandidate> = [
    {
      title: '被拒候选',
      dataIndex: 'label',
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{row.label}</Text>
          <Text type="secondary">{row.strategy_type}</Text>
        </Space>
      ),
    },
    {
      title: '阻断 gate',
      render: (_, row) => (
        <Space size={[4, 4]} wrap>
          {(row.gate_report?.hard_blockers ?? []).slice(0, 6).map((issue, index) => (
            <Tag
              key={`${row.candidate_id}-${issue.gate}-${issue.entity_id}-${index}`}
              color={issueColor(issue)}
            >
              {issue.gate}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '首个阻断原因',
      render: (_, row) => row.gate_report?.hard_blockers[0]?.message ?? '-',
    },
  ];

  const traceColumns: ColumnsType<NgsAgentTraceStep> = [
    {
      title: 'Agent',
      dataIndex: 'agent_name',
      width: 210,
      render: (value: string) => <Text strong>{value}</Text>,
    },
    {
      title: '决策输出',
      dataIndex: 'decision',
      render: (value: string) => <Text>{value}</Text>,
    },
    {
      title: '边界',
      dataIndex: 'boundary',
      render: (value: string) => <Text type="secondary">{value}</Text>,
    },
    {
      title: 'Confidence',
      dataIndex: 'confidence',
      width: 120,
      render: (value: number) => `${Math.round(value * 100)}%`,
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Card
          size="small"
          title="ReOrch for NGS Lab Scheduling - Batch Replay"
          extra={
            <Button type="primary" icon={<ExperimentOutlined />} loading={loading} onClick={() => void run()}>
              运行实验包 Replay
            </Button>
          }
        >
          <Row gutter={[12, 12]}>
            <Col xs={12} md={4}>
              <Statistic title="Replay cases" value={batch?.case_results.length ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="Pass rate" value={Number(batch?.aggregate_metrics.pass_rate ?? 0) * 100} suffix="%" />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="Feasible" value={data?.feasible_candidates.length ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="Rejected" value={data?.rejected_candidates.length ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="TAT risk" value={data?.impact_report.tat_risk_samples.length ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic
                title="Recommended"
                value={recommended ? recommended.soft_score : 0}
                precision={0}
              />
            </Col>
          </Row>
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message={selectedCase ? `${selectedCase.case_id} / ${selectedCase.scenario_id}` : '等待运行'}
            description={
              recommended
                ? `推荐：${recommended.label}。实验包：${batch?.package_id ?? '-'}；只展示 hard-feasible 候选，LIMS writeback 保持人工确认。`
                : '没有通过 hard gate 的候选时，系统会退回人工判断。'
            }
          />
        </Card>

        <Card size="small" title="Batch package loader" extra={<FileSearchOutlined />}>
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space wrap>
              <Upload
                accept="application/json,.json"
                maxCount={1}
                beforeUpload={(file) => {
                  void file.text().then((text) => setPackageText(text));
                  return false;
                }}
              >
                <Button icon={<UploadOutlined />}>导入实验包 JSON</Button>
              </Upload>
              <Button type="primary" loading={loading} onClick={runUploadedPackage}>
                读取上传包并 replay
              </Button>
            </Space>
            <Input.TextArea
              rows={8}
              value={packageText}
              onChange={(event) => setPackageText(event.target.value)}
              style={{ fontFamily: 'monospace' }}
            />
          </Space>
        </Card>

        <Card size="small" title="实验包 replay cases">
          <Table
            rowKey="case_id"
            columns={batchColumns}
            dataSource={batch?.case_results ?? []}
            loading={loading}
            size="small"
            pagination={false}
            rowClassName={(row) => (row.case_id === selectedCase?.case_id ? 'ant-table-row-selected' : '')}
            onRow={(row) => ({
              onClick: () => setSelectedCaseId(row.case_id),
              style: { cursor: 'pointer' },
            })}
          />
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={24} xl={16}>
            <Card size="small" title="Top-K hard-feasible repair candidates" extra={<CheckCircleOutlined />}>
              <Table
                rowKey="candidate_id"
                columns={feasibleColumns}
                dataSource={data?.feasible_candidates ?? []}
                loading={loading}
                size="small"
                pagination={false}
                scroll={{ x: 980 }}
              />
            </Card>
          </Col>
          <Col xs={24} xl={8}>
            <Card size="small" title="推荐方案 gate report">
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Descriptions size="small" column={1} bordered>
                  <Descriptions.Item label="Candidate">
                    {recommended?.candidate_id ?? '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="Planner confirmation">
                    <Tag color="blue">
                      {String(data?.audit_package.planner_confirmation_required ?? true)}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="LIMS writeback">
                    <Tag color="default">
                      {String(data?.audit_package.lims_writeback_executed ?? false)}
                    </Tag>
                  </Descriptions.Item>
                </Descriptions>
                <Space size={[4, 4]} wrap>
                  {recommendedGateRows.map(([gate, status]) => (
                    <Tag key={gate} color={gateColor(status)}>
                      {gate}: {status}
                    </Tag>
                  ))}
                </Space>
              </Space>
            </Card>
          </Col>
        </Row>

        <Card size="small" title="Planner confirmation / override">
          <Row gutter={[12, 12]}>
            <Col xs={24} lg={10}>
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label="Replay case">
                  {selectedCase?.case_id ?? '-'}
                </Descriptions.Item>
                <Descriptions.Item label="Recommended candidate">
                  {recommended?.candidate_id ?? '-'}
                </Descriptions.Item>
                <Descriptions.Item label="LIMS writeback">
                  <Tag color="default">false</Tag>
                </Descriptions.Item>
              </Descriptions>
            </Col>
            <Col xs={24} lg={14}>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Select
                  value={selectedDecisionCandidateId ?? undefined}
                  placeholder="选择 override 候选"
                  style={{ width: '100%' }}
                  onChange={setSelectedDecisionCandidateId}
                  options={(data?.feasible_candidates ?? []).map((candidate) => ({
                    value: candidate.candidate_id,
                    label: `${candidate.label} / score ${candidate.soft_score}`,
                  }))}
                />
                <Input.TextArea
                  rows={3}
                  value={plannerReason}
                  onChange={(event) => setPlannerReason(event.target.value)}
                  placeholder="驳回或 override 原因；确认推荐可留空"
                />
                <Space wrap>
                  <Button
                    type="primary"
                    loading={decisionLoading}
                    onClick={() => void submitPlannerDecision('confirm')}
                  >
                    确认推荐
                  </Button>
                  <Button
                    danger
                    loading={decisionLoading}
                    onClick={() => void submitPlannerDecision('reject')}
                  >
                    驳回
                  </Button>
                  <Button
                    loading={decisionLoading}
                    onClick={() => void submitPlannerDecision('override')}
                  >
                    Override 选择
                  </Button>
                </Space>
              </Space>
            </Col>
          </Row>
          <Table
            rowKey="decision_id"
            style={{ marginTop: 12 }}
            dataSource={decisions}
            size="small"
            pagination={false}
            columns={[
              { title: 'Decision', dataIndex: 'decision_id' },
              {
                title: '动作',
                dataIndex: 'action',
                render: (value: string) => <Tag color={value === 'reject' ? 'red' : 'green'}>{value}</Tag>,
              },
              { title: 'Case', dataIndex: 'case_id' },
              { title: 'Candidate', dataIndex: 'selected_candidate_id', render: (value?: string | null) => value ?? '-' },
              { title: '原因', render: (_, row) => row.override_reason ?? row.reason ?? '-' },
              {
                title: 'LIMS 写回',
                dataIndex: 'lims_writeback_executed',
                render: (value: boolean) => <Tag color="default">{String(value)}</Tag>,
              },
            ]}
            locale={{ emptyText: '暂无计划员决策记录' }}
          />
        </Card>

        <Card size="small" title="被 protected feasibility gate 拦截的候选" extra={<StopOutlined />}>
          <Table
            rowKey="candidate_id"
            columns={rejectedColumns}
            dataSource={data?.rejected_candidates ?? []}
            loading={loading}
            size="small"
            pagination={false}
          />
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={24} xl={10}>
            <Card size="small" title="Impact report">
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label="Impacted samples">
                  {(data?.impact_report.impacted_samples ?? []).join(', ') || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="Impacted pools">
                  {(data?.impact_report.impacted_pools ?? []).join(', ') || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="Impacted runs">
                  {(data?.impact_report.impacted_runs ?? []).join(', ') || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="Events">
                  {(data?.impact_report.event_summary ?? []).join('；') || '-'}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
          <Col xs={24} xl={14}>
            <Card size="small" title="Agent trace">
              <Table
                rowKey="agent_name"
                columns={traceColumns}
                dataSource={data?.agent_trace ?? []}
                loading={loading}
                size="small"
                pagination={false}
              />
            </Card>
          </Col>
        </Row>
      </Space>
    </div>
  );
};

export default NgsLabPage;
