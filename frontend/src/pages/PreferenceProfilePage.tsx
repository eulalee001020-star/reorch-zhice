import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { getPreferenceProfile, learnPreference, listCases } from '@/api';
import type { CaseRecord, PreferenceLearningOutput, PreferenceProfile } from '@/types';

const { Text } = Typography;

const plannerId = 'planner-1';

const PreferenceProfilePage: React.FC = () => {
  const [profile, setProfile] = useState<PreferenceProfile | null>(null);
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [learning, setLearning] = useState<PreferenceLearningOutput | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const [nextProfile, nextCases] = await Promise.all([
        getPreferenceProfile(plannerId),
        listCases(),
      ]);
      setProfile(nextProfile);
      setCases(nextCases);
    } catch {
      message.error('加载偏好画像失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const runLearning = async () => {
    setLoading(true);
    try {
      const output = await learnPreference({ planner_id: plannerId, min_samples: 1 });
      setLearning(output);
      setProfile(output.preference_profile);
      message.success('偏好画像已刷新');
    } catch {
      message.error('偏好学习失败');
    } finally {
      setLoading(false);
    }
  };

  const strategyRows = useMemo(
    () =>
      Object.entries(profile?.strategy_preferences ?? {}).map(([strategy, weight]) => ({
        strategy,
        weight,
      })),
    [profile],
  );

  const overrideCount = cases.filter((item) => item.is_override).length;
  const confirmCount = cases.length - overrideCount;

  const caseColumns: ColumnsType<CaseRecord> = [
    {
      title: '案例',
      dataIndex: 'case_id',
      width: 120,
      render: (value: string) => <Text copyable={{ text: value }}>{value.slice(0, 8)}</Text>,
    },
    {
      title: '人工动作',
      width: 130,
      render: (_, row) =>
        row.is_override ? <Tag color="volcano">驳回 / override</Tag> : <Tag color="green">确认采纳</Tag>,
    },
    {
      title: '影响',
      render: (_, row) =>
        row.is_override
          ? '作为负向排序信号，降低原策略在同分场景中的优先级'
          : '作为正向排序信号，增强该策略在相似场景中的排序依据',
    },
    {
      title: '策略',
      dataIndex: 'strategy_type',
      width: 150,
    },
    {
      title: '原因',
      dataIndex: 'override_reason',
      render: (value?: string | null) => value ?? '-',
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert
          type="warning"
          showIcon
          message="偏好画像只做推荐排序辅助"
          description="确认、驳回和 override 会形成 planner preference profile，但它不能覆盖硬约束、质量门、Data Readiness、replay 结论或人工确认。"
        />

        <Card
          size="small"
          title={`Planner Preference Profile / ${plannerId}`}
          extra={
            <Space>
              <Button icon={<ReloadOutlined />} loading={loading} onClick={refresh}>
                刷新
              </Button>
              <Button type="primary" loading={loading} onClick={runLearning}>
                从案例重算偏好
              </Button>
            </Space>
          }
        >
          <Row gutter={[12, 12]}>
            <Col xs={12} md={6}>
              <Statistic title="案例样本" value={cases.length} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="确认采纳" value={confirmCount} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="驳回 / override" value={overrideCount} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title="学习置信度"
                value={Math.round((learning?.confidence ?? 0) * 100)}
                suffix="%"
              />
            </Col>
          </Row>
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={24} lg={12}>
            <Card size="small" title="策略偏好权重">
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                {strategyRows.length ? (
                  strategyRows.map((row) => (
                    <div key={row.strategy}>
                      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                        <Text>{row.strategy}</Text>
                        <Text>{Math.round(Number(row.weight) * 100)}%</Text>
                      </Space>
                      <Progress percent={Math.round(Number(row.weight) * 100)} />
                    </div>
                  ))
                ) : (
                  <Text type="secondary">暂无偏好权重</Text>
                )}
              </Space>
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card size="small" title="学习证据">
              <Space direction="vertical" style={{ width: '100%' }}>
                <Tag color={learning?.recommended_use === 'ranking_tiebreaker_only' ? 'green' : 'blue'}>
                  {learning?.recommended_use ?? 'observation_only'}
                </Tag>
                {(learning?.evidence_summary ?? [
                  '当前展示已归档案例和 profile；点击“从案例重算偏好”可刷新可审计学习输出。',
                ]).map((item) => (
                  <Text key={item}>{item}</Text>
                ))}
              </Space>
            </Card>
          </Col>
        </Row>

        <Card size="small" title="确认 / 驳回 / override 对 profile 的影响">
          <Table
            rowKey="case_id"
            columns={caseColumns}
            dataSource={cases}
            loading={loading}
            size="small"
            pagination={{ pageSize: 8 }}
          />
        </Card>
      </Space>
    </div>
  );
};

export default PreferenceProfilePage;
