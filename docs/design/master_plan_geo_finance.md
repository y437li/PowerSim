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

**Deliverable (this plan):** the financial model — principles, formulas, conventions, data shapes, named invariants, and the schema obligations it places on B, C, and the eval path. The downstream **§13 project-finance SPEC section** (human-gated REBUILD_SPEC change) formalizes this after the Fable gate. Default cost figures and pass/fail numbers are contract-stage decisions (§5.13).

### 5.1 Three foundational principles (these constrain everything below)

**P1 — Hourly-resolved revenue integration.** Every revenue/cost stream is accounted at the **hourly** level and integrated up; it is **never** approximated as annual-average-price × annual-quantity.

```
revenue_s(year) = Σ_{t=1}^{8760} q_{s,t} · p_{s,t}      # per stream s, per hour t  (q = dispatch quantity, p = scenario price)
```

*Proof of necessity (valley/peak arbitrage):* the policy's entire value is **temporal** — charge in the ¥250/MWh valley, discharge into the ¥780/MWh critical peak (§3.7). The annual *average* price is unchanged by shifting energy; only the hour-by-hour product `q_t·p_t` captures the ¥530/MWh spread the policy harvests. **Annual-average accounting mathematically erases exactly the value the policy creates** — so it is prohibited. *Grounding:* the merged env already does this correctly — `EnvInfo.c_energy_yuan` per step is `price_t · quantity_t · Δt`, so an **hourly accumulation inside the env preserves arbitrage value**; finance must consume those hourly-accumulated per-stream sums, never reconstruct revenue from annual averages outside the env.

**P2 — The dispatched year is the atomic finance unit (storage couples hours).** SOC ties timesteps together, so project value **cannot be decomposed hour-by-hour independently** — a single hour's cash flow is not standalone-well-defined. The indivisible finance input is a **full dispatched year** (a `PolicyEvalResult`-grade object). This is *also why per-policy comparison is meaningful*: different policies produce different trajectories under **identical prices**, so the revenue difference is purely the policy's doing.

**P3 — Cash-flow basis = D13 real-money, enforced by type AND by test** *(named invariant **INV-BASIS**)*. Finance consumes **only** real money, **never** the RL reward. The input type accepts only the D13 real-money fields (`PolicyEvalResult.{energy_cost,demand_charge,degradation,curtailment,voll}_yuan` and per-stream extensions, §5.5); the reward-basis fields (`penalty_yuan`, `soc_*`, and any `cost_total_reward_basis_yuan` / `c_demand_shape` / `reward` upstream) must be **structurally unreachable** from the cash-flow path — not merely unused. *Grounding:* the merged `PolicyEvalResult` already separates these — `total_cost_yuan` = the 5 real-money summands, while `penalty_yuan` / `soc_violation_mwh` are sibling reporting fields **excluded** from the total. The invariant makes that separation load-bearing. **Reviewer-grade test (mandatory):** build a fixture where real-money and reward-basis totals differ materially (add SOC penalties + demand-shaping), run the cash-flow engine, and **assert the output equals the real-money number exactly and would FAIL if anyone ever wired `penalty_yuan`/reward-basis**. The §13 contract states the D13 rationale in one line so no future "simplification" collapses it.

### 5.2 Framing — merchant exporter, and the dual economic view

Gansu = **615 MW wind + 330 MW solar + 294.5 MWh/98.16 MW battery serving 50–100 MW load** behind 945 MW export / 400 MW import. Generation ≫ load (~10×) ⇒ merchant exporter with embedded load; the §3 objective maximizes net export revenue. Two economic **views**, both reported per policy:

| View | CAPEX basis | Benefit stream | Answers |
|---|---|---|---|
| **(I) Absolute project** | full plant | annual operating net revenue under π (hourly-integrated, P1) | *Is the whole plant a good investment?* |
| **(II) Incremental storage** | battery CAPEX only | Δ(operating result) of π-with-battery **vs no-battery baseline** | *Does the battery pay; which policy maximizes its value?* |

View (II) is the **per-policy discriminator** (all §11 policies share CAPEX, differ only in battery dispatch + wear→replacement). For an own-load scenario (§5.3 aluminum), View (II)'s "benefit" is literally the **avoided cost** vs the grid-only counterfactual.

### 5.3 Revenue/cost streams as DATA — scenario = configuration *(BINDING; v1 = power-supply only)*

End-product prices are **scenario-specific and time-dependent**; physical quantities are **hourly time series**. The model therefore abstracts **revenue/cost streams as data**, keyed to the device that produces them — the *same* NPV/IRR/LCOE engine then prices any scenario by configuration alone:

