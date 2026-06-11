"""energy_go.env.jax_env — pure-JAX Energy GO environment core.

Contract: contracts/env/jax_env_core.md
Spec: §2 (MDP), §3 (physics & costs), §4 (generators), §7 (JAX architecture)
Decisions: D3–D13, D17, D19, D21
"""
from __future__ import annotations

from typing import NamedTuple

import jax
import jax.numpy as jnp

# ---------------------------------------------------------------------------
# Module-level constants (precomputed outside jitted step)
# ---------------------------------------------------------------------------

# PRICE_TABLE_YPW — shape (24,) ¥/MWh
# Gansu TOU tariff at Δt=1h steps (each step lands on :00, minute=0 always, D8)
# h=0..6:  250  Valley (23:00–7:00)
# h=7:     450  Mid
# h=8..10: 620  Peak
# h=11:    780  Critical peak (10:30 ≤ 11:00 < 11:30)
# h=12..17:450  Mid (11:30–18:00)
# h=18:    620  Peak (18:00–19:00)
# h=19..20:780  Critical peak (19:00–21:00)
# h=21..22:620  Peak (21:00–23:00)
# h=23:    250  Valley
PRICE_TABLE_YPW: jax.Array = jnp.array(
    [250, 250, 250, 250, 250, 250, 250,   # 0–6  Valley
     450,                                   # 7    Mid
     620, 620, 620,                         # 8–10 Peak
     780,                                   # 11   Critical peak
     450, 450, 450, 450, 450, 450,          # 12–17 Mid
     620,                                   # 18   Peak
     780, 780,                              # 19–20 Critical peak
     620, 620,                              # 21–22 Peak
     250],                                  # 23   Valley
    dtype=jnp.float32,
)

# MONTH_OF_STEP — shape (8761,) int32
# MONTH_OF_STEP[t] = month index 0=Jan…11=Dec for step t ∈ [0,8759].
# Extra element at index 8760 = 11 (safe t+1 lookup at t=8759).
_DAYS_PER_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_month_list: list[int] = []
for _m, _d in enumerate(_DAYS_PER_MONTH):
    _month_list.extend([_m] * (_d * 24))
assert len(_month_list) == 8760
_month_list.append(11)  # index 8760 = December (safe t+1 sentinel)
MONTH_OF_STEP: jax.Array = jnp.array(_month_list, dtype=jnp.int32)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class EnvState(NamedTuple):
    """Mutable env state — all fields are JAX scalar arrays."""
    soc:        jax.Array  # float32, fraction ∈ [0,1]
    month_peak: jax.Array  # float32, MW — peak grid import this billing month
    t:          jax.Array  # int32   — step index [0, 8759]
    rng:        jax.Array  # PRNGKey


class EnvParams(NamedTuple):
    """Site/cost parameters — Gansu defaults.  Shared across vmapped envs."""
    # Wind fleet
    wind_rated_mw:               float = 615.0
    wind_v_cutin:                float = 3.0
    wind_v_rated:                float = 12.0
    wind_v_cutout:               float = 25.0
    wind_hub_height_m:           float = 105.0
    # Solar PV
    pv_capacity_mw:              float = 330.0
    pv_k_T:                      float = -0.003
    pv_eta_inv:                  float = 0.97
    pv_degradation:              float = 0.98
    # Battery
    bat_capacity_mwh:            float = 294.5
    bat_power_mw:                float = 98.16
    bat_eta_ch:                  float = 0.97
    bat_eta_dis:                 float = 0.97
    soc_min:                     float = 0.2
    soc_max:                     float = 0.9
    soc_init:                    float = 0.5
    # Grid
    grid_max_export_mw:          float = 945.0
    grid_max_import_mw:          float = 400.0
    # Costs
    c_deg_yuan_per_mwh:          float = 10.0
    voll_yuan_per_mwh:           float = 20_000.0
    curtail_yuan_per_mwh:        float = 800.0
    demand_rate_yuan_per_mw_month: float = 32_000.0
    soc_penalty_yuan_per_mwh:    float = 20_000.0
    reward_scale:                float = 1e-5
    # Prices
    price_spread_yuan_per_mwh:   float = 30.0
    price_spread_sigma:          float = 10.0
    # Forecast
    forecast_sigma_max:          float = 0.10
    # Episode
    episode_len:                 int   = 168


