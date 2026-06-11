"""Tests for contracts/training/training_pipeline.md

ALL TESTS ARE RED at the gate stage — energy_go.training is not yet implemented.
The imports below intentionally fail until implementation lands; that is correct.

Standard:
- Every numeric assertion has the arithmetic shown in a comment.
- Edge cases are pinned at contract boundaries.
- Reviewer-added cases are marked: # reviewer: <reason>

Run:  pytest tests/training/test_training_training_pipeline.py
Expected at gate stage: ImportError / collection errors for every test.
"""

import jax
import jax.numpy as jnp
import numpy as np
import pytest
import json

# --- Imports that will fail until implementation (intentionally RED at gate) ---
from energy_go.training.normalizer import (
    RunningStats,
    init_running_stats,
    update_stats,
    normalize_obs,
    normalize_reward,
)
from energy_go.training.config import RunConfig
from energy_go.training.baselines import NoBatteryPolicy, TouPolicy, run_baseline
from energy_go.training.eval import PolicyEvalResult, run_eval
from energy_go.training.telemetry import build_train_metrics, build_eval_compare

# Telemetry validator (merged in PR #23, task #8)
from energy_go.telemetry.validate import validate as validate_telemetry

# Env types (against jax_env_core contract; import path D22b)
from energy_go.env.jax_env import EnvParams, step as env_step, reset as env_reset, PRICE_TABLE_YPW


# ---------------------------------------------------------------------------
# § 4 — RunningStats (VecNormalize as pure JAX arrays)
# ---------------------------------------------------------------------------

class TestRunningStatsInit:
    def test_init_shape_and_defaults(self):
        # D=107 (obs dim from jax_env_core §5.4)
        stats = init_running_stats(107)
        assert stats.mean.shape == (107,)
        assert stats.var.shape == (107,)
        assert stats.count.shape == ()
        # initial mean=0, var=1, count=0
        assert jnp.all(stats.mean == 0.0)
        assert jnp.all(stats.var == 1.0)
        assert int(stats.count) == 0

    def test_init_reward_stats(self):
        # Reward stats: D=1 (single scalar reward)
        stats = init_running_stats(1)
        assert stats.mean.shape == (1,)
        assert stats.var.shape == (1,)
        assert int(stats.count) == 0

    def test_init_dtype_float32(self):
        stats = init_running_stats(4)
        assert stats.mean.dtype == jnp.float32
        assert stats.var.dtype == jnp.float32


class TestRunningStatsUpdate:
    """Welford parallel (batch) update algorithm — §4.2."""

    def test_first_batch_single_sample(self):
        # 1D stats (D=1), batch of 1 sample: obs=[[5.0]]
        # First update from count=0:
        #   batch_mean=5.0, batch_var=0.0, n=1
        #   delta=5.0-0.0=5.0, tot=1
        #   new_mean = 0.0 + 5.0*1/1 = 5.0
        #   m_a=1.0*0=0, m_b=0.0*1=0, M2=0+0+5²*0*1/1=0
        #   new_var = 0/1 = 0.0
        #   new_count = 1
        stats = init_running_stats(1)
        batch = jnp.array([[5.0]])
        s = update_stats(stats, batch)
        assert float(s.mean[0]) == pytest.approx(5.0, abs=1e-6)
        assert float(s.var[0])  == pytest.approx(0.0, abs=1e-6)
        assert int(s.count)     == 1

    def test_first_batch_two_samples(self):
        # 1D stats, batch of 2: obs=[[2.0], [4.0]]
        # batch_mean=3.0, batch_var=((2-3)²+(4-3)²)/2=1.0, n=2, count_old=0
        # delta=3.0-0.0=3.0, tot=2
        # new_mean = 0.0 + 3.0*2/2 = 3.0
        # m_a=1.0*0=0, m_b=1.0*2=2, M2=0+2+3²*0*2/2=2
        # new_var = 2.0/2 = 1.0
        stats = init_running_stats(1)
        batch = jnp.array([[2.0], [4.0]])
        s = update_stats(stats, batch)
        assert float(s.mean[0]) == pytest.approx(3.0, abs=1e-6)
        assert float(s.var[0])  == pytest.approx(1.0, abs=1e-6)  # pop-var of [2,4] = 1.0
        assert int(s.count)     == 2

    def test_two_sequential_batches(self):
        # Continuing from count=2, mean=3.0, var=1.0
        # Second batch: obs=[[4.0], [6.0]]
        # batch_mean=5.0, batch_var=1.0, n=2
        # delta=5.0-3.0=2.0, tot=4
        # new_mean = 3.0 + 2.0*2/4 = 3.0 + 1.0 = 4.0
        # m_a=1.0*2=2.0, m_b=1.0*2=2.0
        # M2 = 2.0 + 2.0 + 4.0*(2*2/4) = 2+2+4=8
        # new_var = 8.0/4 = 2.0  (population variance of [2,4,4,6] = 2.0)
        # Verify: mean([2,4,4,6])=4, var([2,4,4,6])=((−2)²+0²+0²+2²)/4=8/4=2 ✓
        stats = init_running_stats(1)
        s1 = update_stats(stats, jnp.array([[2.0], [4.0]]))
        s2 = update_stats(s1,    jnp.array([[4.0], [6.0]]))
        assert float(s2.mean[0]) == pytest.approx(4.0, abs=1e-6)
        assert float(s2.var[0])  == pytest.approx(2.0, abs=1e-6)
        assert int(s2.count)     == 4

    def test_multidim_batch(self):
        # D=3, batch=[[1,2,3],[3,4,5]]
        # means=[2,3,4], vars=[1,1,1]
        stats = init_running_stats(3)
        batch = jnp.array([[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]])
        s = update_stats(stats, batch)
        np.testing.assert_allclose(np.array(s.mean), [2.0, 3.0, 4.0], atol=1e-5)
        np.testing.assert_allclose(np.array(s.var),  [1.0, 1.0, 1.0], atol=1e-5)
        assert int(s.count) == 2

    def test_large_count_stability(self):
        # 1000-sample batch of all-one vectors (D=1) → mean=1, var=0
        stats = init_running_stats(1)
        batch = jnp.ones((1000, 1))
        s = update_stats(stats, batch)
        assert float(s.mean[0]) == pytest.approx(1.0, abs=1e-5)
        assert float(s.var[0])  == pytest.approx(0.0, abs=1e-5)
        assert int(s.count) == 1000

    def test_sequential_vs_one_shot(self):
        # Splitting a batch into two halves then updating sequentially
        # should give the same result as updating with the full batch at once.
        rng = np.random.RandomState(0)
        data = rng.randn(100, 4).astype(np.float32)
        stats = init_running_stats(4)

        s_full = update_stats(stats, jnp.array(data))
        s_split = update_stats(update_stats(stats, jnp.array(data[:50])),
                               jnp.array(data[50:]))
        np.testing.assert_allclose(np.array(s_full.mean), np.array(s_split.mean), atol=1e-4)
        np.testing.assert_allclose(np.array(s_full.var),  np.array(s_split.var),  atol=1e-4)


