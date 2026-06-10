"""GansuParams — site and cost parameters for the Gansu Energy GO environment.

All fields have defaults matching the Gansu site spec (REBUILD_SPEC.md §2–§3, §4.2 D19).
Units are documented per field; contracts/env/reference_implementation.md is authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GansuParams:
    # --- Wind fleet (Vestas V150-4.2 MW × 146 turbines, total 615 MW rated) ---
    wind_p_rated_mw:    float = 615.0    # total fleet MW
    wind_v_cutin:       float = 3.0      # m/s — cut-in (exclusive: cubic term = 0 at exactly v_cutin)
    wind_v_rated:       float = 12.0     # m/s
    wind_v_cutout:      float = 25.0     # m/s — cut-out inclusive (v ≥ v_cutout → 0)
    wind_hub_height_m:  float = 105.0    # hub height for power-law shear (§3.1)

    # --- Solar PV fleet (Trina Vertex N reference, 330 MW capacity) ---
    pv_capacity_mw:     float = 330.0
    pv_k_T:             float = -0.003   # /°C  temperature coefficient
    pv_eta_inv:         float = 0.97     # inverter efficiency
    pv_degradation:     float = 0.98     # year-1 degradation factor

    # --- Battery (294.5 MWh / 98.16 MW, D4: SOC bounds 0.2–0.9) ---
    bat_capacity_mwh:   float = 294.5
    bat_power_mw:       float = 98.16    # P_max_ch = P_max_dis (MW)
    bat_eta_ch:         float = 0.97     # round-trip charge efficiency
    bat_eta_dis:        float = 0.97     # round-trip discharge efficiency
    soc_min:            float = 0.2      # D4
    soc_max:            float = 0.9      # D4

    # --- Grid connection (D5: physics export limit = 945 MW, D12: import limit 400 MW) ---
    grid_max_export_mw: float = 945.0    # PCC export limit (MW)
    grid_max_import_mw: float = 400.0    # per-site import limit (MW, D12)

    # --- Cost parameters (¥ units, §3.4) ---
    c_deg_yuan_per_mwh:             float = 10.0        # battery throughput degradation cost
    voll_yuan_per_mwh:              float = 20_000.0    # value of lost load
    curtail_penalty_yuan_per_mwh:   float = 800.0       # curtailment penalty
    demand_rate_yuan_per_mw_month:  float = 32_000.0    # §3.7: 32 ¥/kW·month × 1000 kW/MW
    reward_scale:                   float = 1e-5        # §3.5: scale reward to ≈ O(1)

    # --- Sell-price spread (D7: effective_spread = max(0, nominal + noise) ≥ 0) ---
    price_spread_yuan_per_mwh:      float = 30.0        # nominal spread (¥/MWh)
    price_spread_sigma:             float = 10.0        # spread noise std (¥/MWh)

    # --- Forecast (D6: horizon-scaled noise; D9: stride = 1 step, not 4) ---
    forecast_horizon:   int   = 24
    forecast_sigma_max: float = 0.10     # 10 % noise at horizon H_max = 24
