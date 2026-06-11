# Review record — `contracts/training/eval_envstate_obs_fix.md` (PR #72)

**Reviewer:** backend-reviewer
**Feature:** eval.py `carry.obs` → `get_obs()` fix (EnvState has no `.obs`)
**Tests:** `tests/training/test_training_eval_envstate_obs_fix.py` (4, all `@pytest.mark.slow`)

## Verdict: APPROVE (contract + tests gate @ bab6f19)

### Bug + fix verified against main
- `eval.py:_step` L117 `raw_obs = carry.obs` — `carry` is the `EnvState` (L116), and
  `EnvState` is a NamedTuple of `(soc, month_peak, t, rng)` only — no `.obs`. Raises
  `AttributeError` on the first `_step`. Latent since PR #40 (eval predated EnvState's
  finalised API in PR #33); surfaced by task #42 smoke testing.
- Fix: `raw_obs = get_obs(env_state, env_params, data)` + add `get_obs` to the
  `from energy_go.env.jax_env import …` line. Verified:
  - `get_obs(state, params, data)` signature on main (jax_env.py L166) matches.
  - `env_state` (L116), `env_params` (L91), `data` (run_eval param, closure) are all in
    `_step`'s scope.
  - **No latent carry bug:** `_step` returns `(new_state, info)` → `lax.scan` threads the
    carry to `new_state`, so the rollout advances correctly once the AttributeError is gone
    (checked specifically — an unmasked stuck-at-step-0 bug, like the make_item_buffer case,
    is NOT present here).

### Tests
- `test_run_eval_returns_policy_eval_result` — primary regression (no AttributeError). Solid.
- `test_run_eval_additive_identity` — `total == energy+demand+degradation+curtailment+voll`,
  atol 0.1. Matches eval's `total_cost_yuan` decomposition (L136); penalty/SOC correctly
  excluded per D13. (Note: near-tautological since `total` is *constructed* as that sum —
  harmless, documents the invariant + guards refactor divergence.)
- `test_run_eval_obs_stats_frozen_during_rollout` — two calls, same checkpoint+data →
  identical total (frozen stats / determinism). Good.
- `test_run_eval_full_year_length` — `total != 0` (confirms 8760-step scan ran). Good.
- All 4 `@pytest.mark.slow` (D30-consistent — full-year JIT scan).

### No reviewer-added cases
Coverage is proportionate to a one-line fix: the primary regression is pinned, the cost
identity + determinism + full-year-length round it out. A full-year hand-computed total isn't
feasible to add. Approved suite = developer's 4.

### Non-blocking
- The additive-identity test is internally tautological; a stronger (optional) check would
  cross-validate `total_cost` against an independent sum (e.g. `Σ infos.cost_total_real_yuan`)
  — only if that field's D13 decomposition matches these 5 terms.
