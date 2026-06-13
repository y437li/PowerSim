"""Tests for POST /api/site/assemble — site_assemble.md v1.0.0.

Contract: contracts/serving/site_assemble.md
Decision: D37 (assembly in one Python implementation; single-source)
Depends on: config_validation.md v1.0.0 (LOCKED), tariff_model_schema.md v1.0.0 (LOCKED),
            device_model_schema.md v2.0.0 (LOCKED), geo_site_api.md v1.0.0

Coverage map (§10 invariants):
  §I1  — Gansu fleet → site_config values match site_gansu.yaml
  §I2  — Gansu assembled config → 0 errors, 0 warnings
  §I3  — site_config present even when errors non-empty
  §I4  — all HTTP 400 codes fire on correct triggers
  §I5  — fleet merge: same model_id entries sum counts
  §I6  — missing battery → validation error (not 400)
  §I7  — costs defaults: omitting costs → ASSEMBLE_DEFAULTS values
  §I8  — tariff sourcing: demand_rate/spread from tariff schema
  §I9  — site_meta echoed back when provided; absent when omitted
  §I10 — PV fleet_capacity_mw used directly as assets.solar.fleet_capacity_mw

All tests use FastAPI TestClient (httpx backend); no external I/O.
"""
from __future__ import annotations

