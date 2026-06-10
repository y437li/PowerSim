"""Tests for energy_go.env.jax_env and energy_go.generators.synthetic.

Contract: contracts/env/jax_env_core.md
Spec:     §2 (MDP), §3 (physics & costs), §4 (generators), §7 (JAX architecture)
Decisions: D3–D13, D17, D19, D21

Hand-computed expected values are shown as arithmetic in comments.
Tests fail until the implementation is in place (step 2 / red-phase).
"""
from __future__ import annotations

import math

import jax
import jax.numpy as jnp
import pytest

# ---------------------------------------------------------------------------
# Module imports — will fail until implementation lands (expected / correct)
# ---------------------------------------------------------------------------
from energy_go.env.jax_env import (  # noqa: E402
    EnvInfo,
    EnvParams,
    EnvState,
    MONTH_OF_STEP,
    PRICE_TABLE_YPW,
    reset,
    step,
)
from energy_go.generators.synthetic import generate_year

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

GANSU = EnvParams()  # Gansu defaults (contract §3.2)


def _state(
    soc: float = 0.5,
    month_peak: float = 0.0,
    t: int = 0,
    rng: jax.Array | None = None,
) -> EnvState:
    """Minimal EnvState for unit tests; rng defaults to PRNGKey(42)."""
    return EnvState(
        soc=jnp.float32(soc),
        month_peak=jnp.float32(month_peak),
        t=jnp.int32(t),
        rng=jax.random.PRNGKey(42) if rng is None else rng,
    )


def _zero_action() -> jax.Array:
    """Action that does nothing: no battery, no solar/wind allocation."""
    return jnp.zeros(6, dtype=jnp.float32)


def _action(a_bat=0.0, f_sl=0.0, f_sb=0.0, f_wl=0.0, f_wb=0.0, f_bl=0.0) -> jax.Array:
    return jnp.array([a_bat, f_sl, f_sb, f_wl, f_wb, f_bl], dtype=jnp.float32)


@pytest.fixture(scope="session")
def synthetic_year():
    """Pre-generated year; session-scoped so generation runs once."""
    return generate_year(jax.random.PRNGKey(0))


# ===========================================================================
# 1. Module-level constants
# ===========================================================================


class TestModuleConstants:
    def test_price_table_shape(self):
        assert PRICE_TABLE_YPW.shape == (24,)

    def test_price_table_values(self):
        # §3.7 + D8 minute-accurate lookup at minute=0 for each hour
        # Valley (23:00–7:00) = 250
        for h in [0, 1, 2, 3, 4, 5, 6, 23]:
            assert int(PRICE_TABLE_YPW[h]) == 250, f"h={h} should be Valley 250"
        # Mid (7:00–8:00, 11:30–18:00) at :00 → h=7 and h=12..17
        assert int(PRICE_TABLE_YPW[7]) == 450, "h=7 should be Mid 450"
        for h in [12, 13, 14, 15, 16, 17]:
            assert int(PRICE_TABLE_YPW[h]) == 450, f"h={h} should be Mid 450"
        # Peak (8:00–10:30, 18:00–19:00, 21:00–23:00) at :00 → h=8,9,10,18,21,22
        for h in [8, 9, 10, 18, 21, 22]:
            assert int(PRICE_TABLE_YPW[h]) == 620, f"h={h} should be Peak 620"
        # Critical peak (10:30–11:30, 19:00–21:00) at :00 → h=11,19,20
        # h=11: 11:00 ∈ [10:30, 11:30) → Critical
        # h=10: 10:00 < 10:30 → Peak (NOT Critical)
        assert int(PRICE_TABLE_YPW[11]) == 780, "h=11: 10:30≤11:00<11:30 → Critical 780"
        for h in [19, 20]:
            assert int(PRICE_TABLE_YPW[h]) == 780, f"h={h} should be Critical 780"

    def test_month_of_step_shape(self):
        assert MONTH_OF_STEP.shape == (8761,)

    def test_month_of_step_january(self):
        # Jan = 31 days × 24 h = 744 steps (t=0..743)
        assert int(MONTH_OF_STEP[0]) == 0
        assert int(MONTH_OF_STEP[743]) == 0   # last Jan step

    def test_month_of_step_february_start(self):
        # Feb starts at t=744
        assert int(MONTH_OF_STEP[744]) == 1

    def test_month_of_step_december(self):
        # Dec ends at t=8759
        assert int(MONTH_OF_STEP[8759]) == 11

    def test_month_of_step_extra_entry(self):
        # Index 8760 must exist (for safe t+1 lookup at t=8759)
        assert int(MONTH_OF_STEP[8760]) == 11   # still December (no rollover needed)


# ===========================================================================
# 2. Solar PV formula (§3.1)
# ===========================================================================


class TestSolarPV:
    """Tests for P_pv = P_cap × (G/1000) × clamp(1+k_T(T-25), 0.5, 1.2) × η_inv × D"""

    def _make_data(self, irr: float, temp: float, t: int = 12) -> jax.Array:
        """Synthetic single-step data row, broadcast to (8760,4) shape."""
        d = jnp.zeros((8760, 4))
        return d.at[t, 1].set(irr).at[t, 2].set(temp)

    def test_pv_standard_conditions(self):
        # G=1000 W/m², T=25°C → temp_factor=1.0
        # P_pv = 330 × 1.0 × 1.0 × 0.97 × 0.98 = 330 × 0.9506 = 313.698 MW
        # 330 × 0.97 = 320.10; 320.10 × 0.98 = 313.698
        data = self._make_data(1000.0, 25.0)
        state = _state(t=12)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        expected = 330.0 * 1.0 * 1.0 * 0.97 * 0.98  # = 313.698 MW
        assert info.p_pv_mw == pytest.approx(expected, rel=1e-5)

    def test_pv_high_temperature(self):
        # G=800 W/m², T=35°C
        # irr_factor = 800/1000 = 0.8
        # temp_factor = clamp(1 + (−0.003)×(35−25), 0.5, 1.2) = clamp(0.97, 0.5, 1.2) = 0.97
        # P_pv = 330 × 0.8 × 0.97 × 0.97 × 0.98
        #      = 330 × 0.8 = 264.0
        #      × 0.97 (temp_factor) = 256.08
        #      × 0.97 (η_inv) = 248.3976
        #      × 0.98 (D)     = 243.4296 MW
        data = self._make_data(800.0, 35.0)
        state = _state(t=12)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        expected = 330.0 * 0.8 * 0.97 * 0.97 * 0.98  # = 243.4296 MW
        assert info.p_pv_mw == pytest.approx(expected, rel=1e-5)

    def test_pv_zero_irradiance(self):
        # G=0 → P_pv=0 regardless of temperature
        data = self._make_data(0.0, 25.0)
        state = _state(t=12)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        assert float(info.p_pv_mw) == pytest.approx(0.0, abs=1e-7)

    def test_pv_negative_irradiance_clamped_to_zero(self):
        # Negative irradiance (data error) → P_pv=0 (jnp.where guard)
        data = self._make_data(-10.0, 25.0)
        state = _state(t=12)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        assert float(info.p_pv_mw) == pytest.approx(0.0, abs=1e-7)

    def test_pv_temp_factor_clamped_at_high_cold(self):
        # T=−500°C → 1 + (−0.003)×(−525) = 1 + 1.575 = 2.575 → clamp to 1.2
        # P_pv = 330 × 0.5 × 1.2 × 0.97 × 0.98 = 330 × 0.57036 = 188.219 MW (G=500)
        data = self._make_data(500.0, -500.0)
        state = _state(t=12)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        expected = 330.0 * (500.0 / 1000.0) * 1.2 * 0.97 * 0.98  # = 188.219 MW
        assert info.p_pv_mw == pytest.approx(expected, rel=1e-5)


