"""Tests for contracts/serving/geo_site_api.md v1.0.0.

Contract: geo_site_api — workstream A serving surface

All test values are derived from the LOCKED upstream contracts:
  - config_validation.md v1.0.0 (ValidationIssue shape, rule_ids)
  - device_model_schema.md v2.0.0 (physics values, Gansu 4 model IDs)
  - tariff_model_schema.md v1.0.0 (cn-gansu 24-vector, band names, demand_rate)

Units: ¥/MWh for tariff prices; MW for generator/grid power; MWh for battery energy;
       m/s for wind speeds; m for hub height; °C for temperature; W/m² for irradiance.
"""
from __future__ import annotations

import json
import time
import pytest
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """TestClient for the serving app (with lifespan startup)."""
    from energy_go.serving.app import app
    with TestClient(app) as c:
        yield c


# Gansu site config dict (mirrors contracts/shared/device_model_schema.md §7)
GANSU_SITE_CONFIG = {
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
        # (12, 24) seasonal tariff — required by device_model_schema v2.0.0 (E-TAR-SHAPE check).
        # All 12 months identical (seasonally flat Gansu TOU): valley=250, mid=450,
        # peak=620, critical_peak=780 ¥/MWh.  tariff_model_schema §7.1 / D8.
        "price_table_yuan_per_mwh": [
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Jan
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Feb
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Mar
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Apr
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # May
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Jun
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Jul
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Aug
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Sep
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Oct
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Nov
            [250, 250, 250, 250, 250, 250, 250, 450, 620, 620, 620, 780, 450, 450, 450, 450, 450, 450, 620, 780, 780, 620, 620, 250],  # Dec
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

# Minimal device_models dict — physics for the 4 Gansu device IDs
GANSU_DEVICE_MODELS = {
    "schema_version": "2.0.0",
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
        },
        "trina-vertex-n-670w": {
            "type": "pv_panel",
            "physics": {
                "k_T_per_c": -0.003,
                "eta_inverter": 0.97,
                "degradation_yr1": 0.98,
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
        },
        "pcc-substation-945mw": {
            "type": "grid_connection",
            "physics": {
                "max_export_mw": 945.0,
                "max_import_mw": 400.0,
            },
        },
    },
}


# ---------------------------------------------------------------------------
# §3.1  POST /api/site/validate
# ---------------------------------------------------------------------------

class TestSiteValidate:

    def test_gansu_clean_no_errors_no_warnings(self, client):
        """Gansu config + device_models → errors=[], warnings=[].
        Arithmetic: 98.16/294.5=0.3333C ≤ 100/300=0.3333C (E-BAT-CRATE OK);
                    294.5/98.16=3.00h ≤ 10h (W-BAT-DUR-10H OK);
                    (12,24) tariff matrix (E-TAR-SHAPE OK with device_model_schema v2.0.0).
        """
        resp = client.post("/api/site/validate", json={
            "site_config": GANSU_SITE_CONFIG,
            "device_models": GANSU_DEVICE_MODELS,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["errors"] == [], f"Expected no errors for Gansu, got: {body['errors']}"
        assert body["warnings"] == [], f"Expected no warnings for Gansu, got: {body['warnings']}"

    def test_negative_battery_capacity_yields_e_cap_pos(self, client):
        """battery.fleet_capacity_mwh = -10 → E-CAP-POS hard error.
        Arithmetic: -10.0 ≤ 0, not(x > 0) is True → E-CAP-POS fired.
        """
        bad_config = {
            **GANSU_SITE_CONFIG,
            "assets": {
                **GANSU_SITE_CONFIG["assets"],
                "battery": {
                    "model": "catl-lmp-300mwh",
                    "fleet_capacity_mwh": -10.0,  # invalid
                    "fleet_power_mw": 98.16,
                },
            },
        }
        resp = client.post("/api/site/validate", json={
            "site_config": bad_config,
            "device_models": GANSU_DEVICE_MODELS,
        })
        assert resp.status_code == 200
        body = resp.json()
        rule_ids = [e["rule_id"] for e in body["errors"]]
        assert "E-CAP-POS" in rule_ids, f"Expected E-CAP-POS in errors, got: {body['errors']}"

    def test_e_cap_pos_error_fields_present(self, client):
        """ValidationIssue shape: rule_id, field, message, constraint — all strings."""
        bad_config = {
            **GANSU_SITE_CONFIG,
            "assets": {
                **GANSU_SITE_CONFIG["assets"],
                "wind": {
                    "model": "vestas-v150-4.2",
                    "fleet_rated_mw": 0.0,  # ≤ 0 → E-CAP-POS
                },
            },
        }
        resp = client.post("/api/site/validate", json={
            "site_config": bad_config,
            "device_models": GANSU_DEVICE_MODELS,
        })
        body = resp.json()
        errors = [e for e in body["errors"] if e["rule_id"] == "E-CAP-POS"]
        assert len(errors) >= 1
        issue = errors[0]
        for field_name in ("rule_id", "field", "message", "constraint"):
            assert field_name in issue, f"Missing field '{field_name}' in ValidationIssue"
            assert isinstance(issue[field_name], str), f"'{field_name}' must be str"
        # No 'severity' field — severity is implicit per LOCKED contract §2
        assert "severity" not in issue

    def test_http_200_even_with_errors(self, client):
        """Validation failure returns HTTP 200 (not 422/400) — errors in body."""
        bad_config = {"assets": {"battery": {"fleet_capacity_mwh": -1.0}}}
        resp = client.post("/api/site/validate", json={"site_config": bad_config})
        assert resp.status_code == 200

    def test_missing_device_models_skips_device_rules(self, client):
        """device_models absent → device-dependent rules (E-BAT-CRATE, W-BAT-CRATE-2C)
        silently skipped, not errored (config_validation.md §3.3).
        """
        # Config with very high C-rate that would fail E-BAT-CRATE with device_models
        high_crate_config = {
            **GANSU_SITE_CONFIG,
            "assets": {
                **GANSU_SITE_CONFIG["assets"],
                "battery": {
                    "model": "catl-lmp-300mwh",
                    "fleet_capacity_mwh": 100.0,
                    "fleet_power_mw": 400.0,  # 400/100 = 4.0C >> device limit
                },
            },
        }
        # Without device_models: E-BAT-CRATE must NOT appear
        resp_no_models = client.post("/api/site/validate", json={
            "site_config": high_crate_config,
            # device_models omitted
        })
        assert resp_no_models.status_code == 200
        body_no = resp_no_models.json()
        rule_ids_no = [e["rule_id"] for e in body_no["errors"]]
        assert "E-BAT-CRATE" not in rule_ids_no, (
            "E-BAT-CRATE must be skipped when device_models is absent"
        )

    def test_high_crate_with_device_models_yields_e_bat_crate(self, client):
        """400MW/100MWh = 4.0C > device limit 100MW/300MWh = 0.333C → E-BAT-CRATE.
        Arithmetic: 400/100=4.0C; device: 100/300=0.333C; 4.0>0.333 → error.
        """
        high_crate_config = {
            **GANSU_SITE_CONFIG,
            "assets": {
                **GANSU_SITE_CONFIG["assets"],
                "battery": {
                    "model": "catl-lmp-300mwh",
                    "fleet_capacity_mwh": 100.0,
                    "fleet_power_mw": 400.0,
                },
            },
        }
        resp = client.post("/api/site/validate", json={
            "site_config": high_crate_config,
            "device_models": GANSU_DEVICE_MODELS,
        })
        body = resp.json()
        rule_ids = [e["rule_id"] for e in body["errors"]]
        assert "E-BAT-CRATE" in rule_ids

    def test_tariff_wrong_shape_yields_e_tar_shape(self, client):
        """Tariff table with 12 entries (not 24) → E-TAR-SHAPE.
        Arithmetic: len=12 ≠ 24 → E-TAR-SHAPE.
        """
        bad_tariff_config = {
            **GANSU_SITE_CONFIG,
            "tariff": {
                "price_table_yuan_per_mwh": [250.0] * 12,  # wrong length
            },
        }
        resp = client.post("/api/site/validate", json={
            "site_config": bad_tariff_config,
            "device_models": GANSU_DEVICE_MODELS,
        })
        body = resp.json()
        rule_ids = [e["rule_id"] for e in body["errors"]]
        assert "E-TAR-SHAPE" in rule_ids

    def test_battery_duration_warning(self, client):
        """294.5MWh / 9.816MW = 30.0h > 10h → W-BAT-DUR-10H soft warning.
        Arithmetic: 294.5/9.816 ≈ 30.0h > 10h → warning fires.
        """
        long_dur_config = {
            **GANSU_SITE_CONFIG,
            "assets": {
                **GANSU_SITE_CONFIG["assets"],
                "battery": {
                    "model": "catl-lmp-300mwh",
                    "fleet_capacity_mwh": 294.5,
                    "fleet_power_mw": 9.816,  # ~30h duration
                },
            },
        }
        resp = client.post("/api/site/validate", json={
            "site_config": long_dur_config,
            "device_models": GANSU_DEVICE_MODELS,
        })
        body = resp.json()
        warn_ids = [w["rule_id"] for w in body["warnings"]]
        assert "W-BAT-DUR-10H" in warn_ids

    def test_missing_site_config_key_returns_400(self, client):
        """Request missing 'site_config' key → HTTP 400."""
        resp = client.post("/api/site/validate", json={"device_models": {}})
        assert resp.status_code == 400

    def test_validate_returns_all_errors_exhaustively(self, client):
        """Multiple hard violations → all collected (non-short-circuiting per §3.1 invariant).
        Both wind (fleet_rated_mw=0) and battery (fleet_capacity_mwh=-1) bad → both E-CAP-POS.
        """
        multi_bad_config = {
            **GANSU_SITE_CONFIG,
            "assets": {
                **GANSU_SITE_CONFIG["assets"],
                "wind": {
                    "model": "vestas-v150-4.2",
                    "fleet_rated_mw": 0.0,
                },
                "battery": {
                    "model": "catl-lmp-300mwh",
                    "fleet_capacity_mwh": -1.0,
                    "fleet_power_mw": 98.16,
                },
            },
        }
        resp = client.post("/api/site/validate", json={
            "site_config": multi_bad_config,
            "device_models": GANSU_DEVICE_MODELS,
        })
        body = resp.json()
        e_cap_pos_fields = [
            e["field"] for e in body["errors"] if e["rule_id"] == "E-CAP-POS"
        ]
        # Both fields must appear — not short-circuited
        assert any("fleet_rated_mw" in f for f in e_cap_pos_fields)
        assert any("fleet_capacity_mwh" in f for f in e_cap_pos_fields)

    def test_passthrough_fidelity_matches_validate_directly(self, client):
        # reviewer: backend-reviewer (PR #94) — D32(i)/D18 single-source-of-truth.
        # The endpoint MUST be a pure passthrough of energy_go.env.config_validation.validate():
        # its errors/warnings must be EXACTLY what validate() produces on the same input —
        # same rule_id sets, nothing re-derived, added, or dropped. The per-rule tests confirm
        # individual rules surface; this pins exact fidelity, which is the whole point of the
        # "never re-implements rules" guarantee the D18 architecture rests on. Compares against
        # a DIRECT validate() call (no hardcoded rule list), so it stays correct as rules evolve.
        from energy_go.env.config_validation import validate
        cfg = {
            **GANSU_SITE_CONFIG,
            "assets": {
                **GANSU_SITE_CONFIG["assets"],
                "battery": {
                    "model": "catl-lmp-300mwh",
                    "fleet_capacity_mwh": -5.0,   # E-CAP-POS (hard error)
                    "fleet_power_mw": 98.16,
                },
            },
            "tariff": {"price_table_yuan_per_mwh": [1, 2, 3]},  # E-TAR-SHAPE (hard error)
        }
        direct = validate(cfg, GANSU_DEVICE_MODELS)
        resp = client.post("/api/site/validate", json={
            "site_config": cfg, "device_models": GANSU_DEVICE_MODELS,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert {e.rule_id for e in direct.errors} == {e["rule_id"] for e in body["errors"]}, (
            "endpoint errors must EXACTLY match validate() — no rule re-implementation (D32(i))"
        )
        assert {w.rule_id for w in direct.warnings} == {w["rule_id"] for w in body["warnings"]}, (
            "endpoint warnings must EXACTLY match validate() — no rule re-implementation (D32(i))"
        )

    def test_site_config_not_a_dict_returns_400(self, client):
        # reviewer: backend-reviewer (PR #94) — contract §3.1: "HTTP 400 ... site_config is not
        # a dict". Only the missing-key trigger is tested (test_missing_site_config_key_returns_400);
        # this pins the present-but-non-dict trigger the contract also specifies. Note: validate()
        # itself tolerates a non-dict (returns empty per config_validation §3.2), so the 400 MUST
        # originate from the endpoint's request-shape guard — not from validate() raising.
        resp = client.post("/api/site/validate", json={"site_config": "not-a-dict"})
        assert resp.status_code == 400, (
            f"site_config that is present but not a dict must be HTTP 400; got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# §3.2  GET /api/tariff/regions
# ---------------------------------------------------------------------------

class TestTariffRegions:

    def test_list_returns_cn_gansu(self, client):
        """Region list includes cn-gansu."""
        resp = client.get("/api/tariff/regions")
        assert resp.status_code == 200
        body = resp.json()
        ids = [r["region_id"] for r in body["regions"]]
        assert "cn-gansu" in ids

    def test_schema_version_present(self, client):
        resp = client.get("/api/tariff/regions")
        body = resp.json()
        assert "schema_version" in body
        assert isinstance(body["schema_version"], str)

    def test_each_region_has_required_fields(self, client):
        """Each region entry has: region_id, currency, price_min, price_max,
        demand_rate_yuan_per_mw_month, provenance.
        """
        resp = client.get("/api/tariff/regions")
        body = resp.json()
        required = {"region_id", "currency", "price_min_yuan_per_mwh",
                    "price_max_yuan_per_mwh", "demand_rate_yuan_per_mw_month",
                    "provenance"}
        for region in body["regions"]:
            missing = required - region.keys()
            assert not missing, f"Region {region.get('region_id')} missing fields: {missing}"

    def test_gansu_price_min_le_max(self, client):
        """price_min_yuan_per_mwh ≤ price_max_yuan_per_mwh for cn-gansu.
        Gansu: min=250 ¥/MWh (valley), max=780 ¥/MWh (critical peak).
        """
        resp = client.get("/api/tariff/regions")
        body = resp.json()
        gansu = next(r for r in body["regions"] if r["region_id"] == "cn-gansu")
        assert gansu["price_min_yuan_per_mwh"] <= gansu["price_max_yuan_per_mwh"]
        # Gansu specific values (from tariff_model_schema.md §3)
        assert gansu["price_min_yuan_per_mwh"] == pytest.approx(250.0)
        assert gansu["price_max_yuan_per_mwh"] == pytest.approx(780.0)

    def test_gansu_demand_rate(self, client):
        """cn-gansu demand_rate = 32000.0 ¥/MW·month (tariff_model_schema §3)."""
        resp = client.get("/api/tariff/regions")
        body = resp.json()
        gansu = next(r for r in body["regions"] if r["region_id"] == "cn-gansu")
        # 32000 ¥/MW·month from §3.7 + tariff_model_schema §3
        assert gansu["demand_rate_yuan_per_mw_month"] == pytest.approx(32000.0)

    def test_provenance_is_string(self, client):
        resp = client.get("/api/tariff/regions")
        body = resp.json()
        for region in body["regions"]:
            assert region["provenance"] in ("public", "private")


# ---------------------------------------------------------------------------
# §3.3  GET /api/tariff/regions/{region_id}
# ---------------------------------------------------------------------------

class TestTariffRegionDetail:

    def test_gansu_price_table_shape(self, client):
        """cn-gansu price_table_yuan_per_mwh has shape (12, 24).
        Invariant from tariff_model_schema §2 and device_model_schema v2.0.0.
        """
        resp = client.get("/api/tariff/regions/cn-gansu")
        assert resp.status_code == 200
        body = resp.json()
        table = body["price_table_yuan_per_mwh"]
        assert len(table) == 12, f"Expected 12 rows, got {len(table)}"
        for i, row in enumerate(table):
            assert len(row) == 24, f"Month {i}: expected 24 hours, got {len(row)}"

    def test_gansu_all_months_identical(self, client):
        """cn-gansu initial entry: 12 identical rows (replicated ×12 per tariff_model_schema §3)."""
        resp = client.get("/api/tariff/regions/cn-gansu")
        body = resp.json()
        table = body["price_table_yuan_per_mwh"]
        row0 = table[0]
        for m, row in enumerate(table[1:], start=1):
            assert row == pytest.approx(row0), f"Month {m} differs from month 0"

    def test_gansu_price_table_values(self, client):
        """Spot-check Gansu hourly prices against LOCKED Gansu vector.
        From tariff_model_schema §3 and device_model_schema §6:
          h=0  → 250 ¥/MWh (valley)
          h=7  → 450 ¥/MWh (mid)
          h=8  → 620 ¥/MWh (peak)
          h=11 → 780 ¥/MWh (critical peak) — minute=0 → 11:00 < 11:30 → critical_peak
          h=12 → 450 ¥/MWh (mid)
          h=19 → 780 ¥/MWh (critical peak)
          h=23 → 250 ¥/MWh (valley)
        """
        resp = client.get("/api/tariff/regions/cn-gansu")
        body = resp.json()
        row = body["price_table_yuan_per_mwh"][0]  # any month (all identical in v1)
        checks = {0: 250.0, 7: 450.0, 8: 620.0, 11: 780.0,
                  12: 450.0, 19: 780.0, 23: 250.0}
        for h, expected in checks.items():
            assert row[h] == pytest.approx(expected), (
                f"h={h}: expected {expected} ¥/MWh, got {row[h]}"
            )

    def test_monthly_bands_count(self, client):
        """monthly_bands has exactly 12 entries."""
        resp = client.get("/api/tariff/regions/cn-gansu")
        body = resp.json()
        assert len(body["monthly_bands"]) == 12

    def test_monthly_bands_cover_full_day_no_gaps(self, client):
        """For each month, bands cover [0, 24) without gaps or overlaps.
        Bands must be contiguous: band[k].end_hour == band[k+1].start_hour.
        First band start=0; last band end=24.
        """
        resp = client.get("/api/tariff/regions/cn-gansu")
        body = resp.json()
        for entry in body["monthly_bands"]:
            bands = entry["bands"]
            assert bands[0]["start_hour"] == 0, "First band must start at hour 0"
            assert bands[-1]["end_hour"] == 24, "Last band must end at hour 24"
            for i in range(len(bands) - 1):
                assert bands[i]["end_hour"] == bands[i + 1]["start_hour"], (
                    f"Gap/overlap between band {i} and {i+1} in month {entry['month']}"
                )

    def test_tariff_band_schema(self, client):
        """TariffBand has name (str), start_hour (int), end_hour (int),
        price_yuan_per_mwh (float). start_hour < end_hour.
        """
        resp = client.get("/api/tariff/regions/cn-gansu")
        body = resp.json()
        bands = body["monthly_bands"][0]["bands"]
        for band in bands:
            assert isinstance(band["name"], str)
            assert isinstance(band["start_hour"], int)
            assert isinstance(band["end_hour"], int)
            assert isinstance(band["price_yuan_per_mwh"], float)
            assert band["start_hour"] < band["end_hour"]

    def test_gansu_band_names_correct(self, client):
        """Gansu month-0 bands: 250→valley, 450→mid, 620→peak, 780→critical_peak.
        From tariff_model_schema §7.1 band-name lookup table.
        """
        resp = client.get("/api/tariff/regions/cn-gansu")
        body = resp.json()
        bands = body["monthly_bands"][0]["bands"]
        name_for_price = {b["price_yuan_per_mwh"]: b["name"] for b in bands}
        assert name_for_price[250.0] == "valley"
        assert name_for_price[450.0] == "mid"
        assert name_for_price[620.0] == "peak"
        assert name_for_price[780.0] == "critical_peak"

    def test_sell_clamp_present_and_units(self, client):
        """sell_clamp has spread=30 ¥/MWh and noise_std=10 ¥/MWh (tariff_model_schema §3)."""
        resp = client.get("/api/tariff/regions/cn-gansu")
        body = resp.json()
        sc = body["sell_clamp"]
        # Values from D7 / tariff_model_schema §3
        assert sc["spread_yuan_per_mwh"] == pytest.approx(30.0)
        assert sc["spread_noise_std_yuan_per_mwh"] == pytest.approx(10.0)

    def test_unknown_region_returns_400(self, client):
        resp = client.get("/api/tariff/regions/cn-nonexistent")
        assert resp.status_code == 400
        body = resp.json()
        assert body.get("code") == "TARIFF_REGION_NOT_FOUND"


# ---------------------------------------------------------------------------
# §3.4  GET /api/tariff/bands/{region_id}?month=N
# ---------------------------------------------------------------------------

class TestTariffBands:

    def test_gansu_month_0_bands_match_expected_rle(self, client):
        """RLE of Gansu month-0 vector (24 values) expected bands:
        [0-7)→250(valley), [7-8)→450(mid), [8-11)→620(peak), [11-12)→780(critical_peak),
        [12-18)→450(mid), [18-19)→620(peak), [19-21)→780(critical_peak),
        [21-23)→620(peak), [23-24)→250(valley).
        9 bands total.
        """
        resp = client.get("/api/tariff/bands/cn-gansu?month=0")
        assert resp.status_code == 200
        body = resp.json()
        assert body["region_id"] == "cn-gansu"
        assert body["month"] == 0
        bands = body["bands"]
        # Each band: (start, end, name)
        expected = [
            (0,  7,  "valley"),
            (7,  8,  "mid"),
            (8,  11, "peak"),
            (11, 12, "critical_peak"),
            (12, 18, "mid"),
            (18, 19, "peak"),
            (19, 21, "critical_peak"),
            (21, 23, "peak"),
            (23, 24, "valley"),
        ]
        assert len(bands) == len(expected), (
            f"Expected {len(expected)} bands, got {len(bands)}: {bands}"
        )
        for i, (exp_start, exp_end, exp_name) in enumerate(expected):
            b = bands[i]
            assert b["start_hour"] == exp_start, f"Band {i} start: {b['start_hour']} ≠ {exp_start}"
            assert b["end_hour"] == exp_end, f"Band {i} end: {b['end_hour']} ≠ {exp_end}"
            assert b["name"] == exp_name, f"Band {i} name: {b['name']} ≠ {exp_name}"

    def test_bands_cover_full_24_hours(self, client):
        """Bands [start,end) must cover [0,24) exactly — no gap, no overlap."""
        resp = client.get("/api/tariff/bands/cn-gansu?month=0")
        bands = resp.json()["bands"]
        cursor = 0
        for b in bands:
            assert b["start_hour"] == cursor, f"Gap at hour {cursor}"
            cursor = b["end_hour"]
        assert cursor == 24

    def test_unknown_region_returns_400(self, client):
        resp = client.get("/api/tariff/bands/cn-unknown?month=0")
        assert resp.status_code == 400
        assert resp.json()["code"] == "TARIFF_REGION_NOT_FOUND"

    def test_month_out_of_range_returns_400(self, client):
        """month=12 is out of [0, 11] → HTTP 400."""
        resp = client.get("/api/tariff/bands/cn-gansu?month=12")
        assert resp.status_code == 400
        assert resp.json()["code"] == "TARIFF_MONTH_OUT_OF_RANGE"

    def test_month_negative_returns_400(self, client):
        resp = client.get("/api/tariff/bands/cn-gansu?month=-1")
        assert resp.status_code == 400

    def test_price_yuan_per_mwh_values_are_float(self, client):
        """price_yuan_per_mwh must be float (not int) in JSON response."""
        resp = client.get("/api/tariff/bands/cn-gansu?month=0")
        bands = resp.json()["bands"]
        for b in bands:
            assert isinstance(b["price_yuan_per_mwh"], float), (
                f"price_yuan_per_mwh should be float, got {type(b['price_yuan_per_mwh'])}"
            )

    # reviewer: test that all 12 months are reachable (month=11 boundary)
    def test_month_11_dec_returns_200(self, client):
        """month=11 (December) is the last valid month — must return 200."""
        resp = client.get("/api/tariff/bands/cn-gansu?month=11")
        assert resp.status_code == 200
        body = resp.json()
        assert body["month"] == 11
        assert len(body["bands"]) > 0

    # reviewer: test that bands contain no zero-width entries (start == end)
    def test_no_zero_width_bands(self, client):
        """Every band must have end_hour > start_hour (non-zero width)."""
        resp = client.get("/api/tariff/bands/cn-gansu?month=0")
        for b in resp.json()["bands"]:
            assert b["end_hour"] > b["start_hour"], f"Zero-width band: {b}"


# ---------------------------------------------------------------------------
# §3.5  POST /api/site/weather/fetch
# ---------------------------------------------------------------------------

class TestWeatherFetch:

    def test_valid_request_returns_job_id_and_queued_status(self, client):
        """Valid request returns job_id string and status='queued'."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 38.5,
            "lon": 99.9,
            "years": [2020, 2021, 2022],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["job_id"], str)
        assert body["status"] == "queued"
        assert body["lat"] == pytest.approx(38.5)
        assert body["lon"] == pytest.approx(99.9)
        assert body["years"] == [2020, 2021, 2022]

    def test_lat_out_of_range_returns_400(self, client):
        """lat=95.0 > 90 → HTTP 400, code WEATHER_PARAM_INVALID."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 95.0,  # > 90
            "lon": 99.9,
            "years": [2020],
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "WEATHER_PARAM_INVALID"

    def test_lon_out_of_range_returns_400(self, client):
        """lon=-181 < -180 → HTTP 400."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 38.5,
            "lon": -181.0,
            "years": [2020],
        })
        assert resp.status_code == 400

    def test_empty_years_returns_400(self, client):
        """Empty years list → HTTP 400."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 38.5, "lon": 99.9, "years": [],
        })
        assert resp.status_code == 400

    def test_years_too_long_returns_400(self, client):
        """years list with 21 entries (> 20) → HTTP 400."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 38.5, "lon": 99.9,
            "years": list(range(2000, 2021)),  # 21 years
        })
        assert resp.status_code == 400

    def test_year_out_of_range_returns_400(self, client):
        """year=1939 < 1940 → HTTP 400."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 38.5, "lon": 99.9, "years": [1939],
        })
        assert resp.status_code == 400

    def test_future_year_out_of_range_returns_400(self, client):
        """year=2025 > 2024 (max allowed) → HTTP 400."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 38.5, "lon": 99.9, "years": [2025],
        })
        assert resp.status_code == 400

    def test_each_request_returns_distinct_job_ids(self, client):
        """Two separate POST requests return distinct job_ids."""
        resp1 = client.post("/api/site/weather/fetch", json={
            "lat": 38.5, "lon": 99.9, "years": [2020],
        })
        resp2 = client.post("/api/site/weather/fetch", json={
            "lat": 38.5, "lon": 99.9, "years": [2021],
        })
        assert resp1.json()["job_id"] != resp2.json()["job_id"]

    # reviewer: boundary lat/lon exactly at limits must be accepted
    def test_lat_lon_at_exact_limits_accepted(self, client):
        """lat=90, lon=180 are valid boundary values — must return 200."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 90.0, "lon": 180.0, "years": [2020],
        })
        assert resp.status_code == 200

    # reviewer: lat=-90, lon=-180 boundary
    def test_lat_lon_at_negative_limits_accepted(self, client):
        """lat=-90, lon=-180 are valid — must return 200."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": -90.0, "lon": -180.0, "years": [2020],
        })
        assert resp.status_code == 200

    # reviewer: single year at min (1940) is valid
    def test_year_min_boundary_accepted(self, client):
        """year=1940 is the minimum valid year — must return 200."""
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 38.5, "lon": 99.9, "years": [1940],
        })
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# §3.6  GET /api/site/weather/jobs/{job_id}
# ---------------------------------------------------------------------------

class TestWeatherJobStatus:

    def _start_job(self, client) -> str:
        resp = client.post("/api/site/weather/fetch", json={
            "lat": 38.5, "lon": 99.9, "years": [2020],
        })
        return resp.json()["job_id"]

    def test_unknown_job_returns_404(self, client):
        resp = client.get("/api/site/weather/jobs/no-such-job")
        assert resp.status_code == 404
        assert resp.json()["code"] == "JOB_NOT_FOUND"

    def test_known_job_returns_status_field(self, client):
        job_id = self._start_job(client)
        resp = client.get(f"/api/site/weather/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == job_id
        assert body["status"] in ("queued", "running", "done", "error")
        assert "progress_pct" in body
        assert isinstance(body["progress_pct"], (int, float))
        assert 0 <= body["progress_pct"] <= 100

    def test_queued_status_has_no_result_field(self, client):
        """A queued job must not have a 'result' field (no premature data)."""
        job_id = self._start_job(client)
        resp = client.get(f"/api/site/weather/jobs/{job_id}")
        body = resp.json()
        if body["status"] == "queued":
            assert "result" not in body or body.get("result") is None

    def test_done_result_schema(self, client):
        """When status='done', result has required fields with correct units."""
        # This test requires the job to complete — skip if it stays queued
        job_id = self._start_job(client)
        # Poll briefly (in unit tests, cache hit may resolve immediately)
        for _ in range(5):
            resp = client.get(f"/api/site/weather/jobs/{job_id}")
            body = resp.json()
            if body["status"] == "done":
                result = body["result"]
                assert "cache_path" in result
                assert "years_cached" in result
                assert isinstance(result["years_cached"], list)
                assert "row_count" in result
                assert isinstance(result["row_count"], int)
                # Summary stats — float, units: m/s, W/m², °C
                assert "wind_mps_mean" in result
                assert "irr_wm2_mean" in result
                assert "temp_c_mean" in result
                assert isinstance(result["wind_mps_mean"], float)
                assert isinstance(result["irr_wm2_mean"], float)
                assert isinstance(result["temp_c_mean"], float)
                return
            time.sleep(0.1)
        pytest.skip("Job did not complete in polling window — skip done-result check")

    def test_error_status_has_error_message(self, client):
        """If status='error', error_message is a non-empty string."""
        # Create a job; if it errors, verify the schema
        job_id = self._start_job(client)
        for _ in range(5):
            resp = client.get(f"/api/site/weather/jobs/{job_id}")
            body = resp.json()
            if body["status"] == "error":
                assert "error_message" in body
                assert isinstance(body["error_message"], str)
                assert len(body["error_message"]) > 0
                return
            time.sleep(0.1)
        pytest.skip("Job did not enter error state in polling window")

    # reviewer: terminal states (done/error) must not re-transition
    def test_done_job_stays_done_on_subsequent_poll(self, client):
        """A done job polled again must still return status='done' (terminal state)."""
        job_id = self._start_job(client)
        # Poll until done or give up
        for _ in range(10):
            resp = client.get(f"/api/site/weather/jobs/{job_id}")
            if resp.json()["status"] == "done":
                # Poll again — must still be done
                resp2 = client.get(f"/api/site/weather/jobs/{job_id}")
                assert resp2.json()["status"] == "done"
                return
            time.sleep(0.1)
        pytest.skip("Job did not complete for terminal-state test")


# ---------------------------------------------------------------------------
# §3.7  GET /api/site/weather-coverage
# ---------------------------------------------------------------------------

class TestWeatherCoverage:

    def test_valid_coords_returns_200_and_available(self, client):
        """Gansu coords (38.5, 99.9) → historical_available=true."""
        resp = client.get("/api/site/weather-coverage?lat=38.5&lon=99.9")
        assert resp.status_code == 200
        body = resp.json()
        assert body["historical_available"] is True
        assert body["bootstrap_available"] is True
        assert body["lat"] == pytest.approx(38.5)
        assert body["lon"] == pytest.approx(99.9)

    def test_response_schema(self, client):
        """All required fields present with correct types."""
        resp = client.get("/api/site/weather-coverage?lat=38.5&lon=99.9")
        body = resp.json()
        assert isinstance(body["historical_available"], bool)
        assert isinstance(body["bootstrap_available"], bool)
        assert isinstance(body["available_year_count"], int)
        assert body["source"] == "open_meteo"
        # year_range is [int, int] or null
        yr = body["year_range"]
        if yr is not None:
            assert len(yr) == 2
            assert yr[0] <= yr[1]

    def test_lat_out_of_range_returns_400(self, client):
        """lat=91 → HTTP 400, code COVERAGE_PARAM_INVALID."""
        resp = client.get("/api/site/weather-coverage?lat=91&lon=99.9")
        assert resp.status_code == 400
        assert resp.json()["code"] == "COVERAGE_PARAM_INVALID"

    def test_lon_out_of_range_returns_400(self, client):
        resp = client.get("/api/site/weather-coverage?lat=38.5&lon=181")
        assert resp.status_code == 400

    def test_missing_lat_returns_400(self, client):
        resp = client.get("/api/site/weather-coverage?lon=99.9")
        assert resp.status_code == 400

    def test_missing_lon_returns_400(self, client):
        resp = client.get("/api/site/weather-coverage?lat=38.5")
        assert resp.status_code == 400

    def test_lat_lon_echoed_in_response(self, client):
        """lat/lon in request are echoed in response body."""
        resp = client.get("/api/site/weather-coverage?lat=35.0&lon=110.0")
        body = resp.json()
        assert body["lat"] == pytest.approx(35.0)
        assert body["lon"] == pytest.approx(110.0)

    # reviewer: available_year_count matches year_range length
    def test_available_year_count_consistent_with_year_range(self, client):
        """If year_range is [start, end], available_year_count = end - start + 1."""
        resp = client.get("/api/site/weather-coverage?lat=38.5&lon=99.9")
        body = resp.json()
        yr = body["year_range"]
        if yr is not None:
            expected_count = yr[1] - yr[0] + 1
            assert body["available_year_count"] == expected_count, (
                f"year_range={yr} but available_year_count={body['available_year_count']}"
            )


# ---------------------------------------------------------------------------
# §3.8  GET /api/devices/models
# ---------------------------------------------------------------------------

class TestDeviceModels:

    # Gansu device IDs from LOCKED device_model_schema §6 + registry.json
    GANSU_IDS = {
        "vestas-v150-4.2",
        "trina-vertex-n-670w",
        "catl-lmp-300mwh",
        "pcc-substation-945mw",
    }

    def test_all_4_gansu_models_present(self, client):
        """All 4 LOCKED Gansu device IDs are in the model list."""
        resp = client.get("/api/devices/models")
        assert resp.status_code == 200
        body = resp.json()
        ids = set(body["models"].keys())
        missing = self.GANSU_IDS - ids
        assert not missing, f"Missing device models: {missing}"

    def test_schema_version_present(self, client):
        resp = client.get("/api/devices/models")
        body = resp.json()
        assert "schema_version" in body

    def test_model_id_key_matches_entry(self, client):
        """The map key equals model_id field in each entry."""
        resp = client.get("/api/devices/models")
        for key, entry in resp.json()["models"].items():
            assert entry["model_id"] == key, (
                f"Key '{key}' ≠ model_id '{entry['model_id']}'"
            )

    def test_type_field_valid_values(self, client):
        """type must be one of: wind_turbine, pv_panel, battery, grid_connection."""
        valid_types = {"wind_turbine", "pv_panel", "battery", "grid_connection"}
        resp = client.get("/api/devices/models")
        for entry in resp.json()["models"].values():
            assert entry["type"] in valid_types

    def test_vestas_physics_values_match_locked_contract(self, client):
        """vestas-v150-4.2 physics must match LOCKED device_model_schema §6.
        v_cutin=3.0 m/s; v_rated=12.0 m/s; v_cutout=25.0 m/s;
        hub_height=105.0 m; rated_mw_per_unit=4.2 MW.
        Units: m/s for speeds, m for height, MW for power per unit.
        """
        resp = client.get("/api/devices/models")
        phy = resp.json()["models"]["vestas-v150-4.2"]["physics"]
        assert phy["v_cutin_mps"]        == pytest.approx(3.0)
        assert phy["v_rated_mps"]        == pytest.approx(12.0)
        assert phy["v_cutout_mps"]       == pytest.approx(25.0)
        assert phy["hub_height_m"]       == pytest.approx(105.0)
        assert phy["rated_mw_per_unit"]  == pytest.approx(4.2)   # MW, not kW

    def test_catl_physics_values_match_locked_contract(self, client):
        """catl-lmp-300mwh: eta_ch=0.97, soc_min=0.2, capacity_mwh=300 MWh, power_mw=100 MW.
        Units: MWh for capacity, MW for power (not kWh/kW).
        """
        resp = client.get("/api/devices/models")
        phy = resp.json()["models"]["catl-lmp-300mwh"]["physics"]
        assert phy["eta_ch"]                 == pytest.approx(0.97)
        assert phy["soc_min"]                == pytest.approx(0.2)
        assert phy["capacity_mwh_per_unit"]  == pytest.approx(300.0)   # MWh
        assert phy["power_mw_per_unit"]      == pytest.approx(100.0)   # MW

    def test_pcc_physics_values(self, client):
        """pcc-substation-945mw: max_export=945 MW, max_import=400 MW."""
        resp = client.get("/api/devices/models")
        phy = resp.json()["models"]["pcc-substation-945mw"]["physics"]
        assert phy["max_export_mw"] == pytest.approx(945.0)   # MW
        assert phy["max_import_mw"] == pytest.approx(400.0)   # MW

    def test_economics_field_present_and_dict(self, client):
        """Each model has an 'economics' field (may be empty dict per schema §1.3)."""
        resp = client.get("/api/devices/models")
        for entry in resp.json()["models"].values():
            assert "economics" in entry
            assert isinstance(entry["economics"], dict)

    def test_vestas_economics_units(self, client):
        """vestas-v150-4.2 economics: capex_per_kw_yuan (¥/kW), not ¥/MW.
        Value from device_model_schema §1.4: 5800.0 ¥/kW.
        """
        resp = client.get("/api/devices/models")
        econ = resp.json()["models"]["vestas-v150-4.2"]["economics"]
        if "capex_per_kw_yuan" in econ:
            # 5800 ¥/kW (≈800 USD/kW at 2024 exchange rate) — sanity range check
            # Source: device_model_schema §1.4
            assert econ["capex_per_kw_yuan"] == pytest.approx(5800.0)

    # reviewer: no model should have mixed-unit economics fields (kW vs MW)
    def test_battery_capex_unit_is_per_kwh_not_per_mwh(self, client):
        """catl economics: capex_energy_per_kwh_yuan (¥/kWh), NOT ¥/MWh.
        Value from device_model_schema §1.4: 1000.0 ¥/kWh.
        """
        resp = client.get("/api/devices/models")
        econ = resp.json()["models"]["catl-lmp-300mwh"]["economics"]
        if "capex_energy_per_kwh_yuan" in econ:
            # 1000 ¥/kWh (≈140 USD/kWh LFP 2024) — per device_model_schema §1.4
            assert econ["capex_energy_per_kwh_yuan"] == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# §3.9  GET /api/devices/models/{model_id}
# ---------------------------------------------------------------------------

class TestDeviceModelDetail:

    def test_known_model_returns_200(self, client):
        resp = client.get("/api/devices/models/vestas-v150-4.2")
        assert resp.status_code == 200

    def test_detail_matches_list_entry(self, client):
        """Single-model detail equals the corresponding entry in the list response."""
        list_resp = client.get("/api/devices/models")
        detail_resp = client.get("/api/devices/models/vestas-v150-4.2")
        list_entry = list_resp.json()["models"]["vestas-v150-4.2"]
        detail_entry = detail_resp.json()
        assert detail_entry["model_id"] == list_entry["model_id"]
        assert detail_entry["type"] == list_entry["type"]
        assert detail_entry["physics"] == list_entry["physics"]

    def test_unknown_model_returns_400(self, client):
        resp = client.get("/api/devices/models/nonexistent-model")
        assert resp.status_code == 400
        assert resp.json()["code"] == "DEVICE_MODEL_NOT_FOUND"

    def test_all_4_gansu_models_retrievable_individually(self, client):
        for model_id in [
            "vestas-v150-4.2",
            "trina-vertex-n-670w",
            "catl-lmp-300mwh",
            "pcc-substation-945mw",
        ]:
            resp = client.get(f"/api/devices/models/{model_id}")
            assert resp.status_code == 200, f"Model {model_id} not retrievable"


# ---------------------------------------------------------------------------
# §3.10  GET /api/devices/search
# ---------------------------------------------------------------------------

class TestDeviceSearch:

    def test_prefix_search_vestas(self, client):
        """q=vestas returns at least the vestas-v150-4.2 model."""
        resp = client.get("/api/devices/search?q=vestas")
        assert resp.status_code == 200
        body = resp.json()
        ids = [r["model_id"] for r in body["results"]]
        assert "vestas-v150-4.2" in ids

    def test_prefix_search_catl(self, client):
        """q=catl returns catl-lmp-300mwh."""
        resp = client.get("/api/devices/search?q=catl")
        body = resp.json()
        ids = [r["model_id"] for r in body["results"]]
        assert "catl-lmp-300mwh" in ids

    def test_empty_q_returns_all_models(self, client):
        """q='' (empty string) returns all models."""
        resp = client.get("/api/devices/search?q=")
        body = resp.json()
        assert len(body["results"]) >= 4  # at least 4 Gansu models

    def test_limit_respected(self, client):
        """limit=1 returns at most 1 result."""
        resp = client.get("/api/devices/search?q=&limit=1")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) <= 1

    def test_result_schema(self, client):
        """Each result has model_id, type, label fields."""
        resp = client.get("/api/devices/search?q=vestas")
        result = resp.json()["results"][0]
        assert "model_id" in result
        assert "type" in result
        assert "label" in result
        assert isinstance(result["label"], str)

    def test_wind_turbine_label_format(self, client):
        """Wind turbine label contains MW and hub height in metres.
        Gansu: 4.2 MW, 105m hub (device_model_schema §6).
        """
        resp = client.get("/api/devices/search?q=vestas")
        results = {r["model_id"]: r for r in resp.json()["results"]}
        label = results["vestas-v150-4.2"]["label"]
        assert "4.2" in label, f"Label should contain rated MW: {label}"
        assert "MW" in label, f"Label should have unit MW: {label}"

    def test_battery_label_format(self, client):
        """Battery label contains MWh and MW.
        Gansu catl: 300 MWh / 100 MW (device_model_schema §6).
        """
        resp = client.get("/api/devices/search?q=catl")
        results = {r["model_id"]: r for r in resp.json()["results"]}
        label = results["catl-lmp-300mwh"]["label"]
        assert "MWh" in label, f"Battery label must mention MWh: {label}"
        assert "MW" in label, f"Battery label must mention MW: {label}"

    def test_no_q_param_returns_400(self, client):
        """Missing q parameter → HTTP 400."""
        resp = client.get("/api/devices/search")
        assert resp.status_code == 400

    def test_limit_over_50_returns_400(self, client):
        """limit=51 > max(50) → HTTP 400."""
        resp = client.get("/api/devices/search?q=&limit=51")
        assert resp.status_code == 400

    def test_limit_zero_returns_400(self, client):
        """limit=0 < min(1) → HTTP 400."""
        resp = client.get("/api/devices/search?q=&limit=0")
        assert resp.status_code == 400

    def test_no_matching_results_returns_empty_list(self, client):
        """q=zzzyyyxxx matches nothing → results=[] (not 404)."""
        resp = client.get("/api/devices/search?q=zzzyyyxxx")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    # reviewer: result type field matches device_model_schema type values
    def test_type_field_in_results_is_valid(self, client):
        valid_types = {"wind_turbine", "pv_panel", "battery", "grid_connection"}
        resp = client.get("/api/devices/search?q=")
        for r in resp.json()["results"]:
            assert r["type"] in valid_types, f"Invalid type: {r['type']}"

    # reviewer: case-insensitive search (q=VESTAS matches vestas-v150-4.2)
    def test_case_insensitive_search(self, client):
        """Search is case-insensitive: q=VESTAS matches vestas-v150-4.2."""
        resp = client.get("/api/devices/search?q=VESTAS")
        assert resp.status_code == 200
        ids = [r["model_id"] for r in resp.json()["results"]]
        assert "vestas-v150-4.2" in ids, f"Case-insensitive search failed: {ids}"

    # reviewer: limit=50 (max) is accepted
    def test_limit_at_max_accepted(self, client):
        """limit=50 is the maximum — must return 200."""
        resp = client.get("/api/devices/search?q=&limit=50")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# D38 — ACTIVE_DEVICE_TYPES filter regression (inert-exclusion guard)
# ---------------------------------------------------------------------------

class TestActiveDeviceFilter:
    """D38 regression: INERT/gated catalog entries must be ABSENT from the
    device-feed endpoints even when present in device_models.yaml.

    Two exclusion mechanisms are tested:

    1. **Type-based exclusion** — electrolyzer_pem (h-tec-pem-1mw, D35/D38):
       excluded because "electrolyzer_pem" ∉ ACTIVE_DEVICE_TYPES (type-allowlist arm
       of is_surfaceable).  Covers all future INERT type families automatically.

    2. **Provenance-based exclusion** — pcc-sst-stub (D38 instance-inert clause):
       injected with its REAL type "grid_connection" (∈ ACTIVE_DEVICE_TYPES) but
       with provenance "USER-provided, pending".  is_surfaceable() returns False
       because provenance == "USER-provided, pending", so the entry is hidden from
       the feed without touching its LOCKED benchmark_device_library type.

    Live-feed tests (no monkeypatch) run against the REAL config/device_models.yaml
    and assert pcc-sst-stub is absent from all three endpoints.

    Technique: monkeypatch the module-level _device_models_cache to inject a synthetic
    device_models dict.  _get_device_models() returns the cache directly when not None,
    so the patch is seen by all three device endpoints during the test.  monkeypatch
    restores the original cache value after the test (function-scoped restore,
    module-scoped client unaffected).
    """

    # Synthetic device_models dict injected by monkeypatch tests.
    # ONE active + ONE INERT-type entry (electrolyzer) + ONE INERT-provenance entry (pcc-sst-stub).
    _FAKE_MODELS = {
        "schema_version": "2.2.0",   # D35 schema version
        "models": {
            "vestas-v150-4.2": {     # ACTIVE — wind_turbine ∈ ACTIVE_DEVICE_TYPES, no pending provenance
                "type": "wind_turbine",
                "physics": {
                    "v_cutin_mps": 3.0, "v_rated_mps": 12.0, "v_cutout_mps": 25.0,
                    "hub_height_m": 105.0, "rated_mw_per_unit": 4.2,
                },
                "economics": {"capex_per_kw_yuan": 5800.0},
            },
            "h-tec-pem-1mw": {       # INERT via TYPE — electrolyzer_pem ∉ ACTIVE_DEVICE_TYPES (D35/D38)
                "type": "electrolyzer_pem",
                "physics": {
                    "stack_efficiency_kwh_per_kg": 55.0,
                    "max_power_mw_per_unit": 1.0,
                },
                "economics": {"capex_per_kw_yuan": 1200.0},
            },
            "pcc-sst-stub": {        # INERT via PROVENANCE — type grid_connection ∈ ACTIVE_DEVICE_TYPES
                # Injected with its REAL type "grid_connection" (matches actual device_models.yaml
                # and LOCKED benchmark_device_library contract).  Excluded from the feed because
                # provenance == "USER-provided, pending" — the provenance arm of is_surfaceable().
                # This exactly mirrors the on-disk entry; no LOCKED contract needs to change.
                "type": "grid_connection",
                "provenance": "USER-provided, pending",
                "physics": {"max_export_mw": 200.0, "max_import_mw": 200.0},
                "economics": {},
            },
        },
    }

    def test_inert_electrolyzer_absent_from_models_list(self, client, monkeypatch):
        """INERT entries must NOT appear in GET /api/devices/models.

        Injects _FAKE_MODELS (one ACTIVE, one INERT-type, one INERT-provenance).
        The list endpoint must surface only the active entry.

        Arithmetic:
          vestas-v150-4.2: type wind_turbine ∈ ACTIVE, no pending provenance → is_surfaceable=True
          h-tec-pem-1mw:   type electrolyzer_pem ∉ ACTIVE                   → is_surfaceable=False
          pcc-sst-stub:    type grid_connection ∈ ACTIVE, BUT provenance=="USER-provided, pending"
                           → is_surfaceable=False (provenance arm)
        """
        import energy_go.serving.geo_site_api as geo_api
        monkeypatch.setattr(geo_api, "_device_models_cache", self._FAKE_MODELS)

        resp = client.get("/api/devices/models")
        assert resp.status_code == 200
        models = resp.json()["models"]

        # Active model must be present
        assert "vestas-v150-4.2" in models, (
            "Active wind_turbine model must be in device feed"
        )
        # INERT electrolyzer must be absent (D38)
        assert "h-tec-pem-1mw" not in models, (
            "INERT electrolyzer_pem model must be excluded from device feed (D38)"
        )
        # INERT pcc-sst-stub (with stub type) must be absent (D38)
        assert "pcc-sst-stub" not in models, (
            "INERT grid_connection_stub model must be excluded from device feed (D38)"
        )

    def test_inert_electrolyzer_and_stub_absent_from_search(self, client, monkeypatch):
        """INERT entries must NOT appear in GET /api/devices/search.

        Same injection as test_inert_electrolyzer_absent_from_models_list.
        h-tec-pem-1mw excluded via type-arm; pcc-sst-stub excluded via provenance-arm.
        """
        import energy_go.serving.geo_site_api as geo_api
        monkeypatch.setattr(geo_api, "_device_models_cache", self._FAKE_MODELS)

        # Search for the INERT electrolyzer by prefix
        resp = client.get("/api/devices/search?q=h-tec")
        assert resp.status_code == 200
        ids = [r["model_id"] for r in resp.json()["results"]]
        assert "h-tec-pem-1mw" not in ids, (
            "INERT electrolyzer_pem must be excluded from device search (D38)"
        )

        # Search for the INERT pcc-sst-stub by prefix
        resp_sst = client.get("/api/devices/search?q=pcc-sst")
        ids_sst = [r["model_id"] for r in resp_sst.json()["results"]]
        assert "pcc-sst-stub" not in ids_sst, (
            "INERT grid_connection_stub (pcc-sst-stub) must be excluded from search (D38)"
        )

        # Active model remains searchable
        resp2 = client.get("/api/devices/search?q=vestas")
        ids2 = [r["model_id"] for r in resp2.json()["results"]]
        assert "vestas-v150-4.2" in ids2, (
            "Active wind_turbine must still appear in search after D38 filter"
        )

    def test_inert_model_detail_returns_400(self, client, monkeypatch):
        """Requesting an INERT model by ID must return 400 DEVICE_MODEL_NOT_FOUND.

        The detail endpoint treats INERT models as absent from the feed — same
        code path as requesting a model_id that doesn't exist at all. (D38.)
        Both the electrolyzer and the pcc-sst-stub (with stub type) must return 400.
        """
        import energy_go.serving.geo_site_api as geo_api
        monkeypatch.setattr(geo_api, "_device_models_cache", self._FAKE_MODELS)

        for inert_id in ("h-tec-pem-1mw", "pcc-sst-stub"):
            resp = client.get(f"/api/devices/models/{inert_id}")
            assert resp.status_code == 400, (
                f"INERT model '{inert_id}' must return 400 from detail endpoint, "
                f"got {resp.status_code}"
            )
            assert resp.json()["code"] == "DEVICE_MODEL_NOT_FOUND", (
                f"DEVICE_MODEL_NOT_FOUND code expected for INERT model '{inert_id}' (D38)"
            )

    def test_live_feed_excludes_pcc_sst_stub(self, client):
        """pcc-sst-stub must be ABSENT from the live device feed (REAL device_models.yaml).

        Runs against the REAL config/device_models.yaml — no monkeypatch.
        pcc-sst-stub has type: grid_connection (ACTIVE, LOCKED in benchmark_device_library)
        but provenance: "USER-provided, pending".  is_surfaceable() must return False
        for it (provenance arm), so it is absent from all three device endpoints.

        Three assertions:
          (a) GET /api/devices/models — pcc-sst-stub absent from the models map.
          (b) GET /api/devices/search?q=pcc-sst — pcc-sst-stub absent from search results.
          (c) GET /api/devices/models/pcc-sst-stub — returns 400 DEVICE_MODEL_NOT_FOUND.
        """
        # (a) list
        resp = client.get("/api/devices/models")
        assert resp.status_code == 200
        models = resp.json()["models"]
        assert "pcc-sst-stub" not in models, (
            "pcc-sst-stub must be excluded from live device feed (D38 provenance arm)"
        )

        # (b) search
        resp_s = client.get("/api/devices/search?q=pcc-sst")
        assert resp_s.status_code == 200
        ids = [r["model_id"] for r in resp_s.json()["results"]]
        assert "pcc-sst-stub" not in ids, (
            "pcc-sst-stub must be excluded from device search (D38 provenance arm)"
        )

        # (c) detail endpoint
        resp_d = client.get("/api/devices/models/pcc-sst-stub")
        assert resp_d.status_code == 400, (
            f"pcc-sst-stub detail must return 400 (excluded by D38), got {resp_d.status_code}"
        )
        assert resp_d.json()["code"] == "DEVICE_MODEL_NOT_FOUND", (
            "DEVICE_MODEL_NOT_FOUND code expected for pcc-sst-stub detail (D38 provenance arm)"
        )

    def test_is_surfaceable_imported_from_resolver(self, client):
        """is_surfaceable must be imported from energy_go.env.resolver (D18/D38).

        Verifies the single-source invariant for the compound predicate: the function
        used by the feed endpoints is the canonical resolver export, not a local copy.
        """
        from energy_go.env.resolver import is_surfaceable as resolver_fn
        import energy_go.serving.geo_site_api as geo_api

        assert geo_api.is_surfaceable is resolver_fn, (
            "geo_site_api.is_surfaceable must be the exact same object as "
            "energy_go.env.resolver.is_surfaceable — no local serving copy (D18)"
        )

    def test_is_surfaceable_logic(self, client):
        """is_surfaceable() predicate: active-type + no-pending-provenance = True.

        Unit-tests the four cases of the compound predicate to pin both arms:
          (1) active type, no provenance     → True  (normal active device)
          (2) active type, pending provenance → False (provenance-pending stub)
          (3) inert type, no provenance      → False (INERT device family)
          (4) inert type, pending provenance → False (both arms fail)
        """
        from energy_go.env.resolver import is_surfaceable

        # (1) active, no provenance — surfaceable
        assert is_surfaceable({"type": "wind_turbine"}) is True, (
            "active type with no provenance key must be surfaceable"
        )
        # (2) active type, pending provenance — NOT surfaceable
        assert is_surfaceable(
            {"type": "grid_connection", "provenance": "USER-provided, pending"}
        ) is False, (
            "active type with provenance=='USER-provided, pending' must NOT be surfaceable"
        )
        # (3) inert type, no provenance — NOT surfaceable
        assert is_surfaceable({"type": "electrolyzer_pem"}) is False, (
            "INERT type with no provenance must NOT be surfaceable"
        )
        # (4) both arms fail — NOT surfaceable
        assert is_surfaceable(
            {"type": "electrolyzer_pem", "provenance": "USER-provided, pending"}
        ) is False, (
            "INERT type with pending provenance must NOT be surfaceable"
        )

    def test_active_device_types_imported_from_resolver(self, client):
        """ACTIVE_DEVICE_TYPES must be imported from energy_go.env.resolver (D18/D38).

        Verifies the single-source invariant: the set used by the feed is NOT a
        local serving literal but the canonical resolver export.  Fails if the
        serving module defines its own copy instead of importing.
        """
        from energy_go.env.resolver import ACTIVE_DEVICE_TYPES as resolver_set
        import energy_go.serving.geo_site_api as geo_api

        # The module-level name in geo_site_api must resolve to the resolver's object
        assert geo_api.ACTIVE_DEVICE_TYPES is resolver_set, (
            "geo_site_api.ACTIVE_DEVICE_TYPES must be the exact same object as "
            "energy_go.env.resolver.ACTIVE_DEVICE_TYPES — no local serving copy (D18)"
        )

    def test_active_device_types_contains_4_gansu_types(self, client):
        """ACTIVE_DEVICE_TYPES must contain exactly the 4 Gansu resolver-live categories.

        Arithmetic: the Gansu parity set = {wind_turbine, pv_panel, battery, grid_connection}.
        These are the 4 types with a composition-rule entry in _NON_OVERRIDABLE (resolver.py).
        Any deviation is a contract violation (D38).
        """
        from energy_go.env.resolver import ACTIVE_DEVICE_TYPES
        expected = {"wind_turbine", "pv_panel", "battery", "grid_connection"}
        assert ACTIVE_DEVICE_TYPES == expected, (
            f"ACTIVE_DEVICE_TYPES must equal the 4 Gansu resolver-live types; "
            f"got {ACTIVE_DEVICE_TYPES}"
        )