class EnvInfo(NamedTuple):
    """Per-step outputs — all float32 scalars.

    Aggregate flows (original fields):
      p_curtailed_mw = p_sol_curtailed_mw + p_wind_curtailed_mw + p_bat_curtailed_mw

    Per-source breakdown (13 additive fields, §3.3 amendment):
      Battery-to-grid curtailment is non-zero whenever discharge pushes aggregate
      export past the PCC limit (scale_exp applied equally to all three export channels,
      §5.3.5). Energy conservation: P_dis_actual = bat_to_load + bat_to_grid + bat_curtailed.
    """
    # ---- Aggregate power flows (MW) ----
    p_wind_mw:          jax.Array
    p_pv_mw:            jax.Array
    p_bat_ch_mw:        jax.Array
    p_bat_dis_mw:       jax.Array
    p_import_mw:        jax.Array
    p_export_mw:        jax.Array
    p_load_served_mw:   jax.Array
    p_load_unserved_mw: jax.Array
    p_curtailed_mw:     jax.Array  # aggregate = sol + wind + bat curtailed
    # ---- Costs (¥) ----
    c_import_yuan:                jax.Array
    r_export_yuan:                jax.Array
    c_energy_yuan:                jax.Array
    c_demand_shape_yuan:          jax.Array
    c_demand_charge_yuan:         jax.Array
    c_degradation_yuan:           jax.Array
    c_curtail_yuan:               jax.Array
    c_voll_yuan:                  jax.Array
    cost_total_real_yuan:         jax.Array
    cost_total_reward_basis_yuan: jax.Array
    penalty_yuan:                 jax.Array
    soc_violation_mwh:            jax.Array
    # ---- Prices ----
    price_buy_yuan_per_mwh:  jax.Array
    price_sell_yuan_per_mwh: jax.Array
    # ---- Per-source flow breakdown (13 additive fields for telemetry/harness) ----
    p_sol_to_load_mw:    jax.Array  # solar → load (after load cap)
    p_sol_to_bat_mw:     jax.Array  # solar → battery (after scale_bat)
    p_sol_to_grid_mw:    jax.Array  # solar → grid (after PCC curtailment)
    p_sol_curtailed_mw:  jax.Array  # solar curtailed at PCC
    p_wind_to_load_mw:   jax.Array  # wind → load (after load cap)
    p_wind_to_bat_mw:    jax.Array  # wind → battery (after scale_bat)
    p_wind_to_grid_mw:   jax.Array  # wind → grid (after PCC curtailment)
    p_wind_curtailed_mw: jax.Array  # wind curtailed at PCC
    p_bat_to_load_mw:    jax.Array  # battery discharge → load
    p_bat_to_grid_mw:    jax.Array  # battery discharge → grid (after PCC curtailment)
    p_bat_curtailed_mw:  jax.Array  # battery curtailed at PCC (non-zero when bat_to_grid > export headroom)
    p_grid_to_bat_mw:    jax.Array  # grid → battery (actual, after import cap)
    p_grid_to_load_mw:   jax.Array  # grid → load
    # ---- Constraint-signal bools (for harness telemetry, no physics recompute needed) ----
    load_capped:        jax.Array   # bool — True when load-cap scaling was applied (P_to_load_total > load_mw)
    import_cap_active:  jax.Array   # bool — True when import cap reduced grid_to_bat with load fully served


# ---------------------------------------------------------------------------
# Observation builder
# ---------------------------------------------------------------------------

