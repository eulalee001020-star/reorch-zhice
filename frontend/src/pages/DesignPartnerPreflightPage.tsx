import React, { useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  List,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Upload,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  FileSearchOutlined,
  PlayCircleOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  runDesignPartnerPreflight,
  runDesignPartnerSamplePreflight,
} from '@/api';
import type {
  DesignPartnerEvidenceCheck,
  DesignPartnerMoatLayer,
  DesignPartnerPreflightRequest,
  DesignPartnerPreflightResponse,
} from '@/types';

const checkColumns: ColumnsType<DesignPartnerEvidenceCheck> = [
  { title: '证据门', dataIndex: 'check_id', width: 220 },
  { title: '类别', dataIndex: 'category', width: 130 },
  {
    title: '状态',
    dataIndex: 'status',
    width: 130,
    render: (status: DesignPartnerEvidenceCheck['status']) => {
      const color = status === 'passed' ? 'green' : status === 'blocked' ? 'red' : 'orange';
      return <Tag color={color}>{status}</Tag>;
    },
  },
  { title: '客观判断', dataIndex: 'finding' },
  {
    title: '下一动作',
    dataIndex: 'required_action',
    render: (value?: string | null) => value ?? '-',
  },
];

const moatColumns: ColumnsType<DesignPartnerMoatLayer> = [
  { title: '壁垒层', dataIndex: 'layer', width: 210 },
  {
    title: '证据覆盖',
    dataIndex: 'evidence_coverage_score',
    width: 220,
    render: (value: number) => <Progress percent={Math.round(value)} size="small" />,
  },
  {
    title: '状态',
    dataIndex: 'status',
    width: 110,
    render: (status: DesignPartnerMoatLayer['status']) => (
      <Tag color={status === 'validated' ? 'green' : status === 'building' ? 'blue' : 'default'}>
        {status}
      </Tag>
    ),
  },
  { title: '客户私有资产', dataIndex: 'customer_private_asset_count', width: 130 },
  {
    title: '可复用脱敏资产',
    dataIndex: 'reusable_deidentified_asset_count',
    width: 150,
  },
  {
    title: '主要缺口',
    dataIndex: 'gaps',
    render: (items: string[]) => (
      items.length ? (
        <Space direction="vertical" size={0}>
          {items.map((item) => <span key={item}>{item}</span>)}
        </Space>
      ) : '-'
    ),
  },
];

const stageColor = {
  data_repair: 'red',
  replay_ready: 'blue',
  shadow_ready: 'green',
} as const;

