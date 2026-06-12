"""energy_go.env.config_validation — two-tier site-config validator.

Contract: contracts/shared/config_validation.md v1.0.0 (LOCKED @ c06f951)
Spec refs: REBUILD_SPEC §3.6; LINEAGE D26 (two-tier), D18 (single-source), D32(i)
Owner (physics rules): jax-env-engineer
Owner (econ rules): finance-expert
Task: #66

Public API:
    validate(site_config, device_models=None) -> ValidationResult  — non-raising
    validate_from_paths(site_config_path, device_models_path)      — convenience

Versioning (rl-architect, LOCK @ c06f951):
    Adding/activating gated rules = minor, no re-LOCK.
    Removing/renaming rule_id or changing ValidationResult/ValidationIssue shape = major.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple, Union

import yaml


# ---------------------------------------------------------------------------
# Data types (§2)
# ---------------------------------------------------------------------------

class ValidationIssue(NamedTuple):
    rule_id:    str   # stable; format "E-<CAT>-<MNEM>" or "W-<...>"
    field:      str   # dot-path, e.g. "assets.battery.fleet_capacity_mwh"
    message:    str   # human-readable sentence
    constraint: str   # numbers shown — e.g. "98.16MW/294.5MWh=0.333C ≤ 0.333C OK"


class ValidationResult(NamedTuple):
    errors:   list  # list[ValidationIssue] — hard errors; config rejected if non-empty
    warnings: list  # list[ValidationIssue] — soft warnings; proceed with explicit ack


class ConfigValidationError(ValueError):
    """Raised by resolve_site() when ValidationResult.errors is non-empty.

    Attributes:
        errors:   list[ValidationIssue]  (the failing hard-error rules)
        warnings: list[ValidationIssue]  (warnings that also fired; informational)
    """

    def __init__(self, errors: list, warnings: list):
        self.errors = errors
        self.warnings = warnings
        msg = f"{len(errors)} config error(s): " + "; ".join(
            f"[{e.rule_id}] {e.message}" for e in errors
        )
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> "float | None":
    """Convert to float; return None on failure (missing/malformed/NaN string)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pos(x: "float | None") -> bool:
    """True iff x is a well-defined positive number.

    IEEE-754-safe: uses `x > 0` so NaN returns False (NaN > 0 is False),
    correctly treating NaN as non-positive.  Equivalent to `not (x > 0)` being
    the check for "not positive" — see §4 E-CAP-POS NaN guard note.
    """
    return x is not None and bool(x > 0)


