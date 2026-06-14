"""DeviceEconParams — project economics from config/device_models.yaml (#103).

Loaded by the serving layer and passed verbatim to finance().  The finance
engine reads ONLY these fields — no filesystem I/O inside finance() (purity).

Units: ¥ (yuan), MWh, years.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class DeviceEconParams:
    """Per-site economics block extracted from a benchmark_device_library entry.

    All cost fields default to 0.0 so unit tests can specify only what matters.
    """
    # Capital expenditure
    total_capex_yuan:        float = 0.0    # ¥ total installed cost (year-0)

    # Operating expenditure (per-year fixed, and per-MWh variable)
    fixed_om_yuan_per_yr:    float = 0.0    # ¥/yr  (O&M labour, insurance, …)
    var_om_yuan_per_mwh:     float = 0.0    # ¥/MWh throughput
    asset_mgmt_yuan_per_yr:  float = 0.0    # ¥/yr  (asset-management fee)

    # Battery physical capacity (used for LCOS denominator)
    bat_capacity_mwh:        float = 0.0    # MWh usable capacity

    # Nameplate generation capacity (used as LCOE denominator fallback)
    nameplate_mwh_per_yr:    float = 0.0    # MWh/yr at rated capacity

    # Lifecycle / end-of-life fields (from config/device_models.yaml via #103)
    # Used by first-to-fire(calendar, throughput) EOL mechanism (§13.6).
    replacement_cost_fraction: float = 0.0   # fraction of total_capex_yuan per replacement event
    cycle_life_full_equiv:     float = 0.0   # full-equivalent cycles to end-of-life (0 = no limit)
    lifetime_years:            int   = 0     # calendar years to end-of-life (0 = no limit)
    residual_value_fraction:   float = 0.0   # fraction of total_capex_yuan as scrap/resale at horizon N
    decommissioning_yuan:      float = 0.0   # absolute site-cleanup cost at horizon N (¥)
