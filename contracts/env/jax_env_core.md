# Contract: jax_env_core — Pure-JAX Environment Core

- **Area:** env
- **Branch:** `feat/env-jax-env-core`
- **Spec sections:** §2 (MDP), §3 (physics & costs), §4 (synthetic generators), §7 (JAX architecture)
- **Decisions:** D3–D13, D17, D19, D21
- **Status:** DRAFT — awaiting backend-reviewer APPROVE before implementation
- **Review record:** `contracts/reviews/jax_env_core.md`
- **Parity ground-truth:** `contracts/env/reference_implementation.md` (D11)

---

## 1. Scope

This contract specifies:
1. `energy_go.env.jax_env` — `EnvState`, `EnvParams`, `EnvInfo`, `step()`, `reset()`
2. `energy_go.generators.synthetic` — `generate_year()`

The JAX core is a **fresh implementation from §3/§4 spec + decisions**, not a line-by-line port of the NumPy reference (D11 parity strategy: two independent implementations of the same spec so the parity test is a real cross-check).

The existing `tests/env/test_env_parity_gansu.py` `TestJaxReferenceParity` suite is **unskipped** when `energy_go.env.jax_env` first becomes importable.

---

## 2. Module layout

```
src/energy_go/
  env/
    __init__.py         (existing — no changes)
    jax_env.py          NEW — EnvState, EnvParams, EnvInfo, step(), reset()
  generators/
    __init__.py         (existing — no changes)
    synthetic.py        NEW — generate_year()
```

---

## 3. Types

### 3.1 `EnvState` (NamedTuple / JAX pytree)

All fields are JAX arrays (jnp.float32 scalars unless noted).

```python
class EnvState(NamedTuple):
    soc:        jax.Array   # float32, fraction of E_capacity; bounds [0.0, 1.0] enforced by step
    month_peak: jax.Array   # float32, MW — peak grid import in current billing month
    t:          jax.Array   # int32 — current step index [0, 8759]
    rng:        jax.Array   # PRNGKey — advanced each step for stochastic sell-price spread
```

**Units:** `soc` is dimensionless (fraction), `month_peak` is MW, `t` is a dimensionless step index.

### 3.2 `EnvParams` (NamedTuple — shared across vmapped envs)

Default values are the Gansu site (D11). All float32 scalars unless noted.

```python
class EnvParams(NamedTuple):
    # Wind fleet (Vestas V150-4.2 MW turbines, §3.1)
    wind_rated_mw:      float = 615.0   # total fleet rated MW (D: 146 turbines × 4.2 MW)
    wind_v_cutin:       float = 3.0     # m/s — cut-in (v < v_cutin → 0)
    wind_v_rated:       float = 12.0    # m/s — rated wind speed
    wind_v_cutout:      float = 25.0    # m/s — cut-out (v ≥ v_cutout → 0)
    wind_hub_height_m:  float = 105.0   # hub height for power-law shear

    # Solar PV (Trina Vertex N, §3.1)
    pv_capacity_mw:     float = 330.0   # installed DC capacity, MW
    pv_k_T:             float = -0.003  # /°C — temperature coefficient
    pv_eta_inv:         float = 0.97    # inverter efficiency
    pv_degradation:     float = 0.98    # year-1 degradation factor

    # Battery (§3.2, D4)
    bat_capacity_mwh:   float = 294.5   # usable energy capacity
    bat_power_mw:       float = 98.16   # P_max_ch = P_max_dis, MW
    bat_eta_ch:         float = 0.97    # per-side efficiency (RTE ≈ 94%)
    bat_eta_dis:        float = 0.97
    soc_min:            float = 0.2     # D4: hard lower bound (fraction)
    soc_max:            float = 0.9     # D4: hard upper bound (fraction)
    soc_init:           float = 0.5     # initial SOC for reset()

    # Grid connection (D5, D12)
    grid_max_export_mw: float = 945.0   # PCC export limit (MW) — D5
    grid_max_import_mw: float = 400.0   # import limit (MW) — D12

    # Costs (§3.4, ¥ units)
    c_deg_yuan_per_mwh:           float = 10.0       # battery throughput degradation
    voll_yuan_per_mwh:            float = 20_000.0   # value of lost load
    curtail_yuan_per_mwh:         float = 800.0      # curtailment penalty
    demand_rate_yuan_per_mw_month: float = 32_000.0  # §3.7 demand charge rate
    soc_penalty_yuan_per_mwh:     float = 20_000.0   # §3.5 SOC violation penalty (= VOLL)
    reward_scale:                 float = 1e-5       # §3.5 reward scaling

    # Sell-price spread (D7)
    price_spread_yuan_per_mwh:    float = 30.0       # nominal spread (¥/MWh)
    price_spread_sigma:           float = 10.0       # spread noise std

    # Forecast noise (D6)
    forecast_sigma_max:           float = 0.10       # 10% noise at H_max=24

    # Episode length (D3)
    episode_len:                  int   = 168        # 168 = 7-day train; 8760 = eval
```

