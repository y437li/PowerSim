# Finance engine — acceptance basis (hand-computed vectors, downside formulas, criteria)

**Owner:** finance-expert (finance acceptance gate for workstream-D) · **Status:** acceptance basis for the `finance()` engine (task #4)
**Governs:** finance-engineer's `finance()` contract + test cases. The numbers here are the **hand-computed expected values** that the reviewer-approved tests MUST encode (engineering rule: "finance tests assert hand-computed expected numbers with the arithmetic shown in a comment"). finance-expert is the acceptance gate when the implementation lands.

**Authoritative surface:** §13.12 `finance(ensemble, price_paths, econ, finance_config) -> FinanceResult` (merged #100, LOCKED). This document does **not** alter the surface; it supplies the semantics finance-engineer's contract is gated against. Econ defaults = the merged #103 China benchmark library (`config/device_models.yaml`, schema 2.1.0). USER-concluded §13 decisions are fixed inputs (M=50/D34, P95 tail, CAPM values §13.5b) — not re-opened here.

> **Workstream-D boundaries are locked by rl-architect's D39** (`docs/design/workstream_d_finance_architecture.md`, PR #108 — amended per the R3 ruling below; admin-merges on green CI). **Area = new `finance`** (`src/energy_go/finance/`, `tests/finance/`, `contracts/finance/finance_engine.md`); these vectors become that contract's test-case section, which finance-expert co-authors + gates. This doc supplies the semantics for D39 §6.2 (parity vectors → §C) + §6.4 (downside formulas → §A) + the discount module (Vector 0). **The canonical percentile-regime table (R1/R2/R3) lives in §A.0 and D39 §6.7 references it as canonical.** View I/II aggregation lives in the `engine.py` facade (D39 §2): **View II = NPV(π) − NPV(`baseline_policy_id`) over the CRN-shared draws** (index-aligned m ⇒ pure-dispatch delta, P2); `baseline_policy_id` absent ⇒ View II omitted, never fabricated.

---

## Conventions used by every vector

- All amounts ¥ (RMB), nominal; rates decimal; energy MWh. CF indexed `y = 0…N`; `CF(0) = −Total_overnight_CAPEX`.
- `CF(y) = EBITDA(y) − Replacement(y) − Tax(y)`; `CF(N)` adds Terminal (§13.8).
- `EBITDA(y) = Σ revenue − Σ cost(FixedOM, VarOM, asset-mgmt)` after the §13.4 price path. Base vectors use a **uniform constant-real path** `m(y)=1` ⇒ INV-FINLAYER `requires_retrain=false`.
- Discount rate `r` shown explicitly per vector (CAPM base `r_e`; §13.5). Vectors use small round inputs so NPV/IRR/MIRR/DSCR are hand-verifiable; the realistic Gansu numbers live in #103 and are exercised by an integration smoke, not these unit vectors.
- IRR roots are given as the **exact quadratic solution** (N=2 vectors) so the arithmetic is shown end-to-end, not a black-box solver output.

---

## Vector 0 — CAPM → r_e → WACC worked example (gates the discount module)

**Exercises:** the discount module (§13.5): term-matched CGB `r_f` (linear-interp to horizon), Hamada relever, CAPM cost of equity, WACC. Produces the base discount rate `r_e` (unlevered) and the levered `WACC` consumed by Vectors 1/3. CAPM values are the USER-confirmed §13.5b defaults; the CGB/LPR points below are **illustrative static-curve placeholders** (the real curve is the user-editable config, §13.6) — the test fixtures pin these exact placeholder points so the arithmetic is reproducible.

**Inputs (USER-confirmed §13.5b + illustrative static curve)**
```
beta_unlevered β_U = 0.60 ;  ERP = 0.060 (total-China) ;  CRP = 0.0
horizon = 20 yr ;  CGB curve points: 10yr = 0.0200, 30yr = 0.0260   (illustrative config)
tax_rate = 0.25
base case:    D/E = 0.0   (all-equity)
levered case: D/E = 1.5   ⇒ E/V = 0.4, D/V = 0.6
cost of debt: 5yr-LPR + 125 bps ;  5yr-LPR = 0.0350  ⇒  r_d = 0.0350 + 0.0125 = 0.0475
```

**Expected (hand-computed)**
```
r_f (linear-interp 10yr↔30yr to 20yr) = 0.0200 + (0.0260 − 0.0200)·(20−10)/(30−10)
    = 0.0200 + 0.0060·0.5 = 0.0230   (2.30%)                              # assert ±1e-6

BASE (unlevered, all-equity): β_L = β_U·(1+(1−tax)·D/E) = 0.60·(1+0.75·0) = 0.60
    r_e (base) = r_f + β_L·ERP + CRP = 0.0230 + 0.60·0.060 + 0 = 0.0230 + 0.0360
               = 0.0590   (5.90%)   ⇒ base discount rate                  # assert ±1e-6
    WACC(base) = r_e = 0.0590        (all-equity ⇒ WACC collapses to r_e, §13.5)

LEVERED toggle (D/E=1.5): β_L = 0.60·(1+0.75·1.5) = 0.60·(1+1.125) = 0.60·2.125 = 1.275
    r_e (lev) = 0.0230 + 1.275·0.060 = 0.0230 + 0.0765 = 0.0995   (9.95%)  # assert ±1e-6
    WACC(lev) = (E/V)·r_e + (D/V)·r_d·(1−tax)
              = 0.4·0.0995 + 0.6·0.0475·0.75
              = 0.03980 + 0.6·0.0356250 = 0.03980 + 0.0213750
              = 0.061175   (6.1175%)  ⇒ levered discount rate             # assert ±1e-6
```
**Asserts:** base discount = `r_e` (= WACC when D/E=0); levered discount = WACC; Hamada relever applied only in the levered case; `nearest`-tenor is a config alternative to linear-interp (§13.5a). The P(IRR<hurdle) default hurdle (§13.10b) = this `r_e` unless an explicit hurdle field overrides. *(The 0.10 discount in Vectors 1–3 is a deliberately round placeholder for transparent NPV/IRR arithmetic; in production the base discount is this CAPM `r_e`.)*

---

## Vector 1 — BASE: pre-tax, unlevered, single trajectory (M=1)

**Exercises:** NPV, IRR, MIRR, simple & discounted payback, LCOE. `distribution_valid=false` (M=1 ⇒ point estimates only, distributional fields **absent**, §13.10c).

**Inputs**
```
N = 2 yr ;  CAPEX (overnight, t=0) = ¥1,000,000
revenue(y)      = ¥700,000   (hourly-integrated grid_export net, P1)   y=1,2
fixed_OM(y)     = ¥100,000                                              y=1,2
var_OM, replacement, tax, terminal = 0
EBITDA(y)       = 700,000 − 100,000 = ¥600,000                          y=1,2
E_net(y)        = 10,000 MWh                                            y=1,2
discount r (= r_e, base) = 0.10
CF = [ −1,000,000 ,  +600,000 ,  +600,000 ]
```

**Expected (hand-computed)**
```
NPV(0.10) = −1,000,000 + 600,000/1.10 + 600,000/1.10²
          = −1,000,000 + 545,454.5455 + 495,867.7686
          = ¥ 41,322.31                                   # assert ±¥1

IRR: let u = 1/(1+IRR).  600,000u + 600,000u² = 1,000,000
     u² + u − 1.6666667 = 0 ;  disc = 1 + 4·1.6666667 = 7.6666667 ;  √ = 2.7688746
     u = (−1 + 2.7688746)/2 = 0.8844373 ;  1+IRR = 1/0.8844373 = 1.1306624
IRR = 0.1306624 = 13.0662 %                                # assert ±0.01 pp

MIRR (reinvest = finance = r = 0.10):
     FV_pos@yr2 = 600,000·1.10 + 600,000 = 1,260,000 ;  PV_neg = 1,000,000
     MIRR = (1,260,000/1,000,000)^(1/2) − 1 = √1.26 − 1 = 1.1224972 − 1
          = 0.122497 = 12.2497 %                           # assert ±0.01 pp ; MIRR reported alongside IRR (§13.8)

Simple payback   = 1 + (1,000,000 − 600,000)/600,000 = 1.66667 yr   # fractional interp
Discounted payback@0.10:
     cum disc CF: yr1 = 545,454.55 (rem 454,545.45) ; yr2 disc CF = 495,867.77
     = 1 + 454,545.45/495,867.77 = 1.91667 yr

LCOE (§13.8, r=0.10):
     PV(costs) = 1,000,000 + 100,000/1.10 + 100,000/1.10²
               = 1,000,000 + 90,909.09 + 82,644.63 = 1,173,553.72
     PV(E_net) = 10,000/1.10 + 10,000/1.10² = 9,090.909 + 8,264.463 = 17,355.372 MWh
     LCOE = 1,173,553.72 / 17,355.372 = ¥ 67.62 /MWh        # assert ±¥0.01/MWh
```
**Honesty assert:** `distribution_valid=false`; `downside_risk.distributional` and all percentile fields **absent** (not fabricated); only `single_trajectory` + point estimates present; M=1 banner string present (§13.10c).

---

## Vector 2 — TAX TOGGLE: Vector 1 + 25% corporate tax (reported as a delta)

**Exercises:** the `tax_rate` toggle (§13.9), straight-line depreciation, tax-as-delta-to-base. Same CAPEX/EBITDA as Vector 1.

**Inputs (added to Vector 1)**
```
tax_rate = 0.25 ;  depreciation = straight-line, depreciation_years = 2  ⇒  dep(y) = 1,000,000/2 = 500,000
taxable(y)  = EBITDA − dep = 600,000 − 500,000 = 100,000
tax(y)      = 0.25 · 100,000 = ¥25,000                     y=1,2
CF(y)       = EBITDA − tax = 600,000 − 25,000 = ¥575,000
CF = [ −1,000,000 , +575,000 , +575,000 ]
```

**Expected (hand-computed)**
```
NPV(0.10) = −1,000,000 + 575,000/1.10 + 575,000/1.10²
          = −1,000,000 + 522,727.27 + 475,206.61 = −¥ 2,066.12           # assert ±¥1

ΔNPV_tax (delta vs Vector 1, the reported quantity) =
     −(25,000/1.10 + 25,000/1.10²) = −(22,727.27 + 20,661.16) = −¥ 43,388.43
     cross-check: 41,322.31 + (−43,388.43) = −2,066.12  ✓                # tax is a pure delta

IRR_after_tax:  575,000(u + u²) = 1,000,000 ;  u² + u − 1.7391304 = 0
     disc = 7.9565217 ; √ = 2.8207307 ; u = 0.9103654 ; 1+IRR = 1/0.9103654 = 1.0984601
IRR = 0.0984601 = 9.8460 %                                                # assert ±0.01 pp
     ⇒ below the 10% hurdle ⇒ after-tax NPV<0 ; the 15%-renewable-qualifying flag (tax_rate=0.15) is the same computation with 0.15.
```
**Asserts:** tax block reported as `delta_to_base`; base case unchanged (Vector 1 numbers reproduced with `tax=off`); VAT **not** modeled (§13.14-11).

---

## Vector 3 — LEVERED DELTA: Vector 1 + debt toggle (equity-IRR + min-DSCR)

**Exercises:** debt toggle (§13.9), equity IRR, DSCR, debt-gating (DSCR/equity-IRR **absent unless debt ON**). Pre-tax EBITDA from Vector 1; clean numbers (5% / 2-yr amortizing) for hand-checkable amortization.

**Inputs**
```
CAPEX = 1,000,000 ;  D/E = 1.5  ⇒  D/V = 0.6, E/V = 0.4  ⇒  Debt = 600,000, Equity = 400,000
loan: amortizing, rate r_d = 0.05, term = 2 yr (level payment)
payment A = 600,000 · [0.05·1.05²] / [1.05² − 1] = 600,000 · 0.055125 / 0.1025 = ¥ 322,682.93 /yr
amort:  yr1 int = 600,000·0.05 = 30,000 ; prin = 292,682.93 ; bal = 307,317.07
        yr2 int = 307,317.07·0.05 = 15,365.85 ; prin = 307,317.08 ; bal ≈ 0  ✓
EBITDA(y) = 600,000 (pre-tax base)
```

**Expected (hand-computed)**
```
CFADS(y) = EBITDA (pre-tax base, §13.8 CFADS ≈ EBITDA − Tax; tax off here) = 600,000
DSCR(y)  = CFADS / DebtService = 600,000 / 322,682.93 = 1.8594   (level, y=1,2)
min_DSCR = 1.859                                                  # assert ±0.001 (1.85941)

Equity CF:  CF_eq(0) = −(CAPEX − Debt) = −400,000
            CF_eq(y) = EBITDA − A = 600,000 − 322,682.93 = 277,317.07   (y=1,2)
Equity IRR: 277,317.07(u+u²) = 400,000 ;  u² + u − 1.4423923 = 0
     disc = 6.7695692 ; √ = 2.6018396 ; u = 0.8009198 ; 1+IRR_eq = 1/0.8009198 = 1.2485645
IRR_eq = 0.2485645 = 24.8565 %                                   # assert ±0.01 pp

Levered delta (the reported quantity):
     ΔIRR = IRR_eq − IRR_project = 24.8565 % − 13.0662 % = +11.79 pp   (positive leverage: project return > r_d)
     min_DSCR = 1.86
```
**Asserts:** with `debt=off`, `equity_IRR` and `min_DSCR` are **absent** (not 0/null) — debt-gating (§13.12 inv 3 / §13.9); with `debt=on` they appear and are reported as deltas to the unlevered base.

---

## Vector 4 — LIFECYCLE: replacement CAPEX at EOL + terminal/residual (§13.6, mandatory)

**Exercises:** the **§13.6 lifecycle layer** — battery **replacement CAPEX** scheduled at `first-of(lifetime_years, cycle_life via throughput)`, **terminal value** (residual − decommissioning) at year N, and their effect on NPV and LCOE. This is the cash half of **INV-DEG** (§13.2/§3.6) and the mechanism behind **View II** (the per-policy discriminator IS wear→replacement timing, §13.1). **USER-concluded mandatory** (§13.6 / §13.13-7) — not optional, not deferrable without an rl-architect + human §13.6 scope change. *(Vectors 1–3 are deliberately zero-replacement for transparent base arithmetic; Vector 4 is the lifecycle gate they omit.)*

**Inputs** (econ fields are present in the merged #103 device library — `DeviceEconParams` must surface them)
```
CAPEX (battery, t=0) = ¥1,000,000 ;  N = 4 yr ;  EBITDA = ¥600,000/yr ;  r = 0.10
lifetime_years            = 2     # toy calendar bound → replacement fires END of yr 2 (first-of)
replacement_cost_fraction = 0.70  → replacement CAPEX = 0.70·1,000,000 = ¥700,000  (booked yr 2)
residual_value_fraction   = 0.05  → residual = ¥50,000 ;  decommissioning = ¥20,000
terminal (yr N=4)         = residual − decommissioning = 50,000 − 20,000 = ¥30,000
CF = [ −1,000,000 ,  600,000 ,  600,000−700,000 = −100,000 ,  600,000 ,  600,000+30,000 = 630,000 ]
```

**Expected (hand-computed)**
```
NPV(0.10) = −1,000,000 + 600,000/1.10 + (−100,000)/1.10² + 600,000/1.10³ + 630,000/1.10⁴
          = −1,000,000 + 545,454.55 − 82,644.63 + 450,788.88 + 430,298.48
          = ¥ 343,897.27                                              # assert ±¥1

LCOE (r=0.10, E_net = 10,000 MWh/yr, FixedOM=0 for clarity):
  PV(costs) = CAPEX + repl/1.10² − residual/1.10⁴
            = 1,000,000 + 700,000/1.21 − 50,000/1.4641
            = 1,000,000 + 578,512.40 − 34,150.67 = 1,544,361.72
  PV(E_net) = Σ_{y=1..4} 10,000/1.10^y = 31,698.65 MWh
  LCOE_with_replacement = 1,544,361.72 / 31,698.65 = ¥ 48.72 /MWh     # assert ±¥0.01/MWh
  (LCOE_without_replacement = ¥31.55/MWh — ignoring replacement understates LCOE ~54%)

MIRR(0.10) = 17.85 %                                                  # assert ±0.01 pp ; the IRR-companion
  # the yr-2 replacement makes CF sign-flip (−,+,−,+,+ = 3 sign changes) ⇒ multiple-IRR risk (§13.8).
  # Gate on NPV + LCOE + MIRR; do NOT gate a bare IRR (≈24% but multi-root) — this is exactly why §13.8
  # mandates MIRR alongside IRR in replacement years.
```
**Asserts:** gate on **NPV + LCOE + MIRR** (not bare IRR — replacement-year sign flip → multi-IRR, §13.8). Replacement CAPEX appears as a **negative CF in the replacement year** (yr 2 here), once; terminal `residual − decommissioning` adds to `CF(N)`; LCOE includes `+Replacement − Residual` (§13.8). A horizon ≥ 2·lifetime runs unit-1 then unit-2, each with its own residual (§13.6).

**General mechanism, not a battery special-case (D39 §2 D1a; finance-expert scope call).** The engine implements **one data-driven lifecycle path**: any device whose econ block carries the lifecycle fields gets `first-of(lifetime_years, throughput→cycle_life)` replacement + terminal/residual. **Battery (first-of(10yr, cycle-life)) is the mandatory headline — Vector 4 gates it fully.** **PV-inverter** subsystem replacement (calendar-only, ~yr10–12, partial `replacement_cost_fraction`) and **wind overhaul** fall out of the same path; v1 vector coverage = Vector 4 (battery, full) **+ a light PV-inverter calendar-replacement smoke** (`lifetime_years`-only trigger, no cycle-life) confirming a non-battery calendar replacement rides the same code. A dedicated wind-overhaul vector is a v2 refinement (rides the mechanism with a smoke in v1).

**Cycle-life trigger basis (explicit, per the "arithmetic shown" rule — load-bearing for View II):** the throughput arm of `first-of` fires when `cumulative bat_throughput_mwh ≥ cycle_life_full_equiv · usable_energy_mwh`, with **`usable_energy_mwh = nameplate `capacity_mwh`** (a full-equivalent cycle = nameplate throughput, by the field's definition). **The operating SOC window** (`soc_min..soc_max`, D4-LOCKED — Gansu 0.2–0.9) **must NOT enter `usable_energy`**: it already limits the *numerator* (`bat_throughput_mwh` the policy actually generates per dispatch), so folding it into the denominator double-counts the window and mis-times replacement. *Separate #103 data-provenance requirement (device-library owner):* `cycle_life_full_equiv` must store a **true full-equivalent** count — a manufacturer figure quoted at a rated DoD (e.g. #103 BYD "8000 at 90% DoD") must be converted (`8000·0.90 = 7200`) before storage, else replacement fires ~(1−DoD) late and over-states View-II battery value. Engine logic is correct for whatever full-equivalent values #103 lands on; the conversion is a #103 fix, not engine logic.

**INV-DEG EOL-replacement assert (the cash half FIN-24 does not cover):** with `lifetime_years = 3` but `cycle_life_full_equiv` reached at **yr 2** via throughput, the replacement fires at **yr 2** (`first-of` — the throughput trigger beats the calendar bound) ⇒ replacement CAPEX booked **once** at yr 2; `degradation_yuan` remains memo-only (never a period deduction). A **hard-cycling policy replaces earlier** than a gentle one under identical prices — exactly View II's per-policy discrimination (§13.1). *Test must assert both: (i) the throughput-triggered year, and (ii) cash impact = replacement CAPEX once, degradation memo-only.*

---

## §A — Downside-stat definitions as testable formulas (§13.10b), with a worked M=50 ensemble

All downside metrics are computed on the **M weather draws at a fixed price path** (M is the *only* stochastic axis — INV-FINLAYER; price paths are a separate deterministic family, never cross-producted). Worked numbers use a clean linear ensemble so every stat is hand-checkable.

**Canonical percentile estimator (finance-expert LOCKS — reproducibility):**
For a higher-is-better metric (NPV, IRR, MIRR), the **exceedance** percentile is
```
P_q  =  np.quantile(sorted_ascending(metric), 1 − q, method='lower')
```
("in q of weather scenarios the project achieves at least P_q"). For lower-is-better metrics (LCOE, payback) use `q` with `method='higher'`. `method='lower'/'higher'` (nearest-rank, no interpolation) is mandated so the headline number is a realized draw and bit-reproducible across the server engine and the client library.

**§A.0 — Percentile regimes (canonical R1/R2/R3; D39 §6.7 references this table).** The populated metric set + confidence tags vary by `(sample_kind, M)`; the `FinanceResult` **shape is identical across all three** (absent fields = a represented "no distribution available," **never fabricated** — §13.10c). **One estimator** (the lock above) across R2+R3 — a second estimator is a review-fail.

| Regime | Trigger | `distribution_valid` | Populated | Suppressed (absent, not fabricated) |
|---|---|---|---|---|
| **R1 fast-iteration** | M = 1 | **false** | `single_trajectory` only — point NPV, max drawdown+year, worst-year CF; non-dismissable M=1 banner | every percentile + the whole `distributional` downside block |
| **R2 bootstrap** (v1 default) | `sample_kind=bootstrap`, M ≥ 50 (D34) | true | **P50/P75/P90/P95** + bootstrap CI + per-percentile `confidence`; full downside panel incl. **CVaR-5%** (k=ceil(0.05·M)=3 at M=50), worst-case NPV, P(NPV<0), P(IRR<hurdle), max drawdown+year, worst-year CF | P99 (optional `indicative_low_confidence` only, never a bare headline) |
| **R3 empirical small-sample** | `sample_kind=empirical`, M≈10 (`weather.mode: real`) | true | **per-year trajectories** (headline) + **empirical P50** + **empirical worst/best-of-N** (labeled "worst/best of N observed years," **NOT** percentiles) + **P(NPV<0)** frequency; all empirical-caveat-tagged | **P75/P90/P95/P99 AND CVaR-5%** as labeled stats — under the locked nearest-rank estimator at M≈10, P90 = `x[floor(0.10·(M−1))]` = the min and CVaR-5% (k=1) = the single worst, so all three would relabel one number; the honest worst-case is surfaced once as "worst-of-N" |

R3 is rl-architect's D39 §4 ruling (finance-expert domain call, team-lead-backed). The §A worked ensemble below is the **R2** case (M=50); the **R3** empirical worked vector is **§A.1**. CVaR-5% is a full headline in R2 (k=3 meaningful) and suppressed only in R3.

**Worked ensemble (M=50):**  `NPV_m = −100,000 + (m−1)·10,000`, m = 1…50  (ascending; range −100,000 … +390,000).

| Stat | Formula | Worked value |
|---|---|---|
| **Worst-case NPV (max loss)** | `min_m NPV_m` | −¥100,000 |
| **P(NPV < 0)** | `#{m: NPV_m < 0} / M` | 10/50 = **0.20** (m=1…10) |
| **P(IRR < hurdle)** | `#{m: IRR_m < hurdle} / M`, hurdle default = `r_e` (override field wins) | IRR ensemble below ⇒ **0.24** |
| **CVaR-5%** | `k = ceil(0.05·M)`; mean of the `k` lowest NPVs | k=3 → mean(−100k,−90k,−80k) = **−¥90,000** |
| **P50 / P75 / P90 / P95** | estimator above, q=0.50/0.75/0.90/0.95 | **140,000 / 20,000 / −60,000 / −80,000** |
| **Max cumulative drawdown + year** | `min(0, min_y cumCF_excl_CAPEX(y))`; year = argmin | see trajectory ↓ |
| **Worst single-year CF** | `min` over y=1…N and all M of annual net CF (year-0 CAPEX excluded — certain) | see trajectory ↓ |

Percentile rank checks — **0-based numpy indices** (the index a test encoder asserts on `np.sort(x)`; `method='lower'` virtual index `i = floor((1−q)·(M−1))` on the ascending array, M=50):
`P50 → i=floor(0.50·49)=24 → x[24]=140,000`; `P75 → i=floor(0.25·49)=12 → x[12]=20,000`; `P90 → i=floor(0.10·49)=4 → x[4]=−60,000`; `P95 → i=floor(0.05·49)=2 → x[2]=−80,000`. *(0-based: `x[0]` is the worst draw −100,000; `x[49]` the best +390,000. Encode against `numpy` 0-based indexing — do **not** use 1-based labels.)*

**IRR ensemble for P(IRR<hurdle):** `IRR_m = 0.04 + (m−1)·0.005`, m=1…50; hurdle = 0.10 ⇒ `IRR_m<0.10` for m=1…12 ⇒ **12/50 = 0.24**.

**Drawdown / worst-year trajectory** (single trajectory; annual net CF excl. year-0 CAPEX):
```
y:        1         2         3         4         5
CF(y):  +100,000  −150,000  −250,000  +180,000  +320,000
cum:    +100,000   −50,000  −300,000  −120,000  +200,000
max cumulative drawdown = min(0, min cum) = −¥300,000  at  year 3
worst single-year CF    = min CF(y)       = −¥250,000  (year 3)
```
> **Drawdown definition LOCKED to the §13.10b literal:** *running shortfall below zero* in cumulative operating CF (year-0 CAPEX excluded), i.e. `min(0, min_y cumCF(y))` with the argmin year. (The peak-to-trough alternative is **not** used; flagged so finance-engineer encodes the shortfall-below-zero form.)

**Bootstrap CI (§13.10a) — testable despite randomness:**
- Seeded: `B = 2000` resamples of the M draws with replacement, fixed seed in `finance_config`/provenance ⇒ **same seed → identical CI** (determinism assert).
- Default 90% CI = (P5, P95) of the bootstrap distribution of the statistic.
- Property asserts: point estimate ∈ CI; CI width ≥ 0; **degenerate case** (all M draws equal) ⇒ CI width = 0; `confidence` tag = `indicative_low_confidence` when width exceeds the §13.10a thresholds (IRR ≥ 2 pp, NPV ≥ 20%·|P50|), else `sound`.

**M=1 honesty (§13.10c) reasserted here:** at M=1 every §A distributional stat is **absent** (not P50=P90=single draw); only `single_trajectory` (max drawdown+year, worst-year CF, point NPV) is emitted.

---

## §A.1 — R3 empirical small-sample worked vector (real-weather, M≈10)

This is the **R3** regime of the §A.0 canonical table (D39 §4): `sample_kind="empirical"`, the ~10 ERA5 historical calendar years used **as-is** (not block-bootstrapped). The output uses the **same ONE locked estimator** as R2 (`np.quantile(sorted, 1−q, method='lower')` / `'higher'`) — only the *populated set* is narrower, per the small-sample honesty discipline. `distribution_valid=True` (it is a valid empirical distribution; just narrow). All R3 outputs carry `empirical_caveat=true`.

**Worked ensemble (M=10).** Per-draw NPV over 10 historical years — each draw is one calendar year's full N-year degraded trajectory (§13.7/F-B) — shown ascending for the arithmetic (in practice keyed by calendar year, unsorted):
```
NPV_m (¥) = [ −80,000, −30,000, +10,000, +40,000, +60,000, +90,000, +120,000, +150,000, +200,000, +260,000 ]   # m = 1…10
sorted ascending (0-based): x[0]=−80,000 … x[9]=+260,000
```

**R3 POPULATED** (the honest small-sample set):

| Stat | Formula (M=10) | Worked value |
|---|---|---|
| **per-year trajectory strip** | all N=10 observed years surfaced **individually** — THE headline | 10 per-year entries (each: NPV + CF series) |
| **empirical P50** | `np.quantile(sorted, 1−0.50, method='lower')` → `x[floor(0.50·9)] = x[4]` | **¥60,000** |
| **empirical worst-of-N** | `min_m NPV_m` — labeled **"worst of 10 observed years"**, NOT a percentile | **−¥80,000** |
| **empirical best-of-N** | `max_m NPV_m` — labeled **"best of 10 observed years"**, NOT a percentile | **+¥260,000** |
| **P(NPV<0)** | `#{NPV_m < 0} / M` — empirical frequency over the actual years | 2/10 = **0.20** ("2 of 10 historical years lose money") |
| **P(IRR<hurdle)** | `#{IRR_m < hurdle} / M` — empirical **frequency** (NOT a percentile/tail estimator, so it does **not** collapse at small M; honest at M≈10, same class as P(NPV<0)) | populated; hurdle default = `r_e` |

**Kept-P50 confidence tag — `indicative_low_confidence`, NEVER `"sound"` (binding).** The empirical P50 is *kept* (it doesn't collapse like the tails) but it is still a ~10-sample median, so its `confidence` is **`indicative_low_confidence`** — consistent with the "every R3 percentile is `indicative_low_confidence`" rule below and with the §13.10a CI-width derivation: for the worked sample, P50's 90% bootstrap CI is **(¥10,000, ¥120,000)**, width **¥110,000**, which is **~9×** the convergence threshold (20%·|P50| = ¥12,000) → `indicative_low_confidence` by a wide margin. "Meaningful median" (§A.0) justifies **keeping** P50 vs suppressing it; it does **not** make it `"sound"`. The tag must be **derived** from the CI width per §13.10a (the regime never hardcodes `"sound"` for R3). *Test must assert `P50.confidence == "indicative_low_confidence"` in R3.*

**R3 SUPPRESSED** (absent = `None`, **never fabricated** — the §13.10c discipline). Each would collapse to the observed worst at M≈10, so labeling it as a fitted percentile/tail is a relabel of the worst-of-N:

| Stat | Why suppressed (M=10) |
|---|---|
| **P90** | `x[floor(0.10·9)] = x[0] = −80,000` = the **worst-of-N** → labeling it "P90" claims a 90%-exceedance probability 10 samples can't support |
| **P95 / P99** | even deeper than P90 → `x[0]` (= worst) → not credible at M=10 (P95 needs M≥50 / R2) |
| **P75** | `x[floor(0.25·9)] = x[2] = +10,000` — a coarse small-sample value; **only P50 is kept** in R3 |
| **CVaR-5%** | `k = ceil(0.05·10) = 1` → mean of 1 worst = −80,000 = **worst-of-N** → would double-label the same number |
| **bootstrap CI** | optional; if shown, every R3 percentile is `confidence="indicative_low_confidence"` and never a bare headline |

**One estimator, identical schema (D39).** R3 reuses R2's estimator verbatim — a second estimator is a review-fail. The `FinanceResult` shape is **identical** across R1/R2/R3; R3 simply leaves the suppressed fields `None` (a represented "no distribution available"), exactly as R1 (M=1) leaves the whole distributional block `None`. `sample_kind` selects the populated set; there is **no schema branch**.

**Maps to FIN-47–52** (currently skip-stubbed pending this section; finance-engineer un-skips + encodes):
- **FIN-47** — `distribution_valid=True` at M=10 empirical.
- **FIN-48** — `P75`, `P90`, `P95`, `P99`, **and** `CVaR-5%` are all `None`.
- **FIN-49** — empirical `P50 = ¥60,000` (`x[4]`, rank `floor(0.50·9)=4`).
- **FIN-50** — `worst_of_n = −¥80,000`, `best_of_n = +¥260,000`, labeled (not percentiles).
- **FIN-51** — `P(NPV<0) = 0.20` (2 of 10).
- **FIN-52** — R3 uses the **same** `np.quantile(...,'lower')` estimator as R2.

---

## §B — D13 → cash-flow no-double-count invariants (each a required hand-computed test, §13.2)

| Invariant | Test fixture | Expected |
|---|---|---|
| **INV-BASIS** (§13.0 P3) | a draw where reward-basis totals differ materially (SOC penalties + demand-shaping added) | cash-flow output = **real-money** number exactly; **fails** if any `penalty_yuan/soc_*/c_demand_shape/reward` field is wired |
| **INV-DEG** (memo half) | one year of battery throughput, EOL not reached | `degradation_yuan` is **memo-only** — no period cash deduction (FIN-24) |
| **INV-DEG** (cash half — Vector 4) | throughput reaches `cycle_life_full_equiv` at yr 2 while `lifetime_years=3` | replacement CAPEX appears **once**, at the **throughput-triggered** year (yr 2, `first-of`), = `replacement_cost_fraction·CAPEX`; `degradation_yuan` still memo-only. *The cash half FIN-24 omits; gates the §13.6 lifecycle layer + View II discrimination.* |
| **INV-CURT** (flag OFF) | one curtailment hour, `curtailment_penalty_contract=off` | cash loss = foregone `grid_export` revenue **only** (not revenue + ¥800/MWh penalty) |
| **INV-VOLL** (own-load) | one unserved-load hour | cash hit = lost **product** revenue once — VOLL **XOR** lost-product, never both |
| **INV-FINLAYER** (§13.4) | a non-uniform per-stream price path | `requires_retrain=true`, result badged; env trace **independent** of `price_path` (no price-path/escalation field reachable from dispatch) |
| **INV-STREAM-AUTHORITY** (§13.2/§13.7; D32(b)) | a draw where the streams-net and the `real_money` aggregate **disagree** (streams-net = ¥100,000, `energy_cost_yuan` = decoy ¥555,555) | operating cash built from the **6 stream accumulators ONLY** → cash = ¥100,000 exactly; `real_money.{energy_cost_yuan, demand_charge_yuan, total_cost_yuan}` are **non-additive D13 reconciliation views** (`energy_cost_yuan ≡ grid_import_value − grid_export_value`; `demand_charge_yuan ≡ demand_charge stream`) — **never summed onto** the stream-derived cash. Only `real_money.{degradation, curtailment, voll}` (no stream representation) carry cash treatment beyond the streams (INV-DEG/CURT/VOLL). *Fails if energy_cost/demand_charge/total_cost are added on top (double-count).* |

---

## §C — Acceptance criteria for the finance engine (the gate finance-expert applies)

The implementation is accepted (finance-expert verdict toward QA) only if **all** hold:

1. **Surface conformance.** Signature, `FinanceResult` shape, and field names match §13.12 exactly (typed `PolicyEnsemble` with structural `seed`/`M`; `per_policy → {View I, View II} → per price_path`; `single_trajectory` vs `distributional` split). Pure function: no I/O, no network, no hidden global (treasury curve passed via `finance_config`).
2. **Vectors 0–4 pass to tolerance.** Discount module (Vector 0): `r_f`/`r_e(base)`/`β_L`/`r_e(lev)`/`WACC` ±1e-6 (decimal). Cash-flow/metrics (Vectors 1–3): NPV ±¥1; IRR/MIRR/equity-IRR ±0.01 pp; DSCR ±0.001; LCOE ±¥0.01/MWh; payback ±0.001 yr. **Lifecycle (Vector 4): replacement CAPEX booked once at `first-of(lifetime_years, cycle_life)`, terminal `residual−decommissioning` at year N → NPV ¥343,897.27; LCOE-with-replacement ¥48.72/MWh** — against the hand-computed numbers above, arithmetic in test comments. Vector 0 gates `discount.py` independently of metric math (CAPM→WACC must not ship ungated); **Vector 4 gates the §13.6 lifecycle layer — `DeviceEconParams` must surface `replacement_cost_fraction`/`cycle_life_full_equiv`/`lifetime_years`/`residual_value_fraction`/`decommissioning` (present in #103), and the lifecycle layer is mandatory (not silently omittable, §13.6/§13.13-7).**
3. **Tax & debt are deltas.** Base = pre-tax unlevered (`discount = r_e`); tax toggle reproduces Vector 2's ΔNPV; debt toggle reproduces Vector 3's equity-IRR/min-DSCR; **debt-gated fields absent when debt off**; **distributional fields absent when `distribution_valid=false` (M=1)** — absence is represented, never fabricated.
4. **Downside formulas** (§A) match exactly, including the **LOCKED** percentile estimator (`np.quantile(...,'lower'/'higher')`), `CVaR k=ceil(0.05·M)`, and the shortfall-below-zero drawdown.
4b. **Percentile regimes R1/R2/R3** (§A.0 canonical table, D39 §6.7): M=1 → point estimates + banner only; bootstrap M≥50 → P50/P75/P90/P95 + CI + full downside incl. CVaR-5%; empirical M≈10 → per-year + P50 + worst/best-of-N + P(NPV<0), **P75/P90/P95/P99 + CVaR-5% suppressed (absent, not fabricated)**. One estimator across R2+R3; identical `FinanceResult` shape; `sample_kind` selects the populated set, no schema branch.
5. **Invariants** (§B) — all six no-double-count / axis-separation tests pass: INV-BASIS structurally (reward-basis fields unreachable from the cash-flow path); INV-STREAM-AUTHORITY (operating cash from the 6 stream accumulators only; `real_money.{energy_cost, demand_charge, total_cost}` are non-additive reconciliation views — fails on double-count); **INV-DEG BOTH halves — memo-only (no throughput→EOL) AND cash (throughput→`first-of` replacement CAPEX once, Vector 4)** — not just the memo half.
6. **CRN structural** (§13.12 inv 1): every policy's `runs` list has length M with index-aligned draws from `ensemble.seed`; the seed travels into `provenance`. Per-policy deltas are pure dispatch under a synthetic two-policy fixture with identical draws.
7. **Determinism & provenance.** Fixed inputs → identical `FinanceResult` (incl. seeded bootstrap CI). `provenance` carries seed, M, `valuation_date`, `r_f(curve_date, tenor, yield)`, `r_e`/WACC, discount params, escalation/price_path, scenario_id, code_version; mismatched-assumption results are refused for comparison.
8. **Econ defaults sourced from #103** (`config/device_models.yaml` 2.1.0) with per-value provenance; CAPM values from §13.5b (`USER-confirmed/2026-06-13`); none hardcoded in engine code — all UI-editable.
9. **View II gating + definition** (§13.12 inv 3; D39 §2 `engine.py` facade): View II = **NPV(π) − NPV(`baseline_policy_id`) over the CRN-shared draws** (index-aligned m ⇒ pure-dispatch delta, P2), computed in the facade. `baseline_policy_id ∈ runs.keys()` ⇒ incremental-storage view produced; absent ⇒ View II **omitted** (never fabricated), View I still produced.
10. **Client/server parity** (§13.4): the stage-⑤ client library reproduces the engine within ≤0.01 pp (IRR/MIRR) and ≤¥1k (NPV) per draw on a shared ≥(M=5 × N=20 × ≥2 multiplier vectors) test vector.

**finance-expert is the acceptance gate.** QA (qa-engineer) issues the closing verdict; finance-expert's APPROVE on the finance semantics is required for the contract test-gate and again at implementation audit.
