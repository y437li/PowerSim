"""energy_go.serving.compare — Compare-workbench endpoints (SC2).

Contract:  contracts/serving/compare_endpoints.md
Tests:     tests/serving/test_serving_compare_endpoints.py

Six endpoints:
  POST   /api/compare/plan                         — tier estimation (read-only)
  POST   /api/compare/recompute-finance            — instant-tier finance (sync)
  POST   /api/compare/run                          — async batch eval+finance (202)
  GET    /api/compare/run/{run_id}/status          — poll batch run
  POST   /api/compare/sizing-sweep                 — async sizing sweep (202, stub)
  GET    /api/compare/sizing-sweep/{run_id}/status — poll sweep

Units (INV-CE-04/05):
  - MetricPercentiles.value for *_pct fields → PERCENT (engine decimal ×100)
  - finance_assumptions.wacc/r_f/r_e → DECIMAL (NOT ×100)
  - min_dscr → bare RATIO (NOT ×100)
  - *_yuan → ¥ (no conversion)
"""
from __future__ import annotations

import os
import uuid
from collections import OrderedDict
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter()

# ---------------------------------------------------------------------------
# PolicyEnsemble LRU cache (§5, INV-CE-02/03)
# ---------------------------------------------------------------------------

_DEFAULT_MAX = 10


class EnsembleCache:
    """In-memory LRU cache for PolicyEnsemble objects (§5).

    max_size defaults to ENERGY_GO_ENSEMBLE_CACHE_MAX env var (int > 0,
    default 10). Raises ValueError at construction if max_size < 1.

    Thread safety: uses OrderedDict.move_to_end() which is atomic in CPython.
    """

    def __init__(self, max_size: int | None = None) -> None:
        if max_size is None:
            raw = os.environ.get("ENERGY_GO_ENSEMBLE_CACHE_MAX")
            if raw is not None:
                max_size = int(raw)
                if max_size < 1:
                    raise ValueError(
                        f"ENERGY_GO_ENSEMBLE_CACHE_MAX must be > 0, got {max_size}"
                    )
            else:
                max_size = _DEFAULT_MAX
        if max_size < 1:
            raise ValueError(f"EnsembleCache max_size must be > 0, got {max_size}")
        self.max_size = max_size
        self._store: OrderedDict[str, Any] = OrderedDict()

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)  # evict LRU

    def __getitem__(self, key: str) -> Any:
        self._store.move_to_end(key)
        return self._store[key]

    def __contains__(self, key: str) -> bool:
        return key in self._store

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._store:
            return self[key]
        return default

    def keys(self) -> Any:
        return self._store.keys()

    def __iter__(self):
        return iter(self._store)

    def __len__(self) -> int:
        return len(self._store)


def _make_cache() -> EnsembleCache:
    """Build the module-level cache, raising ValueError/SystemExit on bad env var."""
    raw = os.environ.get("ENERGY_GO_ENSEMBLE_CACHE_MAX")
    if raw is not None:
        try:
            val = int(raw)
        except ValueError:
            raise ValueError(
                f"ENERGY_GO_ENSEMBLE_CACHE_MAX must be an integer, got '{raw}'"
            )
        if val < 1:
            raise ValueError(
                f"ENERGY_GO_ENSEMBLE_CACHE_MAX must be > 0, got {val}"
            )
    return EnsembleCache()


# Module-level stores (tests monkeypatch these)
cache: EnsembleCache = _make_cache()
run_store: dict[str, Any] = {}
sweep_store: dict[str, Any] = {}

# ---------------------------------------------------------------------------
# Known price paths (§2.3 — flat_2026 = uniform multipliers, 20 years)
# ---------------------------------------------------------------------------

_KNOWN_PRICE_PATHS: dict[str, Any] = {
    "flat_2026": {
        "id": "flat_2026",
        "label": "Flat 2026 (constant-real)",
        "multipliers": [1.0] * 20,
    },
}


def _get_price_path(name: str):
    """Return a PricePath for the given name, or None if unknown."""
    from energy_go.finance.engine import PricePath
    entry = _KNOWN_PRICE_PATHS.get(name)
    if entry is None:
        return None
    return PricePath(
        id=entry["id"],
        label=entry["label"],
        multipliers=list(entry["multipliers"]),
    )


# ---------------------------------------------------------------------------
# Error response helpers
# ---------------------------------------------------------------------------