const DesignPartnerPreflightPage: React.FC = () => {
  const [requestText, setRequestText] = useState('');
  const [report, setReport] = useState<DesignPartnerPreflightResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  const runCustomerPreflight = async () => {
    setLoading(true);
    setFeedback(null);
    try {
      const payload = JSON.parse(requestText) as DesignPartnerPreflightRequest;
      const next = await runDesignPartnerPreflight(payload);
      setReport(next);
      setFeedback({ type: 'success', text: `预检完成：${next.stage}` });
    } catch {
      setFeedback({
        type: 'error',
        text: '预检失败：请检查 JSON、mapping、引用和治理字段',
      });
    } finally {
      setLoading(false);
    }
  };

  const runSyntheticSample = async () => {
    setLoading(true);
    setFeedback(null);
    try {
      const next = await runDesignPartnerSamplePreflight();
      setReport(next);
      setFeedback({ type: 'success', text: `合成样例完成：${next.stage}` });
    } catch {
      setFeedback({ type: 'error', text: '合成样例预检失败' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="demo-page">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div className="demo-hero">
          <Row gutter={[18, 18]} align="middle">
            <Col xs={24} lg={14}>
              <div className="hero-eyebrow">Design Partner / evidence-gated onboarding</div>
              <h1 className="hero-title">试点阶段由证据决定，不由演示完成度决定</h1>
              <div className="hero-subtitle">
                数据、治理、约束、案例、工作流与 ROI 使用同一套引用台账；生产回写始终不在预检授权范围内。
              </div>
            </Col>
            <Col xs={24} lg={10}>
              <div className="metric-strip metric-strip--three">
                <div className="metric-tile">
                  <div className="metric-label">Gate 1</div>
                  <div className="metric-value">Repair</div>
                  <div className="metric-note">字段与治理</div>
                </div>
                <div className="metric-tile">
                  <div className="metric-label">Gate 2</div>
                  <div className="metric-value">Replay</div>
                  <div className="metric-note">历史回放</div>
                </div>
                <div className="metric-tile">
                  <div className="metric-label">Gate 3</div>
                  <div className="metric-value">Shadow</div>
                  <div className="metric-note">只读并行</div>
                </div>
              </div>
            </Col>
          </Row>
        </div>

        <Card
          className="partner-pack-card"
          size="small"
          title="客户证据包"
          extra={
            <Space className="partner-pack-actions" wrap>
              <Button
                icon={<PlayCircleOutlined />}
                loading={loading}
                onClick={runSyntheticSample}
              >
                运行合成样例
              </Button>
              <Button
                type="primary"
                icon={<FileSearchOutlined />}
                loading={loading}
                disabled={!requestText.trim()}
                onClick={runCustomerPreflight}
              >
                运行客户预检
              </Button>
            </Space>
          }
        >
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Upload
              accept="application/json,.json"
              maxCount={1}
              beforeUpload={(file) => {
                void file.text().then(setRequestText);
                return false;
              }}
            >
              <Button icon={<UploadOutlined />}>导入预检 JSON</Button>
            </Upload>
            <Input.TextArea
              rows={10}
              value={requestText}
              onChange={(event) => setRequestText(event.target.value)}
              placeholder="DesignPartnerPreflightRequest JSON"
              style={{ fontFamily: 'monospace' }}
            />
            {feedback && (
              <Alert type={feedback.type} showIcon message={feedback.text} />
            )}
          </Space>
        </Card>

        {report ? (
          <>
            <Card size="small" title="最高安全阶段">
              <Row gutter={[12, 12]}>
                <Col xs={24} md={6}>
                  <Statistic
                    title="Stage"
                    value={report.stage}
                    valueStyle={{ color: report.stage === 'data_repair' ? '#cf1322' : '#1677ff' }}
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic title="Evidence scope" value={report.evidence_scope} />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic title="ROI evidence" value={report.roi_summary.evidence_level} />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="Eligible cases"
                    value={report.roi_summary.eligible_case_count}
                    suffix={`/ ${report.roi_summary.submitted_case_count}`}
                  />
                </Col>
              </Row>
              <Alert
                showIcon
                type={report.evidence_scope === 'synthetic_sample' ? 'warning' : 'info'}
                message={report.claim_boundary}
                style={{ marginTop: 12 }}
              />
              <Descriptions
                className="partner-summary"
                size="small"
                bordered
                column={1}
                style={{ marginTop: 12 }}
              >
                <Descriptions.Item label="Preflight ID">{report.preflight_id}</Descriptions.Item>
                <Descriptions.Item label="Data fingerprint">
                  <span className="mono-wrap">{report.data_fingerprint}</span>
                </Descriptions.Item>
                <Descriptions.Item label="允许动作">
                  <Space size={[4, 4]} wrap>
                    {report.allowed_actions.map((item) => <Tag color="green" key={item}>{item}</Tag>)}
                  </Space>
                </Descriptions.Item>
                <Descriptions.Item label="禁止动作">
                  <Space size={[4, 4]} wrap>
                    {report.blocked_actions.map((item) => <Tag color="red" key={item}>{item}</Tag>)}
                  </Space>
                </Descriptions.Item>
              </Descriptions>
            </Card>

            <Card size="small" title="证据门结果">
              <Table
                rowKey="check_id"
                columns={checkColumns}
                dataSource={report.checks}
                size="small"
                pagination={false}
                scroll={{ x: 980 }}
              />
            </Card>

            <Card size="small" title="四层壁垒证据">
              <Table
                rowKey="layer"
                columns={moatColumns}
                dataSource={report.moat_layers}
                size="small"
                pagination={false}
                scroll={{ x: 1050 }}
              />
            </Card>

            <Row gutter={[12, 12]}>
              <Col xs={24} lg={10}>
                <Card size="small" title="ROI 证据边界">
                  <Descriptions size="small" bordered column={1}>
                    <Descriptions.Item label="证据等级">
                      <Tag color={stageColor[report.stage]}>{report.roi_summary.evidence_level}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="案例估算值">
                      {report.roi_summary.currency} {report.roi_summary.estimated_case_savings}
                    </Descriptions.Item>
                    <Descriptions.Item label="执行实测值">
                      {report.roi_summary.currency} {report.roi_summary.realized_case_savings}
                    </Descriptions.Item>
                    <Descriptions.Item label="可声明口径">
                      {report.roi_summary.claim_allowed}
                    </Descriptions.Item>
                  </Descriptions>
                </Card>
              </Col>
              <Col xs={24} lg={14}>
                <Card size="small" title="下一步动作">
                  <List
                    size="small"
                    dataSource={report.required_next_actions}
                    renderItem={(item) => <List.Item>{item}</List.Item>}
                  />
                </Card>
              </Col>
            </Row>
          </>
        ) : (
          <Alert
            showIcon
            type="info"
            message="尚无预检结果"
            description="客户证据与合成样例使用相同闸门，但 evidence_scope 和 claim boundary 始终分开。"
          />
        )}
      </Space>
    </div>
  );
};

export default DesignPartnerPreflightPage;
