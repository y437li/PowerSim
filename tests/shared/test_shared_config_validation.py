"""Tests for the config_validation shared contract (task #66).

Contract: contracts/shared/config_validation.md
Spec refs: REBUILD_SPEC §3.6; LINEAGE D26, D18, D32(i)
Owner: jax-env-engineer (physics rules), finance-expert (econ rules)

All expected values are hand-computed with arithmetic in comments.
Tests are RED until implementation in src/energy_go/env/config_validation.py.
"""

import math
import pytest

# Gansu base config — produces validate() -> (errors=[], warnings=[]) by design.
# See contracts/shared/device_model_schema.md §7 for field mapping.
GANSU_SITE = {
    "assets": {
        "wind": {
            "model": "vestas-v150-4.2",
            "fleet_rated_mw": 615.0,
        },
        "solar": {
            "model": "trina-vertex-n-670w",
            "fleet_capacity_mw": 330.0,
        },
        "battery": {
            "model": "catl-lmp-300mwh",
            "fleet_capacity_mwh": 294.5,
            "fleet_power_mw": 98.16,
        },
        "grid": {
            "model": "pcc-substation-945mw",
        },
    },
    "tariff": {
        "price_table_yuan_per_mwh": [
            250, 250, 250, 250, 250, 250, 250,  # h=0-6 valley
            450,                                 # h=7 mid
            620, 620, 620,                       # h=8-10 peak
            780,                                 # h=11 critical
            450, 450, 450, 450, 450, 450,        # h=12-17 mid
            620,                                 # h=18 peak
            780, 780,                            # h=19-20 critical
            620, 620,                            # h=21-22 peak
            250,                                 # h=23 valley
        ],
    },
    "costs": {
        "c_deg_yuan_per_mwh": 10.0,
        "voll_yuan_per_mwh": 20000.0,
        "curtail_yuan_per_mwh": 800.0,
        "demand_rate_yuan_per_mw_month": 32000.0,
        "soc_penalty_yuan_per_mwh": 20000.0,
        "reward_scale": 1.0e-5,
        "price_spread_yuan_per_mwh": 30.0,
        "price_spread_sigma": 10.0,
    },
    "forecast": {
        "sigma_max": 0.10,
    },
}

# Gansu device models — populated economics from v1.1.0 (PR #86).
GANSU_MODELS = {
    "schema_version": "1.1.0",
    "models": {
        "vestas-v150-4.2": {
            "type": "wind_turbine",
            "physics": {
                "v_cutin_mps": 3.0,
                "v_rated_mps": 12.0,
                "v_cutout_mps": 25.0,
                "hub_height_m": 105.0,
                "rated_mw_per_unit": 4.2,
            },
            "economics": {
                "capex_per_kw_yuan": 5800.0,
                "opex_fixed_per_kw_year_yuan": 180.0,
                "opex_var_per_mwh_yuan": 0.0,
                "lifetime_years": 25.0,
                "replacement_cost_fraction": 0.15,
                "residual_value_fraction": 0.05,
                "construction_months": 18.0,
                "decommissioning_cost_per_kw_yuan": 100.0,
            },
        },
        "trina-vertex-n-670w": {
            "type": "pv_panel",
            "physics": {
                "k_T_per_c": -0.003,
                "eta_inverter": 0.97,
                "degradation_yr1": 0.98,
            },
            "economics": {
                "capex_per_kw_yuan": 3200.0,
                "opex_fixed_per_kw_year_yuan": 80.0,
                "opex_var_per_mwh_yuan": 0.0,
                "lifetime_years": 25.0,
                "replacement_cost_fraction": 0.20,
                "residual_value_fraction": 0.02,
                "construction_months": 12.0,
                "decommissioning_cost_per_kw_yuan": 60.0,
            },
        },
        "catl-lmp-300mwh": {
            "type": "battery",
            "physics": {
                "eta_ch": 0.97,
                "eta_dis": 0.97,
                "soc_min": 0.2,
                "soc_max": 0.9,
                "capacity_mwh_per_unit": 300.0,
                "power_mw_per_unit": 100.0,
            },
            "economics": {
                "capex_energy_per_kwh_yuan": 1000.0,
                "capex_power_per_kw_yuan": 0.0,
                "opex_fixed_per_kwh_year_yuan": 20.0,
                "opex_var_per_mwh_yuan": 0.0,
                "lifetime_years": 12.0,
                "cycle_life_full_equiv": 6000.0,
                "eol_soh_threshold": 0.80,
                "replacement_cost_fraction": 0.70,
                "residual_value_fraction": 0.05,
                "construction_months": 6.0,
                "decommissioning_cost_per_kwh_yuan": 30.0,
            },
        },
        "pcc-substation-945mw": {
            "type": "grid_connection",
            "physics": {
                "max_export_mw": 945.0,
                "max_import_mw": 400.0,
            },
            "economics": {
                "capex_lump_sum_yuan": 0.0,
                "opex_fixed_per_mw_year_yuan": 5000.0,
                "lifetime_years": 40.0,
                "residual_value_fraction": 0.10,
                "decommissioning_cost_yuan": 0.0,
            },
        },
    },
}


# Gansu device models at schema_version 2.0.0 — mirrors device_models.yaml on main.
# Used for D33 fix tests: the live file has schema_version="2.0.0" and the flat (24,)
# tariff in site_gansu.yaml must NOT produce E-TAR-SHAPE under v2.0+ rules.
GANSU_MODELS_V2 = {
    "schema_version": "2.0.0",
    "models": {
        k: v for k, v in GANSU_MODELS["models"].items()
    },
}


def _import_validate():
    """Import validate() — test is skipped if module not yet implemented."""
    pytest.importorskip("energy_go.env.config_validation")
    from energy_go.env.config_validation import validate
    return validate


def _import_all():
    """Import all public symbols. Skips if not yet implemented."""
    mod = pytest.importorskip("energy_go.env.config_validation")
    return mod


import copy


class TestGansuPassesClean:
    """Gansu baseline: validate() must return (errors=[], warnings=[])."""

    def test_gansu_no_errors(self):
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        assert result.errors == [], (
            f"Gansu config must produce no hard errors; got: {result.errors}"
        )

    def test_gansu_no_warnings(self):
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        assert result.warnings == [], (
            f"Gansu config must produce no warnings; got: {result.warnings}"
        )

    def test_gansu_no_device_models_no_crash(self):
        """validate(site, device_models=None) must not raise."""
        validate = _import_validate()
        result = validate(GANSU_SITE, None)
        # Device-dependent rules skipped — no crash
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)