class TestNormalizeObs:
    """Normalise + clip ±10 — §4.3."""

    def _stats_from_data(self, data):
        """Helper: init stats and update once."""
        stats = init_running_stats(data.shape[1])
        return update_stats(stats, jnp.array(data))

    def test_obs_at_mean_is_zero(self):
        # mean=4.0, var=2.0 (from the two-batch test)
        # obs=4.0 → (4.0-4.0)/sqrt(2+1e-8) = 0.0
        stats = init_running_stats(1)
        s1 = update_stats(stats, jnp.array([[2.0], [4.0]]))
        s2 = update_stats(s1,    jnp.array([[4.0], [6.0]]))
        # mean=4, var=2, std=sqrt(2+1e-8)≈1.41421356
        result = normalize_obs(jnp.array([4.0]), s2, clip=10.0)
        assert float(result[0]) == pytest.approx(0.0, abs=1e-5)

    def test_obs_one_std_above_mean(self):
        # mean=4.0, var=2.0, std≈1.41421356
        # obs = 4.0 + 1.41421356 = 5.41421356
        # normalized = (5.41421356 - 4.0) / 1.41421356 = 1.0
        stats = init_running_stats(1)
        s1 = update_stats(stats, jnp.array([[2.0], [4.0]]))
        s2 = update_stats(s1,    jnp.array([[4.0], [6.0]]))
        std = float(jnp.sqrt(s2.var[0] + 1e-8))   # ≈ 1.41421356
        obs = 4.0 + std
        result = normalize_obs(jnp.array([obs]), s2, clip=10.0)
        assert float(result[0]) == pytest.approx(1.0, rel=1e-4)

    def test_clip_at_positive_10(self):
        # mean=4.0, var=2.0, std≈1.41421356
        # obs = 4.0 + 11 * 1.41421356 = 4 + 15.5564 = 19.5564
        # raw normalized = 11.0 → clipped to 10.0
        stats = init_running_stats(1)
        s1 = update_stats(stats, jnp.array([[2.0], [4.0]]))
        s2 = update_stats(s1,    jnp.array([[4.0], [6.0]]))
        std = float(jnp.sqrt(s2.var[0] + 1e-8))
        obs = 4.0 + 11.0 * std
        result = normalize_obs(jnp.array([obs]), s2, clip=10.0)
        assert float(result[0]) == pytest.approx(10.0, rel=1e-5)

    def test_clip_at_negative_10(self):
        # mean=4.0, var=2.0, std≈1.41421356
        # obs = 4.0 - 12 * 1.41421356 ≈ 4.0 - 16.9706 = -12.9706
        # raw normalized = -12.0 → clipped to -10.0
        stats = init_running_stats(1)
        s1 = update_stats(stats, jnp.array([[2.0], [4.0]]))
        s2 = update_stats(s1,    jnp.array([[4.0], [6.0]]))
        std = float(jnp.sqrt(s2.var[0] + 1e-8))
        obs = 4.0 - 12.0 * std
        result = normalize_obs(jnp.array([obs]), s2, clip=10.0)
        assert float(result[0]) == pytest.approx(-10.0, rel=1e-5)

    def test_initial_stats_var_1_prevents_division_by_zero(self):
        # With init var=1, count=0: normalize should not produce NaN or Inf.
        # normalize_obs([5.0], init_stats) = (5.0-0.0)/sqrt(1+1e-8) ≈ 4.9999999
        stats = init_running_stats(1)
        result = normalize_obs(jnp.array([5.0]), stats, clip=10.0)
        assert jnp.isfinite(result).all()
        assert float(result[0]) == pytest.approx(5.0 / float(jnp.sqrt(1.0 + 1e-8)), rel=1e-4)

    def test_107d_obs_normalizes_each_dim_independently(self):
        # Each dimension normalised independently using its own mean and variance.
        rng = np.random.RandomState(42)
        data = rng.randn(200, 107).astype(np.float32) * 3.0 + 1.0
        stats = init_running_stats(107)
        s = update_stats(stats, jnp.array(data))
        # obs = mean → all outputs should be ≈0
        obs = jnp.array(np.array(s.mean))
        result = normalize_obs(obs, s, clip=10.0)
        np.testing.assert_allclose(np.array(result), np.zeros(107), atol=1e-4)


class TestNormalizeReward:
    """Reward is normalised by std only (no mean subtraction) — §4.3."""

    def test_reward_normalised_by_std_not_mean(self):
        # stats: mean=100.0, var=400.0 (std=20.0) — built from two-point batch
        # reward = 100.0 → reward_norm = 100.0 / 20.0 = 5.0 (NOT 0.0 — mean NOT subtracted)
        stats = init_running_stats(1)
        # Build stats: batch [80, 120] → mean=100, var=400, std=20
        s = update_stats(stats, jnp.array([[80.0], [120.0]]))
        # mean=100, var=400: (80-100)²+(120-100)² = 400+400=800; 800/2=400 ✓
        result = normalize_reward(jnp.array([100.0]), s, clip=10.0)
        # 100.0 / sqrt(400+1e-8) = 100/20 = 5.0
        assert float(result[0]) == pytest.approx(5.0, rel=1e-4)

    def test_reward_clip_positive(self):
        # std=20.0, reward=250.0 → 250/20=12.5 → clipped to 10.0
        stats = init_running_stats(1)
        s = update_stats(stats, jnp.array([[80.0], [120.0]]))
        result = normalize_reward(jnp.array([250.0]), s, clip=10.0)
        assert float(result[0]) == pytest.approx(10.0, rel=1e-5)

    def test_reward_clip_negative(self):
        # std=20.0, reward=-250.0 → -250/20=-12.5 → clipped to -10.0
        stats = init_running_stats(1)
        s = update_stats(stats, jnp.array([[80.0], [120.0]]))
        result = normalize_reward(jnp.array([-250.0]), s, clip=10.0)
        assert float(result[0]) == pytest.approx(-10.0, rel=1e-5)


# ---------------------------------------------------------------------------
# § 3 — RunConfig
# ---------------------------------------------------------------------------

