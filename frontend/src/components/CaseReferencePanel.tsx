/**
 * 历史案例参考与偏好画像 — 在工作台上直接可见。
 *
 * - Show matched historical cases
 * - Preference profile summary
 * - Manual weight adjustments
 * - Must be visible on workbench, not hidden in secondary pages
 *
 * Requirements: 31.6
 */

import React, { useEffect, useState } from 'react';
import {
  Card,
  Table,
  Tag,
  Descriptions,
  Slider,
  Space,
  Button,
  Empty,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { usePlanStore, useWorkbenchStore } from '@/stores';
import { refreshRecommendation } from '@/stores';
import type { CaseRecord, PreferenceProfile } from '@/types';
import { listCases, getPreferenceProfile } from '@/api';

export const CaseReferencePanel: React.FC = () => {
  const incidentContextId = useWorkbenchStore((s) => s.incidentContextId);
  const planSelectionOutput = usePlanStore((s) => s.planSelectionOutput);
  const manualWeights = usePlanStore((s) => s.manualWeights);
  const setManualWeights = usePlanStore((s) => s.setManualWeights);

  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [profile, setProfile] = useState<PreferenceProfile | null>(null);
  const [loadingCases, setLoadingCases] = useState(false);

  // Fetch matched cases when recommendation is available
  useEffect(() => {
    if (!planSelectionOutput?.matched_case_ids?.length) {
      setCases([]);
      return;
    }
    setLoadingCases(true);
    listCases()
      .then((all) => {
        const matched = all.filter((c) =>
          planSelectionOutput.matched_case_ids.includes(c.case_id),
        );
        setCases(matched);
      })
      .catch(() => setCases([]))
      .finally(() => setLoadingCases(false));
  }, [planSelectionOutput?.matched_case_ids]);

  // Fetch preference profile
  useEffect(() => {
    getPreferenceProfile('current_planner')
      .then(setProfile)
      .catch(() => setProfile(null));
  }, []);

  const caseColumns: ColumnsType<CaseRecord> = [
    {
      title: '案例 ID',
      dataIndex: 'case_id',
      width: 80,
      render: (id: string) => id.slice(0, 8),
    },
    {
      title: '策略',
      dataIndex: 'strategy_type',
      width: 100,
      render: (s: string) => <Tag>{s}</Tag>,
    },
    {
      title: 'Override',
      dataIndex: 'is_override',
      width: 70,
      render: (v: boolean) => (v ? <Tag color="red">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 100,
      render: (t: string) => dayjs(t).format('MM-DD HH:mm'),
    },
  ];

  // Weight adjustment
  const currentWeights = manualWeights ?? planSelectionOutput?.weights_used ?? {};
  const weightKeys = Object.keys(currentWeights);

  const handleWeightChange = (key: string, value: number) => {
    const updated = { ...currentWeights, [key]: value / 100 };
    setManualWeights(updated);
  };

  const handleApplyWeights = () => {
    if (incidentContextId) {
      refreshRecommendation(incidentContextId);
    }
  };

  return (
    <Card title="历史案例 & 偏好画像" size="small">
      {/* Matched cases */}
      {cases.length > 0 ? (
        <Table<CaseRecord>
          dataSource={cases}
          columns={caseColumns}
          rowKey="case_id"
          size="small"
          pagination={false}
          loading={loadingCases}
          style={{ marginBottom: 12 }}
        />
      ) : (
        <Empty description="暂无匹配案例" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}

      {/* Preference profile summary */}
      {profile && (
        <Descriptions
          size="small"
          column={2}
          title="偏好画像"
          style={{ marginTop: 8, marginBottom: 8 }}
        >
          {Object.entries(profile.strategy_preferences).map(([key, val]) => (
            <Descriptions.Item key={key} label={key}>
              {(val * 100).toFixed(0)}%
            </Descriptions.Item>
          ))}
          <Descriptions.Item label="Override 次数">
            {profile.override_history.length}
          </Descriptions.Item>
        </Descriptions>
      )}

      {/* Manual weight adjustments */}
      {weightKeys.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontWeight: 500, marginBottom: 8, fontSize: 13 }}>
            权重微调
          </div>
          {weightKeys.map((key) => (
            <div key={key} style={{ marginBottom: 4 }}>
              <Space>
                <span style={{ width: 140, display: 'inline-block', fontSize: 12 }}>
                  {key}
                </span>
                <Slider
                  min={0}
                  max={100}
                  value={Math.round((currentWeights[key] ?? 0) * 100)}
                  onChange={(v) => handleWeightChange(key, v)}
                  style={{ width: 120 }}
                />
              </Space>
            </div>
          ))}
          <Button size="small" type="primary" onClick={handleApplyWeights} style={{ marginTop: 8 }}>
            应用权重
          </Button>
        </div>
      )}
    </Card>
  );
};
