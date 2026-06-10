"""gansu_env.py — pure-Python / NumPy reference implementation.

Implements REBUILD_SPEC.md §2–§4 with all §6 bug-fixes applied (D3–D10, D19).
This module is the ground-truth fixture; it is NOT used for training.

Contract: contracts/env/reference_implementation.md
Deliberate deviations from old code: see contract §Deliberate deviations.

Constraint enforcement order (§3.6, mandatory):
  STEP 1  — clip/renorm actions
  STEP 2  — generate renewable power
  STEP 3  — compute renewable routing fractions
  STEP 4  — battery dynamics (SOC clip)
  STEP 5  — cap flows-to-load
  STEP 6  — renewable surplus → grid
  STEP 7  — PCC export limit (per-source proportional curtailment)
  STEP 8  — grid import (VOLL if import > limit)
  STEP 9  — prices (D8: minute-accurate; D7: spread clamp)
  STEP 10 — costs (10a intermediate, 10b month boundary, 10c totals + reward)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from reference.gansu_params import GansuParams
from reference.tariff import get_price

if TYPE_CHECKING:  # pragma: no cover
    pass

# ---------------------------------------------------------------------------
# Module-level constant: month index for each of the 8760 hourly steps.
# Precomputed from days-per-month for a standard non-leap year (365 × 24 = 8760).
# No datetime arithmetic is required inside env_step.
# ---------------------------------------------------------------------------
_DAYS_PER_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
assert sum(_DAYS_PER_MONTH) == 365

_month_of_step_list: list[int] = []
for _m, _days in enumerate(_DAYS_PER_MONTH):
    _month_of_step_list.extend([_m] * (_days * 24))
assert len(_month_of_step_list) == 8760

MONTH_OF_STEP: np.ndarray = np.array(_month_of_step_list, dtype=np.int32)
"""Shape (8760,) int array: MONTH_OF_STEP[t] ∈ {0..11} (Jan=0, Dec=11)."""

# ---------------------------------------------------------------------------
# Hour profile for load generation (§4.2, D19)
# Spec: 0.5 for h∈{0..5,22,23}, 0.8 for h∈{6,21}, 1.0 for h∈{8..17}
# Unspecified hours (7, 18, 19, 20) follow the ramp pattern: 0.9.
# ---------------------------------------------------------------------------
_HOUR_PROFILE: list[float] = [
    0.5,  # 0 — night
    0.5,  # 1
    0.5,  # 2
    0.5,  # 3
    0.5,  # 4
    0.5,  # 5
    0.8,  # 6 — dawn (spec)
    0.9,  # 7 — morning ramp
    1.0,  # 8 — work start (spec)
    1.0,  # 9
    1.0,  # 10
    1.0,  # 11
    1.0,  # 12
    1.0,  # 13
    1.0,  # 14
    1.0,  # 15
    1.0,  # 16
    1.0,  # 17 — work end (spec)
    0.9,  # 18 — early evening ramp-down
    0.9,  # 19 — evening
    0.9,  # 20 — evening
    0.8,  # 21 — late evening (spec)
    0.5,  # 22 — night (spec)
    0.5,  # 23
]
assert len(_HOUR_PROFILE) == 24

_DOW_FACTOR: list[float] = [1.0, 1.0, 1.0, 1.0, 1.0, 0.7, 0.6]
"""Mon=0 → 1.0 … Sat=5 → 0.7, Sun=6 → 0.6."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EnvState:
    """Mutable environment state (one per episode step).

    Fields
    ------
    soc:           State-of-charge as a fraction ∈ [0, 1]; initialise near D4 midpoint.
    month_peak_mw: Highest grid-import seen this calendar month (MW ≥ 0).
    t:             Step index into the 8760-element synthetic-year arrays (0 ≤ t < 8760).
    rng:           Seeded NumPy Generator; used for sell-price spread noise.
    """
    soc:            float
    month_peak_mw:  float
    t:              int
    rng:            np.random.Generator


