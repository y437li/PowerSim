# Contract: Serving REST API

- **Status:** DRAFT
- **Area:** serving
- **Spec:** REBUILD_SPEC.md §6–§7
- **Reviewer:** backend-reviewer (APPROVE gate before implementation)
- **Units note:** all power in **MW**, energy in **MWh**, prices in **¥/MWh**, costs in **¥**. Any deviation is a contract violation.

## Purpose

A thin FastAPI layer that exposes Energy GO configuration, run history, and evaluation
results to the React dashboard and 3D scene.  No physics or training logic lives here —
the server reads YAML configs and checkpoint metadata from the filesystem and returns
JSON.

Module location: `src/energy_go/serving/rest_api.py`
App factory: `energy_go.serving.app:app` (the `FastAPI()` instance; `uvicorn`
launches this).

## Endpoints

All responses include a top-level `"units"` object where units are not unambiguous from
the field name.  Timestamps are ISO 8601 UTC strings.  IDs are filesystem-safe slugs
(no path separators).

### `GET /health`

```json
{
  "status": "ok",
  "version": "1.0.0",
  "policy_loaded": false,
  "run_id": "run_001" | null
}
```

- `version` — serving-layer semver (hardcoded in the module).
- `policy_loaded` — true if a policy weights file has been loaded into memory.
- `run_id` — the currently loaded run's ID, or null.
- Always returns 200.  Never returns 4xx/5xx for a healthy server (monitoring probes must
  be able to depend on this).

### `GET /config/sites`

List available site configuration files under `config/`.

```json
{
  "sites": [
    {"id": "gansu", "name": "Gansu Wind+Solar+Battery", "path": "config/site_gansu.yaml"}
  ]
}
```

- `id` — filename stem, e.g. `site_gansu.yaml` → id `"gansu"`.
- `name` — `site.name` from the YAML, or `id` if absent.
- `path` — relative path from the working directory.
- Returns 200 with an empty `"sites": []` if the `config/` directory is absent.

### `GET /config/sites/{site_id}`

Full parsed content of `config/site_{site_id}.yaml`.

```json
{
  "site": {
    "name": "...",
    "battery": {"capacity_mwh": 294.5, "max_charge_mw": 100.0, ...},
    "grid_connection": {"max_export_mw": 945.0, "max_import_mw": 400.0},
    ...
  },
  "units": {
    "battery.capacity_mwh": "MWh",
    "battery.max_charge_mw": "MW",
    "battery.max_discharge_mw": "MW",
    "grid_connection.max_export_mw": "MW",
    "grid_connection.max_import_mw": "MW"
  }
}
```

- Returns 404 `{"error": "site not found", "detail": "no config/site_{site_id}.yaml"}` if
  the file does not exist.
- The raw YAML is parsed verbatim; no field transformation.

### `GET /config/assets/turbines`
### `GET /config/assets/pv`
### `GET /config/assets/batteries`

List assets from the corresponding YAML files under `config/`.  Each category maps to a
glob: `config/turbine_*.yaml`, `config/pv_*.yaml`, `config/battery_*.yaml`.

```json
{
  "category": "turbines",
  "items": [
    {
      "id": "vestas_v150",
      "name": "Vestas V150-4.2",
      "rated_power_mw": 4.2,
      "hub_height_m": 105.0
    }
  ],
  "units": {"rated_power_mw": "MW", "hub_height_m": "m"}
}
```

- Returns 200 with empty `"items": []` if no matching YAML files exist.
- `id` — filename stem after the category prefix (e.g. `turbine_vestas_v150.yaml` → `"vestas_v150"`).
- Unknown asset fields are passed through verbatim.

### `GET /runs`

List available checkpoint runs under `checkpoints/`.  Each subdirectory is a run.

```json
{
  "runs": [
    {
      "id": "run_001",
      "created_at": "2026-06-10T08:00:00Z",
      "episodes_trained": 150,
      "latest_eval_reward": -0.4321,
      "has_policy": true
    }
  ]
}
```

