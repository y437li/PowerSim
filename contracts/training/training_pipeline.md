# Contract: Training Pipeline (§5 SAC)

- **Area:** training
- **Branch:** `feat/training-pipeline`
- **Spec sections:** §5 (training methodology), §7 (JAX architecture)
- **Decisions:** D3 (168/8760 episode lengths, Δt=1 h), D13 (real vs reward-basis costs), D18 (LOCKED telemetry schema), D21 (sub-month demand charge = 0), D22b (import path `energy_go.env.jax_env`), D22c (author against contract, parallel to jax_env_core implementation)
- **Status:** DRAFT — awaiting backend-reviewer APPROVE before implementation
- **Review record:** `contracts/reviews/training_pipeline.md`
- **Depends on:**
  - `contracts/env/jax_env_core.md` — env step API signature and import path (authored against contract; impl in PR #33)
  - `contracts/shared/checkpoint_format.md` — on-disk checkpoint structure (task #20, D25 relocated to shared/; may be in parallel; referenced by type alias `CheckpointData` below)
  - `contracts/shared/telemetry_schema.md` v1.0.0 — LOCKED wire format for `train_metrics` + `eval_compare`
- **Owner:** training-engineer · **Reviewer:** backend-reviewer

---

## 1. Scope

This contract specifies the §5 JAX SAC training pipeline — all Python modules under
`src/energy_go/training/`. It covers:

1. `energy_go.training.config` — `RunConfig` (hyperparameters + training logistics)
2. `energy_go.training.normalizer` — `RunningStats` (VecNormalize reimplemented as pure JAX arrays, clip ±10; saved with checkpoint and loaded at inference)
3. `energy_go.training.baselines` — `NoBatteryPolicy`, `TouPolicy`, `run_baseline()` (JAX-native; run in the same JAX env for a fair comparison)
4. `energy_go.training.run_training` — `train(config, key, data) -> CheckpointData` — main SAC training loop
5. `energy_go.training.eval` — `run_eval(checkpoint, data, params) -> PolicyEvalResult` — deterministic full-year eval
6. `energy_go.training.telemetry` — `build_train_metrics(...)`, `build_eval_compare(...)` — produce LOCKED-schema-compliant telemetry dicts

It does **not** specify the on-disk checkpoint serialisation — see `contracts/shared/checkpoint_format.md` (task #20, D25) for that.

---

## 2. Module layout

```
src/energy_go/
  training/
    __init__.py          # exports: train, run_eval, run_baseline, RunConfig, RunningStats, PolicyEvalResult
    config.py            # RunConfig dataclass
    normalizer.py        # RunningStats, update_stats, normalize_obs, normalize_reward
    baselines.py         # NoBatteryPolicy, TouPolicy, run_baseline
    run_training.py      # train() — JAX SAC loop
    eval.py              # run_eval(), PolicyEvalResult
    telemetry.py         # build_train_metrics(), build_eval_compare()
```

---

## 3. RunConfig

```python
from dataclasses import dataclass, field

@dataclass
class RunConfig:
    # --- SAC hyperparameters (§5) — do NOT change defaults without a new DECISION ---
    lr: float         = 1e-4    # learning rate for actor, critic, and ent_coef Adam optimisers
    gamma: float      = 0.999   # discount factor — demand charge is a monthly signal (§5 "Why γ=0.999")
    batch_size: int   = 512     # mini-batch size for SAC gradient updates
    buffer_size: int  = 1_000_000  # replay buffer capacity (env-step tuples)
    tau: float        = 0.005   # Polyak target-network update coefficient
    ent_coef: str | float = "auto"  # entropy coefficient; "auto" = dual-variable auto-tuning
    total_env_steps: int = 500_000  # total environment steps over the training run (§5)

    # --- Parallelism ---
    n_envs: int = 4096   # number of vmapped parallel environments (§7 "vmap 4096 envs")
                         # MUST be a power of 2 ≥ 1; implementations MAY reduce for CPU-only runs
                         # but MUST document the actual value in telemetry (env_steps_per_sec)

    # --- Episode config (D3) ---
    episode_len: int      = 168   # 7-day training episode (168 steps at Δt=1 h)
    eval_episode_len: int = 8760  # full 365-day eval (8760 steps at Δt=1 h)

    # --- VecNormalize (§5, §7) ---
    norm_obs: bool    = True   # normalise observations with running mean/std
    norm_reward: bool = True   # normalise reward during training only; eval uses raw reward
    clip_obs: float   = 10.0   # clip normalised obs to ±clip_obs
    clip_reward: float = 10.0  # clip normalised reward to ±clip_reward

    # --- Actor architecture ---
    # SAC MLP actor and twin-Q critic, both with the same hidden sizes.
    # These default to the §5 / sbx defaults; changing them requires a new DECISION.
    hidden_sizes: tuple[int, ...] = (256, 256)  # shared for actor and critic

    # --- Training logistics ---
    eval_every_steps: int  = 10_000   # run a full eval every this many env steps
    log_every_steps: int   = 1_000    # emit a train_metrics message every this many env steps
    seed: int              = 42       # master PRNG seed for reproducibility
    run_id: str            = ""       # assigned at run start (UUID); passed through to telemetry
    site_config_id: str    = "site_gansu"  # site YAML basename used for training (e.g. "site_gansu")
                                           # Carried in checkpoint run_config_json for UI provenance
                                           # (contracts/shared/checkpoint_format.md §4.1)
```

### 3.1 Constraints

- `gamma` MUST be 0.999. Any PR that lowers it requires a new rl-architect DECISION (demand charge is a monthly signal; §5 "Why γ=0.999").
- `total_env_steps` MUST be ≥ 500 000 for a production run; shorter values are permitted only for unit-test smoke runs.
- `n_envs` × `total_env_steps / n_envs` = `total_env_steps` exactly — the loop terminates at `total_env_steps` regardless of how many complete episodes fit.

---

## 4. RunningStats (VecNormalize reimplemented as pure arrays)

§5 specifies `VecNormalize(norm_obs=True, norm_reward=True, clip 10)`. The original SB3
`VecNormalize` wraps Python Gym envs and tracks stats in NumPy. The JAX rebuild reimplement
this as **explicit JAX arrays** that can be saved with the checkpoint and loaded at inference —
no SB3 `.pkl` file, no Python state.

```python
from typing import NamedTuple
import jax.numpy as jnp

class RunningStats(NamedTuple):
    mean:  jax.Array   # shape (D,), float32 — running mean
    var:   jax.Array   # shape (D,), float32 — running (population) variance ≥ 0
    count: jax.Array   # scalar int32 — number of samples seen
```

The dimension `D` is determined by the caller:
- Obs stats: `D = 107` (jax_env_core contract §5.4: 107-dim observation vector)
- Reward stats: `D = 1`

### 4.1 Initialisation

```python
def init_running_stats(D: int) -> RunningStats:
    return RunningStats(
        mean  = jnp.zeros(D, dtype=jnp.float32),
        var   = jnp.ones(D, dtype=jnp.float32),   # start at 1 to avoid /0 before first update
        count = jnp.zeros((), dtype=jnp.int32),
    )
```

### 4.2 Batch update — Welford parallel algorithm

```python
def update_stats(stats: RunningStats, batch: jax.Array) -> RunningStats:
    """Update running stats with a new batch of shape (N, D) or (N,) for reward.

    Uses the Welford parallel (batch) algorithm — numerically stable,
    O(1) memory, order-independent within a single batch.
    """
    batch = jnp.atleast_2d(batch)       # (N, D)
    n = batch.shape[0]
    batch_mean = jnp.mean(batch, axis=0)
    batch_var  = jnp.var(batch, axis=0)  # population variance of this batch

    old_count  = stats.count.astype(jnp.float32)
    n_f        = jnp.float32(n)
    tot        = old_count + n_f

    delta    = batch_mean - stats.mean
    new_mean = stats.mean + delta * n_f / tot

    m_a      = stats.var * old_count
    m_b      = batch_var * n_f
    M2       = m_a + m_b + delta**2 * old_count * n_f / tot
    new_var  = M2 / tot                  # population variance over all samples seen so far

    return RunningStats(
        mean  = new_mean,
        var   = new_var,
        count = stats.count + n,
    )
```

**Edge case — count = 0 (first batch):**
The formula reduces correctly to `new_mean = batch_mean` and `new_var = batch_var` because
`m_a = 0` and `delta² * 0 * n / n = 0`.

### 4.3 Normalise + clip

```python
_EPS = 1e-8  # prevents /0 when var is exactly 0

def normalize_obs(obs: jax.Array, stats: RunningStats, clip: float = 10.0) -> jax.Array:
    """Normalise obs: (obs - mean) / std, clipped to [-clip, clip]."""
    std = jnp.sqrt(stats.var + _EPS)
    return jnp.clip((obs - stats.mean) / std, -clip, clip)

def normalize_reward(r: jax.Array, stats: RunningStats, clip: float = 10.0) -> jax.Array:
    """Normalise reward by std only (NOT shifted by mean) — SB3 VecNormalize convention."""
    std = jnp.sqrt(stats.var + _EPS)
    return jnp.clip(r / std, -clip, clip)
```

> **Why reward is normalised by std only (no mean shift):** SB3 VecNormalize normalises
> rewards by the standard deviation of the *return* (not per-step reward mean), but the
> standard implementation uses `r / std`. The mean is not subtracted because reward-mean
> information is needed to distinguish positive-sum from negative-sum episodes. This matches
> the SB3 default (`norm_obs=True, norm_reward=True`).

### 4.4 Eval mode

During eval (`run_eval`):
- `norm_obs` stats from training are applied to eval observations (shared, frozen — no update).
- `norm_reward` is **not** applied; the eval loop reports raw `reward` from `env.step()`.
- `stats` objects saved with the checkpoint MUST be loaded and used identically at inference.

---

## 5. Policy architecture (SAC MLP)

The actor and twin-Q critics are plain MLPs compatible with `flax.linen.Dense`.

### 5.1 Action space

Single scalar action: `a ∈ [-1, 1]`
- `+1` = charge battery at maximum rate (`bat_power_mw = 98.16 MW`)
- `-1` = discharge at maximum rate
- `0`  = idle

Deterministic eval policy: `a = tanh(actor_mean(obs))`. The env clips any out-of-range
value via `jnp.clip(a, -1, 1)` before computing physics (jax_env_core §5.3.3).

### 5.2 Actor network

```
Input:  obs (107,)
Dense(256) → ReLU
Dense(256) → ReLU
Dense(2)   → split into (mean, log_std_raw)
log_std = clip(log_std_raw, -5, 2)
std = exp(log_std)
# Stochastic (training): action = tanh(mean + std * N(0,1))
# Deterministic (eval):  action = tanh(mean)
```

### 5.3 Critic network (×2 for clipped double-Q)

```
Input: concat(obs (107,), action (1,)) = (108,)
Dense(256) → ReLU
Dense(256) → ReLU
Dense(1)   → Q-value scalar
```

### 5.4 Observation input to actor/critic

The 107-dim obs from `env.step()` is **normalised by `normalize_obs(obs, obs_stats)` before
being fed to the actor/critic**. The raw obs is stored in the replay buffer; normalisation
is applied at sample time (so stats updates are reflected on old data, matching SB3 behaviour).

---

## 6. Training loop — `train()`

```python
def train(
    config: RunConfig,
    key: jax.Array,               # master PRNG key
    data: SyntheticYear,          # pre-generated synthetic year — shape (8760, 4)
    emit_fn: Callable[[dict], None] | None = None,  # telemetry callback (push to websocket etc.)
) -> CheckpointData:
    """Run the §5 SAC training loop.

    Returns a CheckpointData with actor weights + normalisation stats + metadata.
    If emit_fn is provided, train_metrics and eval_compare dicts are passed to it
    at the configured cadence (log_every_steps and eval_every_steps).
    """
```

### 6.1 Training loop behaviour

1. **Env setup:** construct `N = config.n_envs` parallel environments via
   `jax.vmap(env.reset, in_axes=(0, None, None))` over a batch of keys.
   `EnvParams` uses `episode_len = config.episode_len` (168 for training).
   Episode start steps are drawn uniformly at random from `[0, 8760 - 168]` each reset, so
   the 7-day slice sees all seasons and tariff patterns (§5 "Why 7-day random-start episodes").

2. **Replay buffer:** capacity `config.buffer_size`. Stores raw (not normalised) obs tuples
   `(obs, action, reward, next_obs, done)`. Buffer is a circular FIFO backed by JAX arrays.

3. **Actor/critic update:** every env step, after storing to the buffer, sample a mini-batch
   of size `config.batch_size` and perform one SAC gradient update (1 actor + 2 critic + ent_coef
   updates via `optax.adam(lr=config.lr)`). This is the `train_freq=1, gradient_steps=1` §5 setting.

4. **VecNormalize:** `obs_stats` is updated after every rollout batch using `update_stats`.
   `reward_stats` is updated analogously. Normalised obs and rewards are used for actor/critic
   inputs and Q targets respectively. The raw (un-normalised) reward from `env.step()` is what
   is stored in the replay buffer and also what is accumulated for telemetry cost reporting.

5. **Target entropy** for auto ent_coef: `target_entropy = -action_dim = -1.0` (standard SAC).

6. **Eval cadence:** every `config.eval_every_steps` env steps, call `run_eval()` with the
   current checkpoint and emit an `eval_compare` telemetry message.

7. **Loop termination:** at exactly `config.total_env_steps` env steps consumed (across all
   envs, counting each vmapped step as `n_envs` steps). Partial episodes are abandoned; the
   loop does NOT run extra steps to complete a final episode.

8. **Final checkpoint:** written at the end of the run regardless of eval cadence (so the
   final model is always saved).

### 6.2 End-to-end on device

The rollout + buffer insert + gradient update MUST execute entirely on the JAX default device
with no Python-side host↔device copies per step. This is the §7 requirement ("end-to-end on
device — zero host↔device copies per step"). Concrete constraints:
- The env step, buffer insert, and SAC update are all inside a single `jax.jit` compiled region.
- Telemetry scalars (losses, reward, throughput) are extracted via `jax.device_get()` only at the
  configured telemetry cadence (every `log_every_steps` steps), not every step.

---

## 7. Baselines

Both baselines run via `run_baseline()` using the same JAX env for a fair comparison (§5 "in
`agents/baseline_agent.py`"; our equivalents are JAX-native policies). Baselines are evaluated
over the full 8760-step year with the deterministic policy fixed, no VecNormalize applied.

```python
def run_baseline(
    policy_name: str,           # "no_battery" | "rule_based_tou"
    data: SyntheticYear,        # same synthetic year used for RL eval
    params: EnvParams | None = None,   # None → Gansu defaults
) -> PolicyEvalResult:
    """Run one of the §5 baseline policies for a full eval year. Returns real-money costs."""
```

### 7.1 NoBatteryPolicy

```
action(obs, state) → 0.0   # always idle — no battery charge or discharge
```

Consequence: `p_bat_ch = p_bat_dis = 0` every step. Battery SOC stays at `soc_init = 0.5`.
No degradation cost. `c_degradation_yuan = 0` for the entire year.

### 7.2 TouPolicy (rule-based TOU)

Action purely based on `hour = t % 24` (looked up from `PRICE_TABLE_YPW` in jax_env_core):

| Hours | Price tier | Action |
|-------|-----------|--------|
| 0–6, 23 | Valley (250 ¥/MWh) | +1.0 (charge at max) |
| 7, 12–17 | Mid (450 ¥/MWh) | 0.0 (idle) |
| 8–10 | Peak (620 ¥/MWh) | −1.0 (discharge at max) |
| 11 | Critical peak (780 ¥/MWh) | −1.0 (discharge at max) |
| 18–20 | Critical/Peak (620–780) | −1.0 (discharge at max) |
| 21–22 | Peak (620 ¥/MWh) | −1.0 (discharge at max) |

The policy ignores SOC; the env's clip logic handles SOC bounds (D4). The policy is stateless:
`action(obs, t) = PRICE_TABLE_YPW[t % 24] > 450.0 ? -1.0 : (... == 250.0 ? +1.0 : 0.0)`.

Equivalently:
```python
price = PRICE_TABLE_YPW[t % 24]
action = jnp.where(price > 450.0, -1.0,   # peak / critical peak → discharge
         jnp.where(price < 450.0, +1.0,   # valley → charge
                                   0.0))  # mid → idle
```

---

## 8. Eval loop — `run_eval()`

```python
@dataclass
class PolicyEvalResult:
    """Real-money cost breakdown over a full evaluation year.

    All ¥ fields are real money (cost_total_real_yuan basis, D13).
    Additive identity: total_cost_yuan = energy_cost_yuan + demand_charge_yuan
                                         + degradation_yuan + curtailment_yuan + voll_yuan
    SOC/penalty fields are safety/reporting metrics and are NOT in total_cost_yuan.
    """
    energy_cost_yuan:     float   # Σ c_energy_yuan over 8760 steps (§3.4)
    demand_charge_yuan:   float   # Σ c_demand_charge_yuan (month-boundary steps only, D10)
    degradation_yuan:     float   # Σ c_degradation_yuan
    curtailment_yuan:     float   # Σ c_curtail_yuan
    voll_yuan:            float   # Σ c_voll_yuan
    total_cost_yuan:      float   # = sum of the 5 above (assertion in tests)
    soc_violations_count: int     # number of steps where soc_violation_mwh > 0
    soc_violation_mwh:    float   # total overshoot energy (MWh)
    penalty_yuan:         float   # total reward-shaping penalty (NOT in total_cost_yuan)

def run_eval(
    checkpoint: CheckpointData,
    data: SyntheticYear,
    params: EnvParams | None = None,    # None → Gansu defaults
) -> PolicyEvalResult:
    """Deterministic policy rollout over the full 8760-step year.

    - Uses actor weights and obs_stats from checkpoint.
    - Normalises obs using frozen obs_stats (no stat updates).
    - Reports RAW (un-normalised) reward / real-money costs.
    - eval_episode_len = 8760; no episode resets (the year runs to completion).
    - EnvParams.episode_len = 8760 so `done` fires only at t=8759.
    """
```

### 8.1 Eval invariants

1. **Deterministic:** eval always uses `action = tanh(actor_mean(normalized_obs))` — no sampling.
2. **Same data:** `data` is the same synthetic year used for training (caller's responsibility).
3. **Frozen stats:** `obs_stats` from the checkpoint are NOT updated during eval.
4. **Raw reward:** the cumulative `reward` from `env.step()` is summed but not used for the
   PolicyEvalResult — only the real-money cost fields from `EnvInfo` are used.
5. **Honest reporting:** if RL `total_cost_yuan > baseline total_cost_yuan`, the eval still runs
   to completion, the numbers are reported as-is, and the telemetry `eval_compare` message is
   emitted honestly (§5 "Report results honestly: if the agent does not beat the rule-based
   baseline, say so with the numbers").

---

## 9. Telemetry emission

This module is a **telemetry producer**. All emitted messages MUST:
1. Conform to the LOCKED schema `contracts/shared/telemetry_schema.md` v1.0.0 (D18).
2. Pass `energy_go.telemetry.validate(msg)` with zero errors (the Python validator, task #8).
3. Be validated in the test suite using the `validate-telemetry` skill (mandatory per training-engineer charter).

```python
def build_train_metrics(
    global_step: int,
    wall_seconds: float,
    env_steps_per_sec: float,
    actor_loss: float,
    critic_loss: float,
    ent_coef: float,
    reward_scaled_mean: float,           # mean of ×1e-5 scaled env reward over the log window
    reward_norm_mean: float | None,      # VecNormalize-normalised reward; None at eval checkpoints
    cost_total_real_mean_yuan: float,    # mean per-episode real-money cost over the log window
    is_eval_checkpoint: bool,
    checkpoint_id: str | None,
    run_id: str,
) -> dict:
    """Build a telemetry envelope with kind='train_metrics'.

    Returns a dict conforming to telemetry_schema.md envelope + train_metrics payload.
    Does NOT emit (caller decides transport).
    """

def build_eval_compare(
    eval_horizon_steps: int,
    checkpoint_id: str,
    rl: PolicyEvalResult,
    no_battery: PolicyEvalResult,
    rule_based_tou: PolicyEvalResult,
    run_id: str,
) -> dict:
    """Build a telemetry envelope with kind='eval_compare'.

    cost_basis is 'real_money' per LOCKED schema.
    Additive identity for each policy is asserted before returning:
      total_cost_yuan == energy_cost + demand_charge + degradation + curtailment + voll
    Raises AssertionError if the identity fails (producer fault, not consumer fault).
    """
```

### 9.1 Envelope fields

The envelope is defined by `contracts/shared/telemetry_schema.md`:
- `schema_version`: `"1.0.0"`
- `kind`: `"train_metrics"` or `"eval_compare"`
- `ts_utc`: ISO-8601 UTC wall-clock time of emission
- `run_id`: `config.run_id` (assigned before `train()` is called)
- `seq`: monotonically increasing integer per `(run_id, kind)` across the run

### 9.2 Acceptance gate

The test suite MUST include at least one test that:
1. Calls `build_train_metrics(...)` with concrete values.
2. Calls `build_eval_compare(...)` with concrete values.
3. Passes both messages through `energy_go.telemetry.validate` and asserts the error list is empty.

---

## 10. Checkpoint cross-reference

`CheckpointData` is the return type of `train()` and the input to `run_eval()`. Its fields are
specified in `contracts/training/checkpoint_format.md` (task #20). For this contract, the
required fields are:

```python
# Minimum required by run_eval() and serving layer — must be present in CheckpointData:
checkpoint.actor_params   # Flax param dict (or equivalent) for the actor MLP (§5.2)
checkpoint.obs_stats      # RunningStats for the obs (D=107); frozen during eval
checkpoint.run_config     # RunConfig used for this training run
checkpoint.global_step    # int — env steps consumed when checkpoint was saved
checkpoint.checkpoint_id  # str — UUID; ties telemetry train_metrics to checkpoint
```

The save/load round-trip MUST produce **identical actions** on any fixed obs:
```python
# After save + load:
a1 = deterministic_action(checkpoint_before, obs)
a2 = deterministic_action(checkpoint_after,  obs)
assert jnp.allclose(a1, a2, atol=1e-6)
```

---

## 11. §5 package identity — `sbx-rl` vs `sbx` on PyPI (task #11)

**`sbx` on PyPI (version 0.1.x) is the StudyBox terminal flashcard application — NOT the
SB3-in-JAX library.** The correct PyPI name for Stable-Baselines3-in-JAX is `sbx-rl` (latest
0.26.0 as of 2026-06-10). Any `pyproject.toml` dependency on `sbx` installs the wrong package.

The training implementation MAY use `sbx-rl` (SAC actor/critic networks) combined with a
custom JAX rollout loop, OR it MAY implement the full SAC loop natively using `flax` + `optax`
+ `flashbax` without `sbx-rl`. Both options are valid as long as:
1. Actor/critic architecture matches §5.2–5.3.
2. Hyperparameters match RunConfig defaults.
3. End-to-end on device with no per-step H↔D copies.
4. The vmap ≥ 4096 envs requirement is met.

`STACK.md` must be updated to clarify `sbx-rl` (not `sbx`) as the optional PyPI dependency name
in the same PR as this contract. `pyproject.toml` optional extras `[training]` MUST list `sbx-rl`
(NOT `sbx`).

---

## 12. Deliberate deviations from §5/§6

| Behaviour | Old (§5/SB3) | New (JAX rebuild) | Reason |
|---|---|---|---|
| `DummyVecEnv` (4 envs) | SB3 `DummyVecEnv` with 4 Python env copies | `jax.vmap` over ≥4096 env states on device | §7 "vmap 4096 envs"; end-to-end on device |
| `VecNormalize` as SB3 object | SB3 `VecNormalize` with `.pkl` file | `RunningStats` NamedTuple in JAX, saved as part of checkpoint (npz) | §7 "Keep VecNormalize logic as explicit running-stat arrays" |
| `train_freq=1, gradient_steps=1` | SB3 per-env-step | Same policy, JAX-native | Direct port |
| Python `DummyVecEnv` env | `PowerEnv` (Python) | `energy_go.env.jax_env.step()` + `reset()` (JAX) via import path `energy_go.env.jax_env` | D22b |

---

## 13. Out of scope

- §10 Tier 1 enhancements (E2 SOC/temperature efficiency, E5 forecast-error regime) — DEFERRED until JAX baseline parity (D17, D22c)
- ONNX export of actor weights — serving layer (see `contracts/serving/`)
- Hyperparameter sweeps (env-harness-engineer) — separate contract
- Multi-site / §8 composable assets — after §3 baseline (D2)
- PPO or other algorithms — SAC only per §5
- Distributed training (multi-GPU/multi-host) — out of v1 scope