```
stream = { type:           grid_export | grid_import | demand_charge | h2_sale | avoided_cost | … ,
           unit:           ¥/MWh | ¥/kg | ¥/t | ¥/MW·month ,
           source_device_id: <device-model id>            # the device whose dispatch produces q_{s,t}
           quantity_source:  which dispatch quantity feeds q_{s,t}   (P_export, H2_kg, load_served, …)
           price_model:     { kind: flat | tou | indexed | spot,  params | series } ,
           escalation_pct_per_year: <num> }
scenario = { id, streams:[…], price assumptions, weather_mode, discount/escalation } # the configuration that selects/prices streams
```

| Scenario (config) | Active stream(s) | Unit | Source device |
|---|---|---|---|
| **power-supply** (= Gansu) | `grid_export` (+ `grid_import`, `demand_charge` cost streams) | ¥/MWh, ¥/MW·month | grid/PCC |
| **hydrogen** | `h2_sale` | ¥/kg | electrolyzer (§8.2, kWh/kg physics) |
| **aluminum** | `avoided_cost` | ¥/t (via avoided ¥/MWh) | industrial-continuous load (§8.3) |

**v1 scope guard (USER-binding):** v1 ships **power-supply ONLY** — only `grid_export` (+ the `grid_import`/`demand_charge` cost streams) is **wired**; `h2_sale` and `avoided_cost` are **defined and demonstrated as config-only** (the field exists, exercised by `grid_export`; the others slot in by adding a stream entry, **not** built in v1). §5 *shows* they compose cleanly so the expansion is architecturally cheap. If the stream shape needs to flex B's device schema, that's a B-lock accommodation (flagged to the B owner).

### 5.4 The D13 → cash-flow mapping table *(mandatory artifact + named anti-double-count invariants)*

D13 "real money" means **economically real (not reward-shaping)** — but **not all real-money items are period cash**. The cash-flow engine maps each D13 component (a `PolicyEvalResult` field) as follows; each row carries a named invariant and a hand-computed no-double-count test:

| D13 component (field) | Period cash? | Cash treatment | Invariant + hand-computed test |
|---|---|---|---|
| `energy_cost_yuan` = c_import − r_export | **Yes** — operating cash | split into **`grid_export` revenue** and **`grid_import` cost** streams, each hourly-integrated (P1) | — (direct; test: Σ hourly q·p = field) |
| `demand_charge_yuan` | **Yes** — operating cash | direct OPEX line (¥/MW·month, D10/D21) | — |
| `degradation_yuan` (c_degradation, ¥10/MWh) | **No** — not period cash | the dispatch-layer **wear signal**; cash treatment = **battery replacement/augmentation CAPEX** scheduled by cumulative throughput/aging (lumpy, booked in the year incurred), optionally a reserve **accrual** | **INV-DEG:** never both the hourly proxy AND replacement CAPEX in the same cash flow. *Test:* a year of throughput → assert cash impact appears once (as replacement CAPEX at the EOL year), and `degradation_yuan` is memo-only (excluded from operating cash). |
| `curtailment_yuan` (c_curtail, ¥800/MWh) | **Conditional** | cash **only if** `scenario.curtailment_penalty_contract` flag ON; else **excluded** (the opportunity cost is already in reduced `grid_export` revenue) | **INV-CURT:** with the flag OFF, the cash loss of a curtailed MWh = **foregone export revenue ONLY**, not revenue+penalty. *Test:* a curtailment hour → assert cash loss == foregone `grid_export` revenue, **not** revenue + 800 ¥/MWh, when the flag is off. |
| `voll_yuan` (c_voll, ¥20 000/MWh) | **Conditional** | cash **only** as a contractual reliability penalty (`scenario.reliability_penalty_contract` ON); in **own-load** scenarios (aluminum/datacenter) the damage is **lost PRODUCT revenue** (captured in that stream), not VOLL | **INV-VOLL:** VOLL cash **XOR** lost-product revenue — never both. *Test:* an unserved-load hour in the aluminum scenario → assert the cash hit is the lost aluminum revenue once, not aluminum-loss + VOLL. |
| `penalty_yuan`, `soc_*` | **Never cash** | reward-shaping / safety reporting | **INV-BASIS** (§5.1 P3): structurally unreachable from the cash path; the reviewer-grade test proves it. |

