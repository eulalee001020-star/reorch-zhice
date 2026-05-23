/**
 * Core TypeScript interfaces — aligned to backend Pydantic models.
 */

import type {
  ConfirmAction,
  DeliveryRiskLevel,
  IncidentSeverity,
  IncidentStatus,
  IncidentType,
  NeighborhoodType,
  RepairMode,
  ReportSource,
  RuleApplicableStage,
  RuleCategory,
  StrategyType,
  WritebackStatus,
} from './enums';

export interface CurrentUser {
  user_id: string;
  role: string;
  username: string;
  display_name: string;
}

export interface LoginResponse {
  api_key: string;
  user: CurrentUser;
}

// ---------------------------------------------------------------------------
// Incident & Schedule
// ---------------------------------------------------------------------------

export interface IncidentCreateRequest {
  incident_type: IncidentType;
  external_event_id?: string | null;
  occurred_at: string; // ISO-8601
  workshop_id?: string | null;
  resource_id: string;
  report_source: ReportSource;
  source_system?: string | null;
  description?: string | null;
  idempotency_key?: string | null;
  raw_payload?: Record<string, unknown> | null;
}

export interface Incident {
  incident_id: string; // UUID
  incident_type: IncidentType;
  occurred_at: string;
  resource_id: string;
  report_source: ReportSource;
  severity: IncidentSeverity;
  status: IncidentStatus;
  description?: string | null;
  deduplicated_from: string[];
  created_at: string;
  raw_payload?: Record<string, unknown> | null;
}

export interface Resource {
  resource_id: string;
  name: string;
  capabilities: string[];
  is_bottleneck: boolean;
  has_redundancy: boolean;
  criticality: string;
}

export interface Operation {
  operation_id: string;
  work_order_id: string;
  resource_id: string;
  required_capabilities: string[];
  start_time: string;
  end_time: string;
  predecessor_ids: string[];
  successor_ids: string[];
  is_affected: boolean;
  is_adjusted: boolean;
}

export interface WorkOrder {
  work_order_id: string;
  product_name: string;
  due_date: string;
  operations: Operation[];
  priority: number;
}

export interface ScheduleDetail {
  work_orders: WorkOrder[];
  resources: Resource[];
}

export interface ScheduleSnapshot {
  snapshot_id: string;
  captured_at: string;
  workshop_id: string;
  work_orders: WorkOrder[];
  raw_data?: Record<string, unknown> | null;
}

export interface GanttDiffPayload {
  baseline_snapshot_id: string;
  candidate_plan_id: string;
  adjusted_operations: Record<string, unknown>[];
  time_shifts: Record<string, unknown>[];
  resource_switches: Record<string, unknown>[];
  critical_path_changes: Record<string, unknown>[];
}

// ---------------------------------------------------------------------------
// Impact & Strategy
// ---------------------------------------------------------------------------

export interface AffectedOperation {
  operation_id: string;
  work_order_id: string;
  resource_id: string;
  is_direct: boolean;
  estimated_delay_minutes: number;
}

export interface AffectedWorkOrder {
  work_order_id: string;
  product_name: string;
  due_date: string;
  delivery_risk_level: DeliveryRiskLevel;
  remaining_buffer_minutes: number;
  affected_operations: AffectedOperation[];
}

export interface ImpactReport {
  incident_id: string;
  schedule_snapshot_id: string;
  analysis_reference_time: string;
  affected_work_orders: AffectedWorkOrder[];
  affected_operations: AffectedOperation[];
  affected_resource_ids: string[];
  delivery_risk_distribution: Record<string, number>;
  estimated_total_delay_minutes: number;
  is_degraded_mode: boolean;
  degraded_reason?: string | null;
  severity_upgraded: boolean;
  upgraded_severity?: IncidentSeverity | null;
}

export interface StrategyRecommendation {
  strategy_type: StrategyType;
  confidence: number;
  key_factors: string[];
  historical_case_ids: string[];
  alternative_strategy?: StrategyType | null;
  reasoning: string;
}

export interface RuleSelectionResult {
  rule_name: string;
  rule_category: RuleCategory;
  applicable_stage: RuleApplicableStage;
  confidence: number;
  reasoning: string;
  alternative_rule?: string | null;
}

export interface NeighborhoodConfig {
  neighborhood_type: NeighborhoodType;
  target_operation_ids: string[];
  intensity: number;
  estimated_impact_scope: number;
  reasoning: string;
}

export interface RepairPolicyConfig {
  repair_mode: RepairMode;
  frozen_operation_ids: string[];
  allowed_perturbation_scope: string[];
  search_time_budget_seconds: number;
  candidate_count_target: number;
  fallback_condition: string;
  fallback_mode: string;
}

