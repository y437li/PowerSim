// src/utils/touSchedule.ts — consumed by PriceTimeline background bands and getTouTier()
import type { TariffTier, EnvStepPayload } from "../types/telemetry";

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

// ── computeBandSegments ───────────────────────────────────────────────────────

/**
 * One contiguous run of steps sharing the same TOU tier on the PriceTimeline x-axis.
 * x1/x2 are step indices (inclusive) — feed directly into Recharts ReferenceArea x1/x2.
 */
export interface BandSegment {
  tier: TariffTier;
  x1: number;          // step index at start of this contiguous tier run (inclusive)
  x2: number;          // step index at end of this contiguous tier run (inclusive)
  priceYuanPerMwh: number;
}

/**
 * Map history entries onto x-axis band segments for PriceTimeline ReferenceArea.
 *
 * For each contiguous run of adjacent steps that share the same TOU tier
 * (determined by `hour_of_day * 60 + minute_of_hour` → getTouTier, minute-aware per D8),
 * emit one BandSegment{tier, x1, x2}. Handles repeating 24h cycles correctly:
 * valley(23:00) → valley(00:00) merges into one segment; different-tier transitions always split.
 *
 * C1 correctness: uses getTouTier (minute-aware) so 11:00 (660 min) → critical_peak, not mid.
 * A naïve hour-only lookup would misplace this band by 30 minutes.
 */
export function computeBandSegments(history: EnvStepPayload[]): BandSegment[] {
  if (history.length === 0) return [];

  const getBand = (s: EnvStepPayload): TouBand => {
    const minOfDay = s.hour_of_day * 60 + s.minute_of_hour;
    return (
      TOU_SCHEDULE.find((b) => minOfDay >= b.fromMinutes && minOfDay < b.toMinutes) ??
      TOU_SCHEDULE[TOU_SCHEDULE.length - 1]
    );
  };

  const segments: BandSegment[] = [];
  let segStart = 0;
  let curBand = getBand(history[0]);

  for (let i = 1; i < history.length; i++) {
    const band = getBand(history[i]);
    if (band.tier !== curBand.tier) {
      segments.push({
        tier: curBand.tier,
        x1: history[segStart].step,
        x2: history[i - 1].step,
        priceYuanPerMwh: curBand.priceYuanPerMwh,
      });
      segStart = i;
      curBand = band;
    }
  }
  // Emit the final segment
  segments.push({
    tier: curBand.tier,
    x1: history[segStart].step,
    x2: history[history.length - 1].step,
    priceYuanPerMwh: curBand.priceYuanPerMwh,
  });

  return segments;
}
