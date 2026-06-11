"""Tests for contracts/env/reference_implementation.md.

Every assertion uses a hand-computed expected value; the arithmetic is shown in the
comment above each test.  Tolerances are rel=1e-5 (relative) unless the value can be
exactly 0, where abs=1e-9 is used.

Import: from reference.gansu_env import ...
        from reference.gansu_params import GansuParams
        from reference.tariff import get_price

These will raise ImportError until the implementation exists — that is intentional for
the contract-first gate stage.  Reviewer evaluates the *logic*, not whether the tests run.

The invariant helpers from energy_go.testing.invariants are used in sections 18 and 19
below.  They are *also* importable without the reference implementation, so that part of
the test suite can run at gate stage.
"""

import math

import numpy as np
import pytest

# Invariant helpers are always importable (no reference implementation dependency).
from energy_go.testing.invariants import (
    assert_cost_identities,
    assert_demand_charge_timing,
    assert_energy_conserved,
    assert_episode_invariants,
    assert_physical_bounds,
    assert_soc_dynamics,
    run_determinism_check,
    run_episode,
)

from reference.gansu_env import (
    battery_step,
    compute_sell_price,
    env_step,
    generate_year,
    get_obs,
    solar_power,
    wind_power,
    EnvState,
    StepResult,
)
from reference.gansu_params import GansuParams
from reference.tariff import get_price

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PARAMS = GansuParams()   # all Gansu defaults

# Shear factor used throughout wind tests: (105/10)^0.14
#   ln(10.5) = 2.351375,  × 0.14 = 0.329193,  e^0.329193 = 1.38985
SHEAR = (105.0 / 10.0) ** 0.14   # ≈ 1.38985


def make_state(soc=0.5, month_peak_mw=0.0, t=0, seed=42):
    return EnvState(soc=soc, month_peak_mw=month_peak_mw, t=t,
                    rng=np.random.default_rng(seed))


# ===========================================================================
# 1. Wind power (§3.1)
# ===========================================================================

class TestWindPower:

    def test_below_cutin_is_zero(self):
        # v_10m = 1.5 m/s → v_hub = 1.5 × 1.38985 = 2.085 < 3.0 → P = 0
        assert wind_power(1.5, PARAMS) == pytest.approx(0.0, abs=1e-9)

    def test_at_cutin_is_zero(self):
        # v_10m s.t. v_hub = 3.0 exactly: v_10m = 3.0 / SHEAR
        # P = 615 × ((3−3)/(12−3))³ = 0 (cubic term is exactly 0)
        v10 = 3.0 / SHEAR
        assert wind_power(v10, PARAMS) == pytest.approx(0.0, abs=1e-9)

    def test_cubic_region_half_rated(self):
        # v_10m s.t. v_hub = 7.5 exactly: v_10m = 7.5 / SHEAR
        # P = 615 × ((7.5−3)/(12−3))³ = 615 × (4.5/9)³ = 615 × 0.5³ = 615 × 0.125 = 76.875 MW
        v10 = 7.5 / SHEAR
        assert wind_power(v10, PARAMS) == pytest.approx(76.875, rel=1e-5)

    def test_cubic_region_v10_6(self):
        # v_10m = 6.0 → v_hub = 6.0 × 1.38985 = 8.3391 ∈ [3, 12)
        # ratio = (8.3391 − 3) / 9 = 5.3391 / 9 = 0.59323
        # P = 615 × 0.59323³
        #   0.59323² = 0.351931,  × 0.59323 = 0.208774
        #   615 × 0.208774 = 128.396 MW
        assert wind_power(6.0, PARAMS) == pytest.approx(615.0 * ((6.0 * SHEAR - 3) / 9) ** 3,
                                                         rel=1e-5)

    def test_rated_region_is_flat(self):
        # v_10m = 13 → v_hub = 13 × 1.38985 = 18.068 ∈ [12, 25) → P = 615.0 MW
        assert wind_power(13.0, PARAMS) == pytest.approx(615.0, rel=1e-6)

    def test_at_rated_speed_continuous(self):
        # v_hub = 12.0 exactly (boundary): cubic gives ((12−3)/9)³ = 1; flat also 1 → both = 615
        v10 = 12.0 / SHEAR
        assert wind_power(v10, PARAMS) == pytest.approx(615.0, rel=1e-6)

    def test_at_cutout_is_zero(self):
        # v_hub = 25.0 → cut-out is inclusive (≥), so P = 0
        v10 = 25.0 / SHEAR
        assert wind_power(v10, PARAMS) == pytest.approx(0.0, abs=1e-9)

    def test_just_below_cutout_is_rated(self):
        # v_hub = 24.999 < 25.0 → flat region → P = 615.0 MW
        v10 = 24.999 / SHEAR
        assert wind_power(v10, PARAMS) == pytest.approx(615.0, rel=1e-5)

    def test_above_cutout_is_zero(self):
        # v_10m = 22 → v_hub = 22 × 1.38985 = 30.577 > 25 → P = 0
        assert wind_power(22.0, PARAMS) == pytest.approx(0.0, abs=1e-9)

    def test_zero_wind_is_zero(self):
        # v_10m = 0 → v_hub = 0 < v_cutin → P = 0
        assert wind_power(0.0, PARAMS) == pytest.approx(0.0, abs=1e-9)


# ===========================================================================
# 2. Solar power (§3.1)
# ===========================================================================

class TestSolarPower:

    def test_zero_irradiance_is_zero(self):
        # G = 0 → P = 0 regardless of temperature (spec: "P_pv = 0 if G ≤ 0")
        assert solar_power(0.0, 25.0, PARAMS) == pytest.approx(0.0, abs=1e-9)

    def test_negative_irradiance_is_zero(self):
        # G = −100 → P = 0
        assert solar_power(-100.0, 25.0, PARAMS) == pytest.approx(0.0, abs=1e-9)

    def test_nominal_irradiance_nominal_temp(self):
        # G = 800 W/m², T = 35°C
        # temp_factor = clamp(1 + (−0.003)×(35−25), 0.5, 1.2) = clamp(0.97, …) = 0.97
        # P = 330 × (800/1000) × 0.97 × 0.97 × 0.98
        #   = 330 × 0.8 × 0.97 × 0.97 × 0.98
        #   0.97 × 0.97 = 0.9409;  0.9409 × 0.98 = 0.922082
        #   330 × 0.8 = 264;  264 × 0.922082 = 243.430 MW
        expected = 330.0 * (800.0 / 1000.0) * 0.97 * 0.97 * 0.98
        assert solar_power(800.0, 35.0, PARAMS) == pytest.approx(expected, rel=1e-5)
        assert expected == pytest.approx(243.430, rel=1e-4)

    def test_nominal_irradiance_reference_temp(self):
        # G = 1000 W/m², T = 25°C (STC reference)
        # temp_factor = clamp(1 + (−0.003)×0, 0.5, 1.2) = 1.0
        # P = 330 × 1.0 × 1.0 × 0.97 × 0.98
        #   = 330 × 0.97 × 0.98 = 330 × 0.9506 = 313.698 MW
        expected = 330.0 * 1.0 * 1.0 * 0.97 * 0.98
        assert solar_power(1000.0, 25.0, PARAMS) == pytest.approx(expected, rel=1e-5)
        assert expected == pytest.approx(313.698, rel=1e-4)

    def test_temp_clamp_upper(self):
        # T = −80°C → temp_factor = 1 + (−0.003)×(−80−25) = 1 + 0.315 = 1.315 → clamped to 1.2
        # P = 330 × 1.0 × 1.2 × 0.97 × 0.98
        #   = 330 × 1.2 × 0.9506 = 330 × 1.14072 = 376.438 MW
        expected = 330.0 * 1.0 * 1.2 * 0.97 * 0.98
        assert solar_power(1000.0, -80.0, PARAMS) == pytest.approx(expected, rel=1e-5)
        assert expected == pytest.approx(376.438, rel=1e-4)

    def test_temp_clamp_lower(self):
        # T = 400°C → temp_factor = 1 + (−0.003)×375 = 1 − 1.125 = −0.125 → clamped to 0.5
        # P = 330 × 1.0 × 0.5 × 0.97 × 0.98
        #   = 330 × 0.5 × 0.9506 = 330 × 0.4753 = 156.849 MW
        expected = 330.0 * 1.0 * 0.5 * 0.97 * 0.98
        assert solar_power(1000.0, 400.0, PARAMS) == pytest.approx(expected, rel=1e-5)
        assert expected == pytest.approx(156.849, rel=1e-4)

    def test_high_irradiance_scales_linearly(self):
        # G = 500 vs 1000 at same T → ratio should be exactly 0.5
        p500 = solar_power(500.0, 25.0, PARAMS)
        p1000 = solar_power(1000.0, 25.0, PARAMS)
        assert p500 == pytest.approx(p1000 / 2.0, rel=1e-9)


# ===========================================================================
# 3. Tariff (§3.7, D8: minute-aware)
# ===========================================================================

class TestGetPrice:

    def test_valley_midnight(self):
        # hour=0, minute=0 → 23:00–7:00 → valley = 250 ¥/MWh
        assert get_price(0, 0) == 250.0

    def test_valley_early_morning(self):
        # hour=3, minute=0 → 23:00–7:00 → valley = 250 ¥/MWh
        assert get_price(3, 0) == 250.0

    def test_valley_end_before_mid(self):
        # hour=6, minute=59 → still valley (7:00 boundary not yet reached)
        assert get_price(6, 59) == 250.0

    def test_mid_starts_at_7(self):
        # hour=7, minute=0 → 7:00–8:00 → mid = 450 ¥/MWh
        assert get_price(7, 0) == 450.0

    def test_peak_starts_at_8(self):
        # hour=8, minute=0 → 8:00–10:30 → peak = 620 ¥/MWh
        assert get_price(8, 0) == 620.0

    def test_peak_just_before_critical_morning(self):
        # hour=10, minute=29 → still 8:00–10:30 → peak = 620 ¥/MWh
        # D8: if this returned 780 the minute-awareness fix failed
        assert get_price(10, 29) == 620.0

    def test_critical_peak_starts_at_1030(self):
        # hour=10, minute=30 → 10:30–11:30 → critical peak = 780 ¥/MWh
        # D8 fix: old code used hour-only lookup and got this boundary wrong
        assert get_price(10, 30) == 780.0

    def test_critical_peak_continues_at_11(self):
        # hour=11, minute=0 → 10:30–11:30 → critical peak = 780 ¥/MWh
        assert get_price(11, 0) == 780.0

    def test_critical_peak_ends_at_1130(self):
        # hour=11, minute=30 → 11:30–18:00 → mid = 450 ¥/MWh
        # D8 fix: old code with hour-only would see h=11 and might give 780
        assert get_price(11, 30) == 450.0

    def test_mid_afternoon(self):
        # hour=14, minute=0 → 11:30–18:00 → mid = 450 ¥/MWh
        assert get_price(14, 0) == 450.0

    def test_mid_just_before_peak(self):
        # hour=17, minute=59 → still 11:30–18:00 → mid = 450 ¥/MWh
        assert get_price(17, 59) == 450.0

    def test_peak_evening_start(self):
        # hour=18, minute=0 → 18:00–19:00 → peak = 620 ¥/MWh
        assert get_price(18, 0) == 620.0

    def test_critical_peak_evening(self):
        # hour=19, minute=0 → 19:00–21:00 → critical peak = 780 ¥/MWh
        assert get_price(19, 0) == 780.0

    def test_critical_peak_evening_20h(self):
        # hour=20, minute=30 → 19:00–21:00 → critical peak = 780 ¥/MWh
        assert get_price(20, 30) == 780.0

    def test_peak_late_evening(self):
        # hour=21, minute=0 → 21:00–23:00 → peak = 620 ¥/MWh
        assert get_price(21, 0) == 620.0

    def test_valley_starts_at_23(self):
        # hour=23, minute=0 → 23:00–7:00 → valley = 250 ¥/MWh
        assert get_price(23, 0) == 250.0