export interface SolverChainConfig {
  primary_solver: string;
  fallback_solver: string;
  fallback_rule: string;
  degradation_trigger: string;
  max_timeout_seconds: number;
}

// ---------------------------------------------------------------------------
// Solver & Evaluation
// ---------------------------------------------------------------------------

export interface SolverChain {
  strategy_type: string;
  rule_selection: string;
  neighborhood_selection: string;
  repair_policy: string;
  solver_name: string;
  key_parameters: Record<string, unknown>;
  search_budget_seconds: number;
  constraint_validation_result: string;
  stages: string[];
}

export interface SolverMetadata {
  solve_time_seconds: number;
  iteration_count: number;
  objective_trajectory: number[];
  degradation_occurred: boolean;
  degradation_reason?: string | null;
}

export interface ConstraintViolation {
  constraint_type: string;
  operation_id: string;
  resource_id?: string | null;
  detail: string;
}

export interface ConstraintValidationReport {
  is_feasible: boolean;
  violations: ConstraintViolation[];
  checked_constraints: string[];
}

export interface CandidatePlan {
  plan_id: string;
  strategy_type: string;
  schedule_detail: ScheduleDetail;
  gantt_version: string;
  solver_chain: SolverChain;
  feasibility_status: string;
  solver_metadata: SolverMetadata;
  constraint_report: ConstraintValidationReport;
  created_at: string;
}

export interface KPIVector {
  delayed_order_count: number;
  max_delay_minutes: number;
  spi: number;
  resource_utilization_delta: number;
  changeover_count_delta: number;
  critical_order_otd_impact: number;
  normalized_score: number;
}

export interface ComparisonMatrixRow {
  plan_id: string;
  kpi_vector: KPIVector;
  delta_vs_baseline: Record<string, number>;
  is_score_close: boolean;
}

export interface ComparisonMatrix {
  rows: ComparisonMatrixRow[];
  normalization_method: string;
  score_unit_descriptions: Record<string, string>;
  baseline_snapshot_id: string;
}

// ---------------------------------------------------------------------------
// Recommendation & Explanation
// ---------------------------------------------------------------------------

export interface PlanSelectionInput {
  incident_id: string;
  incident_type: string;
  severity: string;
  schedule_snapshot_id: string;
  candidate_plans: CandidatePlan[];
  goal_mode: string;
  preference_profile: Record<string, unknown>;
  historical_case_matches: Record<string, unknown>[];
  manual_weights?: Record<string, number> | null;
  execution_constraints?: Record<string, unknown> | null;
}

export interface PlanSelectionOutput {
  recommended_plan_id: string;
  recommended_rank: number;
  top_scored_plan_id: string;
  recommendation_confidence: number;
  auto_preselected: boolean;
  ranked_plan_list: Record<string, unknown>[];
  reason_codes: string[];
  reason_summary: string;
  risk_flags: string[];
  comparison_matrix: ComparisonMatrix;
  gantt_diff_payload: GanttDiffPayload;
  goal_mode_used: string;
  weights_used: Record<string, number>;
  matched_case_ids: string[];
  alternative_plan_ids: string[];
  audit_metadata: Record<string, unknown>;
}

export interface RecommendationExplanation {
  core_reasons: string[];
  key_advantages: string[];
  main_risks: string[];
  comparison_with_alternatives: Record<string, unknown>[];
  summary: string;
  referenced_case_ids: string[];
}

export interface SolverChainExplanation {
  algorithm_category: string;
  applicable_scenario: string;
  chain_reason: string;
  optimization_objectives: string[];
  computation_time_seconds: number;
  stages: string[];
  frozen_constraints?: string[] | null;
}

// ---------------------------------------------------------------------------
// Controlled Agents
// ---------------------------------------------------------------------------

export interface AgentTraceStep {
  agent_name: string;
  input_summary: string;
  output_summary: string;
  freedom_level: string;
  llm_allowed: boolean;
  deterministic_tools: string[];
  guardrail: string;
}

export interface IncidentUnderstandingRequest {
  text: string;
  occurred_at?: string | null;
  workshop_id?: string | null;
  report_source?: string;
  source_system?: string | null;
}

export interface IncidentUnderstandingOutput {
  incident_type: string;
  resource_id?: string | null;
  estimated_duration_minutes?: number | null;
  risk_hint?: string | null;
  confidence: number;
  requires_human_confirmation: boolean;
  supported_by_solver: boolean;
  unsupported_reason?: string | null;
  normalized_fields: Record<string, unknown>;
  incident_create_request?: IncidentCreateRequest | null;
  trace: AgentTraceStep[];
}

