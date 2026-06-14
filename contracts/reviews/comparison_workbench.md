# Review record — `comparison_workbench` (PR #132)

**Reviewer:** frontend-reviewer · **Feature:** `contracts/frontend/comparison_workbench.md` · **Branch:** `feat/frontend-comparison-workbench`

## Round 1 — `49d0158` — REQUEST_CHANGES (2026-06-14) — contract + tests gate (pre-implementation)

Reviewed the v1.0.0-draft contract + the ~70-case suite (14 describe blocks) against D42/D41/D39
and the LOCKED telemetry schema. **This is a strong, well-structured contract** — the two-mode
discipline, regime suppression (R1/R2/R3 exact strings), baseline re-designation, store invariants,
sizing-sweep clamps, and the naming/isolation guards are all well-covered, and the engineer pre-marked
several good defensive cases `// reviewer:` (T-REGIME-4, T-STORE-8, §13, §14). Three issues block the
gate — all are data-correctness / internal-consistency, exactly what this gate exists to catch.

### Blockers

- **B1 — §7.3 contradicts Q5 (mixed-regime rule), and the min-regime resolution is unnamed/untested.**
  §7.3 (line 632): *"the entire table uses the MINIMUM regime."* Q5 (line 695) proposes the **opposite**:
  *"minimum regime for the shared Downside Risk section; per-column regime for the Upside section."* The
  contract contradicts itself, and `T-MIXED-1` pins §7.3 (whole-table-min) via a comment "caller resolves
  minimum regime" — so the resolution logic isn't a named, tested function (unlike `deriveRegime`).
  **Decision (my answer to your Q2):** whole-table-minimum (§7.3) is correct — a delta cell is
  baseline-relative, so you **cannot** render "Δ P90 NPV" when the baseline's P90 is suppressed; a
  per-column-Upside split (Q5) orphans every delta column. **Fix:** (a) delete/rewrite Q5 to "RESOLVED:
  whole-table-minimum (deltas are undefined against suppressed baseline cells)"; (b) expose a named pure
  function, e.g. `resolveComparisonRegime(variants): FinanceRegime` (min over each variant's regime,
  R1<R3<R2 severity), mirroring `deriveRegime`, and pin it with tests (R2+R1→R1, R2+R3→R3, R3+R1→R1,
  all-R2→R2). Needs finance-expert sign-off (delta-accounting, D42) → SC4.

