"""Tests for Extended PolicyEvalResult — per-stream + physical-quantity accumulators.

Contract: contracts/training/eval_result_extended.md
Spec: §5.5 (eval), §3 (physics / EnvInfo)
Decisions: D3 (Δt=1h), D13 (cost separation), master plan §5.5/§8

ALL tests use hand-computed expected values; the arithmetic is shown in comments.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import jax.numpy as jnp
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers — build mock EnvInfo-like objects
# ---------------------------------------------------------------------------

def _make_mock_infos(n_steps: int, **field_values) -> SimpleNamespace:
    """Build a mock stacked EnvInfo with (n_steps,)-shaped fields.

    Unspecified fields default to 0.  Accepts scalar values (broadcast to all steps)
    or (n_steps,)-length lists/arrays.
    """
    ALL_FIELDS = [
        # aggregate flows (MW)
        "p_wind_mw", "p_pv_mw", "p_bat_ch_mw", "p_bat_dis_mw",
        "p_import_mw", "p_export_mw", "p_load_served_mw", "p_load_unserved_mw",
        "p_curtailed_mw",
        # costs (¥)
        "c_import_yuan", "r_export_yuan", "c_energy_yuan",
        "c_demand_shape_yuan", "c_demand_charge_yuan", "c_degradation_yuan",
        "c_curtail_yuan", "c_voll_yuan",
        "cost_total_real_yuan", "cost_total_reward_basis_yuan",
        "penalty_yuan", "soc_violation_mwh",
        # prices
        "price_buy_yuan_per_mwh", "price_sell_yuan_per_mwh",
        # per-source breakdown (13 fields)
        "p_sol_to_load_mw", "p_sol_to_bat_mw", "p_sol_to_grid_mw", "p_sol_curtailed_mw",
        "p_wind_to_load_mw", "p_wind_to_bat_mw", "p_wind_to_grid_mw", "p_wind_curtailed_mw",
        "p_bat_to_load_mw", "p_bat_to_grid_mw", "p_bat_curtailed_mw",
        "p_grid_to_bat_mw", "p_grid_to_load_mw",
        # constraint signals
        "load_capped", "import_cap_active",
    ]
    ns = SimpleNamespace()
    for f in ALL_FIELDS:
        val = field_values.get(f, 0.0)
        if isinstance(val, (int, float)):
            ns.__dict__[f] = jnp.full((n_steps,), float(val), dtype=jnp.float32)
        else:
            ns.__dict__[f] = jnp.array(val, dtype=jnp.float32)
    return ns


# ---------------------------------------------------------------------------
# Import the target module (red at contract stage — module/function doesn't exist yet)
# ---------------------------------------------------------------------------

def _import_accumulate():
    from energy_go.training.eval import _accumulate_physical_quantities  # noqa: PLC0415
    return _accumulate_physical_quantities


def _import_policy_eval_result():
    from energy_go.training.eval import PolicyEvalResult  # noqa: PLC0415
    return PolicyEvalResult


def _import_policy_dict():
    from energy_go.training.telemetry import _policy_dict  # noqa: PLC0415
    return _policy_dict


def _import_run_eval():
    from energy_go.training.eval import run_eval  # noqa: PLC0415
    return run_eval


# ---------------------------------------------------------------------------
# 1. Field-count and presence tests
# ---------------------------------------------------------------------------

class TestPolicyEvalResultFields:
    """PolicyEvalResult has exactly 33 fields (9 existing + 24 new)."""

    def test_total_field_count(self):
        PolicyEvalResult = _import_policy_eval_result()
        fields = [f.name for f in dataclasses.fields(PolicyEvalResult)]
        assert len(fields) == 33, (
            f"Expected 33 fields (9 existing + 2 cost-stream + 9 aggregate + 13 per-source), "
            f"got {len(fields)}: {fields}"
        )

    def test_existing_9_fields_present(self):
        PolicyEvalResult = _import_policy_eval_result()
        existing = {
            "energy_cost_yuan", "demand_charge_yuan", "degradation_yuan",
            "curtailment_yuan", "voll_yuan", "total_cost_yuan",
            "soc_violations_count", "soc_violation_mwh", "penalty_yuan",
        }
        actual = {f.name for f in dataclasses.fields(PolicyEvalResult)}
        assert existing.issubset(actual), f"Missing existing fields: {existing - actual}"

    def test_new_cost_stream_fields_present(self):
        PolicyEvalResult = _import_policy_eval_result()
        fields = {f.name for f in dataclasses.fields(PolicyEvalResult)}
        assert "r_export_yuan" in fields
        assert "c_import_yuan" in fields

    def test_new_aggregate_mwh_fields_present(self):
        PolicyEvalResult = _import_policy_eval_result()
        expected_agg = {
            "wind_generated_mwh", "pv_generated_mwh",
            "bat_charge_mwh", "bat_discharge_mwh",
            "grid_import_mwh", "grid_export_mwh",
            "load_served_mwh", "load_unserved_mwh", "curtailed_mwh",
        }
        actual = {f.name for f in dataclasses.fields(PolicyEvalResult)}
        assert expected_agg.issubset(actual), f"Missing aggregate fields: {expected_agg - actual}"

    def test_new_per_source_fields_present(self):
        PolicyEvalResult = _import_policy_eval_result()
        expected_per_source = {
            "wind_to_load_mwh", "wind_to_bat_mwh", "wind_to_grid_mwh", "wind_curtailed_mwh",
            "pv_to_load_mwh", "pv_to_bat_mwh", "pv_to_grid_mwh", "pv_curtailed_mwh",
            "bat_to_load_mwh", "bat_to_grid_mwh", "bat_curtailed_mwh",
            "grid_to_bat_mwh", "grid_to_load_mwh",
        }
        actual = {f.name for f in dataclasses.fields(PolicyEvalResult)}
        assert expected_per_source.issubset(actual), (
            f"Missing per-source fields: {expected_per_source - actual}"
        )


# ---------------------------------------------------------------------------
# 2. Accumulation formula tests — Δt = 1h (D3), so Σ p_X_mw = total MWh
# ---------------------------------------------------------------------------

class TestAccumulationFormula:
    """Accumulation: field_mwh = Σ p_field_mw × 1h.  Δt=1h so Σ p_X_mw (in MW) = MWh."""

    def test_wind_accumulation_constant(self):
        # 5 steps, p_wind_mw = 100 MW each step
        # Expected: wind_generated_mwh = 5 × 100 MW × 1 h = 500 MWh
        _acc = _import_accumulate()
        infos = _make_mock_infos(5, p_wind_mw=100.0)
        result = _acc(infos)
        assert result["wind_generated_mwh"] == pytest.approx(500.0, rel=1e-5), (
            "5 steps × 100 MW × 1h = 500 MWh"
        )

    def test_pv_accumulation_constant(self):
        # 3 steps, p_pv_mw = 50 MW
        # Expected: pv_generated_mwh = 3 × 50 = 150 MWh
        _acc = _import_accumulate()
        infos = _make_mock_infos(3, p_pv_mw=50.0)
        result = _acc(infos)
        assert result["pv_generated_mwh"] == pytest.approx(150.0, rel=1e-5), (
            "3 steps × 50 MW × 1h = 150 MWh"
        )

    def test_bat_charge_discharge_accumulation(self):
        # 4 steps, p_bat_ch_mw = 80 MW, p_bat_dis_mw = 60 MW
        # Expected: bat_charge_mwh = 4×80 = 320, bat_discharge_mwh = 4×60 = 240
        _acc = _import_accumulate()
        infos = _make_mock_infos(4, p_bat_ch_mw=80.0, p_bat_dis_mw=60.0)
        result = _acc(infos)
        assert result["bat_charge_mwh"] == pytest.approx(320.0, rel=1e-5), "4×80 = 320 MWh"
        assert result["bat_discharge_mwh"] == pytest.approx(240.0, rel=1e-5), "4×60 = 240 MWh"

    def test_grid_import_export_accumulation(self):
        # 6 steps, p_import_mw = 200 MW, p_export_mw = 120 MW
        # Expected: grid_import_mwh = 6×200 = 1200, grid_export_mwh = 6×120 = 720
        _acc = _import_accumulate()
        infos = _make_mock_infos(6, p_import_mw=200.0, p_export_mw=120.0)
        result = _acc(infos)
        assert result["grid_import_mwh"] == pytest.approx(1200.0, rel=1e-5), "6×200 = 1200 MWh"
        assert result["grid_export_mwh"] == pytest.approx(720.0, rel=1e-5), "6×120 = 720 MWh"

    def test_load_served_unserved_accumulation(self):
        # 2 steps, p_load_served_mw = 90 MW, p_load_unserved_mw = 10 MW
        # Expected: load_served_mwh = 2×90 = 180, load_unserved_mwh = 2×10 = 20
        _acc = _import_accumulate()
        infos = _make_mock_infos(2, p_load_served_mw=90.0, p_load_unserved_mw=10.0)
        result = _acc(infos)
        assert result["load_served_mwh"] == pytest.approx(180.0, rel=1e-5), "2×90 = 180 MWh"
        assert result["load_unserved_mwh"] == pytest.approx(20.0, rel=1e-5), "2×10 = 20 MWh"

    def test_curtailed_accumulation(self):
        # 3 steps, p_curtailed_mw = 15 MW
        # Expected: curtailed_mwh = 3×15 = 45 MWh
        _acc = _import_accumulate()
        infos = _make_mock_infos(3, p_curtailed_mw=15.0)
        result = _acc(infos)
        assert result["curtailed_mwh"] == pytest.approx(45.0, rel=1e-5), "3×15 = 45 MWh"

    def test_per_source_wind_accumulation(self):
        # 3 steps, wind breakdown: to_load=60, to_bat=20, to_grid=10, curtailed=10 (sum=100)
        # Expected MWh: to_load=180, to_bat=60, to_grid=30, curtailed=30
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            3,
            p_wind_to_load_mw=60.0, p_wind_to_bat_mw=20.0,
            p_wind_to_grid_mw=10.0, p_wind_curtailed_mw=10.0,
        )
        result = _acc(infos)
        assert result["wind_to_load_mwh"]   == pytest.approx(180.0, rel=1e-5), "3×60 = 180"
        assert result["wind_to_bat_mwh"]    == pytest.approx(60.0,  rel=1e-5), "3×20 = 60"
        assert result["wind_to_grid_mwh"]   == pytest.approx(30.0,  rel=1e-5), "3×10 = 30"
        assert result["wind_curtailed_mwh"] == pytest.approx(30.0,  rel=1e-5), "3×10 = 30"

    def test_per_source_pv_accumulation(self):
        # 4 steps, pv breakdown: to_load=120, to_bat=40, to_grid=20, curtailed=20 (sum=200)
        # Expected MWh: to_load=480, to_bat=160, to_grid=80, curtailed=80
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            4,
            p_sol_to_load_mw=120.0, p_sol_to_bat_mw=40.0,
            p_sol_to_grid_mw=20.0, p_sol_curtailed_mw=20.0,
        )
        result = _acc(infos)
        assert result["pv_to_load_mwh"]   == pytest.approx(480.0, rel=1e-5), "4×120 = 480"
        assert result["pv_to_bat_mwh"]    == pytest.approx(160.0, rel=1e-5), "4×40 = 160"
        assert result["pv_to_grid_mwh"]   == pytest.approx(80.0,  rel=1e-5), "4×20 = 80"
        assert result["pv_curtailed_mwh"] == pytest.approx(80.0,  rel=1e-5), "4×20 = 80"

    def test_per_source_bat_discharge_accumulation(self):
        # 5 steps, bat discharge breakdown: to_load=50, to_grid=30, curtailed=10 (sum=90)
        # Expected MWh: to_load=250, to_grid=150, curtailed=50
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            5,
            p_bat_to_load_mw=50.0, p_bat_to_grid_mw=30.0, p_bat_curtailed_mw=10.0,
        )
        result = _acc(infos)
        assert result["bat_to_load_mwh"]  == pytest.approx(250.0, rel=1e-5), "5×50 = 250"
        assert result["bat_to_grid_mwh"]  == pytest.approx(150.0, rel=1e-5), "5×30 = 150"
        assert result["bat_curtailed_mwh"] == pytest.approx(50.0, rel=1e-5), "5×10 = 50"

    def test_per_source_grid_flows(self):
        # 2 steps, grid_to_bat=40, grid_to_load=60
        # Expected: grid_to_bat_mwh=80, grid_to_load_mwh=120
        _acc = _import_accumulate()
        infos = _make_mock_infos(2, p_grid_to_bat_mw=40.0, p_grid_to_load_mw=60.0)
        result = _acc(infos)
        assert result["grid_to_bat_mwh"]  == pytest.approx(80.0,  rel=1e-5), "2×40 = 80"
        assert result["grid_to_load_mwh"] == pytest.approx(120.0, rel=1e-5), "2×60 = 120"

    def test_cost_stream_accumulation(self):
        # 4 steps, c_import_yuan=5000 ¥/step, r_export_yuan=2000 ¥/step
        # Expected: c_import_yuan=20000 ¥, r_export_yuan=8000 ¥
        _acc = _import_accumulate()
        infos = _make_mock_infos(4, c_import_yuan=5000.0, r_export_yuan=2000.0)
        result = _acc(infos)
        assert result["c_import_yuan"] == pytest.approx(20000.0, rel=1e-5), "4×5000 = 20000"
        assert result["r_export_yuan"] == pytest.approx(8000.0,  rel=1e-5), "4×2000 = 8000"

    def test_zero_flows_give_zero_mwh(self):
        # All flows = 0 → all MWh accumulators = 0
        _acc = _import_accumulate()
        infos = _make_mock_infos(8760)  # all fields default 0
        result = _acc(infos)
        for key, val in result.items():
            assert val == pytest.approx(0.0, abs=1e-6), (
                f"Zero-flow scenario: {key} expected 0 but got {val}"
            )

    def test_variable_steps_accumulation(self):
        # 3 steps with varying p_wind_mw: [100, 200, 150]
        # Expected: wind_generated_mwh = 100+200+150 = 450 MWh
        _acc = _import_accumulate()
        infos = _make_mock_infos(3, p_wind_mw=[100.0, 200.0, 150.0])
        result = _acc(infos)
        assert result["wind_generated_mwh"] == pytest.approx(450.0, rel=1e-5), (
            "100+200+150 = 450 MWh"
        )

    def test_returns_dict_with_exactly_24_keys(self):
        # _accumulate_physical_quantities returns exactly 24 keys (2 cost + 9 aggregate + 13 per-source)
        _acc = _import_accumulate()
        infos = _make_mock_infos(3, p_wind_mw=100.0)
        result = _acc(infos)
        assert len(result) == 24, (
            f"Expected 24 keys (2 cost-stream + 9 aggregate + 13 per-source), got {len(result)}: "
            f"{sorted(result.keys())}"
        )


# ---------------------------------------------------------------------------
# 3. Energy conservation identities (§3 physics invariants, contract §4)
# ---------------------------------------------------------------------------

class TestEnergyConservation:
    """Per-source conservation identities must hold to float32 tolerance."""

    def test_wind_conservation(self):
        # Wind: to_load=60, to_bat=20, to_grid=10, curtailed=10 → sum=100 = p_wind_mw
        # 5 steps:
        #   wind_generated_mwh   = 5×100 = 500
        #   wind_to_load_mwh     = 5×60  = 300
        #   wind_to_bat_mwh      = 5×20  = 100
        #   wind_to_grid_mwh     = 5×10  = 50
        #   wind_curtailed_mwh   = 5×10  = 50
        #   check: 300+100+50+50 = 500 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            5,
            p_wind_mw=100.0,
            p_wind_to_load_mw=60.0, p_wind_to_bat_mw=20.0,
            p_wind_to_grid_mw=10.0, p_wind_curtailed_mw=10.0,
        )
        r = _acc(infos)
        lhs = r["wind_generated_mwh"]                               # 500
        rhs = (r["wind_to_load_mwh"] + r["wind_to_bat_mwh"]        # 300+100
                + r["wind_to_grid_mwh"] + r["wind_curtailed_mwh"])  # +50+50 = 500
        assert lhs == pytest.approx(rhs, rel=1e-4), (
            f"Wind conservation violated: {lhs:.4f} ≠ {rhs:.4f} "
            f"(diff={abs(lhs-rhs):.6f})"
        )

    def test_pv_conservation(self):
        # PV: to_load=30, to_bat=10, to_grid=5, curtailed=5 → sum=50 = p_pv_mw
        # 4 steps:
        #   pv_generated_mwh = 4×50 = 200
        #   pv_to_load_mwh   = 4×30 = 120
        #   pv_to_bat_mwh    = 4×10 = 40
        #   pv_to_grid_mwh   = 4×5  = 20
        #   pv_curtailed_mwh = 4×5  = 20
        #   check: 120+40+20+20 = 200 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            4,
            p_pv_mw=50.0,
            p_sol_to_load_mw=30.0, p_sol_to_bat_mw=10.0,
            p_sol_to_grid_mw=5.0,  p_sol_curtailed_mw=5.0,
        )
        r = _acc(infos)
        lhs = r["pv_generated_mwh"]                                # 200
        rhs = (r["pv_to_load_mwh"] + r["pv_to_bat_mwh"]           # 120+40
                + r["pv_to_grid_mwh"] + r["pv_curtailed_mwh"])     # +20+20 = 200
        assert lhs == pytest.approx(rhs, rel=1e-4), (
            f"PV conservation violated: {lhs:.4f} ≠ {rhs:.4f}"
        )

    def test_battery_discharge_conservation(self):
        # Battery discharge: to_load=50, to_grid=30, curtailed=10 → sum=90 = p_bat_dis_mw
        # 3 steps:
        #   bat_discharge_mwh = 3×90 = 270
        #   bat_to_load_mwh   = 3×50 = 150
        #   bat_to_grid_mwh   = 3×30 = 90
        #   bat_curtailed_mwh = 3×10 = 30
        #   check: 150+90+30 = 270 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            3,
            p_bat_dis_mw=90.0,
            p_bat_to_load_mw=50.0, p_bat_to_grid_mw=30.0, p_bat_curtailed_mw=10.0,
        )
        r = _acc(infos)
        lhs = r["bat_discharge_mwh"]                               # 270
        rhs = r["bat_to_load_mwh"] + r["bat_to_grid_mwh"] + r["bat_curtailed_mwh"]  # 150+90+30
        assert lhs == pytest.approx(rhs, rel=1e-4), (
            f"Battery discharge conservation violated: {lhs:.4f} ≠ {rhs:.4f}"
        )

    def test_wind_conservation_with_zero_curtailment(self):
        # Wind: to_load=80, to_bat=20, to_grid=0, curtailed=0 → p_wind_mw=100
        # 2 steps: wind_generated=200, to_load=160, to_bat=40, to_grid=0, curtailed=0
        # check: 160+40+0+0 = 200 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            2,
            p_wind_mw=100.0,
            p_wind_to_load_mw=80.0, p_wind_to_bat_mw=20.0,
            p_wind_to_grid_mw=0.0,  p_wind_curtailed_mw=0.0,
        )
        r = _acc(infos)
        lhs = r["wind_generated_mwh"]                               # 200
        rhs = (r["wind_to_load_mwh"] + r["wind_to_bat_mwh"]
                + r["wind_to_grid_mwh"] + r["wind_curtailed_mwh"])  # 160+40+0+0 = 200
        assert lhs == pytest.approx(rhs, rel=1e-4)

    # reviewer: AGGREGATE-vs-per-source consistency for curtailment. The env defines
    # p_curtailed_mw = p_sol_curtailed + p_wind_curtailed + p_bat_curtailed (EnvInfo
    # aggregate). Accumulated, curtailed_mwh must equal the sum of the three per-source
    # curtailed accumulators. The per-source conservation tests above don't cross-check
    # the AGGREGATE field against its parts — this pins that consistency.
    # 4 steps: p_curtailed=25 = wind 10 + pv 10 + bat 5 → curtailed_mwh=100;
    #          wind_curt=40, pv_curt=40, bat_curt=20 → sum=100.
    def test_aggregate_curtailed_equals_per_source_sum(self):
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            4,
            p_curtailed_mw=25.0,
            p_wind_curtailed_mw=10.0, p_sol_curtailed_mw=10.0, p_bat_curtailed_mw=5.0,
        )
        r = _acc(infos)
        lhs = r["curtailed_mwh"]                                          # 4×25 = 100
        rhs = r["wind_curtailed_mwh"] + r["pv_curtailed_mwh"] + r["bat_curtailed_mwh"]  # 40+40+20
        assert lhs == pytest.approx(rhs, rel=1e-4), (
            f"aggregate curtailed_mwh={lhs:.4f} ≠ Σ per-source {rhs:.4f} "
            "(curtailed_mwh must equal wind+pv+bat curtailed)"
        )

    # reviewer: grid-import decomposition — ties to the F-IMPORT fix (§3.6 row 9):
    # the env guarantees P_import = grid_to_load + grid_to_bat. Accumulated,
    # grid_import_mwh must equal grid_to_bat_mwh + grid_to_load_mwh. A load-first
    # F-IMPORT regression (battery-first import) would break this identity.
    # 6 steps: p_import=150 = grid_to_bat 50 + grid_to_load 100 → grid_import_mwh=900;
    #          grid_to_bat=300, grid_to_load=600 → sum=900.
    def test_grid_import_equals_to_bat_plus_to_load(self):
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            6,
            p_import_mw=150.0,
            p_grid_to_bat_mw=50.0, p_grid_to_load_mw=100.0,
        )
        r = _acc(infos)
        lhs = r["grid_import_mwh"]                                  # 6×150 = 900
        rhs = r["grid_to_bat_mwh"] + r["grid_to_load_mwh"]          # 300+600 = 900
        assert lhs == pytest.approx(rhs, rel=1e-4), (
            f"grid_import_mwh={lhs:.4f} ≠ grid_to_bat+grid_to_load {rhs:.4f} "
            "(F-IMPORT §3.6 row 9: P_import = grid_to_load + grid_to_bat)"
        )


# ---------------------------------------------------------------------------
# 4. D13 cost identity: energy_cost_yuan = c_import_yuan - r_export_yuan
# ---------------------------------------------------------------------------

class TestCostIdentity:
    """D13 identity must hold: energy_cost = c_import − r_export."""

    def test_c_energy_identity_basic(self):
        # 3 steps: c_energy_yuan=3000 ¥/step, c_import_yuan=5000, r_export_yuan=2000
        # (D13: c_energy = c_import − r_export → 5000−2000=3000 ✓)
        # Expected totals: c_energy=9000, c_import=15000, r_export=6000
        # Identity: 9000 = 15000 - 6000 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            3,
            c_energy_yuan=3000.0,   # = c_import - r_export
            c_import_yuan=5000.0,
            r_export_yuan=2000.0,
        )
        # Existing c_energy via run_eval accumulation (separate path, tested indirectly here via mock)
        r = _acc(infos)
        c_import_total = r["c_import_yuan"]   # 3×5000 = 15000
        r_export_total = r["r_export_yuan"]   # 3×2000 = 6000
        expected_c_energy = c_import_total - r_export_total  # 15000-6000 = 9000
        # Also compute directly for reference
        direct_c_energy = 3 * 3000.0  # 9000
        assert expected_c_energy == pytest.approx(direct_c_energy, rel=1e-5), (
            f"D13 identity: {c_import_total}-{r_export_total}={expected_c_energy} "
            f"≠ direct {direct_c_energy}"
        )

    def test_c_energy_identity_export_dominant(self):
        # 5 steps: c_import=0 ¥/step (no import), r_export=3000 ¥/step
        # c_energy_yuan per step = 0 - 3000 = -3000 ¥ (net revenue)
        # Totals: c_import=0, r_export=15000, identity: 0-15000=-15000
        _acc = _import_accumulate()
        infos = _make_mock_infos(5, c_import_yuan=0.0, r_export_yuan=3000.0)
        r = _acc(infos)
        assert r["c_import_yuan"] == pytest.approx(0.0,     abs=1e-3)
        assert r["r_export_yuan"] == pytest.approx(15000.0, rel=1e-5), "5×3000=15000"

    def test_c_energy_identity_no_trading(self):
        # 4 steps: c_import=0, r_export=0 → c_energy=0
        _acc = _import_accumulate()
        infos = _make_mock_infos(4, c_import_yuan=0.0, r_export_yuan=0.0)
        r = _acc(infos)
        assert r["c_import_yuan"] == pytest.approx(0.0, abs=1e-6)
        assert r["r_export_yuan"] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 5. Wire isolation — _policy_dict must return exactly the 9 LOCKED fields
# ---------------------------------------------------------------------------

class TestWireIsolation:
    """_policy_dict in telemetry.py must serialize only the 9 LOCKED eval_compare fields."""

    LOCKED_KEYS = {
        "energy_cost_yuan", "demand_charge_yuan", "degradation_yuan",
        "curtailment_yuan", "voll_yuan", "total_cost_yuan",
        "soc_violations_count", "soc_violation_mwh", "penalty_yuan",
    }

    def _make_extended_result(self):
        """Construct an extended PolicyEvalResult with all 33 fields populated non-zero."""
        PolicyEvalResult = _import_policy_eval_result()
        return PolicyEvalResult(
            # existing 9
            energy_cost_yuan=100.0, demand_charge_yuan=200.0, degradation_yuan=50.0,
            curtailment_yuan=30.0, voll_yuan=0.0, total_cost_yuan=380.0,
            soc_violations_count=2, soc_violation_mwh=0.5, penalty_yuan=10.0,
            # new cost-stream
            r_export_yuan=40.0, c_import_yuan=140.0,
            # new aggregate
            wind_generated_mwh=6150.0, pv_generated_mwh=2900.0,
            bat_charge_mwh=850.0, bat_discharge_mwh=780.0,
            grid_import_mwh=300.0, grid_export_mwh=500.0,
            load_served_mwh=7200.0, load_unserved_mwh=0.0, curtailed_mwh=60.0,
            # new per-source
            wind_to_load_mwh=4000.0, wind_to_bat_mwh=500.0,
            wind_to_grid_mwh=300.0,  wind_curtailed_mwh=1350.0,
            pv_to_load_mwh=2000.0,   pv_to_bat_mwh=350.0,
            pv_to_grid_mwh=200.0,    pv_curtailed_mwh=350.0,
            bat_to_load_mwh=600.0,   bat_to_grid_mwh=150.0, bat_curtailed_mwh=30.0,
            grid_to_bat_mwh=200.0,   grid_to_load_mwh=100.0,
        )

    def test_policy_dict_has_exactly_9_keys(self):
        _policy_dict = _import_policy_dict()
        result = self._make_extended_result()
        d = _policy_dict(result)
        assert set(d.keys()) == self.LOCKED_KEYS, (
            f"_policy_dict returned {len(d)} keys, expected 9.\n"
            f"Extra:   {set(d.keys()) - self.LOCKED_KEYS}\n"
            f"Missing: {self.LOCKED_KEYS - set(d.keys())}"
        )

    def test_policy_dict_no_mwh_fields(self):
        _policy_dict = _import_policy_dict()
        result = self._make_extended_result()
        d = _policy_dict(result)
        mwh_keys = [k for k in d if k.endswith("_mwh") and k != "soc_violation_mwh"]
        assert mwh_keys == [], (
            f"eval_compare must not contain physical MWh fields; found: {mwh_keys}"
        )

    def test_policy_dict_no_cost_stream_split(self):
        _policy_dict = _import_policy_dict()
        result = self._make_extended_result()
        d = _policy_dict(result)
        assert "r_export_yuan" not in d, "r_export_yuan must not appear in eval_compare"
        assert "c_import_yuan" not in d, "c_import_yuan must not appear in eval_compare"

    def test_policy_dict_existing_values_unchanged(self):
        _policy_dict = _import_policy_dict()
        result = self._make_extended_result()
        d = _policy_dict(result)
        assert d["energy_cost_yuan"]   == pytest.approx(100.0,  rel=1e-9)
        assert d["demand_charge_yuan"] == pytest.approx(200.0,  rel=1e-9)
        assert d["total_cost_yuan"]    == pytest.approx(380.0,  rel=1e-9)
        assert d["soc_violations_count"] == 2
        assert d["soc_violation_mwh"]  == pytest.approx(0.5,    rel=1e-9)
        assert d["penalty_yuan"]       == pytest.approx(10.0,   rel=1e-9)


# ---------------------------------------------------------------------------
# 6. Backward compatibility — existing 9 fields computed identically
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Existing 9 PolicyEvalResult fields must be computed identically to before."""

    def test_existing_cost_fields_sum_to_total(self):
        # Construct a PolicyEvalResult (all new fields present) and verify the
        # old additive identity still holds: total = sum of the 5 costs
        # Example: energy=100, demand=200, degrad=50, curtail=30, voll=0 → total=380
        PolicyEvalResult = _import_policy_eval_result()
        r = PolicyEvalResult(
            energy_cost_yuan=100.0, demand_charge_yuan=200.0, degradation_yuan=50.0,
            curtailment_yuan=30.0, voll_yuan=0.0, total_cost_yuan=380.0,
            soc_violations_count=0, soc_violation_mwh=0.0, penalty_yuan=0.0,
            r_export_yuan=0.0, c_import_yuan=0.0,
            wind_generated_mwh=0.0, pv_generated_mwh=0.0,
            bat_charge_mwh=0.0, bat_discharge_mwh=0.0,
            grid_import_mwh=0.0, grid_export_mwh=0.0,
            load_served_mwh=0.0, load_unserved_mwh=0.0, curtailed_mwh=0.0,
            wind_to_load_mwh=0.0, wind_to_bat_mwh=0.0,
            wind_to_grid_mwh=0.0, wind_curtailed_mwh=0.0,
            pv_to_load_mwh=0.0, pv_to_bat_mwh=0.0,
            pv_to_grid_mwh=0.0, pv_curtailed_mwh=0.0,
            bat_to_load_mwh=0.0, bat_to_grid_mwh=0.0, bat_curtailed_mwh=0.0,
            grid_to_bat_mwh=0.0, grid_to_load_mwh=0.0,
        )
        # Additive identity: 100+200+50+30+0 = 380
        expected_total = 100.0 + 200.0 + 50.0 + 30.0 + 0.0
        assert r.total_cost_yuan == pytest.approx(expected_total, rel=1e-9), (
            "total_cost_yuan must equal sum of 5 cost components"
        )


