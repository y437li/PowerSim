/**
 * Power-flow line animation: width, particle speed, and PV emissive intensity.
 * Contract: contracts/frontend3d/site_scene.md §4.2, §7
 *
 * Flow line sizing formula (§4.2):
 *   normalized    = denominator > 0 ? clamp(flow_mw / denominator, 0, 1) : 0
 *   line_width    = 0.5 + normalized × 5.5   // canvas units, range [0.5, 6.0]
 *   particle_speed = 0.2 + normalized × 2.8  // units/s, range [0.2, 3.0]
 *
 * For regular flows the denominator is site_max_mw (wind_capacity + solar_capacity).
 * For grid PCC lines:
 *   export: clamp(pcc.export_mw / pcc.max_export_mw, 0, 1)  (D5: Gansu 945 MW)
 *   import: clamp(pcc.import_mw / pcc.max_import_mw, 0, 1)  (D12: Gansu 400 MW)
 *
 * NaN/Inf inputs are clamped defensively to their minimum values.
 *
 * PV emissive (§7):
 *   emissive = clamp(irradiance_wm2 / 1000, 0, 1)
 */

/** Clamp a value to [min, max], treating NaN as min. */
function safeClamp(value: number, min: number, max: number): number {
  if (!isFinite(value) || value < min) return min;
  if (value > max) return max;
  return value;
}

/**
 * Power-flow line width in canvas units.
 *
 * @param flowMw      - power flow in MW (negative values treated as 0)
 * @param denominator - normalization denominator in MW (> 0; if 0, returns minimum)
 * @returns           - line width in canvas units, range [0.5, 6.0]
 */
export function calcFlowWidth(flowMw: number, denominator: number): number {
  if (!isFinite(flowMw)) return 0.5; // NaN/Inf → minimum
  if (denominator <= 0) return 0.5;  // degenerate config guard
  const normalized = safeClamp(flowMw / denominator, 0, 1);
  return 0.5 + normalized * 5.5;
}

/**
 * Power-flow particle speed.
 *
 * @param flowMw      - power flow in MW
 * @param denominator - normalization denominator in MW
 * @returns           - particle speed in units/s, range [0.2, 3.0]
 */
export function calcFlowSpeed(flowMw: number, denominator: number): number {
  if (!isFinite(flowMw)) return 3.0; // Inf → maximum (belt-and-suspenders)
  if (denominator <= 0) return 0.2;
  const normalized = safeClamp(flowMw / denominator, 0, 1);
  return 0.2 + normalized * 2.8;
}

/**
 * PV panel emissive intensity from solar irradiance.
 *
 * @param irradianceWm2 - solar irradiance in W/m²
 * @returns             - emissive factor [0, 1] for the PV surface material
 */
export function calcEmissive(irradianceWm2: number): number {
  if (!isFinite(irradianceWm2)) return 0;
  return safeClamp(irradianceWm2 / 1000, 0, 1);
}