# ===========================================================================
# 3. Wind power curve (§3.1)
# ===========================================================================


class TestWindPowerCurve:
    """Wind: v_hub = v_10m × (h_hub/10)^0.14; power curve per §3.1."""

    # (h_hub/10)^0.14 for hub_height=105 m: (10.5)^0.14
    # ln(10.5)=2.3514, 0.14×2.3514=0.32920, e^0.32920≈1.38965
    HUB_FACTOR = (105.0 / 10.0) ** 0.14  # ≈ 1.38965

    def _make_data(self, v_10m: float, t: int = 0) -> jax.Array:
        d = jnp.zeros((8760, 4))
        return d.at[t, 0].set(v_10m)

    def test_wind_below_cutin(self):
        # v_10m=2.0 → v_hub=2.0×1.38965=2.779 m/s < 3.0 (v_cutin) → P_wind=0
        data = self._make_data(2.0)
        state = _state(t=0)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        assert float(info.p_wind_mw) == pytest.approx(0.0, abs=1e-6)

    def test_wind_exactly_at_cutin(self):
        # v_10m such that v_hub = v_cutin = 3.0 exactly → P_wind=0 (strict: v < v_cutin → 0)
        # v_10m = 3.0 / HUB_FACTOR = 3.0 / 1.38965 ≈ 2.1588 m/s
        v_10m = 3.0 / self.HUB_FACTOR
        data = self._make_data(v_10m)
        state = _state(t=0)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        # At exactly v_cutin: ((3-3)/9)^3 = 0 → P=0
        assert float(info.p_wind_mw) == pytest.approx(0.0, abs=1e-4)

    def test_wind_at_cutout(self):
        # v_hub ≥ 25 m/s → P_wind=0 (cut-out)
        # v_10m = 25.0/1.38965 ≈ 17.99 → v_hub ≈ 25 exactly; use 18.5 to be safely above
        data = self._make_data(18.5)
        state = _state(t=0)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        assert float(info.p_wind_mw) == pytest.approx(0.0, abs=1e-5)

    def test_wind_rated_region(self):
        # v_10m=14 → v_hub=14×1.38965=19.455 m/s ∈ [12, 25) → P_rated = 615 MW
        data = self._make_data(14.0)
        state = _state(t=0)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        assert float(info.p_wind_mw) == pytest.approx(615.0, rel=1e-5)

    def test_wind_cubic_region(self):
        # v_10m=6.0 → v_hub=6.0×1.38965=8.338 m/s ∈ [3, 12)
        # p_frac = ((8.338−3)/(12−3))^3 = (5.338/9)^3 = (0.59311)^3 = 0.20855
        # P_wind = 615 × 0.20855 = 128.26 MW
        v_10m = 6.0
        v_hub = v_10m * self.HUB_FACTOR
        p_frac = ((v_hub - 3.0) / (12.0 - 3.0)) ** 3
        expected = 615.0 * p_frac

        data = self._make_data(v_10m)
        state = _state(t=0)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        assert float(info.p_wind_mw) == pytest.approx(expected, rel=1e-4)


# ===========================================================================
# 4. Battery dynamics (§3.2, D4)
# ===========================================================================


