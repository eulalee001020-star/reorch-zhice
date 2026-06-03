import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  Modal,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined,
  CloudUploadOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  compileRuleCandidates,
  listRuleCandidateReviews,
  publishRuleCandidate,
  replayRuleCandidate,
  reviewRuleCandidate,
} from '@/api';
import type { RuleCandidateReviewRecord } from '@/types';

const { Text, Paragraph } = Typography;

function statusTag(status: string) {
  const map: Record<string, { color: string; label: string }> = {
    pending_human_review: { color: 'blue', label: '待人工审核' },
    approved_for_replay: { color: 'cyan', label: '待 replay' },
    replay_passed: { color: 'green', label: 'replay 通过' },
    replay_failed: { color: 'red', label: 'replay 失败' },
    rejected: { color: 'volcano', label: '已拒绝' },
    published_readonly: { color: 'purple', label: '只读发布' },
  };
  const item = map[status] ?? { color: 'default', label: status };
  return <Tag color={item.color}>{item.label}</Tag>;
}

const defaultRuleText =
  'M4 operator unavailable after 16:00, urgent jobs should avoid it';

const RuleCandidateReviewPage: React.FC = () => {
  const [records, setRecords] = useState<RuleCandidateReviewRecord[]>([]);
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [ruleText, setRuleText] = useState(defaultRuleText);
  const [rejecting, setRejecting] = useState<RuleCandidateReviewRecord | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  const refresh = async () => {
    setLoading(true);
    try {
      const data = await listRuleCandidateReviews();
      setRecords(data.records);
      setStatusCounts(data.status_counts);
    } catch {
      message.error('加载规则候选失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const publishedRecords = useMemo(
    () => records.filter((record) => record.published_record),
    [records],
  );

  const runAction = async (
    key: string,
    fn: () => Promise<RuleCandidateReviewRecord>,
    okMessage: string,
  ) => {
    setActionLoading(key);
    try {
      await fn();
      message.success(okMessage);
      await refresh();
    } catch {
      message.error('操作失败，请检查候选状态和必填原因');
    } finally {
      setActionLoading(null);
    }
  };

  const handleCompile = async () => {
    if (!ruleText.trim()) {
      message.warning('请输入现场规则文本');
      return;
    }
    setActionLoading('compile');
    try {
      await compileRuleCandidates({
        rule_text: ruleText,
        source: 'planner_feedback',
      });
      message.success('已生成待审核规则候选');
      await refresh();
    } catch {
      message.error('生成规则候选失败');
    } finally {
      setActionLoading(null);
    }
  };

  const columns: ColumnsType<RuleCandidateReviewRecord> = [
    {
      title: '候选',
      width: 240,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Text strong copyable={{ text: row.candidate.candidate_id }}>
            {row.candidate.candidate_id}
          </Text>
          <Text type="secondary">{row.candidate.constraint_type}</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      render: statusTag,
    },
    {
      title: '置信度',
      width: 90,
      render: (_, row) => `${Math.round(row.candidate.confidence * 100)}%`,
    },
    {
      title: '编译规则',
      render: (_, row) => (
        <Paragraph style={{ marginBottom: 0 }} ellipsis={{ rows: 2, expandable: true }}>
          {row.candidate.compiled_rule}
        </Paragraph>
      ),
    },
    {
      title: 'Replay',
      width: 150,
      render: (_, row) => {
        if (!row.replay_result) return <Text type="secondary">未运行</Text>;
        return (
          <Space direction="vertical" size={0}>
            <Tag color={row.replay_result.pass_replay ? 'green' : 'red'}>
              {row.replay_result.pass_replay ? 'pass' : 'fail'}
            </Tag>
            <Text type="secondary">{row.replay_result.blocked_reason ?? 'no blocker'}</Text>
          </Space>
        );
      },
    },
    {
      title: '拒绝原因',
      dataIndex: 'reject_reason',
      render: (value?: string | null) => value ?? '-',
    },
    {
      title: '操作',
      width: 300,
      render: (_, row) => (
        <Space size="small" wrap>
          <Button
            size="small"
            icon={<CheckCircleOutlined />}
            disabled={!['pending_human_review', 'replay_failed'].includes(row.status)}
            loading={actionLoading === `${row.candidate.candidate_id}-approve`}
            onClick={() =>
              runAction(
                `${row.candidate.candidate_id}-approve`,
                () =>
                  reviewRuleCandidate(row.candidate.candidate_id, {
                    action: 'approve_for_replay',
                    reviewer_id: 'planner-1',
                    review_note: 'scope confirmed for replay',
                  }),
                '已送入 replay',
              )
            }
          >
            送 replay
          </Button>
          <Button
            size="small"
            icon={<PlayCircleOutlined />}
            disabled={row.status !== 'approved_for_replay'}
            loading={actionLoading === `${row.candidate.candidate_id}-replay`}
            onClick={() =>
              runAction(
                `${row.candidate.candidate_id}-replay`,
                () => replayRuleCandidate(row.candidate.candidate_id, { scenario_count: 3 }),
                'Replay 已完成',
              )
            }
          >
            replay
          </Button>
          <Button
            size="small"
            icon={<CloudUploadOutlined />}
            disabled={row.status !== 'replay_passed'}
            loading={actionLoading === `${row.candidate.candidate_id}-publish`}
            onClick={() =>
              runAction(
                `${row.candidate.candidate_id}-publish`,
                () =>
                  publishRuleCandidate(row.candidate.candidate_id, {
                    publisher_id: 'planner-1',
                    release_note: 'validated by rule candidate review console',
                  }),
                '已生成只读发布记录',
              )
            }
          >
            发布记录
          </Button>
          <Button
            size="small"
            danger
            icon={<StopOutlined />}
            disabled={['rejected', 'published_readonly'].includes(row.status)}
            onClick={() => {
              setRejecting(row);
              setRejectReason(row.reject_reason ?? '');
            }}
          >
            拒绝
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          message="规则候选审核台"
          description="候选规则必须经过人工审核、replay 和只读发布记录；这里不直接修改求解器硬约束或客户主系统。"
        />

        <Card
          size="small"
          title="生成候选"
          extra={
            <Button type="primary" loading={actionLoading === 'compile'} onClick={handleCompile}>
              编译规则候选
            </Button>
          }
        >
          <Input.TextArea
            rows={3}
            value={ruleText}
            onChange={(event) => setRuleText(event.target.value)}
            placeholder="输入计划员复盘、override 原因或现场隐性规则"
          />
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic title="待审核" value={statusCounts.pending_human_review ?? 0} />
            </Card>
          </Col>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic title="待 replay" value={statusCounts.approved_for_replay ?? 0} />
            </Card>
          </Col>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic title="replay 通过" value={statusCounts.replay_passed ?? 0} />
            </Card>
          </Col>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic title="已拒绝" value={statusCounts.rejected ?? 0} />
            </Card>
          </Col>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic title="只读发布" value={statusCounts.published_readonly ?? 0} />
            </Card>
          </Col>
        </Row>

        <Card size="small" title="候选列表">
          <Table
            rowKey={(record) => record.candidate.candidate_id}
            columns={columns}
            dataSource={records}
            loading={loading}
            size="small"
            pagination={{ pageSize: 8 }}
            scroll={{ x: 1160 }}
          />
        </Card>

        <Card size="small" title="只读发布记录">
          <Table
            rowKey={(record) => record.published_record?.release_id ?? record.candidate.candidate_id}
            dataSource={publishedRecords}
            size="small"
            pagination={false}
            columns={[
              {
                title: 'Release',
                render: (_, row) => row.published_record?.release_id ?? '-',
              },
              {
                title: 'Candidate',
                render: (_, row) => row.candidate.candidate_id,
              },
              {
                title: '发布人',
                render: (_, row) => row.published_record?.published_by ?? '-',
              },
              {
                title: '发布时间',
                render: (_, row) =>
                  row.published_record
                    ? dayjs(row.published_record.published_at).format('YYYY-MM-DD HH:mm')
                    : '-',
              },
              {
                title: '只读',
                render: (_, row) => (
                  <Tag color={row.published_record?.readonly ? 'green' : 'default'}>
                    {String(row.published_record?.readonly ?? true)}
                  </Tag>
                ),
              },
            ]}
            locale={{ emptyText: '暂无发布记录' }}
          />
        </Card>
      </Space>

      <Modal
        title="拒绝规则候选"
        open={Boolean(rejecting)}
        okText="确认拒绝"
        cancelText="取消"
        onCancel={() => setRejecting(null)}
        onOk={() => {
          if (!rejecting) return;
          void runAction(
            `${rejecting.candidate.candidate_id}-reject`,
            () =>
              reviewRuleCandidate(rejecting.candidate.candidate_id, {
                action: 'reject',
                reviewer_id: 'planner-1',
                reject_reason: rejectReason,
              }),
            '已拒绝候选',
          ).then(() => {
            setRejecting(null);
            setRejectReason('');
          });
        }}
      >
        {rejecting && (
          <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
            <Descriptions.Item label="候选">{rejecting.candidate.candidate_id}</Descriptions.Item>
            <Descriptions.Item label="规则">{rejecting.candidate.compiled_rule}</Descriptions.Item>
          </Descriptions>
        )}
        <Input.TextArea
          rows={3}
          value={rejectReason}
          onChange={(event) => setRejectReason(event.target.value)}
          placeholder="填写拒绝原因，例如：缺少资源范围、时间窗口不明确、replay 中导致急单违约"
        />
      </Modal>
    </div>
  );
};

export default RuleCandidateReviewPage;
