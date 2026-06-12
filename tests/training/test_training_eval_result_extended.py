"""Tests for extended PolicyEvalResult (stream-keyed + physical-quantity accumulators).

Contract: contracts/training/eval_result_extended.md
Spec: §5.5, §3, master plan §5.3/§5.5/§8; decisions D3/D13/D17/D31/F1
Owner: jax-env-engineer + training-engineer
Reviewer gate: backend-reviewer
v3: stream-keyed StreamAccumulator per rl-architect architectural ruling (#82 gate).

All expected values are hand-computed with the arithmetic shown in comments.
Δt = 1h (D3) → accumulated p_X_mw [MW] over N steps = N × p_X_mw [MWh].
"""
import dataclasses
import pytest
from types import SimpleNamespace

import numpy as np

# ---------------------------------------------------------------------------
# Imports under test — RED until implementation is complete (correct).
# ---------------------------------------------------------------------------
from energy_go.training.eval import (
    StreamAccumulator,
    PolicyEvalResult,
    _build_streams,
    _accumulate_physical_quantities,
)
from energy_go.training.telemetry import _policy_dict


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_ALL_INFO_FIELDS = [
    # aggregate generation
    "p_wind_mw", "p_pv_mw",
    # aggregate grid
    "p_export_mw", "p_import_mw",
    # aggregate curtailed / load
    "p_curtailed_mw", "p_load_mw", "p_load_unserved_mw",
    # per-step costs — c_import and r_export are separate EnvInfo fields (D13)
    "c_import_yuan", "r_export_yuan", "c_energy_yuan",
    "c_demand_charge_yuan", "c_degradation_yuan",
    "c_curtail_yuan", "c_voll_yuan", "penalty_yuan",
    "soc_violation_mwh",
    # per-source breakdown (13 EnvInfo fields — "sol" naming for PV per jax_env.py)
    "p_wind_to_load_mw", "p_wind_to_bat_mw",
    "p_wind_to_grid_mw", "p_wind_curtailed_mw",
    "p_sol_to_load_mw",  "p_sol_to_bat_mw",
    "p_sol_to_grid_mw",  "p_sol_curtailed_mw",
    "p_bat_to_load_mw",  "p_bat_to_grid_mw", "p_bat_curtailed_mw",
    "p_grid_to_bat_mw",  "p_grid_to_load_mw",
]


def _make_mock_infos(n_steps: int, **kwargs) -> SimpleNamespace:
    """Build a mock infos object with (n_steps,)-shaped float64 array fields.

    All fields default to 0.0 unless overridden. Field names match EnvInfo.
    """
    data = {f: np.zeros(n_steps) for f in _ALL_INFO_FIELDS}
    for k, v in kwargs.items():
        data[k] = np.full(n_steps, float(v))
    return SimpleNamespace(**data)


def _params(demand_rate_yuan_per_mw_month: float = 100.0) -> SimpleNamespace:
    """Minimal mock EnvParams for _build_streams."""
    return SimpleNamespace(demand_rate_yuan_per_mw_month=demand_rate_yuan_per_mw_month)


def _make_zero_result() -> PolicyEvalResult:
    """Construct a fully-populated 32-field PolicyEvalResult with all zeros."""
    _z = StreamAccumulator(volume=0.0, value_yuan=0.0)
    return PolicyEvalResult(
        # existing 9
        energy_cost_yuan=0.0, demand_charge_yuan=0.0, degradation_yuan=0.0,
        curtailment_yuan=0.0, voll_yuan=0.0, total_cost_yuan=0.0,
        soc_violations_count=0, soc_violation_mwh=0.0, penalty_yuan=0.0,
        # streams dict (6 rev4 keys)
        streams={
            "grid_export": _z, "grid_import": _z, "demand_charge": _z,
            "h2_sale": _z, "avoided_cost": _z, "token_sale": _z,
        },
        # 9 physical-qty
        generation_mwh=0.0, wind_generated_mwh=0.0, pv_generated_mwh=0.0,
        bat_charge_mwh=0.0, bat_discharge_mwh=0.0, bat_throughput_mwh=0.0,
        load_served_mwh=0.0, load_unserved_mwh=0.0, curtailed_mwh=0.0,
        # 13 per-source
        wind_to_load_mwh=0.0, wind_to_bat_mwh=0.0,
        wind_to_grid_mwh=0.0, wind_curtailed_mwh=0.0,
        pv_to_load_mwh=0.0,   pv_to_bat_mwh=0.0,
        pv_to_grid_mwh=0.0,   pv_curtailed_mwh=0.0,
        bat_to_load_mwh=0.0,  bat_to_grid_mwh=0.0, bat_curtailed_mwh=0.0,
        grid_to_bat_mwh=0.0,  grid_to_load_mwh=0.0,
    )


# ---------------------------------------------------------------------------
# 1. StreamAccumulator NamedTuple
# ---------------------------------------------------------------------------

