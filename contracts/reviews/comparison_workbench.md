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

## Round 2 — `0a47d24` (v1.1.0-draft) — REQUEST_CHANGES (2026-06-14)

Re-reviewed the contract + suite (now 933 / 1721 lines). **Excellent progress** — the finance-expert
corrections + new sections are well-built: `PercentileResult.confidence` (sound|indicative_low_confidence)
with a clean `data-confidence`/`data-headline` rendering contract (§15, T-CONF-1..4); `SingleTrajectoryResult`
(R1 4-field, "NPV (single scenario)" label); `DownsideRiskResult` (R3 partial — p_irr_below_hurdle present,
cvar5 null); restructured `FinanceResultSummary` (provenance + per-metric `MetricPercentiles`); new §16
ConfigDiffPanel (carries `unit` ✓), §17 FinanceParamPanel instant-tier, §18 comment thread; corrected
T-R1-4 / T-R3-7. Canonical `sample_kind {bootstrap|empirical}` applied throughout (matches the rl-architect
#133 ruling). Of the Round-1 blockers:

- **B2 — RESOLVED.** `FinanceResultSummary.provenance` now carries `distribution_valid` + `sample_kind`;
  `deriveRegime(distribution_valid, sample_kind)` is canonical (bootstrap→R2, empirical→R3). *Minor nit
  (should-fix, non-blocking):* a top-level `regime` field still coexists with `deriveRegime(provenance)` —
  add one line naming the single read-path (recommend: UI derives via `deriveRegime(provenance.…)`; the
  top-level `regime` is a backend denorm not read by table components) to foreclose drift.

- **B1 — PARTIAL (still blocks).** §7.3 body (line 845) now correctly states "table uses MINIMUM regime."
  But **Q5 (line 925) still contradicts it** — "minimum-regime for shared *sections*" + re-asks the
  per-column-Upside variant. And there is still **no named `resolveComparisonRegime`** — T-MIXED-1 passes
  `regime="R1"` with the comment "caller resolves," so the min-regime logic (R2+R1→R1) is untested. Fix:
  (a) delete the contradictory "shared sections" phrasing — Q5 → RESOLVED: whole-table-minimum (deltas are
  undefined against suppressed baseline cells; this is a frontend data-integrity call, finance-expert
  confirms only the downside accounting); (b) export `resolveComparisonRegime(variants): FinanceRegime`
  (severity R1 < R3 < R2 → returns the min) and I add unit tests (R2+R1→R1, R2+R3→R3, R3+R1→R1, all-R2→R2).

- **B3 — PARTIAL (still blocks).** §7.4 now encodes direction-of-good for THREE metrics via the
  "winner per metric" highlight (highest IRR, lowest LCOE, lowest p_npv_neg). But: (i) it is **not a
  complete per-metric table** — MIRR, NPV, payback, max_drawdown, worst_case_npv, cvar5, worst_year_cf
  direction is unspecified; (ii) the **delta-cell coloring** rule (distinct from the winner ★) is still
  unspecified — e.g. an LCOE delta of −¥12/MWh is an *improvement* but no rule says it renders good/green;
  (iii) §7 delta tests still only cover higher-better (T-DELTA-1..4: IRR, Worst NPV). Fix: add a §7.x
  **direction-of-good table for every displayed metric** (higher-better: irr/mirr/npv/worst_case_npv/
  best_of_n_npv/worst_year_cf/cvar5; lower-better: lcoe/payback/p_npv_neg/p_irr_below_hurdle/max_drawdown)
  and state that **both** the winner-★ AND the delta-cell color derive from it (recommend a testable
  encoding, e.g. `data-delta-direction="good"|"bad"|"neutral"` on the delta cell, mirroring §15's
  `data-confidence`). I then add reviewer tests pinning LCOE + P(NPV<0) delta sign + good/bad direction.

### Answers to the Round-2 open questions
- **Q5 (mixed-regime):** whole-table-minimum — decisive (B1). Close Q5; delete "shared sections."
- **Q6 (R3 `p_irr_below_hurdle` confidence):** finance-expert's call (finance honesty, not frontend). My
  read: it's a frequency count, NOT a percentile, so the §15 per-percentile confidence rule does not apply;
  the engineer's "not indicative-tagged" assumption is reasonable — but finance-expert confirms (SC4-adjacent).
- **SC3 (dashboard charts):** standing condition — **do NOT hold the gate**; approve-with-[PENDING] (charts
  stubbed per DV-5). Resolve before chart integration.
- **SC5 (recompute-finance endpoint):** does not block the contract gate; standing condition before the
  finance-slider implementation.

### Verified-good this round
§15 confidence rendering (data-confidence/data-headline, P99-always-indicative, R3-P50-indicative);
§16 ConfigDiffPanel (differing-first, common-collapsed, instant ⚡, units carried); §17 FinanceParamPanel
(sliders, instant label, scope); corrected R1 (no IRR, "NPV (single scenario)") + R3 (p_irr_below_hurdle
shown as frequency); canonical sample_kind enum.

**Verdict: REQUEST_CHANGES (Round 2).** B2 resolved; **B1** (reconcile Q5↔§7.3 + name+test
`resolveComparisonRegime`) and **B3** (complete direction-of-good table + delta-coloring rule + lower-better
delta tests) remain. Strongly converged — both are bounded contract edits; I add the held tests on the next
revision. SC1/SC2/SC3/SC5 carry to implementation; SC4 resolved.

## Round 3 — `a745cc2` (v1.2.0-draft) + reviewer test — APPROVE (2026-06-14)

All three blockers resolved and code-verified:

- **B1 ✓** — `resolveComparisonRegime(variants): FinanceRegime` added (§2.5): severity `{R1:0, R3:1, R2:2}`,
  returns the min over `v.finance_result?.regime`, default R2 when empty/no-result. Reads the backend
  `regime` field (consistent with B2 — not deriveRegime). §7.3 + the §2.5 docstring state whole-table-min,
  per-column **rejected**, and mixed-regime **delta cells suppressed** (not just the banner). **Q5 CLOSED.**
  Tests T-RESOLVE-1..6 (all-R2→R2, R1+R2→R1, R3+R2→R3, R1+R3→R1, empty/null→R2, single-string return) +
  T-DELTA-7 (IRR delta suppressed when table regime=R1). Correct.

- **B2 ✓** — `FinanceResultSummary.regime` docstring: "Read DIRECTLY from the backend response — NEVER
  recompute client-side"; `deriveRegime()` docstring: "use ONLY when you do not yet have a
  FinanceResultSummary (raw PolicyEnsemble)." Single source documented; the prior dual-source nit closed.

- **B3 ✓** — §7.8 added: a **complete per-metric direction-of-good table** (all 11 metrics — higher-better:
  IRR/MIRR/NPV/CVaR/WorstNPV/MaxDD/BestOfN; lower-better: LCOE/payback/P(NPV<0)/P(IRR<hurdle)), with display
  units, `Δ = variant − baseline`, and the coloring rule ("green/red derived from direction + sign, NOT sign
  alone"). Unit guards: IRR/MIRR delta in **pp**, P-metric delta in **pp-from-fraction**, LCOE in **¥/MWh**
  (the ¥/kWh ×1000 trap). Tests T-DELTA-5 (LCOE lower-better → negative Δ = good), T-DELTA-6 (¥/MWh not
  ¥/kWh; `0.312` must not appear).

**Finance-expert precision (incorporated + tested):** `single_trajectory` present at all M (HEADLINE at R1);
`best_of_n_npv_yuan` R3-only — gate by regime not truthiness (T-R3-9); `cvar5_yuan` R2-only, null at R1+R3
(T-R3-10); R3 frequencies as "X of N years" not smooth % (T-R3-8, `X = round(p·m_draws)`). **SC5 RESOLVED:**
`useFinanceRecompute` → `POST /api/compare/finance` `(eval_result_id, finance_config)`, 404
`EVAL_RESULT_NOT_FOUND` + re-run CTA. Canonical `sample_kind {bootstrap|empirical}` (per #133) applied.

### Reviewer test added this round (`// reviewer:`)
- **T-DELTA-8** — P(NPV<0) delta: lower-better + shown in **pp** (fraction→pp), `−0.08` must NOT appear,
  cell `data-delta-direction="good"`. Covers the lower-better *probability* category (T-DELTA-5 covered the
  lower-better *price* category LCOE) and the §7.8 line-967 fraction→pp unit guard. esbuild parse-clean.

### Minor should-fix (non-blocking — fold into implementation)
- **Attribute-name alignment:** §7.8 (line 962) specifies `data-direction="higher-better"|"lower-better"`
  (the metric property), but T-DELTA-5/T-DELTA-8 assert `data-delta-direction="good"` (the derived verdict).
  Both are reasonable (metric property vs computed cell verdict) — but the contract should document BOTH
  attributes explicitly so the implementer adds the right ones (recommend: `data-direction` = metric
  property; `data-delta-direction = "good"|"bad"|"neutral"` = derived from direction + Δ sign). The tests
  pin `data-delta-direction`; §7.8 should name it.

### Standing conditions for implementation (NOT blocking the contract+tests gate)
- **SC1** — serving config-library contract (`GET/POST /api/configs`, `/configs/:id/fork`, `/comments`).
- **SC2 — serving compare endpoints (PR #134).** *Active cross-area item:* #134's `FinanceResultSummary`
  §2.4 is currently the **superseded flat shape** (`sample_kind:"synthetic"` — violates the #133 LOCK; no
  per-percentile `confidence`; `point_irr_pct` vs the R1 correction). I posted REQUEST_CHANGES on #134 and
  **escalated the canonical-shape direction to rl-architect + finance-expert.** #132's v1.2.0 nested shape is
  the finance-expert-aligned + #133-aligned target; #134 must serialize TO it. **Implementation of #132 is
  blocked until #134 conforms.** (If the ruling unexpectedly reverses to flat, §2.4/§2.5/§7.8 reopen — but
  that would require relaxing #133 + dropping finance-expert's confidence contract, so I expect it to confirm
  the nested shape.)
- **SC3** — dashboard-engineer confirms `SurfaceChartProps` + `NpvFanChartProps` (§5 `[PENDING]`; charts
  stubbed in tests per DV-5).
- **SC4 RESOLVED** (finance-expert regime corrections applied). **SC5 RESOLVED** (recompute endpoint).

### Approved suite = developer cases (§1–§18, incl. T-RESOLVE-1..6, T-DELTA-1..7, T-R3-8/9/10, §15 confidence,
§16 diff, §17 finance, §18 comments) + the reviewer case **T-DELTA-8**.

**Verdict: APPROVE** (contract + tests gate). B1/B2/B3 resolved + code-verified; finance-expert precision +
SC4/SC5 in; one non-blocking attribute-name nit; SC1/SC2/SC3 carry to implementation (SC2 = the #134
nested-shape convergence I escalated). Strong contract — implementation may proceed once SC1/SC2/SC3 clear.

## Round 4 — `25f54e0` (v1.3.0-draft) — REQUEST_CHANGES (2026-06-14) — D45 reference-swap conformance

The D45 ruling locked `contracts/shared/finance_result_summary.md` v1.1.0 **metric-major** (the recommended
outcome — both #132 + #134 had converged on it). Round 4 swaps #132's inline `FinanceResultSummary` for a
reference to the locked shared contract. **Mostly clean — one bounded fixture non-conformance blocks the
SC4/D45 gate.**

**Verified-good:**
- **§2.4 reference block ✓** — inline type defs removed; references the locked `finance_result_summary.md`
  v1.1.0; no local redefinition of `PercentileResult`/`MetricPercentiles`/`SingleTrajectoryResult`/
  `DownsideRiskResult`/`DebtMetrics`/`FinanceResultSummary`. Field-name deltas absorbed
  (`payback_yr`→`payback_discounted_yr`, `debt_metrics`, `view_ii_delta`, `schema_version`).
- **§2.3 ✓** — `FinanceParamSet` stays frontend-owned; #134 §2.3 maps it (no redefinition). Matches the D45 note.
- **§7.8 ✓** — Payback row → "Payback (discounted)"; new rows Equity IRR (`debt_metrics.equity_irr_pct`,
  pp, higher-better) + Min DSCR (`debt_metrics.min_dscr`, × ratio, higher-better); `data-direction` lists
  updated. Correct per the locked scalar `debt_metrics`.
- **R1 fixture ✓** — all 5 `MetricPercentiles` null, `single_trajectory` only, `downside_risk`/`debt_metrics`
  null. Conforms to #135 R1 nullability.
- **R3 fixture ✓** — UNIFORM `p50`-only across all 5 metrics, every p50 `indicative_low_confidence`
  (rule A + rule C satisfied), `best_of_n_npv_yuan` present, `p_irr_below_hurdle` present, `cvar5_yuan` null.

**Blocker (D45 conformance):**
- **BD45-1 — the R2 fixture violates the locked #135 rules C and B.** The locked schema's **rule C**
  (line ~116: "Percentile-presence is UNIFORM across metrics … reject any cross-metric presence mismatch")
  requires every metric at R2 to carry `p50/p75/p90/p95` (p99 optional). But `FINANCE_RESULT_R2` gives only
  `irr_pct` the full set; `npv_yuan` has just `{p50, p90}` and `mirr_pct`/`lcoe_yuan_per_mwh`/
  `payback_discounted_yr` only `{p50}` — a non-uniform shape the producer can never emit (rule-C reject).
  Also **rule B** (`bootstrap_ci` present at R2 ONLY in `npv_yuan`'s nodes): the R2 `npv_yuan` nodes carry no
  `bootstrap_ci`, so the fixture isn't a faithful R2 payload and doesn't exercise the NPV-only-CI rule. This
  was valid under #132's old self-defined shape (per-metric independent percentiles), but the D45 reference
  imposes #135's stricter invariants — and the "near-no-op" fixture update only renamed fields, it didn't
  make R2 rule-C-uniform. **Fix:** give all 5 R2 metrics `p50/p75/p90/p95` (uniform), add `bootstrap_ci` to
  `npv_yuan`'s R2 nodes (and NOT to the other metrics), keep one consistent `confidence` per percentile q
  across metrics (rule A). R1/R3 already conform; this is R2-only. (validate-telemetry: fixtures must be
  valid against the LOCKED schema — a non-conformant central fixture pins behavior against impossible data.)

**Verdict: REQUEST_CHANGES** — narrow: only the R2 fixture must be brought into #135 rule-C/rule-B
conformance (uniform p50/p75/p90/p95 across all 5 metrics + npv-only bootstrap_ci). The reference-swap,
§2.3, §7.8, and R1/R3 fixtures are all correct. SC1/SC2/SC3 standing conditions unchanged. Re-gate on the
fixture fix — should be the last round.