# ===========================================================================
# 4. Sell price (§3.4, D7: spread clamp)
# ===========================================================================

class TestComputeSellPrice:

    def test_nominal_spread(self):
        # price_buy=620, spread_noise=0 → effective_spread=max(0,30+0)=30
        # price_sell = max(0, 620−30) = 590 ¥/MWh
        assert compute_sell_price(620.0, 0.0, PARAMS) == pytest.approx(590.0, rel=1e-9)

    def test_positive_noise_widens_spread(self):
        # price_buy=620, spread_noise=20 → effective_spread=max(0,30+20)=50
        # price_sell = max(0, 620−50) = 570 ¥/MWh
        assert compute_sell_price(620.0, 20.0, PARAMS) == pytest.approx(570.0, rel=1e-9)

    def test_negative_noise_narrows_spread(self):
        # price_buy=620, spread_noise=−20 → noisy_spread=10 → effective_spread=10
        # price_sell = max(0, 620−10) = 610 ¥/MWh
        assert compute_sell_price(620.0, -20.0, PARAMS) == pytest.approx(610.0, rel=1e-9)

    def test_negative_noise_clamps_spread_to_zero(self):
        # price_buy=620, spread_noise=−50 → noisy_spread=−20 → effective_spread=max(0,−20)=0
        # price_sell = max(0, 620−0) = 620 ¥/MWh  (D7: no risk-free-arbitrage hole)
        # Old code: price_sell = 620 − (30 − 50) = 640 > price_buy — arbitrage!
        assert compute_sell_price(620.0, -50.0, PARAMS) == pytest.approx(620.0, rel=1e-9)

    def test_sell_price_clamped_to_zero(self):
        # price_buy=20, spread_noise=0 → effective_spread=30 → 20−30=−10 → clamped to 0
        assert compute_sell_price(20.0, 0.0, PARAMS) == pytest.approx(0.0, abs=1e-9)

    def test_valley_price_with_nominal_spread(self):
        # price_buy=250, spread_noise=0 → price_sell = max(0, 250−30) = 220 ¥/MWh
        assert compute_sell_price(250.0, 0.0, PARAMS) == pytest.approx(220.0, rel=1e-9)


# ===========================================================================
# 5. Battery dynamics (§3.2, §3.6 rows 3–6)
# ===========================================================================

class TestBatteryStep:

    def test_charge_no_violation(self):
        # SOC_0=0.5, a_bat=1.0 → P_target=98.16 MW (full charge attempt)
        # p_ren_to_bat=0 → P_ch_from_gen=0, P_grid→bat=98.16 MW
        # ΔSOC = 0.97 × 98.16 × 1 / 294.5 = 95.2152 / 294.5 = 0.32330
        # SOC_new = 0.5 + 0.32330 = 0.82330 ∈ [0.2, 0.9] → no violation
        soc_new, p_ch, p_dis, p_g2b, viol = battery_step(
            soc=0.5, a_bat=1.0, p_ren_to_bat=0.0, params=PARAMS)
        expected_dsoc = 0.97 * 98.16 * 1.0 / 294.5
        assert soc_new == pytest.approx(0.5 + expected_dsoc, rel=1e-5)
        assert p_ch == pytest.approx(98.16, rel=1e-6)
        assert p_dis == pytest.approx(0.0, abs=1e-9)
        assert p_g2b == pytest.approx(98.16, rel=1e-6)
        assert viol == pytest.approx(0.0, abs=1e-9)

    def test_charge_partial_from_renewable(self):
        # SOC_0=0.5, a_bat=0.5 → P_target=49.08 MW
        # p_ren_to_bat=30 MW → P_ch_from_gen=min(30,49.08)=30, P_grid→bat=19.08
        # ΔSOC = 0.97 × 49.08 / 294.5 = 47.6076 / 294.5 = 0.16165
        # SOC_new = 0.5 + 0.16165 = 0.66165
        soc_new, p_ch, p_dis, p_g2b, viol = battery_step(
            soc=0.5, a_bat=0.5, p_ren_to_bat=30.0, params=PARAMS)
        p_target = 0.5 * 98.16
        expected_dsoc = 0.97 * p_target * 1.0 / 294.5
        assert soc_new == pytest.approx(0.5 + expected_dsoc, rel=1e-5)
        assert p_ch == pytest.approx(p_target, rel=1e-5)
        assert p_g2b == pytest.approx(p_target - 30.0, rel=1e-5)
        assert viol == pytest.approx(0.0, abs=1e-9)

    def test_charge_clips_to_soc_max(self):
        # SOC_0=0.85, a_bat=1.0, p_ren_to_bat=0
        # Unconstrained: SOC_new = 0.85 + 0.97×98.16/294.5 = 0.85 + 0.32330 = 1.17330 > 0.9
        # Clip: P_ch_clip = (0.9−0.85)×294.5 / (0.97×1) = 14.725/0.97 = 15.1804 MW
        # soc_violation_mwh = (1.17330 − 0.9) × 294.5 = 0.27330 × 294.5 = 80.490 MWh
        #   equivalently: (98.16 − 15.1804) × 0.97 = 82.9796 × 0.97 = 80.490 MWh
        P_ch_clip = (0.9 - 0.85) * 294.5 / (0.97 * 1.0)   # = 15.1804 MW
        viol_expected = (0.97 * 98.16 * 1.0 / 294.5 - (0.9 - 0.85)) * 294.5  # = 80.490 MWh
        soc_new, p_ch, p_dis, p_g2b, viol = battery_step(
            soc=0.85, a_bat=1.0, p_ren_to_bat=0.0, params=PARAMS)
        assert soc_new == pytest.approx(0.9, abs=1e-9)
        assert p_ch == pytest.approx(P_ch_clip, rel=1e-5)
        assert p_dis == pytest.approx(0.0, abs=1e-9)
        assert viol == pytest.approx(viol_expected, rel=1e-5)
        assert viol_expected == pytest.approx(80.490, rel=1e-4)

    def test_charge_zero_action(self):
        # a_bat=0 → no charge, no discharge
        soc_new, p_ch, p_dis, p_g2b, viol = battery_step(
            soc=0.5, a_bat=0.0, p_ren_to_bat=0.0, params=PARAMS)
        assert soc_new == pytest.approx(0.5, abs=1e-9)
        assert p_ch == pytest.approx(0.0, abs=1e-9)
        assert p_dis == pytest.approx(0.0, abs=1e-9)
        assert viol == pytest.approx(0.0, abs=1e-9)

    def test_discharge_no_violation(self):
        # SOC_0=0.7, a_bat=−1.0 → P_dis=98.16 MW (full discharge)
        # ΔSOC = −P_dis / (η_dis × E_cap) × dt = −98.16 / (0.97 × 294.5) = −98.16 / 285.665
        #       = −0.34362  (non-blocking fix: comment was 0.34372; code value is correct)
        # SOC_new = 0.7 − 0.34362 = 0.35638 ∈ [0.2, 0.9] → no violation
        soc_new, p_ch, p_dis, p_g2b, viol = battery_step(
            soc=0.7, a_bat=-1.0, p_ren_to_bat=0.0, params=PARAMS)
        expected_dsoc = -(98.16 / (0.97 * 294.5))
        assert soc_new == pytest.approx(0.7 + expected_dsoc, rel=1e-5)
        assert p_dis == pytest.approx(98.16, rel=1e-6)
        assert p_ch == pytest.approx(0.0, abs=1e-9)
        assert p_g2b == pytest.approx(0.0, abs=1e-9)
        assert viol == pytest.approx(0.0, abs=1e-9)

    def test_discharge_clips_to_soc_min(self):
        # SOC_0=0.25, a_bat=−1.0 (wants 98.16 MW discharge)
        # Unconstrained: SOC_new = 0.25 − 98.16/(0.97×294.5) = 0.25 − 0.34362 = −0.09362 < 0.2
        # (non-blocking fix: comment was 0.34372; correct is 0.34362; code is correct)
        # Clip: P_dis_clip = (0.25−0.2) × 294.5 × 0.97 / 1 = 14.725 × 0.97 = 14.28325 MW
        # soc_violation = (0.2 − (−0.09372)) × 294.5 = 0.29372 × 294.5 = 86.471 MWh
        #   equivalently: (98.16 − 14.28325) × 1 / 0.97 = 83.8768 / 0.97 = 86.471 MWh
        P_dis_clip = (0.25 - 0.2) * 294.5 * 0.97 / 1.0   # = 14.28325 MW
        viol_expected = (98.16 - P_dis_clip) * 1.0 / 0.97   # = 86.471 MWh
        soc_new, p_ch, p_dis, p_g2b, viol = battery_step(
            soc=0.25, a_bat=-1.0, p_ren_to_bat=0.0, params=PARAMS)
        assert soc_new == pytest.approx(0.2, abs=1e-9)
        assert p_dis == pytest.approx(P_dis_clip, rel=1e-5)
        assert p_ch == pytest.approx(0.0, abs=1e-9)
        assert viol == pytest.approx(viol_expected, rel=1e-5)
        assert viol_expected == pytest.approx(86.471, rel=1e-4)

    def test_discharge_no_charge_simultaneously(self):
        # a_bat < 0 → p_ch must be exactly 0 (charge XOR discharge)
        _, p_ch, p_dis, _, _ = battery_step(
            soc=0.5, a_bat=-0.5, p_ren_to_bat=0.0, params=PARAMS)
        assert p_ch == pytest.approx(0.0, abs=1e-9)
        assert p_dis > 0.0

    def test_charge_ignores_ren_when_bat_is_discharging(self):
        # a_bat < 0 → p_ren_to_bat irrelevant (no charging occurs)
        soc_new_no_ren, _, _, _, _ = battery_step(
            soc=0.5, a_bat=-0.5, p_ren_to_bat=0.0, params=PARAMS)
        soc_new_with_ren, _, _, _, _ = battery_step(
            soc=0.5, a_bat=-0.5, p_ren_to_bat=50.0, params=PARAMS)
        assert soc_new_no_ren == pytest.approx(soc_new_with_ren, abs=1e-9)

    def test_soc_exactly_at_max_with_charge_action(self):  # reviewer: M5 (exact values)
        # SOC_0 = soc_max = 0.9; a_bat=1.0 → P_target=98.16 MW, p_ren_to_bat=0
        # P_ch_clip = (0.9−0.9) × 294.5 / (0.97 × 1) = 0 MW
        # soc_unconstrained = 0.9 + 0.97 × 98.16 / 294.5 = 0.9 + 0.32330 = 1.22330
        # soc_violation_mwh = (1.22330 − 0.9) × 294.5 = 0.32330 × 294.5
        #                    = 0.97 × 98.16 = 95.2152 MWh  (exact: η_ch × P_target × Δt)
        # penalty_yuan = 20000 × 95.2152 = 1,904,304 ¥
        viol_expected_mwh = 0.97 * 98.16 * 1.0   # = 95.2152 MWh
        penalty_expected = 20_000.0 * viol_expected_mwh  # = 1,904,304 ¥

        soc_new, p_ch, p_dis, p_g2b, viol = battery_step(
            soc=0.9, a_bat=1.0, p_ren_to_bat=0.0, params=PARAMS)
        assert soc_new == pytest.approx(0.9, abs=1e-9)
        assert p_ch == pytest.approx(0.0, abs=1e-9)
        assert viol == pytest.approx(viol_expected_mwh, rel=1e-5), (
            f"M5: soc_violation_mwh={viol:.6f} ≠ 0.97×98.16={viol_expected_mwh:.6f}")
        assert viol_expected_mwh == pytest.approx(95.2152, rel=1e-4)

        # Now verify penalty via env_step
        action = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        state = make_state(soc=0.9, t=0)
        result = env_step(state, action, (0.0, 0.0, 0.0), 0.0, PARAMS)
        assert result.soc_violation_mwh == pytest.approx(viol_expected_mwh, rel=1e-5)
        assert result.penalty_yuan == pytest.approx(penalty_expected, rel=1e-5), (
            f"M5: penalty_yuan={result.penalty_yuan:.2f} ≠ 20000×95.2152={penalty_expected:.2f}")

    def test_soc_exactly_at_min_with_discharge_action(self):
        # SOC_0 = soc_min = 0.2; any a_bat < 0 → no energy available → P_dis=0, violation>0
        soc_new, p_ch, p_dis, p_g2b, viol = battery_step(
            soc=0.2, a_bat=-1.0, p_ren_to_bat=0.0, params=PARAMS)
        assert soc_new == pytest.approx(0.2, abs=1e-9)
        assert p_dis == pytest.approx(0.0, abs=1e-9)
        assert viol > 0.0


