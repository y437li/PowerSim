# Review record: `finance_engine`

**Contract:** `contracts/finance/finance_engine.md`
**Tests:** `tests/finance/test_finance_finance_engine.py` (FIN-00–FIN-57; R3 FIN-47–52 skip-marked PENDING D39)
**Required reviewer:** backend-reviewer (sole gate for the pure engine)
**Semantics / acceptance gate:** finance-expert (PR #107; reviewed in parallel)
**Task:** #6 · **PRs:** #110 (superseded — branch underscore) → **#111** (`feat/finance-finance-engine`)
**Stage:** contract + tests (pre-implementation). Implementation lands after this gate + finance-expert; CI greens then; QA closes. Merges **after D39 (#108)**.

---

## backend-reviewer gate — APPROVE (2026-06-13)

### Round 1 (#110) → REQUEST_CHANGES
- **Blocker 1 — branch name.** `feat/finance-finance_engine` (underscore) failed `check_conventions.sh` (CI red). Resolved by re-opening as **#111** on `feat/finance-finance-engine`.
- **Blocker 2 — latent double-count.** §4 (EBITDA from streams) vs §3.5 (reads `real_money.*`) didn't pin the authoritative operating-cash source; FIN-23 couldn't discriminate (streams-net == `energy_cost_yuan` == 100k). Routed to finance-expert (semantics owner).
- **Missed edge cases.** Added by me (see below).

### Round 2 (#111) → all resolved
- **Blocker 2 RESOLVED** (commit 6ef872c, finance-expert ruling **INV-STREAM-AUTHORITY**): streams are the authoritative operating-cash source; `energy_cost_yuan`/`demand_charge_yuan`/`total_cost_yuan` are **non-additive reconciliation VIEWS** (`energy_cost_yuan ≡ grid_import.value − grid_export.value`; `demand_charge_yuan ≡ demand_charge stream`); only `degradation/curtailment/voll` carry cash beyond the streams. Encoded as **§3.5 split** (cash-bearing vs view-only — my requested wording), new **§3.5a**, **§4 annotation**, and **FIN-23b** decoy fixture (stream-net ¥100k; `energy_cost_yuan` decoy ¥555,555; assert cf==¥100k; an additive impl → ¥655,555 fails). Verified against finance-expert's confirmed verbatim text and mirrored in #107 §B (INV-STREAM-AUTHORITY row, re-APPROVED @ c494bcf).
- **FIN-22b cumsum bug fixed** (commit 8ad86cf): now passes the **annual** CF series; `max_drawdown()` cumsums internally per §13.10b (`min(0, min(np.cumsum(cf_excl_capex)))`).
- **Tax/debt end-to-end VALUE tests** (FIN-56/FIN-57): `finance(tax_toggle=True, depreciation_years=2)` → after-tax NPV −¥2,066.12 & ΔNPV −¥43,388.43; `finance(debt_toggle=True, D/E=1.5, term=2, r_d=0.05)` → equity-IRR 24.8565% & min-DSCR 1.8594. Both through the `finance()` facade.
- **Discount-fixture pin** (commit 7c76da6): `_make_base_config` pins `equity_risk_premium=0.0` with `r_f_override=0.10` so the engine's CAPM `r_e` collapses to 0.10 for the Vector 1–3 end-to-end tests (otherwise r_e=0.136 would break FIN-56/57). Vector 0 (FIN-00*) is unaffected — it uses `_CAPM_CONFIG_BASE` with ERP=0.06 (r_e=0.0590). Correct separation.

### Verified sound (re-derived independently, two methods)
- **Vectors 0–3 + §A downside** encode finance-expert's corrected #107 numbers exactly with arithmetic shown: V0 r_f 0.0230 / r_e(base) 0.0590 / β_L(lev) 1.275 / r_e(lev) 0.0995 / WACC 0.061175; V1 NPV ¥41,322.31 / IRR **13.0662%** / MIRR 12.2497% / LCOE ¥67.62; V2 NPV −¥2,066.12 / IRR **9.8460%**; V3 DSCR **1.8594** / equity-IRR **24.8565%**; downside worst −100k, P(NPV<0) 0.20, P(IRR<hurdle) 0.24, CVaR −90k (k=ceil(0.05·50)=3), P50/75/90/95 = 140k/20k/−60k/−80k via **0-based** x[24]/x[12]/x[4]/x[2], drawdown −300k@yr3 (shortfall-below-zero), worst-year −250k.
- Boundary discipline: FIN-16 excludes NPV=0, FIN-17 excludes IRR=0.10 (strict `<`).
- Invariants FIN-23/23b/24–27 are genuine no-double-count traps. R3 FIN-47–52 correctly `pytest.mark.skip(PENDING D39)`; FIN-48 collapse rationale matches D39 §4.
- Contract faithful to §13.12 + D39: PolicyEnsemble/FinanceConfig/FinanceResult shapes, 7 sub-modules + engine facade, CRN (ragged→ValueError), View II = NPV(π)−NPV(baseline)/omitted-when-absent, debt-toggle gating (None-not-zero), purity, M=1 honesty, LOCKED estimator.
- Conventions: CLAUDE.md `finance` area + STACK.md row correct. `check_conventions.sh` needed no area edit (area-agnostic); the finance test-location guard finance-engineer added is a fine additive tightening (kept).

### Reviewer-added cases (CLAUDE.md — I own these; commit 69650b3, self-fix 0efd02b)
- **FIN-53** drawdown no-shortfall clamp → cf=[100k,50k,200k] ⇒ `max_drawdown==0.0` (pins the `min(0,·)` shortfall-below-zero clamp vs peak-to-trough). Self-fixed (0efd02b) to pass the **annual** series, aligning with the FIN-22b call convention.
- **FIN-54** CVaR k=ceil at integer 0.05·M → M=20⇒k=1 (CVaR −10,000); M=40⇒k=2 (CVaR −19,500). Guards an `int()+1` over-count.
- **FIN-55** multi-sign MIRR → cf=[−1000,2500,−1560] ⇒ MIRR 9.6022% single-valued where IRR has 2 roots (§4 multi-IRR-risk).
- All hand-computed with arithmetic in comments, verified two ways. They fail-at-run until the engine is implemented (expected at the pre-impl gate).

### Approved suite = developer cases (FIN-00–52, 56–57) + reviewer cases (FIN-53–55).
**Note:** CI is red with `ModuleNotFoundError: energy_go.finance` — expected at the contract+tests gate (tests import the not-yet-built engine). Implementation makes CI green within #111 before it is marked ready.

**Approved content head:** `7c76da6` (Blocker-2 resolution 6ef872c + my FIN-53 self-fix 0efd02b + discount-fixture pin 7c76da6). This review-record commit sits on top. Merges after D39 (#108).
