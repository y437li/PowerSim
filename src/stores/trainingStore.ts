import { create } from "zustand";
import type { TrainMetricsPayload, TelemetryEnvelope } from "../types/telemetry";

export interface TrainingState {
  latest: TrainMetricsPayload | null;
  history: TrainMetricsPayload[];
  /** seq from last received train_metrics envelope (null before first message). */
  lastTrainSeq: number | null;
  /**
   * true when a forward sequence gap was detected in the train_metrics stream:
   * msg.seq > lastTrainSeq + 1. Out-of-order / duplicate messages are silently
   * accepted (gap flag stays unchanged). Reset on clear().
   * Mirrors telemetryStore.seqGap semantics for env_step.
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
        trainSeqGap: state.trainSeqGap || gap,
      };
    });
  },

  clear() {
    set({ latest: null, history: [], lastTrainSeq: null, trainSeqGap: false });
  },
}));