The per-scenario contract flags (`curtailment_penalty_contract`, `reliability_penalty_contract`) live in the scenario config (§5.3). This table is the **canonical answer** to "does cash flow include degradation/curtailment costs": **degradation → only as replacement CAPEX; curtailment/VOLL → only under an explicit contract flag; otherwise the economic effect is already in the revenue streams.**

### 5.5 The finance input object — *extend `PolicyEvalResult`*

*Finding (grounded in merged `eval.py`):* today's `PolicyEvalResult` is **annual aggregates of 5 cost buckets** and carries **no per-stream split** (`c_energy` merges export+import) and **no physical quantities**. That is **insufficient** for finance, which needs per-stream revenue/cost and quantities for LCOE/LCOS/OPEX/replacement. The hourly integration is already correct inside the env (P1), so the fix is an **extended `PolicyEvalResult`** carrying hourly-accumulated **per-stream annual sums + physical quantities**:

```
extended PolicyEvalResult (per dispatched year, per policy, per scenario):
  streams:      { grid_export_yuan, grid_import_yuan, demand_charge_yuan, [h2_sale_yuan, …] }   # P1 sums
  quantities:   { export_mwh, import_mwh, generation_mwh, curtailed_mwh, unserved_mwh,
                  bat_throughput_mwh, bat_discharge_mwh, [h2_kg, …] }                            # for OPEX/LCOE/LCOS/replacement
  real_money:   { energy_cost_yuan, demand_charge_yuan, degradation_yuan, curtailment_yuan, voll_yuan, total_cost_yuan }  # existing D13
  memo_only:    { penalty_yuan, soc_violation_mwh, soc_violations_count }                        # INV-BASIS: never cash
```

This is a request on the **eval/env path** (jax-env + training owners): expose the per-stream + quantity accumulators in `EnvInfo`/`PolicyEvalResult`. v1 needs only `grid_export`/`grid_import`/quantities (power-supply); §8 streams add fields later. Flagged for the gate.

### 5.6 CAPEX, construction, replacement, terminal value

CAPEX per device-model instance, summed over the site, keyed by the **same device-model ID** as B's physics facet:

```
generators:  CAPEX_i = capacity_kw_i · capex_per_kw_yuan_i
battery:     CAPEX_i = energy_kwh_i · capex_energy_per_kwh_yuan_i + power_kw_i · capex_power_per_kw_yuan_i
grid/fixed:  CAPEX_i = capex_lump_sum_yuan_i
Total_overnight_CAPEX = (Σ_i CAPEX_i)·(1 + soft_cost_fraction)
```

**Construction:** default overnight at t=0; optional phasing over `T_c=max_i(construction_months)` (IDC capitalized only if debt on, §5.9b). COD=year 0; ops y=1…N. **Replacement (degradation-driven, the INV-DEG cash channel):** device reaches `lifetime_years` or `cycle_life_full_equiv`/`eol_soh_threshold` → C resets params, D books `replacement_cost_fraction·CAPEX_i` that year (≈ one battery replacement in 20 yr, **policy-dependent**). **Terminal (year N):** `Σ_i residual_value_fraction_i·CAPEX_i − Σ_i decommissioning_cost_yuan_i`; optional Gordon continuing-value.

### 5.7 Econ facet — *what B must carry* (D defines fields; B's schema carries them on the device ID)

| Field | Unit | Use |
|---|---|---|
| `capex_per_kw_yuan` | ¥/kW | gen overnight CAPEX |
| `capex_energy_per_kwh_yuan` / `capex_power_per_kw_yuan` | ¥/kWh, ¥/kW | battery two-part CAPEX |
| `capex_lump_sum_yuan` | ¥ | grid/fixed infra |
| `opex_fixed_per_kw_year_yuan` | ¥/kW·yr | fixed O&M |
| `opex_var_per_mwh_yuan` | ¥/MWh | variable O&M (≠ D13 `c_degradation`) |
| `lifetime_years` · `cycle_life_full_equiv` · `eol_soh_threshold` | yr · cycles · frac | replacement triggers + depreciation |
| `replacement_cost_fraction` · `residual_value_fraction` | frac | replacement / salvage |
| `degradation_pct_per_year` | %/yr | capacity fade — **shared w/ B physics; D references** |
| `construction_months` · `decommissioning_cost_yuan` | months · ¥ | phasing / terminal |
| *(tax)* `depreciation_years` · `depreciation_method` | yr · enum | tax layer |

The env build-step **ignores** the `econ:` block (never enters jitted `step`); it exists solely for D's offline calc. Recommended home: an `econ:` block beside `physics:` on the same device-model ID in B's `config/device_models.yaml`.