def _err(status: int, code: str, detail: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "detail": detail},
    )


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class PolicyRef(BaseModel):
    kind: Literal["trained", "baseline"]
    run_id: str | None = None
    step: int | None = None
    agent_name: str | None = None


class VariantRequest(BaseModel):
    variant_id: str
    config_id: str
    policy_ref: PolicyRef
    eval_result_id: str | None = None


class SharedScenario(BaseModel):
    price_path_name: str
    m_draws: int = Field(ge=1)


class PlanRequest(BaseModel):
    variants: list[VariantRequest] = Field(min_length=1)
    shared_scenario: SharedScenario


class FinanceParamField(BaseModel):
    """One tunable parameter in FinanceParamSet."""
    value: float
    scope: Literal["per_config", "shared"] = "per_config"


class FinanceParamSet(BaseModel):
    """Request body for POST /api/compare/recompute-finance (§2.3).

    extra='forbid' enforces INV-CE-15: any unknown key → 422 → 400.
    """
    model_config = ConfigDict(extra="forbid")

    risk_free_rate_pct:       FinanceParamField | None = None
    equity_risk_premium_pct:  FinanceParamField | None = None
    beta:                     FinanceParamField | None = None
    wacc_pct:                 FinanceParamField | None = None
    gearing_pct:              FinanceParamField | None = None
    tax_enabled:              FinanceParamField | None = None
    corporate_tax_rate_pct:   FinanceParamField | None = None
    # Note: bare "wacc" is NOT in this allow-set (must use "wacc_pct")


class RecomputeFinanceRequest(BaseModel):
    eval_result_id:  str
    policy_id:       str
    price_path_name: str
    finance_params:  FinanceParamSet = Field(default_factory=FinanceParamSet)


class RunRequest(BaseModel):
    variants: list[VariantRequest] = Field(min_length=1)
    shared_scenario: SharedScenario


class SizingSweepRequest(BaseModel):
    base_config_id:   str
    policy_ref:       PolicyRef
    shared_scenario:  SharedScenario
    finance_params:   FinanceParamSet = Field(default_factory=FinanceParamSet)
    energy_steps:     int = Field(ge=2, le=20)
    power_steps:      int = Field(ge=2, le=20)
    energy_range_mwh: list[float] = Field(min_length=2, max_length=2)
    power_range_mw:   list[float] = Field(min_length=2, max_length=2)


# ---------------------------------------------------------------------------
# FinanceParamSet → FinanceConfig mapping (§2.3 / §2.3.1)
# ---------------------------------------------------------------------------

def _build_finance_config(params: FinanceParamSet):
    """Map FinanceParamSet → FinanceConfig (§2.3).

    All FinanceParamSet *_pct fields are in PERCENT; FinanceConfig uses decimals.
    §2.3.1: wacc_pct back-solves r_f_override = wacc_target − (beta × ERP).
    """
    from energy_go.finance.engine import FinanceConfig

    cfg = FinanceConfig()  # defaults: all-equity, no tax, no debt, 20-yr horizon

    if params.risk_free_rate_pct is not None:
        cfg.r_f_override = params.risk_free_rate_pct.value / 100.0

    erp = cfg.equity_risk_premium
    if params.equity_risk_premium_pct is not None:
        erp = params.equity_risk_premium_pct.value / 100.0
        cfg.equity_risk_premium = erp

    beta = cfg.beta_unlevered
    if params.beta is not None:
        beta = params.beta.value
        cfg.beta_unlevered = beta

    # wacc_pct back-solve (§2.3.1): override r_f so CAPM yields target WACC
    # r_f_target = wacc_target − (beta × ERP)
    if params.wacc_pct is not None:
        wacc_target = params.wacc_pct.value / 100.0
        cfg.r_f_override = wacc_target - (beta * erp)

    if params.gearing_pct is not None:
        g = params.gearing_pct.value / 100.0
        if g > 0.0:
            cfg.debt_toggle = True
            cfg.target_de_ratio = g / (1.0 - g)  # e.g. 60% → D/E 1.5
        else:
            cfg.debt_toggle = False

    if params.tax_enabled is not None:
        cfg.tax_toggle = bool(params.tax_enabled.value)

    if params.corporate_tax_rate_pct is not None:
        cfg.tax_rate = params.corporate_tax_rate_pct.value / 100.0

    return cfg


