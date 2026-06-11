import React from "react";
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceArea,
  ResponsiveContainer,
} from "recharts";
import type { EnvStepPayload, TariffTier } from "../../types/telemetry";
import { TOU_SCHEDULE, computeBandSegments } from "../../utils/touSchedule";
import { getTouColor } from "../../utils/touColors";

interface PriceTimelineProps {
  history: EnvStepPayload[];
}

/**
 * Accessible band list — shared between empty and non-empty renders.
 * Uses the visually-hidden pattern (clipped, 1px) so getByRole("list") still works.
 * NOT display:none — that removes from the accessibility tree entirely.
 * Each <li> carries data-tier, data-from-min, data-to-min from the static TOU_SCHEDULE
 * for the C1 geometry tests (pins 630/690, not the naïve 660/720 hourly boundary).
 */
function TouBandList(): JSX.Element {
  return (
    <ul
      aria-label="TOU bands"
      style={{
        position: "absolute",
        width: "1px",
        height: "1px",
        padding: 0,
        margin: "-1px",
        overflow: "hidden",
        clip: "rect(0,0,0,0)",
        whiteSpace: "nowrap",
        border: 0,
      }}
    >
      {TOU_SCHEDULE.map((band, i) => (
        <li
          key={i}
          data-tier={band.tier}
          data-from-min={String(band.fromMinutes)}
          data-to-min={String(band.toMinutes)}
        >
          {band.tier}
        </li>
      ))}
    </ul>
  );
}

export function PriceTimeline({ history }: PriceTimelineProps): JSX.Element {
  if (history.length === 0) {
    return (
      <div data-testid="price-timeline" data-state="empty" className="card price-timeline">
        <div className="card__title">Price Timeline</div>
        <div className="card__body timeline-empty">No data yet</div>
        <TouBandList />
      </div>
    );
  }

  // Chart-level data: step + price + tier for tooltip/coloring
  const data = history.map((s) => ({
    step: s.step,
    price: s.price_buy_yuan_per_mwh,
    tier: s.tariff_tier,
  }));

  // C1 fix: compute TOU background bands as x-axis step-index spans.
  // computeBandSegments groups adjacent steps by tier using minute-aware getTouTier (D8),
  // so 11:00 (660 min) → critical_peak (630–690), not mid.
  // These drive ReferenceArea x1/x2 — NOT y-axis price stripes.
  const bandSegments = computeBandSegments(history);

  // Per-segment line data: each segment's steps + the first step of the next segment
  // (bridge point) to avoid visual gaps between tier-coloured segments.
  const tierLineSegments = bandSegments.map((seg, segIdx) => {
    const pts = history
      .filter((s) => s.step >= seg.x1 && s.step <= seg.x2)
      .map((s) => ({ step: s.step, price: s.price_buy_yuan_per_mwh }));
    const nextSeg = bandSegments[segIdx + 1];
    if (nextSeg) {
      const bridge = history.find((s) => s.step === nextSeg.x1);
      if (bridge) pts.push({ step: bridge.step, price: bridge.price_buy_yuan_per_mwh });
    }
    return { seg, pts };
  });

  return (
    <div data-testid="price-timeline" className="card price-timeline">
      <div className="card__title">Price Timeline (¥/MWh)</div>
      <div className="card__body">
        <ResponsiveContainer width="100%" height={180}>
          <ComposedChart data={data}>
            <XAxis dataKey="step" type="number" domain={["dataMin", "dataMax"]} />
            <YAxis domain={[0, 900]} unit=" ¥/MWh" />
            {/*
              TOU background bands on the X-AXIS (time dimension), not y-axis price stripes.
              Each band spans x1..x2 step indices computed from the static TOU_SCHEDULE
              via computeBandSegments — never from the tariff_tier stream (C1, §2.4).
            */}
            {bandSegments.map((seg, i) => (
              <ReferenceArea
                key={`band-${i}`}
                x1={seg.x1}
                x2={seg.x2}
                fill={getTouColor(seg.tier).bg}
                fillOpacity={0.35}
              />
            ))}
            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
            <Tooltip formatter={(v: any) => v == null ? ['', ''] : [`¥${v}/MWh`, "Buy price"]} />
            {/*
              Tier-coloured price line — one Line per contiguous tier segment (§2.4 [should]).
              Each segment's line uses its tier's colour token from touColors.ts.
            */}
            {tierLineSegments.map(({ seg, pts }, segIdx) => (
              <Line
                key={`tier-line-${segIdx}`}
                data={pts}
                dataKey="price"
                type="stepAfter"
                dot={false}
                stroke={getTouColor(seg.tier as TariffTier).text}
                strokeWidth={1.5}
                isAnimationActive={false}
                legendType="none"
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {/* Accessible band list — visually hidden; carries data-from-min/data-to-min for C1 tests */}
      <TouBandList />
    </div>
  );
}