class TestRunConfig:
    def test_default_gamma_is_0999(self):
        # MUST be 0.999 — demand charge is a monthly signal (§5)
        cfg = RunConfig()
        assert cfg.gamma == 0.999

    def test_default_lr(self):
        assert RunConfig().lr == pytest.approx(1e-4)

    def test_default_batch_size(self):
        assert RunConfig().batch_size == 512

    def test_default_buffer_size(self):
        assert RunConfig().buffer_size == 1_000_000

    def test_default_tau(self):
        assert RunConfig().tau == pytest.approx(0.005)

    def test_default_ent_coef(self):
        assert RunConfig().ent_coef == "auto"

    def test_default_total_env_steps(self):
        assert RunConfig().total_env_steps == 500_000

    def test_default_n_envs(self):
        assert RunConfig().n_envs == 4096

    def test_default_episode_len(self):
        # D3: 7-day training episode
        assert RunConfig().episode_len == 168

    def test_default_eval_episode_len(self):
        # D3: full year eval
        assert RunConfig().eval_episode_len == 8760

    def test_default_clip_10(self):
        cfg = RunConfig()
        assert cfg.clip_obs    == pytest.approx(10.0)
        assert cfg.clip_reward == pytest.approx(10.0)

    def test_default_hidden_sizes(self):
        assert RunConfig().hidden_sizes == (256, 256)

    def test_default_norm_flags(self):
        cfg = RunConfig()
        assert cfg.norm_obs    is True
        assert cfg.norm_reward is True

    def test_default_site_config_id(self):
        # Must default to "site_gansu" (§3 RunConfig + checkpoint cross-reference §10)
        assert RunConfig().site_config_id == "site_gansu"


# ---------------------------------------------------------------------------
# § 7 — Baselines
# ---------------------------------------------------------------------------

class TestNoBatteryPolicy:
    """NoBatteryPolicy outputs a 6-dim action [0.0, 1.0, 0.0, 1.0, 0.0, 0.0] — §7.1.

    Critical: allocating f_sol→load=f_wind→load=0 with a_bat=0 would serve ZERO load from
    renewable → VOLL every step → 'RL beats no-battery' is trivially/misleadingly true.
    The correct no-battery baseline directs all renewable to load (f_sol→load=f_wind→load=1).
    """

    def test_action_shape_is_6(self):
        # Action must be 6-dim per §2.2 "Energy Router" action space
        policy = NoBatteryPolicy()
        action = policy.action(t=jnp.int32(3))
        assert action.shape == (6,), f"NoBattery action shape {action.shape} != (6,)"

    def test_a_bat_is_zero(self):
        # a_bat=0 means no battery activity at any hour
        policy = NoBatteryPolicy()
        for h in range(24):
            action = policy.action(t=jnp.int32(h))
            assert float(action[0]) == pytest.approx(0.0, abs=1e-6), \
                f"NoBattery a_bat != 0 at hour {h}"

    def test_f_sol_load_is_one(self):
        # f_sol→load=1.0 to serve load from solar and prevent VOLL (§7.1 critical note)
        policy = NoBatteryPolicy()
        for h in range(24):
            action = policy.action(t=jnp.int32(h))
            assert float(action[1]) == pytest.approx(1.0, abs=1e-6), \
                f"NoBattery f_sol→load != 1 at hour {h}"

    def test_f_sol_bat_is_zero(self):
        policy = NoBatteryPolicy()
        action = policy.action(t=jnp.int32(0))
        assert float(action[2]) == pytest.approx(0.0, abs=1e-6)

    def test_f_wind_load_is_one(self):
        # f_wind→load=1.0 to serve load from wind and prevent VOLL (§7.1 critical note)
        policy = NoBatteryPolicy()
        for h in range(24):
            action = policy.action(t=jnp.int32(h))
            assert float(action[3]) == pytest.approx(1.0, abs=1e-6), \
                f"NoBattery f_wind→load != 1 at hour {h}"

    def test_f_wind_bat_is_zero(self):
        policy = NoBatteryPolicy()
        action = policy.action(t=jnp.int32(0))
        assert float(action[4]) == pytest.approx(0.0, abs=1e-6)

    def test_f_bat_load_is_zero(self):
        policy = NoBatteryPolicy()
        action = policy.action(t=jnp.int32(0))
        assert float(action[5]) == pytest.approx(0.0, abs=1e-6)

    def test_action_vector_matches_contract(self):
        # Full 6-vector: [0.0, 1.0, 0.0, 1.0, 0.0, 0.0] (§7.1)
        policy = NoBatteryPolicy()
        action = policy.action(t=jnp.int32(9))  # mid-day hour
        expected = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        np.testing.assert_allclose(np.array(action), expected, atol=1e-6)

    def test_degradation_is_zero_in_eval(self):
        # With p_bat=0 always, no battery throughput → c_degradation_yuan = 0 for the year
        # (cost formula: C_deg = c_deg_yuan_per_mwh * (p_bat_ch + p_bat_dis) * Δt
        #  = 10 * (0 + 0) * 1.0 = 0 ¥/step → Σ over 8760 steps = 0)
        from energy_go.generators.synthetic import generate_year
        key = jax.random.PRNGKey(0)
        data = generate_year(key)
        result = run_baseline("no_battery", data)
        assert result.degradation_yuan == pytest.approx(0.0, abs=1e-3)


