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
| `createRestClient` | `function` | Request timeout in ms. Default: 30_000. Uses Promise.race for fake-timer compat. */ |

### `restClientSingleton.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `restClient` | `const` | — |

### `wsClient.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `WsClientOptions` | `interface` | — |
| `WsClient` | `interface` | — |
| `createWsClient` | `function` | Called when the server sends a kind="status" control frame. */ |

### `wsClientSingleton.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `TELEMETRY_WS_URL` | `const` | wsClientSingleton — two WsClient instances wired to telemetryStore + trainingStore. |
| `TRAINING_WS_URL` | `const` | wsClientSingleton — two WsClient instances wired to telemetryStore + trainingStore. |
| `handleEnvStep` | `function` | wsClientSingleton — two WsClient instances wired to telemetryStore + trainingStore. |
| `handleTrainMetrics` | `function` | wsClientSingleton — two WsClient instances wired to telemetryStore + trainingStore. |
| `handleStatusChange` | `function` | wsClientSingleton — two WsClient instances wired to telemetryStore + trainingStore. |
| `telemetryWsClient` | `const` | wsClientSingleton — two WsClient instances wired to telemetryStore + trainingStore. |
| `trainingWsClient` | `const` | wsClientSingleton — two WsClient instances wired to telemetryStore + trainingStore. |

<!-- generated:end -->