class TestValidationIssueShape:
    """Each ValidationIssue must have exactly the 4 NamedTuple fields."""

    def test_issue_fields(self):
        mod = _import_all()
        issue = mod.ValidationIssue(
            rule_id="E-CAP-POS",
            field="assets.battery.fleet_capacity_mwh",
            message="fleet_capacity_mwh must be > 0",
            constraint="fleet_capacity_mwh = -10.0 MWh — must be > 0",
        )
        assert issue.rule_id == "E-CAP-POS"
        assert issue.field == "assets.battery.fleet_capacity_mwh"
        assert isinstance(issue.message, str)
        assert isinstance(issue.constraint, str)

    def test_validation_result_fields(self):
        mod = _import_all()
        result = mod.ValidationResult(errors=[], warnings=[])
        assert result.errors == []
        assert result.warnings == []


class TestECapPos:
    """E-CAP-POS: non-positive physical capacity → hard error."""

    def test_battery_capacity_zero(self):
        # fleet_capacity_mwh = 0.0 → ≤ 0 → ERROR
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_capacity_mwh"] = 0.0
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in ids, f"Expected E-CAP-POS in errors; got {result.errors}"
        fields = [e.field for e in result.errors]
        assert any("fleet_capacity_mwh" in f for f in fields)

    def test_battery_capacity_negative(self):
        # fleet_capacity_mwh = -10.0 → ERROR
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_capacity_mwh"] = -10.0
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in ids

    def test_battery_power_negative(self):
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = -1.0
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in ids

    def test_wind_rated_zero(self):
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["wind"]["fleet_rated_mw"] = 0.0
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in ids

    def test_solar_capacity_negative(self):
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["solar"]["fleet_capacity_mw"] = -5.0
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in ids

    def test_exhaustive_collects_multiple(self):
        """All negative fields produce separate issues, not just the first."""
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_capacity_mwh"] = -1.0
        site["assets"]["wind"]["fleet_rated_mw"] = -1.0
        result = validate(site, GANSU_MODELS)
        cap_errors = [e for e in result.errors if e.rule_id == "E-CAP-POS"]
        assert len(cap_errors) >= 2, (
            "Both negative fields must produce separate E-CAP-POS issues"
        )


class TestEBatCrate:
    """E-BAT-CRATE: fleet C-rate > device per-unit C-rate → hard error.

    Device: catl-lmp-300mwh, power_mw_per_unit=100.0, capacity_mwh_per_unit=300.0
    Device C-rate = 100.0 / 300.0 = 0.3333 C
    """

    def test_fleet_crate_ok(self):
        # Gansu: 98.16/294.5 = 0.3332 C ≤ 0.3333 C → no error
        # Arithmetic: 98.16/294.5 = 0.33327...  100.0/300.0 = 0.33333...
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-BAT-CRATE" not in ids

    def test_fleet_crate_exceeds_device(self):
        # fleet_power_mw = 200.0, fleet_capacity_mwh = 294.5
        # fleet C-rate = 200.0 / 294.5 = 0.679 C
        # device C-rate = 100.0 / 300.0 = 0.333 C
        # 0.679 > 0.333 → ERROR
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 200.0
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-BAT-CRATE" in ids, (
            "fleet_power=200.0 / fleet_cap=294.5 = 0.679C "
            "> device 100.0/300.0 = 0.333C must be E-BAT-CRATE error"
        )

    def test_fleet_crate_just_below_device_no_error(self):
        # fleet_power_mw = 98.0, fleet_capacity_mwh = 300.0 (= device per-unit exactly)
        # fleet C-rate = 98.0/300.0 = 0.3267 C < 0.3333 C → no error
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 98.0
        site["assets"]["battery"]["fleet_capacity_mwh"] = 300.0
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-BAT-CRATE" not in ids

    def test_crate_skipped_without_device_models(self):
        """Without device_models, E-BAT-CRATE is silently skipped (not errored)."""
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 200.0  # would error with models
        result = validate(site, None)
        ids = [e.rule_id for e in result.errors]
        assert "E-BAT-CRATE" not in ids

    def test_constraint_contains_numbers(self):
        """constraint field must include actual MW/MWh/C-rate numbers."""
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 200.0
        result = validate(site, GANSU_MODELS)
        crate_errors = [e for e in result.errors if e.rule_id == "E-BAT-CRATE"]
        assert crate_errors, "Expected E-BAT-CRATE error"
        # constraint must contain numeric values (MW or C)
        assert any(ch.isdigit() for ch in crate_errors[0].constraint)


class TestEBatUnit:
    """E-BAT-UNIT: explicit unit_count inconsistent with fleet sizing.

    device: capacity_mwh_per_unit=300.0, power_mw_per_unit=100.0
    """

    def test_no_explicit_unit_count_skipped(self):
        # Gansu has no explicit unit_count → rule skipped
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-BAT-UNIT" not in ids

    def test_explicit_unit_count_consistent(self):
        # unit_count=1, fleet_capacity_mwh=294.5
        # energy check: abs(1*300.0 - 294.5)/294.5 = 5.5/294.5 = 0.0187 = 1.87% > 1%
        # Hmm, that's > 1%... let me use fleet_capacity_mwh=300.0 exactly.
        # unit_count=1, fleet=300.0 → abs(1*300.0 - 300.0)/300.0 = 0% → OK
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["unit_count"] = 1
        site["assets"]["battery"]["fleet_capacity_mwh"] = 300.0
        site["assets"]["battery"]["fleet_power_mw"] = 100.0
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-BAT-UNIT" not in ids

    def test_explicit_unit_count_energy_inconsistent(self):
        # unit_count=5, fleet_capacity_mwh=294.5, device.capacity_mwh_per_unit=300.0
        # energy check: abs(5*300.0 - 294.5)/294.5 = abs(1500-294.5)/294.5 = 1205.5/294.5 = 4.094 = 409% >> 1%
        # → E-BAT-UNIT ERROR
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["unit_count"] = 5
        site["assets"]["battery"]["fleet_capacity_mwh"] = 294.5
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-BAT-UNIT" in ids, (
            "unit_count=5 with fleet_cap=294.5MWh vs 5×300=1500MWh must be E-BAT-UNIT"
        )

    def test_explicit_unit_count_just_outside_tolerance(self):
        # unit_count=2, fleet_capacity_mwh=594.0
        # energy check: abs(2*300.0 - 594.0)/594.0 = abs(600-594)/594 = 6/594 = 0.0101 = 1.01% > 1%
        # → E-BAT-UNIT ERROR (just outside 1% tolerance)
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["unit_count"] = 2
        site["assets"]["battery"]["fleet_capacity_mwh"] = 594.0
        site["assets"]["battery"]["fleet_power_mw"] = 200.0
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-BAT-UNIT" in ids, (
            "unit_count=2, 2×300=600 vs fleet=594 → 1.01% > 1% tolerance → E-BAT-UNIT"
        )

    def test_unit_count_skipped_without_device_models(self):
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["unit_count"] = 5  # would error with models
        result = validate(site, None)
        ids = [e.rule_id for e in result.errors]
        assert "E-BAT-UNIT" not in ids