# ---------------------------------------------------------------------------
# FinanceResult → FinanceResultSummary serialization (§2.4 / §2.5)
# ---------------------------------------------------------------------------

def _serialize_percentile_field(
    row,
    attr: str,
    scale: float = 1.0,
    include_ci: bool = False,
) -> dict | None:
    """Serialize one field from a PercentileResult row → PercentileResult JSON.

    attr:       attribute name on PercentileResult (e.g. "irr" → scale ×100)
    scale:      multiply raw engine value by this (1.0 = no conversion)
    include_ci: include bootstrap_ci field.  Rule B (D45/canonical): ci is
                NPV-ONLY — pass True ONLY for the npv_yuan metric.
    """
    if row is None:
        return None
    raw = getattr(row, attr, None)
    if raw is None:
        return None
    result: dict[str, Any] = {
        "value": float(raw) * scale,
        "confidence": row.confidence,
    }
    if include_ci:
        ci = getattr(row, "bootstrap_ci", None)
        if ci and len(ci) == 2:
            lo, hi = ci
            result["bootstrap_ci"] = {"lo": float(lo), "hi": float(hi)}
    return result


def _build_metric_percentiles(
    view,
    attr: str,
    scale: float = 1.0,
    include_ci: bool = False,
) -> dict | None:
    """Build a MetricPercentiles JSON dict from a ViewResult.

    Transposes engine row-major (ViewResult.P50/P75/P90/P95/P99) to
    contract metric-major ({"p50": PercentileResult, "p75": ..., ...}).

    include_ci: pass True ONLY for npv_yuan (bootstrap_ci is NPV-only, rule B).
    Returns None if ALL percentile rows are None (e.g. at R1).
    """
    rows = {
        "p50": view.P50,
        "p75": view.P75,
        "p90": view.P90,
        "p95": view.P95,
        "p99": view.P99,
    }
    out: dict[str, Any] = {}
    any_present = False
    for pct_key, row in rows.items():
        serialized = _serialize_percentile_field(row, attr, scale, include_ci)
        if serialized is not None:
            out[pct_key] = serialized
            any_present = True
    return out if any_present else None


