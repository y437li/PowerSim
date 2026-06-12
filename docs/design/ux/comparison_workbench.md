# Comparison Workbench — UX Design

> **Owner:** ui-designer · **Task:** #67
> **Status:** DRAFT v0.5 (2026-06-12) — M=1 honesty: suppress downside/P90 columns at v1 default (single scenario), M=1 banner above table
> **Gate:** USER reviews aesthetic direction before frontend contracts are written against this.
> **Inputs:** wizard_flow.md (sibling doc), master_plan_geo_finance.md §5, REBUILD_SPEC §3–§5
> **USER directive:** "有个地方可以多选,然后跑simulation根据算法看finance projection"
> **USER ruling (headless):** Workbench does NOT connect to the 3D simulator or live dashboard. No streaming, no 3D scene. Results are tables + charts. Think "analysis report", not "mission control."
> **rl-architect ruling (v1.1 spine amendment):** VARIANT-TIERING = stage-invalidation DAG applied to a variant set: (a) finance-assumption or cost-only-device-swap variants → re-slice cached cash flows, INSTANT; (b) dispatch-relevant diffs → vmapped batch eval; (c) no-compatible-policy → retrain required. UNIFIES `/api/finance/compare` (policy) + View II (battery-incremental) into one any-variant-vs-baseline DELTA framework. finance-expert OWNS delta-accounting correctness (baseline designation + NO-DOUBLE-COUNT). TWO EVAL MODES: observed (wizard ④/dashboard: telemetry + D24 pacing + 3D) vs batch (workbench: vmapped, OFF-WIRE #82 accumulators, no telemetry/pacing). Same env + accumulators, different surfaces. Workbench = batch mode only.
> **Area owners:** frontend (workbench UI) · serving (orchestration contract — name the 2 modes) · finance-expert (delta math) · rl-architect (variant-set tiering in v1.1 spine amendment)

---

## 1. Purpose and product story

The Comparison Workbench is a **first-class sibling view** to the wizard pipeline (route `/compare`). Where the wizard is the creation path — one operator building up one site's finance projection — the workbench is the **comparison path**: select a set of variants, run whatever simulations are needed, and see all results side-by-side.

```
 Wizard (/wizard)                         Workbench (/compare)
 ─────────────────────────────────────    ─────────────────────────────────────
  Config → Algo → Train → Eval → Finance  Variants × Run plan → Table + Charts
  (one site, end-to-end pipeline)         (multiple variants, analysis report)

  "Add to Comparison →" at Config/         entry points
  Eval/Finance stages ──────────────────────►
```

**Company demo story (USER's priority, task #68).** The workbench's primary demo is a **device-swap variant pair**:

- **Baseline**: Gansu site, traditional 945 MW substation grid connection (standard CAPEX), SAC-trained policy
- **Variant A**: same site, same policy, SST (solid-state transformer) grid connection (different CAPEX, potentially different grid-loss parameters)

Swapping the grid connection is a classic "what's the SST premium worth?" question. If the physics change (grid-loss parameters differ), the workbench detects a dispatch-relevant diff and queues a fast headless eval run. If it's a CAPEX-only change (same physics), it's an instant server-side finance recalculation. The user sees the IRR, NPV, and payback period side-by-side and can make the investment decision.

---

## 2. Variant model

A **variant** bundles three axes. Every variant specifies all three; the workbench computes the finance projection from them.

```
variant = {
  id:                string                  // workbench-local label ("Baseline", "A", "B", ...)
  is_baseline:       bool                    // one variant per workbench is the baseline
  site_config:       config_hash | null      // references a saved site config; null = "not set"
  policy:            policy_ref | null       // {run_id, step} from policy library, OR a baseline
                                             //   agent name, OR null = "needs training"
  eval_result:       eval_result_id | null   // a completed eval result from Stage ④ Eval Library,
                                             //   or null = "needs eval run"
  price_path:        price_path_name | null  // revenue-price trajectory to apply (e.g.
                                             //   "declining-real", "stress", "custom-2026-06");
                                             //   null = use workbench shared path (default).
                                             //   A scenario is identified by (variant × price_path).
                                             //   Per-variant override is set in the Variant Editor.
  finance_overrides: FinanceSnapshot         // a full snapshot of finance assumptions for this
                                             //   variant; can be shared or per-variant
}
```

**Scenario framing.** A **scenario** in the workbench is identified by the pair `(variant × price_path)`. Two variants running under different price paths are distinct scenarios — "Baseline × declining-real" and "Baseline × stress" are separate entries in the comparison. By default all variants share a single workbench-level price path (set in the shared controls); per-variant override is available in the Variant Editor for deliberate cross-path comparisons. Price-path changes are always instant client-side (re-multiply cached M cash-flow series, same as Finance Stage ⑤ §3.3).

**Baseline designation.** One variant (default: the first added) is the baseline. All other variants' metric columns show delta values against the baseline: `+2.1 pp IRR` (green), `−¥42M NPV` (red), `+0.8 yr payback` (amber). The baseline column shows absolute values only.

**DELTA framework — unified any-variant-vs-baseline** *(rl-architect v1.1 spine ruling)*. The workbench unifies the existing `/api/finance/compare` (policy-vs-policy) and View II (battery-incremental vs no-battery baseline) into one any-variant-vs-baseline delta framework. Every workbench result column is a delta against the designated baseline — not an isolated absolute projection. This removes two separate "compare" surfaces (the old policy compare endpoint and the View I/II toggle) and replaces them with a single general mechanism: pick a baseline, pick variants, delta everything.

**NO-DOUBLE-COUNT constraint** *(owned by finance-expert)*. When two or more variants share the same dispatch results (same policy + same eval result, differing only in CAPEX/OPEX or finance assumptions), the delta applies only to the cost/revenue side — the operational cash flows are re-used from the cached eval, not re-run. The finance expert must ensure that variants sharing a dispatch are delta-projected consistently: no variant's operating revenue is counted twice, and the baseline's operational contribution is not subtracted more than once across the variant set. The `POST /api/compare/plan` response will indicate which variants share a dispatch root so the UI can label shared-dispatch variant groups.

**Shared vs. per-variant assumptions.** The workbench has two modes:

| Mode | When to use | Behaviour |
|------|-------------|-----------|
| **Shared** (default) | Apples-to-apples comparison — same WACC/horizon for all | One assumption panel sets all variants; changes propagate immediately |
| **Per-variant** | Sensitivity across different assumption scenarios | Each variant row has its own `[✎ Assumptions]` toggle; the header shows a `⚠ Assumptions differ` notice |

Switching from Shared → Per-variant seeds each variant's snapshot from the current shared assumptions. Switching back asks: "Unify assumptions? (Resets per-variant overrides to shared.)"

---

## 3. Execution tier model

When the user clicks **[Run missing]**, the workbench determines what each variant needs. This is determined server-side: `POST /api/compare/plan` takes the variant list and returns an execution plan with a tier label per variant.

### The four tiers *(rl-architect v1.1 spine: (a)/(b)/(c) canonical labels)*

```
┌──────────┬────────────────────────────────────┬──────────────────┬───────────┐
│ Tier     │ What differs                       │ Duration         │ Visual    │
├──────────┼────────────────────────────────────┼──────────────────┼───────────┤
│ (a) 0    │ Finance assumptions only, OR        │ < 1 s            │ ⚡        │
│ Instant  │ cost-only device swap (e.g. SST     │ client-side      │           │
│          │ grid connection = CAPEX diff only)  │ re-slices cached │           │
│          │ — same policy + same eval result    │ cash flows       │           │
├──────────┼────────────────────────────────────┼──────────────────┼───────────┤
│ (a) 1    │ CAPEX/OPEX or tax/debt structure    │ ~1–5 s           │ ⚡        │
│ Fast     │ change (same eval result, different │ server-side      │           │
│          │ cost structure) — F1 dividend path  │ finance recalc   │           │
├──────────┼────────────────────────────────────┼──────────────────┼───────────┤
│ (b) 2    │ Dispatch-relevant config diff;      │ seconds–minutes  │ ▶         │
│ Eval     │ compatible policy exists →          │ vmapped batch    │           │
│          │ vmapped batch eval, batch mode only │ eval (batch mode)│           │
├──────────┼────────────────────────────────────┼──────────────────┼───────────┤
│ (c) 3    │ No compatible policy for this       │ N/A (manual)     │ ⚠         │
│ Retrain  │ config — §2.2 compat check fails   │                  │           │
└──────────┴────────────────────────────────────┴──────────────────┴───────────┘
```

**SST-vs-traditional = showcase path for (a).** The company demo (grid-SST vs traditional substation) is a cost-only-device-swap when the SST's physics parameters are identical (only CAPEX differs). This is deliberately the ⚡ Tier 0/1 instant path — the demo must snap to results without queuing an eval run. If the SST changes dispatch-relevant physics (e.g. different loss coefficients or PCC power limit), it becomes Tier (b) — batch eval queued.

**Dispatch-relevant config diff** means: any change that alters the observation space, action space, or physics parameters that affect optimal dispatch — e.g. different device count (changes obs_dim), different battery size or C-rate, different PCC limit, adding/removing a load type. A CAPEX-only change that doesn't affect physics is Tier (a) 0/1.

**Compatible policy** = the existing policy's `obs_dim` and `action_dim` match the new config's resolved dimensions (same check as Stage ④ compatibility check: `GET /api/eval/check-compat`).

**Tier (b) batch eval** uses the vmapped batch eval path from PR #82 (OFF-WIRE accumulators, no telemetry/pacing). The workbench never uses observed mode (telemetry + D24 pacing + 3D animation). See §7.

### Visual treatment per tier

```
 Tier 0/1 — ⚡ Instant / Fast:
   Status chip:  [ ⚡ Ready — instant ]  (blue chip, no action needed)

 Tier 2 — ▶ Eval needed:
   Status chip:  [ ▶ Eval needed (~2 min) ]  (amber chip)
   Action:       included in [Run missing ▶ N evals]

 Tier 3 — ⚠ Retrain required:
   Status chip:  [ ⚠ Retrain required ]  (red chip)
   Action:       [ → Open in Wizard / Train stage ]  (secondary link)
   Note:         Variant is greyed in the results table (shows "—" in each cell)
                 with tooltip: "No trained policy compatible with this config.
                 Go to Train stage to create one."

 Running (during eval):
   Status chip:  [ ⏳ Running... ]  (pulse animation)
   In table:     each cell for this variant shows a shimmer placeholder
```

---

## 4. Layout and wireframes

### 4.1 Overall page structure

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Wizard  ·  COMPARISON WORKBENCH                [+ New variant]  [Export ▾]│
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌── VARIANTS ─────────────────────────────────────────────────────────────┐ │
│  │                                                                         │ │
│  │  Label    Config / Policy                  Finance        Status        │ │
│  │  ─────────────────────────────────────────────────────────────────────  │ │
│  │  ★ Base   Gansu-v1 · SAC run-a1b2c3 ·     WACC 7.0%      ✓ Ready       │ │
│  │           best ckpt 2026-06-10             20 yr          (eval exists) │ │
│  │           [edit] [duplicate] [remove]                                   │ │
│  │                                                                         │ │
│  │  A        Gansu-v1 · SAC run-a1b2c3 ·     WACC 7.0%     ⚡ Instant     │ │
│  │  (SST)    best ckpt 2026-06-10             20 yr          CAPEX differs  │ │
│  │           (CAPEX override: SST +¥120M)    [edit] [dup]  [remove]        │ │
│  │                                                                         │ │
│  │  B        Gansu-SST · (no compatible      WACC 7.0%     ⚠ Retrain      │ │
│  │  (new     policy yet)                     20 yr          required       │ │
│  │   config) [edit] [dup] [remove]                          [→ Train ↗]    │ │
│  │                                                                         │ │
│  │  [+ Add variant]  ·  Shared: WACC 7.0% · 20yr [✎]  ·                    │ │
│  │  Price path: declining-real [✎ Edit path]                               │ │
│  │  [Run missing ▶  1 eval needed]                                         │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌── RESULTS ──────────────────────────────────────────────────────────────┐ │
│  │  [Table]  [NPV vs Rate]  [Per-variant detail]                           │ │
│  │                                                                         │ │
│  │  (active tab content — see §4.2/4.3/4.4)                                │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

Key layout decisions:
- **Variants section is always visible** — the user needs to see and manage variants while reading results.
- **"← Wizard" back-link** — top-left, always present. Navigates to wizard Stage ⑤ Finance (or stage selector if multiple active).
- **[Run missing]** button appears only when at least one Tier 2 variant exists; label counts: "Run missing ▶ 2 evals". No button if all variants are Tier 0/1 (results update automatically).
- **Export** produces a PDF/CSV with all variant assumptions and all result tables.

### 4.2 Results tab — Table (distribution-aware)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [Table ●]  [NPV vs Rate]  [Per-variant detail]                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SCENARIO SUMMARY  (scenario = price path × variant)                        │
│  WACC 7.0% · 20yr · View I · Merchant · M=50 · Price: declining-real        │
│  (or: "⚠ Price paths differ · Assumptions differ — see per-variant detail") │
│                                                                              │
│  ── UPSIDE ─────────────────────────────────────────────────────────────── │
│  ┌────────────┬─────────────────┬──────────────────────────────────────────┐ │
│  │ Metric     │ ★ Baseline      │ A (SST)                                  │ │
│  │            │ Gansu-v1        │ Gansu-v1 +SST                            │ │
│  │            │  P50    P90     │  P50    P90     ΔP50                     │ │
│  ├────────────┼─────────────────┼──────────────────────────────────────────┤ │
│  │ IRR        │  8.2%   7.6%    │  8.7%   8.1%   +0.5 pp                  │ │
│  │ NPV ¥M     │  ¥142   ¥118    │  ¥156   ¥130   +¥14M                    │ │
│  │ MIRR       │  7.1%   6.7%    │  7.4%   6.9%   +0.3 pp                  │ │
│  │ LCOE ¥/MWh │   312    319    │   311    318    −1                       │ │
│  │ Payback yr │   8.3    9.0    │   7.9    8.5   −0.4                      │ │
│  └────────────┴─────────────────┴──────────────────────────────────────────┘ │
│                                                                              │
│  ── DOWNSIDE RISK ──────────────────────────────────────────────────────── │
│  ┌────────────┬─────────────────┬──────────────────────────────────────────┐ │
│  │ Metric     │ ★ Baseline      │ A (SST)          Δ vs baseline           │ │
│  ├────────────┼─────────────────┼──────────────────────────────────────────┤ │
│  │ Worst NPV  │  −¥38 M         │  −¥22 M          +¥16M (less exposed)   │ │
│  │ P(NPV<0)   │   18 %          │   12 %           −6 pp                  │ │
│  │ P(IRR<7%)  │   24 %          │   16 %           −8 pp                  │ │
│  │ CVaR-5%    │  −¥76 M         │  −¥54 M          +¥22M                  │ │
│  └────────────┴─────────────────┴──────────────────────────────────────────┘ │
│                                                                              │
│  ── OPERATIONAL ────────────────────────────────────────────────────────── │
│  ┌────────────┬─────────────────┬──────────────────────────────────────────┐ │
│  │ CAPEX ¥M   │ ¥1 800 M        │ ¥1 920 M         +6.7%                  │ │
│  │ OPEX ¥M/yr │  ¥28 M          │  ¥30 M           +7%                    │ │
│  │ Export MWh │ 1 234 567       │ 1 234 567          0                     │ │
│  └────────────┴─────────────────┴──────────────────────────────────────────┘ │
│                                                                              │
│  † ΔP50 = baseline P50 vs variant P50 (independent ensembles). If runs are  │
│    seed-paired, seed-paired Δ (per-draw mean) is available — see finance-   │
│    expert §13 ruling.                                                        │
│  B (new config): all cells show ─ (retrain required)                        │
│  Delta coloring: green = better than baseline (lower risk, higher return);  │
│    red = worse; amber = neutral. Best value per metric: subtle green tint.  │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Delta display rules:**
- Baseline column: P50 + P90 absolute values (upside section); absolute worst-case values (downside section). No delta on baseline.
- Other variant columns: P50 + P90 absolute values + `ΔP50` (delta of P50s) in the upside section; absolute worst-case values + delta in the downside section.
- **Delta is delta of P50s, not P50 of deltas.** This is the default because variants run independent weather ensembles (different random seeds). If the ensembles are seed-paired (same seeds across variants), finance-expert will supply a per-draw delta in `POST /api/compare/finance`; the UI then swaps to show it automatically, and the footnote `†` updates to reflect the seed-pairing.
- **Downside delta direction:** for Worst NPV / CVaR-5%, positive delta (less negative) = green (better). For P(NPV<0) / P(IRR<hurdle), negative delta (lower probability) = green (better).
- Tier 3 variants (retrain required): cells show `—` with a tooltip.
- Tier 2 variants currently running: cells show a shimmer placeholder.

**P90 direction:** for IRR/NPV/MIRR, P90 represents the downside (90% of scenarios achieve *at least* this value) — it is shown *beneath* P50. For LCOE/Payback, P90 represents the upside (90% of scenarios have costs *no worse* than this value). Column header suffix clarifies direction for each row type.

**Metric groups:**
The table has three sections: **Upside** (IRR, NPV, MIRR, LCOE, Payback) with P50 + P90 + ΔP50 columns; **Downside Risk** (Worst NPV, P(NPV<0), P(IRR<hurdle), CVaR-5%) with absolute + delta columns; and **Operational summary** (CAPEX, levelized OPEX, annual export) with deterministic values. A `[▾ Show all]` toggle expands to show P75/P99 rows and year-by-year cash-flow breakdown.

**M = 1 state in the comparison table (v1 default):** At M = 1 the probabilistic metrics in the Downside Risk section are **suppressed across all variant columns** — cells show `— (M > 1 required)` with a tooltip `"Risk distribution metrics require ensemble. Run with M ≥ 50."` The Upside P90 column is also suppressed (P90 = single draw = not a bankability floor). The same M = 1 banner shown in Finance §10 appears above the table header. Cross-variant deltas on suppressed metrics are also suppressed. Well-defined single-trajectory values (Worst single-year cash flow, max drawdown) remain visible where they appear.

### 4.3 Results tab — NPV vs Discount Rate (NpvFanChart, multi-variant)

With M > 1 weather draws the chart shows **one fan per variant**: each variant contributes a median line + P25-P75 band. The fan widths give an immediate visual read on which variant has tighter vs wider uncertainty, which is as important as the median level.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [Table]  [NPV vs Rate ●]  [Per-variant detail]                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  NPV vs Discount Rate — P50 ± P25-P75 bands (M = 50)                       │
│                                                                              │
│  ¥300M │                                                                     │
│        │ ★░░░░░░░░  ← baseline P10-P90 band (light blue)                    │
│  ¥200M │ ★▒▒▒▒▒▒▒▒  ← baseline P25-P75 band (medium blue)                  │
│        │ ★────────  ← baseline P50 median                                   │
│  ¥100M │   A░░░░░░  ← variant A P10-P90 band (light orange)                 │
│        │   A▒▒▒▒▒▒  ← variant A P25-P75 band (medium orange)               │
│        │   A──────  ← variant A P50 median  (dashed line)                  │
│     ¥0 ├─────────────────────────────────────────────────────────────────── │
│        │         ★P90 IRR ★P50 IRR A P90 A P50        rate %               │
│ -¥100M │         (7.6%)  (8.2%) (8.1%) (8.7%)                              │
│        └────────────────────────────────────────────────────────────────── │
│          3%     5%     7% (WACC)    9%    11%    13%    15%                 │
│                         ↑ WACC ref                                          │
│                                                                              │
│  Legend: ★ Baseline (blue)  ·  A (SST) (orange, dashed)  ·  B — (unavail.) │
│  [✎ Range]  [● Show P10-P90 bands]  [○ Median-only view]                   │
│  Hover: P10/P50/P90 NPV for all variants simultaneously at cursor rate      │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Fan chart behaviour:**
- **Per-variant color coding:** each variant gets a distinct hue (baseline = blue; A = orange; C = green; etc.). The median line is solid for baseline, dashed for variants. Fan bands use the same hue at 30% opacity (P25-P75) and 15% opacity (P10-P90).
- **IRR markers:** both P50 IRR and P90 IRR x-intercepts are marked per variant on the zero line (small circles; P50 = filled, P90 = open). This gives the full "bankability spread" for each variant visually.
- **Toggle controls:** `[● Show P10-P90 bands]` / `[○ Median-only view]` — default is bands shown; median-only reduces visual complexity for clean screenshots.
- **Rate-slider interaction:** adjusting the WACC slider in the Assumptions panel live-updates the WACC reference line and re-discounts all M×N-variant series client-side (instant, same as §13 of stage_5_finance.md).
- Tier 3 variants: excluded from chart, noted in legend as `B — (retrain required)`.
- X-axis range configurable via `[✎ Range]` inline button (default 3%–15%).
- Hover tooltip: P10/P50/P90 NPV for all shown variants simultaneously at cursor rate.

### 4.4 Results tab — Per-variant detail

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [Table]  [NPV vs Rate]  [Per-variant detail ●]                              │
│  Select variant: [★ Baseline ▼]                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ★ BASELINE — Gansu-v1 · SAC run-a1b2c3 · Price: declining-real             │
│  Assumptions: WACC 7.0% · 20yr · View I · Merchant · Synthetic M=50        │
│  Config: #a1b2c3  ·  Eval: run-a1b2c3 / best_ckpt  ·  2026-06-10           │
│                                                                              │
│  DOWNSIDE RISK                                                               │
│  Worst NPV −¥38M  Max ddwn ¥842M (yr 5)  P(NPV<0) 18%  P(IRR<7%) 24%      │
│  CVaR-5% −¥76M   Worst yr cash flow −¥12M                                  │
│                                                                              │
│  HEADLINE METRICS (upside context)                                          │
│  IRR  8.2%  P50  ·  7.6% P90       NPV  ¥142M P50  ·  ¥118M P90            │
│  MIRR  7.1% P50  ·  LCOE ¥312/MWh  ·  Payback 8.3yr P50                   │
│  [▾ full distribution: P50/P75/P90/P99 + histogram]  M=50                  │
│                                                                              │
│  CASH FLOW (bar chart, year-by-year — same as Finance Stage ⑤)             │
│  [chart — year 0 to 20, with battery replacement year marker]               │
│                                                                              │
│  SENSITIVITY TORNADO (top-5 drivers)                                        │
│  [chart — ±ΔNPV ranked by impact]                                           │
│                                                                              │
│  ASSUMPTIONS (collapsible)                                                  │
│  ▾ Discount Rate  WACC 7.0% (= r_f 2.85% + β 0.75 × ERP 5.50%)            │
│  ▾ Capital Structure  ...                                                   │
│  Price path: declining-real                                                  │
│  [full FinanceAssumptionsPanel displayed read-only; ✎ Edit to switch to     │
│   per-variant mode and unlock editing]                                       │
│                                                                              │
│  [← Baseline]  [A (SST) →]                                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Per-variant detail** is a drill-down: same content as Stage ⑤ Finance's results panel but in read-only mode. It shows the **Downside Risk panel first** (same six metrics as Finance §10: worst NPV, max drawdown + year, P(NPV<0), P(IRR<hurdle), CVaR-5%, worst yr), followed by the headline P50/P90 upside context, cashflow bar chart, sensitivity tornado, and full assumptions. The active price path is shown in both the variant header and the assumptions block. Left/right arrows navigate between variants.

---

## 5. Variant editor

When the user clicks `[+ New variant]`, `[edit]` on an existing variant, or `[Duplicate baseline]`, they enter the **Variant Editor** — an inline expanded row or a side panel (decision deferred to frontend contract; preference is inline row expansion to keep the context visible).

```
┌── VARIANT EDITOR — A (SST) ─────────────────────────────────────────────────┐
│                                                                              │
│  LABEL                                                                       │
│  [ A (SST)                    ]                                              │
│                                                                              │
│  SITE CONFIG                                                                 │
│  [ Gansu-v1 (current)    ▼ ]  [or: Paste config hash]  [← Load from wizard] │
│  → Config hash: #a1b2c3  ·  Gansu, 100×Vestas V150, 1×CATL 300 MWh,        │
│    pcc-substation-945mw  ·  Tariff: Gansu-TOU-2024                          │
│                                                                              │
│  CAPEX / OPEX OVERRIDES  (appears if config differs from benchmark)         │
│  Grid connection:  [¥ 240 M   ] (benchmark: ¥120M; +¥120M = SST premium)   │
│                     [benchmark-cited ↺]                                      │
│  (other CAPEX fields default to benchmark; override any here)               │
│                                                                              │
│  POLICY                                                                      │
│  [ SAC run-a1b2c3 best_ckpt (2026-06-10)  ▼ ]                              │
│  → Compatible ✓  ·  Trained on: config #a1b2c3  ·  2.4M steps              │
│                                                                              │
│  EXECUTION PLAN (auto-computed on change):                                  │
│  ⚡ Instant — CAPEX differs from baseline, same policy + eval result.       │
│     Finance projection runs in <1 s on save.                                │
│                                                                              │
│  PRICE PATH                                                                  │
│  [● Shared path (declining-real)  ○ Per-variant override]                  │
│  (Per-variant: [declining-real ▼]  [✎ Edit curve] — reuses PricePathSelector│
│   from Finance §3.3; change is instant client-side re-multiply)             │
│                                                                              │
│  FINANCE ASSUMPTIONS                                                         │
│  [● Shared assumptions  ○ Per-variant]                                      │
│  Shared: WACC 7.0% · 20yr · View I · Merchant  [✎ Edit shared]             │
│                                                                              │
│  [Cancel]                                    [Save variant]                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Config selection in the variant editor:**
- Dropdown shows all saved site configs (recently used, named). A "Load from wizard" shortcut imports the current wizard Stage ① config.
- `POST /api/compare/plan` is called on every meaningful change to show the updated execution tier before the user saves.
- CAPEX/OPEX overrides appear as a compact overlay section — the override UI reuses `AssumptionField` primitives from Finance Stage ⑤.

**Policy selection:**
- Dropdown shows all entries from the policy library (same as Stage ④ Eval `PolicyLibrary` component).
- Compatibility check runs immediately when config + policy pair changes; shows `✓ Compatible` or `⊗ Incompatible — obs_dim mismatch`.
- "No policy yet" option: leaves `policy` null, tier becomes Tier 3.
- Baselines (always-available agents like "do nothing" / "peak-shave heuristic") are included.

---

## 6. Entry points — "Add to comparison" flows

The workbench is reachable from three points in the wizard. In each case, clicking `[+ Add to Comparison]` or `[+ Compare]` opens a lightweight "Add to workbench" modal:

```
┌── ADD TO COMPARISON ──────────────────────────────────────────────────────┐
│                                                                            │
│  Add to:  [★ Baseline of new comparison  ▼]                               │
│           OR  [Variant in existing: "SST vs trad." ▼]                     │
│                                                                            │
│  Label for this variant: [ Traditional grid             ]                 │
│                                                                            │
│  [Cancel]                                           [Add →]               │
└────────────────────────────────────────────────────────────────────────────┘
```

### 6.1 From Stage ① Config

**Button:** `[+ Add to Comparison]` secondary action in the Config stage footer, beside "Save & Continue".
**What is sent:** the current site config `config_hash`.
**Effect:** creates a variant with only the config axis populated; policy and eval result are null (Tier 3 until the user trains and evals). The variant editor opens in the workbench pre-populated with this config.
**Primary use case:** set up the variant pair before training ("I'll train both, then compare").

### 6.2 From Stage ④ Eval Results Library

**Button:** `[+ Compare]` action on each row of the Eval Results Library.
**What is sent:** `{eval_result_id, policy_id, config_hash}` tuple.
**Effect:** creates a variant with config + policy + eval result all populated (Tier 0/1 — finance projection runs immediately using shared assumptions). The workbench shows results right away.
**Primary use case:** compare two already-trained policies — e.g. SAC vs. a baseline agent on the same site.

### 6.3 From Stage ⑤ Finance

**Button:** `[+ Add to Comparison]` in the Finance stage footer, beside "Export results + assumptions".
**What is sent:** `{eval_result_id, policy_id, config_hash, finance_snapshot}`.
**Effect:** creates a fully-specified variant (config + policy + eval + assumptions). In the workbench, this variant's finance projection is identical to what was shown in Stage ⑤.
**Primary use case:** the USER's company demo story — configure the first variant completely in the wizard, then `[+ Add to Comparison]`, duplicate it in the workbench, and swap the grid connection for the second variant.

### 6.4 Workbench-native creation

**Buttons:**
- `[+ New variant]` (top right) — opens the variant editor with all fields blank.
- `[Duplicate]` on any existing variant row — opens the variant editor pre-populated; user changes only what differs (e.g. CAPEX override).

**Primary use case for duplicate:** the SST demo story — start from the configured baseline, duplicate it, change only the grid connection CAPEX.

---

## 7. Two eval modes — design constraint (rl-architect v1.1 ruling)

The rl-architect v1.1 spine amendment defines two canonical eval modes that share the same env + accumulators but target different surfaces:

| Mode | Where | Surface | Pacing | 3D | Output |
|------|-------|---------|--------|----|--------|
| **Observed** | Wizard ④ · Live dashboard | Telemetry WS stream | D24 real-time pacing | ✓ 3D scene animation | Live metrics + replay |
| **Batch** | Workbench (this doc) | OFF-WIRE (#82 accumulators) | vmapped, no pacing | ✗ never | Static accumulator results |

Batch mode = same env + same accumulators as observed mode, different surface. PR #82 (OFF-WIRE accumulators) enables this split — no new env mechanism needed. The workbench **exclusively** uses batch mode.

**No streaming.** Batch evals return a single result when complete. The workbench polls `GET /api/compare/run/{run_id}/status` every 5 s until `status == "complete"`. No WebSocket needed for the workbench.

**No 3D.** The workbench route never mounts `SceneMountPoint`. No telemetry store, no animation loop.

**No D24 pacing.** Batch eval runs at full vmapped speed — not gated to real-time display. Duration is determined by compute, not wall-clock step pacing.

**Duration estimates.** The execution plan endpoint returns an estimated duration per variant. The [Run missing] button label shows: `▶ Run 2 evals (~4 min total)`. During runs, a compact progress bar appears inside the variant row (not a full-screen modal).

**Partial results.** If the workbench has N variants and only M < N are ready, the results tab shows the M ready variants' data with "─ (running)" or "─ (retrain required)" cells for the rest. The user does not wait for all variants before seeing any results.

**Concurrent runs.** The backend runs multiple headless evals concurrently (vmap-based). The workbench submits a run batch via `POST /api/compare/run` and polls for completion — it does not model backend parallelism.

**Serving-engineer contract note.** The orchestration contract (`contracts/serving/`) must name both modes and specify how the API surfaces them. The workbench calls the batch-mode path; the wizard ④ / dashboard calls the observed-mode path. Naming is serving-engineer's decision; this doc uses "batch" and "observed" as working terms.

---

## 8. Navigation and routing

```
/compare                   — workbench landing; empty state on first visit
/compare/:comparison_id    — a named/saved comparison (future, v2)
```

**Top nav treatment.** The workbench sits alongside the wizard in the app nav:

```
 [Wizard  ①②③④⑤]  |  [Compare]  |  /training (power)  |  /eval (power)
```

The nav entry "Compare" is always present. The wizard's stage bar is only shown on `/wizard` routes.

**State persistence (v1):** comparison is in-memory (lost on browser refresh). A "Save comparison" button (v2) serialises the variant list to the server. For v1, the `[Export]` button is the persistence mechanism.

---

## 9. Component inventory — new components for this view

Reuses from wizard_flow.md §10:
- `PolicyLibrary` — policy + baseline selector (same component, same data)
- `FinanceAssumptionsPanel` — full assumptions panel (read-only mode in Per-variant detail; edit mode in variant editor)
- `AssumptionsStrip` — one-liner summary (shared assumptions bar above results table)
- `NpvFanChart` — NPV vs discount rate fan chart (multi-variant: one median + bands per variant; degrades to multi-line when M=1)
- `CashFlowChart` — per-variant detail tab
- `TornadoChart` — per-variant sensitivity

Shared with Finance Stage ⑤ (reused):
- `PricePathSelector` — (from Finance §3.3) preset cards with 20yr sparklines; also used for shared workbench-level price path control and per-variant override in VariantEditor
- `CurveEditor` — (from Finance §3.3) drag + table mode curve editor; reused for any custom-path editing in workbench
- `DownsideRiskPanel` — (from Finance §10) worst-case NPV, max drawdown + year, P(NPV<0), P(IRR<hurdle), CVaR-5%, worst yr; reused in per-variant detail

New components needed (to be specced in frontend contracts):
- `VariantList` — top section; rows of variants with status chips, edit/duplicate/remove actions; shared-assumptions bar + shared price-path control; [Run missing] button; [+ Add variant] action
- `VariantRow` — single variant row; label, config/policy/price-path summary, finance summary, status chip, action buttons
- `VariantEditor` — inline or side-panel form; config selector, CAPEX/policy/price-path/assumptions fields; live execution-plan display
- `ExecutionPlanBadge` — tier indicator chip: ⚡ Instant / ▶ Eval needed / ⚠ Retrain req. / ⏳ Running
- `ComparisonTable` — results table; three-section layout (Upside / Downside Risk / Operational); variant columns, metric rows; delta coloring; shimmer placeholders for running variants; "—" for retrain-required variants
- `ComparisonResultsTabs` — [Table] / [NPV vs Rate] / [Per-variant detail] tab bar with result panels
- `PerVariantDetail` — single-variant drill-down; DownsideRiskPanel first, then headline P50/P90, cash flow, tornado, assumptions (read-only); prev/next nav
- `AddToComparisonModal` — lightweight modal for entry-point flows (from Config/Eval/Finance stages)
- `SharedAssumptionsBar` — one-liner strip showing shared WACC/horizon + price-path name; [✎ Edit] opens stripped-down `FinanceAssumptionsPanel` for Class B params + PricePathSelector for shared path

---

## 10. API surface (design intent — to be locked in backend contract)

These endpoints are needed for the workbench. They are design-level notes; the actual contracts live in `contracts/serving/`.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /api/compare/plan` | POST | Takes variant list; returns execution plan (tier per variant, duration estimates, shared-dispatch groups) |
| `POST /api/compare/run` | POST | Submits Tier (b) variants for batch-mode eval; returns `run_id`; batch mode = vmapped, OFF-WIRE |
| `GET /api/compare/run/{run_id}/status` | GET | Poll for batch eval completion; returns `{status, results_by_variant_id}` |
| `POST /api/compare/finance` | POST | Server-side finance Δ-projection for Tier (a) 1 variants (CAPEX/OPEX/tax/debt); re-slices cached cash flows; NO-DOUBLE-COUNT logic enforced here |

Tier (a) 0 (instant finance re-slice from same cash-flow series) is handled client-side, same as Finance Stage ⑤ Class B parameters.

**Contract ownership:** serving-engineer owns the orchestration contract for `compare/run` (must formally distinguish observed-mode vs batch-mode eval in the contract). finance-expert owns the delta-accounting logic in `compare/finance` (NO-DOUBLE-COUNT correctness).

---

## 11. Open questions

**Q1 — Comparison persistence (v1 scope):** For v1, comparisons are in-memory only. Is that acceptable, or should the workbench persist to the server automatically? *(Deferred to USER review; v1 = in-memory, [Export] for sharing.)*

**Q2 — Shared-assumption mutation:** If the user edits the shared assumptions while some variants are Tier 2 (have eval results), does that trigger an instant finance re-projection on those variants (Tier 0/1)? Yes — changing only the discount-rate parameters should always be Tier 0. If CAPEX/OPEX in shared assumptions changes, it may push Tier 0 → Tier 1. The execution plan is always re-run server-side after any assumption change.

**Q3 — Weather mode per variant:** In v1, all variants use the same weather mode and ensemble size M. Per-variant M override and cross-variant weather mode comparisons (Synthetic vs Historical) are deferred to v2. The ensemble size M is a workbench-level parameter, not a per-variant one — all variants in a comparison run share the same M.

**Q5 — Delta method (seed-pairing):** The default Δ is delta-of-P50s (independent ensembles). If the backend supports seed-paired runs (same weather draws across variants), the `POST /api/compare/finance` response can include a `seed_paired_delta` field. The `ComparisonTable` will display it when present and update the `†` footnote accordingly. **finance-expert must rule in §13 which delta method is the default and whether seed-pairing is supported in v1.** This is a gate on the table schema in the frontend contract.

**Q6 — Band toggle memory:** Should `[● Show P10-P90 bands]` / `[○ Median-only]` state persist across tab switches? Yes — user preference is sticky within the session. Noted for frontend-engineer's state management.

**Q4 — Export format:** For the company demo, the primary output is likely a one-page PDF comparing two variants side-by-side. v1 will produce CSV + a raw-data dump. A formatted PDF report is v2.

**Q7 — Scenario (price path × variant) identifier:** When two variants run different price paths, how does the comparison table label them? Proposed: the variant header row shows `A (SST) · declining-real` and `A (SST) · stress` as separate columns (or separate scenario rows). This needs a decision: are multiple price-path × variant combos separate COLUMNS or separate ROWS in the table? Suggested: if variants differ only by price path, they appear as rows in a "price path comparison" sub-mode, with the variant header fixed and a price-path row label. If variants differ by both config and price path, they appear as separate columns. **This framing decision gates the ComparisonTable schema in the frontend contract** — table schema needs to be decided before the contract is written. Flag for USER review.

**Q8 — Shared vs per-variant downside risk in NpvFanChart tab:** The §4.3 NpvFanChart multi-variant chart shows upside fans per variant. Should it also show a "downside zone" (P(NPV<0) region, i.e. the proportion of paths where NPV is negative) visually? This would require a horizontal shaded band below the x-axis for each variant's downside probability. v1: omit (separate Downside Risk section in Table tab is sufficient). Revisit if USER requests it.

---

## 12. Visual language (extends wizard_flow.md §10)

The workbench inherits all design tokens from the existing dark theme (wizard_flow.md §10). No new color variables needed. Status chip colors:

```
⚡ Instant/Fast   — #60a5fa (blue, same as active nav link)
▶ Eval needed    — #f59e0b (amber, same as Class A notice)
⚠ Retrain        — #f87171 (red, same as error boundary)
⏳ Running        — #a78bfa (violet pulse — new; conveys async work)
✓ Ready           — #34d399 (green — new; success/complete state)
```

Delta coloring in table:
```
Better than baseline  — #34d399 (green)
Worse than baseline   — #f87171 (red)
Neutral (±0)          — #94a3b8 (slate)
```

---

*docs/design/ux/comparison_workbench.md — ui-designer, task #67 — v0.1 2026-06-12 (initial design: variant model, execution tiers, layout, wireframes, component inventory) · v0.2 2026-06-12 (rl-architect v1.1 ruling: DELTA framework, NO-DOUBLE-COUNT, two-mode terminology observed/batch, (a)/(b)/(c) canonical tier labels, SST showcase path, vmapped batch eval for Tier (b), serving-/finance-expert ownership notes) · v0.3 2026-06-12 (USER directive: distribution-aware comparison — §4.2 table with P50+P90 columns per variant + delta-of-P50s default + seed-pairing footnote slot; §4.3 NpvFanChart multi-variant with per-variant bands + IRR P50/P90 markers + band-toggle control; §4.4 headline updated to P50/P90 pair; AssumptionsStrip M=50; §9 NpvCurveChart → NpvFanChart; Q5 delta-method gate on finance contract + Q6 band-toggle memory) · v0.4 2026-06-12 (USER directive: scenario = price path × variant — price_path field in variant model; §4.1 shared price-path control in VariantList; §4.2 table restructured into Upside / Downside Risk / Operational sections, worst-case columns (Worst NPV, P(NPV<0), P(IRR<hurdle), CVaR-5%) with deltas; §4.4 DownsideRiskPanel first in per-variant detail, price-path name in variant header; §5 PRICE PATH control in VariantEditor; §9 PricePathSelector + CurveEditor + DownsideRiskPanel as shared components; Q7 scenario-column framing gate; Q8 NpvFanChart downside-zone deferred) · v0.5 2026-06-12 (frontend-reviewer REQUEST_CHANGES: M=1 honesty — §4.2 Downside Risk section cells show "— (M>1 required)" at M=1; P90 Upside column suppressed at M=1; M=1 banner above table; cross-variant deltas on suppressed metrics suppressed; single-trajectory metrics (max drawdown, worst yr) remain visible)*
