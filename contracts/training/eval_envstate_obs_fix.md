# Fix: eval.py `carry.obs` — EnvState has no `obs` attribute

**Area:** training  
**Branch:** `fix/training-eval-envstate-obs-api`  
**Fixes:** bug in `src/energy_go/training/eval.py` introduced in PR #40  
**Spec sections:** §5.4 (obs computed at beginning of step), §7 (JAX env API)

---

## 1. Bug description

`eval.py:_step` (line 117 on main) does:

```python
raw_obs = carry.obs  # depends on jax_env_core EnvState API
```

`EnvState` is a `NamedTuple` with fields `soc, month_peak, t, rng` only — no `obs`
field. Observations are computed on-the-fly by `get_obs(state, params, data)`.
This raises `AttributeError: 'EnvState' object has no attribute 'obs'` at eval
time, which was caught during task #42 smoke testing (post-PR #33 merge).

## 2. Root cause

`eval.py` was written before `EnvState`'s API was finalised (PR #33). The code
assumed `EnvState` would store the computed observation as a field. The JAX env
core instead computes observations on demand via `get_obs()`, which is already
exported by `energy_go.env.jax_env`.

## 3. Fix

Replace the single buggy line in `_step` with a call to `get_obs`:

```python
# Before (buggy — EnvState has no .obs attribute):
raw_obs = carry.obs

# After (correct — §5.4: obs computed from state at beginning of step):
raw_obs = get_obs(env_state, env_params, data)
```

And add `get_obs` to the local import inside `run_eval()`:

```python
from energy_go.env.jax_env import EnvParams, reset, step, get_obs  # D22b import path
```

No other changes to `eval.py`. Behaviour is unchanged on a correctly working run —
this is a pure API-call fix.

## 4. Interfaces

### `get_obs` signature (from `energy_go.env.jax_env`)

```python
def get_obs(
    state: EnvState,
    params: EnvParams,
    data: jax.Array,  # SyntheticYear, shape (8760, N_FEAT)
) -> jax.Array:       # float32, shape (107,)
```

Called internally by `step()` (§5.4: obs of the INPUT state) and by `reset()`.
Same RNG derivation as inside `step()` so forecast noise is always independent
from the price-spread draw.

### `eval.py:_step` after fix

```python
@jax.jit
def _step(carry, _):
    env_state = carry
    raw_obs = get_obs(env_state, env_params, data)   # ← fixed; was carry.obs
    norm_obs = normalize_obs(raw_obs, obs_stats, clip=obs_clip)
    action = _deterministic_action(actor_params, norm_obs)
    new_state, new_obs, reward, done, info = step(env_state, action, env_params, data)
    return new_state, info
```

## 5. Behaviour / edge cases

- **Normal operation:** `get_obs(env_state, env_params, data)` produces the same
  107-dim observation vector that `step()` would compute for the same state.
  Determinism and reproducibility are preserved.
- **t=0 (first step of year):** `get_obs` at t=0 uses `data[0, :]` — no boundary
  issue; `EnvState.t` starts at 0 after `reset()`.
- **t=8759 (last step):** `get_obs` at t=8759 — `data[8759, :]` is valid.
- **Frozen obs_stats:** eval does NOT call `update_stats`; `obs_stats` are loaded
  from checkpoint and never mutated inside `_step`. Unchanged by this fix.
- **jax.lax.scan compatibility:** `carry` remains the bare `EnvState` NamedTuple
  (not a `(state, obs)` pair), so the scan signature is unchanged.

## 6. Out of scope

- Any change to `EnvState` fields — the env is locked (PR #33 merged).
- Any change to `run_eval`'s return type or the `PolicyEvalResult` fields.
- Any change to how `step()` computes observations.

## 7. Test coverage requirement

A new integration test `test_run_eval_returns_policy_eval_result` must call
`run_eval()` with a randomly-initialised `CheckpointData` (correct weight shapes,
obs_mean=0, obs_var=1) and a synthetic year, and assert:
1. The call does not raise (catches `AttributeError: ... has no attribute 'obs'`).
2. The return type is `PolicyEvalResult`.
3. `total_cost_yuan == energy_cost_yuan + demand_charge_yuan + degradation_yuan
   + curtailment_yuan + voll_yuan` (additive identity, §8).

Marked `@pytest.mark.slow` (JIT-compiles 8760-step scan).
