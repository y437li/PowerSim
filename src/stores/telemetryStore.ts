import { create } from "zustand";
import type { EnvStepPayload, TelemetryEnvelope, WsStatus } from "../types/telemetry";

const HISTORY_MAX_LEN = 168; // D3: max episode length = 168 steps at Δt=1h
const FRAME_ERRORS_CAP = 10; // §13.2: ring buffer cap

// ─── FrameError type (§13.1) ────────────────────────────────────────────────

/**
 * One entry in the frame-validation failure ring buffer.
 * Populated by wsClient.handleMessage when validate() rejects a data frame.
 */
export interface FrameError {
  /** ISO-8601 timestamp: msg.ts_utc if parseable, else new Date().toISOString() */
  ts_utc: string;
  /** msg.kind, or "unknown" if the message was not parseable */
  kind: string;
  /** msg.seq, or -1 if the message was not parseable */
  seq: number;
  /** Validation error codes from ValidationResult.errors, or ["validate_threw"] */
  errors: string[];
}

// ─── Store ───────────────────────────────────────────────────────────────────

export interface TelemetryState {
  // Latest env_step payload (null until first message)
  envStep: EnvStepPayload | null;
  // Ring buffer: up to HISTORY_MAX_LEN most-recent env_step payloads
  history: EnvStepPayload[];
  // WebSocket connection status
  wsStatus: WsStatus;
  // Current run_id (null until first message)
  runId: string | null;
  // Sequence gap detection
  lastSeq: number | null;
  seqGap: boolean;
  // §13.2: Ring buffer of recent frame validation failures — most-recent-first.
  frameErrors: FrameError[];

  // Actions
  receiveEnvStep: (msg: TelemetryEnvelope) => void;
  clearHistory: () => void;
  setWsStatus: (status: WsStatus) => void;
  /** Prepend a new FrameError entry; trim the buffer to FRAME_ERRORS_CAP (10). */
  pushFrameError: (err: FrameError) => void;
}

export const useTelemetryStore = create<TelemetryState>((set, get) => ({
  envStep: null,
  history: [],
  wsStatus: "disconnected",
  runId: null,
  lastSeq: null,
  seqGap: false,
  frameErrors: [],

  receiveEnvStep(msg: TelemetryEnvelope) {
    const payload = msg.payload as EnvStepPayload;
    const incomingRunId = msg.run_id;
    const incomingSeq = msg.seq;
    const state = get();

    // §12.3: run_id change → store-internal reset (clears prior-run history).
    // The first message after a new run must NOT false-flag a seq gap.
    const isNewRun = state.runId !== null && incomingRunId !== state.runId;

    if (isNewRun) {
      // Reset all history for the new run
      set({
        envStep: payload,
        history: [payload],
        runId: incomingRunId,
        lastSeq: incomingSeq,
        seqGap: false,
      });
      return;
    }

    // Seq gap detection: only flag a gap for forward jumps (seq > lastSeq + 1).
    // Out-of-order / duplicate messages (seq ≤ lastSeq) are silently accepted.
    // First message (lastSeq === null) is never a gap — any seq is valid.
    const isGap = state.lastSeq !== null && incomingSeq > state.lastSeq + 1;

    // Ring buffer: append, then drop oldest if over capacity
    const newHistory = [...state.history, payload];
    if (newHistory.length > HISTORY_MAX_LEN) {
      newHistory.splice(0, newHistory.length - HISTORY_MAX_LEN);
    }

    set({
      envStep: payload,
      history: newHistory,
      runId: incomingRunId,
      lastSeq: incomingSeq,
      seqGap: isGap,
    });
  },

  clearHistory() {
    set({
      envStep: null,
      history: [],
      runId: null,
      lastSeq: null,
      seqGap: false,
      frameErrors: [], // §13.2: reset ring buffer on history clear
    });
  },

  setWsStatus(status: WsStatus) {
    set({ wsStatus: status });
  },

  pushFrameError(err: FrameError) {
    const { frameErrors } = get();
    // Prepend (newest-first); trim to cap
    const next = [err, ...frameErrors];
    if (next.length > FRAME_ERRORS_CAP) {
      next.length = FRAME_ERRORS_CAP;
    }
    set({ frameErrors: next });
  },
}));