### 3.3 `EnvInfo` (NamedTuple — per-step outputs)

All float32 scalars (MW / ¥ / fraction). Fields align with the LOCKED telemetry schema (D13, D18).

```python
class EnvInfo(NamedTuple):
    # Power flows (MW)
    p_wind_mw:          jax.Array   # total wind generation
    p_pv_mw:            jax.Array   # total solar generation
    p_bat_ch_mw:        jax.Array   # battery charge power (≥0)
    p_bat_dis_mw:       jax.Array   # battery discharge power (≥0)
    p_import_mw:        jax.Array   # grid import (≥0)
    p_export_mw:        jax.Array   # grid export (≥0)
    p_load_served_mw:   jax.Array   # load served (MW)
    p_load_unserved_mw: jax.Array   # unserved load (VOLL trigger)
    p_curtailed_mw:     jax.Array   # curtailed energy (PCC export limit + bat excess)

    # Costs (¥ per step — each is the step's ¥ contribution)
    c_import_yuan:                  jax.Array   # C_import = price_buy × P_import × Δt
    r_export_yuan:                  jax.Array   # R_export = price_sell × P_export × Δt
    c_energy_yuan:                  jax.Array   # C_E = C_import − R_export
    c_demand_shape_yuan:            jax.Array   # raw C_DC_shape (D13 reward-shaping)
    c_demand_charge_yuan:           jax.Array   # real monthly ¥ charge (D10/D21: 0 except month-end)
    c_degradation_yuan:             jax.Array
    c_curtail_yuan:                 jax.Array
    c_voll_yuan:                    jax.Array
    cost_total_real_yuan:           jax.Array   # D13 real-money total
    cost_total_reward_basis_yuan:   jax.Array   # D13 reward-basis total
    penalty_yuan:                   jax.Array   # SOC violation penalty
    soc_violation_mwh:              jax.Array   # energy overshoot (MWh)

    # Price
    price_buy_yuan_per_mwh:   jax.Array
    price_sell_yuan_per_mwh:  jax.Array
```

### 3.4 `SyntheticYear` type alias

```python
SyntheticYear = jax.Array   # shape (8760, 4), dtype float32
                             # columns: [wind_mps, irr_wm2, temp_c, load_mw]
```

---

## 4. Module-level constants (precomputed, not in jitted step)

### 4.1 `PRICE_TABLE_YPW` — shape [24], ¥/MWh

Indexed by `hour = t % 24`. Derived from §3.7 tariff via minute-accurate lookup at minute=0 (D8).
At Δt=1 h steps land on :00 so minute=0 always; the table is exact.

```
h=0..6:  250  (Valley: 23:00–7:00)
h=7:     450  (Mid: 7:00–8:00)
h=8:     620  (Peak: 8:00–10:30; 8:00 < 10:30)
h=9:     620  (Peak)
h=10:    620  (Peak: 10:00 < 10:30 boundary)
h=11:    780  (Critical peak: 10:30 ≤ 11:00 < 11:30)
h=12:    450  (Mid: 11:30 ≤ 12:00 < 18:00)
h=13:    450  (Mid)
h=14:    450  (Mid)
h=15:    450  (Mid)
h=16:    450  (Mid)
h=17:    450  (Mid)
h=18:    620  (Peak: 18:00–19:00)
h=19:    780  (Critical peak: 19:00–21:00)
h=20:    780  (Critical peak)
h=21:    620  (Peak: 21:00–23:00)
h=22:    620  (Peak)
h=23:    250  (Valley)
```

