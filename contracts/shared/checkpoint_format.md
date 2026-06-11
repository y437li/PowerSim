# Contract: Checkpoint Format (SHARED)

- **Status:** DRAFT — both reviewers comment (advisory); rl-architect locks on own authority (D25; same precedent as telemetry_schema)
- **Area:** shared — `contracts/shared/` (training producer + serving consumer; D25 relocates from the D22d-proposed `contracts/training/` path)
- **Spec sections:** §5 (training methodology), §7 (JAX architecture — actor MLP + VecNormalize)
- **Decisions:** D22d (checkpoint is next shared contract to LOCK; actor weights + running normalisation stats), D25 (relocate to contracts/shared/ — same precedent as telemetry_schema), D22b (import path `energy_go.env.jax_env`), D13 (real vs reward-basis costs)
- **Owner:** training-engineer · **Reviewers:** backend-reviewer + frontend-reviewer (both advisory COMMENT); **Locked by:** rl-architect
- **Consumers:** `energy_go.training.run_training` (producer), `energy_go.serving` (consumer — MLP policy export / ONNX), `energy_go.training.eval` (loads for eval), serving websocket inference stream
- **Cross-reference:** `contracts/training/training_pipeline.md` (defines `RunningStats`, actor architecture, `RunConfig`); `contracts/shared/telemetry_schema.md` (checkpoint_id ties to train_metrics)

---

## 1. Purpose

The checkpoint is the **single artifact that carries everything inference needs**: actor weights
and VecNormalize normalisation statistics. A downstream system (serving layer) must be able to:

1. Load the checkpoint without importing `energy_go.training`.
2. Reconstruct the actor forward pass from raw numpy arrays.
3. Produce identical actions to the training-time policy on any fixed observation.

There is **no separate `.pkl` file** for VecNormalize stats — all state is in one file.

---

## 2. File format

Checkpoints are stored as **NumPy `.npz` archives** (compressed numpy arrays). This format:
- Is language-agnostic (loadable in Python, Julia, MATLAB, or any language with numpy compat).
- Contains only primitive arrays (no Python objects, no Flax pytree metadata).
- Round-trips through `np.savez_compressed` / `np.load` without any custom serialisation logic.
- Is readable by the serving layer without importing JAX or Flax.

File extension: `.npz`
Naming convention: `checkpoint_<run_id>_step<global_step>.npz` (e.g. `checkpoint_abc123_step500000.npz`)

---

## 3. Schema version

Every checkpoint file contains a `schema_version` string entry (numpy string array, scalar).
Current version: **`"1.0.0"`** (semver).

Versioning rules:
- **Patch** (1.0.x) — documentation change only; no key change.
- **Minor** (1.x.0) — additive: new optional key added; consumers ignore unknown keys.
- **Major** (x.0.0) — any key removal/rename/retype or algorithm change. Requires a new
  rl-architect DECISION and re-lock of this contract.

---

## 4. Required keys

All keys listed below MUST be present in every checkpoint. A loader MUST raise `KeyError`
with a descriptive message if any required key is absent.

### 4.1 Metadata

| Key | dtype | shape | Description |
|-----|-------|-------|-------------|
| `schema_version` | `str` | scalar | `"1.0.0"` |
| `checkpoint_id` | `str` | scalar | UUID v4 string, e.g. `"a1b2c3d4-…"`. Ties `train_metrics` and `eval_compare` telemetry to this checkpoint; serves as the join key between the artifact, the training dashboard, and the serving layer (see §8.1 cross-contract note). |
| `run_id` | `str` | scalar | Training run identifier (matches telemetry envelope `run_id`). |
| `global_step` | `int64` | scalar | Environment steps consumed when this checkpoint was written. |
| `created_at_utc` | `str` | scalar | ISO-8601 UTC wall-clock timestamp of when this checkpoint was written, e.g. `"2026-06-10T14:03:00Z"`. Enables chronological ordering of checkpoints across runs in the training dashboard and run-history view. **Must be the actual write time, not the start of the training run.** |
| `code_version` | `str` | scalar | Short identifier tying the checkpoint to the codebase state that produced it. Convention: the first 8 characters of the git commit SHA at training time (e.g. `"5cc25b5a"`), or `"unknown"` if not determinable. Enables the dashboard eval-vs-baseline panel to display the exact policy provenance and lets the user reproduce a result. |
| `run_config_json` | `str` | scalar | JSON-serialised `RunConfig` (all fields). **Must include** `seed` (for reproducibility) and `site_config_id` (e.g. `"site_gansu"` — the site YAML used for training). See `contracts/training/training_pipeline.md` §3 for the full RunConfig schema. **Note:** JSON has no tuple type — Python tuple fields (e.g. `hidden_sizes: tuple = (256, 256)`) serialise as JSON arrays `[256, 256]`. Consumers must not expect Python tuples when deserialising. |

