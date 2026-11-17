// Supply planning types. They mirror app/models/supply.py.

export interface RequirementCoverage {
  work_order_id: string;
  operation_id: string;
  item_id: string;
  required_quantity: number;
  covered_quantity: number;
  ready_at: string | null;
  sources: string[];
}

export interface OperationKit {
  work_order_id: string;
  operation_id: string;
  planned_start: string;
  is_complete: boolean;
  ready_at: string | null;
  wait_minutes: number;
  requirements: RequirementCoverage[];
}

export interface KitReport {
  supply_snapshot_id: string;
  reference_time: string;
  operations: OperationKit[];
  kit_rate: number;
  on_time_kit_rate: number;
  late_operation_ids: string[];
  unresolved_operation_ids: string[];
}

export interface ReadinessGap {
  gap_id: string;
  description: string;
  owner: string | null;
  due_at: string | null;
  closed_at: string | null;
}

export interface ReadinessLine {
  order_key: string;
  item_id: string;
  supplier_id: string | null;
  quantity: number;
  arrived: boolean;
  usable: boolean;
  arrived_at: string | null;
  usable_at: string | null;
  open_gaps: ReadinessGap[];
  overdue_gap_ids: string[];
}

export interface ReadinessReport {
  reference_time: string;
  lines: ReadinessLine[];
  arrived_count: number;
  usable_count: number;
  arrived_not_usable_count: number;
  open_gap_count: number;
  overdue_gap_count: number;
  unowned_gap_count: number;
}

export interface SupplierScore {
  supplier_id: string;
  name: string;
  deliveries: number;
  on_time_rate: number;
  average_late_hours: number;
  late_p80_minutes: number;
  reject_rate: number;
  average_response_hours: number | null;
  score: number;
  tier: 'A' | 'B' | 'C' | 'unrated';
  notes: string[];
}

export interface MrpBucket {
  bucket_start: string;
  gross_requirement: number;
  scheduled_receipt: number;
  projected_available: number;
  net_requirement: number;
  planned_order_receipt: number;
  planned_order_release: number;
}

export interface MrpRecord {
  item_id: string;
  low_level_code: number;
  opening_balance: number;
  safety_stock: number;
  lead_time_buckets: number;
  buckets: MrpBucket[];
  past_due_release: number;
}

export interface MrpResult {
  bucket_minutes: number;
  horizon_start: string;
  records: MrpRecord[];
}
