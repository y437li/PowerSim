// All TOU tier colour tokens live here — nowhere else defines them inline.
import type { TariffTier } from "../types/telemetry";
import { TOKEN } from "../styles/tokenValues";

export const TOU_COLORS: Record<TariffTier, { bg: string; text: string; border: string }> = {
  critical_peak: { bg: TOKEN.touCriticalPeakBg, text: TOKEN.touCriticalPeakText, border: TOKEN.touCriticalPeakBorder }, // red
  peak:          { bg: TOKEN.touPeakBg,          text: TOKEN.touPeakText,          border: TOKEN.touPeakBorder },          // amber
  mid:           { bg: TOKEN.touMidBg,            text: TOKEN.touMidText,            border: TOKEN.touMidBorder },            // blue
  valley:        { bg: TOKEN.touValleyBg,         text: TOKEN.touValleyText,         border: TOKEN.touValleyBorder },         // green
};

/** Returns the colour tokens for a TOU tier. */
export function getTouColor(tier: TariffTier): { bg: string; text: string; border: string } {
  return TOU_COLORS[tier];
}

/** Returns the CSS variable name for a TOU tier, e.g. "--tou-peak". */
export function getTouCssVar(tier: TariffTier): string {
  return `--tou-${tier}`;
}
