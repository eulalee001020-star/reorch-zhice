/**
 * 推荐与确认区 — 展示推荐理由 + 三种确认操作。
 *
 * - Show recommendation: plan ID, confidence, auto-preselect, core reasons, risks
 * - "Why not another plan" comparison summary
 * - Low confidence → no auto-select, prompt compare top-2
 * - 3 buttons: Accept, Adjust, Reject
 * - Adjust mode: simple form for operation adjustments
 * - Reject: override reason modal (required)
 * - After confirm: show success + writeback progress
 *
 * Requirements: 13.1-13.12, 31.4, 31.7
 */

import React, { useState } from 'react';
import {
  Card,
  Button,
  Tag,
  Descriptions,
  Alert,
  Modal,
  Input,
  Space,
  Spin,
  Progress,
  Divider,
  Form,
  InputNumber,
  message,
} from 'antd';
import {
  CheckOutlined,
  EditOutlined,
  RollbackOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
} from '@ant-design/icons';
import {
  useWorkbenchStore,
  usePlanStore,
  useConfirmStore,
} from '@/stores';
import { ConfirmAction } from '@/types';
import { confirmPlan } from '@/api';
import { exportDecisionPdf, exportDecisionExcel } from '@/api/exports';

const { TextArea } = Input;

type PanelMode = 'view' | 'adjust' | 'confirmed';