- `id` — directory name under `checkpoints/`.
- `created_at` — mtime of the run directory in ISO 8601 UTC; absent if not determinable.
- `episodes_trained` — from `checkpoints/{run_id}/metadata.json` field `"episodes_trained"`,
  or 0 if absent.
- `latest_eval_reward` — from `metadata.json` field `"latest_eval_reward"` (float, reward
  units = dimensionless ×1e-5-scaled; see D13), or null if absent.
- `has_policy` — true if `checkpoints/{run_id}/policy.npz` or `policy.onnx` exists.
- Returns 200 with empty `"runs": []` if `checkpoints/` is absent.

### `GET /runs/latest`

Identical response to `GET /runs/{run_id}` (below) for the run with the most recent
`created_at`.  Returns 404 `{"error": "no runs found"}` if `checkpoints/` is empty.

### `GET /runs/{run_id}`

```json
{
  "id": "run_001",
  "created_at": "2026-06-10T08:00:00Z",
  "site_id": "gansu",
  "episodes_trained": 150,
  "has_policy": true,
  "normalization": {
    "obs_mean": [float, ...],
    "obs_std": [float, ...]
  },
  "latest_eval_reward": -0.4321,
  "units": {
    "normalization.obs_mean": "same units as obs vector (mixed; see telemetry schema)",
    "latest_eval_reward": "dimensionless (reward = -(cost_total_reward_basis_yuan + penalty)*1e-5)"
  }
}
```

- `normalization` — obs running-stat arrays from `checkpoints/{run_id}/normalization.npz`
  (keys `"obs_mean"`, `"obs_std"`), serialized as float arrays.  Null if absent.
- All fields from `metadata.json` are merged into the response.
- Returns 404 `{"error": "run not found", "detail": "no checkpoints/{run_id}"}`.

### `GET /runs/{run_id}/eval`

Evaluation results for the run.  This is the LOCKED `eval_compare` payload from
`checkpoints/{run_id}/eval_results.json` (same schema as
`contracts/shared/telemetry_schema.json` `eval_compare.payload`), served verbatim
with a serving-added `"units"` key appended.

```json
{
  "eval_horizon_steps": 8760,
  "checkpoint_id": "run_001",
  "cost_basis": "real_money",
  "policies": {
    "rl": {
      "total_cost_yuan": 42000.0,
      "energy_cost_yuan": 38000.0,
      "demand_charge_yuan": 3000.0,
      "degradation_yuan": 500.0,
      "curtailment_yuan": 200.0,
      "voll_yuan": 300.0,
      "soc_violations_count": 0,
      "soc_violation_mwh": 0.0,
      "penalty_yuan": 0.0
    },
    "no_battery": {
      "total_cost_yuan": 60000.0,
      "energy_cost_yuan": 55000.0,
      "demand_charge_yuan": 4000.0,
      "degradation_yuan": 0.0,
      "curtailment_yuan": 500.0,
      "voll_yuan": 500.0,
      "soc_violations_count": 0,
      "soc_violation_mwh": 0.0,
      "penalty_yuan": 0.0
    },
    "rule_based_tou": {
      "total_cost_yuan": 50000.0,
      "energy_cost_yuan": 44000.0,
      "demand_charge_yuan": 4000.0,
      "degradation_yuan": 1000.0,
      "curtailment_yuan": 700.0,
      "voll_yuan": 300.0,
      "soc_violations_count": 0,
      "soc_violation_mwh": 0.0,
      "penalty_yuan": 0.0
    }
  },
  "units": {
    "*.total_cost_yuan": "¥",
    "*.energy_cost_yuan": "¥",
    "*.demand_charge_yuan": "¥",
    "*.degradation_yuan": "¥",
    "*.curtailment_yuan": "¥",
    "*.voll_yuan": "¥",
    "*.soc_violation_mwh": "MWh",
    "*.penalty_yuan": "¥",
    "eval_horizon_steps": "steps (1 step = 1 h per D3)"
  }
}
```

