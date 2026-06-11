/**
 * isPayloadFinite — NaN/Inf guard for EnvStepPayload.
 * Contract: contracts/frontend3d/scene_graph.md §1
 *
 * Extracted from SiteScene.tsx (PR #7) into a shared utility so that both
 * SiteScene and SceneContent can use the same guard without duplication.
 *
 * Returns true iff every numeric field in the payload is a finite number.
 * A payload that fails this check must be discarded by callers (freeze on
 * last valid, do not animate to NaN/Inf).
 */

import type { EnvStepPayload } from "../types/telemetry";

/**
 * Returns true iff every numeric field in `step` is a finite number.
 * A false return means the payload contains NaN or ±Infinity and must
 * not be used for animation or display.
 */
export function isPayloadFinite(step: EnvStepPayload): boolean {
  // Scalar fields (LOCKED telemetry schema v1.0.0, PR #6)
  const scalars: number[] = [
    step.step, step.episode, step.dt_hours,
    step.hour_of_day, step.minute_of_hour,
    step.wind_speed_mps, step.irradiance_wm2, step.temperature_c,
    step.load_mw, step.price_buy_yuan_per_mwh, step.price_sell_yuan_per_mwh,
    step.battery.soc, step.battery.p_charge_mw, step.battery.p_discharge_mw,
    step.battery.p_max_charge_mw, step.battery.p_max_discharge_mw,
    step.battery.soc_violation_mwh, step.battery.capacity_mwh,
    step.generation.gross_solar_mw, step.generation.gross_wind_mw,
    step.pcc.export_mw, step.pcc.import_mw,
    step.pcc.max_export_mw, step.pcc.max_import_mw,
    step.month_peak_mw, step.reward,
  ];
  for (const v of scalars) {
    if (!isFinite(v)) return false;
  }
  // Flows block — all values must be finite
  const flows = Object.values(step.flows) as number[];
  for (const v of flows) {
    if (!isFinite(v)) return false;
  }
  return true;
}
