# `src/energy_go/training`

<!-- curated -->
## Purpose

This package implements the §5/§7 SAC training pipeline. Its responsibilities fall into five areas:

- **Training loop** (`run_training.py`): the `train()` function runs device-resident SAC (D27) — a flashbax replay buffer, jitted env step, and `lax.scan` over the inner loop. The actor MLP forward pass is exposed separately as `actor_forward` for use by eval and serving.
- **Evaluation and baselines** (`eval.py`, `baselines.py`): `run_eval()` rolls out a policy deterministically over a full 8760-step year and returns a `PolicyEvalResult` with real-money cost breakdowns. Baselines cover §5 (`NoBatteryPolicy`, `TouPolicy`) and §11 (`GreedyPolicy`, `DpOraclePolicy`, `MpcPolicy`); `run_benchmark()` runs any §11 baseline over the same eval year.
- **Observation and reward normalisation** (`normalizer.py`): `RunningStats` carries a Welford running mean/variance; `update_stats` does parallel batch updates (§4.2); `normalize_reward` divides by std only, not mean, per the SB3 convention locked in §12 N1.
- **Checkpoint format** (`checkpoint_format.py`): `save_checkpoint`/`load_checkpoint` serialise `CheckpointData` (actor weights + normaliser stats) to `.npz` atomically; `actor_forward_numpy` runs the actor from a raw `(107,)` NumPy observation for use in serving without a JAX dependency (see `contracts/shared/checkpoint_format.md`). The discount factor γ = 0.999 is LOCKED for demand-charge problems.
- **Telemetry emission** (`telemetry.py`): `build_train_metrics` and `build_eval_compare` construct schema-compliant envelopes (LOCKED schema v1.0.0, D18) for streaming to the serving layer (see `contracts/training/training_pipeline.md §9`).

What does NOT live here: the WebSocket/HTTP serving layer (that is the `serving` package) and the JAX env physics (that is the `env` package).
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `__init__.py`

> Energy GO training package — §5 SAC pipeline.

_No public symbols exported._

### `baselines.py`

> §5 baseline policies — NoBatteryPolicy and TouPolicy — §7 of training_pipeline contract.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `NoBatteryPolicy` | `class` | No-battery baseline — §7.1. |
| `TouPolicy` | `class` | Rule-based time-of-use policy — §7.2. |
| `run_baseline` | `function` | Run one of the §5 baseline policies for a full eval year — §7. |
| `GreedyPolicy` | `class` | Greedy myopic baseline — §11.1. |
| `DpOraclePolicy` | `class` | DP oracle baseline — §11.2. |
| `MpcPolicy` | `class` | MPC receding-horizon baseline — §11.3. |
| `run_benchmark` | `function` | Run one §11 benchmark baseline over the full eval year. |

### `checkpoint_format.py`

> Checkpoint save/load and pure-NumPy actor inference — contracts/shared/checkpoint_format.md.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `CheckpointData` | `class` | All-in-one checkpoint carrying actor weights + VecNormalize stats — §5.1. |
| `save_checkpoint` | `function` | Serialise CheckpointData to a .npz file atomically — §5. |
| `load_checkpoint` | `function` | Load a .npz checkpoint and return a CheckpointData — §5. |
| `actor_forward_numpy` | `function` | Deterministic actor action from a raw (107,) observation — §6. |

### `config.py`

> RunConfig — §5 training hyperparameters and logistics.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `RunConfig` | `class` | — |

### `eval.py`

> Deterministic full-year eval loop — §8 of training_pipeline contract.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `StreamAccumulator` | `class` | Per-stream annual accumulator for workstream D project finance. |
| `PolicyEvalResult` | `class` | Real-money cost breakdown over a full evaluation year — §8. |
| `result_to_physical_quantities_entry` | `function` | Serialise the physical_quantities section for one policy in eval_results.json. |
| `run_eval` | `function` | Deterministic policy rollout over the full 8760-step year — §8. |

### `normalizer.py`

> VecNormalize reimplemented as pure JAX arrays — §4 of training_pipeline contract.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `RunningStats` | `class` | Running mean and population variance for a D-dimensional observation/reward. |
| `init_running_stats` | `function` | Initialise RunningStats for a D-dimensional vector. |
| `update_stats` | `function` | Welford parallel batch update — §4.2. |
| `normalize_obs` | `function` | Normalise a (D,) observation using running stats, clip to ±clip. |
| `normalize_reward` | `function` | Normalise a reward scalar by std only (SB3 convention, §12 N1). |

### `run_training.py`

> SAC training pipeline — §5 / §7 of training_pipeline contract + REBUILD_SPEC.md.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `actor_forward` | `function` | Pure-JAX actor MLP forward pass — §5.2. |
| `SACState` | `class` | All SAC parameters and optimizer states packed as a JAX pytree. |
| `train` | `function` | SAC training loop — §5 / §7 of training_pipeline contract. |

### `telemetry.py`

> Telemetry producers — §9 of training_pipeline contract.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `build_train_metrics` | `function` | Build a telemetry envelope with kind='train_metrics' — §9. |
| `build_eval_compare` | `function` | Build a telemetry envelope with kind='eval_compare' — §9. |

<!-- generated:end -->