### 5.8 Metrics — exact formulas (¥; on annual CF(y), y=0…N)

`CF(0)=−Total_overnight_CAPEX`; `CF(y)=EBITDA(y)−Replacement(y)−Tax(y)`; `CF(N)` adds Terminal. `EBITDA(y)=Σ_streams Σ_t(rev−cost) − FixedOM − VarOM` (P1).

```
NPV(r) = Σ CF(y)/(1+r)^y
IRR    : Σ CF(y)/(1+IRR)^y = 0           # numeric; report MIRR (replacement years → multi-IRR risk)
MIRR   = [FV_pos/−PV_neg]^(1/N) − 1
LCOE   = PV(CAPEX+FixedOM+VarOM+Replacement−Residual) / PV(E_net MWh)       # ¥/MWh
LCOS   = PV(battery CAPEX+O&M+replacement−residual+charging cost) / PV(MWh discharged)   # ¥/MWh; policy-sensitive
Payback: simple & discounted, fractional by interpolation
DSCR(y)= CFADS(y)/DebtService(y), CFADS≈EBITDA−Tax     # if debt on
```

`E_net` / discharged-MWh come from the §5.5 quantity accumulators (P1/P2), not annual averages.

### 5.9 Ensemble / distributional from day one — *the §12 coupling*

The finance interface takes an **ENSEMBLE of dispatched-year results** and outputs **DISTRIBUTIONS**, even though v1 fills it with M=1 — so the §12/PR#77 block-bootstrap generator plugs in as Monte-Carlo with **no breaking change**:

```
input  : ensemble = { multi_year_run_m : m=1…M }     # M weather draws from §12 (v1: M=1)
per draw: cash_flow_m → { IRR_m, NPV_m(r), LCOE_m, LCOS_m, payback_m }
output : exceedance distribution → P50 / P90 / P99 per metric   # P90 IRR = the bankability/debt-sizing number
```

P50/P90/P99 is the industry-standard exceedance form and the natural shape of an ensemble; v1 (M=1) collapses to a point estimate that **becomes a fan** when M grows — same schema. Relative policy ranking is robust at M=1 (shared draw). **The §12 generator's validation battery (PR #77 §4.2) is part of D's evidence chain** — the P50/P90 numbers are only as valid as the ensemble's statistical fidelity (marginals, cross-correlation, ramp/persistence tails), so D's acceptance references it.

### 5.9b Tax & debt — layered, default-off (clean base case)

Base = **pre-tax, all-equity (unlevered project IRR)**. **Tax toggle:** `tax_rate` (China 25%; renewable 15% alt), straight-line depreciation, simple loss offset; out-of-scope v1: VAT, deferred tax, incentive timing. **Debt toggle:** simple amortizing loan at `gearing`/`interest_rate` → equity IRR + DSCR; out-of-scope v1: sculpting/DSRA/refinancing/tranches. Both reported as **deltas** to base.

### 5.10 Sensitivity — a surface, not a line

1. **Discount-rate sweep (primary 1-D display):** NPV(r), r∈[3%,12%], per policy at P50; IRR = x-intercept; overlaid with the DP-oracle ceiling.
2. **Sensitivity surface:** NPV/IRR over **(discount rate × weather exceedance percentile)** — the USER's rate axis crossed with the §5.9 P50/P90/P99 axis (rate axis v1; percentile axis when MC lands).
3. **Tornado:** ±swings ranked by |ΔNPV| — CAPEX (±20%), tariff/price escalation (±2pp), battery cycle-life→replacement (±), discount rate (±2pp), O&M (±20%), weather percentile (P50↔P90), replacement cost (±).
4. **Interest-rate sweep (if debt):** equity IRR & min-DSCR vs `interest_rate`.

### 5.11 Per-policy comparison + delivery — *off-wire REST resource (decided)*

Finance is an **off-wire batch artifact** (frontend-reviewer consult, integrated): a new REST resource

```
GET /api/finance/compare?policies=…&scenario=…
→ { per policy π : { View I & II : { P50/P90/P99 of IRR, NPV(r_base), LCOE, LCOS, payback, [equity IRR, min DSCR] },
                     cash_flow_series, npv_vs_r_curve, sensitivity_surface },
    provenance : { checkpoint_id, weather_mode, M, discount_rate, escalation_assumptions, scenario_id, code_version } }
joined to operating runs by (policy_id, checkpoint_id, scenario_id)
```