@dataclass
class StepResult:  # noqa: too-many-instance-attributes
    """Per-step output from env_step.

    All power flows in MW (≥ 0).
    All costs in ¥ (already × Δt = 1 h).
    Field names mirror the LOCKED telemetry schema v1.0.0 env_step payload.
    price_buy/sell_yuan_per_mwh are reference-only (not in telemetry).
    """
    # Power generation (MW)
    p_wind_mw:              float
    p_solar_mw:             float

    # Power flows (MW) — per-source fully accounted
    wind_to_load_mw:        float
    wind_to_bat_mw:         float
    wind_to_grid_mw:        float
    solar_to_load_mw:       float
    solar_to_bat_mw:        float
    solar_to_grid_mw:       float
    bat_to_load_mw:         float
    bat_to_grid_mw:         float
    grid_to_load_mw:        float
    grid_to_bat_mw:         float
    solar_curtailed_mw:     float
    wind_curtailed_mw:      float
    bat_curtailed_mw:       float
    load_unserved_mw:       float

    # Battery
    p_bat_charge_mw:        float
    p_bat_discharge_mw:     float
    soc_violation_mwh:      float

    # PCC aggregates (MW)
    p_import_mw:            float
    p_export_mw:            float

    # Prices (reference-only, not in telemetry schema)
    price_buy_yuan_per_mwh:  float
    price_sell_yuan_per_mwh: float

    # Per-step costs (¥)
    c_import_yuan:                  float
    r_export_yuan:                  float
    c_energy_yuan:                  float
    c_demand_shape_yuan:            float
    c_degradation_yuan:             float
    c_curtail_yuan:                 float
    c_voll_yuan:                    float
    penalty_yuan:                   float
    c_demand_charge_yuan:           float

    # D13: two independently-reconstructable cost totals
    cost_total_real_yuan:           float
    cost_total_reward_basis_yuan:   float

    # Reward
    reward:                         float

    # Updated state (for episode chaining)
    new_state:              EnvState


# ---------------------------------------------------------------------------
# Sub-functions
# ---------------------------------------------------------------------------

def wind_power(v_10m: float, params: GansuParams) -> float:
    """Fleet wind output in MW from 10 m wind speed (m/s). Stateless.

    Applies power-law shear (§3.1):
        v_hub = v_10m · (hub_height / 10)^0.14
    Then piecewise cubic power curve:
        v < v_cutin  OR  v ≥ v_cutout  → 0
        v_cutin ≤ v < v_rated          → p_rated · ((v − v_cutin) / (v_rated − v_cutin))³
        v_rated ≤ v < v_cutout         → p_rated
    Cut-out is INCLUSIVE (≥). Cut-in is exclusive (cubic = 0 at v_cutin).
    """
    # Power-law shear: open terrain exponent 0.14
    v_hub = v_10m * (params.wind_hub_height_m / 10.0) ** 0.14

    # Use a 1e-9 m/s tolerance on the cut-out boundary so that floating-point
    # round-tripping (v_10m = v_cutout / SHEAR; v_hub = v_10m * SHEAR) correctly
    # returns 0 — the round-trip gives 24.999...996 rather than 25.0 exactly.
    if v_hub < params.wind_v_cutin or v_hub >= params.wind_v_cutout - 1e-9:
        return 0.0
    if v_hub < params.wind_v_rated:
        frac = (v_hub - params.wind_v_cutin) / (params.wind_v_rated - params.wind_v_cutin)
        return params.wind_p_rated_mw * frac ** 3
    # v_rated ≤ v_hub < v_cutout
    return params.wind_p_rated_mw


def solar_power(G: float, T: float, params: GansuParams) -> float:
    """Fleet PV output in MW from irradiance G (W/m²) and temperature T (°C). Stateless.

    P = 0  if G ≤ 0
    P = pv_capacity · (G/1000) · clamp(1 + k_T·(T−25), 0.5, 1.2) · eta_inv · degradation
    """
    if G <= 0.0:
        return 0.0
    temp_factor = max(0.5, min(1.2, 1.0 + params.pv_k_T * (T - 25.0)))
    return params.pv_capacity_mw * (G / 1000.0) * temp_factor * params.pv_eta_inv * params.pv_degradation


