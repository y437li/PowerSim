"""CAPM → r_e → WACC computation for the Energy GO finance engine.

Single entry point: compute_wacc(config) → dict

No I/O; no JAX — pure Python / arithmetic. (finance() purity §3.1)

References: §13.5, PR #107 Vector 0.
Units: decimal rates (e.g. 0.10 = 10%); years for tenor.

Vector 0 reference (PR #107):
  CGB: 10yr=0.020, 30yr=0.026 → r_f @20yr = 0.0230 (linear interp)
  All-equity (D/E=0): β_L=0.60, r_e=0.0590, WACC=0.0590
  Levered (D/E=1.5, r_d=LPR_5yr+125bps=0.0475, tax=0.25):
    β_L=1.275, r_e=0.0995, WACC=0.061175
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from energy_go.finance.engine import FinanceConfig


def _cgb_interpolate(points: dict[int, float], tenor_yr: int) -> float:
    """Linear-interpolate CGB yield at a given tenor (years).

    Clamps to nearest endpoint if tenor_yr is outside the curve range.

    FIN-00a: r_f = 0.020 + (0.026−0.020)·(20−10)/(30−10) = 0.0230  ✓
    """
    sorted_tenors = sorted(points.keys())
    if not sorted_tenors:
        raise ValueError("CGB curve has no points")
    if tenor_yr <= sorted_tenors[0]:
        return points[sorted_tenors[0]]
    if tenor_yr >= sorted_tenors[-1]:
        return points[sorted_tenors[-1]]
    for i in range(len(sorted_tenors) - 1):
        t_lo, t_hi = sorted_tenors[i], sorted_tenors[i + 1]
        if t_lo <= tenor_yr <= t_hi:
            y_lo = points[t_lo]
            y_hi = points[t_hi]
            frac = (tenor_yr - t_lo) / (t_hi - t_lo)
            return y_lo + frac * (y_hi - y_lo)
    return points[sorted_tenors[-1]]


def compute_wacc(config: "FinanceConfig") -> dict:
    """Compute discount rates from FinanceConfig.

    Returns a dict with:
      r_f             — risk-free rate (decimal)
      r_f_tenor_yr    — tenor matched (years)
      r_f_curve_date  — date the CGB curve was snapshotted
      beta_levered    — Hamada-relevered β
      r_e             — CAPM cost of equity (levered if debt on, else unlevered)
      wacc            — WACC (= r_e when all-equity)
      r_d             — cost of debt (decimal); 0.0 when debt off
      hurdle_rate     — P(IRR < hurdle) threshold; default = unlevered r_e (CAPM base)

    Formulas:
      β_L   = β_U · (1 + (1−t) · D/E)         (Hamada)
      r_e   = r_f + β_L · (ERP + CRP)          (CAPM)
      WACC  = (E/V)·r_e + (D/V)·r_d·(1−t)     (Miles–Ezzell variant)
      hurdle = r_f + β_U · (ERP + CRP)         (unlevered base, constant)
    """
    horizon = config.horizon_years

    # ── Risk-free rate ────────────────────────────────────────────────────────
    if config.r_f_override is not None:
        r_f = config.r_f_override
        r_f_tenor_yr = horizon
        r_f_curve_date = config.valuation_date
    elif config.cgb_curve is not None:
        curve = config.cgb_curve
        r_f = _cgb_interpolate(curve.points, horizon)
        r_f_tenor_yr = horizon
        r_f_curve_date = curve.snapshot_date
    else:
        raise ValueError(
            "FinanceConfig must provide either r_f_override or cgb_curve "
            "(no risk-free rate source)"
        )

    # ── Cost of debt ──────────────────────────────────────────────────────────
    if config.r_d_override is not None:
        r_d = config.r_d_override
    elif config.cgb_curve is not None:
        r_d = config.cgb_curve.lpr_5yr + config.credit_spread
    else:
        # Fallback: r_f plus credit spread (only reachable when r_f_override set)
        r_d = r_f + config.credit_spread

    # ── Levered beta (Hamada equation) ───────────────────────────────────────
    # Use target D/E only when debt is toggled on
    de_ratio = config.target_de_ratio if config.debt_toggle else 0.0
    beta_levered = config.beta_unlevered * (1.0 + (1.0 - config.tax_rate) * de_ratio)

    # ── Cost of equity (levered) ──────────────────────────────────────────────
    erp_crp = config.equity_risk_premium + config.country_risk_premium
    r_e = r_f + beta_levered * erp_crp

    # ── WACC ──────────────────────────────────────────────────────────────────
    if config.debt_toggle and de_ratio > 0.0:
        e_frac = 1.0 / (1.0 + de_ratio)         # E/V
        d_frac = de_ratio / (1.0 + de_ratio)     # D/V
        wacc = e_frac * r_e + d_frac * r_d * (1.0 - config.tax_rate)
    else:
        wacc = r_e  # all-equity: WACC collapses to r_e

    # ── Hurdle rate (always unlevered CAPM base) ──────────────────────────────
    if config.hurdle_rate_override is not None:
        hurdle_rate = config.hurdle_rate_override
    else:
        # D/E=0 → β_L = β_U → hurdle = r_f + β_U·(ERP+CRP)
        hurdle_rate = r_f + config.beta_unlevered * erp_crp

    return {
        "r_f":            r_f,
        "r_f_tenor_yr":   r_f_tenor_yr,
        "r_f_curve_date": r_f_curve_date,
        "beta_levered":   beta_levered,
        "r_e":            r_e,
        "wacc":           wacc,
        "r_d":            r_d,
        "hurdle_rate":    hurdle_rate,
    }
