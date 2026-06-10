"""Tests for energy_go.telemetry.validate (task #23).

Contract: contracts/shared/telemetry_validate.md
Schema:   contracts/shared/telemetry_schema.json  (LOCKED v1.0.0)
Fixtures: contracts/shared/telemetry_examples/*.json

D13 identity arithmetic is shown in each test comment.
TOL = 1e-6; _approx(a,b) := |a-b| <= 1e-6 + 1e-6*max(|a|,|b|)
(1e-6 relative coefficient is float32-safe; env JAX core is float32 — see F1 in contract)
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "contracts" / "shared" / "telemetry_examples"


def _load(name: str) -> dict:
    """Load a golden fixture by filename (without .json)."""
    return json.loads((EXAMPLES_DIR / f"{name}.json").read_text())


def _env_step_a() -> dict:
    return _load("env_step_a")


def _env_step_b() -> dict:
    return _load("env_step_b")


def _eval_compare() -> dict:
    return _load("eval_compare")


def _train_metrics() -> dict:
    return _load("train_metrics")


# ---------------------------------------------------------------------------
# Import check
# ---------------------------------------------------------------------------


class TestModuleImport:
    def test_module_importable(self):
        """energy_go.telemetry.validate must import without error."""
        import energy_go.telemetry.validate as tv  # noqa: F401

    def test_validate_callable(self):
        """Top-level validate() must be callable."""
        import energy_go.telemetry.validate as tv
        assert callable(tv.validate)

    def test_schema_version_constant(self):
        """SCHEMA_VERSION must equal the LOCKED contract version."""
        import energy_go.telemetry.validate as tv
        assert tv.SCHEMA_VERSION == "1.0.0"

    def test_tol_constant(self):
        """TOL must be 1e-6 (numeric identity tolerance)."""
        import energy_go.telemetry.validate as tv
        assert tv.TOL == 1e-6

    def test_public_functions_exposed(self):
        """check_finite, check_env_step, check_eval_compare must be public."""
        import energy_go.telemetry.validate as tv
        assert callable(tv.check_finite)
        assert callable(tv.check_env_step)
        assert callable(tv.check_eval_compare)


# ---------------------------------------------------------------------------
# Golden-fixture tests — every example must validate clean
# ---------------------------------------------------------------------------


class TestGoldenExamples:
    def test_env_step_a_valid(self):
        """env_step_a.json must pass all checks (schema + identities + conservation)."""
        import energy_go.telemetry.validate as tv
        assert tv.validate(_env_step_a()) == []

    def test_env_step_b_valid(self):
        """env_step_b.json must pass all checks."""
        import energy_go.telemetry.validate as tv
        assert tv.validate(_env_step_b()) == []

    def test_eval_compare_valid(self):
        """eval_compare.json must pass all checks."""
        import energy_go.telemetry.validate as tv
        assert tv.validate(_eval_compare()) == []

    def test_train_metrics_valid(self):
        """train_metrics.json must pass all checks (no cost identities for train_metrics)."""
        import energy_go.telemetry.validate as tv
        assert tv.validate(_train_metrics()) == []

    def test_all_example_files_valid(self):
        """Every *.json file in contracts/shared/telemetry_examples/ must pass."""
        import energy_go.telemetry.validate as tv
        files = sorted(EXAMPLES_DIR.glob("*.json"))
        assert files, "No example files found — check EXAMPLES_DIR path"
        for fp in files:
            msg = json.loads(fp.read_text())
            errs = tv.validate(msg)
            assert errs == [], f"{fp.name} failed:\n" + "\n".join(f"  {e}" for e in errs)


# ---------------------------------------------------------------------------
# Input type handling
# ---------------------------------------------------------------------------


class TestInputTypes:
    def test_dict_input(self):
        """validate() accepts a dict."""
        import energy_go.telemetry.validate as tv
        assert tv.validate(_train_metrics()) == []

    def test_json_str_input(self):
        """validate() accepts a JSON-encoded string."""
        import energy_go.telemetry.validate as tv
        assert tv.validate(json.dumps(_train_metrics())) == []

    def test_json_bytes_input(self):
        """validate() accepts UTF-8-encoded bytes."""
        import energy_go.telemetry.validate as tv
        assert tv.validate(json.dumps(_train_metrics()).encode("utf-8")) == []

    def test_invalid_type_raises_type_error(self):
        """validate() raises TypeError for unexpected types (int, list, None)."""
        import energy_go.telemetry.validate as tv
        with pytest.raises(TypeError):
            tv.validate(42)
        with pytest.raises(TypeError):
            tv.validate(None)
        with pytest.raises(TypeError):
            tv.validate([])

    def test_invalid_json_string_raises_value_error(self):
        """validate() raises ValueError for non-JSON strings."""
        import energy_go.telemetry.validate as tv
        with pytest.raises(ValueError):
            tv.validate("not-json{{{")

    def test_returns_list_not_raises_on_invalid_message(self):
        """validate() never raises on a structurally-wrong-but-parseable message."""
        import energy_go.telemetry.validate as tv
        bad = {"kind": "env_step", "seq": "wrong-type"}
        result = tv.validate(bad)
        assert isinstance(result, list)
        assert len(result) > 0  # must report errors


# ---------------------------------------------------------------------------
# Schema conformance
# ---------------------------------------------------------------------------


class TestSchemaConformance:
    def test_missing_required_envelope_field(self):
        """Removing a required envelope field (e.g. 'kind') must produce a schema error."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        del msg["kind"]
        errs = tv.validate(msg)
        assert any("kind" in e for e in errs), f"Expected 'kind' in errors: {errs}"

    def test_wrong_type_seq(self):
        """seq must be integer; a string value must produce a schema error."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        msg["seq"] = "not-an-int"
        errs = tv.validate(msg)
        assert any("seq" in e for e in errs), f"Expected 'seq' in errors: {errs}"

    def test_unknown_kind(self):
        """kind must be one of the three contracted values; 'bogus' must error."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        msg["kind"] = "bogus"
        errs = tv.validate(msg)
        assert any("kind" in e.lower() or "bogus" in e for e in errs), f"Expected kind error: {errs}"

    def test_soc_out_of_range(self):
        """battery.soc must be in [0.2, 0.9]; 1.5 must produce a schema error."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["battery"]["soc"] = 1.5
        errs = tv.validate(msg)
        assert any("soc" in e for e in errs), f"Expected soc error: {errs}"

    def test_negative_flow_value(self):
        """flows.*_mw values must be >= 0; -5.0 must produce a schema error."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["flows"]["solar_to_load_mw"] = -5.0
        errs = tv.validate(msg)
        assert any("solar_to_load_mw" in e for e in errs), f"Expected flow error: {errs}"

    def test_invalid_tariff_tier(self):
        """tariff_tier must be one of the four contracted values."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["tariff_tier"] = "super_peak"
        errs = tv.validate(msg)
        assert any("tariff_tier" in e or "super_peak" in e for e in errs), f"Expected tariff error: {errs}"

    def test_missing_required_payload_field(self):
        """Removing a required payload field must produce a schema error."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        del msg["payload"]["reward"]
        errs = tv.validate(msg)
        assert any("reward" in e for e in errs), f"Expected reward error: {errs}"


