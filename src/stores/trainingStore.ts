import { create } from "zustand";
import type { TrainMetricsPayload, TelemetryEnvelope } from "../types/telemetry";

export interface TrainingState {
  latest: TrainMetricsPayload | null;
  history: TrainMetricsPayload[];
  /** seq from last received train_metrics envelope (null before first message). */
  lastTrainSeq: number | null;
  /**
   * true when the CURRENT message has a forward sequence gap:
   * msg.seq > lastTrainSeq + 1. Resets to false on the next contiguous message.
   * Out-of-order / duplicate messages are silently accepted (gap=false).
   * Reset on clear(). Non-sticky — mirrors telemetryStore.seqGap semantics.
   */
  trainSeqGap: boolean;
  /**
   * ISO-8601 UTC timestamp from the envelope of the most recent train_metrics
   * message (msg.ts_utc). Used by TrainingPanel's StreamStatusBanner to detect
   * data-stale scenarios (no message received in >30 s while WS is connected).
   * Updated each message; null on clear(). Optional so test mocks that omit it
   * receive null via ?? null — no test-breakage from emptyTrainingState().
   */
  latestTsUtc?: string | null;

  receiveTrainMetrics: (msg: TelemetryEnvelope) => void;
  clear: () => void;
}

export const useTrainingStore = create<TrainingState>((set) => ({
  latest: null,
  history: [],
  lastTrainSeq: null,
  trainSeqGap: false,
  latestTsUtc: null,

  receiveTrainMetrics(msg: TelemetryEnvelope) {
    const payload = msg.payload as TrainMetricsPayload;
    const incomingSeq = msg.seq;
    set((state) => {
      const gap =
        state.lastTrainSeq !== null && incomingSeq > state.lastTrainSeq + 1;
      return {
        latest: payload,
        history: [...state.history, payload],
        lastTrainSeq: incomingSeq,
        trainSeqGap: gap,
        latestTsUtc: msg.ts_utc,
      };
    });
  },

  clear() {
    set({
      latest: null,
      history: [],
      lastTrainSeq: null,
      trainSeqGap: false,
      latestTsUtc: null,
    });
  },
}));
