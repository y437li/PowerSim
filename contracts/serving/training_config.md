# Contract: `training_config` — wizard algorithm/hyperparam → RunConfig

**Version:** 1.0.0
**Area:** serving
**Owner:** serving-engineer
**Spec refs:** REBUILD_SPEC §5 (training), §6–§7 (serving layer)
**Decisions:** D18 (single-validator / single-source), D37 (assembly in one Python impl),
D32(b) (no client-side dialect of RunConfig)
**Consumes:**
- `contracts/training/training_pipeline.md` — `RunConfig` dataclass (fields, defaults,
  constraints)
- `contracts/serving/training_proxy.md` — `POST /training/start` (the downstream
  endpoint that consumes `config_id` to launch a training run; the two endpoints are
  complementary, not overlapping)
**Produced by:** serving-engineer; frontend advisory (frontend-engineer: stage-② wizard
consumer); backend-reviewer gates.
**Frontend advisory:** frontend-engineer (PR #115, `feat/frontend-stage-algorithm`).
The frontend contract (stage_config §3.8) cites this contract.

---

## 1. Purpose

This contract defines `POST /api/training/config` — the stage-② wizard submission
endpoint that converts the user's algorithm + hyperparameter form into a persisted,
fully-assembled `RunConfig` and returns a stable `config_id` for subsequent use by
`POST /training/start`.

**Problem it solves (D37 / D32(b)):** The stage-② wizard collects a user-friendly
form (`algorithm_type`, optional SAC hyperparams, baseline list). Assembling that form
into a canonical `RunConfig` — filling server-enforced constants (`gamma=0.999`,
`tau=0.005`, etc.), validating ranges, persisting for later use — MUST live in ONE
Python implementation, not be duplicated in frontend TypeScript.

**Relationship to `POST /training/start`** (in `training_proxy.md`): this endpoint
persists the config and returns `config_id`; `/training/start` accepts `config_id` to
look up the persisted config and relay it to the harness.  They are distinct by
design so the wizard can edit hyperparams and regenerate a config without starting
a run, and so the frontend can pass `config_id` through the UX flow without
re-transmitting the full RunConfig.

**Single-source rule (D18 / D32(b) / D37):** all RunConfig assembly logic lives in
`src/energy_go/serving/training_config.py`.  No hyperparameter construction in TypeScript.

---

## 2. Module

`src/energy_go/serving/training_config.py`
Registered on `app` from `energy_go.serving.app`.

---

## 3. Endpoint

### 3.1 `POST /api/training/config`

**Purpose:** Validate and assemble a wizard algorithm-selection form into a canonical
`RunConfig`, persist it server-side, and return a stable `config_id` + `config_hash`
for the training launch flow.

**HTTP conventions:**
- `200`: assembly and validation passed; body contains assembled config + ids.
- `422`: request body fails schema or RunConfig constraint validation.
  Body: `{"detail": "<human-readable>", "code": "VALIDATION_ERROR",
           "errors": [{"field": "<path>", "message": "<reason>"}]}`.
- `500`: unexpected server exception.
  Body: `{"detail": "internal error", "code": "INTERNAL_ERROR"}`.

---

## 4. Request body

```json
{
  "algorithm_type": "sac",
  "site_config_id": "site_gansu",
  "seed": 42,
  "sac_hyperparams": {
    "lr": 1e-4,
    "hidden_sizes": [256, 256],
    "batch_size": 512,
    "buffer_size": 1000000,
    "total_env_steps": 500000,
    "eval_every_steps": 10000,
    "n_envs": 4096
  },
  "baselines": ["no_battery", "tou"]
}
```

### 4.1 Top-level fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `algorithm_type` | `"sac"` \| `"baseline_only"` | yes | — | Algorithm mode |
| `site_config_id` | string | yes | — | Must match a `config/site_{id}.yaml` file |
| `seed` | int | no | `42` | Master PRNG seed for reproducibility; carried into RunConfig |
| `sac_hyperparams` | object | **required when `algorithm_type="sac"`; must be absent when `"baseline_only"`** | — | User-adjustable SAC fields (§4.2) |
| `baselines` | string[] | yes | — | Non-empty list of baseline names to evaluate (§4.3) |

### 4.2 `sac_hyperparams` fields

All fields are optional; omitted fields take the RunConfig default shown.
Unknown fields are rejected with 422 (forward-compat is managed explicitly).

| Field | Type | Default | Constraint | Unit |
|---|---|---|---|---|
| `lr` | float | `1e-4` | `(0, 1e-2]` | dimensionless |
| `hidden_sizes` | int[] | `[256, 256]` | 1–4 elements; each ∈ `[16, 1024]`; must be non-empty | — |
| `batch_size` | int | `512` | power of 2, ∈ `{64, 128, 256, 512, 1024}` | — |
| `buffer_size` | int | `1_000_000` | `[100_000, 2_000_000]` | env-step tuples |
| `total_env_steps` | int | `500_000` | `≥ 500_000`; divisible by `n_envs` | env steps |
| `eval_every_steps` | int | `10_000` | `[1_000, 100_000]`; ≤ `total_env_steps` | env steps |
| `n_envs` | int | `4096` | power of 2; ∈ `[1, 4096]` | parallel envs |

### 4.3 `baselines` enum

| Value | Description |
|---|---|
| `"no_battery"` | `NoBatteryPolicy` — grid-import whenever renewables insufficient; battery idle |
| `"tou"` | `TouPolicy` — charge during off-peak, discharge during peak TOU hours |

Any other string value → 422 `UNKNOWN_BASELINE`.  Both values are always valid
regardless of `algorithm_type`.

### 4.4 `baseline_only` mode

When `algorithm_type = "baseline_only"`:
- `sac_hyperparams` field **MUST be absent** from the request body (422 if present).
- `baselines` field is required and must be non-empty.
- The assembled `run_config` in the response has all SAC hyperparameters at their
  defaults (the `run_config` object is always a full `RunConfig`; the `algorithm_type`
  field in the response signals how it will be used).

---

## 5. Server-side assembly rules

The endpoint assembles a `RunConfig` by merging user-supplied `sac_hyperparams`
over the RunConfig defaults, then stamping server-enforced constants.

### 5.1 User-adjustable fields (from request body)

Fields accepted from `sac_hyperparams` (§4.2): `lr`, `hidden_sizes`, `batch_size`,
`buffer_size`, `total_env_steps`, `eval_every_steps`, `n_envs`.
Additional top-level fields threaded in: `seed`, `site_config_id`.

### 5.2 Server-enforced constants (NOT user-adjustable)

These are set by the server regardless of what the client sends.  Any attempt to
override them via `sac_hyperparams` is rejected with 422.

| Field | Value | Rationale |
|---|---|---|
| `gamma` | `0.999` | LOCKED (RunConfig §3.1 — demand charge monthly signal; any change needs rl-architect DECISION) |
| `tau` | `0.005` | Polyak coefficient — §5 default |
| `ent_coef` | `"auto"` | Dual-variable entropy auto-tuning — §5 |
| `episode_len` | `168` | 7-day episode @ Δt=1h — D3 |
| `eval_episode_len` | `8760` | Full-year eval — §5 |
| `norm_obs` | `true` | VecNormalize — §5/§7 |
| `norm_reward` | `true` | VecNormalize — §5/§7 |
| `clip_obs` | `10.0` | VecNormalize clamp — §5/§7 |
| `clip_reward` | `10.0` | VecNormalize clamp — §5/§7 |
| `log_every_steps` | `1_000` | Telemetry cadence — telemetry_schema.md |
| `run_id` | `""` | Assigned at run start by `/training/start` |

### 5.3 `config_id` and `config_hash` generation

- **`config_id`:** A UUID4 string generated at assembly time.  Stable for the
  lifetime of the server process.  Used as the key to look up the persisted config
  when `/training/start` is called.
- **`config_hash`:** `sha256(canonical_json(run_config))` where `canonical_json` is
  `json.dumps(run_config_as_dict, sort_keys=True, separators=(',', ':'))`.
  Allows the frontend to detect duplicate configs without storing the full RunConfig.

### 5.4 Persistence

The assembled `RunConfig` is stored in-process in a dict keyed by `config_id`
(v1: in-memory; v2: file-backed under `run_configs/`).  The store is module-level and
lives for the server process lifetime.  A server restart invalidates all `config_id`s;
the frontend MUST re-submit if it receives a 404 from `/training/start`.

---

## 6. Response body (HTTP 200)

```json
{
  "config_id":      "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "config_hash":    "a3f1c8e2...b7d4",
  "algorithm_type": "sac",
  "baselines":      ["no_battery", "tou"],
  "run_config": {
    "lr":               1e-4,
    "gamma":            0.999,
    "batch_size":       512,
    "buffer_size":      1000000,
    "tau":              0.005,
    "ent_coef":         "auto",
    "total_env_steps":  500000,
    "n_envs":           4096,
    "episode_len":      168,
    "eval_episode_len": 8760,
    "norm_obs":         true,
    "norm_reward":      true,
    "clip_obs":         10.0,
    "clip_reward":      10.0,
    "hidden_sizes":     [256, 256],
    "eval_every_steps": 10000,
    "log_every_steps":  1000,
    "seed":             42,
    "run_id":           "",
    "site_config_id":   "site_gansu"
  }
}
```

### 6.1 Response field types and units

| Field | Type | Description |
|---|---|---|
| `config_id` | string (UUID4) | Stable handle for this config; pass to `/training/start` |
| `config_hash` | string (hex, 64 chars) | SHA-256 of canonical JSON-serialized `run_config` |
| `algorithm_type` | `"sac"` \| `"baseline_only"` | Echoed from request |
| `baselines` | string[] | Echoed from request |
| `run_config` | object | Fully-assembled `RunConfig` (all fields present; no omissions) |
| `run_config.lr` | float | Learning rate (dimensionless) |
| `run_config.gamma` | float | Discount factor (dimensionless; always 0.999) |
| `run_config.batch_size` | int | SAC mini-batch size (env-step tuples) |
| `run_config.buffer_size` | int | Replay buffer capacity (env-step tuples) |
| `run_config.total_env_steps` | int | Total env steps for training run |
| `run_config.n_envs` | int | Number of vmapped parallel environments |
| `run_config.hidden_sizes` | int[] | MLP hidden layer widths |
| `run_config.eval_every_steps` | int | Eval cadence (env steps) |
| `run_config.log_every_steps` | int | Telemetry emit cadence (env steps; always 1000) |
| `run_config.seed` | int | PRNG seed |
| `run_config.site_config_id` | string | Site YAML basename |
| `run_config.run_id` | string | Always `""` (assigned at `/training/start`) |

---

## 7. Error body

**HTTP 422:**
```json
{
  "detail": "hyperparameter validation failed",
  "code": "VALIDATION_ERROR",
  "errors": [
    {
      "field": "sac_hyperparams.total_env_steps",
      "message": "must be >= 500000; got 1000"
    }
  ]
}
```

Error codes:

| Code | Trigger |
|---|---|
| `VALIDATION_ERROR` | Any constraint violation in §4.2; unknown `baselines` value; `sac_hyperparams` present when `algorithm_type="baseline_only"`; unknown field in `sac_hyperparams` |
| `UNKNOWN_SITE` | `site_config_id` does not match any `config/site_*.yaml` |
| `INTERNAL_ERROR` | Unexpected exception |

---

## 8. Invariants

1. `run_config.gamma` is always `0.999` in every response — never user-settable.
2. `run_config.run_id` is always `""` — assigned later by `/training/start`.
3. `config_hash = sha256(json.dumps(run_config_dict, sort_keys=True, separators=(',', ':')))`.
4. `config_id` is UUID4; unique per call (even for identical params — different UUIDs).
5. `sac_hyperparams` is absent in `baseline_only` requests; present in `sac` requests.
6. `total_env_steps` divisible by `n_envs` (422 if not — RunConfig §3.1 constraint).
7. The full `run_config` object in the response contains every `RunConfig` field —
   no optional omissions; the frontend can deep-compare vs defaults without re-fetching.

---

## 9. Out of scope

- Launching a training run (`POST /training/start` in `training_proxy.md`).
- Storing configs to disk (v1 is in-memory; file-backed is a future enhancement).
- Per-site hyperparameter validation (beyond checking `site_config_id` exists).
- Changing server-enforced constants (gamma etc.) — requires rl-architect DECISION.
