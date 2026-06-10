# Energy GO — Rebuild Specification

Everything you need to rebuild the system from scratch: methodology, formulas, parameters, and a language/stack recommendation.

> Source of truth extracted from: `python/env/power_env.py`, `gym_energy_router/core/{reward,renewable_models,weather_generator,load_generator}.py`, `python/agents/train_sac.py`, `config/site_gansu.yaml`.

---

## 1. What the system is

An RL agent (SAC) controls a grid-connected **wind + solar + battery** plant (modeled on Gansu/Jiuquan, China) to minimize total electricity cost:

```
minimize  Σ_t [ Energy_Cost + Demand_Charge + Battery_Degradation + Penalties ]
```

via **time-of-use arbitrage** (charge at ¥0.25 valley, discharge at ¥0.78 critical peak), **peak shaving** (demand charge ¥32/kW·month on monthly max grid import), and **renewable routing** (self-consume vs. sell vs. store).

**Site totals (Gansu config):** Wind 615 MW, Solar 330 MW, Battery 294.5 MWh / 98.16 MW, Load 50–100 MW, PCC export limit 945 MW (200 MW in the YAML grid section), import limit 400 MW.

---

## 2. MDP specification

| Element | Value |
|---|---|
| Timestep `Δt` | 1 hour in `EnergyStorageEnvV2` (15-min in design docs / data pipeline — pick one and be consistent) |
| Episode | Training: 7 days (168 steps), random start in synthetic year. Eval: 365 days (8760 steps) |
| Discount γ | 0.999 |
| Observation | 11 base dims + 24×4 forecast dims = **107** |
| Action | **6-dim continuous** (see §4) |

### 2.1 Observation vector

Base (11):
```
[ wind_speed_mps, irradiance_wm2, temperature_c, load_MW,
  SOC, current_price, month_peak/500,
  sin(2πh/24), cos(2πh/24), sin(2πm/12), cos(2πm/12) ]
```

Forecast (24 steps × 4 vars, 1-hour resolution over next 24 h), normalized:
```
[ wind/20, irradiance/1000, load_kw/100000, price ]  × 24
```
Forecast noise grows linearly with horizon (config: 10% at max horizon) — agent must plan under uncertainty.

Observations are further normalized at training time by `VecNormalize` (running mean/std, clip ±10).

### 2.2 Action vector (explicit flow control, "Energy Router")

```
a[0] = a_bat            ∈ [-1, 1]   battery: + charge, − discharge (× max power)
a[1] = f_solar→load     ∈ [0, 1]
a[2] = f_solar→bat      ∈ [0, 1]
a[3] = f_wind→load      ∈ [0, 1]
a[4] = f_wind→bat       ∈ [0, 1]
a[5] = f_bat→load       ∈ [0, 1]   (remainder of discharge goes to grid)
```
If `f_x→load + f_x→bat > 1`, renormalize to sum 1. Unallocated renewable goes to grid.

---

## 3. Physics & cost formulas

### 3.1 Renewable generation

**Solar PV** (Trina Vertex N reference):
```
P_pv = P_capacity · (G / 1000) · clamp(1 + k_T·(T − 25), 0.5, 1.2) · η_inv · D
k_T = −0.003 /°C,  η_inv = 0.97,  D = 0.98 (year-1 degradation)
P_pv = 0 if G ≤ 0
```

**Wind turbine** (Vestas V150-4.2MW reference):
```
v_hub = v_10m · (h_hub / 10)^0.14          # power-law shear, open terrain
P_wind = 0                                  if v < v_cutin (3) or v ≥ v_cutout (25)
       = P_rated · ((v − v_cutin)/(v_rated − v_cutin))³   if v_cutin ≤ v < v_rated (12)
       = P_rated                            if v_rated ≤ v < v_cutout
```

### 3.2 Battery dynamics

```
ΔSOC = (η_ch·P_ch − P_dis/η_dis) · Δt / E_capacity
η_ch = η_dis = 0.97   (RTE ≈ 94%)
SOC ∈ [soc_min, soc_max] = [0.2, 0.9]   (docs say 0.1–0.9; code uses 0.2)
```
On boundary overshoot: clip P_ch/P_dis so SOC lands exactly on the limit, record `violation_mwh` = overshoot energy → penalized in reward.

Charging priority: renewable-allocated power first, grid tops up the remainder:
```
a_bat ≥ 0:  P_target = a_bat · P_max_ch
            P_ch_from_gen = min(P_ren→bat_alloc, P_target)
            P_grid→bat    = max(0, P_target − P_ch_from_gen)
a_bat < 0:  P_dis = −a_bat · P_max_dis
            P_bat→load = f_bat→load · P_dis ;  P_bat→grid = rest
```

### 3.3 Power balance & constraints (per step)

