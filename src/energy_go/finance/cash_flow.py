"""D13 → cash-flow mapping for the Energy GO finance engine.

Entry point: build_cash_flow_series()

INV-STREAM-AUTHORITY (§3.5a, D39):
  Operating cash is built from the 6 stream accumulators ONLY (streams[*].value_yuan).
  real_money.energy_cost_yuan, .demand_charge_yuan, .total_cost_yuan are
  NON-ADDITIVE reconciliation VIEWS and MUST NOT enter EBITDA.

INV-BASIS (§3.0/§3.2):
  penalty_yuan, soc_violation_mwh, soc_violations_count are structurally
  unreachable — this module never touches them.

Units: ¥ (yuan), MWh.
"""

from __future__ import annotations

from typing import Sequence

from energy_go.training.eval import PolicyEvalResult


def build_cash_flow_series(
    eval_results: Sequence[PolicyEvalResult],
    *,
    capex_yuan: float = 0.0,
    fixed_om_yuan: float = 0.0,
    var_om_yuan_per_mwh: float = 0.0,
    asset_mgmt_yuan: float = 0.0,
    include_degradation_as_cash: bool = False,
    curtailment_penalty_contract: bool = False,
    reliability_penalty_contract: bool = False,
) -> list[float]:
    """Build CF series [cf[0], cf[1], …, cf[N]] from a policy trajectory.

    cf[0] = -capex_yuan  (year-0 CAPEX, always ≤ 0)
    cf[y] = EBITDA(y)   for y = 1 … N  (one entry per PolicyEvalResult)

    EBITDA is assembled ONLY from streams (INV-STREAM-AUTHORITY):
      revenue = grid_export + h2_sale + avoided_cost + token_sale
      cost    = grid_import + demand_charge
      EBITDA  = revenue - cost - FixedOM - VarOM·MWh - AssetMgmt

    Optional real_money cash items (controlled by flags):
      degradation_yuan: NOT period cash by default (INV-DEG §3.6); include if flag=True
      curtailment_yuan: NOT cash unless curtailment_penalty_contract=True (INV-CURT §3.7)
      voll_yuan:        NOT cash unless reliability_penalty_contract=True  (INV-VOLL §3.8)

    Args:
        eval_results: one PolicyEvalResult per operating year (N entries)
        capex_yuan:   year-0 capital expenditure in ¥ (default 0)
        fixed_om_yuan: annual fixed O&M cost in ¥/yr (default 0)
        var_om_yuan_per_mwh: variable O&M in ¥/MWh of generation (default 0)
        asset_mgmt_yuan: annual asset-management fee in ¥/yr (default 0)
        include_degradation_as_cash: False (default) = INV-DEG applies
        curtailment_penalty_contract: True = curtailment_yuan enters cash
        reliability_penalty_contract: True = voll_yuan enters cash

    Returns: list of length N+1: [cf_yr0, cf_yr1, …, cf_yrN]
    """
    cf: list[float] = [-capex_yuan]  # year-0

    for yr in eval_results:
        # ── Revenue streams (inflows; value_yuan ≥ 0) ──────────────────────
        revenue = (
            yr.streams["grid_export"].value_yuan
            + yr.streams["h2_sale"].value_yuan
            + yr.streams["avoided_cost"].value_yuan
            + yr.streams["token_sale"].value_yuan
        )

        # ── Cost streams (outflows; value_yuan ≥ 0) ────────────────────────
        # NOTE: energy_cost_yuan and demand_charge_yuan from real_money are
        # non-additive views of these same streams; they are NOT read here.
        # (INV-STREAM-AUTHORITY §3.5a)
        stream_cost = (
            yr.streams["grid_import"].value_yuan
            + yr.streams["demand_charge"].value_yuan
        )

        # ── EBITDA (stream-net minus O&M) ──────────────────────────────────
        ebitda = (
            revenue
            - stream_cost
            - fixed_om_yuan
            - var_om_yuan_per_mwh * yr.generation_mwh
            - asset_mgmt_yuan
        )

        # ── Optional real_money cash items ─────────────────────────────────
        if include_degradation_as_cash:   # INV-DEG §3.6 default: False
            ebitda -= yr.degradation_yuan
        if curtailment_penalty_contract:  # INV-CURT §3.7 default: False
            ebitda -= yr.curtailment_yuan
        if reliability_penalty_contract:  # INV-VOLL §3.8 default: False
            ebitda -= yr.voll_yuan

        cf.append(ebitda)

    return cf
