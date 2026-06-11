# Master Plan — Geo-Data Selection · Device-Physics Schema · Multi-Year Simulation · Project Finance

> **Status:** DRAFT — coordinated plan, **no implementation**. **Review gate:** team-lead (Fable) reviews this draft and summarizes to the USER; implementation tasks spawn only after that gate (task #53).
> **Plan lead:** rl-architect (cross-cutting architecture + integration).
> **Workstream owners:** finance-expert → D · jax-env-engineer → B/C feasibility · frontend-reviewer → A/E consult.
> **Builds on:** §8 (composable assets), §12 / PR #77 (historical-weather design), §11 (benchmark ladder).
> **How to read:** §1 is the unifying architecture (the keystone) + §1.1 the scenario abstraction (USER directive). §2–§6 are the five workstreams, each authored/integrated by its domain owner (B/C jax-env-engineer, A/E frontend-reviewer, D finance-expert) under the plan lead's cross-cutting frame. §7–§9 are sequencing + the explicit v1 scope, contracts/risks, and the gate decisions.

---

## 1. The unifying architecture — the device-model registry as the universal join key

The five workstreams look independent but share **one keystone**: a **device model** (a concrete piece of equipment — *Vestas V150-4.2*, *Trina Vertex N 670 W*, *CATL LMP 300 MWh*, *PCC substation 945 MW*) that today appears in three disconnected places — the LOCKED 3D `registry.json` (visual), the hardcoded `gansu_params.py` (physics), and nowhere (economics). **The plan unifies them under one device-model ID** carrying three facets:

```
device model  <id>  ─┬─ VISUAL    : assets/3d/registry.json   (LOCKED, exists)
                     ├─ PHYSICS   : power curve / efficiency / degradation / limits   (B — NEW)
                     └─ ECONOMICS : CAPEX / OPEX / lifetime / replacement cost        (D — NEW)
```

The 3D registry **already** keys by exactly these IDs (`vestas-v150-4.2`, `trina-vertex-n-670w`, `catl-lmp-300mwh`, `pcc-substation-945mw`) and that key-equals-config-ID invariant is LOCKED. So the device-physics schema (B) and the economic schema (D) **attach to the same IDs** — no new identifier space, and "add a device" becomes "add one registry entry with three facets."

This is why **B is the foundation** and the others depend on it:

```
                    ┌──────────────────────────────────────────┐
   §8 AssetModel ──▶│  B — DEVICE-MODEL PHYSICS+ECON SCHEMA     │◀── §11 benchmark ladder
   3D registry   ──▶│  (physics params + CAPEX/OPEX, keyed by   │      (D's policy comparison)
                    │   device-model id; env consumes schema —  │
                    │   no hardcoded Gansu constants)           │
                    └───────┬───────────────┬───────────────┬───┘
                            │               │               │
            §12/PR#77 ──▶ A geo-UI        C multi-year     D project finance ──▶ E policy-econ UI
            (weather)     (lat/lon →      (10/20 yr,       (CAPEX/OPEX from B,    (choose policies,
                          fetch → site-    YoY degrade      cash flows from C,    side-by-side
                          config of B      from B, price    IRR/NPV/LCOE,         economic results)
                          devices)         escalation)      sensitivity, vs §11)
```

**Foundational role of B:** A composes a site from B device-models; C compounds dispatch years using B degradation curves; D draws CAPEX/OPEX from B; E renders D. Get B's schema right and the rest are well-posed; get it wrong and four workstreams inherit the mess.

**Invariants this plan must preserve (non-negotiable):**
- **Gansu parity (D11):** Gansu becomes *a schema instance* whose physics facet reproduces today's `gansu_params.py` **exactly** (parity test asserts bit-equality of the derived constants). The schema generalizes; it must not perturb the parity year.
- **Pure jitted `step` (§7):** the env consumes the schema at **build time** (Python composes the params into the jitted closure); no schema lookup, dict access, or I/O ever enters the jitted hot loop. Same discipline as §12's offline build.
- **LOCKED contracts:** telemetry (`env_step`/`train_metrics`/`eval_compare`) and the checkpoint format are about obs/action/costs, not device params — they are **unaffected** by B *as long as* the obs/action dims stay composition-derived (§8.4) and any new cost terms (fuel, H₂, finance) are additive under the D13 accounting identities. New cost components that need to appear on the wire would be a **telemetry minor version bump** (additive) — flagged, not assumed.

### 1.1 Scenario abstraction — *a scenario is a configuration, not a mode* (BINDING, USER directive)

The USER's expansion ambitions (power supply, hydrogen production, electrolytic-aluminum, **data centers producing AI tokens**) must be **architecturally cheap, not multiplicative**. The containing principle, binding on this plan:

> **A scenario is purely a CONFIGURATION** — never a separate codebase, mode, or branch.
> `scenario = { site devices (from B's schema) } + { revenue / cost streams } + { policy objective }`.

This is the *second half* of the keystone: §1's device-model registry composes the **physical** site; the scenario abstraction composes the **economic + objective** layer on top — both pure config over the same device-model IDs. The three named scenarios then map cleanly to **existing §8 capabilities — no new code paths**:

| Scenario | Site composition (B / §8 devices) | Revenue / cost streams (D) | Status |
|---|---|---|---|
| **Power supply** (= today's Gansu) | wind + solar + battery + grid | grid-export revenue (¥/MWh, the §3 TOU tariff) | **v1 — the working end-to-end deliverable** |
| **Hydrogen production** | same site **+ electrolyzer** (§8.2 PEM/alkaline already specced) | H₂ revenue (¥/kg via the kWh/kg conversion physics, §8.2) replacing/augmenting export | **validation case** (config-only, design-proven) |
| **Electrolytic aluminum** | site **+ `industrial_continuous` load** (§8.3 archetype already specced) | avoided-cost / tariff economics for the smelter load | **validation case** (config-only, design-proven) |
| **Data center (AI tokens)** | site **+ `load_data_center`** (§8.3 archetype — **already in the registry from PR #38**; the asset zoo anticipated it) | token revenue (`¥/token × tokens/h`) — power-driven, hourly, the **same time-series revenue schema** as electricity/H₂ | **validation case** (config-only; v1 = fixed load) |

That all four already decompose into §8's composable assets — three of them shipping device models already in the registry — is the *proof* that the abstraction contains the complexity: adding a scenario = composing existing device models + declaring its revenue streams + objective, **not** writing a hydrogen-mode or token-mode.

**One scenario-specific nuance (data center):** unlike aluminum's continuous load, data-center load is **partially flexible** — deferrable batch inference/training jobs make it a potentially *dispatchable/shiftable* load that would extend the **action** space, not just the device list. **v1 treats it as a fixed/archetype load** (config-only, like the others); the **flexible-load action extension is a flagged future item, explicitly NOT v1** (§7.1). This is the one place a future scenario touches the action space rather than pure config — worth naming so it isn't assumed into v1.

**The one structural requirement this adds (→ workstream D):** the finance schema must **abstract revenue streams per device/scenario** — `{type: grid_export | h2_sale | avoided_cost | token_sale, unit: ¥/MWh | ¥/kg | ¥/token | …, source_device_id}`, **time-resolved hourly** (token/H₂/electricity revenue are all power-driven hourly quantities) — rather than hardcoding electricity-export. With that, the same finance engine prices any scenario. *Bound into finance-expert's §5.3 revenue-stream schema.*

**v1 scope is fixed (USER directive):** ship the **power-supply scenario end-to-end ONLY**. Hydrogen and aluminum are **validation cases for the abstraction** (the plan must *demonstrate* they're config-only, which the table above does) — **not v1 deliverables**. See §7 for the explicit "what is NOT being built now."

---

## 2. Workstream B — Device-physics (+economic) schema  ·  *owner: jax-env-engineer (feasibility); builds on §8*

**Goal:** every device model carries its physics (and, jointly with D, its economics) as schema data, so the env is **schema-driven, not Gansu-hardcoded**. Adding a turbine/PV/battery/grid model = adding a schema entry.

**Design (jax-env-engineer domain review, integrated):**
- **Schema = the §8.2 params, made first-class and keyed by device-model ID.** §8 already specifies the param sets per *type* (wind: `p_rated,v_cutin,v_rated,v_cutout,hub_height`; PV: `p_capacity,k_T,eta_inv,degradation`; gas; electrolyzer; battery; loads). B turns each *concrete model* into an entry of `{type, physics:{…§8.2 params…}, econ:{…D fields…}}`.
- **The resolver = produce an `EnvParams` instance.** Domain insight (jax-env-engineer): `EnvParams` (the NamedTuple) *already is* the resolved-param struct, so the resolver's job is simply `YAML + site config → EnvParams`. The **Gansu bit-parity gate is exactly `resolve_gansu() == EnvParams()` (defaults)** — clean and decisive. `gansu_params.py` is replaced by resolving the Gansu site's device IDs against the schema.
- **Structural gap to fix (jax-env-engineer):** today `jax_env.py` has a **module-level hardcoded `PRICE_TABLE_YPW` `(24,)`** that the jitted `step` closes over directly — the tariff is *per-site*, so it must become an **`EnvParams.price_table` field** (the resolver populates it; `step` reads `params.price_table`, not the module global). Since `params` is shared across vmapped envs (not in the vmap batch axis), a `(24,)` field rides cleanly in the pytree. **The bit-parity test must cover the tariff array, not just scalars.**
- **Resolver output + the LOCK stays closed (jax-env-engineer):** the resolver outputs `(EnvParams, obs_dim, action_dim)`; different site configs → different dims → each unique `(obs_dim, action_dim)` pair gets its own JAX trace (standard trace-cache). The **LOCKED checkpoint format is Gansu-specific (`obs_dim=107, action_dim=6`) and stays closed for B** — non-Gansu §8 sites get site-specific checkpoint formats later; B itself does not reopen the lock.
- **Schema location — RESOLVED: sibling `config/device_models.yaml`, keyed by the existing device IDs.** *Three concurring votes (rl-architect, frontend-reviewer, jax-env-engineer).* Rationale (jax-env-engineer): (1) **schema mismatch** — `registry.json` carries visual `{path,dims_m,pivot,…}` consumed by frontend3d; physics params are a different schema with a different consumer (the JAX env); (2) **lock cost** — adding required physics fields to `registry.json` is a breaking change → reopen the LOCKED v1.0.0 registry; a new YAML is purely additive; (3) **the join key is the link, not the file** — the device-model ID already appears in both `site_gansu.yaml` and `registry.json`; `config/device_models.yaml` fits the `config/<asset>_<name>.yaml` naming convention alongside `site_gansu.yaml`. The 3D lock stays closed; physics/econ iterate freely.
- **Scope:** the 4 Gansu device models first (prove schema-equals-hardcoded, incl. the tariff array), then the §8 library (gas, electrolyzer, load archetypes) per-model as today (each its own contract + test, §8.5).
- **Contracts:** new `contracts/shared/device_model_schema.md` (schema format + resolver) — **shared** (env consumes; A/C/D reference) → rl-architect lock after both reviewers comment.

**Remaining open:** how instance overrides vs model defaults compose (config ergonomics).

---

## 3. Workstream A — Web geo-data selection  ·  *frontend-reviewer consult; builds on §12 / PR #77*

**Goal:** the web/training UI lets the user pick **latitude/longitude** (map or input), pull historical weather for that location, and generate a runnable **site config**.

**Design (frontend-reviewer consult, integrated):**
- **Map provider — MapLibre GL JS** (BSD) via `react-map-gl`, **configurable** tile source (open/free default; opt-in API-key provider via config — avoids mandatory proprietary-key install friction on arbitrary §9 boxes, and we already carry one data-redistribution gate). **Numeric lat/lon fields are co-equal and authoritative**; the map is a convenience. **No-map fallback** (offline/tiles fail) must still allow lat/lon entry — graceful degradation, same discipline as the 3D scene's telemetry-gap freeze. Validate `lat∈[-90,90]`, `lon∈[-180,180]`, and **gate on data-availability** — don't let the user generate a config for a point/year with no Open-Meteo coverage (surface §12/PR#77 availability as a precondition).
- **Fetch path — serving exposes, harness executes, dashboard observes (reuse the existing pattern, don't fork it):** UI → `POST /api/geo/fetch {lat,lon,years,mode}` → **202 + job_id** (async — the fetch is slow, cache-writing, rate-limited; **never** synchronous in the request thread, never inside training/`step`) → progress over the existing WS status frame / REST poll → returns the site-config (or `config_id`). **Content-address the cache** by `(lat, lon, year-range, provider, version)` so re-requests hit cache and the UI can show cached-vs-fetching.
- **Weather-source selector — 3 badged modes with provenance stamped into the artifact (a data-correctness guard, not cosmetics):** (1) **synthetic** (§4 gens; no location; seeded), (2) **historical/real** (lat/lon + specific year(s) from cache), (3) **bootstrap/unlimited** (PR#77 block-bootstrap of real history; lat/lon + seed + block length). The mode is written into the generated site YAML as a **`weather.provenance`** block **and surfaced on all downstream eval/econ results** — so synthetic can never be misread as real and E never silently mixes provenance. Modes 2/3 gated on data-availability.
- **Device-composition panel (operationalizes the join-key invariant):** the panel's ID list comes from the **B `device_model_schema`, keyed by the exact `assets/3d/registry.json` IDs verbatim** (no aliasing/re-typing). Each row: ID · type · nameplate from the physics facet **with units** (MW/MWh) · (when D lands) a CAPEX hint from the econ facet. Counts × nameplate → a **live composed-site total** — but that preview total **must come from the same server-side §8.4 resolver the env build step uses** (a serving resolve-endpoint returning composed totals + obs/action dims); **do NOT reimplement composition in TS** or the preview drifts from what's simulated (same class of guard as the registry-drift test). A configured ID with no schema entry = **hard error surfaced in the UI**, not a silent blank.
- **Site-config artifact:** chosen `(lat,lon)` + selected B device-models → a site YAML (`location` per §12.2 + `weather.provenance` + device-model instances). This YAML is the single artifact A produces and B/C/D consume. A introduces **no** new env physics; the weather-redistribution licensing (PR#77 §4.1) is the carried-forward gate item.

---

## 4. Workstream C — Accelerated multi-year simulation  ·  *jax-env-engineer feasibility*

**Goal:** run **10/20-year** horizons — compounding 8760-h dispatch years with year-over-year **degradation** and price/cost **escalation**, plus sim-speed controls.

**Design (plan-lead seed — jax-env-engineer feasibility):**
- **Structure:** an outer loop over `Y` years, each an 8760-h dispatch episode, with **state carried across years** — battery capacity/efficiency degraded per B's degradation curve, PV degradation per B, and exogenous **escalation** (tariff, fuel, O&M, ¥ discounting) applied per year. The within-year env is unchanged (§3); C wraps it.
- **Device lifetime / replacement:** when a device crosses end-of-life within the horizon (e.g., battery at ~10 yr), a **replacement event** resets its degraded params and emits a **CAPEX event** to D. Lifetime is a B econ param.
- **Device-side feasibility — CONFIRMED §7-clean (jax-env-engineer):** the per-year params (degraded capacity, escalated prices) are **closure constants per year**, so a 20-year run = `Y` jitted 8760-step dispatch years with cheap **host-side param updates between years**. This is an **eval workload**, so D27's "zero host↔device copies per step" (which governs the 10⁷-step *training inner loop*) does **not** apply — the year boundary is the natural host point, exactly the D21 calendar-flush / env-harness eval-loop precedent. The clean pattern:
  ```
  for y in range(Y):
      params_y = update(params_{y-1}, degradation_y, escalation_y)   # host, cheap
      state_y, info_y = jit_episode(params_y, rng_y)                 # 8760 steps, fully on-device
      if eol(info_y): params_y = reset_device(params_y); emit_capex_event(y)
  ```
  **Python outer loop is the right v1 default** (not `lax.scan` across years): `lax.scan` over Y=20×8760 = 175k op-steps is one monolithic trace (≈20× compile, hard to checkpoint/restart/inspect between years) with no throughput gain (finance projection isn't the training bottleneck). *`lax.scan`-across-years is a named **extension point** for accelerated-lifetime research (Y ≫ 20), not v1.*
- **Output:** C's product is the **per-year energy + cost + degradation trajectory** that D turns into cash flows. Sim-speed controls reuse the D24 replay-speed pattern at the year/episode level.

**Open decisions:** escalation model (flat %/yr vs scenario curves — coordinate with D); replacement policy (auto at EOL vs user-scheduled); whether multi-year eval runs the RL policy, the §11 baselines, or both across the horizon.

---

## 5. Workstream D — Project finance  ·  *owner: finance-expert (Sonnet impl: finance-engineer)*

**Deliverable (this plan):** the financial model — its principles, formulas, conventions, data shapes, and the schema obligations it places on B and C. The downstream **§13 project-finance SPEC section** (a human-gated REBUILD_SPEC change) formalizes what §5 designs and is authored *after* this plan's Fable gate. Default cost figures and pass/fail numbers are contract-stage decisions (§5.11).

### 5.1 Two foundational principles (these constrain everything below)

**P1 — Hourly-resolved revenue integration.** Every revenue and cost stream is accounted at the **hourly** level and then integrated up; it is **never** approximated as annual-average-price × annual-quantity.

```
revenue_s(year)  =  Σ_{t=1}^{8760}  q_{s,t} · p_{s,t}            # per stream s, per hour t
cost_s(year)     =  Σ_{t=1}^{8760}  q_{s,t} · p_{s,t}
```

*Proof of necessity (the valley/peak arbitrage example):* the RL policy's entire value is **temporal** — charge the battery in the ¥250/MWh valley, discharge into the ¥780/MWh critical peak (§3.7). The annual *average* price is the same whether or not the battery shifts energy; only the **hour-by-hour** product `q_t·p_t` captures the ¥530/MWh spread the policy harvests. **Annual-average accounting mathematically erases exactly the value the policy creates** — so it is prohibited in this model. The D13 telemetry already carries hourly costs; D's layer consumes the **trajectory**, not summaries.

**P2 — The dispatched year is the atomic finance unit (storage couples hours).** Because SOC ties timesteps together (charging at hour *t* constrains discharge at *t+k*), project value **cannot be decomposed hour-by-hour independently** — a single hour's cash flow is not a well-defined standalone quantity. The indivisible input to finance is therefore a **full dispatched year** (a `PolicyEvalResult`-grade object: the complete 8760-h hourly trajectory of quantities and the realized prices, under one policy and one scenario). This is *also why the per-policy comparison is meaningful*: different policies produce different trajectories under **identical prices**, so the revenue difference is purely the policy's doing.

These two principles are the design's spine; §5.2–§5.10 are their consequences.

### 5.2 Framing — what kind of project, and the dual economic view

The Gansu site is **615 MW wind + 330 MW solar + 294.5 MWh/98.16 MW battery serving a 50–100 MW load** behind a 945 MW export / 400 MW import PCC. Generation ≫ load (~10×), so the plant is **overwhelmingly a merchant exporter with a small embedded load**; the §3 objective (minimize Σcost, `c_energy = c_import − r_export`) is *maximizing net export revenue*. Project finance builds **directly from the D13 hourly real-money telemetry**.

Two economic **views**, both reported per policy (they answer different questions):

| View | CAPEX basis | Benefit stream | Answers |
|---|---|---|---|
| **(I) Absolute project** | full plant | annual operating net revenue under policy π (hourly-integrated, P1) | *Is the whole plant a good investment?* |
| **(II) Incremental storage** | battery CAPEX only | Δ(operating result) of π-with-battery **vs the no-battery baseline** | *Does the battery pay for itself; which policy maximizes its value?* |

View (II) is the **per-policy discriminator**: every §11 policy operates the *same physical plant* and differs only in **battery dispatch** (and wear→replacement). Holding renewables/CAPEX fixed, the storage-incremental NPV isolates exactly what each policy's dispatch is worth.

### 5.3 Revenue & cost streams — the multi-product, time-series schema

End-product prices are **scenario-specific and time-dependent**, and physical quantities are **hourly time series**. The model is therefore a set of **revenue/cost streams**, each = an hourly quantity (from dispatch) × an hourly price (from the scenario):

| Stream | Quantity `q_{s,t}` (hourly, from dispatch) | Price `p_{s,t}` model | Source |
|---|---|---|---|
| Electricity export | `P_export` MWh | **TOU** sell (§3.4 spread model) | exists (D13 `r_export`) |
| Electricity import (cost) | `P_import` MWh | **TOU** buy (§3.7) | exists (D13 `c_import`) |
| Demand charge (cost) | monthly peak MW | ¥/MW·month (§3.7, D10/D21) | exists (D13 `c_demand_charge`) |
| Hydrogen sales | `H2_kg` (§8 electrolyzer) | **flat contract OR indexed** ¥/kg | §8.2 `R_H2` |
| Aluminum / end-product sales | product tonnes (§8 load→offtake) | **spot OR contract** ¥/t | §8 (offtake archetype) |

**The price model is part of the stream schema**, and each stream's price may be: `flat` (constant ¥/unit), `tou` (the §3.7 schedule), `indexed` (a reference series × multiplier), or `spot` (an exogenous hourly series). This generality is required because electricity is TOU (already modeled), H2 is typically a flat or indexed contract, and aluminum is spot/contract — the schema must allow **all** without privileging electricity. New streams (from §8 compositions) register the same way: declare `q` source + `p` model. Each stream carries an `escalation_pct_per_year` (§5.6).

### 5.4 The accounting bridge — D13 → cash flow (memo-vs-cash ruling)

Finance composes **on top of** the LOCKED D13 identity (it does not alter it). Each D13 term maps to a cash treatment; three require an explicit honesty ruling to avoid double-counting:

| D13 term | Cash treatment | Rationale |
|---|---|---|
| `c_energy` (= c_import − r_export) | **Cash** — net grid energy, hourly-integrated (P1) | actual money with the grid |
| `c_demand_charge` | **Cash** — demand charges paid | actual money |
| `c_degradation` (¥10/MWh throughput) | **MEMO only — excluded from cash flow** | a dispatch-shaping proxy for cell wear; the real cash hit is the **replacement CAPEX** (§5.5). Counting both double-charges wear. Kept as a reported memo so over-cycling stays visible. |
| `c_curtail` (¥800/MWh penalty) | **MEMO only — excluded** | curtailment is *foregone export revenue*, already in a lower `r_export`; 800 ¥/MWh is a shaping penalty, not a cash outflow. |
| `c_voll` (¥20 000/MWh penalty) | **MEMO / optional cash** (default excluded) | a reliability shadow price; cash only under explicit PPA liquidated-damages (toggle). |

**Annual operating cash flow (EBITDA-like), built hourly then summed (P1):**

```
EBITDA(y) =  Σ_streams Σ_t (revenue_{s,t} − cost_{s,t})        # electricity, H2, aluminum, … (§5.3)
           − FixedOM(y) − VarOM(y)                            # from B econ facet (§5.7)
```

### 5.5 CAPEX, construction, replacement, terminal value

CAPEX is per device-model instance, summed over the site, keyed by the **same device-model ID** B's physics facet uses (§1 keystone):

```
generators (wind, solar, gas):  CAPEX_i = capacity_kw_i · capex_per_kw_yuan_i
storage (battery):              CAPEX_i = energy_kwh_i · capex_energy_per_kwh_yuan_i
                                        + power_kw_i  · capex_power_per_kw_yuan_i
grid / fixed infrastructure:    CAPEX_i = capex_lump_sum_yuan_i
Total_overnight_CAPEX = (Σ_i CAPEX_i) · (1 + soft_cost_fraction)     # dev, owner's cost, contingency
```

**Construction/commissioning:** default **overnight at t=0**; optional phasing spreads `Total_overnight_CAPEX` over `T_c = max_i(construction_months)` (linear/S-curve), with **IDC capitalized only if debt is modeled** (§5.8). COD = year 0; operations years 1…N. **Replacement (degradation-driven):** when a device reaches calendar life (`lifetime_years`) or usage life (`cycle_life_full_equiv` / `eol_soh_threshold`), C resets its params and D books `replacement_cost_fraction · CAPEX_i` that year — typically **one battery replacement in a 20-yr horizon, and policy-dependent** (harder cycling → earlier replacement → worse NPV; this is the channel that monetizes §5.4's memo `c_degradation`). **Terminal value (year N):** `Σ_i residual_value_fraction_i · CAPEX_i − Σ_i decommissioning_cost_yuan_i`; optional Gordon continuing-value for assets running beyond N.

### 5.6 Multi-year mechanics & conventions — *what C must apply*

C produces, per policy and year y∈{1…N}, a degraded+escalated 8760-h dispatched year (the P2 atom) yielding hourly quantities, realized prices, throughput, and replacement triggers. D requires C to apply (all in one basis):

| Convention | Param | Default | Note |
|---|---|---|---|
| Tariff escalation | `tariff_escalation_pct_per_year` | configurable (~2%/yr nominal) | applies to buy, sell/spread, **and** demand_rate |
| Per-stream price escalation | `escalation_pct_per_year` (per stream) | configurable | H2/aluminum contracts escalate independently |
| O&M inflation | `opex_inflation_pct_per_year` | configurable (~2.5%/yr) | FixedOM, VarOM |
| Capacity fade | `degradation_pct_per_year` (from B) | per device | E_gen(y) compounding; **D references B, doesn't redefine** |
| Basis | nominal vs real | **nominal** | escalations + discount rate in the **same** basis (the classic error); real toggle deflates by one CPI |
| Discount timing | end- vs mid-year | **end-year** | mid-year = ×(1+r)^0.5, optional |
| Year index | — | **CF(0)=−CAPEX, ops y=1…N** | replacement & residual land on their year |

The within-year env is unchanged (§3); C wraps it with per-year closure constants — consistent with §7 purity (year boundary is a host point, like D21's calendar boundary).

### 5.7 Econ facet — *what B must carry* (D defines the fields; B's schema carries them on the device ID)

| Field | Unit | Used for |
|---|---|---|
| `capex_per_kw_yuan` | ¥/kW | overnight CAPEX (wind, PV, gas) |
| `capex_energy_per_kwh_yuan` / `capex_power_per_kw_yuan` | ¥/kWh / ¥/kW | storage two-part CAPEX (battery) |
| `capex_lump_sum_yuan` | ¥ | fixed infrastructure (grid/PCC) |
| `opex_fixed_per_kw_year_yuan` | ¥/kW·yr | annual fixed O&M |
| `opex_var_per_mwh_yuan` | ¥/MWh | variable O&M on throughput (≠ D13 `c_degradation`) |
| `lifetime_years` | yr | calendar EOL → replacement + depreciation |
| `cycle_life_full_equiv` / `eol_soh_threshold` *(storage)* | cycles / fraction | usage EOL trigger |
| `replacement_cost_fraction` | fraction | replacement CAPEX vs original (learning-curve <1) |
| `residual_value_fraction` | fraction | salvage at horizon end |
| `degradation_pct_per_year` | %/yr | capacity fade — **shared with B physics** |
| `construction_months` | months | CAPEX phasing / IDC |
| `decommissioning_cost_yuan` | ¥ | terminal cost |
| *(tax layer)* `depreciation_years`, `depreciation_method` | yr / enum | tax depreciation |

The env build-step **ignores** the econ block (it never enters the jitted `step`); these fields exist solely for D's offline calc. Recommended home: an `econ:` block beside `physics:` on the same device-model ID in B's `config/device_models.yaml` — one ID, three facets.

### 5.8 Metrics — exact formulas (¥; discounting on annual CF(y), y=0…N)

`CF(0) = −Total_overnight_CAPEX` (or phased draws); `CF(y) = EBITDA(y) − Replacement(y) − Tax(y)`, `1≤y<N`; `CF(N)` adds Terminal value.

```
NPV(r)  = Σ_{y=0}^{N} CF(y)/(1+r)^y
IRR     : Σ_{y=0}^{N} CF(y)/(1+IRR)^y = 0        # numeric; report MIRR alongside (replacement years can flip CF sign → multi-IRR)
MIRR    = [ FV_pos/−PV_neg ]^(1/N) − 1            # FV_pos at reinvest r_r; PV_neg at finance r_f (default both = r)
LCOE    = PV(CAPEX+FixedOM+VarOM+Replacement−Residual) / PV(E_net delivered MWh)        # ¥/MWh
LCOS    = PV(battery CAPEX+O&M+replacement−residual+charging cost) / PV(MWh discharged)  # ¥/MWh; policy-sensitive
Payback : min{y : Σ_{0}^{y} CF ≥ 0} (simple) and on discounted CF; fractional by interpolation
DSCR(y) = CFADS(y)/DebtService(y),  CFADS ≈ EBITDA − Tax       # if debt on (§5.8 toggle); report min & average
```

`E_net` and the LCOS discharged-MWh denominator are defined from the hourly trajectory (P1/P2), not annual summaries.

### 5.8b Tax & debt — layered, default-off (clean base case)

Base case = **pre-tax, all-equity (unlevered project IRR)**. **Tax toggle:** corporate `tax_rate` (China 25%; renewable preferential 15% as documented alt), straight-line depreciation (B), simple cumulative loss offset; out of scope v1: VAT (net-of-VAT prices assumed), deferred tax, incentive timing. **Debt toggle:** simple amortizing loan at `gearing`/`interest_rate` → **equity IRR** + DSCR; out of scope v1: sculpting/DSRA/refinancing/tranches. Both reported as **deltas** to the base case; debt `interest_rate` doubles as the interest-rate sensitivity axis.

### 5.9 Ensemble / distributional from day one — *the §12 coupling*

**The finance interface takes an ENSEMBLE of dispatched-year results, and its outputs are DISTRIBUTIONS — even though v1 fills the ensemble with N=1.** This is mandatory so the §12 / PR #77 block-bootstrap generator (unlimited statistically-faithful weather years) plugs in as Monte-Carlo with **no breaking change**.

```
input  :  ensemble = { multi_year_run_m : m = 1…M }       # M weather draws from §12 (v1: M=1)
          multi_year_run_m = (dispatched_year_{m,y} : y = 1…N)   # each a P2 atom (8760-h hourly trajectory)
per draw:  cash_flow_m → { IRR_m, NPV_m(r), LCOE_m, LCOS_m, payback_m }
output :  exceedance distribution over m → P50 / P90 / P99 of each metric
          (e.g. "P90 IRR" = the 10%-exceedance IRR — the bankability/debt-sizing number real project finance uses)
```

- **Bankability framing:** real renewable project finance sizes debt and equity off **exceedance probabilities** (P50 base case, P90/P99 downside). Reporting P50/P90/P99 IRR/NPV/LCOE is the industry-standard form, and it is the natural shape of an ensemble — so the schema is exceedance-shaped from the start.
- **v1 degenerate case:** with M=1 (the §12 generator not yet implemented), every percentile collapses to the single realized year; the UI shows a point estimate that *becomes a fan* when M grows — same schema, no migration.
- **The relative policy ranking is robust even at M=1** (all policies share the same draw); only the absolute distribution width needs M>1.

### 5.10 Sensitivity — a surface, not a line

The USER's rate-sensitivity requirement **composes with weather uncertainty** into a 2-D surface:

1. **Discount-rate sweep (primary 1-D display):** NPV(r) over r∈[3%,12%] per policy at the **P50** weather percentile; IRR is the x-intercept; overlaid across policies with the DP-oracle as the ceiling.
2. **Sensitivity surface (the composition):** NPV (or IRR) over **(discount rate × weather exceedance percentile)** — the rate axis the USER asked for, crossed with the P50/P90/P99 axis from §5.9. v1 (M=1) shows the rate axis only; the percentile axis populates when Monte-Carlo lands.
3. **Tornado diagram:** one-at-a-time ± swings ranked by |ΔNPV| — CAPEX (±20%), tariff/price escalation (±2pp), battery cycle-life→replacement timing (±), discount rate (±2pp), O&M (±20%), **weather percentile (P50↔P90)**, replacement cost (±).
4. **Interest-rate sweep (if debt on):** equity IRR & min-DSCR vs `interest_rate`.

### 5.11 Per-policy comparison + delivery — *off-wire REST resource (decided)*

**Finance is an off-wire batch artifact**, not a telemetry change (integrated decision, frontend-reviewer consult): a new REST resource

```
GET /api/finance/compare?policies=…&scenario=…
→ { per policy π : { View I & II : { P50/P90/P99 of IRR, NPV(r_base), LCOE, LCOS, payback, [equity IRR, min DSCR] },
                     cash_flow_series, npv_vs_r_curve, sensitivity_surface },
    provenance : { checkpoint_id, weather_mode, M, discount_rate, escalation_assumptions, scenario_id, code_version } }
joined to operating runs by (policy_id, checkpoint_id, scenario_id)
```

- It composes **on top of** the LOCKED D13 real-money identity (operating cost → annual OPEX line, no double-count) and does **not** touch the LOCKED `eval_compare` (Kind 3) per-step wire — finance is a different shape/cadence (aggregate, batch), so a REST resource avoids a telemetry version bump.
- **Provenance travels with every result** (checkpoint-id, weather-mode/M, discount & escalation assumptions, scenario-id) so the E UI can **refuse to compare results computed under mismatched assumptions** (e.g. different discount rate or weather mode) — a correctness guard, not cosmetics.
- **Comparison semantics:** all §11 policies share CAPEX and the same scenario, differing only in dispatch (P2). Headline discriminator = **NPV at r_base** and **incremental-battery NPV vs no-battery** (View II). **Economic optimality gap** = `(NPV_oracle − NPV_π)/|NPV_oracle|` with the **DP-oracle as the economic ceiling** — the ¥ analog of §11.4's optimality gap, so the §11 information-set ladder re-expresses directly in money: RL must beat MPC's NPV and approach the oracle's.

### 5.12 Limitations & assumptions (honest)

1. **Single weather draw in v1 (M=1)** — absolute IRR/NPV are point estimates; the *distribution* arrives only when the §12 generator feeds M>1. **Mitigated by design:** the schema is already ensemble/exceedance-shaped (§5.9), so this is a *data* gap, not an *architecture* one. Relative policy ranking is robust at M=1.
2. **Price model = TOU+spread (+ flat/indexed/spot contracts)** — no forward-market/PPA-structure risk modeling, no negative-price dynamics beyond the §3 penalty.
3. **Deterministic availability** — no forced-outage stochastics; a flat `availability_factor` knob is the only hook.
4. **Simplified financing** — single amortizing loan toggle; no sculpting/DSRA/refinancing/tranches.
5. **Simplified tax** — straight-line depreciation, single rate, no VAT/deferred tax/incentive timing.
6. **Overnight + simple-phasing CAPEX** — cost-overrun risk captured only via the tornado CAPEX swing.
7. **Replacement = discrete EOL param-reset** — continuous battery augmentation modeled as a step.
8. **Real-option value ignored** — flexibility/repowering/expansion unvalued (v2).

### 5.13 Decisions requested at the Fable gate (→ USER summary)

1. **Accounting rulings (§5.4):** confirm `c_degradation`/`c_curtail`/`c_voll` are **memo-only** (wear's cash impact flows through replacement CAPEX).
2. **Base case (§5.8b):** pre-tax, all-equity unlevered, with tax & debt as reported toggles — or levered-after-tax as the headline?
3. **Discount rate (§5.8/5.10):** base WACC for a Gansu utility-scale renewable (China ≈ nominal 7–9% / real 5–7%) — confirm a default + sweep range, or USER-specify.
4. **Horizon (§5.6):** 20-yr base + 10-yr variant (battery replacement ~yr 10–12) — confirm both.
5. **Dual view (§5.2):** confirm reporting **both** absolute and incremental-battery economics, with incremental-vs-no-battery as the per-policy headline.
6. **Revenue streams (§5.3):** confirm the multi-product set for the USER's site (electricity always; H2 and aluminum if the §8 composition includes electrolyzer/offtake) and each stream's price-model type (flat/tou/indexed/spot).
7. **Econ defaults (§5.7):** ship Chinese 2024/25 benchmark CAPEX/OPEX (cited as assumptions) as placeholders, or leave fully configurable with no shipped defaults?
8. **Ensemble target (§5.9):** confirm exceedance reporting at **P50/P90/P99**, and that v1 ships M=1 with the ensemble schema in place (Monte-Carlo over §12 as the immediate follow-on).
9. **Currency/basis:** all **¥ (RMB), nominal** — confirm.

## 6. Workstream E — Policy-selector economics UI  ·  *frontend-reviewer consult, integrated*

**Goal:** choose one or more policies (RL checkpoint(s) + §11 baselines) and view their **economic** results **side-by-side** (the D outputs: IRR/NPV/LCOE, cash-flow curves, sensitivity).

**Design (frontend-reviewer consult, integrated):**
- **Finance is a NEW REST resource — kept OFF the LOCKED per-step wire.** `eval_compare` (Kind 3) is LOCKED, per-step/per-episode *operating* results under D13; project finance is a **batch artifact** (one trajectory per (policy, scenario), different shape and cadence). Shoehorning it into Kind 3 would break the lock or abuse the schema (any finance term on the wire = additive minor bump + both-reviewer re-review per the schema's versioning rule — a deliberate decision, not an assumption). **Recommendation: `GET /api/finance/compare?policies=…&scenario=…`** returns a structured economic-comparison doc (per policy: IRR/NPV/LCOE scalars, cash-flow series by year, sensitivity grid, + provenance: checkpoint-id, weather-mode, discount/escalation assumptions). The eval-vs-baseline panel keeps streaming operating results over `eval_compare`; **E layers the economic doc on top, joined by `(policy-id, checkpoint-id, scenario-id)`** so the economics shown provably match the operating run shown. No telemetry change needed.
- **N-policy side-by-side (N≈2–6):** (1) **comparison table = the spine** — policies as columns, metrics as rows (IRR % · NPV ¥@base-discount · LCOE ¥/MWh · payback yr · CAPEX ¥ · 20-yr OPEX ¥), units in every row label, best-in-row highlighted, columns badged RL-vs-baseline + checkpoint-id; (2) **overlaid cumulative *discounted* cash-flow curves** (x=year 0–20, zero line + break-even markers, shared axes — reuse the dashboard's multi-series chart); (3) **sensitivity = overlaid NPV-vs-discount-rate lines** — the **crossover** ("at what discount rate does RL stop beating TOU") is the decision-relevant insight (beats separate heatmaps for ≤6 policies); (4) **assumptions banner shown once** (discount, escalation, horizon, weather-mode, scenario) — and **refuse to compare (or hard-badge) policies evaluated under different assumptions** (correctness guard); (5) selector = the planned checkpoint-id multi-select picker over RL checkpoints (run/step/eval-score provenance) + §11 baselines, type-badged, **no silent truncation** past the cap.
- **Boundary:** D owns the D13→cash-flow accounting basis; E must display the linkage honestly ("D13 operating cost → annual OPEX line"; no double-count). E depends on D's model + the serving checkpoint-id picker.

---

## 7. Sequencing & dependencies

Foundation-first, matching the dependency graph (§1):

1. **B — device-model schema** (physics facet + parity-equals-Gansu). *Unblocks A, C, D.* The critical path.
2. **A (geo-UI)** and **C (multi-year)** — parallelizable once B's schema exists (A composes B devices; C uses B degradation).
3. **D (project finance)** — needs B's econ facet + C's multi-year trajectory + §11 policies. finance-expert designs in parallel with B/C (design is not blocked; *implementation* is).
4. **E (policy-econ UI)** — needs D's model + comparison schema; last.

Design work (this plan, and each section's detailed design) can proceed in parallel **now**; *implementation* follows the foundation-first order, each via the normal contract-first gate.

### 7.1 v1 scope — and what is explicitly NOT being built now (USER directive)

**v1 ships the power-supply scenario end-to-end ONLY** (§1.1). To keep the scope honest:

- **IS v1:** B device-schema (Gansu 4 models + bit-parity, incl. the tariff array) · A geo-UI for power-supply sites · C multi-year for the power-supply site · D project finance with the revenue-stream abstraction but **only the `grid_export` stream wired** · E policy-econ UI for power-supply.
- **NOT v1 (design-proven config-only additions, deferred):** the **hydrogen / aluminum / data-center-token** scenarios (the §1.1 table demonstrates all three are config — electrolyzer/H₂-revenue, industrial-load/avoided-cost, data-center-load/token-revenue — so they're validation cases, not built now); the **flexible/shiftable-load action extension** (data-center deferrable jobs — the one future scenario that touches the *action* space, §1.1 nuance — explicitly out of v1); the full §8 device library beyond Gansu's 4 (gas, electrolyzer, the other load archetypes) as *populated schema entries*; non-Gansu site-specific checkpoint formats; `lax.scan`-across-years (the Y≫20 extension point); the Monte-Carlo ensemble over §12 (finance §5.9 ships **M=1** with the ensemble schema in place — MC plugs in with no breaking change); the API-key map-tile providers (open-tile default only).
- **The abstraction must be *demonstrated*, not *implemented*, in v1:** D's revenue-stream field must exist and be exercised by `grid_export`; B's schema/resolver must be general enough that adding the electrolyzer entry is config — but we do not ship hydrogen/aluminum. This is what keeps the USER's expansion architecturally cheap without multiplying v1.

---

## 8. Cross-cutting contracts, locks, and risks

- **New shared contract:** `contracts/shared/device_model_schema.md` (B) — the schema + resolver; shared (env/A/C/D consume) → rl-architect lock after both reviewers comment. The device-model-ID join-key invariant becomes binding across visual/physics/econ.
- **Gansu parity (D11):** the single highest risk — B's refactor must preserve bit-parity. Mitigation: the `resolve_gansu() == EnvParams()` parity test (covering scalars **and** the `price_table` tariff array, per the B §2 structural gap) is B's first acceptance gate, before any new device models.
- **Known refactor (jax-env-engineer):** the module-level hardcoded `PRICE_TABLE_YPW` in `jax_env.py` must move into `EnvParams.price_table` (per-site tariff) — a prerequisite inside B, not a separate task. The jitted `step` reads `params.price_table`, preserving §7 purity.
- **A/E contract test cases (frontend-reviewer, required when A/E reach gating):** the A/E contracts must name as required cases an **ID-join-key test** (configured device ID with no schema entry → surfaced hard error) and a **provenance-integrity test** (weather-mode stamped + displayed; mismatched-assumption comparison refused) — so the §8 guardrails are gated, not discovered late.
- **Serving-owned surfaces need both reviewers:** the `/api/finance/compare` resource and the geo-fetch async endpoint are serving contracts the frontend consumes — when drafted, loop backend-reviewer (shape) **and** frontend-reviewer (consumption) so join keys + units are pinned on both sides.
- **LOCKED telemetry/checkpoint:** unaffected by B's params; *new cost/finance terms on the wire* = additive minor version bump (re-review by both reviewers per the schema's versioning rule) — flagged for D.
- **New spec section:** §13 project-finance (D) — a **REBUILD_SPEC change → human-gated** per CLAUDE.md; finance-expert drafts, USER approves (this plan's gate already routes to the USER).
- **§7 purity:** B (build-time resolve), C (year-boundary host work), A (offline fetch) all keep the jitted `step` pure — verify in each section's feasibility.
- **Scope risk:** this is five workstreams; the plan recommends shipping **B + the Gansu-parity proof first** as a thin vertical slice, then layering A/C/D/E — rather than a big-bang. Flag for the gate.
- **Frontend correctness guardrails (frontend-reviewer, both A & E):** (1) **units on every displayed number** via the shared formatting utilities (¥, ¥/MWh, MW, MWh, %, yr) — a bare/wrong unit on a finance/energy figure is a critical-bug class; (2) **device-model ID is the literal end-to-end join key** — sourced verbatim from schema/registry, never re-typed/aliased; a missing entry surfaces a hard error (registry-drift-guard analogue); (3) **provenance integrity** — weather-mode + finance assumptions stamped into artifacts and shown on results; synthetic never misread as real; mismatched-assumption comparisons refused; (4) **reuse existing serving REST/WS + single-source telemetry store** — no rogue sockets, no duplicated parsing; (5) **never reimplement composition/finance math in TS** — UI previews (site totals, derived econ) come from the *same* server-side §8.4 resolver / D finance model the simulation uses, or are explicitly tested to match.

---

## 9. Decisions requested at the Fable gate (→ USER summary)

1. **Endorse the device-model-schema-as-keystone architecture** (one ID, three facets; B foundational) **and the scenario-as-configuration abstraction (§1.1)** with **v1 = power-supply only** (hydrogen/aluminum design-proven, not built; §7.1) — and the **foundation-first sequencing** (B → A/C → D → E)?
2. **Schema location — RESOLVED, confirm:** sibling `config/device_models.yaml` keyed by the existing device IDs (keeps the 3D lock closed; ID is the join key regardless of file). **Three concurring votes** (rl-architect, frontend-reviewer, jax-env-engineer) — flagging for the record, not reopening.
3. **Scope/phasing:** thin vertical slice first (B + Gansu-parity, then the power-supply scenario end-to-end), then defer hydrogen/aluminum as config-only validation — confirm this is the intended boundary?
4. **§13 project-finance spec section** — confirm finance-expert authors it and it goes to the USER as a REBUILD_SPEC change.
5. **Multi-year scope (C):** 10 *and* 20 yr; escalation model (flat % vs scenario); replacement at EOL — any USER constraints to fix now?
6. **Accounting basis (D):** confirm finance composes on top of the LOCKED D13 real-money identity (operating cost → project cash flow), with finance as a **separate REST resource** (`/api/finance/compare`, joined to operating runs by `(policy-id, checkpoint-id, scenario-id)`) — **OFF** the LOCKED per-step `eval_compare` wire (frontend-reviewer recommendation; no telemetry change).
7. **Finance-specific rulings — see finance-expert's §5.13 (9 decisions)** for the USER: the memo-vs-cash accounting ruling (§5.4 — degradation/curtail/VOLL memo-only, wear's cash impact via replacement-CAPEX), pre-tax/all-equity base case, WACC default+range, 10 & 20 yr, dual View I/II, ¥-nominal basis, and the **P50/P90/P99 ensemble target (v1 = M=1 point estimate, schema ready)**. These are the finance section's gate decisions; §9-1…6 are the plan-level ones.

---

## 10. Out of scope here
No implementation, no contracts, no spec-section text yet. This is the coordination draft; detailed per-workstream designs (esp. D, authored by finance-expert) and any REBUILD_SPEC change are downstream of the Fable gate and the USER summary.
