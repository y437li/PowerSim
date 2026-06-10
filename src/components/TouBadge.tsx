import type { TariffTier } from "../types/telemetry";
import { getTouColor } from "../utils/touColors";
import { formatYuanPerMwh } from "../utils/units";

const TIER_LABELS: Record<TariffTier, string> = {
  critical_peak: "Critical Peak",
  peak: "Peak",
  mid: "Mid",
  valley: "Valley",
};

interface TouBadgeProps {
  tier: TariffTier | null;
  showPrice?: boolean;
  /** Wire value in ¥/MWh (from price_buy_yuan_per_mwh); formatted via formatYuanPerMwh. */
  priceYuanPerMwh?: number;
  className?: string;
}

/**
 * TOU-tier coloured badge. Tier label from TIER_LABELS; colour tokens from touColors.ts.
 * When showPrice=true and priceYuanPerMwh is supplied, renders the formatted wire price.
 * The price is ALWAYS the wire value (price_buy_yuan_per_mwh); the §3.7 static table
 * is NOT consulted here — that would create a second source of truth.
 */
export function TouBadge({ tier, showPrice = false, priceYuanPerMwh, className = "" }: TouBadgeProps) {
  if (tier === null) {
    return <span className={`tou-badge tou-null ${className}`.trim()}>—</span>;
  }

  const { bg, text, border } = getTouColor(tier);

  return (
    <span
      className={`tou-badge tou-${tier} ${className}`.trim()}
      style={{ backgroundColor: bg, color: text, borderColor: border }}
    >
      {TIER_LABELS[tier]}
      {showPrice && priceYuanPerMwh !== undefined && (
        <span className="tou-badge__price"> {formatYuanPerMwh(priceYuanPerMwh)}</span>
      )}
    </span>
  );
}
