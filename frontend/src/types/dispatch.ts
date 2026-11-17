// Dispatch types. They mirror app/models/dispatch.py.

export interface RouteStop {
  shipment_id: string;
  customer: string;
  arrival: string;
  service_start: string;
  departure: string;
  wait_minutes: number;
  late_minutes: number;
}

export interface VehicleRoute {
  vehicle_id: string;
  depart_at: string;
  return_at: string;
  distance_km: number;
  load: number;
  overtime_minutes: number;
  stops: RouteStop[];
}

export interface DispatchPlan {
  label: string;
  source_plan_id: string | null;
  is_recommended: boolean;
  routes: VehicleRoute[];
  unserved_shipment_ids: string[];
  vehicles_used: number;
  total_distance_km: number;
  late_stop_count: number;
  total_late_minutes: number;
  overtime_minutes: number;
  on_time_rate: number;
  cost: number;
}

export interface DispatchImpact {
  incident_id: string;
  dispatch_snapshot_id: string;
  plans: DispatchPlan[];
}