def get_obs(
    state: EnvState,
    params: EnvParams,
    data: jax.Array,
) -> jax.Array:
    """Build the 107-dim observation vector (§2.1) for *state* without stepping.

    Called internally by step() (obs of the INPUT state) and reset().
    Also exported for serving/parity tests.

    RNG threading: derives rng_fc_init as the second child of a 3-way split of
    state.rng (same split used in step(), so forecast noise is always independent
    from the price-spread draw).
    """
    t = state.t
    h = (t % 24).astype(jnp.int32)
    month = MONTH_OF_STEP[t]

    # Base block (11 dims)
    obs_base = jnp.array([
        data[t, 0],                                                   # obs[0] wind m/s
        data[t, 1],                                                   # obs[1] irr W/m²
        data[t, 2],                                                   # obs[2] temp °C
        data[t, 3],                                                   # obs[3] load MW
        state.soc,                                                    # obs[4] SOC fraction
        PRICE_TABLE_YPW[h],                                           # obs[5] price ¥/MWh
        state.month_peak / 500.0,                                     # obs[6] peak/500
        jnp.sin(2.0 * jnp.pi * h / 24.0),                           # obs[7]
        jnp.cos(2.0 * jnp.pi * h / 24.0),                           # obs[8]
        jnp.sin(2.0 * jnp.pi * month / 12.0),                       # obs[9]
        jnp.cos(2.0 * jnp.pi * month / 12.0),                       # obs[10]
    ], dtype=jnp.float32)

    # Forecast block (24 horizons × 4 features = 96 dims)
    # rng_fc_init: second child of 3-way split (same as step() §5.3.6)
    _, rng_fc_init, _ = jax.random.split(state.rng, 3)

    def forecast_step(rng_carry, h_idx):
        """h_idx: 1-based horizon (1..24)."""
        rng_fc, rng_next = jax.random.split(rng_carry)
        t_fc = jnp.minimum(t + h_idx, jnp.int32(8759))
        sigma_h = params.forecast_sigma_max * h_idx / 24.0  # D6: linear scaling

        eps = jax.random.normal(rng_fc, shape=(4,)) * sigma_h

        wind_true  = data[t_fc, 0]
        irr_true   = data[t_fc, 1]
        load_true  = data[t_fc, 3]
        price_true = PRICE_TABLE_YPW[t_fc % 24]

        fc_wind  = jnp.clip(wind_true  * (1.0 + eps[0]), 0.0, 25.0) / 20.0
        fc_irr   = jnp.clip(irr_true   * (1.0 + eps[1]), 0.0) / 1000.0
        fc_load  = jnp.clip(load_true * 1000.0 * (1.0 + eps[2]), 0.0) / 100_000.0
        fc_price = jnp.clip(price_true * (1.0 + eps[3]), 0.0)

        return rng_next, jnp.array([fc_wind, fc_irr, fc_load, fc_price], dtype=jnp.float32)

    horizons = jnp.arange(1, 25, dtype=jnp.int32)
    _, fc_block = jax.lax.scan(forecast_step, rng_fc_init, horizons)
    # fc_block shape: (24, 4); flatten to (96,)
    obs_fc = fc_block.reshape(96)

    return jnp.concatenate([obs_base, obs_fc])


# ---------------------------------------------------------------------------
# Main step function
# ---------------------------------------------------------------------------

