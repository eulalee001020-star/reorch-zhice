/**
 * 案例库与模板管理页 — Case Library & Template Management.
 *
 * - Case list with filters (incident_type, strategy_type, time_range, execution_result)
 * - Case detail drawer: impact report, candidate plans, decision record, execution result
 * - CaseTemplate management: published and draft template lists
 * - Template edit form: name, applicable types, recommended strategy, thresholds
 * - Template usage stats: reference count, adoption rate, avg execution score
 * - System-level preference learning stats: AI adoption rate trend, Override rate trend, avg response time trend
 *
 * Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  Layout,
  Card,
  Table,
  Tag,
  Button,
  Space,
  Select,
  DatePicker,
  Drawer,
  Descriptions,
  Tabs,
  Form,
  Input,
  Modal,
  Statistic,
  Row,
  Col,
  message,
  Divider,
  Badge,
  Typography,
} from 'antd';
import {
  FileTextOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
  PlusOutlined,
  CheckCircleOutlined,
  EditOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type { ColumnsType } from 'antd/es/table';
import type { CaseRecord, CaseTemplate } from '@/types';
import {
  listCases,
  getCase,
  listTemplates,
  createTemplate,
  editTemplate,
  publishTemplate,
} from '@/api';
import type { ListCasesParams } from '@/api';
import { KPIDashboard } from '@/components/KPIDashboard';
import { exportDecisionPdf, exportDecisionExcel } from '@/api/exports';

const { Content } = Layout;
const { RangePicker } = DatePicker;
const { Text } = Typography;

// ---------------------------------------------------------------------------
// Case List Columns
// ---------------------------------------------------------------------------

const caseColumns: ColumnsType<CaseRecord> = [
  {
    title: '案例 ID',
    dataIndex: 'case_id',
    key: 'case_id',
    width: 100,
    render: (v: string) => <Text copyable={{ text: v }}>{v.slice(0, 8)}</Text>,
  },
  {
    title: '策略',
    dataIndex: 'strategy_type',
    key: 'strategy_type',
    width: 120,
    render: (v: string) => {
      const map: Record<string, { text: string; color: string }> = {
        wait_and_repair: { text: '等待修复', color: 'blue' },
        local_repair: { text: '局部修复', color: 'orange' },
        global_reschedule: { text: '全局重排', color: 'red' },
      };
      const m = map[v] ?? { text: v, color: 'default' };
      return <Tag color={m.color}>{m.text}</Tag>;
    },
  },
  {
    title: 'Override',
    dataIndex: 'is_override',
    key: 'is_override',
    width: 80,
    render: (v: boolean) =>
      v ? <Tag color="volcano">是</Tag> : <Tag color="green">否</Tag>,
  },
  {
    title: '执行评分',
    key: 'execution_score',
    width: 100,
    render: (_: unknown, r: CaseRecord) =>
      r.execution_result
        ? `${(r.execution_result.actual_otd * 100).toFixed(0)}% OTD`
        : '—',
  },
  {
    title: '创建时间',
    dataIndex: 'created_at',
    key: 'created_at',
    width: 160,
    render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
  },
];

// ---------------------------------------------------------------------------
// Template Columns
// ---------------------------------------------------------------------------

const templateColumns = (
  onEdit: (t: CaseTemplate) => void,
  onPublish: (id: string) => void,
): ColumnsType<CaseTemplate> => [
  {
    title: '模板名称',
    dataIndex: 'template_name',
    key: 'template_name',
  },
  {
    title: '状态',
    dataIndex: 'status',
    key: 'status',
    width: 80,
    render: (v: string) =>
      v === 'published' ? (
        <Badge status="success" text="已发布" />
      ) : (
        <Badge status="default" text="草稿" />
      ),
  },
  {
    title: '推荐策略',
    dataIndex: 'recommended_strategy',
    key: 'recommended_strategy',
    width: 120,
  },
  {
    title: '引用次数',
    dataIndex: 'reference_count',
    key: 'reference_count',
    width: 90,
  },
  {
    title: '采纳率',
    dataIndex: 'adoption_rate',
    key: 'adoption_rate',
    width: 90,
    render: (v: number) => `${(v * 100).toFixed(0)}%`,
  },
  {
    title: '操作',
    key: 'actions',
    width: 140,
    render: (_: unknown, r: CaseTemplate) => (
      <Space size="small">
        <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(r)}>
          编辑
        </Button>
        {r.status === 'draft' && (
          <Button
            size="small"
            type="primary"
            icon={<CheckCircleOutlined />}
            onClick={() => onPublish(r.template_id)}
          >
            发布
          </Button>
        )}
      </Space>
    ),
  },
];

// ---------------------------------------------------------------------------
// System-level preference learning stats (mock data for MVP)
// ---------------------------------------------------------------------------

const PreferenceLearningStats: React.FC = () => (
  <Card title="系统偏好学习统计" size="small" style={{ marginBottom: 16 }}>
    <Row gutter={16}>
      <Col span={8}>
        <Statistic
          title="AI 推荐采纳率"
          value={78.5}
          suffix="%"
          precision={1}
          valueStyle={{ color: '#52c41a' }}
          prefix={<ArrowUpOutlined />}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          较上月 +3.2%
        </Text>
      </Col>
      <Col span={8}>
        <Statistic
          title="Override 率"
          value={12.3}
          suffix="%"
          precision={1}
          valueStyle={{ color: '#faad14' }}
          prefix={<ArrowDownOutlined />}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          较上月 -1.8%
        </Text>
      </Col>
      <Col span={8}>
        <Statistic
          title="平均响应时间"
          value={4.2}
          suffix="分钟"
          precision={1}
          valueStyle={{ color: '#1677ff' }}
          prefix={<ArrowDownOutlined />}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          较上月 -0.5 分钟
        </Text>
      </Col>
    </Row>
  </Card>
);

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export const CaseLibraryPage: React.FC = () => {
  // Case list state
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [casesLoading, setCasesLoading] = useState(false);
  const [filters, setFilters] = useState<ListCasesParams>({});

  // Case detail drawer
  const [detailCase, setDetailCase] = useState<CaseRecord | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  // Template state
  const [templates, setTemplates] = useState<CaseTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);

  // Template edit modal
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<CaseTemplate | null>(null);
  const [form] = Form.useForm();

  // Export loading
  const [exportLoading, setExportLoading] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const fetchCases = useCallback(async () => {
    setCasesLoading(true);
    try {
      const data = await listCases(filters);
      setCases(data);
    } catch {
      message.error('加载案例列表失败');
    } finally {
      setCasesLoading(false);
    }
  }, [filters]);

  const fetchTemplates = useCallback(async () => {
    setTemplatesLoading(true);
    try {
      const data = await listTemplates();
      setTemplates(data);
    } catch {
      message.error('加载模板列表失败');
    } finally {
      setTemplatesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCases();
  }, [fetchCases]);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  // ---------------------------------------------------------------------------
  // Case detail
  // ---------------------------------------------------------------------------

  const openCaseDetail = async (record: CaseRecord) => {
    try {
      const full = await getCase(record.case_id);
      setDetailCase(full);
    } catch {
      setDetailCase(record);
    }
    setDetailOpen(true);
  };

  // ---------------------------------------------------------------------------
  // Template CRUD
  // ---------------------------------------------------------------------------

  const handleEditTemplate = (t: CaseTemplate) => {
    setEditingTemplate(t);
    form.setFieldsValue({
      template_name: t.template_name,
      applicable_incident_types: t.applicable_incident_types,
      recommended_strategy: t.recommended_strategy,
      key_parameter_thresholds: JSON.stringify(t.key_parameter_thresholds),
    });
    setEditModalOpen(true);
  };

  const handleCreateTemplate = () => {
    setEditingTemplate(null);
    form.resetFields();
    setEditModalOpen(true);
  };

  const handleSaveTemplate = async () => {
    try {
      const values = await form.validateFields();
      const payload = {
        ...values,
        key_parameter_thresholds: values.key_parameter_thresholds
          ? JSON.parse(values.key_parameter_thresholds)
          : {},
        status: 'draft',
        created_by: 'current_user',
      };

      if (editingTemplate) {
        await editTemplate(editingTemplate.template_id, payload);
        message.success('模板已更新');
      } else {
        await createTemplate(payload);
        message.success('模板已创建');
      }
      setEditModalOpen(false);
      fetchTemplates();
    } catch {
      message.error('保存失败');
    }
  };

  const handlePublishTemplate = async (id: string) => {
    try {
      await publishTemplate(id);
      message.success('模板已发布');
      fetchTemplates();
    } catch {
      message.error('发布失败');
    }
  };

  // ---------------------------------------------------------------------------
  // Export handlers
  // ---------------------------------------------------------------------------

  const handleExport = async (caseRecord: CaseRecord, format: 'pdf' | 'excel') => {
    if (!caseRecord.execution_result?.decision_record_id) {
      message.warning('该案例无关联决策记录，无法导出');
      return;
    }
    const drId = caseRecord.execution_result.decision_record_id;
    setExportLoading(`${caseRecord.case_id}-${format}`);
    try {
      const fn = format === 'pdf' ? exportDecisionPdf : exportDecisionExcel;
      const result = await fn(drId);
      message.success(`导出成功: ${result.filename}`);
    } catch {
      message.error('导出失败');
    } finally {
      setExportLoading(null);
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const caseColumnsWithAction: ColumnsType<CaseRecord> = [
    ...caseColumns,
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: unknown, r: CaseRecord) => (
        <Space size="small">
          <Button size="small" icon={<FileTextOutlined />} onClick={() => openCaseDetail(r)}>
            详情
          </Button>
          <Button
            size="small"
            icon={<FilePdfOutlined />}
            loading={exportLoading === `${r.case_id}-pdf`}
            onClick={() => handleExport(r, 'pdf')}
          >
            PDF
          </Button>
          <Button
            size="small"
            icon={<FileExcelOutlined />}
            loading={exportLoading === `${r.case_id}-excel`}
            onClick={() => handleExport(r, 'excel')}
          >
            Excel
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Layout style={{ minHeight: '100vh', background: '#f0f2f5' }}>
      <Content style={{ padding: 16 }}>
        {/* KPI Dashboard */}
        <KPIDashboard />

        {/* System preference learning stats */}
        <PreferenceLearningStats />

        <Tabs
          defaultActiveKey="cases"
          items={[
            {
              key: 'cases',
              label: '案例列表',
              children: (
                <>
                  {/* Filters */}
                  <Card size="small" style={{ marginBottom: 12 }}>
                    <Space wrap>
                      <Select
                        placeholder="异常类型"
                        allowClear
                        style={{ width: 140 }}
                        onChange={(v) => setFilters((f) => ({ ...f, incident_type: v }))}
                        options={[
                          { label: '设备故障', value: 'equipment_failure' },
                        ]}
                      />
                      <Select
                        placeholder="策略类型"
                        allowClear
                        style={{ width: 140 }}
                        onChange={(v) => setFilters((f) => ({ ...f, strategy_type: v }))}
                        options={[
                          { label: '等待修复', value: 'wait_and_repair' },
                          { label: '局部修复', value: 'local_repair' },
                          { label: '全局重排', value: 'global_reschedule' },
                        ]}
                      />
                      <Select
                        placeholder="执行结果"
                        allowClear
                        style={{ width: 140 }}
                        onChange={(v) => setFilters((f) => ({ ...f, execution_result: v }))}
                        options={[
                          { label: '成功', value: 'success' },
                          { label: '部分成功', value: 'partial' },
                          { label: '失败', value: 'failed' },
                        ]}
                      />
                      <RangePicker
                        onChange={(dates) => {
                          if (dates && dates[0] && dates[1]) {
                            setFilters((f) => ({
                              ...f,
                              start_time: dates[0]!.toISOString(),
                              end_time: dates[1]!.toISOString(),
                            }));
                          } else {
                            setFilters((f) => {
                              const { start_time, end_time, ...rest } = f;
                              return rest;
                            });
                          }
                        }}
                      />
                      <Button type="primary" onClick={fetchCases}>
                        查询
                      </Button>
                    </Space>
                  </Card>

                  {/* Case table */}
                  <Table
                    rowKey="case_id"
                    columns={caseColumnsWithAction}
                    dataSource={cases}
                    loading={casesLoading}
                    size="small"
                    pagination={{ pageSize: 10 }}
                  />
                </>
              ),
            },
            {
              key: 'templates',
              label: '模板管理',
              children: (
                <>
                  <div style={{ marginBottom: 12 }}>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={handleCreateTemplate}
                    >
                      新建模板
                    </Button>
                  </div>
                  <Table
                    rowKey="template_id"
                    columns={templateColumns(handleEditTemplate, handlePublishTemplate)}
                    dataSource={templates}
                    loading={templatesLoading}
                    size="small"
                    pagination={{ pageSize: 10 }}
                  />
                </>
              ),
            },
          ]}
        />

        {/* Case detail drawer */}
        <Drawer
          title="案例详情"
          width={640}
          open={detailOpen}
          onClose={() => setDetailOpen(false)}
        >
          {detailCase && (
            <>
              <Descriptions size="small" column={1} bordered>
                <Descriptions.Item label="案例 ID">
                  {detailCase.case_id}
                </Descriptions.Item>
                <Descriptions.Item label="策略">
                  {detailCase.strategy_type}
                </Descriptions.Item>
                <Descriptions.Item label="Override">
                  {detailCase.is_override ? '是' : '否'}
                </Descriptions.Item>
                {detailCase.override_reason && (
                  <Descriptions.Item label="Override 原因">
                    {detailCase.override_reason}
                  </Descriptions.Item>
                )}
                <Descriptions.Item label="规则选择">
                  {detailCase.rule_selection}
                </Descriptions.Item>
                <Descriptions.Item label="邻域选择">
                  {detailCase.neighborhood_selection}
                </Descriptions.Item>
                <Descriptions.Item label="修复策略">
                  {detailCase.repair_policy}
                </Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {dayjs(detailCase.created_at).format('YYYY-MM-DD HH:mm:ss')}
                </Descriptions.Item>
              </Descriptions>

              <Divider>影响范围</Divider>
              <pre style={{ fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
                {JSON.stringify(detailCase.impact_scope, null, 2)}
              </pre>

              <Divider>异常特征</Divider>
              <pre style={{ fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
                {JSON.stringify(detailCase.incident_features, null, 2)}
              </pre>

              {detailCase.execution_result && (
                <>
                  <Divider>执行结果</Divider>
                  <Descriptions size="small" column={1} bordered>
                    <Descriptions.Item label="实际 OTD">
                      {(detailCase.execution_result.actual_otd * 100).toFixed(1)}%
                    </Descriptions.Item>
                    <Descriptions.Item label="资源利用率">
                      {(detailCase.execution_result.actual_resource_utilization * 100).toFixed(1)}%
                    </Descriptions.Item>
                    <Descriptions.Item label="偏差">
                      {(detailCase.execution_result.deviation_percentage * 100).toFixed(1)}%
                    </Descriptions.Item>
                  </Descriptions>
                </>
              )}

              <Divider>求解链路</Divider>
              <pre style={{ fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
                {JSON.stringify(detailCase.solver_chain, null, 2)}
              </pre>
            </>
          )}
        </Drawer>

        {/* Template edit modal */}
        <Modal
          title={editingTemplate ? '编辑模板' : '新建模板'}
          open={editModalOpen}
          onOk={handleSaveTemplate}
          onCancel={() => setEditModalOpen(false)}
          okText="保存"
          cancelText="取消"
        >
          <Form form={form} layout="vertical" size="small">
            <Form.Item
              name="template_name"
              label="模板名称"
              rules={[{ required: true, message: '请输入模板名称' }]}
            >
              <Input />
            </Form.Item>
            <Form.Item name="applicable_incident_types" label="适用异常类型">
              <Select
                mode="multiple"
                options={[{ label: '设备故障', value: 'equipment_failure' }]}
              />
            </Form.Item>
            <Form.Item name="recommended_strategy" label="推荐策略">
              <Select
                options={[
                  { label: '等待修复', value: 'wait_and_repair' },
                  { label: '局部修复', value: 'local_repair' },
                  { label: '全局重排', value: 'global_reschedule' },
                ]}
              />
            </Form.Item>
            <Form.Item name="key_parameter_thresholds" label="关键参数阈值 (JSON)">
              <Input.TextArea rows={3} placeholder='{"max_delay_minutes": 30}' />
            </Form.Item>
          </Form>
        </Modal>
      </Content>
    </Layout>
  );
};

export default CaseLibraryPage;