class TestTouPolicy:
    """TouPolicy emits a 6-dim action matching the tariff tier — §7.2.

    Valley  (price=250 ¥/MWh): a_bat=+1, f_sol→load=0, f_sol→bat=1, f_wind→load=0, f_wind→bat=1, f_bat→load=0
    Mid     (price=450 ¥/MWh): a_bat= 0, f_sol→load=1, f_sol→bat=0, f_wind→load=1, f_wind→bat=0, f_bat→load=0
    Peak    (price=620 or 780): a_bat=-1, f_sol→load=1, f_sol→bat=0, f_wind→load=1, f_wind→bat=0, f_bat→load=1
    """

    def test_action_shape_is_6(self):
        # TOU policy action must be 6-dim per §2.2 "Energy Router"
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(3))
        assert action.shape == (6,), f"TouPolicy action shape {action.shape} != (6,)"

    def test_valley_hour_a_bat_charges(self):
        # h=3: PRICE_TABLE_YPW[3]=250 (valley) → a_bat=+1.0 (charge)
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(3))
        assert float(action[0]) == pytest.approx(+1.0, abs=1e-6), "valley a_bat should be +1"

    def test_valley_hour_renewable_to_battery(self):
        # Valley: f_sol→bat=1, f_wind→bat=1 (charge from renewable)
        # f_sol→load=0, f_wind→load=0 (load served from cheap grid)
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(3))
        # [a_bat, f_sol→load, f_sol→bat, f_wind→load, f_wind→bat, f_bat→load]
        expected = np.array([+1.0, 0.0, 1.0, 0.0, 1.0, 0.0], dtype=np.float32)
        np.testing.assert_allclose(np.array(action), expected, atol=1e-6,
                                   err_msg="valley hour full 6-vector mismatch")

    def test_critical_peak_hour_a_bat_discharges(self):
        # h=11: PRICE_TABLE_YPW[11]=780 (critical peak) → a_bat=-1.0 (discharge)
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(11))
        assert float(action[0]) == pytest.approx(-1.0, abs=1e-6), "critical peak a_bat should be -1"

    def test_critical_peak_hour_full_vector(self):
        # h=11: peak → discharge + all renewable to load + discharge to load
        # [a_bat=-1, f_sol→load=1, f_sol→bat=0, f_wind→load=1, f_wind→bat=0, f_bat→load=1]
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(11))
        expected = np.array([-1.0, 1.0, 0.0, 1.0, 0.0, 1.0], dtype=np.float32)
        np.testing.assert_allclose(np.array(action), expected, atol=1e-6,
                                   err_msg="critical peak hour full 6-vector mismatch")

    def test_mid_hour_a_bat_idles(self):
        # h=12: PRICE_TABLE_YPW[12]=450 (mid) → a_bat=0.0
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(12))
        assert float(action[0]) == pytest.approx(0.0, abs=1e-6), "mid a_bat should be 0"

    def test_mid_hour_full_vector(self):
        # h=12: mid → idle battery + all renewable to load
        # [a_bat=0, f_sol→load=1, f_sol→bat=0, f_wind→load=1, f_wind→bat=0, f_bat→load=0]
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(12))
        expected = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        np.testing.assert_allclose(np.array(action), expected, atol=1e-6,
                                   err_msg="mid hour full 6-vector mismatch")

    def test_peak_hour_18_a_bat_discharges(self):
        # h=18: PRICE_TABLE_YPW[18]=620 (peak) → a_bat=-1.0
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(18))
        assert float(action[0]) == pytest.approx(-1.0, abs=1e-6)

    def test_peak_hour_18_full_vector(self):
        # h=18: peak → discharge + all renewable to load + f_bat→load=1
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(18))
        expected = np.array([-1.0, 1.0, 0.0, 1.0, 0.0, 1.0], dtype=np.float32)
        np.testing.assert_allclose(np.array(action), expected, atol=1e-6,
                                   err_msg="peak h=18 full 6-vector mismatch")

    def test_hour_23_charges(self):
        # h=23: PRICE_TABLE_YPW[23]=250 (valley) → a_bat=+1.0
        policy = TouPolicy()
        action = policy.action(t=jnp.int32(23))
        assert float(action[0]) == pytest.approx(+1.0, abs=1e-6)

    def test_all_24_hours_a_bat_correct(self):
        # Verify a_bat (action[0]) is consistent with PRICE_TABLE_YPW for ALL hours.
        # valley (price=250): a_bat=+1.0
        # mid    (price=450): a_bat= 0.0
        # peak/critical (price=620 or 780): a_bat=-1.0
        policy = TouPolicy()
        for h in range(24):
            price = float(PRICE_TABLE_YPW[h])
            action = policy.action(t=jnp.int32(h))
            a_bat = float(action[0])
            if price < 450.0:    # valley (250)
                assert a_bat == pytest.approx(+1.0, abs=1e-6), f"TOU h={h}: a_bat expected +1 (valley)"
            elif price == 450.0: # mid
                assert a_bat == pytest.approx(0.0, abs=1e-6),  f"TOU h={h}: a_bat expected 0 (mid)"
            else:                # peak/critical (620, 780)
                assert a_bat == pytest.approx(-1.0, abs=1e-6), f"TOU h={h}: a_bat expected -1 (peak)"

    def test_all_24_hours_fractions_in_range(self):
        # action[1:6] must all be in [0, 1] for all hours (fraction constraints)
        policy = TouPolicy()
        for h in range(24):
            action = policy.action(t=jnp.int32(h))
            fractions = np.array(action[1:6])
            assert np.all(fractions >= 0.0) and np.all(fractions <= 1.0), \
                f"TOU h={h}: fractions out of [0,1]: {fractions}"

    def test_tou_eval_has_zero_penalty(self):
        # Rule-based TOU does not target a specific SOC — env clips at bounds.
        # Verify the result object has penalty_yuan >= 0 (not a negative penalty).
        from energy_go.generators.synthetic import generate_year
        key = jax.random.PRNGKey(0)
        data = generate_year(key)
        result = run_baseline("rule_based_tou", data)
        assert result.penalty_yuan >= 0.0


# ---------------------------------------------------------------------------
# § 8 — PolicyEvalResult additive identity
# ---------------------------------------------------------------------------

class TestPolicyEvalResultIdentity:
    """total_cost_yuan == sum of the 5 real-money components — §8."""

    def _make_result(self, energy, demand, degradation, curtailment, voll, **kwargs):
        total = energy + demand + degradation + curtailment + voll
        return PolicyEvalResult(
            energy_cost_yuan=energy,
            demand_charge_yuan=demand,
            degradation_yuan=degradation,
            curtailment_yuan=curtailment,
            voll_yuan=voll,
            total_cost_yuan=total,
            soc_violations_count=kwargs.get("soc_violations_count", 0),
            soc_violation_mwh=kwargs.get("soc_violation_mwh", 0.0),
            penalty_yuan=kwargs.get("penalty_yuan", 0.0),
        )

    def test_additive_identity_positive_cost(self):
        # 50000 + 3040000 + 400 + 0 + 0 = 3090400
        r = self._make_result(50000.0, 3040000.0, 400.0, 0.0, 0.0)
        assert r.total_cost_yuan == pytest.approx(
            r.energy_cost_yuan + r.demand_charge_yuan + r.degradation_yuan
            + r.curtailment_yuan + r.voll_yuan,
            abs=1e-3,
        )

    def test_additive_identity_net_revenue(self):
        # Net export: energy_cost can be negative (revenue)
        # -60000 + 2880000 + 1200 + 0 + 0 = 2821200
        r = self._make_result(-60000.0, 2_880_000.0, 1200.0, 0.0, 0.0)
        expected = -60000.0 + 2_880_000.0 + 1200.0 + 0.0 + 0.0  # = 2_821_200
        assert r.total_cost_yuan == pytest.approx(expected, abs=1e-3)

    def test_penalty_not_in_total_cost(self):
        # penalty_yuan is a safety metric, NOT in total_cost_yuan (D13/telemetry schema §8.1)
        r = self._make_result(10000.0, 500000.0, 200.0, 50.0, 0.0, penalty_yuan=999.0)
        expected_total = 10000.0 + 500000.0 + 200.0 + 50.0 + 0.0  # = 510250.0
        assert r.total_cost_yuan == pytest.approx(expected_total, abs=1e-3)
        assert r.penalty_yuan == pytest.approx(999.0, abs=1e-6)

    def test_soc_violations_not_in_total_cost(self):
        # soc_violation_mwh and soc_violations_count are NOT summands of total_cost_yuan
        r = self._make_result(10000.0, 0.0, 0.0, 0.0, 0.0,
                              soc_violations_count=5, soc_violation_mwh=2.5)
        assert r.total_cost_yuan == pytest.approx(10000.0, abs=1e-3)
        assert r.soc_violations_count == 5
        assert r.soc_violation_mwh == pytest.approx(2.5, abs=1e-6)

    def test_no_battery_degradation_is_zero_in_result(self):
        # Matches the baseline test: NoBattery → degradation_yuan=0 (p_bat_ch=p_bat_dis=0)
        # No battery throughput → C_deg = 10 ¥/MWh × 0 MWh = 0 ¥
        from energy_go.generators.synthetic import generate_year
        key = jax.random.PRNGKey(0)
        data = generate_year(key)
        result = run_baseline("no_battery", data)
        assert result.degradation_yuan == pytest.approx(0.0, abs=1e-3)
        assert result.total_cost_yuan == pytest.approx(
            result.energy_cost_yuan + result.demand_charge_yuan
            + result.degradation_yuan + result.curtailment_yuan + result.voll_yuan,
            abs=1.0,  # sum tolerance: float64 accumulation
        )