# ---------------------------------------------------------------------------
# Major-version guard (F3)
# ---------------------------------------------------------------------------


class TestMajorVersionGuard:
    def test_major_version_2_rejected(self):
        """schema_version '2.0.0' must produce a version-mismatch error (major != 1)."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        msg["schema_version"] = "2.0.0"
        errs = tv.validate(msg)
        assert any("version" in e.lower() and ("2" in e or "mismatch" in e.lower()) for e in errs), (
            f"Expected version-mismatch error for 2.0.0: {errs}"
        )

    def test_major_version_error_is_first(self):
        """The version-mismatch error must appear before any schema errors (guaranteed order)."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        msg["schema_version"] = "2.0.0"
        msg["seq"] = "also-wrong-type"  # additional schema error
        errs = tv.validate(msg)
        version_indices = [i for i, e in enumerate(errs) if "version" in e.lower()]
        assert version_indices, f"No version error found: {errs}"
        assert version_indices[0] == 0, (
            f"Version-mismatch error must be first; got index {version_indices[0]} in: {errs}"
        )

    def test_minor_version_bump_accepted(self):
        """schema_version '1.1.0' must pass (minor bump is forward-compatible)."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        msg["schema_version"] = "1.1.0"
        errs = tv.validate(msg)
        # No version-mismatch errors; only unknown-field additions would be ignored
        assert not any("version mismatch" in e.lower() for e in errs), (
            f"Minor bump 1.1.0 must not trigger version-mismatch: {errs}"
        )

    def test_patch_version_bump_accepted(self):
        """schema_version '1.0.99' must pass (patch bump is forward-compatible)."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        msg["schema_version"] = "1.0.99"
        errs = tv.validate(msg)
        assert not any("version mismatch" in e.lower() for e in errs), (
            f"Patch bump 1.0.99 must not trigger version-mismatch: {errs}"
        )

    def test_missing_schema_version_no_version_guard_error(self):
        """When schema_version is absent, version guard is skipped (schema errors report it instead)."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        del msg["schema_version"]
        errs = tv.validate(msg)
        # Schema error expected but NOT a version-mismatch error (guard requires schema_version present)
        assert not any("version mismatch" in e.lower() for e in errs), (
            f"No version-mismatch error expected when field absent: {errs}"
        )
        assert any("schema_version" in e or "schema:" in e for e in errs), (
            f"Expected schema error for missing schema_version: {errs}"
        )


# ---------------------------------------------------------------------------
# Defensive check functions (F4)
# ---------------------------------------------------------------------------


class TestDefensiveChecks:
    def test_check_env_step_missing_costs_does_not_raise(self):
        """check_env_step must not raise when 'costs' key is absent — skips cost-identity checks."""
        import energy_go.telemetry.validate as tv
        payload = {"flows": {}, "generation": {}}  # no 'costs' key
        result = tv.check_env_step(payload)
        assert isinstance(result, list), "check_env_step must return a list"
        # No D13 errors expected — checks are skipped on absent fields
        assert not any("D13" in e for e in result), (
            f"D13 errors must be skipped when costs absent: {result}"
        )

    def test_check_env_step_missing_generation_does_not_raise(self):
        """check_env_step must not raise when 'generation' key is absent — skips conservation."""
        import energy_go.telemetry.validate as tv
        payload = {"costs": {}, "flows": {}}  # no 'generation' key
        result = tv.check_env_step(payload)
        assert isinstance(result, list)
        assert not any("conservation" in e.lower() for e in result), (
            f"Conservation errors must be skipped when generation absent: {result}"
        )

    def test_check_eval_compare_missing_policies_does_not_raise(self):
        """check_eval_compare must not raise when 'policies' key is absent."""
        import energy_go.telemetry.validate as tv
        payload = {}  # no 'policies' key
        result = tv.check_eval_compare(payload)
        assert isinstance(result, list), "check_eval_compare must return a list"

    def test_check_eval_compare_policy_missing_fields_does_not_raise(self):
        """check_eval_compare must not raise when a policy entry lacks required cost fields."""
        import energy_go.telemetry.validate as tv
        payload = {"policies": {"partial_policy": {"energy_cost_yuan": 1000.0}}}
        result = tv.check_eval_compare(payload)
        assert isinstance(result, list)

    def test_validate_empty_payload_never_raises(self):
        """validate() on a message with an empty payload dict must return a list, not raise."""
        import energy_go.telemetry.validate as tv
        msg = {
            "schema_version": "1.0.0",
            "kind": "env_step",
            "ts_utc": "2026-01-01T00:00:00Z",
            "run_id": "test",
            "seq": 0,
            "payload": {},
        }
        result = tv.validate(msg)
        assert isinstance(result, list), "validate() must return a list on empty payload"
        assert len(result) > 0, "Empty env_step payload must have schema errors"

    def test_validate_completely_empty_dict_returns_list(self):
        """validate({}) must return a non-empty list of errors, not raise."""
        import energy_go.telemetry.validate as tv
        result = tv.validate({})
        assert isinstance(result, list)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Finiteness checks
# ---------------------------------------------------------------------------


class TestFiniteness:
    def test_nan_in_cost_field(self):
        """NaN in costs.c_energy_yuan must produce a non-finite error."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["costs"]["c_energy_yuan"] = float("nan")
        errs = tv.validate(msg)
        assert any("non-finite" in e for e in errs), f"Expected non-finite error: {errs}"

    def test_inf_in_flow_field(self):
        """Inf in flows.solar_to_load_mw must produce a non-finite error."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["flows"]["solar_to_load_mw"] = float("inf")
        errs = tv.validate(msg)
        assert any("non-finite" in e for e in errs), f"Expected non-finite error: {errs}"

    def test_neg_inf_in_reward(self):
        """-Inf in reward must produce a non-finite error."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["reward"] = float("-inf")
        errs = tv.validate(msg)
        assert any("non-finite" in e for e in errs), f"Expected non-finite error: {errs}"

    def test_nan_in_nested_cumulative(self):
        """NaN anywhere in cost_cum must produce a non-finite error."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["cost_cum"]["c_energy_yuan_cum"] = float("nan")
        errs = tv.validate(msg)
        assert any("non-finite" in e for e in errs), f"Expected non-finite error: {errs}"

    def test_check_finite_returns_empty_for_valid(self):
        """check_finite() returns [] for a valid message with no NaN/Inf."""
        import energy_go.telemetry.validate as tv
        assert tv.check_finite(_env_step_a()) == []

    def test_check_finite_returns_path_in_error(self):
        """check_finite() error string must contain a dot-path locating the bad field."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["costs"]["c_degradation_yuan"] = float("nan")
        errs = tv.check_finite(msg)
        assert errs, "Expected at least one error"
        # path should reference c_degradation_yuan somehow
        assert any("c_degradation_yuan" in e for e in errs), f"Path not in error: {errs}"

    def test_boolean_not_flagged_as_non_finite(self):
        """Booleans (True/False) must not be treated as floats."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        # is_eval_checkpoint is a bool; it must not trigger a non-finite error
        errs = tv.check_finite(msg)
        assert errs == [], f"Unexpected errors for bool field: {errs}"


# ---------------------------------------------------------------------------
# D13 cost identity checks (env_step)
# ---------------------------------------------------------------------------
#
# env_step_a golden values:
#   c_energy_yuan          = -53100.0   (c_import - r_export: 0 - 53100)
#   c_demand_charge_yuan   =      0.0
#   c_demand_shape_yuan    =      0.0
#   c_degradation_yuan     =    400.0
#   c_curtail_yuan         =      0.0
#   c_voll_yuan            =      0.0
#   penalty_yuan           =      0.0
#   cost_total_real_yuan   = -52700.0  = -53100 + 0 + 400 + 0 + 0
#   cost_total_reward_basis_yuan = -52700.0  = -53100 + 2×0 + 400 + 0 + 0
#   reward                 =   0.527   = -(-52700 + 0)*1e-5 = 52700*1e-5 = 0.527
#


class TestD13CostIdentities:
    def test_real_identity_violation(self):
        """cost_total_real_yuan that doesn't match the five summands must error.

        Arithmetic: correct = -53100 + 0 + 400 + 0 + 0 = -52700.
        We set cost_total_real_yuan = -52000 (off by 700) → D13 real identity error.
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["costs"]["cost_total_real_yuan"] = -52000.0  # wrong; correct is -52700
        errs = tv.check_env_step(msg["payload"])
        assert any("D13 real" in e or "real identity" in e for e in errs), f"Expected D13 real error: {errs}"

    def test_reward_basis_identity_violation(self):
        """cost_total_reward_basis_yuan that doesn't match must error.

        Arithmetic: correct = -53100 + 2×0 + 400 + 0 + 0 = -52700.
        We set cost_total_reward_basis_yuan = -51000 (off by 1700) → error.
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["costs"]["cost_total_reward_basis_yuan"] = -51000.0  # wrong; correct is -52700
        errs = tv.check_env_step(msg["payload"])
        assert any("D13 reward" in e or "reward-basis" in e for e in errs), f"Expected D13 reward-basis error: {errs}"

    def test_demand_shape_2x_weight_applied(self):
        """Demand-shaping term enters reward-basis with weight 2.0 (NOT 1.0).

        Set c_demand_shape_yuan = 1000, costs consistent for real but NOT reward-basis
        if weight-1 were used (i.e. set cost_total_reward_basis_yuan to match 1× weight).
        Correct reward-basis = c_energy + 2×1000 + c_deg + c_curt + c_voll
                             = -53100 + 2000 + 400 + 0 + 0 = -50700.
        We put cost_total_reward_basis_yuan = -51700 (uses weight 1 instead of 2) → error.
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        c = msg["payload"]["costs"]
        c["c_demand_shape_yuan"] = 1000.0
        # Real identity: -53100 + 0 + 400 + 0 + 0 = -52700 (unchanged; demand_charge stays 0)
        c["cost_total_real_yuan"] = -52700.0
        # Wrong: uses weight 1 not 2 → -53100 + 1×1000 + 400 = -51700 (incorrect weight)
        c["cost_total_reward_basis_yuan"] = -51700.0
        errs = tv.check_env_step(msg["payload"])
        assert any("D13 reward" in e or "reward-basis" in e for e in errs), f"Expected reward-basis 2× error: {errs}"

    def test_c_energy_decomposition_violation(self):
        """c_energy_yuan must equal c_import_yuan - r_export_yuan.

        Golden: c_energy = -53100 = 0 - 53100.
        We set c_import_yuan = 100.0 but leave c_energy = -53100 → mismatch.
        Correct c_energy would be 100 - 53100 = -53000 ≠ -53100 → error.
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["costs"]["c_import_yuan"] = 100.0  # was 0; c_energy still -53100 → mismatch
        errs = tv.check_env_step(msg["payload"])
        assert any("c_energy" in e for e in errs), f"Expected c_energy decomposition error: {errs}"

    def test_reward_formula_violation(self):
        """reward must equal -(cost_total_reward_basis_yuan + penalty_yuan) * 1e-5.

        Golden: reward = -(-52700 + 0)*1e-5 = 0.527.
        We set reward = 0.600 (wrong) → reward identity error.
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["reward"] = 0.600  # correct is 0.527 = 52700 * 1e-5
        errs = tv.check_env_step(msg["payload"])
        assert any("reward" in e.lower() for e in errs), f"Expected reward formula error: {errs}"

    def test_real_identity_includes_demand_charge(self):
        """Real-money total includes c_demand_charge, NOT c_demand_shape.

        Set c_demand_charge = 5000, update cost_total_real_yuan correctly;
        verify validate() accepts it (sanity check that demand_charge is in real sum).
        Arithmetic: real = -53100 + 5000 + 400 + 0 + 0 = -47700.
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        c = msg["payload"]["costs"]
        c["c_demand_charge_yuan"] = 5000.0
        c["cost_total_real_yuan"] = -47700.0   # -53100 + 5000 + 400 = -47700
        # reward basis unchanged (uses demand_shape=0, not demand_charge)
        # reward = -(-52700 + 0)*1e-5 = 0.527 (still correct because reward_basis unchanged)
        errs = tv.check_env_step(msg["payload"])
        assert errs == [], f"Unexpected errors: {errs}"

    def test_penalty_enters_reward_not_cost_total(self):
        """penalty_yuan enters the reward formula but NOT cost_total_reward_basis_yuan.

        Set penalty = 10000, update reward = -(cost_total_reward_basis_yuan + 10000)*1e-5.
        reward_basis stays = -52700 (no change).
        reward = -(-52700 + 10000)*1e-5 = -(-42700)*1e-5 = 0.427.
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        c = msg["payload"]["costs"]
        c["penalty_yuan"] = 10000.0
        # cost_total_reward_basis_yuan must NOT include penalty → stays -52700
        msg["payload"]["reward"] = 0.427  # = -(-52700 + 10000)*1e-5 = 42700 * 1e-5 = 0.427
        errs = tv.check_env_step(msg["payload"])
        assert errs == [], f"Unexpected errors: {errs}"

    def test_check_env_step_returns_empty_for_valid(self):
        """check_env_step() returns [] for the golden env_step_a fixture."""
        import energy_go.telemetry.validate as tv
        assert tv.check_env_step(_env_step_a()["payload"]) == []


