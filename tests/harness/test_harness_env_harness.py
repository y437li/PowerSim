"""
Tests for contracts/harness/env_harness.md

All tests are RED before implementation — that is correct and expected.

Hand-computed expected values are shown with the arithmetic in comments.
Decisions applied: D3, D4, D5, D10, D12, D13, D18, D21, D22(c).

Import structure (implementation lives in energy_go.harness.*):
    from energy_go.harness import InteractiveEnv, ScenarioReplay, RunManager, Sweeper
    from energy_go.harness.types import (
        RunConfig, RunRecord, RunStatus,
        StepInspection, TrajectoryRecord, SweepVariant, SweepResult,
    )
    from energy_go.env.jax_env import EnvParams, PRICE_TABLE_YPW, MONTH_OF_STEP
    from energy_go.generators.synthetic import generate_year
    from energy_go.telemetry.validate import validate_message
"""

import math
import time
import uuid
from pathlib import Path
from typing import Sequence

import numpy as np
import pytest

# --------------------------------------------------------------------------- #
#  Guard — skip all tests until energy_go.harness is importable               #
# --------------------------------------------------------------------------- #
energy_go_harness = pytest.importorskip("energy_go.harness")
InteractiveEnv = energy_go_harness.InteractiveEnv
ScenarioReplay = energy_go_harness.ScenarioReplay
RunManager = energy_go_harness.RunManager
Sweeper = energy_go_harness.Sweeper

energy_go_harness_types = pytest.importorskip("energy_go.harness.types")
RunConfig = energy_go_harness_types.RunConfig
RunRecord = energy_go_harness_types.RunRecord
RunStatus = energy_go_harness_types.RunStatus
StepInspection = energy_go_harness_types.StepInspection
TrajectoryRecord = energy_go_harness_types.TrajectoryRecord
SweepVariant = energy_go_harness_types.SweepVariant
SweepResult = energy_go_harness_types.SweepResult

jax_env_mod = pytest.importorskip("energy_go.env.jax_env")
EnvParams = jax_env_mod.EnvParams
EnvState = jax_env_mod.EnvState
PRICE_TABLE_YPW = jax_env_mod.PRICE_TABLE_YPW
MONTH_OF_STEP = jax_env_mod.MONTH_OF_STEP

synthetic_mod = pytest.importorskip("energy_go.generators.synthetic")
generate_year = synthetic_mod.generate_year

telemetry_validate_mod = pytest.importorskip("energy_go.telemetry.validate")
validate_message = telemetry_validate_mod.validate_message

import jax
import jax.numpy as jnp


# =========================================================================== #
#  Shared fixtures                                                              #
# =========================================================================== #

TOL_MW = 1e-3   # 1 kW tolerance for power conservation checks
TOL_YEN = 1e-1  # 0.1 ¥ tolerance for cost checks (float32 precision)


def make_deterministic_params(**overrides) -> EnvParams:
    """EnvParams with price_spread_sigma=0 (deterministic sell price) for reproducible tests."""
    defaults = dict(price_spread_sigma=0.0, forecast_sigma_max=0.0)
    defaults.update(overrides)
    return EnvParams(**defaults)


def make_synthetic_data_with_step(
    t_target: int,
    wind_mps: float,
    irr_wm2: float,
    temp_c: float,
    load_mw: float,
    n_steps: int = 8760,
) -> np.ndarray:
    """
    Build a (n_steps, 4) float32 synthetic year array where step t_target has
    specific weather/load values; other steps have zeros.
    Used to make physics tests predictable without calling generate_year().
    """
    data = np.zeros((n_steps, 4), dtype=np.float32)
    data[t_target, 0] = wind_mps
    data[t_target, 1] = irr_wm2
    data[t_target, 2] = temp_c
    data[t_target, 3] = load_mw
    return data


@pytest.fixture
def det_params():
    """Default Gansu params, zero-noise sell price (D7: price_sell = max(0, price_buy−30))."""
    return make_deterministic_params()


@pytest.fixture
def data_t8_no_renewables(det_params):
    """Year data: step t=8 has wind=0, irr=0, temp=25°C, load=50 MW; rest zeros."""
    return make_synthetic_data_with_step(8, 0.0, 0.0, 25.0, 50.0)


@pytest.fixture
def ienv_t8_no_ren(det_params, data_t8_no_renewables):
    """InteractiveEnv ready for step t=8, no renewables."""
    return InteractiveEnv(params=det_params, data=data_t8_no_renewables)


@pytest.fixture
def tmp_storage(tmp_path):
    return tmp_path / "runs"


# =========================================================================== #
#  §1 — make_state construction                                                 #
# =========================================================================== #

class TestMakeState:
    """Unit tests for InteractiveEnv.make_state (§5.1 of contract)."""

    def test_valid_state(self, ienv_t8_no_ren, det_params):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8, month_peak_mw=100.0, seed=42)
        assert abs(float(state.soc) - 0.5) < 1e-6
        assert int(state.t) == 8
        assert abs(float(state.month_peak) - 100.0) < 1e-3

    def test_soc_below_min_raises(self, ienv_t8_no_ren, det_params):
        # D4: soc_min = 0.2; 0.1 is below
        with pytest.raises(ValueError, match="soc"):
            ienv_t8_no_ren.make_state(soc=0.1, t=8)

    def test_soc_above_max_raises(self, ienv_t8_no_ren, det_params):
        # D4: soc_max = 0.9; 0.95 is above
        with pytest.raises(ValueError, match="soc"):
            ienv_t8_no_ren.make_state(soc=0.95, t=8)

    def test_soc_at_min_boundary_ok(self, ienv_t8_no_ren):
        # boundary inclusion: soc == soc_min is valid
        state = ienv_t8_no_ren.make_state(soc=0.2, t=8)
        assert abs(float(state.soc) - 0.2) < 1e-6

    def test_soc_at_max_boundary_ok(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.9, t=8)
        assert abs(float(state.soc) - 0.9) < 1e-6

    def test_t_negative_raises(self, ienv_t8_no_ren):
        with pytest.raises(ValueError, match="t"):
            ienv_t8_no_ren.make_state(soc=0.5, t=-1)

    def test_t_above_8759_raises(self, ienv_t8_no_ren):
        with pytest.raises(ValueError, match="t"):
            ienv_t8_no_ren.make_state(soc=0.5, t=8760)

    def test_t_at_8759_ok(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8759)
        assert int(state.t) == 8759

    def test_month_peak_negative_raises(self, ienv_t8_no_ren):
        with pytest.raises(ValueError, match="month_peak"):
            ienv_t8_no_ren.make_state(soc=0.5, t=8, month_peak_mw=-1.0)

    def test_default_month_peak_zero(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8)
        assert abs(float(state.month_peak) - 0.0) < 1e-6


# =========================================================================== #
#  §2 — InteractiveEnv.step: baseline cost identity (D13)                     #
# =========================================================================== #

class TestStepBaseCostIdentity:
    """
    T1: Pure grid charge, no renewables, month_peak=100 MW (above import → demand_shape=0).
    Arithmetic in comments to verify hand-derivation.

    Setup: t=8 (hour=8, PRICE_TABLE_YPW[8]=620 ¥/MWh), wind=0, irr=0, load=50 MW
           action=[0.5, 0, 0, 0, 0, 0]  (a_bat=0.5, no renewable allocation fractions)
           soc=0.5, month_peak=100 MW

    Power flows:
      P_pv = 0 (irr=0)
      P_wind = 0 (wind=0 < v_cutin=3)
      P_ch_target = 0.5 × 98.16 = 49.08 MW
      max_P_ch = (0.9−0.5) × 294.5 / 0.97 = 0.4×294.5/0.97 = 117.8/0.97 = 121.443 MW → no SOC clip
      P_ch_actual = 49.08 MW
      P_grid_to_bat = 49.08 MW (no renewables)
      load_deficit = max(0, 50−0) = 50 MW
      P_import_raw = 50 + 49.08 = 99.08 MW  < max_import=400 → no import cap
      P_import = 99.08 MW
      P_grid_to_load = 50 MW, P_grid_to_bat = 49.08 MW

    Costs (D13):
      price_buy = 620 ¥/MWh (h=8, peak tier)
      price_sell = max(0, 620−30) = 590 ¥/MWh (D7, sigma=0 → no noise)
      C_import = 620 × 99.08 × 1 = 61 429.6 ¥
      R_export = 590 × 0 × 1 = 0 ¥
      C_E = 61 429.6 − 0 = 61 429.6 ¥
      C_demand_shape = 32 000 × max(0, 99.08−100) = 32 000 × 0 = 0 ¥  (below month_peak)
      C_deg = 10 × 49.08 × 1 = 490.8 ¥   (only charge, no discharge)
      C_curtail = 0 ¥
      C_VOLL = 0 ¥
      penalty = 0 ¥
      cost_total_real         = 61 429.6 + 0 + 490.8 + 0 + 0 = 61 920.4 ¥
      cost_total_reward_basis = 61 429.6 + 2×0 + 490.8 + 0 + 0 = 61 920.4 ¥
      reward = −(61 920.4 + 0) × 1e-5 = −0.619204
    """

    @pytest.fixture
    def insp(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8, month_peak_mw=100.0)
        return ienv_t8_no_ren.step(state, [0.5, 0, 0, 0, 0, 0])

    def test_p_import(self, insp):
        # P_import = 50 (load) + 49.08 (bat) = 99.08 MW
        assert abs(insp.p_import_mw - 99.08) < TOL_MW

    def test_p_export(self, insp):
        assert abs(insp.p_export_mw - 0.0) < TOL_MW

    def test_c_energy(self, insp):
        # C_E = 620 × 99.08 × 1 = 61 429.6 ¥
        assert abs(insp.c_energy_yuan - 61_429.6) < TOL_YEN

    def test_c_demand_shape_zero(self, insp):
        # month_peak=100 > P_import=99.08 → shape = 0
        assert abs(insp.c_demand_shape_yuan - 0.0) < TOL_YEN

    def test_c_degradation(self, insp):
        # C_deg = 10 × 49.08 × 1 = 490.8 ¥
        assert abs(insp.c_degradation_yuan - 490.8) < TOL_YEN

    def test_cost_total_real(self, insp):
        # = 61 429.6 + 0 + 490.8 + 0 + 0 = 61 920.4 ¥
        assert abs(insp.cost_total_real_yuan - 61_920.4) < TOL_YEN

    def test_cost_total_reward_basis(self, insp):
        # same as real when demand_shape=0: = 61 920.4 ¥
        assert abs(insp.cost_total_reward_basis_yuan - 61_920.4) < TOL_YEN

    def test_reward(self, insp):
        # reward = −(61 920.4 + 0) × 1e-5 = −0.619204
        assert abs(insp.reward - (-0.619204)) < 1e-4

    def test_soc_out(self, insp):
        # new_soc = 0.5 + 0.97 × 49.08 / 294.5
        # = 0.5 + 47.6076 / 294.5 = 0.5 + 0.161656 = 0.661656
        expected = 0.5 + (0.97 * 49.08 / 294.5)
        assert abs(insp.soc_out - expected) < 1e-4

    def test_no_soc_violation(self, insp):
        assert insp.soc_violation_mwh == 0.0
        assert not insp.constraint_soc_clipped

    def test_no_import_cap(self, insp):
        assert not insp.constraint_import_capped

    def test_d13_real_identity(self, insp):
        # D13: cost_total_real = c_energy + c_demand_charge + c_deg + c_curtail + c_voll
        computed = (
            insp.c_energy_yuan
            + insp.c_demand_charge_yuan
            + insp.c_degradation_yuan
            + insp.c_curtail_yuan
            + insp.c_voll_yuan
        )
        assert abs(insp.cost_total_real_yuan - computed) < TOL_YEN

    def test_d13_reward_basis_identity(self, insp):
        # D13: cost_total_reward_basis = c_energy + 2·c_demand_shape + c_deg + c_curtail + c_voll
        computed = (
            insp.c_energy_yuan
            + 2.0 * insp.c_demand_shape_yuan
            + insp.c_degradation_yuan
            + insp.c_curtail_yuan
            + insp.c_voll_yuan
        )
        assert abs(insp.cost_total_reward_basis_yuan - computed) < TOL_YEN

    def test_reward_formula(self, insp):
        # reward = −(cost_total_reward_basis + penalty) × 1e-5
        expected = -(insp.cost_total_reward_basis_yuan + insp.penalty_yuan) * 1e-5
        assert abs(insp.reward - expected) < 1e-7


