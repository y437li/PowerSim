// TypeScript types — generated from contracts/shared/telemetry_schema.md v1.0.0 (LOCKED, PR #6)
// DO NOT hand-drift. If the contract changes, these types change.

// ─── WebSocket status ────────────────────────────────────────────────────────
export type WsStatus = "connecting" | "connected" | "disconnected" | "stale";

// ─── Envelope ────────────────────────────────────────────────────────────────
export type TelemetryKind = "env_step" | "train_metrics" | "eval_compare";

export interface TelemetryEnvelope {
  schema_version: string;   // semver e.g. "1.0.0"
  kind: TelemetryKind;
  ts_utc: string;           // ISO-8601 UTC emit time (transport/logging only — use sim_time_utc for sim clock)
  run_id: string;
  seq: number;              // monotonic per (run_id, kind) across WHOLE run; gap-detectable
  payload: EnvStepPayload | TrainMetricsPayload | EvalComparePayload;
}

// ─── env_step payload ────────────────────────────────────────────────────────
export interface BatteryState {
  soc: number;                // fraction [0.2, 0.9] (D4) — display as soc*100 %
  p_charge_mw: number;        // MW ≥ 0
  p_discharge_mw: number;     // MW ≥ 0; charge XOR discharge
  p_max_charge_mw: number;    // §3.6 row 3 — carried for 3D wire scaling
  p_max_discharge_mw: number; // §3.6 row 3
  soc_violation_mwh: number;  // MWh ≥ 0
  capacity_mwh: number;       // MWh (294.5 Gansu)
}

export interface GenerationBlock {
  gross_solar_mw: number; // §3.1 P_pv before curtailment/dispatch
  gross_wind_mw: number;  // §3.1 P_wind before curtailment/dispatch
}

export interface PowerFlows {
  solar_to_load_mw: number;
  solar_to_bat_mw: number;
  solar_to_grid_mw: number;
  wind_to_load_mw: number;
  wind_to_bat_mw: number;
  wind_to_grid_mw: number;
  bat_to_load_mw: number;
  bat_to_grid_mw: number;
  grid_to_load_mw: number;
  grid_to_bat_mw: number;
  solar_curtailed_mw: number; // per-source (ren_curtailed_mw retired at LOCK)
  wind_curtailed_mw: number;
  bat_curtailed_mw: number;
  load_unserved_mw: number;
}

export interface PccState {
  export_mw: number;      // MW
  import_mw: number;      // MW
  max_export_mw: number;  // MW (D5: 945 Gansu physics limit)
  max_import_mw: number;  // MW (D12: 400 Gansu)
}

export type TariffTier = "critical_peak" | "peak" | "mid" | "valley";

export interface PerStepCosts {
  // Real-money summands: cost_total_real = c_energy+c_demand_charge+c_degradation+c_curtail+c_voll
  c_energy_yuan: number;              // = c_import − r_export (§3.4); can be negative
  c_import_yuan: number;              // decomposition of c_energy — display-only, NOT a summand
  r_export_yuan: number;              // decomposition of c_energy — display-only, NOT a summand
  c_demand_charge_yuan: number;       // REAL monthly charge; 0 except at month-boundary (D10)
  c_degradation_yuan: number;
  c_curtail_yuan: number;
  c_voll_yuan: number;
  // Reward-shaping terms (NOT real money)
  c_demand_shape_yuan: number;        // RAW C_DC_shape (§3.4); reward applies 2.0× weight
  penalty_yuan: number;               // SOC etc. (D4/§3.5); enters reward, NOT a cost summand
  // Rate on wire
  demand_rate_yuan_per_mw_month: number; // §3.7 = 32 000 ¥/MW·month
  // Two totals (D13)
  cost_total_real_yuan: number;           // real money: c_energy+c_demand_charge+c_degrad+c_curtail+c_voll
  cost_total_reward_basis_yuan: number;   // reward basis: c_energy+2.0·c_demand_shape+c_degrad+c_curtail+c_voll
}

export interface CumulativeCosts {
  c_energy_yuan_cum: number;
  c_demand_charge_yuan_cum: number;
  c_demand_shape_yuan_cum: number;
  c_degradation_yuan_cum: number;
  c_curtail_yuan_cum: number;
  c_voll_yuan_cum: number;
  penalty_yuan_cum: number;
  cost_total_real_yuan_cum: number;
  cost_total_reward_basis_yuan_cum: number;
}

