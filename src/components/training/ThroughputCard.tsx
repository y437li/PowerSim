import React from "react";
import { Card } from "../Card";
import { NumberDisplay } from "../NumberDisplay";
import { formatThroughput, formatSteps, formatWallSeconds } from "../../utils/units";
import type { TrainMetricsPayload } from "../../types/telemetry";

interface ThroughputCardProps {
  latest: TrainMetricsPayload | null;
}

/**
 * Compact card showing training throughput metrics.
 * All formatting via units.ts — no inline conversion.
 */
export function ThroughputCard({ latest }: ThroughputCardProps): JSX.Element {
  return (
    <Card title="Throughput">
      <div className="throughput-card">
        <div className="throughput-card__row">
          <span className="throughput-card__label">Steps/s</span>
          <span className="throughput-card__value">
            {latest !== null ? formatThroughput(latest.env_steps_per_sec) : "—"}
          </span>
        </div>
        <div className="throughput-card__row">
          <span className="throughput-card__label">Total Steps</span>
          <span className="throughput-card__value">
            {latest !== null ? formatSteps(latest.global_step) : "—"}
          </span>
        </div>
        <div className="throughput-card__row">
          <span className="throughput-card__label">Wall Time</span>
          <span className="throughput-card__value">
            {latest !== null ? formatWallSeconds(latest.wall_seconds) : "—"}
          </span>
        </div>
      </div>
    </Card>
  );
}