### 4.2 Architecture identity

These keys let a consumer (serving layer, harness) reconstruct the observation normalisation
and action post-processing without importing `energy_go.training` or hardcoding constants.

| Key | dtype | shape | Description |
|-----|-------|-------|-------------|
| `obs_dim` | `int64` | scalar | Observation dimensionality: always `107` per §2.1. Loaded by serving to validate `obs_mean`/`obs_var` shapes and to construct the correct input buffer. |
| `action_dim` | `int64` | scalar | Action dimensionality: always `6` per §2.2 ("Energy Router"). Loaded by serving to recover the `action → physical-dispatch` mapping described in §6. |

> **Why record these?** If the site config ever adds observation dimensions (e.g. §10 Tier 1 enhancements), the checkpoint already carries the correct `obs_dim` for the policy it was trained with — the serving layer does not need to parse a separate config file to know the obs shape.

### 4.3 VecNormalize observation statistics

Saved at the moment the checkpoint is written. Consumers apply these BEFORE passing obs to the actor.

| Key | dtype | shape | Description |
|-----|-------|-------|-------------|
| `obs_mean` | `float32` | `(107,)` | Running mean of the 107-dim observation vector |
| `obs_var` | `float32` | `(107,)` | Running population variance (≥ 0) |
| `obs_count` | `int64` | scalar | Number of observations seen (Welford count) |
| `obs_clip` | `float32` | scalar | Clip value (always `10.0` per §5; carried so inference doesn't hardcode it) |

> **Inference recipe** for obs normalisation:
> ```python
> std = np.sqrt(obs_var + 1e-8)
> norm_obs = np.clip((obs - obs_mean) / std, -obs_clip, obs_clip)
> ```
> This is identical to `energy_go.training.normalizer.normalize_obs()` with `clip=obs_clip`.

### 4.4 Actor MLP weights

The actor is a 2-hidden-layer MLP (§5 training_pipeline contract §5.2):
```
Input(107) → Dense(256, ReLU) → Dense(256, ReLU) → Dense(12)
```
Output Dense(12) splits into `(mean(6), log_std_raw(6))`; `log_std = clip(log_std_raw, -5, 2)`.
Deterministic eval action: per-component squash of `mean` — `tanh(mean[0])` for `a_bat`,
`sigmoid(mean[1:6])` for the 5 fractions. See §6 for the full inference recipe.

Keys use the naming convention `actor_<layer>_<param>`:

| Key | dtype | shape | Description |
|-----|-------|-------|-------------|
| `actor_fc1_w` | `float32` | `(107, 256)` | Layer 1 weight matrix (`W` in `xW + b`, row = input dim) |
| `actor_fc1_b` | `float32` | `(256,)` | Layer 1 bias |
| `actor_fc2_w` | `float32` | `(256, 256)` | Layer 2 weight matrix |
| `actor_fc2_b` | `float32` | `(256,)` | Layer 2 bias |
| `actor_out_w` | `float32` | `(256, 12)` | Output layer weight (12 outputs: mean(6) + log_std_raw(6)) |
| `actor_out_b` | `float32` | `(12,)` | Output layer bias |

> **Matrix convention:** weights are stored in `(in_features, out_features)` order so that
> `y = x @ W + b` — same convention as Flax's default `Dense` layer. Transposing in storage
> would require callers to track orientation; this avoids that ambiguity.
>
> **Why flat keys over a nested dict?** `np.savez` only supports flat string keys. Nesting
> would require custom serialisation. Flat keys with a consistent `actor_<layer>_<param>`
> pattern are unambiguous and require no schema metadata.

### 4.5 Optional: critic weights (for resuming training)

These keys are OPTIONAL (not required for inference). A serving-layer consumer MUST NOT
fail if they are absent. A training-resume loader SHOULD fail loudly if they are absent
when resuming is requested.

| Key | dtype | shape | Description |
|-----|-------|-------|-------------|
| `critic1_fc1_w` | `float32` | `(113, 256)` | Critic Q1 layer 1 (input dim = 107 obs + 6 action = 113) |
| `critic1_fc1_b` | `float32` | `(256,)` | |
| `critic1_fc2_w` | `float32` | `(256, 256)` | |
| `critic1_fc2_b` | `float32` | `(256,)` | |
| `critic1_out_w` | `float32` | `(256, 1)` | |
| `critic1_out_b` | `float32` | `(1,)` | |
| `critic2_*` | `float32` | same as critic1 | Second Q-network (clipped double-Q) |
| `ent_coef` | `float32` | scalar | Current entropy coefficient value (for resume) |
| `target_entropy` | `float32` | scalar | Target entropy = −action_dim = −6.0 (for resume; action_dim=6 per §2.2) |

---

## 5. Save / load API

These two functions are the **only** supported way to read/write checkpoints. All other code
must go through this API — never call `np.savez`/`np.load` directly in a consumer.

```python
# energy_go.training.checkpoint_format

def save_checkpoint(data: CheckpointData, path: str | Path) -> None:
    """Serialise CheckpointData to a .npz file at the given path.

    - Converts all JAX arrays to numpy before saving.
    - Compresses with np.savez_compressed.
    - Atomically writes via a temp file in the **same directory** as `path`, then
      os.replace(tmp, path). The temp file MUST be same-directory so the rename is
      same-filesystem — cross-filesystem moves are not atomic on POSIX.
    - obs_count is cast to np.int64 before saving regardless of its Python / JAX type
      (JAX defaults to int32 on CPU-only builds; this ensures the loaded dtype is int64).
    - Raises ValueError if any required key is missing from data.
    - Raises ValueError if any required array has wrong dtype or shape.
    """

def load_checkpoint(path: str | Path) -> CheckpointData:
    """Load a .npz checkpoint file and return a CheckpointData.

    - Validates schema_version: raises ValueError if major version > 1.
    - Raises KeyError with a descriptive message if any required key is absent.
    - Validates dtypes and shapes of all required keys.
    - Returns arrays as numpy (float32 / int64), NOT as JAX arrays.
      Callers convert to JAX if needed: jnp.array(checkpoint.obs_mean).
    """
```

### 5.1 `CheckpointData` type

```python
from dataclasses import dataclass, field
import numpy as np

@dataclass
class CheckpointData:
    # Metadata
    schema_version:  str
    checkpoint_id:   str    # UUID v4; join key for telemetry + serving (§8.1)
    run_id:          str
    global_step:     int
    created_at_utc:  str    # ISO-8601 UTC write time, e.g. "2026-06-10T14:03:00Z"
    code_version:    str    # git SHA prefix or "unknown"
    run_config_json: str    # JSON string; must carry seed + site_config_id

    # Architecture identity (§4.2)
    obs_dim:    int = 107   # observation dimensionality (always 107 for Energy GO v1)
    action_dim: int = 6     # action dimensionality (always 6 per §2.2 "Energy Router")

    # VecNormalize obs stats (numpy, shape (obs_dim,) and scalar)
    obs_mean:   np.ndarray = field(default_factory=lambda: np.zeros(107, dtype=np.float32))
    obs_var:    np.ndarray = field(default_factory=lambda: np.ones(107,  dtype=np.float32))
    obs_count:  int = 0     # saved as np.int64 in .npz (save_checkpoint casts explicitly)
    obs_clip:   float = 10.0

    # Actor MLP weights (numpy float32); shapes correspond to Dense(12) output layer:
    # 12 = 2 * action_dim = mean(6) + log_std_raw(6)
    actor_fc1_w: np.ndarray = field(default=None)    # (107, 256)
    actor_fc1_b: np.ndarray = field(default=None)    # (256,)
    actor_fc2_w: np.ndarray = field(default=None)    # (256, 256)
    actor_fc2_b: np.ndarray = field(default=None)    # (256,)
    actor_out_w: np.ndarray = field(default=None)    # (256, 12)  ← 12 = 2 * action_dim
    actor_out_b: np.ndarray = field(default=None)    # (12,)

    # Optional critic weights (None if not saved / inference-only checkpoint)
    # Critic input dim = obs_dim + action_dim = 113
    critic1_fc1_w: np.ndarray | None = None    # (113, 256)
    critic1_fc1_b: np.ndarray | None = None
    critic1_fc2_w: np.ndarray | None = None
    critic1_fc2_b: np.ndarray | None = None
    critic1_out_w: np.ndarray | None = None
    critic1_out_b: np.ndarray | None = None
    critic2_fc1_w: np.ndarray | None = None    # (113, 256)
    critic2_fc1_b: np.ndarray | None = None
    critic2_fc2_w: np.ndarray | None = None
    critic2_fc2_b: np.ndarray | None = None
    critic2_out_w: np.ndarray | None = None
    critic2_out_b: np.ndarray | None = None
    ent_coef:       float | None = None
    target_entropy: float | None = None    # = -action_dim = -6.0
```

---

## 6. Actor forward pass (inference recipe)

The serving layer or any downstream consumer can reproduce the actor forward pass in pure
NumPy without importing JAX or Flax:

```python
import numpy as np

def actor_forward_numpy(checkpoint: CheckpointData, raw_obs: np.ndarray) -> np.ndarray:
    """Deterministic actor action from a raw (107,) observation.

    Returns: action (6,) — per-component squash applied:
        action[0]   = tanh(mean[0])       # a_bat  ∈ (-1, 1)
        action[1:6] = sigmoid(mean[1:6])  # fractions ∈ (0, 1)
    """
    # Step 1: normalise obs with VecNormalize stats
    std = np.sqrt(checkpoint.obs_var + 1e-8)
    norm_obs = np.clip(
        (raw_obs - checkpoint.obs_mean) / std,
        -checkpoint.obs_clip,
        checkpoint.obs_clip,
    )

    # Step 2: MLP forward pass — y = ReLU(x @ W + b)
    h1 = np.maximum(0.0, norm_obs @ checkpoint.actor_fc1_w + checkpoint.actor_fc1_b)   # (256,)
    h2 = np.maximum(0.0, h1       @ checkpoint.actor_fc2_w + checkpoint.actor_fc2_b)   # (256,)
    out = h2 @ checkpoint.actor_out_w + checkpoint.actor_out_b                          # (12,)

    # Step 3: split mean(6) from log_std_raw(6); apply per-component squash
    mean = out[:6]  # first 6 outputs are the mean vector
    # Per-component squash per §2.2 "Energy Router" action space:
    a_bat     = np.tanh(mean[0:1])            # a_bat ∈ (-1, 1)
    fractions = 1.0 / (1.0 + np.exp(-mean[1:6]))  # sigmoid; fractions ∈ (0, 1)
    return np.concatenate([a_bat, fractions])  # (6,)
```

> **Action → physical dispatch mapping** (for serving consumers):
> Once `action = actor_forward_numpy(checkpoint, raw_obs)` returns a `(6,)` vector, the
> mapping to physical quantities is defined in `contracts/env/jax_env_core.md` §5.3.2:
> - `action[0]` (`a_bat`) × `p_bat_max_mw` (98.16 MW) → battery charge/discharge setpoint
> - `action[1]` (`f_sol→load`) × solar power → solar-to-load flow
> - `action[2]` (`f_sol→bat`)  × solar power → solar-to-battery flow  (sum with [1] clipped to 1)
> - `action[3]` (`f_wind→load`) × wind power → wind-to-load flow
> - `action[4]` (`f_wind→bat`)  × wind power → wind-to-battery flow   (sum with [3] clipped to 1)
> - `action[5]` (`f_bat→load`)  × battery discharge → battery-to-load flow (remainder → grid)
>
> The env handles renormalisation when `action[1]+action[2] > 1` or `action[3]+action[4] > 1`.
> The `site_config_id` in `run_config_json` (§4.1) resolves `p_bat_max_mw` and the site YAML.

This NumPy recipe MUST produce actions identical (within float32 tolerance, atol=1e-5) to
`energy_go.training.run_training.actor_forward()` applied with JAX.

---

## 7. Validation requirements

Every consumer and producer must validate the checkpoint against this contract in tests.
Specifically:

1. **Shape test:** after loading, assert all required keys have the shapes in §4.
2. **Dtype test:** all actor and obs-stats arrays are float32; metadata scalars are the correct type.
3. **Round-trip test:** `save_checkpoint(data, path); load_checkpoint(path)` preserves all values to float32 tolerance.
4. **Forward-pass parity:** `actor_forward_numpy(checkpoint, obs)` and `actor_forward_jax(checkpoint, obs)` agree to atol=1e-5 on a fixed obs vector.
5. **Schema-version rejection:** a checkpoint with `schema_version = "2.0.0"` raises `ValueError` at load time.
6. **Missing-key detection:** a checkpoint missing `obs_mean` (or any required key) raises `KeyError` with a descriptive message.
7. **Atomic write:** if a write is interrupted (simulated by truncating the file), the pre-existing checkpoint at that path is NOT corrupted.

---

## 8. Cross-agent interface summary

| Agent | Role | Operation |
|-------|------|-----------|
| `training-engineer` | Producer | `save_checkpoint(data, path)` at each eval checkpoint and at end of run |
| `serving-engineer` | Consumer | `load_checkpoint(path)` at serving startup; calls `actor_forward_numpy()` |
| `training-engineer` | Consumer | `load_checkpoint(path)` to resume training (optional critic weights needed) |
| `env-harness-engineer` | Consumer | `load_checkpoint(path)` to run eval/replay in the harness UI |

### 8.1 Cross-contract coordination note (for rl-architect at lock time)

`checkpoint_id` (§4.1) currently "ties `train_metrics` telemetry to this checkpoint". For the
dashboard eval-vs-baseline panel to display the exact trained policy for a live inference run,
the following joins need to work end-to-end:

- `eval_compare.checkpoint_id` → the artifact at `<run_id>/checkpoint_<checkpoint_id>.npz`
- serving REST run-history endpoint → surfaces `checkpoint_id` + `created_at_utc` + `code_version` for the policy-picker UI
- serving inference websocket → emits `checkpoint_id` per-step so the 3D scene and cost dashboard know which policy is running

The `eval_compare` telemetry payload already carries `checkpoint_id` (LOCKED schema §Kind 3).
The serving contract (`contracts/serving/rest_api.md`) and the harness contract should
surface the same trio. **No change to this file required** — this note flags the coordination
for rl-architect to verify at lock time that the join key is consistent across the three
locked/in-flight contracts.

---

## 9. Deliberate deviations from §5/SB3

| Old (SB3) | New (JAX rebuild) | Reason |
|---|---|---|
| `vec_normalize.pkl` (Python pickle of SB3 VecNormalize object) | `obs_mean`, `obs_var`, `obs_count`, `obs_clip` as float32 arrays in the same `.npz` | Language-agnostic; no Python/SB3 dependency at inference; no pickle security concerns |
| Separate model file (`policy.zip`) + normalise file (`.pkl`) | Single `.npz` file with all weights + stats | Atomic: serving layer loads one file; no partial-state risk |
| SB3 `SAC.save()` / `SAC.load()` | `save_checkpoint()` / `load_checkpoint()` | Pure numpy; no SB3 import at load time |

---

## 10. Out of scope

- ONNX export (optional serving polish; §7 "ONNX or raw MLP weights")
- Multi-agent / ensemble checkpoints
- Quantised (int8/float16) weights — inference uses float32
- Checkpoint encryption or signing
- Checkpoint diffing / delta updates
