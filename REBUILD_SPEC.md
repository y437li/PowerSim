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