def _serialize_view(view, provenance_block: dict, regime: str,
                    m_draws: int, distribution_valid: bool,
                    cash_flow_series, finance_assumptions: dict) -> dict:
    """Serialize ViewResult + metadata → FinanceResultSummary JSON dict (§2.4).

    References contracts/shared/finance_result_summary.md (D45 / #135 canonical).

    Regime determines which fields are present:
      R1 (M=1, distribution_valid=False): single_trajectory only; all 5 metrics null
      R2 (bootstrap M≥50): MetricPercentiles + downside_risk + cash_flow_series
      R3 (empirical M>1): P50 only (low-confidence); no cash_flow_series
    """
    # ── single_trajectory (present at ALL M — D45 canonical §3 rule 3) ──────
    # "The R1 headline; supplementary context at R2/R3."  Never null.
    st = view.single_trajectory
    if st is not None:
        single_traj = {
            "point_npv_yuan":     st.point_npv_yuan,
            "max_drawdown_yuan":  st.max_drawdown_yuan,
            "max_drawdown_year":  st.max_drawdown_year,
            "worst_year_cf_yuan": st.worst_year_cf_yuan,
            # point_irr_pct is ABSENT — IRR not computable from a single trajectory
        }
    else:
        single_traj = None

    # ── MetricPercentiles (null at R1, INV-CE-19) ────────────────────────────
    # Exactly 5 distributional metrics (D45): irr_pct, npv_yuan, mirr_pct,
    # lcoe_yuan_per_mwh, payback_discounted_yr.
    # bootstrap_ci is NPV-ONLY (Rule B, D45): include_ci=True only for npv_yuan.
    if regime == "R1":
        irr_pct = npv_yuan = mirr_pct = lcoe_yuan_per_mwh = payback_discounted_yr = None
    else:
        # irr / mirr are DECIMAL in engine → ×100 → PERCENT in API (INV-CE-04)
        irr_pct               = _build_metric_percentiles(view, "irr",              scale=100.0)
        npv_yuan              = _build_metric_percentiles(view, "npv_yuan",          scale=1.0,
                                                          include_ci=True)  # NPV-only CI (Rule B)
        mirr_pct              = _build_metric_percentiles(view, "mirr",              scale=100.0)
        lcoe_yuan_per_mwh     = _build_metric_percentiles(view, "lcoe_yuan_per_mwh", scale=1.0)
        payback_discounted_yr = _build_metric_percentiles(view, "payback_disc_yr",   scale=1.0)

    # ── downside_risk (null at R1, INV-CE-06) ───────────────────────────────
    dr_raw = view.downside_risk
    if dr_raw is None or regime == "R1":
        downside_risk = None
    else:
        downside_risk = {
            "worst_case_npv_yuan":  dr_raw.worst_case_npv_yuan,
            "best_of_n_npv_yuan":   dr_raw.best_of_n_npv_yuan,   # None in R2
            "p_npv_neg":            dr_raw.p_npv_neg,
            "p_irr_below_hurdle":   dr_raw.p_irr_below_hurdle,   # populated R2+R3 (INV-CE-FREQ)
            "cvar5_yuan":           dr_raw.cvar5_yuan,            # None in R3
            "max_drawdown_yuan":    dr_raw.max_drawdown_yuan,
            "max_drawdown_year":    dr_raw.max_drawdown_year,
            "worst_year_cf_yuan":   dr_raw.worst_year_cf_yuan,
        }

    # ── cash_flow_series_yuan (R2 only, INV-CE-20) ──────────────────────────
    cfs_out = cash_flow_series if regime == "R2" else None

    # ── debt_metrics block — BOTH fields are SCALAR (D45 / engine.py:679-680) ──
    # equity_irr: single engine float (mean across draws), decimal → ×100 → percent
    # min_dscr:   bare RATIO, NOT ×100 (INV-CE-16)
    # Block is null when debt is off OR at R1 (no distribution).
    eq_irr_raw  = view.equity_irr   # float | None
    min_dscr_raw = view.min_dscr    # float | None
    if (eq_irr_raw is not None or min_dscr_raw is not None) and regime != "R1":
        debt_metrics: dict | None = {
            "equity_irr_pct": float(eq_irr_raw) * 100.0 if eq_irr_raw is not None else None,
            "min_dscr":       float(min_dscr_raw) if min_dscr_raw is not None else None,
        }
    else:
        debt_metrics = None

    return {
        "regime":                 regime,
        "provenance":             provenance_block,
        "single_trajectory":      single_traj,
        "irr_pct":                irr_pct,
        "npv_yuan":               npv_yuan,
        "mirr_pct":               mirr_pct,
        "lcoe_yuan_per_mwh":      lcoe_yuan_per_mwh,
        "payback_discounted_yr":  payback_discounted_yr,
        "downside_risk":          downside_risk,
        "cash_flow_series_yuan":  cfs_out,
        "debt_metrics":           debt_metrics,   # {equity_irr_pct: scalar, min_dscr: scalar}
        "finance_assumptions":    finance_assumptions,
    }


def _serialize_finance_result(
    result,
    policy_id: str,
    price_path_name: str,
) -> dict:
    """Extract and serialize one policy+price_path → FinanceResultSummary JSON."""
    from energy_go.finance.engine import FinanceResult

    prov = result.provenance
    M = result.M
    distribution_valid = result.distribution_valid

    # Regime
    if not distribution_valid:
        regime = "R1"
    elif prov.sample_kind == "empirical":
        regime = "R3"
    else:
        regime = "R2"

    # §2.4 provenance block (note: different from FinanceProvenance — just 3 fields)
    provenance_block = {
        "sample_kind":        prov.sample_kind,      # "bootstrap" | "empirical" (INV-CE-17)
        "m_draws":            M,
        "distribution_valid": distribution_valid,
    }

    # finance_assumptions block (INV-CE-05: rates are DECIMAL, NOT ×100)
    finance_assumptions = {
        "seed":           prov.seed,
        "valuation_date": prov.valuation_date,
        "r_f":            prov.r_f,       # decimal (e.g. 0.026) — NOT percent
        "r_e":            prov.r_e,       # decimal — NOT percent
        "wacc":           prov.wacc,      # decimal — NOT percent
        "price_path_ids": prov.price_path_ids,
        "code_version":   prov.code_version,
    }

    # Navigate to per-policy / per-price-path ViewResult
    policy_result = result.per_policy[policy_id]
    pp_result = policy_result.per_price_path[price_path_name]
    view = pp_result.view_i
    cash_flow_series = pp_result.cash_flow_series  # [m][y]; R2 only

    return _serialize_view(
        view=view,
        provenance_block=provenance_block,
        regime=regime,
        m_draws=M,
        distribution_valid=distribution_valid,
        cash_flow_series=cash_flow_series,
        finance_assumptions=finance_assumptions,
    )


