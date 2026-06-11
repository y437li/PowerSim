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
# Invariant helpers (always importable; no reference implementation required)
# ---------------------------------------------------------------------------
from energy_go.testing.invariants import (
    assert_cost_identities,
    assert_demand_charge_timing,
    assert_energy_conserved,
    assert_episode_invariants,
    assert_physical_bounds,
    assert_soc_dynamics,
    run_determinism_check,
)

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
# JAX env imports (optional — Suite 2 tests are skipped until implemented)
# ---------------------------------------------------------------------------
try:
    import energy_go.env.jax_env as jax_env  # type: ignore[import]
    _JAX_ENV_AVAILABLE = True
except ImportError:
    jax_env = None  # type: ignore[assignment]
    _JAX_ENV_AVAILABLE = False

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

    def test_month_peak_nonnegative(self, episode_rollout):
        # month_peak_mw is a running maximum of p_import → always ≥ 0.
        # Non-blocking fix: renamed from _monotone_within_month which over-promised;
        # a 7-day episode (steps 0..167) stays within Jan so no boundary reset occurs,
        # but the monotonicity assertion is not what this test is set up to verify.
        # Full monotonicity + D10 boundary checks live in TestDemandChargeD10.
        for i, r in enumerate(episode_rollout):
            assert r.new_state.month_peak_mw >= -1e-9, (
                f"Step {i}: negative month_peak {r.new_state.month_peak_mw}")

    def test_total_load_served_plus_unserved_equals_demand(self, year_data, episode_rollout):
        # Conservation: served + unserved = load for every step
        for i, r in enumerate(episode_rollout):
            load_mw = float(year_data["load_mw"][i])
            load_served = (r.wind_to_load_mw + r.solar_to_load_mw
                           + r.bat_to_load_mw + r.grid_to_load_mw)
            total = load_served + r.load_unserved_mw
            assert total == pytest.approx(load_mw, rel=1e-4), (
                f"Step {i}: served+unserved={total:.4f} ≠ demand={load_mw:.4f}")

    def test_per_source_energy_conservation(self, episode_rollout):
        # Per-source conservation (§3.6 row 14, producer assert):
        # wind: to_load + to_bat + to_grid + wind_curtailed == p_wind_mw
        # solar: to_load + to_bat + to_grid + solar_curtailed == p_solar_mw
        for i, r in enumerate(episode_rollout):
            wind_sum = (r.wind_to_load_mw + r.wind_to_bat_mw
                        + r.wind_to_grid_mw + r.wind_curtailed_mw)
            assert wind_sum == pytest.approx(r.p_wind_mw, rel=1e-5, abs=1e-6), (
                f"Step {i}: wind conservation violated: {wind_sum:.6f} ≠ {r.p_wind_mw:.6f}")
            solar_sum = (r.solar_to_load_mw + r.solar_to_bat_mw
                         + r.solar_to_grid_mw + r.solar_curtailed_mw)
            assert solar_sum == pytest.approx(r.p_solar_mw, rel=1e-5, abs=1e-6), (
                f"Step {i}: solar conservation violated: {solar_sum:.6f} ≠ {r.p_solar_mw:.6f}")

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

    def test_all_invariants_via_helpers(self, episode_rollout):
        """
        Run all physics invariants (energy conservation, cost identities,
        physical bounds) using assert_episode_invariants on the 168-step rollout.

        This is the canonical integration check that qa-engineer also runs
        via the qa-verification skill.  If any invariant is violated, the helper
        reports the step index and which invariant failed.
        """
        assert_episode_invariants(
            episode_rollout, PARAMS, energy_tol=1e-5, cost_tol=1e-9)

    def test_soc_dynamics_per_step(self, episode_rollout):
        """
        Verify SOC update formula (§3.2) for every step in the episode rollout
        using assert_soc_dynamics.
        """
        soc = 0.5   # initial SOC of the episode fixture
        for i, r in enumerate(episode_rollout):
            try:
                assert_soc_dynamics(old_soc=soc, result=r, params=PARAMS, tol=1e-5)
            except AssertionError as exc:
                raise AssertionError(f"Step {i}: SOC dynamics check failed\n{exc}") from exc
            soc = r.new_state.soc