Composes **on top of** the LOCKED D13 identity; does **not** touch the LOCKED `eval_compare` (Kind 3) wire (different shape/cadence → REST avoids a telemetry bump). **Provenance travels with every result** so E **refuses to compare results computed under mismatched assumptions** (different discount rate / weather mode) — a correctness guard. **Comparison semantics:** all §11 policies share CAPEX + scenario, differ only in dispatch (P2); headline = NPV at r_base + incremental-battery NPV vs no-battery (View II); **economic optimality gap** `(NPV_oracle − NPV_π)/|NPV_oracle|` with the **DP-oracle as the economic ceiling** — the ¥ analog of §11.4's gap.

### 5.12 Limitations & assumptions (honest)

1. **Single weather draw in v1 (M=1)** — point estimates; the distribution arrives when §12 feeds M>1. *Mitigated by design:* schema already ensemble/exceedance-shaped (§5.9) — a data gap, not architecture. Relative ranking robust at M=1.
2. **Extended `PolicyEvalResult` is a prerequisite** (§5.5) — finance cannot run on today's 5-bucket aggregate; the per-stream+quantity accumulators must land first.
3. **Price model = TOU+spread (+flat/indexed/spot contracts)** — no forward-market/PPA-structure or negative-price modeling beyond §3.
4. **Deterministic availability** — no forced-outage stochastics (`availability_factor` knob only).
5. **Simplified financing & tax** — single loan toggle; straight-line depreciation, single rate.
6. **Overnight + simple-phasing CAPEX** — overrun risk only via the tornado.
7. **Replacement = discrete EOL param-reset** — continuous augmentation modeled as a step.
8. **Real-option value ignored** (v2).

### 5.13 Decisions requested at the Fable gate (→ USER summary)

1. **D13→cash-flow mapping (§5.4):** confirm the table + the four named invariants (INV-BASIS, INV-DEG, INV-CURT, INV-VOLL) and the per-scenario contract flags.
2. **Revenue-stream abstraction + v1 guard (§5.3):** confirm streams-as-data keyed by device, scenario=config, and **v1 wires `grid_export` only** (h2_sale/avoided_cost design-proven config-only).
3. **Extended `PolicyEvalResult` (§5.5):** approve the per-stream + physical-quantity accumulators as a prerequisite (eval/env-path change).
4. **Base case (§5.9b):** pre-tax, all-equity unlevered, tax/debt as toggles — or levered-after-tax headline?
5. **Discount rate (§5.8/5.10):** base WACC (China utility-scale ≈ nominal 7–9% / real 5–7%) — default + sweep range, or USER-specify.
6. **Horizon (§5.6):** 20-yr base + 10-yr variant (battery replacement ~yr 10–12) — confirm both.
7. **Dual view (§5.2):** confirm both absolute + incremental, incremental-vs-no-battery as per-policy headline.
8. **Ensemble target (§5.9):** confirm P50/P90/P99 exceedance reporting, v1 M=1 with the ensemble schema in place.
9. **Econ defaults (§5.7):** ship Chinese 2024/25 benchmark CAPEX/OPEX (cited assumptions) or leave configurable with no defaults?
10. **Currency/basis:** all **¥ (RMB), nominal** — confirm.

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
- **Extended `PolicyEvalResult` — a new D→eval/env coupling and a D prerequisite (finance-expert §5.5):** today's `PolicyEvalResult` is annual aggregates of 5 cost buckets with **no per-stream split** (`c_energy` merges export+import) and **no physical quantities** — **insufficient for finance** (LCOE/LCOS/OPEX/replacement need per-stream revenue/cost + export/import/throughput/discharge/generation MWh). The fix is hourly-accumulated per-stream + quantity accumulators in `EnvInfo`/`PolicyEvalResult` (the env already integrates hourly, so P1 holds). **This lands on the eval/env path (jax-env-engineer + training-engineer own it), is a prerequisite for D, and must be coordinated.** Likely NOT a LOCKED-wire change (finance is the off-wire REST resource; the accumulators feed it), but it touches the merged `eval.py`/`PolicyEvalResult` data structure → its own contract+tests via the env/training gate. v1 needs only `grid_export`/`grid_import` + the quantities (power-supply); §8 streams add fields later.
- **LOCKED telemetry/checkpoint:** unaffected by B's params; *new cost/finance terms on the wire* = additive minor version bump (re-review by both reviewers per the schema's versioning rule) — flagged for D. The extended-`PolicyEvalResult` accumulators (above) are intended for the **off-wire** finance path, so they should **not** require a telemetry bump — confirm at contract time.
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
