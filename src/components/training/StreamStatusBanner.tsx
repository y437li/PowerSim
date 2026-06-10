import React from "react";
import type { WsStatus } from "../../types/telemetry";

/** Data-stale threshold: no train_metrics message received in >30s (wall clock). */
const STALE_THRESHOLD_MS = 30_000;

interface StreamStatusBannerProps {
  wsStatus: WsStatus;
  lastMessageTsUtc: string | null;
  seqGap: boolean; // from trainingStore.trainSeqGap
}

/**
 * Renders a status banner when the training stream is degraded.
 * Returns null when connected, fresh, and no gap — silent in the happy path.
 *
 * Precedence (highest→lowest): disconnected > wsStatus=stale > seqGap > data-stale.
 */
export function StreamStatusBanner({
  wsStatus,
  lastMessageTsUtc,
  seqGap,
}: StreamStatusBannerProps): JSX.Element | null {
  // 1 — WS fully disconnected (highest severity)
  if (wsStatus === "disconnected") {
    return (
      <div className="stream-banner stream-banner--error" role="alert">
        Training stream disconnected
      </div>
    );
  }

  // 2 — WS transport stale (distinct from local data-stale check)
  if (wsStatus === "stale") {
    return (
      <div className="stream-banner stream-banner--warning" role="alert">
        Training stream stale (connection)
      </div>
    );
  }

  // 3 — Seq gap detected by store
  if (seqGap) {
    return (
      <div className="stream-banner stream-banner--warning" role="alert">
        Sequence gap detected — some training steps may be missing
      </div>
    );
  }

  // 4 — Data stale: connected but no message in >30s
  // Only fires when at least one message was received (lastMessageTsUtc !== null)
  if (
    wsStatus === "connected" &&
    lastMessageTsUtc !== null &&
    Date.now() - Date.parse(lastMessageTsUtc) > STALE_THRESHOLD_MS
  ) {
    return (
      <div className="stream-banner stream-banner--warning" role="alert">
        Training stream stale — no update in &gt;30s
      </div>
    );
  }

  return null;
}
