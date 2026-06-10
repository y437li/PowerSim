# Contract: Live Inference WebSocket Stream

- **Status:** DRAFT
- **Area:** serving (frontend consumes — both reviewers advisory; rl-architect locks before implementation)
- **Spec:** REBUILD_SPEC.md §6–§7; LOCKED `contracts/shared/telemetry_schema.md` v1.0.0 (D18)
- **Depends on:** D13 (cost identities), D18 (telemetry schema lock), `rest_api.md`
- **Reviewer:** backend-reviewer (APPROVE gate); frontend-reviewer advisory (this is
  the wire format the 3D scene and dashboard consume)
- **Units:** all power in **MW**, energy in **MWh**, prices in **¥/MWh**, costs in **¥**.
  Telemetry messages follow LOCKED schema units exactly — no remapping at the serving layer.

## Purpose

A WebSocket endpoint that loads a trained policy, drives the Energy GO env step-by-step,
and streams per-step telemetry to the browser (3D scene + dashboard).  The serving layer
is a thin driver — no physics or training logic here.

Module location: `src/energy_go/serving/inference_stream.py`
Registered on: `app` from `energy_go.serving.app`.

## Endpoint

```
WS /ws/inference
```

## Session lifecycle

```
Client                          Server
  |                               |
  |--- connect (WS handshake) --->|
  |                               |  → loads policy if not loaded; sends READY status
  |<--- {"kind":"status","state":"ready", ...} ---|
  |                               |
  |--- {"cmd":"start", "run_id":…, "site_id":…} -->|
  |                               |  → resets env, starts stepping
  |<--- env_step msg (step 0) ---|
  |<--- env_step msg (step 1) ---|
  |        ...                    |
  |--- {"cmd":"pause"} -------->  |  → stops stepping; keeps env state
  |<--- {"kind":"status","state":"paused",...} ---|
  |--- {"cmd":"resume"} ------->  |  → resumes stepping
  |--- {"cmd":"stop"} --------->  |  → server resets, sends stopped, closes connection
  |<--- {"kind":"status","state":"stopped",...} ---|
  |<-- [server closes WS] --------|
```

Multiple clients may connect concurrently.  Each connection gets its own independent
env instance and policy session.  The server never broadcasts to all clients.

## Client → server command messages

All commands are JSON text frames.

### `start`
```json
{
  "cmd": "start",
  "run_id": "run_001",
  "site_id": "gansu",
  "seed": 42
}
```
- `run_id` — must match a run under `checkpoints/`; 404-like error if absent.
- `site_id` — must match a `config/site_{site_id}.yaml`; error if absent.
- `seed` — optional (default: 0).  Passed to the env reset for reproducible trajectories.
- If a session is already running (`start` while state = running or paused): server sends
  an error frame (see below) and continues the current session (no implicit stop).

### `pause`
```json
{"cmd": "pause"}
```
- Halts stepping; keeps env state for resume.
- If no session is active: server sends an error frame with `code: "no_session"`.
- Ignored (no error) if already paused.

### `resume`
```json
{"cmd": "resume"}
```
- Resumes stepping from where it paused.
- If no session is active: server sends an error frame with `code: "no_session"`.
- Ignored (no error) if already running.

### `step`
```json
{"cmd": "step"}
```
- Advances exactly **one** env step and emits one `env_step` frame, then returns to
  `paused` state.  Only valid while paused.
- If not paused (state = running, ready, or stopped): server sends `code: "bad_state"`.
- If no session is active: server sends `code: "no_session"`.

### `stop`
```json
{"cmd": "stop"}
```
- Stops the session, sends a `stopped` status frame, then closes the WebSocket.
- Idempotent — safe to send if no session is active (server closes immediately).

## Server → client message frames

All frames are JSON text.

### `env_step` (data frames)

Each step in the episode produces exactly one `env_step` frame.  The message conforms
exactly to the LOCKED `contracts/shared/telemetry_schema.json` v1.0.0.

```json
{
  "schema_version": "1.0.0",
  "kind": "env_step",
  "ts_utc": "<wall-clock ISO 8601 UTC>",
  "run_id": "<run_id from start command>",
  "seq": 0,
  "payload": {
    "step": 0,
    "episode": 0,
    "dt_hours": 1.0,
    "sim_time_utc": "...",
    "hour_of_day": 0,
    "minute_of_hour": 0,
    "wind_speed_mps": ...,
    "irradiance_wm2": ...,
    "temperature_c": ...,
    "load_mw": ...,
    "price_buy_yuan_per_mwh": ...,
    "price_sell_yuan_per_mwh": ...,
    "tariff_tier": "valley",
    "battery": {...},
    "generation": {...},
    "flows": {...},
    "pcc": {...},
    "costs": {...},
    "cost_cum": {...},
    "month_peak_mw": ...,
    "reward": ...
  }
}
```

- `seq` — strictly monotonic per connection, starting at 0; increments by 1 per step.
- The serving layer MUST call `energy_go.telemetry.validate(msg)` on every frame before
  sending, and MUST assert `== []` (zero validation errors).  A non-empty error list is
  a bug in the serving layer — the test suite pins this (D18 producer obligation).
- `episode` increments when the env resets at the episode boundary (168 steps per D3).
  The stream is continuous across episodes until `stop` is received.

### `status` (control frames)

```json
{
  "kind": "status",
  "state": "ready" | "running" | "paused" | "stopped",
  "session_id": "550e8400-e29b-41d4-a716-446655440000" | null,
  "step": 42,
  "episode": 1,
  "run_id": "run_001" | null,
  "site_id": "gansu" | null,
  "message": "optional human-readable string"
}
```