class TestStreamAccumulatorNamedTuple:
    """StreamAccumulator is a 2-leaf NamedTuple (volume, value_yuan)."""

    def test_is_namedtuple_subclass_of_tuple(self):
        sa = StreamAccumulator(volume=100.0, value_yuan=500.0)
        assert isinstance(sa, tuple), "StreamAccumulator must be a NamedTuple"

    def test_two_leaves_only(self):
        sa = StreamAccumulator(volume=10.0, value_yuan=20.0)
        assert len(sa) == 2, f"expected 2 leaves, got {len(sa)}"

    def test_fields_named_volume_and_value_yuan_in_order(self):
        assert StreamAccumulator._fields == ("volume", "value_yuan"), (
            "fields must be ('volume', 'value_yuan') in that order"
        )

    def test_field_access_by_name(self):
        sa = StreamAccumulator(volume=42.5, value_yuan=1234.0)
        assert sa.volume == pytest.approx(42.5)
        assert sa.value_yuan == pytest.approx(1234.0)

    def test_zero_initialisation(self):
        sa = StreamAccumulator(volume=0.0, value_yuan=0.0)
        assert sa.volume == 0.0
        assert sa.value_yuan == 0.0


# ---------------------------------------------------------------------------
# 2. PolicyEvalResult structure — 32 fields
# ---------------------------------------------------------------------------

class TestPolicyEvalResultStructure:
    """PolicyEvalResult is a dataclass with exactly 32 fields."""

    def test_total_field_count_is_32(self):
        # 9 wire-locked + 1 streams + 9 physical-qty + 13 per-source = 32
        result = _make_zero_result()
        n = len(dataclasses.fields(result))
        assert n == 32, f"expected 32 fields, got {n}"

    def test_existing_9_wire_locked_fields_present(self):
        result = _make_zero_result()
        names = {f.name for f in dataclasses.fields(result)}
        locked = {
            "energy_cost_yuan", "demand_charge_yuan", "degradation_yuan",
            "curtailment_yuan", "voll_yuan", "total_cost_yuan",
            "soc_violations_count", "soc_violation_mwh", "penalty_yuan",
        }
        missing = locked - names
        assert not missing, f"missing wire-locked fields: {missing}"

    def test_streams_field_is_dict(self):
        result = _make_zero_result()
        assert hasattr(result, "streams")
        assert isinstance(result.streams, dict)

    def test_physical_qty_fields_present(self):
        result = _make_zero_result()
        names = {f.name for f in dataclasses.fields(result)}
        phys = {
            "generation_mwh", "wind_generated_mwh", "pv_generated_mwh",
            "bat_charge_mwh", "bat_discharge_mwh", "bat_throughput_mwh",
            "load_served_mwh", "load_unserved_mwh", "curtailed_mwh",
        }
        missing = phys - names
        assert not missing, f"missing physical-qty fields: {missing}"

    def test_per_source_fields_count_is_13(self):
        result = _make_zero_result()
        names = {f.name for f in dataclasses.fields(result)}
        per_src = {
            "wind_to_load_mwh", "wind_to_bat_mwh", "wind_to_grid_mwh", "wind_curtailed_mwh",
            "pv_to_load_mwh",   "pv_to_bat_mwh",   "pv_to_grid_mwh",   "pv_curtailed_mwh",
            "bat_to_load_mwh",  "bat_to_grid_mwh",  "bat_curtailed_mwh",
            "grid_to_bat_mwh",  "grid_to_load_mwh",
        }
        assert len(per_src) == 13
        missing = per_src - names
        assert not missing, f"missing per-source fields: {missing}"


# ---------------------------------------------------------------------------
# 3. streams dict — 6 keys, all StreamAccumulator
# ---------------------------------------------------------------------------

_REV4_STREAM_KEYS = frozenset({
    "grid_export", "grid_import", "demand_charge",
    "h2_sale", "avoided_cost", "token_sale",
})


class TestStreamsDict:
    """streams dict has exactly the 6 rev4 keys, all are StreamAccumulator instances."""

    def test_exactly_six_rev4_keys(self):
        result = _make_zero_result()
        assert set(result.streams.keys()) == _REV4_STREAM_KEYS

    def test_all_values_are_stream_accumulator(self):
        result = _make_zero_result()
        for key, val in result.streams.items():
            assert isinstance(val, StreamAccumulator), (
                f"streams['{key}'] must be StreamAccumulator, got {type(val)}"
            )

    def test_v1_zero_placeholders_h2_avoided_token(self):
        """h2_sale, avoided_cost, token_sale must be exactly zero in v1."""
        result = _make_zero_result()
        for key in ("h2_sale", "avoided_cost", "token_sale"):
            assert result.streams[key].volume == 0.0, f"streams['{key}'].volume != 0"
            assert result.streams[key].value_yuan == 0.0, f"streams['{key}'].value_yuan != 0"

    def test_build_streams_returns_exactly_six_rev4_keys(self):
        infos = _make_mock_infos(1)
        streams = _build_streams(infos, _params())
        assert set(streams.keys()) == _REV4_STREAM_KEYS