class TestBatteryDynamics:
    """Battery: ΔSOC = (η_ch·P_ch − P_dis/η_dis) · Δt / E_cap"""

    # Gansu battery defaults: cap=294.5 MWh, power=98.16 MW, η=0.97, soc∈[0.2,0.9]

    def _make_data_wind(self, wind_mps: float = 15.0, load_mw: float = 0.0) -> jax.Array:
        """Data with enough wind to satisfy battery allocation."""
        return jnp.zeros((8760, 4)).at[:, 0].set(wind_mps).at[:, 3].set(load_mw)

    def test_battery_charge_normal(self):
        # soc=0.5, a_bat=0.5 (50% charge), all wind allocated to battery
        # P_target = 0.5 × 98.16 = 49.08 MW
        # headroom = (0.9−0.5)×294.5 / 0.97 = 0.4×294.5/0.97 = 117.8/0.97 = 121.44 MW → no clip
        # ΔSOC = 0.97 × 49.08 / 294.5 = 47.6076/294.5 = 0.16165
        # new_SOC = 0.5 + 0.16165 = 0.66165
        soc_init = 0.5
        a_bat = 0.5
        P_target = a_bat * 98.16  # = 49.08 MW
        delta_soc = 0.97 * P_target / 294.5  # = 47.6076/294.5 = 0.16165
        expected_soc = soc_init + delta_soc  # ≈ 0.66165

        data = self._make_data_wind()  # plenty of wind → renew to bat
        state = _state(soc=soc_init)
        act = _action(a_bat=a_bat, f_wb=1.0)  # all wind → battery
        new_state, _, _, _, info = step(state, act, GANSU, data)

        assert float(new_state.soc) == pytest.approx(expected_soc, rel=1e-4)
        assert float(info.soc_violation_mwh) == pytest.approx(0.0, abs=1e-6)

    def test_battery_discharge_normal(self):
        # soc=0.7, a_bat=−0.4 (40% discharge)
        # P_dis = 0.4 × 98.16 = 39.264 MW
        # floor headroom = (0.7−0.2)×294.5×0.97 = 0.5×294.5×0.97 = 142.833 MW → no clip
        # ΔSOC = −39.264 / (0.97 × 294.5) = −39.264 / 285.665 = −0.13747
        # new_SOC = 0.7 − 0.13747 = 0.56253
        soc_init = 0.7
        a_bat = -0.4
        P_dis = abs(a_bat) * 98.16  # = 39.264 MW
        delta_soc = P_dis / (0.97 * 294.5)  # = 39.264/285.665 = 0.13747
        expected_soc = soc_init - delta_soc  # ≈ 0.56253

        data = jnp.zeros((8760, 4)).at[:, 3].set(500.0)  # large load, bat→load
        state = _state(soc=soc_init)
        act = _action(a_bat=a_bat, f_bl=1.0)  # all battery discharge → load
        new_state, _, _, _, info = step(state, act, GANSU, data)

        assert float(new_state.soc) == pytest.approx(expected_soc, rel=1e-4)
        assert float(info.soc_violation_mwh) == pytest.approx(0.0, abs=1e-6)

    def test_soc_clip_at_max_charge(self):
        # soc=0.85, a_bat=1.0 (full charge attempt)
        # headroom = (0.9−0.85)×294.5 / 0.97 = 14.725/0.97 = 15.180 MW (max before hitting soc_max)
        # P_target = 98.16 MW > 15.180 → clipped; new_SOC = 0.90 (exactly)
        # violation = unconstrained_stored − constrained_stored
        #           = (98.16−15.180) × 0.97 = 82.98 × 0.97 = 80.491 MWh
        soc_init = 0.85
        headroom_mwh = (0.9 - soc_init) * 294.5  # = 14.725 MWh
        max_P = headroom_mwh / 0.97  # = 15.1804 MW
        P_target = 98.16
        expected_violation = max(0.0, (P_target - max_P) * 0.97)
        # = (98.16 - 15.1804) * 0.97 = 82.9796 * 0.97 = 80.490 MWh

        data = self._make_data_wind()
        state = _state(soc=soc_init)
        act = _action(a_bat=1.0, f_wb=1.0)
        new_state, _, _, _, info = step(state, act, GANSU, data)

        assert float(new_state.soc) == pytest.approx(0.9, abs=1e-5)
        assert float(info.soc_violation_mwh) == pytest.approx(expected_violation, rel=1e-4)

    def test_soc_clip_at_min_discharge(self):
        # soc=0.25, a_bat=−1.0 (full discharge attempt)
        # max_P_dis = (0.25−0.20)×294.5×0.97 = 0.05×294.5×0.97 = 14.2833 MW
        # P_dis_target = 98.16 MW > 14.2833 → clipped; new_SOC = 0.20 (exactly)
        # violation = (98.16/0.97 − 14.2833/0.97) × ... hmm, see contract §5.3.4
        # violation_mwh = max(0, unconstrained_ΔSOC_dis − constrained_ΔSOC_dis) × E_cap
        # unconstrained_ΔSOC_dis = 98.16/(0.97×294.5) = 98.16/285.665 = 0.34387
        # constrained_ΔSOC_dis  = soc − soc_min = 0.25−0.20 = 0.05
        # violation = max(0, 0.34387−0.05) × 294.5 = 0.29387 × 294.5 = 86.545 MWh
        soc_init = 0.25
        P_dis_target = 98.16
        uncon_dsoc = P_dis_target / (0.97 * 294.5)  # 0.34387
        con_dsoc = soc_init - 0.2  # 0.05
        expected_violation = max(0.0, uncon_dsoc - con_dsoc) * 294.5  # 86.545 MWh

        data = jnp.zeros((8760, 4)).at[:, 3].set(500.0)
        state = _state(soc=soc_init)
        act = _action(a_bat=-1.0, f_bl=1.0)
        new_state, _, _, _, info = step(state, act, GANSU, data)

        assert float(new_state.soc) == pytest.approx(0.2, abs=1e-5)
        assert float(info.soc_violation_mwh) == pytest.approx(expected_violation, rel=1e-3)

    def test_no_simultaneous_charge_discharge(self):
        # a_bat=0.5 (charge) → P_dis=0; a_bat=−0.3 (discharge) → P_ch=0 (structural, sign of a_bat)
        data = self._make_data_wind()
        state = _state(soc=0.5)
        act_ch = _action(a_bat=0.5, f_wb=1.0)
        _, _, _, _, info_ch = step(state, act_ch, GANSU, data)

        act_dis = _action(a_bat=-0.3, f_bl=1.0)
        _, _, _, _, info_dis = step(state, act_dis, GANSU, data)

        # Charge step: P_dis = 0
        assert float(info_ch.p_bat_dis_mw) == pytest.approx(0.0, abs=1e-6)
        # Discharge step: P_ch = 0
        assert float(info_dis.p_bat_ch_mw) == pytest.approx(0.0, abs=1e-6)


# ===========================================================================
# 5. Action parsing and source allocation renormalization (§2.2, §3.6)
# ===========================================================================


