"""Finance engine — `finance()` facade (§13.12, D39).

Public surface exported by this module:
  finance()          — pure entry point
  PolicyEnsemble     — M×N dispatch trajectories
  PricePath          — per-year revenue multiplier
  CgbCurve           — CGB yield-curve snapshot
  FinanceConfig      — discount / tax / debt / horizon configuration
  FinanceResult      — top-level output
  (plus all nested output types)

All types and the engine are defined here so the test imports
  from energy_go.finance.engine import finance, PolicyEnsemble, …
resolve in one place.

Purity: finance() performs no network access, no filesystem I/O, no clock reads.
        Purity is structural (FIN-37).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Sequence

import numpy as np

from energy_go.training.eval import PolicyEvalResult  # §13.7 / task #55
from energy_go.finance.discount import compute_wacc
from energy_go.finance.cash_flow import build_cash_flow_series, _eol_events
from energy_go.finance.metrics import (
    npv, irr, mirr, lcoe, lcos,
    payback_simple, payback_discounted, dscr,
)
from energy_go.finance.distributions import (
    exceedance_percentile, cvar5, p_below, max_drawdown, worst_year_cf,
)
from energy_go.finance.price_path import any_nonuniform, get_multiplier
from energy_go.finance.sensitivity import npv_vs_r_curve, compute_sensitivity_surface
from energy_go.finance.econ_params import DeviceEconParams


# ── Version ───────────────────────────────────────────────────────────────────

try:
    from importlib.metadata import version as _pkg_version
    _CODE_VERSION: str = _pkg_version("energy-go")
except Exception:
    _CODE_VERSION = "0.1.0"


# ── Input types ───────────────────────────────────────────────────────────────


@dataclass
class PolicyEnsemble:
    """§13.12 input: M weather draws × N-year trajectories per policy.

    Leaf: PolicyEvalResult (task #55). The engine reads:
      - streams[*].{volume, value_yuan}  — 6-stream accumulators (INV-STREAM-AUTHORITY)
      - generation_mwh, bat_discharge_mwh, bat_throughput_mwh  — physical quantities
      - degradation_yuan, curtailment_yuan, voll_yuan  — cash-bearing real_money
    memo_only block (penalty_yuan, soc_*) is structurally unreachable (INV-BASIS).

    runs[policy_id][m][n] — m ∈ [0, M), n ∈ [0, N)
    len(runs[π]) == M for all π; ragged → ValueError.
    """
    seed:        int
    M:           int
    sample_kind: Literal["bootstrap", "empirical"]
    runs:        dict[str, list[list[PolicyEvalResult]]]


@dataclass
class PricePath:
    """§13.4 deterministic finance scenario — per-year revenue multiplier.

    multipliers[y-1] is applied to revenue streams in year y.
    Uniform (all 1.0): constant-real prices (D31/F1); requires_retrain=False.
    Non-uniform: requires_retrain=True (INV-FINLAYER §3.9).
    """
    id:          str
    label:       str
    multipliers: list[float]   # length N; multipliers[0] = year-1 factor


@dataclass
class CgbCurve:
    """Static CGB yield-curve snapshot (§13.5a)."""
    snapshot_date: str            # ISO 8601 date; travels in provenance
    points:        dict[int, float]  # tenor_yr → yield (decimal)
    lpr_5yr:       float          # 5yr LPR (decimal) for cost-of-debt base


@dataclass
class FinanceConfig:
    """Discount / tax / debt / horizon configuration (§13.5–§13.9).

    base case = pre-tax, all-equity (D31): r = r_e (CAPM); tax OFF; debt OFF.
    """
    # CAPM inputs (§13.5b)
    beta_unlevered:          float              = 0.60
    equity_risk_premium:     float              = 0.060
    country_risk_premium:    float              = 0.0
    cgb_curve:               "CgbCurve | None"  = None
    r_f_override:            "float | None"     = None   # bypasses curve interp
    # Tax toggle (§13.9)
    tax_toggle:              bool               = False
    tax_rate:                float              = 0.25
    depreciation_years:      int                = 20     # straight-line
    # Debt toggle (§13.9)
    debt_toggle:             bool               = False
    target_de_ratio:         float              = 1.5
    credit_spread:           float              = 0.0125  # 125 bps over 5yr LPR
    loan_term_years:         int                = 20
    r_d_override:            "float | None"     = None   # bypasses LPR + credit_spread
    # Horizon / project
    horizon_years:           int                = 20
    valuation_date:          str                = "2026-01-01"
    # Bootstrap CI (§13.10a)
    bootstrap_seed:          int                = 42
    bootstrap_n_resamples:   int                = 2000
    bootstrap_ci_level:      float              = 0.90   # 90% CI
    # Downside thresholds
    hurdle_rate_override:    "float | None"     = None   # None → r_e (CAPM base)
    # View II
    baseline_policy_id:      "str | None"       = None   # absent → View II omitted


# ── Output types ──────────────────────────────────────────────────────────────


@dataclass
class PercentileResult:
    """One exceedance-percentile row."""
    npv_yuan:             float
    irr:                  float    # decimal
    mirr:                 float    # decimal
    lcoe_yuan_per_mwh:    float
    lcos_yuan_per_mwh:    float
    payback_simple_yr:    float
    payback_disc_yr:      float
    bootstrap_ci:         tuple    # (lower, upper) at bootstrap_ci_level
    confidence:           str      # "sound" | "indicative_low_confidence"


@dataclass
class DownsideRisk:
    """§13.10b — six downside metrics; present only when distribution_valid=True."""
    worst_case_npv_yuan:    float
    p_npv_neg:              float
    p_irr_below_hurdle:     float
    cvar5_yuan:             float
    max_drawdown_yuan:      float
    max_drawdown_year:      int
    worst_year_cf_yuan:     float


@dataclass
class SingleTrajectoryResult:
    """§13.10c — metrics present at ALL M (including M=1)."""
    max_drawdown_yuan:   float
    max_drawdown_year:   int
    worst_year_cf_yuan:  float
    point_npv_yuan:      float


@dataclass
class ViewResult:
    """Per-policy, per-price-path result for one View (I or II)."""
    # Present at all M:
    single_trajectory: SingleTrajectoryResult
    # Present only when distribution_valid=True:
    P50:  "PercentileResult | None" = None
    P75:  "PercentileResult | None" = None
    P90:  "PercentileResult | None" = None
    P95:  "PercentileResult | None" = None
    P99:  "PercentileResult | None" = None
    downside_risk: "DownsideRisk | None" = None
    # Debt-toggle-gated (None, not 0.0, when debt OFF):
    equity_irr: "float | None" = None
    min_dscr:   "float | None" = None


@dataclass
class PricePathResult:
    view_i:              ViewResult
    view_ii:             "ViewResult | None"
    cash_flow_series:    list        # [m][y] pre-price-path baseline ¥
    npv_vs_r_curve:      list        # [(r, npv_yuan), …]
    sensitivity_surface: dict


@dataclass
class PolicyFinanceResult:
    per_price_path: dict   # str → PricePathResult


@dataclass
class FinanceProvenance:
    """§13.12 — travels with every result."""
    seed:           int
    M:              int
    sample_kind:    str
    valuation_date: str
    r_f:            float
    r_f_tenor_yr:   int
    r_f_curve_date: str
    r_e:            float
    wacc:           float
    beta_levered:   float
    scenario_id:    str
    code_version:   str
    price_path_ids: list
    m1_banner:      bool = False   # True when M=1 (§13.10c non-dismissable banner)


@dataclass
class FinanceResult:
    """Top-level output of finance() — §13.12."""
    M:                  int
    distribution_valid: bool
    requires_retrain:   bool
    per_policy:         dict   # str → PolicyFinanceResult
    provenance:         FinanceProvenance


# ── Engine internals ──────────────────────────────────────────────────────────


def _validate_ensemble(ensemble: PolicyEnsemble) -> None:
    """Raise ValueError if the ensemble is ragged (CRN requirement §3.2)."""
    for pid, runs in ensemble.runs.items():
        if len(runs) != ensemble.M:
            raise ValueError(
                f"ragged ensemble: policy '{pid}' has {len(runs)} draws "
                f"but ensemble.M={ensemble.M}"
            )


def _build_annual_cf(
    traj: list[PolicyEvalResult],
    price_path: PricePath,
    econ: DeviceEconParams,
    config: FinanceConfig,
) -> list[float]:
    """Build full CF [CAPEX_yr0, yr1, …, yrN] for one draw, with price path and tax.

    CF(y) = EBITDA(y) − Tax(y) − Replacement(y);  CF(N) adds Terminal
    Revenue streams are scaled by price_path.multipliers (INV-FINLAYER).
    Tax (straight-line depreciation) applied when config.tax_toggle=True.
    Replacement CAPEX fires at first-to-fire(calendar, throughput) years (§13.6).
    Terminal = residual_value − decommissioning at year N.
    """
    N = len(traj)
    annual: list[float] = []
    dep = econ.total_capex_yuan / max(1, config.depreciation_years) if config.tax_toggle else 0.0

    # Lifecycle events: compute once per trajectory
    repl_years, repl_capex, terminal_val = _eol_events(traj, econ)

    for y_idx, yr in enumerate(traj):
        year = y_idx + 1  # 1-indexed

        # ── Revenue streams (inflows) ────────────────────────────────────────
        gross_revenue = (
            yr.streams["grid_export"].value_yuan
            + yr.streams["h2_sale"].value_yuan
            + yr.streams["avoided_cost"].value_yuan
            + yr.streams["token_sale"].value_yuan
        )
        # ── Cost streams (outflows) ──────────────────────────────────────────
        stream_cost = (
            yr.streams["grid_import"].value_yuan
            + yr.streams["demand_charge"].value_yuan
        )

        # Apply price-path multiplier to revenue (INV-FINLAYER)
        m = get_multiplier(price_path, y_idx)
        scaled_revenue = m * gross_revenue

        # EBITDA
        ebitda = (
            scaled_revenue
            - stream_cost
            - econ.fixed_om_yuan_per_yr
            - econ.var_om_yuan_per_mwh * yr.generation_mwh
            - econ.asset_mgmt_yuan_per_yr
        )

        # Tax on EBITDA (straight-line depreciation, no negative tax)
        # Tax is computed BEFORE replacement (replacement CAPEX is not expensed against revenue)
        if config.tax_toggle:
            taxable = max(0.0, ebitda - dep)
            ebitda -= config.tax_rate * taxable

        # Lifecycle: replacement CAPEX at EOL year (INV-DEG §3.6 cash half)
        # degradation_yuan is NOT subtracted — it is a memo-only wear signal.
        if year in repl_years:
            ebitda -= repl_capex

        # Lifecycle: terminal value at horizon N (residual − decommissioning)
        if year == N:
            ebitda += terminal_val

        annual.append(ebitda)

    return [-econ.total_capex_yuan] + annual


def _cf_costs_and_energy(
    traj: list[PolicyEvalResult],
    econ: DeviceEconParams,
) -> tuple[list[float], list[float], list[float]]:
    """Extract cost-only CF and energy/storage vectors for LCOE/LCOS.

    Sign convention (per lcoe() docstring §13.8 literal):
      cf_costs[t] < 0  →  cost (CAPEX, O&M, replacement CAPEX)
      cf_costs[t] > 0  →  credit (residual/scrap value at horizon N)

    Decommissioning is NOT included in cf_costs: it enters the NPV cash flow
    (via _build_annual_cf terminal_val) but is excluded from LCOE numerator
    per §13.8 literal ("LCOE = PV(CAPEX + OM + Replacement − Residual) / PV(E_net)").
    """
    N = len(traj)
    repl_years, repl_capex, _ = _eol_events(traj, econ)   # terminal_val NOT in LCOE

    cf_costs = [-econ.total_capex_yuan]
    e_gen: list[float] = [0.0]
    e_discharge: list[float] = [0.0]

    for y_idx, yr in enumerate(traj):
        year = y_idx + 1
        cost = -econ.fixed_om_yuan_per_yr - econ.var_om_yuan_per_mwh * yr.generation_mwh

        # Replacement CAPEX at EOL year (cost, negative)
        if year in repl_years:
            cost -= repl_capex

        # Residual value credit at year N (positive → reduces PV(costs) in lcoe())
        # Decommissioning is deliberately excluded (NPV-only, not LCOE)
        if year == N:
            residual_value = econ.total_capex_yuan * econ.residual_value_fraction
            cost += residual_value

        cf_costs.append(cost)
        e_gen.append(yr.generation_mwh)
        e_discharge.append(yr.bat_discharge_mwh)

    return cf_costs, e_gen, e_discharge


def _bootstrap_ci(
    values: np.ndarray,
    q: float,
    seed: int,
    B: int = 2000,
    ci_level: float = 0.90,
) -> tuple[float, float]:
    """Bootstrap CI for exceedance_percentile(q) via resampling.

    FIN-35: same seed → identical CI (determinism).
    FIN-45: degenerate (all values equal) → CI width = 0.
    """
    rng = np.random.default_rng(seed)
    M = len(values)
    boot_stats = np.empty(B, dtype=float)
    for i in range(B):
        resample = rng.choice(values, size=M, replace=True)
        boot_stats[i] = exceedance_percentile(resample, q, higher_is_better=True)
    alpha = (1.0 - ci_level) / 2.0
    lo = float(np.quantile(boot_stats, alpha))
    hi = float(np.quantile(boot_stats, 1.0 - alpha))
    return (lo, hi)


def _compute_percentile_row(
    q: float,
    npv_arr: np.ndarray,
    irr_arr: np.ndarray,
    mirr_arr: np.ndarray,
    lcoe_arr: np.ndarray,
    lcos_arr: np.ndarray,
    pb_simple_arr: np.ndarray,
    pb_disc_arr: np.ndarray,
    bootstrap_seed: int,
    bootstrap_n: int,
    bootstrap_ci_level: float,
    confidence: str = "sound",
) -> PercentileResult:
    return PercentileResult(
        npv_yuan          = exceedance_percentile(npv_arr,       q),
        irr               = exceedance_percentile(irr_arr,       q),
        mirr              = exceedance_percentile(mirr_arr,      q),
        lcoe_yuan_per_mwh = exceedance_percentile(lcoe_arr,      q, higher_is_better=False),
        lcos_yuan_per_mwh = exceedance_percentile(lcos_arr,      q, higher_is_better=False),
        payback_simple_yr = exceedance_percentile(pb_simple_arr, q, higher_is_better=False),
        payback_disc_yr   = exceedance_percentile(pb_disc_arr,   q, higher_is_better=False),
        bootstrap_ci      = _bootstrap_ci(npv_arr, q, bootstrap_seed, bootstrap_n, bootstrap_ci_level),
        confidence        = confidence,
    )


def _make_view(
    npv_arr: np.ndarray,
    irr_arr: np.ndarray,
    mirr_arr: np.ndarray,
    lcoe_arr: np.ndarray,
    lcos_arr: np.ndarray,
    pb_simple_arr: np.ndarray,
    pb_disc_arr: np.ndarray,
    all_annual_cfs: list[list[float]],
    distribution_valid: bool,
    config: FinanceConfig,
    wacc_info: dict,
    equity_irr_val: "float | None",
    min_dscr_val: "float | None",
) -> ViewResult:
    """Build one ViewResult (View I or delta-View II) from per-draw metric arrays."""
    M = len(npv_arr)

    # ── Single trajectory (always present, use draw m=0) ─────────────────────
    m0_annual = all_annual_cfs[0][1:]  # strip year-0 CAPEX
    dd = max_drawdown(m0_annual)
    wc = worst_year_cf(m0_annual)
    st = SingleTrajectoryResult(
        point_npv_yuan   = float(npv_arr[0]),
        max_drawdown_yuan= dd["drawdown_yuan"],
        max_drawdown_year= dd["drawdown_year"],
        worst_year_cf_yuan=wc["worst_cf_yuan"],
    )

    if not distribution_valid:
        return ViewResult(
            single_trajectory = st,
            equity_irr        = equity_irr_val,
            min_dscr          = min_dscr_val,
        )

    # ── Distributional percentiles (R2: M≥50, bootstrap) ─────────────────────
    seed = config.bootstrap_seed
    n_res = config.bootstrap_n_resamples
    ci_lvl = config.bootstrap_ci_level

    def _prow(q, confidence="sound"):
        return _compute_percentile_row(
            q, npv_arr, irr_arr, mirr_arr, lcoe_arr, lcos_arr,
            pb_simple_arr, pb_disc_arr, seed, n_res, ci_lvl, confidence,
        )

    hurdle = wacc_info["hurdle_rate"]

    # ── Downside risk ─────────────────────────────────────────────────────────
    # worst-case draw for max_drawdown across all M draws
    # (contract says "min_y cumCF_excl_CAPEX per §13.10b" — use worst draw's single-draw value)
    # For the downside panel we aggregate over all draws
    all_annual_worst_draws = [cfs[1:] for cfs in all_annual_cfs]  # strip CAPEX
    # max_drawdown of each draw individually
    dd_vals = [max_drawdown(a)["drawdown_yuan"] for a in all_annual_worst_draws]
    dd_years = [max_drawdown(a)["drawdown_year"] for a in all_annual_worst_draws]
    worst_dd_idx = int(np.argmin(dd_vals))
    worst_yr_vals = [worst_year_cf(a)["worst_cf_yuan"] for a in all_annual_worst_draws]

    dr = DownsideRisk(
        worst_case_npv_yuan  = float(np.min(npv_arr)),
        p_npv_neg            = p_below(npv_arr, 0.0),
        p_irr_below_hurdle   = p_below(irr_arr, hurdle),
        cvar5_yuan           = cvar5(npv_arr, M),
        max_drawdown_yuan    = dd_vals[worst_dd_idx],
        max_drawdown_year    = dd_years[worst_dd_idx],
        worst_year_cf_yuan   = float(np.min(worst_yr_vals)),
    )

    return ViewResult(
        single_trajectory = st,
        P50  = _prow(0.50),
        P75  = _prow(0.75),
        P90  = _prow(0.90),
        P95  = _prow(0.95),
        P99  = _prow(0.99, confidence="indicative_low_confidence"),
        downside_risk = dr,
        equity_irr    = equity_irr_val,
        min_dscr      = min_dscr_val,
    )


# ── Public entry point ────────────────────────────────────────────────────────


def finance(
    ensemble:       PolicyEnsemble,
    price_paths:    list[PricePath],
    econ:           DeviceEconParams,
    finance_config: FinanceConfig,
) -> FinanceResult:
    """Pure finance engine entry point (§13.12).

    Consumes an already-dispatched PolicyEnsemble and produces NPV/IRR/MIRR/
    LCOE/LCOS/payback distributions, downside-risk panel, bootstrap CIs, and
    sensitivity surfaces.

    Invariants enforced:
    - Purity: no I/O, no network, no filesystem, no clock (FIN-37).
    - CRN: ragged ensembles (|runs[π]| ≠ M) → ValueError (FIN-39).
    - View II: only when baseline_policy_id ∈ ensemble.runs.keys() (FIN-41/42).
    - M=1 honesty: distributional fields absent; m1_banner=True (FIN-28–31).
    - Debt-gating: equity_irr / min_dscr absent (None) when debt_toggle=False (FIN-14).
    - INV-STREAM-AUTHORITY: EBITDA from streams only (FIN-23b).
    """
    # 1. Validate
    _validate_ensemble(ensemble)

    # 2. Discount params
    wacc_info = compute_wacc(finance_config)
    r = wacc_info["wacc"]          # discount rate for NPV
    hurdle = wacc_info["hurdle_rate"]

    # 3. Regime flags
    M = ensemble.M
    distribution_valid = (M >= 50 and ensemble.sample_kind == "bootstrap")
    requires_retrain = any_nonuniform(price_paths)

    # 4. Debt parameters (computed once, same for all policies)
    r_d = wacc_info["r_d"]
    de_ratio = finance_config.target_de_ratio if finance_config.debt_toggle else 0.0
    if finance_config.debt_toggle and de_ratio > 0:
        debt_frac = de_ratio / (1.0 + de_ratio)
        equity_frac = 1.0 / (1.0 + de_ratio)
        loan_n = finance_config.loan_term_years
        total_debt = econ.total_capex_yuan * debt_frac
        equity_invested = econ.total_capex_yuan * equity_frac
        # Level-annuity debt service: A = P·r·(1+r)^n / ((1+r)^n − 1)
        r_d_pow_n = (1.0 + r_d) ** loan_n
        annuity = total_debt * (r_d * r_d_pow_n) / (r_d_pow_n - 1.0)
    else:
        total_debt = 0.0
        equity_invested = econ.total_capex_yuan
        annuity = 0.0

    # 5. Per-policy, per-price-path computation
    per_policy: dict[str, PolicyFinanceResult] = {}
    # Accumulate baseline NPVs for View II (keyed by (price_path.id, draw_index))
    baseline_npvs: dict[str, np.ndarray] = {}  # pp_id → [npv_m …]

    # First pass: compute all NPV arrays (needed for View II delta)
    policy_npv_arrays: dict[str, dict[str, np.ndarray]] = {}  # pid → pp_id → arr

    for policy_id, runs in ensemble.runs.items():
        policy_npv_arrays[policy_id] = {}
        for pp in price_paths:
            npv_arr_m = np.empty(M, dtype=float)
            for m, traj in enumerate(runs):
                cf = _build_annual_cf(traj, pp, econ, finance_config)
                npv_arr_m[m] = npv(cf, r)
            policy_npv_arrays[policy_id][pp.id] = npv_arr_m

    # Cache baseline NPV arrays
    baseline_id = finance_config.baseline_policy_id
    if baseline_id and baseline_id in policy_npv_arrays:
        baseline_npvs = policy_npv_arrays[baseline_id]

    # Second pass: full metrics per policy / price path
    for policy_id, runs in ensemble.runs.items():
        pp_results: dict[str, PricePathResult] = {}

        for pp in price_paths:
            # Arrays over M draws
            npv_arr        = np.empty(M, dtype=float)
            irr_arr        = np.empty(M, dtype=float)
            mirr_arr       = np.empty(M, dtype=float)
            lcoe_arr       = np.empty(M, dtype=float)
            lcos_arr       = np.empty(M, dtype=float)
            pb_simple_arr  = np.empty(M, dtype=float)
            pb_disc_arr    = np.empty(M, dtype=float)
            all_cfs: list[list[float]] = []

            # Debt metrics (per draw)
            eq_irr_arr  = np.empty(M, dtype=float) if finance_config.debt_toggle else None
            dscr_min_arr = np.empty(M, dtype=float) if finance_config.debt_toggle else None

            for m, traj in enumerate(runs):
                cf = _build_annual_cf(traj, pp, econ, finance_config)
                all_cfs.append(cf)

                npv_arr[m]       = npv(cf, r)
                irr_arr[m]       = irr(cf)
                mirr_arr[m]      = mirr(cf, r, r)
                pb_simple_arr[m] = payback_simple(cf)
                pb_disc_arr[m]   = payback_discounted(cf, r)

                # LCOE/LCOS cost vectors (no revenue; no tax applied to cost-only)
                cf_costs, e_gen, e_dis = _cf_costs_and_energy(traj, econ)
                lcoe_arr[m] = lcoe(cf_costs, e_gen, r)
                lcos_arr[m] = lcos(cf_costs, e_dis, r)

                # Debt metrics
                if finance_config.debt_toggle and annuity > 0:
                    # Re-derive pre-tax EBITDA (CFADS) directly from streams.
                    # Use year index for price-path multiplier (not identity check).
                    ebitda_series = []
                    for y_idx, yr in enumerate(traj):
                        rev = (
                            yr.streams["grid_export"].value_yuan
                            + yr.streams["h2_sale"].value_yuan
                            + yr.streams["avoided_cost"].value_yuan
                            + yr.streams["token_sale"].value_yuan
                        )
                        cost = (
                            yr.streams["grid_import"].value_yuan
                            + yr.streams["demand_charge"].value_yuan
                        )
                        pp_mult = get_multiplier(pp, y_idx)
                        ebitda_y = (pp_mult * rev - cost
                                    - econ.fixed_om_yuan_per_yr
                                    - econ.var_om_yuan_per_mwh * yr.generation_mwh
                                    - econ.asset_mgmt_yuan_per_yr)
                        ebitda_series.append(ebitda_y)
                    n_svc = min(finance_config.loan_term_years, len(ebitda_series))
                    dscr_res = dscr(ebitda_series[:n_svc], [annuity] * n_svc)
                    dscr_min_arr[m] = dscr_res["min_dscr"]

                    # Equity IRR: CF_eq[0]=-equity; CF_eq[y]=EBITDA−annuity
                    cf_eq = [-equity_invested] + [e - annuity for e in ebitda_series]
                    eq_irr_arr[m] = irr(cf_eq)

            # ── View I ────────────────────────────────────────────────────────
            # For debt fields: use average (or m=0 for M=1)
            if finance_config.debt_toggle:
                equity_irr_val: "float | None" = float(np.mean(eq_irr_arr))
                min_dscr_val: "float | None" = float(np.mean(dscr_min_arr))
            else:
                equity_irr_val = None
                min_dscr_val = None

            view_i = _make_view(
                npv_arr, irr_arr, mirr_arr, lcoe_arr, lcos_arr,
                pb_simple_arr, pb_disc_arr, all_cfs,
                distribution_valid, finance_config, wacc_info,
                equity_irr_val, min_dscr_val,
            )

            # ── View II ───────────────────────────────────────────────────────
            view_ii: "ViewResult | None" = None
            if (baseline_id and baseline_id in policy_npv_arrays
                    and policy_id != baseline_id):
                base_npv = baseline_npvs.get(pp.id)
                if base_npv is not None:
                    delta_npv = npv_arr - base_npv
                    # Build stub ViewResult for View II (delta NPV only)
                    delta_arr = delta_npv
                    d_st = SingleTrajectoryResult(
                        point_npv_yuan    = float(delta_arr[0]),
                        max_drawdown_yuan = 0.0,
                        max_drawdown_year = 1,
                        worst_year_cf_yuan= 0.0,
                    )
                    if distribution_valid:
                        view_ii = ViewResult(
                            single_trajectory = d_st,
                            P50 = PercentileResult(
                                npv_yuan          = exceedance_percentile(delta_arr, 0.50),
                                irr               = 0.0,
                                mirr              = 0.0,
                                lcoe_yuan_per_mwh = 0.0,
                                lcos_yuan_per_mwh = 0.0,
                                payback_simple_yr = 0.0,
                                payback_disc_yr   = 0.0,
                                bootstrap_ci      = (0.0, 0.0),
                                confidence        = "sound",
                            ),
                        )
                    else:
                        view_ii = ViewResult(single_trajectory=d_st)

            # ── Cash flow series for UI ───────────────────────────────────────
            cfs_matrix = [cf[1:] for cf in all_cfs]  # [m][y] pre-price-path ¥

            # ── NPV-vs-r curve (use m=0 CF) ───────────────────────────────────
            r_curve = npv_vs_r_curve(all_cfs[0])

            pp_results[pp.id] = PricePathResult(
                view_i           = view_i,
                view_ii          = view_ii,
                cash_flow_series = cfs_matrix,
                npv_vs_r_curve   = r_curve,
                sensitivity_surface = compute_sensitivity_surface(all_cfs[0], r),
            )

        per_policy[policy_id] = PolicyFinanceResult(per_price_path=pp_results)

    # 6. Provenance
    provenance = FinanceProvenance(
        seed          = ensemble.seed,
        M             = M,
        sample_kind   = ensemble.sample_kind,
        valuation_date= finance_config.valuation_date,
        r_f           = wacc_info["r_f"],
        r_f_tenor_yr  = wacc_info["r_f_tenor_yr"],
        r_f_curve_date= wacc_info["r_f_curve_date"],
        r_e           = wacc_info["r_e"],
        wacc          = wacc_info["wacc"],
        beta_levered  = wacc_info["beta_levered"],
        scenario_id   = f"finance-{ensemble.seed}-{M}-{finance_config.valuation_date}",
        code_version  = _CODE_VERSION,
        price_path_ids= [pp.id for pp in price_paths],
        m1_banner     = (M == 1),
    )

    return FinanceResult(
        M                 = M,
        distribution_valid= distribution_valid,
        requires_retrain  = requires_retrain,
        per_policy        = per_policy,
        provenance        = provenance,
    )