# ---------------------------------------------------------------------------
# 4. _build_streams: grid_export
# ---------------------------------------------------------------------------

class TestBuildStreamsGridExport:
    """grid_export.volume = Σ p_export_mw [MWh]; value_yuan = Σ r_export_yuan [¥]."""

    def test_volume_accumulates_p_export_mw(self):
        # 10 steps × 50 MW = 500 MWh  (Δt=1h, D3)
        infos = _make_mock_infos(10, p_export_mw=50.0)
        streams = _build_streams(infos, _params())
        assert streams["grid_export"].volume == pytest.approx(500.0, rel=1e-4)  # 10×50

    def test_value_yuan_accumulates_r_export(self):
        # 8 steps × 75 ¥/step = 600 ¥
        infos = _make_mock_infos(8, r_export_yuan=75.0)
        streams = _build_streams(infos, _params())
        assert streams["grid_export"].value_yuan == pytest.approx(600.0, rel=1e-4)  # 8×75

    def test_zero_when_no_export(self):
        infos = _make_mock_infos(24)
        streams = _build_streams(infos, _params())
        assert streams["grid_export"].volume == pytest.approx(0.0, abs=1e-6)
        assert streams["grid_export"].value_yuan == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 5. _build_streams: grid_import
# ---------------------------------------------------------------------------

class TestBuildStreamsGridImport:
    """grid_import.volume = Σ p_import_mw [MWh]; value_yuan = Σ c_import_yuan [¥]."""

    def test_volume_accumulates_p_import_mw(self):
        # 6 steps × 200 MW = 1200 MWh
        infos = _make_mock_infos(6, p_import_mw=200.0)
        streams = _build_streams(infos, _params())
        assert streams["grid_import"].volume == pytest.approx(1200.0, rel=1e-4)  # 6×200

    def test_value_yuan_accumulates_c_import(self):
        # 12 steps × 300 ¥/step = 3600 ¥
        infos = _make_mock_infos(12, c_import_yuan=300.0)
        streams = _build_streams(infos, _params())
        assert streams["grid_import"].value_yuan == pytest.approx(3600.0, rel=1e-4)  # 12×300

    def test_zero_when_no_import(self):
        infos = _make_mock_infos(24)
        streams = _build_streams(infos, _params())
        assert streams["grid_import"].volume == pytest.approx(0.0, abs=1e-6)
        assert streams["grid_import"].value_yuan == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 6. _build_streams: demand_charge (annual peak MW — D31/F1)
# ---------------------------------------------------------------------------

class TestBuildStreamsDemandCharge:
    """demand_charge.volume = max(c_demand_charge_yuan) / demand_rate [MW] (D31/F1).
    demand_charge.value_yuan = Σ c_demand_charge_yuan [¥].
    Annual peak = max single-step booking / rate (not Σ monthly peaks).
    """

    def test_volume_is_max_booking_divided_by_rate(self):
        # bookings = [0, 500, 300] ¥; rate = 100 ¥/MW/month
        # annual peak MW = max([0,500,300]) / 100 = 500/100 = 5.0 MW
        infos = _make_mock_infos(3)
        infos.c_demand_charge_yuan = np.array([0.0, 500.0, 300.0])
        streams = _build_streams(infos, _params(demand_rate_yuan_per_mw_month=100.0))
        assert streams["demand_charge"].volume == pytest.approx(5.0, rel=1e-4)  # 500/100

    def test_value_yuan_is_sum_of_bookings(self):
        # bookings = [0, 500, 300] → Σ = 800 ¥
        infos = _make_mock_infos(3)
        infos.c_demand_charge_yuan = np.array([0.0, 500.0, 300.0])
        streams = _build_streams(infos, _params(demand_rate_yuan_per_mw_month=100.0))
        assert streams["demand_charge"].value_yuan == pytest.approx(800.0, rel=1e-4)  # 0+500+300

    def test_volume_uses_max_not_mean_or_sum(self):
        # [100, 400, 200] → peak = 400/50 = 8 MW  (mean≈4.67, sum/50=14)
        infos = _make_mock_infos(3)
        infos.c_demand_charge_yuan = np.array([100.0, 400.0, 200.0])
        streams = _build_streams(infos, _params(demand_rate_yuan_per_mw_month=50.0))
        assert streams["demand_charge"].volume == pytest.approx(8.0, rel=1e-4)  # 400/50

    def test_demand_charge_zero_when_no_bookings(self):
        infos = _make_mock_infos(100)  # all zeros
        streams = _build_streams(infos, _params())
        assert streams["demand_charge"].volume == pytest.approx(0.0, abs=1e-6)
        assert streams["demand_charge"].value_yuan == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 7. _build_streams: dormant streams always zero in v1
# ---------------------------------------------------------------------------