class TestETarShape:
    """E-TAR-SHAPE: tariff table must be exactly 24 entries (v1 flat format)."""

    def test_24_entries_ok(self):
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" not in ids

    def test_wrong_length_12(self):
        # 12 entries instead of 24 → ERROR
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["tariff"]["price_table_yuan_per_mwh"] = [300.0] * 12
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" in ids, "12-entry tariff must produce E-TAR-SHAPE"

    def test_wrong_length_25(self):
        # 25 entries instead of 24 → ERROR
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["tariff"]["price_table_yuan_per_mwh"] = [300.0] * 25
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" in ids, "25-entry tariff must produce E-TAR-SHAPE"

    def test_empty_tariff(self):
        # 0 entries → ERROR
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["tariff"]["price_table_yuan_per_mwh"] = []
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" in ids


class TestETarShapeV2:
    """E-TAR-SHAPE v2.0+ rules (D33 fix): flat (24,) OR seasonal (12,24) both accepted.

    The coverage gap that hid the live bug: no test exercised schema_version=2.0.0
    against a flat (24,) tariff.  These tests pin the relaxed acceptance set.
    """

    # reviewer: backend-reviewer (D33 gap — schema 2.0.0 + flat (24,) → must be OK)
    def test_v2_flat_24_ok(self):
        # D33 fix: schema_version=2.0.0 + flat (24,) tariff → NO E-TAR-SHAPE.
        # Regression guard: this is the exact combination that was broken on main
        # (device_models.yaml@2.0.0 + site_gansu.yaml flat (24,) → live E-TAR-SHAPE error).
        # resolver.py L221-229 accepts flat (24,) and replicates ×12; validator must agree.
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS_V2)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" not in ids, (
            "schema_version=2.0.0 + flat (24,) tariff must NOT produce E-TAR-SHAPE "
            "(resolver.py replicates ×12 — validator must accept what the resolver broadcasts)"
        )

    # reviewer: backend-reviewer (D33 — seasonal (12,24) must also pass under v2)
    def test_v2_seasonal_12x24_ok(self):
        # schema_version=2.0.0 + (12,24) nested list → NO E-TAR-SHAPE.
        # This is the canonical v2 format from the POST /api/site/validate endpoint.
        # Each of the 12 rows is a copy of the Gansu TOU profile.
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        flat_row = site["tariff"]["price_table_yuan_per_mwh"]   # 24 scalars
        site["tariff"]["price_table_yuan_per_mwh"] = [list(flat_row) for _ in range(12)]
        result = validate(site, GANSU_MODELS_V2)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" not in ids, (
            "schema_version=2.0.0 + (12,24) seasonal table must NOT produce E-TAR-SHAPE"
        )

    # reviewer: backend-reviewer (D33 — wrong flat length under v2 must still error)
    def test_v2_wrong_flat_length_errors(self):
        # schema_version=2.0.0 + flat (11,) — neither flat-24 nor (12,24) → ERROR.
        # Arithmetic: len=11 ≠ 24 and not a (12,24) matrix.
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["tariff"]["price_table_yuan_per_mwh"] = [300.0] * 11
        result = validate(site, GANSU_MODELS_V2)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" in ids, (
            "schema_version=2.0.0 + flat (11,) tariff — not flat-24 nor (12,24) → E-TAR-SHAPE"
        )

    # reviewer: backend-reviewer (D33 — wrong nested shape under v2 must still error)
    def test_v2_wrong_seasonal_shape_errors(self):
        # schema_version=2.0.0 + 12 rows of 23 elements → not (12,24) and not flat-24 → ERROR.
        # Arithmetic: 12 rows × 23 cols ≠ (12,24).
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["tariff"]["price_table_yuan_per_mwh"] = [[300.0] * 23 for _ in range(12)]
        result = validate(site, GANSU_MODELS_V2)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" in ids, (
            "schema_version=2.0.0 + (12,23) table — wrong row width → E-TAR-SHAPE"
        )

    # reviewer: backend-reviewer (D33 — wrong row count under v2 must still error)
    def test_v2_wrong_row_count_errors(self):
        # schema_version=2.0.0 + 11 rows of 24 elements → not (12,24) and not flat-24 → ERROR.
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["tariff"]["price_table_yuan_per_mwh"] = [[300.0] * 24 for _ in range(11)]
        result = validate(site, GANSU_MODELS_V2)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" in ids, (
            "schema_version=2.0.0 + (11,24) table — wrong row count → E-TAR-SHAPE"
        )

    # reviewer: backend-reviewer (D33 — flat len-23 is still wrong under v2)
    def test_v2_flat_len23(self):
        # schema_version=2.0.0 + flat (23,) list — one short of the legal flat-24 form → ERROR.
        # Arithmetic: len=23 ≠ 24 (not flat-24) and not a nested list (not (12,24)) → E-TAR-SHAPE.
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["tariff"]["price_table_yuan_per_mwh"] = [300.0] * 23
        result = validate(site, GANSU_MODELS_V2)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" in ids, (
            "schema_version=2.0.0 + flat (23,) — one short of valid flat-24 → E-TAR-SHAPE"
        )

    def test_v2_no_device_models_no_e_tar_shape(self):
        # Without device_models, v2 branch is unreachable — check falls back to v1 (len==24).
        # Gansu flat (24,) → no error even under v1 path.
        validate = _import_validate()
        result = validate(GANSU_SITE, None)
        ids = [e.rule_id for e in result.errors]
        assert "E-TAR-SHAPE" not in ids

    # reviewer: backend-reviewer (D33 highest-value regression — end-to-end with live files)
    def test_real_gansu_config_validates_no_tar_shape(self):
        # Load the ACTUAL repo files (config/site_gansu.yaml + config/device_models.yaml).
        # live device_models.yaml is schema_version=2.0.0; site_gansu.yaml has a flat (24,) tariff.
        # This is the exact configuration that was broken on main before D33.
        # (a) validate() must return no E-TAR-SHAPE.
        # (b) resolve_site() must not raise ConfigValidationError (tested via import guard below).
        import pathlib
        import yaml as _yaml
        validate = _import_validate()
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        site_path   = repo_root / "config" / "site_gansu.yaml"
        models_path = repo_root / "config" / "device_models.yaml"
        site   = _yaml.safe_load(open(site_path))
        models = _yaml.safe_load(open(models_path))
        # Confirm the live file is still v2.0.0 (pin the schema so regressions are caught)
        assert models.get("schema_version", "").startswith("2."), (
            f"device_models.yaml is expected to be schema v2.x; got {models.get('schema_version')}"
        )
        # (a) validate() — no JAX required; must return no E-TAR-SHAPE
        result = validate(site, models)
        tar_errors = [e for e in result.errors if e.rule_id == "E-TAR-SHAPE"]
        assert not tar_errors, (
            f"Live site_gansu.yaml + device_models.yaml@2.0.0 must NOT produce E-TAR-SHAPE "
            f"(D33 regression guard); got: {tar_errors}"
        )
        # (b) resolve_site() — JAX-gated; if JAX is available, resolve must not raise
        # ConfigValidationError (which would indicate the validator↔resolver parity is broken)
        try:
            import importlib
            resolver_mod = importlib.import_module("energy_go.env.resolver")
            resolver_mod.resolve_site(str(site_path), str(models_path))
        except RuntimeError as exc:
            if "AVX" in str(exc) or "cpu_feature" in str(exc) or "jaxlib" in str(exc):
                pass  # JAX not available on this platform — (a) is the binding guard
            else:
                raise
        except Exception as exc:
            from energy_go.env.config_validation import ConfigValidationError
            if isinstance(exc, ConfigValidationError):
                pytest.fail(
                    f"resolve_site() raised ConfigValidationError (validator↔resolver parity broken): {exc}"
                )
            # Other errors (e.g. JAX import errors caught as ImportError/ModuleNotFoundError) are OK

    # reviewer: backend-reviewer (D33 parity — resolve_site succeeds on inline (12,24))
    def test_resolver_inline_seasonal_passthrough(self):
        # Parity test: resolve_site() must NOT raise on a site with an inline (12,24) tariff.
        # test_v2_seasonal_12x24_ok already proves validate() accepts (12,24); THIS test
        # proves the resolver-side of the parity invariant — "validator-accepts ⟺
        # resolver-accepts" is now proven for BOTH shapes in the accepted set {(24,),(12,24)}.
        #
        # Approach: start from site_gansu.yaml (disk), replace the flat (24,) tariff with
        # a (12,24) matrix (12 copies of the same row), write to a temp file, call resolve_site().
        # JAX-guarded: same pattern as test_real_gansu_config_validates_no_tar_shape.
        import pathlib, tempfile, os
        import yaml as _yaml
        validate = _import_validate()
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        models_path = repo_root / "config" / "device_models.yaml"

        # Build site with (12,24) inline tariff (12 identical rows of the Gansu TOU profile)
        site = _yaml.safe_load(open(repo_root / "config" / "site_gansu.yaml"))
        flat_row = list(site["tariff"]["price_table_yuan_per_mwh"])  # 24 scalars
        site["tariff"]["price_table_yuan_per_mwh"] = [list(flat_row) for _ in range(12)]

        # (a) validate() must accept inline (12,24) under v2.0+ — no JAX needed
        models = _yaml.safe_load(open(models_path))
        result = validate(site, models)
        assert "E-TAR-SHAPE" not in [e.rule_id for e in result.errors], (
            "inline (12,24) tariff must NOT produce E-TAR-SHAPE under schema v2.0+ "
            "(D33 parity — validator side)"
        )

        # (b) resolve_site() must not raise ConfigValidationError on inline (12,24)
        # Writes a temp YAML so resolve_site() can load it from disk.
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="test_gansu_seasonal_"
        )
        try:
            _yaml.dump(site, tmp)
            tmp.close()
            try:
                import importlib
                resolver_mod = importlib.import_module("energy_go.env.resolver")
                resolver_mod.resolve_site(tmp.name, str(models_path))
            except RuntimeError as exc:
                if "AVX" in str(exc) or "cpu_feature" in str(exc) or "jaxlib" in str(exc):
                    pass  # JAX not available on this platform — (a) is the binding guard
                else:
                    raise
            except Exception as exc:
                from energy_go.env.config_validation import ConfigValidationError
                if isinstance(exc, ConfigValidationError):
                    pytest.fail(
                        f"resolve_site() raised ConfigValidationError on inline (12,24) "
                        f"(D33 parity broken — resolver-side): {exc}"
                    )
                # Other non-ConfigValidationError exceptions (ImportError, ModuleNotFoundError)
                # indicate JAX unavailability — acceptable on this platform.
        finally:
            os.unlink(tmp.name)

    # reviewer: backend-reviewer (F2 — validator+resolver AGREE on rejecting 24-nested)
    def test_v2_flat_24_nested_rejected_by_both(self):
        # Parity boundary: a 24-element list-of-lists (e.g. [[250],[450],…]*24) has
        # len==24 but is NOT flat scalars — NOT in {flat (24,), (12,24)}.
        # validator flat_ok: `not any(isinstance(row, list)...)` → False → flat_ok=False
        # validator seasonal_ok: len==24 ≠ 12 → False
        # → E-TAR-SHAPE (validator rejects)
        # resolver flat branch: scalar guard `not any(...)` → False → falls to else: raise
        # → ValueError (resolver rejects)
        # Both sides must agree: this shape is INVALID.
        import pathlib, tempfile, os
        import yaml as _yaml
        validate = _import_validate()

        # Build [[v]]*24 — 24 rows of a single-element list (clearly not a scalar vector)
        nested_24 = [[v] for v in GANSU_SITE["tariff"]["price_table_yuan_per_mwh"]]
        # Arithmetic: len=24, but each element is a list → flat_ok=False, seasonal_ok=False.

        # (a) validator must reject
        site = copy.deepcopy(GANSU_SITE)
        site["tariff"]["price_table_yuan_per_mwh"] = nested_24
        result = validate(site, GANSU_MODELS_V2)
        assert "E-TAR-SHAPE" in [e.rule_id for e in result.errors], (
            "[[v]]*24 (24 single-element lists) must produce E-TAR-SHAPE "
            "— not flat scalars, not (12,24)"
        )

        # (b) resolver must also reject (ValueError), not silently build wrong-shape table.
        # JAX-guarded: if JAX fails to import/initialize on this platform, skip resolver
        # half — (a) is the binding guard.  Catches AttributeError (ARM circular import),
        # RuntimeError (AVX), ImportError, and ModuleNotFoundError.
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        models_path = repo_root / "config" / "device_models.yaml"
        gansu_site = _yaml.safe_load(open(repo_root / "config" / "site_gansu.yaml"))
        gansu_site["tariff"]["price_table_yuan_per_mwh"] = nested_24
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="test_gansu_nested24_"
        )
        try:
            _yaml.dump(gansu_site, tmp)
            tmp.close()
            try:
                import importlib
                resolver_mod = importlib.import_module("energy_go.env.resolver")
            except (ImportError, ModuleNotFoundError, RuntimeError, AttributeError):
                resolver_mod = None  # JAX unavailable — skip resolver half
            if resolver_mod is not None:
                try:
                    resolver_mod.resolve_site(tmp.name, str(models_path))
                    # No exception → resolver silently accepted [[v]]*24 → parity broken
                    pytest.fail(
                        "resolve_site() silently accepted [[v]]*24 (24 single-element lists); "
                        "must raise ValueError to match validator E-TAR-SHAPE (F2 scalar guard)"
                    )
                except ValueError:
                    pass  # correct — resolver rejects, matching validator
                except (RuntimeError, AttributeError) as exc:
                    # JAX initialization failed mid-resolve (ARM platform) — skip
                    pass
        finally:
            os.unlink(tmp.name)

    # reviewer: backend-reviewer (lock: len==12 of scalars is NEVER read as a seasonal table)
    def test_v2_flat_12_scalars_errors(self):
        # schema_version=2.0.0 + flat (12,) of SCALARS — len matches the seasonal ROW COUNT
        # but elements are scalars, not 24-length rows → neither flat-24 nor (12,24).
        # validator flat_ok:    len 12 != 24                     → False
        # validator seasonal_ok: len==12 but rows are scalars     → all(isinstance(row,list)) False → False
        # → E-TAR-SHAPE.  Guards against a buggy impl mistaking len==12 for seasonal.
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["tariff"]["price_table_yuan_per_mwh"] = [300.0] * 12
        result = validate(site, GANSU_MODELS_V2)
        assert "E-TAR-SHAPE" in [e.rule_id for e in result.errors], (
            "schema_version=2.0.0 + flat (12,) scalars — not flat-24, not (12,24) → E-TAR-SHAPE"
        )

    # reviewer: backend-reviewer (malformed/absent schema_version → v1 flat path, no crash)
    def test_malformed_schema_version_uses_v1_path(self):
        # A non-numeric schema_version → int(...split('.')[0]) raises ValueError, caught →
        # use_seasonal stays False → v1 path (len==24 check). Must not crash.
        # (a) flat (24,) Gansu under malformed version → v1 accepts → no E-TAR-SHAPE.
        # (b) (12,24) under malformed version → v1 path: len 12 != 24 → E-TAR-SHAPE.
        validate = _import_validate()
        bad_models = {"schema_version": "not-a-version", "models": GANSU_MODELS["models"]}
        res_a = validate(GANSU_SITE, bad_models)
        assert "E-TAR-SHAPE" not in [e.rule_id for e in res_a.errors], (
            "malformed schema_version must fall back to v1 (flat (24,) accepted, no crash)"
        )
        site = copy.deepcopy(GANSU_SITE)
        flat = site["tariff"]["price_table_yuan_per_mwh"]
        site["tariff"]["price_table_yuan_per_mwh"] = [list(flat) for _ in range(12)]
        res_b = validate(site, bad_models)
        assert "E-TAR-SHAPE" in [e.rule_id for e in res_b.errors], (
            "malformed schema_version → v1 path → (12,24) has len 12 != 24 → E-TAR-SHAPE"
        )