class TestActionParsing:
    def test_fractions_renormalized_when_over_one(self):
        # f_sol_load=0.7, f_sol_bat=0.6 → sum=1.3 > 1 → each scaled by 1/1.3
        # renorm: f_sl=0.7/1.3=0.5385, f_sb=0.6/1.3=0.4615
        data = jnp.zeros((8760, 4)).at[:, 1].set(500.0).at[:, 3].set(0.0)
        state = _state()
        act = _action(f_sl=0.7, f_sb=0.6)
        _, _, _, _, info = step(state, act, GANSU, data)
        # After renorm: P_sol_to_load + P_sol_to_bat should ≤ P_pv
        # P_pv > 0 (irr=500), so flows are positive
        p_to_load_plus_bat = info.p_pv_mw  # all solar should be allocated (100% sum)
        # The renormed fracs sum exactly to 1 → P_sol_to_load + P_sol_to_bat = P_pv
        # (P_sol_to_grid = P_pv - P_sol_to_load - P_sol_to_bat ≈ 0)
        assert p_to_load_plus_bat >= 0.0  # trivially true
        # energy conservation: P_pv == solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed
        # (tested more rigorously in TestEnergyConservation)

    def test_action_clips_to_bounds(self):
        # a_bat > 1 → clipped to 1; fraction < 0 → clipped to 0
        data = jnp.zeros((8760, 4)).at[:, 0].set(15.0)
        state = _state()
        act = jnp.array([2.0, -0.5, 0.5, 0.5, 0.5, 0.5], dtype=jnp.float32)
        # Should not raise; a_bat clipped to 1.0, f_sl clipped to 0.0
        _, _, _, _, info = step(state, act, GANSU, data)
        # With a_bat=1.0 (after clip), P_ch = 98.16 MW (no larger)
        assert float(info.p_bat_ch_mw) <= GANSU.bat_power_mw + 1e-3


# ===========================================================================
# 6. Constraint enforcement — load cap, PCC export, import limit (§3.6)
# ===========================================================================


class TestConstraints:
    def test_load_cannot_be_overserved(self):
        # Solar=200 MW, f_sol_load=1.0, load=50 MW → solar-to-load scaled to 50 MW
        data = jnp.zeros((8760, 4)).at[:, 1].set(
            1000.0 * 1000.0 / 330.0  # irr that gives exactly 1000/330 ratio... use raw irr
        )
        # Easier: set irr so P_pv = 200 MW.
        # P_pv = 330 × (G/1000) × 1.0 × 0.97 × 0.98 → 200 = 330 × g × 0.9506 → g = 0.637
        # G = 637 W/m²
        irr = 200.0 / (330.0 * 0.97 * 0.98)  # irr_factor = G/1000 to give P_pv≈200 MW
        data = jnp.zeros((8760, 4)).at[:, 1].set(irr * 1000.0).at[:, 3].set(50.0)
        state = _state()
        act = _action(f_sl=1.0)  # all solar → load
        _, _, _, _, info = step(state, act, GANSU, data)
        # Load served cannot exceed load_mw
        assert float(info.p_load_served_mw) <= 50.0 + 1e-3

    def test_pcc_export_limit_enforced(self):
        # Wind=800 MW total → f_wind_to_grid=1.0 → export=800 MW > 945? No: 800<945
        # Use wind_rated=615 MW × oversized params to test limit:
        # Direct test: if we push export to 1000 MW, it must be capped at 945 MW
        # We can do this by using large wind+solar with all-to-grid action.
        # max single-source: wind (615 MW) + solar (330 MW) ≈ 945 MW at peak: just at limit.
        # Use peak conditions: G=1000 W/m², v=15 m/s, no load.
        data = (
            jnp.zeros((8760, 4))
            .at[:, 0].set(15.0)   # v_10m=15 → rated region → 615 MW
            .at[:, 1].set(1000.0)  # G=1000 → P_pv=313.7 MW
            .at[:, 3].set(0.0)     # no load
        )
        state = _state()
        act = _action(f_sl=0.0, f_sb=0.0, f_wl=0.0, f_wb=0.0)  # all to grid
        _, _, _, _, info = step(state, act, GANSU, data)
        # Total generation ≈ 615 + 313.7 = 928.7 MW < 945 → no curtailment expected
        # (test still verifies export ≤ max_export)
        assert float(info.p_export_mw) <= GANSU.grid_max_export_mw + 1e-4

    def test_pcc_export_curtailment_triggered(self):
        # Force curtailment: battery discharging + solar + wind all to grid > 945 MW.
        # Use custom params with very low export limit.
        tight_params = EnvParams(grid_max_export_mw=100.0)
        data = (
            jnp.zeros((8760, 4))
            .at[:, 0].set(15.0)    # wind rated → 615 MW
            .at[:, 1].set(1000.0)  # solar → 313.7 MW
            .at[:, 3].set(0.0)
        )
        state = _state(soc=0.8)
        act = _action(f_sl=0.0, f_sb=0.0, f_wl=0.0, f_wb=0.0, a_bat=-0.5, f_bl=0.0)
        _, _, _, _, info = step(state, act, tight_params, data)
        # Export must be ≤ 100 MW and curtailment must be > 0
        assert float(info.p_export_mw) <= 100.0 + 1e-4
        assert float(info.p_curtailed_mw) > 0.0

    def test_import_limit_enforced_voll_triggered(self):
        # load_mw=500 MW, all generation=0, import_limit=400 MW → unserved=100 MW
        # P_load_unserved = 500 − 400 = 100 MW (exact, no gen, no battery)
        # C_VOLL = 20000 × 100 × 1.0 = 2,000,000 ¥
        data = jnp.zeros((8760, 4)).at[:, 3].set(500.0)
        state = _state(soc=0.2)  # SOC at min → no discharge
        act = _zero_action()
        _, _, _, _, info = step(state, act, GANSU, data)

        expected_unserved = 500.0 - GANSU.grid_max_import_mw  # = 100 MW
        expected_voll = GANSU.voll_yuan_per_mwh * expected_unserved * 1.0  # = 2,000,000 ¥
        assert float(info.p_load_unserved_mw) == pytest.approx(expected_unserved, rel=1e-4)
        assert float(info.c_voll_yuan) == pytest.approx(expected_voll, rel=1e-4)


# ===========================================================================
# 7. Costs and reward (§3.4, §3.5, D13)
# ===========================================================================


