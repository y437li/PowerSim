import React, { useMemo } from "react";
import { useTrainingStore } from "../stores/trainingStore";
import { useEvalStore }     from "../stores/evalStore";
import { useTelemetryStore } from "../stores/telemetryStore";
import { createRestClient }  from "../clients/restClient";
import { StreamStatusBanner }   from "../components/training/StreamStatusBanner";
import { RunSelector }          from "../components/training/RunSelector";
import { ThroughputCard }       from "../components/training/ThroughputCard";
import { MetricCurves }         from "../components/training/MetricCurves";
import { CheckpointEventList }  from "../components/training/CheckpointEventList";
import { EvalCompareTable }     from "../components/training/EvalCompareTable";

/**
 * Route: /training — training metrics dashboard.
 *
 * NO 3D scene or SceneMountPoint — training is independent of the simulator view.
 * Consumes: trainingStore (history / latest / trainSeqGap / latestTsUtc),
 *            evalStore (latest), telemetryStore (wsStatus only),
 *            REST client (runs list for RunSelector).
 *
 * Stores are consumed WITHOUT Zustand selectors so that vitest's
 * mockReturnValue(stateObject) works correctly in integration tests — the mock
 * returns the whole state object which is destructured below.
 */
export function TrainingPanel(): JSX.Element {
  // ── Store reads (no selectors — required for test-mock compatibility) ──────
  const trainingState  = useTrainingStore();
  const evalState      = useEvalStore();
  const telemetryState = useTelemetryStore();

  const { history, latest, trainSeqGap, latestTsUtc } = trainingState;
  const { latest: evalLatest }                         = evalState;
  const { wsStatus }                                   = telemetryState;

  // ── REST client — stable singleton per component lifetime ──────────────────
  const restClient = useMemo(
    () => createRestClient({ baseUrl: "/api" }),
    []
  );

  // ── Derived display state ───────────────────────────────────────────────────
  const isEmpty        = history.length === 0;
  const isDisconnected = wsStatus === "disconnected";

  // Timestamp for data-stale check in StreamStatusBanner.
  // latestTsUtc is optional (undefined when mock doesn't supply it) → treat as null.
  const lastMessageTsUtc: string | null = latestTsUtc ?? null;

  return (
    <div data-testid="training-panel" className="route-training-panel">
      {/* 1 — Status banner: renders only when stale / gap / disconnected */}
      <StreamStatusBanner
        wsStatus={wsStatus}
        lastMessageTsUtc={lastMessageTsUtc}
        seqGap={trainSeqGap}
      />

      {/* 2 — Run selector (compact header row; display-only) */}
      <RunSelector restClient={restClient} />

      {/* Content area */}
      {isEmpty ? (
        // Empty state: show "Waiting" only when NOT disconnected (§3.1)
        !isDisconnected ? (
          <div className="training-panel__empty">
            <span className="training-panel__spinner" aria-hidden="true" />
            <p>Waiting for training data…</p>
          </div>
        ) : (
          // Empty + disconnected: blank area — banner above is the signal (E11c)
          <div className="training-panel__blank" />
        )
      ) : (
        <>
          {/* 3 — Throughput summary card */}
          <ThroughputCard latest={latest} />

          {/* 4 — Metric curves (main content, 5 panels) */}
          <MetricCurves history={history} />

          {/* 5 — Checkpoint event list */}
          <CheckpointEventList history={history} />

          {/* 6 — Eval comparison table (only when an eval result exists) */}
          {evalLatest !== null && (
            <EvalCompareTable latest={evalLatest} />
          )}
        </>
      )}
    </div>
  );
}

export default TrainingPanel;