- **B2 — regime is dual-sourced: `FinanceResultSummary.regime` (a field) vs `deriveRegime()` (a function),
  and the summary can't even feed `deriveRegime`.** §2.2 carries `regime` + `sample_kind` but **not**
  `distribution_valid`, so `deriveRegime(distribution_valid, sample_kind)` cannot be called from a
  `FinanceResultSummary`. Two sources of the same fact can drift (D42(5): "single source of truth =
  backend field; never invents a regime from count"). **Decision (my answer to your Q1):** read the
  backend field — do **not** recompute from M. **Fix (pick one, state it in the contract):** (a) make
  `FinanceResultSummary.regime` authoritative (UI reads it directly), and document `deriveRegime()` as the
  mapping applied to the **raw** `FinanceResult`/`PolicyEnsemble` payload (which carries
  `distribution_valid` + `sample_kind`) — i.e. it's the backend/adapter mapping, not re-run on the summary;
  OR (b) drop the precomputed `regime` from the summary, add `distribution_valid`, and always derive via
  `deriveRegime`. Either removes the dual source. (a) matches D42(5) most directly.

- **B3 — per-metric "direction of good" + delta coloring is unspecified; only higher-is-better metrics are
  tested.** §7 pins deltas for IRR (higher-better, `+0.5 pp`) and Worst NPV (higher-better, `+¥16M`,
  T-DELTA-3 "less loss is better → positive=green"). But the table also shows **lower-is-better** metrics:
  `lcoe_yuan_per_mwh`, `payback_p50_yr`, `p_npv_negative_pct`, `p_irr_below_hurdle_pct`, `max_drawdown_yuan`.
  For these, `variant − baseline` is **negative when better**, so a naive "positive=green" rule **mis-colors
  them** (e.g. variant LCOE 300 vs baseline 312 → −¥12/MWh is an *improvement* but would render red). A
  wrong delta color on a finance comparison is a critical bug (prime directive). **Fix:** add a §7.x table
  of direction-of-good per metric — higher-better: `irr/mirr/npv_p50/npv_p90/worst_npv/best_npv/
  worst_year_cashflow/cvar_5pct`; lower-better: `lcoe/payback/p_npv_negative/p_irr_below_hurdle/max_drawdown`
  — and state the coloring rule (good=green regardless of arithmetic sign; show the signed value with its
  natural sign + a good/bad color driven by direction-of-good). I will then add reviewer tests pinning at
  least LCOE (lower-better) and P(NPV<0) (lower-better) delta sign + good/bad treatment.

### Answers to your 4 questions
1. **deriveRegime inputs:** correct — read `distribution_valid` + `sample_kind` from the backend; do NOT
   check M directly (D42(5)). But resolve B2 (the summary doesn't carry `distribution_valid`).
2. **Mixed-regime rule:** whole-table-minimum (§7.3) — see B1. Close Q5.
3. **SC3/SC4 — block or standing?** Standing conditions (do NOT block this gate), with B1–B3 fixed first.
   SC3 (dashboard charts, §5 `[PENDING]`) and SC4 (finance-expert regime confirmation) are cross-area
   producer/consumer boundaries; the tests stub the charts (DV-5) and the regime DISPLAY is frontend's to
   implement against the spec. Same pattern as stage-1 §5.1 / stage-2 SC1. They must resolve **before
   implementation**, not before the contract+tests lock.
4. **Edge cases to add** (I'll add on re-review, marked `// reviewer:`, once B1/B3 spec the direction):
   - lower-is-better delta sign + coloring: LCOE (¥/MWh), P(NPV<0) (%), payback (yr) — **B3**.
   - `resolveComparisonRegime(variants)` unit tests (R2+R1→R1, R2+R3→R3, R3+R1→R1, all-R2→R2) — **B1**.
   - mixed-regime multi-variant: variant A's **delta** cells are suppressed `"—"`, not just the banner
     (§7.3 "deltas on suppressed cells: also suppressed").
   - LCOE level shown with unit `¥/MWh` (not `¥/kWh`) in the table (prime-directive units guard).
   - delta `pp` vs `%`: rate deltas use `pp` (T-DELTA-2 ✓); confirm levels use `%` — add a guard that an
     IRR *level* shows `%` and an IRR *delta* shows `pp` (avoid the classic pp/% confusion).

### Standing conditions (carried to implementation; NOT blocking the gate)
- **SC1** — serving config-library contract (`GET/POST /api/configs`, `/configs/:id/fork`) — serving-engineer.
- **SC2** — serving compare contract (`/api/compare/plan|run|run/:id/status|finance|sizing-sweep`) —
  serving-engineer. The §6 hook body shapes are the frontend's proposal; reconcile before impl (D37 pattern).
- **SC3** — dashboard-engineer confirms `SurfaceChartProps` + `NpvFanChartProps` (§5 `[PENDING]`); tests
  stub charts until then.
- **SC4** — finance-expert confirms the §7.3 R1/R2/R3 suppression rules + R3 partial-downside field set
  (which `FinanceResultSummary` fields show/suppress) per D39, and signs off the B1 mixed-regime rule.

### Verified-good (no action)
deriveRegime all-3-regimes + naming axis (§1); mode selector + `aria-pressed` (§2); scenario lock bar (§3);
tier chips (§4); R1/R2/R3 suppression exact strings + P50-always-shown + worst-year-always-shown + R3
partial downside (§5); delta baseline-absolute / variant-delta / re-designation-flips (§7, higher-better
metrics); store invariants — exactly-one-baseline, first-added, designate, remove-promotes, compare_designs
price-path lock (§8, incl. T-STORE-8); sizing sweep count/progress/clamp[2,20]/R1-banner/point→variant (§9);
modal (§10); config card (§11); per-config downside-first + R1 suppression (§12); naming discipline (§13);
batch-only isolation — no telemetry fields (§14).

**Verdict: REQUEST_CHANGES.** B1 (mixed-regime §7.3/Q5 + named resolver), B2 (regime dual-source), B3
(per-metric direction-of-good + delta coloring) must be fixed in the contract; then I add the reviewer
edge-case tests and re-gate. SC1–SC4 carry to implementation. Strong contract overall — these are
tighten-the-data-contract fixes, not a redesign.