class TestEEconNeg:
    """E-ECON-NEG: negative economics parameters → hard error."""

    def test_positive_econ_ok(self):
        # Gansu has all positive economics in device models → no error
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-ECON-NEG" not in ids

    def test_negative_capex_error(self):
        # capex_per_kw_yuan = -100.0 for wind → ERROR
        validate = _import_validate()
        models = copy.deepcopy(GANSU_MODELS)
        models["models"]["vestas-v150-4.2"]["economics"]["capex_per_kw_yuan"] = -100.0
        result = validate(GANSU_SITE, models)
        ids = [e.rule_id for e in result.errors]
        assert "E-ECON-NEG" in ids, (
            "capex_per_kw_yuan=-100.0 must produce E-ECON-NEG"
        )

    def test_negative_opex_error(self):
        validate = _import_validate()
        models = copy.deepcopy(GANSU_MODELS)
        models["models"]["catl-lmp-300mwh"]["economics"]["opex_fixed_per_kwh_year_yuan"] = -5.0
        result = validate(GANSU_SITE, models)
        ids = [e.rule_id for e in result.errors]
        assert "E-ECON-NEG" in ids

    def test_zero_capex_ok(self):
        # capex_lump_sum_yuan=0.0 for grid (valid — sunk cost) → no E-ECON-NEG
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)  # grid already has 0.0
        ids = [e.rule_id for e in result.errors]
        assert "E-ECON-NEG" not in ids

    def test_econ_skipped_without_device_models(self):
        """Without device_models, E-ECON-NEG is skipped."""
        validate = _import_validate()
        result = validate(GANSU_SITE, None)
        ids = [e.rule_id for e in result.errors]
        assert "E-ECON-NEG" not in ids


