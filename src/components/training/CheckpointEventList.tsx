import React from "react";
import { Card } from "../Card";
import { formatSteps, formatYuan } from "../../utils/units";
import type { TrainMetricsPayload } from "../../types/telemetry";

interface CheckpointEventListProps {
  history: TrainMetricsPayload[];
}

/**
 * Ordered list of eval checkpoint events, newest first.
 * Filters history to is_eval_checkpoint === true only.
 */
export function CheckpointEventList({ history }: CheckpointEventListProps): JSX.Element {
  // Filter and reverse so newest is first
  const checkpoints = [...history]
    .filter((m) => m.is_eval_checkpoint === true)
    .reverse();

  return (
    <Card title="Checkpoints">
      {checkpoints.length === 0 ? (
        <p className="checkpoint-list__empty">No checkpoints yet</p>
      ) : (
        <ol className="checkpoint-list" reversed>
          {checkpoints.map((ckpt, i) => (
            <li key={i} className="checkpoint-list__item">
              <code className="checkpoint-list__id">
                {ckpt.checkpoint_id ?? "—"}
              </code>
              <span className="checkpoint-list__step">
                {formatSteps(ckpt.global_step)}
              </span>
              <span className="checkpoint-list__cost">
                {formatYuan(ckpt.cost_total_real_mean_yuan)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
