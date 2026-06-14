# `src/clients`

<!-- curated -->
## Purpose

WebSocket and REST transport clients. This folder owns all network I/O; it holds no UI state (that belongs to `stores/`) and renders nothing.

`wsClient.ts` defines `createWsClient`: validates every incoming message through `validators/telemetryValidator` before dispatching it, and tracks connection status as `connecting / connected / disconnected / stale`. `wsClientSingleton.ts` exports the two live instances — `telemetryWsClient` (wired to `telemetryStore`) and `trainingWsClient` (wired to `trainingStore`). `restClient.ts` defines `createRestClient` with a configurable timeout (default 30 000 ms) and exposes `getRuns`, `getLatestRun`, and `getSiteConfig`; `restClientSingleton.ts` exports the shared `restClient` instance.

The singleton files are the only place that wire transport clients to stores — components and utilities must not instantiate new clients directly.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `restClient.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `RestClientOptions` | `interface` | — |
| `RestClient` | `interface` | — |
| `createRestClient` | `function` | Factory that creates a typed REST client for the Energy GO serving API. |

### `restClientSingleton.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `restClient` | `const` | — |

### `wsClient.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `WsClientOptions` | `interface` | — |
| `WsClient` | `interface` | — |
| `createWsClient` | `function` | Factory that creates a managed WebSocket client with: |

### `wsClientSingleton.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `TELEMETRY_WS_URL` | `const` | WS endpoint for env_step + status (contracts/serving/inference_stream.md:24) |
| `TRAINING_WS_URL` | `const` | WS endpoint for train_metrics (contracts/serving/training_proxy.md:98) |
| `handleEnvStep` | `function` | Routes env_step envelopes to telemetryStore.receiveEnvStep. |
| `handleTrainMetrics` | `function` | Routes train_metrics envelopes to trainingStore.receiveTrainMetrics. |
| `handleStatusChange` | `function` | Routes WS status changes to telemetryStore.setWsStatus. |
| `telemetryWsClient` | `const` | Telemetry client — connects to /ws/inference. |
| `trainingWsClient` | `const` | Training client — connects to /ws/training/stream. |

<!-- generated:end -->
