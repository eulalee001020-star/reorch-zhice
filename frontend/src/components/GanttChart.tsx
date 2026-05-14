/**
 * 甘特图组件 — MVP: Ant Design Table as simplified gantt representation.
 *
 * - Operation rows with time bars (CSS-based)
 * - Support device/work-order/timeline view toggle
 * - Diff highlighting for adjusted operations
 *
 * Requirements: 12.3, 12.10, 13.2, 27.1-27.9
 */

import React, { useMemo, useState } from 'react';
import { Card, Table, Tag, Radio, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import type { GanttDiffPayload, CandidatePlan } from '@/types';

type ViewMode = 'device' | 'work_order' | 'timeline';

interface GanttRow {
  key: string;
  group: string;
  operation_id: string;
  resource_id: string;
  work_order_id: string;
  start_time: string;
  end_time: string;
  is_adjusted: boolean;
  is_affected: boolean;
}

interface GanttChartProps {
  ganttDiff: GanttDiffPayload;
  candidatePlans: CandidatePlan[];
  selectedPlanId: string;
}

export const GanttChart: React.FC<GanttChartProps> = ({
  ganttDiff,
  candidatePlans,
  selectedPlanId,
}) => {
  const [viewMode, setViewMode] = useState<ViewMode>('device');

  const plan = candidatePlans.find((p) => p.plan_id === selectedPlanId);

  // Build rows from plan schedule detail
  const rows: GanttRow[] = useMemo(() => {
    if (!plan) return [];

    const adjustedOpIds = new Set(
      ganttDiff.adjusted_operations.map((a) => String(a.operation_id ?? '')),
    );

    const allOps: GanttRow[] = [];
    for (const wo of plan.schedule_detail.work_orders) {
      for (const op of wo.operations) {
        allOps.push({
          key: op.operation_id,
          group:
            viewMode === 'device'
              ? op.resource_id
              : viewMode === 'work_order'
                ? wo.work_order_id
                : dayjs(op.start_time).format('YYYY-MM-DD'),
          operation_id: op.operation_id,
          resource_id: op.resource_id,
          work_order_id: wo.work_order_id,
          start_time: op.start_time,
          end_time: op.end_time,
          is_adjusted: adjustedOpIds.has(op.operation_id),
          is_affected: op.is_affected,
        });
      }
    }

    // Sort by group then start_time
    allOps.sort((a, b) => {
      if (a.group !== b.group) return a.group.localeCompare(b.group);
      return dayjs(a.start_time).valueOf() - dayjs(b.start_time).valueOf();
    });

    return allOps;
  }, [plan, ganttDiff, viewMode]);

  // Compute time range for bar rendering
  const { minTime, maxTime } = useMemo(() => {
    if (rows.length === 0) return { minTime: 0, maxTime: 1 };
    const times = rows.flatMap((r) => [
      dayjs(r.start_time).valueOf(),
      dayjs(r.end_time).valueOf(),
    ]);
    return { minTime: Math.min(...times), maxTime: Math.max(...times) };
  }, [rows]);

  const timeRange = maxTime - minTime || 1;

  const columns: ColumnsType<GanttRow> = [
    {
      title: viewMode === 'device' ? '设备' : viewMode === 'work_order' ? '工单' : '日期',
      dataIndex: 'group',
      width: 100,
      ellipsis: true,
    },
    {
      title: '工序',
      dataIndex: 'operation_id',
      width: 90,
      ellipsis: true,
    },
    {
      title: '开始',
      dataIndex: 'start_time',
      width: 110,
      render: (t: string) => dayjs(t).format('MM-DD HH:mm'),
    },
    {
      title: '结束',
      dataIndex: 'end_time',
      width: 110,
      render: (t: string) => dayjs(t).format('MM-DD HH:mm'),
    },
    {
      title: '时间条',
      key: 'bar',
      render: (_: unknown, row: GanttRow) => {
        const start = dayjs(row.start_time).valueOf();
        const end = dayjs(row.end_time).valueOf();
        const left = ((start - minTime) / timeRange) * 100;
        const width = ((end - start) / timeRange) * 100;
        const bgColor = row.is_adjusted
          ? '#ff7a45'
          : row.is_affected
            ? '#ffc069'
            : '#91caff';

        return (
          <Tooltip title={`${row.operation_id}: ${dayjs(row.start_time).format('HH:mm')} - ${dayjs(row.end_time).format('HH:mm')}`}>
            <div
              style={{
                position: 'relative',
                height: 18,
                background: '#f5f5f5',
                borderRadius: 2,
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  left: `${left}%`,
                  width: `${Math.max(width, 1)}%`,
                  height: '100%',
                  background: bgColor,
                  borderRadius: 2,
                  border: row.is_adjusted ? '1px solid #d4380d' : undefined,
                }}
              />
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: '标记',
      key: 'tags',
      width: 100,
      render: (_: unknown, row: GanttRow) => (
        <>
          {row.is_adjusted && <Tag color="volcano">已调整</Tag>}
          {row.is_affected && !row.is_adjusted && <Tag color="orange">受影响</Tag>}
        </>
      ),
    },
  ];

  return (
    <Card
      type="inner"
      size="small"
      title="甘特图"
      extra={
        <Radio.Group
          size="small"
          value={viewMode}
          onChange={(e) => setViewMode(e.target.value)}
        >
          <Radio.Button value="device">设备视角</Radio.Button>
          <Radio.Button value="work_order">工单视角</Radio.Button>
          <Radio.Button value="timeline">时间轴</Radio.Button>
        </Radio.Group>
      }
    >
      <Table<GanttRow>
        dataSource={rows}
        columns={columns}
        rowKey="key"
        size="small"
        pagination={{ pageSize: 50, size: 'small' }}
        scroll={{ y: 300 }}
      />
    </Card>
  );
};
