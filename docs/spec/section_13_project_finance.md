## 13. Project finance (proposal — USER approval)
> **Owner:** finance-expert

**Status: PROPOSAL for USER approval — this is a REBUILD_SPEC change and is human-gated (CLAUDE.md).** This section is the canonical specification of the Energy GO project-finance layer: stage ⑤ of the product spine (D32), `config → algorithm → train → eval → **finance**`. It turns a dispatched operating result (the §11 / eval `PolicyEvalResult`, real-money basis per D13) into a full investor/lender-grade economic picture — **NPV, IRR, MIRR, LCOE, LCOS, payback as DISTRIBUTIONS** over a weather ensemble, with a **downside-risk centerpiece** and a **price-path scenario library**. It consolidates and supersedes the Workstream-D design corpus: master-plan §5 (`docs/design/master_plan_geo_finance.md`, D31), the CAPM discount-rate methodology, the lifecycle-events / asset-management cost model, and the stage-⑤ UX (`docs/design/ux/stage_5_finance.md`). Where the merged design and a later USER directive disagree, **the USER directive recorded in §13.13 governs and is flagged for sign-off**.

The finance engine is **off-wire, offline, and pure**: it never touches the LOCKED per-step `eval_compare` wire (it composes on top of the D13 identity as a separate REST resource, §13.11), and no network/I/O enters it (the treasury-curve table is a static config, §13.6). It is the **third consumer of the single per-step stream economics** (D32(b) single-config invariant): `reward streams ≡ eval-accumulator streams ≡ finance streams`.

---

### 13.0 Scope, basis, and the three foundational principles

**Scope (v1 = power-composite scenario, end-to-end).** v1 ships the **power-supply (power-composite) scenario** through the whole spine (D31/D32). The finance engine prices the **COMPOSITE of the active power-supply real-money streams** (grid export revenue, grid import cost, demand charge — §13.3), not a single hardcoded export line. The hydrogen / aluminum / data-center-token scenarios are **design-proven config-only** (their streams and lifecycle costs are schema-present and demonstrated to compose, but **not wired** in v1) — the revenue-side scope guard (§13.3) and the cost-side scope guard (§13.7) mirror each other.

**Basis (confirm at gate).** All amounts **¥ (RMB), nominal**; rates %/yr; energy MWh; power MW; capacity MWh / MW; tariffs ¥/MWh; demand charge ¥/MW·month. Unit conversions go through the one named utility (engineering rules). **Dispatch runs at constant-real year-1 prices (D31/F1)**; all escalation and price-path shaping are applied **post-hoc in the finance layer** (§13.4) — financially equivalent under uniform escalation, and it keeps the trained policy on-distribution.

**P1 — Hourly-resolved revenue integration.** Every revenue/cost stream is accounted at the **hourly** level and integrated up; it is **never** approximated as annual-average-price × annual-quantity.

```
revenue_s(year) = Σ_{t=1}^{8760} q_{s,t} · p_{s,t}        # per stream s, hour t; q = dispatch quantity, p = price
```

*Necessity:* the policy's entire value is **temporal** — charge in the ¥250/MWh valley, discharge into the ¥780/MWh critical peak (§3.7). The annual *average* price is unchanged by shifting energy; only the hour-by-hour product `q_t·p_t` captures the spread the policy harvests. Annual-average accounting mathematically erases exactly the value the policy creates, so it is prohibited. The merged env already integrates hourly (`EnvInfo.c_energy_yuan = price_t·quantity_t·Δt`); finance **consumes** those hourly-accumulated per-stream sums, never reconstructs revenue from annual averages.

**P2 — The dispatched year is the atomic finance unit.** SOC couples hours, so project value **cannot be decomposed hour-by-hour independently**; the indivisible finance input is a **full dispatched year** (a `PolicyEvalResult`-grade object). This is *also* why per-policy comparison is meaningful: different policies produce different trajectories under **identical prices**, so the revenue difference is purely the policy's doing.

**P3 — Cash-flow basis = D13 real money, enforced by type AND by test (INV-BASIS).** Finance consumes **only** D13 real-money fields; the RL reward-basis fields (`penalty_yuan`, `soc_*`, `c_demand_shape`, `cost_total_reward_basis_yuan`, `reward`) are **structurally unreachable** from the cash-flow path — not merely unused. **Mandatory reviewer-grade test:** a fixture where real-money and reward-basis totals differ materially (SOC penalties + demand-shaping added) → the cash-flow output equals the real-money number exactly and **fails** if anyone ever wires a reward-basis field.

---

### 13.1 Framing — merchant exporter, and the dual economic view

Gansu = **615 MW wind + 330 MW solar + 294.5 MWh / 98.16 MW battery serving 50–100 MW load** behind 945 MW export / 400 MW import. Generation ≫ load (~10×) ⇒ a merchant exporter with embedded load. Two economic **views**, both reported per policy:

| View | CAPEX basis | Benefit stream | Answers |
|---|---|---|---|
| **(I) Absolute project** | full plant | annual operating net revenue under π (hourly-integrated, P1) | *Is the whole plant a good investment?* |
| **(II) Incremental storage** | incremental battery CAPEX (the sizing-tier delta) | Δ(operating result) of π **vs a reference config (typically an adjacent sizing tier)** | *Does the incremental storage tier pay (sizing); which policy maximizes its value?* |

View (II) is the **per-policy headline discriminator** — all §11 policies share CAPEX and scenario, differing only in battery dispatch + wear→replacement (P2). For an own-load scenario (aluminum, future), View (II)'s "benefit" is literally the **avoided cost** vs the grid-only counterfactual.

---

### 13.2 Cash-flow basis — the D13 → cash-flow mapping (mandatory artifact + named anti-double-count invariants)

