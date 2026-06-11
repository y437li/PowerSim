/**
 * inferenceSessionStore — inference session state and control actions.
 * Contract: contracts/frontend/inference_session.md §3
 *
 * Auto-starts an inference session when the server sends status:ready.
 * Fetches the latest checkpoint run from GET /runs/latest and sends cmd:start.
 * Exposes pause(), resume(), setSpeed() for the SessionControlStrip UI.
 */

import { create } from "zustand";
import type { ServerStatusFrame, ServerErrorFrame } from "../types/telemetry";
import { useTelemetryStore } from "./telemetryStore";
import { telemetryWsClient } from "../clients/wsClientSingleton";
import { restClient } from "../clients/restClientSingleton";

// ─── Types ────────────────────────────────────────────────────────────────────

export type InferenceServerState =
  | "idle"      // no status frame received yet
  | "ready"     // server sent status:ready; _autoStart in-flight
  | "running"   // session active, env_step frames flowing
  | "paused"    // session paused
  | "stopped"   // session stopped by server
  | "error";    // _autoStart failed or server sent error frame

export interface InferenceSessionState {
  /** Server-reported session state. "idle" = no status frame received yet. */
  serverState: InferenceServerState;
  /** Active run ID from the server status frame, or null. */
  runId: string | null;
  /** Active site ID from the server status frame, or null. */
  siteId: string | null;
  /** Session UUID assigned per cmd:start (inference_stream.md:180). Null before first start. */
  sessionId: string | null;
  /** Last completed step number (from status frame). */
  step: number;
  /** Current episode number (from status frame). */
  episode: number;
  /** Replay speed sent with cmd:start. Default: 1.0 (D24). Range [0, 100]. */
  speed: number;
  /** Human-readable error description, or null. */
  errorMsg: string | null;

  // ─── Actions ──────────────────────────────────────────────────────────────
  handleServerStatus: (frame: ServerStatusFrame) => void;
  handleServerError: (frame: ServerErrorFrame) => void;
  pause: () => void;
  resume: () => void;
  setSpeed: (speed: number) => void;
  /** Direct session start — exposed for retry. Normally called by _autoStart. */
  startSession: (runId: string, siteId: string) => void;
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const inferenceSessionStore = create<InferenceSessionState>((set, get) => {
  /**
   * Internal: fetch the latest checkpoint run and send cmd:start.
   * Sets serverState="error" on any failure (no runs, network error, etc.).
   */
  async function _autoStart(): Promise<void> {
    try {
      const run = await restClient.getLatestRun();
      get().startSession(run.id, "gansu");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === "no_runs_found") {
        set({
          serverState: "error",
          errorMsg: "No checkpoint runs found. Start training first.",
        });
      } else {
        set({
          serverState: "error",
          errorMsg: `Failed to load run: ${msg}`,
        });
      }
    }
  }

  return {
    // ─── Initial state ───────────────────────────────────────────────────
    serverState: "idle",
    runId: null,
    siteId: null,
    sessionId: null,
    step: 0,
    episode: 0,
    speed: 1.0,
    errorMsg: null,

    // ─── handleServerStatus ───────────────────────────────────────────────
    handleServerStatus(frame: ServerStatusFrame) {
      switch (frame.state) {
        case "ready":
          set({ serverState: "ready", errorMsg: null });
          void _autoStart();
          break;

        case "running": {
          // Session-ID change → clear telemetry history to prevent session mixing.
          // The serving layer assigns a fresh session_id per cmd:start (inference_stream.md:180–182).
          const currentSessionId = get().sessionId;
          if (frame.session_id !== null && frame.session_id !== currentSessionId) {
            useTelemetryStore.getState().clearHistory();
          }
          set({
            serverState: "running",
            runId: frame.run_id,
            siteId: frame.site_id,
            sessionId: frame.session_id,
            step: frame.step,
            episode: frame.episode,
          });
          break;
        }

        case "paused":
          set({
            serverState: "paused",
            step: frame.step,
            episode: frame.episode,
          });
          break;

        case "stopped":
          set({ serverState: "stopped" });
          break;
      }
    },

    // ─── handleServerError ────────────────────────────────────────────────
    handleServerError(frame: ServerErrorFrame) {
      set({
        serverState: "error",
        errorMsg: `${frame.code}: ${frame.message}`,
      });
    },

    // ─── Playback controls ────────────────────────────────────────────────
    pause() {
      telemetryWsClient.send({ cmd: "pause" });
    },

    resume() {
      telemetryWsClient.send({ cmd: "resume" });
    },

    setSpeed(speed: number) {
      set({ speed: Math.max(0, Math.min(100, speed)) });
    },

    // ─── startSession ─────────────────────────────────────────────────────
    startSession(runId: string, siteId: string) {
      telemetryWsClient.send({
        cmd: "start",
        run_id: runId,
        site_id: siteId,
        speed: get().speed,
      });
    },
  };
});

/**
 * React hook for subscribing to inferenceSessionStore state.
 * Components use this; non-React code uses inferenceSessionStore.getState().
 */
export const useInferenceSessionStore = inferenceSessionStore;
