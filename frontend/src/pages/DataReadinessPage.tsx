import React, { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Input,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CheckCircleOutlined, StopOutlined, UploadOutlined, WarningOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { assessInitialScheduleReadiness, normalizeEnterpriseImport } from '@/api';
import type {
  DataReadinessReport,
  EnterpriseFieldMapping,
  InitialScheduleRequest,
  ReadinessIssue,
} from '@/types';

const { Text } = Typography;

interface StopRule {
  key: string;
  condition: string;
  productAction: string;
  promiseBoundary: string;
}

const stopRules: StopRule[] = [
  {
    key: 'blocker',
    condition: '存在 blocker',
    productAction: '只输出字段缺口和修复建议',
    promiseBoundary: '不生成重排方案，不进入 ROI 或采纳率统计',
  },
  {
    key: 'score-low',
    condition: 'readiness < 0.70',
    productAction: '进入数据治理 / mapping 修复',
    promiseBoundary: '只承诺 readiness 评估，不承诺调度效果',
  },
  {
    key: 'score-mid',
    condition: '0.70 <= readiness < 0.85',
    productAction: '允许历史 replay，小范围人工复核',
    promiseBoundary: '不允许自动写回，不用于正式价值归因',
  },
  {
    key: 'score-high',
    condition: 'readiness >= 0.85 且 blocker = 0',
    productAction: '允许 shadow mode 和 Top-K 候选评审',
    promiseBoundary: '仍需计划员确认，不能无人值守执行',
  },
];

const stopRuleColumns: ColumnsType<StopRule> = [
  { title: '停损条件', dataIndex: 'condition', width: 210 },
  { title: '产品动作', dataIndex: 'productAction' },
  { title: '承诺边界', dataIndex: 'promiseBoundary' },
];

const issueColumns: ColumnsType<ReadinessIssue> = [
  {
    title: '级别',
    dataIndex: 'severity',
    width: 110,
    render: (severity: string) => {
      const color = severity === 'blocker' ? 'red' : severity === 'warning' ? 'orange' : 'blue';
      return <Tag color={color}>{severity}</Tag>;
    },
  },
  { title: '代码', dataIndex: 'code', width: 220 },
  { title: '对象', render: (_, row) => row.entity_id ?? row.entity_type ?? '-' },
  { title: '说明', dataIndex: 'message' },
];

function buildReadyRequest(): InitialScheduleRequest {
  const start = dayjs('2026-05-12T08:00:00+08:00');
  return {
    workshop_id: 'WS-HMLV-01',
    planning_start: start.toISOString(),
    goal_modes: ['balanced'],
    max_solutions: 3,
    time_budget_seconds: 6,
    resources: [
      {
        resource_id: 'CNC-01',
        name: 'CNC bottleneck',
        capabilities: ['milling', 'drilling'],
        is_bottleneck: true,
        has_redundancy: false,
        criticality: 'bottleneck',
        cost_per_minute: 6,
      },
      {
        resource_id: 'QC-01',
        name: 'CMM Inspection',
        capabilities: ['inspection'],
        is_bottleneck: false,
        has_redundancy: false,
        criticality: 'quality_gate',
        cost_per_minute: 5,
      },
    ],
    resource_calendar: [],
    changeover_rules: [
      { from_product_family: 'A', to_product_family: 'B', setup_minutes: 20, cost: 500 },
    ],
    work_orders: [
      {
        work_order_id: 'WO-DR-001',
        product_name: 'Urgent valve block',
        product_family: 'A',
        priority: 4,
        due_date: start.add(8, 'hour').toISOString(),
        operations: [
          {
            operation_id: 'WO-DR-001-10',
            work_order_id: 'WO-DR-001',
            duration_minutes: 120,
            eligible_resource_ids: ['CNC-01'],
            required_capabilities: ['milling'],
            predecessor_ids: [],
            product_family: 'A',
            material_requirements: [
              {
                material_id: 'AL-7075',
                required_quantity: 1,
                available_at: start.toISOString(),
                status: 'available',
              },
            ],
          },
          {
            operation_id: 'WO-DR-001-20',
            work_order_id: 'WO-DR-001',
            duration_minutes: 45,
            eligible_resource_ids: ['QC-01'],
            required_capabilities: ['inspection'],
            predecessor_ids: ['WO-DR-001-10'],
            product_family: 'A',
            material_requirements: [],
          },
        ],
      },
    ],
  };
}

function buildBlockedRequest(): InitialScheduleRequest {
  const request = buildReadyRequest();
  return {
    ...request,
    resources: request.resources.filter((resource) => resource.resource_id !== 'QC-01'),
  };
}

function defaultEnterprisePayload(): Record<string, unknown> {
  return {
    resources: [
      {
        id: 'CNC-01',
        name: 'CNC bottleneck',
        skills: ['milling', 'drilling'],
        is_bottleneck: true,
        criticality: 'bottleneck',
        cost_per_minute: 6,
      },
      {
        id: 'QC-01',
        name: 'CMM Inspection',
        skills: ['inspection'],
        criticality: 'quality_gate',
        cost_per_minute: 5,
      },
    ],
    work_orders: [
      {
        orderNo: 'WO-IMPORT-001',
        name: 'Imported urgent valve block',
        family: 'A',
        due: '2026-05-12T16:00:00+08:00',
        prio: 4,
        ops: [
          {
            opNo: 'WO-IMPORT-001-10',
            minutes: 120,
            machines: ['CNC-01'],
            skills: ['milling'],
            predecessors: [],
            family: 'A',
          },
          {
            opNo: 'WO-IMPORT-001-20',
            minutes: 45,
            machines: ['QC-01'],
            skills: ['inspection'],
            predecessors: ['WO-IMPORT-001-10'],
            family: 'A',
          },
        ],
      },
    ],
  };
}

function defaultMapping(): EnterpriseFieldMapping {
  return {
    work_orders_path: 'work_orders',
    resources_path: 'resources',
    work_order_id: 'orderNo',
    product_name: 'name',
    product_family: 'family',
    due_date: 'due',
    priority: 'prio',
    operations: 'ops',
    operation_id: 'opNo',
    duration_minutes: 'minutes',
    resource_id: 'resource_id',
    eligible_resource_ids: 'machines',
    required_capabilities: 'skills',
    predecessor_ids: 'predecessors',
    resource_capabilities: 'skills',
  };
}

function getPath(payload: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>((current, segment) => {
    if (!current || typeof current !== 'object' || Array.isArray(current)) return undefined;
    return (current as Record<string, unknown>)[segment];
  }, payload);
}

function hasField(payload: unknown, field: string): boolean {
  return Boolean(payload && typeof payload === 'object' && field in payload);
}

function validateMapping(
  raw: Record<string, unknown>,
  mapping: EnterpriseFieldMapping,
): ReadinessIssue[] {
  const issues: ReadinessIssue[] = [];
  const resources = getPath(raw, mapping.resources_path);
  const workOrders = getPath(raw, mapping.work_orders_path);
  if (!Array.isArray(resources) || resources.length === 0) {
    issues.push({
      severity: 'blocker',
      code: 'MAPPING_RESOURCES_PATH',
      message: `resources_path "${mapping.resources_path}" 未定位到非空数组。`,
      entity_type: 'mapping',
      entity_id: mapping.resources_path,
    });
  }
  if (!Array.isArray(workOrders) || workOrders.length === 0) {
    issues.push({
      severity: 'blocker',
      code: 'MAPPING_WORK_ORDERS_PATH',
      message: `work_orders_path "${mapping.work_orders_path}" 未定位到非空数组。`,
      entity_type: 'mapping',
      entity_id: mapping.work_orders_path,
    });
  }

  const firstResource = Array.isArray(resources) ? resources[0] : null;
  if (firstResource && !hasField(firstResource, 'resource_id') && !hasField(firstResource, 'id')) {
    issues.push({
      severity: 'blocker',
      code: 'MAPPING_RESOURCE_ID',
      message: '资源记录必须包含 resource_id 或 id，作为 canonical resource_id。',
      entity_type: 'resource',
      entity_id: 'first_resource',
    });
  }
  if (firstResource && !hasField(firstResource, mapping.resource_capabilities)) {
    issues.push({
      severity: 'warning',
      code: 'MAPPING_RESOURCE_CAPABILITIES',
      message: `资源能力字段 "${mapping.resource_capabilities}" 缺失，会削弱能力匹配校验。`,
      entity_type: 'resource',
      entity_id: 'first_resource',
    });
  }

  const firstOrder = Array.isArray(workOrders) ? workOrders[0] : null;
  const requiredOrderFields: Array<[keyof EnterpriseFieldMapping, string]> = [
    ['work_order_id', '工单 ID'],
    ['product_name', '产品名称'],
    ['due_date', '交期'],
    ['operations', '工序数组'],
  ];
  requiredOrderFields.forEach(([key, label]) => {
    if (firstOrder && !hasField(firstOrder, mapping[key])) {
      issues.push({
        severity: 'blocker',
        code: `MAPPING_${String(key).toUpperCase()}`,
        message: `${label} 字段 "${mapping[key]}" 在首条工单中不存在。`,
        entity_type: 'work_order',
        entity_id: 'first_work_order',
      });
    }
  });

  const operations = firstOrder && hasField(firstOrder, mapping.operations)
    ? (firstOrder as Record<string, unknown>)[mapping.operations]
    : [];
  const firstOperation = Array.isArray(operations) ? operations[0] : null;
  const requiredOperationFields: Array<[keyof EnterpriseFieldMapping, string]> = [
    ['operation_id', '工序 ID'],
    ['duration_minutes', '加工时长'],
    ['eligible_resource_ids', '可用资源'],
    ['required_capabilities', '所需能力'],
  ];
  requiredOperationFields.forEach(([key, label]) => {
    if (firstOperation && !hasField(firstOperation, mapping[key])) {
      issues.push({
        severity: key === 'required_capabilities' ? 'warning' : 'blocker',
        code: `MAPPING_${String(key).toUpperCase()}`,
        message: `${label} 字段 "${mapping[key]}" 在首道工序中不存在。`,
        entity_type: 'operation',
        entity_id: 'first_operation',
      });
    }
  });
  return issues;
}

function readinessPolicy(report: DataReadinessReport | null): {
  label: string;
  color: 'success' | 'exception' | 'normal' | 'active';
  description: string;
} {
  if (!report) {
    return {
      label: '未评估',
      color: 'normal',
      description: '先运行 readiness，再决定是否允许 replay、shadow mode 或重排。',
    };
  }
  if (report.blockers.length > 0) {
    return {
      label: '停损',
      color: 'exception',
      description: '存在阻断项，只能输出数据缺口，不进入方案生成和价值归因。',
    };
  }
  if (report.readiness_score < 0.7) {
    return {
      label: '数据修复',
      color: 'exception',
      description: '字段质量不足，只做 mapping 和数据治理，不承诺重排效果。',
    };
  }
  if (report.readiness_score < 0.85) {
    return {
      label: '受限 replay',
      color: 'active',
      description: '可做历史 replay 和人工复核，不能自动写回或计入正式 ROI。',
    };
  }
  return {
    label: '可进入 shadow',
    color: 'success',
    description: '可进入 shadow mode 和 Top-K 候选评审，但仍需计划员确认。',
  };
}

const DataReadinessPage: React.FC = () => {
  const readyRequest = useMemo(() => buildReadyRequest(), []);
  const blockedRequest = useMemo(() => buildBlockedRequest(), []);
  const [report, setReport] = useState<DataReadinessReport | null>(null);
  const [importedRequest, setImportedRequest] = useState<InitialScheduleRequest | null>(null);
  const [rawPayloadText, setRawPayloadText] = useState(() =>
    JSON.stringify(defaultEnterprisePayload(), null, 2),
  );
  const [mapping, setMapping] = useState<EnterpriseFieldMapping>(() => defaultMapping());
  const [mappingIssues, setMappingIssues] = useState<ReadinessIssue[]>([]);
  const [loading, setLoading] = useState(false);
  const policy = readinessPolicy(report);
  const issues = report ? [...report.blockers, ...report.warnings, ...report.infos] : [];

  const run = async (request: InitialScheduleRequest) => {
    setLoading(true);
    try {
      setReport(await assessInitialScheduleReadiness(request));
    } finally {
      setLoading(false);
    }
  };

  const importAndValidate = async () => {
    setLoading(true);
    try {
      const raw = JSON.parse(rawPayloadText) as Record<string, unknown>;
      const nextMappingIssues = validateMapping(raw, mapping);
      setMappingIssues(nextMappingIssues);
      if (nextMappingIssues.some((item) => item.severity === 'blocker')) {
        message.error('Mapping 存在 blocker，不能进入 readiness');
        return;
      }
      const response = await normalizeEnterpriseImport({
        source_system: 'customer_file_import',
        workshop_id: 'WS-CUSTOMER-PILOT',
        planning_start: dayjs('2026-05-12T08:00:00+08:00').toISOString(),
        raw_payload: raw,
        mapping,
      });
      setImportedRequest(response.initial_schedule_request);
      setReport(response.readiness_report);
      message.success('文件导入、mapping 校验和 readiness 已完成');
    } catch {
      message.error('导入失败：请检查 JSON 格式、日期字段和 mapping');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Card
          size="small"
          title="Data Readiness"
          extra={
            <Space>
              <Button icon={<WarningOutlined />} onClick={() => run(blockedRequest)}>
                评估缺字段样本
              </Button>
              <Button type="primary" icon={<CheckCircleOutlined />} onClick={() => run(readyRequest)}>
                评估可运行样本
              </Button>
            </Space>
          }
        >
          <Row gutter={[12, 12]} align="middle">
            <Col xs={24} md={6}>
              <Progress
                type="dashboard"
                percent={Math.round((report?.readiness_score ?? 0) * 100)}
                status={policy.color}
              />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="当前策略" value={policy.label} prefix={<StopOutlined />} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="Blocker" value={report?.blockers.length ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="Warning" value={report?.warnings.length ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="Required Fields" value={report?.required_inputs.length ?? 0} />
            </Col>
          </Row>
          <Alert type={policy.color === 'exception' ? 'error' : 'info'} showIcon message={policy.description} />
        </Card>

        <Card size="small" title="客户文件导入与 Mapping 校验">
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space wrap>
              <Upload
                accept="application/json,.json"
                maxCount={1}
                beforeUpload={(file) => {
                  void file.text().then((text) => {
                    setRawPayloadText(text);
                    setMappingIssues([]);
                  });
                  return false;
                }}
              >
                <Button icon={<UploadOutlined />}>导入 JSON 文件</Button>
              </Upload>
              <Button type="primary" loading={loading} onClick={importAndValidate}>
                校验 Mapping 并评估 Readiness
              </Button>
            </Space>
            <Row gutter={[12, 12]}>
              <Col xs={24} lg={12}>
                <Text strong>Raw payload</Text>
                <Input.TextArea
                  rows={12}
                  value={rawPayloadText}
                  onChange={(event) => setRawPayloadText(event.target.value)}
                  style={{ fontFamily: 'monospace', marginTop: 6 }}
                />
              </Col>
              <Col xs={24} lg={12}>
                <Text strong>Mapping profile</Text>
                <Row gutter={[8, 8]} style={{ marginTop: 6 }}>
                  {Object.entries(mapping).map(([key, value]) => (
                    <Col xs={24} md={12} key={key}>
                      <Input
                        addonBefore={key}
                        value={value}
                        onChange={(event) =>
                          setMapping((current) => ({
                            ...current,
                            [key]: event.target.value,
                          }))
                        }
                      />
                    </Col>
                  ))}
                </Row>
              </Col>
            </Row>
            <Divider style={{ margin: '4px 0' }} />
            <Table
              rowKey={(row) => `${row.code}-${row.entity_id ?? row.message}`}
              columns={issueColumns}
              dataSource={mappingIssues}
              size="small"
              pagination={false}
              locale={{ emptyText: 'Mapping 尚未校验，或没有发现问题' }}
            />
            {importedRequest && (
              <Alert
                type="success"
                showIcon
                message="已生成 canonical InitialScheduleRequest"
                description={`工单 ${importedRequest.work_orders.length} 个，资源 ${importedRequest.resources.length} 个。通过 readiness 后才允许 replay / Top-K / ROI 归因。`}
              />
            )}
          </Space>
        </Card>

        <Card size="small" title="停损规则">
          <Table
            rowKey="key"
            columns={stopRuleColumns}
            dataSource={stopRules}
            size="small"
            pagination={false}
          />
        </Card>

        <Card size="small" title="数据问题与修复建议">
          <Table
            rowKey={(row) => `${row.severity}-${row.code}-${row.entity_id ?? row.entity_type ?? 'global'}`}
            loading={loading}
            columns={issueColumns}
            dataSource={issues}
            size="small"
            pagination={false}
            locale={{ emptyText: '暂无问题，或尚未运行评估' }}
          />
          {report?.recommendations.length ? (
            <Space direction="vertical" style={{ marginTop: 12 }}>
              {report.recommendations.map((item) => (
                <Text key={item}>{item}</Text>
              ))}
            </Space>
          ) : null}
        </Card>
      </Space>
    </div>
  );
};

export default DataReadinessPage;