# ---------------------------------------------------------------------------
# Per-source energy conservation (env_step)
# ---------------------------------------------------------------------------
#
# env_step_a solar: 30+0+0+0 = 30 = gross_solar_mw ✓
# env_step_a wind:  12.5+0+80+0 = 92.5 = gross_wind_mw ✓
#


class TestEnergyConservation:
    def test_solar_conservation_violation(self):
        """solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed must equal gross_solar.

        Golden: 30+0+0+0 = 30.  We set solar_to_load = 25 → sum 25 ≠ 30 → error.
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["flows"]["solar_to_load_mw"] = 25.0  # sum becomes 25 ≠ 30
        errs = tv.check_env_step(msg["payload"])
        assert any("solar" in e.lower() and "conserv" in e.lower() for e in errs), f"Expected solar conservation error: {errs}"

    def test_wind_conservation_violation(self):
        """wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed must equal gross_wind.

        Golden: 12.5+0+80+0 = 92.5.  We set wind_to_grid = 70 → sum 82.5 ≠ 92.5 → error.
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["payload"]["flows"]["wind_to_grid_mw"] = 70.0  # sum becomes 82.5 ≠ 92.5
        errs = tv.check_env_step(msg["payload"])
        assert any("wind" in e.lower() and "conserv" in e.lower() for e in errs), f"Expected wind conservation error: {errs}"

    def test_solar_conservation_zero_generation_valid(self):
        """All solar flows zero and gross_solar_mw = 0 must pass conservation check.

        Arithmetic: 0+0+0+0 = 0 = gross_solar_mw ✓
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        p = msg["payload"]
        p["generation"]["gross_solar_mw"] = 0.0
        for k in ["solar_to_load_mw", "solar_to_bat_mw", "solar_to_grid_mw", "solar_curtailed_mw"]:
            p["flows"][k] = 0.0
        # Also must fix cost identities and reward since we changed load balance implicitly.
        # For the conservation check alone, use check_env_step and filter solar errors.
        errs = [e for e in tv.check_env_step(p) if "solar conserv" in e.lower()]
        assert errs == [], f"Solar conservation errors with zero generation: {errs}"

    def test_wind_conservation_zero_generation_valid(self):
        """All wind flows zero and gross_wind_mw = 0 must pass conservation check."""
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        p = msg["payload"]
        p["generation"]["gross_wind_mw"] = 0.0
        for k in ["wind_to_load_mw", "wind_to_bat_mw", "wind_to_grid_mw", "wind_curtailed_mw"]:
            p["flows"][k] = 0.0
        errs = [e for e in tv.check_env_step(p) if "wind conserv" in e.lower()]
        assert errs == [], f"Wind conservation errors with zero generation: {errs}"


# ---------------------------------------------------------------------------
# eval_compare identity checks
# ---------------------------------------------------------------------------
#
# eval_compare.json golden:
#   rl:            12000000+9000000+1500000+300000+0 = 22800000 ✓
#   no_battery:    18000000+14000000+0+900000+0 = 32900000 ✓
#   rule_based_tou:15000000+11000000+2000000+500000+0 = 28500000 ✓
#


class TestEvalCompareIdentity:
    def test_policy_total_cost_violation(self):
        """total_cost_yuan != sum of 5 components must error.

        rl: correct = 12000000+9000000+1500000+300000+0 = 22800000.
        We set total_cost_yuan = 23000000 (off by 200000) → error.
        """
        import energy_go.telemetry.validate as tv
        msg = _eval_compare()
        msg["payload"]["policies"]["rl"]["total_cost_yuan"] = 23000000.0  # correct is 22800000
        errs = tv.check_eval_compare(msg["payload"])
        assert any("rl" in e for e in errs), f"Expected rl policy error: {errs}"

    def test_all_three_policies_checked(self):
        """check_eval_compare must check every policy, not just the first.

        We corrupt rule_based_tou (third policy): correct total = 28500000.
        We set it to 29000000 → error mentioning rule_based_tou.
        """
        import energy_go.telemetry.validate as tv
        msg = _eval_compare()
        msg["payload"]["policies"]["rule_based_tou"]["total_cost_yuan"] = 29000000.0
        errs = tv.check_eval_compare(msg["payload"])
        assert any("rule_based_tou" in e for e in errs), f"Expected rule_based_tou error: {errs}"

    def test_no_battery_policy_checked(self):
        """no_battery policy total identity is also checked.

        Correct: 18000000+14000000+0+900000+0 = 32900000.  Set to 33000000 → error.
        """
        import energy_go.telemetry.validate as tv
        msg = _eval_compare()
        msg["payload"]["policies"]["no_battery"]["total_cost_yuan"] = 33000000.0
        errs = tv.check_eval_compare(msg["payload"])
        assert any("no_battery" in e for e in errs), f"Expected no_battery error: {errs}"

    def test_check_eval_compare_returns_empty_for_valid(self):
        """check_eval_compare() returns [] for the golden eval_compare fixture."""
        import energy_go.telemetry.validate as tv
        assert tv.check_eval_compare(_eval_compare()["payload"]) == []


# ---------------------------------------------------------------------------
# train_metrics — no cost-identity checks apply
# ---------------------------------------------------------------------------


class TestTrainMetricsNoIdentityCheck:
    def test_train_metrics_no_identity_check(self):
        """train_metrics with no costs.* fields must not trigger D13 or conservation errors."""
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        errs = tv.validate(msg)
        assert errs == [], f"Unexpected errors for valid train_metrics: {errs}"

    def test_train_metrics_kind_specific_checks_skipped(self):
        """check_env_step and check_eval_compare must not be called for train_metrics.

        Manually invoke validate() on a train_metrics message that would be invalid if
        treated as env_step; confirm no D13/conservation errors appear (only schema errors
        if any — but the payload is valid schema).
        """
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        # Inject something that would be a D13 error if it were env_step — just extra key
        msg["payload"]["cost_total_real_yuan"] = 999.0  # unknown extra field, not an error (additionalProperties: true)
        errs = tv.validate(msg)
        # No D13 error expected; the extra field is ignored (additionalProperties: true in schema)
        assert all("D13" not in e and "conservation" not in e.lower() for e in errs), (
            f"train_metrics should not trigger D13/conservation errors: {errs}"
        )


# ---------------------------------------------------------------------------
# Validation order guarantee
# ---------------------------------------------------------------------------


class TestValidationOrder:
    def test_schema_errors_appear_before_identity_errors(self):
        """Schema errors must appear before D13 identity errors in the returned list.

        Inject both a schema error (seq wrong type) and a D13 error (wrong real total).
        Schema error must appear first (or at same position but never after identity error).
        """
        import energy_go.telemetry.validate as tv
        msg = _env_step_a()
        msg["seq"] = "not-an-int"  # schema error
        msg["payload"]["costs"]["cost_total_real_yuan"] = 0.0  # D13 identity error
        errs = tv.validate(msg)
        schema_indices = [i for i, e in enumerate(errs) if "schema:" in e]
        d13_indices = [i for i, e in enumerate(errs) if "D13" in e]
        assert schema_indices, f"No schema errors found: {errs}"
        assert d13_indices, f"No D13 errors found: {errs}"
        assert min(schema_indices) < min(d13_indices), (
            f"Schema errors must precede D13 errors; got indices schema={schema_indices}, d13={d13_indices}"
        )

    def test_version_guard_before_schema_errors(self):
        """Version-mismatch error must appear before schema errors (step 1 in guaranteed order).

        Inject both a version mismatch (2.0.0) and a schema error (seq wrong type).
        Version error must be index 0.
        """
        import energy_go.telemetry.validate as tv
        msg = _train_metrics()
        msg["schema_version"] = "2.0.0"
        msg["seq"] = "wrong-type"
        errs = tv.validate(msg)
        assert errs, f"Expected errors: {errs}"
        assert "version" in errs[0].lower(), (
            f"First error must be version-mismatch; got: {errs[0]!r}"
        )


# ---------------------------------------------------------------------------
# CLI refactor obligation
# ---------------------------------------------------------------------------


class TestCLIRefactorObligation:
    def test_cli_imports_from_module(self):
        """scripts/validate_telemetry.py must import check_finite/check_env_step/check_eval_compare
        from energy_go.telemetry.validate (not define them inline).
        """
        cli = REPO_ROOT / "scripts" / "validate_telemetry.py"
        assert cli.exists(), "scripts/validate_telemetry.py not found"
        src = cli.read_text()
        assert "from energy_go.telemetry.validate import" in src, (
            "CLI script must import check_finite/check_env_step/check_eval_compare from module"
        )
        # The old inline function definitions must not be present
        assert "def check_finite(" not in src, "check_finite must be removed from CLI (now imported)"
        assert "def check_env_step(" not in src, "check_env_step must be removed from CLI (now imported)"
        assert "def check_eval_compare(" not in src, "check_eval_compare must be removed from CLI (now imported)"

    def test_cli_still_runs_examples(self):
        """scripts/validate_telemetry.py --examples must still exit 0 after the refactor."""
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "validate_telemetry.py"), "--examples"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"CLI --examples failed after refactor:\n{result.stdout}\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Schema data bundling
# ---------------------------------------------------------------------------


class TestSchemaBundling:
    def test_schema_loaded_from_package_data(self):
        """The module must load telemetry_schema.json without relying on a hard-coded repo path.

        We verify this by confirming the module defines its own schema path logic
        (importlib.resources or fallback), not by patching the filesystem.
        This is a source-inspection test.
        """
        import energy_go.telemetry.validate as tv
        src = Path(tv.__file__).read_text()
        assert "importlib" in src or "pkg_resources" in src or "data" in src, (
            "Module must use importlib.resources or equivalent to find schema"
        )

    def test_schema_version_matches_json(self):
        """SCHEMA_VERSION constant must match the '$id' / 'title' in telemetry_schema.json."""
        import energy_go.telemetry.validate as tv
        schema = json.loads((REPO_ROOT / "contracts" / "shared" / "telemetry_schema.json").read_text())
        # The schema title is "Energy GO telemetry v1.0.0"; version embedded as 'v1.0.0'
        assert tv.SCHEMA_VERSION in schema.get("title", ""), (
            f"SCHEMA_VERSION {tv.SCHEMA_VERSION!r} not found in schema title {schema.get('title')!r}"
        )
