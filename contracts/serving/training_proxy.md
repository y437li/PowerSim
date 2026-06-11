# Contract: Training Control Proxy

- **Status:** DRAFT
- **Area:** serving (frontend consumes the training stream — both reviewers advisory; rl-architect locks before implementation)
- **Spec:** REBUILD_SPEC.md §5–§7; LOCKED `contracts/shared/telemetry_schema.md` v1.0.0 (D18)
- **Depends on:** D18 (telemetry schema lock), `rest_api.md`, harness contract (TBD — start/pause/stop parameter shapes will be refined when `contracts/harness/training_control.md` lands)
- **Reviewer:** backend-reviewer (APPROVE gate); frontend-reviewer advisory (training panel UI consumes the stream)
- **Units:** all costs in **¥**, rewards dimensionless (×1e-5 scale), steps integers.

## Purpose

A thin proxy layer that:
1. Relays control commands (`start`, `stop`, `pause`, `resume`) to the env harness.
2. Streams `train_metrics` telemetry from the harness to the dashboard WebSocket clients.
3. Exposes the current training status and run history via REST.

The serving layer adds NO training logic — it is a pass-through.  The harness is the
source of truth for run state; the serving layer caches the latest status for REST
clients.

Module location: `src/energy_go/serving/training_proxy.py`
Registered on: `app` from `energy_go.serving.app`.

## REST endpoints

### `GET /training/status`

```json
{
  "state": "idle" | "running" | "paused" | "stopped",
  "run_id": "run_001" | null,
  "step": 42,
  "episode": 3,
  "last_updated_utc": "2026-06-10T08:00:00Z"
}
```

- `state` — current harness state (cached; updated when harness events arrive).
- `run_id` — null when state is `idle`.
- `step` — global training step count; 0 when `idle`.
- Always returns 200.

### `POST /training/start`

Request body:

```json
{
  "run_id": "run_001",
  "site_id": "gansu",
  "seed": 42,
  "hyperparams": {
    "lr": 1e-4,
    "gamma": 0.999,
    "batch_size": 512,
    "total_steps": 500000
  }
}
```

- `run_id` — a new run ID (must not already exist under `checkpoints/`); error if it does.
- `site_id` — must match a `config/site_{site_id}.yaml`; 422 if absent.
- `seed` — optional (default: 0).
- `hyperparams` — optional; serving layer passes these verbatim to the harness.
  Missing keys use harness defaults.  Unknown keys are passed through (forward-compat).
- Returns 200 `{"run_id": "run_001", "state": "running"}` on success.
- Returns 409 if a run is already active (`state` = running or paused).
- Returns 422 for validation errors.

### `POST /training/stop`

No body required.  Stops the active run and returns:

```json
{"run_id": "run_001", "state": "stopped", "final_step": 12345}
```

- Returns 409 if no run is active.

### `POST /training/pause`

```json
{"run_id": "run_001", "state": "paused", "step": 12345}
```

- Returns 409 if not running (idle, paused, or stopped).

### `POST /training/resume`

```json
{"run_id": "run_001", "state": "running", "step": 12345}
```

- Returns 409 if not paused.

## WebSocket stream

### `WS /ws/training/stream`

Streams `train_metrics` telemetry from the active training run.

**Session lifecycle:**

```
Client                       Server
  |                            |
  |--- connect ---------------→|  → sends current status frame immediately
  |←-- {"kind":"status", ...} -|
  |                            |
  |        ... (harness training runs) ...
  |←-- train_metrics frame --- |  (once per logged step)
  |←-- train_metrics frame --- |
  |           ...              |
  |--- {"cmd":"stop_stream"} →-|  → server closes WS (does NOT stop training)
  |←-- [server closes] -------|
```

Multiple clients may subscribe.  Each receives all frames emitted after their
connection time; no replay of prior frames.

**Server → client frames:**

All frames are JSON text.

#### `train_metrics` (data frames)

Each logged training step produces exactly one frame.  The message conforms to
LOCKED `contracts/shared/telemetry_schema.json` v1.0.0, `kind = "train_metrics"`.

```json
{
  "schema_version": "1.0.0",
  "kind": "train_metrics",
  "ts_utc": "<wall-clock ISO 8601 UTC>",
  "run_id": "run_001",
  "seq": 0,
  "payload": {
    "step": 1000,
    "episode": 10,
    "mean_reward": -0.52,
    "eval_reward": null,
    "actor_loss": 0.31,
    "critic_loss": 0.55,
    "entropy_coef": 0.12,
    "mean_episode_length": 168.0
  }
}
```

The serving layer MUST call `energy_go.telemetry.validate(msg)` on every frame before
sending and MUST assert `== []` (D18 producer obligation).

#### `status` frames

```json
{
  "kind": "status",
  "state": "idle" | "running" | "paused" | "stopped",
  "run_id": "run_001" | null,
  "step": 42,
  "episode": 3
}
```

Sent on: connection open (current state), state transitions (start/pause/resume/stop).

#### `error` frames

```json
{
  "kind": "error",
  "code": "harness_unavailable" | "internal",
  "message": "<human-readable description>"
}
```

After `"harness_unavailable"` or `"internal"`, the server closes the WebSocket.

**Client → server:**

Only one command is accepted:

```json
{"cmd": "stop_stream"}
```

Closes the WS connection.  Does NOT stop the training run (to stop training, use
`POST /training/stop`).

## Error response schema (REST)

Same as `rest_api.md`: `{"error": str, "detail": str|null}`.

- 200 — OK
- 409 — state conflict (run already active / not active)
- 422 — validation error (missing site, run_id already exists, etc.)
- 503 — harness is not reachable (training subsystem not running)

## Harness interface dependency

The serving layer communicates with the harness via an in-process interface
(function calls) or an IPC channel (TCP/socket) — the exact binding is deferred
to `contracts/harness/training_control.md`.  Serving-layer tests use a mock/stub
harness that implements:

```python
class HarnessInterface(Protocol):
    def start(self, run_id: str, site_id: str, seed: int, hyperparams: dict) -> None: ...
    def stop(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def get_status(self) -> dict: ...  # {"state": str, "run_id": str|None, "step": int, "episode": int}
    def subscribe(self, callback: Callable[[dict], None]) -> None: ...  # train_metrics frames
    def unsubscribe(self, callback) -> None: ...
```

The mock returns pre-canned `train_metrics` frames from a fixture file; tests
do not require a live harness process.

## Out of scope

- REST endpoints for hyperparameter sweeps (separate contract, if needed).
- Eval-loop triggering via the serving layer (eval is triggered by the harness).
- Any UI for reviewing LLM-generated analysis.

## Dependencies

- `fastapi>=0.110`, `websockets>=12` (from `serving` extras).
- `energy_go.telemetry.validate` (task #23).
- `contracts/harness/training_control.md` (TBD — harness-engineer; parameter
  shapes for `POST /training/start` will be aligned when that contract lands).
