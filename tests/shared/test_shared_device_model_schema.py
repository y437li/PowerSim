"""Tests for the device_model_schema shared contract.

Contract: contracts/shared/device_model_schema.md
Spec:     §2.1 (obs), §2.2 (action), §3.1–§3.4 (physics), §7, §8
Decisions: D2, D3, D5, D12, D19, D23

Tests are RED at contract time (resolver + config files not yet implemented).
They turn GREEN after Workstream B implementation.

FIRST ACCEPTANCE GATE: resolve_gansu() == EnvParams() bit-parity on all scalar
fields AND the (24,) price_table array (see TestGansuParity).

All expected values are hand-derived from the contract §8 mapping table and the
current EnvParams() defaults (which the resolver must reproduce exactly).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

# ---------------------------------------------------------------------------
# Imports (RED at contract time — resolver not yet implemented)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

resolver = pytest.importorskip(
    "energy_go.env.resolver",
    reason="resolver not yet implemented — tests are RED at contract stage",
)
resolve_site = resolver.resolve_site
resolve_gansu = resolver.resolve_gansu
DeviceModelError = resolver.DeviceModelError

jax_env = pytest.importorskip(
    "energy_go.env.jax_env",
    reason="jax_env not available",
)
EnvParams = jax_env.EnvParams
PRICE_TABLE_YPW = jax_env.PRICE_TABLE_YPW

# ---------------------------------------------------------------------------
# Expected Gansu values (hand-derived from contract §8 + current EnvParams defaults)
# ---------------------------------------------------------------------------

# §3.1 wind physics (vestas-v150-4.2 model constants)
_EXPECTED_WIND_RATED_MW        = 615.0    # 146 turbines × 4.2 MW rounded per spec
_EXPECTED_WIND_V_CUTIN         = 3.0      # m/s — §3.1
_EXPECTED_WIND_V_RATED         = 12.0     # m/s — §3.1
_EXPECTED_WIND_V_CUTOUT        = 25.0     # m/s — §3.1
_EXPECTED_HUB_HEIGHT_M         = 105.0    # m   — model default, no site override

# §3.2 solar physics (trina-vertex-n-670w model constants)
_EXPECTED_PV_CAPACITY_MW       = 330.0    # MW — fleet total
_EXPECTED_PV_K_T               = -0.003   # /°C — temperature coefficient
_EXPECTED_PV_ETA_INV           = 0.97     # — inverter efficiency
_EXPECTED_PV_DEGRADATION       = 0.98     # — year-1 factor, model default

# §3.3 battery (catl-lmp-300mwh, D4 SOC bounds)
_EXPECTED_BAT_CAPACITY_MWH     = 294.5    # MWh — actual deployed < 300 MWh nominal
_EXPECTED_BAT_POWER_MW         = 98.16    # MW  — actual deployed < 100 MW nominal
_EXPECTED_BAT_ETA_CH           = 0.97     # — charge efficiency
_EXPECTED_BAT_ETA_DIS          = 0.97     # — discharge efficiency
_EXPECTED_SOC_MIN              = 0.2      # — D4
_EXPECTED_SOC_MAX              = 0.9      # — D4
_EXPECTED_SOC_INIT             = 0.5      # — EnvParams default (not in site YAML)

# §3.6 grid (pcc-substation-945mw, D5, D12)
_EXPECTED_GRID_MAX_EXPORT_MW   = 945.0    # MW — model default (D5)
_EXPECTED_GRID_MAX_IMPORT_MW   = 400.0    # MW — model default (D12)

# §3.4 costs
_EXPECTED_C_DEG                = 10.0     # ¥/MWh
_EXPECTED_VOLL                 = 20_000.0 # ¥/MWh — VOLL
_EXPECTED_CURTAIL              = 800.0    # ¥/MWh — curtailment penalty
_EXPECTED_DEMAND_RATE          = 32_000.0 # ¥/MW·month
_EXPECTED_SOC_PENALTY          = 20_000.0 # ¥/MWh — same rate as VOLL
_EXPECTED_REWARD_SCALE         = 1e-5     # §3.5
_EXPECTED_PRICE_SPREAD         = 30.0     # ¥/MWh — D7
_EXPECTED_PRICE_SPREAD_SIGMA   = 10.0     # ¥/MWh — D7
_EXPECTED_FORECAST_SIGMA_MAX   = 0.10     # — D6: 10% at horizon 24
_EXPECTED_EPISODE_LEN          = 168      # steps — D3; EnvParams default

# §3 Gansu TOU tariff — 24 entries, index = hour 0–23 (D8)
# Valley=250, Mid=450, Peak=620, Critical-peak=780 ¥/MWh
# h=0–6: Valley (23:00–07:00)
# h=7: Mid
# h=8–10: Peak
# h=11: Critical peak (10:30–11:30 boundary per D8)
# h=12–17: Mid (11:30–18:00)
# h=18: Peak
# h=19–20: Critical peak (19:00–21:00)
# h=21–22: Peak (21:00–23:00)
# h=23: Valley
_EXPECTED_PRICE_TABLE = np.array([
    250, 250, 250, 250, 250, 250, 250,   # h=0–6   Valley
    450,                                  # h=7     Mid
    620, 620, 620,                        # h=8–10  Peak
    780,                                  # h=11    Critical peak
    450, 450, 450, 450, 450, 450,         # h=12–17 Mid
    620,                                  # h=18    Peak
    780, 780,                             # h=19–20 Critical peak
    620, 620,                             # h=21–22 Peak
    250,                                  # h=23    Valley
], dtype=np.float32)
assert len(_EXPECTED_PRICE_TABLE) == 24, "TOU table must have exactly 24 entries"

_DEVICE_MODELS_PATH = _REPO_ROOT / "config" / "device_models.yaml"
_SITE_GANSU_PATH    = _REPO_ROOT / "config" / "site_gansu.yaml"


# ===========================================================================
# 1. TestYamlSchema — device_models.yaml loads and has correct structure
# ===========================================================================

class TestYamlSchema:
    """config/device_models.yaml exists and satisfies the schema contract."""

    def test_device_models_yaml_exists(self):
        """config/device_models.yaml must exist."""
        assert _DEVICE_MODELS_PATH.exists(), (
            f"config/device_models.yaml not found at {_DEVICE_MODELS_PATH}"
        )

    def test_schema_version_present(self):
        """schema_version: '1.0.0' must be present."""
        with open(_DEVICE_MODELS_PATH) as f:
            doc = yaml.safe_load(f)
        assert doc.get("schema_version") == "1.0.0", (
            f"Expected schema_version '1.0.0'; got {doc.get('schema_version')!r}"
        )

    def test_all_gansu_model_ids_present(self):
        """All 4 LOCKED registry IDs must appear in device_models.yaml."""
        with open(_DEVICE_MODELS_PATH) as f:
            doc = yaml.safe_load(f)
        models = doc.get("models", {})
        required = [
            "vestas-v150-4.2",
            "trina-vertex-n-670w",
            "catl-lmp-300mwh",
            "pcc-substation-945mw",
        ]
        for model_id in required:
            assert model_id in models, (
                f"model_id '{model_id}' missing from device_models.yaml"
            )

    def test_gansu_model_ids_match_registry_json(self):
        """device_models.yaml Gansu IDs must match the LOCKED registry.json keys verbatim.

        # reviewer: registry-drift-guard (frontend-reviewer advisory, PR #79)
        # The binding join-key invariant: device-model ID = same key in both
        # device_models.yaml (physics) and registry.json (3D visual). A mismatch
        # would silently break the serving layer's cross-schema join.
        #
        # registry.json keys for Gansu (from LOCKED v1.0.0):
        #   vestas-v150-4.2, trina-vertex-n-670w, catl-lmp-300mwh, pcc-substation-945mw
        """
        import json
        registry_path = _REPO_ROOT / "assets" / "3d" / "registry.json"
        assert registry_path.exists(), f"registry.json not found at {registry_path}"

        with open(registry_path) as f:
            registry = json.load(f)
        with open(_DEVICE_MODELS_PATH) as f:
            device_models = yaml.safe_load(f)

        registry_ids = set(registry.get("assets", {}).keys())
        model_ids = set(device_models.get("models", {}).keys())

        # Every Gansu registry ID must appear in device_models.yaml
        gansu_registry_ids = {
            "vestas-v150-4.2", "trina-vertex-n-670w",
            "catl-lmp-300mwh", "pcc-substation-945mw",
        }
        for registry_id in gansu_registry_ids:
            assert registry_id in registry_ids, (
                f"Gansu registry ID '{registry_id}' missing from registry.json — "
                f"registry may have drifted"
            )
            assert registry_id in model_ids, (
                f"Gansu registry ID '{registry_id}' missing from device_models.yaml — "
                f"IDs have drifted between registry and device model schema"
            )

        # The 4 Gansu device model IDs must match the 4 Gansu registry entries exactly
        gansu_model_ids = {k for k in model_ids if k in registry_ids}
        assert gansu_model_ids == gansu_registry_ids, (
            f"Gansu device model IDs do not match registry.json Gansu entries.\n"
            f"  In device_models: {gansu_model_ids}\n"
            f"  In registry:      {gansu_registry_ids}"
        )

    def test_model_id_format(self):
        """All model IDs must match ^[a-z0-9][a-z0-9.-]*$ (registry.json convention)."""
        import re
        with open(_DEVICE_MODELS_PATH) as f:
            doc = yaml.safe_load(f)
        pattern = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
        for model_id in doc.get("models", {}):
            assert pattern.match(model_id), (
                f"model_id '{model_id}' violates ^[a-z0-9][a-z0-9.-]*$ format"
            )

    def test_wind_model_required_physics_fields(self):
        """vestas-v150-4.2 must have all required wind_turbine physics fields."""
        with open(_DEVICE_MODELS_PATH) as f:
            doc = yaml.safe_load(f)
        physics = doc["models"]["vestas-v150-4.2"]["physics"]
        required = ["v_cutin_mps", "v_rated_mps", "v_cutout_mps",
                    "hub_height_m", "rated_mw_per_unit"]
        for field in required:
            assert field in physics, f"vestas-v150-4.2 missing physics.{field}"

    def test_solar_model_required_physics_fields(self):
        """trina-vertex-n-670w must have all required pv_panel physics fields."""
        with open(_DEVICE_MODELS_PATH) as f:
            doc = yaml.safe_load(f)
        physics = doc["models"]["trina-vertex-n-670w"]["physics"]
        required = ["k_T_per_c", "eta_inverter", "degradation_yr1"]
        for field in required:
            assert field in physics, f"trina-vertex-n-670w missing physics.{field}"

    def test_battery_model_required_physics_fields(self):
        """catl-lmp-300mwh must have all required battery physics fields."""
        with open(_DEVICE_MODELS_PATH) as f:
            doc = yaml.safe_load(f)
        physics = doc["models"]["catl-lmp-300mwh"]["physics"]
        required = ["eta_ch", "eta_dis", "soc_min", "soc_max",
                    "capacity_mwh_per_unit", "power_mw_per_unit"]
        for field in required:
            assert field in physics, f"catl-lmp-300mwh missing physics.{field}"

    def test_grid_model_required_physics_fields(self):
        """pcc-substation-945mw must have all required grid_connection physics fields."""
        with open(_DEVICE_MODELS_PATH) as f:
            doc = yaml.safe_load(f)
        physics = doc["models"]["pcc-substation-945mw"]["physics"]
        required = ["max_export_mw", "max_import_mw"]
        for field in required:
            assert field in physics, f"pcc-substation-945mw missing physics.{field}"

    def test_gansu_wind_physics_values(self):
        """vestas-v150-4.2 physics constants match §3.1 spec values."""
        with open(_DEVICE_MODELS_PATH) as f:
            doc = yaml.safe_load(f)
        p = doc["models"]["vestas-v150-4.2"]["physics"]
        # §3.1 exact values
        assert p["v_cutin_mps"] == pytest.approx(3.0)
        assert p["v_rated_mps"] == pytest.approx(12.0)
        assert p["v_cutout_mps"] == pytest.approx(25.0)
        assert p["hub_height_m"] == pytest.approx(105.0)
        assert p["rated_mw_per_unit"] == pytest.approx(4.2)

    def test_gansu_battery_physics_values(self):
        """catl-lmp-300mwh physics constants match §3.3/D4 values."""
        with open(_DEVICE_MODELS_PATH) as f:
            doc = yaml.safe_load(f)
        p = doc["models"]["catl-lmp-300mwh"]["physics"]
        # η = 0.97 per spec; D4 SOC bounds
        assert p["eta_ch"]  == pytest.approx(0.97)
        assert p["eta_dis"] == pytest.approx(0.97)
        assert p["soc_min"] == pytest.approx(0.2)
        assert p["soc_max"] == pytest.approx(0.9)

    def test_site_gansu_has_assets_section(self):
        """config/site_gansu.yaml must contain the 'assets' section after B."""
        assert _SITE_GANSU_PATH.exists(), f"site_gansu.yaml not found at {_SITE_GANSU_PATH}"
        with open(_SITE_GANSU_PATH) as f:
            site = yaml.safe_load(f)
        assert "assets" in site, "site_gansu.yaml missing 'assets' section"
        for key in ("wind", "solar", "battery", "grid"):
            assert key in site["assets"], f"assets.{key} missing from site_gansu.yaml"

    def test_site_gansu_tariff_length(self):
        """config/site_gansu.yaml tariff.price_table_yuan_per_mwh must have 24 entries."""
        with open(_SITE_GANSU_PATH) as f:
            site = yaml.safe_load(f)
        table = site["tariff"]["price_table_yuan_per_mwh"]
        assert len(table) == 24, (
            f"price_table must have 24 entries; got {len(table)}"
        )


# ===========================================================================
# 2. TestGansuParity — resolve_gansu() == EnvParams() bit-exact (THE GATE)
# ===========================================================================

class TestGansuParity:
    """
    FIRST ACCEPTANCE GATE (contract §5, plan §2 Workstream B).

    resolve_gansu()[0] must equal EnvParams() bit-exactly for all scalar fields
    AND the (24,) price_table array.  If this fails, B is not complete.
    """

    @pytest.fixture(scope="class")
    def resolved(self):
        params, obs_dim, action_dim = resolve_gansu(_DEVICE_MODELS_PATH)
        return params, obs_dim, action_dim

    def test_obs_dim(self, resolved):
        """resolve_gansu returns obs_dim=107 (§2.1 LOCKED: 11 + 24×4)."""
        _, obs_dim, _ = resolved
        # 11 base features + 24 horizons × 4 features = 107
        assert obs_dim == 107, f"Expected obs_dim=107; got {obs_dim}"

    def test_action_dim(self, resolved):
        """resolve_gansu returns action_dim=6 (§2.2 LOCKED: a_bat + 5 fractions)."""
        _, _, action_dim = resolved
        assert action_dim == 6, f"Expected action_dim=6; got {action_dim}"

    # --- Wind scalars ---

    def test_wind_rated_mw(self, resolved):
        """wind_rated_mw = 615.0 MW (fleet total per site config)."""
        params, _, _ = resolved
        # 146 turbines × 4.2 MW ≈ 613.2; spec rounds to 615 (site override)
        assert params.wind_rated_mw == pytest.approx(_EXPECTED_WIND_RATED_MW)
        assert params.wind_rated_mw == EnvParams().wind_rated_mw

    def test_wind_v_cutin(self, resolved):
        """wind_v_cutin = 3.0 m/s (vestas-v150-4.2 non-overridable physics)."""
        params, _, _ = resolved
        assert params.wind_v_cutin == pytest.approx(_EXPECTED_WIND_V_CUTIN)
        assert params.wind_v_cutin == EnvParams().wind_v_cutin

    def test_wind_v_rated(self, resolved):
        """wind_v_rated = 12.0 m/s (vestas-v150-4.2 non-overridable physics)."""
        params, _, _ = resolved
        assert params.wind_v_rated == pytest.approx(_EXPECTED_WIND_V_RATED)
        assert params.wind_v_rated == EnvParams().wind_v_rated

    def test_wind_v_cutout(self, resolved):
        """wind_v_cutout = 25.0 m/s (vestas-v150-4.2 non-overridable physics)."""
        params, _, _ = resolved
        assert params.wind_v_cutout == pytest.approx(_EXPECTED_WIND_V_CUTOUT)
        assert params.wind_v_cutout == EnvParams().wind_v_cutout

    def test_wind_hub_height(self, resolved):
        """wind_hub_height_m = 105.0 m (vestas-v150-4.2 model default; no site override)."""
        params, _, _ = resolved
        assert params.wind_hub_height_m == pytest.approx(_EXPECTED_HUB_HEIGHT_M)
        assert params.wind_hub_height_m == EnvParams().wind_hub_height_m

    # --- Solar scalars ---

    def test_pv_capacity_mw(self, resolved):
        """pv_capacity_mw = 330.0 MW (fleet total from site config)."""
        params, _, _ = resolved
        assert params.pv_capacity_mw == pytest.approx(_EXPECTED_PV_CAPACITY_MW)
        assert params.pv_capacity_mw == EnvParams().pv_capacity_mw

    def test_pv_k_T(self, resolved):
        """pv_k_T = -0.003 /°C (trina non-overridable physics)."""
        params, _, _ = resolved
        assert params.pv_k_T == pytest.approx(_EXPECTED_PV_K_T)
        assert params.pv_k_T == EnvParams().pv_k_T

    def test_pv_eta_inv(self, resolved):
        """pv_eta_inv = 0.97 (trina non-overridable physics)."""
        params, _, _ = resolved
        assert params.pv_eta_inv == pytest.approx(_EXPECTED_PV_ETA_INV)
        assert params.pv_eta_inv == EnvParams().pv_eta_inv

    def test_pv_degradation(self, resolved):
        """pv_degradation = 0.98 (trina model default; no site override)."""
        params, _, _ = resolved
        assert params.pv_degradation == pytest.approx(_EXPECTED_PV_DEGRADATION)
        assert params.pv_degradation == EnvParams().pv_degradation

    # --- Battery scalars ---

    def test_bat_capacity_mwh(self, resolved):
        """bat_capacity_mwh = 294.5 MWh (site override; 294.5 < 300 nominal)."""
        params, _, _ = resolved
        assert params.bat_capacity_mwh == pytest.approx(_EXPECTED_BAT_CAPACITY_MWH)
        assert params.bat_capacity_mwh == EnvParams().bat_capacity_mwh

    def test_bat_power_mw(self, resolved):
        """bat_power_mw = 98.16 MW (site override; 98.16 < 100 nominal)."""
        params, _, _ = resolved
        assert params.bat_power_mw == pytest.approx(_EXPECTED_BAT_POWER_MW)
        assert params.bat_power_mw == EnvParams().bat_power_mw

    def test_bat_eta_ch(self, resolved):
        """bat_eta_ch = 0.97 (catl non-overridable physics; §3.3)."""
        params, _, _ = resolved
        assert params.bat_eta_ch == pytest.approx(_EXPECTED_BAT_ETA_CH)
        assert params.bat_eta_ch == EnvParams().bat_eta_ch

    def test_bat_eta_dis(self, resolved):
        """bat_eta_dis = 0.97 (catl non-overridable physics; §3.3)."""
        params, _, _ = resolved
        assert params.bat_eta_dis == pytest.approx(_EXPECTED_BAT_ETA_DIS)
        assert params.bat_eta_dis == EnvParams().bat_eta_dis

    def test_soc_min(self, resolved):
        """soc_min = 0.2 (catl non-overridable physics; D4)."""
        params, _, _ = resolved
        assert params.soc_min == pytest.approx(_EXPECTED_SOC_MIN)
        assert params.soc_min == EnvParams().soc_min

    def test_soc_max(self, resolved):
        """soc_max = 0.9 (catl non-overridable physics; D4)."""
        params, _, _ = resolved
        assert params.soc_max == pytest.approx(_EXPECTED_SOC_MAX)
        assert params.soc_max == EnvParams().soc_max

    def test_soc_init(self, resolved):
        """soc_init = 0.5 (EnvParams default; not in site YAML)."""
        params, _, _ = resolved
        assert params.soc_init == pytest.approx(_EXPECTED_SOC_INIT)
        assert params.soc_init == EnvParams().soc_init

    # --- Grid scalars ---

    def test_grid_max_export_mw(self, resolved):
        """grid_max_export_mw = 945.0 MW (pcc model default; D5)."""
        params, _, _ = resolved
        assert params.grid_max_export_mw == pytest.approx(_EXPECTED_GRID_MAX_EXPORT_MW)
        assert params.grid_max_export_mw == EnvParams().grid_max_export_mw

    def test_grid_max_import_mw(self, resolved):
        """grid_max_import_mw = 400.0 MW (pcc model default; D12)."""
        params, _, _ = resolved
        assert params.grid_max_import_mw == pytest.approx(_EXPECTED_GRID_MAX_IMPORT_MW)
        assert params.grid_max_import_mw == EnvParams().grid_max_import_mw

    # --- Cost scalars ---

    def test_c_deg(self, resolved):
        """c_deg_yuan_per_mwh = 10.0 ¥/MWh (§3.4)."""
        params, _, _ = resolved
        assert params.c_deg_yuan_per_mwh == pytest.approx(_EXPECTED_C_DEG)
        assert params.c_deg_yuan_per_mwh == EnvParams().c_deg_yuan_per_mwh

    def test_voll(self, resolved):
        """voll_yuan_per_mwh = 20 000 ¥/MWh (§3.4 VOLL)."""
        params, _, _ = resolved
        assert params.voll_yuan_per_mwh == pytest.approx(_EXPECTED_VOLL)
        assert params.voll_yuan_per_mwh == EnvParams().voll_yuan_per_mwh

    def test_curtail_penalty(self, resolved):
        """curtail_yuan_per_mwh = 800 ¥/MWh (§3.4)."""
        params, _, _ = resolved
        assert params.curtail_yuan_per_mwh == pytest.approx(_EXPECTED_CURTAIL)
        assert params.curtail_yuan_per_mwh == EnvParams().curtail_yuan_per_mwh

    def test_demand_rate(self, resolved):
        """demand_rate_yuan_per_mw_month = 32 000 ¥/MW·month (§3.7: 32 ¥/kW × 1000)."""
        params, _, _ = resolved
        assert params.demand_rate_yuan_per_mw_month == pytest.approx(_EXPECTED_DEMAND_RATE)
        assert params.demand_rate_yuan_per_mw_month == EnvParams().demand_rate_yuan_per_mw_month

    def test_soc_penalty(self, resolved):
        """soc_penalty_yuan_per_mwh = 20 000 ¥/MWh (§3.5; equals VOLL)."""
        params, _, _ = resolved
        assert params.soc_penalty_yuan_per_mwh == pytest.approx(_EXPECTED_SOC_PENALTY)
        assert params.soc_penalty_yuan_per_mwh == EnvParams().soc_penalty_yuan_per_mwh

    def test_reward_scale(self, resolved):
        """reward_scale = 1e-5 (§3.5)."""
        params, _, _ = resolved
        assert params.reward_scale == pytest.approx(_EXPECTED_REWARD_SCALE)
        assert params.reward_scale == EnvParams().reward_scale

    def test_price_spread(self, resolved):
        """price_spread_yuan_per_mwh = 30.0 ¥/MWh (D7)."""
        params, _, _ = resolved
        assert params.price_spread_yuan_per_mwh == pytest.approx(_EXPECTED_PRICE_SPREAD)
        assert params.price_spread_yuan_per_mwh == EnvParams().price_spread_yuan_per_mwh

    def test_price_spread_sigma(self, resolved):
        """price_spread_sigma = 10.0 ¥/MWh (D7)."""
        params, _, _ = resolved
        assert params.price_spread_sigma == pytest.approx(_EXPECTED_PRICE_SPREAD_SIGMA)
        assert params.price_spread_sigma == EnvParams().price_spread_sigma

    def test_forecast_sigma_max(self, resolved):
        """forecast_sigma_max = 0.10 (D6: 10% max noise at horizon 24)."""
        params, _, _ = resolved
        assert params.forecast_sigma_max == pytest.approx(_EXPECTED_FORECAST_SIGMA_MAX)
        assert params.forecast_sigma_max == EnvParams().forecast_sigma_max

    def test_episode_len(self, resolved):
        """episode_len = 168 steps (D3; EnvParams default; not in site YAML)."""
        params, _, _ = resolved
        assert params.episode_len == _EXPECTED_EPISODE_LEN
        assert params.episode_len == EnvParams().episode_len

    # --- Tariff array (THE NEW FIELD — the critical part of the parity gate) ---

    def test_price_table_shape(self, resolved):
        """price_table must be shape (24,) float32."""
        params, _, _ = resolved
        # After refactor, price_table is a JAX array; convert to numpy for comparison
        table = np.asarray(params.price_table)
        assert table.shape == (24,), (
            f"price_table shape must be (24,); got {table.shape}"
        )
        assert table.dtype == np.float32, (
            f"price_table dtype must be float32; got {table.dtype}"
        )

    def test_price_table_values(self, resolved):
        """price_table values match the Gansu TOU tariff exactly (D8).

        Hand-derived: Valley=250, Mid=450, Peak=620, Critical-peak=780 ¥/MWh.
        h=0–6 Valley, h=7 Mid, h=8–10 Peak, h=11 Crit, h=12–17 Mid,
        h=18 Peak, h=19–20 Crit, h=21–22 Peak, h=23 Valley.
        """
        params, _, _ = resolved
        table = np.asarray(params.price_table)
        np.testing.assert_array_equal(
            table, _EXPECTED_PRICE_TABLE,
            err_msg="price_table does not match Gansu TOU tariff (D8)",
        )

    def test_price_table_equals_module_constant(self, resolved):
        """resolve_gansu().price_table must equal the existing PRICE_TABLE_YPW module constant."""
        params, _, _ = resolved
        np.testing.assert_array_equal(
            np.asarray(params.price_table),
            np.asarray(PRICE_TABLE_YPW),
            err_msg=(
                "resolve_gansu().price_table != PRICE_TABLE_YPW: "
                "backward-compatibility broken"
            ),
        )

    def test_price_table_equals_envparams_default(self):
        """EnvParams().price_table must equal PRICE_TABLE_YPW (default preserved)."""
        # This test does not depend on the resolver — it checks the EnvParams refactor.
        params = EnvParams()
        assert hasattr(params, "price_table"), (
            "EnvParams must have a 'price_table' field after the §5 refactor"
        )
        np.testing.assert_array_equal(
            np.asarray(params.price_table),
            np.asarray(PRICE_TABLE_YPW),
            err_msg="EnvParams().price_table != PRICE_TABLE_YPW",
        )

    # --- Parametrized all-fields parity sweep (future-proof gate) ---

    @pytest.mark.parametrize("field", [
        f for f in EnvParams()._fields
        if f != "price_table"  # (24,) array — tested by test_price_table_* above
    ])
    def test_all_envparams_scalar_fields_parity(self, resolved, field):
        """Every scalar EnvParams field from resolve_gansu() must equal EnvParams() default.

        # reviewer: complete-by-construction parametric parity sweep (rl-architect, PR #79)
        # Auto-covers any scalar field added to EnvParams in the future.
        # price_table is excluded (array type, tested separately).
        # Arithmetic: resolved values come from site YAML float literals; they must
        # reproduce the same IEEE-754 value as the EnvParams() Python float literals.
        # pytest.approx(rel=1e-9) catches unit-conversion bugs while allowing
        # float representation noise in the YAML round-trip.
        """
        params, _, _ = resolved
        resolved_val = getattr(params, field)
        default_val = getattr(EnvParams(), field)
        assert resolved_val == pytest.approx(default_val, rel=1e-9), (
            f"EnvParams.{field}: resolve_gansu() returned {resolved_val!r}, "
            f"expected EnvParams() default {default_val!r}. "
            f"A composition bug or YAML round-trip error introduced a drift."
        )


# ===========================================================================
# 3. TestCompositionRule — non-overridable physics raises DeviceModelError
# ===========================================================================

class TestCompositionRule:
    """The resolver enforces the non-overridable / site-overridable distinction."""

    def test_override_wind_v_cutin_raises(self, tmp_path):
        """Site attempting to override v_cutin_mps raises DeviceModelError."""
        # Write a minimal device_models.yaml with vestas
        dm = {
            "schema_version": "1.0.0",
            "models": {
                "vestas-v150-4.2": {
                    "type": "wind_turbine",
                    "physics": {
                        "v_cutin_mps": 3.0, "v_rated_mps": 12.0,
                        "v_cutout_mps": 25.0, "hub_height_m": 105.0,
                        "rated_mw_per_unit": 4.2,
                    },
                    "economics": {},
                },
                "trina-vertex-n-670w": {
                    "type": "pv_panel",
                    "physics": {"k_T_per_c": -0.003, "eta_inverter": 0.97,
                                "degradation_yr1": 0.98},
                    "economics": {},
                },
                "catl-lmp-300mwh": {
                    "type": "battery",
                    "physics": {"eta_ch": 0.97, "eta_dis": 0.97, "soc_min": 0.2,
                                "soc_max": 0.9, "capacity_mwh_per_unit": 300.0,
                                "power_mw_per_unit": 100.0},
                    "economics": {},
                },
                "pcc-substation-945mw": {
                    "type": "grid_connection",
                    "physics": {"max_export_mw": 945.0, "max_import_mw": 400.0},
                    "economics": {},
                },
            },
        }
        dm_path = tmp_path / "device_models.yaml"
        with open(dm_path, "w") as f:
            yaml.dump(dm, f)

        # Site tries to override v_cutin_mps (non-overridable physics constant)
        site_bad = {
            "assets": {
                "wind": {
                    "model": "vestas-v150-4.2",
                    "fleet_rated_mw": 615.0,
                    "v_cutin_mps": 2.5,   # ← illegal override of physics constant
                },
                "solar": {"model": "trina-vertex-n-670w", "fleet_capacity_mw": 330.0},
                "battery": {"model": "catl-lmp-300mwh",
                            "fleet_capacity_mwh": 294.5, "fleet_power_mw": 98.16},
                "grid": {"model": "pcc-substation-945mw"},
            },
            "tariff": {"price_table_yuan_per_mwh": [float(x) for x in _EXPECTED_PRICE_TABLE]},
            "costs": {
                "c_deg_yuan_per_mwh": 10.0, "voll_yuan_per_mwh": 20000.0,
                "curtail_yuan_per_mwh": 800.0,
                "demand_rate_yuan_per_mw_month": 32000.0,
                "soc_penalty_yuan_per_mwh": 20000.0, "reward_scale": 1e-5,
                "price_spread_yuan_per_mwh": 30.0, "price_spread_sigma": 10.0,
            },
            "forecast": {"sigma_max": 0.10},
        }
        site_path = tmp_path / "site_bad.yaml"
        with open(site_path, "w") as f:
            yaml.dump(site_bad, f)

        with pytest.raises(DeviceModelError, match="v_cutin"):
            resolve_site(site_path, dm_path)

    def test_override_bat_eta_ch_raises(self, tmp_path):
        """Site attempting to override eta_ch raises DeviceModelError."""
        dm = {
            "schema_version": "1.0.0",
            "models": {
                "vestas-v150-4.2": {
                    "type": "wind_turbine",
                    "physics": {"v_cutin_mps": 3.0, "v_rated_mps": 12.0,
                                "v_cutout_mps": 25.0, "hub_height_m": 105.0,
                                "rated_mw_per_unit": 4.2},
                    "economics": {},
                },
                "trina-vertex-n-670w": {
                    "type": "pv_panel",
                    "physics": {"k_T_per_c": -0.003, "eta_inverter": 0.97,
                                "degradation_yr1": 0.98},
                    "economics": {},
                },
                "catl-lmp-300mwh": {
                    "type": "battery",
                    "physics": {"eta_ch": 0.97, "eta_dis": 0.97, "soc_min": 0.2,
                                "soc_max": 0.9, "capacity_mwh_per_unit": 300.0,
                                "power_mw_per_unit": 100.0},
                    "economics": {},
                },
                "pcc-substation-945mw": {
                    "type": "grid_connection",
                    "physics": {"max_export_mw": 945.0, "max_import_mw": 400.0},
                    "economics": {},
                },
            },
        }
        dm_path = tmp_path / "device_models.yaml"
        with open(dm_path, "w") as f:
            yaml.dump(dm, f)

        site_bad = {
            "assets": {
                "wind": {"model": "vestas-v150-4.2", "fleet_rated_mw": 615.0},
                "solar": {"model": "trina-vertex-n-670w", "fleet_capacity_mw": 330.0},
                "battery": {
                    "model": "catl-lmp-300mwh",
                    "fleet_capacity_mwh": 294.5, "fleet_power_mw": 98.16,
                    "eta_ch": 0.95,   # ← illegal override
                },
                "grid": {"model": "pcc-substation-945mw"},
            },
            "tariff": {"price_table_yuan_per_mwh": [float(x) for x in _EXPECTED_PRICE_TABLE]},
            "costs": {
                "c_deg_yuan_per_mwh": 10.0, "voll_yuan_per_mwh": 20000.0,
                "curtail_yuan_per_mwh": 800.0,
                "demand_rate_yuan_per_mw_month": 32000.0,
                "soc_penalty_yuan_per_mwh": 20000.0, "reward_scale": 1e-5,
                "price_spread_yuan_per_mwh": 30.0, "price_spread_sigma": 10.0,
            },
            "forecast": {"sigma_max": 0.10},
        }
        site_path = tmp_path / "site_bad.yaml"
        with open(site_path, "w") as f:
            yaml.dump(site_bad, f)

        with pytest.raises(DeviceModelError, match="eta_ch"):
            resolve_site(site_path, dm_path)

    def test_hub_height_override_accepted(self, tmp_path):
        """Site-level hub_height_m override is accepted (site-overridable field)."""
        dm = {
            "schema_version": "1.0.0",
            "models": {
                "vestas-v150-4.2": {
                    "type": "wind_turbine",
                    "physics": {"v_cutin_mps": 3.0, "v_rated_mps": 12.0,
                                "v_cutout_mps": 25.0, "hub_height_m": 105.0,
                                "rated_mw_per_unit": 4.2},
                    "economics": {},
                },
                "trina-vertex-n-670w": {
                    "type": "pv_panel",
                    "physics": {"k_T_per_c": -0.003, "eta_inverter": 0.97,
                                "degradation_yr1": 0.98},
                    "economics": {},
                },
                "catl-lmp-300mwh": {
                    "type": "battery",
                    "physics": {"eta_ch": 0.97, "eta_dis": 0.97, "soc_min": 0.2,
                                "soc_max": 0.9, "capacity_mwh_per_unit": 300.0,
                                "power_mw_per_unit": 100.0},
                    "economics": {},
                },
                "pcc-substation-945mw": {
                    "type": "grid_connection",
                    "physics": {"max_export_mw": 945.0, "max_import_mw": 400.0},
                    "economics": {},
                },
            },
        }
        dm_path = tmp_path / "device_models.yaml"
        with open(dm_path, "w") as f:
            yaml.dump(dm, f)

        site_ok = {
            "assets": {
                "wind": {
                    "model": "vestas-v150-4.2",
                    "fleet_rated_mw": 615.0,
                    "hub_height_m": 120.0,   # ← valid site override
                },
                "solar": {"model": "trina-vertex-n-670w", "fleet_capacity_mw": 330.0},
                "battery": {"model": "catl-lmp-300mwh",
                            "fleet_capacity_mwh": 294.5, "fleet_power_mw": 98.16},
                "grid": {"model": "pcc-substation-945mw"},
            },
            "tariff": {"price_table_yuan_per_mwh": [float(x) for x in _EXPECTED_PRICE_TABLE]},
            "costs": {
                "c_deg_yuan_per_mwh": 10.0, "voll_yuan_per_mwh": 20000.0,
                "curtail_yuan_per_mwh": 800.0,
                "demand_rate_yuan_per_mw_month": 32000.0,
                "soc_penalty_yuan_per_mwh": 20000.0, "reward_scale": 1e-5,
                "price_spread_yuan_per_mwh": 30.0, "price_spread_sigma": 10.0,
            },
            "forecast": {"sigma_max": 0.10},
        }
        site_path = tmp_path / "site_ok.yaml"
        with open(site_path, "w") as f:
            yaml.dump(site_ok, f)

        # Must not raise; hub_height override must be applied
        params, _, _ = resolve_site(site_path, dm_path)
        assert params.wind_hub_height_m == pytest.approx(120.0), (
            "hub_height_m site override (120.0) must take precedence over model default (105.0)"
        )

    # ---------------------------------------------------------------------------
    # Parametrized rejection of ALL non-overridable physics fields
    # ---------------------------------------------------------------------------

    def _make_minimal_dm(self, tmp_path):
        """Helper: write a minimal device_models.yaml with Gansu models."""
        dm = {
            "schema_version": "1.0.0",
            "models": {
                "vestas-v150-4.2": {
                    "type": "wind_turbine",
                    "physics": {
                        "v_cutin_mps": 3.0, "v_rated_mps": 12.0,
                        "v_cutout_mps": 25.0, "hub_height_m": 105.0,
                        "rated_mw_per_unit": 4.2,
                    },
                    "economics": {},
                },
                "trina-vertex-n-670w": {
                    "type": "pv_panel",
                    "physics": {"k_T_per_c": -0.003, "eta_inverter": 0.97,
                                "degradation_yr1": 0.98},
                    "economics": {},
                },
                "catl-lmp-300mwh": {
                    "type": "battery",
                    "physics": {"eta_ch": 0.97, "eta_dis": 0.97, "soc_min": 0.2,
                                "soc_max": 0.9, "capacity_mwh_per_unit": 300.0,
                                "power_mw_per_unit": 100.0},
                    "economics": {},
                },
                "pcc-substation-945mw": {
                    "type": "grid_connection",
                    "physics": {"max_export_mw": 945.0, "max_import_mw": 400.0},
                    "economics": {},
                },
            },
        }
        dm_path = tmp_path / "device_models.yaml"
        with open(dm_path, "w") as f:
            yaml.dump(dm, f)
        return dm_path

    def _make_site_with_override(self, tmp_path, device, field, value):
        """Helper: write a site YAML that illegally overrides one physics constant."""
        # Base valid site
        assets = {
            "wind":    {"model": "vestas-v150-4.2",    "fleet_rated_mw": 615.0},
            "solar":   {"model": "trina-vertex-n-670w", "fleet_capacity_mw": 330.0},
            "battery": {"model": "catl-lmp-300mwh",
                        "fleet_capacity_mwh": 294.5, "fleet_power_mw": 98.16},
            "grid":    {"model": "pcc-substation-945mw"},
        }
        # Inject the illegal override into the correct device section
        assets[device][field] = value
        site = {
            "assets": assets,
            "tariff": {"price_table_yuan_per_mwh": [float(x) for x in _EXPECTED_PRICE_TABLE]},
            "costs": {
                "c_deg_yuan_per_mwh": 10.0, "voll_yuan_per_mwh": 20000.0,
                "curtail_yuan_per_mwh": 800.0,
                "demand_rate_yuan_per_mw_month": 32000.0,
                "soc_penalty_yuan_per_mwh": 20000.0, "reward_scale": 1e-5,
                "price_spread_yuan_per_mwh": 30.0, "price_spread_sigma": 10.0,
            },
            "forecast": {"sigma_max": 0.10},
        }
        site_path = tmp_path / "site_bad.yaml"
        with open(site_path, "w") as f:
            yaml.dump(site, f)
        return site_path

    @pytest.mark.parametrize("device,field,value", [
        # wind_turbine non-overridable (§3.1)
        ("wind",    "v_cutin_mps",  2.5),    # cut-in; illegal override (3.0 in model)
        ("wind",    "v_rated_mps",  10.0),   # rated; illegal override (12.0 in model)
        ("wind",    "v_cutout_mps", 20.0),   # cut-out; illegal override (25.0 in model)
        # pv_panel non-overridable (§3.2)
        ("solar",   "k_T_per_c",   -0.004), # temperature coeff; illegal (−0.003 in model)
        ("solar",   "eta_inverter", 0.95),   # inverter eff; illegal (0.97 in model)
        # battery non-overridable (§3.3 / D4)
        ("battery", "eta_ch",  0.95),        # charge eff; illegal (0.97 in model)
        ("battery", "eta_dis", 0.95),        # discharge eff; illegal (0.97 in model)
        ("battery", "soc_min", 0.1),         # SOC floor; illegal (0.2 in model / D4)
        ("battery", "soc_max", 0.95),        # SOC ceiling; illegal (0.9 in model / D4)
    ])
    def test_override_any_nonoverridable_field_raises(self, tmp_path, device, field, value):
        """Every non-overridable physics constant must raise DeviceModelError if overridden.

        # reviewer: per-field override rejection coverage, all 9 fields (rl-architect +
        # backend-reviewer, PR #79).  An impl that forgets to guard a single field would
        # pass the old 2-field test but fail here.  Parametrized so each field is an
        # independent test case with a clear name in the failure output.
        """
        dm_path = self._make_minimal_dm(tmp_path)
        site_path = self._make_site_with_override(tmp_path, device, field, value)
        with pytest.raises(DeviceModelError, match=field):
            resolve_site(site_path, dm_path)

    def test_unknown_model_id_raises(self, tmp_path):
        """Site referencing a model_id not in device_models.yaml raises DeviceModelError."""
        dm = {
            "schema_version": "1.0.0",
            "models": {
                "vestas-v150-4.2": {
                    "type": "wind_turbine",
                    "physics": {"v_cutin_mps": 3.0, "v_rated_mps": 12.0,
                                "v_cutout_mps": 25.0, "hub_height_m": 105.0,
                                "rated_mw_per_unit": 4.2},
                    "economics": {},
                },
                "trina-vertex-n-670w": {
                    "type": "pv_panel",
                    "physics": {"k_T_per_c": -0.003, "eta_inverter": 0.97,
                                "degradation_yr1": 0.98},
                    "economics": {},
                },
                "catl-lmp-300mwh": {
                    "type": "battery",
                    "physics": {"eta_ch": 0.97, "eta_dis": 0.97, "soc_min": 0.2,
                                "soc_max": 0.9, "capacity_mwh_per_unit": 300.0,
                                "power_mw_per_unit": 100.0},
                    "economics": {},
                },
                "pcc-substation-945mw": {
                    "type": "grid_connection",
                    "physics": {"max_export_mw": 945.0, "max_import_mw": 400.0},
                    "economics": {},
                },
            },
        }
        dm_path = tmp_path / "device_models.yaml"
        with open(dm_path, "w") as f:
            yaml.dump(dm, f)

        site_bad = {
            "assets": {
                "wind": {
                    "model": "nonexistent-turbine-x99",  # ← unknown model
                    "fleet_rated_mw": 615.0,
                },
                "solar": {"model": "trina-vertex-n-670w", "fleet_capacity_mw": 330.0},
                "battery": {"model": "catl-lmp-300mwh",
                            "fleet_capacity_mwh": 294.5, "fleet_power_mw": 98.16},
                "grid": {"model": "pcc-substation-945mw"},
            },
            "tariff": {"price_table_yuan_per_mwh": [float(x) for x in _EXPECTED_PRICE_TABLE]},
            "costs": {
                "c_deg_yuan_per_mwh": 10.0, "voll_yuan_per_mwh": 20000.0,
                "curtail_yuan_per_mwh": 800.0,
                "demand_rate_yuan_per_mw_month": 32000.0,
                "soc_penalty_yuan_per_mwh": 20000.0, "reward_scale": 1e-5,
                "price_spread_yuan_per_mwh": 30.0, "price_spread_sigma": 10.0,
            },
            "forecast": {"sigma_max": 0.10},
        }
        site_path = tmp_path / "site_bad.yaml"
        with open(site_path, "w") as f:
            yaml.dump(site_bad, f)

        with pytest.raises(DeviceModelError, match="nonexistent-turbine-x99"):
            resolve_site(site_path, dm_path)


# ===========================================================================
# 4. TestTariffLength — tariff table length validation
# ===========================================================================

class TestTariffLength:
    """Resolver must reject tariff tables that are not exactly 24 entries."""

    def test_tariff_wrong_length_raises(self, tmp_path):
        """Tariff table with 23 entries (off-by-one) must raise ValueError."""
        dm = {
            "schema_version": "1.0.0",
            "models": {
                "vestas-v150-4.2": {
                    "type": "wind_turbine",
                    "physics": {"v_cutin_mps": 3.0, "v_rated_mps": 12.0,
                                "v_cutout_mps": 25.0, "hub_height_m": 105.0,
                                "rated_mw_per_unit": 4.2},
                    "economics": {},
                },
                "trina-vertex-n-670w": {
                    "type": "pv_panel",
                    "physics": {"k_T_per_c": -0.003, "eta_inverter": 0.97,
                                "degradation_yr1": 0.98},
                    "economics": {},
                },
                "catl-lmp-300mwh": {
                    "type": "battery",
                    "physics": {"eta_ch": 0.97, "eta_dis": 0.97, "soc_min": 0.2,
                                "soc_max": 0.9, "capacity_mwh_per_unit": 300.0,
                                "power_mw_per_unit": 100.0},
                    "economics": {},
                },
                "pcc-substation-945mw": {
                    "type": "grid_connection",
                    "physics": {"max_export_mw": 945.0, "max_import_mw": 400.0},
                    "economics": {},
                },
            },
        }
        dm_path = tmp_path / "device_models.yaml"
        with open(dm_path, "w") as f:
            yaml.dump(dm, f)

        site_bad = {
            "assets": {
                "wind": {"model": "vestas-v150-4.2", "fleet_rated_mw": 615.0},
                "solar": {"model": "trina-vertex-n-670w", "fleet_capacity_mw": 330.0},
                "battery": {"model": "catl-lmp-300mwh",
                            "fleet_capacity_mwh": 294.5, "fleet_power_mw": 98.16},
                "grid": {"model": "pcc-substation-945mw"},
            },
            "tariff": {
                "price_table_yuan_per_mwh": [float(x) for x in _EXPECTED_PRICE_TABLE[:23]]  # only 23 entries
            },
            "costs": {
                "c_deg_yuan_per_mwh": 10.0, "voll_yuan_per_mwh": 20000.0,
                "curtail_yuan_per_mwh": 800.0,
                "demand_rate_yuan_per_mw_month": 32000.0,
                "soc_penalty_yuan_per_mwh": 20000.0, "reward_scale": 1e-5,
                "price_spread_yuan_per_mwh": 30.0, "price_spread_sigma": 10.0,
            },
            "forecast": {"sigma_max": 0.10},
        }
        site_path = tmp_path / "site_bad.yaml"
        with open(site_path, "w") as f:
            yaml.dump(site_bad, f)

        with pytest.raises(ValueError, match="24"):
            resolve_site(site_path, dm_path)


# ===========================================================================
# 5. TestUnitCounts — resolver exposes discrete unit counts for A/E instancing
# ===========================================================================

get_unit_counts = getattr(resolver, "get_unit_counts", None)

class TestUnitCounts:
    """get_unit_counts() exposes the canonical rounding rule (§4.1).

    # reviewer: unit-count resolver output (rl-architect + frontend-reviewer, PR #79)
    # Ensures A/E consumers (3D instanced fleet, composition panel) never re-implement
    # the rounding in TS.  Arithmetic shown for Gansu values.
    """

    def test_get_unit_counts_exists(self):
        """resolver module must export get_unit_counts."""
        assert get_unit_counts is not None, (
            "energy_go.env.resolver must export get_unit_counts (§4.1)"
        )

    def test_gansu_wind_unit_count(self):
        """Gansu wind: round(615.0 / 4.2) = 146 turbines.

        Hand-derived: 615.0 / 4.2 = 146.428... → round() = 146.
        (Not floor: 146 × 4.2 = 613.2 MW; spec rounds up to 615 fleet MW override.)
        """
        counts = get_unit_counts(_SITE_GANSU_PATH, _DEVICE_MODELS_PATH)
        # 615.0 / 4.2 = 146.428... → round(146.428) = 146
        assert counts["wind"] == 146, (
            f"Expected 146 wind turbines; got {counts['wind']}. "
            f"Derived: round(615.0 / 4.2) = round(146.43) = 146"
        )

    def test_gansu_battery_unit_count(self):
        """Gansu battery: round(294.5 / 300.0) = 1 unit.

        Hand-derived: 294.5 / 300.0 = 0.9817 → round() = 1.
        (Single 300 MWh unit deployed at 294.5 MWh actual capacity.)
        """
        counts = get_unit_counts(_SITE_GANSU_PATH, _DEVICE_MODELS_PATH)
        # 294.5 / 300.0 = 0.9817 → round(0.9817) = 1
        assert counts["battery"] == 1, (
            f"Expected 1 battery unit; got {counts['battery']}. "
            f"Derived: round(294.5 / 300.0) = round(0.982) = 1"
        )

    def test_explicit_unit_count_takes_precedence(self, tmp_path):
        """site YAML unit_count field overrides the derived rounding formula.

        # reviewer: explicit-override beats formula (§4.1 contract).
        # Arithmetic: site sets unit_count=150 explicitly; derived would be
        # round(615.0/4.2)=146. Explicit must win.
        """
        dm = {
            "schema_version": "1.0.0",
            "models": {
                "vestas-v150-4.2": {
                    "type": "wind_turbine",
                    "physics": {"v_cutin_mps": 3.0, "v_rated_mps": 12.0,
                                "v_cutout_mps": 25.0, "hub_height_m": 105.0,
                                "rated_mw_per_unit": 4.2},
                    "economics": {},
                },
                "trina-vertex-n-670w": {
                    "type": "pv_panel",
                    "physics": {"k_T_per_c": -0.003, "eta_inverter": 0.97,
                                "degradation_yr1": 0.98},
                    "economics": {},
                },
                "catl-lmp-300mwh": {
                    "type": "battery",
                    "physics": {"eta_ch": 0.97, "eta_dis": 0.97, "soc_min": 0.2,
                                "soc_max": 0.9, "capacity_mwh_per_unit": 300.0,
                                "power_mw_per_unit": 100.0},
                    "economics": {},
                },
                "pcc-substation-945mw": {
                    "type": "grid_connection",
                    "physics": {"max_export_mw": 945.0, "max_import_mw": 400.0},
                    "economics": {},
                },
            },
        }
        dm_path = tmp_path / "device_models.yaml"
        with open(dm_path, "w") as f:
            yaml.dump(dm, f)

        site_explicit = {
            "assets": {
                "wind": {
                    "model": "vestas-v150-4.2",
                    "fleet_rated_mw": 615.0,
                    "unit_count": 150,      # explicit — overrides round(615/4.2)=146
                },
                "solar": {"model": "trina-vertex-n-670w", "fleet_capacity_mw": 330.0},
                "battery": {"model": "catl-lmp-300mwh",
                            "fleet_capacity_mwh": 294.5, "fleet_power_mw": 98.16},
                "grid": {"model": "pcc-substation-945mw"},
            },
            "tariff": {"price_table_yuan_per_mwh": [float(x) for x in _EXPECTED_PRICE_TABLE]},
            "costs": {
                "c_deg_yuan_per_mwh": 10.0, "voll_yuan_per_mwh": 20000.0,
                "curtail_yuan_per_mwh": 800.0,
                "demand_rate_yuan_per_mw_month": 32000.0,
                "soc_penalty_yuan_per_mwh": 20000.0, "reward_scale": 1e-5,
                "price_spread_yuan_per_mwh": 30.0, "price_spread_sigma": 10.0,
            },
            "forecast": {"sigma_max": 0.10},
        }
        site_path = tmp_path / "site_explicit.yaml"
        with open(site_path, "w") as f:
            yaml.dump(site_explicit, f)

        counts = get_unit_counts(site_path, dm_path)
        assert counts["wind"] == 150, (
            f"Explicit unit_count=150 must override derived 146; got {counts['wind']}"
        )


# ===========================================================================
# v1.1.0 tests — economics field catalogue (task #57, contract §1.3–§1.4)
# ===========================================================================
# All tests below are RED at contract time (device_models.yaml still has
# economics: {} stubs).  They turn GREEN after the v1.1.0 YAML implementation.
#
# These tests do NOT import JAX / the resolver — they operate purely on
# YAML content.  That means they run even if jaxlib is unavailable.
# ===========================================================================

_DM_PATH = _REPO_ROOT / "config" / "device_models.yaml"


def _load_dm() -> dict:
    """Load device_models.yaml and return the full parsed dict."""
    with open(_DM_PATH) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# §11 version string
# ---------------------------------------------------------------------------

class TestV110VersionString:
    """schema_version bumps to 1.1.0 when economics fields land."""

    def test_schema_version_is_1_1_0(self):
        dm = _load_dm()
        assert dm["schema_version"] == "1.1.0", (
            f"expected schema_version '1.1.0', got {dm['schema_version']!r}"
        )


# ---------------------------------------------------------------------------
# §1.3 economics field presence — all 4 Gansu device models
# ---------------------------------------------------------------------------

class TestEconomicsFieldPresence:
    """All required economics fields are present for each Gansu device model."""

    # Fields required by wind_turbine economics section
    _WIND_FIELDS = {
        "capex_per_kw_yuan",
        "opex_fixed_per_kw_year_yuan",
        "opex_var_per_mwh_yuan",
        "lifetime_years",
        "replacement_cost_fraction",
        "residual_value_fraction",
        "construction_months",
        "decommissioning_cost_per_kw_yuan",
    }

    # Fields required by pv_panel economics section (same structure as wind)
    _PV_FIELDS = {
        "capex_per_kw_yuan",
        "opex_fixed_per_kw_year_yuan",
        "opex_var_per_mwh_yuan",
        "lifetime_years",
        "replacement_cost_fraction",
        "residual_value_fraction",
        "construction_months",
        "decommissioning_cost_per_kw_yuan",
    }

    # Fields required by battery economics section
    _BAT_FIELDS = {
        "capex_energy_per_kwh_yuan",
        "capex_power_per_kw_yuan",
        "opex_fixed_per_kwh_year_yuan",
        "opex_var_per_mwh_yuan",
        "lifetime_years",
        "cycle_life_full_equiv",
        "eol_soh_threshold",
        "replacement_cost_fraction",
        "residual_value_fraction",
        "construction_months",
        "decommissioning_cost_per_kwh_yuan",
    }

    # Fields required by grid_connection economics section
    _GRID_FIELDS = {
        "capex_lump_sum_yuan",
        "opex_fixed_per_mw_year_yuan",
        "lifetime_years",
        "residual_value_fraction",
        "decommissioning_cost_yuan",
    }

    def _econ(self, model_id: str) -> dict:
        dm = _load_dm()
        econ = dm["models"][model_id]["economics"]
        assert isinstance(econ, dict), f"{model_id} economics must be a dict, not empty or null"
        return econ

    def test_wind_economics_has_all_fields(self):
        econ = self._econ("vestas-v150-4.2")
        missing = self._WIND_FIELDS - set(econ)
        assert not missing, f"vestas-v150-4.2 economics missing: {missing}"

    def test_pv_economics_has_all_fields(self):
        econ = self._econ("trina-vertex-n-670w")
        missing = self._PV_FIELDS - set(econ)
        assert not missing, f"trina-vertex-n-670w economics missing: {missing}"

    def test_battery_economics_has_all_fields(self):
        econ = self._econ("catl-lmp-300mwh")
        missing = self._BAT_FIELDS - set(econ)
        assert not missing, f"catl-lmp-300mwh economics missing: {missing}"

    def test_grid_economics_has_all_fields(self):
        econ = self._econ("pcc-substation-945mw")
        missing = self._GRID_FIELDS - set(econ)
        assert not missing, f"pcc-substation-945mw economics missing: {missing}"


# ---------------------------------------------------------------------------
# §1.3 value types — all economics values must be float (not empty/null/string)
# ---------------------------------------------------------------------------

class TestEconomicsFieldTypes:
    """Every economics value is a float (or int coercible to float, > 0 where noted)."""

    def _check_float_fields(self, model_id: str, fields: list[str]) -> None:
        dm = _load_dm()
        econ = dm["models"][model_id]["economics"]
        for field in fields:
            val = econ[field]
            assert isinstance(val, (int, float)), (
                f"{model_id}.economics.{field} = {val!r} is not numeric"
            )
            assert val >= 0, (
                f"{model_id}.economics.{field} = {val} must be ≥ 0"
            )

    def test_wind_economics_types(self):
        self._check_float_fields("vestas-v150-4.2", [
            "capex_per_kw_yuan", "opex_fixed_per_kw_year_yuan", "opex_var_per_mwh_yuan",
            "lifetime_years", "replacement_cost_fraction", "residual_value_fraction",
            "construction_months", "decommissioning_cost_per_kw_yuan",
        ])

    def test_pv_economics_types(self):
        self._check_float_fields("trina-vertex-n-670w", [
            "capex_per_kw_yuan", "opex_fixed_per_kw_year_yuan", "opex_var_per_mwh_yuan",
            "lifetime_years", "replacement_cost_fraction", "residual_value_fraction",
            "construction_months", "decommissioning_cost_per_kw_yuan",
        ])

    def test_battery_economics_types(self):
        self._check_float_fields("catl-lmp-300mwh", [
            "capex_energy_per_kwh_yuan", "capex_power_per_kw_yuan",
            "opex_fixed_per_kwh_year_yuan", "opex_var_per_mwh_yuan",
            "lifetime_years", "cycle_life_full_equiv",
            "replacement_cost_fraction", "residual_value_fraction",
            "construction_months",
        ])

    def test_grid_economics_types(self):
        self._check_float_fields("pcc-substation-945mw", [
            "capex_lump_sum_yuan", "opex_fixed_per_mw_year_yuan",
            "lifetime_years", "residual_value_fraction", "decommissioning_cost_yuan",
        ])


# ---------------------------------------------------------------------------
# §1.3 value ranges — fractions, cycle life, lifetime plausibility
# ---------------------------------------------------------------------------

class TestEconomicsValueRanges:
    """Key economics fields satisfy physical constraints."""

    def _econ(self, mid: str) -> dict:
        return _load_dm()["models"][mid]["economics"]

    def test_wind_lifetime_years_positive_and_realistic(self):
        # Minimum 10yr, max 40yr for wind turbines
        val = self._econ("vestas-v150-4.2")["lifetime_years"]
        assert 10.0 <= val <= 40.0, (
            f"wind lifetime_years={val} outside [10, 40] — check contract §1.4"
        )

    def test_pv_lifetime_years_positive_and_realistic(self):
        val = self._econ("trina-vertex-n-670w")["lifetime_years"]
        assert 10.0 <= val <= 40.0, (
            f"pv lifetime_years={val} outside [10, 40]"
        )

    def test_battery_lifetime_years_positive_and_realistic(self):
        # LFP calendar life: 8–20yr
        val = self._econ("catl-lmp-300mwh")["lifetime_years"]
        assert 5.0 <= val <= 25.0, (
            f"battery lifetime_years={val} outside [5, 25]"
        )

    def test_battery_cycle_life_positive_and_realistic(self):
        # LFP: 4000–10000 full-depth cycles
        val = self._econ("catl-lmp-300mwh")["cycle_life_full_equiv"]
        assert 1000.0 <= val <= 15000.0, (
            f"cycle_life_full_equiv={val} outside [1000, 15000]"
        )

    def test_battery_eol_soh_threshold_is_fraction(self):
        # EOL SOH typically 0.7–0.9 for LFP
        val = self._econ("catl-lmp-300mwh")["eol_soh_threshold"]
        assert 0.5 < val < 1.0, (
            f"eol_soh_threshold={val} must be ∈ (0.5, 1.0)"
        )

    def test_all_replacement_cost_fractions_in_range(self):
        """replacement_cost_fraction ∈ (0, 1] for all models that have it."""
        dm = _load_dm()
        for mid, entry in dm["models"].items():
            econ = entry.get("economics", {})
            if not isinstance(econ, dict):
                continue
            if "replacement_cost_fraction" in econ:
                val = econ["replacement_cost_fraction"]
                assert 0.0 < val <= 1.0, (
                    f"{mid}.economics.replacement_cost_fraction={val} must be ∈ (0, 1]"
                )

    def test_all_residual_value_fractions_in_range(self):
        """residual_value_fraction ∈ [0, 1) for all models."""
        dm = _load_dm()
        for mid, entry in dm["models"].items():
            econ = entry.get("economics", {})
            if not isinstance(econ, dict):
                continue
            if "residual_value_fraction" in econ:
                val = econ["residual_value_fraction"]
                assert 0.0 <= val < 1.0, (
                    f"{mid}.economics.residual_value_fraction={val} must be ∈ [0, 1)"
                )

    def test_battery_capex_energy_nonzero(self):
        # Battery CAPEX energy must be > 0 (it's the primary cost driver)
        val = self._econ("catl-lmp-300mwh")["capex_energy_per_kwh_yuan"]
        assert val > 0.0, (
            f"catl-lmp-300mwh capex_energy_per_kwh_yuan={val} must be > 0"
        )

    def test_wind_capex_nonzero(self):
        # Wind CAPEX must be > 0
        val = self._econ("vestas-v150-4.2")["capex_per_kw_yuan"]
        assert val > 0.0, (
            f"vestas-v150-4.2 capex_per_kw_yuan={val} must be > 0"
        )

    def test_pv_capex_nonzero(self):
        # PV CAPEX must be > 0
        val = self._econ("trina-vertex-n-670w")["capex_per_kw_yuan"]
        assert val > 0.0, (
            f"trina-vertex-n-670w capex_per_kw_yuan={val} must be > 0"
        )

    def test_grid_lifetime_years_positive_and_realistic(self):
        val = self._econ("pcc-substation-945mw")["lifetime_years"]
        assert 20.0 <= val <= 60.0, (
            f"grid lifetime_years={val} outside [20, 60]"
        )


# ---------------------------------------------------------------------------
# §1.3 resolver ignorance — economics fields must NOT affect resolve_gansu()
# ---------------------------------------------------------------------------

class TestResolverIgnoresEconomics:
    """The resolver returns identical EnvParams regardless of economics content.

    This test requires the resolver (skipped at contract time).
    Once resolver is available AND device_models.yaml is at v1.1.0, both
    resolve_gansu() calls must produce bit-identical EnvParams.
    """

    def test_resolver_unaffected_by_economics_fields(self, tmp_path):
        """Stripping economics: {} vs populated economics: {…} → same EnvParams.

        Hand-computed: resolve_gansu() should equal EnvParams() regardless of
        the economics block content.  The resolver is spec'd to ignore economics:.
        """
        # --- Load the v1.1.0 YAML (populated economics) ---
        with open(_DM_PATH) as f:
            dm_populated = yaml.safe_load(f)

        # --- Create a stripped copy with economics: {} for all models ---
        import copy
        dm_stripped = copy.deepcopy(dm_populated)
        for entry in dm_stripped["models"].values():
            entry["economics"] = {}

        stripped_path = tmp_path / "device_models_stripped.yaml"
        with open(stripped_path, "w") as f:
            yaml.dump(dm_stripped, f)

        # Both resolve_gansu() calls must return bit-identical EnvParams
        # (env parity gate: resolver IGNORES economics block)
        params_populated, obs_dim, action_dim = resolve_gansu(str(_DM_PATH))
        params_stripped, obs_dim2, action_dim2 = resolve_gansu(stripped_path)

        assert obs_dim == obs_dim2 == 107
        assert action_dim == action_dim2 == 6

        # Compare all scalar fields
        for field in EnvParams._fields:
            v_pop = getattr(params_populated, field)
            v_str = getattr(params_stripped, field)
            import jax.numpy as jnp
            if hasattr(v_pop, "__len__"):
                # array field (price_table)
                assert jnp.allclose(jnp.array(v_pop), jnp.array(v_str), rtol=1e-9), (
                    f"EnvParams.{field} differs between populated and stripped economics"
                )
            else:
                assert v_pop == pytest.approx(v_str, rel=1e-9), (
                    f"EnvParams.{field} = {v_pop} (populated) vs {v_str} (stripped)"
                )


# ---------------------------------------------------------------------------
# §1.4 Gansu v1.1.0 specific values (hand-derived from contract §1.4 table)
# ---------------------------------------------------------------------------

class TestGansuEconomicsValues:
    """Spot-check the contracted Gansu v1.1.0 initial estimates.

    These are hand-derived from the contract §1.4 default-values table.
    If task #63 benchmark library updates these, the contract §1.4 table and
    these tests must be updated together in the same PR.
    """

    def _econ(self, mid: str) -> dict:
        return _load_dm()["models"][mid]["economics"]

    def test_vestas_capex_per_kw(self):
        # Contracted: 5800.0 ¥/kW (≈800 USD/kW, onshore wind China 2024)
        val = self._econ("vestas-v150-4.2")["capex_per_kw_yuan"]
        assert val == pytest.approx(5800.0, rel=1e-6), f"got {val}"

    def test_vestas_lifetime_years(self):
        # Contracted: 25.0 yr
        val = self._econ("vestas-v150-4.2")["lifetime_years"]
        assert val == pytest.approx(25.0, rel=1e-6), f"got {val}"

    def test_trina_capex_per_kw(self):
        # Contracted: 3200.0 ¥/kW (≈450 USD/kW, utility PV China 2024)
        val = self._econ("trina-vertex-n-670w")["capex_per_kw_yuan"]
        assert val == pytest.approx(3200.0, rel=1e-6), f"got {val}"

    def test_catl_capex_energy_per_kwh(self):
        # Contracted: 1000.0 ¥/kWh (≈140 USD/kWh, LFP grid-scale China 2024)
        val = self._econ("catl-lmp-300mwh")["capex_energy_per_kwh_yuan"]
        assert val == pytest.approx(1000.0, rel=1e-6), f"got {val}"

    def test_catl_cycle_life(self):
        # Contracted: 6000.0 full-depth equivalent cycles
        val = self._econ("catl-lmp-300mwh")["cycle_life_full_equiv"]
        assert val == pytest.approx(6000.0, rel=1e-6), f"got {val}"

    def test_catl_eol_soh_threshold(self):
        # Contracted: 0.80 (80% remaining capacity triggers replacement)
        val = self._econ("catl-lmp-300mwh")["eol_soh_threshold"]
        assert val == pytest.approx(0.80, rel=1e-6), f"got {val}"

    def test_catl_replacement_cost_fraction(self):
        # Contracted: 0.70 (70% of original CAPEX)
        val = self._econ("catl-lmp-300mwh")["replacement_cost_fraction"]
        assert val == pytest.approx(0.70, rel=1e-6), f"got {val}"

    def test_catl_lifetime_years(self):
        # Contracted: 12.0 yr (LFP calendar life at ≥80% SOH)
        val = self._econ("catl-lmp-300mwh")["lifetime_years"]
        assert val == pytest.approx(12.0, rel=1e-6), f"got {val}"

    def test_catl_capex_power_bundled(self):
        # Contracted: 0.0 ¥/kW (power CAPEX bundled into energy CAPEX for LFP)
        val = self._econ("catl-lmp-300mwh")["capex_power_per_kw_yuan"]
        assert val == pytest.approx(0.0, abs=1e-9), f"got {val}"

    def test_pcc_lifetime_years(self):
        # Contracted: 40.0 yr
        val = self._econ("pcc-substation-945mw")["lifetime_years"]
        assert val == pytest.approx(40.0, rel=1e-6), f"got {val}"
