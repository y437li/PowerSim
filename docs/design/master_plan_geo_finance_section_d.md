<!--
  Workstream-D (Project Finance) section text, authored by finance-expert for task #53.
  Drop-in replacement for the §5 STUB in docs/design/master_plan_geo_finance.md (PR #78).
  rl-architect integrates this block in place of the current "## 5. Workstream D" stub.
  Heading numbering (## 5, ### 5.x) matches the master-plan container. DESIGN ONLY — no implementation.
  All currency ¥ (RMB), nominal basis, units explicit at every interface.
  Incorporates: USER directive (hourly-resolved revenue integration), USER directive (ensemble/Monte-Carlo
  from the §12 generator → P50/P90/P99), and the integrated decision that finance is an off-wire REST resource.
-->

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
