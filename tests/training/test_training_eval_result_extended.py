"""Tests for Extended PolicyEvalResult — per-stream + physical-quantity accumulators.

Contract: contracts/training/eval_result_extended.md
Spec: §5.5 (eval), §3 (physics / EnvInfo)
Decisions: D3 (Δt=1h), D10/D21 (demand charge), D13 (cost separation), master plan §5.3/§5.5

ALL tests use hand-computed expected values; the arithmetic is shown in comments.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import jax.numpy as jnp
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers — build mock EnvInfo-like objects
# ---------------------------------------------------------------------------

def _make_mock_infos(n_steps: int, **field_values) -> SimpleNamespace:
    """Build a mock stacked EnvInfo with (n_steps,)-shaped fields.

    Unspecified fields default to 0.  Accepts scalar (broadcast) or
    (n_steps,)-length lists/arrays.
    """
    ALL_FIELDS = [
        "p_wind_mw", "p_pv_mw", "p_bat_ch_mw", "p_bat_dis_mw",
        "p_import_mw", "p_export_mw", "p_load_served_mw", "p_load_unserved_mw",
        "p_curtailed_mw",
        "c_import_yuan", "r_export_yuan", "c_energy_yuan",
        "c_demand_shape_yuan", "c_demand_charge_yuan", "c_degradation_yuan",
        "c_curtail_yuan", "c_voll_yuan",
        "cost_total_real_yuan", "cost_total_reward_basis_yuan",
        "penalty_yuan", "soc_violation_mwh",
        "price_buy_yuan_per_mwh", "price_sell_yuan_per_mwh",
        "p_sol_to_load_mw", "p_sol_to_bat_mw", "p_sol_to_grid_mw", "p_sol_curtailed_mw",
        "p_wind_to_load_mw", "p_wind_to_bat_mw", "p_wind_to_grid_mw", "p_wind_curtailed_mw",
        "p_bat_to_load_mw", "p_bat_to_grid_mw", "p_bat_curtailed_mw",
        "p_grid_to_bat_mw", "p_grid_to_load_mw",
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
# Import helpers
# ---------------------------------------------------------------------------

def _import_accumulate():
    from energy_go.training.eval import _accumulate_physical_quantities
    return _accumulate_physical_quantities


def _import_policy_eval_result():
    from energy_go.training.eval import PolicyEvalResult
    return PolicyEvalResult


def _import_policy_dict():
    from energy_go.training.telemetry import _policy_dict
    return _policy_dict


def _import_run_eval():
    from energy_go.training.eval import run_eval
    return run_eval


# ---------------------------------------------------------------------------
# 1. Field-count and presence tests (9 existing + 27 new = 36 total)
# ---------------------------------------------------------------------------

class TestPolicyEvalResultFields:
    """PolicyEvalResult has exactly 36 fields (9 existing + 27 new)."""

    def test_total_field_count(self):
        PolicyEvalResult = _import_policy_eval_result()
        fields = [f.name for f in dataclasses.fields(PolicyEvalResult)]
        assert len(fields) == 36, (
            f"Expected 36 fields (9 existing + 5 stream + 9 physical-qty + 13 per-source), "
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

    def test_stream_fields_present(self):
        """grid_export + grid_import + demand_charge stream fields."""
        PolicyEvalResult = _import_policy_eval_result()
        stream_fields = {
            "grid_export_mwh", "r_export_yuan",   # grid_export stream
            "grid_import_mwh", "c_import_yuan",   # grid_import stream
            "demand_billing_mw_month",             # demand_charge stream volume
        }
        actual = {f.name for f in dataclasses.fields(PolicyEvalResult)}
        assert stream_fields.issubset(actual), f"Missing stream fields: {stream_fields - actual}"

    def test_physical_qty_fields_present(self):
        PolicyEvalResult = _import_policy_eval_result()
        phy_fields = {
            "generation_mwh",    # LCOE denominator = wind + pv
            "wind_generated_mwh", "pv_generated_mwh",
            "bat_charge_mwh", "bat_discharge_mwh",
            "bat_throughput_mwh",   # cycle-life / VarOM = charge + discharge
            "load_served_mwh", "load_unserved_mwh", "curtailed_mwh",
        }
        actual = {f.name for f in dataclasses.fields(PolicyEvalResult)}
        assert phy_fields.issubset(actual), f"Missing physical-qty fields: {phy_fields - actual}"

    def test_per_source_fields_present(self):
        PolicyEvalResult = _import_policy_eval_result()
        per_src = {
            "wind_to_load_mwh", "wind_to_bat_mwh", "wind_to_grid_mwh", "wind_curtailed_mwh",
            "pv_to_load_mwh", "pv_to_bat_mwh", "pv_to_grid_mwh", "pv_curtailed_mwh",
            "bat_to_load_mwh", "bat_to_grid_mwh", "bat_curtailed_mwh",
            "grid_to_bat_mwh", "grid_to_load_mwh",
        }
        actual = {f.name for f in dataclasses.fields(PolicyEvalResult)}
        assert per_src.issubset(actual), f"Missing per-source fields: {per_src - actual}"

    def test_no_h2_sale_avoided_cost_token_sale_fields(self):
        """v1 scope guard: no zero-placeholder fields for inactive streams."""
        PolicyEvalResult = _import_policy_eval_result()
        names = {f.name for f in dataclasses.fields(PolicyEvalResult)}
        for forbidden in ("h2_sale_mwh", "h2_sale_yuan", "avoided_cost_yuan",
                          "token_sale_yuan", "token_sale_mwh"):
            assert forbidden not in names, (
                f"{forbidden} must NOT be in v1 PolicyEvalResult "
                f"(zero-placeholder fields invite confusion; add additively when scenario lands)"
            )


# ---------------------------------------------------------------------------
# 2. Accumulation formula tests — Δt=1h (D3): Σ p_X_mw = MWh
# ---------------------------------------------------------------------------

class TestAccumulationFormula:
    """accumulate: field_mwh = Σ p_field_mw.  Δt=1h ⇒ MW × 1h = MWh."""

    def test_wind_accumulation_constant(self):
        # 5 steps, p_wind_mw=100 MW → wind_generated_mwh = 5×100 = 500 MWh
        _acc = _import_accumulate()
        infos = _make_mock_infos(5, p_wind_mw=100.0)
        r = _acc(infos)
        assert r["wind_generated_mwh"] == pytest.approx(500.0, rel=1e-5), "5×100=500"

    def test_pv_accumulation_constant(self):
        # 3 steps, p_pv_mw=50 MW → pv_generated_mwh = 150 MWh
        _acc = _import_accumulate()
        infos = _make_mock_infos(3, p_pv_mw=50.0)
        r = _acc(infos)
        assert r["pv_generated_mwh"] == pytest.approx(150.0, rel=1e-5), "3×50=150"

    def test_generation_mwh_is_wind_plus_pv(self):
        # 4 steps: p_wind_mw=100, p_pv_mw=50
        # generation_mwh = 4×(100+50) = 4×150 = 600 MWh
        _acc = _import_accumulate()
        infos = _make_mock_infos(4, p_wind_mw=100.0, p_pv_mw=50.0)
        r = _acc(infos)
        assert r["generation_mwh"] == pytest.approx(600.0, rel=1e-5), "4×150=600"
        # Also verify decomposition
        assert r["generation_mwh"] == pytest.approx(
            r["wind_generated_mwh"] + r["pv_generated_mwh"], rel=1e-6
        ), "generation = wind + pv"

    def test_bat_throughput_is_charge_plus_discharge(self):
        # 4 steps: p_bat_ch_mw=80, p_bat_dis_mw=60
        # bat_throughput_mwh = 4×(80+60) = 4×140 = 560 MWh
        # bat_charge_mwh = 4×80 = 320, bat_discharge_mwh = 4×60 = 240
        _acc = _import_accumulate()
        infos = _make_mock_infos(4, p_bat_ch_mw=80.0, p_bat_dis_mw=60.0)
        r = _acc(infos)
        assert r["bat_throughput_mwh"] == pytest.approx(560.0, rel=1e-5), "4×140=560"
        assert r["bat_charge_mwh"]     == pytest.approx(320.0, rel=1e-5), "4×80=320"
        assert r["bat_discharge_mwh"]  == pytest.approx(240.0, rel=1e-5), "4×60=240"
        # throughput decomposition
        assert r["bat_throughput_mwh"] == pytest.approx(
            r["bat_charge_mwh"] + r["bat_discharge_mwh"], rel=1e-6
        ), "bat_throughput = charge + discharge"

    def test_grid_export_import_accumulation(self):
        # 6 steps: p_export_mw=120, p_import_mw=200
        # grid_export_mwh=720, grid_import_mwh=1200
        _acc = _import_accumulate()
        infos = _make_mock_infos(6, p_export_mw=120.0, p_import_mw=200.0)
        r = _acc(infos)
        assert r["grid_export_mwh"] == pytest.approx(720.0,  rel=1e-5), "6×120=720"
        assert r["grid_import_mwh"] == pytest.approx(1200.0, rel=1e-5), "6×200=1200"

    def test_cost_stream_accumulation(self):
        # 4 steps: c_import_yuan=5000 ¥/step, r_export_yuan=2000 ¥/step
        # c_import_yuan=20000, r_export_yuan=8000
        _acc = _import_accumulate()
        infos = _make_mock_infos(4, c_import_yuan=5000.0, r_export_yuan=2000.0)
        r = _acc(infos)
        assert r["c_import_yuan"] == pytest.approx(20000.0, rel=1e-5), "4×5000=20000"
        assert r["r_export_yuan"] == pytest.approx(8000.0,  rel=1e-5), "4×2000=8000"

    def test_per_source_wind_accumulation(self):
        # 3 steps: wind breakdown to_load=60, to_bat=20, to_grid=10, curtailed=10
        # Expected MWh: to_load=180, to_bat=60, to_grid=30, curtailed=30
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            3,
            p_wind_to_load_mw=60.0, p_wind_to_bat_mw=20.0,
            p_wind_to_grid_mw=10.0, p_wind_curtailed_mw=10.0,
        )
        r = _acc(infos)
        assert r["wind_to_load_mwh"]   == pytest.approx(180.0, rel=1e-5), "3×60=180"
        assert r["wind_to_bat_mwh"]    == pytest.approx(60.0,  rel=1e-5), "3×20=60"
        assert r["wind_to_grid_mwh"]   == pytest.approx(30.0,  rel=1e-5), "3×10=30"
        assert r["wind_curtailed_mwh"] == pytest.approx(30.0,  rel=1e-5), "3×10=30"

    def test_per_source_pv_accumulation(self):
        # 4 steps: pv to_load=120, to_bat=40, to_grid=20, curtailed=20
        # Expected MWh: 480, 160, 80, 80
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            4,
            p_sol_to_load_mw=120.0, p_sol_to_bat_mw=40.0,
            p_sol_to_grid_mw=20.0, p_sol_curtailed_mw=20.0,
        )
        r = _acc(infos)
        assert r["pv_to_load_mwh"]   == pytest.approx(480.0, rel=1e-5), "4×120=480"
        assert r["pv_to_bat_mwh"]    == pytest.approx(160.0, rel=1e-5), "4×40=160"
        assert r["pv_to_grid_mwh"]   == pytest.approx(80.0,  rel=1e-5), "4×20=80"
        assert r["pv_curtailed_mwh"] == pytest.approx(80.0,  rel=1e-5), "4×20=80"

    def test_per_source_bat_discharge_accumulation(self):
        # 5 steps: bat_dis to_load=50, to_grid=30, curtailed=10
        # Expected MWh: 250, 150, 50
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            5, p_bat_to_load_mw=50.0, p_bat_to_grid_mw=30.0, p_bat_curtailed_mw=10.0,
        )
        r = _acc(infos)
        assert r["bat_to_load_mwh"]   == pytest.approx(250.0, rel=1e-5), "5×50=250"
        assert r["bat_to_grid_mwh"]   == pytest.approx(150.0, rel=1e-5), "5×30=150"
        assert r["bat_curtailed_mwh"] == pytest.approx(50.0,  rel=1e-5), "5×10=50"

    def test_zero_flows_give_zero_mwh(self):
        _acc = _import_accumulate()
        infos = _make_mock_infos(8760)
        r = _acc(infos)
        for key, val in r.items():
            assert val == pytest.approx(0.0, abs=1e-6), f"{key}: expected 0 got {val}"

    def test_variable_steps_accumulation(self):
        # 3 steps p_wind_mw=[100, 200, 150] → generation_mwh = 100+200+150 = 450
        _acc = _import_accumulate()
        infos = _make_mock_infos(3, p_wind_mw=[100.0, 200.0, 150.0])
        r = _acc(infos)
        assert r["wind_generated_mwh"] == pytest.approx(450.0, rel=1e-5), "100+200+150=450"

    def test_helper_returns_26_keys(self):
        """_accumulate_physical_quantities returns exactly 26 keys
        (27 new fields minus demand_billing_mw_month, which is derived in run_eval)."""
        _acc = _import_accumulate()
        infos = _make_mock_infos(3)
        r = _acc(infos)
        assert len(r) == 26, (
            f"Expected 26 keys (2 cost-stream + 6 grid/bat aggregate + 9 physical-qty "
            f"+ 13 per-source - 1 demand_billing derived = 26), "
            f"got {len(r)}: {sorted(r.keys())}"
        )
        # demand_billing_mw_month is derived in run_eval, not in the helper
        assert "demand_billing_mw_month" not in r, (
            "demand_billing_mw_month is derived in run_eval(), not in the helper"
        )


# ---------------------------------------------------------------------------
# 3. Energy conservation identities (§3 physics, contract §4)
# ---------------------------------------------------------------------------

class TestEnergyConservation:
    """Per-source and decomposition conservation identities."""

    def test_wind_conservation(self):
        # 5 steps: wind 100 MW → to_load=60, to_bat=20, to_grid=10, curtailed=10 (sum=100)
        # wind_generated_mwh=500 = 300+100+50+50 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            5, p_wind_mw=100.0,
            p_wind_to_load_mw=60.0, p_wind_to_bat_mw=20.0,
            p_wind_to_grid_mw=10.0, p_wind_curtailed_mw=10.0,
        )
        r = _acc(infos)
        lhs = r["wind_generated_mwh"]     # 500
        rhs = (r["wind_to_load_mwh"] + r["wind_to_bat_mwh"]
               + r["wind_to_grid_mwh"] + r["wind_curtailed_mwh"])  # 300+100+50+50=500
        assert lhs == pytest.approx(rhs, rel=1e-4), f"Wind conservation: {lhs:.4f} ≠ {rhs:.4f}"

    def test_pv_conservation(self):
        # 4 steps: pv 50 MW → to_load=30, to_bat=10, to_grid=5, curtailed=5 (sum=50)
        # pv_generated_mwh=200 = 120+40+20+20 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            4, p_pv_mw=50.0,
            p_sol_to_load_mw=30.0, p_sol_to_bat_mw=10.0,
            p_sol_to_grid_mw=5.0, p_sol_curtailed_mw=5.0,
        )
        r = _acc(infos)
        lhs = r["pv_generated_mwh"]   # 200
        rhs = (r["pv_to_load_mwh"] + r["pv_to_bat_mwh"]
               + r["pv_to_grid_mwh"] + r["pv_curtailed_mwh"])  # 120+40+20+20=200
        assert lhs == pytest.approx(rhs, rel=1e-4), f"PV conservation: {lhs:.4f} ≠ {rhs:.4f}"

    def test_battery_discharge_conservation(self):
        # 3 steps: bat_dis 90 MW → to_load=50, to_grid=30, curtailed=10 (sum=90)
        # bat_discharge_mwh=270 = 150+90+30 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            3, p_bat_dis_mw=90.0,
            p_bat_to_load_mw=50.0, p_bat_to_grid_mw=30.0, p_bat_curtailed_mw=10.0,
        )
        r = _acc(infos)
        lhs = r["bat_discharge_mwh"]   # 270
        rhs = r["bat_to_load_mwh"] + r["bat_to_grid_mwh"] + r["bat_curtailed_mwh"]  # 150+90+30
        assert lhs == pytest.approx(rhs, rel=1e-4), f"Bat conservation: {lhs:.4f} ≠ {rhs:.4f}"

    def test_generation_decomposition(self):
        # generation_mwh = wind_generated_mwh + pv_generated_mwh (exact — same JAX arrays)
        # 4 steps: wind=100, pv=50 → generation=4×150=600, wind=4×100=400, pv=4×50=200
        # 600 = 400+200 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(4, p_wind_mw=100.0, p_pv_mw=50.0)
        r = _acc(infos)
        assert r["generation_mwh"] == pytest.approx(
            r["wind_generated_mwh"] + r["pv_generated_mwh"], rel=1e-6
        ), "generation = wind + pv (exact)"

    def test_bat_throughput_decomposition(self):
        # bat_throughput_mwh = bat_charge_mwh + bat_discharge_mwh (exact)
        # 4 steps: ch=80, dis=60 → throughput=4×140=560, charge=320, dis=240
        # 560 = 320+240 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(4, p_bat_ch_mw=80.0, p_bat_dis_mw=60.0)
        r = _acc(infos)
        assert r["bat_throughput_mwh"] == pytest.approx(
            r["bat_charge_mwh"] + r["bat_discharge_mwh"], rel=1e-6
        ), "bat_throughput = charge + discharge (exact)"


# ---------------------------------------------------------------------------
# 4. D13 cost identity and demand-charge reconciliation
# ---------------------------------------------------------------------------

class TestCostAndDemandIdentities:
    """D13: energy_cost = c_import − r_export. Demand: billing × rate = ¥."""

    def test_c_energy_identity(self):
        # 3 steps: c_energy_yuan=3000, c_import=5000, r_export=2000 per step
        # c_import_total=15000, r_export_total=6000, c_energy_total=9000
        # 9000 = 15000 - 6000 ✓
        _acc = _import_accumulate()
        infos = _make_mock_infos(3, c_energy_yuan=3000.0, c_import_yuan=5000.0, r_export_yuan=2000.0)
        r = _acc(infos)
        assert r["c_import_yuan"] == pytest.approx(15000.0, rel=1e-5), "3×5000=15000"
        assert r["r_export_yuan"] == pytest.approx(6000.0,  rel=1e-5), "3×2000=6000"
        expected_c_energy = r["c_import_yuan"] - r["r_export_yuan"]  # 9000
        assert expected_c_energy == pytest.approx(9000.0, rel=1e-5), "15000-6000=9000"

    def test_demand_billing_reconciliation(self):
        """demand_billing_mw_month × demand_rate = demand_charge_yuan.

        Scenario:
          demand_rate = 32000 ¥/MW·month (Gansu default: 32 ¥/kW × 1000)
          12 months, month_peak = 60 MW (constant) → demand_charge per month = 60×32000 = 1 920 000 ¥
          Annual demand_charge_yuan = 12 × 1 920 000 = 23 040 000 ¥
          demand_billing_mw_month = 23 040 000 / 32 000 = 720 MW·month (= 12 × 60 ✓)
        """
        demand_rate = 32000.0    # ¥/MW·month (Gansu default)
        month_peak_mw = 60.0     # MW (constant each month)
        n_months = 12
        # demand_charge is only booked at month boundaries (D10/D21)
        # Simulate: 12 non-zero steps (month boundaries) + rest zero
        n_steps = 8760
        c_dc = np.zeros(n_steps, dtype=np.float32)
        # Put the charge at step 0, 730, 1460, ... (roughly; exact positions don't matter)
        month_steps = [int(i * n_steps / n_months) for i in range(n_months)]
        for s in month_steps:
            c_dc[s] = month_peak_mw * demand_rate  # 1 920 000 ¥
        total_demand_charge_yuan = float(np.sum(c_dc))  # 12 × 1 920 000 = 23 040 000 ¥

        # Compute demand_billing_mw_month
        demand_billing_mw_month = total_demand_charge_yuan / demand_rate
        # Expected: 23 040 000 / 32 000 = 720 MW·month = 12 × 60 ✓
        expected_billing = n_months * month_peak_mw  # 720
        assert demand_billing_mw_month == pytest.approx(expected_billing, rel=1e-5), (
            f"demand_billing = total_demand_charge / rate: "
            f"{total_demand_charge_yuan:.0f} / {demand_rate:.0f} = {demand_billing_mw_month:.2f} "
            f"≠ expected {expected_billing:.2f} (= 12 months × 60 MW)"
        )

    def test_demand_billing_reconciliation_reverse(self):
        """demand_billing × rate → demand_charge_yuan round-trip.

        demand_billing_mw_month = 720.0
        demand_rate = 32000.0 ¥/MW·month
        Expected: demand_charge_yuan = 720 × 32000 = 23 040 000 ¥
        """
        demand_billing_mw_month = 720.0   # MW·month
        demand_rate              = 32000.0 # ¥/MW·month
        expected_demand_charge   = demand_billing_mw_month * demand_rate  # 23 040 000 ¥
        assert expected_demand_charge == pytest.approx(23_040_000.0, rel=1e-5), (
            "720 × 32000 = 23 040 000 ¥"
        )

    def test_zero_demand_billing_when_no_charge(self):
        """If demand_charge_yuan=0, demand_billing_mw_month=0."""
        demand_charge_yuan = 0.0
        demand_rate = 32000.0
        demand_billing_mw_month = (
            demand_charge_yuan / demand_rate if demand_rate != 0.0 else 0.0
        )
        assert demand_billing_mw_month == pytest.approx(0.0, abs=1e-9)

    # reviewer: RE-ADDED — these two cross-source identity cases were dropped by the
    # 91c641a stream-shape revision (originally added at 2b12566). Restored verbatim;
    # they remain valid against the 36-field result (curtailed/grid_import still accumulate).
    #
    # AGGREGATE-vs-per-source curtailment: env defines p_curtailed_mw = p_sol_curtailed
    # + p_wind_curtailed + p_bat_curtailed, so curtailed_mwh must equal the sum of the
    # three per-source curtailed accumulators.
    # 4 steps: p_curtailed=25 = wind 10 + pv 10 + bat 5 → curtailed_mwh=100; sum=40+40+20=100.
    def test_aggregate_curtailed_equals_per_source_sum(self):
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            4,
            p_curtailed_mw=25.0,
            p_wind_curtailed_mw=10.0, p_sol_curtailed_mw=10.0, p_bat_curtailed_mw=5.0,
        )
        r = _acc(infos)
        lhs = r["curtailed_mwh"]
        rhs = r["wind_curtailed_mwh"] + r["pv_curtailed_mwh"] + r["bat_curtailed_mwh"]
        assert lhs == pytest.approx(rhs, rel=1e-4), (
            f"aggregate curtailed_mwh={lhs:.4f} ≠ Σ per-source {rhs:.4f}"
        )

    # reviewer: grid-import decomposition — ties to the F-IMPORT fix (§3.6 row 9):
    # env guarantees P_import = grid_to_load + grid_to_bat, so grid_import_mwh must equal
    # grid_to_bat_mwh + grid_to_load_mwh. A battery-first F-IMPORT regression breaks this.
    # 6 steps: p_import=150 = grid_to_bat 50 + grid_to_load 100 → grid_import_mwh=900; sum=300+600=900.
    def test_grid_import_equals_to_bat_plus_to_load(self):
        _acc = _import_accumulate()
        infos = _make_mock_infos(
            6,
            p_import_mw=150.0,
            p_grid_to_bat_mw=50.0, p_grid_to_load_mw=100.0,
        )
        r = _acc(infos)
        lhs = r["grid_import_mwh"]
        rhs = r["grid_to_bat_mwh"] + r["grid_to_load_mwh"]
        assert lhs == pytest.approx(rhs, rel=1e-4), (
            f"grid_import_mwh={lhs:.4f} ≠ grid_to_bat+grid_to_load {rhs:.4f} "
            "(F-IMPORT §3.6 row 9: P_import = grid_to_load + grid_to_bat)"
        )


# ---------------------------------------------------------------------------
# 5. Wire isolation — _policy_dict must return exactly the 9 LOCKED fields
# ---------------------------------------------------------------------------

class TestWireIsolation:
    """_policy_dict in telemetry.py serializes ONLY the 9 LOCKED eval_compare fields."""

    LOCKED_KEYS = {
        "energy_cost_yuan", "demand_charge_yuan", "degradation_yuan",
        "curtailment_yuan", "voll_yuan", "total_cost_yuan",
        "soc_violations_count", "soc_violation_mwh", "penalty_yuan",
    }

    def _make_full_result(self):
        PolicyEvalResult = _import_policy_eval_result()
        return PolicyEvalResult(
            # existing 9
            energy_cost_yuan=100.0,  demand_charge_yuan=200.0, degradation_yuan=50.0,
            curtailment_yuan=30.0,   voll_yuan=0.0,            total_cost_yuan=380.0,
            soc_violations_count=2,  soc_violation_mwh=0.5,    penalty_yuan=10.0,
            # stream fields
            grid_export_mwh=500.0,   r_export_yuan=40.0,
            grid_import_mwh=300.0,   c_import_yuan=140.0,
            demand_billing_mw_month=720.0,
            # physical quantities
            generation_mwh=9050.0,
            wind_generated_mwh=6150.0, pv_generated_mwh=2900.0,
            bat_charge_mwh=850.0,    bat_discharge_mwh=780.0,  bat_throughput_mwh=1630.0,
            load_served_mwh=7200.0,  load_unserved_mwh=0.0,    curtailed_mwh=60.0,
            # per-source (13)
            wind_to_load_mwh=4000.0, wind_to_bat_mwh=500.0,
            wind_to_grid_mwh=300.0,  wind_curtailed_mwh=1350.0,
            pv_to_load_mwh=2000.0,   pv_to_bat_mwh=350.0,
            pv_to_grid_mwh=200.0,    pv_curtailed_mwh=350.0,
            bat_to_load_mwh=600.0,   bat_to_grid_mwh=150.0,  bat_curtailed_mwh=30.0,
            grid_to_bat_mwh=200.0,   grid_to_load_mwh=100.0,
        )

    def test_policy_dict_has_exactly_9_keys(self):
        _policy_dict = _import_policy_dict()
        d = _policy_dict(self._make_full_result())
        assert set(d.keys()) == self.LOCKED_KEYS, (
            f"_policy_dict returned {len(d)} keys, expected 9.\n"
            f"Extra:   {set(d.keys()) - self.LOCKED_KEYS}\n"
            f"Missing: {self.LOCKED_KEYS - set(d.keys())}"
        )

    def test_policy_dict_no_mwh_fields(self):
        _policy_dict = _import_policy_dict()
        d = _policy_dict(self._make_full_result())
        mwh = [k for k in d if k.endswith("_mwh") and k != "soc_violation_mwh"]
        assert mwh == [], f"eval_compare must not contain MWh fields; found: {mwh}"

    def test_policy_dict_no_billing_or_stream_volume_fields(self):
        _policy_dict = _import_policy_dict()
        d = _policy_dict(self._make_full_result())
        for forbidden in ("r_export_yuan", "c_import_yuan", "demand_billing_mw_month",
                          "generation_mwh", "bat_throughput_mwh",
                          "grid_export_mwh", "grid_import_mwh"):
            assert forbidden not in d, f"{forbidden} must NOT appear in eval_compare"

    def test_policy_dict_values_unchanged(self):
        _policy_dict = _import_policy_dict()
        d = _policy_dict(self._make_full_result())
        assert d["energy_cost_yuan"]     == pytest.approx(100.0, rel=1e-9)
        assert d["demand_charge_yuan"]   == pytest.approx(200.0, rel=1e-9)
        assert d["total_cost_yuan"]      == pytest.approx(380.0, rel=1e-9)
        assert d["soc_violations_count"] == 2
        assert d["soc_violation_mwh"]    == pytest.approx(0.5,   rel=1e-9)
        assert d["penalty_yuan"]         == pytest.approx(10.0,  rel=1e-9)


# ---------------------------------------------------------------------------
# 6. Backward compatibility — existing 9 fields unchanged
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Existing 9 fields computed identically; additive identity holds."""

    def test_total_cost_additive_identity(self):
        # energy=100, demand=200, degrad=50, curtail=30, voll=0 → total=380
        PolicyEvalResult = _import_policy_eval_result()
        r = PolicyEvalResult(
            energy_cost_yuan=100.0, demand_charge_yuan=200.0, degradation_yuan=50.0,
            curtailment_yuan=30.0,  voll_yuan=0.0,            total_cost_yuan=380.0,
            soc_violations_count=0, soc_violation_mwh=0.0,    penalty_yuan=0.0,
            grid_export_mwh=0.0,    r_export_yuan=0.0,
            grid_import_mwh=0.0,    c_import_yuan=0.0,
            demand_billing_mw_month=0.0,
            generation_mwh=0.0,
            wind_generated_mwh=0.0, pv_generated_mwh=0.0,
            bat_charge_mwh=0.0,     bat_discharge_mwh=0.0,  bat_throughput_mwh=0.0,
            load_served_mwh=0.0,    load_unserved_mwh=0.0,  curtailed_mwh=0.0,
            wind_to_load_mwh=0.0,   wind_to_bat_mwh=0.0,
            wind_to_grid_mwh=0.0,   wind_curtailed_mwh=0.0,
            pv_to_load_mwh=0.0,     pv_to_bat_mwh=0.0,
            pv_to_grid_mwh=0.0,     pv_curtailed_mwh=0.0,
            bat_to_load_mwh=0.0,    bat_to_grid_mwh=0.0,  bat_curtailed_mwh=0.0,
            grid_to_bat_mwh=0.0,    grid_to_load_mwh=0.0,
        )
        # 100+200+50+30+0 = 380
        expected = 100.0 + 200.0 + 50.0 + 30.0 + 0.0
        assert r.total_cost_yuan == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# 7. eval_results.json extension — physical_quantities key
