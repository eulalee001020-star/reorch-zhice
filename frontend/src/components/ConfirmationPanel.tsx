/**
 * 推荐与确认区 — 展示推荐理由 + 三种确认操作。
 *
 * - Show recommendation: plan ID, confidence, auto-preselect, core reasons, risks
 * - "Why not another plan" comparison summary
 * - Low confidence → no auto-select, prompt compare top-2
 * - 3 buttons: Accept, Adjust, Reject
 * - Adjust mode: simple form for operation adjustments
 * - Reject: override reason modal (required)
 * - After confirm: keep MES untouched and offer an explicit sandbox dry-run
 *
 * Requirements: 13.1-13.12, 31.4, 31.7
 */

import React, { useState } from 'react';
import {
  App as AntdApp,
  Card,
  Button,
  Tag,
  Descriptions,
  Alert,
  Modal,
  Input,
  Space,
  Spin,
  Divider,
  Form,
  InputNumber,
} from 'antd';
import {
  CheckOutlined,
  EditOutlined,
  RollbackOutlined,
  FilePdfOutlined,
  FileExcelOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import {
  useWorkbenchStore,
  usePlanStore,
  useConfirmStore,
  useAuthStore,
} from '@/stores';
import { ConfirmAction, type SandboxWritebackResponse } from '@/types';
import { confirmPlan, runSandboxWriteback } from '@/api';
import { exportDecisionPdf, exportDecisionExcel } from '@/api/exports';

const { TextArea } = Input;

type PanelMode = 'view' | 'adjust' | 'confirmed';

export const ConfirmationPanel: React.FC = () => {
  const { message } = AntdApp.useApp();
  const incidentContextId = useWorkbenchStore((s) => s.incidentContextId);
  const planSelectionOutput = usePlanStore((s) => s.planSelectionOutput);
  const selectedPlanId = usePlanStore((s) => s.selectedPlanId);
  const overrideReason = useConfirmStore((s) => s.overrideReason);
  const setOverrideReason = useConfirmStore((s) => s.setOverrideReason);
  const currentUser = useAuthStore((s) => s.user);

  const [mode, setMode] = useState<PanelMode>('view');
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmedAction, setConfirmedAction] = useState<ConfirmAction | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [writebackPreview, setWritebackPreview] = useState<SandboxWritebackResponse | null>(null);

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
  const canConfirm = currentUser
    ? ['Planner', 'IT_Admin', 'Management'].includes(currentUser.role)
    : false;

  const handleConfirm = async (action: ConfirmAction) => {
    if (!incidentContextId || !activePlanId) return;

    if (action === ConfirmAction.REJECT_AND_RESELECT && !overrideReason.trim()) {
      setRejectModalOpen(true);
      return;
    }

    setConfirming(true);
    try {
      const confirmResponse = await confirmPlan({
        incident_id: incidentContextId,
        action,
        selected_plan_id: activePlanId,
        adjustments: action === ConfirmAction.ACCEPT_WITH_ADJUSTMENT ? adjustments : undefined,
        override_reason: action === ConfirmAction.REJECT_AND_RESELECT ? overrideReason : undefined,
        confirmed_by: currentUser?.user_id,
      });
      setDecisionRecordId(confirmResponse.decision_record_id);
      setConfirmedAction(action);
      setMode('confirmed');
      message.success(
        action === ConfirmAction.REJECT_AND_RESELECT
          ? '否决决定已记录'
          : '方案已确认，尚未回写',
      );
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

  const handleWritebackPreview = async () => {
    if (!incidentContextId || !decisionRecordId) return;
    setPreviewLoading(true);
    try {
      const preview = await runSandboxWriteback(incidentContextId, {
        decision_record_id: decisionRecordId,
        target_environment: 'sandbox',
        dry_run: true,
      });
      setWritebackPreview(preview);
      message.success('Sandbox 指令预览已生成，未修改外部系统');
    } catch {
      message.error('指令预览生成失败');
    } finally {
      setPreviewLoading(false);
    }
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
        <Alert
          message={
            confirmedAction === ConfirmAction.REJECT_AND_RESELECT
              ? '否决决定已记录，不会生成回写指令'
              : '方案已确认，尚未回写 MES'
          }
          description={
            confirmedAction === ConfirmAction.REJECT_AND_RESELECT
              ? '请返回方案比较区重新选择。'
              : '下一步可生成 Sandbox 指令预览；预览不会修改任何外部系统。'
          }
          type={confirmedAction === ConfirmAction.REJECT_AND_RESELECT ? 'warning' : 'success'}
          showIcon
          style={{ marginBottom: 12 }}
        />
        {confirmedAction !== ConfirmAction.REJECT_AND_RESELECT && (
          <div style={{ marginBottom: 12 }}>
            <Button
              icon={<SafetyCertificateOutlined />}
              loading={previewLoading}
              onClick={handleWritebackPreview}
            >
              生成 Sandbox 指令预览
            </Button>
            {writebackPreview && (
              <Descriptions size="small" column={1} bordered style={{ marginTop: 12 }}>
                <Descriptions.Item label="环境">
                  <Tag color="blue">Sandbox dry-run</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="指令数">
                  {writebackPreview.instruction_count}
                </Descriptions.Item>
                <Descriptions.Item label="系统影响">
                  未修改外部系统
                </Descriptions.Item>
              </Descriptions>
            )}
          </div>
        )}
        <Divider style={{ margin: '12px 0' }} />
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 8, fontSize: 13 }}>学习闭环证据</div>
          <Alert
            message="等待执行结果后再启动学习闭环"
            description="确认本身不构成效果证据；采集 ExecutionResult 后再运行 RuleCandidate → CaseMemory → PreferenceLearning。"
            type="info"
            showIcon
          />
        </div>
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
    <Card title="计划员确认" size="small">
      {pso ? (
        <>
          {/* Recommendation summary */}
          <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
            <Descriptions.Item label="系统建议方案">
              <Tag color="blue">{pso.recommended_plan_id.slice(0, 8)}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="建议置信度">
              <Tag color={pso.recommendation_confidence >= 0.7 ? 'green' : 'orange'}>
                {(pso.recommendation_confidence * 100).toFixed(0)}%
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="默认待确认">
              {pso.auto_preselected ? (
                <Tag color="cyan">已置顶</Tag>
              ) : (
                <Tag color="default">无</Tag>
              )}
            </Descriptions.Item>
          </Descriptions>
          <Alert
            message="系统只给出待确认建议；生产执行和回写必须经过计划员或主管授权。"
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
          />

          {/* Core reasons */}
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontWeight: 500, marginBottom: 4, fontSize: 13 }}>建议依据</div>
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
          {!canConfirm && (
            <Alert
              message="当前角色仅可查看，不能确认或回写方案"
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
            />
          )}

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
                  disabled={!canConfirm}
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
                disabled={!activePlanId || !canConfirm}
                onClick={() => handleConfirm(ConfirmAction.ACCEPT)}
              >
                确认采纳
              </Button>
              <Button
                icon={<EditOutlined />}
                block
                disabled={!activePlanId || !canConfirm}
                onClick={() => setMode('adjust')}
              >
                微调后采纳
              </Button>
              <Button
                danger
                icon={<RollbackOutlined />}
                block
                disabled={!activePlanId || !canConfirm}
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