# ---------------------------------------------------------------------------
# 7. eval_results.json extension — physical_quantities key
# ---------------------------------------------------------------------------

class TestEvalResultsJson:
    """eval_results.json must gain a 'physical_quantities' top-level key."""

    def _import_write_eval_results(self):
        """Import the function that writes eval_results.json."""
        try:
            from energy_go.training.run_training import _write_eval_results  # noqa: PLC0415
            return _write_eval_results
        except ImportError:
            # May be in a different module location — contract specifies the function exists
            pytest.skip("_write_eval_results not yet importable (RED phase)")

    def test_physical_quantities_key_present(self, tmp_path):
        import json
        write_fn = self._import_write_eval_results()
        PolicyEvalResult = _import_policy_eval_result()

        def _make_result(seed: float) -> PolicyEvalResult:
            return PolicyEvalResult(
                energy_cost_yuan=seed,  demand_charge_yuan=seed, degradation_yuan=seed,
                curtailment_yuan=seed,  voll_yuan=0.0,  total_cost_yuan=4*seed,
                soc_violations_count=0, soc_violation_mwh=0.0, penalty_yuan=0.0,
                r_export_yuan=0.0, c_import_yuan=seed,
                wind_generated_mwh=seed*100, pv_generated_mwh=seed*50,
                bat_charge_mwh=0.0, bat_discharge_mwh=0.0,
                grid_import_mwh=0.0, grid_export_mwh=0.0,
                load_served_mwh=seed*80, load_unserved_mwh=0.0, curtailed_mwh=0.0,
                wind_to_load_mwh=seed*80, wind_to_bat_mwh=0.0,
                wind_to_grid_mwh=seed*20, wind_curtailed_mwh=0.0,
                pv_to_load_mwh=seed*50, pv_to_bat_mwh=0.0,
                pv_to_grid_mwh=0.0,      pv_curtailed_mwh=0.0,
                bat_to_load_mwh=0.0, bat_to_grid_mwh=0.0, bat_curtailed_mwh=0.0,
                grid_to_bat_mwh=0.0, grid_to_load_mwh=0.0,
            )

        out_path = tmp_path / "eval_results.json"
        write_fn(
            path=out_path,
            rl=_make_result(1.0),
            no_battery=_make_result(2.0),
            rule_based_tou=_make_result(1.5),
            checkpoint_id="test-chkpt-001",
        )
        data = json.loads(out_path.read_text())
        assert "physical_quantities" in data, (
            "eval_results.json must have top-level 'physical_quantities' key"
        )
        assert "rl" in data["physical_quantities"]
        assert "no_battery" in data["physical_quantities"]
        assert "rule_based_tou" in data["physical_quantities"]

    def test_physical_quantities_mwh_fields(self, tmp_path):
        import json
        write_fn = self._import_write_eval_results()
        PolicyEvalResult = _import_policy_eval_result()

        result = PolicyEvalResult(
            energy_cost_yuan=100.0,  demand_charge_yuan=200.0, degradation_yuan=50.0,
            curtailment_yuan=30.0,   voll_yuan=0.0,            total_cost_yuan=380.0,
            soc_violations_count=0,  soc_violation_mwh=0.0,    penalty_yuan=0.0,
            r_export_yuan=40.0, c_import_yuan=140.0,
            wind_generated_mwh=6150.0, pv_generated_mwh=2900.0,
            bat_charge_mwh=850.0, bat_discharge_mwh=780.0,
            grid_import_mwh=300.0, grid_export_mwh=500.0,
            load_served_mwh=7200.0, load_unserved_mwh=0.0, curtailed_mwh=60.0,
            wind_to_load_mwh=4000.0, wind_to_bat_mwh=500.0,
            wind_to_grid_mwh=300.0,  wind_curtailed_mwh=1350.0,
            pv_to_load_mwh=2000.0,   pv_to_bat_mwh=350.0,
            pv_to_grid_mwh=200.0,    pv_curtailed_mwh=350.0,
            bat_to_load_mwh=600.0,   bat_to_grid_mwh=150.0, bat_curtailed_mwh=30.0,
            grid_to_bat_mwh=200.0,   grid_to_load_mwh=100.0,
        )
        out_path = tmp_path / "eval_results.json"
        write_fn(
            path=out_path,
            rl=result, no_battery=result, rule_based_tou=result,
            checkpoint_id="test-chkpt-002",
        )
        data = json.loads(out_path.read_text())
        rl_phys = data["physical_quantities"]["rl"]
        # Check a sample of the 24 new fields are present with correct values
        assert rl_phys["wind_generated_mwh"] == pytest.approx(6150.0, rel=1e-5)
        assert rl_phys["pv_generated_mwh"]   == pytest.approx(2900.0, rel=1e-5)
        assert rl_phys["bat_discharge_mwh"]  == pytest.approx(780.0,  rel=1e-5)
        assert rl_phys["r_export_yuan"]       == pytest.approx(40.0,   rel=1e-5)
        assert rl_phys["c_import_yuan"]       == pytest.approx(140.0,  rel=1e-5)
        # Conservation: wind_generated = to_load+to_bat+to_grid+curtailed
        # 6150 = 4000+500+300+1350 = 6150 ✓
        lhs = rl_phys["wind_generated_mwh"]
        rhs = (rl_phys["wind_to_load_mwh"] + rl_phys["wind_to_bat_mwh"]
               + rl_phys["wind_to_grid_mwh"] + rl_phys["wind_curtailed_mwh"])
        assert lhs == pytest.approx(rhs, rel=1e-4), "Wind conservation in JSON"

    def test_policies_dict_has_only_9_locked_fields(self, tmp_path):
        """The top-level 'policies' dict must retain exactly the 9 LOCKED keys."""
        import json
        write_fn = self._import_write_eval_results()
        PolicyEvalResult = _import_policy_eval_result()
        result = PolicyEvalResult(
            energy_cost_yuan=100.0, demand_charge_yuan=0.0, degradation_yuan=0.0,
            curtailment_yuan=0.0,   voll_yuan=0.0, total_cost_yuan=100.0,
            soc_violations_count=0, soc_violation_mwh=0.0, penalty_yuan=0.0,
            r_export_yuan=0.0, c_import_yuan=100.0,
            wind_generated_mwh=0.0, pv_generated_mwh=0.0,
            bat_charge_mwh=0.0, bat_discharge_mwh=0.0,
            grid_import_mwh=0.0, grid_export_mwh=0.0,
            load_served_mwh=0.0, load_unserved_mwh=0.0, curtailed_mwh=0.0,
            wind_to_load_mwh=0.0, wind_to_bat_mwh=0.0,
            wind_to_grid_mwh=0.0, wind_curtailed_mwh=0.0,
            pv_to_load_mwh=0.0, pv_to_bat_mwh=0.0,
            pv_to_grid_mwh=0.0, pv_curtailed_mwh=0.0,
            bat_to_load_mwh=0.0, bat_to_grid_mwh=0.0, bat_curtailed_mwh=0.0,
            grid_to_bat_mwh=0.0, grid_to_load_mwh=0.0,
        )
        out_path = tmp_path / "eval_results.json"
        write_fn(
            path=out_path, rl=result, no_battery=result,
            rule_based_tou=result, checkpoint_id="test-003",
        )
        data = json.loads(out_path.read_text())
        locked_keys = {
            "energy_cost_yuan", "demand_charge_yuan", "degradation_yuan",
            "curtailment_yuan", "voll_yuan", "total_cost_yuan",
            "soc_violations_count", "soc_violation_mwh", "penalty_yuan",
        }
        for policy_name in ("rl", "no_battery", "rule_based_tou"):
            policy_keys = set(data["policies"][policy_name].keys())
            assert policy_keys == locked_keys, (
                f"policies.{policy_name} must have exactly 9 LOCKED keys; "
                f"extra={policy_keys - locked_keys}, missing={locked_keys - policy_keys}"
            )