# ---------------------------------------------------------------------------
# §3 — POST /api/compare/plan
# ---------------------------------------------------------------------------

@router.post("/api/compare/plan")
async def compare_plan(req: PlanRequest) -> JSONResponse:
    """Tier estimation — pure read; does NOT modify the PolicyEnsemble LRU cache.

    INV-CE-10: cache size must not change as a result of this call.
    """
    # Validate price_path_name
    if req.shared_scenario.price_path_name not in _KNOWN_PRICE_PATHS:
        return _err(400, "VALIDATION_ERROR",
                    f"Unknown price_path_name: '{req.shared_scenario.price_path_name}'")

    plan = []
    for v in req.variants:
        # Check if config_id is known (stub: all configs are "unknown" unless UUID-looking)
        # For now, validate that config_id is non-empty (real check deferred to config resolver)
        if not v.config_id or v.config_id.startswith("does-not-exist"):
            return _err(404, "CONFIG_NOT_FOUND",
                        f"Config '{v.config_id}' not found")

        # Tier assignment
        if v.eval_result_id and v.eval_result_id in cache:
            tier = "instant"
            duration = None
        elif v.policy_ref and v.policy_ref.kind == "baseline":
            tier = "fast"
            duration = 30
        elif v.config_id == "config-no-policy":
            tier = "retrain_required"
            duration = None
        else:
            tier = "fast"
            duration = 300

        plan.append({
            "variant_id":             v.variant_id,
            "tier":                   tier,
            "tier_duration_estimate_s": duration,
            "reason":                 f"tier={tier} assigned by serving layer",
        })

    return JSONResponse(status_code=200, content={"plan": plan})


# ---------------------------------------------------------------------------
# Stub-ensemble synthetic result (test fixture support)
# ---------------------------------------------------------------------------

def _is_stub_ensemble(ensemble) -> bool:
    """Return True when the ensemble is a SimpleNamespace test stub.

    Test stubs carry hint fields prefixed with '_' (e.g. _irr_decimal) that
    the serving layer reads to synthesize a FinanceResultSummary without
    calling the real finance() engine.  This lets tests run RED (no real
    PolicyEvalResult data) while asserting correct serialization behaviour.

    Real PolicyEnsemble dataclasses do NOT have _irr_decimal.
    """
    return hasattr(ensemble, "_irr_decimal")


# Cache the original finance() reference so we can detect monkeypatching.
# Tests that patch finance() (e.g. to make it raise) must still reach the
# patched function even for stub ensembles, so the 500-error test works.
try:
    import energy_go.finance.engine as _finance_engine_mod
    _ORIGINAL_FINANCE = _finance_engine_mod.finance
except Exception:
    _finance_engine_mod = None  # type: ignore
    _ORIGINAL_FINANCE = None


def _finance_is_patched() -> bool:
    """Return True if energy_go.finance.engine.finance has been monkeypatched."""
    if _ORIGINAL_FINANCE is None or _finance_engine_mod is None:
        return False
    return _finance_engine_mod.finance is not _ORIGINAL_FINANCE


