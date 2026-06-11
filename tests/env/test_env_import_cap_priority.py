"""Tests for F-IMPORT fix: §3.6 row 9 load-first grid import priority.

Contract: contracts/env/import_cap_priority.md
Spec:     §3.6 row 9 ("Load served first, then battery charging reduced, then load shed")
Decision: D12 (grid_max_import_mw = 400 MW)

These tests target `src/reference/gansu_env.py` STEP 8.  They will FAIL on the
unfixed reference (battery-first priority) and PASS on the corrected version.

All expected values are hand-computed; arithmetic is shown in comments.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Import path — reference lives in src/reference (not installed as a package)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "src" / "reference"))

from reference.gansu_env import EnvState, env_step  # noqa: E402
from reference.gansu_params import GansuParams        # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DEFAULT_PARAMS = GansuParams()

# Nighttime, zero renewables: irr=0 → P_solar=0; wind=0 → P_wind=0
NIGHT_WEATHER = (0.0, 0.0, 25.0)  # (wind_mps, irr_wm2, temp_c)


def _state(soc: float = 0.5, month_peak: float = 0.0, t: int = 12) -> EnvState:
    """Create a minimal EnvState; t=12 to avoid month-boundary bookings."""
    return EnvState(
        soc=soc,
        month_peak_mw=month_peak,
        t=t,
        rng=np.random.default_rng(42),
    )


def _action(a_bat: float = 0.0, f_sl: float = 0.0, f_sb: float = 0.0,
            f_wl: float = 0.0, f_wb: float = 0.0, f_bl: float = 0.0) -> np.ndarray:
    return np.array([a_bat, f_sl, f_sb, f_wl, f_wb, f_bl], dtype=np.float64)


# ---------------------------------------------------------------------------
# 1. TC-1 — Discriminating case: load_deficit < max_import < load_deficit + p_g2b
# ---------------------------------------------------------------------------

class TestImportCapLoadFirst:
    """§3.6 row 9: load-first priority when cap is binding."""

    def test_tc1_load_served_bat_reduced_under_cap(self):
        """TC-1: load=350, p_g2b=98.16, max_import=400 → 350 < 400 < 448.16.

        Correct (load-first):
          grid_to_load = min(350, 400) = 350 MW
          import_headroom = 400 - 350 = 50 MW
          p_g2b_actual = min(98.16, 50) = 50 MW
          p_import = 350 + 50 = 400 MW
          load_unserved = 0 MW  → c_voll = 0 ¥

        Old wrong (battery-first):
          p_g2b_actual = 98.16 MW  (bat fully honoured)
          grid_to_load = 400 - 98.16 = 301.84 MW
          load_unserved = 350 - 301.84 = 48.16 MW
          c_voll = 20000 * 48.16 ≈ 963,200 ¥  (spurious)

        Setup: a_bat=1.0 (max grid charge), soc=0.5 → no SOC clip.
          bat_power_mw=98.16; zero renewables → p_g2b_raw = 98.16 MW.
        """
        result = env_step(
            _state(),
            _action(a_bat=1.0),
            weather=NIGHT_WEATHER,
            load=350.0,
            params=DEFAULT_PARAMS,
        )

        # Load fully served — zero VOLL
        assert result.load_unserved_mw == pytest.approx(0.0, abs=1e-3), (
            f"Load must be fully served before bat charging; "
            f"got load_unserved={result.load_unserved_mw:.3f} MW"
        )
        assert result.c_voll_yuan == pytest.approx(0.0, abs=1.0), (
            f"Zero VOLL expected; got {result.c_voll_yuan:.1f} ¥"
        )
        # Battery charging reduced to headroom remainder: 400 - 350 = 50 MW
        assert result.grid_to_bat_mw == pytest.approx(50.0, abs=1e-3), (
            f"Battery import headroom = 400 - 350 = 50 MW; "
            f"got grid_to_bat={result.grid_to_bat_mw:.3f} MW"
        )
        # Load gets full 350 MW from grid
        assert result.grid_to_load_mw == pytest.approx(350.0, abs=1e-3), (
            f"grid_to_load must be 350 MW; got {result.grid_to_load_mw:.3f} MW"
        )
        # Total import at cap
        assert result.p_import_mw == pytest.approx(400.0, abs=1e-3), (
            f"P_import = 350 + 50 = 400 MW; got {result.p_import_mw:.3f} MW"
        )

    def test_tc2_load_exactly_at_import_limit_bat_zero(self):
        """TC-2: load=400 == max_import → battery gets zero headroom.

        Correct:
          grid_to_load = min(400, 400) = 400 MW
          import_headroom = 400 - 400 = 0 MW
          p_g2b_actual = min(98.16, 0) = 0 MW
          p_import = 400 MW
          load_unserved = 0 MW
        """
        result = env_step(
            _state(),
            _action(a_bat=1.0),
            weather=NIGHT_WEATHER,
            load=400.0,
            params=DEFAULT_PARAMS,
        )
        assert result.load_unserved_mw == pytest.approx(0.0, abs=1e-3), (
            "Load at import limit: zero unserved"
        )
        assert result.grid_to_bat_mw == pytest.approx(0.0, abs=1e-3), (
            "Battery gets zero headroom when load == max_import"
        )
        assert result.grid_to_load_mw == pytest.approx(400.0, abs=1e-3)
        assert result.p_import_mw == pytest.approx(400.0, abs=1e-3)

    def test_tc3_load_exceeds_cap_shed_bat_zero(self):
        """TC-3: load=500 > max_import=400 → load shed, battery gets nothing.

        Correct:
          grid_to_load = min(500, 400) = 400 MW
          load_unserved = 500 - 400 = 100 MW
          import_headroom = 400 - 400 = 0 MW
          p_g2b_actual = 0 MW
          p_import = 400 MW
          c_voll_yuan = 20000 * 100 * 1.0 = 2,000,000 ¥
        """
        result = env_step(
            _state(),
            _action(a_bat=1.0),
            weather=NIGHT_WEATHER,
            load=500.0,
            params=DEFAULT_PARAMS,
        )
        # load_unserved = 500 - 400 = 100 MW
        assert result.load_unserved_mw == pytest.approx(100.0, abs=1e-3), (
            f"load_unserved = 500 - 400 = 100 MW; got {result.load_unserved_mw:.3f} MW"
        )
        # Battery gets zero (load already exhausts the cap)
        assert result.grid_to_bat_mw == pytest.approx(0.0, abs=1e-3), (
            "Battery gets no import when load > max_import"
        )
        assert result.p_import_mw == pytest.approx(400.0, abs=1e-3)
        # c_voll = 20000 ¥/MWh × 100 MW × 1 h = 2,000,000 ¥
        assert result.c_voll_yuan == pytest.approx(2_000_000.0, rel=1e-4), (
            f"c_voll = 20000 * 100 = 2,000,000 ¥; got {result.c_voll_yuan:.1f} ¥"
        )

    def test_tc4_no_cap_triggered(self):
        """TC-4: load=200, p_g2b=98.16, total=298.16 < max_import=400 → no cap.

        Expected: bat fully served (98.16 MW), load fully served (200 MW),
        p_import = 298.16 MW, load_unserved = 0.
        """
        result = env_step(
            _state(),
            _action(a_bat=1.0),
            weather=NIGHT_WEATHER,
            load=200.0,
            params=DEFAULT_PARAMS,
        )
        assert result.load_unserved_mw == pytest.approx(0.0, abs=1e-3)
        # bat fully served (200 + 98.16 = 298.16 < 400, no cap)
        assert result.grid_to_bat_mw == pytest.approx(98.16, abs=1e-3), (
            "No cap triggered: bat_power_mw=98.16 MW served in full"
        )
        assert result.grid_to_load_mw == pytest.approx(200.0, abs=1e-3)
        # p_import = 200 + 98.16 = 298.16 MW
        assert result.p_import_mw == pytest.approx(298.16, abs=1e-3)


# ---------------------------------------------------------------------------
# 2. Cost correctness under TC-1 scenario
# ---------------------------------------------------------------------------

class TestImportCapCostCorrectness:
    """Verify that VOLL cost is zero in TC-1 (load fully served)."""

    def test_zero_voll_when_load_served(self):
        """No spurious VOLL cost when load fits within import cap.

        Hand-derived:
          load=350, max_import=400 → load fully served → c_voll = 0
          old code: load_unserved=48.16 → c_voll = 20000*48.16 ≈ 963,200 ¥ (spurious)
        """
        result = env_step(
            _state(),
            _action(a_bat=1.0),
            weather=NIGHT_WEATHER,
            load=350.0,
            params=DEFAULT_PARAMS,
        )
        assert result.c_voll_yuan == pytest.approx(0.0, abs=1.0)

    def test_cost_total_real_excludes_spurious_voll(self):
        """cost_total_real_yuan must NOT include spurious VOLL from F-IMPORT bug.

        Under TC-1 scenario, old code adds ≈963,200 ¥ spurious VOLL to cost total.
        With fix: c_voll == 0, cost_total_real = C_E + C_demand_charge + C_deg + C_curtail.
        We verify: cost_total_real ≤ some reasonable bound (here: no runaway VOLL).
        """
        result = env_step(
            _state(),
            _action(a_bat=1.0),
            weather=NIGHT_WEATHER,
            load=350.0,
            params=DEFAULT_PARAMS,
        )
        # cost_total_real = C_E + C_DC + C_deg + C_curtail + C_VOLL
        # With fix: C_VOLL = 0, so total is just C_E + C_deg
        # C_E = price_buy * 400 MW - price_sell * 0 MW (no export in this scenario)
        # Roughly 400 * 250 (min price at t=12 is 450) = 180,000 ¥ ballpark, well < 500k
        assert result.cost_total_real_yuan < 500_000.0, (
            f"Spurious VOLL would push cost >> 500k; got {result.cost_total_real_yuan:.0f} ¥"
        )
        assert result.c_voll_yuan == pytest.approx(0.0, abs=1.0)


# ---------------------------------------------------------------------------
# 3. Identity invariants hold after fix
# ---------------------------------------------------------------------------

class TestImportCapIdentities:
    """Physical identity checks that hold regardless of whether cap is active."""

    @pytest.mark.parametrize("load_mw", [200.0, 350.0, 400.0, 500.0])
    def test_p_import_equals_grid_to_bat_plus_grid_to_load(self, load_mw):
        """p_import_mw == grid_to_bat_mw + grid_to_load_mw for all cap scenarios."""
        result = env_step(
            _state(),
            _action(a_bat=1.0),
            weather=NIGHT_WEATHER,
            load=load_mw,
            params=DEFAULT_PARAMS,
        )
        assert result.p_import_mw == pytest.approx(
            result.grid_to_bat_mw + result.grid_to_load_mw, abs=1e-6
        )

    @pytest.mark.parametrize("load_mw", [200.0, 350.0, 400.0, 500.0])
    def test_p_import_never_exceeds_max(self, load_mw):
        """p_import_mw ≤ grid_max_import_mw = 400 MW always."""
        result = env_step(
            _state(),
            _action(a_bat=1.0),
            weather=NIGHT_WEATHER,
            load=load_mw,
            params=DEFAULT_PARAMS,
        )
        assert result.p_import_mw <= DEFAULT_PARAMS.grid_max_import_mw + 1e-6, (
            f"Import exceeded cap: {result.p_import_mw:.3f} > {DEFAULT_PARAMS.grid_max_import_mw} MW"
        )

    @pytest.mark.parametrize("load_mw", [200.0, 350.0, 400.0, 500.0])
    def test_load_unserved_non_negative(self, load_mw):
        """load_unserved_mw ≥ 0 for all scenarios (floating-point guard)."""
        result = env_step(
            _state(),
            _action(a_bat=1.0),
            weather=NIGHT_WEATHER,
            load=load_mw,
            params=DEFAULT_PARAMS,
        )
        assert result.load_unserved_mw >= -1e-9, (
            f"load_unserved must be ≥ 0; got {result.load_unserved_mw:.6f} MW"
        )