def step(
    state: EnvState,
    action: jax.Array,
    params: EnvParams,
    data: jax.Array,
) -> tuple[EnvState, jax.Array, jax.Array, jax.Array, EnvInfo]:
    """Full environment step — jittable and vmappable with in_axes=(0,0,None,None).

    Returns (new_state, obs, reward, done, info)
    where obs is from the INPUT state (§5.4: computed at BEGINNING of step).

    Constraint enforcement order (§3.6):
      1. parse/clip actions
      2. battery dynamics (SOC clip + violation)
      3. cap flows-to-load
      4. PCC export limit + curtailment
      5. grid import + VOLL
      6. costs and reward
    """
    t = state.t

    # ------------------------------------------------------------------
    # Obs for the INPUT state (§5.4: computed BEFORE action is applied)
    # ------------------------------------------------------------------
    obs = get_obs(state, params, data)

    # ------------------------------------------------------------------
    # STEP 1 — Parse / clip actions
    # ------------------------------------------------------------------
    a_bat    = jnp.clip(action[0], -1.0,  1.0)
    f_sl_raw = jnp.clip(action[1],  0.0,  1.0)  # solar → load
    f_sb_raw = jnp.clip(action[2],  0.0,  1.0)  # solar → battery
    f_wl_raw = jnp.clip(action[3],  0.0,  1.0)  # wind  → load
    f_wb_raw = jnp.clip(action[4],  0.0,  1.0)  # wind  → battery
    f_bl     = jnp.clip(action[5],  0.0,  1.0)  # battery → load

    # Renormalise solar fractions if sum > 1 (jnp.where — no Python branch)
    s_solar = f_sl_raw + f_sb_raw
    f_sl = jnp.where(s_solar > 1.0, f_sl_raw / s_solar, f_sl_raw)
    f_sb = jnp.where(s_solar > 1.0, f_sb_raw / s_solar, f_sb_raw)

    # Renormalise wind fractions
    s_wind = f_wl_raw + f_wb_raw
    f_wl = jnp.where(s_wind > 1.0, f_wl_raw / s_wind, f_wl_raw)
    f_wb = jnp.where(s_wind > 1.0, f_wb_raw / s_wind, f_wb_raw)

    # ------------------------------------------------------------------
    # STEP 2 — Renewable generation (§3.1)
    # ------------------------------------------------------------------

    # Solar PV
    irr      = data[t, 1]
    temp     = data[t, 2]
    irr_factor  = irr / 1000.0
    temp_factor = jnp.clip(1.0 + params.pv_k_T * (temp - 25.0), 0.5, 1.2)
    P_pv = jnp.where(
        irr <= 0.0,
        0.0,
        params.pv_capacity_mw * irr_factor * temp_factor * params.pv_eta_inv * params.pv_degradation,
    )

    # Wind turbine
    v_10m  = data[t, 0]
    v_hub  = v_10m * (params.wind_hub_height_m / 10.0) ** 0.14
    p_frac = jnp.where(
        v_hub < params.wind_v_cutin,
        0.0,
        jnp.where(
            v_hub >= params.wind_v_cutout,
            0.0,
            jnp.where(
                v_hub >= params.wind_v_rated,
                1.0,
                ((v_hub - params.wind_v_cutin) / (params.wind_v_rated - params.wind_v_cutin)) ** 3,
            ),
        ),
    )
    P_wind = params.wind_rated_mw * p_frac

    # ------------------------------------------------------------------
    # STEP 3 — Battery dynamics (§3.2, §3.6 rules #3–6)
    # ------------------------------------------------------------------
    charging = a_bat >= 0.0

    # ---- Charge mode ----
    P_ch_target   = a_bat * params.bat_power_mw
    P_ren_to_bat  = P_pv * f_sb + P_wind * f_wb          # renewable allocated to battery
    P_ch_from_gen = jnp.minimum(P_ren_to_bat, P_ch_target)
    P_grid_to_bat = jnp.maximum(0.0, P_ch_target - P_ch_from_gen)
    P_ch_desired  = P_ch_from_gen + P_grid_to_bat          # == P_ch_target

    max_P_ch   = (params.soc_max - state.soc) * params.bat_capacity_mwh / params.bat_eta_ch
    max_P_ch   = jnp.maximum(0.0, max_P_ch)
    P_ch_actual = jnp.minimum(P_ch_desired, max_P_ch)
    violation_ch = jnp.maximum(0.0, (P_ch_desired - P_ch_actual) * params.bat_eta_ch)
    new_soc_ch   = state.soc + params.bat_eta_ch * P_ch_actual / params.bat_capacity_mwh

    # Actual grid supplement after SOC clip
    P_grid_to_bat_actual_ch = jnp.maximum(0.0, P_ch_actual - P_ch_from_gen)

    # ---- Discharge mode ----
    P_dis_target = (-a_bat) * params.bat_power_mw
    max_P_dis    = (state.soc - params.soc_min) * params.bat_capacity_mwh * params.bat_eta_dis
    max_P_dis    = jnp.maximum(0.0, max_P_dis)
    P_dis_actual = jnp.minimum(P_dis_target, max_P_dis)
    violation_dis = jnp.maximum(0.0, (P_dis_target - P_dis_actual) / params.bat_eta_dis)
    new_soc_dis  = state.soc - P_dis_actual / (params.bat_eta_dis * params.bat_capacity_mwh)

    # ---- Combine charge/discharge (jnp.where — no Python branch) ----
    P_bat_ch    = jnp.where(charging, P_ch_actual, 0.0)
    P_bat_dis   = jnp.where(charging, 0.0, P_dis_actual)
    P_grid_to_bat_raw = jnp.where(charging, P_grid_to_bat_actual_ch, 0.0)
    violation_mwh = jnp.where(charging, violation_ch, violation_dis)
    new_soc       = jnp.where(charging, new_soc_ch, new_soc_dis)

    # Actual ren-to-bat (charging: how much of bat charge came from renewables)
    P_ren_to_bat_actual = jnp.where(charging, P_bat_ch - P_grid_to_bat_raw, 0.0)
    P_ren_to_bat_actual = jnp.maximum(0.0, P_ren_to_bat_actual)

    # Initial bat allocation to load / grid (discharge mode only)
    P_bat_to_load_pre = jnp.where(charging, 0.0, P_bat_dis * f_bl)
    P_bat_to_grid_pre = jnp.where(charging, 0.0, P_bat_dis * (1.0 - f_bl))

    # ------------------------------------------------------------------
    # STEP 4 — Load cap (§3.6 rule #7)
    # ------------------------------------------------------------------
    P_sol_to_load_raw  = P_pv   * f_sl
    P_wind_to_load_raw = P_wind * f_wl

    P_to_load_total = P_sol_to_load_raw + P_wind_to_load_raw + P_bat_to_load_pre
    load_mw = data[t, 3]

    scale_to_load = jnp.where(
        P_to_load_total > load_mw,
        load_mw / (P_to_load_total + 1e-30),
        1.0,
    )
    load_capped = P_to_load_total > load_mw

    P_sol_to_load  = P_sol_to_load_raw  * scale_to_load
    P_wind_to_load = P_wind_to_load_raw * scale_to_load
    P_bat_to_load  = P_bat_to_load_pre  * scale_to_load

    # Battery discharge excess re-routes to grid
    excess_bat     = P_bat_to_load_pre - P_bat_to_load
    P_bat_to_grid  = P_bat_to_grid_pre + excess_bat

    # ------------------------------------------------------------------
    # STEP 5 — Renewable surplus to grid (§3.3 rule #2)
    # ------------------------------------------------------------------
    # scale_bat: fraction of allocated ren-to-bat that was actually absorbed
    scale_bat = jnp.where(
        P_ren_to_bat > 1e-12,
        P_ren_to_bat_actual / (P_ren_to_bat + 1e-30),
        0.0,
    )

    P_solar_to_bat = P_pv   * f_sb * scale_bat
    P_wind_to_bat  = P_wind * f_wb * scale_bat

    P_sol_to_grid  = jnp.maximum(0.0, P_pv   - P_sol_to_load  - P_solar_to_bat)
    P_wind_to_grid = jnp.maximum(0.0, P_wind  - P_wind_to_load - P_wind_to_bat)

    # ------------------------------------------------------------------
    # STEP 6 — PCC export limit (§3.6 rule #8)
    # ------------------------------------------------------------------
    # Save pre-curtailment per-source values for telemetry breakdown (§3.3 amendment)
    P_sol_to_grid_pre_curt  = P_sol_to_grid
    P_wind_to_grid_pre_curt = P_wind_to_grid
    P_bat_to_grid_pre_curt  = P_bat_to_grid

    P_export_raw = P_sol_to_grid + P_wind_to_grid + P_bat_to_grid
    scale_exp = jnp.where(
        P_export_raw > params.grid_max_export_mw,
        params.grid_max_export_mw / (P_export_raw + 1e-30),
        1.0,
    )

    P_sol_to_grid  = P_sol_to_grid  * scale_exp
    P_wind_to_grid = P_wind_to_grid * scale_exp
    P_bat_to_grid  = P_bat_to_grid  * scale_exp

    P_export     = P_sol_to_grid + P_wind_to_grid + P_bat_to_grid
    P_curtailed  = P_export_raw - P_export

    # Per-source curtailment breakdown (non-negative by construction, sum == P_curtailed)
    P_sol_curtailed  = P_sol_to_grid_pre_curt  - P_sol_to_grid
    P_wind_curtailed = P_wind_to_grid_pre_curt - P_wind_to_grid
    P_bat_curtailed  = P_bat_to_grid_pre_curt  - P_bat_to_grid

    # ------------------------------------------------------------------
    # STEP 7 — Grid import (§3.6 rule #9): load-first priority
    # "Load served first, then battery charging reduced, then load shed."
    # ------------------------------------------------------------------
    P_load_served_no_grid = P_sol_to_load + P_wind_to_load + P_bat_to_load
    load_deficit   = jnp.maximum(0.0, load_mw - P_load_served_no_grid)

    # Load has first claim on import headroom (up to max_import_mw)
    grid_to_load  = jnp.minimum(load_deficit, params.grid_max_import_mw)
    load_unserved = jnp.maximum(0.0, load_deficit - grid_to_load)

    # Battery charging gets whatever headroom remains after load is served
    import_headroom_for_bat = jnp.maximum(0.0, params.grid_max_import_mw - grid_to_load)
    P_grid_to_bat_actual    = jnp.minimum(P_grid_to_bat_raw, import_headroom_for_bat)
    P_grid_to_bat_actual    = jnp.maximum(0.0, P_grid_to_bat_actual)
    import_cap_active = (load_unserved < 1e-6) & (P_grid_to_bat_actual < P_grid_to_bat_raw - 1e-6)

    P_load_served = P_load_served_no_grid + grid_to_load
    P_import      = grid_to_load + P_grid_to_bat_actual

    # ------------------------------------------------------------------
    # STEP 8 — Price lookup (D7, D8)
    # ------------------------------------------------------------------
    hour = (t % 24).astype(jnp.int32)
    price_buy = PRICE_TABLE_YPW[hour]

    # 3-way RNG split: price-spread, forecast-noise, new state key
    rng_spread, rng_fc_init, new_rng = jax.random.split(state.rng, 3)

    noise      = jax.random.normal(rng_spread) * params.price_spread_sigma
    eff_spread = jnp.maximum(0.0, params.price_spread_yuan_per_mwh + noise)  # D7: clamp ≥ 0
    price_sell = jnp.maximum(0.0, price_buy - eff_spread)                    # D7: sell ≥ 0

    # ------------------------------------------------------------------
    # STEP 9 — Costs (§3.4, D13)
    # ------------------------------------------------------------------
    C_import  = price_buy  * P_import * 1.0
    R_export  = price_sell * P_export * 1.0
    C_E       = C_import - R_export

    # D13: demand shape — raw incremental charge (NOT doubled; 2× applied in reward)
    C_DC_shape = params.demand_rate_yuan_per_mw_month * jnp.maximum(0.0, P_import - state.month_peak)

    C_deg     = params.c_deg_yuan_per_mwh * (P_bat_ch + P_bat_dis) * 1.0
    C_curtail = params.curtail_yuan_per_mwh * P_curtailed * 1.0
    C_VOLL    = params.voll_yuan_per_mwh * load_unserved * 1.0

    # Demand charge booking (D10, D21)
    is_month_end = (MONTH_OF_STEP[t + 1] != MONTH_OF_STEP[t])
    is_terminal  = (t == jnp.int32(8759))
    books_charge = is_month_end | is_terminal

    peak_incl_now   = jnp.maximum(state.month_peak, P_import)
    C_demand_charge = jnp.where(
        books_charge,
        peak_incl_now * params.demand_rate_yuan_per_mw_month,
        0.0,
    )
    # D21 invariant (2): new_month_peak = 0.0 EXACTLY after booking
    new_month_peak = jnp.where(books_charge, 0.0, peak_incl_now)

    # D13 cost totals
    cost_total_real         = C_E + C_demand_charge + C_deg + C_curtail + C_VOLL
    cost_total_reward_basis = C_E + 2.0 * C_DC_shape + C_deg + C_curtail + C_VOLL

    penalty = params.soc_penalty_yuan_per_mwh * violation_mwh

    # Reward (§3.5)
    reward = -(cost_total_reward_basis + penalty) * params.reward_scale

    # ------------------------------------------------------------------
    # STEP 10 — State update and termination
    # ------------------------------------------------------------------
    new_state = EnvState(
        soc        = new_soc,
        month_peak = new_month_peak,
        t          = t + jnp.int32(1),
        rng        = new_rng,
    )

    done = (t == jnp.int32(params.episode_len) - jnp.int32(1))

    info = EnvInfo(
        p_wind_mw           = P_wind,
        p_pv_mw             = P_pv,
        p_bat_ch_mw         = P_bat_ch,
        p_bat_dis_mw        = P_bat_dis,
        p_import_mw         = P_import,
        p_export_mw         = P_export,
        p_load_served_mw    = P_load_served,
        p_load_unserved_mw  = load_unserved,
        p_curtailed_mw      = P_curtailed,
        c_import_yuan       = C_import,
        r_export_yuan       = R_export,
        c_energy_yuan       = C_E,
        c_demand_shape_yuan = C_DC_shape,
        c_demand_charge_yuan= C_demand_charge,
        c_degradation_yuan  = C_deg,
        c_curtail_yuan      = C_curtail,
        c_voll_yuan         = C_VOLL,
        cost_total_real_yuan         = cost_total_real,
        cost_total_reward_basis_yuan = cost_total_reward_basis,
        penalty_yuan        = penalty,
        soc_violation_mwh   = violation_mwh,
        price_buy_yuan_per_mwh  = price_buy,
        price_sell_yuan_per_mwh = price_sell,
        # Per-source flow breakdown (13 additive fields, §3.3 amendment)
        p_sol_to_load_mw    = P_sol_to_load,
        p_sol_to_bat_mw     = P_solar_to_bat,
        p_sol_to_grid_mw    = P_sol_to_grid,
        p_sol_curtailed_mw  = P_sol_curtailed,
        p_wind_to_load_mw   = P_wind_to_load,
        p_wind_to_bat_mw    = P_wind_to_bat,
        p_wind_to_grid_mw   = P_wind_to_grid,
        p_wind_curtailed_mw = P_wind_curtailed,
        p_bat_to_load_mw    = P_bat_to_load,
        p_bat_to_grid_mw    = P_bat_to_grid,
        p_bat_curtailed_mw  = P_bat_curtailed,
        p_grid_to_bat_mw    = P_grid_to_bat_actual,
        p_grid_to_load_mw   = grid_to_load,
        load_capped         = load_capped,
        import_cap_active   = import_cap_active,
    )

    return new_state, obs, reward, done, info


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def reset(
    key: jax.Array,
    params: EnvParams,
    data: jax.Array,
    episode_start: int = 0,
) -> tuple[EnvState, jax.Array]:
    """Initialise a new episode starting at *episode_start*.

    Returns (state, obs) where obs is the 107-dim observation for state.
    """
    state = EnvState(
        soc        = jnp.float32(params.soc_init),
        month_peak = jnp.float32(0.0),
        t          = jnp.int32(episode_start),
        rng        = key,
    )
    obs = get_obs(state, params, data)
    return state, obs
