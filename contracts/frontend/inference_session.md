# Contract: Inference Session Control

- **Status:** DRAFT
- **Area:** frontend
- **Task:** #27
- **Spec refs:** `contracts/serving/inference_stream.md` (session lifecycle, cmd:start, D24 speed), `contracts/serving/rest_api.md` (GET /runs/latest)
- **Reviewer:** frontend-reviewer (APPROVE gate)
- **Depends on:** `app_integration.md` (wsClient, restClient singletons), `app_shell.md` (WsClient interface), `live_dashboard.md` (telemetryStore)

## Problem

After PR #45 the app connects `/ws/inference` and listens, but never sends `cmd:start`.
The serving session model requires `cmd:start` (with `run_id`, `site_id`, `speed`) on
the same connection before any `env_step` frames flow.  `SiteView` and `LiveDashboard`
therefore show "Waiting for telemetry" permanently.

## Solution (v1)

**Auto-start on `status:ready`** with the latest available checkpoint run, `site_id =
"gansu"`, `speed = 1.0` (D24 default).  A minimal control strip (pause / resume / speed
dial) is rendered in `SiteView` so the operator can throttle or pause.

## Module locations

| Module | Path |
|---|---|
| WsClient extension | `src/clients/wsClient.ts` (existing) |
| RestClient extension | `src/clients/restClient.ts` (existing) |
| Inference session store | `src/stores/inferenceSessionStore.ts` (new) |
| WsClientSingleton wiring | `src/clients/wsClientSingleton.ts` (existing) |
| SessionControlStrip | `src/components/SessionControlStrip.tsx` (new) |
| SiteView | `src/routes/SiteView.tsx` (existing) |

---

## §1 — `WsClient` interface and `WsClientOptions` extensions

### §1.1 `WsClient.send()`

Add to the existing `WsClient` interface:

```typescript
send(msg: unknown): void;
```

Behaviour:
- If the WebSocket is not connected (`ws === null`), **no-op** (do NOT throw, queue, or
  log a warning — dropping is intentional; caller should wait for `status:ready`).
- When connected: `ws.send(JSON.stringify(msg))`.
- Callers never pass a pre-serialized string; the implementation always serializes.

### §1.2 `WsClientOptions` new callbacks

Add two **optional** callbacks to `WsClientOptions`:

```typescript
/** Called when the server sends a `{"kind":"status", ...}` control frame. */
onServerStatus?: (frame: ServerStatusFrame) => void;

/** Called when the server sends a `{"kind":"error", ...}` control frame. */
onServerError?: (frame: ServerErrorFrame) => void;
```

Both default to a no-op if omitted (backward-compatible — existing callers need no change).

### §1.3 Message routing in `handleMessage`

Extend the `switch (envelope.kind)` dispatch (already in `wsClient.ts`) to add:

```
case "status":  onServerStatus?.(frame as ServerStatusFrame);  break;
case "error":   onServerError?.(frame as ServerErrorFrame);    break;
```

`status` and `error` frames do NOT carry a `payload` wrapper — they are top-level objects.
The payload-guard relaxation MUST be kind-specific: only `"status"` and `"error"` bypass
the `payload === undefined` check.  `"env_step"`, `"train_metrics"`, and `"eval_compare"`
frames MUST still require `payload` — that guard is load-bearing per D18 (a malformed
`env_step` with no payload reaching `telemetryStore` would crash the dashboard).

Implementation note: do NOT remove the guard globally before the switch.  Instead, after
parsing the JSON and extracting `kind`, branch on whether `kind` is a control frame
(`"status"` | `"error"`) or a data frame, and apply the payload guard only to data frames.

### §1.4 `ServerStatusFrame` and `ServerErrorFrame` types

Add to `src/types/telemetry.ts`:

