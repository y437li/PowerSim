/**
 * Telemetry Zustand store — live env_step state.
 * Contract: contracts/frontend/app_shell.md §6.1
 *
 * This store is the single source of truth for live telemetry.
 * The 3D scene (and dashboard) subscribe here; they NEVER open their own socket.
 *
 * In test environments this module is mocked via vi.mock in each test file:
 *   vi.mock("../../src/stores/telemetryStore", () => ({
 *     useTelemetryStore: vi.fn(...),
 *   }));
 */

import { create } from "zustand";
import type { EnvStepPayload, WsStatus } from "../types/telemetry";

interface TelemetryState {
  // Connection meta
  wsStatus: WsStatus;
  runId: string | null;
  lastSeq: number | null;
  seqGap: boolean;

  // Latest env_step (null until first message)
  envStep: EnvStepPayload | null;

  // History ring buffer: last N steps for timeline charts
  history: EnvStepPayload[];
  historyMaxLen: number;         // default 168 (one training episode, D3)

  // Actions
  receiveEnvStep(payload: EnvStepPayload, runId: string, seq: number): void;
  setWsStatus(status: WsStatus): void;
  clearHistory(): void;
}

export const useTelemetryStore = create<TelemetryState>((set, get) => ({
  wsStatus: "connecting",
  runId: null,
  lastSeq: null,
  seqGap: false,
  envStep: null,
  history: [],
  historyMaxLen: 168,

  receiveEnvStep(payload, runId, seq) {
    const state = get();

    // run_id change → reset before appending (§6.1 store-internal)
    const resetNeeded = state.runId !== null && state.runId !== runId;

    const prevSeq = resetNeeded ? null : state.lastSeq;
    const seqGap = prevSeq !== null && seq > prevSeq + 1;

    const newHistory = resetNeeded
      ? [payload]
      : [...state.history.slice(-(state.historyMaxLen - 1)), payload];

    set({
      runId,
      lastSeq: seq,
      seqGap,
      envStep: payload,
      history: newHistory,
    });
  },

  setWsStatus(status) {
    set({ wsStatus: status });
  },

  clearHistory() {
    set({ history: [], envStep: null, lastSeq: null, seqGap: false });
  },
}));
