/**
 * Telemetry type definitions — LOCKED v1.0.0 (PR #6, commit 98beee0)
 * Source: contracts/shared/telemetry_schema.md
 * DO NOT deviate from these field names; a change requires a new rl-architect DECISION.
 */

export type TelemetryKind = "env_step" | "train_metrics" | "eval_compare";

export type TariffTier = "peak" | "shoulder" | "off_peak";

export type WsStatus = "connecting" | "connected" | "disconnected" | "stale";

/** Envelope that wraps every telemetry message on the wire. */
export interface TelemetryEnvelope {
  schema_version: string;       // semver e.g. "1.0.0"
  kind: TelemetryKind;
  ts_utc: string;               // ISO-8601 UTC — emit clock only (NOT sim clock)
  run_id: string;
  seq: number;                  // monotonic per (run_id, kind)
  payload: EnvStepPayload | TrainMetricsPayload | EvalComparePayload;
}

// ─── env_step ────────────────────────────────────────────────────────────────

/** Power-flow block (all values MW, non-negative). */
export interface FlowsBlock {
  /** Net solar dispatch to each sink (post-curtailment). */
  solar_to_load_mw: number;
  solar_to_bat_mw: number;
  solar_to_grid_mw: number;
  /** Net wind dispatch to each sink (post-curtailment). */
  wind_to_load_mw: number;
  wind_to_bat_mw: number;
  wind_to_grid_mw: number;
  /** Battery to load / grid (discharge side). */
  bat_to_load_mw: number;
  bat_to_grid_mw: number;
  /** Grid import to load / battery. */
  grid_to_load_mw: number;
  grid_to_bat_mw: number;
  /** Curtailment — split by source (LOCKED v1.0.0: replaces ren_curtailed_mw). */
  solar_curtailed_mw: number;
  wind_curtailed_mw: number;
  /** Battery excess curtailment when both SOC ceiling and export limit hit. */
  bat_curtailed_mw: number;
  /** Unserved load — value of lost load (VOLL) event indicator. */
  load_unserved_mw: number;
}

/** Gross generation before dispatch/curtailment (LOCKED v1.0.0 addition). */
export interface GenerationBlock {
  gross_solar_mw: number;   // §3.1 P_pv before dispatch
  gross_wind_mw: number;    // §3.1 P_wind before dispatch
}

/** Battery state including power-max fields (LOCKED v1.0.0 addition). */
export interface BatteryBlock {
  soc: number;                  // state of charge [0.2, 0.9] (D4)
  p_charge_mw: number;          // actual charge power (≥ 0)
  p_discharge_mw: number;       // actual discharge power (≥ 0)
  p_max_charge_mw: number;      // SOC-dependent max charge rate (LOCKED v1.0.0)
  p_max_discharge_mw: number;   // SOC-dependent max discharge rate (LOCKED v1.0.0)
  soc_violation_mwh: number;    // overflow/underflow energy (penalised at 20000 ¥/MWh)
  capacity_mwh: number;         // rated capacity
}

/** Grid connection state including import limit (D12). */
export interface PccBlock {
  export_mw: number;            // power exported to grid this step
  import_mw: number;            // power imported from grid this step
  max_export_mw: number;        // site PCC limit (Gansu default 945 MW, D5)
  max_import_mw: number;        // site import limit (Gansu default 400 MW, D12)
}

/** Per-step cost breakdown. */
export interface CostsBlock {
  c_energy_yuan: number;
  c_import_yuan: number;        // display decomposition of c_energy (import portion)
  r_export_yuan: number;        // display decomposition of c_energy (export rebate)
  c_demand_charge_yuan: number; // real monthly demand charge (D10)
  c_demand_shape_yuan: number;  // raw C_DC_shape (2× weight applied by reward, D13)
  c_degradation_yuan: number;
  c_curtail_yuan: number;
  c_voll_yuan: number;
  penalty_yuan: number;         // SOC + hard-constraint penalties
  cost_total_real_yuan: number; // real-money total (D13)
  cost_total_reward_basis_yuan: number; // reward-basis total (D13)
}

/** Cumulative cost totals. */
export interface CostCumBlock {
  c_energy_yuan_cum: number;
  c_demand_charge_yuan_cum: number;
  c_degradation_yuan_cum: number;
  c_curtail_yuan_cum: number;
  c_voll_yuan_cum: number;
}

/**
 * Full env_step payload.
 * LOCKED v1.0.0 (PR #6). Consumers must use payload.sim_time_utc, NOT envelope ts_utc.
 * Global numeric invariant: ALL numeric fields are finite (no NaN / ±Inf); a message
 * that violates this MUST be silently discarded by the consumer.
 */
export interface EnvStepPayload {
  step: number;
  episode: number;
  dt_hours: number;               // always 1.0 (D3)
  sim_time_utc: string;           // ISO-8601 — sim clock; consumers use THIS, not ts_utc

  // Environment observables
  hour_of_day: number;            // [0, 23]
  minute_of_hour: number;         // [0, 59] (D8: minute-aware tariff boundaries)
  wind_speed_mps: number;         // m/s
  irradiance_wm2: number;         // W/m²
  temperature_c: number;          // °C
  load_mw: number;                // site demand (MW)
  price_buy_yuan_per_mwh: number; // ¥/MWh
  price_sell_yuan_per_mwh: number;// ¥/MWh (clamped ≥ 0, spread ≥ 0, D7)
  tariff_tier: TariffTier;

  battery: BatteryBlock;
  generation: GenerationBlock;    // LOCKED v1.0.0 addition
  flows: FlowsBlock;
  pcc: PccBlock;                  // includes max_import_mw (D12)
  costs: CostsBlock;
  cost_cum: CostCumBlock;
  month_peak_mw: number;
  reward: number;
}

// ─── train_metrics ────────────────────────────────────────────────────────────

export interface TrainMetricsPayload {
  step: number;
  episode: number;
  mean_episode_return: number;
  policy_loss: number;
  value_loss: number;
  entropy: number;
  eval_mean_return?: number;
}

// ─── eval_compare ─────────────────────────────────────────────────────────────

export interface EvalComparePayload {
  run_id: string;
  episode: number;
  rl_total_cost_yuan: number;
  baseline_no_battery_yuan: number;
  baseline_rule_based_tou_yuan: number;
  rl_vs_no_battery_pct: number;
  rl_vs_rule_based_pct: number;
}
