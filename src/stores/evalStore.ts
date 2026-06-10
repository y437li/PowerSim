import { create } from "zustand";
import type { EvalComparePayload, TelemetryEnvelope } from "../types/telemetry";

export interface EvalState {
  latest: EvalComparePayload | null;

  receiveEvalCompare: (msg: TelemetryEnvelope) => void;
  clear: () => void;
}

export const useEvalStore = create<EvalState>((set) => ({
  latest: null,

  receiveEvalCompare(msg: TelemetryEnvelope) {
    const payload = msg.payload as EvalComparePayload;
    set({ latest: payload });
  },

  clear() {
    set({ latest: null });
  },
}));
