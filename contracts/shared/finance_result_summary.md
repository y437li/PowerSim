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

  // ── Percentiles — null per regime ──
  //   R1: "percentiles": null  (whole block)
  //   R2: p50/p75/p90/p95 present (p99 optional, indicative-only)
  //   R3: p50 present (confidence ALWAYS "indicative_low_confidence"); p75/p90/p95/p99 = null
  "percentiles": {
    "p50": { /* PercentileSummary */ },
    "p75": { /* … */ }, "p90": { /* … */ }, "p95": { /* … */ },
    "p99": null
  },

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

  // ── Debt metrics — null when debt_toggle=false ──
  "debt_metrics": {
    "equity_irr_pct": 14.21,           // PERCENT (×100 of engine decimal) — INV-CE-04
    "min_dscr": 1.836                  // BARE RATIO (1.836 = 1.836×) — NOT ×100 — INV-CE-16
  },

  // ── View-II incremental — present ONLY on the View-II summary; null on View-I ──
  "view_ii_delta": null                // see per-draw-diff rule (§3 rule 7)
}
```

**`PercentileSummary`** (each percentile node):
```jsonc
{
  "npv_yuan": 1500000.0,
  "irr_pct": 13.1,                     // PERCENT (×100 of engine decimal 0.131)
  "mirr_pct": 12.2,                    // PERCENT
  "lcoe_yuan_per_mwh": 48.3,
  "lcos_yuan_per_mwh": 12.7,
  "payback_simple_yr": 7.2,
  "payback_disc_yr": 9.1,
  "bootstrap_ci_yuan": [1429000.0, 1673000.0],  // NPV-percentile CI (lower,upper) at ci_level; null at R3 (no bootstrap CI)
  "confidence": "sound"                // "sound" | "indicative_low_confidence" — R3 p50 ALWAYS indicative; R2 p99 (if present) ALWAYS indicative
}
```

---

## 3. Binding semantics rules (finance-expert-owned acceptance criteria)

1. **`sample_kind` ∈ {"bootstrap","empirical"}** — the wire value. "synthetic"/"synthetic (block-bootstrap)" is a UI display label only, never the field value. (Enforces the #133 LOCK.)
2. **Regime is DERIVED by the producer** from `(distribution_valid, sample_kind)` — `!distribution_valid→R1; bootstrap→R2; empirical→R3` — and must agree with the nullability below. Serving never trusts a caller-supplied regime.
3. **Regime nullability (exhaustive):** R1 → `percentiles=null`, `downside_risk=null`; only `single_trajectory` carries values. R2 → p50/p75/p90/p95 present, p99 optional; downside full incl. `cvar5_yuan`; `best_of_n_npv_yuan=null`. R3 → p50 only (others null), `cvar5_yuan=null`, `best_of_n_npv_yuan` present, `p_irr_below_hurdle` present.
4. **R3 confidence is forced:** every R3 percentile (only p50) carries `confidence="indicative_low_confidence"` — never "sound". Any R2 p99 likewise indicative. The consumer must NOT render an `indicative_low_confidence` value as a bare/bold headline (§13.10c).
5. **Units (pinned; folds #134 INV-CE-04/16):** IRR/MIRR/equity_irr = **percent ×100**; `min_dscr` = **bare ratio** (not ×100); `p_npv_neg`/`p_irr_below_hurdle` = **probability ∈[0,1]** (not ×100); NPV/drawdown/CF = **¥**; LCOE/LCOS = **¥/MWh**; payback = **years**; `*_year` = **1-indexed int**.
6. **`p_irr_below_hurdle` is POPULATED at R2 AND R3** (empirical frequency `#{IRR_m<hurdle}/M`; does NOT collapse at M≈10). Null only at R1 (block absent). [The #132 bug; #134 had it right.]
7. **View-II / any `*_delta` field = percentile OF the per-draw CRN differences, NEVER a difference of percentiles** (Vector 5 / D41): `npv_p50_delta_yuan = P50({NPV(π)_m − NPV(baseline)_m})`, CRN-paired — NOT `P50(π) − P50(baseline)`. Valid only when both legs share draws; `irr` deltas in percentage POINTS. When v1.1.0 ships only a P50 delta, the per-draw basis is documented explicitly.
8. **M≈10 honesty (R3):** `p_npv_neg`/`p_irr_below_hurdle` have resolution 1/M (0.1 at M=10). Wire value stays the decimal frequency; the consumer SHOULD surface the count ("2 of 10 years") rather than a false-precision "20.0%". (Display guidance, not a wire field.)