D13 "real money" means **economically real (not reward-shaping)** — but **not all real-money items are period cash**. The engine maps each D13 component (a `PolicyEvalResult` field) as follows; each row carries a named invariant and a hand-computed no-double-count test (asserted in the finance contract's test cases):

| D13 component (field) | Period cash? | Cash treatment | Invariant + hand-computed test |
|---|---|---|---|
| `energy_cost_yuan` = c_import − r_export | **Yes** — operating cash | split into **`grid_export` revenue** and **`grid_import` cost** streams, each hourly-integrated (P1) | direct — test: Σ hourly q·p = field |
| `demand_charge_yuan` | **Yes** — operating cash | direct OPEX line (¥/MW·month, D10/D21) | direct |
| `degradation_yuan` (c_degradation, ¥10/MWh) | **No** — not period cash | dispatch-layer **wear signal**; cash treatment = **battery replacement CAPEX** scheduled by first-to-fire(calendar, throughput) (§13.6), booked in the year incurred; optional reserve accrual | **INV-DEG:** never both the hourly proxy AND replacement CAPEX in the same cash flow. *Test:* a year of throughput → cash impact appears once (replacement CAPEX at the EOL year), `degradation_yuan` memo-only. |
| `curtailment_yuan` (c_curtail, ¥800/MWh) | **Conditional** | cash **only if** `scenario.curtailment_penalty_contract` ON; else excluded (the opportunity cost is already in reduced `grid_export` revenue) | **INV-CURT:** flag OFF → cash loss of a curtailed MWh = foregone export revenue ONLY, not revenue+penalty. *Test:* curtailment hour → cash loss == foregone `grid_export` revenue when flag off. |
| `voll_yuan` (c_voll, ¥20 000/MWh) | **Conditional** | cash **only** as a contractual reliability penalty (`scenario.reliability_penalty_contract` ON); in own-load scenarios the damage is **lost PRODUCT revenue** (captured in that stream), not VOLL | **INV-VOLL:** VOLL cash **XOR** lost-product revenue — never both. *Test:* unserved-load hour (aluminum) → cash hit = lost product revenue once, not loss + VOLL. |
| `penalty_yuan`, `soc_*` | **Never cash** | reward-shaping / safety reporting | **INV-BASIS** (§13.0 P3): structurally unreachable; the reviewer-grade test proves it. |

The per-scenario contract flags (`curtailment_penalty_contract`, `reliability_penalty_contract`) live in the scenario config. **Canonical answer** to "does cash flow include degradation / curtailment costs": **degradation → only as replacement CAPEX; curtailment / VOLL → only under an explicit contract flag; otherwise the economic effect is already in the revenue streams.**

---

### 13.3 Revenue / cost streams as DATA — scenario = configuration (v1 = power-composite)

End-product prices are **scenario-specific and time-dependent**; physical quantities are **hourly time series**. Streams are therefore **data**, keyed to the device that produces them; the *same* NPV/IRR/LCOE engine prices any scenario by configuration alone:

```
stream = { type:           grid_export | grid_import | demand_charge | h2_sale | avoided_cost | token_sale | … ,
           unit:           ¥/MWh | ¥/kg | ¥/t | ¥/token | ¥/MW·month ,
           source_device_id: <device-model id>,                  # the device whose dispatch produces q_{s,t}
           quantity_source:  P_export | H2_kg | load_served | … , # which dispatch quantity feeds q_{s,t}
           price_model:     { kind: flat | tou | indexed | spot, params | series },
           price_path:      <price-path id or custom multiplier vector>,   # §13.4, finance-layer only
           escalation_pct_per_year: <num> }
scenario = { id, streams:[…], price assumptions, weather_mode, discount/escalation }
```

| Scenario (config) | Active stream(s) | Unit | Source device | v1 |
|---|---|---|---|---|
| **power-composite** (= Gansu) | `grid_export` (+ `grid_import`, `demand_charge` cost streams) | ¥/MWh, ¥/MW·month | grid / PCC | **WIRED** |
| **hydrogen** | `h2_sale` | ¥/kg | electrolyzer (§8.2) | design-proven, not built |
| **aluminum** | `avoided_cost` | ¥/t (via avoided ¥/MWh) | industrial-continuous load (§8.3) | design-proven, not built |
| **data-center (AI tokens)** | `token_sale` | ¥/token | `load_data_center` (registry, PR #38) | design-proven, not built |

**v1 revenue = COMPOSITE (USER directive, §13.13-8).** v1 prices the **composite of the active power-supply streams** — `grid_export` revenue net of `grid_import` and `demand_charge` costs — integrated hourly (P1) and summed into View I / View II. The non-power streams (`h2_sale`, `avoided_cost`, `token_sale`) are **defined and demonstrated config-only**: the stream field exists and is exercised by the power streams; the others slot in by adding a stream entry, **not** by new code. The `token_sale` stream is power-driven (tokens/h ∝ served power) and prices identically — `q_{s,t}·p_{s,t}` per hour. The data-center **flexible-load action extension** is a future *action-space* change (not finance), explicitly not v1.

---

### 13.4 Price-path scenario library (finance-layer only — the F1 dividend)

Because dispatch runs at **constant-real year-1 prices** (D31/F1), the entire price-trajectory question lives in the finance layer as a **per-year multiplier vector** `m(y), y=1…N` applied post-hoc to the hourly-integrated stream revenues. Changing the price path **re-multiplies the cached per-draw cash-flow series** — **no re-dispatch, no server round-trip** (instant, client-side; the realized §13.13-9 interactive UX).

```
revenue_s(year y, path) = m_s(y) · Σ_{t} q_{s,t}·p_{s,t}        # m normalised to m(1) = 1.0 (= year-1 tariff)
```

**INV-FINLAYER (named invariant — parallel to INV-BASIS).** Price paths, escalation, and contract structures (flat / indexed / spot) are a **post-hoc transform applied in the finance layer** over the dispatched-year streams, which are produced at **constant-real year-1 prices** (D31/F1). They are **structurally barred from re-entering env dispatch** — no price-path, escalation rate, or contract term may flow into the jitted `step` or alter the trained policy's observation distribution. A *uniform* path leaves relative TOU structure (hence optimal dispatch) unchanged ⇒ it is a **pure, financially-exact** finance transform. A **non-uniform / stream-specific** path genuinely changes dispatch incentives; applied post-hoc it is only an *approximation*, so it **must raise an explicit retrain flag — never a silent finance knob**. *Guard test (mandatory):* a non-uniform per-stream path → the engine sets `requires_retrain=true` in provenance and the result is badged, and a test asserts that no price-path/escalation field is reachable from the dispatch path (the env trace is independent of `price_path`). v1 default = the shared uniform path.

**Two distinct distributional axes — do NOT conflate (INV-FINLAYER corollary).** The model has two orthogonal axes, and the spec keeps them separate:
- **Weather draws `M` = the stochastic Monte-Carlo axis** — the M ensemble members are random weather realizations (§12 block-bootstrap); they produce the **P50/P75/P90/P95 exceedance distribution** and the downside-risk panel (§13.10).
- **Price paths = DETERMINISTIC finance scenarios = a sensitivity axis** (§13.11), **not** Monte-Carlo draws.

Each price path yields **its own** distribution-over-M (and its own surface); the two are **never** collapsed into a single cross-product "distribution" — doing so makes P90 meaningless. The §13.10 / §13.12 schema makes the dimensionality explicit: the exceedance distribution is over **M weather draws at a fixed price path**; sweeping price paths produces a family of such distributions.

**Preset library** (each a named multiplier vector; defaults overridable, confirm at gate):

| Preset | Shape | Default parameterization |
|---|---|---|
| **constant-real** | flat `m(y) = 1.0` | real terms held; nominal escalation handled separately if currency-nominal |
| **escalation** | rising | `m(y) = (1+g)^(y−1)`, default `g` = revenue-escalation (§13.6) |
| **declining-real** | falling | `m(y) = (1−d)^(y−1)`, default `d` ≈ 1–2%/yr (merchant-tariff erosion) |
| **step-change** | level then step | `m(y)=1` to year `y₀`, then `m(y)=s` (e.g. PPA→merchant rollover, default step at ~yr 8) |
| **stress** | sharp early fall | front-loaded decline (e.g. −X% over years 1–3) — the lender stress scenario |
| **custom** | user-edited | a full editable `(N,)` multiplier vector, drag or table entry, named `"custom — from <source-preset>"` |

**Per-stream paths (advanced).** A stream may carry its own `price_path`; default = one shared path across all streams. Per-stream paths are for differently structured revenue contracts, and trip the INV-FINLAYER retrain flag above (non-uniform → approximate post-hoc, badged). v1 default = the shared uniform path.

**Client/server parity (binding for the stage-⑤ frontend).** Price-path re-multiplication recomputes the full distributional set client-side (NPV/IRR/MIRR/CVaR × M draws). The client-side financial library must match the server engine within **≤ 0.01 pp** (IRR / MIRR) and **≤ ¥1k** (NPV) per draw, proven against a shared test vector (≥ M=5 draws × N=20-yr series at ≥ 2 distinct multiplier vectors). The finance contract specifies the test-vector format and field names.

---

### 13.5 Discount rate — CAPM with a time-selected, term-matched treasury r_f (USER directive)

The discount rate is **derived via CAPM → WACC**, anchored on a **time-selected, term-matched China Government Bond (CGB) yield** — not a hand-set constant. This supersedes the master-plan "default WACC" framing. All rates nominal, annualized, decimal.

```
r_f        = treasury_yield(valuation_date, term = horizon_years)        # the directive's core (§13.5a)
β_levered  = β_unlevered · (1 + (1 − tax_rate)·(D/E))                    # Hamada relever; = β_unlevered if all-equity
r_e        = r_f + β_levered · ERP + CRP                                  # CAPM cost of equity
r_d        = reference_rate(valuation_date) + credit_spread               # cost of debt, LPR-anchored, also time-selected
WACC       = (E/V)·r_e + (D/V)·r_d·(1 − tax_rate)

discount_rate (BASE = all-equity, pre-tax) = r_e        # base case ⇒ WACC collapses to r_e (D31/§13.9)
discount_rate (levered toggle)             = WACC
```

**13.5a — r_f selected by time (two explicit dimensions).** (1) **Valuation-date dependence:** the analysis takes a `valuation_date` and uses the CGB yield *as of that date*; `valuation_date` + the exact yield used travel in `/api/finance/compare` provenance (a stale/mismatched rate is machine-visible). (2) **Term-matching:** the risk-free tenor is matched to the project horizon — `r_f = interp( CGB_curve(snapshot ≤ valuation_date), horizon_years )`; default convention **linear interpolation** to the exact `horizon_years` (20 yr interpolates 10yr↔30yr), `nearest`-tenor a config alternative. Currency/region-keyed: CNY → CGB; future regions → the corresponding sovereign curve (task #58 currency layering).

**13.5b — named, overridable defaults — USER-CONFIRMED (2026-06-13; provenance `USER-confirmed/2026-06-13`).** The CAPM methodology AND these default values are USER-confirmed (the USER accepted the §13 CAPM methodology-brief recommendations in full). All remain UI-editable with provenance badges; none is "pending."

| Field | Default (USER-confirmed) | Basis |
|---|---|---|
| `beta_unlevered` | **0.60** | utility-scale renewable IPP asset beta, **upper end for a merchant wind+solar+storage exporter** (Damodaran green-energy ~0.5–0.6 + merchant-storage tilt) |
| beta levering | Hamada `β_L = β_U·(1+(1−tax)·D/E)` | `= β_U` in the all-equity base |
| `equity_risk_premium` (ERP) | **0.060** (total China ERP) | **total-China-ERP convention** (mature ~4.5–5% + China premium ~1–1.5%, Damodaran), paired with **CRP = 0** to avoid double-count with the CGB r_f |
| `country_risk_premium` (CRP) | **0.0** | CNY/CGB base ⇒ sovereign risk already in r_f; non-zero only for a cross-border/USD valuation |
| `cost_of_debt` | **5yr LPR + 125 bps** *(levered only)* | LPR-anchored (PBoC), time-selected like r_f; spread = project credit margin |
| `target_de_ratio` (D/E) | **0.0** base · **1.5** (60/40) levered toggle | base = all-equity unlevered; renewable PF gearing ~60% for the levered case |
| `tax_rate` | **0.25** (15% renewable-preferential where qualifying) | levered/post-tax toggle only; **VAT explicitly out of v1** (§13.14) |

**Base case = unlevered / pre-tax** (discount = `r_e`); **levered (WACC + equity-IRR + DSCR) is a default-OFF toggle reported as a delta** (§13.9). **Treasury tenor: linear-interpolate the CGB curve to the exact horizon** (20yr → interp 10↔30; 10yr → 10yr point; §13.5a). **v1 data source: static user-editable CGB + LPR curve config; live-fetch deferred to v2** (§13.6).

**13.5c — sensitivity sweeps anchor on the CAPM base** (§13.10): the NPV-vs-rate curve's base point is `r_e` (or WACC); the swept band is `r_f ± Δ` (e.g. ±100 bps on the term-matched CGB) and `ERP ± Δ` (e.g. ±150 bps) — anchored and parameter-meaningful, not an arbitrary `[3%,12%]` band.

---

### 13.6 CAPEX, OPEX, lifecycle replacements, asset-management, terminal value

**CAPEX** per device-model instance, summed over the site, keyed by the **same device-model ID** as the physics facet (`device_models.yaml` econ block, task #57). **Fleet sizing is configurable** (D32(h)): `CAPEX = unit_count × unit_price`.

**Econ defaults — SHIP the #63 China benchmark library (USER decision §13.13-10).** The default CAPEX / OPEX / lifecycle *values* on each device-model ID are **sourced from finance-engineer's #63 device benchmark library** (the 2024/25 China market benchmarks — wind ¥/kW, PV ¥/kW + inverter, LFP battery ¥/kWh + ¥/kW, grid lump-sum, O&M, replacement/residual fractions, lifetimes). Each shipped value carries its #63 provenance/citation; all remain overridable. **§13's econ layer depends on #63** (named in the §13.7 dependencies note); the **fields** are fixed here, the **numbers** come from #63 verbatim. (Distinct from the CAPM discount-rate values, which are USER-confirmed §13.5b.)

```
generators:  CAPEX_i = capacity_mw_i · 1000 · capex_per_kw_yuan_i
battery:     CAPEX_i = energy_mwh_i · 1000 · capex_energy_per_kwh_yuan_i + power_mw_i · 1000 · capex_power_per_kw_yuan_i
grid/fixed:  CAPEX_i = capex_lump_sum_yuan_i
Total_overnight_CAPEX = (Σ_i CAPEX_i) · (1 + soft_cost_fraction)
```

Construction: default overnight at t=0; optional phasing over `T_c = max_i(construction_months)` (IDC capitalized only under the debt toggle). COD = year 0; ops y = 1…N.

**Lifecycle events — first-to-fire(calendar, usage) (USER directive).** Every device carries a schedule of **replacement / subsystem-replacement / overhaul** events. A device is replaced at the **first trigger to fire**:

```
t_replace = min( lifetime_years ,  first year cumulative_throughput ≥ cycle_life_full_equiv · usable_energy )
```

- **Battery (v1):** `lifetime_years = 10` (the USER's calendar prior) **AND** `cycle_life_full_equiv` (the throughput design) → **first-to-fire** (reconciles both; neither dropped). A hard-cycling policy hits cycle-life before yr 10 → earlier replacement (preserves INV-DEG's policy discrimination); a gentle policy → the year-10 calendar bound. Replacement books `replacement_cost_fraction · CAPEX_i` (fraction < 1 reflects cost decline) and resets degraded physics (C resets params, D books cash) — so a 20-yr horizon runs battery unit-1 yrs 1–10, unit-2 yrs 10–20, each with its own residual.
- **PV inverter:** `subsystem_replacement` ~yr 10–12 (inverter ≈ 10–15% of PV CAPEX), partial param restore. **Wind:** periodic major-component `overhaul` (OPEX or partial CAPEX). **Grid/PCC:** long life + small maintenance reserve.
- **Non-power devices** (electrolyzer stack, smelter reline, data-center IT refresh ~4–5 yr) are **schema-present, design-proven, not built** in v1 — the **cost-side scope guard mirrors the §13.3 revenue-side guard**.

**Standard asset-management cost lines** (project/site-level finance config, not per-device) — each a named, overridable field; **none silently dropped** (USER directive), small-but-included ones flagged: **insurance** (~0.25–0.5%/yr of CAPEX, material), **grid-connection/transmission fee** (¥/MWh exported, material on volume), **land lease** (¥/yr, small — low default, included), **asset-management/admin** (~0.5–1% of revenue, small — included), plus device-level fixed O&M (¥/MW·yr) and variable O&M (¥/MWh, ≠ D13 `c_degradation`).

**Terminal (year N):** `Σ_i residual_value_fraction_i · CAPEX_i − Σ_i decommissioning_cost_yuan_i`; optional Gordon continuing-value. All lifecycle / asset-management costs are entered in **real year-1 ¥**; escalation is applied in the finance layer post-hoc (D31/F1), never in dispatch.

---

### 13.7 The finance input object — extended `PolicyEvalResult` (a D prerequisite)

Today's `PolicyEvalResult` is annual aggregates of 5 cost buckets with **no per-stream split** (`c_energy` merges export+import) and **no physical quantities** — **insufficient** for finance (LCOE/LCOS/OPEX/replacement need per-stream revenue/cost + quantities). The env already integrates hourly (P1), so the fix is hourly-accumulated **per-stream annual sums + physical quantities** (task #55 / eval_result_extended; the env/training path owns it):

**Temporal axis — the finance unit is a draw = a full N-year DEGRADED trajectory (resolves backend-reviewer F-B).** One `ExtendedPolicyEvalResult` is **one dispatched project-year**. A finance *draw* (one weather realization) is the **sequence of N of them — workstream C's full N-year run with per-year degraded physics** (battery/PV capacity fade, replacement resets, escalation applied post-hoc per F1). So **inter-year revenue degradation IS captured** (each year's streams reflect that year's degraded capacity), not approximated — this is option (i), C's M×N degraded dispatch, **not** a single year-1 result reused. The per-policy ensemble fed to `finance()` is therefore `M draws × N years` (§13.12). Dispatch still runs at **constant-real year-1 prices** (F1); only *prices* are held real and escalated in the finance layer — *physics* degrades year-over-year via C.

```
extended PolicyEvalResult (per dispatched year, per policy, per scenario):
  streams:    { grid_export_yuan, grid_import_yuan, demand_charge_yuan, [h2_sale_yuan, …] }    # P1 sums
  quantities: { export_mwh, import_mwh, generation_mwh, curtailed_mwh, unserved_mwh,
                bat_throughput_mwh, bat_discharge_mwh, [h2_kg, …] }                              # OPEX/LCOE/LCOS/replacement
  real_money: { energy_cost_yuan, demand_charge_yuan, degradation_yuan, curtailment_yuan, voll_yuan, total_cost_yuan }
  memo_only:  { penalty_yuan, soc_violation_mwh, soc_violations_count }                          # INV-BASIS: never cash
```

v1 needs only `grid_export` / `grid_import` + the quantities (power-composite); §8 streams add fields later. Intended for the **off-wire** finance path → should **not** require a telemetry bump (confirm at contract time). **D32(b) single-config invariant:** these eval-accumulator streams must be the *same* per-step stream economics the reward and the finance engine consume — one source, no dialect divergence.

**v1 dependencies / sequencing (consolidated).** Finance v1 has **three hard prerequisites**: (1) the **extended `PolicyEvalResult`** above (per-stream + physical-quantity hourly accumulators; task #55) — finance cannot run on today's 5-bucket aggregate; (2) the **§12 weather pipeline / block-bootstrap generator** — choosing **M = 50** (§13.10) promotes §12 from a design-study to a **finance critical-path dependency**, because every percentile (P90/P95 especially) is only as valid as the §12 ensemble's statistical fidelity (**depends on §12's validation battery, PR #77 §4.2**, passing — part of D's acceptance/evidence chain); and (3) the **#63 China device benchmark library** — supplies the shipped CAPEX/OPEX/lifecycle econ defaults (§13.6, USER decision §13.13-10). Build order: extended-eval (#55) + §12 ensemble + #63 econ defaults → finance engine → `/api/finance/compare` → stage-⑤ UI.

---

### 13.8 Metrics — exact formulas (¥; on annual CF(y), y = 0…N)

`CF(0) = −Total_overnight_CAPEX`; `CF(y) = EBITDA(y) − Replacement(y) − Tax(y)`; `CF(N)` adds Terminal. `EBITDA(y) = Σ_streams Σ_t (rev − cost) − FixedOM − VarOM − asset-mgmt lines` (P1, after the §13.4 price path).

```
NPV(r) = Σ_{y=0}^{N} CF(y)/(1+r)^y
IRR    : Σ CF(y)/(1+IRR)^y = 0                 # numeric; report MIRR alongside (replacement years → multi-IRR risk)
MIRR   = [ FV_pos(reinvest=r) / −PV_neg(finance=r) ]^(1/N) − 1
LCOE   = PV(CAPEX + FixedOM + VarOM + Replacement − Residual) / PV(E_net MWh)              # ¥/MWh
LCOS   = PV(battery CAPEX + O&M + replacement − residual + charging cost) / PV(MWh discharged)   # ¥/MWh; policy-sensitive; View II
Payback: simple & discounted, fractional by interpolation
DSCR(y)= CFADS(y)/DebtService(y),  CFADS ≈ EBITDA − Tax      # levered toggle only
```

`E_net` and discharged-MWh come from the §13.7 quantity accumulators (P1/P2), never annual averages. **MIRR is reported alongside IRR** (D31) because replacement-year sign flips create multiple-IRR risk.

---

### 13.9 Tax & debt — layered, default-off (clean base case)

Base = **pre-tax, all-equity (unlevered project IRR)** (D31) ⇒ the base discount rate is `r_e` (§13.5). **Tax toggle:** `tax_rate` (China 25%; 15% renewable-preferential alt), straight-line depreciation, simple loss offset; out-of-scope v1: VAT, deferred tax, incentive timing. **Debt toggle:** simple amortizing loan at `gearing` / `interest_rate` → equity IRR + DSCR; out-of-scope v1: sculpting / DSRA / refinancing / tranches. Both reported as **deltas** to the base case.

---

### 13.10 Distributions, downside risk, and confidence (the centerpiece)

The finance interface takes, **per policy, an ENSEMBLE of M weather draws — each draw a full N-year degraded trajectory** (§13.7/F-B; from §12 block-bootstrap × workstream-C) — and outputs **DISTRIBUTIONS** of every metric. **Default M = 50 (USER-confirmed, D34).** **§12 block-bootstrap is a v1 PREREQUISITE** at M = 50, and the §12 generator's validation battery (PR #77 §4.2) is part of D's acceptance/evidence chain — the percentile numbers (especially the P90/P95 tail) are only as valid as the ensemble's statistical fidelity (marginals, cross-correlation, ramp/persistence tails).

**Common Random Numbers (CRN) — binding.** All policies in a single comparison consume the **same M weather draws** (shared seed / identical ensemble), so per-policy metric deltas are **pure dispatch** (P2), not weather noise. The shared seed travels in provenance.

```
input   : ensemble.runs[policy_id] = { draw_m : m = 1…M },       # per policy: M draws; index m = SAME draw ∀ policies (CRN, seed on ensemble)
          draw_m = [ ExtendedPolicyEvalResult(year n) : n = 1…N ]   # each draw = C's full N-year degraded trajectory (§13.7, F-B)
per draw: cash_flow_m (N-year, after §13.4 price path) → { NPV_m(r), IRR_m, MIRR_m, LCOE_m, LCOS_m, payback_m }
output  : { M, distribution_valid,                              # distribution_valid=false ⇒ point estimates only (§13.10c)
            per-metric exceedance distribution {P50,P75,P90,P95} + downside-risk panel + bootstrap CI }
```

The result is the cross-product **{K deterministic price paths} × {one distribution over the M weather draws}** — the M axis is the *only* stochastic/distributional axis; price paths are a separate deterministic sensitivity axis (§13.4, INV-FINLAYER) and are **never** multiplied into the weather distribution. M = 50 grows the weather axis only.

**13.10a — Exceedance percentiles + bootstrap CI + per-percentile confidence (USER-decided percentile set).** The headline exceedance set is **P50 / P75 / P90 / P95** (USER decision §13.13-3); **P95 is the decision tail** at M = 50 (≈ the 2.5th-worst of 50 draws — defensible). **P99 is dropped from the headline** (≈ the 0.5th-worst of 50 → not credible); it may be retained **only** as an optional `indicative_low_confidence` field with its bootstrap CI if cheap, never as a bare headline. A credible P99 would gate on M ≥ 100. **Each percentile carries its own `bootstrap_ci` and a `confidence` tag** (`sound | indicative_low_confidence`, derived from the bootstrap CI width relative to the convergence threshold) — so the schema makes statistical confidence explicit per number and the UI **never renders a low-confidence percentile as a bare headline** (the "report honestly" rule). Bootstrap: resample the M draws with replacement, default 90% CI = P5–P95 of the bootstrap distribution. Exceedance form = "in X% of weather scenarios the project achieves *at least* this." For IRR / NPV / MIRR higher percentile-value = better; for LCOE / payback lower = better.
- **P50 / P75 / P90 / P95 are the sound, USER-decided headline set at M = 50** — P90/P95 are the bankability/stress tail.
- A **convergence hint** fires when a metric's CI width exceeds a threshold (default ≥ 2 pp for IRR, ≥ 20% of |P50-NPV| for NPV — locked here, not hardcoded in the frontend): *"wide range — add more weather scenarios."*

**13.10b — Downside-risk panel (the centerpiece — what the USER shows investors/lenders).** The downside is the headline, the upside is context. Six metrics:

| Metric | Definition |
|---|---|
| **Worst-case NPV (max loss)** | NPV of the worst single ensemble draw (min over M) |
| **Max cumulative drawdown + year** | maximum running shortfall below zero in cumulative cash flow (excluding the certain year-0 CAPEX); reports the year the hole is deepest |
| **P(NPV < 0)** | fraction of M draws with NPV < 0 |
| **P(IRR < hurdle)** | fraction of M draws with IRR below the hurdle (default hurdle = WACC / `r_e`; an explicit hurdle field overrides) |
| **CVaR-5%** | expected NPV over the worst 5% of draws (mean of the bottom 5th-percentile tail) — the conditional tail loss |
| **Worst single-year cash flow** | min annual net CF over years 1…N and all M draws (year-0 CAPEX excluded — CAPEX is certain) |

**13.10c — M = 1 honesty (binding; carried in the schema by `distribution_valid`).** M = 1 is a **valid fast-iteration mode** but the probabilistic / distributional metrics are then **undefined and must be SUPPRESSED, never shown as proxies**: P(NPV<0)/P(IRR<hurdle) would collapse to binary 0%/100% (reads as "no chance of loss" — affirmatively misleading); CVaR-5%, "worst-case NPV", and the percentiles collapse to the single draw. The `FinanceResult` carries `M` and **`distribution_valid`** (= false whenever M = 1); when `distribution_valid` is false the engine emits **point estimates only** and the percentile / downside-distribution fields are **explicitly absent (a represented "no distribution available"), never fabricated** as P50 = P90 = the single draw. The schema is **identical** to the M = 50 case — an honest collapse, not a silent relabel. At M = 1 the UI shows only the **single-trajectory well-defined** metrics — single-scenario NPV (labelled `"NPV (single scenario)"`, not "worst-case"/"P50"), max cumulative drawdown + year, worst single-year CF — under a prominent non-dismissable banner reproduced on export: *"M = 1 — single scenario; risk distribution requires an ensemble (M ≥ 50)."* **Relative policy ranking is robust at M = 1** under CRN (shared draw), so M = 1 is legitimate for quick comparison; bankability-grade risk needs M ≥ 50.

> **M = 50 default is a USER-CONFIRMED override of D31's M = 1 guard (records as LINEAGE D34).** The USER's decision — real distributions / CI / downside-risk / price-paths in v1 — is an **explicit, confirmed override** of D31's "v1 ships M = 1" provision (supersedes D31's M=1 clauses only; the rest of D31 stands). §13 sets **M = 50 as the v1 default**, retaining **M = 1 as a valid fast-iteration mode** where distributional metrics are suppressed (the §13.10c honesty rule). The schema is identical across M (M = 1 is the M-collapsed case), so no architecture changes — only the *default* and the v1 guard change. **Recorded as LINEAGE D34** (co-authored rl-architect + finance-expert; lands with this spec PR on merge).

---

### 13.11 Sensitivity — a surface, not a line

1. **Discount-rate sweep (primary 1-D display):** NPV(r) over the §13.5c CAPM-anchored band, per policy at P50; IRR = x-intercept; overlaid with the DP-oracle ceiling. With M > 1 this becomes an **NPV-vs-rate fan** (median + P25–P75 + P10–P90 bands).
2. **Sensitivity surface:** NPV / IRR over **(discount-parameter × weather-exceedance percentile)** — the rate axis crossed with the §13.10 percentile axis.
3. **Tornado:** ±swings ranked by |ΔNPV| — CAPEX (±20%), price path / escalation (±), battery cycle-life → replacement (±), discount rate (±2pp), O&M (±20%), weather percentile (P50↔P90), replacement cost (±).
4. **Interest-rate sweep (levered):** equity IRR & min-DSCR vs `interest_rate`.

---

### 13.12 Per-policy comparison + delivery — pure engine + off-wire REST resource

**Pure cash-flow-engine function boundary (the contract surface backend-reviewer gates).** The finance engine is a **pure function** of explicit inputs — no I/O, no network, no hidden global state (the treasury curve is passed in via `finance_config`, §13.6):

```
finance( ensemble:       PolicyEnsemble,                      # the POLICY axis + the STOCHASTIC (M) axis, typed so CRN is structural
         price_paths:     list[PricePath],                    # deterministic finance scenarios, the sensitivity axis (§13.4)
         econ:            DeviceEconParams,                    # SHARED across policies — NOT per-policy (P2: same CAPEX/scenario, §13.1)
         finance_config:  FinanceConfig                        # discount (CAPM/curve), tax/debt toggles, horizon, escalation, flags,
                                                              #   + baseline_policy_id (the no-battery ref for View II)
       ) -> FinanceResult {
         M, distribution_valid,                                 # false at M=1 ⇒ point estimates only, distributional fields absent (§13.10c)
         requires_retrain,                                      # true if any non-uniform/stream-specific price_path applied (INV-FINLAYER, §13.4)
         per_policy: { policy_id -> { View I & II : { P50, P75, P90, P95 of {IRR, NPV(r), MIRR, LCOE, LCOS, payback},   # USER set
                                       [ P99 ]: optional, indicative_low_confidence only (dropped from headline, §13.10a),
                                       per_percentile: { value, bootstrap_ci, confidence: sound|indicative_low_confidence },
                                       downside_risk: {
                                         single_trajectory: { max_drawdown_yuan, max_drawdown_year, worst_year_cf_yuan,
                                                              point_npv_yuan },          # present at ALL M (incl. M=1)
                                         distributional:    { worst_case_npv_yuan, p_npv_neg, p_irr_below_hurdle, cvar5_yuan } },
                                                                                          # ABSENT when distribution_valid=false (M=1)
                                       [ equity_IRR, min_DSCR ]      # debt-toggle-gated — emitted ONLY when debt ON (§13.9)
                                     } per price_path } },
         cash_flow_series, npv_vs_r_curve, sensitivity_surface, provenance }   # provenance carries seed + M (CRN)

PolicyEnsemble = {
    seed: int,                       # the shared CRN seed — structural, travels into provenance
    M:    int,                       # ensemble size (default 50, D34)
    runs: dict[policy_id -> list[ length-M; each = an N-year ExtendedPolicyEvalResult trajectory (§13.7/F-B) ]]
}
```

**Binding invariants on the `finance()` boundary (the load-bearing part — settle dict-vs-typed-struct with backend-reviewer; the typed `PolicyEnsemble` is preferred so the CRN seed is structural, not implicit):**
1. **CRN (D34):** every policy's list in `runs` has length `M`, and **index `m` = the SAME weather draw** (generated from `ensemble.seed`) across **all** policies. That index-alignment is what makes per-policy deltas pure dispatch (P2); the shared `seed` lives on the ensemble (not `finance_config`) so CRN is structurally visible and travels into `provenance`.
2. **Shared econ/scenario (P2, §13.1):** `econ`, `price_paths`, and the M weather draws are **identical across policies**; only the dispatched results (the `ExtendedPolicyEvalResult` contents) differ. `econ` is a single shared arg — **not** per-policy (all §11 policies share CAPEX + scenario, differ only in dispatch).
3. **View II:** requires `finance_config.baseline_policy_id ∈ ensemble.runs.keys()` (the no-battery reference). If absent → only **View I** (absolute) is produced and View II is **omitted, never fabricated**.
4. **Three distinct dimensions; axis separation preserved (INV-FINLAYER):** **policy** (side-by-side comparison) × **M weather** (the ONE stochastic/distributional axis) × **price_paths** (deterministic sensitivity family). The distribution is still over **M only** (`{K price-paths} × {one distribution over M draws}`, never cross-producted); F-A adds the policy axis but does **not** touch the M-only-is-stochastic rule.

`per_policy` falls out of `runs`' keys; View II from `baseline_policy_id`; CRN from the shared `seed` + index-alignment; the exceedance distribution still over M. The REST resource below is a thin wrapper over this pure function. **`distribution_valid` is load-bearing** (§13.10c): at M = 1 only the `single_trajectory` downside metrics + point estimates are present; the `distributional` block and percentiles are **absent, not fabricated**. **DSCR/equity-IRR are debt-toggle-gated** (§13.9): absent (not zero/null) unless the debt toggle is ON.

**Delivery — off-wire REST resource.** Finance is an **off-wire batch artifact**: a new REST resource

```
GET /api/finance/compare?policies=…&scenario=…
→ { per policy π : { View I & II : { P50/P75/P90/P95 (headline, CI/confidence-annotated, §13.10a) [+ P99 indicative-only] of {NPV(r_base), IRR, MIRR, LCOE, LCOS, payback},
                                     downside_risk:{ worst_npv, max_drawdown+year, p_npv_neg, p_irr_below_hurdle, cvar5, worst_year_cf },
                                     bootstrap_ci, [equity IRR, min DSCR] },
                     cash_flow_series (per draw, pre-price-path baseline §13.4), npv_vs_r_fan, sensitivity_surface },
    provenance : { checkpoint_id, weather_mode, M, valuation_date, r_f(curve_date,tenor,yield), r_e/WACC,
                   discount_params, escalation/price_path, scenario_id, code_version } }
joined to operating runs by (policy_id, checkpoint_id, scenario_id)
```

Composes **on top of** the LOCKED D13 identity; does **not** touch the LOCKED `eval_compare` (Kind 3) wire (different shape/cadence → REST avoids a telemetry bump; any finance term on the wire would be an additive-minor bump + both-reviewer re-review, deliberately avoided). **Provenance travels with every result** so the UI **refuses to compare results computed under mismatched assumptions** (different discount rate / weather mode / price path) — a correctness guard. Headline = NPV at `r_base` + incremental-battery NPV vs no-battery (View II); **economic optimality gap** `(NPV_oracle − NPV_π)/|NPV_oracle|` with the DP-oracle as the economic ceiling (the ¥ analog of §11.4's gap). The serving resource needs **both reviewers** (backend shape + frontend consumption).

---

### 13.13 USER gate decisions — RESOLVED (one item in follow-up discussion)

The §13 sign-off items (REBUILD_SPEC change → human-gated). **The USER reviewed the package and decided** (2026-06-13); all items below are **RESOLVED** — including the CAPM methodology + default values (the follow-up CAPM methodology discussion concluded 2026-06-13 with all recommendations accepted).

1. **✅ RESOLVED — Ensemble default M (§13.10):** **M = 50 confirmed**, with M = 1 retained as an honest fast-iteration mode (distributional metrics suppressed). An explicit override of D31's "v1 M = 1" guard → **records as LINEAGE D34** (co-authored rl-architect + finance-expert; supersedes D31's M=1 clauses only; lands with this PR on merge).
2. **✅ RESOLVED — Downside-risk centerpiece (§13.10b):** the six metrics confirmed as the headline (worst-case NPV / max loss, max drawdown + year, P(NPV<0), P(IRR<hurdle), CVaR-5%, worst single-year CF), upside as context.
3. **✅ RESOLVED — Tail percentile (§13.10a):** **headline set = P50/P75/P90/P95** + bootstrap CI on each; **P95 is the decision tail** (≈ 2.5th-worst of 50, defensible). **P99 dropped from the headline** (≈ 0.5th-worst, not credible at M = 50); retained only as optional indicative/low-confidence with CI. Convergence-hint thresholds (IRR ≥ 2 pp, NPV ≥ 20% of |P50|).
4. **✅ RESOLVED — Price-path library + INV-FINLAYER (§13.4):** the 5 presets + editable custom curve as a **finance-layer-only** post-hoc transform (INV-FINLAYER — barred from dispatch; non-uniform → retrain flag); two-axis separation; constant-real default; shared-uniform path default with advanced per-stream paths.
5. **✅ RESOLVED — Discount rate = CAPM, methodology + values (§13.5):** CAPM with time-matched CGB r_f, unlevered/pre-tax base (levered toggle as a delta). **USER-confirmed values (2026-06-13):** **β_U = 0.60** (merchant-storage tilt); **ERP = 6.0% total-China with CRP = 0** (no double-count); **cost of debt 5yr-LPR + 125 bps** (levered only); **D/E 0 base · 1.5 levered**; **tax 25%** (15% renewable where qualifying); **VAT out of v1**; **treasury tenor linear-interp to exact horizon**; **static user-editable CGB+LPR curve config in v1** (live-fetch v2). All UI-editable with `USER-confirmed/2026-06-13` provenance.
6. **✅ RESOLVED — Horizon (§13.6):** **20-yr primary + 10-yr variant** confirmed.
7. **✅ RESOLVED — Lifecycle replacement (§13.6):** battery replacement at **first-of(10-yr calendar, cycle-life)**; PV-inverter subsystem replacement; cost-side scenario-completeness; asset-management lines named, none dropped.
8. **✅ RESOLVED — v1 revenue = COMPOSITE (§13.3):** v1 prices the composite of active power-supply streams (export net of import + demand charge); h2/avoided-cost/token design-proven config-only.
9. **✅ RESOLVED — Carried-over base rulings (D31, unchanged):** D13→cash-flow memo-vs-cash mapping + INV-BASIS/INV-DEG/INV-CURT/INV-VOLL (§13.2); pre-tax all-equity base, tax/debt default-off toggles (§13.9); dual View I/II, View II per-policy headline (§13.1); MIRR alongside IRR (§13.8); ¥-nominal basis with real-year-1 dispatch (D31/F1); extended `PolicyEvalResult` prerequisite (§13.7, task #55); off-wire `/api/finance/compare` (§13.12).
10. **✅ RESOLVED — Econ defaults (§13.6):** **SHIP the #63 China benchmark library** CAPEX/OPEX/lifecycle values as cited defaults (overridable). §13's econ layer depends on #63.

---

### 13.14 Limitations & assumptions (honest)

1. **Price-path approximation for non-uniform escalation (§13.4):** post-hoc multipliers are *exact* only for uniform paths (relative TOU unchanged → dispatch unchanged, D31/F1); stream-specific / strongly non-uniform paths that would change dispatch incentives are an *approximation* without retraining — recorded, not hidden.
2. **Extended `PolicyEvalResult` is a prerequisite** (§13.7) — finance cannot run on today's 5-bucket aggregate.
3. **Price model = TOU + spread (+ flat/indexed/spot contracts)** — no forward-market/PPA-structure or negative-price modeling beyond §3.
4. **Deterministic availability** — no forced-outage stochastics (`availability_factor` knob only); the only stochasticity priced is weather (the §12 ensemble).
5. **Simplified financing & tax** — single loan toggle; straight-line depreciation, single rate.
6. **Overnight + simple-phasing CAPEX** — overrun risk only via the tornado.
7. **Replacement = discrete EOL param-reset** — continuous augmentation modeled as a step.
8. **Static treasury curve in v1** (§13.5/§13.6) — reproducible; live fetch is v2.
9. **Real-option value ignored** (v2).
10. **Ensemble fidelity & tail resolution (§13.10).** v1 prices **M = 50** weather draws via §12 block-bootstrap (a v1 prerequisite); the headline tail is **P95** (decision percentile; P50/P75/P90/P95 sound), **P99 dropped from the headline** (≈ 0.5th-worst of 50 → not credible; indicative-only if shown), and every percentile is only as valid as the §12 ensemble's statistical fidelity (cited via PR #77 §4.2). Weather is the **only** stochastic axis priced; price paths are deterministic scenarios, not draws.
11. **VAT excluded from v1 (§13.5b/§13.9).** The tax layer models corporate income tax only (pre-tax base + 25%/15% toggle, straight-line depreciation); **VAT** (input VAT on CAPEX, output VAT on sales — a cash-timing item) and deferred-tax are **out of v1**.