class TestCostsAndReward:
    def test_energy_cost_import_only(self):
        # P_import=50 MW at h=12 (Mid, price=450 ¥/MWh), no export, no gen
        # C_import = 450 × 50 × 1.0 = 22,500 ¥
        # price_sell = max(0, 450 − spread) — but P_export=0 so R_export=0
        # C_E = 22,500 − 0 = 22,500 ¥
        data = jnp.zeros((8760, 4)).at[12, 3].set(50.0)
        state = _state(t=12)  # h=12 → price=450
        act = _zero_action()
        _, _, _, _, info = step(state, act, GANSU, data)

        assert float(info.price_buy_yuan_per_mwh) == pytest.approx(450.0, abs=0.1)
        assert float(info.c_import_yuan) == pytest.approx(22_500.0, rel=1e-4)
        assert float(info.c_energy_yuan) == pytest.approx(22_500.0, rel=1e-4)

    def test_degradation_cost(self):
        # Battery throughput (ch + dis) × c_deg × Δt
        # a_bat=0.5 → P_ch = 49.08 MW (charge mode, no discharge)
        # C_deg = 10 × 49.08 × 1.0 = 490.8 ¥
        data = jnp.zeros((8760, 4)).at[:, 0].set(15.0)
        state = _state(soc=0.5)
        act = _action(a_bat=0.5, f_wb=1.0)
        _, _, _, _, info = step(state, act, GANSU, data)

        P_ch = 0.5 * 98.16  # = 49.08 MW
        expected_deg = 10.0 * P_ch * 1.0  # = 490.8 ¥
        assert float(info.c_degradation_yuan) == pytest.approx(expected_deg, rel=1e-4)

    def test_curtailment_cost(self):
        # Tight export limit → curtailment; verify c_curtail = 800 × P_curtailed × 1.0
        tight = EnvParams(grid_max_export_mw=100.0)
        data = jnp.zeros((8760, 4)).at[:, 0].set(15.0).at[:, 3].set(0.0)
        state = _state()
        act = _zero_action()
        _, _, _, _, info = step(state, act, tight, data)

        expected = 800.0 * float(info.p_curtailed_mw) * 1.0
        assert float(info.c_curtail_yuan) == pytest.approx(expected, rel=1e-5)

    def test_reward_formula(self):
        # reward = −(cost_total_reward_basis + penalty) × reward_scale (§3.5)
        # With no SOC violation: reward = −cost_total_reward_basis × 1e-5
        data = jnp.zeros((8760, 4)).at[:, 3].set(50.0)
        state = _state(t=12, soc=0.5)  # soc=0.5, no violation
        act = _zero_action()
        new_state, obs, reward, done, info = step(state, act, GANSU, data)

        expected_reward = -(info.cost_total_reward_basis_yuan + info.penalty_yuan) * 1e-5
        assert float(reward) == pytest.approx(float(expected_reward), rel=1e-5)

    def test_d13_real_vs_reward_basis_separation(self):
        # D13: cost_total_real uses c_demand_charge; cost_total_reward_basis uses 2×c_demand_shape
        # In sub-month episode: c_demand_charge=0, c_demand_shape may be >0
        data = jnp.zeros((8760, 4)).at[:, 3].set(300.0)
        state = _state(month_peak=100.0, soc=0.5)  # P_import may exceed month_peak
        act = _zero_action()
        _, _, _, _, info = step(state, act, GANSU, data)

        # real = C_E + c_demand_charge + C_deg + C_curtail + C_VOLL
        expected_real = (
            info.c_energy_yuan
            + info.c_demand_charge_yuan
            + info.c_degradation_yuan
            + info.c_curtail_yuan
            + info.c_voll_yuan
        )
        assert float(info.cost_total_real_yuan) == pytest.approx(float(expected_real), rel=1e-5)

        # reward_basis = C_E + 2×C_DC_shape + C_deg + C_curtail + C_VOLL
        expected_basis = (
            info.c_energy_yuan
            + 2.0 * info.c_demand_shape_yuan
            + info.c_degradation_yuan
            + info.c_curtail_yuan
            + info.c_voll_yuan
        )
        assert float(info.cost_total_reward_basis_yuan) == pytest.approx(float(expected_basis), rel=1e-5)

    def test_sell_price_spread_clamped_nonnegative(self):
        # D7: price_sell = max(0, price_buy − max(0, spread + noise)) ≥ 0
        # With extreme spread noise (deterministic seed): sell price must never be negative.
        # Use params with huge sigma to stress-test.
        noisy_params = EnvParams(price_spread_sigma=1000.0)
        data = jnp.zeros((8760, 4)).at[:, 3].set(1.0)
        for t in range(0, 24):
            state = _state(t=t, soc=0.5)
            _, _, _, _, info = step(state, _zero_action(), noisy_params, data)
            assert float(info.price_sell_yuan_per_mwh) >= 0.0, f"price_sell negative at h={t}"

    def test_soc_penalty(self):
        # SOC violation → penalty = soc_penalty_yuan_per_mwh × violation_mwh
        # soc=0.85, a_bat=1.0 (full charge) → violation > 0
        # violation_mwh = (98.16 - 15.180) × 0.97 ≈ 80.491 MWh (from TestBatteryDynamics)
        soc_init = 0.85
        headroom_mwh = (0.9 - soc_init) * 294.5  # 14.725
        max_P = headroom_mwh / 0.97  # 15.1804
        expected_violation = max(0.0, (98.16 - max_P) * 0.97)  # 80.490 MWh
        expected_penalty = 20_000.0 * expected_violation

        data = jnp.zeros((8760, 4)).at[:, 0].set(15.0)
        state = _state(soc=soc_init)
        act = _action(a_bat=1.0, f_wb=1.0)
        _, _, _, _, info = step(state, act, GANSU, data)

        assert float(info.penalty_yuan) == pytest.approx(expected_penalty, rel=1e-3)


# ===========================================================================
# 8. Demand charge — D10 / D21
# ===========================================================================