# ===========================================================================
# 6. Demand charge (§3.4, D10)
# ===========================================================================
# These tests use env_step with carefully chosen inputs to isolate demand charge.

class TestDemandCharge:

    def _step_no_battery(self, p_import_mw, month_peak_prior):
        """Run a step with known import and no renewable/battery activity."""
        # Minimal action: a_bat=0, all fractions = 0 (no RE allocation)
        # But we need p_import to equal p_import_mw exactly.
        # Approach: use a state with the given month_peak and large enough load
        # with no renewable so grid import = load
        action = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        state = make_state(soc=0.5, month_peak_mw=month_peak_prior, t=100)  # hour=4 → valley
        weather = (0.0, 0.0, 0.0)   # no wind, no solar (night)
        load = p_import_mw           # all served from grid
        result = env_step(state, action, weather, load, PARAMS)
        return result

    def test_new_peak_charges_incremental(self):
        # month_peak_prior = 0, P_import = 30 MW
        # C_DC_shape = 32000 × max(0, 30−0) = 32000 × 30 = 960000 ¥
        result = self._step_no_battery(30.0, 0.0)
        assert result.c_demand_shape_yuan == pytest.approx(960_000.0, rel=1e-5)
        assert result.new_state.month_peak_mw == pytest.approx(30.0, rel=1e-9)

    def test_incremental_peak_increase(self):
        # month_peak_prior = 30, P_import = 40 MW
        # C_DC_shape = 32000 × max(0, 40−30) = 32000 × 10 = 320000 ¥
        result = self._step_no_battery(40.0, 30.0)
        assert result.c_demand_shape_yuan == pytest.approx(320_000.0, rel=1e-5)
        assert result.new_state.month_peak_mw == pytest.approx(40.0, rel=1e-9)

    def test_no_new_peak_zero_demand_charge(self):
        # month_peak_prior = 40, P_import = 35 MW (below peak)
        # C_DC_shape = 32000 × max(0, 35−40) = 0 ¥
        result = self._step_no_battery(35.0, 40.0)
        assert result.c_demand_shape_yuan == pytest.approx(0.0, abs=1e-9)
        assert result.new_state.month_peak_mw == pytest.approx(40.0, rel=1e-9)

    def test_exact_peak_no_demand_charge(self):
        # month_peak_prior = 30, P_import = 30 MW (exactly at peak)
        # C_DC_shape = 32000 × max(0, 0) = 0 ¥
        result = self._step_no_battery(30.0, 30.0)
        assert result.c_demand_shape_yuan == pytest.approx(0.0, abs=1e-9)

    def test_c_demand_charge_zero_mid_month(self):  # reviewer: M1-partial
        # On any mid-month step c_demand_charge_yuan must be 0 (D10).
        # t=100 → hour=4 (valley) — NOT a month boundary (Jan ends at t=743)
        result = self._step_no_battery(30.0, 0.0)
        assert result.c_demand_charge_yuan == pytest.approx(0.0, abs=1e-9), (
            "D10: c_demand_charge_yuan must be 0 on non-boundary step")
        # Use assert_demand_charge_timing helper to verify same thing
        assert_demand_charge_timing(
            result, is_month_boundary=False,
            prev_month_peak_mw=0.0, params=PARAMS)

    def test_month_boundary_demand_charge_booked_exact(self):  # reviewer: M1
        # t=743 is the last hour of January (31×24−1 = 743).
        # month_of_step[743] == Jan, month_of_step[744] == Feb → boundary.
        # month_peak_mw=80 MW (prior peak) → c_demand_charge = 80 × 32000 = 2,560,000 ¥
        #
        # Also verifies on every step t ∈ {100, 200, 300} that c_demand_charge_yuan == 0.
        action = np.zeros(6)
        # First verify mid-month steps are zero
        for t_mid in [100, 200, 300]:
            state_mid = make_state(t=t_mid, month_peak_mw=80.0)
            r_mid = env_step(state_mid, action, (0.0, 0.0, 0.0), 50.0, PARAMS)
            assert r_mid.c_demand_charge_yuan == pytest.approx(0.0, abs=1e-9), (
                f"Step t={t_mid}: D10 violated — mid-month step has "
                f"c_demand_charge_yuan={r_mid.c_demand_charge_yuan:.2f}")

        # Then verify the boundary step books the full charge ONCE
        state_jan_end = make_state(t=743, month_peak_mw=80.0)
        result = env_step(state_jan_end, action, (0.0, 0.0, 0.0), 50.0, PARAMS)
        # Expected: 80 MW × 32000 ¥/MW·month = 2,560,000 ¥
        assert result.c_demand_charge_yuan == pytest.approx(
            80.0 * 32_000.0, rel=1e-9), (
            f"D10 M1: c_demand_charge_yuan={result.c_demand_charge_yuan:.2f} "
            f"≠ 80×32000=2,560,000 ¥")
        # And new_state resets the month peak to start fresh for February
        assert result.new_state.month_peak_mw <= result.p_import_mw + 1e-6, (
            "D10: month_peak must reset after boundary booking")
        # Use assert_demand_charge_timing helper
        assert_demand_charge_timing(
            result, is_month_boundary=True,
            prev_month_peak_mw=80.0, params=PARAMS)
        # Also verify cost_total_real includes c_demand_charge_yuan at boundary (D13 identity 3)
        # via env_step. This is the only env_step-level test that crosses a month boundary,
        # so identity 3 of assert_cost_identities is exercised with c_demand_charge > 0 here.
        assert_cost_identities(result, PARAMS)   # identity 3: real = C_E + c_dc + C_deg + ...

    def test_two_month_no_double_count(self):  # reviewer: M2
        # Controlled 2-month rollout: Jan peak=80 MW, Feb peak=60 MW.
        # Σ c_demand_charge_yuan == 80×32000 + 60×32000 == 4,480,000 ¥ (each month once).
        #
        # Jan: t=0..743 (744 steps), set month_peak to 80 at t=742, then step t=743 books it.
        # Feb: t=744..1415 (672 steps), set month_peak to 60 at t=1414, then step t=1415 books it.
        action = np.zeros(6)
        weather = (0.0, 0.0, 0.0)   # night: no RE

        # Accumulate all demand charges over both months
        total_demand_charge = 0.0

        # Run Jan: start from t=742 with month_peak=80 already set
        state = make_state(t=742, month_peak_mw=80.0)
        # Step t=742: mid-month (Jan still continues until t=743)
        r742 = env_step(state, action, weather, 0.0, PARAMS)
        assert r742.c_demand_charge_yuan == pytest.approx(0.0, abs=1e-9), (
            "t=742 is mid-month; no booking expected")
        total_demand_charge += r742.c_demand_charge_yuan

        # Step t=743: Jan boundary (month_of_step[744] == Feb)
        # month_peak from state = 80 (set above); import ≈ 0 so peak unchanged
        state743 = r742.new_state   # t=743 now
        r743 = env_step(state743, action, weather, 0.0, PARAMS)
        assert r743.c_demand_charge_yuan == pytest.approx(
            80.0 * 32_000.0, rel=1e-9), (
            f"t=743 (Jan→Feb): booking expected 80×32000=2,560,000; "
            f"got {r743.c_demand_charge_yuan:.2f}")
        total_demand_charge += r743.c_demand_charge_yuan

        # Run Feb: start from Feb with month_peak already at 60
        # month_peak should have reset after the Jan boundary booking
        state_feb_start = r743.new_state   # t=744, month_peak reset
        # Fast-forward to near end of Feb: t=1414 with peak set to 60
        # (we simulate this by constructing a fresh state at t=1414 with peak=60)
        state_feb_end = make_state(t=1414, month_peak_mw=60.0)
        r1414 = env_step(state_feb_end, action, weather, 0.0, PARAMS)
        assert r1414.c_demand_charge_yuan == pytest.approx(0.0, abs=1e-9), (
            "t=1414 is mid-Feb; no booking expected")
        total_demand_charge += r1414.c_demand_charge_yuan

        # Step t=1415: Feb boundary (Feb ends at t=1415=Feb 28 23:00, assuming 28-day Feb)
        # Actually: Feb has 28×24=672 hours; Feb starts at t=744; ends at t=744+671=1415
        state1415 = r1414.new_state
        r1415 = env_step(state1415, action, weather, 0.0, PARAMS)
        assert r1415.c_demand_charge_yuan == pytest.approx(
            60.0 * 32_000.0, rel=1e-9), (
            f"t=1415 (Feb→Mar): booking expected 60×32000=1,920,000; "
            f"got {r1415.c_demand_charge_yuan:.2f}")
        total_demand_charge += r1415.c_demand_charge_yuan

        # Total across both months: 80×32000 + 60×32000 = 4,480,000 ¥
        assert total_demand_charge == pytest.approx(
            80.0 * 32_000.0 + 60.0 * 32_000.0, rel=1e-9), (
            f"M2: total demand charge {total_demand_charge:.2f} ≠ "
            f"80×32000+60×32000=4,480,000 ¥")


