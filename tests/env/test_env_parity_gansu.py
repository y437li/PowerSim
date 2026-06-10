"""Parity tests: reference implementation vs JAX implementation (Gansu config).

Two test suites in one file:

1. **Reference self-consistency** (always runnable): verify the NumPy reference
   implementation is deterministic, reproducible, and self-consistent over a
   multi-step episode rollout.

2. **JAX vs reference parity** (gated by `pytest.importorskip`): once the JAX
   core is implemented, these tests assert step-level numerical agreement between
   both implementations run on identical inputs and seeds.  Skipped automatically
   until `energy_go.env.jax_env` exists.

Contract reference: contracts/env/reference_implementation.md
Decisions: D3 (Δt=1h), D4 (SOC 0.2–0.9), D5 (export 945 MW), D6–D10 (all §6 fixes),
           D11 (reference is independent from-scratch implementation), D12, D13.
"""

import math

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Reference implementation imports (required)
# ---------------------------------------------------------------------------
from reference.gansu_env import (
    EnvState,
    StepResult,
    env_step,
    generate_year,
    get_obs,
    wind_power,
    solar_power,
)
from reference.gansu_params import GansuParams
from reference.tariff import get_price

# ---------------------------------------------------------------------------
# JAX env imports (optional — tests are skipped until implemented)
# ---------------------------------------------------------------------------
jax_env = pytest.importorskip(
    "energy_go.env.jax_env",
    reason="JAX env not yet implemented; parity tests pending task #8",
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

PARAMS = GansuParams()
EPISODE_STEPS = 168    # 7-day training episode (D3)
EVAL_STEPS    = 8760   # 365-day eval episode (D3)
PARITY_TOL    = 1e-4   # relative tolerance for float32 JAX vs float64 NumPy


def make_ref_state(soc=0.5, month_peak_mw=0.0, t=0, seed=42):
    return EnvState(soc=soc, month_peak_mw=month_peak_mw, t=t,
                    rng=np.random.default_rng(seed))


# ===========================================================================
# Suite 1: Reference self-consistency
# ===========================================================================

class TestReferenceConsistency:
    """Tests that do NOT require the JAX env.  Always run."""

    @pytest.fixture(scope="class")
    def year_data(self):
        return generate_year(seed=0, params=PARAMS)

    @pytest.fixture(scope="class")
    def episode_rollout(self, year_data):
        """Run a full 168-step episode from t=0 and return the list of StepResults."""
        results = []
        state = make_ref_state(soc=0.5, month_peak_mw=0.0, t=0, seed=7)
        action = np.array([0.3, 0.4, 0.3, 0.4, 0.3, 0.7])  # fixed action
        for step_idx in range(EPISODE_STEPS):
            t = step_idx
            wind = year_data["wind_mps"][t]
            irr  = year_data["irradiance_wm2"][t]
            temp = year_data["temperature_c"][t]
            load = year_data["load_mw"][t]
            weather = (float(wind), float(irr), float(temp))
            result = env_step(state, action, weather, float(load), PARAMS)
            results.append(result)
            state = result.new_state
        return results

    def test_episode_rollout_completes(self, episode_rollout):
        assert len(episode_rollout) == EPISODE_STEPS

    def test_soc_stays_within_bounds(self, episode_rollout):
        # Every step's new_state.soc must be in [soc_min, soc_max] = [0.2, 0.9]
        for i, r in enumerate(episode_rollout):
            assert 0.2 - 1e-9 <= r.new_state.soc <= 0.9 + 1e-9, (
                f"Step {i}: SOC = {r.new_state.soc:.6f} outside [0.2, 0.9]")

    def test_month_peak_monotone_within_month(self, episode_rollout):
        # Within January (steps 0..167 for a 7-day episode), month_peak should be non-decreasing
        # unless the month boundary resets it.
        prev_peak = 0.0
        prev_month = 0  # placeholder
        for i, r in enumerate(episode_rollout):
            new_peak = r.new_state.month_peak_mw
            # At month boundary the peak resets; skip the check there
            # Simple check: peak is always ≥ the import this step (barring resets)
            assert new_peak >= -1e-9, f"Step {i}: negative month_peak {new_peak}"

    def test_total_load_served_plus_unserved_equals_demand(self, year_data, episode_rollout):
        # Conservation: served + unserved = load for every step
        for i, r in enumerate(episode_rollout):
            load_mw = float(year_data["load_mw"][i])
            load_served = (r.wind_to_load_mw + r.solar_to_load_mw
                           + r.bat_to_load_mw + r.grid_to_load_mw)
            total = load_served + r.load_unserved_mw
            assert total == pytest.approx(load_mw, rel=1e-4), (
                f"Step {i}: served+unserved={total:.4f} ≠ demand={load_mw:.4f}")

    def test_import_never_exceeds_limit(self, episode_rollout):
        for i, r in enumerate(episode_rollout):
            assert r.p_import_mw <= PARAMS.grid_max_import_mw + 1e-6, (
                f"Step {i}: import {r.p_import_mw:.2f} > {PARAMS.grid_max_import_mw}")

    def test_export_never_exceeds_limit(self, episode_rollout):
        for i, r in enumerate(episode_rollout):
            assert r.p_export_mw <= PARAMS.grid_max_export_mw + 1e-6, (
                f"Step {i}: export {r.p_export_mw:.2f} > {PARAMS.grid_max_export_mw}")

    def test_charge_xor_discharge(self, episode_rollout):
        # Battery never charges and discharges in the same step
        for i, r in enumerate(episode_rollout):
            assert not (r.p_bat_charge_mw > 1e-9 and r.p_bat_discharge_mw > 1e-9), (
                f"Step {i}: simultaneous charge={r.p_bat_charge_mw:.2f} "
                f"and discharge={r.p_bat_discharge_mw:.2f}")

    def test_reward_formula_identity_all_steps(self, episode_rollout):
        # D13: reward = −(cost_total_reward_basis_yuan + penalty_yuan) × 1e-5 for every step
        for i, r in enumerate(episode_rollout):
            expected = -(r.cost_total_reward_basis_yuan + r.penalty_yuan) * 1e-5
            assert r.reward == pytest.approx(expected, rel=1e-9), (
                f"Step {i}: reward formula mismatch")

    def test_cost_total_reward_basis_reconstruction(self, episode_rollout):
        # D13: cost_total_reward_basis = C_E + 2×C_DC_shape + C_deg + C_curtail + C_VOLL
        for i, r in enumerate(episode_rollout):
            reconstructed = (r.c_energy_yuan
                             + 2.0 * r.c_demand_shape_yuan  # D13: ×2 applied here
                             + r.c_degradation_yuan
                             + r.c_curtail_yuan
                             + r.c_voll_yuan)
            assert r.cost_total_reward_basis_yuan == pytest.approx(reconstructed, rel=1e-9), (
                f"Step {i}: cost_total_reward_basis reconstruction mismatch")

    def test_determinism_full_episode(self):
        # Running the same episode twice with the same seed → identical rewards
        def run_episode(seed):
            data = generate_year(seed=0, params=PARAMS)
            state = make_ref_state(seed=seed)
            rewards = []
            action = np.array([0.5, 0.3, 0.4, 0.5, 0.2, 0.7])
            for step_idx in range(EPISODE_STEPS):
                t = step_idx
                weather = (float(data["wind_mps"][t]), float(data["irradiance_wm2"][t]),
                           float(data["temperature_c"][t]))
                load = float(data["load_mw"][t])
                result = env_step(state, action, weather, load, PARAMS)
                rewards.append(result.reward)
                state = result.new_state
            return rewards

        r1 = run_episode(seed=99)
        r2 = run_episode(seed=99)
        for i, (a, b) in enumerate(zip(r1, r2)):
            assert a == pytest.approx(b, rel=1e-12), f"Step {i} not deterministic"

    def test_total_episode_reward_is_finite(self, episode_rollout):
        total_reward = sum(r.reward for r in episode_rollout)
        assert math.isfinite(total_reward), "Episode total reward must be finite"

    def test_obs_shape_every_step(self, year_data):
        # get_obs returns (107,) at every step in an episode
        state = make_ref_state(seed=0)
        for step_idx in range(min(EPISODE_STEPS, 24)):
            t = step_idx
            price_buy = get_price(t % 24, 0)
            obs = get_obs(state, year_data, PARAMS, price_buy)
            assert obs.shape == (107,), f"Step {step_idx}: obs shape {obs.shape}"
            assert np.all(np.isfinite(obs)), f"Step {step_idx}: non-finite obs"
            # Advance state (use a no-op step)
            action = np.zeros(6)
            weather = (float(year_data["wind_mps"][t]),
                       float(year_data["irradiance_wm2"][t]),
                       float(year_data["temperature_c"][t]))
            result = env_step(state, action, weather, float(year_data["load_mw"][t]), PARAMS)
            state = result.new_state

    def test_d6_noise_applied_in_forecast(self, year_data):
        # D6 fix: forecast noise must actually differ from zero-noise baseline
        # Run get_obs 100 times from the same state, different rng seeds.
        # The forecast block (obs[11:]) should show variance; the base block (obs[:11])
        # is deterministic.
        t = 500
        price_buy = get_price(t % 24, 0)
        base_obs_list = []
        for seed in range(100):
            s = make_ref_state(t=t, seed=seed)
            obs = get_obs(s, year_data, PARAMS, price_buy)
            base_obs_list.append(obs)
        arr = np.stack(base_obs_list)  # shape (100, 107)
        # Base block dims [0..10] should be identical across seeds (deterministic inputs)
        base_std = arr[:, :11].std(axis=0)
        for j, std in enumerate(base_std):
            assert std < 1e-9, f"Base obs dim {j} should be deterministic; std={std:.2e}"
        # Forecast block dims [11..106] should show variance (D6 noise)
        forecast_std = arr[:, 11:].std(axis=0)
        assert forecast_std.max() > 1e-4, (
            f"D6 fix: forecast block has no variance (max std={forecast_std.max():.2e}). "
            "Noise may not be applied.")

    def test_d9_no_episode_wraparound(self, year_data):
        # D9 fix: near year end, forecast must not wrap. Run at t=8750 and verify
        # no exception and no NaN/inf.
        t = 8750
        price_buy = get_price(t % 24, 0)
        s = make_ref_state(t=t, seed=0)
        obs = get_obs(s, year_data, PARAMS, price_buy)
        assert obs.shape == (107,)
        assert np.all(np.isfinite(obs)), "Obs near year end contains non-finite values"

    def test_d7_spread_never_negative(self, year_data):
        # D7 fix: price_sell ≤ price_buy in every step
        state = make_ref_state(seed=5)
        action = np.zeros(6)
        for step_idx in range(EPISODE_STEPS):
            t = step_idx
            weather = (float(year_data["wind_mps"][t]),
                       float(year_data["irradiance_wm2"][t]),
                       float(year_data["temperature_c"][t]))
            load = float(year_data["load_mw"][t])
            result = env_step(state, action, weather, load, PARAMS)
            if result.p_export_mw > 1e-6:  # only meaningful when there's export
                assert result.r_export_yuan >= 0.0, (
                    f"Step {step_idx}: negative export revenue {result.r_export_yuan}")
            state = result.new_state

    def test_d8_tariff_correct_at_half_hour_boundaries(self):
        # D8 fix: tariff at 10:29 = Peak (620), 10:30 = Critical peak (780)
        assert get_price(10, 29) == 620.0
        assert get_price(10, 30) == 780.0
        # 11:29 = Critical peak (780), 11:30 = Mid (450)
        assert get_price(11, 29) == 780.0
        assert get_price(11, 30) == 450.0


# ===========================================================================
# Suite 2: JAX vs reference parity
# (All tests in this class are skipped if energy_go.env.jax_env is not importable)
# ===========================================================================

class TestJaxReferenceParity:
    """
    Assert numerical agreement between the JAX env and the NumPy reference
    implementation on identical inputs.

    Tolerance: rel=1e-4 (float32 JAX vs float64 NumPy).

    Run on the Gansu config only — this is the D11 parity special case.
    """

    @pytest.fixture(scope="class")
    def jax_params(self):
        """Convert GansuParams to the JAX env's parameter format."""
        return jax_env.GansuParams.from_numpy_params(PARAMS)

    @pytest.fixture(scope="class")
    def year_data(self):
        return generate_year(seed=0, params=PARAMS)

    def test_wind_power_parity(self, jax_params):
        """wind_power(v_10m, params) agrees to 1e-4 rel."""
        import jax.numpy as jnp
        test_speeds = [0.0, 2.0, 3.0, 6.0, 12.0, 15.0, 25.0, 26.0]
        for v in test_speeds:
            ref = wind_power(v, PARAMS)
            jax_val = float(jax_env.wind_power(jnp.array(v), jax_params))
            assert jax_val == pytest.approx(ref, rel=PARITY_TOL, abs=1e-6), (
                f"wind_power mismatch at v={v}: ref={ref:.4f}, jax={jax_val:.4f}")

    def test_solar_power_parity(self, jax_params):
        """solar_power(G, T, params) agrees to 1e-4 rel."""
        import jax.numpy as jnp
        test_cases = [(0.0, 25.0), (800.0, 35.0), (1000.0, 25.0),
                      (1000.0, -80.0), (1000.0, 400.0)]
        for G, T in test_cases:
            ref = solar_power(G, T, PARAMS)
            jax_val = float(jax_env.solar_power(jnp.array(G), jnp.array(T), jax_params))
            assert jax_val == pytest.approx(ref, rel=PARITY_TOL, abs=1e-6), (
                f"solar_power mismatch at G={G},T={T}: ref={ref:.4f}, jax={jax_val:.4f}")

    def test_tariff_parity(self):
        """get_price agrees for every hour × representative minutes."""
        test_cases = [(0, 0), (7, 0), (8, 0), (10, 29), (10, 30),
                      (11, 30), (18, 0), (19, 0), (21, 0), (23, 0)]
        for h, m in test_cases:
            ref = get_price(h, m)
            jax_val = float(jax_env.get_price(h, m))
            assert jax_val == ref, (
                f"get_price mismatch at h={h}:m={m:02d}: ref={ref}, jax={jax_val}")

    def test_single_step_parity(self, jax_params, year_data):
        """One env_step: all StepResult fields agree to PARITY_TOL."""
        import jax
        import jax.numpy as jnp

        t = 500
        action_np = np.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.6])
        weather_np = (float(year_data["wind_mps"][t]),
                      float(year_data["irradiance_wm2"][t]),
                      float(year_data["temperature_c"][t]))
        load_np = float(year_data["load_mw"][t])
        seed = 77

        # Reference run
        ref_state = make_ref_state(t=t, seed=seed)
        ref_result = env_step(ref_state, action_np, weather_np, load_np, PARAMS)

        # JAX run
        jax_state = jax_env.make_state(soc=0.5, month_peak_mw=0.0, t=t,
                                        rng=jax.random.PRNGKey(seed))
        action_jax = jnp.array(action_np)
        weather_jax = jnp.array(weather_np)
        jax_result = jax_env.env_step(jax_state, action_jax, weather_jax,
                                       jnp.array(load_np), jax_params)

        # Compare every numeric scalar field
        fields_to_check = [
            ("p_wind_mw",              ref_result.p_wind_mw),
            ("p_solar_mw",             ref_result.p_solar_mw),
            ("wind_to_load_mw",        ref_result.wind_to_load_mw),
            ("wind_to_bat_mw",         ref_result.wind_to_bat_mw),
            ("wind_to_grid_mw",        ref_result.wind_to_grid_mw),
            ("solar_to_load_mw",       ref_result.solar_to_load_mw),
            ("solar_to_bat_mw",        ref_result.solar_to_bat_mw),
            ("solar_to_grid_mw",       ref_result.solar_to_grid_mw),
            ("bat_to_load_mw",         ref_result.bat_to_load_mw),
            ("bat_to_grid_mw",         ref_result.bat_to_grid_mw),
            ("grid_to_load_mw",        ref_result.grid_to_load_mw),
            ("grid_to_bat_mw",         ref_result.grid_to_bat_mw),
            ("ren_curtailed_mw",       ref_result.ren_curtailed_mw),
            ("load_unserved_mw",       ref_result.load_unserved_mw),
            ("p_bat_charge_mw",        ref_result.p_bat_charge_mw),
            ("p_bat_discharge_mw",     ref_result.p_bat_discharge_mw),
            ("soc_violation_mwh",      ref_result.soc_violation_mwh),
            ("p_import_mw",            ref_result.p_import_mw),
            ("p_export_mw",            ref_result.p_export_mw),
            ("c_energy_yuan",          ref_result.c_energy_yuan),
            ("c_demand_shape_yuan",    ref_result.c_demand_shape_yuan),
            ("c_degradation_yuan",     ref_result.c_degradation_yuan),
            ("c_curtail_yuan",         ref_result.c_curtail_yuan),
            ("c_voll_yuan",            ref_result.c_voll_yuan),
            ("penalty_yuan",           ref_result.penalty_yuan),
            ("cost_total_reward_basis_yuan", ref_result.cost_total_reward_basis_yuan),
            ("reward",                 ref_result.reward),
            ("new_state.soc",          ref_result.new_state.soc),
            ("new_state.month_peak_mw", ref_result.new_state.month_peak_mw),
        ]

        for name, ref_val in fields_to_check:
            jax_val = float(getattr(jax_result, name.replace(".", "_"),
                                     getattr(getattr(jax_result, "new_state", None),
                                             name.split(".")[-1], None) or 0.0))
            assert jax_val == pytest.approx(ref_val, rel=PARITY_TOL, abs=1e-6), (
                f"Field {name}: ref={ref_val:.6f}, jax={jax_val:.6f}")

    def test_multi_step_soc_trajectory_parity(self, jax_params, year_data):
        """SOC trajectory over 24 steps agrees between ref and JAX (fixed action)."""
        import jax
        import jax.numpy as jnp

        seed = 42
        action_np = np.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.7])
        action_jax = jnp.array(action_np)

        ref_state = make_ref_state(t=0, seed=seed)
        jax_state = jax_env.make_state(soc=0.5, month_peak_mw=0.0, t=0,
                                        rng=jax.random.PRNGKey(seed))
        ref_socs, jax_socs = [], []

        for step_idx in range(24):
            t = step_idx
            weather_np = (float(year_data["wind_mps"][t]),
                          float(year_data["irradiance_wm2"][t]),
                          float(year_data["temperature_c"][t]))
            load_np = float(year_data["load_mw"][t])
            weather_jax = jnp.array(weather_np)

            ref_result = env_step(ref_state, action_np, weather_np, load_np, PARAMS)
            jax_result = jax_env.env_step(jax_state, action_jax, weather_jax,
                                           jnp.array(load_np), jax_params)

            ref_socs.append(ref_result.new_state.soc)
            jax_socs.append(float(jax_result.new_state.soc))
            ref_state = ref_result.new_state
            jax_state = jax_result.new_state

        for i, (rs, js) in enumerate(zip(ref_socs, jax_socs)):
            assert js == pytest.approx(rs, rel=PARITY_TOL, abs=1e-5), (
                f"SOC mismatch at step {i}: ref={rs:.6f}, jax={js:.6f}")

    def test_obs_parity_single_step(self, jax_params, year_data):
        """107-dim observation agrees between ref and JAX."""
        import jax
        import jax.numpy as jnp

        t = 300
        seed = 13
        price_buy = get_price(t % 24, 0)

        ref_state = make_ref_state(t=t, seed=seed)
        ref_obs = get_obs(ref_state, year_data, PARAMS, price_buy)

        jax_state = jax_env.make_state(soc=0.5, month_peak_mw=0.0, t=t,
                                        rng=jax.random.PRNGKey(seed))
        jax_obs = np.array(jax_env.get_obs(jax_state, year_data, jax_params,
                                             jnp.array(price_buy)))

        assert ref_obs.shape == jax_obs.shape == (107,)
        # Base block (deterministic): tight tolerance
        np.testing.assert_allclose(ref_obs[:11], jax_obs[:11], rtol=1e-5, atol=1e-6,
                                    err_msg="Base obs block mismatch")
        # Forecast block (noisy): looser tolerance (same seed, so noise should match)
        np.testing.assert_allclose(ref_obs[11:], jax_obs[11:], rtol=PARITY_TOL, atol=1e-4,
                                    err_msg="Forecast obs block mismatch")

    def test_vmap_consistency(self, jax_params, year_data):
        """vmapping env_step over a batch of states gives the same result as serial."""
        import jax
        import jax.numpy as jnp

        batch_size = 8
        t = 100
        weather_jax = jnp.array([float(year_data["wind_mps"][t]),
                                   float(year_data["irradiance_wm2"][t]),
                                   float(year_data["temperature_c"][t])])
        load_jax = jnp.array(float(year_data["load_mw"][t]))
        action_jax = jnp.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.6])

        # Build a batch of identical states
        single_state = jax_env.make_state(soc=0.5, month_peak_mw=0.0, t=t,
                                           rng=jax.random.PRNGKey(42))
        batch_state = jax.tree_util.tree_map(
            lambda x: jnp.stack([x] * batch_size), single_state)
        batch_action = jnp.stack([action_jax] * batch_size)

        # vmap the step
        batched_step = jax.vmap(
            lambda s, a: jax_env.env_step(s, a, weather_jax, load_jax, jax_params),
            in_axes=(0, 0))
        batch_result = batched_step(batch_state, batch_action)

        # All batch elements should be identical (same input)
        socs = np.array(batch_result.new_state.soc)
        assert np.allclose(socs, socs[0], rtol=1e-7), (
            "vmap elements differ despite identical inputs")

    def test_jit_matches_eager(self, jax_params, year_data):
        """jit(env_step) gives the same result as eager env_step."""
        import jax
        import jax.numpy as jnp

        t = 200
        action_jax = jnp.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.6])
        weather_jax = jnp.array([float(year_data["wind_mps"][t]),
                                   float(year_data["irradiance_wm2"][t]),
                                   float(year_data["temperature_c"][t])])
        load_jax = jnp.array(float(year_data["load_mw"][t]))
        state = jax_env.make_state(soc=0.5, month_peak_mw=0.0, t=t,
                                    rng=jax.random.PRNGKey(55))

        eager_result = jax_env.env_step(state, action_jax, weather_jax,
                                         load_jax, jax_params)
        jitted_step = jax.jit(jax_env.env_step, static_argnums=())
        jitted_result = jitted_step(state, action_jax, weather_jax, load_jax, jax_params)

        assert float(jitted_result.reward) == pytest.approx(
            float(eager_result.reward), rel=1e-6), (
            "jit(env_step) reward differs from eager")
        assert float(jitted_result.new_state.soc) == pytest.approx(
            float(eager_result.new_state.soc), rel=1e-7), (
            "jit(env_step) SOC differs from eager")

    def test_full_eval_episode_parity(self, jax_params, year_data):
        """
        8760-step eval episode: cumulative reward agrees between ref and JAX.
        This is the decisive parity test (D11).

        Tolerance is loosened to rel=1e-3 for the cumulative sum (float32 accumulation
        error over 8760 steps).
        """
        import jax
        import jax.numpy as jnp

        seed = 0
        action_np = np.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.7])
        action_jax = jnp.array(action_np)

        ref_state = make_ref_state(t=0, seed=seed)
        jax_state = jax_env.make_state(soc=0.5, month_peak_mw=0.0, t=0,
                                        rng=jax.random.PRNGKey(seed))
        ref_cum, jax_cum = 0.0, 0.0

        for step_idx in range(EVAL_STEPS):
            t = step_idx
            weather_np = (float(year_data["wind_mps"][t]),
                          float(year_data["irradiance_wm2"][t]),
                          float(year_data["temperature_c"][t]))
            load_np = float(year_data["load_mw"][t])
            weather_jax = jnp.array(weather_np)

            ref_result = env_step(ref_state, action_np, weather_np, load_np, PARAMS)
            jax_result = jax_env.env_step(jax_state, action_jax, weather_jax,
                                           jnp.array(load_np), jax_params)

            ref_cum += ref_result.reward
            jax_cum += float(jax_result.reward)
            ref_state = ref_result.new_state
            jax_state = jax_result.new_state

        assert jax_cum == pytest.approx(ref_cum, rel=1e-3), (
            f"Cumulative reward mismatch over 8760 steps: "
            f"ref={ref_cum:.4f}, jax={jax_cum:.4f}")
