import { create } from "zustand";
import type { EnvStepPayload, TelemetryEnvelope, WsStatus } from "../types/telemetry";

const HISTORY_MAX_LEN = 168; // D3: max episode length = 168 steps at Δt=1h

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

  // Actions
  receiveEnvStep: (msg: TelemetryEnvelope) => void;
  clearHistory: () => void;
  setWsStatus: (status: WsStatus) => void;
}

export const useTelemetryStore = create<TelemetryState>((set, get) => ({
  envStep: null,
  history: [],
  wsStatus: "disconnected",
  runId: null,
  lastSeq: null,
  seqGap: false,

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
    });
  },

  setWsStatus(status: WsStatus) {
    set({ wsStatus: status });
  },
}));