```
1. Cap power-to-load: if Σ(solar→load, wind→load, bat→load) > load,
   scale all three down proportionally; battery excess re-routes to grid.
2. Surplus renewable → grid: P_x→grid = max(0, P_x − P_x→load − P_x→bat)
3. PCC export limit: if total export > max_export_mw,
   scale all exporters proportionally; the cut energy is CURTAILED.
4. Import: P_import = load_deficit + P_grid→bat, capped at max_import_mw.
   Load served first; battery charging reduced next;
   remaining unmet load = P_load_unserved (VOLL penalty).
```

### 3.4 Costs (¥, per step)

```
C_import   = price_buy · P_import · Δt
price_sell = max(0, price_buy − (spread + N(0, σ_spread)))   # spread=30, σ=10 ¥/MWh
R_export   = price_sell · P_export · Δt
C_E        = C_import − R_export

C_DC_shape = demand_rate · max(0, P_import − month_peak)     # incremental peak shaping
             month_peak resets each calendar month; full charge
             month_peak · demand_rate booked at month end / episode end

C_deg      = c_deg · (P_ch + P_dis) · Δt                     # throughput model, c_deg = 10 ¥/MWh

C_curtail  = (ren_curtailed + bat_curtailed) · 800 ¥/MWh · Δt
C_VOLL     = P_unserved · 20000 ¥/MWh · Δt
```

### 3.5 Reward

```
penalty = penalty_base + 20000 · |soc_violation_mwh|         (if SOC limit hit)

reward = −( C_E + 2.0·C_DC_shape + C_deg + C_curtail + C_VOLL ) − penalty
reward *= 1e-5                                               # scale to ~O(1) for SAC
```

### 3.6 Constraint & restriction rules (consolidated)

Every physical restriction in the env, what enforces it, and what happens on violation. **The enforcement order is part of the spec** — steps run in exactly this sequence, and proportional scaling at one stage feeds the next:

```
parse/clip actions → battery dynamics (SOC clip) → cap flows-to-load
→ PCC export limit → grid import limit → costs/penalties
```

| # | Restriction | Limit | Enforcement | On violation |
|---|---|---|---|---|
| 1 | Action bounds | a_bat ∈ [−1,1], fractions ∈ [0,1] | Hard clip | — (silent) |
| 2 | Source allocation | f_x→load + f_x→bat ≤ 1 per source | Renormalize proportionally to sum 1 | — (silent) |
| 3 | Battery power | P_ch ≤ 98.16 MW, P_dis ≤ 98.16 MW | Structural (action × max power) | — |
| 4 | Charge XOR discharge | Battery never charges and discharges in one step | Structural (sign of a_bat selects mode) | — |
| 5 | SOC bounds | SOC ∈ [0.2, 0.9] | Clip P_ch/P_dis so SOC lands exactly on the bound | **Penalty** 20 000 ¥ per MWh of overshoot + violation flag |
| 6 | Charging source priority | Renewable-allocated power charges first, grid tops up | Structural ordering | — |
| 7 | Load cannot be over-served | Σ(solar,wind,bat)→load ≤ load | Scale all three down proportionally; battery excess re-routes to grid | — (silent) |
| 8 | PCC export limit | total export ≤ 945 MW (code) / 200 MW (YAML — reconcile!) | Scale all exporters proportionally | **Curtailment penalty** 800 ¥/MWh on the cut energy |
| 9 | Grid import limit | import ≤ 400 MW | Load served first, then battery charging reduced, then load shed | **VOLL penalty** 20 000 ¥/MWh on unserved load |
| 10 | No negative sell price | price_sell ≥ 0 | `max(0, price − spread)` | — |
| 11 | Wind operating range | 0 output below 3 m/s and at/above 25 m/s cut-out | Power curve | — |
| 12 | PV temperature derating | temp factor clamped to [0.5, 1.2] | Hard clamp | — |
| 13 | Non-negative load | load ≥ 0 | Clamp in generator | — |
| 14 | Energy conservation | Each source fully accounted: P_x = to_load + to_bat + to_grid + curtailed | By construction | — (assert in tests) |

