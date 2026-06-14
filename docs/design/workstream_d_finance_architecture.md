# Workstream-D — Finance / Cash-Flow Engine Architecture (rl-architect DECISION)

**Status:** DECISION (draft for finance-expert alignment → lock on rl-architect authority).
**Owner:** rl-architect (boundaries) · finance-expert (semantics, task #4) · finance-engineer (impl).
**Realizes:** §13 (project finance, D36), §13.12 `finance()` surface, D34 (M=50/P95), D31/F1.
**Reviewer gate:** backend-reviewer (pure engine + REST shape) + frontend-reviewer (REST consumption + client lib).
**Cite as:** D39.

This doc locks the **module boundaries, data path, weather-toggle location, honest-percentile
discipline, and the contract/test ownership split** for the §13 finance layer. It does **not**
re-decide any §13.13-resolved item (M=50, P95, CAPM values, INV-FINLAYER, etc. — all stand).
Heuristic-first v1: this is the path to the first showable financial result; **RL training stays
deferred** — no training run is scoped here.

---

## 1. The data path (end-to-end)

```
 ┌─ workstream-C (multi-year sim) — NOT the finance engine ─────────────────────────┐
 │  §11 heuristic dispatch policy π   (greedy | dp_oracle | mpc | tou | no_battery)  │
 │     run_benchmark(π, env) over the eval year, per weather draw, per degraded year │
 │              │                                                                     │
 │              ▼                                                                     │
 │  ExtendedPolicyEvalResult  (per dispatched year; task #55 — stream-keyed,         │
 │     6 streams × {volume, value_yuan} + 22 physical qtys + D13 real-money + memo)  │
 │              │  × N years (per-year DEGRADED physics: capacity fade, replacement  │
 │              ▼   resets) = ONE draw;  × M weather draws (CRN, shared seed) = …     │
 │  PolicyEnsemble { seed, M, runs: {π -> [N-year trajectory]} }                      │
 └──────────────┬───────────────────────────────────────────────────────────────────┘
                │   (this is the FINANCE ENGINE INPUT — already dispatched, off-wire)
                ▼
 ┌─ workstream-D (the pure finance engine) ────────────────────────────────────────┐
 │  finance(ensemble, price_paths, econ, finance_config) -> FinanceResult            │
 │     cash_flow → metrics → price_path transform → distributions → sensitivity      │
 └──────────────┬───────────────────────────────────────────────────────────────────┘
                ▼
   GET /api/finance/compare   (thin off-wire REST wrapper; both-reviewer gate)
                ▼
   stage-⑤ frontend  +  client-side finance lib (price-path re-multiply, ≤0.01pp / ≤¥1k parity)
```

**The load-bearing boundary:** the **M×N dispatch (running each policy over M weather draws ×
N degraded years) is workstream-C, OUTSIDE the pure finance engine.** The engine's input is an
*already-dispatched* `PolicyEnsemble`; it performs **no dispatch, no env step, no I/O**. This is
what makes `finance()` pure (§13.12) and keeps INV-FINLAYER structural: no price/escalation/contract
term can reach `step` because the engine never calls `step`.

**The exact data-handoff object (the §11→D seam — team-lead ask).** Per scenario, the engine
consumes ONE `PolicyEnsemble`:

```
PolicyEnsemble = {
  seed:        int,                       # shared CRN seed (→ provenance)
  M:           int,                       # 50 (synthetic) | ~10 (real)
  sample_kind: "bootstrap" | "empirical", # selects the §4 percentile regime
  runs: { policy_id -> [ length-M; each draw = [ ExtendedPolicyEvalResult(year n) : n=1..N ] ] }
}
```

Each leaf is the **task-#55 `ExtendedPolicyEvalResult`** verbatim — its 6-stream `{volume,
value_yuan}` accumulators (real year-1 ¥, D31/F1; sign applied by D1a per the §13.7 inflow/outflow
convention) + 22 physical-quantity fields + D13 real-money buckets + memo. **The engine reads ONLY
`streams[*].{volume,value_yuan}` + quantities + real-money; the memo block (`penalty_yuan`, `soc_*`)
is structurally unreachable (INV-BASIS).** No new eval field, no telemetry bump — §11 baselines
(`run_benchmark`) already emit this object; workstream-C just stacks N years × M draws into `runs`.

---

## 2. Module decomposition (boundaries are binding)

New area **`finance`** (created by this DECISION; precedent D15/D20 — a new area comes into
existence by rl-architect DECISION when its first feature lands). Code `src/energy_go/finance/`,
contracts `contracts/finance/`, tests `tests/finance/`, **backend-reviewer-gated** (pure backend,
off-wire). The realizing PR adds `finance` to the CLAUDE.md `<area>` list + `check_conventions.sh`.

| Module | Path | Owns | Purity |
|---|---|---|---|
| **D1a cash_flow** | `finance/cash_flow.py` | D13→cash mapping (§13.2: INV-BASIS/DEG/CURT/VOLL); per-draw N-year CF series from streams + CAPEX/OPEX/lifecycle/terminal (§13.6) | pure |
| **D1b metrics** | `finance/metrics.py` | NPV / IRR / MIRR / LCOE / LCOS / payback / DSCR on a single CF series (§13.8) | pure |
| **D1c price_path** | `finance/price_path.py` | §13.4 post-hoc multiplier transform + preset library + `requires_retrain` flag (INV-FINLAYER) | pure |
| **D1d distributions** | `finance/distributions.py` | M-axis aggregation: exceedance percentiles, bootstrap CI, per-percentile confidence, downside-risk panel (§13.10), `distribution_valid` + percentile-regime honesty (§4 below). Estimator **LOCKED by finance-expert** (PR #107): `np.quantile(sorted, 1−q, method='lower')` (higher-better) / `method='higher'` (lower-better); CVaR-5% over `k=ceil(0.05·M)` worst draws; drawdown = §13.10b literal `min(0, min_y cumCF_excl_CAPEX)` (shortfall-below-zero, **not** peak-to-trough). **ONE estimator** serves R2 and R3 (R3 = same estimator, reduced percentile set). | pure |
| **D1e discount** | `finance/discount.py` | CAPM→WACC from `finance_config` (CGB-curve linear-interp to horizon, Hamada relever, §13.5) | pure |
| **D1f sensitivity** | `finance/sensitivity.py` | §13.11 NPV-vs-r fan, tornado, sensitivity surface | pure |
| **D1 facade** | `finance/engine.py` | the `finance(ensemble, price_paths, econ, finance_config) -> FinanceResult` entry point (§13.12). **Owns View I/II aggregation** (orchestration, not its own module): **View I** = absolute per-policy distribution; **View II** = incremental `NPV(π) − NPV(baseline_policy_id)` computed **over the CRN-shared draws** (index-aligned m, so the delta is pure dispatch — P2). `baseline_policy_id` from `finance_config`; absent → View II omitted, never fabricated (§13.12 inv 3). | pure |
| **D2 econ loader** | `finance/econ_params.py` | `device_models.yaml` econ block (#103 benchmarks) → `DeviceEconParams`; site fleet → per-device CAPEX/OPEX/lifecycle | pure (reads pre-resolved config) |
| **D3 ensemble builder** | workstream-C (`harness`/`training`) — **NOT D** | runs π × M × N → `PolicyEnsemble`; owns the weather toggle (§3) | impure (calls env) |
| **D4 serving** | `serving/` `GET /api/finance/compare` | thin wrapper: build ensemble (D3) → `finance()` → serialize; provenance join | I/O at the edge only |
| **D5 client lib** | frontend `financeClient.ts` | client-side price-path re-multiply; parity ≤0.01pp IRR / ≤¥1k NPV vs server (§13.4) | — |

**Binding invariants on the boundary (from §13.12, restated as acceptance gates):**
- `finance()` is a **pure function** — no network, no filesystem, no clock, no global state; the CGB
  curve and all econ params arrive via arguments. A test imports `finance` and asserts no I/O module
  is reachable from the call (mirrors INV-BASIS structural test).
- **CRN structural:** `PolicyEnsemble.seed` lives on the ensemble (not `finance_config`); every
  policy's `runs` list has length `M` with index-aligned draws. Engine asserts this and refuses
  ragged ensembles.
- **`econ` is a single shared arg**, not per-policy (P2): all policies share CAPEX + scenario.
- **INV-FINLAYER:** price paths enter ONLY in D1c, applied to *already-dispatched* streams; a
  non-uniform/per-stream path sets `requires_retrain=true` and badges the result. No price-path field
  is reachable from any dispatch code (guarded by the D3-side env-trace-independence test).

---

## 3. Weather-source toggle — location and effect (USER narrowed directive)

**The toggle lives in the ensemble builder (D3 / workstream-C), driven by `weather.mode` in the
site YAML (§12 weather_pipeline).** It changes ONLY *what the M scenarios are*; `finance()` sees a
different `PolicyEnsemble` and **the `FinanceResult` schema is unchanged — NO rework.**

| `weather.mode` | What D3 produces | M | Engine sees |
|---|---|---|---|
| `synthetic` (default) | §4/§12 seasonally-stratified **block-bootstrap** draws | **M = 50** (D34) | a 50-draw ensemble |
| `real` | ERA5 historical **calendar years used as-is** (§12 `oracle_years`) | **M ≈ 10** (empirical) | a ~10-draw ensemble |

The engine is **M-agnostic**: it computes distributions over whatever M it is handed. The only
metadata it needs is `M` + a **`sample_kind ∈ {bootstrap, empirical}`** carried on the ensemble (→
provenance). That tag selects the percentile regime in §4 — **no schema branch, no FinanceResult
field added.** This is the same mechanism §13.10c already uses for `distribution_valid`.

---

## 4. Honest-percentile discipline — three regimes, ONE schema

The percentile set populated and its confidence tags vary by `(sample_kind, M)`; the `FinanceResult`
shape is **identical** across all three (absent fields are a represented "no distribution available",
**never fabricated** — §13.10c "report honestly").

| Regime | Trigger | `distribution_valid` | Percentiles populated | Notes |
|---|---|---|---|---|
| **R1 fast-iteration** | M = 1 | **false** | none (point estimate only) | §13.10c existing; single-trajectory downside only; non-dismissable M=1 banner |
| **R2 bootstrap (default v1)** | `sample_kind=bootstrap`, M ≥ 50 | true | **P50 / P75 / P90 / P95** + bootstrap CI per percentile (D34) | P95 = decision tail; P99 dropped from headline (optional `indicative_low_confidence` only); full downside-risk panel |
| **R3 empirical small-sample** | `sample_kind=empirical`, M small (~10) | true | **per-year trajectory strip (headline)** + **empirical P50 (median)** + **empirical worst/best-of-N observed-year range** + **P(NPV<0)** (empirical frequency, e.g. "2 of 10 historical years lose money"); all **empirical-caveat-tagged** | **P75 / P90 / P95 / P99 AND CVaR-5% are ABSENT as labeled stats (not fabricated)** — finance-expert correctness call (PR #107): under the LOCKED nearest-rank estimator, at M≈10 `P90 = quantile(sorted, 0.10, method='lower')` → index `floor(0.10·9)=0` = the MIN, and `CVaR-5% k=ceil(0.05·10)=1` = the single worst → P90/CVaR/worst-case would be **three labels for one number** (the §13.10c relabel trap). The empirical worst/best are surfaced as **"worst/best of N observed years," NOT as percentiles** (a real historical fact, not a fitted tail). A credible P90 needs M≳15–20; P95 gates on the R2 M≥50 path. |

R3 is the honest treatment of "10 real calendar years used as-is" (finance-expert's domain ruling,
team-lead-backed). It reuses R1/R2's exact "absent-not-fabricated" + `confidence` machinery **and the
same single LOCKED estimator** (finance-expert PR #107 §A) — only the *populated set* differs:
{per-year strip + P50 + empirical worst/best-of-N range + P(NPV<0)}, with **no labeled tail
percentile or CVaR** (those collapse to min/2nd-min at N≈10 under the locked nearest-rank estimator).
Schema unchanged — a different M-set + a tighter "what's populated" rule, NO `FinanceResult` rework
(the user's narrowed directive). **finance-engineer implements ONE estimator, not two** — R3 is the
same estimator with a reduced, honestly-labeled output set. If a P90-ish number is ever wanted in R3
it MUST switch to an interpolating estimator AND be tagged `indicative_low_confidence` — but the
locked v1 call is the explicit empirical-range framing. The **convergence hint** (§13.10a) fires in
R3 by construction. The canonical R1/R2/R3 acceptance table is finance-expert PR #107 (§6.7 ref).

---

## 5. Contract / test ownership split (the gate structure)

| Concern | Owner | Deliverable | Gate |
|---|---|---|---|
| **Finance SEMANTICS + hand-computed vectors** | **finance-expert** (task #4) | **DELIVERED — PR #107 `docs/design/finance_engine_acceptance_basis.md`**: fully-worked `finance()` vectors (pre-tax unlevered BASE, tax toggle, levered delta) with arithmetic shown; downside-stat formulas; CAPM worked example; the LOCKED percentile/CVaR/drawdown estimator (§A). finance-expert is the **acceptance gate** for engine correctness. **Writes no production code.** | rl-architect signs the semantics; backend-reviewer co-reviews |
| **IMPLEMENTATION** | **finance-engineer** | D1a–D2 pure modules + `engine.py` facade conforming to the gated contract; passes finance-expert's vectors + backend-reviewer's adversarial cases | backend-reviewer (shape/purity) + finance-expert (numbers) + QA |
| **finance() boundary contract** | finance-engineer authors, **finance-expert co-authors test cases** | `contracts/finance/finance_engine.md` (the §13.12 surface, INV-FINLAYER/INV-BASIS structural barriers) | backend-reviewer |
| **Ensemble builder (D3)** | workstream-C (harness/training) | `PolicyEnsemble` assembly + weather toggle + env-trace-independence test | backend-reviewer |
| **REST `/api/finance/compare`** | serving-engineer | thin wrapper + provenance join | **both reviewers** (§13.12) |
| **Client finance lib (D5)** | frontend-engineer | price-path re-multiply + shared test-vector parity | frontend-reviewer |

**Rule of thumb:** finance-expert owns *"what number is correct and why"*; finance-engineer owns
*"the code that produces it"*; the two never collapse — a hand-computed vector authored by the
implementer is not an independent acceptance gate.

---

## 6. Acceptance criteria (engine v1 = power-composite, heuristic-first)

1. **Purity:** `finance()` provably pure — no I/O reachable; fixed inputs → identical `FinanceResult`.
2. **Hand-computed parity:** passes all of finance-expert's task-#4 vectors (**PR #107**,
   `finance_engine_acceptance_basis.md`: NPV/IRR/MIRR/LCOE/LCOS/DSCR + downside stats) to the stated
   tolerance, arithmetic shown in each test comment. The percentile/CVaR/drawdown estimator matches
   §A of PR #107 exactly (`np.quantile … method`, CVaR `k=ceil(0.05·M)`, drawdown `min(0,min cumCF)`)
   — **ONE estimator** serves R2 and R3 (a second estimator is a review-fail).
3. **INV-BASIS:** a fixture where real-money ≠ reward-basis → cash output = real-money exactly; a
   wired reward-basis field **fails** the test (structural unreachability).
4. **INV-DEG / INV-CURT / INV-VOLL:** the three no-double-count vectors (§13.2) pass.
5. **INV-FINLAYER:** non-uniform price path → `requires_retrain=true` + badge; env trace independent
   of `price_path` (D3-side test).
6. **CRN:** identical M draws across policies → per-policy metric deltas are pure dispatch; ragged
   ensemble rejected.
7. **Three regimes (R1/R2/R3, §4; canonical table = PR #107 §6.7):** M=1 → point estimates only,
   banner; bootstrap M≥50 → P50/P75/P90/P95 + CI; **empirical ~10 → per-year strip + empirical P50 +
   empirical worst/best-of-N range + P(NPV<0); NO labeled P75/P90/P95/P99 or CVaR-5%** (they collapse
   to min/2nd-min at N≈10 under the locked nearest-rank estimator — absent, not faked).
   **View II naming:** `engine.py` computes View II = `NPV(π) − NPV(baseline_policy_id)` over
   CRN-shared draws; `baseline_policy_id` absent → View II omitted (never fabricated).
8. **View II:** `baseline_policy_id` present → incremental-battery NPV vs no-battery; absent → View I
   only, View II omitted (never fabricated).
9. **Debt toggle:** equity-IRR / min-DSCR emitted ONLY when debt ON (absent, not zero/null, when off).
10. **Client/server parity:** ≤0.01pp IRR/MIRR, ≤¥1k NPV per draw on the shared test vector.
11. **Provenance:** every result carries seed + M + sample_kind + valuation_date + r_f(curve,tenor,
    yield) + discount params + price_path + scenario_id + code_version; mismatched-assumption
    results refuse to compare.
12. **Prerequisites green:** extended `PolicyEvalResult` (#55) + §12 block-bootstrap battery
    (PR#77 §4.2) + #103 econ defaults — all merged/passing before engine QA.

---

## 7. Out of scope for v1 (fidelity boundary — reject scope creep)

RL training run (deferred — heuristic dispatch only); hydrogen/aluminum/token streams (design-proven
config-only, §13.3); live treasury fetch (static curve, §13.5/v2); VAT/deferred-tax (§13.14);
forced-outage stochastics; real-option value; non-power action-space extensions. Per §13.14.
