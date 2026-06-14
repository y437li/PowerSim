"""M-axis distribution functions for the finance engine.

LOCKED estimator (D39, PR #107 §A):
  exceedance_percentile: np.quantile(sorted_ascending, 1-q, method='lower')
  for higher-is-better metrics (NPV, IRR, MIRR, …).

All functions are pure (no I/O, no global state).
Units: ¥ (yuan), decimal rates.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np


# ── LOCKED estimator (D39) ────────────────────────────────────────────────────


def exceedance_percentile(
    arr: Sequence[float],
    q: float,
    *,
    higher_is_better: bool = True,
) -> float:
    """P-q exceedance percentile of a metric distribution.

    "P-q exceedance" means: in at least q·100% of scenarios the metric ≥ result.

    LOCKED estimator (D39/§A, one estimator for R2 and R3):
      higher_is_better (NPV, IRR, …):
        np.quantile(sorted_ascending, 1-q, method='lower')
      lower_is_better (cost, risk metric):
        np.quantile(sorted_ascending, q, method='higher')

    PR #107 §A verification:
      M=50, NPV_m = -100k + (m-1)·10k, m=1…50 (ascending):
      P50: np.quantile(arr, 0.50, method='lower') → index floor(0.50·49)=24 → 140k  ✓
      P75: np.quantile(arr, 0.25, method='lower') → index floor(0.25·49)=12 → 20k   ✓
      P90: np.quantile(arr, 0.10, method='lower') → index floor(0.10·49)=4  → -60k  ✓
      P95: np.quantile(arr, 0.05, method='lower') → index floor(0.05·49)=2  → -80k  ✓
    """
    a = np.sort(np.asarray(arr, dtype=float))
    if higher_is_better:
        return float(np.quantile(a, 1.0 - q, method="lower"))
    else:
        return float(np.quantile(a, q, method="higher"))


# ── Downside statistics ───────────────────────────────────────────────────────


def cvar5(arr: Sequence[float], M: int) -> float:
    """Conditional Value at Risk at 5% (mean of worst k draws).

    k = ceil(0.05 · M)

    FIN-18: M=50 → k=ceil(2.5)=3; worst 3 of [-100k,…] = mean(-100k,-90k,-80k) = -90k  ✓
    FIN-54: M=20 → k=ceil(1.0)=1; CVaR = -10k  ✓
    FIN-54: M=40 → k=ceil(2.0)=2; CVaR = mean(-20k,-19k) = -19.5k  ✓
    """
    k = math.ceil(0.05 * M)
    sorted_arr = np.sort(np.asarray(arr, dtype=float))  # ascending; worst first
    return float(np.mean(sorted_arr[:k]))


def p_below(arr: Sequence[float], threshold: float) -> float:
    """Fraction of draws strictly below threshold.

    FIN-16: threshold=0 → P(NPV<0) = 10/50 = 0.20  ✓
    FIN-17: threshold=0.10 → P(IRR<hurdle=0.10) = 12/50 = 0.24  ✓

    Note: strictly less-than (< not ≤); FIN-16 confirms NPV=0 is NOT counted.
    """
    a = np.asarray(arr, dtype=float)
    return float(np.sum(a < threshold) / len(a))


def max_drawdown(cf: Sequence[float]) -> dict:
    """Shortfall-below-zero maximum cumulative drawdown.

    Takes the ANNUAL CF series (year-0 CAPEX excluded). Cumsums internally.
    Formula (LOCKED §13.10b): drawdown = min(0, min(cumsum(cf)))

    FIN-22b: cf=[100k,-150k,-250k,180k,320k]
      cumCF=[100k,-50k,-300k,-120k,200k]; min(0,-300k)=-300k @ yr3 ✓

    FIN-53: cf=[100k,50k,200k]
      cumCF=[100k,150k,350k]; min(0,100k)=0.0 (no shortfall) ✓

    Returns {"drawdown_yuan": float, "drawdown_year": int (1-indexed argmin)}
    """
    cf_arr = np.asarray(cf, dtype=float)
    cum = np.cumsum(cf_arr)
    min_val = float(np.min(cum))
    drawdown = min(0.0, min_val)
    # argmin year is 1-indexed
    year = int(np.argmin(cum)) + 1
    return {"drawdown_yuan": drawdown, "drawdown_year": year}


def worst_year_cf(cf: Sequence[float]) -> dict:
    """Worst single-year cash flow (minimum annual CF, year-0 CAPEX excluded).

    FIN-22c: cf=[100k,-150k,-250k,180k,320k]; min=-250k at year 3 ✓

    Returns {"worst_cf_yuan": float, "worst_cf_year": int (1-indexed)}
    """
    cf_arr = np.asarray(cf, dtype=float)
    idx = int(np.argmin(cf_arr))
    return {"worst_cf_yuan": float(cf_arr[idx]), "worst_cf_year": idx + 1}