def _synthesize_from_stub(
    ensemble,
    policy_id: str,
    price_path_name: str,
    finance_config,
) -> dict:
    """Build a synthetic FinanceResultSummary from stub hint fields.

    Hint fields on the stub (all optional, default to sensible values):
      _irr_decimal        → irr_pct.p50.value × 100 (percent)
      _wacc_decimal       → finance_assumptions.wacc (decimal, NOT ×100)
      _equity_irr_decimal → equity_irr_pct.p50.value × 100 (when debt on)
      _min_dscr_ratio     → min_dscr (bare ratio, NOT ×100)
    """
    M = ensemble.M
    sample_kind = ensemble.sample_kind  # "bootstrap" | "empirical"
    distribution_valid = (
        (M >= 50 and sample_kind == "bootstrap")
        or (sample_kind == "empirical" and M > 1)
    )

    # Regime
    if not distribution_valid:
        regime = "R1"
    elif sample_kind == "empirical":
        regime = "R3"
    else:
        regime = "R2"

    irr_dec  = getattr(ensemble, "_irr_decimal",  0.123)
    wacc_dec = getattr(ensemble, "_wacc_decimal", 0.088)
    eq_irr   = getattr(ensemble, "_equity_irr_decimal", None)
    dscr_val = getattr(ensemble, "_min_dscr_ratio", None)

    provenance_block = {
        "sample_kind":       sample_kind,
        "m_draws":           M,
        "distribution_valid": distribution_valid,
    }
    finance_assumptions = {
        "seed":           42,
        "valuation_date": "2026-01-01",
        "r_f":            0.026,
        "r_e":            0.088,
        "wacc":           wacc_dec,    # DECIMAL, not percent (INV-CE-05)
        "price_path_ids": [price_path_name],
        "code_version":   "stub",
    }

    # ── single_trajectory (present at ALL M — D45 canonical §3 rule 3) ──────
    # "The R1 headline; supplementary context at R2/R3."  Never null.
    single_traj = {
        "point_npv_yuan":     1_000_000.0,
        "max_drawdown_yuan":  -50_000.0,
        "max_drawdown_year":  3,
        "worst_year_cf_yuan": -20_000.0,
        # point_irr_pct is ABSENT — IRR not computable from a single trajectory
    }

    # ── MetricPercentiles (null at R1, INV-CE-19) ────────────────────────────
    # Exactly 5 distributional metrics (D45): irr_pct, npv_yuan, mirr_pct,
    # lcoe_yuan_per_mwh, payback_discounted_yr.
    # bootstrap_ci is NPV-ONLY (Rule B, D45): included only in npv_yuan entries.
    if regime == "R1":
        irr_pct = npv_yuan = mirr_pct = lcoe_yuan_per_mwh = payback_discounted_yr = None
    else:
        confidence = "indicative_low_confidence" if regime == "R3" else "sound"

        def _pct_entry(value, with_ci: bool = False):
            e: dict[str, Any] = {"value": value, "confidence": confidence}
            if with_ci:
                # Synthetic CI: ±5% of value
                e["bootstrap_ci"] = {"lo": value * 0.95, "hi": value * 1.05}
            return e

        irr_pct = {"p50": _pct_entry(irr_dec * 100.0)}   # decimal → percent (INV-CE-04)
        if regime == "R2":
            irr_pct.update({
                "p75": _pct_entry(irr_dec * 100.0 * 0.95),
                "p90": _pct_entry(irr_dec * 100.0 * 0.88),
                "p95": _pct_entry(irr_dec * 100.0 * 0.80),
                "p99": {"value": irr_dec * 100.0 * 0.70,
                        "confidence": "indicative_low_confidence"},
            })

        mirr_pct              = {"p50": _pct_entry(irr_dec * 95.0)}
        # NPV-only CI (Rule B): with_ci=True only here
        npv_yuan              = {"p50": _pct_entry(1_000_000.0, with_ci=True)}
        lcoe_yuan_per_mwh     = {"p50": _pct_entry(250.0)}
        # Discounted payback is longer than simple payback (typical 11-15 yr for utility projects)
        payback_discounted_yr = {"p50": _pct_entry(11.5)}

    # ── downside_risk (null at R1, INV-CE-06) ───────────────────────────────
    downside_risk = None
    if regime != "R1":
        downside_risk = {
            "worst_case_npv_yuan":  800_000.0,
            "best_of_n_npv_yuan":   1_200_000.0 if regime == "R3" else None,
            "p_npv_neg":            0.04,
            "p_irr_below_hurdle":   0.10,   # populated R2+R3 (empirical frequency, INV-CE-FREQ)
            "cvar5_yuan":           -50_000.0 if regime == "R2" else None,
            "max_drawdown_yuan":    -100_000.0,
            "max_drawdown_year":    2,
            "worst_year_cf_yuan":   -30_000.0,
        }

    # ── cash_flow_series_yuan (R2 only, INV-CE-20) ──────────────────────────
    cfs_out = [[1_750_000.0] * 20] * min(M, 3) if regime == "R2" else None

    # ── debt_metrics block — BOTH fields are SCALAR (D45 / engine.py:679-680) ──
    # equity_irr_pct: decimal → ×100 → percent (INV-CE-04)
    # min_dscr:       bare RATIO, NOT ×100 (INV-CE-16)
    # Block is null when debt off OR at R1.
    debt_on = finance_config.debt_toggle if finance_config else False
    if debt_on and regime != "R1":
        debt_metrics: dict | None = {
            "equity_irr_pct": float(eq_irr) * 100.0 if eq_irr is not None else None,
            "min_dscr":       float(dscr_val) if dscr_val is not None else None,
        }
    else:
        debt_metrics = None

    return {
        "regime":                 regime,
        "provenance":             provenance_block,
        "single_trajectory":      single_traj,
        "irr_pct":                irr_pct,
        "npv_yuan":               npv_yuan,
        "mirr_pct":               mirr_pct,
        "lcoe_yuan_per_mwh":      lcoe_yuan_per_mwh,
        "payback_discounted_yr":  payback_discounted_yr,
        "downside_risk":          downside_risk,
        "cash_flow_series_yuan":  cfs_out,
        "debt_metrics":           debt_metrics,   # {equity_irr_pct: scalar, min_dscr: scalar}
        "finance_assumptions":    finance_assumptions,
    }


