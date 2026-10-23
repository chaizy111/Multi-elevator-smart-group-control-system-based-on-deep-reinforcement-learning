export type Pattern = "normal" | "morning" | "evening" | "interfloor" | "burst";
export type ControllerName = "round_robin" | "eta" | "eta_zone" | "ppo";
export interface Config {
  schema_version: number;
  seed: number;
  building: {
    floor_count: number;
    elevator_count: number;
    capacity: number;
    lobby_floor: number;
    floor_height_m: number;
    initial_floors: number[] | null;
  };
  physics: Record<string, number>;
  simulation: {
    arrival_horizon_s: number;
    max_drain_s: number;
    snapshot_interval_s: number;
    max_passengers: number;
    start_time_of_day_s: number;
    max_events: number;
  };
  traffic: {
    pattern: Pattern;
    arrival_rate_per_min: number;
    segments: Record<string, unknown>[];
    bursts: Record<string, unknown>[];
  };
  controller: { name: ControllerName; model_id: string | null };
  reposition: { enabled: boolean; idle_review_s: number; cooldown_s: number };
  metrics: { long_wait_threshold_s: number };
  reward: Record<string, number>;
}
export interface Model {
  model_id: string;
  sha256: string;
  training_steps: number;
  seed: number;
  attention: boolean;
  training_config: { stage: string; domain_randomization: boolean };
  support: { max_floors: number; max_elevators: number };
  validation: { cost?: number; complete?: boolean };
}
export interface Trace {
  trace_id: string;
  hash: string;
  count: number;
  seed: number;
  config: Config;
}
export interface Segment {
  from_floor: number;
  to_floor: number;
  start_us: number;
  end_us: number;
  purpose: string;
}
export interface Elevator {
  id: string;
  position_floor: number;
  direction: string;
  load: number;
  capacity: number;
  target_floor: number | null;
  phase: string;
  purpose: string | null;
  segment: Segment | null;
  distance_floors: number;
}
export interface Floor {
  floor: number;
  up_count: number;
  down_count: number;
  max_wait_s: number;
}
export type MetricValues = Record<
  string,
  number | boolean | null | Record<string, unknown>
>;
export interface Snapshot {
  run_id: string;
  sequence: number;
  type: string;
  status: string;
  sim_time_s: number;
  speed_multiplier: number;
  elevators: Elevator[];
  floor_queues: Floor[];
  metrics: MetricValues;
  recent_decisions?: Record<string, unknown>[];
  decision?: Record<string, unknown> | null;
  final_metrics?: { final: MetricValues };
}
export interface Job {
  id: string;
  kind: string;
  status: string;
  config: { config: Config; trace_id: string; speed_multiplier: number };
  snapshot: Snapshot | null;
  error: { message: string } | null;
  progress?: { completed: number; total: number; failed: unknown[] };
}
export interface Passenger {
  passenger_id: string;
  origin_floor: number;
  destination_floor: number;
  status: string;
  assigned_elevator: string | null;
  waiting_time: number | null;
  censored_wait_age: number | null;
}
export interface Artifact {
  id: string;
  name: string;
  url: string;
  size: number;
}
export type Row = Record<string, string | number | boolean | null>;