# ---------------------------------------------------------------------------

class TestEvalResultsJson:
    """eval_results.json must gain 'physical_quantities' top-level key (27 new fields)."""

    def _import_write_eval_results(self):
        try:
            from energy_go.training.run_training import _write_eval_results
            return _write_eval_results
        except ImportError:
            pytest.skip("_write_eval_results not yet importable (RED phase)")

    def _make_result(self, seed: float) -> object:
        PolicyEvalResult = _import_policy_eval_result()
        return PolicyEvalResult(
            energy_cost_yuan=seed,    demand_charge_yuan=seed*2, degradation_yuan=seed,
            curtailment_yuan=seed,    voll_yuan=0.0,             total_cost_yuan=5*seed,
            soc_violations_count=0,   soc_violation_mwh=0.0,     penalty_yuan=0.0,
            grid_export_mwh=seed*100, r_export_yuan=seed*10,
            grid_import_mwh=seed*50,  c_import_yuan=seed*20,
            demand_billing_mw_month=seed*10,
            generation_mwh=seed*200,
            wind_generated_mwh=seed*150, pv_generated_mwh=seed*50,
            bat_charge_mwh=seed*20,      bat_discharge_mwh=seed*18, bat_throughput_mwh=seed*38,
            load_served_mwh=seed*180,    load_unserved_mwh=0.0,    curtailed_mwh=seed*5,
            wind_to_load_mwh=seed*100,   wind_to_bat_mwh=seed*10,
            wind_to_grid_mwh=seed*30,    wind_curtailed_mwh=seed*10,
            pv_to_load_mwh=seed*40,      pv_to_bat_mwh=seed*5,
            pv_to_grid_mwh=seed*3,       pv_curtailed_mwh=seed*2,
            bat_to_load_mwh=seed*15,     bat_to_grid_mwh=seed*2, bat_curtailed_mwh=seed*1,
            grid_to_bat_mwh=seed*5,      grid_to_load_mwh=seed*10,
        )

    def test_physical_quantities_key_present(self, tmp_path):
        import json
        write_fn = self._import_write_eval_results()
        out = tmp_path / "eval_results.json"
        write_fn(path=out, rl=self._make_result(1.0), no_battery=self._make_result(2.0),
                 rule_based_tou=self._make_result(1.5), checkpoint_id="test-001")
        data = json.loads(out.read_text())
        assert "physical_quantities" in data, "eval_results.json missing 'physical_quantities'"
        for policy in ("rl", "no_battery", "rule_based_tou"):
            assert policy in data["physical_quantities"], f"physical_quantities.{policy} missing"

    def test_physical_quantities_has_27_fields_per_policy(self, tmp_path):
        import json
        write_fn = self._import_write_eval_results()
        out = tmp_path / "eval_results.json"
        write_fn(path=out, rl=self._make_result(1.0), no_battery=self._make_result(1.0),
                 rule_based_tou=self._make_result(1.0), checkpoint_id="test-002")
        data = json.loads(out.read_text())
        phys_rl = data["physical_quantities"]["rl"]
        assert len(phys_rl) == 27, (
            f"Expected 27 physical-quantity fields per policy, got {len(phys_rl)}: "
            f"{sorted(phys_rl.keys())}"
        )

    def test_physical_quantities_sample_values(self, tmp_path):
        import json
        write_fn = self._import_write_eval_results()
        out = tmp_path / "eval_results.json"
        write_fn(path=out, rl=self._make_result(1.0), no_battery=self._make_result(1.0),
                 rule_based_tou=self._make_result(1.0), checkpoint_id="test-003")
        data = json.loads(out.read_text())
        rl = data["physical_quantities"]["rl"]
        assert rl["generation_mwh"]         == pytest.approx(200.0, rel=1e-5)
        assert rl["bat_throughput_mwh"]      == pytest.approx(38.0,  rel=1e-5)
        assert rl["demand_billing_mw_month"] == pytest.approx(10.0,  rel=1e-5)
        assert rl["grid_export_mwh"]         == pytest.approx(100.0, rel=1e-5)
        assert rl["r_export_yuan"]           == pytest.approx(10.0,  rel=1e-5)

    def test_policies_dict_retains_9_locked_keys(self, tmp_path):
        """The 'policies' dict must retain exactly the 9 LOCKED keys."""
        import json
        write_fn = self._import_write_eval_results()
        out = tmp_path / "eval_results.json"
        write_fn(path=out, rl=self._make_result(1.0), no_battery=self._make_result(1.0),
                 rule_based_tou=self._make_result(1.0), checkpoint_id="test-004")
        data = json.loads(out.read_text())
        locked = {
            "energy_cost_yuan", "demand_charge_yuan", "degradation_yuan",
            "curtailment_yuan", "voll_yuan", "total_cost_yuan",
            "soc_violations_count", "soc_violation_mwh", "penalty_yuan",
        }
        for policy in ("rl", "no_battery", "rule_based_tou"):
            keys = set(data["policies"][policy].keys())
            assert keys == locked, (
                f"policies.{policy} must have exactly 9 LOCKED keys; "
                f"extra={keys - locked}, missing={locked - keys}"
            )

    def test_no_h2_sale_or_avoided_cost_in_physical_quantities(self, tmp_path):
        """v1 scope guard: no placeholder streams in physical_quantities."""
        import json
        write_fn = self._import_write_eval_results()
        out = tmp_path / "eval_results.json"
        write_fn(path=out, rl=self._make_result(1.0), no_battery=self._make_result(1.0),
                 rule_based_tou=self._make_result(1.0), checkpoint_id="test-005")
        data = json.loads(out.read_text())
        phys = data["physical_quantities"]["rl"]
        for forbidden in ("h2_sale_mwh", "h2_sale_yuan", "avoided_cost_yuan",
                          "token_sale_yuan", "token_sale_mwh"):
            assert forbidden not in phys, (
                f"{forbidden} must NOT appear in physical_quantities (v1 scope guard)"
            )