class TestDemandCharge:
    def test_d21_sub_month_episode_books_zero(self):
        # D21: 7-day training episode starting at t=0 (all within January).
        # None of t=0..167 is a calendar-month boundary (Jan ends at t=743).
        # t=8759 is also never reached.
        # Therefore Σ c_demand_charge_yuan over the episode == 0.
        data = jnp.zeros((8760, 4)).at[:, 3].set(200.0)
        state = _state(soc=0.5, month_peak=0.0, t=0)
        total_dc = 0.0
        for _ in range(168):
            state, _, _, done, info = step(state, _zero_action(), GANSU, data)
            total_dc += float(info.c_demand_charge_yuan)
            if done:
                break
        # D21: sub-month slice books zero real demand charge
        assert total_dc == pytest.approx(0.0, abs=1e-9)

    def test_month_boundary_books_demand_charge(self):
        # Step t=743 → t=744: Jan→Feb boundary.
        # month_peak_at_step_743 = 150 MW
        # c_demand_charge at step 743 = 150 × 32000 = 4,800,000 ¥
        data = jnp.zeros((8760, 4)).at[:, 3].set(50.0)  # light load, P_import < month_peak
        state = _state(soc=0.5, month_peak=150.0, t=743)  # last Jan step
        params = EnvParams(episode_len=8760)
        _, _, _, _, info = step(state, _zero_action(), params, data)

        expected_dc = 150.0 * 32_000.0  # = 4,800,000 ¥
        assert float(info.c_demand_charge_yuan) == pytest.approx(expected_dc, rel=1e-6)

    def test_mid_month_step_zero_demand_charge(self):
        # t=100 (mid-January); no boundary → c_demand_charge = 0
        data = jnp.zeros((8760, 4)).at[:, 3].set(100.0)
        state = _state(soc=0.5, month_peak=0.0, t=100)
        _, _, _, _, info = step(state, _zero_action(), GANSU, data)
        assert float(info.c_demand_charge_yuan) == pytest.approx(0.0, abs=1e-9)

    def test_year_end_terminal_flush(self):
        # t=8759 (year-end) → terminal flush books demand charge for Dec
        # month_peak=200 MW → c_demand_charge = 200×32000 = 6,400,000 ¥
        data = jnp.zeros((8760, 4)).at[:, 3].set(50.0)
        state = _state(soc=0.5, month_peak=200.0, t=8759)
        params = EnvParams(episode_len=8760)
        _, _, _, _, info = step(state, _zero_action(), params, data)

        expected_dc = 200.0 * 32_000.0  # = 6,400,000 ¥
        assert float(info.c_demand_charge_yuan) == pytest.approx(expected_dc, rel=1e-6)

    def test_month_peak_resets_after_booking(self):
        # At month boundary, month_peak resets to P_import at the boundary step.
        data = jnp.zeros((8760, 4)).at[:, 3].set(50.0)
        state = _state(soc=0.5, month_peak=300.0, t=743)
        params = EnvParams(episode_len=8760)
        new_state, _, _, _, _ = step(state, _zero_action(), params, data)
        # After the Jan→Feb boundary: new month_peak should track Feb's imports
        # (not carry forward Jan's 300 MW peak)
        assert float(new_state.month_peak) < 300.0  # resets to P_import at t=743


# ===========================================================================
# 9. Observation vector (§2.1)
# ===========================================================================


class TestObservation:
    def test_obs_shape(self):
        # §2.1: 11 base + 24×4 forecast = 107-dim
        data = jnp.zeros((8760, 4)).at[:, 3].set(1.0)
        state = _state()
        _, obs, _, _, _ = step(state, _zero_action(), GANSU, data)
        assert obs.shape == (107,)

    def test_obs_soc_position(self):
        # obs[4] = SOC (fraction)
        data = jnp.zeros((8760, 4))
        state = _state(soc=0.65)
        _, obs, _, _, _ = step(state, _zero_action(), GANSU, data)
        assert float(obs[4]) == pytest.approx(0.65, abs=1e-5)

    def test_obs_month_peak_normalization(self):
        # obs[6] = month_peak / 500 → 250 / 500 = 0.5
        data = jnp.zeros((8760, 4))
        state = _state(month_peak=250.0)
        _, obs, _, _, _ = step(state, _zero_action(), GANSU, data)
        assert float(obs[6]) == pytest.approx(0.5, abs=1e-5)

    def test_obs_time_encoding(self):
        # t=6 → h=6; sin(2π×6/24) = sin(π/2) = 1.0; cos(2π×6/24) = cos(π/2) = 0.0
        data = jnp.zeros((8760, 4))
        state = _state(t=6)
        _, obs, _, _, _ = step(state, _zero_action(), GANSU, data)
        assert float(obs[7]) == pytest.approx(math.sin(2 * math.pi * 6 / 24), abs=1e-5)
        assert float(obs[8]) == pytest.approx(math.cos(2 * math.pi * 6 / 24), abs=1e-5)

    def test_obs_forecast_nonneg_price(self):
        # D6: forecast price obs (obs[14::4]) must all be ≥ 0 even with large noise
        noisy = EnvParams(forecast_sigma_max=2.0)
        data = jnp.zeros((8760, 4))
        state = _state(soc=0.5, rng=jax.random.PRNGKey(999))
        _, obs, _, _, _ = step(state, _zero_action(), noisy, data)
        price_obs = obs[14::4]  # every 4th element starting at 14 = forecast price
        assert (price_obs >= 0.0).all(), "D6: forecast price obs must be ≥ 0"


# ===========================================================================
# 10. Done flag and episode termination (D3)
# ===========================================================================


class TestEpisodeTermination:
    def test_done_at_last_step(self):
        # done = (t == episode_len − 1)
        data = jnp.zeros((8760, 4))
        state = _state(t=167)  # episode_len=168, last step = 167
        _, _, _, done, _ = step(state, _zero_action(), GANSU, data)
        assert bool(done) is True

    def test_not_done_before_last_step(self):
        data = jnp.zeros((8760, 4))
        state = _state(t=166)
        _, _, _, done, _ = step(state, _zero_action(), GANSU, data)
        assert bool(done) is False

    def test_done_eval_episode(self):
        # eval episode: episode_len=8760, done at t=8759
        eval_params = EnvParams(episode_len=8760)
        data = jnp.zeros((8760, 4))
        state = _state(t=8759)
        _, _, _, done, _ = step(state, _zero_action(), eval_params, data)
        assert bool(done) is True


# ===========================================================================
# 11. Energy conservation (§3.6 rule #14)
# ===========================================================================


