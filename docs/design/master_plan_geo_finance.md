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

---

## 2. Workstream B — Device-physics (+economic) schema  ·  *owner: jax-env-engineer (feasibility); builds on §8*

**Goal:** every device model carries its physics (and, jointly with D, its economics) as schema data, so the env is **schema-driven, not Gansu-hardcoded**. Adding a turbine/PV/battery/grid model = adding a schema entry.

**Design (plan-lead seed — jax-env-engineer to refine):**
- **Schema = the §8.2 params, made first-class and keyed by device-model ID.** §8 already specifies the param sets per *type* (wind: `p_rated,v_cutin,v_rated,v_cutout,hub_height`; PV: `p_capacity,k_T,eta_inv,degradation`; gas; electrolyzer; battery; loads). B turns each *concrete model* into a registry entry of `{type, physics:{…§8.2 params…}, econ:{…D params…}}`.
- **Location decision (open):** extend the LOCKED `assets/3d/registry.json` with a `physics`/`econ` block per ID (one registry, three facets — maximal cohesion, but edits a LOCKED file → superseding DECISION + re-lock), **or** a sibling `config/device_models.yaml` keyed by the same IDs (keeps the 3D lock untouched; two files share the ID invariant). *Plan-lead lean: sibling file keyed by the same ID* — avoids reopening the 3D lock, preserves the join-key invariant, and physics/econ params iterate faster than the visual lock should. jax-env-engineer + frontend-reviewer to weigh in.
- **Env consumption:** a site YAML references device-model IDs + instance counts/overrides; a Python **build step** resolves IDs → physics params → the §8.4 composed obs/action + the jitted `step` closure. `gansu_params.py` is replaced by *resolving the Gansu site's device IDs against the schema* — and the parity test asserts the resolved constants equal today's hardcoded values.
- **Scope:** start with the 4 Gansu device models (wind/PV/battery/grid) to prove schema-equals-hardcoded parity, then the §8 library (gas, electrolyzer, load archetypes) lands per-model as today (each its own contract + test, §8.5).
- **Contracts:** a new `contracts/env/device_model_schema.md` (the schema format + resolver) — likely a **shared** contract (env consumes; A/C/D reference) → rl-architect lock after both reviewers comment.

**Open decisions:** schema location (registry-extend vs sibling); how instance overrides vs model defaults compose; whether econ params live with physics (one schema) or in D's section (cross-referenced).

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
- **Device-side feasibility (jax-env-engineer to confirm):** the per-year params (degraded capacity, escalated prices) are **closure constants per year**, so a 20-year run = 20 jitted dispatch years with per-year param updates between them (host-side, cheap) — consistent with §7 (no host work *inside* `step`; the year boundary is a natural host point, like the §10/§D21 calendar boundaries). Whether to `lax.scan` across years or keep a Python outer loop mirrors the D27 training-loop decision (Python outer loop of jitted years is the likely answer; eval-at-year-cadence stays host-level).
- **Output:** C's product is the **per-year energy + cost + degradation trajectory** that D turns into cash flows. Sim-speed controls reuse the D24 replay-speed pattern at the year/episode level.

**Open decisions:** escalation model (flat %/yr vs scenario curves — coordinate with D); replacement policy (auto at EOL vs user-scheduled); whether multi-year eval runs the RL policy, the §11 baselines, or both across the horizon.

---

## 5. Workstream D — Project finance  ·  *owner: finance-expert (Sonnet impl: finance-engineer)*  ·  **STUB — finance-expert designs**

