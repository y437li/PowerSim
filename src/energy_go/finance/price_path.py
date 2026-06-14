"""Price-path utilities for the Energy GO finance engine.

A PricePath is a deterministic per-year revenue multiplier vector (§13.4 / D31/F1).
Post-hoc application: revenue_s(y) = m[y] · Σ_t q_{s,t}·p_{s,t}

INV-FINLAYER (§3.9): non-uniform paths set requires_retrain=True because they
change the dispatch economics (the policy was optimised for a different tariff).

No I/O. Units: dimensionless multipliers, ¥.
"""

from __future__ import annotations

from typing import Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from energy_go.finance.engine import PricePath


def is_uniform(price_path: "PricePath") -> bool:
    """Return True iff all multipliers == 1.0 (constant-real, D31/F1).

    FIN-27: [1.0, 1.0] → uniform; [1.0, 0.8] → non-uniform.
    """
    return all(m == 1.0 for m in price_path.multipliers)


def any_nonuniform(price_paths: Sequence["PricePath"]) -> bool:
    """Return True iff ANY price path in the list is non-uniform.

    Used to set FinanceResult.requires_retrain (INV-FINLAYER §3.9).
    """
    return any(not is_uniform(pp) for pp in price_paths)


def get_multiplier(price_path: "PricePath", year_idx: int) -> float:
    """Get the multiplier for year index `year_idx` (0-based, year 1 = index 0).

    Clamps to the last multiplier if year_idx >= len(multipliers).
    """
    mults = price_path.multipliers
    if year_idx < len(mults):
        return mults[year_idx]
    return mults[-1]