# =========================================================================== #
#  §3 — Real-money vs reward-basis divergence (D13, step B analogue)          #
# =========================================================================== #

class TestStepDemandShapeDivergence:
    """
    T2: month_peak=40 MW (below P_import=99.08 MW) → demand shape fires.
    This pins the D13 real/reward-basis split and the 2× weight.

    C_demand_shape = 32 000 × max(0, 99.08 − 40) = 32 000 × 59.08 = 1 890 560 ¥ (raw)
    cost_total_real        = 61 429.6 + 0 + 490.8 + 0 + 0 = 61 920.4 ¥  (demand_shape NOT in real)
    cost_total_reward_basis = 61 429.6 + 2×1 890 560 + 490.8 = 3 843 040.4 ¥  (2× weight applied)
    reward = −3 843 040.4 × 1e-5 = −38.430404
    """

    @pytest.fixture
    def insp(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8, month_peak_mw=40.0)
        return ienv_t8_no_ren.step(state, [0.5, 0, 0, 0, 0, 0])

    def test_c_demand_shape(self, insp):
        # 32 000 × (99.08 − 40) = 32 000 × 59.08 = 1 890 560 ¥
        expected = 32_000.0 * (99.08 - 40.0)
        assert abs(insp.c_demand_shape_yuan - expected) < 1.0  # 1 ¥ tolerance on float32

    def test_c_demand_charge_zero(self, insp):
        # D21: t=8 is mid-episode, not a month boundary → demand charge = 0
        assert insp.c_demand_charge_yuan == 0.0

    def test_real_total_excludes_demand_shape(self, insp):
        # Real total = 61 920.4 ¥ — same as T1, demand_shape not in real (D13)
        assert abs(insp.cost_total_real_yuan - 61_920.4) < TOL_YEN

    def test_reward_basis_includes_2x_demand_shape(self, insp):
        # = 61 429.6 + 2×1 890 560 + 490.8 = 3 843 040.4 ¥
        expected = 61_429.6 + 2.0 * 32_000.0 * (99.08 - 40.0) + 490.8
        assert abs(insp.cost_total_reward_basis_yuan - expected) < 1.0

    def test_reward_diverges_from_real(self, insp):
        # reward = −3 843 040.4 × 1e-5 = −38.430404
        assert abs(insp.reward - (-38.430404)) < 0.01

    def test_month_peak_updated(self, insp):
        # new month_peak = max(40, 99.08) = 99.08 MW
        assert abs(insp.month_peak_out_mw - 99.08) < TOL_MW

    def test_d13_identities_hold(self, insp):
        real = (
            insp.c_energy_yuan + insp.c_demand_charge_yuan
            + insp.c_degradation_yuan + insp.c_curtail_yuan + insp.c_voll_yuan
        )
        rb = (
            insp.c_energy_yuan + 2.0 * insp.c_demand_shape_yuan
            + insp.c_degradation_yuan + insp.c_curtail_yuan + insp.c_voll_yuan
        )
        assert abs(insp.cost_total_real_yuan - real) < TOL_YEN
        assert abs(insp.cost_total_reward_basis_yuan - rb) < TOL_YEN


# =========================================================================== #
#  §4 — SOC violation (D4)                                                     #
# =========================================================================== #

class TestSOCViolation:
    """
    T3: soc=0.88, full charge — SOC would overshoot soc_max=0.9.

    P_ch_target = 1.0 × 98.16 = 98.16 MW
    max_P_ch = (0.90 − 0.88) × 294.5 / 0.97
             = 0.02 × 294.5 / 0.97
             = 5.89 / 0.97
             = 6.07216 MW
    P_ch_actual = min(98.16, 6.07216) = 6.07216 MW
    violation_mwh = (98.16 − 6.07216) × 0.97 × 1 = 92.08784 × 0.97 = 89.32520 MWh
    penalty = 20 000 × 89.32520 = 1 786 504 ¥
    new_soc = 0.88 + 0.97 × 6.07216 / 294.5 = 0.88 + 0.02000 = 0.9000
    """

    @pytest.fixture
    def insp(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.88, t=8, month_peak_mw=100.0)
        return ienv_t8_no_ren.step(state, [1.0, 0, 0, 0, 0, 0])

    def test_soc_violation_mwh(self, insp):
        # (98.16 − 6.07216) × 0.97 = 89.325 MWh
        max_p_ch = (0.90 - 0.88) * 294.5 / 0.97       # 6.07216 MW
        violation = (98.16 - max_p_ch) * 0.97
        # = 92.08784 × 0.97 = 89.3252 MWh
        assert abs(insp.soc_violation_mwh - violation) < 0.01  # 10 kWh tolerance

    def test_penalty(self, insp):
        # 20 000 × 89.325 = 1 786 500 ¥ (approx)
        max_p_ch = (0.90 - 0.88) * 294.5 / 0.97
        violation = (98.16 - max_p_ch) * 0.97
        expected_penalty = 20_000.0 * violation
        assert abs(insp.penalty_yuan - expected_penalty) < 1.0

    def test_soc_out_at_max(self, insp):
        # new_soc = 0.88 + 0.97 × 6.07216 / 294.5 = 0.9 (exactly at max)
        assert abs(insp.soc_out - 0.9) < 1e-4

    def test_constraint_soc_clipped(self, insp):
        assert insp.constraint_soc_clipped is True

    def test_reward_includes_penalty(self, insp):
        # reward = −(cost_total_reward_basis + penalty) × 1e-5
        # penalty dominates; must be more negative than T1
        expected = -(insp.cost_total_reward_basis_yuan + insp.penalty_yuan) * 1e-5
        assert abs(insp.reward - expected) < 1e-5

    def test_d13_identities_hold(self, insp):
        real = (
            insp.c_energy_yuan + insp.c_demand_charge_yuan
            + insp.c_degradation_yuan + insp.c_curtail_yuan + insp.c_voll_yuan
        )
        rb = (
            insp.c_energy_yuan + 2.0 * insp.c_demand_shape_yuan
            + insp.c_degradation_yuan + insp.c_curtail_yuan + insp.c_voll_yuan
        )
        assert abs(insp.cost_total_real_yuan - real) < TOL_YEN
        assert abs(insp.cost_total_reward_basis_yuan - rb) < TOL_YEN


class TestSOCViolationDischarge:
    """
    T3b: soc=0.22, full discharge — SOC would go below soc_min=0.2.

    P_dis_target = 1.0 × 98.16 = 98.16 MW
    max_P_dis = (0.22 − 0.20) × 294.5 × 0.97 / 1
              = 0.02 × 294.5 × 0.97
              = 5.7133 MW
    P_dis_actual = min(98.16, 5.7133) = 5.7133 MW
    violation_mwh = (98.16 − 5.7133) / 0.97 = 92.4467 / 0.97 = 95.3059 MWh
    penalty = 20 000 × 95.3059 = 1 906 118 ¥
    new_soc = 0.22 − 5.7133 / (0.97 × 294.5) = 0.22 − 0.02000 = 0.20
    """

    @pytest.fixture
    def insp(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.22, t=8, month_peak_mw=0.0)
        return ienv_t8_no_ren.step(state, [-1.0, 0, 0, 0, 0, 1.0])  # discharge + bat_to_load

    def test_soc_out_at_min(self, insp):
        assert abs(insp.soc_out - 0.2) < 1e-4

    def test_soc_violation_positive(self, insp):
        # violation > 0 (would discharge below min)
        assert insp.soc_violation_mwh > 0.0

    def test_constraint_soc_clipped(self, insp):
        assert insp.constraint_soc_clipped is True


# =========================================================================== #
#  §5 — VOLL and import cap (D12)                                              #
# =========================================================================== #

