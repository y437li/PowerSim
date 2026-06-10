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
import type { EnvStepPayload } from "../../types/telemetry";
import { TOU_SCHEDULE } from "../../utils/touSchedule";
import { getTouColor } from "../../utils/touColors";

interface PriceTimelineProps {
  history: EnvStepPayload[];
}

/** Accessible band list — shared between empty and non-empty renders.
 *  Uses the visually-hidden pattern: clipped off-screen but accessible to AT and role queries.
 *  NOT display:none — that removes from accessibility tree and breaks getByRole().
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

  const data = history.map((s) => ({
    step: s.step,
    price: s.price_buy_yuan_per_mwh,
    tier: s.tariff_tier,
  }));

  return (
    <div data-testid="price-timeline" className="card price-timeline">
      <div className="card__title">Price Timeline (¥/MWh)</div>
      <div className="card__body">
        <ResponsiveContainer width="100%" height={180}>
          <ComposedChart data={data}>
            <XAxis dataKey="step" />
            <YAxis domain={[0, 900]} unit=" ¥/MWh" />
            {/* TOU background price-band shading (C1: static schedule, NOT tariff_tier stream) */}
            <ReferenceArea y1={0}   y2={350}  fill={getTouColor("valley").bg}       fillOpacity={0.3} />
            <ReferenceArea y1={350} y2={535}  fill={getTouColor("mid").bg}           fillOpacity={0.3} />
            <ReferenceArea y1={535} y2={700}  fill={getTouColor("peak").bg}          fillOpacity={0.3} />
            <ReferenceArea y1={700} y2={900}  fill={getTouColor("critical_peak").bg} fillOpacity={0.3} />
            <Tooltip formatter={(v: number) => [`¥${v}/MWh`, "Buy price"]} />
            <Line
              type="stepAfter"
              dataKey="price"
              dot={false}
              stroke="#1d4ed8"
              strokeWidth={1.5}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {/* Accessible band list — hidden, carries data-from-min/data-to-min for C1 geometry tests */}
      <TouBandList />
    </div>
  );
}