def compute_sell_price(price_buy: float, spread_noise: float, params: GansuParams) -> float:
    """Sell price in ¥/MWh after D7 spread clamp (no negative spread, no negative price).

    effective_spread = max(0, params.price_spread_yuan_per_mwh + spread_noise)  # D7
    price_sell       = max(0, price_buy − effective_spread)                     # floor at 0
    """
    effective_spread = max(0.0, params.price_spread_yuan_per_mwh + spread_noise)
    return max(0.0, price_buy - effective_spread)


def battery_step(
    soc: float,
    a_bat: float,
    p_ren_to_bat: float,
    params: GansuParams,
    dt: float = 1.0,
) -> tuple[float, float, float, float, float]:
    """Battery dynamics for one Δt (§3.2, §3.6 rows 3–5).

    Parameters
    ----------
    soc:           State-of-charge fraction at start of step.
    a_bat:         Battery action ∈ [−1, 1]; ≥ 0 → charge, < 0 → discharge.
    p_ren_to_bat:  Renewable power already allocated to battery charging (MW).
    params:        GansuParams.
    dt:            Time step in hours (D3: Δt = 1 h).

    Returns
    -------
    (soc_new, p_ch, p_dis, p_grid_to_bat, soc_violation_mwh)
      soc_new          — clipped to [soc_min, soc_max]
      p_ch             — actual charge power (MW ≥ 0); 0 when discharging
      p_dis            — actual discharge power (MW ≥ 0); 0 when charging
      p_grid_to_bat    — grid supplement for charging (MW ≥ 0); 0 when discharging
      soc_violation_mwh — stored-energy overshoot beyond the hit SOC bound (MWh ≥ 0)
    """
    if a_bat >= 0.0:
        # ---- Charging ----
        p_target = a_bat * params.bat_power_mw
        p_ch_from_gen = min(p_ren_to_bat, p_target)           # renewable-first
        p_grid_to_bat = max(0.0, p_target - p_ch_from_gen)
        p_ch_desired = p_ch_from_gen + p_grid_to_bat           # == p_target

        soc_unconstrained = soc + params.bat_eta_ch * p_ch_desired * dt / params.bat_capacity_mwh

        if soc_unconstrained > params.soc_max:
            # Clip to soc_max
            p_ch_actual = (params.soc_max - soc) * params.bat_capacity_mwh / (params.bat_eta_ch * dt)
            soc_new = params.soc_max
            soc_violation = (soc_unconstrained - params.soc_max) * params.bat_capacity_mwh
        else:
            p_ch_actual = p_ch_desired
            soc_new = soc_unconstrained
            soc_violation = 0.0

        # Actual grid supplement (may be reduced by SOC clip)
        p_grid_to_bat_actual = max(0.0, p_ch_actual - p_ch_from_gen)

        return soc_new, p_ch_actual, 0.0, p_grid_to_bat_actual, soc_violation

    else:
        # ---- Discharging ----
        p_dis_desired = -a_bat * params.bat_power_mw

        soc_unconstrained = soc - p_dis_desired * dt / (params.bat_eta_dis * params.bat_capacity_mwh)

        if soc_unconstrained < params.soc_min:
            # Clip to soc_min
            p_dis_actual = (soc - params.soc_min) * params.bat_capacity_mwh * params.bat_eta_dis / dt
            soc_new = params.soc_min
            soc_violation = (params.soc_min - soc_unconstrained) * params.bat_capacity_mwh
        else:
            p_dis_actual = p_dis_desired
            soc_new = soc_unconstrained
            soc_violation = 0.0

        return soc_new, 0.0, p_dis_actual, 0.0, soc_violation


# ---------------------------------------------------------------------------
# Main step function
# ---------------------------------------------------------------------------

