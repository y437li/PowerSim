## 8. Composable asset library (extension)
> **Owner:** rl-architect

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