**Backend-correctness invariants preserved in the nested envelope (backend-reviewer, from #134; binding):** the reshape MUST retain — IRR ×100 (rule 5), `min_dscr` bare ratio (rule 5), `p_irr_below_hurdle` populated at R2+R3 (rule 6), debt-gating (`debt_metrics=null` when `debt_toggle=false`), and the closed allow-set (no field outside this schema on the wire). These are not lost in the producer reshape.

---

## 4. Versioning + single-source / default-deny

- **Single-source (D45):** any change to this shape is a change HERE; #132 + #134 re-reference. A producer or consumer redefining `FinanceResultSummary` locally is a review-fail.
- **Default-deny forward note (finance-expert):** a new `PercentileSummary`/`downside_risk` field is **absent from the wire summary until explicitly added here** (a superseding bump, finance-expert-owned) — keeps serving/frontend from silently leaking unvetted engine fields.
- **Versioning:** additive optional field = **minor** (e.g. v1.2.0); field removal/rename/retype, regime-nullability change, or units change = **major** → superseding DECISION + re-LOCK + both-reviewer re-review. semver in `schema_version`.

---

## 5. Test cases (reviewer-gated; `# reviewer:` marks reviewer additions)

1. **Round-trip:** a valid R2 summary serializes/deserializes byte-stable; all blocks present.
2. **`sample_kind` enum (≡ #133 LOCK):** `"synthetic"` (or any non-`{bootstrap,empirical}`) at `provenance.sample_kind` → **reject** (the #134 source bug). Accept `bootstrap`/`empirical`.
3. **Regime derivation:** producer sets `regime` from `(distribution_valid, sample_kind)` per rule 2; a caller-supplied `regime` disagreeing with the derivation → reject (regime is producer-derived, not trusted).
4. **R1 nullability:** `distribution_valid=false` → `percentiles=null` AND `downside_risk=null`; only `single_trajectory` populated; `point_npv_yuan` labeled "NPV (single scenario)", never P50.
5. **R2 nullability:** p50/p75/p90/p95 present, p99 optional (if present → `confidence="indicative_low_confidence"`); `downside_risk` full incl. `cvar5_yuan`; `best_of_n_npv_yuan=null`.
6. **R3 nullability + forced confidence:** p50 present with `confidence="indicative_low_confidence"` (NEVER "sound"); p75/p90/p95/p99=null; `cvar5_yuan=null`; `best_of_n_npv_yuan` present; **`p_irr_below_hurdle` PRESENT** (rule 6 — the #132 bug); `bootstrap_ci_yuan=null` in the p50 node.
7. **Units (rule 5):** hand-checked — engine IRR 0.131 → `irr_pct=13.1`; `min_dscr` stays 1.836 (NOT 183.6); `p_npv_neg=0.04` (NOT 4.0); a value violating any unit → reject.
8. **Debt-gating:** `debt_toggle=false` → `debt_metrics=null`; true → `{equity_irr_pct (×100), min_dscr (ratio)}` present.
9. **View-II per-draw-diff (rule 7 / D41):** `view_ii_delta` present only on the View-II summary (null on View-I); its value = percentile of per-draw CRN differences, NOT diff-of-percentiles (reuse finance-expert's anti-correlated counter-example: identical marginals, anti-correlated → diff-of-percentiles=0 but per-draw P50 delta ≠ 0).
10. **Closed allow-set:** a field outside this schema on the wire → reject (default-deny, §4).
11. **# reviewer (backend): correctness-invariant preservation** — assert the #134 backend fixes survive the nested envelope (IRR ×100, min_dscr ratio, p_irr@R2+R3-frequency, debt-gating, closed allow-set).
12. **# reviewer (frontend): consumer honesty** — `indicative_low_confidence` percentiles + R1 `single_trajectory` are not rendered as bare/bold headlines (§13.10c); R3 surfaces "k of N" not false-precision %.

---

## 6. Out of scope
- The in-process `FinanceResult` dataclass (lives in `finance_engine.md`, the engine output).
- Display labels (e.g. "synthetic (block-bootstrap)") — UI concern, never wire field values.
- The per-draw cash-flow arrays / full ensemble (referenced/derived, not in the summary).