### 4.2 `MONTH_OF_STEP` — shape [8761], int32

`MONTH_OF_STEP[t]` = month index (0=Jan … 11=Dec) for step t.
Shape is 8761 (not 8760) so `MONTH_OF_STEP[state.t + 1]` is safe even at t=8759 (yields 11).
Precomputed from cumulative days-per-month: Jan=744 h, Feb=672 h (28 days), Mar=744, Apr=720, May=744, Jun=720, Jul=744, Aug=744, Sep=720, Oct=744, Nov=720, Dec=744.

---

## 5. Function specifications

### 5.1 `generate_year(key: jax.Array) -> SyntheticYear`

Generates one synthetic year of weather and load data. **Must be called once before training** and the result passed as `data` to every `step()`/`reset()` call.

**Returns:** float32 array of shape `(8760, 4)`:
- `[:, 0]` — wind speed at 10 m (m/s), clipped to `[0, 25]`
- `[:, 1]` — surface irradiance (W/m²), ≥ 0
- `[:, 2]` — ambient temperature (°C), unbounded
- `[:, 3]` — site load (MW), ≥ 0

**Wind (§4.1):**
```
wind[t] = clip(μ_w + A_d·sin(2π(t/24 − 0.25)) + 2·cos(2πt/8760) + AR1_w[t], 0, 25)
μ_w=6, A_d=2, AR1: ρ=0.95, σ_w=2 (innovations σ = σ_w·√(1−ρ²))
```

**Solar (§4.1):**
```
d = t // 24  (day of year, 0-based)
h = t % 24   (hour of day)
sunrise = 6 − 2·cos(2πd/365)
sunset  = 18 + 2·cos(2πd/365)
mid     = (sunrise + sunset) / 2
daylen  = sunset − sunrise
base    = G_peak · (1 − ((h − mid)/(daylen/2))²)   if sunrise ≤ h < sunset, else 0
cloud_factor = U(0.2, 0.8) with prob 0.3, else 1.0  (per time step)
seasonal = 0.7 + 0.3·cos(2π(d−172)/365)
irr[t]  = max(0, base · seasonal · cloud_factor)
G_peak  = 1000 W/m² (peak irradiance)
```

**Temperature (§4.1):**
```
temp[t] = 20 + 8·sin(2π(h−9)/24) + 15·cos(2π(d−200)/365) + N(0, 2)
```

**Load (§4.2, D19: ×100 the literal §4.2 figures):**
```
CDD = max(temp[t] − 18, 0)
HDD = max(18 − temp[t], 0)
dow_factor = [1,1,1,1,1,0.7,0.6][d % 7]     (Mon=1 … Sun=0.6)
hour_profile[h]: linearly scales 0.5 at midnight to 1.0 at noon, back to 0.5 at midnight
L_t = (base_kw · hour_profile[h] · dow_factor + α_kw·CDD + β_kw·HDD + AR1_load[t])
base_kw = 75_000, α_kw = 4_500, β_kw = 3_750  # D19: ×100 literal §4.2 figures
load_mw[t] = max(0, L_t / 1000.0)  # kW → MW, clip negative
AR1_load: ρ=0.8, σ_innovation = 5_000 kW · √(1−0.8²) = 3_000 kW
```

**RNG threading:** `jax.random.split` into sub-keys for each stochastic process; no Python-level randomness.

**Fixed seed → identical output.** Given the same `key`, `generate_year` must return bit-identical arrays.

---

### 5.2 `reset(key: jax.Array, params: EnvParams, data: SyntheticYear, episode_start: int = 0) -> tuple[EnvState, jax.Array]`

Initialises a new episode starting at `episode_start`.

