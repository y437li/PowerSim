# Master Plan — Geo-Data Selection · Device-Physics Schema · Multi-Year Simulation · Project Finance

> **Status:** DRAFT — coordinated plan, **no implementation**. **Review gate:** team-lead (Fable) reviews this draft and summarizes to the USER; implementation tasks spawn only after that gate (task #53).
> **Plan lead:** rl-architect (cross-cutting architecture + integration).
> **Workstream owners:** finance-expert → D · jax-env-engineer → B/C feasibility · frontend-reviewer → A/E consult.
> **Builds on:** §8 (composable assets), §12 / PR #77 (historical-weather design), §11 (benchmark ladder).
> **How to read:** §1 is the unifying architecture (the keystone). §2–§6 are the five workstreams — B/A/C seeded by the plan lead for domain refinement; D/E are framed requirements for their owners to design. §7–§9 are sequencing, contracts/risks, and the decisions requested at the gate.

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

The USER's expansion ambitions (power supply, hydrogen production, electrolytic-aluminum) must be **architecturally cheap, not multiplicative**. The containing principle, binding on this plan:

> **A scenario is purely a CONFIGURATION** — never a separate codebase, mode, or branch.
> `scenario = { site devices (from B's schema) } + { revenue / cost streams } + { policy objective }`.

This is the *second half* of the keystone: §1's device-model registry composes the **physical** site; the scenario abstraction composes the **economic + objective** layer on top — both pure config over the same device-model IDs. The three named scenarios then map cleanly to **existing §8 capabilities — no new code paths**:

| Scenario | Site composition (B / §8 devices) | Revenue / cost streams (D) | Status |
|---|---|---|---|
| **Power supply** (= today's Gansu) | wind + solar + battery + grid | grid-export revenue (¥/MWh, the §3 TOU tariff) | **v1 — the working end-to-end deliverable** |
| **Hydrogen production** | same site **+ electrolyzer** (§8.2 PEM/alkaline already specced) | H₂ revenue (¥/kg via the kWh/kg conversion physics, §8.2) replacing/augmenting export | **validation case** (config-only, design-proven) |
| **Electrolytic aluminum** | site **+ `industrial_continuous` load** (§8.3 archetype already specced) | avoided-cost / tariff economics for the smelter load | **validation case** (config-only, design-proven) |

That all three already decompose into §8's composable assets is the *proof* that the abstraction contains the complexity: adding a scenario = composing existing device models + declaring its revenue streams + objective, **not** writing a hydrogen-mode or aluminum-mode.

**The one structural requirement this adds (→ workstream D):** the finance schema must **abstract revenue streams per device/scenario** — `{type: grid_export | h2_sale | avoided_cost, unit: ¥/MWh | ¥/kg | …, source_device_id}` — rather than hardcoding electricity-export. With that, the same finance engine prices any scenario. *Flagged to finance-expert as binding for §5.*

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

## 5. Workstream D — Project finance  ·  *owner: finance-expert (Sonnet impl: finance-engineer)*  ·  **STUB — finance-expert designs**

**Plan-lead framing (requirements + dependencies; finance-expert owns the design):**
- **Deliverable:** a **new spec section** (proposed §13 project-finance) + a UI section. Owned and reviewed by finance-expert; implemented by finance-engineer after gates.
- **Inputs:** CAPEX/OPEX from the **B device-model econ facet**; multi-year cash-flow trajectory from **C**; the policy set from **§11** (RL vs TOU vs no-battery vs greedy/MPC/DP-oracle).
- **Required outputs (from the USER directive):** 20-year cash flows; **IRR / NPV / LCOE**; **discount/interest-rate sensitivity analysis** (display); **per-policy economic comparison** (each policy's operating result → its project economics, side by side).
- **BINDING (USER directive, §1.1): abstract REVENUE STREAMS, do not hardcode electricity-export.** The finance schema must represent revenue/cost streams as data — `{type: grid_export | h2_sale | avoided_cost | …, unit: ¥/MWh | ¥/kg | …, source_device_id}` — so the *same* finance engine prices power-supply (grid export), hydrogen (H₂ sale, ¥/kg), and aluminum (avoided cost) by configuration alone. This is the one structural requirement the scenario abstraction adds to D.
- **Resolved hooks (now firm):** finance is a **separate REST resource** (`/api/finance/compare`), **OFF** the LOCKED `eval_compare` wire, joined to operating runs by `(policy-id, checkpoint-id, scenario-id)` (frontend-reviewer; §6/§9-6). It composes **on top of** the D13 real-money operating-cost identity (operating cost → annual OPEX line, no double-count). Provenance (checkpoint-id, weather-mode, discount/escalation assumptions) travels with every result.
- **finance-expert: please author §5** (model structure, formulas, assumptions, sensitivity methodology, the revenue-stream abstraction, the per-policy comparison schema E renders) and flag the exact **econ field set B must carry** + the **escalation/discount conventions C applies**.

---

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
- **NOT v1 (design-proven config-only additions, deferred):** the **hydrogen** and **aluminum** scenarios (the §1.1 table demonstrates they're config — electrolyzer/H₂-revenue and industrial-load/avoided-cost — so they're validation cases, not built now); the full §8 device library beyond Gansu's 4 (gas, electrolyzer, the other load archetypes) as *populated schema entries*; non-Gansu site-specific checkpoint formats; `lax.scan`-across-years (the Y≫20 extension point); the API-key map-tile providers (open-tile default only).
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
6. **Accounting basis (D):** confirm finance composes on top of the LOCKED D13 real-money identity (operating cost → project cash flow), with finance as a **separate REST resource** (`/api/finance/compare`, joined to operating runs by `(policy-id, checkpoint-id, scenario-id)`) — **OFF** the LOCKED per-step `eval_compare` wire (frontend-reviewer recommendation; no telemetry change). finance-expert to confirm the field set + basis.

---

## 10. Out of scope here
No implementation, no contracts, no spec-section text yet. This is the coordination draft; detailed per-workstream designs (esp. D, authored by finance-expert) and any REBUILD_SPEC change are downstream of the Fable gate and the USER summary.