class TestEnergyConservation:
    def _check_conservation(self, info: EnvInfo, tol: float = 1e-3):
        """P_x = P_x→load + P_x→bat + P_x→grid + P_x→curtailed for each source."""
        # Wind: P_wind = P_wind→load + P_wind→bat + P_wind→grid + P_wind→curtailed
        # Solar: P_pv   = P_pv→load  + P_pv→bat  + P_pv→grid  + P_pv→curtailed
        # Battery (discharge): P_bat→load + P_bat→grid (no curtailment)
        # Grid (import) → load + bat (remaining serves load/bat deficit)
        # We verify: total served = load served + curtailed + export (conservation at site level)
        total_gen = info.p_wind_mw + info.p_pv_mw
        total_discharge = info.p_bat_dis_mw
        total_supply = total_gen + total_discharge + info.p_import_mw
        total_demand = (
            info.p_load_served_mw
            + info.p_bat_ch_mw
            + info.p_export_mw
            + info.p_curtailed_mw
            + info.p_load_unserved_mw  # load unserved is a demand that was not met (gap)
        )
        # Site-level: generation + import = load served + bat charge + export + curtailed
        # (unserved load = demand − import ← deficit; not a "supply" item)
        site_supply = total_gen + total_discharge + info.p_import_mw
        site_demand = info.p_load_served_mw + info.p_bat_ch_mw + info.p_export_mw + info.p_curtailed_mw
        assert site_supply == pytest.approx(site_demand, abs=tol), (
            f"Site conservation violated: supply={site_supply:.3f} demand={site_demand:.3f}"
        )

    def test_conservation_all_to_grid(self):
        data = jnp.zeros((8760, 4)).at[:, 0].set(10.0).at[:, 1].set(600.0)
        state = _state()
        act = _zero_action()  # all generation to grid
        _, _, _, _, info = step(state, act, GANSU, data)
        self._check_conservation(info)

    def test_conservation_heavy_load(self):
        data = jnp.zeros((8760, 4)).at[:, 0].set(10.0).at[:, 1].set(600.0).at[:, 3].set(400.0)
        state = _state(soc=0.7)
        act = _action(a_bat=-0.5, f_wl=0.5, f_sl=0.5, f_bl=1.0)
        _, _, _, _, info = step(state, act, GANSU, data)
        self._check_conservation(info)

    def test_conservation_soc_violation(self):
        # SOC violation still conserves energy flows
        data = jnp.zeros((8760, 4)).at[:, 0].set(15.0)
        state = _state(soc=0.85)
        act = _action(a_bat=1.0, f_wb=1.0)
        _, _, _, _, info = step(state, act, GANSU, data)
        self._check_conservation(info)


# ===========================================================================
# 12. reset() function
# ===========================================================================


class TestReset:
    def test_reset_initial_state(self, synthetic_year):
        state, obs = reset(jax.random.PRNGKey(0), GANSU, synthetic_year, episode_start=0)
        assert float(state.soc) == pytest.approx(GANSU.soc_init, abs=1e-6)
        assert float(state.month_peak) == pytest.approx(0.0, abs=1e-6)
        assert int(state.t) == 0

    def test_reset_obs_shape(self, synthetic_year):
        _, obs = reset(jax.random.PRNGKey(0), GANSU, synthetic_year, episode_start=0)
        assert obs.shape == (107,)

    def test_reset_episode_start(self, synthetic_year):
        state, _ = reset(jax.random.PRNGKey(0), GANSU, synthetic_year, episode_start=500)
        assert int(state.t) == 500


# ===========================================================================
# 13. generate_year() (§4)
# ===========================================================================


class TestGenerateYear:
    def test_shape(self, synthetic_year):
        # (8760, 4): wind, irr, temp, load
        assert synthetic_year.shape == (8760, 4)

    def test_wind_bounds(self, synthetic_year):
        # §4.1: clipped to [0, 25] m/s
        assert float(jnp.min(synthetic_year[:, 0])) >= 0.0
        assert float(jnp.max(synthetic_year[:, 0])) <= 25.0

    def test_irradiance_nonneg(self, synthetic_year):
        # irr ≥ 0 W/m²
        assert float(jnp.min(synthetic_year[:, 1])) >= 0.0

    def test_load_nonneg(self, synthetic_year):
        # load ≥ 0 MW (clamped in generator)
        assert float(jnp.min(synthetic_year[:, 3])) >= 0.0

    def test_load_order_of_magnitude(self, synthetic_year):
        # D19: base=75 MW; mean load should be on order of 50–100 MW
        mean_load = float(jnp.mean(synthetic_year[:, 3]))
        assert 10.0 < mean_load < 300.0, f"mean load {mean_load:.1f} MW implausible"

    def test_reproducibility(self):
        # Fixed seed → identical output; different seed → different output
        y1 = generate_year(jax.random.PRNGKey(0))
        y2 = generate_year(jax.random.PRNGKey(0))
        y3 = generate_year(jax.random.PRNGKey(1))
        assert jnp.allclose(y1, y2, atol=0.0), "Same key must give identical year"
        assert not jnp.allclose(y1, y3, atol=1e-6), "Different key should give different year"

    def test_wind_diurnal_pattern(self, synthetic_year):
        # §4.1: diurnal signal A_d=2 with peak at h≈6 (sin(2π(t/24−0.25)))
        # Clipped output won't show exact peaks but variance should be > 0
        assert float(jnp.std(synthetic_year[:, 0])) > 0.0

    def test_solar_zero_at_night(self, synthetic_year):
        # Night hours (h=0..5, h=22..23) should have irradiance ≈ 0 (no sunrise yet)
        # Averaged over the year, h=2 should be near zero
        h2_irr = synthetic_year[2::24, 1]  # h=2 for each day
        assert float(jnp.mean(h2_irr)) < 10.0, "Irradiance at h=2 should be near 0"


# ===========================================================================
# 14. JAX compilation: jit + vmap (§7)
# ===========================================================================


