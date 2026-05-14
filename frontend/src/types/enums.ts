/**
 * Shared enumerations — single source of truth, aligned to backend app/models/enums.py.
 */

export enum IncidentSeverity {
  P1_CRITICAL = 'P1-Critical',
  P2_HIGH = 'P2-High',
  P3_MEDIUM = 'P3-Medium',
  P4_LOW = 'P4-Low',
}

export enum IncidentType {
  EQUIPMENT_FAILURE = 'equipment_failure',
}

export enum IncidentStatus {
  PENDING_ANALYSIS = 'pending_analysis',
  ANALYZING = 'analyzing',
  PENDING_CONFIRMATION = 'pending_confirmation',
  CONFIRMED = 'confirmed',
  EXECUTING = 'executing',
  CLOSED = 'closed',
}

export enum DeliveryRiskLevel {
  SAFE = 'safe',
  WARNING = 'warning',
  BREACH = 'breach',
}

export enum StrategyType {
  WAIT_AND_REPAIR = 'wait_and_repair',
  LOCAL_REPAIR = 'local_repair',
  GLOBAL_RESCHEDULE = 'global_reschedule',
}

export enum RepairMode {
  CONSERVATIVE = 'conservative',
  BALANCED = 'balanced',
  AGGRESSIVE = 'aggressive',
}

export enum RuleCategory {
  DUE_DATE_PRIORITY = 'due_date_priority',
  SHORTEST_PROCESSING_TIME = 'shortest_processing_time',
  MINIMUM_SLACK_TIME = 'minimum_slack_time',
  BOTTLENECK_RESOURCE_PRIORITY = 'bottleneck_resource_priority',
  CRITICAL_ORDER_PRIORITY = 'critical_order_priority',
}

export enum NeighborhoodType {
  CRITICAL_PATH = 'critical_path',
  BOTTLENECK_DEVICE = 'bottleneck_device',
  DELAYED_ORDER = 'delayed_order',
  SAME_DEVICE_SWAP = 'same_device_swap',
  OPERATION_INSERT = 'operation_insert',
  DEVICE_REASSIGNMENT = 'device_reassignment',
}

export enum ConfirmAction {
  ACCEPT = 'accept',
  ACCEPT_WITH_ADJUSTMENT = 'accept_with_adjustment',
  REJECT_AND_RESELECT = 'reject_and_reselect',
}

export enum WritebackStatus {
  SUCCESS = 'success',
  PARTIAL_SUCCESS = 'partial_success',
  FAILED = 'failed',
}

export enum GoalMode {
  DELIVERY_PRIORITY = 'delivery_priority',
  STABILITY_PRIORITY = 'stability_priority',
  BOTTLENECK_PRIORITY = 'bottleneck_priority',
  COST_PRIORITY = 'cost_priority',
  BALANCED = 'balanced',
}

export enum RuleApplicableStage {
  INITIAL_SOLUTION = 'initial_solution',
  REPAIR = 'repair',
}

export enum ReportSource {
  MES = 'MES',
  IOT = 'IoT',
  MANUAL = 'manual',
}