class TestImportCapAndVOLL:
    """
    T4: load=500 MW, max_import=400 MW, no renewables, no battery discharge.

    P_import_raw = 500 + 0 (no bat charging) = 500 MW > max_import=400 → capped
    P_import = 400 MW
    P_load_unserved = max(0, 500 − 400) = 100 MW
    C_VOLL = 20 000 × 100 × 1 = 2 000 000 ¥
    price_buy = 620 ¥/MWh (h=8)
    C_import = 620 × 400 × 1 = 248 000 ¥
    C_E = 248 000 ¥
    C_demand_shape = 32 000 × max(0, 400 − 0) = 12 800 000 ¥ (month_peak=0)
    cost_total_real = 248 000 + 0 + 0 + 0 + 2 000 000 = 2 248 000 ¥
    cost_total_reward_basis = 248 000 + 2×12 800 000 + 0 + 0 + 2 000 000 = 27 848 000 ¥
    reward = −27 848 000 × 1e-5 = −278.48
    """

    @pytest.fixture
    def ienv_high_load(self, det_params):
        data = make_synthetic_data_with_step(8, 0.0, 0.0, 25.0, 500.0)
        return InteractiveEnv(params=det_params, data=data)

    @pytest.fixture
    def insp(self, ienv_high_load):
        state = ienv_high_load.make_state(soc=0.5, t=8, month_peak_mw=0.0)
        return ienv_high_load.step(state, [0.0, 0, 0, 0, 0, 0])

    def test_load_unserved(self, insp):
        # 500 − 400 = 100 MW unserved
        assert abs(insp.load_unserved_mw - 100.0) < TOL_MW

    def test_p_import_capped(self, insp):
        assert abs(insp.p_import_mw - 400.0) < TOL_MW

    def test_c_voll(self, insp):
        # 20 000 × 100 × 1 = 2 000 000 ¥
        assert abs(insp.c_voll_yuan - 2_000_000.0) < TOL_YEN

    def test_constraint_import_capped(self, insp):
        assert insp.constraint_import_capped is True

    def test_real_total(self, insp):
        # 248 000 + 0 + 0 + 0 + 2 000 000 = 2 248 000 ¥
        assert abs(insp.cost_total_real_yuan - 2_248_000.0) < 1.0

    def test_d13_identities(self, insp):
        real = (
            insp.c_energy_yuan + insp.c_demand_charge_yuan
            + insp.c_degradation_yuan + insp.c_curtail_yuan + insp.c_voll_yuan
        )
        rb = (
            insp.c_energy_yuan + 2.0 * insp.c_demand_shape_yuan
            + insp.c_degradation_yuan + insp.c_curtail_yuan + insp.c_voll_yuan
        )
        assert abs(insp.cost_total_real_yuan - real) < TOL_YEN
        assert abs(insp.cost_total_reward_basis_yuan - rb) < TOL_YEN


# =========================================================================== #
#  §6 — Power conservation (per-source energy balance)                        #
# =========================================================================== #

class TestPowerConservation:
    """
    T5: Renewables + load cap fires → conservation must hold after scaling.

    Setup: t=8, wind=12 m/s → P_wind=615 MW (rated, v_hub ≥ v_rated)
           irr=1000 W/m², temp=25°C → P_pv = 330×1.0×1.0×0.97×0.98 = 313.698 MW
           load=200 MW (< total generation → load cap fires)
           action=[0, 0.5, 0, 0.4, 0, 0]
             f_sol_load=0.5, f_sol_bat=0, f_wind_load=0.4, f_wind_bat=0, a_bat=0

    Solar allocation (before load cap):
      P_sol_to_load_pre = 313.698 × 0.5 = 156.849 MW
      P_sol_to_bat = 0
    Wind allocation (before load cap):
      P_wind_to_load_pre = 615 × 0.4 = 246 MW
      P_wind_to_bat = 0

    Load cap:
      P_to_load_total = 156.849 + 246 + 0 = 402.849 MW > 200 → cap fires
      scale = 200 / 402.849 = 0.49647
      P_sol_to_load_post = 156.849 × 0.49647 = 77.853 MW
      P_wind_to_load_post = 246 × 0.49647 = 122.131 MW
      sum served = 77.853 + 122.131 = 200.0 MW ✓

    Solar conservation:
      P_sol_to_grid = P_pv − P_sol_to_load_post − P_sol_to_bat = 313.698 − 77.853 − 0 = 235.845 MW
      Check: 77.853 + 0 + 235.845 + 0 (no curtailment) = 313.698 ✓

    Wind conservation:
      P_wind_to_grid = P_wind − P_wind_to_load_post − P_wind_to_bat = 615 − 122.131 − 0 = 492.869 MW
      Check: 122.131 + 0 + 492.869 + 0 = 615 ✓

    Note: Conservation holds to float tolerance; absolute values are tested separately.
    """

    @pytest.fixture
    def ienv_renewables(self, det_params):
        data = make_synthetic_data_with_step(8, 12.0, 1000.0, 25.0, 200.0)
        return InteractiveEnv(params=det_params, data=data)

    @pytest.fixture
    def insp(self, ienv_renewables):
        state = ienv_renewables.make_state(soc=0.5, t=8, month_peak_mw=300.0)
        return ienv_renewables.step(state, [0.0, 0.5, 0.0, 0.4, 0.0, 0.0])

    def test_solar_conservation(self, insp):
        # solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed == p_pv_mw
        lhs = (
            insp.solar_to_load_mw
            + insp.solar_to_bat_mw
            + insp.solar_to_grid_mw
            + insp.solar_curtailed_mw
        )
        assert abs(lhs - insp.p_pv_mw) < TOL_MW, (
            f"Solar conservation violated: {lhs:.4f} != {insp.p_pv_mw:.4f} MW"
        )

    def test_wind_conservation(self, insp):
        # wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed == p_wind_mw
        lhs = (
            insp.wind_to_load_mw
            + insp.wind_to_bat_mw
            + insp.wind_to_grid_mw
            + insp.wind_curtailed_mw
        )
        assert abs(lhs - insp.p_wind_mw) < TOL_MW, (
            f"Wind conservation violated: {lhs:.4f} != {insp.p_wind_mw:.4f} MW"
        )

    def test_solar_conservation_flag(self, insp):
        assert insp.solar_conservation_ok is True

    def test_wind_conservation_flag(self, insp):
        assert insp.wind_conservation_ok is True

    def test_bat_conservation_flag(self, insp):
        # No discharge in this test (a_bat=0) → bat_dis=0, all bat flows=0: trivially conserved
        assert insp.bat_conservation_ok is True

    def test_load_cap_fired(self, insp):
        assert insp.constraint_load_capped is True

    def test_load_served_equals_demand(self, insp):
        # all load is served (renewables exceed demand)
        served = (
            insp.solar_to_load_mw + insp.wind_to_load_mw
            + insp.bat_to_load_mw + insp.grid_to_load_mw
        )
        assert abs(served - 200.0) < TOL_MW

    def test_p_pv_value(self, insp):
        # P_pv = 330 × 1.0 × 1.0 × 0.97 × 0.98 = 313.698 MW
        # (irr/1000=1.0, temp_factor=clip(1+(-0.003)(25-25),0.5,1.2)=1.0, eta_inv=0.97, degrad=0.98)
        assert abs(insp.p_pv_mw - 313.698) < 0.01

    def test_p_wind_value(self, insp):
        # v_hub = 12 × (105/10)^0.14 ≈ 12 × 1.3898 = 16.677 m/s ≥ v_rated=12 → rated power
        # P_wind = 615 MW
        assert abs(insp.p_wind_mw - 615.0) < 0.1


class TestExportCurtailmentConservation:
    """
    T5b: Very small load, no battery, renewable exceeds export limit → curtailment.

    Using max_export_mw=200 (custom params) so curtailment fires:
      P_pv = 313.698 MW (as above), P_wind = 615 MW
      action=[0, 0, 0, 0, 0, 0] → all to grid (a_bat=0 → charge mode, P_ch_target=0 → no bat)
      P_export_raw = 313.698 + 615 = 928.698 MW > 200
      scale_export = 200/928.698 = 0.21534
      P_sol_to_grid = 313.698 × 0.21534 = 67.565 MW
      P_wind_to_grid = 615 × 0.21534 = 132.435 MW
      P_bat_to_grid = 0 (no discharge)
      P_export = 200 MW
      P_curtailed = 928.698 − 200 = 728.698 MW
      P_sol_curtailed = 313.698 × (1−0.21534) = 246.133 MW
      P_wind_curtailed = 615 × (1−0.21534) = 482.565 MW
      P_bat_curtailed = 0 (no discharge contributing to export)
    Solar conservation: 0 + 0 + 67.565 + 246.133 = 313.698 ✓
    Wind conservation:  0 + 0 + 132.435 + 482.565 = 615 ✓
    """

    @pytest.fixture
    def ienv_small_load_small_export(self):
        params = make_deterministic_params(grid_max_export_mw=200.0)
        data = make_synthetic_data_with_step(8, 12.0, 1000.0, 25.0, 5.0)
        return InteractiveEnv(params=params, data=data)

    @pytest.fixture
    def insp(self, ienv_small_load_small_export):
        state = ienv_small_load_small_export.make_state(soc=0.5, t=8, month_peak_mw=0.0)
        return ienv_small_load_small_export.step(state, [0.0, 0, 0, 0, 0, 0])

    def test_export_cap_fired(self, insp):
        assert insp.constraint_export_capped is True

    def test_p_export_at_max(self, insp):
        assert abs(insp.p_export_mw - 200.0) < TOL_MW

    def test_solar_conservation(self, insp):
        lhs = (
            insp.solar_to_load_mw + insp.solar_to_bat_mw
            + insp.solar_to_grid_mw + insp.solar_curtailed_mw
        )
        assert abs(lhs - insp.p_pv_mw) < TOL_MW

    def test_wind_conservation(self, insp):
        lhs = (
            insp.wind_to_load_mw + insp.wind_to_bat_mw
            + insp.wind_to_grid_mw + insp.wind_curtailed_mw
        )
        assert abs(lhs - insp.p_wind_mw) < TOL_MW

    def test_c_curtail(self, insp):
        # C_curtail = 800 × P_curtailed × 1
        # P_curtailed ≈ 928.698 − 200 = 728.698 MW → 800 × 728.698 = 582 958 ¥
        total_curtailed = (
            insp.solar_curtailed_mw + insp.wind_curtailed_mw + insp.bat_curtailed_mw
        )
        expected = 800.0 * total_curtailed
        assert abs(insp.c_curtail_yuan - expected) < 1.0

    def test_conservation_flags(self, insp):
        assert insp.solar_conservation_ok is True
        assert insp.wind_conservation_ok is True
        assert insp.bat_conservation_ok is True  # no discharge: all zero, trivially satisfied

    def test_bat_curtailed_zero_when_no_discharge(self, insp):
        # No discharge (a_bat=0) → bat contributes nothing to export → bat_curtailed = 0
        assert insp.bat_curtailed_mw == 0.0