class TestBuildStreamsDormantZero:
    """h2_sale, avoided_cost, token_sale are always zero regardless of infos content."""

    def test_dormant_streams_zero_with_nontrivial_infos(self):
        # Non-trivial infos — dormant streams must stay zero
        infos = _make_mock_infos(
            24,
            p_wind_mw=100.0, p_pv_mw=50.0,
            p_import_mw=30.0, p_export_mw=20.0,
            c_import_yuan=600.0, r_export_yuan=200.0,
            c_demand_charge_yuan=1000.0,
        )
        streams = _build_streams(infos, _params())
        for key in ("h2_sale", "avoided_cost", "token_sale"):
            assert streams[key].volume == pytest.approx(0.0, abs=1e-9), (
                f"streams['{key}'].volume must be 0.0 in v1"
            )
            assert streams[key].value_yuan == pytest.approx(0.0, abs=1e-9), (
                f"streams['{key}'].value_yuan must be 0.0 in v1"
            )


# ---------------------------------------------------------------------------
# 8. _accumulate_physical_quantities — key count and aggregate fields
# ---------------------------------------------------------------------------

class TestAccumulatePhysicalQuantities:
    """_accumulate_physical_quantities returns exactly 22 keys and correct values."""

    def test_returns_exactly_22_keys(self):
        infos = _make_mock_infos(1)
        acc = _accumulate_physical_quantities(infos)
        assert len(acc) == 22, (
            f"expected 22 keys, got {len(acc)}: {sorted(acc.keys())}"
        )

    def test_generation_mwh_wind_plus_pv(self):
        # 5 steps: p_wind=200, p_pv=100
        # wind_generated = 5×200 = 1000; pv_generated = 5×100 = 500; gen = 1500
        infos = _make_mock_infos(5, p_wind_mw=200.0, p_pv_mw=100.0)
        acc = _accumulate_physical_quantities(infos)
        assert acc["wind_generated_mwh"] == pytest.approx(1000.0, rel=1e-4)  # 5×200
        assert acc["pv_generated_mwh"] == pytest.approx(500.0, rel=1e-4)     # 5×100
        assert acc["generation_mwh"] == pytest.approx(1500.0, rel=1e-4)       # 1000+500

    def test_bat_charge_from_inflow_sources(self):
        # 4 steps: wind_to_bat=10, sol_to_bat=5, grid_to_bat=3
        # bat_charge = 4×(10+5+3) = 4×18 = 72 MWh
        infos = _make_mock_infos(
            4, p_wind_to_bat_mw=10.0, p_sol_to_bat_mw=5.0, p_grid_to_bat_mw=3.0,
        )
        acc = _accumulate_physical_quantities(infos)
        assert acc["bat_charge_mwh"] == pytest.approx(72.0, rel=1e-4)  # 4×18

    def test_bat_discharge_from_outflow_sources(self):
        # 4 steps: bat_to_load=8, bat_to_grid=6, bat_curtailed=2
        # bat_discharge = 4×(8+6+2) = 4×16 = 64 MWh
        infos = _make_mock_infos(
            4, p_bat_to_load_mw=8.0, p_bat_to_grid_mw=6.0, p_bat_curtailed_mw=2.0,
        )
        acc = _accumulate_physical_quantities(infos)
        assert acc["bat_discharge_mwh"] == pytest.approx(64.0, rel=1e-4)  # 4×16

    def test_bat_throughput_charge_plus_discharge(self):
        # charge=72, discharge=64 → throughput=136
        infos = _make_mock_infos(
            4,
            p_wind_to_bat_mw=10.0, p_sol_to_bat_mw=5.0, p_grid_to_bat_mw=3.0,
            p_bat_to_load_mw=8.0,  p_bat_to_grid_mw=6.0, p_bat_curtailed_mw=2.0,
        )
        acc = _accumulate_physical_quantities(infos)
        assert acc["bat_throughput_mwh"] == pytest.approx(136.0, rel=1e-4)  # 72+64

    def test_load_unserved_accumulates_p_load_unserved(self):
        # 5 steps × 3.0 MW = 15 MWh unserved
        infos = _make_mock_infos(5, p_load_unserved_mw=3.0)
        acc = _accumulate_physical_quantities(infos)
        assert acc["load_unserved_mwh"] == pytest.approx(15.0, rel=1e-4)  # 5×3

    def test_curtailed_mwh_accumulates_p_curtailed(self):
        # 8 steps × 12.5 MW = 100 MWh curtailed
        infos = _make_mock_infos(8, p_curtailed_mw=12.5)
        acc = _accumulate_physical_quantities(infos)
        assert acc["curtailed_mwh"] == pytest.approx(100.0, rel=1e-4)  # 8×12.5

    def test_load_served_from_all_to_load_paths(self):
        # 3 steps: wind_to_load=20, sol_to_load=15, bat_to_load=10, grid_to_load=5
        # load_served = 3×(20+15+10+5) = 3×50 = 150 MWh
        infos = _make_mock_infos(
            3,
            p_wind_to_load_mw=20.0, p_sol_to_load_mw=15.0,
            p_bat_to_load_mw=10.0,  p_grid_to_load_mw=5.0,
        )
        acc = _accumulate_physical_quantities(infos)
        assert acc["load_served_mwh"] == pytest.approx(150.0, rel=1e-4)  # 3×50


