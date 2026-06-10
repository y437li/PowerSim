/**
 * Turbine rotor angular velocity from wind speed.
 * Contract: contracts/frontend3d/site_scene.md §6
 * Spec: REBUILD_SPEC.md §3.1
 *
 * The rotor omega uses a LINEAR ramp between cut-in and rated speed.
 * (The cubic curve applies to electrical power; rotor RPM scales linearly.)
 *
 * Formula:
 *   v < v_cutin             → 0
 *   v_cutin ≤ v < v_rated   → omega_max * (v − v_cutin) / (v_rated − v_cutin)
 *   v_rated ≤ v < v_cutout  → omega_max  (plateau at full speed)
 *   v ≥ v_cutout             → 0         (turbine shuts down)
 *   v < 0                    → 0         (defensive: malformed telemetry)
 */

/**
 * @param windSpeedMps  - wind speed in m/s (from envStep.wind_speed_mps)
 * @param cutInMps      - cut-in wind speed in m/s (e.g. 3)
 * @param ratedMps      - rated wind speed in m/s (e.g. 12)
 * @param cutOutMps     - cut-out wind speed in m/s (e.g. 25)
 * @param omegaMaxRad   - maximum angular velocity in rad/s (visual reference, e.g. 0.2)
 * @returns             - rotor angular velocity in rad/s
 */
export function calcRotorOmega(
  windSpeedMps: number,
  cutInMps: number,
  ratedMps: number,
  cutOutMps: number,
  omegaMaxRad: number
): number {
  // Defensive: negative wind speed, NaN, or Inf → treat as no wind
  if (!isFinite(windSpeedMps) || windSpeedMps < 0) return 0;
  // Below cut-in or at/above cut-out: turbine off
  if (windSpeedMps < cutInMps || windSpeedMps >= cutOutMps) return 0;
  // Rated region: full speed
  if (windSpeedMps >= ratedMps) return omegaMaxRad;
  // Ramp region: linear
  return omegaMaxRad * (windSpeedMps - cutInMps) / (ratedMps - cutInMps);
}