export interface GasAsset {
  id: string; p_mw: number; c_fuel_yuan: number; setpoint: number;
}
export interface ElectrolyzerAsset {
  id: string; p_mw: number; h2_kg: number;
  h2_level_kg: number; tank_kg: number; r_h2_yuan: number; setpoint: number;
}
export interface AssetsExt {
  gas?: GasAsset[];
  electrolyzer?: ElectrolyzerAsset[];
}

export interface EnvStepPayload {
  step: number;
  episode: number;
  dt_hours: number;               // 1.0 (D3)
  sim_time_utc: string;           // SIM clock — timelines key off this
  hour_of_day: number;            // 0–23
  minute_of_hour: number;         // 0–59
  wind_speed_mps: number;
  irradiance_wm2: number;
  temperature_c: number;
  load_mw: number;
  price_buy_yuan_per_mwh: number;
  price_sell_yuan_per_mwh: number;
  tariff_tier: TariffTier;        // per-step price label only; NOT band geometry
  battery: BatteryState;
  generation: GenerationBlock;
  flows: PowerFlows;
  pcc: PccState;
  costs: PerStepCosts;
  cost_cum: CumulativeCosts;
  month_peak_mw: number;
  reward: number;                 // = −(cost_total_reward_basis + penalty)×1e-5 (§3.5)
  assets_ext?: AssetsExt;         // absent for Gansu parity; feature-detect by key presence
}

// ─── train_metrics payload ───────────────────────────────────────────────────
export interface TrainMetricsPayload {
  global_step: number;
  wall_seconds: number;
  env_steps_per_sec: number;
  actor_loss: number;
  critic_loss: number;
  ent_coef: number;
  reward_scaled_mean: number;           // ×1e-5-scaled env reward (matches env_step.reward); unitless
  reward_norm_mean: number | null;      // VecNorm-normalized; null on eval checkpoints
  cost_total_real_mean_yuan: number;    // mean per-episode real ¥ (negative = net revenue)
  is_eval_checkpoint: boolean;
  checkpoint_id: string | null;
}

// ─── eval_compare payload ────────────────────────────────────────────────────
export interface PolicyMetrics {
  energy_cost_yuan: number;
  demand_charge_yuan: number;
  degradation_yuan: number;
  curtailment_yuan: number;
  voll_yuan: number;
  total_cost_yuan: number;          // = energy+demand_charge+degradation+curtailment+voll (real money)
  soc_violations_count: number;     // safety metric, NOT in total_cost_yuan
  soc_violation_mwh: number;        // safety metric, NOT in total_cost_yuan
  penalty_yuan: number;             // reward-basis safety penalty, NOT in total_cost_yuan
}

export interface EvalComparePayload {
  eval_horizon_steps: number;   // 8760 (D3)
  checkpoint_id: string;
  cost_basis: "real_money";     // explicit: all *_yuan fields are real money
  policies: {
    rl: PolicyMetrics;
    no_battery: PolicyMetrics;
    rule_based_tou: PolicyMetrics;
  };
}

// ─── Inference session server frames (inference_stream.md) ───────────────────

/** Server → client session status frame (no `payload` wrapper). */
export interface ServerStatusFrame {
  kind: "status";
  state: "ready" | "running" | "paused" | "stopped";
  session_id: string | null;
  step: number;
  episode: number;
  run_id: string | null;
  site_id: string | null;
  message?: string;
}

/** Server → client error frame (no `payload` wrapper). */
export interface ServerErrorFrame {
  kind: "error";
  code:
    | "run_not_found"
    | "site_not_found"
    | "policy_not_found"
    | "already_running"
    | "no_session"
    | "bad_state"
    | "bad_command"
    | "invalid_message"
    | "internal";
  message: string;
}

// ─── REST client types ───────────────────────────────────────────────────────
/** REST API schema for GET /runs and GET /runs/latest — contracts/serving/rest_api.md §GET-runs. */
export interface RunInfo {
  id: string;
  created_at?: string;         // ISO-8601 UTC; absent if not determinable
  episodes_trained: number;
  latest_eval_reward: number | null;
  has_policy: boolean;
}

export interface SiteConfig {
  site_id: string;
  wind_capacity_mw: number;
  solar_capacity_mw: number;
  battery_capacity_mwh: number;
  battery_max_charge_mw: number;
  battery_max_discharge_mw: number;
  pcc_max_export_mw: number;
  pcc_max_import_mw: number;
}
