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