def _deep_get(d: Any, *keys: str, default: Any = None) -> Any:
    """Navigate nested dicts; return default on any missing key."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


def _get_model_physics(device_models: "dict | None", model_id: "str | None") -> dict:
    """Return physics sub-dict for a model; empty dict if not found or malformed.

    Guards every step against non-dict values so a malformed device_models can
    never propagate an AttributeError (§3.2 non-raising).
    """
    if not isinstance(device_models, dict) or model_id is None:
        return {}
    models = device_models.get("models")
    if not isinstance(models, dict):
        return {}
    model = models.get(model_id)
    if not isinstance(model, dict):
        return {}
    physics = model.get("physics")
    if not isinstance(physics, dict):
        return {}
    return physics


def _resolve_grid_limits(
    site: dict,
    device_models: "dict | None",
) -> "tuple[float | None, float | None]":
    """Resolve (max_export_mw, max_import_mw) — site override first, then model physics."""
    grid_cfg = _deep_get(site, "assets", "grid")
    if not isinstance(grid_cfg, dict):
        return None, None

    # Site-level override takes precedence
    site_export = _safe_float(grid_cfg.get("max_export_mw"))
    site_import = _safe_float(grid_cfg.get("max_import_mw"))

    if site_export is not None and site_import is not None:
        return site_export, site_import

    # Fall back to model physics
    model_id = grid_cfg.get("model")
    gp = _get_model_physics(device_models, model_id)
    export = site_export if site_export is not None else _safe_float(gp.get("max_export_mw"))
    import_ = site_import if site_import is not None else _safe_float(gp.get("max_import_mw"))
    return export, import_


# ---------------------------------------------------------------------------
# Rule implementations — hard errors
# ---------------------------------------------------------------------------

def _check_e_cap_pos(site: dict, device_models: "dict | None", issues: list) -> None:
    """E-CAP-POS — non-positive physical capacity → hard error.

    Uses `not (x > 0)` to catch both ≤ 0 and NaN (IEEE 754 safe, §4).
    Grid limits resolved from device model physics when not overridden in site.
    """
    # Non-grid fields read directly from site
    direct_checks = [
        ("assets.wind.fleet_rated_mw",
         _safe_float(_deep_get(site, "assets", "wind", "fleet_rated_mw"))),
        ("assets.solar.fleet_capacity_mw",
         _safe_float(_deep_get(site, "assets", "solar", "fleet_capacity_mw"))),
        ("assets.battery.fleet_capacity_mwh",
         _safe_float(_deep_get(site, "assets", "battery", "fleet_capacity_mwh"))),
        ("assets.battery.fleet_power_mw",
         _safe_float(_deep_get(site, "assets", "battery", "fleet_power_mw"))),
    ]

    for field, val in direct_checks:
        if val is None:
            continue  # missing field → skip (E-SCHEMA covers it; not in v1 scope)
        if not _pos(val):
            issues.append(ValidationIssue(
                rule_id="E-CAP-POS",
                field=field,
                message=f"{field.split('.')[-1]} must be > 0",
                constraint=f"{field.split('.')[-1]} = {val} — must be > 0",
            ))

    # Grid limits — resolved from model physics (§4 "resolved" note)
    max_export, max_import = _resolve_grid_limits(site, device_models)
    if max_export is not None and not _pos(max_export):
        issues.append(ValidationIssue(
            rule_id="E-CAP-POS",
            field="assets.grid.max_export_mw",
            message="max_export_mw must be > 0",
            constraint=f"max_export_mw = {max_export} — must be > 0",
        ))
    if max_import is not None and not _pos(max_import):
        issues.append(ValidationIssue(
            rule_id="E-CAP-POS",
            field="assets.grid.max_import_mw",
            message="max_import_mw must be > 0",
            constraint=f"max_import_mw = {max_import} — must be > 0",
        ))


def _check_e_bat_crate(site: dict, device_models: dict, issues: list) -> None:
    """E-BAT-CRATE — fleet C-rate > device per-unit rating → hard error.

    Skip guard (§3.2, §4): skips when fleet_capacity_mwh ≤ 0 or NaN
    (E-CAP-POS covers that case; dividing would raise ZeroDivisionError).
    """
    fleet_power = _safe_float(_deep_get(site, "assets", "battery", "fleet_power_mw"))
    fleet_cap   = _safe_float(_deep_get(site, "assets", "battery", "fleet_capacity_mwh"))

    # Division guard: can't compute ratio if cap ≤ 0/NaN
    if not _pos(fleet_cap) or fleet_power is None:
        return

    bat_model_id = _deep_get(site, "assets", "battery", "model")
    bp = _get_model_physics(device_models, bat_model_id)
    dev_power = _safe_float(bp.get("power_mw_per_unit"))
    dev_cap   = _safe_float(bp.get("capacity_mwh_per_unit"))

    if not _pos(dev_cap) or dev_power is None:
        return

    fleet_crate  = fleet_power / fleet_cap
    device_crate = dev_power / dev_cap

    if fleet_crate > device_crate:
        issues.append(ValidationIssue(
            rule_id="E-BAT-CRATE",
            field="assets.battery.fleet_power_mw",
            message="Fleet C-rate exceeds device per-unit rating",
            constraint=(
                f"{fleet_power:.4g}MW/{fleet_cap:.4g}MWh={fleet_crate:.4g}C"
                f" > device limit {dev_power:.4g}MW/{dev_cap:.4g}MWh={device_crate:.4g}C"
            ),
        ))


def _check_e_bat_unit(site: dict, device_models: dict, issues: list) -> None:
    """E-BAT-UNIT — explicit unit_count inconsistent with fleet sizing → hard error.

    Fires only when unit_count is explicitly provided in the site YAML.
    Two sub-checks: energy and power, each with 1% relative tolerance.
    """
    unit_count_raw = _deep_get(site, "assets", "battery", "unit_count")
    if unit_count_raw is None:
        return  # not explicitly set — rule skipped

    unit_count = _safe_float(unit_count_raw)
    if unit_count is None:
        return

    fleet_cap   = _safe_float(_deep_get(site, "assets", "battery", "fleet_capacity_mwh"))
    fleet_power = _safe_float(_deep_get(site, "assets", "battery", "fleet_power_mw"))

    bat_model_id = _deep_get(site, "assets", "battery", "model")
    bp = _get_model_physics(device_models, bat_model_id)
    dev_cap   = _safe_float(bp.get("capacity_mwh_per_unit"))
    dev_power = _safe_float(bp.get("power_mw_per_unit"))

    # Energy sub-check
    if fleet_cap is not None and dev_cap is not None and _pos(fleet_cap):
        expected_cap = unit_count * dev_cap
        rel_err = abs(expected_cap - fleet_cap) / fleet_cap
        if rel_err > 0.01:
            issues.append(ValidationIssue(
                rule_id="E-BAT-UNIT",
                field="assets.battery.unit_count",
                message="Explicit unit_count inconsistent with fleet_capacity_mwh (>1% tolerance)",
                constraint=(
                    f"unit_count={unit_count:.4g},"
                    f" {unit_count:.4g}×{dev_cap:.4g}={expected_cap:.4g}MWh"
                    f" ≠ fleet={fleet_cap:.4g}MWh (>{rel_err*100:.1f}% tolerance)"
                ),
            ))

    # Power sub-check
    if fleet_power is not None and dev_power is not None and _pos(fleet_power):
        expected_power = unit_count * dev_power
        rel_err_p = abs(expected_power - fleet_power) / fleet_power
        if rel_err_p > 0.01:
            issues.append(ValidationIssue(
                rule_id="E-BAT-UNIT",
                field="assets.battery.unit_count",
                message="Explicit unit_count inconsistent with fleet_power_mw (>1% tolerance)",
                constraint=(
                    f"unit_count={unit_count:.4g},"
                    f" {unit_count:.4g}×{dev_power:.4g}={expected_power:.4g}MW"
                    f" ≠ fleet={fleet_power:.4g}MW (>{rel_err_p*100:.1f}% tolerance)"
                ),
            ))


def _check_e_load_svc(site: dict, device_models: "dict | None", issues: list) -> None:
    """E-LOAD-SVC — peak load unservable at maximum supply → hard error.

    Gated on load_peak_mw field being present; skipped when absent.
    max_import_mw resolved from device model physics when not overridden.
    """
    load_peak = _safe_float(_deep_get(site, "load", "load_peak_mw"))
    if load_peak is None:
        return  # not present — rule skipped

    _, max_import = _resolve_grid_limits(site, device_models)
    wind_rated  = _safe_float(_deep_get(site, "assets", "wind", "fleet_rated_mw"))
    solar_cap   = _safe_float(_deep_get(site, "assets", "solar", "fleet_capacity_mw"))
    bat_power   = _safe_float(_deep_get(site, "assets", "battery", "fleet_power_mw"))

    max_supply = (
        (max_import or 0.0)
        + (wind_rated or 0.0)
        + (solar_cap or 0.0)
        + (bat_power or 0.0)
    )

    if load_peak > max_supply:
        issues.append(ValidationIssue(
            rule_id="E-LOAD-SVC",
            field="load.load_peak_mw",
            message="Peak load exceeds maximum supply capacity",
            constraint=(
                f"peak_load={load_peak:.4g}MW"
                f" > max_supply={max_import or 0.0:.4g}+{wind_rated or 0.0:.4g}"
                f"+{solar_cap or 0.0:.4g}+{bat_power or 0.0:.4g}"
                f"={max_supply:.4g}MW"
            ),
        ))


def _check_e_tar_shape(site: dict, device_models: "dict | None", issues: list) -> None:
    """E-TAR-SHAPE — tariff table wrong shape → hard error.

    v1.x (flat (24,)): len != 24
    v2.0+ (seasonal (12,24)): shape != (12, 24)  [post-PR #87]
    """
    price_table = _deep_get(site, "tariff", "price_table_yuan_per_mwh")
    if price_table is None:
        return  # missing tariff section — skip

    # Determine expected shape from schema version
    use_seasonal = False
    if device_models is not None:
        schema_ver = device_models.get("schema_version", "")
        try:
            major = int(str(schema_ver).split(".")[0])
            if major >= 2:
                use_seasonal = True
        except (ValueError, IndexError):
            pass

    if use_seasonal:
        ok = (
            isinstance(price_table, list)
            and len(price_table) == 12
            and all(isinstance(row, list) and len(row) == 24 for row in price_table)
        )
        if not ok:
            shape_str = f"({len(price_table)},)" if isinstance(price_table, list) else "?"
            issues.append(ValidationIssue(
                rule_id="E-TAR-SHAPE",
                field="tariff.price_table_yuan_per_mwh",
                message="Tariff table must be (12, 24) for device_model_schema v2.0+",
                constraint=f"shape(price_table)={shape_str} ≠ (12, 24) (expected seasonal matrix)",
            ))
    else:
        if not (isinstance(price_table, list) and len(price_table) == 24):
            got = len(price_table) if isinstance(price_table, list) else "?"
            issues.append(ValidationIssue(
                rule_id="E-TAR-SHAPE",
                field="tariff.price_table_yuan_per_mwh",
                message="Tariff table must have exactly 24 entries",
                constraint=f"len(price_table)={got} ≠ 24 (expected flat hourly list)",
            ))


def _check_e_econ_neg(site: dict, device_models: dict, issues: list) -> None:
    """E-ECON-NEG — negative economics parameter → hard error (finance-expert owned).

    Gated on economics blocks being present in device_models.
    Checks device-level economics fields that must be non-negative.
    """
    # Fields that MUST be non-negative (zero is legal for "none")
    NON_NEG_FIELDS = frozenset({
        "capex_per_kw_yuan",
        "opex_fixed_per_kw_year_yuan",
        "opex_var_per_mwh_yuan",
        "lifetime_years",
        "capex_energy_per_kwh_yuan",
        "capex_power_per_kw_yuan",
        "opex_fixed_per_kwh_year_yuan",
        "capex_lump_sum_yuan",
        "opex_fixed_per_mw_year_yuan",
        "capex_per_kw_ac_yuan",
    })

    models = device_models.get("models")
    if not isinstance(models, dict):
        return
    for model_id, model_def in models.items():
        if not isinstance(model_def, dict):
            continue  # malformed model entry — skip
        econ = model_def.get("economics")
        if not isinstance(econ, dict):
            continue  # no economics block — skip this device
        for field_name, val in econ.items():
            if field_name not in NON_NEG_FIELDS:
                continue
            fval = _safe_float(val)
            if fval is not None and fval < 0.0:
                issues.append(ValidationIssue(
                    rule_id="E-ECON-NEG",
                    field=f"device_models.models.{model_id}.economics.{field_name}",
                    message=f"{field_name} must be ≥ 0 for model '{model_id}'",
                    constraint=(
                        f"{field_name} = {fval} for model '{model_id}'"
                        f" — must be ≥ 0"
                    ),
                ))


# ---------------------------------------------------------------------------
# Rule implementations — warnings
# ---------------------------------------------------------------------------

def _check_w_bat_crate_2c(site: dict, issues: list) -> None:
    """W-BAT-CRATE-2C — fleet C-rate > 2C (LFP chemistry advisory) → warning.

    Independent from E-BAT-CRATE: fires whenever fleet > 2C, even if fleet ≤ device.

    Skip guard (§3.2, §5): skips when fleet_capacity_mwh ≤ 0 or NaN.
    Called only when device_models is not None (gated per contract §6).
    """
    fleet_power = _safe_float(_deep_get(site, "assets", "battery", "fleet_power_mw"))
    fleet_cap   = _safe_float(_deep_get(site, "assets", "battery", "fleet_capacity_mwh"))

    if not _pos(fleet_cap) or fleet_power is None:
        return

    fleet_crate = fleet_power / fleet_cap
    if fleet_crate > 2.0:
        issues.append(ValidationIssue(
            rule_id="W-BAT-CRATE-2C",
            field="assets.battery.fleet_power_mw",
            message="Fleet C-rate > 2C — LFP BMS shutdowns likely above 2C",
            constraint=(
                f"fleet_power={fleet_power:.4g}MW"
                f"/fleet_capacity={fleet_cap:.4g}MWh"
                f"={fleet_crate:.4g}C > 2.0C LFP advisory"
            ),
        ))


def _check_w_bat_dur_10h(site: dict, issues: list) -> None:
    """W-BAT-DUR-10H — storage duration > 10 hours → warning.

    Skip guard (§3.2, §5): skips when fleet_power_mw ≤ 0 or NaN.
    """
    fleet_cap   = _safe_float(_deep_get(site, "assets", "battery", "fleet_capacity_mwh"))
    fleet_power = _safe_float(_deep_get(site, "assets", "battery", "fleet_power_mw"))

    if not _pos(fleet_power) or fleet_cap is None:
        return

    duration_h = fleet_cap / fleet_power
    if duration_h > 10.0:
        issues.append(ValidationIssue(
            rule_id="W-BAT-DUR-10H",
            field="assets.battery.fleet_capacity_mwh",
            message="Battery storage duration > 10h — likely unit confusion (MWh vs kWh?)",
            constraint=(
                f"{fleet_cap:.4g}MWh/{fleet_power:.4g}MW"
                f"={duration_h:.4g}h > 10h — check units (MWh vs kWh?)"
            ),
        ))


def _check_w_pcc_curtail(site: dict, device_models: "dict | None", issues: list) -> None:
    """W-PCC-CURTAIL — PCC export < 20% of installed gen → severe curtailment warning.

    max_export_mw resolved from device model physics when not in site.
    """
    max_export, _ = _resolve_grid_limits(site, device_models)
    wind_rated  = _safe_float(_deep_get(site, "assets", "wind", "fleet_rated_mw"))
    solar_cap   = _safe_float(_deep_get(site, "assets", "solar", "fleet_capacity_mw"))

    if max_export is None or wind_rated is None or solar_cap is None:
        return

    total_gen = wind_rated + solar_cap
    threshold = 0.20 * total_gen

    if max_export < threshold:
        issues.append(ValidationIssue(
            rule_id="W-PCC-CURTAIL",
            field="assets.grid.max_export_mw",
            message="PCC export < 20% of installed generation — >80% curtailment at rated output",
            constraint=(
                f"max_export={max_export:.4g}MW"
                f" < 0.20×({wind_rated:.4g}+{solar_cap:.4g})"
                f"={threshold:.4g}MW — >80% curtailment at rated output"
            ),
        ))


def _check_w_size_trivial(site: dict, issues: list) -> None:
    """W-SIZE-TRIVIAL — all assets < 1 MW/MWh simultaneously → training will not converge."""
    wind_rated = _safe_float(_deep_get(site, "assets", "wind", "fleet_rated_mw"))
    solar_cap  = _safe_float(_deep_get(site, "assets", "solar", "fleet_capacity_mw"))
    bat_cap    = _safe_float(_deep_get(site, "assets", "battery", "fleet_capacity_mwh"))

    if wind_rated is None or solar_cap is None or bat_cap is None:
        return

    if wind_rated < 1.0 and solar_cap < 1.0 and bat_cap < 1.0:
        issues.append(ValidationIssue(
            rule_id="W-SIZE-TRIVIAL",
            field="assets.wind.fleet_rated_mw",
            message="All assets below 1 MW/MWh — SAC training will not converge",
            constraint=(
                f"wind={wind_rated:.4g}MW, solar={solar_cap:.4g}MW,"
                f" bat={bat_cap:.4g}MWh — all below 1MW/MWh; training will not converge"
            ),
        ))


# ---------------------------------------------------------------------------
# Public API (§3)
# ---------------------------------------------------------------------------

def validate(
    site_config: "dict[str, Any]",
    device_models: "dict[str, Any] | None" = None,
) -> ValidationResult:
    """Validate a parsed site config dict against physics and economics rules.

    Non-raising (§3.2).  Safe to call from UI pre-check and serving endpoint.
    Exhaustive: collects ALL failing rules before returning (§3.1).

    Args:
        site_config:   Parsed YAML content of site_<name>.yaml as a Python dict.
        device_models: Parsed YAML content of device_models.yaml.  If None,
                       rules that require device physics are skipped (not errored).

    Returns:
        ValidationResult(errors, warnings).  Both lists may be empty.
    """
    if not isinstance(site_config, dict):
        return ValidationResult(errors=[], warnings=[])

    # §3.2 non-raising: coerce malformed device_models to None rather than
    # letting .get()/.items() raise AttributeError downstream.
    if device_models is not None and not isinstance(device_models, dict):
        device_models = None

    errors: list = []
    warnings: list = []

    # --- Hard-error rules ---
    _check_e_cap_pos(site_config, device_models, errors)
    _check_e_tar_shape(site_config, device_models, errors)
    _check_e_load_svc(site_config, device_models, errors)

    if device_models is not None:
        _check_e_bat_crate(site_config, device_models, errors)
        _check_e_bat_unit(site_config, device_models, errors)
        _check_e_econ_neg(site_config, device_models, errors)
    # E-ECON-WACC: gated on finance.wacc_pct field (post-finance-config; finance-expert)

    # --- Warning rules ---
    _check_w_bat_dur_10h(site_config, warnings)
    _check_w_pcc_curtail(site_config, device_models, warnings)
    _check_w_size_trivial(site_config, warnings)

    if device_models is not None:
        _check_w_bat_crate_2c(site_config, warnings)
    # W-H2-GT-GEN: gated on assets.electrolyzer (post-§8 electrolyzer)

    return ValidationResult(errors=errors, warnings=warnings)


def validate_from_paths(
    site_config_path: "str | Path",
    device_models_path: "str | Path" = "config/device_models.yaml",
) -> ValidationResult:
    """Convenience: load YAMLs from disk, then call validate()."""
    with open(site_config_path) as f:
        site = yaml.safe_load(f)
    with open(device_models_path) as f:
        models = yaml.safe_load(f)
    return validate(site, models)
