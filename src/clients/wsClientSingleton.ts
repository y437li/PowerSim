/**
 * wsClientSingleton — app-level WsClient wired to telemetryStore + trainingStore.
 * Contract: contracts/frontend/app_integration.md §2
 *
 * STUB — implementation pending gate approval (PR #45).
 * Exports the correct WsClient shape so module resolution succeeds in tests.
 */
import type { WsClient } from "./wsClient";

export const wsClientSingleton: WsClient = {
  connect: () => {},
  disconnect: () => {},
};