def env_step(
    state: EnvState,
    action: np.ndarray,
    weather: tuple[float, float, float],
    load: float,
    params: GansuParams,
    dt: float = 1.0,
) -> StepResult:
    """Full environment step implementing §3.6 constraint enforcement order.

    Parameters
    ----------
    state:   EnvState at the start of this step.
    action:  shape (6,) array [a_bat, f_s→l, f_s→b, f_w→l, f_w→b, f_b→l].
    weather: (wind_mps, irradiance_wm2, temperature_c).
    load:    Load demand in MW.
    params:  GansuParams.
    dt:      Time step in hours (default 1.0, D3).

    Returns
    -------
    StepResult with all flows, costs, and next state.
    """
    # ------------------------------------------------------------------
    # STEP 1 — Parse / clip actions (§3.6 row 1–2)
    # ------------------------------------------------------------------
    a_bat     = float(np.clip(action[0], -1.0, 1.0))
    f_s_l_raw = float(np.clip(action[1],  0.0, 1.0))   # solar → load
    f_s_b_raw = float(np.clip(action[2],  0.0, 1.0))   # solar → battery
    f_w_l_raw = float(np.clip(action[3],  0.0, 1.0))   # wind  → load
    f_w_b_raw = float(np.clip(action[4],  0.0, 1.0))   # wind  → battery
    f_b_l     = float(np.clip(action[5],  0.0, 1.0))   # battery → load

    # Renormalise per-source if fractions sum > 1 (§2.2, §3.6 row 2)
    total_s = f_s_l_raw + f_s_b_raw
    if total_s > 1.0:
        f_s_l = f_s_l_raw / total_s
        f_s_b = f_s_b_raw / total_s
    else:
        f_s_l = f_s_l_raw
        f_s_b = f_s_b_raw

    total_w = f_w_l_raw + f_w_b_raw
    if total_w > 1.0:
        f_w_l = f_w_l_raw / total_w
        f_w_b = f_w_b_raw / total_w
    else:
        f_w_l = f_w_l_raw
        f_w_b = f_w_b_raw

    # Unallocated fraction goes to grid
    # (used implicitly in STEP 6 via complement)

    # ------------------------------------------------------------------
    # STEP 2 — Generate renewable power
    # ------------------------------------------------------------------
    wind_mps, irr_wm2, temp_c = weather
    p_wind  = wind_power(wind_mps, params)
    p_solar = solar_power(irr_wm2, temp_c, params)

    # ------------------------------------------------------------------
    # STEP 3 — Compute renewable routing to battery (initial, pre-cap)
    # ------------------------------------------------------------------
    p_ren_to_bat = p_solar * f_s_b + p_wind * f_w_b

    # ------------------------------------------------------------------
    # STEP 4 — Battery dynamics (SOC clip)
    # ------------------------------------------------------------------
    soc_new, p_ch, p_dis, p_g2b, soc_viol = battery_step(
        state.soc, a_bat, p_ren_to_bat, params, dt
    )

    # Initial battery allocation to load / grid
    p_bat_to_load = p_dis * f_b_l
    p_bat_to_grid = p_dis * (1.0 - f_b_l)

    # ------------------------------------------------------------------
    # STEP 5 — Cap flows-to-load (§3.3 step 1, §3.6 row 7)
    # ------------------------------------------------------------------
    p_wind_to_load_raw  = p_wind  * f_w_l
    p_solar_to_load_raw = p_solar * f_s_l
    p_bat_to_load_orig  = p_bat_to_load     # save before possible scaling

    total_to_load = p_wind_to_load_raw + p_solar_to_load_raw + p_bat_to_load_orig

    if total_to_load > load:
        scale_load = load / total_to_load
        p_wind_to_load  = p_wind_to_load_raw  * scale_load
        p_solar_to_load = p_solar_to_load_raw * scale_load
        p_bat_to_load   = p_bat_to_load_orig  * scale_load
        # Battery discharge excess re-routes to grid (§3.3 step 1)
        p_bat_to_grid  += p_bat_to_load_orig * (1.0 - scale_load)
    else:
        p_wind_to_load  = p_wind_to_load_raw
        p_solar_to_load = p_solar_to_load_raw
        # p_bat_to_load and p_bat_to_grid unchanged

    # ------------------------------------------------------------------
    # STEP 6 — Renewable surplus → grid (§3.3 step 2)
    # Actual ren-to-bat may differ from allocated if SOC was clipped.
    # p_ch - p_g2b = actual renewable power absorbed by battery.
    # ------------------------------------------------------------------
    p_ren_to_bat_actual = p_ch - p_g2b   # p_ch = 0 when discharging
    if p_ren_to_bat > 1e-12:
        scale_bat = p_ren_to_bat_actual / p_ren_to_bat
    else:
        scale_bat = 0.0

    p_wind_to_bat   = p_wind  * f_w_b * scale_bat
    p_solar_to_bat  = p_solar * f_s_b * scale_bat
    p_wind_to_grid  = p_wind  - p_wind_to_load  - p_wind_to_bat
    p_solar_to_grid = p_solar - p_solar_to_load - p_solar_to_bat

    # Clamp tiny floating-point negatives
    p_wind_to_grid  = max(0.0, p_wind_to_grid)
    p_solar_to_grid = max(0.0, p_solar_to_grid)

    # ------------------------------------------------------------------
    # STEP 7 — PCC export limit (§3.3 step 3, §3.6 row 8)
    # Per-source proportional curtailment (B3-minor fix in contract).
    # ------------------------------------------------------------------
    total_export = p_wind_to_grid + p_solar_to_grid + p_bat_to_grid

    if total_export > params.grid_max_export_mw:
        scale_exp = params.grid_max_export_mw / total_export
        # Per-source curtailment: proportional to pre-curtailment grid flows
        wind_curtailed_mw  = p_wind_to_grid  * (1.0 - scale_exp)
        solar_curtailed_mw = p_solar_to_grid * (1.0 - scale_exp)
        bat_curtailed_mw   = p_bat_to_grid   * (1.0 - scale_exp)
        p_wind_to_grid  *= scale_exp
        p_solar_to_grid *= scale_exp
        p_bat_to_grid   *= scale_exp
    else:
        wind_curtailed_mw  = 0.0
        solar_curtailed_mw = 0.0
        bat_curtailed_mw   = 0.0

    # PCC export aggregate
    p_export = p_wind_to_grid + p_solar_to_grid + p_bat_to_grid

    # ------------------------------------------------------------------
    # STEP 8 — Grid import (§3.3 step 4, §3.6 row 9)
    # ------------------------------------------------------------------
    load_deficit          = load - p_wind_to_load - p_solar_to_load - p_bat_to_load
    grid_to_load_required = max(0.0, load_deficit)
    p_import_required     = grid_to_load_required + p_g2b

    if p_import_required > params.grid_max_import_mw:
        if params.grid_max_import_mw < p_g2b:
            # Import limit < battery charge demand → battery partially starved, load fully shed
            p_g2b_actual  = params.grid_max_import_mw
            grid_to_load  = 0.0
        else:
            # Import limit ≥ p_g2b → honour battery charge, cap load
            p_g2b_actual  = p_g2b
            grid_to_load  = min(grid_to_load_required, params.grid_max_import_mw - p_g2b)

        load_unserved = (load
                         - p_wind_to_load - p_solar_to_load
                         - p_bat_to_load  - grid_to_load)
    else:
        p_g2b_actual  = p_g2b
        grid_to_load  = grid_to_load_required
        load_unserved = 0.0

    load_unserved = max(0.0, load_unserved)  # floating-point guard
    p_import      = grid_to_load + p_g2b_actual

    # ------------------------------------------------------------------
    # STEP 9 — Prices (D8: minute-accurate; D7: spread clamp)
    # ------------------------------------------------------------------
    hour_of_day   = state.t % 24
    minute_of_hour = 0          # Δt = 1 h → steps always land on :00 (D3)
    price_buy  = get_price(hour_of_day, minute_of_hour)
    spread_noise = float(state.rng.normal(0.0, params.price_spread_sigma))
    price_sell = compute_sell_price(price_buy, spread_noise, params)

    # ------------------------------------------------------------------
    # STEP 10a — Intermediate cost components (§3.4, D13)
    # ------------------------------------------------------------------
    c_import  = price_buy  * p_import * dt
    r_export  = price_sell * p_export * dt
    c_energy  = c_import - r_export

    # Demand-shape: incremental charge for this step's import above current peak (RAW, D13)
    c_dc_shape    = params.demand_rate_yuan_per_mw_month * max(0.0, p_import - state.month_peak_mw)
    new_month_peak = max(state.month_peak_mw, p_import)

    c_deg     = params.c_deg_yuan_per_mwh * (p_ch + p_dis) * dt
    c_curtail = params.curtail_penalty_yuan_per_mwh * (
        wind_curtailed_mw + solar_curtailed_mw + bat_curtailed_mw
    ) * dt
    c_voll    = params.voll_yuan_per_mwh * load_unserved * dt
    penalty   = 20_000.0 * soc_viol

    # ------------------------------------------------------------------
    # STEP 10b — Month-boundary demand charge (D10)
    # Computed BEFORE cost_total_real so the field is defined when used.
    # month_of_step is module-level MONTH_OF_STEP array.
    # ------------------------------------------------------------------
    is_terminal  = (state.t == 8759)
    next_t       = min(state.t + 1, 8759)
    is_month_end = (int(MONTH_OF_STEP[next_t]) != int(MONTH_OF_STEP[state.t])) or is_terminal

    if is_month_end:
        c_demand_charge = new_month_peak * params.demand_rate_yuan_per_mw_month
        new_month_peak  = 0.0   # reset for next month
    else:
        c_demand_charge = 0.0

    # Anti-double-count (D10 fix): charged ONCE via is_month_end; no separate terminal flush.

    # ------------------------------------------------------------------
    # STEP 10c — D13 cost totals and reward
    # ------------------------------------------------------------------
    cost_total_reward_basis = c_energy + 2.0 * c_dc_shape + c_deg + c_curtail + c_voll
    cost_total_real         = c_energy + c_demand_charge + c_deg + c_curtail + c_voll
    reward = -(cost_total_reward_basis + penalty) * params.reward_scale

    # ------------------------------------------------------------------
    # Build next state
    # ------------------------------------------------------------------
    new_state = EnvState(
        soc=soc_new,
        month_peak_mw=new_month_peak,
        t=min(state.t + 1, 8759),
        rng=state.rng,   # same Generator object (advances in-place via normal() call above)
    )

    return StepResult(
        p_wind_mw=p_wind,
        p_solar_mw=p_solar,
        wind_to_load_mw=p_wind_to_load,
        wind_to_bat_mw=p_wind_to_bat,
        wind_to_grid_mw=p_wind_to_grid,
        solar_to_load_mw=p_solar_to_load,
        solar_to_bat_mw=p_solar_to_bat,
        solar_to_grid_mw=p_solar_to_grid,
        bat_to_load_mw=p_bat_to_load,
        bat_to_grid_mw=p_bat_to_grid,
        grid_to_load_mw=grid_to_load,
        grid_to_bat_mw=p_g2b_actual,
        solar_curtailed_mw=solar_curtailed_mw,
        wind_curtailed_mw=wind_curtailed_mw,
        bat_curtailed_mw=bat_curtailed_mw,
        load_unserved_mw=load_unserved,
        p_bat_charge_mw=p_ch,
        p_bat_discharge_mw=p_dis,
        soc_violation_mwh=soc_viol,
        p_import_mw=p_import,
        p_export_mw=p_export,
        price_buy_yuan_per_mwh=price_buy,
        price_sell_yuan_per_mwh=price_sell,
        c_import_yuan=c_import,
        r_export_yuan=r_export,
        c_energy_yuan=c_energy,
        c_demand_shape_yuan=c_dc_shape,
        c_degradation_yuan=c_deg,
        c_curtail_yuan=c_curtail,
        c_voll_yuan=c_voll,
        penalty_yuan=penalty,
        c_demand_charge_yuan=c_demand_charge,
        cost_total_real_yuan=cost_total_real,
        cost_total_reward_basis_yuan=cost_total_reward_basis,
        reward=reward,
        new_state=new_state,
    )


