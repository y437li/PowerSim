// All TOU tier colour tokens live here — nowhere else defines them inline.
import type { TariffTier } from "../types/telemetry";

export const TOU_COLORS: Record<TariffTier, { bg: string; text: string; border: string }> = {
  critical_peak: { bg: "#fee2e2", text: "#991b1b", border: "#f87171" }, // red
  peak:          { bg: "#fef3c7", text: "#92400e", border: "#fcd34d" }, // amber
  mid:           { bg: "#dbeafe", text: "#1e40af", border: "#93c5fd" }, // blue
  valley:        { bg: "#dcfce7", text: "#166534", border: "#86efac" }, // green
};

/** Returns the colour tokens for a TOU tier. */
export function getTouColor(tier: TariffTier): { bg: string; text: string; border: string } {
  return TOU_COLORS[tier];
}

/** Returns the CSS variable name for a TOU tier, e.g. "--tou-peak". */
export function getTouCssVar(tier: TariffTier): string {
  return `--tou-${tier}`;
}
