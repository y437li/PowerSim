# Review Record — `compare_endpoints` (SC2 — Compare Workbench Endpoints)

**Contract:** `contracts/serving/compare_endpoints.md` v1.0.0
**Canonical (D45):** `contracts/shared/finance_result_summary.md`
**Tests:** `tests/serving/test_serving_compare_endpoints.py`
**PR:** #134 · **Branch:** `feat/serving-compare-endpoints`
**Reviewers:** backend-reviewer + frontend-reviewer (shared contract — both required;
  rl-architect lifts RC; QA_PASS_WITH_ISSUES needs rl-architect APPROVE sign-off)

---

## Stage 1 — Contract + Tests Gate

### frontend-reviewer — APPROVE @ `dd36db1` (2026-06-13)

All 7 items from the initial REQUEST_CHANGES resolved:
- `sample_kind` moved under `provenance` (enum `"bootstrap"|"empirical"`; `"synthetic"` FORBIDDEN per D42/#133)
- `m_draws` + `distribution_valid` present under `provenance`
- Flat fields → `MetricPercentiles` nested shape
- `point_npv_yuan` / `point_irr_pct` → `single_trajectory` block; `point_irr_pct` ABSENT
- Provenance name clash resolved (regime provenance vs `finance_assumptions`)
- SC3 sizing-sweep reconciled in §9.1
- `view_ii_delta` confirmed unused / absent

**`FinanceResultSummary` shape confirmed metric-major** (nested percentile dicts per metric,
not row-major). APPROVE posted on PR #134 @ `dd36db1`.

### backend-reviewer — APPROVE @ `dd36db1` (2026-06-13)

Four drift items from initial REQUEST_CHANGES resolved:
- Per-percentile nesting (`{p50: {value, confidence}, p75: ...}`)
- `sample_kind` enum `{"bootstrap","empirical"}`
- R1/point fields correct (`single_trajectory` non-null only at R1; point_irr_pct absent)
- R3 P50 confidence = `"indicative_low_confidence"`

**Reviewer-added test cases (@ `dd36db1`):**

| Test function | Rationale |
|---|---|
| `test_finance_engine_exception_returns_500` | finance() exception → 500 INTERNAL_ERROR (not 422 or uncaught) |
| `test_finance_unknown_field_in_finance_params_is_400` | INV-CE-15 closed allow-set; unknown key `"gamma"` → 400 VALIDATION_ERROR |
| `test_finance_typo_field_in_finance_params_is_400` | INV-CE-15: `"horizon_year"` typo of `"horizon_years"` → 400 |
| `test_plan_cache_size_unchanged_after_plan` | INV-CE-10: `POST /api/compare/plan` must not evict or populate LRU cache |
| `test_finance_returns_404_for_sweep_run_id` | INV-CE-09: sweep run_ids must NOT resolve via recompute-finance |
| `test_finance_m_draws_equals_requested_m` | provenance.m_draws must equal `shared_scenario.m_draws` from the request |
| `test_finance_sample_kind_is_bootstrap_or_empirical` | INV-CE-17: `"synthetic"` forbidden (D42/#133 LOCK) |

**Approved test-file version:** `tests/serving/test_serving_compare_endpoints.py` @ `dd36db1`
(developer cases + 7 reviewer cases above). **Implementation may proceed.**

### rl-architect — RC cleared @ `dd36db1` (2026-06-13)

Initial RC raised two issues:
1. `sample_kind` must be `{"bootstrap","empirical"}` — not `"synthetic"` (D42/#133 LOCK violation)
2. SC2 §2.4 must adopt nested shape from #132

Both resolved at `dd36db1`. rl-architect cleared RC; D45 decision also issued (D45/#135):
`contracts/shared/finance_result_summary.md` is the single-source canonical for all producers.

---

## Stage 2 — Implementation Code Audit

### Implementation commits (on `feat/serving-compare-endpoints`)

| Commit | Description |
|---|---|
| `1cfcd69` | Initial implementation — 6 endpoints, `EnsembleCache` LRU, stub fast path, `_synthesize_from_stub`, `_serialize_view` |
| `75399ac` | D45 producer fixes — §2.4→pointer, `equity_irr_pct` scalar in `debt_metrics`, `payback_discounted_yr`, `bootstrap_ci` NPV-only, `single_trajectory` always non-null |

### backend-reviewer — code audit APPROVE @ `ef95b69` (2026-06-14)

All 4 D45 producer fixes verified correct against locked #135 (head 1524f5e):
- §2.4 → pointer: clean defer, no re-inline ✓
- `debt_metrics` scalar: `equity_irr_pct` ×100 percent, `min_dscr` bare ratio; gated on `debt_on AND regime≠R1` in BOTH `_serialize_view` and `_synthesize_from_stub` ✓
- `payback_discounted_yr` using engine `payback_disc_yr` attr ✓
- `bootstrap_ci` NPV-only (`include_ci=True` only for `npv_yuan`) ✓

`single_trajectory` null→nonnull test flip confirmed spec-mandated (#135 line 42 "present at ALL M").

**Reviewer pushed commit `ef95b69` — two R3 tests rewritten:**

| Old test | Issue | New test |
|---|---|---|
| `test_finance_p90_confidence_at_r3` | Written under D39 §4 "mark tails low-confidence"; passed vacuously after D45 reversed to R3=p50-only | Positively asserts: regime==R3, p50 present + `"indicative_low_confidence"`, p75/p90/p95/p99 all `None` |
| `test_finance_p90_at_r3_if_present` | Same issue — permissive guard let R3 tail-presence pass silently | Same rewrite |

**Non-blocking follow-up (not gating):** `_serialize_view` delegates R3 tail-nulling to the engine's view rows rather than enforcing it explicitly — sound today because #120's engine R3 impl guarantees it. Add explicit R3 guard in `_serialize_view` if real `PolicyEnsemble` path is wired without that guarantee.

**Approved test-file version:** `tests/serving/test_serving_compare_endpoints.py` @ `ef95b69` (75 tests, 0 skipped). **Gate = APPROVE.** (issuecomment-4702438387)

---

## QA Stage

### qa-engineer — QA_PASS_WITH_ISSUES @ `1cfcd69` (2026-06-14)

**Suite results:** 75/75 compare_endpoints + 489 passed / 24 skipped full serving suite.

Domain invariants verified: INV-CE-01, 04, 05, 09, 11, 15, 16, 17, 18, LRU eviction,
concurrent-read safety, WACC back-solve formula.

**Issues (no correctness bugs):**
1. Missing `contracts/reviews/compare_endpoints.md` → resolved in this file
2. Stale contract status "DRAFT" → resolved (status updated to APPROVED)
3. Contract §2.4 debt fields shape divergence → resolved by `75399ac` (§2.4 is now pointer)

**Merge path:** CI green + rl-architect APPROVE sign-off.

---

## Invariants approved by reviewers

| ID | Invariant |
|----|-----------|
| INV-CE-01 | 404 if eval_result_id not in LRU cache |
| INV-CE-04 | IRR, MIRR, equity IRR in JSON are percent (×100) |
| INV-CE-05 | `finance_assumptions.wacc/r_f/r_e` are decimal (NOT ×100) |
| INV-CE-09 | Sizing-sweep `run_id` must not resolve via recompute-finance |
| INV-CE-10 | `POST /api/compare/plan` is pure read (no cache mutation) |
| INV-CE-11 | `POST /api/compare/run` → 202 (not 200/201) |
| INV-CE-15 | `finance_params` closed allow-set; unknown key → 400 VALIDATION_ERROR |
| INV-CE-16 | `debt_metrics.min_dscr` bare ratio NOT ×100; assert < 10.0 |
| INV-CE-17 | `provenance.sample_kind` ∈ {"bootstrap","empirical"}; "synthetic" FORBIDDEN |
| INV-CE-18 | `single_trajectory` non-null at ALL M (D45 §3 rule 3; updated from old "null at R2/R3") |
| INV-CE-19 | All 5 metrics null at R1: irr_pct, npv_yuan, mirr_pct, lcoe_yuan_per_mwh, payback_discounted_yr |
| INV-CE-20 | `cash_flow_series_yuan` present ONLY at R2 |
| INV-CE-21 | `bootstrap_ci` ONLY in npv_yuan nodes (Rule B, D45) |
| INV-CE-22 | `debt_metrics.equity_irr_pct` SCALAR (not MetricPercentiles); block null when debt off or at R1 |
