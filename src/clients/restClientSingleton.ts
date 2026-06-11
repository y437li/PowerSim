/**
 * restClientSingleton — shared REST client for the Energy GO serving API.
 * Contract: contracts/frontend/inference_session.md §5
 *
 * Stub — implementation pending contract approval.
 */
import { createRestClient } from "./restClient";
export const restClient = createRestClient({ baseUrl: "/api" });
