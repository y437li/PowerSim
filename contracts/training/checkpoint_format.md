# Contract: Checkpoint Format (SHARED)

- **Status:** DRAFT — both reviewers comment; rl-architect locks (D22d; shared contract routing per CLAUDE.md)
- **Area:** training (producer) / serving (consumer)
- **Spec sections:** §5 (training methodology), §7 (JAX architecture — actor MLP + VecNormalize)
- **Decisions:** D22d (checkpoint is next shared contract to LOCK; actor weights + running normalisation stats), D22b (import path `energy_go.env.jax_env`), D13 (real vs reward-basis costs)
- **Owner:** training-engineer · **Reviewers:** backend-reviewer (mandatory) + frontend-reviewer (comment); **Locked by:** rl-architect
- **Consumers:** `energy_go.training.run_training` (producer), `energy_go.serving` (consumer — ONNX/MLP policy export), `energy_go.training.eval` (loads for eval), serving websocket inference stream
- **Cross-reference:** `contracts/training/training_pipeline.md` (defines `RunningStats`, actor architecture, `RunConfig`)

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
| `checkpoint_id` | `str` | scalar | UUID v4 string, e.g. `"a1b2c3d4-…"`. Ties `train_metrics` telemetry to this checkpoint. |
| `run_id` | `str` | scalar | Training run identifier (matches telemetry envelope `run_id`). |
| `global_step` | `int64` | scalar | Environment steps consumed when this checkpoint was written. |
| `run_config_json` | `str` | scalar | JSON-serialised `RunConfig` (all fields). Consumers read this to know the hyperparameters. |

### 4.2 VecNormalize observation statistics

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

### 4.3 Actor MLP weights

The actor is a 2-hidden-layer MLP (§5 training_pipeline contract §5.2):
```
Input(107) → Dense(256, ReLU) → Dense(256, ReLU) → Dense(2)
```
Output Dense(2) splits into `(mean, log_std_raw)`; `log_std = clip(log_std_raw, -5, 2)`.
Deterministic eval action: `tanh(mean(norm_obs))`.

Keys use the naming convention `actor_<layer>_<param>`:

| Key | dtype | shape | Description |
|-----|-------|-------|-------------|
| `actor_fc1_w` | `float32` | `(107, 256)` | Layer 1 weight matrix (`W` in `xW + b`, row = input dim) |
| `actor_fc1_b` | `float32` | `(256,)` | Layer 1 bias |
| `actor_fc2_w` | `float32` | `(256, 256)` | Layer 2 weight matrix |
| `actor_fc2_b` | `float32` | `(256,)` | Layer 2 bias |
| `actor_out_w` | `float32` | `(256, 2)` | Output layer weight (2 outputs: mean + log_std_raw) |
| `actor_out_b` | `float32` | `(2,)` | Output layer bias |

> **Matrix convention:** weights are stored in `(in_features, out_features)` order so that
> `y = x @ W + b` — same convention as Flax's default `Dense` layer. Transposing in storage
> would require callers to track orientation; this avoids that ambiguity.
>
> **Why flat keys over a nested dict?** `np.savez` only supports flat string keys. Nesting
> would require custom serialisation. Flat keys with a consistent `actor_<layer>_<param>`
> pattern are unambiguous and require no schema metadata.

### 4.4 Optional: critic weights (for resuming training)

These keys are OPTIONAL (not required for inference). A serving-layer consumer MUST NOT
fail if they are absent. A training-resume loader SHOULD fail loudly if they are absent
when resuming is requested.

| Key | dtype | shape | Description |
|-----|-------|-------|-------------|
| `critic1_fc1_w` | `float32` | `(108, 256)` | Critic Q1 layer 1 (input dim = 107 obs + 1 action = 108) |
| `critic1_fc1_b` | `float32` | `(256,)` | |
| `critic1_fc2_w` | `float32` | `(256, 256)` | |
| `critic1_fc2_b` | `float32` | `(256,)` | |
| `critic1_out_w` | `float32` | `(256, 1)` | |
| `critic1_out_b` | `float32` | `(1,)` | |
| `critic2_*` | `float32` | same as critic1 | Second Q-network (clipped double-Q) |
| `ent_coef` | `float32` | scalar | Current entropy coefficient value (for resume) |
| `target_entropy` | `float32` | scalar | Target entropy = −action_dim = −1.0 (for resume) |

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
    - Atomically writes via a temp file + rename to avoid corrupt checkpoints on crash.
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
from dataclasses import dataclass
import numpy as np

@dataclass
class CheckpointData:
    # Metadata
    schema_version:  str
    checkpoint_id:   str
    run_id:          str
    global_step:     int
    run_config_json: str       # JSON string; deserialise with RunConfig(**json.loads(...))

    # VecNormalize obs stats (numpy, shape (107,) and scalar)
    obs_mean:   np.ndarray     # float32, (107,)
    obs_var:    np.ndarray     # float32, (107,)
    obs_count:  int
    obs_clip:   float          # =10.0

    # Actor MLP weights (numpy float32)
    actor_fc1_w: np.ndarray    # (107, 256)
    actor_fc1_b: np.ndarray    # (256,)
    actor_fc2_w: np.ndarray    # (256, 256)
    actor_fc2_b: np.ndarray    # (256,)
    actor_out_w: np.ndarray    # (256, 2)
    actor_out_b: np.ndarray    # (2,)

    # Optional critic weights (None if not saved / inference-only checkpoint)
    critic1_fc1_w: np.ndarray | None = None
    critic1_fc1_b: np.ndarray | None = None
    critic1_fc2_w: np.ndarray | None = None
    critic1_fc2_b: np.ndarray | None = None
    critic1_out_w: np.ndarray | None = None
    critic1_out_b: np.ndarray | None = None
    critic2_fc1_w: np.ndarray | None = None
    critic2_fc1_b: np.ndarray | None = None
    critic2_fc2_w: np.ndarray | None = None
    critic2_fc2_b: np.ndarray | None = None
    critic2_out_w: np.ndarray | None = None
    critic2_out_b: np.ndarray | None = None
    ent_coef:      float | None = None
    target_entropy: float | None = None
```

---

## 6. Actor forward pass (inference recipe)

The serving layer or any downstream consumer can reproduce the actor forward pass in pure
NumPy without importing JAX or Flax:

```python
import numpy as np

def actor_forward_numpy(checkpoint: CheckpointData, raw_obs: np.ndarray) -> np.ndarray:
    """Deterministic actor action from a raw (107,) observation.

    Returns: action scalar in (-1, 1) (after tanh).
    """
    # Step 1: normalise obs with VecNormalize stats
    std = np.sqrt(checkpoint.obs_var + 1e-8)
    norm_obs = np.clip((raw_obs - checkpoint.obs_mean) / std, -checkpoint.obs_clip, checkpoint.obs_clip)

    # Step 2: MLP forward pass — y = ReLU(x @ W + b)
    h1 = np.maximum(0.0, norm_obs @ checkpoint.actor_fc1_w + checkpoint.actor_fc1_b)   # (256,)
    h2 = np.maximum(0.0, h1      @ checkpoint.actor_fc2_w + checkpoint.actor_fc2_b)   # (256,)
    out = h2 @ checkpoint.actor_out_w + checkpoint.actor_out_b                         # (2,)

    # Step 3: extract mean; apply tanh (deterministic eval policy)
    mean = out[0]
    return np.tanh(mean)   # scalar in (-1, 1)
```

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
