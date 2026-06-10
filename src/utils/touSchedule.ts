// src/utils/touSchedule.ts — consumed by PriceTimeline background bands and getTouTier()
import type { TariffTier } from "../types/telemetry";

export interface TouBand {
  fromMinutes: number;  // minutes-from-midnight (inclusive start)
  toMinutes: number;    // minutes-from-midnight (exclusive end)
  tier: TariffTier;
  priceYuanPerMwh: number;
}

// §3.7 Gansu 4-tier TOU — minute-accurate (D8)
// 10:30 = 630 min; 11:30 = 690 min; 19:00 = 1140 min; 21:00 = 1260 min; 23:00 = 1380 min
export const TOU_SCHEDULE: TouBand[] = [
  { fromMinutes: 0,    toMinutes: 420,  tier: "valley",        priceYuanPerMwh: 250 },
  { fromMinutes: 420,  toMinutes: 480,  tier: "mid",           priceYuanPerMwh: 450 },
  { fromMinutes: 480,  toMinutes: 630,  tier: "peak",          priceYuanPerMwh: 620 },
  { fromMinutes: 630,  toMinutes: 690,  tier: "critical_peak", priceYuanPerMwh: 780 },
  { fromMinutes: 690,  toMinutes: 1080, tier: "mid",           priceYuanPerMwh: 450 },
  { fromMinutes: 1080, toMinutes: 1140, tier: "peak",          priceYuanPerMwh: 620 },
  { fromMinutes: 1140, toMinutes: 1260, tier: "critical_peak", priceYuanPerMwh: 780 },
  { fromMinutes: 1260, toMinutes: 1380, tier: "peak",          priceYuanPerMwh: 620 },
  { fromMinutes: 1380, toMinutes: 1440, tier: "valley",        priceYuanPerMwh: 250 },
];

export function getTouTier(minuteOfDay: number): TariffTier {
  for (const band of TOU_SCHEDULE) {
    if (minuteOfDay >= band.fromMinutes && minuteOfDay < band.toMinutes) {
      return band.tier;
    }
  }
  return "valley"; // fallback — should never hit if minuteOfDay ∈ [0, 1439]
}

export function getTouPrice(tier: TariffTier): number {
  // Return the first matching band's price (static §3.7 reference, not wire price)
  for (const band of TOU_SCHEDULE) {
    if (band.tier === tier) return band.priceYuanPerMwh;
  }
  return 0;
}
