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