export interface AgentDecisionFlowRequest {
  incident_id: string;
  estimated_repair_time_minutes?: number;
  goal_mode?: string;
  manual_weights?: Record<string, number> | null;
  auto_solve?: boolean;
  auto_recommend?: boolean;
  planner_id?: string;
}

export interface AgentDecisionFlowResponse {
  incident: Incident;
  impact_report: ImpactReport;
  strategy: StrategyRecommendation;
  candidate_plans: CandidatePlan[];
  quality_gates: PlanQualityGateReport[];
  comparison_matrix?: ComparisonMatrix | null;
  recommendation?: PlanSelectionOutput | null;
  recommendation_explanation?: RecommendationExplanation | null;
  solver_chain_explanation?: SolverChainExplanation | null;
  requires_human_confirmation: boolean;
  trace: AgentTraceStep[];
}

export interface FeedbackStructuringRequest {
  override_text: string;
  decision_record_id?: string | null;
  incident_id?: string | null;
  planner_id?: string | null;
}

export interface FeedbackStructuringOutput {
  override_reason: string;
  reason_detail: string;
  future_rule_candidate?: string | null;
  confidence: number;
  requires_human_review: boolean;
  decision_record_id?: string | null;
  incident_id?: string | null;
  trace: AgentTraceStep[];
}

// ---------------------------------------------------------------------------
// Decision & Confirmation
// ---------------------------------------------------------------------------

export interface ConfirmRequest {
  incident_id: string;
  action: ConfirmAction;
  selected_plan_id: string;
  adjustments?: Record<string, unknown>[] | null;
  override_reason?: string | null;
  confirmed_by?: string | null;
}

export interface ConfirmResponse {
  confirmed_plan_id: string;
  derived_from_plan_id: string;
  is_manual_adjusted: boolean;
  constraint_validation: ConstraintValidationReport;
  decision_record_id: string;
}

export interface DecisionRecord {
  decision_record_id: string;
  incident_id: string;
  impact_report_summary: string;
  strategy_type: string;
  all_candidate_plan_ids: string[];
  recommended_plan_id: string;
  confirmed_plan_id: string;
  derived_from_plan_id: string;
  is_override: boolean;
  is_manual_adjusted: boolean;
  override_reason?: string | null;
  confirmed_by: string;
  confirmed_at: string;
  plan_selection_input_version: string;
  plan_selection_output_version: string;
  solver_chain: SolverChain;
  rule_selector_version: string;
  neighborhood_selector_version: string;
  repair_policy_advisor_version: string;
}

// ---------------------------------------------------------------------------
// Case Library
// ---------------------------------------------------------------------------

export interface ExecutionResult {
  incident_id: string;
  decision_record_id: string;
  actual_completion_times: Record<string, string>;
  planned_completion_times: Record<string, string>;
  actual_otd: number;
  actual_resource_utilization: number;
  deviation_percentage: number;
}

export interface WritebackStatusResponse {
  incident_id: string;
  status: WritebackStatus;
  total_instructions: number;
  success_count: number;
  failed_count: number;
  failed_instructions: Record<string, unknown>[];
  timestamp: string;
}

export interface CaseRecord {
  case_id: string;
  incident_features: Record<string, unknown>;
  impact_scope: Record<string, unknown>;
  strategy_type: string;
  confirmed_plan_summary: string;
  execution_result?: ExecutionResult | null;
  is_override: boolean;
  override_reason?: string | null;
  rule_selection: string;
  neighborhood_selection: string;
  repair_policy: string;
  solver_chain: SolverChain;
  created_at: string;
  embedding_vector?: number[] | null;
}

export interface CaseTemplate {
  template_id: string;
  template_name: string;
  applicable_incident_types: string[];
  recommended_strategy: string;
  key_parameter_thresholds: Record<string, unknown>;
  status: string;
  reference_count: number;
  adoption_rate: number;
  created_by: string;
  created_at: string;
}