# ---------------------------------------------------------------------------
# Synthetic year generator
# ---------------------------------------------------------------------------

def generate_year(seed: int, params: GansuParams) -> dict[str, np.ndarray]:
    """Generate one synthetic year (8760 hourly steps) following §4.1 and §4.2 (D19).

    Parameters
    ----------
    seed:   Integer seed for reproducibility (fixed seed → identical arrays).
    params: GansuParams (currently unused beyond D19 load parameters; kept for API consistency).

    Returns
    -------
    dict with shape-(8760,) float64 arrays:
      'wind_mps'       — wind speed at 10 m (m/s), clipped to [0, 25]
      'irradiance_wm2' — surface irradiance (W/m²), ≥ 0
      'temperature_c'  — air temperature (°C)
      'load_mw'        — electrical load (MW), ≥ 0
    """
    rng = np.random.default_rng(seed)

    # Draw all random values in a fixed, reproducible order.
    # Order: wind AR1 noise → solar cloud mask → solar cloud values
    #        → temperature noise → load AR1 noise
    eta_z    = rng.standard_normal(8760)    # wind AR1 innovations
    cloud_do = rng.random(8760) < 0.3      # True → cloudy (prob 0.3)
    cloud_v  = rng.uniform(0.2, 0.8, 8760) # cloud factor when cloudy
    temp_z   = rng.standard_normal(8760)   # temperature noise
    phi_z    = rng.standard_normal(8760)   # load AR1 innovations

    # ---- Wind (§4.1 AR1) ----
    # η[0] = 0, η[t] = 0.95·η[t−1] + sqrt(1−0.95²)·z[t]
    _rho_w = 0.95
    _sig_w = math.sqrt(1.0 - _rho_w ** 2)
    eta = np.zeros(8760)
    for t in range(1, 8760):
        eta[t] = _rho_w * eta[t - 1] + _sig_w * eta_z[t]

    t_arr = np.arange(8760, dtype=float)
    wind_base = (6.0
                 + 2.0 * np.sin(2.0 * math.pi * (t_arr / 24.0 - 0.25))
                 + 2.0 * np.cos(2.0 * math.pi * t_arr / 8760.0)
                 + eta * 2.0)
    wind_mps = np.clip(wind_base, 0.0, 25.0)

    # ---- Solar (§4.1) ----
    d_arr = (t_arr / 24.0).astype(int)   # day of year 0-indexed
    h_arr = (t_arr % 24).astype(int)     # hour of day 0-indexed

    sunrise = 6.0  - 2.0 * np.cos(2.0 * math.pi * d_arr / 365.0)
    sunset  = 18.0 + 2.0 * np.cos(2.0 * math.pi * d_arr / 365.0)
    mid     = (sunrise + sunset) / 2.0
    daylen  = sunset - sunrise
    h_float = h_arr.astype(float)

    # Parabolic insolation envelope
    base = 1000.0 * np.maximum(0.0, 1.0 - ((h_float - mid) / (daylen / 2.0)) ** 2)
    seasonal = 0.7 + 0.3 * np.cos(2.0 * math.pi * (d_arr - 172) / 365.0)
    cloud = np.where(cloud_do, cloud_v, 1.0)
    irradiance_wm2 = np.maximum(0.0, base * seasonal * cloud)

    # ---- Temperature (§4.1) ----
    temp_c = (20.0
              + 8.0  * np.sin(2.0 * math.pi * (h_float - 9.0) / 24.0)
              + 15.0 * np.cos(2.0 * math.pi * (d_arr - 200.0) / 365.0)
              + 2.0  * temp_z)

    # ---- Load (§4.2, D19: ×100 scale, base = 75 000 kW) ----
    # φ[0] = 0, φ[t] = 0.8·φ[t−1] + sqrt(1−0.8²)·z[t]   AR1, ρ=0.8
    _rho_l = 0.8
    _sig_l = math.sqrt(1.0 - _rho_l ** 2)
    phi = np.zeros(8760)
    for t in range(1, 8760):
        phi[t] = _rho_l * phi[t - 1] + _sig_l * phi_z[t]

    hour_profile_arr = np.array([_HOUR_PROFILE[h] for h in h_arr])
    dow_factor_arr   = np.array([_DOW_FACTOR[d % 7]  for d in d_arr])

    cdd = np.maximum(0.0, temp_c - 18.0)
    hdd = np.maximum(0.0, 18.0 - temp_c)

    # D19: base=75_000 kW, α=4_500 kW/°C, β=3_750 kW/°C, σ_AR1=5_000 kW
    L_kw = (75_000.0 * hour_profile_arr * dow_factor_arr
            + 4_500.0 * cdd
            + 3_750.0 * hdd
            + phi * 5_000.0)
    load_mw = np.maximum(0.0, L_kw) / 1000.0

    return {
        "wind_mps":       wind_mps,
        "irradiance_wm2": irradiance_wm2,
        "temperature_c":  temp_c,
        "load_mw":        load_mw,
    }


