<!--
  Workstream-D (Project Finance) section text, authored by finance-expert for task #53.
  Drop-in replacement for the §5 STUB in docs/design/master_plan_geo_finance.md (PR #78).
  rl-architect integrates this block in place of the current "## 5. Workstream D" stub.
  Heading numbering (## 5, ### 5.x) matches the master-plan container. DESIGN ONLY — no implementation.
  All currency ¥ (RMB), nominal basis, units explicit at every interface.
  rev3 incorporates: hourly-resolved revenue integration (USER); ensemble/Monte-Carlo P50/P90/P99 (USER);
  off-wire REST resource (rl-architect/frontend); abstract revenue-stream schema + scenario=config + v1
  power-supply-only scope guard (USER/rl-architect, BINDING); D13→cash-flow mapping table + named
  anti-double-count invariants + real-money-basis invariant (USER, mandatory artifact). Grounded in the
  merged eval.py / baselines.py PolicyEvalResult + D13 semantics.
-->

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
