"""energy_go.env.resolver — device-model schema resolver.

Contract: contracts/shared/device_model_schema.md
         contracts/shared/tariff_model_schema.md (§4.2 — tariff_region integration)
Spec: §2.1 (obs), §2.2 (action), §3.1–§3.4 (physics/costs), §7 (JAX purity), §8
Decisions: D2, D3, D5, D12, D19, D22c, D23

Pure Python — never called inside jit.  The returned EnvParams is passed directly
to jax.jit(step) as the `params` argument.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import jax.numpy as jnp
import yaml

from energy_go.env.jax_env import EnvParams, PRICE_TABLE_YPW  # noqa: F401

# ---------------------------------------------------------------------------
# Default paths (resolved relative to the repo root at import time)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
# resolver.py lives at src/energy_go/env/resolver.py → parents[3] = repo root
_DEFAULT_DEVICE_MODELS = _REPO_ROOT / "config" / "device_models.yaml"
_DEFAULT_TARIFF_SCHEMA = _REPO_ROOT / "config" / "tariff_model_schema.yaml"
_DEFAULT_SITE_GANSU    = _REPO_ROOT / "config" / "site_gansu.yaml"


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class DeviceModelError(ValueError):
    """Raised when model_id is missing or a site override conflicts with a
    non-overridable physics constant (contracts/shared/device_model_schema.md §3)."""


# ---------------------------------------------------------------------------
# Non-overridable physics constants per device type (§3.1 composition rule)
# ---------------------------------------------------------------------------
_NON_OVERRIDABLE: dict[str, frozenset[str]] = {
    "wind_turbine":   frozenset({"v_cutin_mps", "v_rated_mps", "v_cutout_mps"}),
    "pv_panel":       frozenset({"k_T_per_c", "eta_inverter"}),
    "battery":        frozenset({"eta_ch", "eta_dis", "soc_min", "soc_max"}),
    "grid_connection": frozenset(),
}

# Keys in the site YAML assets section that are internal resolver state
_SITE_RESERVED_KEYS = frozenset({"model", "fleet_rated_mw", "fleet_capacity_mw",
                                   "fleet_capacity_mwh", "fleet_power_mw",
                                   "hub_height_m", "degradation_yr1",
                                   "max_export_mw", "max_import_mw",
                                   "unit_count"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Union[str, Path]) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _get_model(device_models: dict, model_id: str) -> dict:
    """Look up model by ID; raise DeviceModelError if not found."""
    models = device_models.get("models", {})
    if model_id not in models:
        raise DeviceModelError(
            f"model_id '{model_id}' not found in device_models.yaml. "
            f"Available: {sorted(models.keys())}"
        )
    return models[model_id]


def _check_no_physics_override(
    device_type: str,
    site_asset: dict,
    model_id: str,
) -> None:
    """Raise DeviceModelError if site_asset contains any non-overridable physics key."""
    forbidden = _NON_OVERRIDABLE.get(device_type, frozenset())
    for key in site_asset:
        if key in forbidden:
            raise DeviceModelError(
                f"Site config attempts to override non-overridable physics constant "
                f"'{key}' of device '{model_id}' (type: {device_type}). "
                f"Non-overridable fields for {device_type}: {sorted(forbidden)}"
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_site(
    site_config_path: Union[str, Path],
    device_models_path: Union[str, Path] = None,
) -> tuple[EnvParams, int, int]:
    """Resolve a site YAML + device model schema to (EnvParams, obs_dim, action_dim).

    Pure Python (never called inside jit).  The returned EnvParams is passed
    directly to jax.jit(step) as the `params` argument.

    Args:
        site_config_path:   path to site_<name>.yaml
        device_models_path: path to device_models.yaml (default: config/device_models.yaml)

    Returns:
        params:     Fully populated EnvParams NamedTuple including price_table
        obs_dim:    Observation dimension (107 for Gansu; site-dependent for §8)
        action_dim: Action dimension (6 for Gansu; site-dependent for §8)

    Raises:
        DeviceModelError: model_id not found, or site overrides a non-overridable constant
        ValueError:       tariff table not exactly 24 entries, required fleet param missing
    """
    if device_models_path is None:
        device_models_path = _DEFAULT_DEVICE_MODELS

    site = _load_yaml(site_config_path)
    device_models = _load_yaml(device_models_path)
    assets = site["assets"]

    # ------------------------------------------------------------------
    # Wind turbine
    # ------------------------------------------------------------------
    wind_cfg    = assets["wind"]
    wind_model  = _get_model(device_models, wind_cfg["model"])
    _check_no_physics_override(wind_model["type"], wind_cfg, wind_cfg["model"])

    wp = wind_model["physics"]
    wind_rated_mw    = float(wind_cfg["fleet_rated_mw"])
    wind_hub_height_m = float(wind_cfg.get("hub_height_m", wp["hub_height_m"]))
    wind_v_cutin     = float(wp["v_cutin_mps"])
    wind_v_rated     = float(wp["v_rated_mps"])
    wind_v_cutout    = float(wp["v_cutout_mps"])

    # ------------------------------------------------------------------
    # Solar PV
    # ------------------------------------------------------------------
    solar_cfg   = assets["solar"]
    solar_model = _get_model(device_models, solar_cfg["model"])
    _check_no_physics_override(solar_model["type"], solar_cfg, solar_cfg["model"])

    sp = solar_model["physics"]
    pv_capacity_mw = float(solar_cfg["fleet_capacity_mw"])
    pv_k_T         = float(sp["k_T_per_c"])
    pv_eta_inv     = float(sp["eta_inverter"])
    pv_degradation = float(solar_cfg.get("degradation_yr1", sp["degradation_yr1"]))

    # ------------------------------------------------------------------
    # Battery
    # ------------------------------------------------------------------
    bat_cfg   = assets["battery"]
    bat_model = _get_model(device_models, bat_cfg["model"])
    _check_no_physics_override(bat_model["type"], bat_cfg, bat_cfg["model"])

    bp = bat_model["physics"]
    bat_capacity_mwh = float(bat_cfg["fleet_capacity_mwh"])
    bat_power_mw     = float(bat_cfg["fleet_power_mw"])
    bat_eta_ch       = float(bp["eta_ch"])
    bat_eta_dis      = float(bp["eta_dis"])
    soc_min          = float(bp["soc_min"])
    soc_max          = float(bp["soc_max"])

    # ------------------------------------------------------------------
    # Grid connection
    # ------------------------------------------------------------------
    grid_cfg   = assets["grid"]
    grid_model = _get_model(device_models, grid_cfg["model"])
    _check_no_physics_override(grid_model["type"], grid_cfg, grid_cfg["model"])

    gp = grid_model["physics"]
    grid_max_export_mw = float(grid_cfg.get("max_export_mw", gp["max_export_mw"]))
    grid_max_import_mw = float(grid_cfg.get("max_import_mw", gp["max_import_mw"]))

    # ------------------------------------------------------------------
    # Tariff — §4.2 tariff_region join (tariff_model_schema.md)
    #
    # If site_config sets `tariff_region`, load the region from
    # config/tariff_model_schema.yaml and source price_table, demand_rate,
    # and spread from it (overrides the inline `tariff` / `costs` blocks).
    #
    # Absent `tariff_region` → inline fallback: read price_table from
    # site["tariff"]["price_table_yuan_per_mwh"] (backward-compatible).
    # ------------------------------------------------------------------
    tariff_region_id = site.get("tariff_region")

    if tariff_region_id:
        # Region-keyed path (§4.2)
        from energy_go.env.tariff_model_schema import load_tariff_schema
        from energy_go.env.config_validation import ConfigValidationError

        tariff_schema = load_tariff_schema(_DEFAULT_TARIFF_SCHEMA)
        if tariff_region_id not in tariff_schema["regions"]:
            from energy_go.env.config_validation import ValidationIssue as _VI
            raise ConfigValidationError(
                errors=[_VI(
                    rule_id="E-TARIFF-REGION",
                    field="tariff_region",
                    message=(
                        f"E-TARIFF-REGION: tariff_region='{tariff_region_id}' not found "
                        f"in tariff_model_schema.yaml; available: "
                        f"{sorted(tariff_schema['regions'].keys())}"
                    ),
                    constraint=f"tariff_region='{tariff_region_id}' absent from schema",
                )],
                warnings=[],
            )
        region = tariff_schema["regions"][tariff_region_id]
        price_table = jnp.array(region.price_table_yuan_per_mwh, dtype=jnp.float32)
        # demand_rate, spread: from region (override inline costs block)
        demand_rate_yuan_per_mw_month = float(region.demand_rate_yuan_per_mw_month)
        price_spread_yuan_per_mwh     = float(region.sell_clamp.spread_yuan_per_mwh)
        price_spread_sigma            = float(region.sell_clamp.spread_noise_std_yuan_per_mwh)
    else:
        # Inline fallback path (backward-compat; existing callers unaffected)
        price_table_raw = site["tariff"]["price_table_yuan_per_mwh"]
        if len(price_table_raw) != 24:
            raise ValueError(
                f"price_table_yuan_per_mwh must have exactly 24 entries; "
                f"got {len(price_table_raw)}"
            )
        # v2.0.0: build (12, 24) seasonal table; flat (24,) site YAML replicated ×12.
        _row = jnp.array(price_table_raw, dtype=jnp.float32)  # shape (24,)
        price_table = jnp.stack([_row] * 12, axis=0)           # shape (12, 24)
        # demand_rate, spread: sourced from inline costs block
        demand_rate_yuan_per_mw_month = float(site["costs"]["demand_rate_yuan_per_mw_month"])
        price_spread_yuan_per_mwh     = float(site["costs"]["price_spread_yuan_per_mwh"])
        price_spread_sigma            = float(site["costs"]["price_spread_sigma"])

    # ------------------------------------------------------------------
    # Costs (non-tariff fields — always from inline costs block)
    # ------------------------------------------------------------------
    costs = site["costs"]
    c_deg_yuan_per_mwh            = float(costs["c_deg_yuan_per_mwh"])
    voll_yuan_per_mwh             = float(costs["voll_yuan_per_mwh"])
    curtail_yuan_per_mwh          = float(costs["curtail_yuan_per_mwh"])
    soc_penalty_yuan_per_mwh      = float(costs["soc_penalty_yuan_per_mwh"])
    reward_scale                  = float(costs["reward_scale"])
    # demand_rate, price_spread, price_spread_sigma set above (tariff path)

    # ------------------------------------------------------------------
    # Forecast
    # ------------------------------------------------------------------
    forecast_sigma_max = float(site["forecast"]["sigma_max"])

    # ------------------------------------------------------------------
    # Build EnvParams (soc_init=0.5 and episode_len=168 use NamedTuple defaults)
    # ------------------------------------------------------------------
    params = EnvParams(
        wind_rated_mw               = wind_rated_mw,
        wind_v_cutin                = wind_v_cutin,
        wind_v_rated                = wind_v_rated,
        wind_v_cutout               = wind_v_cutout,
        wind_hub_height_m           = wind_hub_height_m,
        pv_capacity_mw              = pv_capacity_mw,
        pv_k_T                      = pv_k_T,
        pv_eta_inv                  = pv_eta_inv,
        pv_degradation              = pv_degradation,
        bat_capacity_mwh            = bat_capacity_mwh,
        bat_power_mw                = bat_power_mw,
        bat_eta_ch                  = bat_eta_ch,
        bat_eta_dis                 = bat_eta_dis,
        soc_min                     = soc_min,
        soc_max                     = soc_max,
        # soc_init:   EnvParams default = 0.5 (training param, not in site YAML)
        grid_max_export_mw          = grid_max_export_mw,
        grid_max_import_mw          = grid_max_import_mw,
        c_deg_yuan_per_mwh          = c_deg_yuan_per_mwh,
        voll_yuan_per_mwh           = voll_yuan_per_mwh,
        curtail_yuan_per_mwh        = curtail_yuan_per_mwh,
        demand_rate_yuan_per_mw_month = demand_rate_yuan_per_mw_month,
        soc_penalty_yuan_per_mwh    = soc_penalty_yuan_per_mwh,
        reward_scale                = reward_scale,
        price_spread_yuan_per_mwh   = price_spread_yuan_per_mwh,
        price_spread_sigma          = price_spread_sigma,
        forecast_sigma_max          = forecast_sigma_max,
        # episode_len: EnvParams default = 168 (training param, not in site YAML)
        price_table                 = price_table,
    )

    # obs_dim and action_dim are LOCKED for Gansu (§2.1, §2.2).
    # Non-Gansu sites with different device configurations → §8 extension (deferred).
    obs_dim    = 107  # 11 base + 24 × 4 forecast features
    action_dim = 6    # a_bat + 5 routing fractions (f_sl, f_sb, f_wl, f_wb, f_bl)

    return params, obs_dim, action_dim


def resolve_gansu(
    device_models_path: Union[str, Path] = None,
) -> tuple[EnvParams, int, int]:
    """Convenience: resolve the Gansu site (config/site_gansu.yaml).

    Acceptance gate: ``resolve_gansu()[0] == EnvParams()`` must hold bit-exactly
    for all scalar fields and the ``(12, 24)`` price_table array (v2.0.0: each row == PRICE_TABLE_YPW).

    Returns:
        (params, obs_dim=107, action_dim=6)
    """
    if device_models_path is None:
        device_models_path = _DEFAULT_DEVICE_MODELS
    return resolve_site(_DEFAULT_SITE_GANSU, device_models_path)


def get_unit_counts(
    site_config_path: Union[str, Path],
    device_models_path: Union[str, Path] = None,
) -> dict[str, int]:
    """Return resolved unit counts for discretely-instanced assets.

    Applies the canonical rounding rule (§4.1) or uses the explicit ``unit_count``
    field from the site YAML (explicit takes precedence over the formula).

    Returns a dict with keys ``"wind"`` and ``"battery"``.
    PV and grid are fleet-only — no per-unit count exposed.

    For Gansu:
        ``{"wind": 146, "battery": 1}``
        (146 = round(615.0 / 4.2), 1 = round(294.5 / 300.0))

    Used by the serving REST endpoint so A/E consumers (3D instanced fleet,
    composition panel) never re-implement the rounding rule in TS.
    """
    if device_models_path is None:
        device_models_path = _DEFAULT_DEVICE_MODELS

    site = _load_yaml(site_config_path)
    device_models = _load_yaml(device_models_path)
    assets = site["assets"]

    # --- Wind unit count ---
    wind_cfg = assets["wind"]
    if "unit_count" in wind_cfg:
        wind_units = int(wind_cfg["unit_count"])
    else:
        wind_model = _get_model(device_models, wind_cfg["model"])
        rated_mw_per_unit = float(wind_model["physics"]["rated_mw_per_unit"])
        fleet_rated_mw    = float(wind_cfg["fleet_rated_mw"])
        wind_units = round(fleet_rated_mw / rated_mw_per_unit)
        # Gansu: round(615.0 / 4.2) = round(146.43) = 146

    # --- Battery unit count ---
    bat_cfg = assets["battery"]
    if "unit_count" in bat_cfg:
        bat_units = int(bat_cfg["unit_count"])
    else:
        bat_model = _get_model(device_models, bat_cfg["model"])
        capacity_mwh_per_unit = float(bat_model["physics"]["capacity_mwh_per_unit"])
        fleet_capacity_mwh    = float(bat_cfg["fleet_capacity_mwh"])
        bat_units = round(fleet_capacity_mwh / capacity_mwh_per_unit)
        # Gansu: round(294.5 / 300.0) = round(0.983) = 1

    return {"wind": wind_units, "battery": bat_units}