**Returns:** `(state, obs)` where:
- `state.soc = params.soc_init`
- `state.month_peak = 0.0`
- `state.t = episode_start`
- `state.rng = key`
- `obs` is the 107-dim observation for `state` (§2.1, see §5.4)

---

### 5.3 `step(state: EnvState, action: jax.Array, params: EnvParams, data: SyntheticYear) -> tuple[EnvState, jax.Array, jax.Array, jax.Array, EnvInfo]`

**Returns:** `(new_state, obs, reward, done, info)`

Pure function — **jittable and vmappable with `in_axes=(0,0,None,None)`** (state/action per-env; params/data shared).

#### 5.3.1 Constraint enforcement order (§3.6 — must be exact)

```
1. parse/clip actions
2. battery dynamics (SOC clip + violation)
3. cap flows-to-load (proportional)
4. PCC export limit (proportional + curtailment)
5. grid import limit + VOLL
6. costs and reward
```

#### 5.3.2 Action parsing (§2.2)

`action` is a length-6 float32 vector:

```
a[0] = a_bat         ∈ [−1, 1]   clipped by jnp.clip
a[1] = f_sol_load    ∈ [0, 1]    clipped by jnp.clip
a[2] = f_sol_bat     ∈ [0, 1]    clipped by jnp.clip
a[3] = f_wind_load   ∈ [0, 1]    clipped by jnp.clip
a[4] = f_wind_bat    ∈ [0, 1]    clipped by jnp.clip
a[5] = f_bat_load    ∈ [0, 1]    clipped by jnp.clip
```