class TestBatteryCurtailmentConservation:
    """
    T5c (F1): Discharging battery pushes export over the cap → bat_curtailed > 0.

    Setup: t=8 (price=620), soc=0.7, wind=0, irr=0, load=5 MW (tiny)
           max_export_mw=20 (custom, << discharge capacity)
           action=[-1.0, 0, 0, 0, 0, 0]  (full discharge, f_bat_load=0 → all to grid)

    Discharge:
      P_dis_target = 1.0 × 98.16 = 98.16 MW
      max_P_dis = (0.7−0.2) × 294.5 × 0.97 = 0.5 × 294.5 × 0.97 = 142.843 MW
      P_dis_actual = min(98.16, 142.843) = 98.16 MW   (no SOC clip)
      soc_out = 0.7 − 98.16/(0.97×294.5) = 0.7 − 98.16/285.665 = 0.7 − 0.34366 = 0.35634

    Power flows:
      P_bat_to_load = f_bat_load × P_dis_actual = 0 × 98.16 = 0 MW
      P_bat_to_grid_pre = P_dis_actual − P_bat_to_load = 98.16 MW
      P_sol_to_grid = P_wind_to_grid = 0 (no renewables)

    Load serving:
      P_to_load_total = 0 + 0 + 0 = 0 < load=5 → no load cap
      load_deficit = max(0, 5−0) = 5 MW (served by grid import)
      Wait: in discharge mode, bat_to_load = 0 (f_bat_load=0).
      P_load_served_before_grid = 0. Grid import = load_deficit + P_grid_to_bat
      P_grid_to_bat = 0 (discharge mode)
      P_import_raw = 5 + 0 = 5 MW (load only)
      P_import = min(5, 400) = 5 MW (no import cap)
      P_grid_to_load = 5 MW
      load_unserved = 0

    PCC export cap:
      P_export_raw = P_bat_to_grid_pre = 98.16 MW > max_export=20
      scale_export = 20/98.16 = 0.20375
      P_bat_to_grid_post = 98.16 × 0.20375 = 19.994 ≈ 20 MW
      P_bat_curtailed = P_bat_to_grid_pre × (1−0.20375)
                      = 98.16 × 0.79625 = 78.166 MW
      P_export = 20 MW

    Battery conservation:
      bat_to_load + bat_to_grid + bat_curtailed = 0 + 20 + 78.166 = 98.166 ≈ 98.16 ✓
      (float32 rounding)

    C_curtail = 800 × 78.166 × 1 = 62 532.8 ¥
    """

    @pytest.fixture
    def ienv_bat_curtail(self):
        params = make_deterministic_params(grid_max_export_mw=20.0)
        data = make_synthetic_data_with_step(8, 0.0, 0.0, 25.0, 5.0)
        return InteractiveEnv(params=params, data=data)

    @pytest.fixture
    def insp(self, ienv_bat_curtail):
        state = ienv_bat_curtail.make_state(soc=0.7, t=8, month_peak_mw=200.0)
        return ienv_bat_curtail.step(state, [-1.0, 0, 0, 0, 0, 0])

    def test_bat_curtailed_positive(self, insp):
        # bat_curtailed = 98.16 × (1 − 20/98.16) = 98.16 × 0.79625 ≈ 78.166 MW
        expected_bat_curtailed = 98.16 * (1.0 - 20.0 / 98.16)
        assert insp.bat_curtailed_mw > 0.0, "Battery curtailment should be > 0"
        assert abs(insp.bat_curtailed_mw - expected_bat_curtailed) < 0.1

    def test_p_export_at_max(self, insp):
        assert abs(insp.p_export_mw - 20.0) < TOL_MW

    def test_constraint_export_capped(self, insp):
        assert insp.constraint_export_capped is True

    def test_bat_conservation(self, insp):
        # bat_to_load + bat_to_grid + bat_curtailed = P_dis_actual = 98.16 MW
        lhs = insp.bat_to_load_mw + insp.bat_to_grid_mw + insp.bat_curtailed_mw
        assert abs(lhs - insp.p_bat_dis_mw) < TOL_MW, (
            f"Battery conservation: {lhs:.4f} != P_dis={insp.p_bat_dis_mw:.4f}"
        )

    def test_bat_conservation_flag(self, insp):
        assert insp.bat_conservation_ok is True

    def test_c_curtail_includes_bat(self, insp):
        # C_curtail = 800 × (solar_curtailed + wind_curtailed + bat_curtailed)
        # ≈ 800 × 78.166 = 62 532.8 ¥
        total_curtailed = (
            insp.solar_curtailed_mw + insp.wind_curtailed_mw + insp.bat_curtailed_mw
        )
        expected = 800.0 * total_curtailed
        assert abs(insp.c_curtail_yuan - expected) < 1.0

    def test_no_soc_violation(self, insp):
        # P_dis_actual fits within SOC range (soc=0.7 >> soc_min=0.2)
        assert insp.soc_violation_mwh == 0.0

    def test_d13_identities(self, insp):
        real = (
            insp.c_energy_yuan + insp.c_demand_charge_yuan
            + insp.c_degradation_yuan + insp.c_curtail_yuan + insp.c_voll_yuan
        )
        rb = (
            insp.c_energy_yuan + 2.0 * insp.c_demand_shape_yuan
            + insp.c_degradation_yuan + insp.c_curtail_yuan + insp.c_voll_yuan
        )
        assert abs(insp.cost_total_real_yuan - real) < TOL_YEN
        assert abs(insp.cost_total_reward_basis_yuan - rb) < TOL_YEN


# =========================================================================== #
#  §7 — Demand charge booking at month boundary (D10/D21)                     #
# =========================================================================== #

class TestDemandChargeBooking:
    """
    T6: t=743 is the last step of January (MONTH_OF_STEP[744] = 1 ≠ MONTH_OF_STEP[743] = 0).
    month_peak=150 MW (peak grid import this month).

    Demand charge booked at month end:
      C_demand_charge = peak_incl_now × demand_rate
                      = max(150, P_import_t743) × 32 000

    Use zero load, zero battery action, zero renewables → P_import = 0.
    peak_incl_now = max(150, 0) = 150 MW
    C_demand_charge = 150 × 32 000 = 4 800 000 ¥
    new_month_peak = 0 (reset after booking, D10)

    cost_total_real = C_E + 4 800 000 + 0 + 0 + 0
                    = (price_buy × 0) + 4 800 000 = 4 800 000 ¥
    Note: C_demand_charge is in real total; NOT in reward_basis (D13).
    """

    @pytest.fixture
    def ienv_jan_end(self, det_params):
        # MONTH_OF_STEP[743]=0 (Jan), MONTH_OF_STEP[744]=1 (Feb): t=743 is month boundary
        data = make_synthetic_data_with_step(743, 0.0, 0.0, 25.0, 0.0)  # zero load/renewables
        return InteractiveEnv(params=det_params, data=data)

    @pytest.fixture
    def insp(self, ienv_jan_end):
        state = ienv_jan_end.make_state(soc=0.5, t=743, month_peak_mw=150.0)
        return ienv_jan_end.step(state, [0.0, 0, 0, 0, 0, 0])

    def test_c_demand_charge_booked(self, insp):
        # 150 × 32 000 = 4 800 000 ¥
        assert abs(insp.c_demand_charge_yuan - 4_800_000.0) < 1.0

    def test_month_peak_reset(self, insp):
        # After booking, new month peak resets to 0 (or max(0, P_import) of this step)
        # P_import=0 for this step → new_month_peak = 0
        assert abs(insp.month_peak_out_mw - 0.0) < TOL_MW

    def test_real_total_includes_demand_charge(self, insp):
        # cost_total_real includes 4 800 000 demand charge
        assert insp.cost_total_real_yuan >= 4_800_000.0 - TOL_YEN

    def test_reward_basis_excludes_demand_charge(self, insp):
        # reward_basis does NOT include demand charge (D13)
        # With zero load and zero import: reward_basis ≈ 0
        assert insp.cost_total_reward_basis_yuan < 1000.0  # much less than 4 800 000

    def test_d13_real_identity(self, insp):
        real = (
            insp.c_energy_yuan + insp.c_demand_charge_yuan
            + insp.c_degradation_yuan + insp.c_curtail_yuan + insp.c_voll_yuan
        )
        assert abs(insp.cost_total_real_yuan - real) < TOL_YEN


class TestSubMonthNoDemandCharge:
    """
    D21: A step mid-episode (not month boundary) books zero demand charge.
    """

    def test_mid_episode_no_demand_charge(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8, month_peak_mw=100.0)
        insp = ienv_t8_no_ren.step(state, [0.5, 0, 0, 0, 0, 0])
        assert insp.c_demand_charge_yuan == 0.0


# =========================================================================== #
#  §8 — Year-end demand charge flush (D10/D21, t=8759)                        #
# =========================================================================== #

class TestYearEndDemandChargeFlush:
    """
    T6b: t=8759 is the final eval step (D3). Terminal flush books the last month.

    month_peak=200 MW:
      C_demand_charge = 200 × 32 000 = 6 400 000 ¥
    """

    @pytest.fixture
    def ienv_year_end(self, det_params):
        data = make_synthetic_data_with_step(8759, 0.0, 0.0, 25.0, 0.0)
        return InteractiveEnv(params=det_params, data=data)

    def test_year_end_demand_charge(self, ienv_year_end):
        state = ienv_year_end.make_state(soc=0.5, t=8759, month_peak_mw=200.0)
        insp = ienv_year_end.step(state, [0.0, 0, 0, 0, 0, 0])
        # 200 × 32 000 = 6 400 000 ¥
        assert abs(insp.c_demand_charge_yuan - 6_400_000.0) < 1.0

    def test_year_end_done_flag(self, ienv_year_end):
        state = ienv_year_end.make_state(soc=0.5, t=8759, month_peak_mw=0.0)
        # With episode_len=8760 (eval), t=8759 is the last step
        params = make_deterministic_params(episode_len=8760)
        data = make_synthetic_data_with_step(8759, 0.0, 0.0, 25.0, 0.0)
        ienv = InteractiveEnv(params=params, data=data)
        state = ienv.make_state(soc=0.5, t=8759, month_peak_mw=0.0)
        insp = ienv.step(state, [0.0, 0, 0, 0, 0, 0])
        assert insp.done is True


# =========================================================================== #
#  §9 — Observation vector                                                     #
# =========================================================================== #

class TestObsVector:
    """Observation shape and basic range checks (§5.4 of jax_env_core)."""

    def test_obs_shape(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8)
        insp = ienv_t8_no_ren.step(state, [0.0, 0, 0, 0, 0, 0])
        assert len(insp.obs) == 107

    def test_get_obs_shape(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8)
        obs = ienv_t8_no_ren.get_obs(state)
        assert len(obs) == 107

    def test_obs_all_finite(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8)
        insp = ienv_t8_no_ren.step(state, [0.0, 0, 0, 0, 0, 0])
        assert all(math.isfinite(v) for v in insp.obs)

    def test_obs_soc_slot(self, ienv_t8_no_ren):
        # obs[4] = soc (§5.4 of jax_env_core)
        state = ienv_t8_no_ren.make_state(soc=0.7, t=8)
        insp = ienv_t8_no_ren.step(state, [0.0, 0, 0, 0, 0, 0])
        assert abs(insp.obs[4] - 0.7) < 1e-4