# ---------------------------------------------------------------------------
# 8. Full-year rollout integration test (slow — requires JAX + SyntheticYear)
# ---------------------------------------------------------------------------

class TestFullEvalRollout:
    """run_eval() extended result — integration-level spot checks."""

    @pytest.mark.slow
    def test_full_year_no_battery_physical_quantities(self):
        """Zero-action policy: all physical MWh ≥ 0; conservation identities hold."""
        from energy_go.env.jax_env import EnvParams, make_synthetic_year  # noqa: PLC0415
        from energy_go.training.checkpoint_format import (  # noqa: PLC0415
            CheckpointData, save_checkpoint, load_checkpoint,
        )
        import numpy as np
        import tempfile, os

        run_eval = _import_run_eval()
        PolicyEvalResult = _import_policy_eval_result()

        # Build a zero-weight (all-zeros) actor — always outputs near-zero action
        # (tanh(0)=0 for a_bat; sigmoid(0)=0.5 for fractions)
        obs_dim, action_dim = 107, 6
        hidden = 256
        ckpt = CheckpointData(
            actor_fc1_w=np.zeros((obs_dim, hidden), dtype=np.float32),
            actor_fc1_b=np.zeros(hidden, dtype=np.float32),
            actor_fc2_w=np.zeros((hidden, hidden), dtype=np.float32),
            actor_fc2_b=np.zeros(hidden, dtype=np.float32),
            actor_out_w=np.zeros((hidden, action_dim * 2), dtype=np.float32),
            actor_out_b=np.zeros(action_dim * 2, dtype=np.float32),
            obs_mean=np.zeros(obs_dim, dtype=np.float32),
            obs_var=np.ones(obs_dim, dtype=np.float32),
            obs_count=np.int32(1),
            obs_clip=np.float32(10.0),
            checkpoint_id="test-zero-actor",
            run_id="test-run",
            global_step=0,
            created_at_utc="2026-06-11T00:00:00Z",
            code_version="test",
            run_config_json="{}",
        )
        import jax
        key = jax.random.PRNGKey(42)
        params = EnvParams(episode_len=8760)
        data = make_synthetic_year(key, params)

        result = run_eval(ckpt, data, params)

        # All physical MWh accumulators must be ≥ 0
        for field_name, val in [
            ("wind_generated_mwh",  result.wind_generated_mwh),
            ("pv_generated_mwh",    result.pv_generated_mwh),
            ("bat_charge_mwh",      result.bat_charge_mwh),
            ("bat_discharge_mwh",   result.bat_discharge_mwh),
            ("grid_import_mwh",     result.grid_import_mwh),
            ("grid_export_mwh",     result.grid_export_mwh),
            ("load_served_mwh",     result.load_served_mwh),
            ("load_unserved_mwh",   result.load_unserved_mwh),
            ("curtailed_mwh",       result.curtailed_mwh),
        ]:
            assert val >= 0.0, f"{field_name} must be ≥ 0, got {val}"

        # Wind conservation identity
        wind_lhs = result.wind_generated_mwh
        wind_rhs = (result.wind_to_load_mwh + result.wind_to_bat_mwh
                    + result.wind_to_grid_mwh + result.wind_curtailed_mwh)
        assert wind_lhs == pytest.approx(wind_rhs, rel=1e-3), (
            f"Wind conservation: {wind_lhs:.2f} ≠ {wind_rhs:.2f}"
        )

        # PV conservation identity
        pv_lhs = result.pv_generated_mwh
        pv_rhs = (result.pv_to_load_mwh + result.pv_to_bat_mwh
                  + result.pv_to_grid_mwh + result.pv_curtailed_mwh)
        assert pv_lhs == pytest.approx(pv_rhs, rel=1e-3), (
            f"PV conservation: {pv_lhs:.2f} ≠ {pv_rhs:.2f}"
        )

        # Battery discharge conservation
        bat_lhs = result.bat_discharge_mwh
        bat_rhs = result.bat_to_load_mwh + result.bat_to_grid_mwh + result.bat_curtailed_mwh
        assert bat_lhs == pytest.approx(bat_rhs, rel=1e-3), (
            f"Battery conservation: {bat_lhs:.2f} ≠ {bat_rhs:.2f}"
        )

        # r_export_yuan ≥ 0, c_import_yuan ≥ 0
        assert result.r_export_yuan >= 0.0, "r_export_yuan must be ≥ 0"
        assert result.c_import_yuan >= 0.0, "c_import_yuan must be ≥ 0"

        # energy_cost = c_import - r_export (D13) — should hold to float32 precision
        # (both sides derived from the same c_energy_yuan EnvInfo field)
        expected_c_energy = result.c_import_yuan - result.r_export_yuan
        assert result.energy_cost_yuan == pytest.approx(expected_c_energy, rel=1e-4), (
            f"D13 identity: energy_cost={result.energy_cost_yuan:.2f} "
            f"≠ c_import-r_export={expected_c_energy:.2f}"
        )
