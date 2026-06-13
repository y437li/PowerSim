"""energy_go.serving.site_assembly — wizard-form → site_config assembly.

Contract: contracts/serving/site_assemble.md v1.0.0
Decision: D37 (assembly lives in one Python implementation; no TypeScript duplication)

Pure function — no I/O.  Called by the assemble endpoint after catalog
lookups and all input validation (400 checks) succeed.

Units:
    fleet_rated_mw       — MW   (wind)
    fleet_capacity_mw    — MW   (solar)
    fleet_capacity_mwh   — MWh  (battery energy)
    fleet_power_mw       — MW   (battery power)
    demand_rate          — ¥/MW·month  (from tariff region)
    price_spread         — ¥/MWh       (from tariff region)
    price_spread_sigma   — ¥/MWh       (from tariff region)
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Server defaults — match site_gansu.yaml canonical values (contract §3.4)
# ---------------------------------------------------------------------------

ASSEMBLE_DEFAULTS: dict = {
    "c_deg_yuan_per_mwh":        10.0,
    "voll_yuan_per_mwh":      20000.0,
    "curtail_yuan_per_mwh":     800.0,
    "soc_penalty_yuan_per_mwh": 20000.0,
    "reward_scale":             1.0e-5,
    "forecast_sigma_max":        0.10,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble_site_config(
    fleet: list[dict],
    tariff_region_id: str,
    tariff_schema: dict,
    device_models: dict,
    costs_overrides: dict | None = None,
    forecast_overrides: dict | None = None,
    site_meta: dict | None = None,
) -> dict:
    """Assemble a canonical site_config dict from wizard form inputs.

    Pure function — no I/O.  Called by the endpoint after all catalog lookups
    and input validation succeed.

    Args:
        fleet:             validated fleet entries; each has `model_id` plus either
                           `count` (int, wind/battery) or `fleet_capacity_mw`
                           (float, pv) or neither (grid).
        tariff_region_id:  valid key in tariff_schema["regions"].
        tariff_schema:     loaded by load_tariff_schema(); `schema["regions"]` is
                           a dict of region dataclass objects.
        device_models:     raw device_models YAML dict
                           {"schema_version": ..., "models": {model_id: {...}}}.
        costs_overrides:   optional dict with user-configurable cost fields.
        forecast_overrides: optional dict with forecast fields.
        site_meta:         optional site_meta dict (echoed into site_config).

    Returns:
        site_config dict:
            {
              "assets": { "wind": {...}, "solar": {...}, "battery": {...}, "grid": {...} },
              "tariff_region": str,
              "costs": { ... },
              "forecast": { "sigma_max": float },
              ["site_meta": { ... }]   # present only when site_meta provided
            }

    Raises:
        KeyError: if tariff_region_id or a model_id is not in the schema (caller
                  should validate before calling — these are defensive).
    """
    models = device_models.get("models", {})
    region = tariff_schema["regions"][tariff_region_id]

    # ------------------------------------------------------------------
    # Step 1: Merge fleet entries by model_id
    # Multiple entries with the SAME model_id are merged:
    #   wind/battery: sum count
    #   pv_panel:     sum fleet_capacity_mw
    #   grid_connection: no aggregation (always one per site)
    # ------------------------------------------------------------------
    merged: dict[str, dict] = {}  # model_id → merged entry
    for entry in fleet:
        mid = entry["model_id"]
        dtype = models[mid]["type"]
        if mid not in merged:
            merged[mid] = {
                "model_id": mid,
                "type":     dtype,
                "count":    0,
                "fleet_capacity_mw": 0.0,
            }
        m = merged[mid]
        if dtype in ("wind_turbine", "battery"):
            m["count"] += int(entry["count"])          # count is validated int ≥ 1 by caller
        elif dtype == "pv_panel":
            m["fleet_capacity_mw"] += float(entry["fleet_capacity_mw"])
        # grid_connection: nothing to aggregate

    # ------------------------------------------------------------------
    # Step 2: Build assets dict — one entry per device-type category key
    # Category keys match config_validation.py and resolver.py read paths:
    #   wind_turbine   → "wind"
    #   pv_panel       → "solar"
    #   battery        → "battery"
    #   grid_connection → "grid"
    # ------------------------------------------------------------------
    assets: dict = {}

    for mid, m in merged.items():
        dtype = m["type"]
        phy = models[mid].get("physics", {})

        if dtype == "wind_turbine":
            # fleet_rated_mw = count × rated_mw_per_unit   (§4.2; unit: MW)
            rated_mw_per_unit = float(phy["rated_mw_per_unit"])
            assets["wind"] = {
                "model":          mid,
                "fleet_rated_mw": m["count"] * rated_mw_per_unit,   # MW
            }

        elif dtype == "pv_panel":
            # fleet_capacity_mw direct from request (§4.2; unit: MW)
            # count is absent — no panel_mw_per_unit in device_model_schema v2.0.0
            assets["solar"] = {
                "model":             mid,
                "fleet_capacity_mw": m["fleet_capacity_mw"],         # MW
            }

        elif dtype == "battery":
            # fleet_capacity_mwh = count × capacity_mwh_per_unit  (unit: MWh)
            # fleet_power_mw     = count × power_mw_per_unit      (unit: MW)
            # NOTE: unit_count NOT emitted — contract §4.2 + reviewer case:
            #   config_validation E-BAT-UNIT only fires on explicit unit_count;
            #   absent → skips.  Emitting it would risk spurious E-BAT-UNIT errors.
            capacity_mwh_per_unit = float(phy["capacity_mwh_per_unit"])
            power_mw_per_unit     = float(phy["power_mw_per_unit"])
            assets["battery"] = {
                "model":              mid,
                "fleet_capacity_mwh": m["count"] * capacity_mwh_per_unit,  # MWh
                "fleet_power_mw":     m["count"] * power_mw_per_unit,      # MW
            }

        elif dtype == "grid_connection":
            # model_id only — resolver reads max_export/import from model physics directly
            # (contract §4.2: no max_export_mw / max_import_mw in assembled dict)
            assets["grid"] = {
                "model": mid,
            }

    # ------------------------------------------------------------------
    # Step 3: Costs — user-configurable overrides + tariff-sourced fields
    # Tariff-sourced fields always override request values (contract §4.2).
    # ------------------------------------------------------------------
    co = costs_overrides or {}
    costs: dict = {
        # User-configurable (with ASSEMBLE_DEFAULTS when absent):
        "c_deg_yuan_per_mwh":       float(
            co.get("c_deg_yuan_per_mwh",      ASSEMBLE_DEFAULTS["c_deg_yuan_per_mwh"])
        ),
        "voll_yuan_per_mwh":        float(
            co.get("voll_yuan_per_mwh",        ASSEMBLE_DEFAULTS["voll_yuan_per_mwh"])
        ),
        "curtail_yuan_per_mwh":     float(
            co.get("curtail_yuan_per_mwh",     ASSEMBLE_DEFAULTS["curtail_yuan_per_mwh"])
        ),
        "soc_penalty_yuan_per_mwh": float(
            co.get("soc_penalty_yuan_per_mwh", ASSEMBLE_DEFAULTS["soc_penalty_yuan_per_mwh"])
        ),
        "reward_scale":             float(
            co.get("reward_scale",             ASSEMBLE_DEFAULTS["reward_scale"])
        ),
        # Tariff-region-sourced (always from schema; ¥/MW·month, ¥/MWh, ¥/MWh):
        "demand_rate_yuan_per_mw_month": float(region.demand_rate_yuan_per_mw_month),
        "price_spread_yuan_per_mwh":     float(region.sell_clamp.spread_yuan_per_mwh),
        "price_spread_sigma":            float(
            region.sell_clamp.spread_noise_std_yuan_per_mwh
        ),
    }

    # ------------------------------------------------------------------
    # Step 4: Forecast
    # ------------------------------------------------------------------
    fo = forecast_overrides or {}
    forecast: dict = {
        "sigma_max": float(
            fo.get("sigma_max", ASSEMBLE_DEFAULTS["forecast_sigma_max"])
        ),
    }

    # ------------------------------------------------------------------
    # Step 5: Assemble site_config
    # tariff_region at root (no inline price_table — resolver loads from schema)
    # site_meta present only when provided (contract §4.1)
    # ------------------------------------------------------------------
    site_config: dict = {
        "assets":        assets,
        "tariff_region": tariff_region_id,
        "costs":         costs,
        "forecast":      forecast,
    }
    if site_meta is not None:
        # Filter out None values from optional sub-fields; echo back what was provided
        filtered_meta = {k: v for k, v in site_meta.items() if v is not None}
        if filtered_meta:
            site_config["site_meta"] = filtered_meta

    return site_config
