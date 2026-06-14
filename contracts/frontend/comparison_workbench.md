# Frontend Contract — Comparison Workbench

> **Area:** frontend
> **Contract version:** v1.0.0-draft
> **Status:** DRAFT — awaiting frontend-reviewer gate
> **Branch:** `feat/frontend-comparison-workbench`
> **Owner:** frontend-engineer
> **Realizes:** docs/design/ux/comparison_workbench.md v0.6; LINEAGE D42; D41 (battery config-level compare); D39 (regime display)
> **Pending inputs:** finance-expert regime-tag → display mapping confirmation; dashboard-engineer SurfaceChart + NpvFanChart prop-interface confirmation (marked `[PENDING]` in §5 and §6)
> **Reviewer:** frontend-reviewer
> **REBUILD_SPEC refs:** §3 (env), §5 (training), §13 (finance)
> **Depends on:**
> - `contracts/shared/telemetry_schema.md` v1.0.0 (D39 regime fields: `distribution_valid`, `sample_kind`)
> - `contracts/frontend/design_system.md` (TOKEN color system — no hex literals in this contract's components)
> - `contracts/frontend/stage_config.md` (StageOneConfig → config-library save flow)
> - Serving contracts (design-level only in §6; serving-engineer owns `contracts/serving/compare_*.md`)

---

## 1. Scope

This contract covers:
1. **Config Library** (`/configs` route) — the savable/forkable config catalog
2. **Comparison Workbench** (`/compare` route) — multi-config comparison in two modes
3. **Sizing Sweep sub-mode** — 2D battery sizing surface/heatmap inside the workbench
4. **Shared state** — the workbench Zustand store + REST client hooks
5. **Chart interfaces** — the props contracts between workbench and dashboard-engineer's charts

Out of scope:
- Implementation of `SurfaceChart` and `NpvFanChart` (dashboard-engineer)
- Serving-layer orchestration (serving-engineer)
- Delta-accounting correctness (finance-expert)
- 3D scene / live telemetry (workbench is batch-only, no WebSocket, no telemetry store — D42)

---

## 2. Type definitions

### 2.1 Config library types

```typescript
/** A saved site configuration — first-class artifact per D42 */
export interface SavedConfig {
  id: string;               // server UUID
  config_hash: string;      // deterministic SHA-256 of config content
  label: string;            // user-given name (editable)
  parent_id?: string;       // set when forked from another config
  created_at: string;       // ISO 8601 UTC
  site_summary: {
    site_id: string;
    battery_energy_mwh: number;   // unit: MWh
    battery_power_mw: number;     // unit: MW
    wind_count: number;
    pv_count: number;
    pcc_device_id: string;
    tariff_region: string;
  };
  policy_count: number;     // number of trained policies using this config
  eval_count: number;       // number of eval results using this config
}

export type ConfigSortKey = "created_at" | "label" | "battery_energy_mwh";
```

### 2.2 Workbench variant types

```typescript
/** Policy reference — either a trained policy or a named baseline agent */
export type PolicyRef =
  | { kind: "trained"; run_id: string; step: number }
  | { kind: "baseline"; agent_name: string };

/** Finance assumptions snapshot for a variant */
export interface FinanceSnapshot {
  wacc_pct: number;       // e.g. 7.0 (percent, not fraction); unit: %
  horizon_years: number;  // e.g. 20; unit: years
  price_path_name: string;
  /** Any per-variant overrides beyond the shared path */
  overrides?: Record<string, unknown>;
}

/** Workbench execution tier (rl-architect v1.1 spine ruling) */
export type ExecutionTier =
  | "instant"          // Tier (a)0: finance assumptions only, same eval
  | "fast"             // Tier (a)1: CAPEX/OPEX change, server-side finance recalc
  | "eval_needed"      // Tier (b)2: dispatch-relevant diff; vmapped batch eval
  | "retrain_required" // Tier (c)3: no compatible policy
  | "running"          // Tier (b)2 in progress
  | "unknown";         // execution plan not yet fetched

/** A single variant in the workbench */
export interface WorkbenchVariant {
  id: string;                          // workbench-local UUID
  label: string;                       // e.g. "Baseline", "A (SST)"
  is_baseline: boolean;                // exactly one per workbench
  config_id: string;                   // from config library
  config_hash: string;                 // for verification
  policy: PolicyRef | null;
  eval_result_id: string | null;
  finance: FinanceSnapshot | null;     // null = use shared assumptions
  price_path_name: string | null;      // null = use shared path
  tier: ExecutionTier;
  tier_duration_estimate_s: number | null; // from /api/compare/plan
  run_id: string | null;               // if Tier (b) eval running
  finance_result: FinanceResultSummary | null;
}

/** Finance result as the workbench sees it (read from the backend) */
export interface FinanceResultSummary {
  regime: FinanceRegime;               // "R1" | "R2" | "R3" — from distribution_valid + sample_kind
  sample_kind: "synthetic" | "empirical"; // D39 — NOT labelled R1/R2/R3; data source provenance
  m_draws: number;
  // Upside metrics (unit: % for IRR/MIRR; ¥ for NPV; ¥/MWh for LCOE; years for payback)
  irr_p50_pct: number | null;
  irr_p90_pct: number | null;         // null when regime = R1 or R3
  npv_p50_yuan: number | null;
  npv_p90_yuan: number | null;        // null when regime = R1 or R3
  mirr_p50_pct: number | null;
  lcoe_yuan_per_mwh: number | null;
  payback_p50_yr: number | null;
  // Worst single-year (always available when m_draws >= 1)
  worst_year_cashflow_yuan: number | null;
  max_drawdown_yuan: number | null;   // peak-to-trough capital drawdown; unit: ¥
  // Downside risk (null when regime = R1; partial at R3 per §8.3)
  worst_npv_yuan: number | null;      // min NPV across M draws
  best_npv_yuan: number | null;       // max NPV across M draws (R3 only label)
  p_npv_negative_pct: number | null;  // P(NPV<0) as percentage 0–100
  p_irr_below_hurdle_pct: number | null; // null at R1 and R3
  cvar_5pct_yuan: number | null;      // null at R1 and R3
  // Cash flow series for client-side NPV fan re-discounting
  cash_flow_series_yuan?: number[][];  // [m][year] — present when M > 1 and regime = R2
}
```

### 2.3 Finance regime type (D39 binding)

```typescript
/**
 * Finance regime — D39 M-regime labels ONLY.
 * NAMING: "R1/R2/R3" are reserved for M-regime; data-source provenance
 * uses sample_kind ("synthetic" | "empirical"). Never conflate these two axes.
 *
 * R1 = M=1 (distribution_valid=false)      → point estimates only
 * R2 = M≥50 bootstrap (sample_kind="synthetic") → full distribution
 * R3 = M≈10 empirical (sample_kind="empirical") → partial; no tail percentiles
 */
export type FinanceRegime = "R1" | "R2" | "R3";

/** Derive regime from backend fields (single source of truth = backend) */
export function deriveRegime(
  distribution_valid: boolean,
  sample_kind: "synthetic" | "empirical"
): FinanceRegime {
  if (!distribution_valid) return "R1";
  if (sample_kind === "empirical") return "R3";
  return "R2";
}
```

### 2.4 Workbench mode types (D42)

```typescript
/**
 * Compare-designs: scenario LOCKED, design varies → clean design deltas
 * Press-test: design LOCKED, scenario varies → per-config sensitivity
 */
export type WorkbenchMode = "compare_designs" | "press_test";

/** Shared scenario — locked in compare_designs mode */
export interface SharedScenario {
  price_path_name: string;
  m_draws: number;          // ensemble size
  sample_kind: "synthetic" | "empirical"; // data source (NOT regime label)
  wacc_pct: number;         // unit: %
  horizon_years: number;    // unit: years
}
```

### 2.5 Sizing sweep types (D42 §7)

```typescript
export interface SizingSweepConfig {
  base_config_id: string;
  energy_mwh_min: number;   // unit: MWh
  energy_mwh_max: number;
  energy_steps: number;     // number of grid points on energy axis
  power_mw_min: number;     // unit: MW
  power_mw_max: number;
  power_steps: number;
  metric: "npv_p50" | "irr_p50" | "lcoe";
}

export interface SizingSweepResult {
  run_id: string;
  status: "running" | "complete" | "error";
  configs_total: number;
  configs_done: number;
  energy_axis_mwh: number[];      // ordered grid; unit: MWh
  power_axis_mw: number[];        // ordered grid; unit: MW
  surface: number[][];            // [energy_idx][power_idx] — metric value
  surface_metric: "npv_p50" | "irr_p50" | "lcoe";
  regime: FinanceRegime;          // applies uniformly to all grid points
  recommended_energy_idx: number; // index into energy_axis_mwh
  recommended_power_idx: number;  // index into power_axis_mw
  // M-draw values at the recommended point for hover distribution (R2 only)
  recommended_distribution_yuan?: number[];
}
```

---

## 3. Store — `useWorkbenchStore` (Zustand)

Single Zustand store for the entire workbench. No local state in child components for domain data.

```typescript
interface WorkbenchStoreState {
  // Mode
  mode: WorkbenchMode;

  // Scenario (locked in compare_designs mode)
  sharedScenario: SharedScenario;

  // Variants
  variants: WorkbenchVariant[];
  baselineId: string | null;        // id of the variant marked is_baseline

  // Execution
  planLoading: boolean;
  planError: string | null;
  runLoading: boolean;
  runError: string | null;

  // Sizing sweep
  sweepConfig: SizingSweepConfig | null;
  sweepResult: SizingSweepResult | null;
  sweepLoading: boolean;
  sweepError: string | null;
  sweepRunId: string | null;
  sweepPollActive: boolean;

  // UI state
  activeTab: "table" | "npv_fan" | "per_config" | "sizing_surface";
  showBands: boolean;               // NpvFanChart band toggle; sticky per session
  selectedVariantId: string | null; // for per-config detail tab

  // Actions
  setMode(mode: WorkbenchMode): void;
  setSharedScenario(scenario: Partial<SharedScenario>): void;
  addVariant(variant: Omit<WorkbenchVariant, "id" | "tier" | "tier_duration_estimate_s" | "run_id" | "finance_result">): void;
  removeVariant(id: string): void;
  updateVariant(id: string, update: Partial<WorkbenchVariant>): void;
  designateBaseline(id: string): void;  // re-designate baseline; flips all deltas
  reorderVariants(orderedIds: string[]): void;
  clearAll(): void;

  // Async actions
  fetchExecutionPlan(): Promise<void>;
  runMissingEvals(): Promise<void>;
  pollRunStatus(runId: string): Promise<void>;
  submitSizingSweep(config: SizingSweepConfig): Promise<void>;
  pollSweepStatus(runId: string): Promise<void>;
  addSweepPointAsVariant(energy_idx: number, power_idx: number): void;
}
```

**State invariants:**
- `variants.filter(v => v.is_baseline).length === 1` when `variants.length > 0` (exactly one baseline at all times)
- `baselineId` references a valid `variant.id` when `variants.length > 0`
- In `compare_designs` mode: `variants.every(v => v.price_path_name === null || v.price_path_name === sharedScenario.price_path_name)` — per-variant price path overrides are disallowed in this mode
- `showBands` persists for the browser session (not reset on tab switch)

**Baseline re-designation** (`designateBaseline`):
- Sets `is_baseline = true` on the new baseline, `false` on all others
- Updates `baselineId`
- All delta values in `ComparisonTable` recalculate automatically because they derive from store state
- No API call — pure client-side state change (finance results already cached)

---

## 4. Component interfaces

### 4.1 Route-level components

```typescript
/** /configs route */
export function ConfigLibraryPage(): JSX.Element;

/** /compare route */
export function ComparisonWorkbenchPage(): JSX.Element;
```

### 4.2 Config Library components

```typescript
export function ConfigLibrary(props: {
  onSelectForCompare: (configIds: string[]) => void; // navigates to /compare
}): JSX.Element;

export function ConfigCard(props: {
  config: SavedConfig;
  selected: boolean;
  onToggleSelect: () => void;
  onFork: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onPressTest: () => void;  // → /compare in press_test mode with this config
}): JSX.Element;
```

### 4.3 Workbench shell components

```typescript
/** Mode toggle: "Compare designs" vs "Press-test" (D42 — always visible) */
export function WorkbenchModeSelector(props: {
  mode: WorkbenchMode;
  onChange: (mode: WorkbenchMode) => void;
}): JSX.Element;
// data-testid="mode-compare-designs" and data-testid="mode-press-test"
// Active: aria-pressed="true"; Inactive: aria-pressed="false"

/** Scenario lock bar (compare_designs mode only) */
export function ScenarioLockBar(props: {
  scenario: SharedScenario;
  onUnlock: () => void; // switches to press_test mode
}): JSX.Element;
// data-testid="scenario-lock-bar"
// Shows lock icon + scenario summary + [Unlock → Press-test] button

/** Variant/config list panel */
export function VariantList(props: {
  variants: WorkbenchVariant[];
  baselineId: string | null;
  mode: WorkbenchMode;
  onAddFromLibrary: () => void;
  onRunMissing: () => void;
  onOpenSizingSweep: () => void;
  runLoading: boolean;
  planLoading: boolean;
  planError: string | null;
}): JSX.Element;

/** Single variant row */
export function VariantRow(props: {
  variant: WorkbenchVariant;
  isBaseline: boolean;
  onEdit: () => void;
  onDuplicate: () => void;
  onRemove: () => void;
  onDesignateBaseline: () => void;  // context-menu action
}): JSX.Element;

/** Variant editor (inline expansion or side panel — frontend contract v1 = inline) */
export function VariantEditor(props: {
  variant: WorkbenchVariant | null; // null = new variant
  mode: WorkbenchMode;
  sharedScenario: SharedScenario;
  onSave: (variant: WorkbenchVariant) => void;
  onCancel: () => void;
}): JSX.Element;

/** Tier status chip */
export function ExecutionPlanBadge(props: {
  tier: ExecutionTier;
  estimatedSeconds?: number;
}): JSX.Element;
// "instant"          → "⚡ Instant" (blue token)
// "fast"             → "⚡ Fast (~Xs)" (blue)
// "eval_needed"      → "▶ Eval needed (~Xmin)" (amber)
// "retrain_required" → "⚠ Retrain required" (red)
// "running"          → "⏳ Running…" (violet pulse)
// "unknown"          → "?" (textMuted)

/** Lightweight modal for wizard → workbench entry points */
export function AddToComparisonModal(props: {
  config_id: string;
  policy?: PolicyRef;
  eval_result_id?: string;
  finance_snapshot?: FinanceSnapshot;
  onAdd: (label: string, asBaseline: boolean) => void;
  onCancel: () => void;
}): JSX.Element;
```

### 4.4 Results components

```typescript
/** Tab bar: Table | NPV vs Rate | Per-config detail | Sizing Surface */
export function ComparisonResultsTabs(props: {
  activeTab: WorkbenchStoreState["activeTab"];
  hasSizingSweepResult: boolean;
  onTabChange: (tab: WorkbenchStoreState["activeTab"]) => void;
}): JSX.Element;

/**
 * Three-section comparison table (Upside / Downside Risk / Operational).
 * Regime-aware: suppresses metrics per §8 — suppressed cells show the exact
 * string `"— (M > 1 required)"` (R1) or `"— (tail-suppressed)"` (R3) with tooltip.
 */
export function ComparisonTable(props: {
  variants: WorkbenchVariant[];
  baselineId: string | null;
  regime: FinanceRegime;
  hurdle_rate_pct: number; // for P(IRR<hurdle) label; unit: %
}): JSX.Element;

/**
 * Single-config drill-down.
 * Shows DownsideRiskPanel FIRST (regime-aware suppression).
 * Includes "Press-test this config ▶" button at the bottom.
 */
export function PerConfigDetail(props: {
  variant: WorkbenchVariant;
  regime: FinanceRegime;
  onPressTest: () => void;
  onNext: () => void;
  onPrev: () => void;
  hasPrev: boolean;
  hasNext: boolean;
}): JSX.Element;
```

### 4.5 Sizing sweep components

```typescript
/** Sizing sweep config form + progress + SurfaceChart mount point */
export function SizingSweepPanel(props: {
  sweepConfig: SizingSweepConfig | null;
  sweepResult: SizingSweepResult | null;
  sweepLoading: boolean;
  sweepError: string | null;
  onConfigChange: (config: SizingSweepConfig) => void;
  onSubmit: () => void;
  onAddPointAsVariant: (energy_idx: number, power_idx: number) => void;
}): JSX.Element;
// data-testid="sizing-sweep-panel"
// data-testid="sweep-run-button"
// data-testid="sweep-progress" (shows "Running… X/N configs")
// data-testid="sweep-regime-banner" (when regime != R2)
```

---

## 5. Chart prop interfaces (locked with dashboard-engineer)

*[PENDING dashboard-engineer confirmation — marked below. These interfaces will be finalized and the `[PENDING]` annotations removed before the reviewer gate closes, or in a follow-up commit to this branch.]*

### 5.1 SurfaceChart

Rendered by dashboard-engineer inside `SizingSweepPanel`:

```typescript
// [PENDING: dashboard-engineer to confirm shape]
export interface SurfaceChartProps {
  /** Energy axis values; unit: MWh */
  energyAxis_mwh: number[];
  /** Power axis values; unit: MW */
  powerAxis_mw: number[];
  /**
   * Metric values at each grid point: surface[energy_idx][power_idx].
   * Unit: ¥M for npv_p50; % for irr_p50; ¥/MWh for lcoe.
   */
  surface: number[][];
  metric: "npv_p50" | "irr_p50" | "lcoe";
  metric_unit: "¥M" | "%" | "¥/MWh";
  regime: FinanceRegime;
  recommendedPoint?: {
    energy_idx: number;
    power_idx: number;
    /** M-draw NPV values for hover histogram — only when regime = R2 */
    distribution_yuan?: number[];
  };
  onPointHover?: (energy_idx: number, power_idx: number) => void;
  onPointSelect?: (energy_idx: number, power_idx: number) => void;
}
```

### 5.2 NpvFanChart

Rendered by dashboard-engineer inside `ComparisonResultsTabs`:

```typescript
// [PENDING: dashboard-engineer to confirm shape; especially cash-flow vs pre-computed NPV series]
export interface NpvVariantSeries {
  id: string;
  label: string;
  is_baseline: boolean;
  /** Hex color from TOKEN system */
  color: string;
  /**
   * Pre-computed NPV at each discount rate (client re-discounted from
   * cash_flow_series_yuan if available; else server-computed).
   * All arrays must have length === rates_pct.length.
   */
  rates_pct: number[];                 // e.g. [3,4,5,...,15]; unit: %
  p50_npv_yuan: number[];             // unit: ¥
  p25_npv_yuan?: number[];            // absent when regime = R1 or R3
  p75_npv_yuan?: number[];
  p10_npv_yuan?: number[];
  p90_npv_yuan?: number[];
  /** IRR x-intercept markers (NPV=0 crossing) */
  irr_p50_pct?: number;
  irr_p90_pct?: number;               // absent when regime = R1 or R3
}

export interface NpvFanChartProps {
  variants: NpvVariantSeries[];
  regime: FinanceRegime;
  wacc_ref_pct: number;
  /** Sticky within session per store.showBands */
  showBands: boolean;
  /** Default [3, 15]; unit: % */
  xRange?: [number, number];
  onRateHover?: (rate_pct: number) => void;
}
```

---

## 6. REST client hooks

```typescript
/**
 * Config library operations
 */
export function useConfigLibrary(): {
  configs: SavedConfig[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
};

export function useSaveConfig(): {
  save: (config: SiteConfigPayload) => Promise<SavedConfig>;
  loading: boolean;
  error: string | null;
};

export function useForkConfig(): {
  fork: (config_id: string, label: string) => Promise<SavedConfig>;
  loading: boolean;
  error: string | null;
};

/**
 * Workbench execution plan
 * POST /api/compare/plan → ExecutionPlanResponse
 */
export function useExecutionPlan(): {
  fetchPlan: (variants: WorkbenchVariant[]) => Promise<ExecutionPlanResponse>;
  loading: boolean;
  error: string | null;
};

/**
 * Batch eval submission and polling
 * POST /api/compare/run → {run_id}
 * GET /api/compare/run/:run_id/status → {status, results_by_variant_id}
 */
export function useCompareRun(): {
  submit: (variantIds: string[], sharedScenario: SharedScenario) => Promise<string>;
  poll: (runId: string, onComplete: (results: Record<string, FinanceResultSummary>) => void) => void;
  stopPolling: () => void;
  loading: boolean;
  error: string | null;
};

/**
 * Sizing sweep
 * POST /api/compare/sizing-sweep → {run_id}
 * GET /api/compare/sizing-sweep/:run_id/status → SizingSweepResult
 */
export function useSizingSweep(): {
  submit: (config: SizingSweepConfig) => Promise<string>;
  poll: (runId: string, onUpdate: (result: SizingSweepResult) => void) => void;
  stopPolling: () => void;
  loading: boolean;
  error: string | null;
};
```

**Polling interval:** 5000 ms (5 s) for both `useCompareRun` and `useSizingSweep`.
**Poll stop condition:** `status === "complete"` or `status === "error"`.
**No WebSocket** — the workbench is batch-only (D42; no live telemetry store accessed).

---

## 7. Behavior specifications

### 7.1 Mode switching (D42)

**Compare-designs → Press-test:**
- If `variants.length > 1`: prompt "Press-test which config?" — user picks one; other variants are moved to an "archived" list (accessible via "Restore for comparison") so they can be re-added.
- If `variants.length === 1`: switch directly.
- `sharedScenario` is preserved; scenario controls become editable.

**Press-test → Compare-designs:**
- If per-scenario edits exist: warn "Switching back resets scenarios to the shared default. Continue?"
- On confirm: clear per-variant price_path overrides; re-lock the scenario panel.

**Mode selector visibility:** always visible; never hidden or disabled.

### 7.2 Baseline re-designation

- `designateBaseline(id)` can be called at any time (context menu on any variant row).
- All delta cells in `ComparisonTable` update immediately (pure re-render from new `baselineId`).
- No API call required — finance results are cached in `variant.finance_result`.
- The new baseline's column switches from delta display to absolute display.
- The old baseline's column switches from absolute to delta vs the new baseline.

### 7.3 Regime display enforcement

The `ComparisonTable` must enforce the following rules exactly (single source of truth = the `regime` prop derived via `deriveRegime()` from `FinanceResultSummary`):

**R1 (M=1):**
- P90 columns: cells show `"— (M > 1 required)"` (exact string); tooltip: `"Risk distribution metrics require M ≥ 50. Run with a larger ensemble."`
- Downside Risk section: all four cells (Worst NPV, P(NPV<0), P(IRR<hurdle), CVaR-5%) show `"— (M > 1 required)"`
- Regime banner shown above table header
- Deltas on suppressed cells: also suppressed as `"—"`

**R2 (M≥50):**
- No suppression; all metric columns shown
- No banner

**R3 (M≈10):**
- P90 upside columns: cells show `"— (tail-suppressed)"` with tooltip explaining nearest-rank issue at M≈10
- Downside Risk: Worst NPV (= `worst_npv_yuan`) and Best NPV (= `best_npv_yuan`) and P(NPV<0) shown
- Downside Risk: P(IRR<hurdle) and CVaR-5%: `"— (tail-suppressed)"`
- Regime banner shown above table header
- Deltas on suppressed cells: suppressed

**Mixed-regime comparison:** when the workbench compares a variant at R2 against a variant at R1 (e.g., baseline ran M=50, variant A ran M=1), the entire table uses the MINIMUM regime (most conservative suppression). The header shows "⚠ Some variants have M=1 — all risk metrics suppressed. Re-run with M ≥ 50 to unlock."

### 7.4 Sizing sweep behavior

- Sweep form: energy_steps and power_steps must both be ≥ 2 and ≤ 20 (UI clamps; error shown if invalid).
- Total configs = energy_steps × power_steps; shown as "X configs" beside the [Run sweep] button.
- On submit: the sweep run_id is stored in the workbench store; polling begins at 5 s intervals.
- Progress bar shows: `"Running… {configs_done}/{configs_total} configs (est. Xmin)"`.
- The surface is rendered as soon as `sweepResult.surface` is non-null (partial results are NOT shown — only complete surface).
- Recommended-point marker shown as a ◎ symbol at the `recommended_energy_idx × recommended_power_idx` grid cell.
- Hover over a non-recommended point: shows tooltip with the metric value. No distribution histogram at R1 or R3.
- Hover over the recommended point at R2: shows distribution histogram from `recommended_distribution_yuan`.
- "Add to comparison" click on a point: calls `addSweepPointAsVariant(energy_idx, power_idx)` which creates a new workbench variant with auto-label `"Battery {E} MWh × {P} MW"`.

### 7.5 Variant editor constraints

- In `compare_designs` mode: per-variant price path override is HIDDEN (not disabled — just not shown). Only shared price path applies.
- In `press_test` mode: per-variant price path override is shown and editable.
- `POST /api/compare/plan` is called on every meaningful field change in the variant editor to show the updated tier before saving.

### 7.6 Config library entry point

- Wizard Stage ① "Save & Continue" auto-saves to config library (serving-engineer gate).
- A config saved from the wizard is auto-named `"{site_id}-v{N}"` where N increments per site.
- Multi-select: selecting N ≥ 2 configs → "Compare N configs ▶" button navigates to `/compare` and adds them as variants.
- Selecting 1 config → "Press-test ▶" is the primary action.

---

## 8. Deliberate deviations

| Code | What | Why |
|------|------|-----|
| DV-1 | `WorkbenchModeSelector` uses `aria-pressed` buttons (not radio inputs) | Mode is a two-state UI control with distinct visual affordances; `role="button"` + `aria-pressed` matches the design better than a `fieldset/input[type=radio]` group and is accessible |
| DV-2 | Polling uses `setInterval` rather than WebSocket | D42: workbench is batch-only; no live telemetry feed; a 5 s poll interval is sufficient for batch eval progress |
| DV-3 | `PerConfigDetail` does not show the raw cash-flow series | The `NpvFanChart` client-side re-discount is handled by dashboard-engineer's chart component; this component only passes `cash_flow_series_yuan` to the chart |
| DV-4 | In compare_designs mode, per-variant price path overrides are HIDDEN not disabled | Hidden = the choice never exists in this mode; disabled would imply it's temporarily unavailable |
| DV-5 | Chart prop interfaces marked `[PENDING]` | Dashboard-engineer confirmation required before these interfaces are locked; the tests will use stub chart components until confirmed |

---

## 9. Out of scope (v1)

- Saved/named comparisons (`/compare/:comparison_id`) — v2
- PDF export — v2 (CSV export only in v1)
- Per-variant M override — v2 (M is a workbench-level parameter)
- Cross-variant weather-mode comparison (synthetic vs empirical in the same table) — v2
- Workbench WebSocket / live results — never (batch-only by D42 design)
- The `SurfaceChart` and `NpvFanChart` implementation — dashboard-engineer
- The `DownsideRiskPanel` component reuse details — covered by `contracts/frontend/live_dashboard.md`

---

## 10. Open questions (gates)

**Q1 — Serving contract for config library:** `GET /api/configs`, `POST /api/configs`, `POST /api/configs/:id/fork` are needed before implementation. These are serving-engineer's responsibility. The frontend contract is complete but implementation is BLOCKED until serving files `contracts/serving/config_library.md` (or equivalent). Mark SC1.

**Q2 — Serving contract for compare endpoints:** `POST /api/compare/plan`, `POST /api/compare/run`, `GET /api/compare/run/:run_id/status`, `POST /api/compare/finance`, `POST /api/compare/sizing-sweep` — serving-engineer owns these. Mark SC2.

**Q3 — Chart interface confirmation:** Dashboard-engineer must confirm or revise `SurfaceChartProps` and `NpvFanChartProps` in §5 before these are locked. Mark SC3.

**Q4 — Finance-expert regime display confirmation:** Finance-expert must confirm the R1/R2/R3 suppression rules in §7.3 are correct per D39 (specifically: R3 partial downside panel — which fields, and field names in `FinanceResultSummary`). Mark SC4.

**Q5 — Mixed-regime behavior:** when baseline = R2 and a variant = R1 (or vice versa), the table uses minimum regime (most conservative). Is this correct, or should each column use its own regime? Flagged for finance-expert + frontend-reviewer. Proposed: use minimum regime for the shared Downside Risk section; per-column regime for the Upside section. This avoids the "delta on suppressed vs non-suppressed" problem.

---

*contracts/frontend/comparison_workbench.md — v1.0.0-draft — frontend-engineer — 2026-06-14*
*D42 (comparison workbench model), D41 (battery config-level compare), D39 (regime display)*