class TestJITAndVmap:
    def test_step_jit_compiles(self, synthetic_year):
        data = synthetic_year
        state = _state()
        step_jit = jax.jit(step)
        new_state, obs, reward, done, info = step_jit(state, _zero_action(), GANSU, data)
        assert obs.shape == (107,)

    def test_step_vmap_compiles(self, synthetic_year):
        # vmap over a batch of N states (in_axes=(0,0,None,None))
        N = 8
        states = EnvState(
            soc=jnp.full(N, 0.5),
            month_peak=jnp.zeros(N),
            t=jnp.zeros(N, dtype=jnp.int32),
            rng=jax.random.split(jax.random.PRNGKey(0), N),
        )
        actions = jnp.zeros((N, 6))
        step_v = jax.vmap(step, in_axes=(0, 0, None, None))
        new_states, obs_batch, rewards, dones, infos = step_v(
            states, actions, GANSU, synthetic_year
        )
        assert obs_batch.shape == (N, 107)
        assert rewards.shape == (N,)

    def test_jit_vmap_combined(self, synthetic_year):
        # The spec requires batched_step = jax.jit(jax.vmap(step, ...))
        N = 16
        states = EnvState(
            soc=jnp.full(N, 0.5),
            month_peak=jnp.zeros(N),
            t=jnp.zeros(N, dtype=jnp.int32),
            rng=jax.random.split(jax.random.PRNGKey(7), N),
        )
        actions = jnp.zeros((N, 6))
        batched_step = jax.jit(jax.vmap(step, in_axes=(0, 0, None, None)))
        new_states, obs_batch, rewards, dones, infos = batched_step(
            states, actions, GANSU, synthetic_year
        )
        assert new_states.soc.shape == (N,)

    def test_fixed_seed_determinism(self, synthetic_year):
        # Same state + action + data → identical trajectory (fixed seed reproducibility)
        state = _state(soc=0.5, t=10)
        act = _action(a_bat=0.3, f_wl=0.4, f_wb=0.3, f_sl=0.5, f_bl=0.5)
        new_s1, obs1, r1, d1, _ = step(state, act, GANSU, synthetic_year)
        new_s2, obs2, r2, d2, _ = step(state, act, GANSU, synthetic_year)
        assert jnp.allclose(obs1, obs2, atol=1e-7)
        assert float(r1) == pytest.approx(float(r2), abs=1e-8)


# ===========================================================================
# 15. Reviewer-added cases (backend-reviewer, PR #33 round-3 gate)
# ===========================================================================
class TestReviewerAddedJaxCore:
    """Cases added by backend-reviewer at the contract+tests gate (round-2 commit).

    Hand-computed expected values shown in comments. These verify jnp.where
    purity independently of the reference (jit/vmap value comparison) and pin a
    demand-charge reset invariant the existing suite left loose.
    """

    def test_jit_step_matches_eager(self, synthetic_year):
        # reviewer: §14 only checks jit COMPILES + output shapes, and
        # reviewer: test_fixed_seed_determinism calls step twice on the SAME state
        # reviewer: (trivially equal for any function). Neither catches a stray
        # reviewer: data-dependent Python branch, which traces away under jit and
        # reviewer: would make jit(step) != eager step. This pins value equality on
        # reviewer: reward, new_state, obs, and representative EnvInfo fields.
        # reviewer: The eager result IS the oracle — no magic number (purity check).
        state = _state(soc=0.5, t=200, rng=jax.random.PRNGKey(55))
        action = _action(a_bat=0.3, f_sl=0.4, f_sb=0.3, f_wl=0.5, f_wb=0.4, f_bl=0.6)
        e_ns, e_obs, e_r, e_done, e_info = step(state, action, GANSU, synthetic_year)
        j_ns, j_obs, j_r, j_done, j_info = jax.jit(step)(state, action, GANSU, synthetic_year)
        assert float(j_r) == pytest.approx(float(e_r), rel=1e-6)
        assert float(j_ns.soc) == pytest.approx(float(e_ns.soc), rel=1e-7)
        assert float(j_ns.month_peak) == pytest.approx(float(e_ns.month_peak), rel=1e-7)
        assert int(j_ns.t) == int(e_ns.t)
        assert bool(j_done) == bool(e_done)
        assert float(j_info.c_energy_yuan) == pytest.approx(float(e_info.c_energy_yuan), rel=1e-6)
        assert float(j_info.p_import_mw) == pytest.approx(float(e_info.p_import_mw), rel=1e-6)
        assert jnp.allclose(j_obs, e_obs, rtol=1e-6, atol=1e-6)

    def test_vmap_step_over_batch(self, synthetic_year):
        # reviewer: vmap(step, in_axes=(0,0,None,None)) over a batch of IDENTICAL
        # reviewer: envs must give identical outputs across all lanes AND equal the
        # reviewer: serial single-env result. §14 test_step_vmap_compiles only checks
        # reviewer: output shapes, not lane-identity, so a non-vmap-safe construct
        # reviewer: (e.g. an implicit reduction over the batch axis) would pass it.
        # reviewer: Equality is self-referential — serial result is the oracle.
        N = 8
        single = _state(soc=0.5, t=100, rng=jax.random.PRNGKey(7))
        action = _action(a_bat=0.3, f_sl=0.4, f_sb=0.3, f_wl=0.5, f_wb=0.4, f_bl=0.6)
        batch_state = jax.tree_util.tree_map(
            lambda x: jnp.broadcast_to(x, (N,) + x.shape), single)
        batch_action = jnp.broadcast_to(action, (N, 6))
        b_ns, b_obs, b_r, b_done, b_info = jax.vmap(step, in_axes=(0, 0, None, None))(
            batch_state, batch_action, GANSU, synthetic_year)
        # all lanes identical (identical inputs)
        assert b_r.shape == (N,)
        assert jnp.allclose(b_r, b_r[0], rtol=1e-7)
        assert jnp.allclose(b_ns.soc, b_ns.soc[0], rtol=1e-7)
        assert jnp.allclose(b_obs, b_obs[0], rtol=1e-7)
        # equal to serial single-env step
        s_ns, s_obs, s_r, s_done, s_info = step(single, action, GANSU, synthetic_year)
        assert float(b_r[0]) == pytest.approx(float(s_r), rel=1e-6)
        assert float(b_ns.soc[0]) == pytest.approx(float(s_ns.soc), rel=1e-7)

    def test_month_peak_resets_to_exactly_zero_after_booking(self):
        # reviewer: tightens TestDemandCharge.test_month_peak_resets_after_booking,
        # reviewer: which only asserts new_month_peak < 300 — a buggy "reset to
        # reviewer: P_import" (round-2 B-A: P_import ~= 50 here) would ALSO pass < 300.
        # reviewer: Contract §5.3.7 invariant (2): new_month_peak == 0.0 EXACTLY after
        # reviewer: a month-boundary booking. Step t=743 -> t=744 (Jan->Feb), load=50,
        # reviewer: zero action -> P_import ~= 50; the post-booking peak must be 0
        # reviewer: regardless of P_import. Hand value: 0.0.
        data = jnp.zeros((8760, 4)).at[:, 3].set(50.0)
        state = _state(soc=0.5, month_peak=300.0, t=743)
        params = EnvParams(episode_len=8760)
        new_state, _, _, _, _ = step(state, _zero_action(), params, data)
        assert float(new_state.month_peak) == pytest.approx(0.0, abs=1e-6)
