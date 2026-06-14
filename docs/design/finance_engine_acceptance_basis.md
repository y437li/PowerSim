# Finance engine — acceptance basis (hand-computed vectors, downside formulas, criteria)

**Owner:** finance-expert (finance acceptance gate for workstream-D) · **Status:** acceptance basis for the `finance()` engine (task #4)
**Governs:** finance-engineer's `finance()` contract + test cases. The numbers here are the **hand-computed expected values** that the reviewer-approved tests MUST encode (engineering rule: "finance tests assert hand-computed expected numbers with the arithmetic shown in a comment"). finance-expert is the acceptance gate when the implementation lands.

**Authoritative surface:** §13.12 `finance(ensemble, price_paths, econ, finance_config) -> FinanceResult` (merged #100, LOCKED). This document does **not** alter the surface; it supplies the semantics finance-engineer's contract is gated against. Econ defaults = the merged #103 China benchmark library (`config/device_models.yaml`, schema 2.1.0). USER-concluded §13 decisions are fixed inputs (M=50/D34, P95 tail, CAPM values §13.5b) — not re-opened here.

> **Two coordination points flagged to rl-architect (task #3 boundary), not blocking these vectors:** (1) the engine's **area name** (`finance` vs folding into `serving`) — vectors are area-agnostic; (2) the **small-sample real-weather percentile discipline** (per-year + P50/P90, no P95/P99) is rl-architect's to lock — §A below covers the **synthetic M=50** mode (D34); the real-weather mode reuses the same formulas with a reduced/annotated percentile set per task #3.

---

## Conventions used by every vector

- All amounts ¥ (RMB), nominal; rates decimal; energy MWh. CF indexed `y = 0…N`; `CF(0) = −Total_overnight_CAPEX`.
- `CF(y) = EBITDA(y) − Replacement(y) − Tax(y)`; `CF(N)` adds Terminal (§13.8).
- `EBITDA(y) = Σ revenue − Σ cost(FixedOM, VarOM, asset-mgmt)` after the §13.4 price path. Base vectors use a **uniform constant-real path** `m(y)=1` ⇒ INV-FINLAYER `requires_retrain=false`.
- Discount rate `r` shown explicitly per vector (CAPM base `r_e`; §13.5). Vectors use small round inputs so NPV/IRR/MIRR/DSCR are hand-verifiable; the realistic Gansu numbers live in #103 and are exercised by an integration smoke, not these unit vectors.
- IRR roots are given as the **exact quadratic solution** (N=2 vectors) so the arithmetic is shown end-to-end, not a black-box solver output.

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
     u = (−1 + 2.7688746)/2 = 0.8844373 ;  1+IRR = 1/0.8844373 = 1.1306630
IRR = 0.130663  = 13.0663 %                                # assert ±0.01 pp

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
     disc = 7.9565217 ; √ = 2.8207307 ; u = 0.9103654 ; 1+IRR = 1.0984402
IRR = 0.098440 = 9.8440 %                                                 # assert ±0.01 pp
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
DSCR(y)  = CFADS / DebtService = 600,000 / 322,682.93 = 1.8593   (level, y=1,2)
min_DSCR = 1.859                                                  # assert ±0.001

Equity CF:  CF_eq(0) = −(CAPEX − Debt) = −400,000
            CF_eq(y) = EBITDA − A = 600,000 − 322,682.93 = 277,317.07   (y=1,2)
Equity IRR: 277,317.07(u+u²) = 400,000 ;  u² + u − 1.4423974 = 0
     disc = 6.7695896 ; √ = 2.6018435 ; u = 0.8009217 ; 1+IRR_eq = 1.2485621
IRR_eq = 0.248562 = 24.8562 %                                    # assert ±0.01 pp

Levered delta (the reported quantity):
     ΔIRR = IRR_eq − IRR_project = 24.8562 % − 13.0663 % = +11.79 pp   (positive leverage: project return > r_d)
     min_DSCR = 1.86
```
**Asserts:** with `debt=off`, `equity_IRR` and `min_DSCR` are **absent** (not 0/null) — debt-gating (§13.12 inv 3 / §13.9); with `debt=on` they appear and are reported as deltas to the unlevered base.

---

## §A — Downside-stat definitions as testable formulas (§13.10b), with a worked M=50 ensemble

All downside metrics are computed on the **M weather draws at a fixed price path** (M is the *only* stochastic axis — INV-FINLAYER; price paths are a separate deterministic family, never cross-producted). Worked numbers use a clean linear ensemble so every stat is hand-checkable.

**Canonical percentile estimator (finance-expert LOCKS — reproducibility):**
For a higher-is-better metric (NPV, IRR, MIRR), the **exceedance** percentile is
```
P_q  =  np.quantile(sorted_ascending(metric), 1 − q, method='lower')
```
("in q of weather scenarios the project achieves at least P_q"). For lower-is-better metrics (LCOE, payback) use `q` with `method='higher'`. `method='lower'/'higher'` (nearest-rank, no interpolation) is mandated so the headline number is a realized draw and bit-reproducible across the server engine and the client library.

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

Percentile rank checks (method='lower'): P50→rank 25→x[25]=140,000; P75→rank 13→x[13]=20,000; P90→rank 5→x[5]=−60,000; P95→rank 3→x[3]=−80,000.

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

## §B — D13 → cash-flow no-double-count invariants (each a required hand-computed test, §13.2)

| Invariant | Test fixture | Expected |
|---|---|---|
| **INV-BASIS** (§13.0 P3) | a draw where reward-basis totals differ materially (SOC penalties + demand-shaping added) | cash-flow output = **real-money** number exactly; **fails** if any `penalty_yuan/soc_*/c_demand_shape/reward` field is wired |
| **INV-DEG** | one year of battery throughput | cash impact appears **once** — as replacement CAPEX at the EOL year (first-of(10yr, cycle-life)); `degradation_yuan` is memo-only |
| **INV-CURT** (flag OFF) | one curtailment hour, `curtailment_penalty_contract=off` | cash loss = foregone `grid_export` revenue **only** (not revenue + ¥800/MWh penalty) |
| **INV-VOLL** (own-load) | one unserved-load hour | cash hit = lost **product** revenue once — VOLL **XOR** lost-product, never both |
| **INV-FINLAYER** (§13.4) | a non-uniform per-stream price path | `requires_retrain=true`, result badged; env trace **independent** of `price_path` (no price-path/escalation field reachable from dispatch) |

---

## §C — Acceptance criteria for the finance engine (the gate finance-expert applies)

The implementation is accepted (finance-expert verdict toward QA) only if **all** hold:

1. **Surface conformance.** Signature, `FinanceResult` shape, and field names match §13.12 exactly (typed `PolicyEnsemble` with structural `seed`/`M`; `per_policy → {View I, View II} → per price_path`; `single_trajectory` vs `distributional` split). Pure function: no I/O, no network, no hidden global (treasury curve passed via `finance_config`).
2. **Vectors 1–3 pass to tolerance.** NPV ±¥1; IRR/MIRR/equity-IRR ±0.01 pp; DSCR ±0.001; LCOE ±¥0.01/MWh; payback ±0.001 yr — against the hand-computed numbers above, with the arithmetic in test comments.
3. **Tax & debt are deltas.** Base = pre-tax unlevered (`discount = r_e`); tax toggle reproduces Vector 2's ΔNPV; debt toggle reproduces Vector 3's equity-IRR/min-DSCR; **debt-gated fields absent when debt off**; **distributional fields absent when `distribution_valid=false` (M=1)** — absence is represented, never fabricated.
4. **Downside formulas** (§A) match exactly, including the **LOCKED** percentile estimator (`np.quantile(...,'lower'/'higher')`), `CVaR k=ceil(0.05·M)`, and the shortfall-below-zero drawdown.
5. **Invariants** (§B) — all five no-double-count / axis-separation tests pass, INV-BASIS structurally (reward-basis fields unreachable from the cash-flow path).
6. **CRN structural** (§13.12 inv 1): every policy's `runs` list has length M with index-aligned draws from `ensemble.seed`; the seed travels into `provenance`. Per-policy deltas are pure dispatch under a synthetic two-policy fixture with identical draws.
7. **Determinism & provenance.** Fixed inputs → identical `FinanceResult` (incl. seeded bootstrap CI). `provenance` carries seed, M, `valuation_date`, `r_f(curve_date, tenor, yield)`, `r_e`/WACC, discount params, escalation/price_path, scenario_id, code_version; mismatched-assumption results are refused for comparison.
8. **Econ defaults sourced from #103** (`config/device_models.yaml` 2.1.0) with per-value provenance; CAPM values from §13.5b (`USER-confirmed/2026-06-13`); none hardcoded in engine code — all UI-editable.
9. **View II gating** (§13.12 inv 3): `baseline_policy_id ∈ runs.keys()` ⇒ incremental-storage view produced; absent ⇒ View II **omitted**, View I still produced.
10. **Client/server parity** (§13.4): the stage-⑤ client library reproduces the engine within ≤0.01 pp (IRR/MIRR) and ≤¥1k (NPV) per draw on a shared ≥(M=5 × N=20 × ≥2 multiplier vectors) test vector.

**finance-expert is the acceptance gate.** QA (qa-engineer) issues the closing verdict; finance-expert's APPROVE on the finance semantics is required for the contract test-gate and again at implementation audit.