**Plan-lead framing (requirements + dependencies; finance-expert owns the design):**
- **Deliverable:** a **new spec section** (proposed §13 project-finance) + a UI section. Owned and reviewed by finance-expert; implemented by finance-engineer after gates.
- **Inputs:** CAPEX/OPEX from the **B device-model econ facet**; multi-year cash-flow trajectory from **C**; the policy set from **§11** (RL vs TOU vs no-battery vs greedy/MPC/DP-oracle).
- **Required outputs (from the USER directive):** 20-year cash flows; **IRR / NPV / LCOE**; **discount/interest-rate sensitivity analysis** (display); **per-policy economic comparison** (each policy's operating result → its project economics, side by side).
- **Cross-cutting hooks finance-expert should specify:** which econ params B must carry (CAPEX/kW, fixed+variable OPEX, replacement cost, lifetime, residual value, …); the escalation/discount conventions C must apply; whether finance terms enter telemetry (likely a separate `eval_compare`-adjacent economic rollup, not the per-step wire) — coordinate the accounting basis with the LOCKED D13 real-money identity so "operating cost" composes cleanly into "project cash flow."
- **finance-expert: please author this section** (model structure, formulas, assumptions, sensitivity methodology, the per-policy comparison schema) and flag what B/C must provide.

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

---

## 8. Cross-cutting contracts, locks, and risks

- **New shared contract:** `contracts/env/device_model_schema.md` (B) — the schema + resolver; shared (env/A/C/D consume) → rl-architect lock after both reviewers comment. The device-model-ID join-key invariant becomes binding across visual/physics/econ.
- **Gansu parity (D11):** the single highest risk — B's refactor must preserve bit-parity. Mitigation: schema-resolves-to-current-constants parity test as B's first acceptance gate, before any new device models.
- **LOCKED telemetry/checkpoint:** unaffected by B's params; *new cost/finance terms on the wire* = additive minor version bump (re-review by both reviewers per the schema's versioning rule) — flagged for D.
- **New spec section:** §13 project-finance (D) — a **REBUILD_SPEC change → human-gated** per CLAUDE.md; finance-expert drafts, USER approves (this plan's gate already routes to the USER).
- **§7 purity:** B (build-time resolve), C (year-boundary host work), A (offline fetch) all keep the jitted `step` pure — verify in each section's feasibility.
- **Scope risk:** this is five workstreams; the plan recommends shipping **B + the Gansu-parity proof first** as a thin vertical slice, then layering A/C/D/E — rather than a big-bang. Flag for the gate.
- **Frontend correctness guardrails (frontend-reviewer, both A & E):** (1) **units on every displayed number** via the shared formatting utilities (¥, ¥/MWh, MW, MWh, %, yr) — a bare/wrong unit on a finance/energy figure is a critical-bug class; (2) **device-model ID is the literal end-to-end join key** — sourced verbatim from schema/registry, never re-typed/aliased; a missing entry surfaces a hard error (registry-drift-guard analogue); (3) **provenance integrity** — weather-mode + finance assumptions stamped into artifacts and shown on results; synthetic never misread as real; mismatched-assumption comparisons refused; (4) **reuse existing serving REST/WS + single-source telemetry store** — no rogue sockets, no duplicated parsing; (5) **never reimplement composition/finance math in TS** — UI previews (site totals, derived econ) come from the *same* server-side §8.4 resolver / D finance model the simulation uses, or are explicitly tested to match.

---

## 9. Decisions requested at the Fable gate (→ USER summary)

1. **Endorse the device-model-schema-as-keystone architecture** (one ID, three facets; B foundational) and the **foundation-first sequencing** (B → A/C → D → E)?
2. **Schema location:** sibling `config/device_models.yaml` keyed by the existing device IDs (plan-lead lean, **concurred by frontend-reviewer** — keeps the 3D lock closed; UI resolves all three facets by the shared ID regardless of file), vs extending the LOCKED `registry.json` (one file, but reopens the lock)? *Two votes for the sibling file; awaiting jax-env-engineer.*
3. **Scope/phasing:** thin vertical slice first (B + Gansu-parity), then A/C/D/E — or broader parallel build?
4. **§13 project-finance spec section** — confirm finance-expert authors it and it goes to the USER as a REBUILD_SPEC change.
5. **Multi-year scope (C):** 10 *and* 20 yr; escalation model (flat % vs scenario); replacement at EOL — any USER constraints to fix now?
6. **Accounting basis (D):** confirm finance composes on top of the LOCKED D13 real-money identity (operating cost → project cash flow), with finance as a **separate REST resource** (`/api/finance/compare`, joined to operating runs by `(policy-id, checkpoint-id, scenario-id)`) — **OFF** the LOCKED per-step `eval_compare` wire (frontend-reviewer recommendation; no telemetry change). finance-expert to confirm the field set + basis.

---

## 10. Out of scope here
No implementation, no contracts, no spec-section text yet. This is the coordination draft; detailed per-workstream designs (esp. D, authored by finance-expert) and any REBUILD_SPEC change are downstream of the Fable gate and the USER summary.