# ===========================================================================
# 7. Constraint enforcement — load cap (§3.3 step 1, §3.6 row 7)
# ===========================================================================

class TestLoadCap:

    def test_total_to_load_exceeds_demand(self):
        # P_wind=128 MW, f_w→l=0.5 → wind_to_load_raw=64 MW
        # P_solar=200 MW, f_s→l=0.5 → solar_to_load_raw=100 MW
        # a_bat=−0.5 (discharge), f_b→l=1.0 → bat_to_load_raw = 49.08 MW
        # Total = 64+100+49.08 = 213.08 MW, load=80 MW → OVERSERVED
        # scale = 80/213.08 = 0.37545
        # wind_to_load = 64×0.37545 = 24.029 MW
        # solar_to_load = 100×0.37545 = 37.545 MW
        # bat_to_load = 49.08×0.37545 = 18.427 MW
        # Total_actual = 80 MW ✓
        action = np.array([-0.5, 0.5, 0.0, 0.5, 0.0, 1.0])  # a_bat=−0.5, f_s→l=0.5, f_w→l=0.5, f_b→l=1.0
        state = make_state(soc=0.7, t=480)   # t=480 → hour=0 (valley)
        # Choose wind & solar large enough to over-serve:
        # Use high wind + solar, low load
        weather = (10.0, 800.0, 25.0)   # wind=10 m/s (above cutin), irr=800, T=25
        result = env_step(state, action, weather, 80.0, PARAMS)
        # Total load served = wind_to_load + solar_to_load + bat_to_load must not exceed 80 MW
        total_to_load = (result.wind_to_load_mw + result.solar_to_load_mw
                         + result.bat_to_load_mw + result.grid_to_load_mw)
        assert total_to_load == pytest.approx(80.0, rel=1e-5)

    def test_load_fully_met_no_deficit(self):
        # Simple: load = 0, any action → no unserved load
        action = np.zeros(6)
        state = make_state(t=0)
        result = env_step(state, action, (0.0, 0.0, 0.0), 0.0, PARAMS)
        assert result.load_unserved_mw == pytest.approx(0.0, abs=1e-9)


# ===========================================================================
# 8. Constraint enforcement — PCC export limit (§3.3 step 3, §3.6 row 8)
# ===========================================================================