# ---------------------------------------------------------------------------
# Observation builder
# ---------------------------------------------------------------------------

def get_obs(
    state: EnvState,
    data: dict[str, np.ndarray],
    params: GansuParams,
    price_buy: float,
) -> np.ndarray:
    """Build the 107-dim observation vector (§2.1) with D6 forecast noise, D9 stride=1.

    Parameters
    ----------
    state:     Current EnvState (uses state.t, state.soc, state.month_peak_mw, state.rng).
    data:      Output of generate_year — shape-(8760,) arrays.
    params:    GansuParams (provides forecast_horizon, forecast_sigma_max).
    price_buy: Buy price (¥/MWh) for the current step.

    Returns
    -------
    obs: shape (107,) float64 array.
        [0..10]  = base block (11 dims)
        [11..106] = forecast block (24 × 4 = 96 dims, stride=1, D9)
    """
    t = state.t
    h = t % 24
    month = int(MONTH_OF_STEP[t])

    obs = np.empty(107, dtype=np.float64)

    # --- Base block (11 dims) ---
    obs[0]  = float(data["wind_mps"][t])
    obs[1]  = float(data["irradiance_wm2"][t])
    obs[2]  = float(data["temperature_c"][t])
    obs[3]  = float(data["load_mw"][t])
    obs[4]  = state.soc
    obs[5]  = price_buy
    obs[6]  = state.month_peak_mw / 500.0
    obs[7]  = math.sin(2.0 * math.pi * h / 24.0)
    obs[8]  = math.cos(2.0 * math.pi * h / 24.0)
    obs[9]  = math.sin(2.0 * math.pi * month / 12.0)
    obs[10] = math.cos(2.0 * math.pi * month / 12.0)

    # --- Forecast block (24 × 4 = 96 dims, stride=1, D6, D9) ---
    H_max = params.forecast_horizon   # = 24
    sigma_max = params.forecast_sigma_max  # = 0.10

    for h_idx in range(1, H_max + 1):
        t_future = min(t + h_idx, 8759)
        sigma_h = sigma_max * h_idx / H_max   # D6: linear scaling

        # Draw noise for wind, irr, load, price (4 draws per future step)
        noise = state.rng.standard_normal(4)

        wind_true  = float(data["wind_mps"][t_future])
        irr_true   = float(data["irradiance_wm2"][t_future])
        load_true  = float(data["load_mw"][t_future])
        price_true = float(get_price(t_future % 24, 0))

        wind_noisy  = wind_true  * (1.0 + noise[0] * sigma_h)
        irr_noisy   = irr_true   * (1.0 + noise[1] * sigma_h)
        load_noisy  = load_true  * (1.0 + noise[2] * sigma_h)   # in MW
        price_noisy = price_true * (1.0 + noise[3] * sigma_h)

        # Clip to physical ranges and normalise (contract §get_obs)
        base_idx = 11 + 4 * (h_idx - 1)
        obs[base_idx + 0] = float(np.clip(wind_noisy, 0.0, 25.0)) / 20.0
        obs[base_idx + 1] = float(np.clip(irr_noisy, 0.0, 1000.0)) / 1000.0
        # load in kW for obs normalisation (clip 0–200 000 kW, norm by 100 000)
        load_noisy_kw = load_noisy * 1000.0
        obs[base_idx + 2] = float(np.clip(load_noisy_kw, 0.0, 200_000.0)) / 100_000.0
        obs[base_idx + 3] = float(price_noisy)   # raw ¥/MWh; normalised by VecNormalize

    return obs
