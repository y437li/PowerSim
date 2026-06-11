/**
 * wsClientSingleton — two WsClient instances wired to telemetryStore + trainingStore.
 * Contract: contracts/frontend/app_integration.md §2
 *
 * STUB — implementation pending gate approval (PR #45).
 * Exports the correct shape (URL constants, handler fns, two WsClients) so tests compile
 * and fail with assertion errors rather than module-not-found errors.
 */
import type { WsClient } from "./wsClient";
import type { TelemetryEnvelope, WsStatus } from "../types/telemetry";

// URL constants — exported for §T_url tests (stub values fail intentionally)
export const TELEMETRY_WS_URL = "/ws/stub-telemetry";   // impl: /ws/inference
export const TRAINING_WS_URL = "/ws/stub-training";     // impl: /ws/training/stream

// Handler functions — exported for §T_wire tests (stub no-ops fail intentionally)
export function handleEnvStep(_msg: TelemetryEnvelope): void {}
export function handleTrainMetrics(_msg: TelemetryEnvelope): void {}
export function handleStatusChange(_status: WsStatus): void {}

// Clients — connect/disconnect are stubs; app wires them in useEffect
export const telemetryWsClient: WsClient = {
  connect: () => {},
  disconnect: () => {},
};

export const trainingWsClient: WsClient = {
  connect: () => {},
  disconnect: () => {},
};