```typescript
export interface ServerStatusFrame {
  kind: "status";
  state: "ready" | "running" | "paused" | "stopped";
  session_id: string | null;
  step: number;
  episode: number;
  run_id: string | null;
  site_id: string | null;
  message?: string;
}

export interface ServerErrorFrame {
  kind: "error";
  code:
    | "run_not_found"
    | "site_not_found"
    | "policy_not_found"
    | "already_running"
    | "no_session"
    | "bad_state"
    | "bad_command"
    | "invalid_message"
    | "internal";
  message: string;
}
```

---

## §2 — `RestClient` extension: `getLatestRun()`

Add to the `RestClient` interface and implementation:

```typescript
/** GET /runs/latest — returns the run with the most recent created_at. */
getLatestRun(): Promise<RunInfo>;
```

- On HTTP 404 (`{"error": "no runs found"}`): throw `Error("no_runs_found")`.
- On other 4xx/5xx: propagate the existing error shape.
- Response shape is identical to `GET /runs/{run_id}` (see `rest_api.md`).
- The existing `RunInfo` type is sufficient; no new type needed.

---

## §3 — `inferenceSessionStore`

A Zustand store for inference session state.  Lives in
`src/stores/inferenceSessionStore.ts`.

### §3.1 State shape

```typescript
type InferenceServerState = "idle" | "ready" | "running" | "paused" | "stopped" | "error";

interface InferenceSessionState {
  /** Server-reported session state (from status frames).  "idle" = no status yet. */
  serverState: InferenceServerState;
  /** Active run ID from the server status frame, or null. */
  runId: string | null;
  /** Active site ID from the server status frame, or null. */
  siteId: string | null;
  /** Session UUID from the server (null before first start). */
  sessionId: string | null;
  /** Last completed step number (from status frame). */
  step: number;
  /** Current episode number (from status frame). */
  episode: number;
  /** Replay speed sent with cmd:start.  Default: 1.0 (D24). Range [0, 100]. */
  speed: number;
  /** Human-readable error description, or null. */
  errorMsg: string | null;
}
```

### §3.2 Initial state

```typescript
{
  serverState: "idle",
  runId: null,
  siteId: null,
  sessionId: null,
  step: 0,
  episode: 0,
  speed: 1.0,
  errorMsg: null,
}
```

### §3.3 `handleServerStatus(frame: ServerStatusFrame)`

Updates state from a server status frame.

| `frame.state` | store update |
|---|---|
| `"ready"` | `serverState="ready"`, then trigger `_autoStart()` |
| `"running"` | if `frame.session_id !== current sessionId`: call `telemetryStore.clearHistory()` first; then `serverState="running"`, update `runId`, `siteId`, `sessionId`, `step`, `episode` |
| `"paused"` | `serverState="paused"`, update `step`, `episode` |
| `"stopped"` | `serverState="stopped"` |

**Session-ID change → history clear:** The serving layer assigns a fresh `session_id`
UUID per `cmd:start` specifically to prevent history mixing
(`inference_stream.md:180–182`).  `_autoStart()` fires on every `"ready"` frame —
including reconnects — and always picks the latest run, so the same `run_id` can be
restarted with a new `session_id`.  Without clearing, new-session step-0 frames append
to the old session's ring buffer and the timeline jumps back, mixing two sessions.
Fix: when `frame.session_id` differs from the currently stored `sessionId`, call
`useTelemetryStore.getState().clearHistory()` before updating the store.

`_autoStart()` is called ONLY when transitioning to `"ready"` (i.e. a reconnect sends a
new `"ready"` frame → auto-start fires again with the then-current latest run).

### §3.4 `_autoStart()` — internal async action

```typescript
async function _autoStart(): Promise<void> {
  // 1. Fetch the latest run from GET /runs/latest via restClient singleton
  // 2. If fetch throws "no_runs_found": set errorMsg, serverState="error"; return
  // 3. If fetch throws any other error: set errorMsg, serverState="error"; return
  // 4. If run.has_policy === false: still send cmd:start (server replies policy_not_found)
  // 5. Call startSession(run.id, "gansu")
}
```

The restClient singleton used here is the singleton exported from
`src/clients/restClientSingleton.ts` (a new module created in this task — see §5).

### §3.5 `startSession(runId: string, siteId: string)`

