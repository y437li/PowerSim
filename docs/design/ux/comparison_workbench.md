# Comparison Workbench — UX Design

> **Owner:** ui-designer · **Task:** #67
> **Status:** DRAFT v0.6 (2026-06-14) — D42 model: config library first-class + two-mode discipline + 2D sizing sweep sub-mode
> **Gate:** USER reviews aesthetic direction before frontend contracts are written against this.
> **Inputs:** wizard_flow.md (sibling doc), master_plan_geo_finance.md §5, REBUILD_SPEC §3–§5
> **USER directive:** "有个地方可以多选,然后跑simulation根据算法看finance projection"
> **USER ruling (headless):** Workbench does NOT connect to the 3D simulator or live dashboard. No streaming, no 3D scene. Results are tables + charts. Think "analysis report", not "mission control."
> **rl-architect ruling (v1.1 spine amendment):** VARIANT-TIERING = stage-invalidation DAG applied to a variant set: (a) finance-assumption or cost-only-device-swap variants → re-slice cached cash flows, INSTANT; (b) dispatch-relevant diffs → vmapped batch eval; (c) no-compatible-policy → retrain required. UNIFIES `/api/finance/compare` (policy) + View II (battery-incremental) into one any-variant-vs-baseline DELTA framework. finance-expert OWNS delta-accounting correctness (baseline designation + NO-DOUBLE-COUNT). TWO EVAL MODES: observed (wizard ④/dashboard: telemetry + D24 pacing + 3D) vs batch (workbench: vmapped, OFF-WIRE #82 accumulators, no telemetry/pacing). Same env + accumulators, different surfaces. Workbench = batch mode only.
> **D42 USER decision (2026-06-14):** configs are first-class savable/forkable artifacts; comparison is a first-class entry point (not only post-Stage-⑤); two-mode discipline (Compare designs vs Press-test) enforced; 2D battery sizing = workbench sub-mode with surface/heatmap chart; baseline re-designation freely re-settable; regime display bound to D39 R1/R2/R3; naming fix: `sample_kind` for data-source provenance, R1/R2/R3 reserved for M-regime only.
> **Area owners:** frontend (workbench UI, config library) · serving (orchestration contract — name the 2 modes) · finance-expert (delta math, regime display rules) · rl-architect (variant-set tiering in v1.1 spine amendment) · dashboard-engineer (SurfaceChart, NpvFanChart multi-variant)

---

## 1. Purpose and product story

The Comparison Workbench is a **first-class sibling view** to the wizard pipeline (route `/compare`). It is composed of three integrated views:

1. **Config Library** (`/configs`) — savable/forkable site configs as first-class artifacts
2. **Comparison Workbench** (`/compare`) — multi-config comparison in two distinct modes
3. **Sizing Sweep sub-mode** — auto-generated 2D battery sizing grid rendered as a surface/heatmap inside the workbench

```
 Wizard (/wizard)                         Workbench (/compare)   Config Library (/configs)
 ─────────────────────────────────────    ─────────────────────  ──────────────────────────
  Config → Algo → Train → Eval → Finance  Compare designs         All saved configs; fork,
  (one site, end-to-end pipeline)         Press-test              compare, version
                                          Sizing sweep sub-mode

  Wizard Stage ① "Save" → auto-saves
  config to library ──────────────────────────────────────────────►
  Config Library → multi-select → "Compare" ──────────────────────►
  Stage ④ Eval "Add to compare" ──────────────────────────────────►
  Stage ⑤ Finance "[+ Add to comparison]" ─────────────────────────►
```

**Company demo story (USER's priority, task #68).** The workbench's primary demo is a **device-swap comparison**:
- **Baseline**: Gansu site, traditional substation grid connection (standard CAPEX), SAC-trained policy
- **Variant A**: same site, SST grid connection (different CAPEX, same physics)

The demo runs in **"Compare designs"** mode: the scenario (weather draws, price path) is LOCKED; the only difference is the CAPEX — an instant Tier (a) recalculation.

---

## 2. Two-mode discipline (D42 — enforced in UI)

The comparison workbench enforces two **visually and functionally distinct** modes. The user can never accidentally mix design differences with world-assumption differences in the same view.

```
┌────────────────────────────────────────────────────────────────────────┐
│  MODE SELECTOR  (prominent toggle; visible at all times)               │
│                                                                        │
│  [ ● Compare designs ]  [ ○ Press-test ]                               │
│                                                                        │
│  "Compare designs": lock scenario → vary design (config, CAPEX)        │
│  "Press-test":      lock design  → vary uncertainty (price, M, weather) │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Compare-designs mode

- **Scenario is LOCKED.** One shared scenario-selector panel (price path + ensemble M + sample_kind + finance assumptions) applies to ALL configs in the comparison. The scenario panel is visually locked with a 🔒 icon and a "Scenario locked — shared across all designs" label.
- The result deltas reflect ONLY design differences (config, CAPEX/OPEX, device choices). A delta of +¥14M NPV means the design is genuinely ¥14M better under the SAME world assumptions.
- When the user tries to change the scenario while in this mode: the controls are disabled with a tooltip "Switch to Press-test mode to vary the uncertainty scenario."
- Entry: the user selects multiple configs from the Config Library and clicks "Compare."

### 2.2 Press-test mode

- **Design is LOCKED.** One config is fixed (the "design under test"). The scenario controls (price path, M, weather mode) are fully editable.
- The user can define multiple scenarios and see how the SAME design performs across them.
- Used for single-config sensitivity analysis: "What if the electricity price falls 30%?" "What if we use real weather data (M≈10)?"
- Entry: clicking "Press-test this config ▶" from any config card in the library, or from the Per-variant detail tab in Compare-designs mode.

### 2.3 Mode switching

Switching modes preserves all config selections. Switching from Compare-designs → Press-test prompts "Press-test which config?" if multiple are selected. Switching back warns "Shared scenario will be reset to the default" if per-scenario edits were made.

---

## 3. Config Library (`/configs`)

Configs are **first-class savable/forkable artifacts**. Every site config that passes through the wizard is auto-saved to the library. The library is the primary home for config management.

### 3.1 Config card

```
┌── CONFIG CARD ─────────────────────────────────────────────────────────┐
│  Gansu-v1                              ⋮ (menu: Edit / Fork / Delete)  │
│  config_hash: #a1b2c3                                                  │
│  100× Vestas V150 · 1× CATL 300 MWh · pcc-substation-945mw            │
│  Tariff: cn-gansu · Created 2026-06-10                                 │
│  Forked from: — (origin)                                               │
│  Policies: 2 trained  ·  Evals: 3 results                              │
│                                                                        │
│  [✓ Select for comparison]                                             │
└────────────────────────────────────────────────────────────────────────┘
```

- **Fork** creates a new config with `parent_id` referencing the original. The fork opens in Stage ① Config for editing; on "Save" it is saved as a new config in the library.
- **Edit** reopens in Stage ① Config; saving replaces the config in-place (policies + evals that used the old config are NOT invalidated — training runs are immutable per D32/§h; only eval→finance edge is stale).
- **Delete** is soft-delete only if the config has dependent eval results; hard-delete otherwise.
- **Compare selected:** multi-select up to N configs → "Compare N configs ▶" button opens the workbench in Compare-designs mode.

### 3.2 Config provenance

A config carries:
```typescript
interface SavedConfig {
  id: string;               // server-assigned UUID
  config_hash: string;      // deterministic SHA-256 of config content
  label: string;            // user-given name
  parent_id?: string;       // if forked from another config
  created_at: string;       // ISO 8601
  site_summary: {
    site_id: string;
    battery_energy_mwh: number;
    battery_power_mw: number;
    wind_count: number;
    pv_count: number;
    pcc_device_id: string;
    tariff_region: string;
  };
}
```

---

## 4. Comparison Workbench variant model

A **variant** bundles three axes. Every variant specifies all three; the workbench computes the finance projection from them.

```
variant = {
  id:                string            // workbench-local label ("Baseline", "A", "B", ...)
  is_baseline:       bool             // one variant per workbench is the baseline (freely re-settable)
  config_id:         string           // references a saved config from the config library
  config_hash:       string           // for verification
  policy:            policy_ref | null  // {run_id, step} OR baseline-agent name OR null
  eval_result:       eval_result_id | null
  price_path:        price_path_name  // shared (from workbench scenario) or per-variant in Press-test
  finance_overrides: FinanceSnapshot  // shared or per-variant
}
```

**Baseline designation.** Default = first-added config. User can re-designate at any time via context menu or drag-to-baseline. Re-designation flips all delta directions live. Baseline column shows absolute values; all other columns show deltas.

**NO-DOUBLE-COUNT constraint** *(owned by finance-expert)*. When variants share the same dispatch results (same policy + eval), the delta applies only to the cost/revenue side. `POST /api/compare/plan` response indicates shared-dispatch variant groups.

---

## 5. Execution tier model

Same four tiers as v0.5, unchanged (rl-architect v1.1 spine ruling). See §3 of v0.5 for the tier table. The 2D sizing sweep (§7) uses the same tier model applied to a grid of auto-generated configs.

---

## 6. Layout and wireframes

### 6.1 Overall structure

```
┌───────────────────────────────────────────────────────────────────────────┐
│  ← Configs  ·  COMPARISON WORKBENCH  [● Compare designs | ○ Press-test]  │
│                                                    [+ Add config]  [Export]│
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌── SCENARIO (locked in Compare-designs mode) ─────────────────────────┐ │
│  │  🔒  Price: declining-real  ·  M=50  ·  WACC 7.0%  ·  20yr           │ │
│  │  "Scenario locked — shared across all configs"           [✎ Unlock]   │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌── CONFIGS ────────────────────────────────────────────────────────────┐ │
│  │  ★ Baseline  Gansu-v1 · SAC run-a1b2c3   WACC 7.0%  ✓ Ready          │ │
│  │  A (SST)     Gansu-v1 · SAC run-a1b2c3   WACC 7.0%  ⚡ Instant        │ │
│  │  B (new)     Gansu-SST · (no policy)     WACC 7.0%  ⚠ Retrain        │ │
│  │  [+ Add from library]  ·  [2D Sizing Sweep ▼]                         │ │
│  │  [Run missing ▶ 1 eval needed]                                         │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌── RESULTS ────────────────────────────────────────────────────────────┐ │
│  │  [Table]  [NPV vs Rate]  [Per-config detail]  [Sizing Surface]        │ │
│  │  (active tab content)                                                  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Results tab — Comparison table (regime-aware)

Same table structure as v0.5 §4.2, with regime-based metric suppression (§8 below).

### 6.3 Results tab — NPV vs Rate (NpvFanChart, multi-variant)

One fan per variant: median line + P25-P75 band (suppressed at R1/R3 per §8). From dashboard-engineer; see §9 for the chart interface contract.

### 6.4 Results tab — Per-config detail (Press-test panel nested here)

In Compare-designs mode: single-variant drill-down, same as v0.5 §4.4. The "Press-test this config ▶" button at the bottom opens the press-test panel for the selected config without leaving the workbench.

In Press-test mode: the per-config detail IS the primary view; scenario controls are fully editable; each scenario row shows its own finance projection.

---

## 7. 2D Sizing Sweep sub-mode

Activated via **[2D Sizing Sweep ▼]** in the configs section. Not a separate tool — it is a workbench sub-mode.

```
┌── 2D SIZING SWEEP ────────────────────────────────────────────────────────┐
│  Base config: Gansu-v1  ·  Vary: battery  ·  Metric: NPV P50 (¥M)       │
│  Energy range: [100 MWh] to [600 MWh]  in [6] steps                      │
│  Power range:  [ 50 MW]  to [300 MW]   in [6] steps                      │
│  [Run sweep ▶  36 configs]                                                │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌── SIZING SURFACE (from dashboard-engineer SurfaceChart) ─────────────┐ │
│  │                                                                       │ │
│  │  Power     ↑                                                          │ │
│  │  MW   300  │  ████░░░░  [◎ 250 MW / 400 MWh — recommended]           │ │
│  │        200  │  ████████                                               │ │
│  │        100  │  ██░░░░░░                                               │ │
│  │              └────────────────────────────────────────► Energy MWh    │ │
│  │               100   200   300   400   500   600                       │ │
│  │                                                                       │ │
│  │  Hover: (400 MWh, 250 MW) → NPV P50 = ¥142M                          │ │
│  │         [click to add as variant in main comparison]                  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  [View in main comparison: ★ Baseline (recommended point) vs custom]     │
└───────────────────────────────────────────────────────────────────────────┘
```

**Execution:** the sweep generates N×M auto-configs (one per grid point), runs them through the execution-tier model (Tier b = batch eval for dispatch-relevant diffs, Tier a = instant for CAPEX-only diffs), and populates the surface. Progress bar shows "Running… 24/36 configs" during batch eval.

**Recommended point:** the server (`POST /api/compare/sizing-sweep`) returns a `recommended_energy_mwh` + `recommended_power_mw` (the grid point maximising the selected metric), displayed as a ◎ marker on the surface.

**Hover distribution:** hovering a grid point shows a pop-up with the distribution across M draws (histogram or P50/P90 band), only when regime = R2. At R1 or R3, the hover shows the point estimate with regime banner.

**"Add to comparison":** clicking a surface point adds it as a named variant in the main comparison table (e.g., "Battery 400 MWh × 250 MW").

---

## 8. Regime display (D39 binding — single source of truth = backend field)

The UI reads `distribution_valid` + `sample_kind` from `FinanceResult`/`PolicyEnsemble` to determine regime. It NEVER infers regime from M count alone.

```
Backend field mapping → UI regime:
  distribution_valid = false           →  R1  (M=1, point estimate only)
  distribution_valid = true
    sample_kind = "synthetic"          →  R2  (M≥50 bootstrap)
    sample_kind = "empirical"          →  R3  (M≈10, real ERA5 years)
```

**Naming discipline:** "R1/R2/R3" are ONLY the D39 M-regime labels. The data-source provenance axis (which weather data was used) reads as `sample_kind: "synthetic" | "empirical"`. The UI never displays R1/R2/R3 as data-source labels.

### 8.1 R1 (M=1 — point estimate)

Banner: *"Single-trajectory (M=1) — risk distribution metrics require M ≥ 50."*

| Section | Shown | Suppressed |
|---------|-------|------------|
| Upside P50 | IRR P50, NPV P50, MIRR P50, LCOE, Payback P50 | — |
| Upside P90 | Worst single-year cash flow, max drawdown | All P90 columns |
| Downside Risk | — | Entire panel (Worst NPV, P(NPV<0), CVaR-5%, P(IRR<hurdle)) |

Suppressed cells show `— (M > 1 required)` with tooltip. Deltas on suppressed metrics are also suppressed.

### 8.2 R2 (M≥50 bootstrap — full distribution)

No banner. Full metric set available:
- Upside: P50 + P90 per metric
- Downside Risk: Worst NPV, P(NPV<0), P(IRR<hurdle), CVaR-5%, worst year cash flow

### 8.3 R3 (M≈10 empirical — partial, tail-percentile suppressed)

Banner: *"Empirical ensemble (M≈10 real-weather years) — tail percentiles suppressed; worst/best of N observed years shown instead."*

| Section | Shown | Suppressed |
|---------|-------|------------|
| Upside P50 | IRR P50, NPV P50, MIRR P50, LCOE, Payback P50 | — |
| Upside P90 | — | All P90 columns (nearest-rank at M≈10 = min/max, not a meaningful floor) |
| Downside Risk (partial) | Worst NPV (= min of M runs), Best NPV (= max), P(NPV<0) as frequency (k/M) | CVaR-5%, P(IRR<hurdle), P75/P95 labels |

**Why no P90 at R3:** at M=10, `np.quantile(M, 0.10, method='lower') = index 0 = the minimum`. P90, CVaR-5%, and worst-case would be three labels for one number — the §13.10c relabel trap. D39 resolved this: at R3 show worst/best-of-N and frequency counts only.

---

## 9. Component inventory

### From dashboard-engineer (chart contracts — interfaces locked between engineers)

**`SurfaceChart`** — sizing sweep heatmap:
```typescript
interface SurfaceChartProps {
  energyAxis_mwh: number[];           // x-axis grid values (MWh)
  powerAxis_mw: number[];             // y-axis grid values (MW)
  surface: number[][];                // [energy_idx][power_mw_idx] — metric values
  metric: "npv_p50" | "irr_p50" | "lcoe";
  metric_unit: "¥M" | "%" | "¥/MWh"; // for axis labels and tooltip
  regime: "R1" | "R2" | "R3";
  recommendedPoint?: {
    energy_idx: number;               // index into energyAxis_mwh
    power_idx: number;               // index into powerAxis_mw
    distribution_yuan?: number[];    // M-draw NPV values for hover histogram (R2 only)
  };
  onPointHover?: (energy_idx: number, power_idx: number) => void;
  onPointSelect?: (energy_idx: number, power_idx: number) => void;
}
```

**`NpvFanChart`** — NPV vs discount rate, multi-variant:
```typescript
interface NpvVariantSeries {
  id: string;
  label: string;
  is_baseline: boolean;
  color: string;                       // hex token from TOKEN
  // Pre-computed at each discount rate (server-computed or client-rediscounted):
  rates_pct: number[];
  p50_npv_yuan: number[];
  p25_npv_yuan?: number[];            // absent at R1/R3
  p75_npv_yuan?: number[];
  p10_npv_yuan?: number[];
  p90_npv_yuan?: number[];
  irr_p50_pct?: number;              // x-intercept marker
  irr_p90_pct?: number;             // x-intercept marker (R2 only)
}

interface NpvFanChartProps {
  variants: NpvVariantSeries[];
  regime: "R1" | "R2" | "R3";
  wacc_ref_pct: number;
  showBands: boolean;                  // sticky within session
  xRange?: [number, number];          // default [3, 15]
  onRateHover?: (rate_pct: number) => void;
}
```

*[NOTE: SurfaceChart and NpvFanChart prop interfaces pending dashboard-engineer confirmation — see PR comments. Contract is locked once dashboard-engineer confirms or proposes alternatives.]*

### Existing components reused from wizard

- `FinanceAssumptionsPanel` (read-only in per-config detail; editable in Press-test)
- `PricePathSelector` (shared scenario control + per-config in Press-test)
- `CurveEditor` (custom price path editing)
- `DownsideRiskPanel` (per-config detail — regime-aware suppression applied)
- `PolicyLibrary` (policy picker in variant editor)

### New components for this view

- `ConfigLibrary` — config catalog view; multi-select; fork/edit/delete; "Compare selected"
- `ConfigCard` — single config card with provenance, actions, and "Select for comparison" toggle
- `WorkbenchModeSelector` — prominent Compare-designs / Press-test toggle
- `ScenarioLockBar` — the locked scenario bar (Compare-designs mode) with 🔒 icon
- `VariantList` — config rows with status chips, edit/duplicate/remove; [Run missing] button
- `VariantRow` — single config row; label, config/policy summary, tier status chip
- `VariantEditor` — inline form; config selector, CAPEX/policy/price-path/assumptions; live tier display
- `ExecutionPlanBadge` — tier chip: ⚡ Instant / ▶ Eval needed / ⚠ Retrain req. / ⏳ Running
- `ComparisonTable` — three-section table (Upside / Downside Risk / Operational); regime-aware suppression
- `ComparisonResultsTabs` — [Table] / [NPV vs Rate] / [Per-config detail] / [Sizing Surface] tab bar
- `PerConfigDetail` — single-config drill-down; DownsideRiskPanel first; "Press-test ▶" entry
- `SizingSweepPanel` — sweep config form + SurfaceChart mount + progress bar
- `AddToComparisonModal` — lightweight modal from wizard entry points
- `BaselineRedesignateControl` — context menu / drag UI for changing which config is the baseline

---

## 10. Entry points

Four entry points; same as v0.5 §6 plus the new Config Library first-class path:

1. **Config Library** (`/configs`) — multi-select → "Compare N configs ▶" → Compare-designs mode
2. **Stage ① Config** — "Save & Continue" auto-saves to library; `[+ Add to comparison]` secondary action
3. **Stage ④ Eval Results** — `[+ Compare]` on eval row → creates variant with config+policy+eval
4. **Stage ⑤ Finance** — `[+ Add to Comparison]` in footer → fully-specified variant

The Config Library entry point is the **primary** comparison flow (D42). Stage ④ and Stage ⑤ are convenience shortcuts for users who have completed the wizard.

---

## 11. API surface (design intent — to be locked in backend contracts)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/configs` | GET | List saved configs |
| `POST /api/configs` | POST | Save new config |
| `GET /api/configs/:id` | GET | Get single config |
| `POST /api/configs/:id/fork` | POST | Fork a config |
| `POST /api/compare/plan` | POST | Variant list → execution plan (tier per variant) |
| `POST /api/compare/run` | POST | Submit Tier (b) variants for batch eval; returns `run_id` |
| `GET /api/compare/run/:run_id/status` | GET | Poll batch eval completion |
| `POST /api/compare/finance` | POST | Server-side finance Δ-projection for Tier (a)1 variants |
| `POST /api/compare/sizing-sweep` | POST | Submit 2D battery sizing sweep; returns surface + recommended point |
| `GET /api/compare/sizing-sweep/:run_id/status` | GET | Poll sweep completion |

---

## 12. Routing and persistence

```
/configs                   — config library
/compare                   — workbench (empty state on first visit)
/compare/:comparison_id    — saved comparison (v2)
```

**State persistence (v1):** comparison is in-memory (lost on browser refresh). Config library persists server-side. `[Export]` is the v1 sharing mechanism.

---

## 13. Visual language

Inherits all design tokens from wizard_flow.md §10. Status chip colors unchanged from v0.5. Mode selector visual treatment:
- Active mode: filled button, `TOKEN.accentBlue` border, `TOKEN.bgSurface`
- Inactive mode: outlined, `TOKEN.borderDefault`, `TOKEN.textMuted`
- Scenario lock bar: `TOKEN.accentAmber` 🔒 icon + lock label (amber conveys "constraint active, not error")

---

*docs/design/ux/comparison_workbench.md — ui-designer, task #67*
*v0.1 2026-06-12 · v0.2 2026-06-12 (rl-architect v1.1: DELTA framework, batch/observed modes, SST showcase) · v0.3 2026-06-12 (USER: distribution-aware, P50+P90 columns, NpvFanChart bands) · v0.4 2026-06-12 (USER: scenario = price path × variant, DownsideRisk section, Q7 scenario-column framing) · v0.5 2026-06-12 (frontend-reviewer: M=1 honesty — suppressed cells not dashes, banner, cross-variant suppressed) · v0.6 2026-06-14 (D42 USER: config library first-class + two-mode discipline + 2D sizing sweep sub-mode + baseline re-designation freely re-settable + regime display bound to D39 R1/R2/R3 + naming fix: sample_kind for data-source provenance)*
