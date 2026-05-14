/**
 * Unified status → text / color / icon mapping for frontend rendering.
 * Uses Ant Design 5 token colors and @ant-design/icons names.
 *
 * Requirements: 10.3, 13.9, 17.1
 */

import {
  ConfirmAction,
  GoalMode,
  IncidentStatus,
  WritebackStatus,
} from '@/types';

export interface StatusMeta {
  text: string;
  color: string;
  icon: string;
}

// ---------------------------------------------------------------------------
// IncidentStatus
// ---------------------------------------------------------------------------

export const incidentStatusMap: Record<IncidentStatus, StatusMeta> = {
  [IncidentStatus.PENDING_ANALYSIS]: {
    text: '待分析',
    color: '#faad14', // gold
    icon: 'ClockCircleOutlined',
  },
  [IncidentStatus.ANALYZING]: {
    text: '分析中',
    color: '#1677ff', // blue
    icon: 'SyncOutlined',
  },
  [IncidentStatus.PENDING_CONFIRMATION]: {
    text: '待确认',
    color: '#fa8c16', // orange
    icon: 'ExclamationCircleOutlined',
  },
  [IncidentStatus.CONFIRMED]: {
    text: '已确认',
    color: '#52c41a', // green
    icon: 'CheckCircleOutlined',
  },
  [IncidentStatus.EXECUTING]: {
    text: '执行中',
    color: '#1677ff',
    icon: 'LoadingOutlined',
  },
  [IncidentStatus.CLOSED]: {
    text: '已关闭',
    color: '#8c8c8c', // grey
    icon: 'MinusCircleOutlined',
  },
};

// ---------------------------------------------------------------------------
// WritebackStatus
// ---------------------------------------------------------------------------

export const writebackStatusMap: Record<WritebackStatus, StatusMeta> = {
  [WritebackStatus.SUCCESS]: {
    text: '回写成功',
    color: '#52c41a',
    icon: 'CheckCircleOutlined',
  },
  [WritebackStatus.PARTIAL_SUCCESS]: {
    text: '部分成功',
    color: '#faad14',
    icon: 'WarningOutlined',
  },
  [WritebackStatus.FAILED]: {
    text: '回写失败',
    color: '#ff4d4f', // red
    icon: 'CloseCircleOutlined',
  },
};

// ---------------------------------------------------------------------------
// ConfirmAction
// ---------------------------------------------------------------------------

export const confirmActionMap: Record<ConfirmAction, StatusMeta> = {
  [ConfirmAction.ACCEPT]: {
    text: '确认采纳',
    color: '#52c41a',
    icon: 'CheckOutlined',
  },
  [ConfirmAction.ACCEPT_WITH_ADJUSTMENT]: {
    text: '微调后采纳',
    color: '#1677ff',
    icon: 'EditOutlined',
  },
  [ConfirmAction.REJECT_AND_RESELECT]: {
    text: '否决并重选',
    color: '#ff4d4f',
    icon: 'RollbackOutlined',
  },
};

// ---------------------------------------------------------------------------
// GoalMode
// ---------------------------------------------------------------------------

export const goalModeMap: Record<GoalMode, StatusMeta> = {
  [GoalMode.DELIVERY_PRIORITY]: {
    text: '交付优先',
    color: '#f5222d',
    icon: 'RocketOutlined',
  },
  [GoalMode.STABILITY_PRIORITY]: {
    text: '稳定优先',
    color: '#1677ff',
    icon: 'SafetyOutlined',
  },
  [GoalMode.BOTTLENECK_PRIORITY]: {
    text: '瓶颈优先',
    color: '#fa8c16',
    icon: 'ThunderboltOutlined',
  },
  [GoalMode.COST_PRIORITY]: {
    text: '成本优先',
    color: '#722ed1',
    icon: 'DollarOutlined',
  },
  [GoalMode.BALANCED]: {
    text: '平衡优先',
    color: '#52c41a',
    icon: 'DashboardOutlined',
  },
};