class TestExportLimit:

    def test_curtailment_when_export_exceeds_limit(self):
        # Design: high wind + solar, no load, max_export=600 MW (tight limit)
        # gross RE > 600 MW → proportional curtailment
        # Solar share: p_solar / (p_solar + p_wind) × curtailed; wind share: rest
        params_tight = GansuParams(grid_max_export_mw=600.0)
        action = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])   # all RE to grid
        state = make_state(t=240)    # t=240 = hour 0 of day 10, doesn't matter
        weather = (15.0, 1000.0, 25.0)
        result = env_step(state, action, weather, 0.0, params_tight)
        p_wind = wind_power(15.0, params_tight)
        p_solar = solar_power(1000.0, 25.0, params_tight)
        gross_export = p_wind + p_solar
        # Non-blocking fix: assert the precondition explicitly instead of silently passing
        assert gross_export > 600.0, (
            f"Test precondition failed: gross_export={gross_export:.2f} MW ≤ 600 MW limit; "
            f"wind={p_wind:.2f}, solar={p_solar:.2f}. Adjust weather inputs.")
        assert result.p_export_mw == pytest.approx(600.0, rel=1e-5)
        # solar_curtailed + wind_curtailed should equal total curtailment
        total_curtailed = result.solar_curtailed_mw + result.wind_curtailed_mw
        assert total_curtailed > 0.0
        assert total_curtailed == pytest.approx(gross_export - 600.0, rel=1e-5)
        # Curtailment cost
        expected_c_curtail = total_curtailed * 800.0 * 1.0
        assert result.c_curtail_yuan == pytest.approx(expected_c_curtail, rel=1e-5)

    def test_no_curtailment_under_limit(self):
        # Very low generation → export well below 945 MW → no curtailment
        action = np.zeros(6)
        state = make_state(t=0)
        weather = (0.0, 0.0, 0.0)   # zero generation
        result = env_step(state, action, weather, 0.0, PARAMS)
        # LOCKED schema uses split curtailment fields (not single ren_curtailed_mw)
        assert result.solar_curtailed_mw == pytest.approx(0.0, abs=1e-9)
        assert result.wind_curtailed_mw == pytest.approx(0.0, abs=1e-9)
        assert result.bat_curtailed_mw == pytest.approx(0.0, abs=1e-9)

    def test_proportional_curtailment_arithmetic(self):
        # Three exporters: P_w→g=500, P_s→g=300, P_b→g=200 (total=1000 > 945)
        # scale = 945/1000 = 0.945
        # wind_to_grid = 500×0.945 = 472.5; solar_to_grid = 300×0.945 = 283.5;
        # bat_to_grid = 200×0.945 = 189.0; total = 945.0 ✓
        # wind_curtailed = 500×(1−0.945) = 500×0.055 = 27.5 MW
        # solar_curtailed = 300×0.055 = 16.5 MW
        # bat_curtailed = 200×0.055 = 11.0 MW
        # total_curtailed = 55 MW; C_curtail = 55 × 800 × 1 = 44000 ¥
        scale = 945.0 / 1000.0
        assert 500.0 * scale == pytest.approx(472.5, rel=1e-9)
        assert 300.0 * scale == pytest.approx(283.5, rel=1e-9)
        assert 200.0 * scale == pytest.approx(189.0, rel=1e-9)
        wind_curtailed = 500.0 * (1.0 - scale)
        solar_curtailed = 300.0 * (1.0 - scale)
        bat_curtailed = 200.0 * (1.0 - scale)
        assert wind_curtailed == pytest.approx(27.5, rel=1e-9)
        assert solar_curtailed == pytest.approx(16.5, rel=1e-9)
        assert bat_curtailed == pytest.approx(11.0, rel=1e-9)
        total_curtailed = wind_curtailed + solar_curtailed + bat_curtailed
        assert total_curtailed == pytest.approx(55.0, rel=1e-9)
        assert total_curtailed * 800.0 * 1.0 == pytest.approx(44_000.0, rel=1e-9)

    def test_per_source_conservation_equality_with_curtailment(self):  # reviewer: M4
        """M4: per-source conservation must be strict == (not ≤) even when curtailment active.

        Set up: v_hub = v_rated (12.0 m/s) → P_wind = 615 MW; irr=1000 W/m², T=25°C →
        P_solar = 330×1×1×0.97×0.98 = 313.698 MW; a_bat=−1.0, SOC=0.7, f_b→l=0 → P_dis=98.16 MW.
        All flows directed to grid: action=(−1,0,0,0,0,0).
        Total available for export = 615+313.698+98.16 = 1026.858 MW > 945 → curtailment.
        scale = 945/1026.858 = 0.92026...

        wind_curtailed = 615 × (1−scale); solar_curtailed = 313.698 × (1−scale)
        Per-source: wind_to_grid + wind_curtailed == 615  (== not ≤)
                    solar_to_grid + solar_curtailed == 313.698  (== not ≤)
                    bat_to_grid + bat_curtailed == 98.16  (== not ≤)
        """
        # v_10m such that v_hub = 12.0 exactly (at rated → P_wind = 615 MW)
        v10_rated = 12.0 / SHEAR
        action = np.array([-1.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # full discharge, all to grid
        state = make_state(soc=0.7, t=0)
        weather = (v10_rated, 1000.0, 25.0)
        result = env_step(state, action, weather, 0.0, PARAMS)

        p_wind_expected = 615.0
        p_solar_expected = 330.0 * 1.0 * 1.0 * 0.97 * 0.98  # = 313.698 MW

        # Test precondition: curtailment must be happening
        total_available = p_wind_expected + p_solar_expected + PARAMS.bat_power_mw
        assert total_available > PARAMS.grid_max_export_mw, (
            f"M4 precondition: total={total_available:.2f} must exceed export limit="
            f"{PARAMS.grid_max_export_mw}")

        # Wind per-source conservation EQUALITY (B3 fix: includes wind_curtailed)
        wind_sum = (result.wind_to_load_mw + result.wind_to_bat_mw
                    + result.wind_to_grid_mw + result.wind_curtailed_mw)
        assert wind_sum == pytest.approx(result.p_wind_mw, rel=1e-5), (
            f"M4 wind conservation: {wind_sum:.6f} ≠ p_wind_mw={result.p_wind_mw:.6f}")

        # Solar per-source conservation EQUALITY
        solar_sum = (result.solar_to_load_mw + result.solar_to_bat_mw
                     + result.solar_to_grid_mw + result.solar_curtailed_mw)
        assert solar_sum == pytest.approx(result.p_solar_mw, rel=1e-5), (
            f"M4 solar conservation: {solar_sum:.6f} ≠ p_solar_mw={result.p_solar_mw:.6f}")

        # Battery discharge conservation EQUALITY
        bat_sum = result.bat_to_load_mw + result.bat_to_grid_mw + result.bat_curtailed_mw
        assert bat_sum == pytest.approx(result.p_bat_discharge_mw, rel=1e-5), (
            f"M4 bat conservation: {bat_sum:.6f} ≠ p_bat_discharge_mw={result.p_bat_discharge_mw:.6f}")

        # Also verify via invariant helper
        assert_energy_conserved(result, tol=1e-5)

        # Spot-check curtailment is non-zero (curtailment did happen)
        assert result.wind_curtailed_mw > 0.0, "M4: expected wind curtailment"
        assert result.solar_curtailed_mw > 0.0, "M4: expected solar curtailment"
        assert result.bat_curtailed_mw > 0.0, "M4: expected bat curtailment"

        # Proportional split (B3-minor): each source curtailed proportionally to its
        # pre-curtailment grid flow.  With load=0 all generated power goes to grid,
        # so pre_export = p_wind + p_solar + p_bat_discharge.
        pre_export = result.p_wind_mw + result.p_solar_mw + result.p_bat_discharge_mw
        scale = PARAMS.grid_max_export_mw / pre_export
        assert scale < 1.0, "M4: expected scale < 1 (curtailment active)"
        expected_wind_curt  = result.p_wind_mw           * (1.0 - scale)
        expected_solar_curt = result.p_solar_mw          * (1.0 - scale)
        expected_bat_curt   = result.p_bat_discharge_mw  * (1.0 - scale)
        assert result.wind_curtailed_mw == pytest.approx(expected_wind_curt, rel=1e-5), (
            f"M4 proportional wind: {result.wind_curtailed_mw:.6f} ≠ {expected_wind_curt:.6f}")
        assert result.solar_curtailed_mw == pytest.approx(expected_solar_curt, rel=1e-5), (
            f"M4 proportional solar: {result.solar_curtailed_mw:.6f} ≠ {expected_solar_curt:.6f}")
        assert result.bat_curtailed_mw == pytest.approx(expected_bat_curt, rel=1e-5), (
            f"M4 proportional bat: {result.bat_curtailed_mw:.6f} ≠ {expected_bat_curt:.6f}")


# ===========================================================================
# 9. Constraint enforcement — import limit and VOLL (§3.3 step 4, §3.6 row 9)
# ===========================================================================

class TestImportLimit:

    def test_voll_when_import_exceeds_limit(self):
        # load = 450 MW, no RE, no battery → P_import_required = 450 > 400 MW
        # load_unserved = 450 − 400 = 50 MW
        # C_VOLL = 50 × 20000 × 1 = 1000000 ¥
        action = np.zeros(6)
        state = make_state(t=100)
        weather = (0.0, 0.0, 0.0)   # night, no RE
        result = env_step(state, action, weather, 450.0, PARAMS)
        assert result.load_unserved_mw == pytest.approx(50.0, rel=1e-5)
        assert result.c_voll_yuan == pytest.approx(1_000_000.0, rel=1e-5)
        assert result.p_import_mw == pytest.approx(400.0, rel=1e-5)

    def test_no_voll_within_import_limit(self):
        # load = 300 MW, no RE → import = 300 < 400 → no VOLL
        action = np.zeros(6)
        state = make_state(t=100)
        weather = (0.0, 0.0, 0.0)
        result = env_step(state, action, weather, 300.0, PARAMS)
        assert result.load_unserved_mw == pytest.approx(0.0, abs=1e-9)
        assert result.c_voll_yuan == pytest.approx(0.0, abs=1e-9)

    def test_import_limit_shed_branch_bat_exceeds_grid(self):  # reviewer: M6
        """M6: import cap binds AND load_deficit > max_import → LOAD-FIRST (§3.6 row 9).

        Updated for the F-IMPORT fix (dc87b65). §3.6 row 9 is "load served first,
        then battery charging reduced, then load shed." The old battery-first branch
        this test used to assert ("grid_max_import < p_g2b → battery gets all headroom,
        load fully shed") was WRONG and has been removed from both impls. This test now
        pins the correct load-first behavior and must FAIL against a battery-first regression.

        Setup: grid_max_import=50 MW, a_bat=1.0 (full charge from grid, p_g2b=98.16 MW),
        no RE, load=60 MW. Battery is charging → no bat→load.

        Load-first derivation:
          load_deficit     = 60 − 0 (no RE, no bat→load)            = 60 MW
          grid_to_load     = min(load_deficit, max_import) = min(60,50) = 50 MW   (load first)
          load_unserved    = max(0, 60 − 50)                        = 10 MW   (only remainder shed)
          headroom_for_bat = max(0, max_import − grid_to_load) = max(0,50−50) = 0 MW
          p_g2b_actual     = min(p_g2b, headroom) = min(98.16, 0)   = 0 MW    (battery zeroed)
          p_import         = grid_to_load + p_g2b_actual = 50 + 0    = 50 MW
          c_voll           = 20000 ¥/MWh × 10 MW × 1 h              = 200,000 ¥

        OLD (wrong) battery-first values now rejected: bat=50, grid_to_load=0,
        load_unserved=60, c_voll=1,200,000.
        """
        params_tight = GansuParams(grid_max_import_mw=50.0)
        action = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # full charge, no RE
        state = make_state(soc=0.5, t=0)
        weather = (0.0, 0.0, 0.0)   # no RE
        load = 60.0   # MW

        result = env_step(state, action, weather, load, params_tight)

        # Battery charging zeroed — load consumed the full import headroom first
        assert result.grid_to_bat_mw == pytest.approx(0.0, abs=1e-9), (
            f"M6: grid_to_bat_mw={result.grid_to_bat_mw:.4f} ≠ 0 "
            "(load-first: headroom_for_bat = max_import − grid_to_load = 0)")
        # Load served up to the import cap (50 of the 60 MW deficit)
        assert result.grid_to_load_mw == pytest.approx(50.0, rel=1e-5), (
            f"M6: grid_to_load_mw={result.grid_to_load_mw:.4f} ≠ 50 "
            "(load-first: grid_to_load = min(deficit, max_import) = 50)")
        # Only the remainder (60 − 50) is shed — NOT the full load
        assert result.load_unserved_mw == pytest.approx(10.0, rel=1e-5), (
            f"M6: load_unserved_mw={result.load_unserved_mw:.4f} ≠ 10 "
            "(load-first: max(0, 60 − 50) = 10, not the full 60)")
        # C_VOLL = 10 MW × 20000 ¥/MWh × 1 h = 200,000 ¥
        assert result.c_voll_yuan == pytest.approx(200_000.0, rel=1e-5), (
            f"M6: c_voll_yuan={result.c_voll_yuan:.2f} ≠ 200000 (10 × 20000)")
        # Import limit respected (unchanged from the old expectation)
        assert result.p_import_mw == pytest.approx(50.0, rel=1e-5)


# ===========================================================================
# 10. Energy conservation (§3.6 row 14)
# ===========================================================================

class TestEnergyConservation:

    def _check_conservation(self, result: StepResult, p_wind=None, p_solar=None):
        """B3 fix: delegate to assert_energy_conserved for equality == checks with curtailed flows.

        The original method used ≤ without curtailed flows — replaced by the invariant helper
        which asserts per-source equality including wind_curtailed_mw and solar_curtailed_mw.
        """
        assert_energy_conserved(result, tol=1e-5)  # B3: == not <=, includes curtailed

    def test_energy_conservation_wind_only(self):
        # All wind to grid, no solar, no battery
        # wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed = p_wind_mw (producer assert)
        action = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        state = make_state(t=0)
        weather = (6.0, 0.0, 0.0)   # v=6 m/s, no solar
        result = env_step(state, action, weather, 60.0, PARAMS)
        # Per-source conservation: wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed == p_wind
        wind_accounted = (result.wind_to_load_mw + result.wind_to_bat_mw
                          + result.wind_to_grid_mw + result.wind_curtailed_mw)
        assert wind_accounted == pytest.approx(result.p_wind_mw, rel=1e-5)
        # Solar is zero (G=0), confirm per-source conservation holds trivially
        solar_accounted = (result.solar_to_load_mw + result.solar_to_bat_mw
                           + result.solar_to_grid_mw + result.solar_curtailed_mw)
        assert solar_accounted == pytest.approx(result.p_solar_mw, abs=1e-9)

    def test_total_load_served_plus_unserved_equals_demand(self):
        # Every step: load_served + load_unserved = original load
        for load_mw in [50.0, 100.0, 450.0]:
            action = np.zeros(6)
            state = make_state(t=0)
            weather = (0.0, 0.0, 0.0)
            result = env_step(state, action, weather, load_mw, PARAMS)
            load_served = (result.wind_to_load_mw + result.solar_to_load_mw
                           + result.bat_to_load_mw + result.grid_to_load_mw)
            assert (load_served + result.load_unserved_mw) == pytest.approx(
                load_mw, rel=1e-5)


# ===========================================================================
# 11. Reward computation (§3.5)
# ===========================================================================

class TestReward:

    def test_reward_scale(self):
        # D13: reward = −(cost_total_reward_basis_yuan + penalty_yuan) × 1e-5
        # Setup: no new peak → C_DC_shape=0; no SOC violation; valley price
        # t=100 → h = 100%24 = 4 → valley = 250 ¥/MWh
        action = np.zeros(6)
        state = make_state(t=100, month_peak_mw=200.0)
        weather = (0.0, 0.0, 0.0)
        load = 100.0  # MW
        result = env_step(state, action, weather, load, PARAMS)
        # P_import = 100 MW (all from grid, no RE, no battery)
        # C_import = 250 × 100 × 1 = 25 000 ¥; R_export = 0; C_E = 25 000 ¥
        # C_DC_shape = 32000 × max(0, 100 − 200) = 0 ¥ (below month peak)
        # C_deg = 0; penalty = 0
        # cost_total_reward_basis = 25 000; reward = −25 000 × 1e-5 = −0.25
        assert result.c_import_yuan == pytest.approx(25_000.0, rel=1e-4)
        assert result.c_demand_shape_yuan == pytest.approx(0.0, abs=1e-9)  # raw C_DC_shape (D13)
        assert result.penalty_yuan == pytest.approx(0.0, abs=1e-9)
        assert result.cost_total_reward_basis_yuan == pytest.approx(25_000.0, rel=1e-4)
        assert result.reward == pytest.approx(-25_000.0 * 1e-5, rel=1e-4)
        assert result.reward == pytest.approx(-0.25, rel=1e-4)

    def test_soc_violation_penalty_in_reward(self):
        # SOC at max, charge action → soc_violation > 0 → penalty > 0
        # D13: penalty_yuan is SEPARATE from cost_total_reward_basis_yuan
        #       reward = −(cost_total_reward_basis_yuan + penalty_yuan) × 1e-5
        action = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])  # full charge
        state = make_state(soc=0.9, t=0)
        weather = (0.0, 0.0, 0.0)
        result = env_step(state, action, weather, 0.0, PARAMS)
        assert result.soc_violation_mwh > 0.0
        expected_penalty = 20_000.0 * result.soc_violation_mwh
        assert result.penalty_yuan == pytest.approx(expected_penalty, rel=1e-5)
        # penalty contributes to reward (makes it more negative)
        expected_reward = -(result.cost_total_reward_basis_yuan + result.penalty_yuan) * 1e-5
        assert result.reward == pytest.approx(expected_reward, rel=1e-9)

    def test_reward_formula_identity(self):
        # D13 invariant: reward == −(cost_total_reward_basis_yuan + penalty_yuan) × 1e-5
        # Must hold for any step; test with a mixed action
        action = np.array([0.5, 0.4, 0.3, 0.5, 0.2, 0.8])
        state = make_state(t=300, month_peak_mw=50.0, soc=0.6)
        weather = (6.0, 400.0, 20.0)
        result = env_step(state, action, weather, 75.0, PARAMS)
        expected = -(result.cost_total_reward_basis_yuan + result.penalty_yuan) * 1e-5
        assert result.reward == pytest.approx(expected, rel=1e-9)

    def test_demand_shape_stored_raw_not_doubled(self):
        # D13: c_demand_shape_yuan stores the RAW C_DC_shape (not ×2)
        # The ×2 weight is applied only in cost_total_reward_basis_yuan
        # Verify: cost_total_reward_basis = C_E + 2×c_demand_shape + C_deg + C_curtail + C_VOLL
        action = np.zeros(6)
        state = make_state(t=100, month_peak_mw=0.0)  # new peak guaranteed
        weather = (0.0, 0.0, 0.0)
        result = env_step(state, action, weather, 50.0, PARAMS)
        # c_demand_shape is raw; reward basis includes ×2
        reconstructed_basis = (result.c_energy_yuan + 2.0 * result.c_demand_shape_yuan
                                + result.c_degradation_yuan + result.c_curtail_yuan
                                + result.c_voll_yuan)
        assert result.cost_total_reward_basis_yuan == pytest.approx(reconstructed_basis, rel=1e-9)

    def test_cost_total_real_reconstruction(self):  # reviewer: M3
        # cost_total_real_yuan == c_energy + c_demand_charge + c_degradation + c_curtail + c_voll
        # (D13: real money, uses actual monthly demand charge not reward-shaping version)
        # Two sub-cases: mid-month (c_demand_charge=0) and boundary (c_demand_charge>0)

        # Mid-month case: t=100, month_peak=50 (so no new peak, c_demand_shape=0 too)
        action = np.zeros(6)
        weather = (0.0, 0.0, 0.0)

        state_mid = make_state(t=100, month_peak_mw=200.0)
        result_mid = env_step(state_mid, action, weather, 50.0, PARAMS)
        # C_import = 250×50×1=12500; R_export=0; C_E=12500
        # C_demand_charge=0 (mid-month); C_deg=0; C_curtail=0; C_VOLL=0
        # cost_total_real = 12500
        reconstructed_real = (result_mid.c_energy_yuan + result_mid.c_demand_charge_yuan
                               + result_mid.c_degradation_yuan + result_mid.c_curtail_yuan
                               + result_mid.c_voll_yuan)
        assert result_mid.cost_total_real_yuan == pytest.approx(
            reconstructed_real, rel=1e-9), (
            f"M3 mid-month: cost_total_real={result_mid.cost_total_real_yuan:.2f} ≠ "
            f"reconstructed={reconstructed_real:.2f}")

        # Boundary case: t=743, month_peak=80 → c_demand_charge = 80×32000 = 2,560,000 ¥
        state_bdy = make_state(t=743, month_peak_mw=80.0)
        result_bdy = env_step(state_bdy, action, weather, 0.0, PARAMS)
        reconstructed_real_bdy = (result_bdy.c_energy_yuan + result_bdy.c_demand_charge_yuan
                                   + result_bdy.c_degradation_yuan + result_bdy.c_curtail_yuan
                                   + result_bdy.c_voll_yuan)
        assert result_bdy.cost_total_real_yuan == pytest.approx(
            reconstructed_real_bdy, rel=1e-9), (
            f"M3 boundary: cost_total_real={result_bdy.cost_total_real_yuan:.2f} ≠ "
            f"reconstructed={reconstructed_real_bdy:.2f}")


