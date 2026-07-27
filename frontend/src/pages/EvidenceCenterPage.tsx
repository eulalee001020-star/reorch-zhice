import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Card,
  Col,
  Collapse,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { AuditOutlined } from '@ant-design/icons';
import { getEvidenceCenter } from '@/api';
import type { EvidenceCenterResponse, EvidenceItem } from '@/types';

const { Text } = Typography;

const categoryColor: Record<string, string> = {
  replay: 'blue',
  failure_samples: 'red',
  llm_eval: 'purple',
  data_readiness: 'green',
  quality_gate: 'orange',
};

function evidenceLevel(item: EvidenceItem): { label: string; color: string } {
  if (item.category === 'replay') return { label: 'lab replay', color: 'blue' };
  if (item.category === 'failure_samples') return { label: 'controlled failure set', color: 'volcano' };
  if (item.category === 'llm_eval') return { label: 'offline eval', color: 'purple' };
  if (item.category === 'data_readiness') return { label: 'readiness gate', color: 'green' };
  if (item.category === 'quality_gate') return { label: 'quality gate evidence', color: 'gold' };
  return { label: 'demo evidence', color: 'default' };
}

function metricText(metrics: Record<string, unknown>): string {
  const entries = Object.entries(metrics).slice(0, 4);
  if (!entries.length) return '-';
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join('；');
}

const EvidenceCenterPage: React.FC = () => {
  const [data, setData] = useState<EvidenceCenterResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setData(await getEvidenceCenter());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const counts = data?.summary_counts.by_category as Record<string, number> | undefined;
  const total = Number(data?.summary_counts.total ?? 0);
  const items = data?.items ?? [];
  const gateBackedEvidence = useMemo(
    () => items.filter((item) => item.category === 'quality_gate' || item.category === 'data_readiness').length,
    [items],
  );

  const columns: ColumnsType<EvidenceItem> = [
    {
      title: '证据',
      dataIndex: 'title',
      width: 260,
      render: (title: string, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{title}</Text>
          <Text type="secondary">{row.evidence_id}</Text>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'category',
      width: 130,
      render: (category: string) => <Tag color={categoryColor[category] ?? 'default'}>{category}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 170,
      render: (status: string) => <Tag>{status.replace('live', 'controlled')}</Tag>,
    },
    {
      title: '证据等级',
      width: 170,
      render: (_, row) => {
        const level = evidenceLevel(row);
        return <Tag color={level.color}>{level.label}</Tag>;
      },
    },
    {
      title: '摘要',
      dataIndex: 'summary',
      render: (summary: string, row) => (
        <Space direction="vertical" size={2}>
          <Text>{summary}</Text>
          <Text type="secondary">{metricText(row.metrics)}</Text>
        </Space>
      ),
    },
    {
      title: '来源',
      dataIndex: 'source_path',
      width: 260,
      render: (path?: string | null) => <Text code>{path ?? '-'}</Text>,
    },
  ];

  return (
    <div className="demo-page">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div className="demo-hero">
          <Row gutter={[18, 18]} align="middle">
            <Col xs={24} lg={11}>
              <div className="hero-eyebrow">Evidence Ladder</div>
              <h1 className="hero-title">把可证明的证据和还未证明的 traction 分开</h1>
              <div className="hero-subtitle">
                这里展示受控 replay、失败样本、离线评测和数据就绪证据；真实客户 ROI、上线和自动写回仍需 Design Partner 验证。
              </div>
            </Col>
            <Col xs={24} lg={13}>
              <div className="evidence-ladder">
                <div className="evidence-step">
                  <div className="evidence-step-title">MVP / Demo</div>
                  <div className="evidence-step-body">证明异常决策闭环存在：影响分析、Top-K、质量门、人工确认、审计。</div>
                </div>
                <div className="evidence-step">
                  <div className="evidence-step-title">Lab Replay</div>
                  <div className="evidence-step-body">证明系统能记录采纳、微调、驳回和失败归因，不等于客户采纳率。</div>
                </div>
                <div className="evidence-step">
                  <div className="evidence-step-title">Synthetic / Benchmark</div>
                  <div className="evidence-step-body">证明方法、规模和工程可行性，不等于真实客户 ROI。</div>
                </div>
                <div className="evidence-step boundary-note">
                  <div className="evidence-step-title">Design Partner</div>
                  <div className="evidence-step-body">下一步需要 10-30 条脱敏历史异常、计划员决策和执行结果。</div>
                </div>
              </div>
            </Col>
          </Row>
        </div>

        <Card size="small" title="Evidence Center" extra={<AuditOutlined />}>
          <Row gutter={[12, 12]}>
            <Col xs={12} md={4}>
              <Statistic title="证据项" value={total} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="Replay" value={counts?.replay ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="失败样本" value={counts?.failure_samples ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="LLM eval" value={counts?.llm_eval ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="Data readiness" value={counts?.data_readiness ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="Gate-backed" value={gateBackedEvidence} />
            </Col>
          </Row>
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message="这里集中展示可复核证据，不把受控 replay 写成客户生产结论。"
          />
        </Card>

        <Card size="small" title="证据清单">
          <Table
            rowKey="evidence_id"
            columns={columns}
            dataSource={items}
            loading={loading}
            size="small"
            pagination={false}
            expandable={{
              expandedRowRender: (item) => (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  {item.table && (
                    <Table
                      rowKey={(_, index) => `${item.evidence_id}-${index ?? 0}`}
                      columns={item.table.columns.map((column) => ({
                        title: column,
                        dataIndex: column,
                      }))}
                      dataSource={item.table.rows}
                      size="small"
                      pagination={false}
                      scroll={{ x: 800 }}
                    />
                  )}
                  <Collapse
                    size="small"
                    items={[
                      {
                        key: 'refs',
                        label: 'Source refs / limitations',
                        children: (
                          <Space direction="vertical" size={4}>
                            <Text>Refs: {item.source_refs.join('；') || '-'}</Text>
                            {item.limitations.map((line) => (
                              <Text key={line} type="secondary">{line}</Text>
                            ))}
                          </Space>
                        ),
                      },
                    ]}
                  />
                </Space>
              ),
            }}
          />
        </Card>
      </Space>
    </div>
  );
};

export default EvidenceCenterPage;