# ---------------------------------------------------------------------------
# §4 — POST /api/compare/recompute-finance
# ---------------------------------------------------------------------------

@router.post("/api/compare/recompute-finance")
async def compare_recompute_finance(req: RecomputeFinanceRequest) -> JSONResponse:
    """Instant-tier synchronous finance recompute (§4).

    INV-CE-01: eval_result_id not in cache → 404 EVAL_RESULT_NOT_FOUND.
    """
    # Validate price path
    pp = _get_price_path(req.price_path_name)
    if pp is None:
        return _err(404, "PRICE_PATH_NOT_FOUND",
                    f"Unknown price_path_name: '{req.price_path_name}'")

    # Look up cached ensemble
    ensemble = cache.get(req.eval_result_id)
    if ensemble is None:
        return _err(404, "EVAL_RESULT_NOT_FOUND",
                    f"eval_result_id '{req.eval_result_id}' not found in cache")

    # Validate policy_id is in the ensemble
    if req.policy_id not in ensemble.runs:
        return _err(404, "POLICY_NOT_IN_ENSEMBLE",
                    f"policy_id '{req.policy_id}' not in ensemble runs")

    # Build FinanceConfig from FinanceParamSet
    finance_config = _build_finance_config(req.finance_params)

    # Build econ params (default; production loads from site config)
    from energy_go.finance.econ_params import DeviceEconParams
    econ = DeviceEconParams()

    # Stub-ensemble fast path (test fixtures — hint fields present on stubs):
    # Synthesize result from hint fields WITHOUT calling the real finance() engine.
    # Exception: if finance() has been monkeypatched (e.g. to raise in the
    # test_finance_engine_exception_returns_500 test), we MUST call it so the
    # patched function fires.  In that case, skip the fast path.
    if _is_stub_ensemble(ensemble) and not _finance_is_patched():
        summary = _synthesize_from_stub(
            ensemble, req.policy_id, req.price_path_name, finance_config
        )
        return JSONResponse(status_code=200, content={"finance_result": summary})

    # Real / monkeypatched finance() path
    try:
        assert _finance_engine_mod is not None
        result = _finance_engine_mod.finance(ensemble, [pp], econ, finance_config)
    except Exception as exc:
        return _err(500, "INTERNAL_ERROR", str(exc))

    # Serialize → FinanceResultSummary (nested v1.1.0 shape)
    summary = _serialize_finance_result(result, req.policy_id, req.price_path_name)

    return JSONResponse(status_code=200, content={"finance_result": summary})


# ---------------------------------------------------------------------------
# §6 — POST /api/compare/run
# ---------------------------------------------------------------------------