- `step` and `episode` — last completed step and current episode.  Both 0 at `ready`/`stopped`.
- `run_id` — null at `ready` and `stopped` (no session active).
- `site_id` — the active site ID from the `start` command; null if no session is active.
  Allows the client to verify it is looking at the expected site.
- `session_id` — a fresh UUID v4 assigned at each `start` command.  Null before first
  `start` and after `stop`.  Enables the client to distinguish a new session from a
  resumed one when the same `run_id` is restarted (prevents history mixing).
- Sent on: connection open (state=ready), after start (state=running), after pause
  (state=paused), after resume (state=running), after stop (state=stopped).

### `error` (error frames)

```json
{
  "kind": "error",
  "code": "run_not_found" | "site_not_found" | "policy_not_found" | "already_running"
        | "no_session" | "bad_state" | "bad_command" | "invalid_message" | "internal",
  "message": "<human-readable description>"
}
```

Error code semantics:

| code | trigger | closes WS? |
|---|---|---|
| `run_not_found` | `start` with unknown `run_id` | no |
| `site_not_found` | `start` with unknown `site_id` | no |
| `policy_not_found` | `start` but no `policy.npz`/`.onnx` in run dir | no |
| `already_running` | `start` while session is already running or paused | no |
| `no_session` | `pause`/`resume`/`step` with no active session | no |
| `bad_state` | `step` when not paused, or other state-inappropriate command | no |
| `bad_command` | message is valid JSON but `cmd` is unrecognised | no |
| `invalid_message` | message is not valid JSON or missing required fields | no |
| `internal` | unexpected server error | **yes** (code 1011) |

After `code` = `"internal"`, the server closes the WebSocket with code 1011 (internal
error).  All other error codes leave the connection open; the client may retry.

## Normalization

The serving layer applies the same observation normalization as training:
```
obs_norm = (obs_raw - obs_mean) / max(obs_std, 1e-8)
```
where `obs_mean` and `obs_std` are loaded from `checkpoints/{run_id}/normalization.npz`
at session start.  If `normalization.npz` is absent, the layer uses identity
normalization (`obs_mean=0`, `obs_std=1`) and logs a warning.

The telemetry stream carries **raw (un-normalized) values** — the normalization is
only applied internally when calling the policy.

## Policy loading

Policy weights are loaded from `checkpoints/{run_id}/policy.npz` on first `start` for a
given `run_id`.  Weights are cached in memory for the duration of the server process
(re-loading on subsequent `start` commands for the same `run_id` is a no-op).

Policy file format (`policy.npz`): a NumPy archive with keys `"w_0"`, `"b_0"`,
`"w_1"`, `"b_1"`, ..., `"w_N"`, `"b_N"` for an N-layer MLP (layer 0 = first hidden).
Activation: tanh for hidden layers, identity for output (raw action logits).  Action is
clipped to [−1, 1] before passing to the env.

If ONNX export is available (`policy.onnx`), it is preferred over `policy.npz`
(identical numerical output within float32 tolerance; ONNX runtime = faster inference).
The contract does not prescribe which backend is used — the test suite only checks
that the served action matches a reference forward pass within 1e-5 tolerance.

## Public policy utilities

The `inference_stream` module exposes one public utility function for use by tests and
other consumers that need the forward-pass logic without a live WebSocket session:

```python
def policy_forward(weights: dict[str, np.ndarray], obs: np.ndarray) -> np.ndarray:
    """Run the MLP forward pass.

    Args:
        weights: dict loaded from policy.npz — keys "w_0", "b_0", ..., "w_N", "b_N"
                 (N = number of layers; layer 0 = first hidden, layer N-1 = output).
        obs:     float32 array of shape (obs_dim,), already normalized.

    Returns:
        float32 array of shape (action_dim,) clipped to [−1, 1].

    Activation: tanh for hidden layers (indices 0 … N-2); identity for the output
    layer (index N-1).  Output clipped to [−1, 1] before returning.
    """
```

This function is the single source of truth for the forward-pass logic; the WebSocket
handler and tests both call it.  The test suite imports it directly to verify the
reference identity:
```
served = policy_forward(weights, obs)
np.testing.assert_allclose(served, reference_forward(weights, obs), atol=1e-5)
```

## Replay speed

By default, the server streams as fast as the env step completes (no artificial throttle).
The optional `"speed"` field on the `start` command controls a sleep between frames:

```json
{"cmd": "start", "run_id": "...", "site_id": "...", "speed": 1.0}
```

- `speed = 1.0` (default) — one simulated hour per real second (1 Hz stream).
- `speed = 0.0` — no sleep; stream as fast as possible.
- `speed = 2.0` — 2 simulated hours per real second (2 Hz).
- Range: [0, 100].  Out-of-range values are clamped; negative → 0.

## Step rate and buffering

The env step is deterministic and fast (pure NumPy/JAX forward pass).  There is no
replay buffer on the WS frame queue; if the client cannot consume frames (slow network
or paused), the server back-pressures via the WebSocket send queue (asyncio await send).

## Out of scope

- Multi-client session sharing (each connection is fully isolated).
- Training harness proxy — separate contract `training_proxy.md`.
- Any LLM analysis endpoint.
- Real hardware I/O.

## Dependencies

- `fastapi>=0.110`, `websockets>=12` (from `serving` extras).
- `energy_go.telemetry.validate` (task #23 / `contracts/shared/telemetry_validate.md`).
- `checkpoints/{run_id}/policy.npz` — produced by training-engineer (format defined here;
  the training checkpoint contract will reference this definition when it lands).
- `checkpoints/{run_id}/normalization.npz` — produced by training-engineer.
- The env step interface (NumPy reference implementation from `contracts/env/reference_implementation.md`
  or JAX env step from task #8) — the serving layer calls `env.step(obs, action)`.
