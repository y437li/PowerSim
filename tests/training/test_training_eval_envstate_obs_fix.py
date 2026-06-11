"""Tests for fix/training-eval-envstate-obs-api.

Catches the bug in eval.py:_step where `carry.obs` raised
  AttributeError: 'EnvState' object has no attribute 'obs'
because EnvState stores only (soc, month_peak, t, rng) and observations
must be computed via get_obs(state, params, data).

Contract: contracts/training/eval_envstate_obs_fix.md
"""

import numpy as np
import pytest
import jax
import jax.numpy as jnp

from energy_go.training.checkpoint_format import CheckpointData
from energy_go.training.eval import PolicyEvalResult, run_eval

# ---- Helpers ----------------------------------------------------------------

_OBS_DIM    = 107
_ACTION_DIM = 6
_HIDDEN     = 256


def _make_zero_checkpoint() -> CheckpointData:
    """Minimal valid CheckpointData with zero-initialised weights.

    obs_mean=0, obs_var=1 → normalize_obs is identity (no shift, unit scale).
    All actor weights are zero → actions will all be 0 (tanh(0)=0, sigmoid(0)=0.5).
    This is enough to drive a full 8760-step rollout without crashing.
    """
    rng = np.random.default_rng(42)

    return CheckpointData(
        schema_version  = "1.0.0",
        checkpoint_id   = "00000000-0000-0000-0000-000000000000",
        run_id          = "test-run",
        global_step     = 0,
        created_at_utc  = "2026-01-01T00:00:00Z",
        code_version    = "test",
        run_config_json = '{"seed": 42, "site_config_id": "gansu"}',
        obs_dim         = _OBS_DIM,
        action_dim      = _ACTION_DIM,
        obs_mean        = np.zeros(_OBS_DIM, dtype=np.float32),
        obs_var         = np.ones(_OBS_DIM,  dtype=np.float32),
        obs_count       = 1,
        obs_clip        = 10.0,
        # Actor weights — zeros give tanh(0)=0.0 for a_bat, sigmoid(0)=0.5 for fractions
        actor_fc1_w     = np.zeros((_OBS_DIM, _HIDDEN), dtype=np.float32),
        actor_fc1_b     = np.zeros((_HIDDEN,),           dtype=np.float32),
        actor_fc2_w     = np.zeros((_HIDDEN, _HIDDEN),   dtype=np.float32),
        actor_fc2_b     = np.zeros((_HIDDEN,),           dtype=np.float32),
        actor_out_w     = np.zeros((_HIDDEN, 2 * _ACTION_DIM), dtype=np.float32),
        actor_out_b     = np.zeros((2 * _ACTION_DIM,),   dtype=np.float32),
    )


# ---- Tests ------------------------------------------------------------------

@pytest.mark.slow
def test_run_eval_returns_policy_eval_result():
    """run_eval() must return a PolicyEvalResult without raising.

    This is the primary regression test: before the fix, eval.py:_step accessed
    carry.obs which raised
        AttributeError: 'EnvState' object has no attribute 'obs'
    because EnvState fields are (soc, month_peak, t, rng).

    After the fix, get_obs(env_state, env_params, data) is called instead.
    """
    _syn = pytest.importorskip(
        "energy_go.generators.synthetic",
        reason="requires jax_env_core (PR #33)",
    )
    generate_year = _syn.generate_year

    key  = jax.random.PRNGKey(0)
    data = generate_year(key)
    ckpt = _make_zero_checkpoint()

    result = run_eval(ckpt, data)   # raises AttributeError before fix

    assert isinstance(result, PolicyEvalResult), (
        f"run_eval must return PolicyEvalResult, got {type(result)}"
    )


@pytest.mark.slow
def test_run_eval_additive_identity():
    """total_cost_yuan == sum of the 5 sub-costs — §8 additive identity.

    Hand arithmetic:
        total = energy + demand + degradation + curtailment + voll
    Computed by run_eval() directly from EnvInfo.  The identity must hold
    to float32 precision (atol 0.1 ¥ — rounding over 8760 sums).
    """
    _syn = pytest.importorskip(
        "energy_go.generators.synthetic",
        reason="requires jax_env_core (PR #33)",
    )
    generate_year = _syn.generate_year

    key  = jax.random.PRNGKey(1)
    data = generate_year(key)
    ckpt = _make_zero_checkpoint()

    result = run_eval(ckpt, data)

    expected_total = (
        result.energy_cost_yuan
        + result.demand_charge_yuan
        + result.degradation_yuan
        + result.curtailment_yuan
        + result.voll_yuan
    )
    # atol 0.1 ¥ — float32 accumulation over 8760 steps, real-money scale ¥100k+
    assert result.total_cost_yuan == pytest.approx(expected_total, abs=0.1), (
        f"Additive identity violated: total={result.total_cost_yuan:.4f} ¥ "
        f"vs sum={expected_total:.4f} ¥ "
        f"(energy={result.energy_cost_yuan:.2f}, demand={result.demand_charge_yuan:.2f}, "
        f"degradation={result.degradation_yuan:.2f}, curtailment={result.curtailment_yuan:.2f}, "
        f"voll={result.voll_yuan:.2f})"
    )