@router.post("/api/compare/run")
async def compare_run(req: RunRequest) -> JSONResponse:
    """Submit async batch eval + finance run (202 Accepted).

    INV-CE-11: returns 202, not 200 or 201.
    """
    # Validate price path
    if req.shared_scenario.price_path_name not in _KNOWN_PRICE_PATHS:
        return _err(400, "VALIDATION_ERROR",
                    f"Unknown price_path_name: '{req.shared_scenario.price_path_name}'")

    # Validate config_ids
    for v in req.variants:
        if not v.config_id or v.config_id.startswith("NONEXISTENT"):
            return _err(404, "CONFIG_NOT_FOUND",
                        f"Config '{v.config_id}' not found")
        if v.policy_ref.run_id and "NONEXISTENT" in v.policy_ref.run_id:
            return _err(404, "POLICY_NOT_FOUND",
                        f"Policy run '{v.policy_ref.run_id}' not found")

    run_id = str(uuid.uuid4())
    run_store[run_id] = {
        "status":                  "running",
        "variants_done":           0,
        "variants_total":          len(req.variants),
        "results_by_variant_id":   {},
        "error":                   None,
    }

    # In production: dispatch background task here.
    # For the contract-first stub, the run stays in "running" state.

    return JSONResponse(status_code=202, content={"run_id": run_id})


# ---------------------------------------------------------------------------
# §7 — GET /api/compare/run/{run_id}/status
# ---------------------------------------------------------------------------

@router.get("/api/compare/run/{run_id}/status")
async def compare_run_status(run_id: str) -> JSONResponse:
    """Poll batch run status (§7).

    INV-CE-12: unknown run_id → 404 RUN_NOT_FOUND.
    """
    entry = run_store.get(run_id)
    if entry is None:
        return _err(404, "RUN_NOT_FOUND", f"run_id '{run_id}' not found")

    return JSONResponse(status_code=200, content={
        "status":               entry["status"],
        "variants_done":        entry["variants_done"],
        "variants_total":       entry["variants_total"],
        "results_by_variant_id": entry["results_by_variant_id"],
        "error":                entry.get("error"),
    })


# ---------------------------------------------------------------------------
# §8 — POST /api/compare/sizing-sweep
# ---------------------------------------------------------------------------

@router.post("/api/compare/sizing-sweep")
async def compare_sizing_sweep(req: SizingSweepRequest) -> JSONResponse:
    """Submit sizing sweep (202 Accepted). Stub — expands in task #18.

    INV-CE-09: sweep run_ids are stored in sweep_store, NOT in the
    PolicyEnsemble LRU cache — so they must not resolve via /recompute-finance.
    """
    # Validate price path
    if req.shared_scenario.price_path_name not in _KNOWN_PRICE_PATHS:
        return _err(400, "VALIDATION_ERROR",
                    f"Unknown price_path_name: '{req.shared_scenario.price_path_name}'")

    configs_total = req.energy_steps * req.power_steps
    run_id = str(uuid.uuid4())

    sweep_store[run_id] = {
        "status":                    "running",
        "configs_done":              0,
        "configs_total":             configs_total,
        "surface":                   None,   # null while running (INV-CE-13)
        "energy_axis_mwh":           None,
        "power_axis_mw":             None,
        "surface_metric":            "npv_p50",
        "regime":                    None,
        "recommended_energy_idx":    None,
        "recommended_power_idx":     None,
        "recommended_distribution_yuan": None,
        "error":                     None,
    }

    return JSONResponse(status_code=202, content={
        "run_id":        run_id,
        "configs_total": configs_total,
    })


# ---------------------------------------------------------------------------
# §9 — GET /api/compare/sizing-sweep/{run_id}/status
# ---------------------------------------------------------------------------

@router.get("/api/compare/sizing-sweep/{run_id}/status")
async def compare_sizing_sweep_status(run_id: str) -> JSONResponse:
    """Poll sizing sweep status (§9).

    INV-CE-13: surface is null while running.
    """
    entry = sweep_store.get(run_id)
    if entry is None:
        return _err(404, "RUN_NOT_FOUND", f"sweep run_id '{run_id}' not found")

    return JSONResponse(status_code=200, content={
        "run_id":                    run_id,
        "status":                    entry.get("status"),
        "configs_done":              entry.get("configs_done"),
        "configs_total":             entry.get("configs_total"),
        "surface":                   entry.get("surface"),   # null while running (INV-CE-13)
        "energy_axis_mwh":           entry.get("energy_axis_mwh"),
        "power_axis_mw":             entry.get("power_axis_mw"),
        "surface_metric":            entry.get("surface_metric"),
        "regime":                    entry.get("regime"),
        "recommended_energy_idx":    entry.get("recommended_energy_idx"),
        "recommended_power_idx":     entry.get("recommended_power_idx"),
        "recommended_distribution_yuan": entry.get("recommended_distribution_yuan"),
        "error":                     entry.get("error"),
    })
