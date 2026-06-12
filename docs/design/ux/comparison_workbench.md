# Comparison Workbench — UX Design

> **Owner:** ui-designer · **Task:** #67
> **Status:** DRAFT v0.2 — incorporates rl-architect v1.1 spine ruling (2026-06-12)
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
  finance_overrides: FinanceSnapshot         // a full snapshot of finance assumptions for this
                                             //   variant; can be shared or per-variant
}
```

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
│  │  [+ Add variant]  ·  Shared assumptions: WACC 7.0% · 20yr · [✎ Edit]   │ │
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

### 4.2 Results tab — Table

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [Table ●]  [NPV vs Rate]  [Per-variant detail]                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ASSUMPTIONS SUMMARY                                                        │
│  WACC 7.0% · 20yr horizon · View I (absolute) · Merchant · Synthetic M=1   │
│  (or: "⚠ Assumptions differ across variants — see per-variant detail")      │
│                                                                              │
│  ┌────────────────────┬──────────────┬──────────────────┬──────────────────┐ │
│  │ Metric             │ ★ Baseline   │ A (SST)          │ B (new config)   │ │
│  │                    │ Gansu-v1     │ Gansu-v1 +SST    │ Gansu-SST        │ │
│  ├────────────────────┼──────────────┼──────────────────┼──────────────────┤ │
│  │ IRR                │  11.2 %      │  11.7 % (+0.5pp) │ ─ (retrain req.) │ │
│  │ NPV @ WACC   ¥M    │  ¥142 M      │  ¥156 M (+¥14 M) │ ─                │ │
│  │ MIRR               │   9.8 %      │  10.1 % (+0.3pp) │ ─                │ │
│  │ LCOE          ¥/MWh│    312       │    311 (−1)       │ ─                │ │
│  │ Payback        yr  │    8.3       │    7.9 (−0.4)     │ ─                │ │
│  ├────────────────────┼──────────────┼──────────────────┼──────────────────┤ │
│  │ CAPEX          ¥M  │ ¥1 800 M     │ ¥1 920 M (+6.7%) │ ─                │ │
│  │ Levelized opex ¥/yr│  ¥28 M/yr    │   ¥30 M/yr (+7%) │ ─                │ │
│  │ Export      MWh/yr │ 1 234 567    │ 1 234 567 (0)     │ ─                │ │
│  └────────────────────┴──────────────┴──────────────────┴──────────────────┘ │
│                                                                              │
│  Delta coloring: green = better than baseline; red = worse; amber = neutral  │
│  Best value per row highlighted with subtle green tint (across all variants) │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Delta display rules:**
- Baseline column: absolute values only, no delta.
- Other columns: `absolute_value (Δ_vs_baseline)`. Delta colored green/red/amber based on direction: for IRR/NPV/MIRR — higher is better (green); for CAPEX/LCOE/Payback — lower is better (green).
- Tier 3 variants (retrain required): cells show `—` with a tooltip explaining the reason.
- Tier 2 variants currently running: cells show a shimmer/loading placeholder.

**Metric groups:**
The table has two sections: **Finance metrics** (IRR, NPV, MIRR, LCOE, Payback) and **Operational summary** (CAPEX, levelized OPEX, annual export, battery cycles/yr if available). A `[▾ Show all]` toggle expands to show additional rows (cash flows by year, P50/P90/P99 if available).

### 4.3 Results tab — NPV vs Discount Rate

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [Table]  [NPV vs Rate ●]  [Per-variant detail]                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  NPV vs Discount Rate (¥M)                                                  │
│                                                                              │
│  ¥300M │                                                                     │
│        │ ★─────                                                              │
│  ¥200M │       ★────────                          A─────                    │
│        │               ★────A────                        A────              │
│  ¥100M │                         ★──A──                        ★,A─         │
│        │                               ★,A──                        ─────   │
│     ¥0 ├─────────────────────────────────────┼──────────────────────────────│
│        │                             IRR: ★11.2  A11.7%           rate %    │
│ −¥100M │                                                                     │
│        │                                                                     │
│        └─────────────────────────────────────────────────────────────────── │
│         3%     5%     7% (WACC)    9%    11%    13%    15%                  │
│                       ↑ current                                             │
│                                                                              │
│  Legend:  ★ Baseline (solid)  ·  A (SST) (dashed)  ·  B — (unavailable)    │
│  Hover: shows tooltip with NPV value at cursor rate                          │
│  IRR marker: vertical dotted line at IRR x-intercept per variant            │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Chart behaviour:**
- X-axis: discount rate 3%–15% (configurable range via `[✎ Range]` inline button)
- Y-axis: NPV in ¥M; zero line prominent (thicker border)
- One line per non-retrain variant; Tier 3 variants excluded with a legend note
- Current WACC marked with a vertical dotted reference line
- IRR x-intercepts: where NPV = 0; marked with a small circle + label `"IRR: 11.2%"`
- Hover tooltip: shows NPV at cursor rate for all lines simultaneously
- Variants share the same x-axis range for direct comparison

### 4.4 Results tab — Per-variant detail

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [Table]  [NPV vs Rate]  [Per-variant detail ●]                              │
│  Select variant: [★ Baseline ▼]                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ★ BASELINE — Gansu-v1 · SAC run-a1b2c3                                     │
│  Assumptions: WACC 7.0% · 20yr · View I · Merchant · Synthetic M=1          │
│  Config: #a1b2c3  ·  Eval: run-a1b2c3 / best_ckpt  ·  2026-06-10           │
│                                                                              │
│  HEADLINE METRICS                                                            │
│  IRR 11.2%  ·  NPV ¥142M  ·  MIRR 9.8%  ·  LCOE ¥312/MWh  ·  Payback 8.3yr│
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
│  [full FinanceAssumptionsPanel displayed read-only; ✎ Edit to switch to     │
│   per-variant mode and unlock editing]                                       │
│                                                                              │
│  [← Baseline]  [A (SST) →]                                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Per-variant detail** is a drill-down: same content as Stage ⑤ Finance's results panel but in read-only mode. It shows the single-variant cashflow bar chart, sensitivity tornado, and full assumptions. Left/right arrows navigate between variants. This lets the operator review each variant's numbers in full before comparing.

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
- `NpvCurveChart` — NPV vs discount rate (multi-line variant of Finance Stage ⑤ chart)
- `CashFlowChart` — per-variant detail tab
- `TornadoChart` — per-variant sensitivity

New components needed (to be specced in frontend contracts):
- `VariantList` — top section; rows of variants with status chips, edit/duplicate/remove actions; shared-assumptions bar; [Run missing] button; [+ Add variant] action
- `VariantRow` — single variant row; label, config/policy summary, finance summary, status chip, action buttons
- `VariantEditor` — inline or side-panel form; config selector, CAPEX/policy/assumptions fields; live execution-plan display
- `ExecutionPlanBadge` — tier indicator chip: ⚡ Instant / ▶ Eval needed / ⚠ Retrain req. / ⏳ Running
- `ComparisonTable` — results table; variant columns, metric rows; delta coloring; shimmer placeholders for running variants; "—" for retrain-required variants
- `ComparisonResultsTabs` — [Table] / [NPV vs Rate] / [Per-variant detail] tab bar with result panels
- `PerVariantDetail` — single-variant drill-down; cash flow, tornado, assumptions (read-only); prev/next nav
- `AddToComparisonModal` — lightweight modal for entry-point flows (from Config/Eval/Finance stages)
- `SharedAssumptionsBar` — one-liner strip showing shared WACC/horizon; [✎ Edit] opens a stripped-down `FinanceAssumptionsPanel` covering only Class B params (WACC/horizon/view/currency)

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

**Q3 — Weather mode per variant:** In v1, all variants use the same weather mode (Synthetic M=1). Cross-variant weather comparisons (Synthetic vs Historical) are a v2 feature to avoid combinatorial complexity.

**Q4 — Export format:** For the company demo, the primary output is likely a one-page PDF comparing two variants side-by-side. v1 will produce CSV + a raw-data dump. A formatted PDF report is v2.

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

*docs/design/ux/comparison_workbench.md — ui-designer, task #67 — v0.1 2026-06-12 (initial design: variant model, execution tiers, layout, wireframes, component inventory) · v0.2 2026-06-12 (rl-architect v1.1 ruling: DELTA framework, NO-DOUBLE-COUNT, two-mode terminology observed/batch, (a)/(b)/(c) canonical tier labels, SST showcase path, vmapped batch eval for Tier (b), serving-/finance-expert ownership notes)*