# ---------------------------------------------------------------------------
# 8. Full-year rollout integration (slow — requires JAX + SyntheticYear)
# ---------------------------------------------------------------------------

class TestFullEvalRollout:
    """run_eval() extended result — integration-level spot checks."""

    @pytest.mark.slow
    def test_full_year_zero_actor_physical_quantities(self):
        """Zero-weight actor: all MWh ≥ 0; conservation + decomposition identities hold."""
        import numpy as np
        from energy_go.env.jax_env import EnvParams, make_synthetic_year
        from energy_go.training.checkpoint_format import CheckpointData

        run_eval = _import_run_eval()

        obs_dim, action_dim, hidden = 107, 6, 256
        ckpt = CheckpointData(
            actor_fc1_w=np.zeros((obs_dim, hidden), np.float32),
            actor_fc1_b=np.zeros(hidden, np.float32),
            actor_fc2_w=np.zeros((hidden, hidden), np.float32),
            actor_fc2_b=np.zeros(hidden, np.float32),
            actor_out_w=np.zeros((hidden, action_dim * 2), np.float32),
            actor_out_b=np.zeros(action_dim * 2, np.float32),
            obs_mean=np.zeros(obs_dim, np.float32),
            obs_var=np.ones(obs_dim, np.float32),
            obs_count=np.int32(1),
            obs_clip=np.float32(10.0),
            checkpoint_id="test-zero-actor",
            run_id="test-run", global_step=0,
            created_at_utc="2026-06-11T00:00:00Z",
            code_version="test", run_config_json="{}",
        )
        import jax
        key = jax.random.PRNGKey(42)
        params = EnvParams(episode_len=8760)
        data = make_synthetic_year(key, params)

        result = run_eval(ckpt, data, params)

        # All aggregate MWh ≥ 0
        for fname in ("grid_export_mwh", "grid_import_mwh", "generation_mwh",
                      "wind_generated_mwh", "pv_generated_mwh",
                      "bat_charge_mwh", "bat_discharge_mwh", "bat_throughput_mwh",
                      "load_served_mwh", "load_unserved_mwh", "curtailed_mwh"):
            val = getattr(result, fname)
            assert val >= 0.0, f"{fname} must be ≥ 0, got {val}"

        # r_export_yuan ≥ 0, c_import_yuan ≥ 0
        assert result.r_export_yuan >= 0.0
        assert result.c_import_yuan >= 0.0

        # D13 identity: energy_cost = c_import − r_export
        assert result.energy_cost_yuan == pytest.approx(
            result.c_import_yuan - result.r_export_yuan, rel=1e-4
        ), "D13 cost identity"

        # generation decomposition: wind + pv = generation
        assert result.generation_mwh == pytest.approx(
            result.wind_generated_mwh + result.pv_generated_mwh, rel=1e-4
        ), "generation = wind + pv"

        # bat_throughput = charge + discharge
        assert result.bat_throughput_mwh == pytest.approx(
            result.bat_charge_mwh + result.bat_discharge_mwh, rel=1e-4
        ), "bat_throughput = charge + discharge"

        # Wind conservation
        wind_rhs = (result.wind_to_load_mwh + result.wind_to_bat_mwh
                    + result.wind_to_grid_mwh + result.wind_curtailed_mwh)
        assert result.wind_generated_mwh == pytest.approx(wind_rhs, rel=1e-3), "wind conservation"

        # PV conservation
        pv_rhs = (result.pv_to_load_mwh + result.pv_to_bat_mwh
                  + result.pv_to_grid_mwh + result.pv_curtailed_mwh)
        assert result.pv_generated_mwh == pytest.approx(pv_rhs, rel=1e-3), "pv conservation"

        # demand_billing_mw_month reconciliation
        if params.demand_rate_yuan_per_mw_month != 0.0:
            expected_demand_yuan = (
                result.demand_billing_mw_month * params.demand_rate_yuan_per_mw_month
            )
            assert result.demand_charge_yuan == pytest.approx(expected_demand_yuan, rel=1e-4), (
                "demand_billing × rate = demand_charge_yuan"
            )