# ===========================================================================
# Suite 2: JAX vs reference parity
# (All tests in this class are skipped if energy_go.env.jax_env is not importable)
# ===========================================================================

class TestJaxReferenceParity:
    """
    Assert numerical agreement between the JAX env and the NumPy reference
    implementation on identical inputs (D11 parity special case: Gansu config).

    Tolerance: rel=1e-4 (float32 JAX vs float64 NumPy).

    **Bridge design (contract §9):**
    Both impls run on identical per-step physical inputs via `data_jax` built
    from the reference `year_data` dict.  RNG difference (NumPy vs JAX PRNG) is
    neutralised by setting `price_spread_sigma=0` and `forecast_sigma_max=0` so
    all stochastic terms are deterministically zero.

    API used:
      - `jax_env.EnvState(soc, month_peak, t, rng)` — construct initial state
      - `jax_env.step(state, action, params, data)` — vmappable / jittable step
      - `jax_env.get_obs(state, params, data)` — obs without stepping
      - `jax_env.PRICE_TABLE_YPW[h]` — tariff lookup
    """

    pytestmark = pytest.mark.skipif(
        not _JAX_ENV_AVAILABLE,
        reason="JAX env not yet implemented — parity tests pending",
    )

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def year_data(self):
        return generate_year(seed=0, params=PARAMS)

    @pytest.fixture(scope="class")
    def jax_data(self, year_data):
        """JAX data array aligned to reference year_data (contract §9 bridge).

        data_jax[t] == [wind_mps, irr_wm2, temp_c, load_mw] for every t,
        identical to the inputs reference env_step(…, weather, load, …) receives.
        """
        import jax.numpy as jnp
        data_np = np.stack([
            year_data["wind_mps"],
            year_data["irradiance_wm2"],
            year_data["temperature_c"],
            year_data["load_mw"],
        ], axis=1).astype(np.float32)   # shape (8760, 4)
        return jnp.array(data_np)

    @pytest.fixture(scope="class")
    def noiseless_jax_params(self):
        """EnvParams with all stochastic σ = 0 (neutralise PRNG difference)."""
        return jax_env.EnvParams(price_spread_sigma=0.0, forecast_sigma_max=0.0)

    @pytest.fixture(scope="class")
    def noiseless_ref_params(self):
        """GansuParams with matching σ = 0 for reference env."""
        return GansuParams(price_spread_sigma=0.0, forecast_sigma_max=0.0)

    def _jax_state(self, soc=0.5, month_peak=0.0, t=0, seed=0):
        """Construct a JAX EnvState directly."""
        import jax
        import jax.numpy as jnp
        return jax_env.EnvState(
            soc=jnp.float32(soc),
            month_peak=jnp.float32(month_peak),
            t=jnp.int32(t),
            rng=jax.random.PRNGKey(seed),
        )

    # ------------------------------------------------------------------
    # Tariff parity (uses PRICE_TABLE_YPW, no step needed)
    # ------------------------------------------------------------------

    @pytest.mark.slow  # requires JAX env import (Suite 2 is skipif JAX unavailable)
    def test_tariff_parity_all_hours(self):
        """PRICE_TABLE_YPW[h] agrees with get_price(h, 0) for all 24 hours."""
        for h in range(24):
            ref = get_price(h, 0)
            jax_val = float(jax_env.PRICE_TABLE_YPW[h])
            assert jax_val == pytest.approx(ref, abs=0.1), (
                f"PRICE_TABLE_YPW[{h}]={jax_val} ≠ get_price({h},0)={ref}")

    # ------------------------------------------------------------------
    # Per-formula parity: test via step() with isolated data rows
    # ------------------------------------------------------------------

    @pytest.mark.slow  # builds jax_data (scope=class) and calls jax_env.step
    def test_wind_power_parity(self, jax_data, noiseless_jax_params, noiseless_ref_params):
        """wind_power output agrees to PARITY_TOL for a range of wind speeds."""
        import jax.numpy as jnp
        test_speeds = [0.0, 2.0, 3.0, 6.0, 12.0, 15.0, 25.0, 26.0]
        for v in test_speeds:
            ref = wind_power(v, noiseless_ref_params)
            # Isolate wind: set irr=0 (no solar), load=0, wind=v at t=0
            data = jax_data.at[0, 0].set(float(v)).at[0, 1].set(0.0).at[0, 3].set(0.0)
            state = self._jax_state(t=0)
            act = jnp.zeros(6)
            _, _, _, _, info = jax_env.step(state, act, noiseless_jax_params, data)
            jax_val = float(info.p_wind_mw)
            assert jax_val == pytest.approx(ref, rel=PARITY_TOL, abs=1e-6), (
                f"wind_power at v={v}: ref={ref:.4f}, jax={jax_val:.4f}")

    @pytest.mark.slow  # builds jax_data (scope=class) and calls jax_env.step
    def test_solar_power_parity(self, jax_data, noiseless_jax_params, noiseless_ref_params):
        """solar_power output agrees to PARITY_TOL for a range of (G, T) pairs."""
        import jax.numpy as jnp
        test_cases = [
            (0.0, 25.0), (800.0, 35.0), (1000.0, 25.0),
            (1000.0, -80.0), (1000.0, 400.0),
        ]
        for G, T in test_cases:
            ref = solar_power(G, T, noiseless_ref_params)
            # Isolate solar: wind=0 (below cutin), load=0
            data = (jax_data
                    .at[0, 0].set(0.0)   # v < v_cutin → P_wind=0
                    .at[0, 1].set(float(G))
                    .at[0, 2].set(float(T))
                    .at[0, 3].set(0.0))
            state = self._jax_state(t=0)
            act = jnp.zeros(6)
            _, _, _, _, info = jax_env.step(state, act, noiseless_jax_params, data)
            jax_val = float(info.p_pv_mw)
            assert jax_val == pytest.approx(ref, rel=PARITY_TOL, abs=1e-6), (
                f"solar_power at G={G},T={T}: ref={ref:.4f}, jax={jax_val:.4f}")

    # ------------------------------------------------------------------
    # Single-step full field parity
    # ------------------------------------------------------------------

    def test_single_step_parity(
        self, jax_data, noiseless_jax_params, noiseless_ref_params, year_data
    ):
        """One step: all EnvInfo fields agree to PARITY_TOL (noiseless params)."""
        import jax
        import jax.numpy as jnp

        t = 500
        action_np = np.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.6])
        seed = 77

        # Reference run
        ref_state = make_ref_state(t=t, soc=0.5, seed=seed)
        weather = (float(year_data["wind_mps"][t]),
                   float(year_data["irradiance_wm2"][t]),
                   float(year_data["temperature_c"][t]))
        load = float(year_data["load_mw"][t])
        ref_result = env_step(ref_state, action_np, weather, load, noiseless_ref_params)

        # JAX run — data_jax[t] carries the same (wind, irr, temp, load) values
        jax_state = self._jax_state(t=t, seed=seed)
        new_jax_state, _, reward_jax, _, info = jax_env.step(
            jax_state, jnp.array(action_np), noiseless_jax_params, jax_data)

        # Core physics fields (all in EnvInfo)
        checks = [
            ("p_wind_mw",      float(info.p_wind_mw),              ref_result.p_wind_mw),
            ("p_pv_mw",        float(info.p_pv_mw),                ref_result.p_solar_mw),
            ("p_bat_ch_mw",    float(info.p_bat_ch_mw),            ref_result.p_bat_charge_mw),
            ("p_bat_dis_mw",   float(info.p_bat_dis_mw),           ref_result.p_bat_discharge_mw),
            ("soc_viol_mwh",   float(info.soc_violation_mwh),      ref_result.soc_violation_mwh),
            ("p_import_mw",    float(info.p_import_mw),            ref_result.p_import_mw),
            ("p_export_mw",    float(info.p_export_mw),            ref_result.p_export_mw),
            # p_load_served_mw = Σ {wind,solar,bat,grid}→load
            ("p_load_served",  float(info.p_load_served_mw),
             ref_result.wind_to_load_mw + ref_result.solar_to_load_mw
             + ref_result.bat_to_load_mw + ref_result.grid_to_load_mw),
            ("p_unserved",     float(info.p_load_unserved_mw),     ref_result.load_unserved_mw),
            # p_curtailed_mw = wind_curtailed + solar_curtailed (no bat curtailment at PCC)
            ("p_curtailed",    float(info.p_curtailed_mw),
             ref_result.wind_curtailed_mw + ref_result.solar_curtailed_mw),
            ("c_energy",       float(info.c_energy_yuan),          ref_result.c_energy_yuan),
            ("c_demand_shape", float(info.c_demand_shape_yuan),    ref_result.c_demand_shape_yuan),
            ("c_degradation",  float(info.c_degradation_yuan),     ref_result.c_degradation_yuan),
            ("c_curtail",      float(info.c_curtail_yuan),         ref_result.c_curtail_yuan),
            ("c_voll",         float(info.c_voll_yuan),            ref_result.c_voll_yuan),
            ("penalty",        float(info.penalty_yuan),           ref_result.penalty_yuan),
            ("cost_rb",        float(info.cost_total_reward_basis_yuan),
             ref_result.cost_total_reward_basis_yuan),
            ("reward",         float(reward_jax),                  ref_result.reward),
            ("new_soc",        float(new_jax_state.soc),           ref_result.new_state.soc),
            # month_peak field name: JAX uses .month_peak, ref uses .month_peak_mw
            ("new_month_peak", float(new_jax_state.month_peak),    ref_result.new_state.month_peak_mw),
        ]
        for name, jax_val, ref_val in checks:
            assert jax_val == pytest.approx(ref_val, rel=PARITY_TOL, abs=1e-6), (
                f"{name}: jax={jax_val:.6f} ≠ ref={ref_val:.6f}")

    # ------------------------------------------------------------------
    # Multi-step SOC trajectory
    # ------------------------------------------------------------------

    @pytest.mark.slow  # 24-step JAX trajectory with jax_data
    def test_multi_step_soc_trajectory_parity(
        self, jax_data, noiseless_jax_params, noiseless_ref_params, year_data
    ):
        """SOC trajectory over 24 steps matches between ref and JAX (fixed action)."""
        import jax.numpy as jnp

        seed = 42
        action_np = np.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.7])
        action_jax = jnp.array(action_np)

        ref_state = make_ref_state(t=0, soc=0.5, seed=seed)
        jax_state = self._jax_state(t=0, seed=seed)

        for i in range(24):
            weather = (float(year_data["wind_mps"][i]),
                       float(year_data["irradiance_wm2"][i]),
                       float(year_data["temperature_c"][i]))
            load = float(year_data["load_mw"][i])

            ref_result = env_step(ref_state, action_np, weather, load, noiseless_ref_params)
            new_jax_state, _, _, _, _ = jax_env.step(
                jax_state, action_jax, noiseless_jax_params, jax_data)

            assert float(new_jax_state.soc) == pytest.approx(
                ref_result.new_state.soc, rel=PARITY_TOL, abs=1e-5), (
                f"SOC mismatch at step {i}: "
                f"jax={float(new_jax_state.soc):.6f} ref={ref_result.new_state.soc:.6f}")

            ref_state = ref_result.new_state
            jax_state = new_jax_state

    # ------------------------------------------------------------------
    # Obs parity (uses get_obs directly — noiseless so forecast is deterministic)
    # ------------------------------------------------------------------

    @pytest.mark.slow  # builds jax_data (scope=class) and calls jax_env.get_obs
    def test_obs_parity_single_step(
        self, jax_data, noiseless_jax_params, noiseless_ref_params, year_data
    ):
        """107-dim obs agrees between ref get_obs and JAX get_obs (noiseless params)."""
        t = 300
        seed = 13
        price_buy = get_price(t % 24, 0)

        ref_state = make_ref_state(t=t, soc=0.5, seed=seed)
        ref_obs = get_obs(ref_state, year_data, noiseless_ref_params, price_buy)

        jax_state = self._jax_state(t=t, seed=seed)
        jax_obs = np.array(jax_env.get_obs(jax_state, noiseless_jax_params, jax_data))

        assert ref_obs.shape == jax_obs.shape == (107,)
        # Base block (fully deterministic): tight tolerance
        np.testing.assert_allclose(ref_obs[:11], jax_obs[:11], rtol=1e-5, atol=1e-6,
                                    err_msg="Base obs block mismatch")
        # Forecast block (noiseless → deterministic true values): 1e-4 for float32 vs float64
        np.testing.assert_allclose(ref_obs[11:], jax_obs[11:], rtol=PARITY_TOL, atol=1e-4,
                                    err_msg="Forecast obs block mismatch")

    # ------------------------------------------------------------------
    # JAX compilation: jit + vmap
    # ------------------------------------------------------------------

    @pytest.mark.slow  # triggers jax.jit compilation on jax_data
    def test_jit_matches_eager(self, jax_data, noiseless_jax_params):
        """jit(step) gives the same result as eager step (verifies jnp.where purity)."""
        import jax
        import jax.numpy as jnp

        state = self._jax_state(t=200, seed=55)
        action = jnp.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.6])

        eager_ns, _, eager_r, _, _ = jax_env.step(state, action, noiseless_jax_params, jax_data)
        jitted = jax.jit(jax_env.step)
        jit_ns, _, jit_r, _, _ = jitted(state, action, noiseless_jax_params, jax_data)

        assert float(jit_r) == pytest.approx(float(eager_r), rel=1e-6), (
            "jit(step) reward ≠ eager reward")
        assert float(jit_ns.soc) == pytest.approx(float(eager_ns.soc), rel=1e-7), (
            "jit(step) SOC ≠ eager SOC")

    @pytest.mark.slow  # triggers jax.jit(jax.vmap(...)) compilation on jax_data
    def test_vmap_over_batch(self, jax_data, noiseless_jax_params):
        """vmap(step, in_axes=(0,0,None,None)) gives identical results for equal inputs."""
        import jax
        import jax.numpy as jnp

        batch_size = 8
        single_state = self._jax_state(t=100)
        batch_state = jax.tree_util.tree_map(
            lambda x: jnp.stack([x] * batch_size), single_state)
        batch_action = jnp.zeros((batch_size, 6))

        batched_step = jax.jit(jax.vmap(jax_env.step, in_axes=(0, 0, None, None)))
        batch_ns, _, batch_r, _, batch_info = batched_step(
            batch_state, batch_action, noiseless_jax_params, jax_data)

        # All elements must be identical (identical inputs)
        socs = np.array(batch_ns.soc)
        rewards = np.array(batch_r)
        assert np.allclose(socs, socs[0], rtol=1e-7), "vmap SOC differs across identical envs"
        assert np.allclose(rewards, rewards[0], rtol=1e-7), "vmap reward differs across identical envs"

    # ------------------------------------------------------------------
    # Full-year cumulative parity (decisive D11 test)
    # ------------------------------------------------------------------

    @pytest.mark.slow  # 8760-step JAX trajectory — decisive D11 cross-check
    def test_full_eval_episode_parity(
        self, jax_data, noiseless_jax_params, noiseless_ref_params, year_data
    ):
        """8760-step eval: cumulative reward agrees to rel=1e-3 between ref and JAX.

        Tolerance loosened to 1e-3 for float32 accumulation over 8760 steps.
        This is the decisive D11 parity cross-check.
        """
        import jax
        import jax.numpy as jnp

        eval_jax_params = jax_env.EnvParams(
            episode_len=8760, price_spread_sigma=0.0, forecast_sigma_max=0.0)

        seed = 0
        action_np = np.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.7])
        action_jax = jnp.array(action_np)

        ref_state = make_ref_state(t=0, soc=0.5, seed=seed)
        jax_state = self._jax_state(t=0, seed=seed)
        ref_cum = 0.0
        jax_cum = 0.0

        for t in range(EVAL_STEPS):
            weather = (float(year_data["wind_mps"][t]),
                       float(year_data["irradiance_wm2"][t]),
                       float(year_data["temperature_c"][t]))
            load = float(year_data["load_mw"][t])

            ref_result = env_step(ref_state, action_np, weather, load, noiseless_ref_params)
            new_jax_state, _, jax_r, _, _ = jax_env.step(
                jax_state, action_jax, eval_jax_params, jax_data)

            ref_cum += ref_result.reward
            jax_cum += float(jax_r)
            ref_state = ref_result.new_state
            jax_state = new_jax_state

        assert jax_cum == pytest.approx(ref_cum, rel=1e-3), (
            f"Cumulative reward mismatch over {EVAL_STEPS} steps: "
            f"ref={ref_cum:.4f}, jax={jax_cum:.4f}")

    # ------------------------------------------------------------------
    # Month-boundary demand-charge parity  (reviewer-added, PR #33 round-3)
    # ------------------------------------------------------------------

    @pytest.mark.slow  # builds jax_data (scope=class) and calls jax_env.step at t=743
    def test_month_boundary_demand_charge_parity(
        self, jax_data, noiseless_jax_params, noiseless_ref_params
    ):
        # reviewer: closes the gap that hid round-2 blocker B-A. The parity suite
        # reviewer: never cross-checked c_demand_charge, so a wrong JAX booking
        # reviewer: formula (it booked P_import*rate instead of peak*rate, and reset
        # reviewer: month_peak to P_import instead of 0) would NOT surface here.
        # reviewer: Step t=743 = last January hour (Jan = 31*24 = 744 h -> t=0..743;
        # reviewer: MONTH_OF_STEP[744]=Feb), so both impls book the demand charge.
        # reviewer:
        # reviewer: month_peak = 500 MW is chosen > grid_max_import_mw (400) so it
        # reviewer: dominates P_import (which is import-capped at <=400) -> the booked
        # reviewer: charge is deterministically max(500, P_import)*rate = 500*32000 =
        # reviewer: 16,000,000 yuan on BOTH impls, independent of the actual P_import.
        # reviewer: Asserts (1) the hand value, (2) cross-impl agreement, (3) both
        # reviewer: reset month_peak to 0 after booking.
        import jax.numpy as jnp
        t = 743
        mp = 500.0
        rate = 32_000.0   # demand_rate_yuan_per_mw_month (EnvParams / GansuParams default)
        expected = mp * rate   # 500 * 32000 = 16,000,000 yuan
        action_np = np.zeros(6)

        # JAX: data_jax[t] carries the weather/load
        jax_state = self._jax_state(soc=0.5, month_peak=mp, t=t)
        new_jax_state, _, _, _, info = jax_env.step(
            jax_state, jnp.array(action_np), noiseless_jax_params, jax_data)

        # Reference: fed the same weather/load that jax_data[t] carries
        ref_state = make_ref_state(soc=0.5, month_peak_mw=mp, t=t)
        weather = (float(jax_data[t, 0]), float(jax_data[t, 1]), float(jax_data[t, 2]))
        load = float(jax_data[t, 3])
        ref_result = env_step(ref_state, action_np, weather, load, noiseless_ref_params)

        # (1) hand-anchored deterministic value (month_peak dominates P_import<=400)
        assert float(info.c_demand_charge_yuan) == pytest.approx(expected, rel=PARITY_TOL), (
            f"JAX c_demand_charge={float(info.c_demand_charge_yuan)} != {expected}")
        assert ref_result.c_demand_charge_yuan == pytest.approx(expected, rel=PARITY_TOL), (
            f"ref c_demand_charge={ref_result.c_demand_charge_yuan} != {expected}")
        # (2) cross-impl agreement
        assert float(info.c_demand_charge_yuan) == pytest.approx(
            ref_result.c_demand_charge_yuan, rel=PARITY_TOL)
        # (3) both reset month_peak to 0 after booking
        assert float(new_jax_state.month_peak) == pytest.approx(0.0, abs=1e-4)
        assert ref_result.new_state.month_peak_mw == pytest.approx(0.0, abs=1e-4)