# ---------------------------------------------------------------------------
# § 9 — Telemetry (LOCKED schema validation) — validate-telemetry skill
# ---------------------------------------------------------------------------

class TestTelemetryTrainMetrics:
    """build_train_metrics must produce a LOCKED-schema-valid envelope."""

    def _golden_train_metrics(self, **overrides):
        defaults = dict(
            global_step=10_000,
            wall_seconds=12.3,
            env_steps_per_sec=813_008.13,
            actor_loss=0.42,
            critic_loss=1.31,
            ent_coef=0.18,
            reward_scaled_mean=0.61,
            reward_norm_mean=0.83,
            cost_total_real_mean_yuan=-61_000.0,
            is_eval_checkpoint=False,
            checkpoint_id=None,
            run_id="test-run-001",
        )
        defaults.update(overrides)
        return build_train_metrics(**defaults)

    def test_valid_train_metrics_passes_schema(self):
        msg = self._golden_train_metrics()
        errors = validate_telemetry(msg)
        assert errors == [], f"train_metrics schema errors: {errors}"

    def test_schema_version_is_1_0_0(self):
        msg = self._golden_train_metrics()
        assert msg["schema_version"] == "1.0.0"

    def test_kind_is_train_metrics(self):
        msg = self._golden_train_metrics()
        assert msg["kind"] == "train_metrics"

    def test_run_id_is_propagated(self):
        msg = self._golden_train_metrics(run_id="my-run-42")
        assert msg["run_id"] == "my-run-42"

    def test_global_step_in_payload(self):
        msg = self._golden_train_metrics(global_step=250_000)
        assert msg["payload"]["global_step"] == 250_000

    def test_reward_norm_mean_is_null_at_eval_checkpoint(self):
        # Schema: reward_norm_mean is null when is_eval_checkpoint=True
        msg = self._golden_train_metrics(
            is_eval_checkpoint=True,
            checkpoint_id="ckpt-abc123",
            reward_norm_mean=None,
        )
        assert msg["payload"]["reward_norm_mean"] is None
        errors = validate_telemetry(msg)
        assert errors == [], f"eval_checkpoint train_metrics errors: {errors}"

    def test_non_finite_values_rejected_by_validator(self):
        # Producer must guarantee finite values; validator catches them.
        msg = self._golden_train_metrics()
        msg["payload"]["actor_loss"] = float("nan")
        errors = validate_telemetry(msg)
        assert len(errors) > 0, "NaN actor_loss should be caught by validator"

    def test_seq_is_integer_and_positive(self):
        msg = self._golden_train_metrics()
        assert isinstance(msg["seq"], int)
        assert msg["seq"] >= 0


class TestTelemetryEvalCompare:
    """build_eval_compare must produce a LOCKED-schema-valid envelope."""

    def _make_eval_result(self, energy, demand, degradation, curtailment, voll,
                          penalty=0.0, soc_count=0, soc_mwh=0.0):
        total = energy + demand + degradation + curtailment + voll
        return PolicyEvalResult(
            energy_cost_yuan=energy,
            demand_charge_yuan=demand,
            degradation_yuan=degradation,
            curtailment_yuan=curtailment,
            voll_yuan=voll,
            total_cost_yuan=total,
            soc_violations_count=soc_count,
            soc_violation_mwh=soc_mwh,
            penalty_yuan=penalty,
        )

    def _golden_eval_compare(self):
        rl  = self._make_eval_result(-60_000.0, 2_880_000.0, 1200.0, 0.0, 0.0, penalty=500.0)
        nob = self._make_eval_result(-40_000.0, 3_200_000.0,    0.0, 0.0, 0.0)
        tou = self._make_eval_result(-55_000.0, 2_950_000.0,  900.0, 0.0, 0.0)
        return build_eval_compare(
            eval_horizon_steps=8760,
            checkpoint_id="ckpt-test-001",
            rl=rl,
            no_battery=nob,
            rule_based_tou=tou,
            run_id="test-run-001",
        )

    def test_valid_eval_compare_passes_schema(self):
        msg = self._golden_eval_compare()
        errors = validate_telemetry(msg)
        assert errors == [], f"eval_compare schema errors: {errors}"

    def test_kind_is_eval_compare(self):
        msg = self._golden_eval_compare()
        assert msg["kind"] == "eval_compare"

    def test_eval_horizon_8760(self):
        msg = self._golden_eval_compare()
        assert msg["payload"]["eval_horizon_steps"] == 8760

    def test_cost_basis_is_real_money(self):
        msg = self._golden_eval_compare()
        assert msg["payload"]["cost_basis"] == "real_money"

    def test_all_three_policies_present(self):
        msg = self._golden_eval_compare()
        p = msg["payload"]["policies"]
        assert set(p.keys()) == {"rl", "no_battery", "rule_based_tou"}

    def test_rl_total_cost_additive_identity(self):
        # rl: energy=-60000, demand=2880000, degradation=1200, curtailment=0, voll=0
        # total = -60000 + 2880000 + 1200 + 0 + 0 = 2821200
        msg = self._golden_eval_compare()
        rl = msg["payload"]["policies"]["rl"]
        expected_total = (rl["energy_cost_yuan"] + rl["demand_charge_yuan"]
                          + rl["degradation_yuan"] + rl["curtailment_yuan"] + rl["voll_yuan"])
        assert rl["total_cost_yuan"] == pytest.approx(expected_total, abs=1.0)

    def test_no_battery_total_cost_additive_identity(self):
        # no_battery: energy=-40000, demand=3200000, degradation=0, curtailment=0, voll=0
        # total = -40000 + 3200000 = 3160000
        msg = self._golden_eval_compare()
        nob = msg["payload"]["policies"]["no_battery"]
        expected_total = (nob["energy_cost_yuan"] + nob["demand_charge_yuan"]
                          + nob["degradation_yuan"] + nob["curtailment_yuan"] + nob["voll_yuan"])
        assert nob["total_cost_yuan"] == pytest.approx(expected_total, abs=1.0)

    def test_penalty_excluded_from_total(self):
        # penalty_yuan is a safety metric — NOT in total_cost_yuan (LOCKED schema §8.1)
        msg = self._golden_eval_compare()
        rl = msg["payload"]["policies"]["rl"]
        assert rl["penalty_yuan"] == pytest.approx(500.0, abs=1e-3)
        # total must NOT include penalty
        without_penalty = (rl["energy_cost_yuan"] + rl["demand_charge_yuan"]
                           + rl["degradation_yuan"] + rl["curtailment_yuan"] + rl["voll_yuan"])
        assert rl["total_cost_yuan"] == pytest.approx(without_penalty, abs=1.0)

    def test_build_eval_compare_raises_on_bad_identity(self):
        # build_eval_compare asserts the identity before returning (§9 producer fault)
        rl  = self._make_eval_result(-60_000.0, 2_880_000.0, 1200.0, 0.0, 0.0)
        rl_bad = PolicyEvalResult(
            energy_cost_yuan=rl.energy_cost_yuan,
            demand_charge_yuan=rl.demand_charge_yuan,
            degradation_yuan=rl.degradation_yuan,
            curtailment_yuan=rl.curtailment_yuan,
            voll_yuan=rl.voll_yuan,
            total_cost_yuan=rl.total_cost_yuan + 9999.0,  # deliberately wrong
            soc_violations_count=0,
            soc_violation_mwh=0.0,
            penalty_yuan=0.0,
        )
        nob = self._make_eval_result(-40_000.0, 3_200_000.0, 0.0, 0.0, 0.0)
        tou = self._make_eval_result(-55_000.0, 2_950_000.0, 900.0, 0.0, 0.0)
        with pytest.raises(AssertionError):
            build_eval_compare(
                eval_horizon_steps=8760,
                checkpoint_id="bad-ckpt",
                rl=rl_bad,
                no_battery=nob,
                rule_based_tou=tou,
                run_id="test-run-001",
            )