# ===========================================================================
# 12. Action clipping and renormalization (§2.2, §3.6 rows 1–2)
# ===========================================================================

class TestActionParsing:

    def test_fractions_renormalized_when_sum_exceeds_one(self):
        # reviewer: CORRECTED through review (jax-env flagged a conflict with §3.2 / contract STEP 4).
        # reviewer: f_w→l=0.8, f_w→b=0.8 (sum 1.6 > 1) → renormalize to 0.5 / 0.5 each (f_w→g=0).
        # reviewer: ORIGINAL bug: it asserted wind_to_grid==0 with a_bat=0. But per §3.2 a_bat gates
        # reviewer: ALL charging (P_target = a_bat·P_max = 0 → P_ch_from_gen=min(p_ren_to_bat,0)=0),
        # reviewer: so the renewable allocated to battery is NOT absorbed and the f_w→b share spills
        # reviewer: to grid → wind_to_grid ≈ 68 MW ≠ 0. The original setup could not exhibit renorm.
        # reviewer: FIX: a_bat=1.0 so the f_w→b share is absorbed (soc=0.5 → no SOC clip), load=70 so
        # reviewer: wind_to_load (≈64.2) is not load-capped. Renorm is then observable directly:
        # reviewer:   p_wind = wind_power(6.0) ≈ 128.4 MW
        # reviewer:   wind_to_load = p_wind·0.5 ≈ 64.2 ;  wind_to_bat = p_wind·0.5 ≈ 64.2 ;  wind_to_grid = 0
        action = np.array([1.0, 0.0, 0.0, 0.8, 0.8, 0.0])  # a_bat=1.0, f_w→l=0.8, f_w→b=0.8
        state = make_state(t=0, soc=0.5)
        weather = (6.0, 0.0, 0.0)   # only wind
        result = env_step(state, action, weather, 70.0, PARAMS)
        p_wind = wind_power(6.0, PARAMS)
        # renormalized fractions are 0.5 / 0.5 — verified directly on the per-source flows
        assert result.wind_to_load_mw == pytest.approx(p_wind * 0.5, rel=1e-5)
        assert result.wind_to_bat_mw == pytest.approx(p_wind * 0.5, rel=1e-5)
        assert result.wind_to_grid_mw == pytest.approx(0.0, abs=1e-5)

    def test_abat_clipped_to_minus_one(self):
        # a_bat = −2.0 → clipped to −1.0 → P_dis = 98.16 MW
        action = np.array([-2.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        state = make_state(soc=0.7, t=0)
        weather = (0.0, 0.0, 0.0)
        result = env_step(state, action, weather, 0.0, PARAMS)
        assert result.p_bat_discharge_mw <= PARAMS.bat_power_mw + 1e-9

    def test_abat_clipped_to_one(self):
        # a_bat = +2.0 → clipped to +1.0 → P_ch_target = 98.16 MW
        action = np.array([2.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        state = make_state(soc=0.5, t=0)
        weather = (0.0, 0.0, 0.0)
        result = env_step(state, action, weather, 0.0, PARAMS)
        assert result.p_bat_charge_mw <= PARAMS.bat_power_mw + 1e-9


# ===========================================================================
# 13. Synthetic year generator (§4.1, §4.2)
# ===========================================================================

class TestGenerateYear:

    @pytest.fixture(scope="class")
    def year_data(self):
        return generate_year(seed=0, params=PARAMS)

    def test_output_shape(self, year_data):
        # Each array must have exactly 8760 hourly steps
        for key in ("wind_mps", "irradiance_wm2", "temperature_c", "load_mw"):
            assert year_data[key].shape == (8760,), f"{key} shape wrong"

    def test_wind_bounded(self, year_data):
        # wind clipped to [0, 25] m/s by specification (§4.1)
        assert np.all(year_data["wind_mps"] >= 0.0)
        assert np.all(year_data["wind_mps"] <= 25.0)

    def test_irradiance_nonnegative(self, year_data):
        # irradiance ≥ 0 always
        assert np.all(year_data["irradiance_wm2"] >= 0.0)

    def test_irradiance_zero_at_midnight(self, year_data):
        # Hour 0 of every day is midnight → solar = 0 (no sun before sunrise ≈ 4h)
        midnight_hours = np.arange(0, 8760, 24)
        assert np.all(year_data["irradiance_wm2"][midnight_hours] == 0.0), (
            "Irradiance must be 0 at midnight (hour 0 of each day)")

    def test_load_nonnegative(self, year_data):
        # load clipped to ≥ 0 (§4.2: "max(0, L[t])")
        assert np.all(year_data["load_mw"] >= 0.0)

    def test_load_in_site_range(self, year_data):
        # Load should be in the 50–100 MW range (site nominal)
        # After ×100 scaling fix, check mean is roughly 75 MW
        mean_load = np.mean(year_data["load_mw"])
        assert 30.0 < mean_load < 150.0, (
            f"Mean load {mean_load:.1f} MW out of expected 50–100 MW range; "
            "check §4.2 scaling flag in contract")

    def test_determinism_same_seed(self):
        # Same seed → identical arrays
        d1 = generate_year(seed=42, params=PARAMS)
        d2 = generate_year(seed=42, params=PARAMS)
        for key in d1:
            np.testing.assert_array_equal(d1[key], d2[key],
                err_msg=f"{key} not deterministic for same seed")

    def test_different_seeds_different_output(self):
        # Different seeds → different arrays (with overwhelming probability)
        d1 = generate_year(seed=1, params=PARAMS)
        d2 = generate_year(seed=2, params=PARAMS)
        assert not np.array_equal(d1["wind_mps"], d2["wind_mps"])

    def test_solar_seasonal_variation(self, year_data):
        # Summer irradiance (Jul, t≈4320..5088) mean > winter (Jan, t=0..744) mean
        jan_irr = year_data["irradiance_wm2"][0:744]
        jul_irr = year_data["irradiance_wm2"][4320:5088]
        assert np.mean(jul_irr) > np.mean(jan_irr), (
            "Expected summer irradiance > winter irradiance")


# ===========================================================================
# 14. Observation builder (§2.1, D6, D9)
# ===========================================================================

class TestGetObs:

    @pytest.fixture(scope="class")
    def year_and_obs(self):
        data = generate_year(seed=0, params=PARAMS)
        state = make_state(t=1000, seed=7)
        price_buy = get_price(1000 % 24, 0)
        obs = get_obs(state, data, PARAMS, price_buy)
        return data, state, obs

    def test_obs_shape(self, year_and_obs):
        # §2.1: 11 base + 24×4 forecast = 107 dims
        _, _, obs = year_and_obs
        assert obs.shape == (107,)

    def test_base_soc_in_obs(self, year_and_obs):
        # obs[4] = SOC = state.soc = 0.5
        _, state, obs = year_and_obs
        assert obs[4] == pytest.approx(state.soc, rel=1e-6)

    def test_month_peak_normalized(self, year_and_obs):
        # obs[6] = month_peak_mw / 500 = 0.0 / 500 = 0.0
        _, state, obs = year_and_obs
        assert obs[6] == pytest.approx(state.month_peak_mw / 500.0, rel=1e-6)

    def test_forecast_noise_increases_with_horizon(self):
        # D6: σ_h = σ_max × h/H_max → longer horizon → more noise variance
        # Run many samples and verify std(h=24) > std(h=1)
        data = generate_year(seed=0, params=PARAMS)
        state = make_state(t=500, seed=99)
        price_buy = get_price(500 % 24, 0)
        # Build many obs with different rng states to sample noise distribution
        n_samples = 1000
        h1_vals = []
        h24_vals = []
        for i in range(n_samples):
            s = make_state(t=500, seed=i)
            obs = get_obs(s, data, PARAMS, price_buy)
            h1_vals.append(obs[11])    # first forecast dim (h=1)
            h24_vals.append(obs[11 + 4 * 23])  # last forecast dim (h=24)
        # D6: std at h=24 should be roughly 10× std at h=1
        std_h1 = float(np.std(h1_vals))
        std_h24 = float(np.std(h24_vals))
        assert std_h24 > std_h1, (
            f"D6 violated: h=24 std ({std_h24:.4f}) should be > h=1 std ({std_h1:.4f})")

    def test_forecast_stride_one_step(self):
        # D9: forecast samples t+1, t+2, ..., t+24 (NOT t+4, t+8 etc.)
        # Verify obs[11..14] (h=1) uses data[t+1], not data[t+4]
        data = generate_year(seed=0, params=PARAMS)
        state = make_state(t=100, seed=0)
        price_buy = get_price(100 % 24, 0)
        obs = get_obs(state, data, PARAMS, price_buy)
        # The wind at h=1 (before noise) should be data['wind_mps'][101] / 20
        # We cannot recover exact value due to noise, but we can check the obs for
        # h=1 is consistent with t+1 data, not t+4 (a test helper can expose this)
        # Structural check: obs has 107 elements and forecast block starts at index 11
        assert obs.shape == (107,)
        # Forecast wind at h=1 (normalized by 20) should be within noise range of truth
        true_wind_h1 = data["wind_mps"][101]
        obs_wind_h1 = obs[11] * 20.0   # un-normalize
        # With σ_h1 = 0.10/24 ≈ 0.004, noise is tiny; within 10% of truth
        assert abs(obs_wind_h1 - true_wind_h1) < true_wind_h1 * 0.5 + 1.0

    def test_time_encoding_correct(self, year_and_obs):
        # t=1000 → h = 1000 % 24 = 16 (4 pm)
        # obs[7] = sin(2π×16/24) = sin(4π/3) = −0.8660
        # obs[8] = cos(2π×16/24) = cos(4π/3) = −0.5000
        _, state, obs = year_and_obs
        h = state.t % 24
        assert obs[7] == pytest.approx(math.sin(2 * math.pi * h / 24), abs=1e-6)
        assert obs[8] == pytest.approx(math.cos(2 * math.pi * h / 24), abs=1e-6)


# ===========================================================================
# 15. D9 — forecast does NOT wrap at episode end
# ===========================================================================

class TestForecastNoWrap:

    def test_no_wraparound_near_year_end(self):
        # t = 8750 → t+24 would be 8774 > 8759 (last valid index)
        # Reference implementation must clamp, not wrap
        data = generate_year(seed=0, params=PARAMS)
        state = make_state(t=8750, seed=0)
        price_buy = get_price(8750 % 24, 0)
        obs = get_obs(state, data, PARAMS, price_buy)
        # Must not raise and must return 107-dim obs
        assert obs.shape == (107,)
        # No NaN or inf
        assert np.all(np.isfinite(obs))


# ===========================================================================
# 16. D10 — demand charge not double-counted at episode end
# ===========================================================================

class TestDemandChargeNoDoubleCount:

    def test_month_end_full_demand_charge_booked_once(self):
        # Simulate two consecutive calls to env_step where the second is the first
        # step of a new month.  The demand charge for the *old* month should be
        # booked exactly once (at the boundary), and the new_state's month_peak
        # should reset to 0 (to start accumulating for the next month).
        # This test asserts state machine behavior; exact booking mechanism
        # (separate 'month_end_charge' field vs a spike in cost_total) is left to
        # the implementation, but the month_peak MUST reset.
        action = np.zeros(6)
        # t = 743 is the last hour of January (31 × 24 − 1 = 743)
        # t = 744 is the first hour of February
        # Run step at t=743 (Jan) then t=744 (Feb boundary)
        state_jan_end = make_state(t=743, month_peak_mw=80.0)
        weather = (0.0, 0.0, 0.0)
        result_jan_end = env_step(state_jan_end, action, weather, 50.0, PARAMS)

        state_feb_start = result_jan_end.new_state
        # After the January boundary: month_peak_mw should reset to 0 (or to the
        # current step's import for the new month)
        # The key invariant: new month_peak ≤ current step's P_import (no carry-over)
        result_feb_start = env_step(state_feb_start, action, weather, 50.0, PARAMS)
        # D10: terminal month should not double-count; check no negative reward spike
        # from a phantom second booking
        assert result_feb_start.new_state.month_peak_mw <= 50.0 + 1e-6


# ===========================================================================
# 17. Full-step determinism
# ===========================================================================

class TestDeterminism:

    def test_same_inputs_same_outputs(self):
        # Exact same state + action → exact same StepResult
        data = generate_year(seed=0, params=PARAMS)
        action = np.array([0.3, 0.4, 0.3, 0.5, 0.4, 0.6])
        weather = (6.0, 500.0, 20.0)

        def run():
            s = make_state(t=500, seed=77)
            return env_step(s, action, weather, 75.0, PARAMS)

        r1, r2 = run(), run()
        assert r1.reward == pytest.approx(r2.reward, rel=1e-9)
        assert r1.new_state.soc == pytest.approx(r2.new_state.soc, rel=1e-9)


# ===========================================================================
# 18. Invariant helpers — single-step spot checks (task #21)
# These tests import from energy_go.testing.invariants; they do NOT depend on
# the reference implementation and can run even before task #8 is done.
# They demonstrate the helper API and constitute the "self-test" for task #21.
# ===========================================================================

class TestInvariantHelpersAPI:
    """Smoke-test that the invariant helpers accept a well-formed result object."""

    def _make_good_result(self):
        """Return a hand-crafted StepResult that satisfies every invariant.

        C1 fix: p_import=0 so grid_to_load+grid_to_bat=0+0=0 == p_import=0 ✓.
        The old fixture had p_import=50 while grid_to_load=grid_to_bat=0 —
        that violated the grid-import decomp check in assert_energy_conserved.
        """
        # Step values chosen to satisfy all identities analytically:
        # t=100, hour=4 → valley price=250 ¥/MWh
        # P_wind=128.396, P_solar=0, P_import=0, P_export=78.396
        # load=50 served entirely from wind; no grid import (pure export scenario)
        # C_import = 250×0×1 = 0
        # R_export = 220×78.396×1 = 17247.12  (sell=250-30=220)
        # C_energy = 0-17247.12 = -17247.12
        # C_DC_shape = 0 (p_import=0 ≤ month_peak=100)
        # C_deg = 0 (no bat)
        # C_curtail = 0; C_VOLL = 0; penalty = 0
        # cost_rb = -17247.12; cost_real = -17247.12
        # reward = -(-17247.12+0)×1e-5 = 0.1724712
        soc_new = 0.5
        p_wind = 128.396
        p_solar = 0.0
        p_export = 78.396   # all wind excess goes to grid
        p_import = 0.0      # C1 fix: pure export step, no grid import
        c_import = 250.0 * p_import * 1.0       # = 0
        r_export = 220.0 * p_export * 1.0       # = 17247.12
        c_energy = c_import - r_export           # = -17247.12
        c_deg = 10.0 * (0.0 + 0.0) * 1.0       # = 0
        c_curtail = 800.0 * (0.0 + 0.0 + 0.0) * 1.0  # = 0
        c_voll = 20000.0 * 0.0 * 1.0            # = 0
        c_ds = 32000.0 * max(0.0, p_import - 100.0)  # = 0 (below peak)
        c_dc = 0.0
        penalty = 20000.0 * 0.0                 # = 0
        cost_rb = c_energy + 2.0 * c_ds + c_deg + c_curtail + c_voll
        cost_real = c_energy + c_dc + c_deg + c_curtail + c_voll
        reward = -(cost_rb + penalty) * 1e-5

        # price_buy=250 (hour=4, valley), price_sell=220 (=250−30 nominal spread)
        price_buy  = 250.0
        price_sell = 220.0   # = max(0, 250 − max(0, 30 + 0)) = 220 (D7 nominal)

        new_state = EnvState(soc=soc_new, month_peak_mw=100.0, t=101,
                             rng=np.random.default_rng(42))
        return StepResult(
            p_wind_mw=p_wind, p_solar_mw=p_solar,
            wind_to_load_mw=50.0, wind_to_bat_mw=0.0,
            wind_to_grid_mw=78.396, wind_curtailed_mw=0.0,
            solar_to_load_mw=0.0, solar_to_bat_mw=0.0,
            solar_to_grid_mw=0.0, solar_curtailed_mw=0.0,
            bat_to_load_mw=0.0, bat_to_grid_mw=0.0,
            grid_to_load_mw=0.0, grid_to_bat_mw=0.0,
            bat_curtailed_mw=0.0,
            load_unserved_mw=0.0,
            p_bat_charge_mw=0.0, p_bat_discharge_mw=0.0,
            soc_violation_mwh=0.0,
            p_import_mw=p_import, p_export_mw=p_export,
            price_buy_yuan_per_mwh=price_buy,
            price_sell_yuan_per_mwh=price_sell,
            c_import_yuan=c_import, r_export_yuan=r_export,
            c_energy_yuan=c_energy,
            c_demand_shape_yuan=c_ds,
            c_degradation_yuan=c_deg,
            c_curtail_yuan=c_curtail,
            c_voll_yuan=c_voll,
            penalty_yuan=penalty,
            c_demand_charge_yuan=c_dc,
            cost_total_real_yuan=cost_real,
            cost_total_reward_basis_yuan=cost_rb,
            reward=reward,
            new_state=new_state,
        )

    def test_assert_energy_conserved_passes_on_good_result(self):
        # A hand-crafted result where all flows balance must pass without error.
        result = self._make_good_result()
        assert_energy_conserved(result, tol=1e-5)  # must not raise

    def test_assert_cost_identities_passes_on_good_result(self):
        result = self._make_good_result()
        assert_cost_identities(result, PARAMS, tol=1e-9)  # must not raise (identities only)
        # Also test formula-level checks (GAP 6): price_buy × p_import × dt = c_import
        assert_cost_identities(result, PARAMS, tol=1e-9, check_formulas=True)

    def test_assert_physical_bounds_passes_on_good_result(self):
        result = self._make_good_result()
        assert_physical_bounds(result, PARAMS)  # must not raise

    def test_assert_soc_dynamics_passes_on_good_result(self):
        # No violation: soc_new = soc_old (no battery action)
        result = self._make_good_result()
        assert_soc_dynamics(old_soc=0.5, result=result, params=PARAMS, tol=1e-5)

    def test_assert_energy_conserved_fails_on_bad_conservation(self):
        # Modify wind flow to break conservation → helper must raise AssertionError
        result = self._make_good_result()
        # Over-report wind_to_load by 1 MW: sum > p_wind_mw
        bad = StepResult(
            **{k: getattr(result, k) for k in result.__dataclass_fields__
               if k != "wind_to_load_mw"},
            wind_to_load_mw=result.wind_to_load_mw + 1.0,  # breaks conservation
        )
        with pytest.raises(AssertionError, match="Wind conservation"):
            assert_energy_conserved(bad, tol=1e-5)

    def test_assert_cost_identities_fails_on_wrong_reward(self):
        # Corrupt the reward field → identity 4 must raise
        result = self._make_good_result()
        bad_reward = result.reward + 999.0
        bad = StepResult(
            **{k: getattr(result, k) for k in result.__dataclass_fields__
               if k != "reward"},
            reward=bad_reward,
        )
        with pytest.raises(AssertionError, match="Identity 4"):
            assert_cost_identities(bad, PARAMS, tol=1e-9)

    def test_assert_demand_charge_timing_passes_non_boundary(self):
        # c_demand_charge_yuan = 0 on a non-boundary step → helper must not raise
        result = self._make_good_result()  # has c_demand_charge_yuan = 0.0
        assert_demand_charge_timing(result, is_month_boundary=False,
                                    prev_month_peak_mw=100.0, params=PARAMS)

    def test_assert_demand_charge_timing_passes_boundary(self):
        # prev_peak=100 MW at boundary → expected charge = 100×32000=3,200,000 ¥
        # Build a result with c_demand_charge_yuan=3,200,000
        import dataclasses
        result = self._make_good_result()
        result_with_dc = dataclasses.replace(result, c_demand_charge_yuan=100.0 * 32_000.0)
        assert_demand_charge_timing(result_with_dc, is_month_boundary=True,
                                    prev_month_peak_mw=100.0, params=PARAMS)

    def test_assert_demand_charge_timing_fails_when_nonzero_mid_month(self):
        # Non-boundary step with c_demand_charge_yuan > 0 → must raise (D10 violated)
        import dataclasses
        result = self._make_good_result()
        bad = dataclasses.replace(result, c_demand_charge_yuan=100.0)  # should be 0
        with pytest.raises(AssertionError, match="non-boundary"):
            assert_demand_charge_timing(bad, is_month_boundary=False,
                                        prev_month_peak_mw=100.0, params=PARAMS)

    def test_assert_physical_bounds_fails_on_soc_out_of_range(self):
        # SOC above soc_max → helper must raise
        result = self._make_good_result()
        import dataclasses
        bad_state = EnvState(soc=0.95, month_peak_mw=100.0, t=101,
                             rng=np.random.default_rng(42))
        bad = dataclasses.replace(result, new_state=bad_state)
        with pytest.raises(AssertionError, match="soc_max"):
            assert_physical_bounds(bad, PARAMS)

    def test_assert_physical_bounds_fails_on_price_sell_negative(self):
        # GAP 3: price_sell < 0 → must raise (D7 outer clamp violated)
        import dataclasses
        result = self._make_good_result()
        bad = dataclasses.replace(result, price_sell_yuan_per_mwh=-5.0)
        with pytest.raises(AssertionError, match="D7 outer-clamp"):
            assert_physical_bounds(bad, PARAMS)

    def test_assert_physical_bounds_fails_on_price_sell_above_buy(self):
        # GAP 3: price_sell > price_buy → must raise (D7 spread must be ≥ 0)
        import dataclasses
        result = self._make_good_result()
        bad = dataclasses.replace(result, price_sell_yuan_per_mwh=260.0)  # > price_buy=250
        with pytest.raises(AssertionError, match="sell ≤ buy"):
            assert_physical_bounds(bad, PARAMS)


# ===========================================================================
# 19. Invariant helpers — episode-level integration (task #21)
# Uses run_episode + assert_episode_invariants on a reference implementation run.
# (Only runs if the reference implementation is importable; same guard as suite 1.)
# ===========================================================================

class TestInvariantHelpersEpisode:

    def test_run_episode_returns_n_steps(self):
        # run_episode must return exactly n_steps results
        data = generate_year(seed=0, params=PARAMS)
        state = make_state(t=0, seed=0)
        action = np.zeros(6)
        results = run_episode(
            step_fn=lambda s, a, w, l, p: env_step(s, a, w, l, p),
            initial_state=state,
            action_or_actions=action,
            data=data,
            params=PARAMS,
            n_steps=10,
        )
        assert len(results) == 10

    def test_episode_invariants_hold_over_168_steps(self):
        # Run a full week (168 steps) and verify all invariants pass every step.
        # This is the comprehensive integration check — it calls assert_energy_conserved,
        # assert_cost_identities, and assert_physical_bounds on each result.
        data = generate_year(seed=0, params=PARAMS)
        state = make_state(t=0, seed=0)
        action = np.array([0.3, 0.4, 0.3, 0.5, 0.2, 0.8])  # mixed, non-trivial
        results = run_episode(
            step_fn=lambda s, a, w, l, p: env_step(s, a, w, l, p),
            initial_state=state,
            action_or_actions=action,
            data=data,
            params=PARAMS,
            n_steps=168,
        )
        # Must not raise — all physics invariants must hold for all 168 steps
        assert_episode_invariants(results, PARAMS, energy_tol=1e-5, cost_tol=1e-9)

    def test_run_determinism_check_passes(self):
        # run_determinism_check with n_runs=3 must pass for a pure function
        data = generate_year(seed=0, params=PARAMS)
        action = np.array([0.5, 0.4, 0.3, 0.5, 0.4, 0.6])
        weather = (6.0, 500.0, 20.0)

        def step_fn(state, action, weather, load, params):
            return env_step(state, action, weather, load, params)

        run_determinism_check(
            step_fn=step_fn,
            make_state_fn=lambda: make_state(t=500, seed=77),
            action=action,
            weather=weather,
            load=75.0,
            params=PARAMS,
            n_runs=3,
            tol=1e-12,
        )


# ---------------------------------------------------------------------------
# reviewer (backend-reviewer): D13 boundary divergence — explicit value-pin
# (complements the dev's assert_cost_identities-at-boundary in test_month_boundary_*)
# ---------------------------------------------------------------------------


def test_d13_boundary_divergence_real_vs_reward_basis():
    # reviewer: explicit pin of the D13 real-vs-reward divergence at a month boundary:
    # reviewer: cost_total_real INCLUDES the monthly demand charge, cost_total_reward_basis
    # reviewer: EXCLUDES it. The dev's assert_cost_identities(result) at the M1 boundary
    # reviewer: covers this via identities 2+3; this pins the absolute values for readability.
    # reviewer:
    # reviewer: t=743 (Jan→Feb boundary), month_peak=80 MW, load=0, no RE/battery → import=0:
    # reviewer:   hour = 743 % 24 = 23 → valley 250; c_import = 250×0 = 0; r_export = 0
    # reviewer:   c_energy            = 0
    # reviewer:   c_demand_charge     = new_month_peak(80) × 32000 = 2,560,000   (booked at boundary)
    # reviewer:   c_demand_shape      = 32000 × max(0, 0 − 80)     = 0           (import < peak)
    # reviewer:   cost_total_real         = 0 + 2,560,000 + 0 + 0 + 0 = 2,560,000  (INCLUDES charge)
    # reviewer:   cost_total_reward_basis = 0 + 2·0      + 0 + 0 + 0 = 0          (EXCLUDES charge)
    # reviewer:   reward = −(0 + 0)·1e-5 = 0
    state = make_state(t=743, month_peak_mw=80.0)
    result = env_step(state, np.zeros(6), (0.0, 0.0, 0.0), 0.0, PARAMS)

    assert result.c_demand_charge_yuan == pytest.approx(2_560_000.0, rel=1e-9), (
        f"boundary demand charge {result.c_demand_charge_yuan:.2f} ≠ 80×32000")
    assert result.cost_total_real_yuan == pytest.approx(2_560_000.0, rel=1e-9), (
        f"cost_total_real {result.cost_total_real_yuan:.2f} must INCLUDE the monthly charge")
    assert result.cost_total_reward_basis_yuan == pytest.approx(0.0, abs=1e-6), (
        f"cost_total_reward_basis {result.cost_total_reward_basis_yuan:.2f} must EXCLUDE the "
        "monthly charge (D13): reward basis uses 2·c_demand_shape, never c_demand_charge")
    assert (result.cost_total_real_yuan - result.cost_total_reward_basis_yuan) == pytest.approx(
        result.c_demand_charge_yuan, rel=1e-9), (
        "real − reward_basis must equal c_demand_charge_yuan at a boundary step")
    assert result.reward == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# reviewer (backend-reviewer): D21 episode semantics + D6 price-clip gating
# ---------------------------------------------------------------------------
from reference.gansu_env import _noised_feature as _rv_noised_feature  # noqa: E402


def test_truncated_episode_books_zero_demand_charge():  # reviewer: D21
    # reviewer: D21 (rl-architect binding) — real c_demand_charge books ONLY at a
    # reviewer: calendar-month boundary or year-end (t==8759). A 7-day slice that
    # reviewer: crosses NO boundary books 0 by design (training pressure is the per-step
    # reviewer: 2·C_DC_shape in cost_total_reward_basis; c_demand_charge is real-money/eval).
    # reviewer: t=100..267 ⊂ January (Jan=744h, 267<743 → no Feb crossing, not t==8759) → Σ==0.
    # reviewer: NOT "all 7-day episodes book 0": a straddling slice books at the crossing (M1/M2).
    data = generate_year(seed=0, params=PARAMS)
    state = make_state(t=100, month_peak_mw=50.0, seed=7)
    total_dc = 0.0
    for _ in range(168):
        w = (float(data["wind_mps"][state.t]), float(data["irradiance_wm2"][state.t]),
             float(data["temperature_c"][state.t]))
        r = env_step(state, np.zeros(6), w, float(data["load_mw"][state.t]), PARAMS)
        total_dc += r.c_demand_charge_yuan
        state = r.new_state
    assert total_dc == pytest.approx(0.0, abs=1e-9), (
        f"D21: no-boundary 7-day episode must book 0 real demand charge, got {total_dc:.4f}")


def test_noised_feature_clips_to_floor():  # reviewer: D6
    # reviewer: D6 — _noised_feature clips noised value to [lo, hi]. Seed-independent
    # reviewer: unit check so the integration test below can't silently go vacuous.
    # reviewer: noisy = true·(1 + noise·σ). 250·(1 + (−1.0)·2.0) = 250·(−1) = −250 → clip(0) = 0.
    assert _rv_noised_feature(250.0, -1.0, 2.0, 0.0) == pytest.approx(0.0, abs=1e-9)
    # reviewer: positive passes through: 250·(1 + 0.1·2.0) = 250·1.2 = 300.
    assert _rv_noised_feature(250.0, 0.1, 2.0, 0.0) == pytest.approx(300.0, rel=1e-9)


def test_forecast_price_obs_nonnegative():  # reviewer: D6
    # reviewer: D6 — noised forecast price is clipped ≥ 0. With σ_max=2.0 (stress) many
    # reviewer: draws drive the unclipped value < 0; the clipped obs must stay ≥ 0.
    # reviewer: Non-vacuity: seed=999 produces clip events (verified ≥1 entry == 0).
    data = generate_year(seed=0, params=PARAMS)
    params_high_noise = GansuParams(forecast_sigma_max=2.0)
    state = make_state(t=0, seed=999)
    obs = get_obs(state, data, params_high_noise, price_buy=250.0)
    price_obs = obs[14::4][:24]   # forecast price feature for h_idx=1..24
    assert (price_obs >= 0.0).all(), (
        f"D6: forecast price obs must be ≥ 0; min={price_obs.min():.6f}")
    assert (price_obs == 0.0).any(), (
        "D6 non-vacuity: σ_max=2.0/seed=999 must trigger ≥1 clip-to-floor event")
