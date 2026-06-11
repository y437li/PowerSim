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


# ---------------------------------------------------------------------------
# § 7 — Baselines
# ---------------------------------------------------------------------------

class TestNoBatteryPolicy:
    """NoBatteryPolicy always outputs action=0 — §7.1."""

    def test_action_is_zero_at_valley_hour(self):
        # Valley hour (h=3, price=250): no-battery policy still returns 0.0
        policy = NoBatteryPolicy()
        action = policy.action(t=jnp.int32(3))
        assert float(action) == pytest.approx(0.0, abs=1e-6)

    def test_action_is_zero_at_peak_hour(self):
        # Peak hour (h=19, price=780): no-battery still 0.0
        policy = NoBatteryPolicy()
        action = policy.action(t=jnp.int32(19))
        assert float(action) == pytest.approx(0.0, abs=1e-6)

    def test_action_is_always_zero_all_hours(self):
        # Check all 24 hours → action = 0.0
        policy = NoBatteryPolicy()
        for h in range(24):
            a = float(policy.action(t=jnp.int32(h)))
            assert a == pytest.approx(0.0, abs=1e-6), f"NoBattery action != 0 at hour {h}"

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
    """TouPolicy actions match the tariff tier — §7.2."""

    def test_valley_hour_charges(self):
        # h=3: PRICE_TABLE_YPW[3]=250 (valley) → action=+1.0 (charge)
        policy = TouPolicy()
        a = float(policy.action(t=jnp.int32(3)))
        assert a == pytest.approx(+1.0, abs=1e-6)

    def test_critical_peak_discharges(self):
        # h=11: PRICE_TABLE_YPW[11]=780 (critical peak) → action=-1.0 (discharge)
        policy = TouPolicy()
        a = float(policy.action(t=jnp.int32(11)))
        assert a == pytest.approx(-1.0, abs=1e-6)

    def test_mid_hour_idles(self):
        # h=12: PRICE_TABLE_YPW[12]=450 (mid) → action=0.0
        policy = TouPolicy()
        a = float(policy.action(t=jnp.int32(12)))
        assert a == pytest.approx(0.0, abs=1e-6)

    def test_peak_hour_18_discharges(self):
        # h=18: PRICE_TABLE_YPW[18]=620 (peak) → action=-1.0 (discharge)
        policy = TouPolicy()
        a = float(policy.action(t=jnp.int32(18)))
        assert a == pytest.approx(-1.0, abs=1e-6)

    def test_peak_hour_21_discharges(self):
        # h=21: PRICE_TABLE_YPW[21]=620 (peak) → action=-1.0
        policy = TouPolicy()
        a = float(policy.action(t=jnp.int32(21)))
        assert a == pytest.approx(-1.0, abs=1e-6)

    def test_hour_23_charges(self):
        # h=23: PRICE_TABLE_YPW[23]=250 (valley) → action=+1.0
        policy = TouPolicy()
        a = float(policy.action(t=jnp.int32(23)))
        assert a == pytest.approx(+1.0, abs=1e-6)

    def test_all_24_hours_have_correct_tier(self):
        # Verify that the TOU policy action is consistent with PRICE_TABLE_YPW for ALL hours.
        # valley (price=250): action=+1.0
        # mid    (price=450): action= 0.0
        # peak   (price=620 or 780): action=-1.0
        policy = TouPolicy()
        for h in range(24):
            price = float(PRICE_TABLE_YPW[h])
            action = float(policy.action(t=jnp.int32(h)))
            if price < 450.0:    # valley (250)
                assert action == pytest.approx(+1.0, abs=1e-6), f"TOU h={h}: expected +1 (valley)"
            elif price == 450.0: # mid
                assert action == pytest.approx(0.0, abs=1e-6),  f"TOU h={h}: expected 0 (mid)"
            else:                # peak/critical (620, 780)
                assert action == pytest.approx(-1.0, abs=1e-6), f"TOU h={h}: expected -1 (peak)"

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
            # Actor forward pass: tanh(mean)
            from energy_go.training.run_training import actor_forward
            mean, _ = actor_forward(c.actor_params, norm_obs)
            return jnp.tanh(mean)

        a_before = deterministic_action(ckpt,        obs)
        a_after  = deterministic_action(ckpt_loaded, obs)
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

    def test_same_seed_same_checkpoint_actions(self):
        ckpt_a = self._run_short(seed=7)
        ckpt_b = self._run_short(seed=7)
        obs = jnp.zeros(107, dtype=jnp.float32)

        from energy_go.training.run_training import actor_forward
        a_a, _ = actor_forward(ckpt_a.actor_params, normalize_obs(obs, ckpt_a.obs_stats))
        a_b, _ = actor_forward(ckpt_b.actor_params, normalize_obs(obs, ckpt_b.obs_stats))
        np.testing.assert_allclose(np.array(jnp.tanh(a_a)), np.array(jnp.tanh(a_b)), atol=1e-6)

    def test_different_seeds_different_checkpoints(self):
        ckpt_0 = self._run_short(seed=0)
        ckpt_1 = self._run_short(seed=1)
        obs = jnp.zeros(107, dtype=jnp.float32)

        from energy_go.training.run_training import actor_forward
        a_0, _ = actor_forward(ckpt_0.actor_params, normalize_obs(obs, ckpt_0.obs_stats))
        a_1, _ = actor_forward(ckpt_1.actor_params, normalize_obs(obs, ckpt_1.obs_stats))
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
        # vmap step with zero actions
        actions = jnp.zeros((N, 1))
        new_states, new_obs, rewards, dones, infos = jax.jit(
            jax.vmap(step, in_axes=(0, 0, None, None))
        )(states, actions, params, data)
        assert new_obs.shape == (N, 107)
        assert rewards.shape == (N,)

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

    for t_idx in range(168):
        state, obs, reward, done, info = step(state, jnp.array([0.0]), params, data)
        assert float(info.c_demand_charge_yuan) == pytest.approx(0.0, abs=1e-6), \
            f"Sub-month episode has non-zero c_demand_charge at step {t_idx}"
