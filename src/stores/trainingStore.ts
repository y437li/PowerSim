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

  receiveTrainMetrics: (msg: TelemetryEnvelope) => void;
  clear: () => void;
}

export const useTrainingStore = create<TrainingState>((set) => ({
  latest: null,
  history: [],
  lastTrainSeq: null,
  trainSeqGap: false,

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
      };
    });
  },

  clear() {
    set({ latest: null, history: [], lastTrainSeq: null, trainSeqGap: false });
  },
}));
