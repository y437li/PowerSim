/**
 * Battery SOC fill animation.
 * Contract: contracts/frontend3d/site_scene.md §5
 * Decision: D4 (SOC bounds [0.2, 0.9])
 *
 * Formula:
 *   soc_fill = clamp((soc − soc_min) / (soc_max − soc_min), 0, 1)
 *
 * Maps SOC [0.2, 0.9] → fill factor [0, 1].
 * Values outside [soc_min, soc_max] are clamped (defensive against
 * malformed telemetry; the producer should never send out-of-bounds SOC).
 */

/**
 * @param soc    - battery state of charge [0, 1]
 * @param socMin - minimum SOC bound (D4: 0.2)
 * @param socMax - maximum SOC bound (D4: 0.9)
 * @returns      - fill factor [0, 1] for the SOC fill mesh
 */
export function calcSocFill(
  soc: number,
  socMin: number,
  socMax: number
): number {
  if (!isFinite(soc)) return 0; // defensive: NaN/Inf → empty display
  const normalized = (soc - socMin) / (socMax - socMin);
  return Math.max(0, Math.min(1, normalized));
}