Field notes:
- `eval_horizon_steps` — integer, 8760 for a 365-day eval (D3: Δt = 1 h). **NOT
  `eval_horizon_days`** — the LOCKED schema uses steps.
- `checkpoint_id` — identifies the policy checkpoint that was evaluated.
- `cost_basis: "real_money"` — total_cost_yuan is real-money sum (D13: excludes
  penalty_yuan and the reward-shaping demand-shape term).
- `soc_violations_count` / `soc_violation_mwh` / `penalty_yuan` — safety and
  reward-basis metrics; reported for transparency but **excluded** from
  `total_cost_yuan` per D13.
- The `policies` dict plus top-level fields are a pass-through of `eval_results.json`;
  the server appends a `"units"` key (not in the raw file).
- Tests must wrap the payload (minus the `"units"` key) in an `eval_compare` message
  envelope and call `validate(msg) == []` (D18 producer obligation).
- Returns 404 if the run or `eval_results.json` is absent.

### `GET /runs/{run_id}/train_curve`

Training metrics time-series from `checkpoints/{run_id}/train_curve.jsonl` (newline-
delimited JSON, one record per logged step).

```json
{
  "steps": [1000, 2000, 3000],
  "episodes": [10, 20, 30],
  "mean_reward": [-0.52, -0.48, -0.44],
  "eval_reward": [null, -0.49, -0.43],
  "actor_loss": [0.31, 0.28, 0.24],
  "critic_loss": [0.55, 0.49, 0.41],
  "units": {
    "mean_reward": "dimensionless (reward = -(cost_total_reward_basis_yuan + penalty)*1e-5)",
    "eval_reward": "dimensionless (same scale as mean_reward)",
    "actor_loss": "dimensionless",
    "critic_loss": "dimensionless"
  }
}
```

- Each field is a parallel array; `null` in `eval_reward` means no eval at that step.
- Returns 404 if run absent; returns 200 with all empty arrays if `train_curve.jsonl` absent.

## Error response schema

All 4xx/5xx errors return:
```json
{"error": "<short reason>", "detail": "<optional longer message or null>"}
```

- 404 — resource not found.
- 422 — path/query parameter validation failure (FastAPI default).
- 500 — unexpected server error (stack trace in logs, not in response).

## Filesystem layout (read-only; serving never writes)

```
<work_dir>/
  config/
    site_<id>.yaml
    turbine_<id>.yaml
    pv_<id>.yaml
    battery_<id>.yaml
  checkpoints/
    <run_id>/
      metadata.json         ← episodes_trained, latest_eval_reward, site_id, created_at
      policy.npz            ← MLP weights dict (produced by training-engineer)
      normalization.npz     ← obs_mean, obs_std float32 arrays
      eval_results.json     ← eval_compare.payload (LOCKED schema)
      train_curve.jsonl     ← newline-delimited JSON log records
```

The server uses the working directory at startup (`os.getcwd()`) as `<work_dir>`.

## FastAPI app configuration

```python
from fastapi import FastAPI
app = FastAPI(title="Energy GO Serving API", version="1.0.0")
```

- CORS: allow all origins (dashboard is served separately during dev; origin is restricted
  at the reverse-proxy level in production — out of scope here).
- No auth (local-only tool; §9 installs behind the local network).

## Out of scope

- WebSocket inference stream — separate contract `inference_stream.md`.
- Training proxy WebSocket — separate contract (after harness interface is defined).
- Policy loading from `policy.npz` / ONNX — covered by `inference_stream.md`.
- Writing or modifying checkpoint files.
- LLM analysis endpoint from the original `backend_server.py` — not in the rebuild.

## Dependencies

- `fastapi>=0.110`, `uvicorn[standard]>=0.29`, `pyyaml>=6.0` (all in `serving` extras).
- `energy_go.telemetry.validate` (`contracts/shared/telemetry_validate.md`) for the
  `GET /runs/{run_id}/eval` validator assertion in tests.
