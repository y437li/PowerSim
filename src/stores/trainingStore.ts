import { create } from "zustand";
import type { TrainMetricsPayload, TelemetryEnvelope } from "../types/telemetry";

export interface TrainingState {
  latest: TrainMetricsPayload | null;
  history: TrainMetricsPayload[];

  receiveTrainMetrics: (msg: TelemetryEnvelope) => void;
  clear: () => void;
}

export const useTrainingStore = create<TrainingState>((set) => ({
  latest: null,
  history: [],

  receiveTrainMetrics(msg: TelemetryEnvelope) {
    const payload = msg.payload as TrainMetricsPayload;
    set((state) => ({
      latest: payload,
      history: [...state.history, payload],
    }));
  },

  clear() {
    set({ latest: null, history: [] });
  },
}));