```typescript
function startSession(runId: string, siteId: string): void {
  telemetryWsClient.send({
    cmd: "start",
    run_id: runId,
    site_id: siteId,
    speed: get().speed,
  });
}
```

`telemetryWsClient` is the singleton exported from `wsClientSingleton.ts`.

### §3.6 `pause()`, `resume()`

```typescript
function pause(): void  { telemetryWsClient.send({ cmd: "pause" }); }
function resume(): void { telemetryWsClient.send({ cmd: "resume" }); }
```

Only valid when `serverState` is the expected state; if called in the wrong state, the
server will send a `no_session`/`bad_state` error frame which sets `errorMsg`.

### §3.7 `setSpeed(speed: number)`

```typescript
function setSpeed(speed: number): void {
  set({ speed: Math.max(0, Math.min(100, speed)) });
}
```

Speed is clamped to [0, 100] per D24.  Takes effect on the next `startSession()` call;
there is no live speed-change command in v1 (in-session speed change is out of scope).

### §3.8 `handleServerError(frame: ServerErrorFrame)`

```typescript
function handleServerError(frame: ServerErrorFrame): void {
  set({ errorMsg: `${frame.code}: ${frame.message}`, serverState: "error" });
}
```

`policy_not_found` is the expected error when auto-start fires for a run with no policy
yet (training not yet complete) — the `errorMsg` displayed is:
`"policy_not_found: ..."`.  The UI shows a user-friendly message for this case.

---

## §4 — `wsClientSingleton.ts` wiring

The existing `telemetryWsClient` in `wsClientSingleton.ts` gains two new handlers:

```typescript
onServerStatus: (frame) => inferenceSessionStore.getState().handleServerStatus(frame),
onServerError:  (frame) => inferenceSessionStore.getState().handleServerError(frame),
```

These are added to the `createWsClient` call for `telemetryWsClient` only.
`trainingWsClient` does NOT get these handlers (the training WS never sends status/error
frames of the inference session type).

---

## §5 — `restClientSingleton.ts`

A new singleton module `src/clients/restClientSingleton.ts`:

```typescript
import { createRestClient } from "./restClient";
export const restClient = createRestClient({ baseUrl: "/api" });
```

`inferenceSessionStore` imports `restClient` from here.
`TrainingPanel` (which uses REST calls) is a future consumer; for now this singleton
establishes the shared instance.

---

## §6 — `SessionControlStrip` component

File: `src/components/SessionControlStrip.tsx`

```tsx
<div data-testid="session-control-strip" className="session-control-strip">
  {/* state-dependent content — see §6.1–§6.4 */}
</div>
```

### §6.1 Idle / connecting state (`serverState === "idle"`)

```tsx
<span data-testid="session-status-label">Connecting…</span>
```

### §6.2 Ready state (`serverState === "ready"`)

```tsx
<span data-testid="session-status-label">Starting session…</span>
```

(Auto-start is in-flight.)

### §6.3 Running state (`serverState === "running"`)

```tsx
<span data-testid="session-status-label">Running — step {step} ep {episode}</span>
<button data-testid="session-pause-btn" onClick={pause}>Pause</button>
<select data-testid="session-speed-select" value={speed} onChange={...}>
  <option value={0}>Max speed</option>
  <option value={0.5}>0.5×</option>
  <option value={1}>1× (real-time)</option>
  <option value={2}>2×</option>
  <option value={5}>5×</option>
</select>
```

### §6.4 Paused state (`serverState === "paused"`)

```tsx
<span data-testid="session-status-label">Paused — step {step} ep {episode}</span>
<button data-testid="session-resume-btn" onClick={resume}>Resume</button>
```

### §6.5 Error state (`serverState === "error"`)

```tsx
<span data-testid="session-status-label" className="session-status--error">
  {errorMsg}
</span>
<button data-testid="session-retry-btn" onClick={_retry}>Retry</button>
```

`_retry` sets `serverState="idle"` and `errorMsg=null`, then calls `_autoStart()`
directly. (The user can retry without reconnecting.)

