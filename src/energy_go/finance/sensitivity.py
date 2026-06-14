"""Sensitivity analysis for the Energy GO finance engine.

Provides:
  npv_vs_r_curve: NPV computed at a range of discount rates
  compute_sensitivity_surface: placeholder (§13.11 shape TBD with backend-reviewer)

No I/O. Units: ¥, decimal rates.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from energy_go.finance.metrics import npv


# Default discount-rate sweep for the NPV-vs-r fan chart
_R_SWEEP = [round(r, 4) for r in np.arange(0.0, 0.51, 0.025).tolist()]


def npv_vs_r_curve(
    cf: Sequence[float],
    r_values: Sequence[float] | None = None,
) -> list[tuple[float, float]]:
    """Compute (r, NPV) pairs for a range of discount rates.

    Args:
        cf:       full cash-flow series [CAPEX, yr1, …, yrN]
        r_values: discount rates to evaluate (default: 0% to 50% in 2.5% steps)

    Returns: list of (r, npv_yuan) tuples
    """
    if r_values is None:
        r_values = _R_SWEEP
    return [(r, npv(cf, r)) for r in r_values]


def compute_sensitivity_surface(
    cf: Sequence[float],
    r: float,
) -> dict:
    """Sensitivity surface (§13.11). Shape TBD with backend-reviewer.

    Returns an empty dict as a placeholder; the full tornado / surface
    will be added when the /api/finance/compare contract is finalized.
    """
    return {}