class TestELoadSvc:
    """E-LOAD-SVC: load unservable at max supply — gated on load_peak_mw field."""

    def test_no_load_peak_mw_skipped(self):
        # Gansu has no load_peak_mw → rule skipped
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-LOAD-SVC" not in ids

    def test_load_peak_within_supply(self):
        # max_supply = 400+615+330+98.16 = 1443.16 MW
        # load_peak_mw = 100.0 ≤ 1443.16 → no error
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["load"] = {"load_peak_mw": 100.0}
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-LOAD-SVC" not in ids

    def test_load_peak_exceeds_supply(self):
        # max_supply = 400+615+330+98.16 = 1443.16 MW
        # load_peak_mw = 2000.0 > 1443.16 → ERROR
        # Arithmetic: 400 (import) + 615 (wind) + 330 (solar) + 98.16 (bat) = 1443.16 MW
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["load"] = {"load_peak_mw": 2000.0}
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-LOAD-SVC" in ids, (
            "load_peak=2000.0 > max_supply=1443.16 must be E-LOAD-SVC error"
        )


class TestWBatCrate2C:
    """W-BAT-CRATE-2C: fleet C-rate >2C → warning (LFP chemistry advisory)."""

    def test_gansu_no_warning(self):
        # 98.16/294.5 = 0.333C << 2.0 → no warning
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-BAT-CRATE-2C" not in ids

    def test_crate_above_2c_warning(self):
        # fleet_power_mw=591.0, fleet_capacity_mwh=294.5
        # C-rate = 591.0/294.5 = 2.007 C > 2.0 → WARNING
        # Arithmetic: 591.0/294.5 = 2.00678...
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 591.0
        # This also triggers E-BAT-CRATE (591/294.5=2.007 > device 100/300=0.333)
        # Both warnings and errors are independent
        result = validate(site, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-BAT-CRATE-2C" in ids, (
            "591.0/294.5=2.007C > 2.0C must produce W-BAT-CRATE-2C warning"
        )

    def test_crate_exactly_2c_no_warning(self):
        # fleet_power_mw=589.0, fleet_capacity_mwh=294.5
        # C-rate = 589.0/294.5 = 1.9999 C < 2.0 → no warning
        # Arithmetic: 589.0/294.5 = 1.999660...
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 589.0
        result = validate(site, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-BAT-CRATE-2C" not in ids, (
            "589.0/294.5=1.9997C ≤ 2.0C must NOT produce W-BAT-CRATE-2C"
        )

    def test_crate_warning_skipped_without_device_models(self):
        """Without device_models, W-BAT-CRATE-2C is skipped (same skip as E-BAT-CRATE)."""
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 591.0
        result = validate(site, None)
        ids = [w.rule_id for w in result.warnings]
        assert "W-BAT-CRATE-2C" not in ids