### §6.6 Stopped state (`serverState === "stopped"`)

```tsx
<span data-testid="session-status-label">Session stopped</span>
```

---

## §7 — `SiteView` update

Add `<SessionControlStrip />` inside `<div data-testid="site-view">`:

```tsx
<div data-testid="site-view" className="route-site-view">
  <SceneMountPoint onReady={setContainerEl} />
  <SiteScene ... />
  <SessionControlStrip />
  <LiveDashboard />
</div>
```

---

## Acceptance criteria

| ID | Description |
|---|---|
| §IS1 | `createWsClient` returns an object with `connect`, `disconnect`, AND `send` |
| §IS2 | `send()` is a no-op when the WebSocket is not open (no throw, no error log) |
| §IS3 | `send()` calls `ws.send(JSON.stringify(msg))` when connected |
| §IS4 | `handleMessage` dispatches `kind="status"` to `onServerStatus` callback |
| §IS5 | `handleMessage` dispatches `kind="error"` to `onServerError` callback |
| §IS6 | `restClient.getLatestRun()` calls `GET /api/runs/latest` |
| §IS7 | `getLatestRun()` throws `Error("no_runs_found")` on HTTP 404 |
| §IS8 | `inferenceSessionStore` initial state: `serverState="idle"`, `speed=1.0`, others null/0 |
| §IS9 | `handleServerStatus({state:"ready"})` → triggers `_autoStart()` (mocked) |
| §IS10 | `_autoStart()` success path: fetches latest run → sends `cmd:start` via `telemetryWsClient` with `run_id`, `site_id="gansu"`, `speed` from store |
| §IS11 | `_autoStart()` with `no_runs_found` → `serverState="error"`, `errorMsg` set |
| §IS12 | `_autoStart()` with other REST error → `serverState="error"`, `errorMsg` set |
| §IS13 | `handleServerStatus({state:"running"})` → `serverState="running"`, step/episode updated |
| §IS13b | `handleServerStatus(running, new session_id)` → `telemetryStore.clearHistory()` called before state update |
| §IS13c | `handleServerStatus(running, same session_id)` → `clearHistory()` NOT called |
| §IS14 | `handleServerStatus({state:"paused"})` → `serverState="paused"` |
| §IS15 | `inferenceSessionStore.pause()` → sends `{cmd:"pause"}` via `telemetryWsClient` |
| §IS16 | `inferenceSessionStore.resume()` → sends `{cmd:"resume"}` via `telemetryWsClient` |
| §IS17 | `setSpeed(150)` → clamped to 100; `setSpeed(-5)` → clamped to 0 |
| §IS18 | `handleServerError({code:"policy_not_found",...})` → `serverState="error"`, `errorMsg` contains "policy_not_found" |
| §IS19 | `SessionControlStrip` renders `data-testid="session-pause-btn"` when running |
| §IS20 | `SessionControlStrip` renders `data-testid="session-resume-btn"` when paused |
| §IS21 | `SessionControlStrip` renders `data-testid="session-retry-btn"` with `errorMsg` when error |
| §IS22 | `SessionControlStrip` renders `data-testid="session-status-label"` in all states |
| §IS23 | Clicking pause button calls `inferenceSessionStore.getState().pause()` |
| §IS24 | Clicking resume button calls `inferenceSessionStore.getState().resume()` |
| §IS25 | `SiteView` renders an element with `data-testid="session-control-strip"` |

## Out of scope (v1)

- In-session speed change (live speed dial that takes effect without stopping): requires
  a `cmd:speed` or re-start; deferred to v2.
- Manual run selection UI: auto-start always picks the latest run.
- `cmd:stop` UI: user closes the browser tab; server closes on WS disconnect.
- `cmd:step` (single-step debug): harness concern, not live-view.
- Multi-site switching in live view.
- `seed` field on `cmd:start`: `inference_stream.md` documents an optional `seed`
  (default 0) for reproducible trajectories.  v1 omits it — the server uses seed=0,
  which is correct for the live-view use case.
