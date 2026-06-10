# Contract: Reference Implementation (Gansu)

- **Status:** draft — awaiting backend-reviewer APPROVE
- **Spec:** REBUILD_SPEC.md §2.1–§2.2 (MDP/obs/action), §3.1–§3.7 (physics, costs, reward, tariff),
  §4.1–§4.2 (synthetic data generators), §6 (inconsistencies fixed per D3–D10)
- **Owner:** jax-env-engineer · **Reviewer:** backend-reviewer
- **Area:** env
- **Depends on decisions:** D3 (Δt=1 h), D4 (SOC 0.2–0.9), D5 (export 945 MW), D6 (forecast noise),
  D7 (spread clamp ≥ 0), D8 (minute-aware tariff), D9 (forecast stride = 1), D10 (demand charge once/month),
  D11 (fresh NumPy reference, not vendored legacy)
- **Telemetry schema dependency:** `contracts/shared/telemetry_schema.md` — **LOCKED v1.0.0 (PR #6)**.
  `StepResult` field names mirror the `env_step` payload; D12 (import limit per-site) and D13 (cost
  accounting split: real-money vs reward-basis) are incorporated below.

---

## Purpose

A **pure Python + NumPy** reference implementation of the §3 physics formulas and §4 synthetic data
generators (D11). It:

1. Is the ground truth against which the JAX implementation validates parity.
2. Is written **independently** of the JAX core — two implementations of the same spec means
   agreement validates spec-conformance, not copy-paste correctness.
3. Applies §6 bug-fixes D6–D10 (listed under *Deliberate deviations*).
4. Is **not** used for training — it is a test fixture only.

---

## Module structure

```
reference/                          # NOT legacy/
  __init__.py
  gansu_params.py                   # GansuParams dataclass with default Gansu constants
  tariff.py                         # get_price(hour, minute) → ¥/MWh (D8: minute-aware)
  gansu_env.py                      # all physics sub-functions + env_step + generate_year + get_obs
```

---

## Interfaces

### `GansuParams` (dataclass, all fields have defaults = Gansu site values)

```python
@dataclass
class GansuParams:
    # --- Wind fleet (Vestas V150-4.2 MW × fleet, total 615 MW rated) ---
    wind_p_rated_mw:    float = 615.0    # total fleet MW
    wind_v_cutin:       float = 3.0      # m/s
    wind_v_rated:       float = 12.0     # m/s
    wind_v_cutout:      float = 25.0     # m/s (inclusive cut-out: v ≥ v_cutout → 0)
    wind_hub_height_m:  float = 105.0    # hub height for shear calculation

    # --- Solar PV fleet (Trina Vertex N reference, 330 MW capacity) ---
    pv_capacity_mw:     float = 330.0
    pv_k_T:             float = -0.003   # /°C
    pv_eta_inv:         float = 0.97     # inverter efficiency
    pv_degradation:     float = 0.98     # year-1 degradation factor

    # --- Battery (294.5 MWh / 98.16 MW, D4: SOC bounds 0.2–0.9) ---
    bat_capacity_mwh:   float = 294.5
    bat_power_mw:       float = 98.16    # P_max_ch = P_max_dis
    bat_eta_ch:         float = 0.97
    bat_eta_dis:        float = 0.97
    soc_min:            float = 0.2
    soc_max:            float = 0.9

    # --- Grid connection (D5: physics export limit = 945 MW) ---
    grid_max_export_mw: float = 945.0
    grid_max_import_mw: float = 400.0

    # --- Cost parameters ---
    c_deg_yuan_per_mwh:             float = 10.0        # §3.4 battery throughput cost
    voll_yuan_per_mwh:              float = 20_000.0    # §3.4 value of lost load
    curtail_penalty_yuan_per_mwh:   float = 800.0       # §3.4
    demand_rate_yuan_per_mw_month:  float = 32_000.0    # §3.7 (32 ¥/kW·month × 1000)
    reward_scale:                   float = 1e-5        # §3.5 scale to O(1)

    # --- Spread (D7: clamp spread ≥ 0 before subtracting from buy price) ---
    price_spread_yuan_per_mwh:      float = 30.0
    price_spread_sigma:             float = 10.0

    # --- Forecast (D6: horizon-scaled noise; D9: stride = 1 step) ---
    forecast_horizon:   int   = 24
    forecast_sigma_max: float = 0.10     # 10% noise at horizon H_max
```

### `EnvState` (dataclass)

```python
@dataclass
class EnvState:
    soc:            float   # ∈ [soc_min, soc_max]
    month_peak_mw:  float   # max grid import this calendar month (MW); for demand charge
    t:              int     # step index into the 8760-element synthetic-year arrays
    rng:            np.random.Generator  # seeded; used for sell-price spread noise
```

### `StepResult` (dataclass)

All power flows in **MW**, all costs in **¥** (already × Δt=1 h).
Field names match the **LOCKED** `telemetry_schema.md` v1.0.0 `env_step` payload (PR #6).
Extra reference-only fields (`price_buy_yuan_per_mwh`, `price_sell_yuan_per_mwh`) are
NOT in the telemetry schema — they are internal to the reference implementation for
formula-level invariant checks and debugging.

```python
@dataclass
class StepResult:
    # Power generation (MW)
    p_wind_mw:              float   # gross wind fleet output
    p_solar_mw:             float   # gross solar fleet output

    # Power flows (MW) — by construction: each source fully accounted (§3.6 row 14)
    wind_to_load_mw:        float
    wind_to_bat_mw:         float
    wind_to_grid_mw:        float
    solar_to_load_mw:       float
    solar_to_bat_mw:        float
    solar_to_grid_mw:       float
    bat_to_load_mw:         float
    bat_to_grid_mw:         float
    grid_to_load_mw:        float
    grid_to_bat_mw:         float   # grid supplement for battery charging (§3.2)
    solar_curtailed_mw:     float   # solar share of export-limit curtailment (proportional)
    wind_curtailed_mw:      float   # wind share of export-limit curtailment (proportional)
    bat_curtailed_mw:       float   # battery discharge curtailed at export limit
    load_unserved_mw:       float   # §3.3 step 4, VOLL penalty

    # Battery
    p_bat_charge_mw:        float   # ≥ 0; charge XOR discharge (one is 0)
    p_bat_discharge_mw:     float   # ≥ 0
    soc_violation_mwh:      float   # stored-energy overshoot beyond SOC bound (§3.6 row 5)

    # PCC aggregates (MW)
    p_import_mw:            float   # ≤ grid_max_import_mw
    p_export_mw:            float   # ≤ grid_max_export_mw

    # Prices used this step (¥/MWh) — exposed for formula-level checks and debugging
    price_buy_yuan_per_mwh:         float   # TOU buy price (D8: minute-aware); ∈ {250, 450, 620, 780}
    price_sell_yuan_per_mwh:        float   # D7: max(0, price_buy − max(0, spread + noise)) ≥ 0

    # Per-step costs (¥, already × Δt = 1 h)
    c_import_yuan:                  float   # price_buy × p_import × Δt
    r_export_yuan:                  float   # price_sell × p_export × Δt  (D7: ≥ 0)
    c_energy_yuan:                  float   # C_import − R_export  (D13: c_import/r_export are display-only)
    c_demand_shape_yuan:            float   # RAW incremental C_DC_shape (D13: ×2 applied in reward, not stored)
    c_degradation_yuan:             float   # c_deg_rate × (p_ch + p_dis) × Δt
    c_curtail_yuan:                 float   # curtail_rate × (solar+wind+bat curtailed) × Δt
    c_voll_yuan:                    float   # voll_rate × load_unserved × Δt
    penalty_yuan:                   float   # 20 000 × soc_violation_mwh (D13: separate from cost totals)

    # Month-boundary demand charge (D10): 0 mid-month; = month_peak·demand_rate at month-end/episode-end
    c_demand_charge_yuan:           float   # real ¥ demand charge booked this step (≥ 0)

    # D13: two independently-reconstructable totals
    cost_total_real_yuan:           float   # real-money: C_E + c_demand_charge + C_deg + C_curtail + C_VOLL
    cost_total_reward_basis_yuan:   float   # reward-basis: C_E + 2·C_DC_shape + C_deg + C_curtail + C_VOLL

    # Reward
    reward:                         float   # = −(cost_total_reward_basis_yuan + penalty_yuan) × 1e-5 (§3.5, D13)

    # Updated state (for chaining steps)
    new_state:              EnvState
```

### Sub-functions

```python
def wind_power(v_10m: float, params: GansuParams) -> float:
    """Fleet wind output in MW from 10 m wind speed in m/s. Stateless."""

def solar_power(G: float, T: float, params: GansuParams) -> float:
    """Fleet PV output in MW from irradiance G (W/m²) and temperature T (°C). Stateless."""

def get_price(hour: int, minute: int) -> float:
    """Gansu TOU buy price in ¥/MWh. D8: minute-aware (not hour-only)."""

def compute_sell_price(price_buy: float, spread_noise: float,
                       params: GansuParams) -> float:
    """
    Sell price in ¥/MWh after D7 spread clamp.
    effective_spread = max(0, params.price_spread_yuan_per_mwh + spread_noise)
    price_sell       = max(0, price_buy − effective_spread)
    spread_noise is drawn by caller from N(0, params.price_spread_sigma); pass 0.0 for tests.
    """

def battery_step(
    soc: float,
    a_bat: float,          # ∈ [−1, 1]; ≥ 0 → charge, < 0 → discharge
    p_ren_to_bat: float,   # renewable power already allocated to battery this step (MW)
    params: GansuParams,
    dt: float = 1.0,       # hours
) -> tuple[float, float, float, float, float]:
    """
    Battery dynamics for one Δt.
    Returns: (soc_new, p_ch, p_dis, p_grid_to_bat, soc_violation_mwh)
      soc_new          — clipped to [soc_min, soc_max]
      p_ch             — actual charge power (MW), 0 when discharging
      p_dis            — actual discharge power (MW), 0 when charging
      p_grid_to_bat    — grid supplement to meet charging target (MW), 0 when discharging
      soc_violation_mwh — stored-energy overshoot beyond the hit bound (MWh ≥ 0)
    """

def env_step(
    state: EnvState,
    action: np.ndarray,           # shape (6,): [a_bat, f_s→l, f_s→b, f_w→l, f_w→b, f_b→l]
    weather: tuple[float, float, float],  # (wind_mps, irradiance_wm2, temperature_c)
    load: float,                  # MW
    params: GansuParams,
) -> StepResult:
    """Full env step. Enforces §3.6 constraint order (see Behavior section)."""

def generate_year(seed: int, params: GansuParams) -> dict[str, np.ndarray]:
    """
    Generate one synthetic year following §4.1 (weather) + §4.2 (load).
    Returns dict with shape-(8760,) arrays:
      'wind_mps'        — m/s, clipped to [0, 25]
      'irradiance_wm2'  — W/m², ≥ 0
      'temperature_c'   — °C (unbounded; realistic range ≈ −20 to 45)
      'load_mw'         — MW, ≥ 0
    All arrays are reproducible for the same seed.
    """

def get_obs(
    state: EnvState,
    data: dict[str, np.ndarray],  # from generate_year
    params: GansuParams,
    price_buy: float,             # ¥/MWh for the current step
) -> np.ndarray:
    """
    Build the 107-dim observation vector (§2.1) with D6 forecast noise.
    Shape: (107,) = 11 base dims + 24×4 forecast dims.
    RNG for noise lives in state.rng; calling this advances state.rng in-place.
    """
```

---

## Behavior

### `wind_power` (§3.1)

```
v_hub = v_10m · (hub_height_m / 10)^0.14       # power-law shear, open terrain
P = 0                                            if v_hub < v_cutin  OR  v_hub ≥ v_cutout
P = p_rated · ((v_hub − v_cutin) /
               (v_rated − v_cutin))³             if v_cutin ≤ v_hub < v_rated
P = p_rated                                      if v_rated ≤ v_hub < v_cutout
```

Cut-out is **inclusive** (`≥`). Cut-in is **exclusive** (cubic term is 0 at exactly v_cutin).

### `solar_power` (§3.1)

```
temp_factor = clamp(1 + k_T·(T − 25), 0.5, 1.2)
P = 0                                            if G ≤ 0
P = pv_capacity · (G / 1000) · temp_factor · pv_eta_inv · pv_degradation   otherwise
```

### `get_price` (§3.7, D8)

| Tier          | Condition (hour h, minute m)                                    | ¥/MWh |
|---------------|-----------------------------------------------------------------|-------|
| Critical peak | (h == 10 and m >= 30) or (h == 11 and m < 30)                  | 780   |
|               | h == 19 or h == 20                                              | 780   |
| Peak          | (8 ≤ h < 10) or (h == 10 and m < 30)                            | 620   |
|               | (h == 18) or (21 ≤ h < 23)                                      | 620   |
| Mid           | (h == 7) or (h == 11 and m >= 30) or (12 ≤ h < 18)             | 450   |
| Valley        | (23 ≤ h < 24) or (0 ≤ h < 7)                                   | 250   |

Condition evaluated in priority order: critical_peak → peak → mid → valley.
At Δt=1 h all steps land on :00, so minute=0 always; the function is still correct and future-proof.

### `compute_sell_price` (§3.4, D7)

```
effective_spread = max(0, spread + spread_noise)   # D7: clamp spread ≥ 0
price_sell       = max(0, price_buy − effective_spread)  # never negative
```

### `battery_step` (§3.2, §3.6 rows 3–5)

**Charging (a_bat ≥ 0):**
```
P_target       = a_bat · bat_power_mw
P_ch_from_gen  = min(p_ren_to_bat, P_target)       # renewable first (§3.6 row 6)
P_grid_to_bat  = max(0, P_target − P_ch_from_gen)
P_ch_desired   = P_ch_from_gen + P_grid_to_bat = P_target

# SOC clip (§3.6 row 5):
soc_unconstrained = soc + bat_eta_ch · P_ch_desired · dt / bat_capacity_mwh
if soc_unconstrained > soc_max:
    P_ch_actual     = (soc_max − soc) · bat_capacity_mwh / (bat_eta_ch · dt)
    soc_new         = soc_max
    soc_violation   = (soc_unconstrained − soc_max) · bat_capacity_mwh   # MWh of overshoot
else:
    P_ch_actual     = P_ch_desired
    soc_new         = soc_unconstrained
    soc_violation   = 0

P_grid_to_bat_actual = max(0, P_ch_actual − P_ch_from_gen)
```

**Discharging (a_bat < 0):**
```
P_dis_desired  = −a_bat · bat_power_mw

# SOC clip (§3.6 row 5):
soc_unconstrained = soc − P_dis_desired · dt / (bat_eta_dis · bat_capacity_mwh)
if soc_unconstrained < soc_min:
    P_dis_actual  = (soc − soc_min) · bat_capacity_mwh · bat_eta_dis / dt
    soc_new       = soc_min
    soc_violation = (soc_min − soc_unconstrained) · bat_capacity_mwh   # MWh of overshoot
else:
    P_dis_actual  = P_dis_desired
    soc_new       = soc_unconstrained
    soc_violation = 0

P_grid_to_bat_actual = 0  # no grid when discharging
```

The `soc_violation_mwh` formula is consistent for both directions:
`soc_violation = |ΔSOC_excess| · bat_capacity_mwh`

### `env_step` — constraint enforcement order (§3.6, mandatory sequence)

```
STEP 1 — Parse / clip actions
  a_bat      ← clip(action[0], −1, 1)
  f_s→l_raw  ← clip(action[1], 0, 1);  f_s→b_raw ← clip(action[2], 0, 1)
  f_w→l_raw  ← clip(action[3], 0, 1);  f_w→b_raw ← clip(action[4], 0, 1)
  f_b→l      ← clip(action[5], 0, 1)
  # Renorm per source if sum > 1 (§2.2, §3.6 row 2)
  for src in {solar, wind}:
      total_frac = f_src→l_raw + f_src→b_raw
      if total_frac > 1:
          f_src→l = f_src→l_raw / total_frac
          f_src→b = f_src→b_raw / total_frac
      else:
          f_src→l, f_src→b = f_src→l_raw, f_src→b_raw
  f_src→g = 1 − f_src→l − f_src→b   # unallocated goes to grid

STEP 2 — Generate renewable power
  p_wind  = wind_power(weather[0], params)
  p_solar = solar_power(weather[1], weather[2], params)

STEP 3 — Compute renewable routing
  p_ren_to_bat = p_solar·f_s→b + p_wind·f_w→b
  (initial, before load-cap scaling)

STEP 4 — Battery dynamics (SOC clip)
  soc_new, p_ch, p_dis, p_g2b, soc_viol = battery_step(state.soc, a_bat, p_ren_to_bat, params)
  # Bat discharge allocation
  p_bat_to_load = p_dis · f_b→l
  p_bat_to_grid = p_dis · (1 − f_b→l)

STEP 5 — Cap flows-to-load (§3.3 step 1, §3.6 row 7)
  p_wind_to_load_raw  = p_wind · f_w→l
  p_solar_to_load_raw = p_solar · f_s→l
  total_to_load = p_wind_to_load_raw + p_solar_to_load_raw + p_bat_to_load
  if total_to_load > load:
      scale = load / total_to_load
      p_wind_to_load  = p_wind_to_load_raw · scale
      p_solar_to_load = p_solar_to_load_raw · scale
      p_bat_to_load   = p_bat_to_load · scale
      # Battery discharge excess re-routes to grid (§3.3 step 1)
      p_bat_to_grid  += p_bat_to_load_orig · (1 − scale)
  else:
      p_wind_to_load  = p_wind_to_load_raw
      p_solar_to_load = p_solar_to_load_raw

STEP 6 — Renewable surplus → grid (§3.3 step 2)
  p_wind_to_grid  = p_wind  − p_wind_to_load  − p_wind · f_w→b_actual
  p_solar_to_grid = p_solar − p_solar_to_load − p_solar · f_s→b_actual
  (f_src→b_actual accounts for any re-scaling in battery_step if SOC clipped)

STEP 7 — PCC export limit (§3.3 step 3, §3.6 row 8)
  total_export = p_wind_to_grid + p_solar_to_grid + p_bat_to_grid
  if total_export > grid_max_export_mw:
      scale_exp = grid_max_export_mw / total_export
      # Per-source curtailment: proportional to each source's pre-curtailment grid flow.
      # Computed BEFORE scaling so values are derived from the un-clipped flows.
      wind_curtailed_mw  = p_wind_to_grid  · (1 − scale_exp)
      solar_curtailed_mw = p_solar_to_grid · (1 − scale_exp)
      bat_curtailed_mw   = p_bat_to_grid   · (1 − scale_exp)
      # Then scale each flow down to the export limit
      p_wind_to_grid  *= scale_exp
      p_solar_to_grid *= scale_exp
      p_bat_to_grid   *= scale_exp
  else:
      wind_curtailed_mw  = 0.0
      solar_curtailed_mw = 0.0
      bat_curtailed_mw   = 0.0

STEP 8 — Grid import (§3.3 step 4, §3.6 row 9)
  load_deficit  = load − p_wind_to_load − p_solar_to_load − p_bat_to_load
  grid_to_load_required = max(0, load_deficit)
  p_import_required     = grid_to_load_required + p_g2b          # load first, then battery
  if p_import_required > grid_max_import_mw:
      available_for_load = min(grid_to_load_required,
                               max(0, grid_max_import_mw − p_g2b))  # load served first
      if grid_max_import_mw < p_g2b:
          # even battery charging must be curtailed; load is shed
          p_g2b_actual = grid_max_import_mw
          grid_to_load = 0
      else:
          p_g2b_actual = p_g2b
          grid_to_load = min(grid_to_load_required, grid_max_import_mw − p_g2b)
      load_unserved = load − p_wind_to_load − p_solar_to_load − p_bat_to_load − grid_to_load
  else:
      p_g2b_actual  = p_g2b
      grid_to_load  = grid_to_load_required
      load_unserved = 0
  p_import = grid_to_load + p_g2b_actual

STEP 9 — Prices
  price_buy  = get_price(hour_of_day, minute_of_hour)        # D8: minute-aware
  spread_noise = state.rng.normal(0, params.price_spread_sigma)
  price_sell = compute_sell_price(price_buy, spread_noise, params)

STEP 10 — Costs and reward (§3.4, §3.5, D10, D13)
  # 10a. Intermediate cost components
  C_import  = price_buy  · p_import  · dt
  R_export  = price_sell · p_export  · dt      (p_export = sum of grid flows)
  C_E       = C_import − R_export
  C_DC_shape = demand_rate · max(0, p_import − state.month_peak_mw)  # RAW, stored without ×2 (D13)
  new_month_peak = max(state.month_peak_mw, p_import)
  C_deg     = c_deg · (p_ch + p_dis) · dt
  C_curtail = curtail_penalty · (wind_curtailed_mw + solar_curtailed_mw + bat_curtailed_mw) · dt
  C_VOLL    = voll · load_unserved · dt
  penalty   = 20_000 · soc_viol_mwh

  # 10b. Month-boundary demand charge (D10) — must be computed BEFORE cost_total_real below.
  # month_of_step is a precomputed int array shape (8760,): month_of_step[t] ∈ {0..11}
  # (computed ONCE at env init from cumulative days-per-month; no datetime in jitted step).
  is_terminal  = (state.t == 8759)           # last step of the synthetic year
  next_t       = min(state.t + 1, 8759)
  is_month_end = (month_of_step[next_t] != month_of_step[state.t]) OR is_terminal
  if is_month_end:
      c_demand_charge_yuan = new_month_peak × demand_rate   # real monthly demand charge (≥ 0)
      new_month_peak       = 0.0                            # reset for next month
  else:
      c_demand_charge_yuan = 0.0   # NOT charged mid-month (D10: no per-step accrual)
  # Anti-double-count (D10 fix): the charge is booked exactly ONCE via is_month_end.
  # No separate "terminal flush" — the is_terminal flag in is_month_end handles it.
  # Truncated episode (< 8760 steps): partial-month charge is NOT booked.

  # 10c. D13: two separate cost totals (c_demand_charge_yuan now defined above)
  cost_total_reward_basis = C_E + 2·C_DC_shape + C_deg + C_curtail + C_VOLL  # ×2 applied here
  cost_total_real         = C_E + c_demand_charge_yuan + C_deg + C_curtail + C_VOLL

  reward = −(cost_total_reward_basis + penalty) · reward_scale
```

### `generate_year` (§4.1 and §4.2)

**Wind (§4.1):**
```
η[0]   = 0, η[t] = 0.95·η[t−1] + sqrt(1−0.95²)·N(0,1)   # AR1, ρ=0.95
wind[t] = clip(6 + 2·sin(2π(t/24 − 0.25)) + 2·cos(2πt/8760) + η[t]·2, 0, 25)
```

**Solar (§4.1):**
```
d = t // 24   (day of year, 0-indexed)
h = t % 24    (hour of day, 0-indexed)
sunrise[d] = 6  − 2·cos(2πd/365)
sunset[d]  = 18 + 2·cos(2πd/365)
mid[d]     = (sunrise[d] + sunset[d]) / 2
daylen[d]  = sunset[d] − sunrise[d]
base[t] = G_peak · max(0, 1 − ((h − mid[d]) / (daylen[d]/2))²)   # G_peak = 1000 W/m²
seasonal[d] = 0.7 + 0.3·cos(2π(d−172)/365)
cloud[t] = U(0.2, 0.8) with prob 0.3, else 1.0   (per-step, from seeded RNG)
irradiance[t] = max(0, base[t] · seasonal[d] · cloud[t])
```

**Temperature (§4.1):**
```
temp[t] = 20 + 8·sin(2π(h−9)/24) + 15·cos(2π(d−200)/365) + N(0,2)
```

**Load (§4.2 — ×100 scaling per D19):**

> **D19 (rl-architect, binding, merged to main):** The §4.2 kW parameters are scaled by ×100
> to produce site-scale load: base **75,000 kW (75 MW)**, α **4,500 kW/°C**,
> β **3,750 kW/°C**, σ\_AR1 **5,000 kW**. This is consistent with the `load_kw/100000`
> obs normalization and the stated 50–100 MW site range. Both the NumPy reference and
> the JAX core must apply D19 parameters.

```
φ[0] = 0, φ[t] = 0.8·φ[t−1] + sqrt(1−0.8²)·N(0,1)   # AR1, ρ=0.8
dow_factor = [1,1,1,1,1, 0.7, 0.6]   (Mon–Sun; d % 7)
hour_profile[h]:  0.5 for h ∈ {0..5, 22, 23}, 0.8 for h ∈ {6,21}, 1.0 for h ∈ {8..17}, etc.
    (fully defined in implementation; spec intent: 0.5 nights → 1.0 work hours)
CDD[t] = max(temp[t] − 18, 0)
HDD[t] = max(18 − temp[t], 0)
L[t]   = (75_000·hour_profile[h]·dow_factor[d%7] + 4_500·CDD[t] + 3_750·HDD[t] + φ[t]·5_000)
load_mw[t] = max(0, L[t]) / 1000    # kW → MW; clip to ≥ 0
```

### `get_obs` (§2.1, D6, D9)

```
# Base block (11 dims):
obs[0] = wind_mps
obs[1] = irradiance_wm2
obs[2] = temperature_c
obs[3] = load_mw
obs[4] = soc
obs[5] = price_buy (¥/MWh)
obs[6] = month_peak_mw / 500
obs[7] = sin(2π·h/24)
obs[8] = cos(2π·h/24)
obs[9] = sin(2π·month_of_year/12)
obs[10]= cos(2π·month_of_year/12)

# Forecast block (24 × 4 = 96 dims, D6: horizon-scaled noise, D9: stride=1):
for h_idx in range(1, 25):    # h_idx = 1..24, stride=1 (D9)
    t_future = t + h_idx      # clamp to [0, 8759] if near end of year
    σ_h = σ_max · h_idx / H_max   # D6: 10% at horizon 24, linear in h
    x_true = data at t_future
    x_noisy = x_true · (1 + N(0, σ_h))   # multiplicative
    each noised feature clipped to its physical range
    obs[11 + 4*(h_idx-1) + 0] = clip(x_noisy_wind, 0, 25) / 20
    obs[11 + 4*(h_idx-1) + 1] = clip(x_noisy_irr, 0, 1000) / 1000
    obs[11 + 4*(h_idx-1) + 2] = clip(x_noisy_load_kw, 0, 200_000) / 100_000
    obs[11 + 4*(h_idx-1) + 3] = x_noisy_price   (raw ¥/MWh; further normalized by VecNormalize)

Total: 11 + 96 = 107 dims ✓
```

---

## Units & ranges summary

| Variable                | Unit     | Range / notes                           |
|-------------------------|----------|-----------------------------------------|
| Wind speed              | m/s      | [0, 25] (generator clips)               |
| Irradiance              | W/m²     | [0, 1000]                               |
| Temperature             | °C       | unbounded; realistic −20 to 45          |
| Load                    | **MW**   | [0, ∞); site nominal 50–100 MW          |
| Power flows             | **MW**   | ≥ 0                                     |
| SOC                     | fraction | [0.2, 0.9] (D4)                         |
| Price (buy/sell)        | ¥/MWh    | buy ∈ {250, 450, 620, 780}; sell ≤ buy  |
| Costs / reward raw      | ¥        | per step (already × Δt = 1 h)           |
| Reward                  | unitless | ≈ O(1) after ×1e-5                      |
| Demand rate             | ¥/MW·month | 32 000                                |
| Violation penalty rate  | ¥/MWh    | 20 000 (same as VOLL rate)              |

---

## Edge behavior (testable commitments)

1. **v_hub == v_cutin** → P_wind = 0 (cubic term is exactly 0).
2. **v_hub == v_cutout** → P_wind = 0 (cut-out is inclusive).
3. **G ≤ 0** → P_solar = 0, regardless of temperature.
4. **temp_factor clamp:** T = −80°C → factor = 1.2; T = 400°C → factor = 0.5.
5. **SOC exactly at soc_max with a_bat > 0** → P_ch = 0, soc_violation > 0.
6. **SOC exactly at soc_min with a_bat < 0** → P_dis = 0, soc_violation > 0.
7. **a_bat < 0** → P_ch = 0 (charge XOR discharge, no simultaneous).
8. **Price at 10:29** → peak (620); **10:30** → critical peak (780). D8.
9. **Spread noise = −40** → effective_spread = 0 → price_sell = price_buy (D7).
10. **Price_buy = 20, spread = 30** → price_sell = 0 (clamped, D7).
11. **Export exceeds limit** → proportional curtailment, `solar_curtailed_mw` + `wind_curtailed_mw` + `bat_curtailed_mw` > 0.
12. **Import exceeds 400 MW** → load shed, C_VOLL > 0.
13. **Per-source energy conservation (producer assert, §3.6 row 14):**
    - `wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed == p_wind_mw` (within 1e-9 MW)
    - `solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed == p_solar_mw` (within 1e-9 MW)
14. **Determinism:** same seed → same year arrays; same state + action → same StepResult.
15. **`c_demand_charge_yuan`** is 0 on every step except the month-end/episode-end flush (D10 — the real monthly demand charge `month_peak · demand_rate` is booked exactly once per calendar month; `c_demand_shape_yuan` is the incremental reward-shaping signal every step).

---

## Deliberate deviations from old code (§6 fixes; QA parity tests depend on this list)

| Fix | Old (buggy) | New (this implementation) | Binding decision |
|-----|-------------|---------------------------|-----------------|
| **D6 forecast noise** | `forecast_noise_std` stored but never applied; agent sees perfect future | Horizon-scaled multiplicative noise: σ_h = σ_max·h/H_max = 0.10·h/24; applied in `get_obs` | D6 |
| **D7 spread clamp** | `30 + N(0,10)` can go negative → price_sell > price_buy (arbitrage hole) | `effective_spread = max(0, spread + noise)`; then `price_sell = max(0, …)` | D7 |
| **D8 tariff lookup** | `_get_price(hour)` drops minute — 10:30/11:30 boundaries wrong in forecasts | `get_price(hour, minute)`: minute-aware; 10:30 and 11:30 boundaries correct | D8 |
| **D9 forecast stride** | `step_stride = hours × 4` (assumes 15-min rows) → samples t+4h…t+96h; wraps via `% len(episode_data)` near end | Stride = 1 step; samples t+1…t+24; near end clamps to year array bounds (no wrap) | D9 |
| **D10 demand charge** | `info['total_demand_charge']` double-counts final month on terminal step | Demand charge booked exactly once per calendar month; terminal step does NOT re-book an already-charged month | D10 |
| **Δt** | Config/docs say 15 min; `EnergyStorageEnvV2` uses 1 h but stride assumes 15 min | Δt = 1 h throughout — all formulas, forecast indexing, cost per-step | D3 |
| **SOC bounds** | Docs say 10–90%; code uses 20–90% | SOC ∈ [0.2, 0.9] | D4 |
| **Export limit** | `GridParams.max_export_mw=945` vs YAML 200 MW | Physics limit = 945 MW (D5) | D5 |

---

## Out of scope

- Calendar aging, SOC-dependent efficiency (degradation is throughput-linear only).
- Ramp-rate limits, transformer/line losses, reactive power, grid-frequency services.
- VecNormalize running stats (those live in the training loop, not this reference env).
- §8 composable asset library (gas, electrolyzer) — Gansu config is §3 only.

---

## Invariant helpers (task #21)

Reusable pytest assertions under `src/energy_go/testing/invariants.py`.  These helpers
are framework-agnostic (duck typing, attribute access) — they work with the NumPy
reference `StepResult` and the future JAX `StepResult` NamedTuple as long as field names
match this contract.  They are the second consumer after the reference implementation
tests (qa-engineer uses them in the `qa-verification` skill).

### `assert_energy_conserved(result, *, tol=1e-5)`

Asserts per-source power balance (§3.6 row 14):

| Source | Identity |
|--------|----------|
| Wind   | `wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed == p_wind_mw` |
| Solar  | `solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed == p_solar_mw` |
| Battery discharge | `bat_to_load + bat_to_grid + bat_curtailed == p_bat_discharge_mw` |
| Grid import | `grid_to_load + grid_to_bat == p_import_mw` |

All flow fields must be ≥ −1e-9 (physical non-negativity).

Use `tol=1e-5` for float64 NumPy reference; `tol=1e-4` for float32 JAX.

### `assert_cost_identities(result, params, *, tol=1e-9)`

Asserts all D13 algebraic cost identities for one step:

1. `c_energy == c_import − r_export`
2. `cost_total_reward_basis == c_energy + 2·c_demand_shape + c_degradation + c_curtail + c_voll`
3. `cost_total_real == c_energy + c_demand_charge + c_degradation + c_curtail + c_voll`
4. `reward == −(cost_total_reward_basis + penalty) × reward_scale`
5. `penalty == 20_000 × soc_violation_mwh`
6. `c_curtail == (solar_curtailed + wind_curtailed + bat_curtailed) × curtail_penalty × Δt`
7. `c_voll == load_unserved × voll × Δt`
8. `r_export ≥ 0` (D7 sell-price clamp)
9. `c_degradation == c_deg_rate × (p_bat_charge + p_bat_discharge) × Δt`

Use `tol=1e-9` for float64 (algebraic identity); `tol=1e-6` for float32 JAX.

### `assert_physical_bounds(result, params)`

Asserts hard physical constraints:

| Constraint | Value | Decision |
|-----------|-------|----------|
| SOC ∈ [soc_min, soc_max] | [0.2, 0.9] | D4 |
| p_bat_charge_mw ∈ [0, bat_power_mw] | [0, 98.16] MW | §3.2 |
| p_bat_discharge_mw ∈ [0, bat_power_mw] | [0, 98.16] MW | §3.2 |
| charge XOR discharge | not both > 0 | §3.6 row 4 |
| p_export_mw ≤ grid_max_export_mw | ≤ 945 MW | D5 |
| p_import_mw ≤ grid_max_import_mw | ≤ 400 MW | D12 |

### `assert_soc_dynamics(old_soc, result, params, *, tol=1e-5)`

Verifies the SOC update formula (§3.2) and, when `soc_violation_mwh > 0`,
that the new SOC is exactly at the clipped bound and the violation magnitude
is consistent with `|ΔSOC_excess| × bat_capacity_mwh`.

### `run_determinism_check(step_fn, make_state_fn, action, weather, load, params, *, n_runs=3, tol=1e-12)`

Calls `step_fn(make_state_fn(), action, weather, load, params)` n_runs times and
asserts all numeric fields in `StepResult` are identical across runs (to tolerance `tol`).
A determinism failure means either the function has hidden mutable state or the RNG seeding
is not reproducible.

### `run_episode(step_fn, initial_state, action_or_actions, data, params, *, n_steps, start_t=0) → list`

Runs n_steps of `step_fn` chaining `new_state`, returns list of `StepResult`.
`action_or_actions` may be a single action (broadcast) or a list of per-step actions.

### `assert_episode_invariants(results, params, *, energy_tol=1e-5, cost_tol=1e-9)`

Calls `assert_energy_conserved`, `assert_cost_identities`, and `assert_physical_bounds`
on every element of `results`.  Fails immediately on the first violation, reporting
the step index.

### Tolerance guide

| Scenario | energy_tol | cost_tol |
|----------|-----------|---------|
| NumPy reference (float64) | 1e-5 | 1e-9 |
| JAX float32 | 1e-4 | 1e-6 |
| JAX parity vs NumPy | 1e-4 | 1e-6 |
