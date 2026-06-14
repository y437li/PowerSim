# Contract: `finance_result_summary` — canonical `FinanceResultSummary` wire shape (single-source)

**Area:** shared · **Owner/Lead:** rl-architect (locks) · **Semantics owner:** finance-expert (the regime/percentile/confidence + units rules) · **Reviewers:** backend-reviewer (producer side) + frontend-reviewer (consumer side)
**Test file:** `tests/shared/test_shared_finance_result_summary.py`
**Realizes:** **D45** (single-source the finance WIRE shape) + reconciles #132 (consumer, nested v1.1.0) ⊕ #134 (producer, SC2) + the #133 `sample_kind` LOCK + the §13.10c / D39 regime corrections + D41 (per-draw CRN diff).

---

## 1. Purpose + the single-source principle (D45)

`FinanceResultSummary` is the **wire shape** emitted by serving (`GET /api/finance/compare`, #134) and consumed by the frontend (the comparison workbench, #132). It was **co-defined** in both PRs and drifted (#134 flat v1.0.0 vs #132 nested v1.1.0), producing a `sample_kind:"synthetic"` **#133-LOCK violation** and a missing per-percentile `confidence` field.

> **D45 — single-source (the D18/D37/`telemetry_schema` discipline applied to the finance wire shape): there is ONE canonical `FinanceResultSummary`, defined HERE. The producer (#134 serving) serializes TO it; the consumer (#132 frontend) reads it. NEITHER redefines it.** finance-expert owns the regime/percentile/confidence/units semantics; rl-architect locks; both reviewers gate their respective sides against this file.

This is the **serialized wire view** of the in-process `FinanceResult` (which lives in `finance_engine.md`, the `finance` area) — distinct concern, distinct home (shared/), same pattern as `telemetry_schema` being the wire view that producers/consumers implement against.

---

## 2. Canonical shape — `FinanceResultSummary` v1.1.0

**Atom = one (config, view) summary.** Serving emits one per view: **View-I always**; **View-II only when a `baseline_policy_id` was supplied**. Self-describing (carries its own provenance/regime).

```jsonc
{
  "schema_version": "1.1.0",

  // ── Provenance (self-describing; from FinanceResult.provenance + distribution_valid) ──
  "provenance": {
    "sample_kind": "bootstrap",        // "bootstrap" | "empirical"  — NEVER "synthetic" (that is a DISPLAY label only)
    "m_draws": 50,                     // = FinanceResult.M
    "distribution_valid": true,        // false when M==1
    "hurdle_rate_pct": 12.4,           // percent — the hurdle used for p_irr_below_hurdle
    "valuation_date": "2026-06-14",
    "horizon_years": 20,
    "seed": 42,
    "code_version": "0.4.1"
  },

  // ── Regime — DERIVED by serving, never trusted from caller ──
  "regime": "R2",                      // !distribution_valid→R1 ; sample_kind=="bootstrap"→R2 ; sample_kind=="empirical"→R3

  // ── Single trajectory — present at ALL M (the R1 headline; supplementary at R2/R3) ──
  "single_trajectory": {
    "point_npv_yuan": 1500000.0,       // single-scenario NPV; label "NPV (single scenario)" at R1, never "P50"
    "max_drawdown_yuan": -320000.0,
    "max_drawdown_year": 7,            // 1-indexed
    "worst_year_cf_yuan": 41000.0
  },

  // ── Per-metric percentile distributions (METRIC-MAJOR; D45 ruling) — each = MetricPercentiles | null (null at R1) ──
  //   Regime-nulling is UNIFORM across all metrics (rule C): R2 → p50/p75/p90/p95 (+ optional indicative p99); R3 → p50 only; R1 → every metric block null.
  "irr_pct":            { /* MetricPercentiles */ },   // null at R1; values percent (×100)
  "npv_yuan":           { /* MetricPercentiles */ },   // null at R1; ¥ — the ONLY metric carrying bootstrap_ci (rule B)
  "mirr_pct":           { /* MetricPercentiles */ },   // null at R1; percent
  "lcoe_yuan_per_mwh":  { /* MetricPercentiles */ },   // null at R1; ¥/MWh
  "payback_discounted_yr":         { /* MetricPercentiles */ },   // null at R1; years

  // ── Downside risk — null at R1; PARTIAL at R3 ──
  "downside_risk": {
    "worst_case_npv_yuan": 300000.0,   // min_m NPV_m  ("worst of N years" at R3)
    "best_of_n_npv_yuan": null,        // max_m NPV_m — R3 ONLY; null at R1/R2
    "p_npv_neg": 0.04,                 // probability ∈[0,1] (NOT ×100); #{NPV_m<0}/M
    "p_irr_below_hurdle": 0.10,        // probability ∈[0,1]; POPULATED at R2 AND R3 (empirical frequency, does NOT collapse at M≈10); null ONLY at R1 (block absent)
    "cvar5_yuan": 280000.0,            // R2 ONLY; null at R3 (k=ceil(0.05·10)=1 collapses to worst-of-N)
    "max_drawdown_yuan": -320000.0,
    "max_drawdown_year": 7,
    "worst_year_cf_yuan": 41000.0
  },

  // ── Debt metrics — BOTH SCALAR (engine emits float means, NOT distributional — engine.py:679-680); null when debt_toggle=false ──
  "debt_metrics": {
    "equity_irr_pct": 14.21,           // SCALAR, PERCENT (×100 of float mean) — INV-CE-04; null when debt off
    "min_dscr": 1.836                  // SCALAR BARE RATIO (NOT ×100; <10 realism guard) — INV-CE-16; null when debt off
  },

  // ── View-II incremental — present ONLY on the View-II summary; null on View-I ──
  "view_ii_delta": null                // see per-draw-diff rule (§3 rule 7)
}
```

**`MetricPercentiles`** (one per metric; `null` at R1; regime-nulled UNIFORMLY across metrics — rule C):
```jsonc
{
  "p50": { /* PercentileResult */ },
  "p75": { /* PercentileResult */ },   // R2 only; null/absent at R3
  "p90": { /* PercentileResult */ },   // R2 only; null/absent at R3
  "p95": { /* PercentileResult */ },   // R2 only; null/absent at R3
  "p99": { /* PercentileResult — confidence ALWAYS "indicative_low_confidence" */ }  // R2 optional; null/absent at R3
}
```
**`PercentileResult`** (one per (metric, percentile)):
```jsonc
{
  "value": 13.1,                       // units per PARENT metric (irr_pct→%, npv_yuan→¥, lcoe→¥/MWh, payback→yr)
  "confidence": "sound",               // "sound" | "indicative_low_confidence" — PERCENTILE-level (rule A): EQUAL across ALL metrics at the same q; R3 p50 + R2 p99 ALWAYS indicative
  "bootstrap_ci": { "lo": 1429000.0, "hi": 1673000.0 }  // NPV-ONLY (rule B): present (R2) ONLY in the npv_yuan metric's nodes; null/absent for irr/mirr/lcoe/payback AND everywhere at R3
}
```

**Metric set (canonical, finance-expert ruling):** the **5 DISTRIBUTIONAL metrics** carry per-percentile `MetricPercentiles` — `{npv_yuan, irr_pct, mirr_pct, lcoe_yuan_per_mwh, payback_discounted_yr}`. The **debt metrics `equity_irr_pct` + `min_dscr` are SCALAR** (engine emits `float` means, `engine.py:679-680`, NOT distributional) and live in `debt_metrics`, debt-gated — NOT in the per-percentile set. (NO `lcos`; single discounted payback; supersedes the earlier percentile-major draft's `lcos`/two-payback fields + the mistaken per-percentile `equity_irr_pct`.)

---

## 3. Binding semantics rules (finance-expert-owned acceptance criteria)

1. **`sample_kind` ∈ {"bootstrap","empirical"}** — the wire value. "synthetic"/"synthetic (block-bootstrap)" is a UI display label only, never the field value. (Enforces the #133 LOCK.)
2. **Regime is DERIVED by the producer** from `(distribution_valid, sample_kind)` — `!distribution_valid→R1; bootstrap→R2; empirical→R3` — and must agree with the nullability below. Serving never trusts a caller-supplied regime.
3. **Regime nullability (exhaustive; metric-major):** R1 → ALL 5 per-metric `MetricPercentiles` (`npv_yuan`/`irr_pct`/`mirr_pct`/`lcoe_yuan_per_mwh`/`payback_discounted_yr`) = `null` AND `downside_risk=null` AND the scalar `debt_metrics` (`equity_irr_pct`/`min_dscr`) null (also debt-gated); only `single_trajectory` carries values. R2 → every metric's p50/p75/p90/p95 present, p99 optional; downside full incl. `cvar5_yuan`; `best_of_n_npv_yuan=null`. R3 → every metric's p50 only (p75/p90/p95/p99 null), `cvar5_yuan=null`, `best_of_n_npv_yuan` present, `p_irr_below_hurdle` present. (Presence is UNIFORM across metrics — rule 11.)
4. **R3 confidence is forced:** every R3 percentile (only p50) carries `confidence="indicative_low_confidence"` — never "sound". Any R2 p99 likewise indicative. The consumer must NOT render an `indicative_low_confidence` value as a bare/bold headline (§13.10c).
5. **Units (pinned; folds #134 INV-CE-04/16):** IRR/MIRR/equity_irr = **percent ×100**; `min_dscr` = **bare ratio** (not ×100); `p_npv_neg`/`p_irr_below_hurdle` = **probability ∈[0,1]** (not ×100); NPV/drawdown/CF = **¥**; LCOE/LCOS = **¥/MWh**; payback = **years**; `*_year` = **1-indexed int**.
6. **`p_irr_below_hurdle` is POPULATED at R2 AND R3** (empirical frequency `#{IRR_m<hurdle}/M`; does NOT collapse at M≈10). Null only at R1 (block absent). [The #132 bug; #134 had it right.]
7. **View-II / any `*_delta` field = percentile OF the per-draw CRN differences, NEVER a difference of percentiles** (Vector 5 / D41): `npv_p50_delta_yuan = P50({NPV(π)_m − NPV(baseline)_m})`, CRN-paired — NOT `P50(π) − P50(baseline)`. Valid only when both legs share draws; `irr` deltas in percentage POINTS. When v1.1.0 ships only a P50 delta, the per-draw basis is documented explicitly.
8. **M≈10 honesty (R3):** `p_npv_neg`/`p_irr_below_hurdle` have resolution 1/M (0.1 at M=10). Wire value stays the decimal frequency; the consumer SHOULD surface the count ("2 of 10 years") rather than a false-precision "20.0%". (Display guidance, not a wire field.)
9. **`confidence` is PERCENTILE-level, NOT per-metric (rule A — finance-expert, from `engine.py:_compute_percentile_row`):** the engine sets ONE `confidence` per percentile row; metric-major replicates it under each metric, and it MUST be **EQUAL across all metrics at the same percentile q**. `irr_pct.p50.confidence != npv_yuan.p50.confidence` is incoherent (a state the engine cannot produce) → **reject**.
10. **`bootstrap_ci` is NPV-ONLY (rule B — finance-expert):** the engine computes the bootstrap CI on the NPV array only — no IRR/MIRR/LCOE/payback CI exists. `bootstrap_ci` is present (R2) **ONLY in `npv_yuan`'s** percentile nodes; `null`/absent for every other metric and everywhere at R3. **Never fabricate per-metric CIs** → reject a non-null `bootstrap_ci` on any non-NPV metric.
11. **Percentile-presence is UNIFORM across metrics (rule C — finance-expert):** the engine emits all metrics together per percentile row, so the non-null percentile set is regime-driven and **IDENTICAL for every metric** — you cannot have `irr_pct.p90` present while `npv_yuan.p90` is null. → **reject any cross-metric presence mismatch.**

**Backend-correctness invariants preserved in the nested envelope (backend-reviewer, from #134; binding field-semantics, NOT a one-time reshape note):** the reshape MUST retain —
- **IRR / MIRR / equity_irr = pct (×100)** of the engine decimal (rule 5).
- **`min_dscr` = bare ratio (NOT ×100)**, with the **`min_dscr < 10` realism guard** (a value ≥ 10 indicates a ×100 unit error → reject).
- **`p_irr_below_hurdle` = empirical frequency populated at R2 AND R3** (rule 6) — NOT a tail statistic, NOT ×100.
- **debt-gating:** `equity_irr_pct` + `min_dscr` (the `debt_metrics` block) are `null` when `debt_toggle=false`.
- **closed allow-set (response wire):** no field outside this schema appears on the wire (test #10).

(Scope note: the **request-side** `FinanceConfigRequest` closed allow-set backend-reviewer also flagged is a *separate* concern — that's the `/api/finance/compare` REQUEST shape, governed by the LOCKED `config_artifact_schema` `finance_overrides` allow-set (#133) + `FinanceConfig` (`finance_engine.md`), not by this RESULT-summary contract. Same single-source spirit, different shape; flagged for the request-side contract, out of scope here.)

---

## 4. Versioning + single-source / default-deny

- **Single-source (D45):** any change to this shape is a change HERE; #132 + #134 re-reference. A producer or consumer redefining `FinanceResultSummary` locally is a review-fail.
- **Default-deny forward note (finance-expert):** a new `PercentileResult`/`MetricPercentiles`/`downside_risk` field (or a new top-level metric) is **absent from the wire summary until explicitly added here** (a superseding bump, finance-expert-owned) — keeps serving/frontend from silently leaking unvetted engine fields.
- **Versioning:** additive optional field = **minor** (e.g. v1.2.0); field removal/rename/retype, regime-nullability change, or units change = **major** → superseding DECISION + re-LOCK + both-reviewer re-review. semver in `schema_version`.

---

## 5. Test cases (reviewer-gated; `# reviewer:` marks reviewer additions)

1. **Round-trip:** a valid R2 summary serializes/deserializes byte-stable; all blocks present.
2. **`sample_kind` enum (≡ #133 LOCK):** `"synthetic"` (or any non-`{bootstrap,empirical}`) at `provenance.sample_kind` → **reject** (the #134 source bug). Accept `bootstrap`/`empirical`.
3. **Regime derivation:** producer sets `regime` from `(distribution_valid, sample_kind)` per rule 2; a caller-supplied `regime` disagreeing with the derivation → reject (regime is producer-derived, not trusted).
4. **R1 nullability (metric-major):** `distribution_valid=false` → ALL per-metric `MetricPercentiles` = null AND `downside_risk=null`; only `single_trajectory` populated; `point_npv_yuan` labeled "NPV (single scenario)", never P50.
5. **R2 nullability:** EVERY metric's p50/p75/p90/p95 present, p99 optional (if present → `confidence="indicative_low_confidence"`); `downside_risk` full incl. `cvar5_yuan`; `best_of_n_npv_yuan=null`.
6. **R3 nullability + forced confidence:** EVERY metric's p50 present with `confidence="indicative_low_confidence"` (NEVER "sound"); p75/p90/p95/p99=null for every metric; `cvar5_yuan=null`; `best_of_n_npv_yuan` present; **`p_irr_below_hurdle` PRESENT** (rule 6 — the #132 bug); `bootstrap_ci=null` in `npv_yuan.p50` (no R3 CI).
7. **Units (rule 5):** hand-checked — engine IRR 0.131 → `irr_pct=13.1`; `min_dscr` stays 1.836 (NOT 183.6); `p_npv_neg=0.04` (NOT 4.0); a value violating any unit → reject. **`min_dscr < 10` realism canary (backend-reviewer / INV-CE-16):** an explicit standalone assert — `min_dscr ≥ 10` is implausible (`> 100` = definite ×100 bug) → reject; sharper than the "not 183.6" check.
8. **Debt-gating:** `debt_toggle=false` → `debt_metrics=null`; true → `{equity_irr_pct (×100), min_dscr (ratio)}` present.
9. **View-II per-draw-diff (rule 7 / D41):** `view_ii_delta` present only on the View-II summary (null on View-I); its value = percentile OF the per-draw CRN differences, NOT diff-of-percentiles. **P50-diverging counter-example (finance-expert; the median must actually bite — a symmetric anti-correlated case agrees at P50, so it can't be the test):** `S=[0,10,20,30,40]` (median 20); per-draw CRN diff `d=L−S=[+100,−5,−5,−5,−5]` (median **−5**); `L=S+d=[100,5,15,25,35]` (median 25). Then **diff-of-percentiles = P50(L)−P50(S) = 25−20 = +5 (WRONG)** vs **per-draw P50({L−S}) = −5 (CORRECT)** — **opposite signs**, so diff-of-percentiles can *invert the sign* of the incremental verdict, not just blur magnitude. Apply the locked exceedance estimator to both sides; the sign-divergence is estimator-robust. (v1.1.0 ships only a P50 `view_ii_delta`, so the test must bite at the median.)
10. **Closed allow-set:** a field outside this schema on the wire → reject (default-deny, §4).
11. **# reviewer (backend): correctness-invariant preservation** — assert the #134 backend fixes survive the nested envelope (IRR ×100, min_dscr ratio, p_irr@R2+R3-frequency, debt-gating, closed allow-set).
12. **# reviewer (frontend): consumer honesty** — `indicative_low_confidence` percentiles + R1 `single_trajectory` are not rendered as bare/bold headlines (§13.10c); R3 surfaces "k of N" not false-precision %.
13. **Confidence percentile-level (rule 9/A):** at a given percentile q, `confidence` is EQUAL across all metrics (`irr_pct.p50.confidence == npv_yuan.p50.confidence == mirr_pct.p50.confidence == …`); a fixture with mismatched per-metric confidence at the same q → **reject**.
14. **bootstrap_ci NPV-only (rule 10/B):** at R2, `npv_yuan.{p50..p95}.bootstrap_ci` is present `{lo,hi}`; `irr_pct`/`mirr_pct`/`lcoe_yuan_per_mwh`/`payback_discounted_yr` nodes have `bootstrap_ci=null` (or absent); a non-null CI on any non-NPV metric → **reject**. At R3 all `bootstrap_ci=null`.
15. **Percentile-presence uniform (rule 11/C):** the non-null percentile set is identical across metrics; a fixture with `irr_pct.p90` present but `npv_yuan.p90=null` (or any cross-metric presence mismatch) → **reject**.

---

## 6. Out of scope
- The in-process `FinanceResult` dataclass (lives in `finance_engine.md`, the engine output).
- Display labels (e.g. "synthetic (block-bootstrap)") — UI concern, never wire field values.
- The per-draw cash-flow arrays / full ensemble (referenced/derived, not in the summary).