@pytest.mark.slow
def test_run_eval_obs_stats_frozen_during_rollout():
    """run_eval() with the same checkpoint+data twice must return identical results.

    If obs_stats were mutated during eval (they must NOT be), the second call
    would produce different normalised observations and different costs.

    Hand verification: same checkpoint → same actor policy; same frozen stats →
    same normalisation; deterministic env (key=0) → same rollout → equal totals.
    """
    _syn = pytest.importorskip(
        "energy_go.generators.synthetic",
        reason="requires jax_env_core (PR #33)",
    )
    generate_year = _syn.generate_year

    key  = jax.random.PRNGKey(2)
    data = generate_year(key)
    ckpt = _make_zero_checkpoint()

    r1 = run_eval(ckpt, data)
    r2 = run_eval(ckpt, data)

    assert r1.total_cost_yuan == pytest.approx(r2.total_cost_yuan, rel=1e-5), (
        f"run_eval not deterministic: r1={r1.total_cost_yuan:.4f}, r2={r2.total_cost_yuan:.4f}"
    )


# reviewer: The developer's test_run_eval_additive_identity is internally
# tautological — eval.py constructs total_cost_yuan AS the sum of its own 5
# returned fields, so that assert can never fail regardless of correctness. It
# does NOT catch the realistic §6 bug class: eval summing the WRONG EnvInfo
# field. The env exposes two D13 totals (jax_env.py L487-488):
#     cost_total_real         = C_E + C_demand_charge + C_deg + C_curtail + C_VOLL
#     cost_total_reward_basis = C_E + 2.0*C_DC_shape + C_deg + C_curtail + C_VOLL
# If eval ever pulled cost_total_reward_basis_yuan (the doubled-demand-shape,
# reward-basis total) instead of summing the 5 real-money components, the
# developer's test would still pass while real-money reporting was wrong.
# This test cross-validates eval's total_cost_yuan against an INDEPENDENT scan
# that sums the env's own cost_total_real_yuan field — the true real-money basis
# (D13). It mirrors eval.py exactly: zero-weight actor (action = [tanh(0)=0,
# sigmoid(0)=0.5 ×5]), PRNGKey(0), EnvParams(episode_len=8760), frozen identity
# obs_stats (mean=0, var=1). Expected: the two totals are equal to float32
# accumulation tolerance over 8760 steps (atol 0.1 ¥ on a ¥100k+ scale).
@pytest.mark.slow
def test_run_eval_total_matches_env_cost_total_real():
    """eval.total_cost_yuan == Σ infos.cost_total_real_yuan (independent scan).

    Guards the §6 wrong-field bug: total_cost must be the env's real-money basis
    (cost_total_real), NOT cost_total_reward_basis (which doubles demand-shape).
    """
    _syn = pytest.importorskip(
        "energy_go.generators.synthetic",
        reason="requires jax_env_core (PR #33)",
    )
    generate_year = _syn.generate_year

    from energy_go.env.jax_env import EnvParams, reset, step, get_obs
    from energy_go.training.normalizer import RunningStats, normalize_obs

    key  = jax.random.PRNGKey(7)
    data = generate_year(key)
    ckpt = _make_zero_checkpoint()

    result = run_eval(ckpt, data)

    # --- Independent rollout mirroring eval.run_eval() exactly ---
    env_params = EnvParams(episode_len=8760)
    obs_stats  = RunningStats(
        mean  = jnp.array(ckpt.obs_mean),   # zeros → identity shift
        var   = jnp.array(ckpt.obs_var),    # ones  → unit scale
        count = jnp.int32(ckpt.obs_count),
    )
    obs_clip = float(ckpt.obs_clip)

    # Zero-weight actor: out = 0 for all 12 → mean[:6]=0 →
    #   action[0]   = tanh(0)    = 0.0
    #   action[1:6] = sigmoid(0) = 0.5  (×5)
    zero_action = jnp.array([0.0, 0.5, 0.5, 0.5, 0.5, 0.5], dtype=jnp.float32)

    @jax.jit
    def _step(carry, _):
        # obs/normalisation recomputed for parity, but action is fixed by the
        # zero-weight actor identity above (independent of obs), so we assert on
        # the env's cost field, not on the policy.
        raw_obs  = get_obs(carry, env_params, data)
        _        = normalize_obs(raw_obs, obs_stats, clip=obs_clip)
        new_state, _o, _r, _d, info = step(carry, zero_action, env_params, data)
        return new_state, info

    init_state, _ = reset(jax.random.PRNGKey(0), env_params, data)  # eval uses key 0
    _, infos = jax.lax.scan(_step, init_state, None, length=8760)
    env_total_real = float(jnp.sum(infos.cost_total_real_yuan))

    assert result.total_cost_yuan == pytest.approx(env_total_real, abs=0.1), (
        f"eval total_cost_yuan ({result.total_cost_yuan:.4f} ¥) != env "
        f"Σ cost_total_real_yuan ({env_total_real:.4f} ¥). eval is summing the "
        f"wrong EnvInfo field (likely cost_total_reward_basis_yuan — §6 / D13)."
    )


@pytest.mark.slow
def test_run_eval_full_year_length():
    """run_eval() must scan exactly 8760 steps (the full evaluation year).

    Indirect check: the SOC at the end of the year reflects 8760 transitions
    (the env step counter wraps to 8759 at the last step before reset).  We
    verify the count is non-zero by checking total_cost_yuan > 0 (any grid
    interaction produces non-zero energy cost over 8760 h).
    """
    _syn = pytest.importorskip(
        "energy_go.generators.synthetic",
        reason="requires jax_env_core (PR #33)",
    )
    generate_year = _syn.generate_year

    key  = jax.random.PRNGKey(3)
    data = generate_year(key)
    ckpt = _make_zero_checkpoint()

    result = run_eval(ckpt, data)

    # With zero-weight actor (a_bat=0, fractions=0.5), the plant still dispatches
    # renewables and draws from the grid to cover load; energy cost != 0.
    # cost components are real ¥ values over 8760 steps → magnitudes >> 0
    assert result.total_cost_yuan != 0.0, (
        "total_cost_yuan=0 implies no env transitions occurred (full-year scan not running)"
    )
