# Review record — `contracts/training/eval_envstate_obs_fix.md` (PR #72)

**Reviewer:** backend-reviewer (independent review by the assigned reviewer; this
record is the reviewer's artifact and supersedes the earlier copy committed under
developer commit f0c3e7b)
**Feature:** eval.py `carry.obs` → `get_obs()` fix (EnvState has no `.obs`)
**Stage:** Stage 1 — contract + tests gate
**Tests reviewed @:** developer commit `bab6f19`
**Approved suite:** developer's 4 tests (`bab6f19`) + reviewer's 1 added case (PR head)

## Verdict: APPROVE (contract + tests gate)

### Bug + fix verified against source (not the summary)
- `eval.py:_step` L116-117: `env_state = carry; raw_obs = carry.obs`. `EnvState`
  (jax_env.py L58-63) is a NamedTuple of `(soc, month_peak, t, rng)` only — no
  `.obs`. Confirmed `AttributeError` on the first `_step`. Latent since PR #40;
  surfaced by task #42 smoke testing after PR #33 finalised the EnvState API.
- Proposed fix `raw_obs = get_obs(env_state, env_params, data)`:
  - `get_obs(state, params, data)` signature confirmed at jax_env.py L166-170 —
    matches the call.
  - `env_params` (L91), `data` (closure), `env_state` (L116) all in `_step` scope.
  - **Consistency:** `step()` itself computes `obs = get_obs(state, params, data)`
    for the INPUT state (jax_env.py L259, §5.4). eval's external `get_obs` on the
    same state yields the identical 107-dim vector; RNG derived deterministically
    from `state.rng` inside `get_obs` (L201 split). Determinism preserved.
  - **No latent stuck-at-step-0 bug:** `step` returns `new_state` with `t = t+1`
    (L501) and `rng = new_rng` (L502, third child of the L452 split). `lax.scan`
    threads `new_state` → rollout advances 0→8759 with evolving RNG. Verified.
- **EnvInfo fields** referenced by eval all exist verbatim in `EnvInfo`
  (jax_env.py L106-159): `c_energy_yuan`, `c_demand_charge_yuan`,
  `c_degradation_yuan`, `c_curtail_yuan`, `c_voll_yuan`, `soc_violation_mwh`,
  `penalty_yuan`. No silent field/unit mismatch in the accumulation block.

### Developer tests (4, all `@pytest.mark.slow`)
- `test_run_eval_returns_policy_eval_result` — primary regression (no
  AttributeError + return type). **Pins the bug. Solid.**
- `test_run_eval_additive_identity` — `total == energy+demand+degradation+
  curtailment+voll`, atol 0.1 ¥. **Internally tautological** — eval constructs
  `total_cost_yuan` AS exactly that sum (eval.py L136-139), so it cannot fail on a
  correctness regression; only guards refactor divergence. Harmless. Closed by the
  reviewer-added case below.
- `test_run_eval_obs_stats_frozen_during_rollout` — two calls, same
  checkpoint+data → identical total (frozen stats + fixed `PRNGKey(0)` →
  determinism). **Real check. Good.**
- `test_run_eval_full_year_length` — `total != 0` (8760-step scan ran, not
  vacuous). Weak indirect proxy but acceptable for a one-liner. Good.

### Reviewer-added case (marked `# reviewer:` in the test file)
- `test_run_eval_total_matches_env_cost_total_real` — cross-validates eval's
  `total_cost_yuan` against an INDEPENDENT 8760-step scan summing the env's own
  `cost_total_real_yuan` field (the D13 real-money basis, jax_env.py L487).
  - **Why:** the developer's additive-identity test is tautological and cannot
    catch the realistic §6 wrong-field bug — eval pulling
    `cost_total_reward_basis_yuan` (which doubles demand-shape, L488:
    `C_E + 2.0*C_DC_shape + …`) instead of summing the 5 real-money components.
    That would corrupt real-money reporting while the developer's test still
    passed. This case pins eval to the correct env total.
  - **Hand-derivation:** independent scan mirrors `run_eval` exactly — zero-weight
    actor ⇒ `action = [tanh(0)=0, sigmoid(0)=0.5 ×5]`, `reset(PRNGKey(0))`,
    `EnvParams(episode_len=8760)`, identity obs_stats (mean=0, var=1, clip=10).
    Identical trajectory ⇒ `Σ cost_total_real_yuan` must equal eval's
    `total_cost_yuan` to float32 accumulation tolerance (atol 0.1 ¥ over 8760
    steps, ¥100k+ scale). Arithmetic shown in the test's `# reviewer:` block.
  - Depends on the fix (calls `run_eval`): errors pre-fix, asserts post-fix —
    correct regression behaviour.
  - Local runtime not exercised (local toolchain broken: numpy x86_64/arm64 arch
    mismatch under stale Python 3.9). CI toolchain is Python 3.11 via uv and is
    green at `bab6f19`; the added case uses only verified symbols and parses clean
    (`ast.parse` OK). Runtime is CI's responsibility under the slow-test policy.

### Notes for Stage 2 (implementation)
- The fix must add `get_obs` to the `from energy_go.env.jax_env import …` line in
  `run_eval()` (currently `EnvParams, reset, step` only, eval.py L89).
- Do not alter the `carry = EnvState` scan signature (contract §6, out-of-scope).

**Approved suite = developer's 4 tests + reviewer's 1 = 5 cases.**