# ---------------------------------------------------------------------------
# 9. Per-source breakdown (13 fields)
# ---------------------------------------------------------------------------

class TestPerSourceBreakdowns:
    """The 13 per-source MWh fields accumulate their respective EnvInfo fields."""

    def test_wind_per_source_four_fields(self):
        # 3 steps: to_load=10, to_bat=5, to_grid=3, curtailed=2
        # MWh = 3×{10,5,3,2} = {30,15,9,6}
        infos = _make_mock_infos(
            3,
            p_wind_to_load_mw=10.0, p_wind_to_bat_mw=5.0,
            p_wind_to_grid_mw=3.0,  p_wind_curtailed_mw=2.0,
        )
        acc = _accumulate_physical_quantities(infos)
        assert acc["wind_to_load_mwh"] == pytest.approx(30.0, rel=1e-4)   # 3×10
        assert acc["wind_to_bat_mwh"] == pytest.approx(15.0, rel=1e-4)    # 3×5
        assert acc["wind_to_grid_mwh"] == pytest.approx(9.0, rel=1e-4)    # 3×3
        assert acc["wind_curtailed_mwh"] == pytest.approx(6.0, rel=1e-4)  # 3×2

    def test_pv_per_source_four_fields_sol_to_pv_rename(self):
        # EnvInfo uses p_sol_*; result uses pv_* (§2 contract mapping)
        # 4 steps: to_load=8, to_bat=4, to_grid=2, curtailed=1
        # MWh = 4×{8,4,2,1} = {32,16,8,4}
        infos = _make_mock_infos(
            4,
            p_sol_to_load_mw=8.0,  p_sol_to_bat_mw=4.0,
            p_sol_to_grid_mw=2.0,  p_sol_curtailed_mw=1.0,
        )
        acc = _accumulate_physical_quantities(infos)
        assert acc["pv_to_load_mwh"] == pytest.approx(32.0, rel=1e-4)    # 4×8
        assert acc["pv_to_bat_mwh"] == pytest.approx(16.0, rel=1e-4)     # 4×4
        assert acc["pv_to_grid_mwh"] == pytest.approx(8.0, rel=1e-4)     # 4×2
        assert acc["pv_curtailed_mwh"] == pytest.approx(4.0, rel=1e-4)   # 4×1

    def test_bat_per_source_three_fields(self):
        # 5 steps: to_load=6, to_grid=3, curtailed=1
        # MWh = 5×{6,3,1} = {30,15,5}
        infos = _make_mock_infos(
            5, p_bat_to_load_mw=6.0, p_bat_to_grid_mw=3.0, p_bat_curtailed_mw=1.0,
        )
        acc = _accumulate_physical_quantities(infos)
        assert acc["bat_to_load_mwh"] == pytest.approx(30.0, rel=1e-4)   # 5×6
        assert acc["bat_to_grid_mwh"] == pytest.approx(15.0, rel=1e-4)   # 5×3
        assert acc["bat_curtailed_mwh"] == pytest.approx(5.0, rel=1e-4)  # 5×1

    def test_grid_per_source_two_fields(self):
        # 2 steps: to_bat=50, to_load=100 → MWh = {100,200}
        infos = _make_mock_infos(2, p_grid_to_bat_mw=50.0, p_grid_to_load_mw=100.0)
        acc = _accumulate_physical_quantities(infos)
        assert acc["grid_to_bat_mwh"] == pytest.approx(100.0, rel=1e-4)  # 2×50
        assert acc["grid_to_load_mwh"] == pytest.approx(200.0, rel=1e-4) # 2×100


# ---------------------------------------------------------------------------
# 10. Conservation identities (§6 contract — identities 1,2,3,5,6,7,8)
# ---------------------------------------------------------------------------

