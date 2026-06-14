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

from typing import TYPE_CHECKING, Sequence

from energy_go.training.eval import PolicyEvalResult

if TYPE_CHECKING:
    from energy_go.finance.econ_params import DeviceEconParams


def _eol_events(
    eval_results: Sequence[PolicyEvalResult],
    econ: "DeviceEconParams",
) -> tuple[set[int], float, float]:
    """Compute lifecycle end-of-life events from trajectory + econ params.

    Implements first-to-fire(calendar, throughput) per §13.6:
      t_replace = min(lifetime_years, first yr where cumsum(bat_throughput_mwh)
                                                    ≥ cycle_life_full_equiv × bat_capacity_mwh)

    Replacements fire at years 1 … N-1 only (year N = terminal — no replacement at final year).
    After each replacement the calendar and cycle counters reset.

    Returns:
        replacement_years:    set of 1-indexed years where replacement CAPEX fires
        replacement_capex_yuan: ¥ cost per replacement = total_capex × replacement_cost_fraction
        terminal_value_yuan:  ¥ net credit at year N = residual_value − decommissioning
                              (residual reduces LCOE cost; decommissioning enters NPV-only CF)
    """
    N = len(eval_results)
    replacement_capex = econ.total_capex_yuan * econ.replacement_cost_fraction
    residual_value = econ.total_capex_yuan * econ.residual_value_fraction
    terminal_value = residual_value - econ.decommissioning_yuan

    # No replacement if both limits absent
    if econ.lifetime_years <= 0 and econ.cycle_life_full_equiv <= 0:
        return set(), replacement_capex, terminal_value

    # Cycle limit (MWh): replacement fires when cumulative throughput reaches this
    if econ.cycle_life_full_equiv > 0 and econ.bat_capacity_mwh > 0:
        cycle_limit = econ.cycle_life_full_equiv * econ.bat_capacity_mwh
    else:
        cycle_limit = float("inf")  # no cycle limit → calendar-only

    # Calendar limit (years): replacement fires every lifetime_years years
    cal_limit = econ.lifetime_years if econ.lifetime_years > 0 else N + 1

    replacement_years: set[int] = set()
    current_start = 0    # 0-indexed base year; asset life measured from here
    cum_throughput = 0.0  # MWh since last replacement (or project start)

    for y_idx, yr in enumerate(eval_results):
        cum_throughput += yr.bat_throughput_mwh
        year = y_idx + 1  # 1-indexed
        years_since_start = year - current_start

        cycle_triggered = cum_throughput >= cycle_limit
        cal_triggered = years_since_start >= cal_limit

        if (cycle_triggered or cal_triggered) and year < N:
            # Replacement fires; do NOT fire at terminal year N (→ terminal value instead)
            replacement_years.add(year)
            current_start = year    # new asset life starts here
            cum_throughput = 0.0    # reset cycle-life counter

    return replacement_years, replacement_capex, terminal_value


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
    econ: "DeviceEconParams | None" = None,
) -> list[float]:
    """Build CF series [cf[0], cf[1], …, cf[N]] from a policy trajectory.

    cf[0] = -capex_yuan  (year-0 CAPEX, always ≤ 0)
    cf[y] = EBITDA(y) − Replacement(y)  for y = 1 … N
    cf[N] adds Terminal (residual − decommissioning) when econ is provided.

    EBITDA is assembled ONLY from streams (INV-STREAM-AUTHORITY):
      revenue = grid_export + h2_sale + avoided_cost + token_sale
      cost    = grid_import + demand_charge
      EBITDA  = revenue - cost - FixedOM - VarOM·MWh - AssetMgmt

    Optional real_money cash items (controlled by flags):
      degradation_yuan: NOT period cash by default (INV-DEG §3.6); include if flag=True
      curtailment_yuan: NOT cash unless curtailment_penalty_contract=True (INV-CURT §3.7)
      voll_yuan:        NOT cash unless reliability_penalty_contract=True  (INV-VOLL §3.8)

    Lifecycle (when econ is provided):
      replacement CAPEX fires at first-to-fire(calendar, throughput) years (§13.6).
      terminal = residual_value − decommissioning fires at year N.
      degradation_yuan is NOT a cash item (INV-DEG memo-only; cash path = replacement CAPEX).

    Args:
        eval_results: one PolicyEvalResult per operating year (N entries)
        capex_yuan:   year-0 capital expenditure in ¥ (default 0; econ lifecycle is separate)
        fixed_om_yuan: annual fixed O&M cost in ¥/yr (default 0)
        var_om_yuan_per_mwh: variable O&M in ¥/MWh of generation (default 0)
        asset_mgmt_yuan: annual asset-management fee in ¥/yr (default 0)
        include_degradation_as_cash: False (default) = INV-DEG applies
        curtailment_penalty_contract: True = curtailment_yuan enters cash
        reliability_penalty_contract: True = voll_yuan enters cash
        econ: DeviceEconParams with lifecycle fields; when provided, enables
              replacement CAPEX + terminal value (residual − decommissioning) events.

    Returns: list of length N+1: [cf_yr0, cf_yr1, …, cf_yrN]
    """
    N = len(eval_results)

    # ── Lifecycle events (INV-DEG §3.6 cash half) ──────────────────────────
    replacement_years: set[int] = set()
    replacement_capex_yuan: float = 0.0
    terminal_value_yuan: float = 0.0
    if econ is not None:
        replacement_years, replacement_capex_yuan, terminal_value_yuan = (
            _eol_events(eval_results, econ)
        )

    cf: list[float] = [-capex_yuan]  # year-0

    for y_idx, yr in enumerate(eval_results):
        year = y_idx + 1  # 1-indexed

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

        # ── Lifecycle: replacement CAPEX at EOL year (INV-DEG §3.6 cash half)
        # degradation_yuan is NOT subtracted here — it is a memo-only wear signal.
        # The actual cash cost = replacement_capex_yuan fired by first-to-fire(§13.6).
        if year in replacement_years:
            ebitda -= replacement_capex_yuan

        # ── Lifecycle: terminal value at horizon N (residual − decommissioning)
        if econ is not None and year == N:
            ebitda += terminal_value_yuan

        cf.append(ebitda)

    return cf