export const ConfirmationPanel: React.FC = () => {
  const incidentContextId = useWorkbenchStore((s) => s.incidentContextId);
  const planSelectionOutput = usePlanStore((s) => s.planSelectionOutput);
  const selectedPlanId = usePlanStore((s) => s.selectedPlanId);
  const overrideReason = useConfirmStore((s) => s.overrideReason);
  const setOverrideReason = useConfirmStore((s) => s.setOverrideReason);

  const [mode, setMode] = useState<PanelMode>('view');
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [writebackProgress, setWritebackProgress] = useState<number | null>(null);

  // Adjustment draft state
  const [adjustments, setAdjustments] = useState<Record<string, unknown>[]>([]);
  const [exportLoading, setExportLoading] = useState<string | null>(null);
  const [decisionRecordId, setDecisionRecordId] = useState<string | null>(null);

  if (!incidentContextId) {
    return (
      <Card title="推荐与确认" size="small">
        <Alert message="请先选择异常事件" type="info" showIcon />
      </Card>
    );
  }

  const pso = planSelectionOutput;
  const activePlanId = selectedPlanId ?? pso?.recommended_plan_id;

  const handleConfirm = async (action: ConfirmAction) => {
    if (!incidentContextId || !activePlanId) return;

    if (action === ConfirmAction.REJECT_AND_RESELECT && !overrideReason.trim()) {
      setRejectModalOpen(true);
      return;
    }

    setConfirming(true);
    try {
      await confirmPlan({
        incident_id: incidentContextId,
        action,
        selected_plan_id: activePlanId,
        adjustments: action === ConfirmAction.ACCEPT_WITH_ADJUSTMENT ? adjustments : undefined,
        override_reason: action === ConfirmAction.REJECT_AND_RESELECT ? overrideReason : undefined,
        confirmed_by: 'current_planner', // TODO: from auth context
      }).then((res) => {
        setDecisionRecordId(res.decision_record_id);
      });
      setMode('confirmed');
      setWritebackProgress(30);
      message.success('方案已确认');
      // Simulate writeback progress
      setTimeout(() => setWritebackProgress(70), 2000);
      setTimeout(() => setWritebackProgress(100), 4000);
    } catch {
      message.error('确认失败，请重试');
    } finally {
      setConfirming(false);
    }
  };

  const handleRejectConfirm = () => {
    setRejectModalOpen(false);
    handleConfirm(ConfirmAction.REJECT_AND_RESELECT);
  };

  // Confirmed state
  if (mode === 'confirmed') {
    const handleExport = async (format: 'pdf' | 'excel') => {
      if (!decisionRecordId) {
        message.warning('无决策记录 ID，无法导出');
        return;
      }
      setExportLoading(format);
      try {
        const fn = format === 'pdf' ? exportDecisionPdf : exportDecisionExcel;
        const result = await fn(decisionRecordId);
        message.success(`导出成功: ${result.filename}`);
      } catch {
        message.error('导出失败');
      } finally {
        setExportLoading(null);
      }
    };

    return (
      <Card title="推荐与确认" size="small">
        <Alert message="方案已确认" type="success" showIcon style={{ marginBottom: 12 }} />
        {writebackProgress !== null && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ marginBottom: 8, fontSize: 13 }}>回写进度</div>
            <Progress percent={writebackProgress} status={writebackProgress === 100 ? 'success' : 'active'} />
          </div>
        )}
        <Divider style={{ margin: '12px 0' }} />
        <Space>
          <Button
            icon={<FilePdfOutlined />}
            loading={exportLoading === 'pdf'}
            onClick={() => handleExport('pdf')}
          >
            导出 PDF
          </Button>
          <Button
            icon={<FileExcelOutlined />}
            loading={exportLoading === 'excel'}
            onClick={() => handleExport('excel')}
          >
            导出 Excel
          </Button>
        </Space>
      </Card>
    );
  }

  return (
    <Card title="推荐与确认" size="small">
      {pso ? (
        <>
          {/* Recommendation summary */}
          <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
            <Descriptions.Item label="推荐方案">
              <Tag color="blue">{pso.recommended_plan_id.slice(0, 8)}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="推荐置信度">
              <Tag color={pso.recommendation_confidence >= 0.7 ? 'green' : 'orange'}>
                {(pso.recommendation_confidence * 100).toFixed(0)}%
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="自动预选">
              {pso.auto_preselected ? (
                <Tag color="cyan">是</Tag>
              ) : (
                <Tag color="default">否</Tag>
              )}
            </Descriptions.Item>
          </Descriptions>

          {/* Core reasons */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontWeight: 500, marginBottom: 4, fontSize: 13 }}>核心推荐原因</div>
            {pso.reason_codes.map((r, i) => (
              <Tag key={i} style={{ marginBottom: 4 }}>{r}</Tag>
            ))}
            <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
              {pso.reason_summary}
            </div>
          </div>

          {/* Risk flags */}
          {pso.risk_flags.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontWeight: 500, marginBottom: 4, fontSize: 13 }}>风险提示</div>
              {pso.risk_flags.map((r, i) => (
                <Tag key={i} color="red" style={{ marginBottom: 4 }}>{r}</Tag>
              ))}
            </div>
          )}

          {/* Low confidence warning */}
          {pso.recommendation_confidence < 0.5 && (
            <Alert
              message="置信度较低，建议比较前两名方案后再确认"
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
            />
          )}

          <Divider style={{ margin: '12px 0' }} />

          {/* Adjust mode */}
          {mode === 'adjust' ? (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 500, marginBottom: 8, fontSize: 13 }}>微调操作</div>
              <Form size="small" layout="vertical">
                <Form.Item label="工序 ID">
                  <Input
                    placeholder="operation_id"
                    onChange={(e) =>
                      setAdjustments([{ operation_id: e.target.value }])
                    }
                  />
                </Form.Item>
                <Form.Item label="延迟调整(分钟)">
                  <InputNumber
                    placeholder="0"
                    onChange={(v) =>
                      setAdjustments((prev) => [
                        { ...prev[0], delay_adjustment_minutes: v },
                      ])
                    }
                  />
                </Form.Item>
              </Form>
              <Space>
                <Button
                  type="primary"
                  size="small"
                  loading={confirming}
                  onClick={() => handleConfirm(ConfirmAction.ACCEPT_WITH_ADJUSTMENT)}
                >
                  确认微调
                </Button>
                <Button size="small" onClick={() => setMode('view')}>
                  取消
                </Button>
              </Space>
            </div>
          ) : (
            /* Action buttons */
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button
                type="primary"
                icon={<CheckOutlined />}
                block
                loading={confirming}
                disabled={!activePlanId}
                onClick={() => handleConfirm(ConfirmAction.ACCEPT)}
              >
                确认采纳
              </Button>
              <Button
                icon={<EditOutlined />}
                block
                disabled={!activePlanId}
                onClick={() => setMode('adjust')}
              >
                微调后采纳
              </Button>
              <Button
                danger
                icon={<RollbackOutlined />}
                block
                disabled={!activePlanId}
                onClick={() => setRejectModalOpen(true)}
              >
                否决并重选
              </Button>
            </Space>
          )}
        </>
      ) : (
        <Spin tip="等待推荐结果...">
          <div style={{ height: 100 }} />
        </Spin>
      )}

      {/* Reject reason modal */}
      <Modal
        title="否决原因（必填）"
        open={rejectModalOpen}
        onOk={handleRejectConfirm}
        onCancel={() => setRejectModalOpen(false)}
        okButtonProps={{ disabled: !overrideReason.trim() }}
        okText="确认否决"
        cancelText="取消"
      >
        <TextArea
          rows={4}
          placeholder="请输入否决原因..."
          value={overrideReason}
          onChange={(e) => setOverrideReason(e.target.value)}
        />
      </Modal>
    </Card>
  );
};