export interface PreferenceProfile {
  planner_id: string;
  strategy_preferences: Record<string, number>;
  adjustment_patterns: Record<string, unknown>[];
  override_history: Record<string, unknown>[];
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Planning, Readiness & PoC Value
// ---------------------------------------------------------------------------

export interface ReadinessIssue {
  severity: 'blocker' | 'warning' | 'info' | string;
  code: string;
  message: string;
  entity_type?: string | null;
  entity_id?: string | null;
}

export interface DataReadinessReport {
  is_ready: boolean;
  readiness_score: number;
  blockers: ReadinessIssue[];
  warnings: ReadinessIssue[];
  infos: ReadinessIssue[];
  required_inputs: string[];
  recommendations: string[];
}

export interface PlanningResourceInput {
  resource_id: string;
  name?: string | null;
  capabilities: string[];
  is_bottleneck: boolean;
  has_redundancy: boolean;
  criticality: string;
  cost_per_minute: number;
}

export interface ResourceCalendarWindowInput {
  resource_id: string;
  window_start: string;
  window_end: string;
  availability_type: string;
  reason?: string | null;
}

export interface PlanningMaterialRequirementInput {
  material_id: string;
  required_quantity: number;
  available_at?: string | null;
  status: string;
}

export interface ChangeoverRuleInput {
  from_product_family: string;
  to_product_family: string;
  setup_minutes: number;
  cost: number;
  resource_id?: string | null;
}

export interface PlanningOperationInput {
  operation_id: string;
  work_order_id: string;
  duration_minutes: number;
  eligible_resource_ids: string[];
  required_capabilities: string[];
  predecessor_ids: string[];
  release_time?: string | null;
  product_family?: string | null;
  material_requirements: PlanningMaterialRequirementInput[];
}

export interface PlanningWorkOrderInput {
  work_order_id: string;
  product_name: string;
  due_date: string;
  priority: number;
  product_family?: string | null;
  operations: PlanningOperationInput[];
}

export interface InitialScheduleRequest {
  workshop_id: string;
  planning_start: string;
  resources: PlanningResourceInput[];
  resource_calendar: ResourceCalendarWindowInput[];
  changeover_rules: ChangeoverRuleInput[];
  work_orders: PlanningWorkOrderInput[];
  goal_modes: string[];
  max_solutions: number;
  time_budget_seconds: number;
}

export interface InitialScheduleOption {
  goal_mode: string;
  label: string;
  strengths: string[];
  tradeoffs: string[];
  candidate_plan: CandidatePlan;
  kpis: Record<string, number | string>;
}

export interface InitialScheduleResponse {
  workshop_id: string;
  generated_at: string;
  readiness_report: DataReadinessReport;
  options: InitialScheduleOption[];
}

export interface EnterpriseFieldMapping {
  work_orders_path: string;
  resources_path: string;
  work_order_id: string;
  product_name: string;
  product_family: string;
  due_date: string;
  priority: string;
  operations: string;
  operation_id: string;
  duration_minutes: string;
  resource_id: string;
  eligible_resource_ids: string;
  required_capabilities: string;
  predecessor_ids: string;
  resource_capabilities: string;
}

export interface EnterpriseImportRequest {
  source_system: string;
  workshop_id: string;
  planning_start: string;
  raw_payload: Record<string, unknown>;
  mapping: EnterpriseFieldMapping;
}

export interface EnterpriseImportResponse {
  source_system: string;
  readiness_report: DataReadinessReport;
  initial_schedule_request: InitialScheduleRequest;
}

export interface PlanQualityGateReport {
  plan_id: string;
  pass_gate: boolean;
  confidence_level: string;
  hard_blockers: ConstraintViolation[];
  warnings: string[];
  recommendation_policy: string;
}

export interface PlanQualityGateResponse {
  reports: PlanQualityGateReport[];
}

export interface ValueTrackingInput {
  incident_count: number;
  baseline_decision_minutes: number;
  actual_decision_minutes: number;
  baseline_tardiness_minutes: number;
  actual_tardiness_minutes: number;
  baseline_changeovers: number;
  actual_changeovers: number;
  baseline_overtime_hours: number;
  actual_overtime_hours: number;
  planner_hourly_cost: number;
  tardiness_cost_per_minute: number;
  changeover_cost: number;
  overtime_hourly_cost: number;
}

export interface ValueTrackingReport {
  saved_decision_minutes: number;
  reduced_tardiness_minutes: number;
  reduced_changeovers: number;
  reduced_overtime_hours: number;
  estimated_savings: number;
  savings_breakdown: Record<string, number>;
  payback_commentary: string;
}

export interface WritebackPreviewResponse {
  target_format: string;
  instruction_count: number;
  instructions: Record<string, unknown>[];
}

export interface DigitalTwinRunResponse {
  scenario_id: string;
  initial_schedule: InitialScheduleResponse;
  selected_initial_option?: InitialScheduleOption | null;
  baseline_snapshot?: ScheduleSnapshot | null;
  incident?: Record<string, unknown> | null;
  impact_report?: Record<string, unknown> | null;
  strategy?: Record<string, unknown> | null;
  reschedule_candidates: CandidatePlan[];
  quality_gates: PlanQualityGateReport[];
  simulation_results: Record<string, unknown>[];
  writeback_preview?: WritebackPreviewResponse | null;
  value_report?: ValueTrackingReport | null;
  validation_evidence: Record<string, unknown>;
  runbook: string[];
}