Two enforcement styles, deliberately mixed:
- **Hard projection (silent):** infeasible actions are scaled/clipped into the feasible set with no penalty (#1, 2, 7, 8-scaling). The agent never sees an invalid state, but also gets no gradient signal that it asked for something impossible.
- **Penalized outcomes:** physical consequences with real cost — SOC overshoot, curtailed energy, unserved load (#5, 8, 9) — flow into the reward so the agent learns to avoid them.

**Not modeled** (know the fidelity boundary before extending): no ramp-rate limits on battery or grid exchange, no transformer/line losses, no reactive power or voltage, no battery calendar aging or SOC-dependent efficiency (degradation is throughput-linear only), no minimum import contracts, no grid-frequency services. If real-site rules need any of these, they slot in as extra clamps/penalties at the marked stages.

> JAX port note: every "scale proportionally" and "clip" above is already a pure `jnp.where`/`clip` — the table maps 1:1 onto the jitted step function, in the same order.

### 3.7 Tariff (Gansu 4-tier TOU, ¥/MWh, buy side)

| Tier | Hours (code: `_get_price`) | Price |
|---|---|---|
| Critical peak | 10:30–11:30, 19:00–21:00 | 780 |
| Peak | 8:00–10:30, 18:00–19:00, 21:00–23:00 | 620 |
| Mid | 7:00–8:00, 11:30–18:00 | 450 |
| Valley | 23:00–7:00 | 250 |

Demand charge: **32 000 ¥/MW·month**. Feed-in tariffs: wind 290, solar 260, storage 350 ¥/MWh (used when spread mode is off).

---

## 4. Synthetic data generators

All stochastic processes use a seeded RNG; one synthetic year (8760 h) is generated once, episodes are random 7-day slices (built-in domain randomization).

### 4.1 Weather

```
wind(t)  = μ_w + A_d·sin(2π(t/24 − 0.25)) + 2·cos(2πt/8760) + AR1(ρ=0.95)·σ_w
           μ_w=6, σ_w=2, A_d=2;  clip to [0, 25] m/s

solar(t) : sunrise = 6 − 2cos(2πd/365), sunset = 18 + 2cos(2πd/365)
           base = G_peak·(1 − ((h−mid)/(daylen/2))²)         # parabolic day profile
           × seasonal (0.7 + 0.3cos(2π(d−172)/365))
           × cloud: with p=0.3, factor ~ U(0.2, 0.8), else 1

temp(t)  = 20 + 8·sin(2π(h−9)/24) + 15·cos(2π(d−200)/365) + N(0,2)

AR1 noise: x_t = ρ·x_{t−1} + sqrt(1−ρ²)·N(0,1)
```

### 4.2 Load (CDD/HDD model)

```
L_t = base·hour_profile[h]·dow_factor[d] + α·CDD(T) + β·HDD(T) + AR1(ρ=0.8, σ=50)
CDD = max(T − 18, 0);  HDD = max(18 − T, 0)
base = 750 kW, α = 45 kW/°C, β = 37.5 kW/°C
dow = (1,1,1,1,1, 0.7, 0.6);  hour_profile: 0.5 nights → 1.0 work hours
```

---

## 5. Training methodology

- **Algorithm:** SAC (stable-baselines3), `MlpPolicy`
- **Hyperparameters:** lr 1e-4, γ 0.999, batch 512, buffer 1e6, τ 0.005, `ent_coef="auto"`, train_freq 1, gradient_steps 1, 500k timesteps, 4 parallel envs (`DummyVecEnv`)
- **Normalization:** `VecNormalize(norm_obs=True, norm_reward=True, clip 10)` — stats saved with the model (`vec_normalize.pkl`) and **must be loaded at inference**; eval env shares `obs_rms` with training env, reward unnormalized.
- **Why γ=0.999:** demand charge is a monthly signal; the agent must value rewards hundreds of steps ahead.
- **Why 7-day random-start episodes:** sees all seasons/tariff patterns; faster credit assignment than full-year episodes.
- **Eval:** deterministic policy over the full 365-day year; metrics = total energy cost, demand charge, degradation, curtailment, violations.

**Baselines to compare against** (in `agents/baseline_agent.py`): no-battery, and rule-based TOU (charge in valley, discharge in peak). The RL agent must beat these or it isn't learning anything useful.

---

## 6. System components (current architecture)

| Component | Role | Keep in rebuild? |
|---|---|---|
| `gym_energy_router` (pip pkg) | Env + physics + generators | Yes — this is the core |
| `python/env/power_env.py` | `EnergyStorageEnvV2` (107-obs, 6-action) | Yes |
| `python/agents/` | SAC train / eval / baselines | Yes |
| `rust_core` (PyO3) | Battery + sim hot loop in Rust | Superseded if you move to JAX |
| `python/backend_server.py` + routers/managers/services | API: training control, live inference stream, LLM analysis | Yes (serving layer) |
| `energy_go_web` (React+Vite) | Dashboard reading `live_metrics.json` / API | Yes |
| `config/*.yaml` | Asset library (12 turbines, 10 PV, 12 batteries) + site configs | Yes — keep config-driven design |

### Known inconsistencies to fix in the rebuild
- **Timestep:** docs/config say 15 min; `EnergyStorageEnvV2` runs 1 h (`self.dt=1.0`) while forecast indexing uses `step_stride = hours*4` (assumes 15-min rows). Pick **one** Δt and audit every formula.
- **SOC bounds:** docs 10–90%, code 20–90%.
- **Export limit:** `GridParams.max_export_mw=945` vs YAML `grid_connection.max_export_mw=200`.
- Forecast obs price lookup uses `hour` only (drops the minute) — mid-tier boundaries (10:30, 11:30) are wrong in forecasts.
- **Forecast noise is never applied:** `forecast_noise_std` is stored in `__init__` but unused — `_get_obs()` reads the true future. The agent trains with perfect foresight; evaluation results overstate real-world performance. The rebuild must add horizon-scaled noise to forecast features.
- **Forecast stride off by 4×:** `step_stride = forecast_step_hours * 4` assumes 15-min rows, but data is hourly — the "24 h @ 1 h" forecast actually samples t+4h … t+96h. Also wraps around episode start via `% len(episode_data)` near episode end.
- `info['total_demand_charge']` double-counts the final month on the terminal step (already booked at termination).
- Spread noise `30 + N(0,10)` can go negative → sell price above buy price (risk-free arbitrage hole); clamp spread ≥ 0.

---

## 7. Language recommendation: JAX (core) — not Go

### TL;DR
**Rebuild the environment + training in JAX. Keep/rewrite the serving layer separately (FastAPI is fine; Go only if you want a single static binary for the dashboard backend).** Go is the wrong tool for the RL core.

### Why not Go for the RL core
- No real RL/autodiff ecosystem (no SB3/torch equivalent; Gorgonia is not production-grade). You'd hand-write SAC, GPU kernels, and replay buffers.
- Your bottleneck is **not** request concurrency (Go's strength); it's **simulation + gradient throughput** (JAX's strength).
- You already tried the "fast core in a systems language" route (`rust_core`) — it speeds up the env but the Python↔env boundary and GPU sync still cap you at ~350 FPS training.

### Why JAX fits this project unusually well
Your env is pure array math: power balance, clips, proportional scaling, a scalar SOC update, sinusoidal generators, AR(1) noise. No branching on external I/O. That's exactly what `jit`/`vmap` eat:

- **Vectorized envs:** `vmap` the step function over 2,000–10,000 parallel envs on one GPU. Realistic throughput: **10⁶–10⁷ env-steps/sec** vs your current ~9,000 (CPU env) and 350 FPS end-to-end training. Training runs go from hours to **minutes**.
- **End-to-end on device:** env, replay buffer, and SAC update all live on GPU — zero host↔device copies per step (this is what kills SB3+Gym setups).
- **Existing building blocks:** SAC/PPO in JAX already exist — **purejaxrl**, **sbx (SB3-in-JAX)**, **Brax-style training loops**, `flashbax` (replay buffers), `gymnax` (env API pattern to copy).
- **Domain randomization for free:** `vmap` over battery/price/weather params → train one robust policy across the whole asset library simultaneously.
- Deletes `rust_core` entirely — one language for the whole research stack.

### What the JAX rewrite looks like

```python
class EnvState(NamedTuple):       # pure, immutable
    soc: jnp.ndarray; month_peak: jnp.ndarray; t: jnp.ndarray; rng: jax.Array

def step(state, action, params, data) -> tuple[EnvState, Obs, Reward]:
    # §3 formulas, written with jnp.where instead of if/else
    ...

batched_step = jax.jit(jax.vmap(step, in_axes=(0, 0, None, None)))
```

Gotchas to plan for:
1. **No data-dependent Python branching** — every `if` in §3 becomes `jnp.where`/`clip` (your env is 90% there already).
2. Pre-generate the synthetic year as a device array; index with `lax.dynamic_slice`.
3. AR(1)/cloud noise via `jax.random` with explicit key threading (you get reproducibility for free).
4. Calendar month boundaries: precompute a `month_of_step` array, detect change with array compare — no datetime logic in the jitted step.
5. Keep `VecNormalize` logic as explicit running-stat arrays saved with the checkpoint.

### Where Go *would* make sense
Only the **production serving layer**: a small Go service that loads the trained policy via **ONNX Runtime** (export: JAX → `jax2tf`/ONNX, or just export the actor MLP weights — it's a plain MLP, trivially reimplemented in ~50 lines of Go), serves the dashboard websocket, and talks to real site hardware. You get a single static binary, easy deploys, great concurrency. But that's optional polish, not the rebuild's core.

### Suggested rebuild order
1. **Port the env to JAX as pure functions** (§3 formulas + §4 generators), unit-test against the current Python env step-for-step on fixed seeds.
2. Fix the §6 inconsistencies while porting (decide Δt = 15 min or 1 h once).
3. Training loop: start from **sbx** or **purejaxrl** SAC; vmap 4096 envs.
4. Re-run baselines (rule-based TOU) in the same JAX env for fair comparison.
5. Export policy (ONNX or raw weights) → serving layer (keep FastAPI, or Go if you want).
6. Point the React dashboard at the new serving API (unchanged contract: `live_metrics.json` shape).
7. Extend to the composable asset library (§8) once the §3 plant reproduces baseline results.

---

## 8. Composable asset library (extension)

The rebuild must support **picking and combining assets into new systems** the agent learns to operate — not just the fixed Gansu wind+solar+battery plant. Every asset is a pure parameterized model; a site YAML composes instances of them; the env derives its observation/action spaces and the power-balance from the composition.

### 8.1 Asset abstraction

Every asset type implements the same pure-function interface (JAX-jittable, vmappable):

```python
class AssetModel(Protocol):
    def power(self, internal_state, weather, action, params, dt) -> (P_mw, new_state, costs)
```

- `P_mw > 0` = injects to the bus (generators, storage discharge); `P_mw < 0` = draws from the bus (loads, storage charge, electrolyzers).
- Stateless assets (wind, solar, fixed loads) have empty internal state; stateful assets (battery, gas, electrolyzer+tank) carry it as a pytree.
- Asset types register in a **model registry**; site YAML references `type` + `params` (the existing config-driven asset library pattern: 12 turbines, 10 PV, 12 batteries — now extended).

### 8.2 Generation models

**Wind turbine** — §3.1 power curve. Params: `p_rated, v_cutin, v_rated, v_cutout, hub_height`.

**Solar PV** — §3.1 PV model. Params: `p_capacity, k_T, eta_inv, degradation`.

**Gas combustion (dispatchable)** — open-cycle gas turbine / reciprocating engine. Action: setpoint `u ∈ [0,1]`.
```
P = 0                      if u < u_off (0.05)        # off
P = P_min + u'·(P_max−P_min) otherwise                 # u rescaled to [0,1] over the on-range
|P_t − P_{t−1}| ≤ ramp_mw_per_step                     # ramp limit (clip + report)
η(x) = η_max·(0.55 + 0.45·x),  x = P/P_max             # part-load efficiency, linear approx
C_fuel = (price_gas_th / η(x)) · P · Δt                # ¥, price_gas_th in ¥/MWh_thermal
```
Reference params (aeroderivative class): `P_max 30 MW, P_min 0.4·P_max, ramp 0.5·P_max per hour, η_max 0.38, price_gas_th 250 ¥/MWh_th`. Optional: CO₂ cost `0.2 tCO₂/MWh_th × carbon_price`. Start-up costs / min up-down times are **out of scope v1** (unit commitment is integer logic; if needed later, model as penalties, not hard constraints, to stay JAX-friendly).

**Hydrogen electrolyzer (controllable load)** — both types, same model shape, different params. Action: setpoint `u ∈ [0,1]`.

```
P_ely = 0                          if u < u_min_load   # standby
P_ely = u · P_max_ely              otherwise, clipped to [P_min_ely, P_max_ely]
H2_kg = P_ely · Δt · 1000 / e_spec                     # e_spec = specific energy, kWh/kg
tank: ΔH2 = H2_kg − H2_demand_kg(t);  H2_level ∈ [0, tank_kg]  (clip + penalty, like SOC)
R_H2 = price_h2 · H2_kg_sold                           # ¥, revenue term in reward
```

| Param | PEM | Alkaline |
|---|---|---|
| Operating range (% of P_max) | 5–100 | 20–100 |
| Specific energy `e_spec` (kWh/kg, system) | 55 | 52 |
| Standby draw (% of P_max) | 1 | 2 |
| Ramp | unconstrained at Δt ≥ 15 min | unconstrained at Δt ≥ 15 min |
| Degradation (¥/MWh throughput) | 8 | 4 |

(At hourly/15-min steps the real PEM-vs-alkaline ramp difference vanishes — what the agent learns to exploit is the **min-load and standby difference**. State that in tests.) Reference: `P_max_ely 20 MW, tank 2000 kg, price_h2 30 ¥/kg`.

**Charging priority** mirrors the battery rule (§3.2): renewable power allocated to the electrolyzer is consumed first; grid tops up the remainder, subject to the import limit (load served first, then battery, then electrolyzer).

### 8.3 Load models (profile archetypes)

All loads share the §4.2 structure — `L_t = base·profile[h]·dow[d] + α·CDD + β·HDD + AR1` — and differ by parameter set:

| Archetype | profile[h] shape | dow | α (CDD) | β (HDD) | Notes |
|---|---|---|---|---|---|
| `commercial` | 0.5 night → 1.0 work hours | (1,1,1,1,1,.7,.6) | mid | mid | the existing §4.2 model |
| `residential` | 0.4 night, 0.6 midday, 1.0 at 19–22 | weekend ×1.1 daytime | high | high | evening peak |
| `industrial_continuous` | flat 0.95–1.0 | all 1.0 | low | low | process load |
| `industrial_two_shift` | 1.0 at 6–22, 0.3 night | (1,1,1,1,1,.5,.5) | low | low | shift work |
| `data_center` | flat 0.9 | all 1.0 | high | none | cooling-dominated CDD |
| `ev_fleet` | 0.2 day, peak 1.0 at 18–23 | weekend shifted +2 h | none | none | optional `flexible_fraction` for future DR |

Each instance: `base_mw, profile[24], dow[7], alpha, beta, ar1_rho, ar1_sigma`. A site can compose **multiple load instances**; total load = Σ instances. Per-load forecasts enter the observation like the existing load forecast.

### 8.4 Composition → MDP

The observation and action vectors are **derived from the site YAML**, concatenated in declaration order:

```
obs    = [ weather, time encodings, price, month_peak ]            # base block
         + per stateful asset: its internal state (SOC, H2 level, gas P_prev)
         + per asset: forecast block (as §2.1, normalized)
action = per renewable source s:   f_s→load, f_s→bat, f_s→ely      # fractions [0,1]
         + per battery:            a_bat ∈ [−1,1], f_bat→load
         + per dispatchable (gas): u ∈ [0,1]
         + per electrolyzer:       u ∈ [0,1]
```

The Gansu config (§1–§3) is the special case: 2 renewable sources + 1 battery, no gas/ely → exactly the 6-dim action of §2.2. **Parity tests run on this config.**

Power balance, PCC limits, import priority, and cost/penalty enforcement keep the §3.3–§3.6 order, with the bus summing over all composed assets. New constraint-table rows: gas ramp (clip, silent), gas min-load (structural via setpoint mapping), electrolyzer operating range (structural), H₂ tank bounds (clip + penalty, same style as SOC #5).

### 8.5 Implications

- **Training:** domain randomization now spans compositions — `vmap` over asset params trains one policy per composition family; different compositions (different obs/action dims) are different policies. The harness must support launching runs per site config.
- **Reward** gains terms: `+C_fuel` (gas), `−R_H2` (hydrogen revenue), electrolyzer/gas degradation — same 1e-5 scaling; re-verify the scale keeps rewards O(1).
- **3D:** each asset type maps to an `assets/3d/<function>/` category and a `registry.json` entry (gas turbine hall, electrolyzer skid + H₂ tank with fill level, per-archetype load buildings).
- **Dashboard:** cost breakdown gains fuel and H₂ revenue components; per-asset flow table grows with composition.
- **Contracts:** each asset model is its own contract + test file (`contracts/env/gas_turbine.md`, `contracts/env/electrolyzer.md`, `contracts/env/load_archetypes.md`, …) with hand-computed expected values per the worked example.

---

## 9. Install & launch scripts (deployment)

**Interpretation of the request** (user wording: *"launch scripts that we can install the app on mac or windows based on the server types"*): the rebuild ships **one-command install + launch scripts** for **macOS** and **Windows** that stand up the Energy GO app, and what gets installed/started is selected by a **`--server-type`** flag (the *role* the machine plays). This section specifies the contract those scripts satisfy; the implementation is a separate task. Linux is out of scope for v1 of this section (CI runs on Linux but uses `pyproject` extras directly, not these scripts).

### 9.1 Files (per `scripts/<verb>_<object>` convention)

| Script | OS | Role |
|---|---|---|
| `scripts/install_app.sh` | macOS (bash/zsh) | install dependencies for the chosen server type, then optionally launch |
| `scripts/install_app.ps1` | Windows (PowerShell 5.1+/7) | same, Windows-native |
| `scripts/run_app.sh` | macOS | launch an already-installed server type (no dependency work) |
| `scripts/run_app.ps1` | Windows | same, Windows-native |

`install_app` is **idempotent install (+ optional launch)**; `run_app` is **launch-only** and assumes a prior install. The two `.sh`/`.ps1` pairs are behavioural mirrors — same flags, same server-type taxonomy, same exit codes — differing only in platform mechanics (Homebrew/`uv` vs winget/`uv`; `venv/bin` vs `venv\Scripts`; SIGTERM vs `Stop-Process`).

### 9.2 Server types (`--server-type`)

The role selects which dependency groups install and which processes launch. Maps 1:1 to `pyproject` optional-dependency extras and to STACK.md areas.

| `--server-type` | Installs | Launches | Default accelerator |
|---|---|---|---|
| `dev` | full stack: JAX core, training (sbx/purejaxrl, optax, flax), serving (FastAPI), frontend (Node + Vite) | FastAPI backend (reload) + Vite dev server (HMR) | `gpu` if detected, else `cpu` |
| `training` | JAX core + training + eval + baselines; **no** Node/frontend | training/eval harness entrypoint (no web) | `gpu` if detected, else `cpu` |
| `serving` | JAX core (inference only) + FastAPI + exported policy runtime (ONNX or raw-MLP weights, §7 §5); **built** frontend static assets; **no** training deps | FastAPI backend serving the locked telemetry stream + static frontend bundle | `cpu` |
| `full` | union of `training` + `serving` (one box trains and serves) | training harness + FastAPI + built frontend | `gpu` if detected, else `cpu` |

- **Accelerator is orthogonal:** `--accel cpu|gpu` overrides the default and selects the **jaxlib** variant (CPU wheel vs CUDA/Metal wheel). The script must verify the toolchain (CUDA on Windows/Linux GPU boxes; on macOS, GPU = Metal via `jax-metal`, best-effort with a CPU fallback warning) and fail loudly with a remediation hint rather than silently installing the CPU wheel on a GPU box.
- The `serving` type never pulls training-only deps — this keeps the production serving image minimal (aligns with §7 "Go *would* make sense" optional path; the Python serving layer is the v1 default).

### 9.3 What `install_app` does (ordered)

1. **Preflight:** detect OS + arch (Apple Silicon vs Intel; Windows x64), check/install the base toolchain — Python (pinned in STACK.md) via `uv` (preferred) or `pyenv`/winget; **Node LTS** only for `dev`/`serving`/`full`. Refuse unsupported OS/arch with a clear message.
2. **Python env:** create a project-local virtualenv (`.venv/`), never touch system Python.
3. **Dependencies:** install the `pyproject` extras group for the server type; install the jaxlib variant per `--accel`.
4. **Config selection:** `--site <path>` (default `config/site_gansu.yaml`); validate it loads. Resolve checkpoint to serve via `--checkpoint <id|path>` for `serving`/`full` (error if absent and no default).
5. **Frontend (dev/serving/full):** `npm ci` then — `dev` leaves source for HMR; `serving`/`full` run `npm run build` to produce the static bundle the backend serves.
6. **Launch (unless `--no-launch`):** start the processes for the server type (§9.2), wire ports (`--backend-port`, default 8000; `--frontend-port`, default 5173), write a PID/run file under `.run/` so `run_app`/`--uninstall` can find them, and print the URLs.

`run_app` performs only steps 4 (config resolve) + 6 (launch), erroring if `.venv/`/build artifacts are missing ("run install_app first").

### 9.4 Idempotency, uninstall, errors

- **Idempotent:** re-running `install_app` with the same args detects an up-to-date `.venv`/lockfile/build and is a near-no-op; a changed lockfile triggers an upgrade. Never destructive to user-edited `config/` files.
- **`--uninstall`:** stops running services (via the `.run/` PID file), removes `.venv/`, frontend `node_modules/` + build output, and `.run/`. Leaves `config/` and checkpoints unless `--purge` is also given (which additionally clears local checkpoints/run artifacts). Prints exactly what it removed.
- **Errors:** every failure exits non-zero with a one-line cause + remediation. No partial silent success. Re-running after a fixed error resumes cleanly (idempotency).
- **No secrets in scripts:** any API keys (e.g. the §6 LLM analysis service, if enabled) come from environment/`.env`, never baked in.

### 9.5 Acceptance criteria (for the implementation task)

- `bash scripts/install_app.sh --server-type serving --accel cpu --no-launch` on macOS and `pwsh scripts/install_app.ps1 -ServerType serving -Accel cpu -NoLaunch` on Windows both complete green from a clean checkout, producing a `.venv` with serving (not training) deps and a built frontend bundle.
- `--server-type training --no-launch` installs training deps and **no** Node/frontend.
- Re-running the same command is idempotent (second run makes no dependency changes; exit 0).
- `run_app` launches a previously-installed `serving` box and the FastAPI health endpoint responds; killing via `--uninstall` stops it and removes `.venv`/build, leaving `config/` intact.
- An invalid `--server-type` / `--accel`, a GPU `--accel gpu` on a box with no detected accelerator, or a missing `--checkpoint` for `serving` each exit non-zero with a remediation message.
- The `.sh` and `.ps1` variants accept the same flag set and select the same server-type behaviour (cross-platform parity test, documented in the implementation's contract).
- All dependency versions/pins come from `pyproject` + STACK.md; the scripts hardcode no version not also recorded there.

---

## 10. Env-logic enhancements (proposal — opt-in, parity-preserving)

**Status: PROPOSAL for user approval.** This section enumerates candidate enhancements to the simulation env logic beyond the current §3 plant and §8 asset library, each with mechanism, cost/benefit, and build-order impact, so the user can approve, trim, or reorder. Nothing here is binding until the user approves the specific items; approved items each become a numbered DECISION + their own contract + tests.

### 10.0 Governing rules (apply to every enhancement below)

1. **Each maps to a §3.6 "Not modeled" line.** §3.6 already names the fidelity boundary (no ramp-rate, no losses, no reactive/voltage, no battery calendar aging or SOC-dependent efficiency, no min-import contracts, no frequency services) and says real-site rules "slot in as extra clamps/penalties at the marked stages." Each enhancement is a **deliberate, itemized lift** of one of those lines. **Voltage, reactive power, and grid-frequency services remain OUT regardless** — they require a power-flow solver this env is not (the boundary moves by item, not wholesale).
2. **Toggleable, default OFF.** Every enhancement is gated by a site-YAML flag (e.g. `physics.battery_aging: false`). With all flags OFF the env is byte-for-byte the current §3 physics, so the **Gansu parity case (D11) validates against the unenhanced model** — parity is never at risk. The parity test asserts all enhancement flags are OFF.
3. **Sequence after baseline parity.** Build order: §3 parity → §8 asset library → these. An enhancement that adds emitted fields is a **minor** telemetry bump (§ telemetry contract Versioning); one that changes the §4 synthetic year must use a **separate seed/config** so the D11 parity year is bit-identical.
4. **Stays jittable.** Every mechanism is expressible as `jnp.where`/`clip`/lookup with explicit RNG threading (§7) — no data-dependent Python branching, no host sync.
5. **Re-verify reward scale.** Any new cost/penalty term keeps the 1e-5 scaling and must keep reward ~O(1) (§3.5).

### 10.1 Candidate enhancements

| ID | Enhancement | Mechanism (sketch) | Lifts §3.6 line | Benefit | Cost / risk |
|---|---|---|---|---|---|
| **E1** | Battery capacity fade (aging) | `E_cap = E_0·(1 − f_cal·age − f_cyc·Σthroughput)`. At 7-day episodes, within-episode fade is negligible → implement as **per-episode initial capacity** sampled from an aging schedule (domain randomization), not a per-step state. | "no battery calendar aging" | Long-horizon economics; SOC headroom shrinks with fleet age; cheap robustness via DR over capacity | Low. `capacity_mwh` is already per-step on the telemetry wire, so consumers already handle variable capacity. No new emitted field. |
| **E2** | SOC/temperature-dependent efficiency | Replace constants `η_ch=η_dis=0.97` with a clamped curve `η(SOC, T)` (low/high-SOC and cold-temp penalties), evaluated as a jnp polynomial/lookup. | "no SOC-dependent efficiency" | Agent learns an efficiency sweet-spot SOC band; more realistic losses feed `C_deg`/energy | Low. Localized to §3.2; two constants → one curve. Re-verify reward O(1). |
| **E3** | Battery & grid ramp-rate limits | `|P_t − P_{t−1}| ≤ R_max·Δt`, silent clip at the §3.6 #3/#8 stages — same style as the gas ramp already in §8.4. Adds `P_prev` state (gas already carries one). | "no ramp-rate limits" | Smoother, more deployable dispatch | **Low marginal value at Δt=1 h (D3):** a full power swing within one hour is usually physical, so the limit rarely binds. More valuable only under a future 15-min Δt. Defer. |
| **E4** | Weather/load stochastic coupling | A shared latent temperature/synoptic anomaly drives PV derate (`k_T`), load (CDD/HDD §4.2), and wind **together** (incl. hot + low-wind + high-load co-stress), replacing the current independent generators. | (tightens §4 generator realism; no new physics) | Correlated stress scenarios force the policy to hedge joint extremes — strong robustness/sim-to-real gain | Medium. **Changes the §4 synthetic year → must run on a separate seed/config; the D11 parity year stays bit-identical.** Touches generators only, not the jitted step. |
| **E5** | Forecast-error regime switching | Extend D6's linear `σ_h = σ_max·(h/H)` with a Markov **regime** (calm/stormy) modulating `σ_max`, and/or fat-tailed errors. Lives in `_get_obs` (D6), adds a regime state + key threading. | (extends D6 forecast-noise model) | Robustness to forecast blow-ups; the single biggest sim-to-real gap after "noise never applied" (already fixed by D6) | Low–medium. **Affects observations only, not physics/cost** — so per-step physics parity is unaffected; only the trajectory differs. |
| **E6** | Richer curtailment / grid-interaction | Time-varying PCC acceptance (exogenous grid-availability signal) and/or curtailment hysteresis, replacing the static `max_export_mw` (D5). | "no min-import contracts" (partial) | Realistic congestion/curtailment economics | **Higher + boundary risk.** Needs a new exogenous generator, and the realistic version drifts toward voltage/congestion modeling that §3.6 explicitly excludes. Keep strictly to a scalar time-varying export cap if taken at all. |

### 10.2 Recommended tiering (rl-architect's call — user may override)

- **Tier 1 — recommended first** (cheap, localized to §3, parity-safe, high value): **E2** (SOC/T efficiency) and **E5** (forecast regime noise). Neither changes the parity-year data; both are small jittable additions.
- **Tier 2 — high value, moderate cost:** **E1** (battery aging as per-episode capacity DR) and **E4** (weather/load coupling — with the separate-seed guard so D11 parity is untouched).
- **Tier 3 — defer:** **E3** (ramp limits — weak at Δt=1 h) and **E6** (dynamic grid — highest cost and the only candidate that risks the voltage/reactive boundary; if taken, restrict to a scalar export-cap signal).

### 10.3 Per-enhancement deliverable (once approved)

Each approved enhancement ships as: a numbered LINEAGE **DECISION**; a site-YAML toggle (default OFF); its own `contracts/env/<enhancement>.md` + `tests/env/test_env_<enhancement>.py` with hand-computed expected values; application in **both** the JAX core and the NumPy reference (D11); a parity-regression test proving Gansu (all flags OFF) is unchanged; and, if it emits new telemetry, a minor schema bump with both reviewers' sign-off.

### 10.4 Open questions for the user

1. Which tier(s) to greenlight? (Recommend approving **Tier 1** now, scoping Tier 2/3 later.)
2. For E1, is per-episode capacity sampling (vs a true multi-year per-step fade) the right fidelity, given 7-day episodes?
3. For E4/E6, confirm the "separate seed, parity-year untouched" and "no voltage/reactive" guardrails are acceptable boundaries.
