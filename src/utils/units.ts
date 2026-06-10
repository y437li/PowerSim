// ALL unit conversions live here — nowhere else imports conversion math inline.
// Wire values are always MW, MWh, ¥, ¥/MWh; display conversions are this file's job.

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

/**
 * SOC: fraction [0,1] → display percent. D4: 0.2→20.0, 0.9→90.0.
 * Uses toFixed(10) to eliminate IEEE-754 artifacts (e.g. 0.55*100 = 55.00000000000001).
 */
export function socToPercent(soc: number): number {
  return parseFloat((soc * 100).toFixed(10));
}

/** Power: MW → kW (display only; wire values are always MW). */
export function mwToKw(mw: number): number {
  return mw * 1000;
}

/** Power: kW → MW */
export function kwToMw(kw: number): number {
  return kw / 1000;
}

/**
 * Format a ¥ amount with thousands separator.
 * Negative values: "¥-52,700". Zero: "¥0".
 */
export function formatYuan(yuan: number, decimals = 0): string {
  const abs = Math.abs(yuan);
  const sign = yuan < 0 ? "-" : "";
  const fixed = abs.toFixed(decimals);
  const parts = fixed.split(".");
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const formatted = parts.join(".");
  return `¥${sign}${formatted}`;
}

/**
 * Format a ¥/MWh price. Contract rule: wire prices are ¥/MWh, NEVER ¥/kWh.
 * e.g. 620 → "¥620/MWh"
 */
export function formatYuanPerMwh(yuanPerMwh: number): string {
  return `¥${yuanPerMwh}/MWh`;
}

/**
 * Format power picking unit by magnitude:
 *  < 1 MW → kW (integer, e.g. "850 kW", "0 kW")
 *  ≥ 1 MW → MW (1 decimal, e.g. "1.2 MW", "40.0 MW")
 */
export function formatPower(mw: number): string {
  if (mw < 1) {
    return `${Math.round(mwToKw(mw))} kW`;
  }
  return `${mw.toFixed(1)} MW`;
}

/**
 * Format an ISO-8601 UTC sim clock as "DDD HH:MM".
 * Uses getUTCDay/getUTCHours/getUTCMinutes — timezone-invariant.
 * Contract: the sim clock IS the UTC clock; no conversion is applied.
 * e.g. "2026-03-10T08:00:00Z" → "Tue 08:00"
 */
export function formatSimTime(isoUtc: string): string {
  const d = new Date(isoUtc);
  const dayName = DAYS[d.getUTCDay()];
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${dayName} ${hh}:${mm}`;
}