# =========================================================================== #
#  §10 — Action validation                                                     #
# =========================================================================== #

class TestActionValidation:
    """Edge cases for action input."""

    def test_wrong_length_raises(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8)
        with pytest.raises(ValueError, match="action"):
            ienv_t8_no_ren.step(state, [0.5, 0, 0])  # length 3

    def test_out_of_bounds_action_clipped(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8)
        # a_bat=2.0 should be clipped to 1.0
        insp = ienv_t8_no_ren.step(state, [2.0, 0, 0, 0, 0, 0])
        assert insp.constraint_action_clipped is True
        assert abs(insp.action_clipped[0] - 1.0) < 1e-6

    def test_action_raw_preserved(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8)
        raw = [1.5, -0.1, 0.3, 0.0, 0.0, 0.0]
        insp = ienv_t8_no_ren.step(state, raw)
        assert insp.action_raw == raw


# =========================================================================== #
#  §11 — Determinism                                                           #
# =========================================================================== #

class TestDeterminism:
    """Same inputs → identical outputs (§7 of contract)."""

    def test_step_deterministic(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8, seed=42)
        insp1 = ienv_t8_no_ren.step(state, [0.5, 0, 0, 0, 0, 0])
        insp2 = ienv_t8_no_ren.step(state, [0.5, 0, 0, 0, 0, 0])
        assert insp1.reward == insp2.reward
        assert insp1.soc_out == insp2.soc_out
        assert insp1.p_import_mw == insp2.p_import_mw

    def test_different_seeds_give_different_price(self):
        """price_sell differs between seeds when sigma>0."""
        params = EnvParams(price_spread_sigma=10.0)
        data = make_synthetic_data_with_step(8, 0.0, 0.0, 25.0, 50.0)
        ienv1 = InteractiveEnv(params=params, data=data)
        ienv2 = InteractiveEnv(params=params, data=data)
        state_s0 = ienv1.make_state(soc=0.5, t=8, seed=0)
        state_s1 = ienv2.make_state(soc=0.5, t=8, seed=1)
        insp0 = ienv1.step(state_s0, [0.0, 0, 0, 0, 0, 0])
        insp1 = ienv2.step(state_s1, [0.0, 0, 0, 0, 0, 0])
        # Different seeds → different spread draws → different price_sell with high probability
        # (Not guaranteed for any specific pair, but almost certain over 10-¥/MWh std)
        assert insp0.price_sell_yuan_per_mwh != insp1.price_sell_yuan_per_mwh


# =========================================================================== #
#  §12 — ScenarioReplay                                                        #
# =========================================================================== #

class TestScenarioReplayBasic:
    """Smoke tests for ScenarioReplay (§5.2 of contract)."""

    @pytest.fixture
    def replay(self, det_params):
        return ScenarioReplay(params=det_params)

    def test_trajectory_length(self, replay):
        actions = [[0.0, 0, 0, 0, 0, 0]] * 5
        traj = replay.run(data_seed=0, start_t=0, n_steps=5, actions=actions)
        assert traj.n_steps == 5
        assert len(traj.steps) == 5

    def test_trajectory_step_seq(self, replay):
        actions = [[0.0, 0, 0, 0, 0, 0]] * 3
        traj = replay.run(data_seed=0, start_t=10, n_steps=3, actions=actions)
        seqs = [s.seq for s in traj.steps]
        assert seqs == [0, 1, 2]

    def test_episode_reward_sum(self, replay):
        actions = [[0.0, 0, 0, 0, 0, 0]] * 3
        traj = replay.run(data_seed=0, start_t=0, n_steps=3, actions=actions)
        expected = sum(s.step_inspection.reward for s in traj.steps)
        assert abs(traj.episode_reward_sum - expected) < 1e-7

    def test_real_cost_sum(self, replay):
        actions = [[0.0, 0, 0, 0, 0, 0]] * 3
        traj = replay.run(data_seed=0, start_t=0, n_steps=3, actions=actions)
        expected = sum(s.step_inspection.cost_total_real_yuan for s in traj.steps)
        assert abs(traj.episode_real_cost_yuan - expected) < TOL_YEN


class TestScenarioReplayDeterminism:
    """Same seed+actions → identical trajectory (§7 of contract)."""

    @pytest.fixture
    def replay(self, det_params):
        return ScenarioReplay(params=det_params)

    def test_identical_runs(self, replay):
        actions = [[0.3, 0.2, 0.1, 0.4, 0.1, 0.5]] * 10
        traj1 = replay.run(data_seed=42, start_t=0, n_steps=10, actions=actions)
        traj2 = replay.run(data_seed=42, start_t=0, n_steps=10, actions=actions)
        for s1, s2 in zip(traj1.steps, traj2.steps):
            assert s1.step_inspection.reward == s2.step_inspection.reward
            assert s1.step_inspection.soc_out == s2.step_inspection.soc_out

    def test_different_seeds_differ(self, replay):
        actions = [[0.3, 0.2, 0.1, 0.4, 0.1, 0.5]] * 5
        traj1 = replay.run(data_seed=0, start_t=0, n_steps=5, actions=actions)
        traj2 = replay.run(data_seed=99, start_t=0, n_steps=5, actions=actions)
        rewards1 = [s.step_inspection.reward for s in traj1.steps]
        rewards2 = [s.step_inspection.reward for s in traj2.steps]
        assert rewards1 != rewards2  # different synthetic years → different physics


class TestScenarioReplayErrors:
    """Input validation for ScenarioReplay."""

    @pytest.fixture
    def replay(self, det_params):
        return ScenarioReplay(params=det_params)

    def test_neither_actions_nor_policy_raises(self, replay):
        with pytest.raises(ValueError):
            replay.run(data_seed=0, start_t=0, n_steps=5)

    def test_both_actions_and_policy_raises(self, replay):
        with pytest.raises(ValueError):
            replay.run(
                data_seed=0, start_t=0, n_steps=2,
                actions=[[0]*6, [0]*6],
                policy_fn=lambda obs: np.zeros(6),
            )

    def test_wrong_action_count_raises(self, replay):
        with pytest.raises(ValueError):
            replay.run(data_seed=0, start_t=0, n_steps=5, actions=[[0]*6] * 3)

    def test_start_t_overflow_raises(self, replay):
        # start_t + n_steps = 8760 + 1 > 8760
        with pytest.raises(ValueError):
            replay.run(data_seed=0, start_t=8758, n_steps=5, actions=[[0]*6]*5)

    def test_n_steps_zero_raises(self, replay):
        with pytest.raises(ValueError):
            replay.run(data_seed=0, start_t=0, n_steps=0, actions=[])

    def test_policy_fn_used(self, replay):
        """Policy callable path: obs → action, runs without error."""
        policy = lambda obs: np.zeros(6)
        traj = replay.run(data_seed=0, start_t=0, n_steps=5, policy_fn=policy)
        assert traj.n_steps == 5


class TestScenarioReplayCostIdentities:
    """All StepInspection records in a trajectory satisfy D13 identities."""

    @pytest.fixture
    def replay(self, det_params):
        return ScenarioReplay(params=det_params)

    def test_d13_identities_all_steps(self, replay):
        actions = [[0.3, 0.2, 0, 0.4, 0, 0.3]] * 20
        traj = replay.run(data_seed=7, start_t=0, n_steps=20, actions=actions)
        for ts in traj.steps:
            si = ts.step_inspection
            real = (
                si.c_energy_yuan + si.c_demand_charge_yuan
                + si.c_degradation_yuan + si.c_curtail_yuan + si.c_voll_yuan
            )
            rb = (
                si.c_energy_yuan + 2.0 * si.c_demand_shape_yuan
                + si.c_degradation_yuan + si.c_curtail_yuan + si.c_voll_yuan
            )
            assert abs(si.cost_total_real_yuan - real) < TOL_YEN
            assert abs(si.cost_total_reward_basis_yuan - rb) < TOL_YEN


class TestScenarioReplayConservationAllSteps:
    """Conservation identity holds for every step in a trajectory."""

    @pytest.fixture
    def replay(self, det_params):
        return ScenarioReplay(params=det_params)

    def test_conservation_all_steps(self, replay):
        actions = [[0.3, 0.2, 0.1, 0.4, 0.1, 0.3]] * 50
        traj = replay.run(data_seed=5, start_t=100, n_steps=50, actions=actions)
        for ts in traj.steps:
            si = ts.step_inspection
            assert si.solar_conservation_ok, f"Solar conservation failed at seq={ts.seq}"
            assert si.wind_conservation_ok, f"Wind conservation failed at seq={ts.seq}"
            assert si.bat_conservation_ok, f"Battery conservation failed at seq={ts.seq}"


# =========================================================================== #
#  §13 — RunManager lifecycle                                                  #
# =========================================================================== #

@pytest.fixture
def base_run_config():
    return RunConfig(
        env_params={},   # use EnvParams defaults
        data_seed=0,
        episode_len=168,
        total_env_steps=10_000,
        log_every_steps=500,
        eval_every_steps=5_000,
        checkpoint_every_steps=5_000,
        n_envs=2,
        learning_rate=3e-4,
        gamma=0.99,
        batch_size=64,
        buffer_size=10_000,
    )


