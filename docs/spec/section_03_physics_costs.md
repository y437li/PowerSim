## 3. Physics & cost formulas
> **Owner:** jax-env-engineer

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