class TestConservationIdentities:
    """Per-source energy conservation and accumulator decomposition identities."""

    def test_identity_1_wind_source_conservation(self):
        # wind_generated = wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed
        # 6 steps: p_wind=20 = to_load10 + to_bat4 + to_grid3 + curtailed3
        # wind_generated=120; sum=60+24+18+18=120 ✓
        infos = _make_mock_infos(
            6,
            p_wind_mw=20.0,
            p_wind_to_load_mw=10.0, p_wind_to_bat_mw=4.0,
            p_wind_to_grid_mw=3.0,  p_wind_curtailed_mw=3.0,
        )
        acc = _accumulate_physical_quantities(infos)
        lhs = acc["wind_generated_mwh"]  # 6×20 = 120
        rhs = (acc["wind_to_load_mwh"] + acc["wind_to_bat_mwh"]
             + acc["wind_to_grid_mwh"] + acc["wind_curtailed_mwh"])  # 60+24+18+18
        assert lhs == pytest.approx(120.0, rel=1e-4)
        assert lhs == pytest.approx(rhs, rel=1e-4)

    def test_identity_2_pv_source_conservation(self):
        # pv_generated = pv_to_load + pv_to_bat + pv_to_grid + pv_curtailed
        # 4 steps: p_pv=15 = to_load8 + to_bat4 + to_grid2 + curtailed1
        # pv_generated=60; sum=32+16+8+4=60 ✓
        infos = _make_mock_infos(
            4,
            p_pv_mw=15.0,
            p_sol_to_load_mw=8.0, p_sol_to_bat_mw=4.0,
            p_sol_to_grid_mw=2.0, p_sol_curtailed_mw=1.0,
        )
        acc = _accumulate_physical_quantities(infos)
        lhs = acc["pv_generated_mwh"]   # 4×15 = 60
        rhs = (acc["pv_to_load_mwh"] + acc["pv_to_bat_mwh"]
             + acc["pv_to_grid_mwh"] + acc["pv_curtailed_mwh"])  # 32+16+8+4
        assert lhs == pytest.approx(60.0, rel=1e-4)
        assert lhs == pytest.approx(rhs, rel=1e-4)

    def test_identity_3_bat_discharge_conservation(self):
        # bat_discharge = bat_to_load + bat_to_grid + bat_curtailed
        # 5 steps: dis=6+3+1=10 → bat_discharge=50; 30+15+5=50 ✓
        infos = _make_mock_infos(
            5, p_bat_to_load_mw=6.0, p_bat_to_grid_mw=3.0, p_bat_curtailed_mw=1.0,
        )
        acc = _accumulate_physical_quantities(infos)
        lhs = acc["bat_discharge_mwh"]   # 5×10 = 50
        rhs = (acc["bat_to_load_mwh"] + acc["bat_to_grid_mwh"] + acc["bat_curtailed_mwh"])
        assert lhs == pytest.approx(50.0, rel=1e-4)
        assert lhs == pytest.approx(rhs, rel=1e-4)

    def test_identity_5_generation_decomposition(self):
        # generation_mwh = wind_generated_mwh + pv_generated_mwh (exact)
        # 3 steps: p_wind=100, p_pv=60 → gen=480; 300+180=480 ✓
        infos = _make_mock_infos(3, p_wind_mw=100.0, p_pv_mw=60.0)
        acc = _accumulate_physical_quantities(infos)
        assert acc["generation_mwh"] == pytest.approx(
            acc["wind_generated_mwh"] + acc["pv_generated_mwh"], rel=1e-4
        )  # 300+180 = 480

    def test_identity_6_bat_throughput_decomposition(self):
        # bat_throughput = bat_charge + bat_discharge; charge=72, discharge=64 → 136
        infos = _make_mock_infos(
            4,
            p_wind_to_bat_mw=10.0, p_sol_to_bat_mw=5.0, p_grid_to_bat_mw=3.0,
            p_bat_to_load_mw=8.0,  p_bat_to_grid_mw=6.0, p_bat_curtailed_mw=2.0,
        )
        acc = _accumulate_physical_quantities(infos)
        assert acc["bat_throughput_mwh"] == pytest.approx(
            acc["bat_charge_mwh"] + acc["bat_discharge_mwh"], rel=1e-4
        )  # 72+64 = 136

    def test_identity_7_aggregate_curtailed_equals_per_source_sum(self):
        # curtailed_mwh = wind_curtailed + pv_curtailed + bat_curtailed
        # 3 steps: total=15 = wind6 + pv5 + bat4 → curtailed=45; 18+15+12=45 ✓
        infos = _make_mock_infos(
            3,
            p_curtailed_mw=15.0,
            p_wind_curtailed_mw=6.0, p_sol_curtailed_mw=5.0, p_bat_curtailed_mw=4.0,
        )
        acc = _accumulate_physical_quantities(infos)
        lhs = acc["curtailed_mwh"]   # 3×15 = 45
        rhs = (acc["wind_curtailed_mwh"]   # 3×6 = 18
             + acc["pv_curtailed_mwh"]     # 3×5 = 15
             + acc["bat_curtailed_mwh"])   # 3×4 = 12
        assert lhs == pytest.approx(45.0, rel=1e-4)
        assert lhs == pytest.approx(rhs, rel=1e-4)

    def test_identity_8_grid_import_volume_equals_to_bat_plus_to_load(self):
        # streams["grid_import"].volume = grid_to_bat_mwh + grid_to_load_mwh (§3.6 F-IMPORT)
        # 5 steps: p_import=80 = to_bat30 + to_load50 → import=400; 150+250=400 ✓
        infos = _make_mock_infos(
            5, p_import_mw=80.0, p_grid_to_bat_mw=30.0, p_grid_to_load_mw=50.0,
        )
        streams = _build_streams(infos, _params())
        acc = _accumulate_physical_quantities(infos)
        lhs = streams["grid_import"].volume    # 5×80 = 400
        rhs = acc["grid_to_bat_mwh"] + acc["grid_to_load_mwh"]  # 150+250
        assert lhs == pytest.approx(400.0, rel=1e-4)
        assert lhs == pytest.approx(rhs, rel=1e-4)