class TestWBatDur10H:
    """W-BAT-DUR-10H: storage duration >10h → warning."""

    def test_gansu_no_warning(self):
        # 294.5/98.16 = 3.00h < 10h → no warning
        # Arithmetic: 294.5/98.16 = 2.9999...  ≈ 3.00h
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-BAT-DUR-10H" not in ids

    def test_duration_above_10h_warning(self):
        # fleet_capacity_mwh=294.5, fleet_power_mw=9.816
        # duration = 294.5/9.816 = 30.0h > 10h → WARNING
        # Arithmetic: 294.5/9.816 = 30.003... ≈ 30h
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 9.816
        result = validate(site, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-BAT-DUR-10H" in ids, (
            "294.5/9.816=30.0h > 10h must produce W-BAT-DUR-10H warning"
        )

    def test_duration_exactly_10h_no_warning(self):
        # fleet_capacity_mwh=294.5, fleet_power_mw=29.45
        # duration = 294.5/29.45 = 10.0h → NOT > 10h → no warning
        # Arithmetic: 294.5/29.45 = 10.000000
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 29.45
        result = validate(site, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-BAT-DUR-10H" not in ids, (
            "294.5/29.45=10.0h exactly must NOT produce W-BAT-DUR-10H (threshold is >10h)"
        )


class TestWPccCurtail:
    """W-PCC-CURTAIL: PCC export ≪ 20% of installed generation → warning.

    Gansu: max_export=945, installed=(615+330)=945 → threshold=0.20×945=189
    945 ≥ 189 → no warning.
    """

    def test_gansu_no_warning(self):
        # max_export=945.0 ≥ 0.20×(615+330) = 0.20×945 = 189.0 → no warning
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-PCC-CURTAIL" not in ids

    def test_pcc_severely_constrained_warning(self):
        # Suppose max_export_mw=100.0 (via site override), installed=(615+330)=945
        # threshold = 0.20×945 = 189.0
        # 100.0 < 189.0 → WARNING
        # Arithmetic: 0.20 × (615+330) = 0.20 × 945 = 189.0
        validate = _import_validate()
        models = copy.deepcopy(GANSU_MODELS)
        models["models"]["pcc-substation-945mw"]["physics"]["max_export_mw"] = 100.0
        result = validate(GANSU_SITE, models)
        ids = [w.rule_id for w in result.warnings]
        assert "W-PCC-CURTAIL" in ids, (
            "max_export=100.0 < 0.20×945=189.0 must produce W-PCC-CURTAIL"
        )

    def test_pcc_just_above_threshold_no_warning(self):
        # installed = (615+330) = 945 → threshold = 0.20×945 = 189.0
        # max_export=190.0 ≥ 189.0 → no warning
        validate = _import_validate()
        models = copy.deepcopy(GANSU_MODELS)
        models["models"]["pcc-substation-945mw"]["physics"]["max_export_mw"] = 190.0
        result = validate(GANSU_SITE, models)
        ids = [w.rule_id for w in result.warnings]
        assert "W-PCC-CURTAIL" not in ids