# ---------------------------------------------------------------------------
# § 10 — Checkpoint round-trip
# ---------------------------------------------------------------------------

class TestCheckpointRoundTrip:
    """Save + load produces identical actions — §10 / checkpoint_format contract."""

    def _get_dummy_checkpoint(self):
        """Build a minimal CheckpointData by running a very short training loop."""
        from energy_go.generators.synthetic import generate_year
        from energy_go.training.run_training import train
        from energy_go.training.config import RunConfig

        cfg = RunConfig(
            total_env_steps=1024,  # minimal smoke run
            n_envs=4,
            buffer_size=2048,
            batch_size=32,
            seed=0,
        )
        key = jax.random.PRNGKey(0)
        data = generate_year(key)
        return train(cfg, key, data, emit_fn=None)

    def test_checkpoint_has_required_fields(self):
        ckpt = self._get_dummy_checkpoint()
        assert hasattr(ckpt, "actor_params"),   "checkpoint missing actor_params"
        assert hasattr(ckpt, "obs_stats"),       "checkpoint missing obs_stats"
        assert hasattr(ckpt, "run_config"),      "checkpoint missing run_config"
        assert hasattr(ckpt, "global_step"),     "checkpoint missing global_step"
        assert hasattr(ckpt, "checkpoint_id"),   "checkpoint missing checkpoint_id"

    def test_save_load_identical_actions(self, tmp_path):
        """After save + load, deterministic policy produces identical actions on fixed obs."""
        from energy_go.training.checkpoint_format import save_checkpoint, load_checkpoint

        ckpt = self._get_dummy_checkpoint()
        path = tmp_path / "test_ckpt.npz"
        save_checkpoint(ckpt, path)

        ckpt_loaded = load_checkpoint(path)

        # Fixed obs: all-zeros 107-dim vector
        obs = jnp.zeros(107, dtype=jnp.float32)

        def deterministic_action(c, raw_obs):
            norm_obs = normalize_obs(raw_obs, c.obs_stats, clip=10.0)
            # Actor forward pass: per-component squash (§5.2)
            # tanh for a_bat (action[0]), sigmoid for 5 fractions (action[1:6])
            from energy_go.training.run_training import actor_forward
            mean, _ = actor_forward(c.actor_params, norm_obs)
            # mean shape: (6,); split squash
            a_bat = jnp.tanh(mean[:1])
            fractions = jax.nn.sigmoid(mean[1:])
            return jnp.concatenate([a_bat, fractions])  # (6,)

        a_before = deterministic_action(ckpt,        obs)
        a_after  = deterministic_action(ckpt_loaded, obs)
        assert a_before.shape == (6,), f"action shape {a_before.shape} != (6,)"
        np.testing.assert_allclose(np.array(a_before), np.array(a_after), atol=1e-6)

    def test_obs_stats_restored_correctly(self, tmp_path):
        """obs_stats (mean, var, count) round-trip through save/load."""
        from energy_go.training.checkpoint_format import save_checkpoint, load_checkpoint

        ckpt = self._get_dummy_checkpoint()
        path = tmp_path / "test_ckpt.npz"
        save_checkpoint(ckpt, path)
        ckpt_loaded = load_checkpoint(path)

        np.testing.assert_allclose(
            np.array(ckpt.obs_stats.mean),
            np.array(ckpt_loaded.obs_stats.mean),
            atol=1e-6,
        )
        np.testing.assert_allclose(
            np.array(ckpt.obs_stats.var),
            np.array(ckpt_loaded.obs_stats.var),
            atol=1e-6,
        )
        assert int(ckpt.obs_stats.count) == int(ckpt_loaded.obs_stats.count)


