import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { Card } from "../Card";
import { formatSteps } from "../../utils/units";
import type { TrainMetricsPayload } from "../../types/telemetry";

interface MetricCurvesProps {
  history: TrainMetricsPayload[];
}

interface ChartPanel {
  key: keyof TrainMetricsPayload;
  label: string;
  color: string;
  allowNegative?: boolean;
}

const PANELS: ChartPanel[] = [
  { key: "actor_loss",              label: "Actor Loss",      color: "#6366f1" },
  { key: "critic_loss",             label: "Critic Loss",     color: "#f59e0b" },
  { key: "ent_coef",                label: "Entropy Coeff",   color: "#10b981" },
  { key: "reward_scaled_mean",      label: "Reward (scaled)", color: "#3b82f6" },
  { key: "cost_total_real_mean_yuan", label: "Episode Cost",  color: "#ef4444", allowNegative: true },
];

/** Truncate a checkpoint_id string to at most 10 chars for the marker label. */
function truncateId(id: string | null): string {
  if (!id) return "—";
  return id.length > 10 ? id.slice(0, 10) : id;
}

/**
 * Five line-chart panels driven by trainingStore.history.
 * X-axis: global_step. Each panel shows one scalar series.
 * Checkpoint markers (vertical reference lines) on panels where is_eval_checkpoint=true.
 * reward_norm_mean is deliberately NOT plotted (null on eval checkpoints, different basis).
 */
export function MetricCurves({ history }: MetricCurvesProps): JSX.Element {
  if (history.length === 0) {
    return (
      <div data-testid="metric-curves" className="metric-curves metric-curves--empty">
        <p>No training data yet</p>
      </div>
    );
  }

  const checkpointSteps = history
    .filter((m) => m.is_eval_checkpoint)
    .map((m) => ({ step: m.global_step, id: m.checkpoint_id }));

  // Build chart-ready data — filter out null values for each series separately
  const chartData = history.map((m) => ({
    step: m.global_step,
    actor_loss: m.actor_loss,
    critic_loss: m.critic_loss,
    ent_coef: m.ent_coef,
    reward_scaled_mean: m.reward_scaled_mean,
    cost_total_real_mean_yuan: m.cost_total_real_mean_yuan,
  }));

  return (
    <div data-testid="metric-curves" className="metric-curves">
      {/* Accessible checkpoint ID list — visually hidden, full IDs for screen readers and tests.
           SVG label inside Recharts (below) is separately truncated to 10 chars for display space. */}
      {checkpointSteps.length > 0 && (
        <ul className="sr-only" aria-label="Checkpoint markers">
          {checkpointSteps.map(({ step, id }) => (
            <li key={step}>{id ?? "—"}</li>
          ))}
        </ul>
      )}
      {PANELS.map((panel) => (
        <div key={panel.key} className="metric-curves__panel">
          <Card title={panel.label}>
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis
                  dataKey="step"
                  tickFormatter={(v: number) => formatSteps(v)}
                  tick={{ fontSize: 11 }}
                />
                <YAxis
                  allowDataOverflow={false}
                  domain={panel.allowNegative ? ["auto", "auto"] : [0, "auto"]}
                  tick={{ fontSize: 11 }}
                />
                <Tooltip
                  formatter={(value: number) =>
                    panel.key === "cost_total_real_mean_yuan"
                      ? [`¥${value.toLocaleString()}`, panel.label]
                      : [value.toFixed(4), panel.label]
                  }
                  labelFormatter={(v: number) => formatSteps(v)}
                />
                <Line
                  type="monotone"
                  dataKey={panel.key as string}
                  stroke={panel.color}
                  dot={false}
                  strokeWidth={1.5}
                  connectNulls={false}
                />
                {/* Checkpoint reference lines */}
                {checkpointSteps.map(({ step, id }) => (
                  <ReferenceLine
                    key={step}
                    x={step}
                    stroke="#9ca3af"
                    strokeDasharray="4 2"
                    label={{
                      value: truncateId(id),
                      position: "top",
                      fontSize: 9,
                      fill: "#6b7280",
                    }}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </div>
      ))}
    </div>
  );
}