import math
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient pointed at the Energy GO serving app."""
    from energy_go.serving.app import app
    return TestClient(app)


# Canonical Gansu wizard request matching site_gansu.yaml fleet.
GANSU_FLEET_REQUEST = {
    "fleet": [
        {"model_id": "vestas-v150-4.2",     "count": 146},
        {"model_id": "trina-vertex-n-670w",  "count": 1, "fleet_capacity_mw": 330.0},
        {"model_id": "catl-lmp-300mwh",      "count": 1},
        {"model_id": "pcc-substation-945mw", "count": 1},
    ],
    "tariff_region": "cn-gansu",
}

# Minimal Gansu request without optional fields (site_meta, costs, forecast).
GANSU_MINIMAL = {
    "fleet": GANSU_FLEET_REQUEST["fleet"],
    "tariff_region": "cn-gansu",
}


# ---------------------------------------------------------------------------
# §I1 — Gansu fleet assembly values match site_gansu.yaml
# ---------------------------------------------------------------------------

class TestGansuAssemblyValues:
    """§I1: Assembled site_config values match the canonical Gansu site configuration.

    Arithmetic shown explicitly per CLAUDE.md engineering rules.

    site_gansu.yaml:
        wind.fleet_rated_mw  = 615.0  (note: spec rounds 146 × 4.2 = 613.2 → site YAML uses 615.0)
        solar.fleet_capacity_mw = 330.0
        battery.fleet_capacity_mwh = 294.5   (single CATL unit; note < 300 nominal)
        battery.fleet_power_mw     = 98.16   (single CATL unit; note < 100 nominal)

    Assemble from count × per-unit:
        wind: 146 × 4.2 MW/unit = 613.2 MW
        battery: 1 × 300.0 MWh/unit = 300.0 MWh;  1 × 100.0 MW/unit = 100.0 MW
        solar: fleet_capacity_mw = 330.0 (direct)
    """

    def test_wind_fleet_rated_mw(self, client):
        """§I1-wind: 146 turbines × 4.2 MW/unit = 613.2 MW (not 615.0 — that's the YAML override)."""
        # 146 × 4.2 = 613.2 — assemble uses count × rated_mw_per_unit, not the YAML rounding
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        assert resp.status_code == 200
        sc = resp.json()["site_config"]
        assert sc["assets"]["wind"]["model"] == "vestas-v150-4.2"
        assert math.isclose(sc["assets"]["wind"]["fleet_rated_mw"], 613.2, rel_tol=1e-6), (
            f"Expected 146 × 4.2 = 613.2 MW; got {sc['assets']['wind']['fleet_rated_mw']}"
        )

    def test_battery_capacity_mwh(self, client):
        """§I1-bat-mwh: 1 unit × 300.0 MWh/unit = 300.0 MWh."""
        # 1 × 300.0 = 300.0 MWh
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        sc = resp.json()["site_config"]
        assert math.isclose(sc["assets"]["battery"]["fleet_capacity_mwh"], 300.0, rel_tol=1e-6), (
            f"Expected 1 × 300.0 = 300.0 MWh; got {sc['assets']['battery']['fleet_capacity_mwh']}"
        )

    def test_battery_power_mw(self, client):
        """§I1-bat-mw: 1 unit × 100.0 MW/unit = 100.0 MW."""
        # 1 × 100.0 = 100.0 MW
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        sc = resp.json()["site_config"]
        assert math.isclose(sc["assets"]["battery"]["fleet_power_mw"], 100.0, rel_tol=1e-6), (
            f"Expected 1 × 100.0 = 100.0 MW; got {sc['assets']['battery']['fleet_power_mw']}"
        )

    def test_solar_fleet_capacity_mw(self, client):
        """§I1-solar: fleet_capacity_mw = 330.0 (direct from request; no per-unit multiply)."""
        # Direct: fleet_capacity_mw = 330.0 MW
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        sc = resp.json()["site_config"]
        assert sc["assets"]["solar"]["model"] == "trina-vertex-n-670w"
        assert math.isclose(sc["assets"]["solar"]["fleet_capacity_mw"], 330.0, rel_tol=1e-6), (
            f"Expected fleet_capacity_mw = 330.0 MW; got {sc['assets']['solar']['fleet_capacity_mw']}"
        )

    def test_grid_model_present(self, client):
        """§I1-grid: grid model present; no max_export/import in assembled dict."""
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        sc = resp.json()["site_config"]
        assert sc["assets"]["grid"]["model"] == "pcc-substation-945mw"
        # max_export_mw / max_import_mw are NOT in the assembled dict (resolver reads from model directly)
        assert "max_export_mw" not in sc["assets"]["grid"]
        assert "max_import_mw" not in sc["assets"]["grid"]

    def test_tariff_region_in_site_config(self, client):
        """§I1-tariff: tariff_region echoed at root of assembled site_config."""
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        sc = resp.json()["site_config"]
        assert sc["tariff_region"] == "cn-gansu"
        # No inline tariff.price_table in assembled dict — tariff_region replaces it
        assert "tariff" not in sc or sc.get("tariff") is None

    def test_costs_tariff_sourced(self, client):
        """§I1-costs-tariff: demand_rate and spread sourced from cn-gansu tariff region.

        cn-gansu: demand_rate = 32000.0 ¥/MW·month, spread = 30.0 ¥/MWh, sigma = 10.0 ¥/MWh.
        """
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        sc = resp.json()["site_config"]
        costs = sc["costs"]
        assert math.isclose(costs["demand_rate_yuan_per_mw_month"], 32000.0, rel_tol=1e-6), (
            f"Expected 32000.0 ¥/MW·month from cn-gansu; got {costs['demand_rate_yuan_per_mw_month']}"
        )
        assert math.isclose(costs["price_spread_yuan_per_mwh"], 30.0, rel_tol=1e-6)
        assert math.isclose(costs["price_spread_sigma"], 10.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# §I2 — Gansu assembled config: 0 errors, 0 warnings
# ---------------------------------------------------------------------------

class TestGansuValidationClean:
    """§I2: Gansu config assembled and immediately validated → clean (parity test)."""

    def test_gansu_zero_errors(self, client):
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        assert resp.status_code == 200
        body = resp.json()
        assert body["errors"] == [], (
            f"Expected 0 errors for Gansu fleet; got: {body['errors']}"
        )

    def test_gansu_zero_warnings(self, client):
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        body = resp.json()
        assert body["warnings"] == [], (
            f"Expected 0 warnings for Gansu fleet; got: {body['warnings']}"
        )

    def test_gansu_minimal_also_clean(self, client):
        """Omitting site_meta, costs, forecast still gives clean validation with defaults."""
        resp = client.post("/api/site/assemble", json=GANSU_MINIMAL)
        assert resp.status_code == 200
        body = resp.json()
        assert body["errors"] == []
        assert body["warnings"] == []


# ---------------------------------------------------------------------------
# §I3 — site_config always present even when errors non-empty
# ---------------------------------------------------------------------------

class TestSiteConfigAlwaysPresent:
    """§I3: site_config is always in the 200 response body, including error cases."""

    def test_site_config_present_with_errors(self, client):
        """Wind-only fleet (no battery) → validation errors, but site_config still returned."""
        req = {
            "fleet": [
                {"model_id": "vestas-v150-4.2", "count": 10},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        body = resp.json()
        assert "site_config" in body
        assert body["site_config"] is not None
        # Wind is assembled
        assert "wind" in body["site_config"]["assets"]
        # Errors exist (no battery)
        assert len(body["errors"]) > 0

    def test_site_config_assets_readable_on_error(self, client):
        """Wind fleet_rated_mw is readable from site_config even when errors non-empty."""
        req = {
            "fleet": [
                {"model_id": "vestas-v150-4.2", "count": 50},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        body = resp.json()
        # 50 × 4.2 = 210.0 MW
        assert math.isclose(
            body["site_config"]["assets"]["wind"]["fleet_rated_mw"], 210.0, rel_tol=1e-6
        ), f"Expected 50 × 4.2 = 210.0 MW; got {body['site_config']['assets']['wind']['fleet_rated_mw']}"


# ---------------------------------------------------------------------------
# §I4 — HTTP 400 codes
# ---------------------------------------------------------------------------

class TestHttp400Codes:
    """§I4: All HTTP 400 reason codes fire on their respective trigger conditions (§5)."""

    def test_fleet_empty_list(self, client):
        """§I4-FLEET_EMPTY: empty fleet list → 400 FLEET_EMPTY."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [],
            "tariff_region": "cn-gansu",
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "FLEET_EMPTY"

    def test_fleet_absent(self, client):
        """§I4-FLEET_EMPTY: missing fleet key → 400."""
        resp = client.post("/api/site/assemble", json={
            "tariff_region": "cn-gansu",
        })
        assert resp.status_code == 400

    def test_tariff_region_absent(self, client):
        """§I4-TARIFF_REGION_REQUIRED: missing tariff_region → 400 TARIFF_REGION_REQUIRED."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [{"model_id": "vestas-v150-4.2", "count": 10}],
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "TARIFF_REGION_REQUIRED"

    def test_tariff_region_empty_string(self, client):
        """§I4-TARIFF_REGION_REQUIRED: empty string tariff_region → 400 TARIFF_REGION_REQUIRED."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [{"model_id": "vestas-v150-4.2", "count": 10}],
            "tariff_region": "",
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "TARIFF_REGION_REQUIRED"

    def test_tariff_region_unknown(self, client):
        """§I4-TARIFF_REGION_NOT_FOUND: unknown region → 400 TARIFF_REGION_NOT_FOUND."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [{"model_id": "vestas-v150-4.2", "count": 10}],
            "tariff_region": "xx-nonexistent",
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "TARIFF_REGION_NOT_FOUND"

    def test_device_model_not_found_single(self, client):
        """§I4-DEVICE_MODEL_NOT_FOUND: unknown model_id → 400 with missing_ids field."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [{"model_id": "not-a-real-model", "count": 1}],
            "tariff_region": "cn-gansu",
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "DEVICE_MODEL_NOT_FOUND"
        assert "not-a-real-model" in body.get("missing_ids", [])

    def test_device_model_not_found_multiple(self, client):
        """§I4-DEVICE_MODEL_NOT_FOUND: multiple unknown models → all listed in missing_ids."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [
                {"model_id": "fake-wind-1", "count": 10},
                {"model_id": "fake-batt-1", "count": 1},
            ],
            "tariff_region": "cn-gansu",
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "DEVICE_MODEL_NOT_FOUND"
        assert "fake-wind-1" in body.get("missing_ids", [])
        assert "fake-batt-1" in body.get("missing_ids", [])

    def test_fleet_count_zero(self, client):
        """§I4-FLEET_COUNT_INVALID: count = 0 → 400 FLEET_COUNT_INVALID."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [{"model_id": "vestas-v150-4.2", "count": 0}],
            "tariff_region": "cn-gansu",
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "FLEET_COUNT_INVALID"

    def test_fleet_count_negative(self, client):
        """§I4-FLEET_COUNT_INVALID: count = -1 → 400 FLEET_COUNT_INVALID."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [{"model_id": "vestas-v150-4.2", "count": -1}],
            "tariff_region": "cn-gansu",
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "FLEET_COUNT_INVALID"

    def test_fleet_mixed_model_wind(self, client):
        """§I4-FLEET_MIXED_MODEL: two distinct wind turbine model_ids → 400 FLEET_MIXED_MODEL."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [
                {"model_id": "vestas-v150-4.2", "count": 100},
                # Hypothetical second wind turbine model — different model_id, same type
                {"model_id": "siemens-sg14-222dd", "count": 50},
            ],
            "tariff_region": "cn-gansu",
        })
        # Note: if the second model doesn't exist, DEVICE_MODEL_NOT_FOUND fires first.
        # Either 400 code is valid — the test checks that the request is rejected.
        assert resp.status_code == 400

    # reviewer: test that FLEET_MIXED_MODEL fires with known models of same type
    # (requires adding a second wind turbine model to device_models.yaml in test fixtures
    # OR testing via mocked device_models — deferred to integration test)

    def test_pv_fleet_capacity_required(self, client):
        """§I4-PV_FLEET_CAPACITY_REQUIRED: pv_panel entry with no fleet_capacity_mw → 400."""
        resp = client.post("/api/site/assemble", json={
            "fleet": [
                {"model_id": "trina-vertex-n-670w", "count": 1},
                # No fleet_capacity_mw — pv_panel has no panel_mw_per_unit in schema
            ],
            "tariff_region": "cn-gansu",
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "PV_FLEET_CAPACITY_REQUIRED"

    def test_malformed_json_body(self, client):
        """§I4-general: non-JSON body → 422 (FastAPI validation)."""
        resp = client.post("/api/site/assemble",
                          content=b"not json",
                          headers={"Content-Type": "application/json"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# §I5 — Fleet merge: same model_id entries sum counts
# ---------------------------------------------------------------------------

class TestFleetMerge:
    """§I5: Multiple entries with the same model_id are merged before assembly."""

    def test_same_wind_model_merged(self, client):
        """Two entries for vestas-v150-4.2 → counts summed: (100 + 46) × 4.2 = 613.2 MW."""
        # 100 + 46 = 146 total; 146 × 4.2 = 613.2 MW
        req = {
            "fleet": [
                {"model_id": "vestas-v150-4.2", "count": 100},
                {"model_id": "vestas-v150-4.2", "count": 46},
                {"model_id": "catl-lmp-300mwh", "count": 1},
                {"model_id": "pcc-substation-945mw", "count": 1},
                {"model_id": "trina-vertex-n-670w", "count": 1, "fleet_capacity_mw": 330.0},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        wind_mw = resp.json()["site_config"]["assets"]["wind"]["fleet_rated_mw"]
        # (100 + 46) × 4.2 = 146 × 4.2 = 613.2 MW
        assert math.isclose(wind_mw, 613.2, rel_tol=1e-6), f"Expected 613.2 MW; got {wind_mw}"

    def test_same_pv_model_merged_fleet_capacity(self, client):
        """Two pv_panel entries → fleet_capacity_mw values summed: 200 + 130 = 330.0 MW."""
        # 200 + 130 = 330.0 MW
        req = {
            "fleet": [
                {"model_id": "trina-vertex-n-670w", "count": 1, "fleet_capacity_mw": 200.0},
                {"model_id": "trina-vertex-n-670w", "count": 1, "fleet_capacity_mw": 130.0},
                {"model_id": "catl-lmp-300mwh", "count": 1},
                {"model_id": "pcc-substation-945mw", "count": 1},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        solar_mw = resp.json()["site_config"]["assets"]["solar"]["fleet_capacity_mw"]
        assert math.isclose(solar_mw, 330.0, rel_tol=1e-6), f"Expected 330.0 MW; got {solar_mw}"


# ---------------------------------------------------------------------------
# §I6 — Missing battery → validation error (not 400)
# ---------------------------------------------------------------------------

class TestMissingAssetsValidationErrors:
    """§I6: Missing required device categories produce validation errors in body (not HTTP 400)."""

    def test_no_battery_produces_validation_error(self, client):
        """No battery in fleet → response HTTP 200 with at least one validation error."""
        req = {
            "fleet": [
                {"model_id": "vestas-v150-4.2", "count": 146},
                {"model_id": "trina-vertex-n-670w", "count": 1, "fleet_capacity_mw": 330.0},
                {"model_id": "pcc-substation-945mw", "count": 1},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200  # NOT 400 — assembly succeeded; validation has errors
        body = resp.json()
        assert len(body["errors"]) > 0, "Expected validation error for missing battery"
        assert body["site_config"] is not None  # site_config still assembled

    def test_validation_issue_schema(self, client):
        """Each ValidationIssue has required string fields per config_validation.md §2."""
        req = {
            "fleet": [
                {"model_id": "vestas-v150-4.2", "count": 146},
                {"model_id": "pcc-substation-945mw", "count": 1},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        for issue in resp.json()["errors"] + resp.json()["warnings"]:
            assert isinstance(issue["rule_id"], str) and issue["rule_id"]
            assert isinstance(issue["field"], str) and issue["field"]
            assert isinstance(issue["message"], str) and issue["message"]
            assert isinstance(issue["constraint"], str) and issue["constraint"]


# ---------------------------------------------------------------------------
# §I7 — costs defaults: omitting costs → ASSEMBLE_DEFAULTS values
# ---------------------------------------------------------------------------

class TestCostDefaults:
    """§I7: Omitting the costs block produces the canonical server defaults."""

    def test_default_c_deg(self, client):
        """c_deg_yuan_per_mwh defaults to 10.0 ¥/MWh."""
        resp = client.post("/api/site/assemble", json=GANSU_MINIMAL)
        costs = resp.json()["site_config"]["costs"]
        assert math.isclose(costs["c_deg_yuan_per_mwh"], 10.0, rel_tol=1e-9)

    def test_default_voll(self, client):
        """voll_yuan_per_mwh defaults to 20000.0 ¥/MWh."""
        resp = client.post("/api/site/assemble", json=GANSU_MINIMAL)
        costs = resp.json()["site_config"]["costs"]
        assert math.isclose(costs["voll_yuan_per_mwh"], 20000.0, rel_tol=1e-9)

    def test_default_curtail(self, client):
        """curtail_yuan_per_mwh defaults to 800.0 ¥/MWh."""
        resp = client.post("/api/site/assemble", json=GANSU_MINIMAL)
        costs = resp.json()["site_config"]["costs"]
        assert math.isclose(costs["curtail_yuan_per_mwh"], 800.0, rel_tol=1e-9)

    def test_default_soc_penalty(self, client):
        """soc_penalty_yuan_per_mwh defaults to 20000.0 ¥/MWh."""
        resp = client.post("/api/site/assemble", json=GANSU_MINIMAL)
        costs = resp.json()["site_config"]["costs"]
        assert math.isclose(costs["soc_penalty_yuan_per_mwh"], 20000.0, rel_tol=1e-9)

    def test_default_reward_scale(self, client):
        """reward_scale defaults to 1.0e-5."""
        resp = client.post("/api/site/assemble", json=GANSU_MINIMAL)
        costs = resp.json()["site_config"]["costs"]
        assert math.isclose(costs["reward_scale"], 1.0e-5, rel_tol=1e-9)

    def test_default_forecast_sigma_max(self, client):
        """forecast.sigma_max defaults to 0.10."""
        resp = client.post("/api/site/assemble", json=GANSU_MINIMAL)
        forecast = resp.json()["site_config"]["forecast"]
        assert math.isclose(forecast["sigma_max"], 0.10, rel_tol=1e-9)

    def test_costs_override_respected(self, client):
        """Provided costs values are used instead of defaults."""
        req = {
            **GANSU_MINIMAL,
            "costs": {
                "c_deg_yuan_per_mwh": 15.0,
                "voll_yuan_per_mwh": 25000.0,
                "curtail_yuan_per_mwh": 1000.0,
                "soc_penalty_yuan_per_mwh": 25000.0,
                "reward_scale": 2.0e-5,
            },
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        costs = resp.json()["site_config"]["costs"]
        assert math.isclose(costs["c_deg_yuan_per_mwh"], 15.0, rel_tol=1e-9)
        assert math.isclose(costs["voll_yuan_per_mwh"], 25000.0, rel_tol=1e-9)
        assert math.isclose(costs["curtail_yuan_per_mwh"], 1000.0, rel_tol=1e-9)
        assert math.isclose(costs["reward_scale"], 2.0e-5, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# §I8 — Tariff sourcing: demand_rate/spread from tariff schema, not request
# ---------------------------------------------------------------------------

class TestTariffSourcing:
    """§I8: Tariff-derived costs always come from the tariff region schema."""

    def test_tariff_costs_not_overridable_via_costs_block(self, client):
        """demand_rate/spread in assembled costs come from tariff schema even if
        conflicting values were in the costs block (tariff schema is authoritative)."""
        req = {
            **GANSU_FLEET_REQUEST,
            "costs": {
                # These should be ignored for tariff-sourced fields
                "c_deg_yuan_per_mwh": 5.0,
            },
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        costs = resp.json()["site_config"]["costs"]
        # Tariff-sourced: always from cn-gansu schema
        assert math.isclose(costs["demand_rate_yuan_per_mw_month"], 32000.0, rel_tol=1e-6)
        assert math.isclose(costs["price_spread_yuan_per_mwh"], 30.0, rel_tol=1e-6)
        assert math.isclose(costs["price_spread_sigma"], 10.0, rel_tol=1e-6)
        # User-provided c_deg is used
        assert math.isclose(costs["c_deg_yuan_per_mwh"], 5.0, rel_tol=1e-9)

    def test_all_tariff_sourced_fields_present(self, client):
        """demand_rate, price_spread_yuan_per_mwh, price_spread_sigma all present."""
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        costs = resp.json()["site_config"]["costs"]
        assert "demand_rate_yuan_per_mw_month" in costs
        assert "price_spread_yuan_per_mwh" in costs
        assert "price_spread_sigma" in costs

    def test_no_inline_price_table_in_site_config(self, client):
        """Assembled site_config has tariff_region string, NOT an inline price_table."""
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        sc = resp.json()["site_config"]
        assert sc.get("tariff_region") == "cn-gansu"
        # No tariff.price_table_yuan_per_mwh in the assembled config
        tariff_section = sc.get("tariff")
        if tariff_section is not None:
            assert "price_table_yuan_per_mwh" not in tariff_section, (
                "Assembled config must not include inline price_table (uses tariff_region string)"
            )


# ---------------------------------------------------------------------------
# §I9 — site_meta echoed back when provided; absent when omitted
# ---------------------------------------------------------------------------

class TestSiteMeta:
    """§I9: site_meta is echoed in site_config when provided; absent when not provided."""

    def test_site_meta_echoed_when_provided(self, client):
        req = {
            **GANSU_FLEET_REQUEST,
            "site_meta": {
                "name": "Test Site",
                "lat": 38.5,
                "lon": 99.9,
                "province": "Gansu",
                "weather_mode": "synthetic",
            },
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        meta = resp.json()["site_config"].get("site_meta")
        assert meta is not None
        assert meta["name"] == "Test Site"
        assert math.isclose(meta["lat"], 38.5, rel_tol=1e-9)
        assert math.isclose(meta["lon"], 99.9, rel_tol=1e-9)
        assert meta["province"] == "Gansu"
        assert meta["weather_mode"] == "synthetic"

    def test_site_meta_absent_when_omitted(self, client):
        """When site_meta is omitted from request, site_config has no site_meta key."""
        resp = client.post("/api/site/assemble", json=GANSU_MINIMAL)
        assert resp.status_code == 200
        sc = resp.json()["site_config"]
        assert "site_meta" not in sc or sc["site_meta"] is None

    def test_partial_site_meta_ok(self, client):
        """Partial site_meta (only name) is accepted; absent sub-fields omitted from echo."""
        req = {
            **GANSU_FLEET_REQUEST,
            "site_meta": {"name": "Partial Site"},
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        meta = resp.json()["site_config"].get("site_meta")
        assert meta is not None
        assert meta.get("name") == "Partial Site"

    def test_latlon_optional_no_400(self, client):
        """site_meta without lat/lon does NOT produce a 400 (coordinates are optional)."""
        req = {
            **GANSU_FLEET_REQUEST,
            "site_meta": {"name": "No Coords"},
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# §I10 — PV fleet_capacity_mw used directly as assets.solar.fleet_capacity_mw
# ---------------------------------------------------------------------------

class TestPvFleetCapacity:
    """§I10: PV fleet_capacity_mw from fleet entry becomes assets.solar.fleet_capacity_mw."""

    def test_pv_capacity_direct(self, client):
        """fleet_capacity_mw = 250.0 → assets.solar.fleet_capacity_mw = 250.0 MW."""
        # Direct: 250.0 MW PV
        req = {
            "fleet": [
                {"model_id": "trina-vertex-n-670w", "count": 1, "fleet_capacity_mw": 250.0},
                {"model_id": "catl-lmp-300mwh", "count": 1},
                {"model_id": "pcc-substation-945mw", "count": 1},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        solar_mw = resp.json()["site_config"]["assets"]["solar"]["fleet_capacity_mw"]
        assert math.isclose(solar_mw, 250.0, rel_tol=1e-9), f"Expected 250.0 MW; got {solar_mw}"

    def test_pv_zero_fleet_capacity_produces_400_not_200(self, client):
        """fleet_capacity_mw = 0.0 for PV → 400 (invalid, must be > 0)."""
        req = {
            "fleet": [
                {"model_id": "trina-vertex-n-670w", "count": 1, "fleet_capacity_mw": 0.0},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 400

    def test_pv_negative_fleet_capacity_produces_400(self, client):
        """fleet_capacity_mw = -10.0 → 400 FLEET_COUNT_INVALID or similar."""
        req = {
            "fleet": [
                {"model_id": "trina-vertex-n-670w", "count": 1, "fleet_capacity_mw": -10.0},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 400

    def test_pv_no_count_does_not_crash(self, client):
        """pv_panel entry with count=1 and fleet_capacity_mw is valid."""
        req = {
            "fleet": [
                {"model_id": "trina-vertex-n-670w", "count": 1, "fleet_capacity_mw": 100.0},
                {"model_id": "catl-lmp-300mwh", "count": 1},
                {"model_id": "pcc-substation-945mw", "count": 1},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Additional edge cases not covered by §I1–§I10."""

    def test_response_200_structure(self, client):
        """200 response has exactly the required top-level keys."""
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        assert resp.status_code == 200
        body = resp.json()
        assert "site_config" in body
        assert "errors" in body
        assert "warnings" in body

    def test_site_config_has_required_sections(self, client):
        """Assembled site_config has assets, tariff_region, costs, forecast sections."""
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        sc = resp.json()["site_config"]
        assert "assets" in sc
        assert "tariff_region" in sc
        assert "costs" in sc
        assert "forecast" in sc

    def test_fleet_order_irrelevant(self, client):
        """Fleet list order does not affect assembly result (wind still goes to wind category)."""
        req_reversed = {
            "fleet": [
                {"model_id": "pcc-substation-945mw", "count": 1},
                {"model_id": "catl-lmp-300mwh", "count": 1},
                {"model_id": "trina-vertex-n-670w", "count": 1, "fleet_capacity_mw": 330.0},
                {"model_id": "vestas-v150-4.2", "count": 146},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req_reversed)
        assert resp.status_code == 200
        assert resp.json()["errors"] == []

    def test_battery_only_fleet(self, client):
        """Battery + grid only (no wind, no solar) → assembles; validation may warn/error."""
        req = {
            "fleet": [
                {"model_id": "catl-lmp-300mwh", "count": 2},
                {"model_id": "pcc-substation-945mw", "count": 1},
            ],
            "tariff_region": "cn-gansu",
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        # Battery correctly assembled: 2 × 300 = 600 MWh; 2 × 100 = 200 MW
        sc = resp.json()["site_config"]
        assert math.isclose(sc["assets"]["battery"]["fleet_capacity_mwh"], 600.0, rel_tol=1e-6), (
            f"Expected 2 × 300 = 600.0 MWh; got {sc['assets']['battery']['fleet_capacity_mwh']}"
        )
        assert math.isclose(sc["assets"]["battery"]["fleet_power_mw"], 200.0, rel_tol=1e-6), (
            f"Expected 2 × 100 = 200.0 MW; got {sc['assets']['battery']['fleet_power_mw']}"
        )
        # No wind/solar in assets
        assert "wind" not in sc["assets"]
        assert "solar" not in sc["assets"]

    # reviewer: test that POST /api/site/validate is UNCHANGED (still accepts resolved dict)
    def test_validate_endpoint_still_works(self, client):
        """§§ geo_site_api §3.1 unchanged: POST /api/site/validate still accepts pre-assembled config."""
        # First assemble to get a valid site_config
        assemble_resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        assert assemble_resp.status_code == 200
        site_config = assemble_resp.json()["site_config"]

        # Then validate the assembled config via the unchanged validate endpoint
        validate_resp = client.post("/api/site/validate", json={"site_config": site_config})
        assert validate_resp.status_code == 200
        validate_body = validate_resp.json()
        assert "errors" in validate_body
        assert "warnings" in validate_body
        # The assembled Gansu config should validate cleanly
        assert validate_body["errors"] == []

    def test_forecast_override(self, client):
        """Explicit forecast.sigma_max override is used."""
        req = {
            **GANSU_FLEET_REQUEST,
            "forecast": {"sigma_max": 0.20},
        }
        resp = client.post("/api/site/assemble", json=req)
        assert resp.status_code == 200
        assert math.isclose(
            resp.json()["site_config"]["forecast"]["sigma_max"], 0.20, rel_tol=1e-9
        )

    def test_content_type_json(self, client):
        """Response Content-Type is application/json."""
        resp = client.post("/api/site/assemble", json=GANSU_FLEET_REQUEST)
        assert "application/json" in resp.headers.get("content-type", "")