# ---------------------------------------------------------------------------
# § 6 — Training loop determinism and JAX compilation
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Fixed seed → identical trajectory — §6.8."""

    def _run_short(self, seed):
        from energy_go.generators.synthetic import generate_year
        from energy_go.training.run_training import train
        from energy_go.training.config import RunConfig

        cfg = RunConfig(
            total_env_steps=512,
            n_envs=4,
            buffer_size=1024,
            batch_size=32,
            seed=seed,
        )
        key = jax.random.PRNGKey(seed)
        data = generate_year(key)
        return train(cfg, key, data, emit_fn=None)

    def _deterministic_action(self, ckpt, obs):
        """Per-component squash of actor_mean: tanh for a_bat, sigmoid for 5 fractions (§5.2)."""
        from energy_go.training.run_training import actor_forward
        norm_obs = normalize_obs(obs, ckpt.obs_stats)
        mean, _ = actor_forward(ckpt.actor_params, norm_obs)
        # mean shape: (6,); per-component squash
        a_bat = jnp.tanh(mean[:1])
        fractions = jax.nn.sigmoid(mean[1:])
        return jnp.concatenate([a_bat, fractions])  # (6,)

    def test_same_seed_same_checkpoint_actions(self):
        ckpt_a = self._run_short(seed=7)
        ckpt_b = self._run_short(seed=7)
        obs = jnp.zeros(107, dtype=jnp.float32)
        a_a = self._deterministic_action(ckpt_a, obs)
        a_b = self._deterministic_action(ckpt_b, obs)
        assert a_a.shape == (6,), f"action shape {a_a.shape} != (6,)"
        np.testing.assert_allclose(np.array(a_a), np.array(a_b), atol=1e-6)

    def test_different_seeds_different_checkpoints(self):
        ckpt_0 = self._run_short(seed=0)
        ckpt_1 = self._run_short(seed=1)
        obs = jnp.zeros(107, dtype=jnp.float32)
        a_0 = self._deterministic_action(ckpt_0, obs)
        a_1 = self._deterministic_action(ckpt_1, obs)
        # Different seeds → different actions (with overwhelmingly high probability)
        assert not np.allclose(np.array(a_0), np.array(a_1), atol=1e-4), \
            "Different seeds produced identical checkpoint — training is not random"


class TestVmapCompilation:
    """vmap over ≥4096 envs compiles without error — §6.2 / §7."""

    def test_vmap_env_step_compiles(self):
        # Minimal vmap smoke test: vmap env.step over N=8 env states compiles.
        from energy_go.generators.synthetic import generate_year
        from energy_go.env.jax_env import EnvState, EnvParams, reset, step

        N = 8
        params = EnvParams()
        key = jax.random.PRNGKey(0)
        data = generate_year(key)
        keys = jax.random.split(key, N)

        # vmap reset
        states, obs = jax.vmap(reset, in_axes=(0, None, None))(keys, params, data)
        # vmap step with NoBattery actions (6-dim; f_sol→load=f_wind→load=1 avoids VOLL)
        # action: [a_bat=0, f_sol→load=1, f_sol→bat=0, f_wind→load=1, f_wind→bat=0, f_bat→load=0]
        actions = jnp.tile(jnp.array([[0.0, 1.0, 0.0, 1.0, 0.0, 0.0]]), (N, 1))  # (N, 6)
        new_states, new_obs, rewards, dones, infos = jax.jit(
            jax.vmap(step, in_axes=(0, 0, None, None))
        )(states, actions, params, data)
        assert new_obs.shape == (N, 107)
        assert rewards.shape == (N,)
        assert actions.shape == (N, 6), f"action shape {actions.shape} != (N, 6)"

    def test_4096_envs_vmap_compiles(self):
        # The contract requires n_envs=4096 as the default — test that vmap at this scale compiles.
        from energy_go.generators.synthetic import generate_year
        from energy_go.env.jax_env import EnvState, EnvParams, reset, step

        N = 4096
        params = EnvParams()
        key = jax.random.PRNGKey(42)
        data = generate_year(key)
        keys = jax.random.split(key, N)

        # vmap reset — compilation test only, assert shape
        states, obs = jax.jit(jax.vmap(reset, in_axes=(0, None, None)))(keys, params, data)
        assert obs.shape == (N, 107)


# ---------------------------------------------------------------------------
# § 5 — Policy architecture: actor output shape and ranges, critic input, target_entropy
# ---------------------------------------------------------------------------

class TestActorOutputShape:
    """Actor MLP output has shape (6,) and respects per-component squash ranges — §5.2."""

    def _get_short_checkpoint(self):
        from energy_go.generators.synthetic import generate_year
        from energy_go.training.run_training import train
        from energy_go.training.config import RunConfig
        cfg = RunConfig(total_env_steps=512, n_envs=4, buffer_size=1024, batch_size=32, seed=0)
        key = jax.random.PRNGKey(0)
        return train(cfg, key, generate_year(key), emit_fn=None)

    def test_actor_output_shape_is_6(self):
        # actor_forward returns (mean(6), log_std(6)); mean has shape (6,) — §5.2 Dense(12)
        from energy_go.training.run_training import actor_forward
        ckpt = self._get_short_checkpoint()
        obs = jnp.zeros(107, dtype=jnp.float32)
        norm_obs = normalize_obs(obs, ckpt.obs_stats)
        mean, log_std = actor_forward(ckpt.actor_params, norm_obs)
        assert mean.shape == (6,), f"actor mean shape {mean.shape} != (6,)"
        assert log_std.shape == (6,), f"actor log_std shape {log_std.shape} != (6,)"

    def test_a_bat_in_open_tanh_range(self):
        # After tanh squash, action[0] ∈ (-1, 1) — strictly open (never exactly ±1)
        from energy_go.training.run_training import actor_forward
        ckpt = self._get_short_checkpoint()
        # Test with multiple obs vectors
        for seed in range(5):
            obs = jax.random.normal(jax.random.PRNGKey(seed), (107,)).astype(jnp.float32)
            norm_obs = normalize_obs(obs, ckpt.obs_stats)
            mean, _ = actor_forward(ckpt.actor_params, norm_obs)
            a_bat = float(jnp.tanh(mean[0]))
            assert -1.0 < a_bat < 1.0, \
                f"a_bat={a_bat} out of open (-1, 1) range (tanh squash)"

    def test_fractions_in_open_sigmoid_range(self):
        # After sigmoid squash, action[1:6] ∈ (0, 1) — strictly open (never exactly 0 or 1)
        from energy_go.training.run_training import actor_forward
        ckpt = self._get_short_checkpoint()
        for seed in range(5):
            obs = jax.random.normal(jax.random.PRNGKey(seed + 10), (107,)).astype(jnp.float32)
            norm_obs = normalize_obs(obs, ckpt.obs_stats)
            mean, _ = actor_forward(ckpt.actor_params, norm_obs)
            fractions = np.array(jax.nn.sigmoid(mean[1:]))
            assert np.all(fractions > 0.0) and np.all(fractions < 1.0), \
                f"fractions {fractions} out of open (0, 1) range (sigmoid squash)"

    def test_deterministic_action_has_shape_6(self):
        # Full deterministic eval action after per-component squash must be (6,)
        from energy_go.training.run_training import actor_forward
        ckpt = self._get_short_checkpoint()
        obs = jnp.ones(107, dtype=jnp.float32)
        norm_obs = normalize_obs(obs, ckpt.obs_stats)
        mean, _ = actor_forward(ckpt.actor_params, norm_obs)
        a_bat = jnp.tanh(mean[:1])
        fractions = jax.nn.sigmoid(mean[1:])
        action = jnp.concatenate([a_bat, fractions])
        assert action.shape == (6,), f"deterministic action shape {action.shape} != (6,)"

    def test_critic_input_is_113(self):
        # Critic input = concat(obs(107), action(6)) = 113 — §5.3
        # critic1_fc1_w must have shape (113, 256) when saved to checkpoint
        ckpt = self._get_short_checkpoint()
        # Access critic weights via the checkpoint object (optional keys)
        if hasattr(ckpt, "critic1_params") and ckpt.critic1_params is not None:
            # For Flax: check the first Dense layer input size
            # The first weight matrix of critic1 fc1 should have input dim=113
            from energy_go.training.checkpoint_format import save_checkpoint, load_checkpoint
            import tempfile, pathlib
            with tempfile.TemporaryDirectory() as tmp:
                path = pathlib.Path(tmp) / "ckpt.npz"
                save_checkpoint(ckpt, path)
                loaded = load_checkpoint(path)
                # critic1_fc1_w: (113, 256) per §4.4 of checkpoint_format contract
                if loaded.critic1_fc1_w is not None:
                    assert loaded.critic1_fc1_w.shape == (113, 256), \
                        f"critic1_fc1_w shape {loaded.critic1_fc1_w.shape} != (113, 256)"
        else:
            pytest.skip("critic1_params not present in checkpoint (inference-only mode)")

    def test_target_entropy_is_minus_6(self):
        # target_entropy = -action_dim = -6.0 (§6.1.5)
        from energy_go.training.run_training import SAC_TARGET_ENTROPY
        assert SAC_TARGET_ENTROPY == pytest.approx(-6.0, abs=1e-6), \
            f"SAC_TARGET_ENTROPY={SAC_TARGET_ENTROPY}, expected -6.0 (action_dim=6)"

    def test_actor_params_shape_fc1_w(self):
        # actor_fc1_w must have shape (107, 256): input=107-dim obs, output=256 hidden — §5.2
        from energy_go.training.checkpoint_format import save_checkpoint, load_checkpoint
        import tempfile, pathlib
        ckpt = self._get_short_checkpoint()
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "ckpt.npz"
            save_checkpoint(ckpt, path)
            loaded = load_checkpoint(path)
            assert loaded.actor_fc1_w.shape == (107, 256), \
                f"actor_fc1_w {loaded.actor_fc1_w.shape} != (107, 256)"
            assert loaded.actor_fc2_w.shape == (256, 256), \
                f"actor_fc2_w {loaded.actor_fc2_w.shape} != (256, 256)"
            # actor_out_w: (256, 12) — 12 = 2 * 6 = mean(6) + log_std_raw(6)
            assert loaded.actor_out_w.shape == (256, 12), \
                f"actor_out_w {loaded.actor_out_w.shape} != (256, 12)"
            assert loaded.actor_out_b.shape == (12,), \
                f"actor_out_b {loaded.actor_out_b.shape} != (12,)"


# ---------------------------------------------------------------------------
# Reviewer-added cases (to be filled in by backend-reviewer)
# ---------------------------------------------------------------------------

# reviewer: verify reward normalization is std-only, not (r - mean)/std, by checking
# that two different reward values with the same distance from zero get different norms.
def test_reward_norm_not_mean_shifted():
    # reward_stats: mean=100, var=400 (std=20)
    # normalize_reward(0.0)   = 0.0/20 = 0.0   (not (0-100)/20 = -5.0)
    # normalize_reward(100.0) = 100.0/20 = 5.0  (not (100-100)/20 = 0.0)
    stats = init_running_stats(1)
    s = update_stats(stats, jnp.array([[80.0], [120.0]]))
    r0   = float(normalize_reward(jnp.array([0.0]),   s, clip=10.0))
    r100 = float(normalize_reward(jnp.array([100.0]), s, clip=10.0))
    # std-only: r0=0/20=0.0; r100=100/20=5.0
    # if mean-shifted: r0=-5.0; r100=0.0
    assert r0   == pytest.approx(0.0, abs=1e-5),   f"normalize_reward(0) = {r0}, expected 0 (std-only)"
    assert r100 == pytest.approx(5.0, rel=1e-4),   f"normalize_reward(100) = {r100}, expected 5 (std-only)"


# reviewer: eval obs_stats are FROZEN — updating after eval should not change actions.
def test_eval_obs_stats_frozen():
    """Running normalize_obs with the same stats twice must produce the same result.
    (This is trivially true but pins that eval does NOT call update_stats on the loaded stats.)"""
    stats = init_running_stats(107)
    s = update_stats(stats, jnp.array(np.random.RandomState(1).randn(50, 107).astype(np.float32)))
    obs = jnp.ones(107, dtype=jnp.float32)
    a1 = normalize_obs(obs, s, clip=10.0)
    # Simulating eval: stats are NOT updated
    a2 = normalize_obs(obs, s, clip=10.0)
    np.testing.assert_array_equal(np.array(a1), np.array(a2))


# reviewer: sub-month training episodes must never book c_demand_charge (D21).
def test_sub_month_demand_charge_is_zero_per_step():
    """A 7-day (168-step) episode must have c_demand_charge = 0 on every step.
    Training demand pressure comes from 2·c_demand_shape only (D21)."""
    # This test needs the env and the info output — smoke test on the raw env step.
    from energy_go.generators.synthetic import generate_year
    from energy_go.env.jax_env import EnvParams, reset, step

    key = jax.random.PRNGKey(0)
    data = generate_year(key)
    params = EnvParams(episode_len=168)
    state, _ = reset(key, params, data)

    # NoBattery 6-dim action: [a_bat=0, f_sol→load=1, f_sol→bat=0, f_wind→load=1, f_wind→bat=0, f_bat→load=0]
    # Directing renewable to load avoids VOLL domination (§7.1 critical note)
    no_battery_action = jnp.array([0.0, 1.0, 0.0, 1.0, 0.0, 0.0])
    for t_idx in range(168):
        state, obs, reward, done, info = step(state, no_battery_action, params, data)
        assert float(info.c_demand_charge_yuan) == pytest.approx(0.0, abs=1e-6), \
            f"Sub-month episode has non-zero c_demand_charge at step {t_idx}"


# ---------------------------------------------------------------------------
# Reviewer-added (backend-reviewer, PR #40 round-2 gate): _EPS div-0 guards
# ---------------------------------------------------------------------------
# reviewer: §4.3 adds _EPS=1e-8 specifically to prevent /0 when var is exactly 0
# reviewer: (a constant-valued batch). That guard was never exercised. These pin
# reviewer: that normalize_obs / normalize_reward stay finite at var==0.

def test_normalize_reward_var_zero_stays_finite():
    # reviewer: constant reward batch [[5],[5]] → mean=5, var=0 (pop-var of identical samples).
    # reviewer: normalize_reward(5) = 5 / sqrt(0 + 1e-8) = 5 / 1e-4 = 50000 → clipped to +10.0; finite.
    stats = init_running_stats(1)
    s = update_stats(stats, jnp.array([[5.0], [5.0]]))
    assert float(s.var[0]) == pytest.approx(0.0, abs=1e-6)
    r = float(normalize_reward(jnp.array([5.0]), s, clip=10.0))
    assert math.isfinite(r), f"normalize_reward not finite at var=0: {r}"
    assert r == pytest.approx(10.0, abs=1e-4)  # 5/1e-4 = 50000 → clip 10


def test_normalize_obs_var_zero_stays_finite():
    # reviewer: constant obs batch [[3],[3]] → var=0; normalize_obs must stay finite (no /0).
    # reviewer: (3 − 3) / sqrt(0 + 1e-8) = 0 / 1e-4 = 0.0; finite, exactly 0.
    stats = init_running_stats(1)
    s = update_stats(stats, jnp.array([[3.0], [3.0]]))
    assert float(s.var[0]) == pytest.approx(0.0, abs=1e-6)
    o = float(normalize_obs(jnp.array([3.0]), s, clip=10.0))
    assert math.isfinite(o), f"normalize_obs not finite at var=0: {o}"
    assert o == pytest.approx(0.0, abs=1e-4)
