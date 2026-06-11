/**
 * wsClientSingleton — two WsClient instances wired to telemetryStore + trainingStore.
 * Contract: contracts/frontend/app_integration.md §2
 *
 * Two clients are required because the serving layer exposes two WebSocket endpoints
 * carrying different message kinds:
 *   WS /ws/inference        → env_step + status  (inference_stream.md:24)
 *   WS /ws/training/stream  → train_metrics       (training_proxy.md:98)
 *
 * Handler functions are exported as named exports for direct testability (§T_wire).
 * URL constants are exported for direct URL pinning tests (§T_url).
 *
 * Neither client opens a socket at import time — connect() is called by App.useEffect.
 */

import { createWsClient, type WsClient } from "./wsClient";
import type { TelemetryEnvelope, WsStatus, ServerStatusFrame, ServerErrorFrame } from "../types/telemetry";
import { useTelemetryStore } from "../stores/telemetryStore";
import { useTrainingStore } from "../stores/trainingStore";
import { inferenceSessionStore } from "../stores/inferenceSessionStore";

// ─── URL constants ────────────────────────────────────────────────────────────

/** WS endpoint for env_step + status (contracts/serving/inference_stream.md:24) */
export const TELEMETRY_WS_URL = "/ws/inference";

/** WS endpoint for train_metrics (contracts/serving/training_proxy.md:98) */
export const TRAINING_WS_URL = "/ws/training/stream";

// ─── Handler functions (exported for §T_wire direct tests) ───────────────────

/** Routes env_step envelopes to telemetryStore.receiveEnvStep. */
export function handleEnvStep(msg: TelemetryEnvelope): void {
  useTelemetryStore.getState().receiveEnvStep(msg);
}

/** Routes train_metrics envelopes to trainingStore.receiveTrainMetrics. */
export function handleTrainMetrics(msg: TelemetryEnvelope): void {
  useTrainingStore.getState().receiveTrainMetrics(msg);
}

/**
 * Routes WS status changes to telemetryStore.setWsStatus.
 * TrainingPanel reads wsStatus from telemetryStore (confirmed TrainingPanel.tsx:33),
 * so a single status path serves both SiteView and TrainingPanel.
 * trainingWsClient's onStatusChange is a no-op.
 */
export function handleStatusChange(status: WsStatus): void {
  useTelemetryStore.getState().setWsStatus(status);
}

// ─── Client singletons ────────────────────────────────────────────────────────

/**
 * Telemetry client — connects to /ws/inference.
 * Receives env_step; drives telemetryStore (SiteView / LiveDashboard).
 */
export const telemetryWsClient: WsClient = createWsClient({
  url: TELEMETRY_WS_URL,
  onEnvStep: handleEnvStep,
  onTrainMetrics: () => {},        // /ws/inference never sends train_metrics
  onEvalCompare: () => {},          // eval_compare: no v1 consumer
  onStatusChange: handleStatusChange,
  // Session control: route server status/error frames to inferenceSessionStore
  onServerStatus: (frame: ServerStatusFrame) =>
    inferenceSessionStore.getState().handleServerStatus(frame),
  onServerError: (frame: ServerErrorFrame) =>
    inferenceSessionStore.getState().handleServerError(frame),
});

/**
 * Training client — connects to /ws/training/stream.
 * Receives train_metrics; drives trainingStore (TrainingPanel).
 */
export const trainingWsClient: WsClient = createWsClient({
  url: TRAINING_WS_URL,
  onEnvStep: () => {},              // /ws/training/stream never sends env_step
  onTrainMetrics: handleTrainMetrics,
  onEvalCompare: () => {},
  onStatusChange: () => {},         // training WS status not surfaced in UI
                                    // (TrainingPanel reads wsStatus from telemetryStore)
});
