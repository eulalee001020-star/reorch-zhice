/**
 * Supply page: kit status of the schedule, arrived-vs-usable readiness,
 * supplier scores and MRP netting.
 *
 * Read-only. The data comes from the supply snapshot imported next to the
 * schedule snapshot; when none is imported the page says how to get one.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Card,
  Col,
  Empty,
  Row,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { getKitReport, getMrp, getSupplierScores, getSupplyReadiness } from '@/api';
import type {
  KitReport,
  MrpRecord,
  MrpResult,
  OperationKit,
  ReadinessLine,
  ReadinessReport,
  SupplierScore,
} from '@/types';

const { Text } = Typography;

const TIER_COLORS: Record<string, string> = { A: 'green', B: 'blue', C: 'red', unrated: 'default' };

function formatTime(value: string | null): string {
  return value ? dayjs(value).format('MM-DD HH:mm') : '未知';
}

function formatQuantity(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function sourceLabel(source: string): string {
  if (source === 'stock') return '库存';
  if (source.startsWith('substitute:')) return `替代料 ${source.slice('substitute:'.length)}`;
  if (source.startsWith('pending:')) return `${source.slice('pending:'.length)} 时间未定`;
  return source;
}

function kitStatus(kit: OperationKit): React.ReactNode {
  if (!kit.is_complete) return <Tag color="red">缺料，无到货时间</Tag>;
  if (kit.wait_minutes > 0) return <Tag color="orange">需等料 {Math.round(kit.wait_minutes)} 分钟</Tag>;
  return <Tag color="green">按时齐套</Tag>;
}

const SupplyPage: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [riskAdjusted, setRiskAdjusted] = useState(false);
  const [allowSubstitutes, setAllowSubstitutes] = useState(false);
  const [kit, setKit] = useState<KitReport | null>(null);
  const [readiness, setReadiness] = useState<ReadinessReport | null>(null);
  const [suppliers, setSuppliers] = useState<SupplierScore[]>([]);
  const [mrp, setMrp] = useState<MrpResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [kitReport, readinessReport, supplierScores, mrpResult] = await Promise.all([
        getKitReport({ risk_adjusted: riskAdjusted, allow_substitutes: allowSubstitutes }),
        getSupplyReadiness(),
        getSupplierScores(),
        getMrp(3),
      ]);
      setKit(kitReport);
      setReadiness(readinessReport);
      setSuppliers(supplierScores);
      setMrp(mrpResult);
      setMissing(false);
    } catch (caught) {
      const status = (caught as { response?: { status?: number } }).response?.status;
      if (status === 404) {
        setMissing(true);
      } else {
        setError('物料数据加载失败，请确认后端已启动。');
      }
    } finally {
      setLoading(false);
    }
  }, [riskAdjusted, allowSubstitutes]);

  useEffect(() => {
    void load();
  }, [load]);

  const kitColumns: ColumnsType<OperationKit> = [
    { title: '工序', dataIndex: 'operation_id', width: 150 },
    { title: '工单', dataIndex: 'work_order_id', width: 130 },
    {
      title: '计划开工',
      dataIndex: 'planned_start',
      width: 110,
      render: (value: string) => formatTime(value),
    },
    {
      title: '齐套时间',
      dataIndex: 'ready_at',
      width: 110,
      render: (value: string | null) => formatTime(value),
    },
    { title: '状态', width: 170, render: (_, row) => kitStatus(row) },
    {
      title: '物料与来源',
      render: (_, row) => (
        <Space direction="vertical" size={2}>
          {row.requirements.map((item) => (
            <Text key={item.item_id}>
              {item.item_id}：需 {formatQuantity(item.required_quantity)}，已落实{' '}
              {formatQuantity(item.covered_quantity)}
              <Text type="secondary">（{item.sources.map(sourceLabel).join('、') || '无来源'}）</Text>
            </Text>
          ))}
        </Space>
      ),
    },
  ];

  const readinessColumns: ColumnsType<ReadinessLine> = [
    { title: '到货单', dataIndex: 'order_key', width: 110 },
    { title: '物料', dataIndex: 'item_id', width: 120 },
    { title: '数量', dataIndex: 'quantity', width: 80 },
    {
      title: '已到货',
      dataIndex: 'arrived',
      width: 80,
      render: (value: boolean) => (value ? <Tag color="blue">已到货</Tag> : <Tag>在途</Tag>),
    },
    {
      title: '可使用',
      dataIndex: 'usable',
      width: 150,
      render: (value: boolean, row) =>
        value ? <Tag color="green">可使用</Tag> : <Tag color="orange">预计 {formatTime(row.usable_at)}</Tag>,
    },
    {
      title: '挡住使用的缺项',
      render: (_, row) =>
        row.open_gaps.length === 0 ? (
          <Text type="secondary">无</Text>
        ) : (
          <Space direction="vertical" size={2}>
            {row.open_gaps.map((gap) => (
              <Text key={gap.gap_id}>
                {gap.description}
                <Text type={gap.owner ? 'secondary' : 'danger'}>
                  {' '}
                  · {gap.owner ?? '无责任人'} · {gap.due_at ? formatTime(gap.due_at) : '无完成时间'}
                </Text>
                {row.overdue_gap_ids.includes(gap.gap_id) && <Tag color="red">已超期</Tag>}
              </Text>
            ))}
          </Space>
        ),
    },
  ];

  const supplierColumns: ColumnsType<SupplierScore> = [
    { title: '供应商', dataIndex: 'name', width: 130, ellipsis: true },
    {
      title: '等级',
      dataIndex: 'tier',
      width: 80,
      render: (tier: string) => <Tag color={TIER_COLORS[tier]}>{tier === 'unrated' ? '未评级' : tier}</Tag>,
    },
    { title: '评分', dataIndex: 'score', width: 70 },
    { title: '交付次数', dataIndex: 'deliveries', width: 90 },
    {
      title: '准时率',
      dataIndex: 'on_time_rate',
      width: 80,
      render: (value: number) => `${(value * 100).toFixed(0)}%`,
    },
    {
      title: '不合格率',
      dataIndex: 'reject_rate',
      width: 90,
      render: (value: number) => `${(value * 100).toFixed(1)}%`,
    },
    {
      title: (
        <Tooltip title="历史延迟的第 80 百分位。勾选“按供应商风险”后，会加到该供应商的承诺日期上。">
          承诺日期缓冲
        </Tooltip>
      ),
      dataIndex: 'late_p80_minutes',
      width: 120,
      render: (value: number) => (value > 0 ? `${(value / 60).toFixed(1)} 小时` : '无'),
    },
  ];

  const mrpColumns: ColumnsType<MrpRecord> = [
    { title: '物料', dataIndex: 'item_id', width: 140 },
    { title: '期初可用', dataIndex: 'opening_balance', width: 90 },
    { title: '安全库存', dataIndex: 'safety_stock', width: 90 },
    ...(mrp?.records[0]?.buckets ?? []).map((bucket, index) => ({
      title: dayjs(bucket.bucket_start).format('MM-DD'),
      key: `bucket-${index}`,
      render: (_: unknown, row: MrpRecord) => {
        const cell = row.buckets[index];
        return (
          <Space direction="vertical" size={0}>
            <Text>毛需求 {formatQuantity(cell.gross_requirement)}</Text>
            <Text type="secondary">在途 {formatQuantity(cell.scheduled_receipt)}</Text>
            <Text type={cell.net_requirement > 0 ? 'danger' : undefined}>
              结余 {formatQuantity(cell.projected_available)}
            </Text>
            {cell.planned_order_release > 0 && (
              <Tag color="gold">建议下达 {formatQuantity(cell.planned_order_release)}</Tag>
            )}
          </Space>
        );
      },
    })),
    {
      title: '已错过下达',
      dataIndex: 'past_due_release',
      width: 110,
      render: (value: number) => (value > 0 ? <Tag color="red">{formatQuantity(value)}</Tag> : '-'),
    },
  ];

  if (loading && !kit) {
    return (
      <div style={{ padding: 24 }}>
        <Spin />
      </div>
    );
  }

  if (missing) {
    return (
      <div className="demo-page">
        <Empty
          description={
            <Space direction="vertical">
              <Text>还没有导入物料数据。</Text>
              <Text type="secondary">
                本地演示可运行 python tools/run_local_demo.py --scenario material --serve
              </Text>
            </Space>
          }
        />
      </div>
    );
  }

  return (
    <div className="demo-page">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div className="demo-hero">
          <div className="hero-eyebrow">Supply Readiness</div>
          <h1 className="hero-title">每道工序开工前，料齐了吗</h1>
          <div className="hero-subtitle">
            按需求时间把库存和在途分配给工序，区分“已到货”和“可使用”。供应出问题时，这里的齐套时间就是重排要遵守的开工下限。
          </div>
        </div>

        {error && <Alert type="error" showIcon message={error} />}

        <Card size="small" title="齐套概览">
          <Row gutter={[12, 12]} align="middle">
            <Col xs={12} md={4}>
              <Statistic title="待开工工序" value={kit?.operations.length ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="按时齐套率" value={((kit?.on_time_kit_rate ?? 0) * 100).toFixed(0)} suffix="%" />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="需等料" value={kit?.late_operation_ids.length ?? 0} />
            </Col>
            <Col xs={12} md={4}>
              <Statistic title="缺料无时间" value={kit?.unresolved_operation_ids.length ?? 0} />
            </Col>
            <Col xs={24} md={8}>
              <Space direction="vertical" size={4}>
                <Space>
                  <Switch checked={riskAdjusted} onChange={setRiskAdjusted} size="small" />
                  <Text>按供应商历史延迟给承诺日期加缓冲</Text>
                </Space>
                <Space>
                  <Switch checked={allowSubstitutes} onChange={setAllowSubstitutes} size="small" />
                  <Text>允许使用已批准的替代料</Text>
                </Space>
              </Space>
            </Col>
          </Row>
        </Card>

        <Card size="small" title="工序齐套">
          <Table
            size="small"
            rowKey="operation_id"
            loading={loading}
            columns={kitColumns}
            dataSource={kit?.operations ?? []}
            pagination={false}
          />
        </Card>

        <Card
          size="small"
          title="到货与可用"
          extra={
            <Text type="secondary">
              已到货 {readiness?.arrived_count ?? 0} 行，其中 {readiness?.arrived_not_usable_count ?? 0} 行还不能用；
              未关闭缺项 {readiness?.open_gap_count ?? 0} 项，无责任人 {readiness?.unowned_gap_count ?? 0} 项
            </Text>
          }
        >
          <Table
            size="small"
            rowKey="order_key"
            columns={readinessColumns}
            dataSource={readiness?.lines ?? []}
            pagination={false}
          />
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={24} xl={10}>
            <Card size="small" title="供应商评分">
              <Table
                size="small"
                rowKey="supplier_id"
                columns={supplierColumns}
                dataSource={suppliers}
                pagination={false}
                scroll={{ x: 660 }}
              />
            </Card>
          </Col>
          <Col xs={24} xl={14}>
            <Card size="small" title="MRP 净需求（按天）">
              <Table
                size="small"
                rowKey="item_id"
                columns={mrpColumns}
                dataSource={(mrp?.records ?? []).filter((record) =>
                  record.buckets.some((bucket) => bucket.gross_requirement > 0),
                )}
                pagination={false}
                scroll={{ x: 760 }}
              />
            </Card>
          </Col>
        </Row>
      </Space>
    </div>
  );
};

export default SupplyPage;
