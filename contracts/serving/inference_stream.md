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
  sending (D18 producer obligation).  The obligation has two tiers:

  **Test-time (hard gate):** Every test that receives an `env_step` frame MUST assert
  `validate(msg) == []`.  A non-empty error list in tests is a bug in the serving layer —
  the test suite is the hard gate that prevents systematic validation failures.

  **Runtime (resilient):** In the live inference stream a D18 validation failure MUST be
  logged as a structured warning (fields: `kind`, `seq`, error list) and MUST NOT crash
  the WebSocket session or silently drop the frame.  Rationale: a transient physics NaN
  in a multi-hour live session should not terminate the connection; the test-time gate
  catches systematic bugs before they reach production.
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
| `policy_not_found` | `start` but no canonical checkpoint in run dir (see §Policy loading) | no |
| `already_running` | `start` while session is already running or paused | no |
| `no_session` | `pause`/`resume`/`step` with no active session | no |
| `bad_state` | `step` when not paused, or other state-inappropriate command | no |
| `bad_command` | message is valid JSON but `cmd` is unrecognised | no |
| `invalid_message` | message is not valid JSON or missing required fields | no |
| `internal` | unexpected server error | **yes** (code 1011) |

After `code` = `"internal"`, the server closes the WebSocket with code 1011 (internal
error).  All other error codes leave the connection open; the client may retry.

## Normalization

The serving layer applies the **exact same obs normalization as training** using the
stats embedded in the checkpoint (`CheckpointData.obs_mean`, `obs_var`, `obs_clip`):

```
std      = sqrt(obs_var + 1e-8)
obs_norm = clip((obs_raw - obs_mean) / std, -obs_clip, obs_clip)
```

`obs_clip` is always `10.0` (§5 training_pipeline; carried in the checkpoint so
inference does not hardcode it).  This is identical to
`energy_go.training.normalizer.normalize_obs()` with `clip=obs_clip`.

There is no separate `normalization.npz` file — all stats are in the single checkpoint
archive loaded via `load_checkpoint` (§Policy loading).

The telemetry stream carries **raw (un-normalized) values** — normalization is only
applied internally before calling the policy.

## Policy loading

**Checkpoint discovery** — on `start`, the serving layer resolves the checkpoint path
for a `run_id` as follows (first match wins):

1. `checkpoints/{run_id}/checkpoint_*.npz` — canonical format (checkpoint_format.md).
   If multiple files match, pick the one with the highest `_step<N>` suffix (integer N).
2. Legacy fallback: `checkpoints/{run_id}/policy.npz` — backward-compatible with runs
   produced before the checkpoint_format contract landed.  In this case, load weights
   from the `w_0/b_0` keys and `normalization.npz` for stats (if present).

If neither is found, the server sends `code: "policy_not_found"` and does not start.

**Loading** — canonical checkpoints are loaded via:

```python
from energy_go.training.checkpoint_format import load_checkpoint, actor_forward_numpy
checkpoint = load_checkpoint("checkpoints/{run_id}/checkpoint_…npz")
```

The returned `CheckpointData` is cached in memory per `run_id` for the server lifetime
(re-loading on subsequent `start` for the same `run_id` is a no-op).

**Forward pass** — uses `actor_forward_numpy` from `energy_go.training.checkpoint_format`
exactly as specified in checkpoint_format.md §6:

```
action = actor_forward_numpy(checkpoint, raw_obs)  # (6,) float32
```

where `raw_obs` is the **un-normalized** observation from the env step.  The function
applies normalization (§Normalization above), MLP forward pass with ReLU activations,
clips `mean` to ±8.0 (D28), then returns `[tanh(mean[0]), sigmoid(mean[1:6])]`.

The test suite MUST verify: `actor_forward_numpy(checkpoint, obs)` agrees with a
reference forward pass to atol=1e-5 on fixed inputs.

## Public policy utilities

The `inference_stream` module exposes one public utility function for use by tests and
other consumers that need the forward-pass logic without a live WebSocket session:

```python
def policy_forward(checkpoint: "CheckpointData", obs: np.ndarray) -> np.ndarray:
    """Run the actor forward pass — thin wrapper around actor_forward_numpy (§6).

    Args:
        checkpoint: CheckpointData loaded via load_checkpoint().
        obs:        float32 (obs_dim,) raw (un-normalized) observation.

    Returns:
        float32 (6,) action: [tanh(mean[0]), sigmoid(mean[1:6])].
        Identical to actor_forward_numpy(checkpoint, obs).
    """
```

`policy_forward` is the single callable the WebSocket handler and tests use; it
delegates entirely to `actor_forward_numpy` (checkpoint_format.md §6, D26).  The
test suite imports it directly to verify parity:

```python
from energy_go.serving.inference_stream import policy_forward
from energy_go.training.checkpoint_format import actor_forward_numpy

action_served    = policy_forward(checkpoint, raw_obs)
action_reference = actor_forward_numpy(checkpoint, raw_obs)
np.testing.assert_allclose(action_served, action_reference, atol=1e-5)
```

**Dependencies:** `contracts/shared/checkpoint_format.md` v1.0.0 (LOCKED).
Frontend validator gap: `telemetryStore.receiveEnvStep` must validate/skip-on-fail
before the real-env cutover goes live (tracked; see D26 / task #29).

## Replay speed

**D24 (binding):** default speed = 1.0 (1 Hz).  The previous wording ("no artificial
throttle") referred to no throttle *beyond* the speed control — not to a default of 0.
The `"speed"` field on the `start` command controls the inter-frame sleep:

```json
{"cmd": "start", "run_id": "...", "site_id": "...", "speed": 1.0}
```

- `speed = 1.0` (default) — one simulated hour per real second (1 Hz stream).
- `speed = 0.0` — no sleep; stream as fast as the env step completes.
- `speed = 2.0` — 2 simulated hours per real second (2 Hz).
- Range: [0, 100].  Out-of-range values are clamped; negative → 0.
- Implementation: `sleep_s = 0.0 if speed == 0 else 1.0 / speed`.

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