Source allocation renormalization (§3.6 rule #2):
```
s_solar = f_sol_load + f_sol_bat;  if s_solar > 1: f_sol_load /= s_solar; f_sol_bat /= s_solar
s_wind  = f_wind_load + f_wind_bat; similar renorm
```
Implemented as `jnp.where(s > 1, f/s, f)` — **no data-dependent Python branching**.

#### 5.3.3 Renewable generation (§3.1)

**Solar PV:**
```
irr_factor  = data[t, 1] / 1000.0
temp_factor = jnp.clip(1.0 + params.pv_k_T * (data[t, 2] − 25.0), 0.5, 1.2)
P_pv        = jnp.where(data[t, 1] <= 0, 0.0,
                        params.pv_capacity_mw * irr_factor * temp_factor
                        * params.pv_eta_inv * params.pv_degradation)
```

**Wind turbine:**
```
v_10m  = data[t, 0]
v_hub  = v_10m * (params.wind_hub_height_m / 10.0) ** 0.14
# power curve (jnp.where, no Python branching):
p_frac = jnp.where(v_hub < params.wind_v_cutin,  0.0,
         jnp.where(v_hub >= params.wind_v_cutout, 0.0,
         jnp.where(v_hub >= params.wind_v_rated,  1.0,
                   ((v_hub − params.wind_v_cutin) / (params.wind_v_rated − params.wind_v_cutin)) ** 3)))
P_wind = params.wind_rated_mw * p_frac
```

#### 5.3.4 Battery dynamics (§3.2, §3.6 rules #3–6)

**Charge mode** (a_bat ≥ 0):
```
P_ch_target    = a_bat * params.bat_power_mw
P_ren_to_bat   = P_pv * f_sol_bat + P_wind * f_wind_bat   (renewable allocated to battery)
P_ch_from_gen  = jnp.minimum(P_ren_to_bat, P_ch_target)
P_grid_to_bat  = jnp.maximum(0.0, P_ch_target − P_ch_from_gen)
P_ch           = P_ch_from_gen + P_grid_to_bat             (= P_ch_target)
# SOC clip:
max_P_ch       = (params.soc_max − state.soc) * params.bat_capacity_mwh / (params.bat_eta_ch * 1.0)
P_ch_actual    = jnp.minimum(P_ch, max_P_ch)
# violation (overshoot energy that would have been stored):
violation_mwh  = jnp.maximum(0.0, (P_ch − P_ch_actual) * params.bat_eta_ch * 1.0)
new_soc        = state.soc + params.bat_eta_ch * P_ch_actual / params.bat_capacity_mwh
```

**Discharge mode** (a_bat < 0):
```
P_dis_target   = −a_bat * params.bat_power_mw
max_P_dis      = (state.soc − params.soc_min) * params.bat_capacity_mwh * params.bat_eta_dis / 1.0
P_dis_actual   = jnp.minimum(P_dis_target, max_P_dis)
# violation (overshoot energy that would have been drawn from battery beyond soc_min):
violation_mwh  = jnp.maximum(0.0, (P_dis_target − P_dis_actual) / params.bat_eta_dis * 1.0)
new_soc        = state.soc − P_dis_actual / (params.bat_eta_dis * params.bat_capacity_mwh)
```

Combined with `jnp.where(a_bat >= 0.0, ...)` — single `step` handles both modes.

`new_soc` is clipped to `[soc_min, soc_max]` by construction (not an extra clip).

#### 5.3.5 Power flows

```
P_sol_to_load  = P_pv   * f_sol_load
P_sol_to_bat   = P_pv   * f_sol_bat
P_wind_to_load = P_wind * f_wind_load
P_wind_to_bat  = P_wind * f_wind_bat
P_bat_to_load  = f_bat_load * P_dis_actual    (discharge mode only; 0 in charge mode)
P_bat_to_grid  = P_dis_actual − P_bat_to_load (discharge mode only)
P_grid_to_bat  = P_grid_to_bat                (charge mode only; 0 in discharge mode)
```

**Load cap (§3.6 rule #7):**
```
P_to_load_total = P_sol_to_load + P_wind_to_load + P_bat_to_load
load_mw         = data[t, 3]
scale_to_load   = jnp.where(P_to_load_total > load_mw,
                             load_mw / P_to_load_total, 1.0)
P_sol_to_load   *= scale_to_load
P_wind_to_load  *= scale_to_load
P_bat_to_load   *= scale_to_load
excess_bat      = P_bat_to_load_pre_scale − P_bat_to_load  # re-routes to grid
P_bat_to_grid   += excess_bat
```

**Surplus renewable to grid (§3.3 rule #2):**
```
P_sol_to_grid  = P_pv   − P_sol_to_load  − P_sol_to_bat
P_wind_to_grid = P_wind − P_wind_to_load − P_wind_to_bat
(both ≥ 0 by construction after load-cap)
```

**PCC export limit (§3.6 rule #8):**
```
P_export_raw   = P_sol_to_grid + P_wind_to_grid + P_bat_to_grid
scale_export   = jnp.where(P_export_raw > params.grid_max_export_mw,
                            params.grid_max_export_mw / P_export_raw, 1.0)
P_sol_to_grid  *= scale_export
P_wind_to_grid *= scale_export
P_bat_to_grid  *= scale_export
P_export       = P_sol_to_grid + P_wind_to_grid + P_bat_to_grid
P_curtailed    = P_export_raw − P_export    (energy curtailed at PCC)
```

**Grid import (§3.6 rule #9):**
```
P_load_served  = P_sol_to_load + P_wind_to_load + P_bat_to_load
load_deficit   = jnp.maximum(0.0, load_mw − P_load_served)
P_import_raw   = load_deficit + P_grid_to_bat          (load deficit + battery-grid-charge)
P_import       = jnp.minimum(P_import_raw, params.grid_max_import_mw)
# if import capped: reduce grid-to-bat first, then shed load
P_grid_to_bat  = jnp.minimum(P_grid_to_bat, P_import − load_deficit)
P_grid_to_bat  = jnp.maximum(0.0, P_grid_to_bat)        # no negative
P_load_unserved = jnp.maximum(0.0, P_import_raw − params.grid_max_import_mw − P_grid_to_bat_reduction)
# Simpler: load_unserved = max(0, load_deficit - (P_import - P_grid_to_bat_actual))
```

> Implementation note: handle import capping in this order — reduce `P_grid_to_bat` first (down to 0), then if `load_deficit` still exceeds `max_import_mw`, the remainder is `P_load_unserved`. Pure `jnp.where`/`jnp.minimum` — no Python branching.

#### 5.3.6 Price lookup (D7, D8)

```
hour           = state.t % 24
price_buy      = PRICE_TABLE_YPW[hour]           # module constant, D8
rng_spread, new_rng = jax.random.split(state.rng)
noise          = jax.random.normal(rng_spread) * params.price_spread_sigma
eff_spread     = jnp.maximum(0.0, params.price_spread_yuan_per_mwh + noise)  # D7: clamp ≥ 0
price_sell     = jnp.maximum(0.0, price_buy − eff_spread)                    # D7: sell ≥ 0
```

#### 5.3.7 Costs (§3.4, D13)

```
C_import  = price_buy  * P_import  * 1.0          (¥, Δt=1h)
R_export  = price_sell * P_export  * 1.0
C_E       = C_import − R_export

C_DC_shape = params.demand_rate_yuan_per_mw_month * jnp.maximum(0.0, P_import − state.month_peak)
# (raw shape term; 2× weight applied by reward formula, not stored)

C_deg     = params.c_deg_yuan_per_mwh * (P_bat_ch_actual + P_dis_actual) * 1.0
C_curtail = params.curtail_yuan_per_mwh * P_curtailed * 1.0
C_VOLL    = params.voll_yuan_per_mwh   * P_load_unserved * 1.0
```

**Demand charge booking (D10, D21):**
```
is_month_end = (MONTH_OF_STEP[state.t + 1] != MONTH_OF_STEP[state.t])
is_terminal  = (state.t == 8759)  # year-end eval terminal flush
books_charge = is_month_end | is_terminal
new_month_peak = jnp.where(books_charge, P_import, jnp.maximum(state.month_peak, P_import))
C_demand_charge = jnp.where(books_charge, new_month_peak * params.demand_rate_yuan_per_mw_month, 0.0)
```
> D21: a sub-month training episode (episode_len=168) never crosses a calendar month boundary and t is never 8759, so `C_demand_charge = 0` throughout. This is correct by design — training pressure comes from `2·C_DC_shape` in the reward.

**Cost totals (D13):**
```
cost_total_real_yuan         = C_E + C_demand_charge + C_deg + C_curtail + C_VOLL
cost_total_reward_basis_yuan = C_E + 2.0*C_DC_shape + C_deg + C_curtail + C_VOLL
penalty_yuan = params.soc_penalty_yuan_per_mwh * violation_mwh
```

#### 5.3.8 Reward (§3.5)

```
reward = −(cost_total_reward_basis_yuan + penalty_yuan) * params.reward_scale
```

#### 5.3.9 State update and termination

```
new_state = EnvState(
    soc        = new_soc,
    month_peak = new_month_peak,
    t          = state.t + 1,
    rng        = new_rng,
)
done = (state.t == params.episode_len − 1)
```

---

### 5.4 Observation vector (§2.1)

107-dimensional float32 vector. Computed at the BEGINNING of the step (from `state` and `data[state.t]`), before any action is applied.

**Base (indices 0–10):**
```
obs[0]  = data[t, 0]             # wind_speed_mps (raw m/s)
obs[1]  = data[t, 1]             # irradiance_wm2 (raw W/m²)
obs[2]  = data[t, 2]             # temperature_c (raw °C)
obs[3]  = data[t, 3]             # load_mw (raw MW)
obs[4]  = state.soc              # SOC fraction [0.2, 0.9]
obs[5]  = PRICE_TABLE_YPW[hour]  # current price (raw ¥/MWh)
obs[6]  = state.month_peak / 500.0
obs[7]  = jnp.sin(2π * hour / 24.0)
obs[8]  = jnp.cos(2π * hour / 24.0)
obs[9]  = jnp.sin(2π * MONTH_OF_STEP[t] / 12.0)
obs[10] = jnp.cos(2π * MONTH_OF_STEP[t] / 12.0)
```

**Forecast (indices 11–106): 24 horizons × 4 features:**

For each horizon `h = 1 … 24`:
```
base = 11 + 4*(h-1)
t_fc = jnp.minimum(t + h, 8759)        # D9: clamp at end of year, no wraparound
σ_h  = params.forecast_sigma_max * h / 24.0   # D6: horizon-scaled noise

rng_fc, rng = jax.random.split(rng)     # per-horizon noise (4 draws)
ε = jax.random.normal(rng_fc, shape=(4,)) * σ_h

obs[base+0] = jnp.clip(data[t_fc,0]*(1+ε[0]), 0.0, 25.0) / 20.0       # wind/20
obs[base+1] = jnp.clip(data[t_fc,1]*(1+ε[1]), 0.0)        / 1000.0     # irr/1000
obs[base+2] = jnp.clip(data[t_fc,3]*1000.0*(1+ε[2]), 0.0) / 100_000.0  # load_kw/100000
obs[base+3] = jnp.clip(data[t_fc,4_price_column]*(1+ε[3]), 0.0)         # price ¥/MWh, clipped ≥ 0 (D6)
```

> **Note:** the 4th forecast feature is the tariff price at `t_fc`. Since `PRICE_TABLE_YPW` is a 24-element array, `price_at_t_fc = PRICE_TABLE_YPW[(t_fc % 24).astype(int)]`.

> VecNormalize (running mean/std, clip ±10) is applied by the training loop, not inside `step`. The obs returned by `step` are raw/lightly-normalized.

---

## 6. Deliberate deviations from §6

These match the reference implementation (D11 parity). Both impls apply the same fixes.

| Deviation | Old behavior (§6 bug) | New behavior | Decision |
|---|---|---|---|
| Forecast noise | `forecast_noise_std` stored but never applied | Horizon-scaled multiplicative Gaussian applied per feature per step | D6 |
| Forecast stride | `step_stride = hours×4` (assumed 15-min rows) | stride = 1 step (1-hour resolution); no wraparound (lax-clamped) | D9 |
| Price minute accuracy | Hour-only lookup; 10:30/11:30 boundaries wrong | `PRICE_TABLE_YPW[hour]` at Δt=1h resolves all boundaries correctly | D8 |
| Spread clamp | Spread + noise can be negative → sell > buy (arbitrage) | `eff_spread = max(0, spread + noise)`; `price_sell = max(0, price_buy - eff_spread)` | D7 |
| Demand charge double-count | Terminal step re-booked an already-charged month | `is_month_end` OR `t==8759`; no separate terminal re-book | D10 |
| Sub-month demand charge | Unclear; "terminal flush for partial month" | D21: sub-month episode books 0 (`c_demand_charge=0`); reward-shaping pressure via `2·C_DC_shape` | D21 |
| SOC bounds | Docs 10–90% | `[0.2, 0.9]` (D4); penalty rate = `params.soc_penalty_yuan_per_mwh` | D4 |
| Load scale | §4.2 literal: base=750 kW (contradicts §1/§3 site load 50–100 MW) | D19: base=75,000 kW; α=4,500 kW/°C; β=3,750 kW/°C; σ=5,000 kW | D19 |
| Forecast price clip | Price obs stored raw (can go negative with large noise) | `jnp.clip(price_noisy, 0.0, jnp.inf)` — D6: clipped ≥ 0 | D6 |

---

## 7. Out of scope

- SOC/temperature-dependent efficiency (D17 Tier 1 E2 — separate contract, toggle-OFF until added)
- Forecast-error regime switching (D17 Tier 1 E5 — separate contract)
- §8 composable assets (gas, electrolyzers, multi-site) — D2 sequencing
- VecNormalize / running-stat normalization — training layer
- Ramp-rate limits, reactive power, voltage, calendar aging — §3.6 fidelity boundary
- ONNX export — serving layer

---

## 8. Energy conservation invariant (by construction)

For each source `x ∈ {solar, wind, bat, grid}`:
```
P_x = P_x→load + P_x→bat + P_x→grid + P_x→curtailed
```
The step function ensures this holds at floating-point precision for every source by tracking all allocations explicitly and computing any remainder as `to_grid`. Tests assert this identity on every non-trivial step.