class TestWSizeTrivial:
    """W-SIZE-TRIVIAL: all assets below 1 MW/MWh simultaneously → warning."""

    def test_gansu_not_trivial(self):
        validate = _import_validate()
        result = validate(GANSU_SITE, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-SIZE-TRIVIAL" not in ids

    def test_all_below_1mw_warning(self):
        # wind=0.1MW, solar=0.1MW, bat=0.1MWh — all trivially small
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["wind"]["fleet_rated_mw"] = 0.1
        site["assets"]["solar"]["fleet_capacity_mw"] = 0.1
        site["assets"]["battery"]["fleet_capacity_mwh"] = 0.1
        site["assets"]["battery"]["fleet_power_mw"] = 0.05
        result = validate(site, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-SIZE-TRIVIAL" in ids, (
            "wind=0.1MW, solar=0.1MW, bat=0.1MWh must produce W-SIZE-TRIVIAL"
        )

    def test_wind_above_1mw_not_trivial(self):
        # wind=1.1MW — above threshold; rule requires ALL below 1
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["wind"]["fleet_rated_mw"] = 1.1
        site["assets"]["solar"]["fleet_capacity_mw"] = 0.1
        site["assets"]["battery"]["fleet_capacity_mwh"] = 0.1
        site["assets"]["battery"]["fleet_power_mw"] = 0.05
        result = validate(site, GANSU_MODELS)
        ids = [w.rule_id for w in result.warnings]
        assert "W-SIZE-TRIVIAL" not in ids, (
            "wind=1.1MW above threshold → W-SIZE-TRIVIAL must not fire"
        )


class TestConfigValidationError:
    """ConfigValidationError is raised by resolve_site() on hard errors."""

    def test_error_not_raised_on_valid_gansu(self):
        """Import is optional — skip if resolver not yet implemented."""
        pytest.importorskip("energy_go.env.resolver")
        from energy_go.env.resolver import resolve_gansu
        # resolve_gansu() should not raise ConfigValidationError or DeviceModelError
        try:
            resolve_gansu()
        except ImportError:
            pytest.skip("jax_env not available")

    def test_config_validation_error_has_errors_field(self):
        mod = _import_all()
        err = mod.ConfigValidationError.__new__(mod.ConfigValidationError)
        err.errors = [
            mod.ValidationIssue("E-CAP-POS", "assets.battery.fleet_capacity_mwh",
                                "must be > 0", "-10.0 MWh — must be > 0")
        ]
        err.warnings = []
        assert len(err.errors) == 1
        assert err.errors[0].rule_id == "E-CAP-POS"

    def test_config_validation_error_is_valueerror(self):
        mod = _import_all()
        assert issubclass(mod.ConfigValidationError, ValueError)


class TestNonRaising:
    """validate() must never raise, even on malformed inputs."""

    def test_empty_dict_no_crash(self):
        validate = _import_validate()
        result = validate({}, GANSU_MODELS)
        assert isinstance(result.errors, list)

    def test_none_assets_no_crash(self):
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site.pop("assets", None)
        result = validate(site, GANSU_MODELS)
        assert isinstance(result.errors, list)

    def test_missing_battery_section_no_crash(self):
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"].pop("battery", None)
        result = validate(site, GANSU_MODELS)
        assert isinstance(result.errors, list)

    def test_none_tariff_no_crash(self):
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site.pop("tariff", None)
        result = validate(site, GANSU_MODELS)
        assert isinstance(result.errors, list)

    def test_malformed_device_models_string_no_crash(self):
        # reviewer: backend-reviewer (PR #89 stage-2 [HIGH] — §3.2 malformed device_models)
        # device_models="not-a-dict" → validate() must coerce to None (not raise AttributeError)
        # Reproduced AttributeError in e3b1d9b via 'str' has no 'get'.
        validate = _import_validate()
        result = validate(GANSU_SITE, "not-a-dict")   # must NOT raise
        assert isinstance(result.errors, list), "malformed device_models must not raise"

    def test_malformed_device_models_models_not_dict_no_crash(self):
        # reviewer: backend-reviewer (PR #89 stage-2 [HIGH] — §3.2 malformed device_models)
        # {"models": "nope"} → _check_e_econ_neg iterates "nope".items() → AttributeError.
        validate = _import_validate()
        result = validate(GANSU_SITE, {"models": "nope"})   # must NOT raise
        assert isinstance(result.errors, list)

    def test_malformed_device_models_model_entry_not_dict_no_crash(self):
        # reviewer: backend-reviewer (PR #89 stage-2 [HIGH] — §3.2 malformed device_models)
        # {"models": {"x": "str"}} → model_def.get("physics") → AttributeError.
        validate = _import_validate()
        result = validate(GANSU_SITE, {"models": {"x": "str"}})   # must NOT raise
        assert isinstance(result.errors, list)


class TestExhaustive:
    """validate() collects ALL issues, never short-circuits."""

    def test_multiple_errors_all_reported(self):
        # Inject battery_capacity=0 AND tariff wrong length → both errors reported
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_capacity_mwh"] = 0.0
        site["tariff"]["price_table_yuan_per_mwh"] = [300.0] * 12
        result = validate(site, GANSU_MODELS)
        ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in ids, "E-CAP-POS must be collected"
        assert "E-TAR-SHAPE" in ids, "E-TAR-SHAPE must be collected (not short-circuited)"


# ===========================================================================
# Reviewer-added edge cases (backend-reviewer, PR #89 advisory)
# Cover gaps the original suite missed: §3.2 division-guard non-raising,
# E-CAP-POS NaN/grid coverage, W-BAT-CRATE-2C independence, strict-> boundary.
# Hand-values re-verified by execution. Contract amended at 19770be to spec these.
# ===========================================================================

class TestReviewerDivisionGuard:
    """# reviewer: backend-reviewer — §3.2 division guard (no ZeroDivisionError escapes)."""

    def test_zero_capacity_with_models_no_crash_crate_skips(self):
        # reviewer: backend-reviewer (PR #89 [HIGH])
        # fleet_capacity_mwh=0.0 WITH device_models: E-BAT-CRATE would compute
        # fleet_power/0.0 → ZeroDivisionError in Python. §3.2 division guard requires
        # the C-rate rule to SKIP (denominator ≤ 0); E-CAP-POS catches the zero;
        # validate() must NOT raise.
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_capacity_mwh"] = 0.0
        result = validate(site, GANSU_MODELS)            # must NOT raise
        err_ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in err_ids, f"zero capacity must fire E-CAP-POS; got {err_ids}"
        assert "E-BAT-CRATE" not in err_ids, (
            "E-BAT-CRATE must SKIP on zero capacity (§3.2 guard), not compute 98.16/0.0"
        )

    def test_zero_power_with_models_no_crash_duration_skips(self):
        # reviewer: backend-reviewer (PR #89 [HIGH])
        # fleet_power_mw=0.0: W-BAT-DUR-10H computes fleet_capacity/0.0 → ZeroDivisionError.
        # §3.2 guard: duration rule SKIPS (denominator ≤ 0); E-CAP-POS catches zero power;
        # no raise. (C-rate = 0.0/294.5 = 0C, so W-BAT-CRATE-2C/E-BAT-CRATE simply don't fire.)
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 0.0
        result = validate(site, GANSU_MODELS)            # must NOT raise
        err_ids = [e.rule_id for e in result.errors]
        warn_ids = [w.rule_id for w in result.warnings]
        assert "E-CAP-POS" in err_ids, f"zero power must fire E-CAP-POS; got {err_ids}"
        assert "W-BAT-DUR-10H" not in warn_ids, (
            "W-BAT-DUR-10H must SKIP on zero power (§3.2 guard), not compute 294.5/0.0"
        )
        assert "W-BAT-CRATE-2C" not in warn_ids, "C-rate=0/294.5=0C → no 2C warning"

    def test_nan_capacity_fires_e_cap_pos(self):
        # reviewer: backend-reviewer (PR #89 [LOW] NaN / §4 IEEE-754 note)
        # NaN capacity is "obviously unreasonable" (user directive). E-CAP-POS MUST use
        # `not (x > 0)`: nan > 0 is False → not(False)=True → fires.  A naive `x <= 0`
        # would MISS nan (nan <= 0 is False).  Also exercises §3.2: E-BAT-CRATE skips
        # on a NaN denominator without raising.
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_capacity_mwh"] = float("nan")
        result = validate(site, GANSU_MODELS)            # must NOT raise
        err_ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in err_ids, (
            f"NaN capacity must fire E-CAP-POS via `not (x>0)`; got {err_ids}"
        )
        assert "E-BAT-CRATE" not in err_ids, "E-BAT-CRATE must skip on NaN denominator (§3.2)"


class TestReviewerCrateIndependenceAndBoundary:
    """# reviewer: backend-reviewer — W-BAT-CRATE-2C independence + strict-> C-rate boundary."""

    def test_2c_warning_fires_while_crate_error_passes(self):
        # reviewer: backend-reviewer (PR #89 [MED] independence)
        # Proves W-BAT-CRATE-2C fires "even if E-BAT-CRATE passes" — needs a device rated >2C.
        # device per-unit: power_mw_per_unit=700, capacity_mwh_per_unit=300 → 700/300 = 2.3333C
        # fleet: fleet_power_mw=650, fleet_capacity_mwh=294.5 → 650/294.5 = 2.2071C
        # 2.0 < 2.2071 → W-BAT-CRATE-2C fires;  2.2071 ≤ 2.3333 → E-BAT-CRATE does NOT fire.
        validate = _import_validate()
        models = copy.deepcopy(GANSU_MODELS)
        models["models"]["catl-lmp-300mwh"]["physics"]["power_mw_per_unit"] = 700.0
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 650.0
        result = validate(site, models)
        warn_ids = [w.rule_id for w in result.warnings]
        err_ids = [e.rule_id for e in result.errors]
        assert "W-BAT-CRATE-2C" in warn_ids, "2.207C > 2.0C must fire W-BAT-CRATE-2C"
        assert "E-BAT-CRATE" not in err_ids, (
            "2.207C ≤ device 2.333C must NOT fire E-BAT-CRATE — proves W/E independence"
        )

    def test_crate_exactly_equal_device_no_error(self):
        # reviewer: backend-reviewer (PR #89 [LOW] strict-> boundary, "no tolerance")
        # "HARD ERROR iff fleet_crate > device_crate" — equality must NOT error.
        # fleet: power=100.0, capacity=300.0 → 0.33333C ; device catl 100/300 → 0.33333C.
        # 0.33333 > 0.33333 is False (same float) → no error.
        validate = _import_validate()
        site = copy.deepcopy(GANSU_SITE)
        site["assets"]["battery"]["fleet_power_mw"] = 100.0
        site["assets"]["battery"]["fleet_capacity_mwh"] = 300.0
        result = validate(site, GANSU_MODELS)
        err_ids = [e.rule_id for e in result.errors]
        assert "E-BAT-CRATE" not in err_ids, (
            "fleet_crate == device_crate (0.333C) must NOT error (strict > , no tolerance)"
        )


class TestReviewerGridCapPos:
    """# reviewer: backend-reviewer — E-CAP-POS coverage of resolved grid limits (§4 lists them)."""

    def test_grid_export_zero_fires_e_cap_pos(self):
        # reviewer: backend-reviewer (PR #89 [MED] grid coverage)
        # §4 lists grid.max_export_mw (resolved) as an E-CAP-POS field; resolved from
        # device physics. max_export_mw=0.0 → not (0 > 0) → E-CAP-POS.
        validate = _import_validate()
        models = copy.deepcopy(GANSU_MODELS)
        models["models"]["pcc-substation-945mw"]["physics"]["max_export_mw"] = 0.0
        result = validate(GANSU_SITE, models)
        err_ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in err_ids, f"zero grid max_export must fire E-CAP-POS; got {err_ids}"
        assert any("max_export" in e.field for e in result.errors), (
            "E-CAP-POS issue must reference the max_export field"
        )

    def test_grid_import_zero_fires_e_cap_pos(self):
        # reviewer: backend-reviewer (PR #89 [MED] grid coverage)
        validate = _import_validate()
        models = copy.deepcopy(GANSU_MODELS)
        models["models"]["pcc-substation-945mw"]["physics"]["max_import_mw"] = 0.0
        result = validate(GANSU_SITE, models)
        err_ids = [e.rule_id for e in result.errors]
        assert "E-CAP-POS" in err_ids, f"zero grid max_import must fire E-CAP-POS; got {err_ids}"
        assert any("max_import" in e.field for e in result.errors), (
            "E-CAP-POS issue must reference the max_import field"
        )
