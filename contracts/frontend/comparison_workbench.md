# Frontend Contract — Comparison Workbench

> **Area:** frontend
> **Contract version:** v1.4.0-draft (Round 5 — finance-expert SC4 deltas 2/3/4: rule A/B explicit, bootstrap_ci NPV-only fixture, debt_metrics levered render spec + tests)
> **Status:** DRAFT — awaiting frontend-reviewer + finance-expert (SC4) gate
> **Branch:** `feat/frontend-comparison-workbench`
> **Owner:** frontend-engineer
> **Realizes:** docs/design/ux/comparison_workbench.md v0.7; LINEAGE D42; D43; D41; D39; **D45**
> **Finance-expert corrections applied (Round 2):**
>   - `sample_kind="bootstrap"` for R2 (not "synthetic")
>   - per-percentile `PercentileResult.confidence` field (cross-cutting)
>   - R1 = `single_trajectory` only; IRR/MIRR/LCOE/payback ABSENT at M=1
>   - R3 `p_irr_below_hurdle` IS populated (frequency count, honest at M≈10)
>   - R3 field names: `worst_case_npv_yuan` / `best_of_n_npv_yuan`; `cvar5_yuan = null`
>   - R3 P50 always `indicative_low_confidence`
>   - `deriveRegime` reads `FinanceResult.provenance.sample_kind` (nested path)
> **D43 applied:** config carries a comment THREAD (`ConfigComment[]`); `parent_param_delta` for fork provenance
> **D45 applied (Round 4+5):** `FinanceResultSummary` + related types (`PercentileResult`, `MetricPercentiles`, `SingleTrajectoryResult`, `DownsideRiskResult`, `DebtMetrics`) now REFERENCE `contracts/shared/finance_result_summary.md` v1.1.0 — NOT redefined here. Field-name deltas absorbed: `payback_yr` → `payback_discounted_yr`; `debt_metrics`/`view_ii_delta`/`schema_version` added. Round 5: rule A (confidence equal-across-metrics), rule B (bootstrap_ci NPV-only), levered render spec + tests (T-RULE-A/B, T-DEBT-1..5), `ComparisonTable.debt_toggle` prop.
> **Pending:** SC3 (dashboard-engineer chart interfaces) — non-blocking standing condition
> **Gate:** frontend-reviewer + finance-expert (SC4 — confirms this contract matches the locked D45 shape)
> **REBUILD_SPEC refs:** §3 (env), §5 (training), §13 (finance)
> **Depends on:**
> - **`contracts/shared/finance_result_summary.md` v1.1.0 (D45 LOCK)** — canonical `FinanceResultSummary` wire shape
> - `contracts/shared/telemetry_schema.md` v1.0.0 (D39 regime fields)
> - `contracts/frontend/design_system.md` (TOKEN system — no hex literals)
> - `contracts/frontend/stage_config.md` (Stage ① → config-library save flow)
> - `contracts/serving/compare_endpoints.md` (#134) — endpoint surface + `FinanceParamSet` → `FinanceConfig` mapping (§2.3)

---

## 1. Scope

This contract covers:
1. **Config Library** (`/configs`) — savable/forkable config catalog with comment threads (D43)
2. **Comparison Workbench** (`/compare`) — multi-config comparison in two modes (D42)
3. **Input-diff highlighting** — auto-detect which params differ; mute identical ones; winner-per-metric highlight; sortable table
4. **Finance params as instant tier** — live-scrubbable sliders; no re-sim; debounced recompute POST
5. **Sizing Sweep sub-mode** — 2D battery sizing surface/heatmap
6. **Shared state** — Zustand store + REST client hooks
7. **Chart interfaces** — props contract between workbench and dashboard-engineer

Out of scope: `SurfaceChart` and `NpvFanChart` implementation (dashboard-engineer); serving orchestration (serving-engineer); delta-accounting correctness (finance-expert); 3D / live telemetry (batch-only; D42).

---

## 2. Type definitions

### 2.1 Config annotation types (D43)

```typescript
/** A comment in the config's collaborative human+agent annotation thread (D43) */
export interface ConfigComment {
  id: string;               // server UUID
  author: "agent" | "human";
  timestamp: string;        // ISO 8601 UTC
  text: string;
}

/**
 * Structured param delta for forked configs — shows exactly what changed
 * relative to the parent config. Populated server-side on fork.
 */
export type ParamDelta = Record<
  string,
  { from: unknown; to: unknown; label: string; unit?: string }
>;
```

### 2.2 Config library types

```typescript
/** A saved site configuration — first-class artifact per D42 */
export interface SavedConfig {
  id: string;               // server UUID
  config_hash: string;      // deterministic SHA-256 of config content
  label: string;
  parent_id?: string;
  /** Structured param delta vs parent — populated when forked (D43) */
  parent_param_delta?: ParamDelta;
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
  /** Finance params embedded in the config (used as defaults; can be overridden in workbench) */
  finance_params: FinanceParamSet;
  policy_count: number;
  eval_count: number;
  /** Collaborative annotation thread (D43) — ordered chronologically, oldest first */
  comment_thread: ConfigComment[];
}

export type ConfigSortKey = "created_at" | "label" | "battery_energy_mwh";
```

### 2.3 Finance parameter types (instant tier ⚡)

Finance parameters are the **instant tier** — changing them triggers `POST /api/compare/finance`
on cached dispatch data with NO env re-run. Physical params (battery sizing, fleet counts) are NOT here.

> **Single-source note (D45 / rl-architect):** `FinanceParamSet` remains **frontend-owned** here (it is a UI representation of live-scrubbable parameters, not a pure wire type). The serving layer (#134 §2.3) single-sources the mapping from `FinanceParamSet` → `FinanceConfig` (the finance engine's request dataclass). #132 DEFINES `FinanceParamSet`; #134 §2.3 MAPS it. No redefinition in #134.

```typescript
/**
 * Scope determines whether a param applies uniformly across all configs
 * (for fair apples-to-apples comparison) or is independently set per config.
 *
 * D42 fairness defaults:
 *   market-rate params (r_f, ERP, beta → WACC, tax) → "common"
 *     (comparing configs with different market rates is misleading)
 *   financing-structure params (gearing, debt term) → "per_config"
 *     (each config may reflect a different financing plan)
 */
export type FinanceParamScope = "common" | "per_config";

export interface FinanceParamEntry<T = number> {
  value: T;
  scope: FinanceParamScope;
  unit?: string;        // display unit: "%" | "years" | "¥/MWh" | etc.
  min?: T;              // slider range
  max?: T;
  step?: T;
}

/** All finance params that are live-scrubbable without re-running the env (instant tier ⚡) */
export interface FinanceParamSet {
  // CAPM / market-rate params — default scope: "common"
  risk_free_rate_pct: FinanceParamEntry;        // r_f; unit: "%"
  equity_risk_premium_pct: FinanceParamEntry;   // ERP; unit: "%"
  beta: FinanceParamEntry;
  // cost_of_equity = r_f + β × ERP (CAPM-derived, shown read-only; can be overridden by wacc_pct)
  wacc_pct: FinanceParamEntry;                  // WACC override (can set directly); unit: "%"
  hurdle_rate_pct: FinanceParamEntry;           // for P(IRR<hurdle); unit: "%"
  inflation_pct: FinanceParamEntry;             // unit: "%"

  // Financing structure — default scope: "per_config"
  gearing_pct: FinanceParamEntry;               // D/(D+E); unit: "%"
  cost_of_debt_pct: FinanceParamEntry;          // LPR + spread; unit: "%"
  loan_term_years: FinanceParamEntry<number>;   // unit: "years"
  horizon_years: FinanceParamEntry<number>;     // unit: "years"

  // Tax — default scope: "common"
  tax_enabled: FinanceParamEntry<boolean>;
  corporate_tax_rate_pct: FinanceParamEntry;    // unit: "%"
}

/** Which tier a parameter change belongs to */
export type FinanceParamTier = "instant" | "re_sim";
```

### 2.4 Finance result types — D45 shared contract reference

> **SINGLE-SOURCE (D45 LOCK):** `FinanceResultSummary` and its constituent types are defined in
> **`contracts/shared/finance_result_summary.md` v1.1.0**. They are NOT redefined here.
> Redefining any of these in component code or another contract is a review-fail.
>
> **Import path (implementation):** from TypeScript types generated from the D45 shared contract.
> Do NOT import from local type definitions.

Types referenced from `contracts/shared/finance_result_summary.md` v1.1.0:

| Type | Summary |
|------|---------|
| `PercentileResult` | `{ value, confidence, bootstrap_ci? }`. `confidence` is PERCENTILE-LEVEL: at any given q, the value is IDENTICAL across all 5 distributional metrics — enforced by the engine (rule A). `bootstrap_ci` is NPV-ONLY: present ONLY on `npv_yuan` nodes; MUST be absent (undefined/null) on `irr_pct`, `mirr_pct`, `lcoe_yuan_per_mwh`, `payback_discounted_yr` nodes (rule B). |
| `MetricPercentiles` | `{ p50?, p75?, p90?, p95?, p99? }`. Presence is UNIFORM across metrics at same regime (rule C). |
| `SingleTrajectoryResult` | `{ point_npv_yuan, max_drawdown_yuan, max_drawdown_year, worst_year_cf_yuan }`. Present at ALL M; HEADLINE at R1. |
| `DownsideRiskResult` | `{ worst_case_npv_yuan, best_of_n_npv_yuan?, p_npv_neg, p_irr_below_hurdle, cvar5_yuan, max_drawdown_yuan, max_drawdown_year, worst_year_cf_yuan }` |
| `DebtMetrics` | `{ equity_irr_pct: number \| null, min_dscr: number \| null }` — null when `debt_toggle=false` |
| `FinanceResultSummary` | Canonical shape below. Read `.regime` directly (B2 resolution). |

Canonical `FinanceResultSummary` shape (from D45 §2 — summarized for this contract's readers):

```typescript
// ALL types below come from contracts/shared/finance_result_summary.md v1.1.0
// Do NOT redefine locally. Import from the shared types module.

interface FinanceResultSummary {
  schema_version: string;           // "1.1.0"
  /**
   * B2 RESOLUTION: Read DIRECTLY from the backend — NEVER recompute client-side.
   * Use deriveRegime() ONLY for raw PolicyEnsemble (where 'regime' is absent).
   */
  regime: FinanceRegime;
  provenance: {
    sample_kind: "bootstrap" | "empirical";  // #133 LOCK: "synthetic" is display only
    m_draws: number;
    distribution_valid: boolean;
    hurdle_rate_pct: number;      // % — the hurdle used for p_irr_below_hurdle
    valuation_date: string;       // ISO date
    horizon_years: number;
    seed: number;
    code_version: string;
  };
  /** Present at ALL M; HEADLINE at R1 (sole output); supplementary at R2/R3 */
  single_trajectory: SingleTrajectoryResult | null;
  // ── 5 distributional metrics (null at R1; metric-major — D45 orientation ruling) ──
  irr_pct:               MetricPercentiles | null;
  npv_yuan:              MetricPercentiles | null;   // ONLY metric with bootstrap_ci (rule B)
  mirr_pct:              MetricPercentiles | null;
  lcoe_yuan_per_mwh:     MetricPercentiles | null;
  payback_discounted_yr: MetricPercentiles | null;   // RENAMED from "payback_yr" (v1.2.0→v1.3.0)
  // ── Downside risk (null at R1; partial at R3) ──
  downside_risk: DownsideRiskResult | null;
  // ── Debt metrics (scalar, NOT distributional; null when debt_toggle=false) ──
  debt_metrics: DebtMetrics | null;
  // ── View-II incremental (null on View-I summaries) ──
  view_ii_delta: null | object;  // per-draw CRN diff P50 — D41 rule 7; null for View-I
  /** NPV fan re-discounting (R2 only; m_draws ≥ 2) */
  cash_flow_series_yuan?: number[][];
}
```

**Key deltas from v1.2.0 inline defs:**

| Delta | v1.2.0 | v1.3.0 (D45) |
|-------|---------|--------------|
| Payback field name | `payback_yr` | `payback_discounted_yr` |
| Debt metrics | absent | `debt_metrics: DebtMetrics \| null` |
| View-II delta | absent | `view_ii_delta` (null on View-I) |
| Schema version | absent | `schema_version: "1.1.0"` |
| Provenance | 3 fields | +`hurdle_rate_pct`, `valuation_date`, `horizon_years`, `seed`, `code_version` |
| `bootstrap_ci` | any metric (implicit) | NPV-ONLY (rule B); null on irr/mirr/lcoe/payback |
| Confidence scope | per-cell | PERCENTILE-LEVEL = equal across all metrics at same q (rule A) |

**Binding semantics rules** — see `contracts/shared/finance_result_summary.md` §3 (rules 1–11, all authoritative). Consumer MUST NOT render `indicative_low_confidence` as bold/headline (§13.10c); MUST display R3 frequencies as "X of N years" not smooth % (DV-8).

### 2.5 Finance regime (D39 binding — corrected)

```typescript
/**
 * Finance regime — D39 M-regime labels ONLY.
 *
 * NAMING DISCIPLINE (D42):
 *   "R1/R2/R3" = M-regime labels ONLY.
 *   Data-source provenance = provenance.sample_kind ("bootstrap" | "empirical").
 *   NEVER conflate these two axes in UI text or variable names.
 *
 * R1 = M=1 (distribution_valid=false)
 * R2 = M≥50 bootstrap (provenance.sample_kind="bootstrap")
 * R3 = M≈10 empirical (provenance.sample_kind="empirical")
 */
export type FinanceRegime = "R1" | "R2" | "R3";

/**
 * B2 RESOLUTION — Derive regime from RAW PolicyEnsemble provenance fields.
 * Use this ONLY when you do NOT yet have a FinanceResultSummary
 * (e.g. pre-eval display, or server-side when constructing the summary).
 *
 * When reading a FinanceResultSummary, read `.regime` directly — NEVER call this.
 * (D42(5) single-source: the backend sets regime; the frontend reads it.)
 */
export function deriveRegime(
  distribution_valid: boolean,
  sample_kind: "bootstrap" | "empirical"
): FinanceRegime {
  if (!distribution_valid) return "R1";
  if (sample_kind === "bootstrap") return "R2";
  return "R3";  // empirical
}

/**
 * B1 RESOLUTION — Resolve the comparison table's effective regime from a set of variants.
 * Result = MINIMUM regime (most conservative suppression) across all variant regimes.
 *
 * Severity ordering (most to least restrictive): R1 < R3 < R2
 *   R1 = most restrictive: single_trajectory only; ALL percentiles suppressed
 *   R3 = middle: P50 shown muted; tail percentiles + CVaR suppressed
 *   R2 = least restrictive: full distribution; no suppression
 *
 * Rules:
 * 1. The ENTIRE table uses this resolved regime — including the upside section.
 *    Per-column regime is rejected (Q5 CLOSED).
 * 2. Mixed-regime delta cells are SUPPRESSED (not just the banner):
 *    no delta is computed when one column's metric is populated and another's is suppressed.
 * 3. Default R2 when variants is empty or no variant has a finance_result.
 */
export function resolveComparisonRegime(variants: WorkbenchVariant[]): FinanceRegime {
  const severity: Record<FinanceRegime, number> = { R1: 0, R3: 1, R2: 2 };
  let min: FinanceRegime = "R2";
  for (const v of variants) {
    const r = v.finance_result?.regime;
    if (!r) continue;
    if (severity[r] < severity[min]) min = r;
  }
  return min;
}
```

### 2.6 Workbench mode types (D42)

```typescript
/**
 * Compare-designs: scenario LOCKED, design varies → clean design deltas
 * Press-test: design LOCKED, scenario varies → per-config sensitivity
 */
export type WorkbenchMode = "compare_designs" | "press_test";

/** Shared scenario — locked in compare_designs mode */
export interface SharedScenario {
  price_path_name: string;
  m_draws: number;
  sample_kind: "bootstrap" | "empirical"; // data-source provenance (NOT a regime label)
  wacc_pct: number;         // unit: %
  horizon_years: number;    // unit: years
}
```

### 2.7 Workbench variant types

```typescript
/** Policy reference — trained policy or named baseline agent */
export type PolicyRef =
  | { kind: "trained"; run_id: string; step: number }
  | { kind: "baseline"; agent_name: string };

/** Workbench execution tier (rl-architect v1.1 spine ruling) */
export type ExecutionTier =
  | "instant"          // ⚡ finance param only (no re-sim)
  | "fast"             // ⚡ CAPEX/OPEX — server-side finance recalc
  | "eval_needed"      // ▶ dispatch-relevant diff; vmapped batch eval
  | "retrain_required" // ⚠ no compatible policy
  | "running"          // ⏳ eval in progress
  | "unknown";         // plan not yet fetched

/** A single variant in the workbench */
export interface WorkbenchVariant {
  id: string;
  label: string;
  is_baseline: boolean;     // exactly one per workbench
  config_id: string;
  config_hash: string;
  policy: PolicyRef | null;
  eval_result_id: string | null;
  /**
   * Per-variant finance param overrides on top of the config's defaults.
   * null = use shared common params from useWorkbenchStore.sharedFinanceParams.
   * Partial = only override the specified keys; others fall back to shared params.
   */
  finance_params: Partial<FinanceParamSet> | null;
  /** Per-variant price path override — null in compare_designs mode (invariant) */
  price_path_name: string | null;
  tier: ExecutionTier;
  tier_duration_estimate_s: number | null;
  run_id: string | null;
  finance_result: FinanceResultSummary | null;
}
```

### 2.8 Input-diff types

```typescript
/** A single parameter comparison across all configs in the workbench */
export interface ConfigParamDiff {
  param_path: string;           // dot-notation, e.g. "site_summary.battery_energy_mwh"
  param_label: string;          // human-readable label
  param_tier: FinanceParamTier; // "instant" (finance param) or "re_sim" (physical param)
  unit?: string;
  /** Values keyed by config_id */
  values: Record<string, unknown>;
  /** true if at least two configs have different values for this param */
  differs: boolean;
}

/** Config diff summary — computed client-side from loaded configs whenever variants change */
export interface WorkbenchDiffSummary {
  differing_params: ConfigParamDiff[];     // params that differ (shown prominently)
  common_params: ConfigParamDiff[];        // params that are identical (collapsed/muted)
  finance_param_diffs: ConfigParamDiff[];  // subset of differing_params with tier="instant"
  physical_param_diffs: ConfigParamDiff[]; // subset with tier="re_sim"
}
```

### 2.9 Sizing sweep types

```typescript
export interface SizingSweepConfig {
  base_config_id: string;
  energy_mwh_min: number; energy_mwh_max: number; energy_steps: number;
  power_mw_min: number;   power_mw_max: number;   power_steps: number;
  metric: "npv_p50" | "irr_p50" | "lcoe";
}

export interface SizingSweepResult {
  run_id: string;
  status: "running" | "complete" | "error";
  configs_total: number; configs_done: number;
  energy_axis_mwh: number[]; power_axis_mw: number[];
  surface: number[][];        // [energy_idx][power_idx]
  surface_metric: "npv_p50" | "irr_p50" | "lcoe";
  regime: FinanceRegime;
  recommended_energy_idx: number; recommended_power_idx: number;
  /** M-draw NPV values at recommended point for hover histogram (R2 only) */
  recommended_distribution_yuan?: number[];
}
```

---

## 3. Store — `useWorkbenchStore` (Zustand)

Single Zustand store. No domain state in child components.

```typescript
interface WorkbenchStoreState {
  // Mode
  mode: WorkbenchMode;

  // Shared scenario (locked in compare_designs mode)
  sharedScenario: SharedScenario;

  /**
   * Shared finance params (market-rate; scope="common" by default).
   * Propagated to all variants where the matching param has scope="common".
   */
  sharedFinanceParams: FinanceParamSet;

  // Variants
  variants: WorkbenchVariant[];
  baselineId: string | null;

  /** Recomputed synchronously on every addVariant / removeVariant */
  diffSummary: WorkbenchDiffSummary | null;

  // Execution
  planLoading: boolean; planError: string | null;
  runLoading: boolean;  runError: string | null;
  /** Finance recompute loading state per variant_id (⚡ instant tier) */
  financeRecomputeLoading: Record<string, boolean>;

  // Sizing sweep
  sweepConfig: SizingSweepConfig | null;
  sweepResult: SizingSweepResult | null;
  sweepLoading: boolean; sweepError: string | null;
  sweepRunId: string | null; sweepPollActive: boolean;

  // UI state
  activeTab: "table" | "npv_fan" | "per_config" | "sizing_surface";
  showBands: boolean;               // sticky within session
  selectedVariantId: string | null;
  tableSortMetric: string | null;   // null = default order
  tableSortDir: "asc" | "desc";
  diffPanelShowAllParams: boolean;  // false = differing params only

  // Actions
  setMode(mode: WorkbenchMode): void;
  setSharedScenario(s: Partial<SharedScenario>): void;
  /** Update a shared (common-scope) finance param; triggers recompute on all variants */
  setSharedFinanceParam<K extends keyof FinanceParamSet>(
    key: K, value: FinanceParamSet[K]["value"]
  ): void;
  /** Update a per-variant finance param override */
  setVariantFinanceParam<K extends keyof FinanceParamSet>(
    variantId: string, key: K, value: FinanceParamSet[K]["value"], scope: FinanceParamScope
  ): void;
  addVariant(v: Omit<WorkbenchVariant, "id" | "tier" | "tier_duration_estimate_s" | "run_id" | "finance_result">): void;
  removeVariant(id: string): void;
  updateVariant(id: string, update: Partial<WorkbenchVariant>): void;
  designateBaseline(id: string): void;
  reorderVariants(orderedIds: string[]): void;
  clearAll(): void;

  // Async
  fetchExecutionPlan(): Promise<void>;
  runMissingEvals(): Promise<void>;
  pollRunStatus(runId: string): Promise<void>;
  /** ⚡ Instant tier — POST /api/compare/finance (SC5 confirmed); no env re-run */
  recomputeFinance(variantId: string): Promise<void>;
  submitSizingSweep(config: SizingSweepConfig): Promise<void>;
  pollSweepStatus(runId: string): Promise<void>;
  addSweepPointAsVariant(energy_idx: number, power_idx: number): void;
}
```

**State invariants:**
1. `variants.filter(v => v.is_baseline).length === 1` when `variants.length > 0`
2. `baselineId` references a valid `variant.id` when `variants.length > 0`
3. In `compare_designs` mode: `updateVariant(id, {price_path_name: X})` is a no-op — price_path_name stays null
4. `diffSummary` is recomputed synchronously on every `addVariant` / `removeVariant` call
5. `sharedFinanceParams` only propagates to variants where the matching param has `scope: "common"`
6. `financeRecomputeLoading[id] = true` during recompute; key deleted/false on complete or error

---

## 4. Component interfaces

### 4.1 Route-level
```typescript
export function ConfigLibraryPage(): JSX.Element;
export function ComparisonWorkbenchPage(): JSX.Element;
```

### 4.2 Config library
```typescript
export function ConfigLibrary(props: {
  onSelectForCompare: (configIds: string[]) => void;
}): JSX.Element;

export function ConfigCard(props: {
  config: SavedConfig;
  selected: boolean;
  onToggleSelect: () => void;
  onFork: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onPressTest: () => void;
}): JSX.Element;
// Shows: label, site_summary (battery MWh/MW, fleet), policy_count, eval_count
// If parent_id set: shows "Forked from [parent_label]" + param delta summary from parent_param_delta
// Shows latest comment from comment_thread + "[N comments]" expander

/** D43 — collaborative annotation thread (human + agent) */
export function ConfigCommentThread(props: {
  config_id: string;
  comments: ConfigComment[];
  onAddComment: (text: string) => void;
  loading: boolean;
}): JSX.Element;
// data-testid="comment-thread"
// Each entry: data-testid="comment-{id}", data-author="agent"|"human"
// Agent entries: "AI" badge (TOKEN.accentAmber)
// Human entries: inline textarea at bottom + [Post] button
```

### 4.3 Workbench shell
```typescript
/** Mode toggle — D42: always visible, never hidden */
export function WorkbenchModeSelector(props: {
  mode: WorkbenchMode;
  onChange: (mode: WorkbenchMode) => void;
}): JSX.Element;
// data-testid="mode-compare-designs", "mode-press-test"
// aria-pressed="true" on active; "false" on inactive
// Clicking active mode = no-op (does NOT call onChange)

/** Scenario lock bar (compare_designs mode) */
export function ScenarioLockBar(props: {
  scenario: SharedScenario;
  onUnlock: () => void;
}): JSX.Element;
// data-testid="scenario-lock-bar"
// Shows: 🔒, price_path_name, "M={m_draws}", "{wacc_pct}%"
// [Unlock → Press-test] button calls onUnlock

export function VariantList(props: {
  variants: WorkbenchVariant[];
  baselineId: string | null;
  mode: WorkbenchMode;
  onAddFromLibrary: () => void;
  onRunMissing: () => void;
  onOpenSizingSweep: () => void;
  runLoading: boolean; planLoading: boolean; planError: string | null;
}): JSX.Element;

export function VariantRow(props: {
  variant: WorkbenchVariant;
  isBaseline: boolean;
  onEdit: () => void;
  onDuplicate: () => void;
  onRemove: () => void;
  onDesignateBaseline: () => void;
}): JSX.Element;

export function VariantEditor(props: {
  variant: WorkbenchVariant | null;
  mode: WorkbenchMode;
  sharedScenario: SharedScenario;
  onSave: (v: WorkbenchVariant) => void;
  onCancel: () => void;
}): JSX.Element;

export function ExecutionPlanBadge(props: {
  tier: ExecutionTier;
  estimatedSeconds?: number;
}): JSX.Element;
// instant/fast   → "⚡ Instant"/"⚡ Fast (~Xs)" (blue TOKEN)
// eval_needed    → "▶ Eval needed (~Xmin)" (amber)
// retrain_required → "⚠ Retrain required" (red)
// running        → "⏳ Running…" (violet pulse)
// unknown        → "?" (textMuted)

export function AddToComparisonModal(props: {
  config_id: string;
  policy?: PolicyRef;
  eval_result_id?: string;
  finance_snapshot?: FinanceParamSet;
  onAdd: (label: string, asBaseline: boolean) => void;
  onCancel: () => void;
}): JSX.Element;
```

### 4.4 Input-diff highlighting (new)
```typescript
/**
 * Shows which INPUT params differ across compared configs.
 * "Delta-first": differing params at top (prominent); identical params collapsed below.
 * Winner-per-metric highlight in ComparisonTable (best value per result column).
 */
export function ConfigDiffPanel(props: {
  diffSummary: WorkbenchDiffSummary;
  showAllParams: boolean;
  onToggleShowAll: () => void;
}): JSX.Element;
// data-testid="config-diff-panel"
// data-testid="diff-param-{param_path}" for each differing param (with value per config)
// data-testid="common-param-count" shows "N params identical" + "[show all]" toggle
// Finance param diffs (tier="instant") labeled with "⚡" icon
// Physical param diffs (tier="re_sim") labeled with "▶ will re-sim"
```

### 4.5 Finance param editing (instant tier ⚡)
```typescript
/**
 * Live-scrubbable finance param panel.
 * Sliders debounced at 300ms → POST /api/compare/recompute-finance.
 * scope="common" params → update ALL variants simultaneously.
 * scope="per_config" params → update named variant only.
 */
export function FinanceParamPanel(props: {
  params: FinanceParamSet;
  mode: "shared" | "per_config";
  variantId?: string;
  onParamChange: (
    key: keyof FinanceParamSet,
    value: number | boolean,
    scope: FinanceParamScope
  ) => void;
  recomputeLoading: boolean;
}): JSX.Element;
// data-testid="finance-param-panel"
// Shows "⚡ INSTANT — updates live off cached dispatch" label
// Each slider: data-testid="finance-param-{key}", data-scope="common"|"per_config"

export function FinanceParamSlider(props: {
  paramKey: string;
  value: number;
  min: number; max: number; step: number;
  unit: string;
  scope: FinanceParamScope;
  label: string;
  recomputeLoading: boolean;
  onScopeToggle: () => void;
  onChange: (value: number) => void;
}): JSX.Element;
// data-testid="finance-param-slider-{paramKey}"
// data-testid="scope-toggle-{paramKey}" — toggles common ↔ per_config
// While recomputeLoading: shimmer on the value display
```

### 4.6 Results components
```typescript
export function ComparisonResultsTabs(props: {
  activeTab: WorkbenchStoreState["activeTab"];
  hasSizingSweepResult: boolean;
  onTabChange: (tab: WorkbenchStoreState["activeTab"]) => void;
}): JSX.Element;

/**
 * Three-section table (Upside / Downside Risk / Operational).
 * Regime-aware suppression AND per-percentile confidence-aware styling.
 * Delta-first: baseline column absolute; variant columns show delta + (absolute) subscript.
 * Winner highlight: ★ or subtle green on best value per row.
 * Sortable: clicking column header cycles asc→desc→default.
 */
export function ComparisonTable(props: {
  variants: WorkbenchVariant[];
  baselineId: string | null;
  regime: FinanceRegime;
  hurdle_rate_pct: number;     // unit: %
  sortMetric: string | null;
  sortDir: "asc" | "desc";
  onSort: (metric: string) => void;
  /** D45: show the levered view (Equity IRR + Min DSCR rows from debt_metrics) */
  debt_toggle: boolean;
}): JSX.Element;
// debt_toggle render rules (D45):
//   - Show debt rows only when debt_toggle=true AND variant.finance_result.debt_metrics != null
//   - data-testid="debt-equity-irr-row" (equity_irr_pct: scalar %, e.g. "9.8%"; higher=better)
//   - data-testid="debt-min-dscr-row"   (min_dscr: scalar ratio, e.g. "1.45×"; higher=better)
//   - Both are SCALAR (NOT distributional) — MUST NOT render P50/P75/P90 sub-rows
//   - delta coloring: data-delta-direction per §7.8 (higher=better → "good" if Δ>0)

export function PerConfigDetail(props: {
  variant: WorkbenchVariant;
  regime: FinanceRegime;
  onPressTest: () => void;
  onNext: () => void; onPrev: () => void;
  hasPrev: boolean; hasNext: boolean;
}): JSX.Element;

export function SizingSweepPanel(props: {
  sweepConfig: SizingSweepConfig | null;
  sweepResult: SizingSweepResult | null;
  sweepLoading: boolean; sweepError: string | null;
  onConfigChange: (config: SizingSweepConfig) => void;
  onSubmit: () => void;
  onAddPointAsVariant: (energy_idx: number, power_idx: number) => void;
}): JSX.Element;
// data-testid="sizing-sweep-panel", "sweep-run-button", "sweep-progress", "sweep-regime-banner"
```

---

## 5. Chart prop interfaces (pending dashboard-engineer confirmation — SC3)

```typescript
// [PENDING SC3: dashboard-engineer to confirm]
export interface SurfaceChartProps {
  energyAxis_mwh: number[];
  powerAxis_mw: number[];
  surface: number[][];
  metric: "npv_p50" | "irr_p50" | "lcoe";
  metric_unit: "¥M" | "%" | "¥/MWh";
  regime: FinanceRegime;
  recommendedPoint?: {
    energy_idx: number; power_idx: number;
    distribution_yuan?: number[];  // R2 hover histogram only
  };
  onPointHover?: (energy_idx: number, power_idx: number) => void;
  onPointSelect?: (energy_idx: number, power_idx: number) => void;
}

// [PENDING SC3: dashboard-engineer to confirm]
export interface NpvVariantSeries {
  id: string; label: string; is_baseline: boolean; color: string;
  rates_pct: number[];
  p50_npv_yuan: number[];
  p25_npv_yuan?: number[];
  p75_npv_yuan?: number[];
  p10_npv_yuan?: number[];
  p90_npv_yuan?: number[];
  irr_p50_pct?: number;
  irr_p90_pct?: number;  // absent at R1 and R3
}

export interface NpvFanChartProps {
  variants: NpvVariantSeries[];
  regime: FinanceRegime;
  wacc_ref_pct: number;
  showBands: boolean;
  xRange?: [number, number];
  onRateHover?: (rate_pct: number) => void;
}
```

---

## 6. REST client hooks

```typescript
export function useConfigLibrary(): {
  configs: SavedConfig[]; loading: boolean; error: string | null; refetch: () => void;
};
export function useSaveConfig(): {
  save: (config: SiteConfigPayload) => Promise<SavedConfig>;
  loading: boolean; error: string | null;
};
export function useForkConfig(): {
  fork: (config_id: string, label: string) => Promise<SavedConfig>;
  loading: boolean; error: string | null;
};

/** POST /api/configs/:id/comments — human-authored comment (D43) */
export function useAddComment(): {
  add: (config_id: string, text: string) => Promise<ConfigComment>;
  loading: boolean; error: string | null;
};

export function useExecutionPlan(): {
  fetchPlan: (variants: WorkbenchVariant[]) => Promise<ExecutionPlanResponse>;
  loading: boolean; error: string | null;
};
export function useCompareRun(): {
  submit: (variantIds: string[], sharedScenario: SharedScenario) => Promise<string>;
  poll: (runId: string, onComplete: (results: Record<string, FinanceResultSummary>) => void) => void;
  stopPolling: () => void;
  loading: boolean; error: string | null;
};

/**
 * Finance recompute — ⚡ INSTANT tier.
 * SC5 RESOLVED (serving-engineer confirmed): POST /api/compare/finance → FinanceResultSummary.
 * No env re-run. finance() called on cached PolicyEnsemble with new FinanceConfig.
 * Synchronous (HTTP 200 with result in body; < 100 ms on warm cache).
 *
 * Request:  { eval_result_id: string, finance_config: FinanceParamSet }
 *   eval_result_id = WorkbenchVariant.eval_result_id (server-side cache key — NOT variant.id)
 *
 * Errors:
 *   404 { code: "EVAL_RESULT_NOT_FOUND" } — cache evicted or invalid ID
 *   → UI must warn user "result expired — re-run eval" and offer [Re-run] CTA.
 *
 * [Cache lifecycle — PolicyEnsemble eviction policy TBD: serving-engineer flagged as needing
 *  rl-architect DECISION before contracts/serving/compare_endpoints.md (SC2) is filed.
 *  Does NOT block this frontend contract.]
 */
export function useFinanceRecompute(): {
  recompute: (eval_result_id: string, finance_config: FinanceParamSet) => Promise<FinanceResultSummary>;
  loading: boolean; error: string | null;
};

export function useSizingSweep(): {
  submit: (config: SizingSweepConfig) => Promise<string>;
  poll: (runId: string, onUpdate: (result: SizingSweepResult) => void) => void;
  stopPolling: () => void;
  loading: boolean; error: string | null;
};
```

**Polling interval:** 5000 ms for `useCompareRun` and `useSizingSweep`.
**Finance recompute:** single POST (no polling); debounced at 300 ms on slider drag.
**No WebSocket** — workbench is batch-only (D42).

---

## 7. Behavior specifications

### 7.1 Mode switching (D42)

**Compare-designs → Press-test:**
- If `variants.length > 1`: prompt "Press-test which config?" — user picks one; others archived.
- `sharedScenario` preserved; scenario controls become editable.

**Press-test → Compare-designs:**
- If per-scenario edits exist: warn + confirm; clear `price_path_name` overrides; re-lock.

**Mode selector:** always visible; never hidden.

### 7.2 Baseline re-designation

`designateBaseline(id)` → sets exactly one `is_baseline`; all delta cells recompute from store state; no API call.

### 7.3 Regime display (D39 binding — corrected per finance-expert)

**Regime detection (read from `FinanceResultSummary.provenance`):**
```
distribution_valid=false                       → R1
distribution_valid=true, sample_kind="bootstrap" → R2
distribution_valid=true, sample_kind="empirical" → R3
```

**Per-percentile confidence rendering (applies at ALL regimes — cross-cutting rule):**
- `confidence="sound"` → render normally; can be bold/headline
- `confidence="indicative_low_confidence"` → MUST be muted; append `"(indicative)"` inline; MUST NOT be bold/headline; MUST NOT be primary cell focus

**R1 (M=1, `distribution_valid=false`):**
- Show: `single_trajectory.point_npv_yuan` labeled **"NPV (single scenario)"** (NOT "P50")
- Show: `single_trajectory.max_drawdown_yuan`, `max_drawdown_year`, `worst_year_cf_yuan`
- Suppress ALL `MetricPercentiles` fields (IRR, MIRR, LCOE, payback — `null` in schema at R1)
- Suppress: entire `downside_risk` block (`null` at R1)
- Suppressed cells: exact string `"— (M > 1 required)"` + tooltip
- Banner: `"M=1 — single scenario; risk distribution requires an ensemble (M ≥ 50)."`

**R2 (M≥50, `sample_kind="bootstrap"`):**
- Show: IRR, NPV, MIRR, LCOE, payback at P50/P75/P90/P95 (all `confidence="sound"`)
- Show: P99 if present → styled `indicative_low_confidence`
- Show: full `downside_risk` block (all fields present)
- No suppression banner

**R3 (M≈10, `sample_kind="empirical"`):**
- Show: P50 of each metric → styled `indicative_low_confidence` (muted + `"(indicative)"`)
- Suppress: P75/P90/P95/P99 (absent in schema) → cells show `"— (tail-suppressed)"`
- Show `downside_risk` partial:
  - `worst_case_npv_yuan` (worst-of-N runs)
  - `best_of_n_npv_yuan` (best-of-N runs)
  - `p_npv_neg` (frequency count — honest at M≈10)
  - `p_irr_below_hurdle` — **PRESENT at R3**; displayed as frequency (e.g. "3/10 runs below hurdle")
  - `cvar5_yuan = null` → suppressed as `"— (tail-suppressed)"`
- Banner: `"Empirical ensemble (M≈10 real years) — tail percentiles + CVaR suppressed; worst/best of N + loss frequencies shown."`

**Mixed-regime rule (Q5 CLOSED — whole-table-min):**
- `resolveComparisonRegime(variants)` returns R1 < R3 < R2 minimum across all variants
- The **entire table** uses this resolved regime — including the upside section
- **Per-column regime is rejected** — a delta between a suppressed and populated metric is undefined
- **Mixed-regime delta cells are SUPPRESSED** (not just the banner):
  when one column's metric is populated and another's is suppressed, NO delta is rendered (show `"—"`)

**R3 frequency display (DV-8):**
`p_npv_neg` and `p_irr_below_hurdle` at R3 MUST be displayed as `"X of N observed years"`
(e.g. `"2 of 10 years = 20%"`), NOT as a smooth percentage like `"20.0%"`.
Resolution = 1/M = 10 percentage points at M≈10; a decimal percentage falsely implies sub-1pp precision.
Compute X = round(p * m_draws), format as `"{X} of {m_draws} years"`.

### 7.4 Input-diff highlighting

`diffSummary` is computed synchronously on every `addVariant` / `removeVariant`:
- Walk each param in `SavedConfig.site_summary` + `finance_params` across all loaded configs
- `differs = true` iff ≥ 2 configs have different values for this param
- `ConfigDiffPanel`: differing params first (prominent); identical params collapsed
- **Winner per metric** in `ComparisonTable`: best variant per row gets `★` or subtle green highlight
  - Highest IRR P50 = winner for IRR row; lowest LCOE P50 = winner for LCOE row
  - Lowest `p_npv_neg` = winner for downside risk row
- Table is **sortable** by any metric column: header click cycles asc→desc→default; client-side only (no API)

### 7.5 Finance params — instant tier (⚡)

Slider `onChange` debounced at 300 ms → `recomputeFinance(variantId)` → `POST /api/compare/finance` (SC5 confirmed):
- **No env re-run** — `finance()` called on cached `PolicyEnsemble`; only FinanceConfig changes
- `financeRecomputeLoading[variantId] = true` during POST; result cells show subtle shimmer
- **Scope rules (D42 fairness):**
  - `scope="common"` param: `setSharedFinanceParam` propagates to ALL variants; each triggers individual recompute
  - `scope="per_config"` param: `setVariantFinanceParam` updates only the named variant
  - Scope toggle per param in `FinanceParamPanel`; tooltip explains default

### 7.6 Config comment thread (D43)

- `comment_thread` rendered chronologically (oldest first)
- Agent comments (`author: "agent"`): auto-appended by backend when agent proposes/refines a config; tagged "AI" (TOKEN.accentAmber)
- Human comments (`author: "human"`): inline textarea at thread bottom; `[Post]` → `POST /api/configs/:id/comments`
- Workbench variant row: latest comment truncated to 1 line + `[N comments]` expander
- Compare view: `ConfigDiffPanel` shows latest comment per config alongside param diffs
- `parent_param_delta` shown as structured diff summary (NOT in comment thread): `"Forked from [parent_label]: battery_energy_mwh 300→400 MWh, gearing_pct 60→70%"`

### 7.8 Delta direction-of-good and coloring (B3 resolution)

Per-metric rules for delta cell coloring. A positive arithmetic delta is NOT always good.

| Metric | Display unit | Direction | Δ = (variant − baseline) | Positive Δ = good? |
|--------|-------------|-----------|--------------------------|---------------------|
| IRR P50/P90 | pp (percentage points) | higher = better | Δ in pp | ✓ green |
| MIRR P50 | pp | higher = better | Δ in pp | ✓ green |
| NPV P50/P90 | ¥M | higher = better | Δ in ¥M | ✓ green |
| LCOE P50 | ¥/MWh | **lower = better** | Δ in ¥/MWh | ✗ red; **negative Δ = green** |
| Payback (discounted) P50 | years | **lower = better** | Δ in years | ✗ red; **negative Δ = green** |
| P(NPV<0) | % (display from fraction) | **lower = better** | Δ in pp | ✗ red; **negative Δ = green** |
| P(IRR<hurdle) | % (display from fraction) | **lower = better** | Δ in pp | ✗ red; **negative Δ = green** |
| CVaR-5% | ¥M | higher = better (less negative) | Δ in ¥M | ✓ green |
| Worst NPV | ¥M | higher = better (less negative) | Δ in ¥M | ✓ green |
| Max drawdown | ¥M | higher = better (less negative) | Δ in ¥M | ✓ green |
| Best-of-N NPV | ¥M | higher = better | Δ in ¥M | ✓ green |
| Equity IRR (`debt_metrics.equity_irr_pct`) | pp | higher = better | Δ in pp | ✓ green |
| Min DSCR (`debt_metrics.min_dscr`) | × (ratio) | higher = better | Δ in × | ✓ green |

> **Debt metrics note (D45):** `DebtMetrics` fields are SCALAR (engine emits float means, not distributions). Render only when `debt_toggle=true` AND `debt_metrics != null`; hide entire debt rows otherwise. No regime-conditional logic needed.
>
> **Levered-view render spec (D45):**
> - `equity_irr_pct` (unit: %) → display as `"X.X%"` · `data-testid="debt-equity-irr-row"` · `data-direction="higher-better"`
> - `min_dscr` (unit: ratio ×) → display as `"X.XX×"` · `data-testid="debt-min-dscr-row"` · `data-direction="higher-better"`
> - MUST NOT render P50/P75/P90 sub-rows — these are scalars, not distributions
> - Delta: `data-delta-direction` follows §7.8 derivation rule (higher-better → "good" if Δ>0)
> - Guard: if `debt_metrics.equity_irr_pct == null` or `debt_metrics.min_dscr == null` (levered inputs incomplete), render cell as `"—"` with `data-testid` still present
>
> **Rule A (confidence equal-across-metrics):** At any given `q`, `irr_pct.{q}.confidence == npv_yuan.{q}.confidence` (all 5 distributional metrics share one confidence per percentile row, set by the engine). The UI MUST read confidence from each node individually — do NOT assume they differ; do NOT hard-code regime→confidence mapping. If a mismatch is detected (data integrity bug), log a `console.warn` and render the more conservative value (`"indicative_low_confidence"` wins).
>
> **Rule B (bootstrap_ci NPV-ONLY):** `bootstrap_ci` is computed by the engine exclusively for `npv_yuan` (used in the NPV-fan chart). It is absent (`undefined`) on `irr_pct`, `mirr_pct`, `lcoe_yuan_per_mwh`, and `payback_discounted_yr` nodes. The UI MUST NOT attempt to read `bootstrap_ci` from non-`npv_yuan` nodes. The NPV-fan chart reads `npv_yuan.{p50..p95}.bootstrap_ci`.

Two attributes govern coloring in `ComparisonTable` — both are required:

**`data-direction` (static, on metric row headers)** — intrinsic direction of the metric:
- `"higher-better"` — IRR, MIRR, NPV, CVaR-5%, Worst NPV, Best-of-N NPV, Max drawdown, Worst-year CF, Equity IRR, Min DSCR
- `"lower-better"` — LCOE, Payback (discounted), P(NPV<0), P(IRR<hurdle)

**`data-delta-direction` (computed, on individual delta cells)** — semantic verdict for THIS cell (mirrors §15 `data-confidence`):
- `"good"` → render green (improvement vs baseline)
- `"bad"` → render red (regression vs baseline)
- `"neutral"` → no color (zero or suppressed delta)

Derivation rule:
```
data-delta-direction =
  if delta == 0 or suppressed: "neutral"
  elif data-direction == "higher-better" and delta > 0: "good"
  elif data-direction == "lower-better"  and delta < 0: "good"
  else: "bad"
```

Coloring MUST derive from `data-delta-direction`, never from arithmetic sign alone.
Tests pin `data-delta-direction` (T-DELTA-5, T-DELTA-7, T-DELTA-8).

**Unit guards (hard errors in tests):**
- IRR/MIRR deltas: **pp** (percentage points), NOT raw percent. 8.7% − 8.2% = +0.5 pp, label "+0.5 pp"
- P(NPV<0)/P(IRR<hurdle) deltas: **pp**, NOT decimal fraction. (0.18 − 0.24) × 100 = −6 pp
- LCOE: **¥/MWh**, NOT ¥/kWh. 300 ¥/MWh ≠ 0.300 ¥/kWh (1 MWh = 1000 kWh unit trap)
- NPV deltas: formatted as ¥M (e.g. `"+¥16.0M"`), NOT raw yuan strings

**CRN delta rule (D41 binding):** when comparing two configs in the workbench,
NPV/IRR deltas displayed in the table MUST use per-draw CRN differences:
```
delta_m = metric(A)_m − metric(B)_m    for m = 1…M
displayed_delta = percentile(delta_m array)    (e.g. P50 of differences)
```
NOT the naive delta-of-percentiles (P50_A − P50_B), which overstates significance.
Prerequisite: both variants share the same CRN seed and M draws.
If regimes differ or CRN is not shared: show columns side-by-side with NO delta rendered.

### 7.7 Sizing sweep

- `energy_steps` and `power_steps` ∈ [2, 20]; UI clamps; error shown if invalid
- Total configs = energy_steps × power_steps; shown before Run button
- Progress: `"Running… {configs_done}/{configs_total} configs"`
- Surface rendered on `status=complete` only (no partial renders)
- Recommended point: ◎ marker; hover at R2 = distribution histogram from `recommended_distribution_yuan`
- "Add to comparison" → `addSweepPointAsVariant(energy_idx, power_idx)` → auto-label `"Battery {E} MWh × {P} MW"`

---

## 8. Deliberate deviations

| Code | What | Why |
|------|------|-----|
| DV-1 | `WorkbenchModeSelector` uses `aria-pressed` buttons | Two-state toggle; matches design affordance better than `fieldset/radio` |
| DV-2 | Finance recompute is single POST (no polling) | `finance()` on cached M=50 ensemble < 1 s; no need for async job |
| DV-3 | Sliders debounced at 300 ms | Prevent API spam on continuous drag |
| DV-4 | Per-variant price path HIDDEN (not disabled) in compare_designs | Hidden = it doesn't exist; disabled = temporarily unavailable |
| DV-5 | R3 P50 shown muted (not hidden) | Hiding implies no data; muted + caveat is more informative/honest |
| DV-6 | Table sort is client-side | Finance results already in store; sort = pure render re-order; no API call |
| DV-7 | `p_irr_below_hurdle` shown as frequency at R3 | Finance-expert: frequency count is honest at M≈10; CVaR tail not credible but loss-count is |
| DV-8 | R3 frequencies rendered as `"X of N years"` not `"X.0%"` | Resolution = 1/M = 10 pp at M≈10; decimal % falsely implies sub-1pp precision |
| DV-9 | `single_trajectory` shown as HEADLINE at R1; secondary context at R2/R3 | Backend provides it at all M; display role differs by regime — sole output at R1 |

---

## 9. Out of scope (v1)

- Saved/named comparisons (`/compare/:id`) — v2
- PDF export — v2
- Per-variant M override — v2
- Cross-variant weather-mode comparison — v2
- `SurfaceChart` and `NpvFanChart` implementation — dashboard-engineer
- Agent-authored comments API (serving-engineer owns the comment POST endpoint)

---

## 10. Open gates

**SC1** — Config library endpoints (`GET /api/configs`, `POST /api/configs`, `POST /api/configs/:id/fork`, `POST /api/configs/:id/comments`) — serving-engineer. **Blocks implementation.**

**SC2** — Compare endpoints (`POST /api/compare/plan`, `POST /api/compare/run`, `GET /api/compare/run/:id/status`) — serving-engineer. **Blocks implementation.**

**SC3** — `SurfaceChartProps` + `NpvFanChartProps` — dashboard-engineer confirmation. **Blocks chart integration.**

**SC4** — Finance-expert regime display confirmation. **RESOLVED in v1.1.0** — corrections applied; R1 single_trajectory only; R3 p_irr_below_hurdle present; sample_kind="bootstrap" for R2; per-percentile confidence.

**SC5 RESOLVED** — `POST /api/compare/finance` (confirmed by serving-engineer): synchronous, request `{ eval_result_id, finance_config }`, 404 `{ code: "EVAL_RESULT_NOT_FOUND" }`. Applied in §6 `useFinanceRecompute` and §7.5.
**Open sub-question:** PolicyEnsemble cache eviction policy (serving-engineer flagged; needs rl-architect DECISION). Blocks `contracts/serving/compare_endpoints.md` (SC2) but does **NOT** block this frontend contract.

**Q5 CLOSED** — Whole-table-min is correct. `resolveComparisonRegime(variants)` (R1 < R3 < R2) governs the entire table including upside columns. Per-column regime rejected. Mixed-regime delta cells suppressed. See §2.5 `resolveComparisonRegime` and §7.3.

**Q6 CLOSED** — `p_irr_below_hurdle` at R3 has NO per-field `confidence` tag (finance-expert confirmed). Use panel-level R3 caveat banner instead (already specified in R3 banner text in §7.3). No `indicative_low_confidence` on `DownsideRiskResult` fields.

---

*contracts/frontend/comparison_workbench.md — v1.2.0-draft — frontend-engineer — 2026-06-14*
*D42 (comparison workbench model), D43 (config comment thread), D41 (battery config-level compare), D39 (regime display)*
*Round 2 corrections: sample_kind="bootstrap" for R2; PercentileResult.confidence; R1=single_trajectory only; R3 p_irr_below_hurdle present; field names corrected; deriveRegime updated.*
*Round 3 (B1): Q5 CLOSED — resolveComparisonRegime() whole-table-min (R1<R3<R2); delta suppression rule; R3 frequency display "X of N years".*
*Round 3 (B2): Q6 CLOSED — FinanceResultSummary.regime read directly from backend; deriveRegime = raw PolicyEnsemble mapper only.*
*Round 3 (B3): §7.8 direction-of-good per metric (LCOE/payback/P-metrics lower-better); unit guards (pp, ¥/MWh); CRN delta rule (D41).*
*Round 3 (SC5): endpoint confirmed POST /api/compare/finance; eval_result_id; cache-lifetime DECISION pending (rl-architect).*
*Round 3 (finance-expert precision): single_trajectory present at all M; best_of_n R3-only; cvar5 R2-only.*
