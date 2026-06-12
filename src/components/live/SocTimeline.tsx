import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import type { EnvStepPayload } from "../../types/telemetry";
import { socToPercent } from "../../utils/units";
import { TOKEN } from "../../styles/tokenValues";

// Named color exports — imported by design_system tests (suites 6+7) and
// any consumer that needs to programmatically query SOC chart colors.
export const SOC_LINE_COLOR   = TOKEN.chartSoc;     // #3b82f6
export const SOC_BOUNDS_COLOR = TOKEN.accentGreen;  // #22c55e
export const SOC_BAND_BG      = TOKEN.touValleyBg;  // #dcfce7

interface SocTimelineProps {
  history: EnvStepPayload[];
}

export function SocTimeline({ history }: SocTimelineProps): JSX.Element {
  if (history.length === 0) {
    return (
      <div data-testid="soc-timeline" data-state="empty" className="card soc-timeline">
        <div className="card__title">State of Charge</div>
        <div className="card__body timeline-empty">No data yet</div>
      </div>
    );
  }

  const data = history.map((s) => ({
    step: s.step,
    soc: socToPercent(s.battery.soc),
  }));

  return (
    <div data-testid="soc-timeline" className="card soc-timeline">
      <div className="card__title">State of Charge</div>
      <div className="card__body">
        {/* Accessible bounds labels for tests that can't query SVG */}
        <div className="soc-bounds-label" aria-label="SOC bounds">
          Min <strong>20</strong>% — Max <strong>90</strong>%
        </div>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={data}>
            <XAxis dataKey="step" />
            <YAxis domain={[0, 100]} unit="%" />
            {/* D4 bounds band shaded between 20–90% */}
            <ReferenceArea y1={20} y2={90} fill={SOC_BAND_BG} fillOpacity={0.3} />
            <ReferenceLine
              y={20}
              stroke={SOC_BOUNDS_COLOR}
              strokeDasharray="4 4"
              label={{ value: "Min 20%", position: "insideBottomLeft", fontSize: 10 }}
            />
            <ReferenceLine
              y={90}
              stroke={SOC_BOUNDS_COLOR}
              strokeDasharray="4 4"
              label={{ value: "Max 90%", position: "insideTopLeft", fontSize: 10 }}
            />
            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
            <Tooltip formatter={(v: any) => v == null ? ['', ''] : [`${Number(v).toFixed(1)} %`, "SOC"]} />
            <Line type="monotone" dataKey="soc" dot={false} stroke={SOC_LINE_COLOR} strokeWidth={1.5} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
