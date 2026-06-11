<!--
  Workstream-D (Project Finance) section text, authored by finance-expert for task #53.
  This is the drop-in replacement for the §5 STUB in docs/design/master_plan_geo_finance.md (PR #78).
  rl-architect integrates this block in place of the current "## 5. Workstream D" stub.
  Heading numbering (## 5, ### 5.x) matches the master-plan container. DESIGN ONLY — no implementation.
  All currency ¥ (RMB), units explicit at every interface.
-->

## 5. Workstream D — Project finance  ·  *owner: finance-expert (Sonnet impl: finance-engineer)*

**Deliverable:** a new spec section (proposed **§13 project-finance** — a REBUILD_SPEC change → human-gated) plus the model that feeds the §6/E policy-economics UI. This section fixes the *financial model, formulas, conventions, and the schema obligations on B and C*; pass/fail numbers and default cost figures are contract-stage decisions (flagged in §5.10).

### 5.0 Framing — what kind of project this is

The Gansu site is **615 MW wind + 330 MW solar + 294.5 MWh / 98.16 MW battery serving a 50–100 MW local load** behind a 945 MW export / 400 MW import PCC. Generation ≫ load by ~10×, so the plant is **overwhelmingly a merchant exporter with a small embedded load**. The §3 objective ("minimize Σ cost", where `c_energy = c_import − r_export`) is therefore *maximizing export revenue net of import* — the operating result is naturally a **net cash inflow**, and project finance can be built **directly from the D13 real-money telemetry**, not only as an avoided-cost calculation.

Two complementary economic **views** fall out of this, and both are needed because they answer different questions:

| View | CAPEX basis | Benefit stream | Answers |
|---|---|---|---|
| **(I) Absolute project** | full plant (wind+PV+battery+grid) | annual operating net revenue under policy π (from D13) | *Is the whole plant a good investment?* |
| **(II) Incremental storage** | battery CAPEX only | Δ(operating result) of policy-π-with-battery **vs the no-battery baseline** | *Does the battery pay for itself, and which policy maximizes its value?* |

View (II) is where the **per-policy comparison lives**: every §11 policy operates the *same physical plant* and differs only in **battery dispatch** (and resulting wear → replacement timing). Holding renewables/CAPEX fixed, the storage-incremental NPV isolates exactly the money each policy's dispatch is worth. View (I) is the headline "is this a real project"; View (II) is the headline "is the RL policy worth it." **Both are reported per policy.**

### 5.1 From dispatch telemetry to a cash flow — the accounting bridge

The LOCKED D13 identity gives, per step and accumulated per year, the real-money operating cost:

```
cost_total_real_yuan = c_energy + c_demand_charge + c_degradation + c_curtail + c_voll
c_energy = c_import − r_export        (¥; negative ⇒ net export revenue)
```

Project finance composes **on top of** this identity (it does **not** alter it). Each D13 component maps to a cash-flow treatment, and three of them require an explicit honesty ruling to avoid double-counting:

| D13 term | Cash treatment in the project model | Rationale |
|---|---|---|
| `c_energy` (= c_import − r_export) | **Cash** — net grid energy revenue/cost | actual money exchanged with the grid |
| `c_demand_charge` | **Cash** — demand charges paid (¥32 000/MW·month, D10/D21) | actual money |
| `c_degradation` (¥10/MWh throughput) | **MEMO only — excluded from cash flow** | this is a *dispatch-shaping operating proxy* for cell wear; the real cash consequence of wear is the **replacement CAPEX event** (§5.3). Counting both double-charges the same degradation. The throughput proxy stays a reported memo line so a policy that over-cycles is still visible. |
| `c_curtail` (¥800/MWh penalty) | **MEMO only — excluded from cash flow** | curtailment is *foregone export revenue*, already reflected as a lower `r_export` inside `c_energy`. The 800 ¥/MWh is a reward-shaping penalty rate, not a cash outflow. Adding it would double-count the lost MWh. |
| `c_voll` (¥20 000/MWh penalty) | **MEMO / optional cash** — default excluded, reportable as reliability shadow cost | VOLL is a shadow reliability price, not a contractual payment — unless the site carries PPA liquidated-damages clauses (a toggle). Default base case excludes it from cash flow and reports it as a risk memo. |

**Net operating cash flow (EBITDA-like), year y** — built from the cash terms plus O&M from B:

```
EBITDA(y) = −[ c_energy(y) + c_demand_charge(y) ]          # = r_export − c_import − demand charges
            − FixedOM(y) − VarOM(y)
            + OtherRevenue(y)                              # feed-in/PPA/ancillary, v1 default 0
```

where `FixedOM`, `VarOM` come from B's econ facet (§5.2) and `c_energy`, `c_demand_charge` come from C's multi-year roll of the D13 telemetry (§5.4). **This ruling (memo-vs-cash on c_degradation / c_curtail / c_voll) is the single most important accounting decision in the section and is flagged for reviewer confirmation (§5.10 Q1).**

### 5.2 CAPEX & the device-model econ facet — *what B must carry*

CAPEX is built **per device-model instance**, summed over the site composition, keyed by the **same device-model ID** the 3D registry and B's physics facet use (§1 keystone). Per device type:

```
generators (wind, solar, gas):  CAPEX_i = capacity_kw_i · capex_per_kw_yuan_i
storage (battery):              CAPEX_i = energy_kwh_i · capex_energy_per_kwh_yuan_i      (cells/racks)
                                        + power_kw_i  · capex_power_per_kw_yuan_i        (PCS/inverter)
grid / fixed infrastructure:    CAPEX_i = capex_lump_sum_yuan_i                          (substation, interconnection)

Hard_CAPEX     = Σ_i CAPEX_i
Total_overnight_CAPEX = Hard_CAPEX · (1 + soft_cost_fraction)                            # dev, owner's cost, contingency
```

**Econ facet B must carry per device-model (the schema obligation D places on B):**

| Field | Unit | Used for |
|---|---|---|
| `capex_per_kw_yuan` | ¥/kW | overnight CAPEX (wind, PV, gas) |
| `capex_energy_per_kwh_yuan` | ¥/kWh | storage energy CAPEX (battery) |
| `capex_power_per_kw_yuan` | ¥/kW | storage power/PCS CAPEX (battery) |
| `capex_lump_sum_yuan` | ¥ | fixed infrastructure (grid/PCC) |
| `opex_fixed_per_kw_year_yuan` | ¥/kW·yr | annual fixed O&M |
| `opex_var_per_mwh_yuan` | ¥/MWh | variable O&M on throughput/generation (distinct from D13 `c_degradation`) |
| `lifetime_years` | yr | calendar end-of-life → replacement timing & depreciation |
| `cycle_life_full_equiv` *(storage)* | cycles | usage end-of-life: replacement when cumulative equivalent full cycles ≥ this |
| `eol_soh_threshold` *(storage)* | fraction | alt. EOL trigger: replace when state-of-health < threshold (e.g. 0.70) |
| `replacement_cost_fraction` | fraction | replacement CAPEX as fraction of original (learning-curve decline; <1 typical) |
| `residual_value_fraction` | fraction | salvage at horizon end as fraction of (depreciated) CAPEX |
| `degradation_pct_per_year` | %/yr | annual capacity fade — **shared with B physics; D references, does not redefine** |
| `construction_months` | months | construction-period CAPEX phasing / IDC |
| `decommissioning_cost_yuan` | ¥ | terminal cost (can be ~0 or net-negative w/ salvage) |
| *(optional, tax layer)* `depreciation_years`, `depreciation_method` | yr / enum | tax depreciation schedule |

**Recommendation to B:** co-locate this econ facet with the physics facet in the same per-ID device-model schema (the plan-lead's sibling-`config/device_models.yaml` lean, §2) under an `econ:` block — one ID, three facets (visual/physics/econ). D specifies the *fields*; B owns the *file*. Default *values* are placeholders/benchmarks flagged as assumptions (§5.10 Q6).

### 5.3 Construction timing, replacement, terminal value

**Construction / commissioning.** CAPEX is spent before COD (commercial operation date), not all at t=0. v1 convention:
- Default: **overnight CAPEX at t=0** (single point), with an **optional construction-period phasing** toggle that spreads `Total_overnight_CAPEX` across `T_c = max_i(construction_months)` using a linear or S-curve drawdown.
- **IDC (interest during construction)** is capitalized into CAPEX **only if debt is modeled** (§5.5); default all-equity ⇒ no IDC. Stated assumption.
- COD = **year 0**; operating cash flows accrue years 1…N. (Year-indexing convention fixed in §5.4.)

**Replacement schedule (degradation-driven — the battery channel).** Within an N-year horizon a device whose calendar life (`lifetime_years`) or usage life (`cycle_life_full_equiv` / `eol_soh_threshold`) is reached triggers a **replacement event**: C resets that device's degraded params; D books a **replacement CAPEX** = `replacement_cost_fraction · original_CAPEX_i` in that year. For a Gansu LFP battery (~10–12 yr / cycle-limited) this is typically **one replacement in a 20-yr horizon** — and crucially **policy-dependent**: a policy that cycles harder reaches `cycle_life` sooner ⇒ earlier/額外 replacement ⇒ worse NPV. This is the channel through which dispatch aggression is correctly monetized (and why §5.1 keeps `c_degradation` as memo-only — the cash hit is *here*).

**Terminal / residual value (year N).**
```
Terminal_value = Σ_i residual_value_fraction_i · CAPEX_i  −  Σ_i decommissioning_cost_yuan_i
```
Default = salvage-net-of-decommissioning. Optional **continuing-value** (Gordon growth) for assets operating beyond N: `TV = EBITDA(N+1)/(r − g)`. Battery residual ≈ scrap; renewables retain land/repower option (stated as a v2 real-option, not valued in v1).

### 5.4 Multi-year mechanics & conventions — *what C must apply*

C produces, for each policy π and year y ∈ {1…N}, a degraded+escalated 8760-h dispatch roll yielding `c_energy(y)`, `c_demand_charge(y)`, throughput/generation MWh, and any replacement triggers. D requires C to apply these **conventions** (all must share one basis — see the nominal rule):

| Convention | Param (C) | Default | Note |
|---|---|---|---|
| Tariff escalation | `tariff_escalation_pct_per_year` | configurable (e.g. 2.0%/yr nominal) | applied to buy price, sell price/spread, **and** demand_rate |
| O&M inflation | `opex_inflation_pct_per_year` | configurable (e.g. 2.5%/yr nominal) | applied to FixedOM, VarOM |
| PV/wind capacity fade | `degradation_pct_per_year` (from B) | per device | E_gen(y) = E_gen(1)·Π(1−d) |
| Battery SOH / cycle fade | SOH curve / `cycle_life` (from B) | per device | drives replacement (§5.3), not a price |
| **Basis** | nominal vs real | **nominal** | *escalations and discount rate MUST be in the same basis* — the classic error. Real-terms toggle deflates by one CPI. |
| Discounting timing | end-year vs mid-year | **end-year** | mid-year = ×(1+r)^0.5 adjustment, optional toggle |
| Year indexing | COD spend / ops start | **CF(0) = −CAPEX, ops y=1…N** | fixed convention; replacement & residual land on their year |

**The within-year env is unchanged (§3); C wraps it** with per-year closure constants (degraded capacity, escalated prices) — consistent with §7 purity (year boundary is a host point, like the D21 calendar boundary). D consumes C's per-year aggregates only; no per-step coupling.

### 5.5 Metrics — exact formulas (¥, all discounting on annual CF(y), y = 0…N)

Let `CF(0) = −Total_overnight_CAPEX` (or the phased construction draws), `CF(y) = EBITDA(y) − Replacement(y) − Tax(y)` for y = 1…N−1, and `CF(N) = EBITDA(N) − Tax(N) + Terminal_value`.

**NPV** (¥), at nominal discount rate r (WACC):
```
NPV(r) = Σ_{y=0}^{N} CF(y) / (1+r)^y
```

**IRR** — the rate r* with NPV(r*) = 0:
```
Σ_{y=0}^{N} CF(y) / (1+IRR)^y = 0          # solved numerically (bisection on the sign-bracketed NPV curve)
```
*Caveat:* replacement years can flip CF sign more than once ⇒ multiple-IRR risk. Report **MIRR** as the robust companion.

**MIRR** (finance rate r_f, reinvestment rate r_r; default both = r):
```
MIRR = [ FV_pos / −PV_neg ]^(1/N) − 1
FV_pos = Σ_{CF(y)>0} CF(y)·(1+r_r)^(N−y) ;  PV_neg = Σ_{CF(y)<0} CF(y)/(1+r_f)^y
```

**LCOE** (¥/MWh) — levelized lifetime cost per unit net energy delivered:
```
LCOE = [ Σ_{y=0}^{N} (CAPEX(y) + FixedOM(y) + VarOM(y) + Replacement(y) − Residual(y)) / (1+r)^y ]
       ÷ [ Σ_{y=1}^{N} E_net(y) / (1+r)^y ]
```
`E_net(y)` = net energy delivered (MWh) = generation − curtailment − auxiliary (definition fixed at contract stage; export+load-served basis recommended).

**LCOS** (¥/MWh discharged) — the storage analog, **policy-sensitive** (both numerator charging cost and denominator MWh-discharged depend on dispatch):
```
LCOS = [ PV( battery CAPEX + battery O&M + replacement − residual + charging_energy_cost ) ]
       ÷ [ PV( MWh_discharged ) ]
```

**Payback** (yr) — simple and discounted; fractional year by linear interpolation:
```
Simple_payback     = min{ y : Σ_{k=0}^{y} CF(k) ≥ 0 }
Discounted_payback = min{ y : Σ_{k=0}^{y} CF(k)/(1+r)^k ≥ 0 }
```

**DSCR** (only if debt modeled, §5.6) — report **min** and **average** over the debt tenor:
```
DSCR(y) = CFADS(y) / DebtService(y)
CFADS(y) ≈ EBITDA(y) − Tax(y)                     # v1 ignores ΔWC
DebtService(y) = Principal(y) + Interest(y)
```

### 5.6 Tax, depreciation & debt — layered, default-off for a clean base case

To keep v1 honest and the base IRR/NPV clean, finance layers are **toggles**, default off:

- **Base case = pre-tax, all-equity (unlevered).** Project IRR on total CAPEX. Cleanest comparison across policies.
- **Tax layer (optional):** corporate income tax `tax_rate` (China standard **25%**; renewable preferential **15%** as a documented alternative). Straight-line depreciation over `depreciation_years` (B); `Tax(y) = max(0, tax_rate·(EBITDA(y) − Depreciation(y) − Interest(y)))` with simple cumulative loss offset. **Out of scope v1:** VAT (net-of-VAT prices assumed), deferred tax, incentive-timing, loss-carryforward limits — stated.
- **Debt layer (optional):** simple amortizing loan at `gearing` (e.g. 60% D / 40% E) and `interest_rate`; produces **equity IRR** (post-debt-service) and **DSCR**. **Out of scope v1:** debt sculpting, DSRA, refinancing, multi-tranche — stated. Debt interest doubles as an **interest-rate sensitivity** axis (the USER's explicit ask).

Both layers reported as **deltas to the base case**, never silently folded in.

### 5.7 Sensitivity analysis (the USER's explicit display requirement)

1. **Discount-rate sweep (primary requested display).** NPV(r) over r ∈ [r_min, r_max] (e.g. 3%–12%) per policy → an **NPV-vs-discount-rate curve**; the IRR is its x-intercept. Overlaid across policies with the DP-oracle as the ceiling.
2. **Interest-rate sweep (if debt on).** Equity IRR and min-DSCR vs debt `interest_rate`.
3. **Tornado diagram.** One-at-a-time ± swings ranked by |ΔNPV|, on the high-leverage drivers (the candidates named by team-lead/rl-architect, plus discount rate and weather):
   - CAPEX (±20%) · tariff/sell-price escalation (±2 pp) · battery cycle-life/degradation → replacement timing (±) · discount rate (±2 pp) · O&M (±20%) · capacity factor / **weather year** (±) · replacement cost (±).
   Each bar = NPV(low) vs NPV(high); width = sensitivity.
4. **2-D heatmap (optional).** NPV over (discount rate × CAPEX) or (discount rate × tariff escalation).
5. **Scenario bundles (optional).** Low / Base / High input sets.

### 5.8 Per-policy economic comparison semantics

Every §11 ladder policy (no-battery, rule-based TOU, greedy, MPC, DP-oracle, SA/ACO, RL) operates the **same physical plant over the same realized weather/price year** (§11's apples-to-apples basis) and differs only in **dispatch** (and wear→replacement). For each policy π:

```
C(π) → per-year operating trajectory → D's model → { NPV(r_base), IRR, MIRR, LCOE, LCOS,
                                                     payback, [equity IRR, min DSCR],
                                                     cash-flow curve, NPV-vs-r curve }
       reported BOTH as View (I) absolute and View (II) incremental-vs-no-battery (§5.0).
```

- **Headline discriminator:** because CAPEX is identical across policies, the cleanest comparison is **NPV at the base discount rate** and the **incremental storage NPV vs no-battery** (View II). 
- **Economic optimality gap** — the money analog of §11.4's optimality gap: `(NPV_oracle − NPV_π) / |NPV_oracle|`, with the **DP-oracle as the economic upper bound** ("money left on the table" in ¥). The §11 information-set ladder thus re-expresses directly in ¥-NPV terms — RL must beat MPC's NPV and approach the oracle's.

### 5.9 Telemetry / wire basis — *separate offline rollup (confirms rl-architect's lean)*

**Finance is a separate offline rollup; it does NOT touch the per-step `env_step` wire — no new per-step telemetry fields.** It consumes (a) the existing **LOCKED `eval_compare` per-policy real-money operating costs** (Kind 3), (b) C's multi-year per-year aggregates, and (c) B's econ facet, and emits a **new aggregate `finance_compare` artifact** (one record per run, policies × metrics × sensitivity curves).

Two delivery options for that artifact (decision → §5.10 Q1):
- **(b·preferred for v1)** a **separate serving/finance REST artifact** outside the LOCKED telemetry schema — keeps the LOCKED wire untouched; finance is offline/aggregate, not streamed per-step. 
- **(a·if E needs it streamed)** a **new telemetry Kind** (`finance_compare`) = additive **minor** version bump, requiring both-reviewer re-review per the schema's versioning rule.

**Confirmed: separate rollup on top of D13, not a per-step wire change.** This preserves every LOCKED contract.

### 5.10 Honest limitations (and the natural v2)

1. **Single-scenario weather (the headline limitation).** The entire cash flow rides on **one realized weather/price year** (per §11, shared across policies), degraded/escalated across N years. Real IRR has a *distribution* from interannual variability. **Natural v2 — explicitly flagged: a Monte-Carlo IRR/NPV distribution** over the §12 / PR #77 **unlimited block-bootstrap synthetic years**, reporting a P10/P50/P90 fan instead of a point estimate. PR #77's generator is the ready-made MC engine; v1 is deterministic point estimates, and the *relative* policy ranking (same exogenous year) is robust even though absolute IRRs are not.
2. **Price model = the env's TOU+spread**, not a forward/PPA/market curve — no merchant price-risk modeling, no negative-price or curtailment-market dynamics beyond the §3 penalty. Revenue risk understated.
3. **Deterministic availability** — no forced-outage/failure stochastics; availability ≈ 100% (a flat `availability_factor` knob is the only hook).
4. **Simplified financing** — debt is a single amortizing loan toggle; no sculpting/DSRA/refinancing/tranches.
5. **Simplified tax** — straight-line depreciation, single rate, no VAT/deferred tax/incentive timing.
6. **Overnight + simple-phasing CAPEX** — no detailed S-curve or cost-overrun distribution (captured only via the tornado CAPEX swing).
7. **Replacement = discrete EOL param-reset** — real continuous battery augmentation is modeled as a step.
8. **Real-option value ignored** — operational flexibility, repowering, capacity expansion unvalued (v2).

### 5.11 Decisions requested at the Fable gate (→ USER summary)

1. **Accounting rulings (§5.1, §5.9):** confirm `c_degradation`/`c_curtail`/`c_voll` are **memo-only** (cash impact of wear flows through replacement CAPEX), and finance is a **separate offline rollup** (preferred: a finance REST artifact, not a per-step wire change).
2. **Base case (§5.6):** pre-tax, all-equity unlevered as the base, with tax & debt as reported toggles — or does the USER want levered-after-tax as the headline?
3. **Discount rate (§5.5/5.7):** base WACC for a Gansu utility-scale renewable project (China utility-scale ≈ nominal 7–9% / real 5–7%) — confirm a default + the sweep range, or USER-specify.
4. **Horizon (§5.4):** 20-yr base + 10-yr variant (battery replacement ~yr 10–12) — confirm both.
5. **Dual view (§5.0):** confirm reporting **both** absolute project economics and incremental-battery economics, with incremental-vs-no-battery as the per-policy headline.
6. **Econ defaults (§5.2):** source Chinese 2024/25 benchmark CAPEX/OPEX (cited as assumptions) for the placeholder values, or leave fully configurable with no shipped defaults?
7. **Currency/basis:** all **¥ (RMB), nominal** — confirm.