# ---------------------------------------------------------------------------
# 11. D13 cost identity — identity 4 (§6 contract)
# ---------------------------------------------------------------------------

class TestD13CostIdentity:
    """energy_cost_yuan == streams["grid_import"].value_yuan - streams["grid_export"].value_yuan.

    D13: c_energy_yuan = c_import_yuan - r_export_yuan per step.
    Summing: Σ c_energy = Σ c_import - Σ r_export
           = grid_import.value_yuan - grid_export.value_yuan.
    """

    def test_d13_with_both_import_and_export(self):
        # 10 steps: c_import=500¥, r_export=100¥, c_energy=400¥ per step
        # energy_cost_yuan = 10×400 = 4000
        # grid_import.value_yuan = 10×500 = 5000; grid_export = 10×100 = 1000
        # identity: 4000 == 5000 - 1000 ✓
        infos = _make_mock_infos(
            10, c_energy_yuan=400.0, c_import_yuan=500.0, r_export_yuan=100.0,
        )
        streams = _build_streams(infos, _params())
        energy_cost = float(np.sum(infos.c_energy_yuan))   # 10×400 = 4000
        assert energy_cost == pytest.approx(4000.0, rel=1e-4)
        assert streams["grid_import"].value_yuan == pytest.approx(5000.0, rel=1e-4)
        assert streams["grid_export"].value_yuan == pytest.approx(1000.0, rel=1e-4)
        d13_rhs = streams["grid_import"].value_yuan - streams["grid_export"].value_yuan
        assert energy_cost == pytest.approx(d13_rhs, rel=1e-4)

    def test_d13_net_revenue_when_export_only(self):
        # 5 steps: c_import=0, r_export=200¥, c_energy=-200¥ (net revenue)
        # energy_cost_yuan = -1000; 0 - 1000 = -1000 ✓
        infos = _make_mock_infos(
            5, c_energy_yuan=-200.0, c_import_yuan=0.0, r_export_yuan=200.0,
        )
        streams = _build_streams(infos, _params())
        energy_cost = float(np.sum(infos.c_energy_yuan))  # -1000
        d13_rhs = streams["grid_import"].value_yuan - streams["grid_export"].value_yuan
        assert energy_cost == pytest.approx(-1000.0, rel=1e-4)
        assert d13_rhs == pytest.approx(-1000.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 12. Wire isolation — _policy_dict returns exactly the 9 LOCKED keys
# ---------------------------------------------------------------------------

_LOCKED_WIRE_KEYS = frozenset({
    "energy_cost_yuan", "demand_charge_yuan", "degradation_yuan",
    "curtailment_yuan", "voll_yuan", "total_cost_yuan",
    "soc_violations_count", "soc_violation_mwh", "penalty_yuan",
})


def _make_full_result() -> PolicyEvalResult:
    """Non-trivial PolicyEvalResult — ensures new fields don't accidentally appear in wire."""
    _z = StreamAccumulator(volume=0.0, value_yuan=0.0)
    return PolicyEvalResult(
        energy_cost_yuan=100.0, demand_charge_yuan=320000.0, degradation_yuan=50.0,
        curtailment_yuan=20.0, voll_yuan=0.0, total_cost_yuan=320170.0,
        # total = 100+320000+50+20+0 = 320170 ✓
        soc_violations_count=2, soc_violation_mwh=0.1, penalty_yuan=5.0,
        streams={
            "grid_export":   StreamAccumulator(volume=500.0, value_yuan=40.0),
            "grid_import":   StreamAccumulator(volume=300.0, value_yuan=140.0),
            "demand_charge": StreamAccumulator(volume=5.0,   value_yuan=320000.0),
            "h2_sale": _z, "avoided_cost": _z, "token_sale": _z,
        },
        generation_mwh=9050.0, wind_generated_mwh=7000.0, pv_generated_mwh=2050.0,
        bat_charge_mwh=800.0, bat_discharge_mwh=780.0, bat_throughput_mwh=1580.0,
        load_served_mwh=8100.0, load_unserved_mwh=0.0, curtailed_mwh=25.0,
        wind_to_load_mwh=5000.0, wind_to_bat_mwh=500.0,
        wind_to_grid_mwh=1400.0, wind_curtailed_mwh=100.0,
        pv_to_load_mwh=1500.0,  pv_to_bat_mwh=300.0,
        pv_to_grid_mwh=225.0,   pv_curtailed_mwh=25.0,
        bat_to_load_mwh=700.0,  bat_to_grid_mwh=75.0, bat_curtailed_mwh=5.0,
        grid_to_bat_mwh=0.0,    grid_to_load_mwh=900.0,
    )


class TestWireIsolation:
    """_policy_dict serialises ONLY the 9 LOCKED keys — new fields must NOT leak."""

    def test_wire_has_exactly_9_locked_keys(self):
        wire = _policy_dict(_make_full_result())
        assert set(wire.keys()) == _LOCKED_WIRE_KEYS, (
            f"expected {_LOCKED_WIRE_KEYS}, got {set(wire.keys())}"
        )

    def test_streams_key_not_in_wire(self):
        wire = _policy_dict(_make_full_result())
        assert "streams" not in wire

    def test_no_mwh_fields_in_wire(self):
        # reviewer: backend-reviewer — narrow the suffix guard to the one LOCKED
        # _mwh wire field. `soc_violation_mwh` (contract eval_result_extended.md
        # lines 70-81) is one of the 9 LOCKED wire keys — a penalty/violation
        # diagnostic, NOT one of the 22 new physical-quantity accumulators. The
        # original blanket suffix filter contradicted the locked 9-key schema
        # (test_wire_has_exactly_9_locked_keys), making the two tests jointly
        # unsatisfiable. Exempt ONLY soc_violation_mwh (not all locked keys) so
        # this stays an independent guard that still catches a NEW physical-qty
        # _mwh/_mw field even if one were wrongly added to _LOCKED_WIRE_KEYS.
        _WIRE_QTY_EXEMPT = {"soc_violation_mwh"}
        wire = _policy_dict(_make_full_result())
        leaked = [
            k for k in wire
            if (k.endswith("_mwh") or k.endswith("_mw")) and k not in _WIRE_QTY_EXEMPT
        ]
        assert leaked == [], f"physical-qty fields leaked to wire: {leaked}"

    def test_locked_field_values_pass_through_unchanged(self):
        result = _make_full_result()
        wire = _policy_dict(result)
        assert wire["energy_cost_yuan"] == pytest.approx(100.0, rel=1e-4)
        assert wire["demand_charge_yuan"] == pytest.approx(320000.0, rel=1e-4)
        assert wire["total_cost_yuan"] == pytest.approx(320170.0, rel=1e-4)
        assert wire["soc_violations_count"] == 2


# ---------------------------------------------------------------------------
# 13. Reviewer-added cases (backend-reviewer @ 81c02c9, adapted to v3 stream API)
# ---------------------------------------------------------------------------

class TestReviewerCases:
    """Cases added by backend-reviewer at review commit 81c02c9.

    Physics assertions are unchanged.  In v3, grid_import volume moves from
    r["grid_import_mwh"] (flat dict) to streams["grid_import"].volume (stream dict)
    per rl-architect architectural ruling (#82 gate).
    """

    def test_aggregate_curtailed_equals_per_source_sum(self):
        """# reviewer: backend-reviewer
        Aggregate curtailed MWh must equal sum of per-source curtailed MWh.
        4 steps: p_curtailed=25 = wind_curt 10 + pv_curt 10 + bat_curt 5
        → curtailed_mwh = 4×25 = 100
        → wind_curtailed+pv_curtailed+bat_curtailed = 40+40+20 = 100 ✓
        """
        infos = _make_mock_infos(
            4,
            p_curtailed_mw=25.0,
            p_wind_curtailed_mw=10.0,
            p_sol_curtailed_mw=10.0,
            p_bat_curtailed_mw=5.0,
        )
        acc = _accumulate_physical_quantities(infos)
        lhs = acc["curtailed_mwh"]            # 4×25 = 100
        rhs = (acc["wind_curtailed_mwh"]      # 4×10 = 40
             + acc["pv_curtailed_mwh"]        # 4×10 = 40
             + acc["bat_curtailed_mwh"])       # 4×5  = 20
        assert lhs == pytest.approx(100.0, rel=1e-4)
        assert lhs == pytest.approx(rhs, rel=1e-4)

    def test_grid_import_volume_equals_to_bat_plus_to_load(self):
        """# reviewer: backend-reviewer (v3: grid_import.volume from streams dict)
        Grid import volume (streams["grid_import"].volume) must equal
        grid_to_bat_mwh + grid_to_load_mwh per §3.6 F-IMPORT row 9.
        6 steps: p_import=150 = grid_to_bat 50 + grid_to_load 100
        → streams["grid_import"].volume = 6×150 = 900 MWh
        → grid_to_bat_mwh + grid_to_load_mwh = 300+600 = 900 ✓
        """
        infos = _make_mock_infos(
            6,
            p_import_mw=150.0,
            p_grid_to_bat_mw=50.0,
            p_grid_to_load_mw=100.0,
        )
        streams = _build_streams(infos, _params())
        acc = _accumulate_physical_quantities(infos)
        lhs = streams["grid_import"].volume                         # 6×150 = 900
        rhs = acc["grid_to_bat_mwh"] + acc["grid_to_load_mwh"]    # 300+600 = 900
        assert lhs == pytest.approx(900.0, rel=1e-4)
        assert lhs == pytest.approx(rhs, rel=1e-4)
