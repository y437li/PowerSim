"""energy_go.env.tariff_model_schema — tariff region library loader and validator.

Contract: contracts/shared/tariff_model_schema.md v1.0.0
Spec:     §3.4 (costs), §3.7 (Gansu 4-tier TOU), D3 (Δt=1h), D7 (sell clamp), D8 (minute-accurate)
Decisions: D7 (spread clamp ≥ 0), D8 (minute=0 at Δt=1h), D31/F1 (constant-real-price default)

Public API (imports):
    from energy_go.env.tariff_model_schema import (
        load_tariff_schema, TariffRegion, SellClamp,
        validate_tariff_region, ValidationIssue, ValidationResult,
    )

Pure Python — never called inside jit.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Union

import numpy as np
import yaml

# Re-export LOCKED types from config_validation — same NamedTuple shape.
# ValidationIssue: (rule_id, field, message, constraint)  — NO severity field.
# ValidationResult: (errors, warnings)                   — severity is implicit.
from energy_go.env.config_validation import ValidationIssue, ValidationResult

__all__ = [
    "SellClamp",
    "TariffRegion",
    "load_tariff_schema",
    "validate_tariff_region",
    "ValidationIssue",
    "ValidationResult",
]

# Default schema path (resolved from repo root at import time)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_TARIFF_SCHEMA = _REPO_ROOT / "config" / "tariff_model_schema.yaml"


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

class SellClamp(NamedTuple):
    """D7 sell-price clamp parameters.

    Effective sell price = max(0, buy_price − max(0, spread + N(0, σ))).
    Both parameters ≥ 0 by convention (W-TARIFF-SPREAD-NEG fires if either < 0).
    """

    spread_yuan_per_mwh: float             # mean buy-sell spread (¥/MWh)
    spread_noise_std_yuan_per_mwh: float   # σ for spread noise draw (¥/MWh); 0.0 = deterministic


class TariffRegion(NamedTuple):
    """One region entry parsed from config/tariff_model_schema.yaml.

    Attributes
    ----------
    currency : str
        ISO-4217 currency code (e.g. "CNY").  Display-layer only — the env is ¥-pure internally.
    price_table_yuan_per_mwh : np.ndarray, shape (12, 24), dtype float32
        Row index = month (0=Jan … 11=Dec); column index = hour of day (0–23).
        At Δt=1h every step lands at minute=0 (D3/D8), so columns are exact.
    demand_rate_yuan_per_mw_month : float
        ¥/MW·month.  Maps to EnvParams.demand_rate_yuan_per_mw_month.
        0.0 is valid (no demand-charge site).  < 0 is a hard error (E-TARIFF-DEMAND).
    sell_clamp : SellClamp
        D7 sell-price clamp parameters.
    provenance : str
        "public" for entries from the committed public YAML;
        "private" for entries injected via ENERGY_GO_PRIVATE_CONFIG overlay.
        Runtime-injected by the resolver — NOT stored in the YAML.
    """

    currency: str
    price_table_yuan_per_mwh: np.ndarray       # shape (12, 24) float32 ¥/MWh
    demand_rate_yuan_per_mw_month: float
    sell_clamp: SellClamp
    provenance: str = "public"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_tariff_schema(
    path: Union[str, Path, None] = None,
    provenance: str = "public",
) -> dict:
    """Load config/tariff_model_schema.yaml; parse region entries into TariffRegion objects.

    Parameters
    ----------
    path :
        Path to the YAML file.  Defaults to ``config/tariff_model_schema.yaml``
        relative to the repo root.
    provenance :
        Injected into every TariffRegion.provenance.  Pass "private" for entries
        loaded from a private overlay (ENERGY_GO_PRIVATE_CONFIG mechanism).

    Returns
    -------
    dict with keys:
        ``"schema_version"`` : str | None
        ``"regions"``        : dict[str, TariffRegion]

    Notes
    -----
    load_tariff_schema does NOT validate region entries — call validate_tariff_region()
    separately to run the E-/W-TARIFF-* rules.
    """
    if path is None:
        path = _DEFAULT_TARIFF_SCHEMA
    path = Path(path)

    with open(path) as f:
        raw = yaml.safe_load(f)

    regions: dict[str, TariffRegion] = {}
    for region_id, entry in raw.get("regions", {}).items():
        # price_table — parse to (12, 24) float32 ndarray
        raw_table = entry["price_table_yuan_per_mwh"]
        table = np.array(raw_table, dtype=np.float32)

        sell_clamp = SellClamp(
            spread_yuan_per_mwh=float(entry["sell_clamp"]["spread_yuan_per_mwh"]),
            spread_noise_std_yuan_per_mwh=float(
                entry["sell_clamp"]["spread_noise_std_yuan_per_mwh"]
            ),
        )
        regions[region_id] = TariffRegion(
            currency=str(entry["currency"]),
            price_table_yuan_per_mwh=table,
            demand_rate_yuan_per_mw_month=float(entry["demand_rate_yuan_per_mw_month"]),
            sell_clamp=sell_clamp,
            provenance=provenance,
        )

    return {
        "schema_version": raw.get("schema_version"),
        "regions": regions,
    }


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_tariff_region(region_dict: dict) -> ValidationResult:
    """Validate one raw region dict against the tariff schema rules (§5).

    The ``region_dict`` is the raw Python dict as read from YAML (or constructed
    in tests).  It is NOT a TariffRegion object — validation runs before parsing.

    Validation rules applied (in order):

    Hard errors (result.errors):
        E-TARIFF-SHAPE  — price_table shape ≠ (12, 24); also catches ragged tables
        E-TARIFF-DEMAND — demand_rate_yuan_per_mw_month < 0

    Soft warnings (result.warnings):
        W-TARIFF-PRICE-NEG       — any price_table entry < 0  (shape must be valid first)
        W-TARIFF-SPREAD-NEG      — spread < 0 OR spread_noise_std < 0
        W-TARIFF-CURRENCY-UNKNOWN — currency != "CNY"

    Parameters
    ----------
    region_dict :
        dict with keys: currency, price_table_yuan_per_mwh,
        demand_rate_yuan_per_mw_month, sell_clamp (sub-dict).

    Returns
    -------
    ValidationResult(errors, warnings)
        errors:   list[ValidationIssue] — hard errors; block env startup if non-empty
        warnings: list[ValidationIssue] — soft warnings; operator review recommended

    Notes
    -----
    ValidationIssue has NO 'severity' field — severity is implicit in which list
    the issue appears in (errors = hard, warnings = soft).  See config_validation §2.
    """
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    # ------------------------------------------------------------------
    # E-TARIFF-SHAPE — price_table must be exactly shape (12, 24)
    # Checks ALL rows explicitly to catch ragged tables (row-0-only sampling misses
    # a short last row; backend-reviewer PR #91 ragged test pins this).
    # ------------------------------------------------------------------
    raw_table = region_dict.get("price_table_yuan_per_mwh", [])
    shape_ok = _check_table_shape(raw_table)

    if not shape_ok:
        try:
            n_rows = len(raw_table) if hasattr(raw_table, "__len__") else "?"
            first_row_len = len(raw_table[0]) if n_rows and raw_table else "?"
            constraint_str = (
                f"required (12, 24); got ({n_rows}, {first_row_len}) or ragged"
            )
        except Exception:
            constraint_str = "required (12, 24); actual shape could not be determined"
        errors.append(ValidationIssue(
            rule_id="E-TARIFF-SHAPE",
            field="price_table_yuan_per_mwh",
            message=(
                f"E-TARIFF-SHAPE: price_table_yuan_per_mwh must be shape (12, 24) "
                f"[months × hours]; {constraint_str}"
            ),
            constraint=constraint_str,
        ))
    else:
        # ---------------------------------------------------------------
        # W-TARIFF-PRICE-NEG — any price entry < 0 (only when shape is valid)
        # Fire once on first negative cell found (avoids issue flooding).
        # ---------------------------------------------------------------
        for m, row in enumerate(raw_table):
            for h, v in enumerate(row):
                if float(v) < 0.0:
                    warnings.append(ValidationIssue(
                        rule_id="W-TARIFF-PRICE-NEG",
                        field="price_table_yuan_per_mwh",
                        message=(
                            f"W-TARIFF-PRICE-NEG: price_table[{m}][{h}]={float(v):.1f} < 0 "
                            f"(unusual for CN market)"
                        ),
                        constraint=f"price_table[{m}][{h}]={float(v):.1f} < 0",
                    ))
                    # One warning is sufficient; break out of both loops.
                    break
            else:
                continue
            break

    # ------------------------------------------------------------------
    # W-TARIFF-SPREAD-NEG — spread < 0 OR σ < 0
    # ------------------------------------------------------------------
    sell_clamp = region_dict.get("sell_clamp", {})
    if isinstance(sell_clamp, dict):
        spread_raw = sell_clamp.get("spread_yuan_per_mwh")
        sigma_raw  = sell_clamp.get("spread_noise_std_yuan_per_mwh")
    else:
        # Support SellClamp NamedTuple as input (e.g. in nested calls)
        spread_raw = getattr(sell_clamp, "spread_yuan_per_mwh", None)
        sigma_raw  = getattr(sell_clamp, "spread_noise_std_yuan_per_mwh", None)

    if spread_raw is not None:
        try:
            spread_f = float(spread_raw)
            if spread_f < 0.0:
                warnings.append(ValidationIssue(
                    rule_id="W-TARIFF-SPREAD-NEG",
                    field="sell_clamp.spread_yuan_per_mwh",
                    message=(
                        f"W-TARIFF-SPREAD-NEG: spread_yuan_per_mwh={spread_f:.1f} < 0 "
                        f"(negative spread → sell > buy → risk-free arbitrage, D7)"
                    ),
                    constraint=f"spread_yuan_per_mwh={spread_f:.1f} < 0",
                ))
        except (TypeError, ValueError):
            pass

    if sigma_raw is not None:
        try:
            sigma_f = float(sigma_raw)
            if sigma_f < 0.0:
                warnings.append(ValidationIssue(
                    rule_id="W-TARIFF-SPREAD-NEG",
                    field="sell_clamp.spread_noise_std_yuan_per_mwh",
                    message=(
                        f"W-TARIFF-SPREAD-NEG: spread_noise_std_yuan_per_mwh={sigma_f:.1f} < 0 "
                        f"(negative σ is mathematically incoherent)"
                    ),
                    constraint=f"spread_noise_std_yuan_per_mwh={sigma_f:.1f} < 0",
                ))
        except (TypeError, ValueError):
            pass

    # ------------------------------------------------------------------
    # W-TARIFF-CURRENCY-UNKNOWN — currency != "CNY"
    # ------------------------------------------------------------------
    currency = region_dict.get("currency", "")
    if str(currency) != "CNY":
        warnings.append(ValidationIssue(
            rule_id="W-TARIFF-CURRENCY-UNKNOWN",
            field="currency",
            message=(
                f"W-TARIFF-CURRENCY-UNKNOWN: currency='{currency}'; "
                f"env is ¥-pure, only 'CNY' is recognised"
            ),
            constraint=f"currency='{currency}' != 'CNY'",
        ))

    # ------------------------------------------------------------------
    # E-TARIFF-DEMAND — demand_rate < 0 (HARD ERROR)
    # rl-architect ruling: commercially impossible for CN demand charge (unlike
    # negative spot/spread prices which occur in real oversupply markets).
    # ------------------------------------------------------------------
    demand_raw = region_dict.get("demand_rate_yuan_per_mw_month")
    if demand_raw is not None:
        try:
            demand_f = float(demand_raw)
            if demand_f < 0.0:
                errors.append(ValidationIssue(
                    rule_id="E-TARIFF-DEMAND",
                    field="demand_rate_yuan_per_mw_month",
                    message=(
                        f"E-TARIFF-DEMAND: demand_rate={demand_f:.1f} < 0 "
                        f"(commercially impossible for CN demand charge)"
                    ),
                    constraint=f"demand_rate={demand_f:.1f} < 0",
                ))
        except (TypeError, ValueError):
            pass

    return ValidationResult(errors=errors, warnings=warnings)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_table_shape(raw_table: object) -> bool:
    """Return True iff raw_table has exactly shape (12, 24) with no ragged rows.

    Handles both list-of-lists and numpy array inputs.
    Checks ALL 12 rows (not just row 0) to catch ragged tables where the last
    row is shorter — a row-0-only check would miss that failure (backend-reviewer PR #91).
    """
    # Numpy array path
    if hasattr(raw_table, "shape"):
        return bool(raw_table.shape == (12, 24))

    # List / tuple path — check row count then ALL row lengths
    try:
        if not hasattr(raw_table, "__len__"):
            return False
        if len(raw_table) != 12:
            return False
        return all(
            hasattr(row, "__len__") and len(row) == 24
            for row in raw_table
        )
    except Exception:
        return False