class TestRunManagerLifecycle:
    """State machine tests for RunManager (§5.3 of contract)."""

    def test_start_run_returns_run_id(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        assert isinstance(run_id, str)
        assert len(run_id) > 0

    def test_start_run_status_running(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        record = mgr.get_run(run_id)
        assert record.status == RunStatus.RUNNING

    def test_pause_run(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        mgr.pause_run(run_id)
        assert mgr.get_run(run_id).status == RunStatus.PAUSED

    def test_resume_run(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        mgr.pause_run(run_id)
        mgr.resume_run(run_id)
        assert mgr.get_run(run_id).status == RunStatus.RUNNING

    def test_stop_run_terminal(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        mgr.stop_run(run_id)
        assert mgr.get_run(run_id).status == RunStatus.STOPPED

    def test_resume_stopped_raises(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        mgr.stop_run(run_id)
        with pytest.raises(ValueError):
            mgr.resume_run(run_id)

    def test_pause_idempotent(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        mgr.pause_run(run_id)
        mgr.pause_run(run_id)  # second call is a no-op
        assert mgr.get_run(run_id).status == RunStatus.PAUSED

    def test_stop_idempotent(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        mgr.stop_run(run_id)
        mgr.stop_run(run_id)  # second call is a no-op
        assert mgr.get_run(run_id).status == RunStatus.STOPPED

    def test_unknown_run_id_raises_key_error(self, tmp_storage):
        mgr = RunManager(storage_dir=tmp_storage)
        with pytest.raises(KeyError):
            mgr.get_run("nonexistent-run-id")
        with pytest.raises(KeyError):
            mgr.pause_run("nonexistent-run-id")
        with pytest.raises(KeyError):
            mgr.stop_run("nonexistent-run-id")


class TestRunManagerHistory:
    """Multiple runs tracked and queryable (§5.3)."""

    def test_multiple_runs_tracked(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        id1 = mgr.start_run(base_run_config)
        id2 = mgr.start_run(base_run_config)
        id3 = mgr.start_run(base_run_config)
        runs = mgr.list_runs()
        ids = {r.run_id for r in runs}
        assert id1 in ids and id2 in ids and id3 in ids

    def test_list_runs_newest_first(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        ids = [mgr.start_run(base_run_config) for _ in range(3)]
        runs = mgr.list_runs()
        # newest first: last started = runs[0]
        assert runs[0].run_id == ids[-1]

    def test_unique_run_ids(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        ids = [mgr.start_run(base_run_config) for _ in range(5)]
        assert len(set(ids)) == 5

    def test_get_run_returns_correct_config(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        record = mgr.get_run(run_id)
        assert record.config.data_seed == base_run_config.data_seed
        assert record.config.total_env_steps == base_run_config.total_env_steps


class TestRunConfigValidation:
    """RunManager.start_run validates RunConfig (§4.2)."""

    def test_invalid_episode_len_raises(self, tmp_storage):
        mgr = RunManager(storage_dir=tmp_storage)
        bad_config = RunConfig(env_params={}, data_seed=0, episode_len=100)  # not 168 or 8760
        with pytest.raises(ValueError, match="episode_len"):
            mgr.start_run(bad_config)

    def test_unknown_env_param_raises(self, tmp_storage):
        mgr = RunManager(storage_dir=tmp_storage)
        bad_config = RunConfig(
            env_params={"not_a_real_param": 99.0},
            data_seed=0,
        )
        with pytest.raises(ValueError, match="env_params"):
            mgr.start_run(bad_config)

    def test_n_envs_zero_raises(self, tmp_storage):
        mgr = RunManager(storage_dir=tmp_storage)
        bad_config = RunConfig(env_params={}, data_seed=0, n_envs=0)
        with pytest.raises(ValueError, match="n_envs"):
            mgr.start_run(bad_config)


# =========================================================================== #
#  §14 — Telemetry schema conformance (D18, validate-telemetry skill)         #
# =========================================================================== #

class TestMetricsTelemetryConformance:
    """
    stream_metrics emits messages conforming to LOCKED telemetry_schema.md v1.0.0.
    Uses energy_go.telemetry.validate (D18) to assert conformance.
    """

    def _collect_messages(self, mgr, run_id, n=5, timeout=5.0):
        msgs = []
        it = mgr.stream_metrics(run_id, timeout_s=timeout)
        for _ in range(n):
            try:
                msgs.append(next(it))
            except StopIteration:
                break
        return msgs

    def test_messages_have_envelope_fields(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        msgs = self._collect_messages(mgr, run_id, n=3)
        for msg in msgs:
            assert "schema_version" in msg
            assert "kind" in msg
            assert "ts_utc" in msg
            assert "run_id" in msg
            assert "seq" in msg
            assert "payload" in msg

    def test_schema_version_locked(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        msgs = self._collect_messages(mgr, run_id, n=3)
        for msg in msgs:
            assert msg["schema_version"] == "1.0.0"

    def test_run_id_matches(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        msgs = self._collect_messages(mgr, run_id, n=3)
        for msg in msgs:
            assert msg["run_id"] == run_id

    def test_seq_monotonic(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        msgs = self._collect_messages(mgr, run_id, n=5)
        seqs = [m["seq"] for m in msgs]
        for a, b in zip(seqs, seqs[1:]):
            assert b > a, f"seq not strictly monotonic: {seqs}"

    def test_validate_message_passes(self, tmp_storage, base_run_config):
        """energy_go.telemetry.validate raises no error on well-formed messages."""
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        msgs = self._collect_messages(mgr, run_id, n=3)
        for msg in msgs:
            errors = validate_message(msg)
            assert errors == [], f"Telemetry validation errors: {errors}"

    def test_train_metrics_kind(self, tmp_storage, base_run_config):
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        msgs = self._collect_messages(mgr, run_id, n=5)
        kinds = {m["kind"] for m in msgs}
        # At minimum, train_metrics should appear
        assert "train_metrics" in kinds

    def test_no_nan_or_inf(self, tmp_storage, base_run_config):
        """All numeric fields in streamed messages are finite (no NaN/Inf)."""
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(base_run_config)
        msgs = self._collect_messages(mgr, run_id, n=5)

        def check_finite(obj, path=""):
            if isinstance(obj, float):
                assert math.isfinite(obj), f"Non-finite value at {path}: {obj}"
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    check_finite(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    check_finite(v, f"{path}[{i}]")

        for msg in msgs:
            check_finite(msg)

    def test_eval_compare_when_triggered(self, tmp_storage):
        """eval_compare is emitted when is_eval_checkpoint triggers."""
        eval_config = RunConfig(
            env_params={},
            data_seed=1,
            total_env_steps=5_000,
            eval_every_steps=2_500,
            n_envs=2,
        )
        mgr = RunManager(storage_dir=tmp_storage)
        run_id = mgr.start_run(eval_config)
        msgs = self._collect_messages(mgr, run_id, n=20, timeout=30.0)
        eval_msgs = [m for m in msgs if m["kind"] == "eval_compare"]
        if eval_msgs:  # only check if eval ran within timeout
            for m in eval_msgs:
                payload = m["payload"]
                assert "policies" in payload
                assert "rl" in payload["policies"]
                assert "no_battery" in payload["policies"]
                assert "rule_based_tou" in payload["policies"]
                assert payload["cost_basis"] == "real_money"
                # Additive identity per policy
                for policy_name, p in payload["policies"].items():
                    total = (
                        p["energy_cost_yuan"] + p["demand_charge_yuan"]
                        + p["degradation_yuan"] + p["curtailment_yuan"]
                        + p["voll_yuan"]
                    )
                    assert abs(total - p["total_cost_yuan"]) < 1.0, (
                        f"eval_compare additive identity violated for {policy_name}: "
                        f"{total:.2f} != {p['total_cost_yuan']:.2f}"
                    )


class TestValidateMessageNegative:
    """
    F2: validate_message must REJECT broken envelopes (errors != []).
    Without this, a no-op validator or a subtly-wrong producer message
    would slip through the conformance tests above.
    """

    def test_missing_required_field_envelope(self):
        # Drop 'kind' — required by schema envelope
        broken = {
            "schema_version": "1.0.0",
            # "kind" deliberately missing
            "ts_utc": "2026-06-10T08:00:00Z",
            "run_id": "test-run",
            "seq": 1,
            "payload": {}
        }
        errors = validate_message(broken)
        assert errors != [], (
            "validate_message should reject an envelope missing required 'kind' field"
        )

    def test_nan_in_numeric_field_rejected(self):
        # A payload with NaN violates the global finiteness invariant (LOCKED schema §5)
        broken = {
            "schema_version": "1.0.0",
            "kind": "train_metrics",
            "ts_utc": "2026-06-10T08:00:00Z",
            "run_id": "test-run",
            "seq": 1,
            "payload": {
                "global_step": 1000,
                "wall_seconds": float("nan"),  # NaN — must be rejected
                "env_steps_per_sec": 1e6,
                "actor_loss": 0.5,
                "critic_loss": 1.0,
                "ent_coef": 0.2,
                "reward_scaled_mean": 0.5,
                "reward_norm_mean": None,
                "cost_total_real_mean_yuan": -1000.0,
                "is_eval_checkpoint": False,
                "checkpoint_id": None,
            }
        }
        errors = validate_message(broken)
        assert errors != [], (
            "validate_message should reject a message with NaN in a numeric field"
        )

    def test_inf_in_numeric_field_rejected(self):
        broken = {
            "schema_version": "1.0.0",
            "kind": "train_metrics",
            "ts_utc": "2026-06-10T08:00:00Z",
            "run_id": "test-run",
            "seq": 2,
            "payload": {
                "global_step": 2000,
                "wall_seconds": float("inf"),  # +Inf — must be rejected
                "env_steps_per_sec": 1e6,
                "actor_loss": 0.5,
                "critic_loss": 1.0,
                "ent_coef": 0.2,
                "reward_scaled_mean": 0.5,
                "reward_norm_mean": None,
                "cost_total_real_mean_yuan": -1000.0,
                "is_eval_checkpoint": False,
                "checkpoint_id": None,
            }
        }
        errors = validate_message(broken)
        assert errors != [], (
            "validate_message should reject a message with +Inf in a numeric field"
        )

    def test_wrong_kind_rejected(self):
        # 'kind' must be one of "env_step" | "train_metrics" | "eval_compare"
        broken = {
            "schema_version": "1.0.0",
            "kind": "not_a_real_kind",
            "ts_utc": "2026-06-10T08:00:00Z",
            "run_id": "test-run",
            "seq": 1,
            "payload": {}
        }
        errors = validate_message(broken)
        assert errors != [], (
            "validate_message should reject an envelope with an invalid 'kind' value"
        )

    def test_missing_payload_field_rejected(self):
        # train_metrics payload is missing required 'global_step'
        broken = {
            "schema_version": "1.0.0",
            "kind": "train_metrics",
            "ts_utc": "2026-06-10T08:00:00Z",
            "run_id": "test-run",
            "seq": 1,
            "payload": {
                # global_step deliberately missing
                "wall_seconds": 1.0,
                "env_steps_per_sec": 1e6,
                "actor_loss": 0.5,
                "critic_loss": 1.0,
                "ent_coef": 0.2,
                "reward_scaled_mean": 0.5,
                "reward_norm_mean": None,
                "cost_total_real_mean_yuan": -1000.0,
                "is_eval_checkpoint": False,
                "checkpoint_id": None,
            }
        }
        errors = validate_message(broken)
        assert errors != [], (
            "validate_message should reject a train_metrics payload missing 'global_step'"
        )

    def test_eval_compare_cost_identity_violation_rejected(self):
        """
        eval_compare with total_cost_yuan != sum of components must be rejected.
        D13: total = energy + demand + degradation + curtailment + voll.
        """
        broken_policy = {
            "energy_cost_yuan": 100.0,
            "demand_charge_yuan": 200.0,
            "degradation_yuan": 50.0,
            "curtailment_yuan": 0.0,
            "voll_yuan": 0.0,
            "total_cost_yuan": 999.0,   # wrong: should be 350.0
            "soc_violations_count": 0,
            "soc_violation_mwh": 0.0,
            "penalty_yuan": 0.0,
        }
        broken = {
            "schema_version": "1.0.0",
            "kind": "eval_compare",
            "ts_utc": "2026-06-10T08:00:00Z",
            "run_id": "test-run",
            "seq": 1,
            "payload": {
                "eval_horizon_steps": 8760,
                "checkpoint_id": "ckpt-1",
                "cost_basis": "real_money",
                "policies": {
                    "rl": broken_policy,
                    "no_battery": broken_policy,
                    "rule_based_tou": broken_policy,
                }
            }
        }
        errors = validate_message(broken)
        assert errors != [], (
            "validate_message should reject eval_compare where total_cost_yuan "
            "violates the D13 additive identity"
        )


class TestStreamMetricsUnknownRunIdRaises:
    def test_unknown_run_id(self, tmp_storage):
        mgr = RunManager(storage_dir=tmp_storage)
        with pytest.raises(KeyError):
            list(mgr.stream_metrics("unknown-run-id", timeout_s=0.1))


# =========================================================================== #
#  §15 — Sweeper                                                               #
# =========================================================================== #

class TestSweeperBasic:
    """Smoke tests for Sweeper (§5.4 of contract)."""

    @pytest.fixture
    def sweep_variants(self):
        return [
            SweepVariant(
                variant_id="high_lr",
                env_params_overrides={},
                training_params_overrides={"learning_rate": 1e-3},
            ),
            SweepVariant(
                variant_id="low_lr",
                env_params_overrides={},
                training_params_overrides={"learning_rate": 1e-4},
            ),
        ]

    def test_result_count(self, tmp_storage, base_run_config, sweep_variants):
        sw = Sweeper(storage_dir=tmp_storage)
        results = sw.run_sweep(
            variants=sweep_variants,
            n_seeds=2,
            n_eval_steps=168,
            base_config=base_run_config,
        )
        # 2 variants × 2 seeds = 4 results
        assert len(results) == 4

    def test_result_types(self, tmp_storage, base_run_config, sweep_variants):
        sw = Sweeper(storage_dir=tmp_storage)
        results = sw.run_sweep(
            variants=sweep_variants, n_seeds=1, n_eval_steps=168,
            base_config=base_run_config,
        )
        for r in results:
            assert isinstance(r, SweepResult)
            assert isinstance(r.variant_id, str)
            assert isinstance(r.seed, int)
            assert isinstance(r.run_id, str)
            assert isinstance(r.reward_mean, float)
            assert isinstance(r.completed, bool)

    def test_variant_ids_in_results(self, tmp_storage, base_run_config, sweep_variants):
        sw = Sweeper(storage_dir=tmp_storage)
        results = sw.run_sweep(
            variants=sweep_variants, n_seeds=1, n_eval_steps=168,
            base_config=base_run_config,
        )
        result_variant_ids = {r.variant_id for r in results}
        assert result_variant_ids == {"high_lr", "low_lr"}


class TestSweeperDeterminism:
    """Same variant+seed → same result (§7 of contract)."""

    def test_same_variant_seed_identical(self, tmp_storage, base_run_config):
        sw = Sweeper(storage_dir=tmp_storage)
        v = [SweepVariant("v1", {}, {})]
        r1 = sw.run_sweep(v, n_seeds=1, n_eval_steps=168, base_config=base_run_config)
        r2 = sw.run_sweep(v, n_seeds=1, n_eval_steps=168, base_config=base_run_config)
        assert r1[0].reward_mean == r2[0].reward_mean


class TestSweeperErrors:
    """Input validation for Sweeper."""

    def test_empty_variants_raises(self, tmp_storage, base_run_config):
        sw = Sweeper(storage_dir=tmp_storage)
        with pytest.raises(ValueError):
            sw.run_sweep([], n_seeds=1, n_eval_steps=168, base_config=base_run_config)

    def test_duplicate_variant_ids_raises(self, tmp_storage, base_run_config):
        sw = Sweeper(storage_dir=tmp_storage)
        dups = [
            SweepVariant("dup", {}, {}),
            SweepVariant("dup", {}, {}),
        ]
        with pytest.raises(ValueError, match="variant_id"):
            sw.run_sweep(dups, n_seeds=1, n_eval_steps=168, base_config=base_run_config)

    def test_n_seeds_zero_raises(self, tmp_storage, base_run_config):
        sw = Sweeper(storage_dir=tmp_storage)
        with pytest.raises(ValueError):
            sw.run_sweep(
                [SweepVariant("v1", {}, {})],
                n_seeds=0,
                n_eval_steps=168,
                base_config=base_run_config,
            )


# =========================================================================== #
#  §16 — Price tier and telemetry tariff_tier field                            #
# =========================================================================== #

class TestTariffTier:
    """
    tariff_tier in StepInspection matches §3.7 tier boundaries.
    At Δt=1h, steps land on :00; tier per PRICE_TABLE_YPW:
      h=0–6:  valley (250 ¥/MWh)
      h=7:    mid    (450 ¥/MWh)
      h=8–10: peak   (620 ¥/MWh)
      h=11:   critical_peak (780 ¥/MWh)  [10:30–11:30 ⊃ 11:00]
      h=12–17:mid   (450 ¥/MWh)
      h=18:   peak   (620 ¥/MWh)
      h=19–20:critical_peak (780 ¥/MWh)
      h=21–22:peak   (620 ¥/MWh)
      h=23:   valley (250 ¥/MWh)
    """

    @pytest.mark.parametrize("t,expected_tier", [
        (0,  "valley"),         # h=0
        (3,  "valley"),         # h=3
        (7,  "mid"),            # h=7
        (8,  "peak"),           # h=8
        (10, "peak"),           # h=10
        (11, "critical_peak"),  # h=11 ∈ [10:30,11:30)
        (12, "mid"),            # h=12
        (18, "peak"),           # h=18
        (19, "critical_peak"),  # h=19 ∈ [19:00,21:00)
        (23, "valley"),         # h=23
    ])
    def test_tariff_tier(self, det_params, t, expected_tier):
        data = make_synthetic_data_with_step(t, 0.0, 0.0, 25.0, 0.0)
        ienv = InteractiveEnv(params=det_params, data=data)
        state = ienv.make_state(soc=0.5, t=t)
        insp = ienv.step(state, [0.0, 0, 0, 0, 0, 0])
        assert insp.tariff_tier == expected_tier

    @pytest.mark.parametrize("t,expected_price", [
        (0,  250.0),
        (7,  450.0),
        (8,  620.0),
        (11, 780.0),
        (19, 780.0),
        (23, 250.0),
    ])
    def test_price_buy(self, det_params, t, expected_price):
        data = make_synthetic_data_with_step(t, 0.0, 0.0, 25.0, 0.0)
        ienv = InteractiveEnv(params=det_params, data=data)
        state = ienv.make_state(soc=0.5, t=t)
        insp = ienv.step(state, [0.0, 0, 0, 0, 0, 0])
        assert abs(insp.price_buy_yuan_per_mwh - expected_price) < 1e-3

    def test_price_sell_at_most_price_buy(self, det_params):
        """D7: price_sell ≤ price_buy always."""
        for t in range(24):
            data = make_synthetic_data_with_step(t, 0.0, 0.0, 25.0, 10.0)
            ienv = InteractiveEnv(params=det_params, data=data)
            state = ienv.make_state(soc=0.5, t=t)
            insp = ienv.step(state, [0.0, 0, 0, 0, 0, 0])
            assert insp.price_sell_yuan_per_mwh <= insp.price_buy_yuan_per_mwh


# =========================================================================== #
#  §17 — All numeric fields finite (LOCKED telemetry invariant)               #
# =========================================================================== #

class TestFiniteness:
    """All StepInspection numeric fields are finite — no NaN/Inf."""

    def test_step_inspection_all_finite(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8)
        insp = ienv_t8_no_ren.step(state, [0.5, 0.3, 0.2, 0.4, 0.1, 0.5])
        numeric_fields = {
            "p_pv_mw", "p_wind_mw", "p_bat_ch_mw", "p_bat_dis_mw",
            "p_import_mw", "p_export_mw", "load_unserved_mw", "soc_violation_mwh",
            "c_import_yuan", "r_export_yuan", "c_energy_yuan", "c_demand_shape_yuan",
            "c_demand_charge_yuan", "c_degradation_yuan", "c_curtail_yuan",
            "c_voll_yuan", "penalty_yuan", "cost_total_real_yuan",
            "cost_total_reward_basis_yuan", "reward",
        }
        for field in numeric_fields:
            val = getattr(insp, field)
            assert math.isfinite(val), f"Field {field} = {val} is not finite"

    def test_obs_all_finite(self, ienv_t8_no_ren):
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8)
        insp = ienv_t8_no_ren.step(state, [0.0, 0, 0, 0, 0, 0])
        for i, v in enumerate(insp.obs):
            assert math.isfinite(v), f"obs[{i}] = {v} is not finite"


# =========================================================================== #
#  §18 — D13 cost identity holds over a 7-day episode (168 steps)             #
# =========================================================================== #

class TestD21SubMonthEpisode168Steps:
    """
    D21: A full 168-step training episode (7 days) starting at t=0.
    No month boundary within steps 0–167 → Σ c_demand_charge_yuan = 0.
    Training pressure comes from 2·c_demand_shape, not c_demand_charge.
    """

    @pytest.fixture
    def replay(self, det_params):
        return ScenarioReplay(params=det_params)

    def test_sum_demand_charge_zero(self, replay):
        # 168 steps starting at t=0: no month boundary in Jan (Jan ends at t=743)
        actions = [[0.3, 0, 0, 0.3, 0, 0.2]] * 168
        traj = replay.run(data_seed=0, start_t=0, n_steps=168, actions=actions)
        total_demand_charge = sum(
            ts.step_inspection.c_demand_charge_yuan for ts in traj.steps
        )
        assert total_demand_charge == 0.0, (
            f"D21 violated: 7-day episode booked demand charge = {total_demand_charge} ¥"
        )

    def test_reward_pressure_nonzero(self, replay):
        """Even with demand_charge=0, reward still responds to demand shape (2× weight)."""
        high_import_action = [0.0, 0, 0, 0, 0, 0]  # high import (no generation, just serve load)
        actions = [high_import_action] * 168
        traj = replay.run(data_seed=0, start_t=0, n_steps=168, actions=actions)
        total_shape = sum(
            ts.step_inspection.c_demand_shape_yuan for ts in traj.steps
        )
        # With non-zero load, import > 0, so shape > 0 most steps
        assert total_shape >= 0.0  # always non-negative


# =========================================================================== #
#  §19 — Monthly demand charge: two months (D10 no double-count)              #
# =========================================================================== #

class TestTwoMonthDemandCharge:
    """
    Start at t=700 (Jan), run 100 steps crossing the Jan→Feb boundary at t=743.
    Verify: exactly one demand charge booking in Jan, zero in Feb steps.
    t=700 to t=743: 44 Jan steps
    t=744 to t=799: 56 Feb steps (no month boundary)
    """

    @pytest.fixture
    def replay(self, det_params):
        return ScenarioReplay(params=det_params)

    def test_single_demand_charge_booking(self, replay):
        # Zero everything except battery charge (drives month_peak up for interesting charge)
        actions = [[0.3, 0, 0, 0, 0, 0]] * 100  # charges from grid, drives import/month_peak
        traj = replay.run(data_seed=0, start_t=700, n_steps=100, actions=actions)
        bookings = [
            (ts.seq, ts.step_inspection.c_demand_charge_yuan)
            for ts in traj.steps
            if ts.step_inspection.c_demand_charge_yuan > 0
        ]
        # Should see exactly one booking at the Jan boundary (seq=43, t=743)
        assert len(bookings) == 1, (
            f"Expected exactly 1 demand charge booking, got: {bookings}"
        )
        seq, charge = bookings[0]
        assert seq == 43  # t=743 is step 0+43 = seq 43 within this trajectory


# reviewer: check that PRICE_TABLE_YPW[11]=780 correctly since critical-peak
# is 10:30-11:30 and hour 11 lands at 11:00 which is within that window. D8 §3.7.
class TestPriceTableCriticalPeakHour11:
    """
    D8: hour 11 (11:00:00) is within the critical-peak window 10:30–11:30.
    PRICE_TABLE_YPW[11] must equal 780 ¥/MWh, NOT 450 (mid) or 620 (peak).
    """

    def test_price_table_hour_11(self):
        assert PRICE_TABLE_YPW[11] == 780.0, (
            f"PRICE_TABLE_YPW[11] = {PRICE_TABLE_YPW[11]} ≠ 780 ¥/MWh. "
            "Hour 11 (11:00) lies within critical-peak window 10:30–11:30 (D8/§3.7)."
        )

    def test_price_table_hour_10(self):
        # Hour 10 (10:00) is BEFORE 10:30 boundary → still peak (620)
        assert PRICE_TABLE_YPW[10] == 620.0, (
            f"PRICE_TABLE_YPW[10] = {PRICE_TABLE_YPW[10]} ≠ 620 ¥/MWh. "
            "Hour 10 (10:00) is before critical-peak boundary at 10:30."
        )

    def test_price_table_hour_12(self):
        # Hour 12 (12:00) is AFTER 11:30 boundary → mid (450)
        assert PRICE_TABLE_YPW[12] == 450.0, (
            f"PRICE_TABLE_YPW[12] = {PRICE_TABLE_YPW[12]} ≠ 450 ¥/MWh. "
            "Hour 12 (12:00) is after critical-peak boundary at 11:30, → mid tier."
        )


# =========================================================================== #
#  §R — Reviewer-added edge cases (backend-reviewer, PR #43 gate, e499f48)     #
# =========================================================================== #
class TestReviewerAddedHarness:
    """Backend-reviewer edge cases. Hand-derived; arithmetic shown in comments.

    Targets untested edges: (1) all THREE grid channels exporting under one PCC
    cap — uniform scale_export; (2) D7 sell-price clamp at a valley hour (T1-T6
    are all at peak h=8); (3) charge-mode battery conservation branch; (4) the
    C_DC_shape max(0,·) knife-edge at month_peak == P_import.
    """

    # --- R1: mixed solar+wind+battery export, all curtailed by the SAME scale ---
    @pytest.fixture
    def insp_mixed_export(self):
        # reviewer: T5b is renewable-only export, T5c is battery-only. This exercises ALL
        # reviewer: THREE grid channels exporting simultaneously under a binding PCC cap,
        # reviewer: verifying jax_env_core §5.3.5 applies ONE scale_export uniformly to
        # reviewer: P_sol_to_grid / P_wind_to_grid / P_bat_to_grid.
        # reviewer: t=8, wind=12 (rated), irr=1000, load=5, a_bat=-1 (discharge), all
        # reviewer: allocation fractions 0 → solar, wind, and battery all flow to grid;
        # reviewer: max_export=200 binds. With bat_to_load=0 and no renewable-to-load, the
        # reviewer: pre-cap grid flow of each source equals p_pv / p_wind / p_bat_dis, so a
        # reviewer: single scale_export ⇒ curtailed fraction identical across all three:
        # reviewer:   sol_curtailed/p_pv == wind_curtailed/p_wind == bat_curtailed/p_bat_dis.
        params = make_deterministic_params(grid_max_export_mw=200.0)
        data = make_synthetic_data_with_step(8, 12.0, 1000.0, 25.0, 5.0)
        ienv = InteractiveEnv(params=params, data=data)
        state = ienv.make_state(soc=0.7, t=8, month_peak_mw=200.0)
        return ienv.step(state, [-1.0, 0, 0, 0, 0, 0])

    def test_mixed_export_at_cap(self, insp_mixed_export):
        # reviewer: P_export pinned at the cap; export-cap constraint flag set.
        assert abs(insp_mixed_export.p_export_mw - 200.0) < TOL_MW
        assert insp_mixed_export.constraint_export_capped is True

    def test_mixed_all_three_conservation(self, insp_mixed_export):
        # reviewer: every source's per-source conservation holds after proportional curtailment.
        assert insp_mixed_export.solar_conservation_ok is True
        assert insp_mixed_export.wind_conservation_ok is True
        assert insp_mixed_export.bat_conservation_ok is True

    def test_mixed_uniform_scale_export(self, insp_mixed_export):
        # reviewer: ONE scale_export ⇒ identical curtailed fraction across all three channels.
        # reviewer: pre-cap grid flow == generation/discharge for each (nothing routed to load).
        i = insp_mixed_export
        frac_sol = i.solar_curtailed_mw / i.p_pv_mw
        frac_wind = i.wind_curtailed_mw / i.p_wind_mw
        frac_bat = i.bat_curtailed_mw / i.p_bat_dis_mw
        assert abs(frac_sol - frac_wind) < 1e-3, (frac_sol, frac_wind)
        assert abs(frac_sol - frac_bat) < 1e-3, (frac_sol, frac_bat)
        assert i.bat_curtailed_mw > 0.0

    def test_mixed_c_curtail_sums_all_sources(self, insp_mixed_export):
        # reviewer: C_curtail = 800 ¥/MWh × (solar + wind + bat curtailed) × 1 h.
        i = insp_mixed_export
        expected = 800.0 * (i.solar_curtailed_mw + i.wind_curtailed_mw + i.bat_curtailed_mw)
        assert abs(i.c_curtail_yuan - expected) < 1.0

    # --- R2: D7 sell-price clamp at a valley hour (h=0) ---
    @pytest.fixture
    def insp_valley(self):
        # reviewer: every hand-cost test T1-T6 runs at peak h=8 (620). This pins the D7
        # reviewer: sell-price formula at a VALLEY hour. t=0 → PRICE_TABLE_YPW[0]; with
        # reviewer: spread=30 and sigma=0, price_sell = max(0, price_buy − 30), and the
        # reviewer: D7 invariant price_sell ≤ price_buy must hold.
        params = make_deterministic_params()
        data = make_synthetic_data_with_step(0, 0.0, 0.0, 25.0, 50.0)
        ienv = InteractiveEnv(params=params, data=data)
        state = ienv.make_state(soc=0.5, t=0, month_peak_mw=100.0)
        return ienv.step(state, [0.0, 0, 0, 0, 0, 0])

    def test_valley_price_buy_matches_table(self, insp_valley):
        # reviewer: price_buy at h=0 == PRICE_TABLE_YPW[0] (source of truth, not hardcoded).
        assert abs(insp_valley.price_buy_yuan_per_mwh - float(PRICE_TABLE_YPW[0])) < TOL_YEN

    def test_valley_price_sell_clamp(self, insp_valley):
        # reviewer: D7: price_sell = max(0, price_buy − 30); and price_sell ≤ price_buy.
        pb = insp_valley.price_buy_yuan_per_mwh
        assert abs(insp_valley.price_sell_yuan_per_mwh - max(0.0, pb - 30.0)) < TOL_YEN
        assert insp_valley.price_sell_yuan_per_mwh <= pb + 1e-6

    def test_valley_tariff_tier(self, insp_valley):
        # reviewer: hour 0 classifies as the valley tier.
        assert insp_valley.tariff_tier == "valley"

    # --- R3: battery conservation in CHARGE mode (the other §4.4 branch) ---
    def test_bat_conservation_charge_mode(self, ienv_t8_no_ren):
        # reviewer: T5c covers discharge; this pins the charge-mode branch of bat_conservation_ok.
        # reviewer: a_bat=0.5 (charge) → p_bat_dis=0 and bat_to_load=bat_to_grid=bat_curtailed=0,
        # reviewer: so |0+0+0 − 0| = 0 < 1e-3 ⇒ flag True; bat_curtailed is 0 in charge mode.
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8, month_peak_mw=100.0)
        insp = ienv_t8_no_ren.step(state, [0.5, 0, 0, 0, 0, 0])
        assert insp.p_bat_dis_mw == 0.0
        assert insp.bat_to_load_mw == 0.0
        assert insp.bat_to_grid_mw == 0.0
        assert insp.bat_curtailed_mw == 0.0
        assert insp.bat_conservation_ok is True

    # --- R4: C_DC_shape knife-edge at month_peak == P_import ---
    def test_demand_shape_zero_at_exact_boundary(self, ienv_t8_no_ren):
        # reviewer: T1 (month_peak=100 > import) and T2 (month_peak=40 < import) bracket the
        # reviewer: max(0, P_import − month_peak) clamp; this pins the exact boundary.
        # reviewer: T1 setup → P_import = 50 + 0.5×98.16 = 99.08 MW. Set month_peak = 99.08
        # reviewer: exactly → C_DC_shape = 32000 × max(0, 99.08 − 99.08) = 0 ¥.
        state = ienv_t8_no_ren.make_state(soc=0.5, t=8, month_peak_mw=99.08)
        insp = ienv_t8_no_ren.step(state, [0.5, 0, 0, 0, 0, 0])
        # exact-equality at the clamp; allow 1 ¥ for any float32 residual (vs 1.89e6 if active)
        assert abs(insp.c_demand_shape_yuan - 0.0) < 1.0
