"""Scalar financial metrics for a single cash-flow series.

All functions operate on a plain Python list/array [cf[0], cf[1], ..., cf[N]]
where cf[0] = year-0 CAPEX (negative), cf[1..N] = annual operating cash flows.

No I/O; no JAX — pure NumPy + scipy. (finance() purity requirement §3.1)

References: §13.8, PR #107 Vectors 1–3.
Units: ¥ (yuan), ¥/MWh, years, decimal rates (e.g. 0.10 = 10%).
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def npv(cf: Sequence[float], rate: float) -> float:
    """Net Present Value.

    NPV = Σ_{t=0}^{N} cf[t] / (1+rate)^t

    Vector 1 check: cf=[-1M,600k,600k], rate=0.10
      = -1,000,000 + 545,454.55 + 495,867.77 = ¥41,322.31  ✓
    """
    total = 0.0
    r = 1.0 + rate
    factor = 1.0
    for c in cf:
        total += c / factor
        factor *= r
    return total


def _brentq(f, a: float, b: float, xtol: float = 1e-12, maxiter: int = 200) -> float:
    """Brent's root-finding method (no external dependencies).

    Requires f(a) and f(b) to have opposite signs.
    """
    fa, fb = f(a), f(b)
    if fa * fb > 0:
        raise ValueError(f"brentq: no sign change in [{a}, {b}]")
    if abs(fa) < abs(fb):
        a, b = b, a
        fa, fb = fb, fa
    c, fc = a, fa
    mflag = True
    s, fs = b, fb
    d = 0.0
    for _ in range(maxiter):
        if abs(b - a) < xtol:
            break
        if fa != fc and fb != fc:
            # Inverse quadratic interpolation
            s = (a * fb * fc / ((fa - fb) * (fa - fc))
                 + b * fa * fc / ((fb - fa) * (fb - fc))
                 + c * fa * fb / ((fc - fa) * (fc - fb)))
        else:
            s = b - fb * (b - a) / (fb - fa)

        cond1 = not ((3 * a + b) / 4 < s < b or b < s < (3 * a + b) / 4)
        cond2 = mflag and abs(s - b) >= abs(b - c) / 2
        cond3 = (not mflag) and abs(s - b) >= abs(c - d) / 2
        cond4 = mflag and abs(b - c) < xtol
        cond5 = (not mflag) and abs(c - d) < xtol
        if cond1 or cond2 or cond3 or cond4 or cond5:
            s = (a + b) / 2
            mflag = True
        else:
            mflag = False

        fs = f(s)
        d, c, fc = c, b, fb
        if fa * fs < 0:
            b, fb = s, fs
        else:
            a, fa = s, fs
        if abs(fa) < abs(fb):
            a, b = b, a
            fa, fb = fb, fa

    return b


def irr(cf: Sequence[float]) -> float:
    """Internal Rate of Return (no external dependencies — pure Python/NumPy).

    Finds r such that npv(cf, r) = 0 using Brent's method.

    Vector 1 check: cf=[-1M,600k,600k]
      Solves 600k·u + 600k·u² = 1M → IRR = 13.0662%  ✓
    Vector 3 equity check: cf=[-400k,277.3k,277.3k]
      IRR = 24.8565%  ✓
    """
    cf = list(cf)

    def _f(r: float) -> float:
        return npv(cf, r)

    lo, hi = -0.9999, 100.0

    try:
        f_lo = _f(lo)
        # Find a bracket with a sign change
        for hi_try in [100.0, 10.0, 5.0, 2.0, 1.0, 0.5]:
            f_hi = _f(hi_try)
            if f_lo * f_hi < 0:
                hi = hi_try
                break
        else:
            return float("nan")
        return float(_brentq(_f, lo, hi))
    except (ValueError, ZeroDivisionError):
        return float("nan")


def mirr(cf: Sequence[float], finance_rate: float, reinvest_rate: float) -> float:
    """Modified Internal Rate of Return.

    FV_pos = Σ_{t: cf[t]>0}  cf[t] · (1+reinvest_rate)^(N-t)
    PV_neg = Σ_{t: cf[t]<0} |cf[t]| / (1+finance_rate)^t
    MIRR   = (FV_pos / PV_neg)^(1/N) - 1

    Single-valued by construction (avoids the multi-IRR ambiguity of §4).

    Vector 1 check: cf=[-1M,600k,600k], N=2, r=0.10
      FV_pos = 600k·1.10 + 600k = 1,260,000
      PV_neg = 1,000,000
      MIRR = √(1.26) - 1 = 12.2497%  ✓

    FIN-55 multi-sign check: cf=[-1000,2500,-1560], N=2, r=0.10
      FV_pos = 2500·1.10^1 = 2,750
      PV_neg = 1000 + 1560/1.21 = 2,289.256
      MIRR = √(2750/2289.256) - 1 = 9.6022%  ✓
    """
    cf = list(cf)
    n = len(cf) - 1  # number of periods (year 1 … N)

    fv_pos = 0.0
    pv_neg = 0.0
    for t, c in enumerate(cf):
        if c > 0:
            fv_pos += c * (1.0 + reinvest_rate) ** (n - t)
        elif c < 0:
            pv_neg += (-c) / (1.0 + finance_rate) ** t

    if pv_neg == 0.0 or fv_pos == 0.0:
        return float("nan")
    return (fv_pos / pv_neg) ** (1.0 / n) - 1.0


def lcoe(
    cf_costs: Sequence[float],
    e_net: Sequence[float],
    rate: float,
) -> float:
    """Levelised Cost of Energy (¥/MWh).

    LCOE = PV(|costs|) / PV(energy)

    cf_costs: [cf[0], ..., cf[N]] where values are ≤ 0 (CAPEX + annual costs, sign-negative).
    e_net:    [0, e[1], ..., e[N]]  annual net generation in MWh; e[0] is typically 0.

    Vector 1 check: cf_costs=[-1M,-100k,-100k], e_net=[0,10k,10k], rate=0.10
      PV_costs = 1M + 100k/1.10 + 100k/1.21 = 1,173,553.72
      PV_energy = 10k/1.10 + 10k/1.21 = 17,355.37
      LCOE = 67.62 ¥/MWh  ✓
    """
    r = 1.0 + rate
    pv_costs = 0.0
    pv_energy = 0.0
    factor = 1.0
    for c, e in zip(cf_costs, e_net):
        pv_costs += abs(c) / factor
        pv_energy += e / factor
        factor *= r
    if pv_energy == 0.0:
        return float("inf")
    return pv_costs / pv_energy


def lcos(
    cf_costs: Sequence[float],
    e_storage: Sequence[float],
    rate: float,
) -> float:
    """Levelised Cost of Storage (¥/MWh discharged).

    Analogous to LCOE but with battery discharge as the denominator.
    Typically computed on the storage subsystem costs only; here we accept
    the caller's cost series as-is (consistent with the LCOE interface).

    cf_costs:  same sign convention as lcoe() (negative = cost)
    e_storage: [0, d[1], ..., d[N]]  annual discharge MWh
    """
    return lcoe(cf_costs, e_storage, rate)


def payback_simple(cf: Sequence[float]) -> float:
    """Simple payback period (years) — fractional.

    Vector 1 check: cf=[-1M,600k,600k]
      After yr1: cumCF = -400k; payback = 1 + 400k/600k = 1.66667 yr  ✓
    """
    cf = list(cf)
    invested = -cf[0]  # initial outlay (positive)
    cumulative = 0.0
    for t, c in enumerate(cf[1:], start=1):
        prev = cumulative
        cumulative += c
        if cumulative >= invested:
            # Linear interpolation in the recovery year
            remaining = invested - prev
            return float(t - 1) + remaining / c
    return float("inf")  # not recovered within horizon


def payback_discounted(cf: Sequence[float], rate: float) -> float:
    """Discounted payback period (years) — fractional.

    Cumulates PV-discounted CFs until ≥ 0 (recovering the CAPEX in present value).

    Vector 1 check: cf=[-1M,600k,600k], rate=0.10
      disc yr1 = 545,454.55 → cum = 545,454.55 < 1M
      remaining = 454,545.45
      disc yr2 = 495,867.77
      payback = 1 + 454,545.45/495,867.77 = 1.91667 yr  ✓
    """
    cf = list(cf)
    r = 1.0 + rate
    invested = -cf[0]
    cumulative = 0.0
    factor = r  # starts at (1+r)^1 for year 1
    for t, c in enumerate(cf[1:], start=1):
        prev = cumulative
        disc_c = c / factor
        cumulative += disc_c
        if cumulative >= invested:
            remaining = invested - prev
            return float(t - 1) + remaining / disc_c
        factor *= r
    return float("inf")


def dscr(
    cfads_series: Sequence[float],
    service_series: Sequence[float],
) -> dict:
    """Debt-Service Coverage Ratio per year and the minimum over the series.

    DSCR(y) = CFADS(y) / DebtService(y)

    Vector 3 check: CFADS=[600k,600k], service=[322,682.93, 322,682.93]
      DSCR = 1.8594 (level annuity → same both years)  ✓

    Returns: {"min_dscr": float, "dscr_series": list[float]}
    """
    series = [c / s for c, s in zip(cfads_series, service_series)]
    return {"min_dscr": float(min(series)), "dscr_series": series}
