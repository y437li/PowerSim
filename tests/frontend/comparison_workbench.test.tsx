/**
 * Test suite: comparison_workbench.test.tsx
 * Contract: contracts/frontend/comparison_workbench.md v1.2.0-draft
 *
 * Tests must be RED until implementation. Do NOT modify approved tests to make them pass.
 * Reviewer-added cases marked: // reviewer:
 *
 * Round 2 amendments (2026-06-14):
 *   - Fixtures corrected: sample_kind="bootstrap" (not "synthetic") for R2
 *   - FINANCE_RESULT_R1 restructured: single_trajectory only; irr_pct=null (absent at M=1)
 *   - FINANCE_RESULT_R3 corrected: worst_case_npv_yuan / best_of_n_npv_yuan;
 *       p_irr_below_hurdle IS present (not null); cvar5_yuan=null
 *   - New §15: per-percentile confidence styling
 *   - New §16: input-diff highlighting (ConfigDiffPanel)
 *   - New §17: finance param instant tier (FinanceParamPanel)
 *   - New §18: D43 config comment thread
 *
 * Round 3 amendments (2026-06-14 — B1/B2/B3 resolution):
 *   - Added resolveComparisonRegime import (§2.5)
 *   - New §1bis: resolveComparisonRegime tests (T-RESOLVE-1..5) — B1 whole-table-min
 *   - T-R3-8 added: R3 frequency display as "X of N years" not smooth % (DV-8)
 *   - T-DELTA-5..7 added: direction-of-good (LCOE lower-better); unit guard (¥/MWh not ¥/kWh);
 *       mixed-regime delta suppression — B3 resolution
 *   - Fixtures updated: FINANCE_RESULT_R2 and R3 have non-null single_trajectory
 *       (finance-expert: backend provides it at ALL M, not R1-only)
 *   - best_of_n_npv_yuan: R3 only; cvar5_yuan: R2 only (gated by regime in fixtures)
 */

import React from "react";
import { render, screen, fireEvent, waitFor, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi, type Mock } from "vitest";

// Import under test (will fail until implemented — RED is correct)
import {
  deriveRegime,
  resolveComparisonRegime,   // B1: resolveComparisonRegime — whole-table-min
  type FinanceRegime,
  type WorkbenchMode,
  type WorkbenchVariant,
  type FinanceResultSummary,
  type SingleTrajectoryResult,
  type DownsideRiskResult,
  type PercentileResult,
  type MetricPercentiles,
  type SavedConfig,
  type ConfigComment,
  type ConfigParamDiff,
  type WorkbenchDiffSummary,
  type SizingSweepResult,
  type SharedScenario,
  type FinanceParamSet,
} from "../../src/types/workbench";
import { useWorkbenchStore } from "../../src/stores/workbenchStore";
import { WorkbenchModeSelector } from "../../src/components/workbench/WorkbenchModeSelector";
import { ScenarioLockBar } from "../../src/components/workbench/ScenarioLockBar";
import { ComparisonTable } from "../../src/components/workbench/ComparisonTable";
import { ExecutionPlanBadge } from "../../src/components/workbench/ExecutionPlanBadge";
import { VariantRow } from "../../src/components/workbench/VariantRow";
import { SizingSweepPanel } from "../../src/components/workbench/SizingSweepPanel";
import { AddToComparisonModal } from "../../src/components/workbench/AddToComparisonModal";
import { ConfigCard } from "../../src/components/workbench/ConfigCard";
import { PerConfigDetail } from "../../src/components/workbench/PerConfigDetail";
import { ConfigCommentThread } from "../../src/components/workbench/ConfigCommentThread";
import { ConfigDiffPanel } from "../../src/components/workbench/ConfigDiffPanel";
import { FinanceParamPanel } from "../../src/components/workbench/FinanceParamPanel";
import { FinanceParamSlider } from "../../src/components/workbench/FinanceParamSlider";

// ─── Fixtures ────────────────────────────────────────────────────────────────

/**
 * CORRECTED: sample_kind="bootstrap" (not "synthetic") — D42 naming discipline.
 * "bootstrap" = block-bootstrap M≥50 synthetic draws → R2.
 * "empirical" = M≈10 real ERA5 years → R3.
 */
const SHARED_SCENARIO_R2: SharedScenario = {
  price_path_name: "declining-real",
  m_draws: 50,
  sample_kind: "bootstrap",  // CORRECTED: was "synthetic" in v1.0.0
  wacc_pct: 7.0,
  horizon_years: 20,
};

/**
 * R2 finance result — M≥50 bootstrap (CORRECTED from v1.0.0):
 * - sample_kind: "bootstrap" (not "synthetic")
 * - nested PercentileResult shape with .value + .confidence
 * - downside_risk block uses worst_case_npv_yuan / p_irr_below_hurdle (fraction)
 * - Round 3: single_trajectory is non-null (finance-expert precision note B:
 *   backend provides it at ALL M, not R1-only; primary display at R1 only)
 */
const FINANCE_RESULT_R2: FinanceResultSummary = {
  regime: "R2",
  provenance: {
    sample_kind: "bootstrap",    // CORRECTED
    m_draws: 50,
    distribution_valid: true,
  },
  // Non-null at R2 (finance-expert: backend provides single_trajectory at ALL M).
  // At R2 it supplements the percentile view but is NOT the primary cell.
  single_trajectory: {
    point_npv_yuan: 142_000_000,
    max_drawdown_yuan: 842_000_000,
    max_drawdown_year: 3,
    worst_year_cf_yuan: -12_000_000,
  },
  irr_pct: {
    p50: { value: 8.2, confidence: "sound" },
    p75: { value: 7.9, confidence: "sound" },
    p90: { value: 7.6, confidence: "sound" },
    p95: { value: 7.2, confidence: "sound" },
    // p99 would be indicative_low_confidence if present
  },
  npv_yuan: {
    p50: { value: 142_000_000, confidence: "sound" },
    p90: { value: 118_000_000, confidence: "sound" },
  },
  mirr_pct: {
    p50: { value: 7.1, confidence: "sound" },
  },
  lcoe_yuan_per_mwh: {
    p50: { value: 312, confidence: "sound" },
  },
  payback_yr: {
    p50: { value: 8.3, confidence: "sound" },
  },
  downside_risk: {
    worst_case_npv_yuan: -38_000_000,   // CORRECTED: was "worst_npv_yuan"
    p_npv_neg: 0.18,                    // fraction 0-1; display as 18%
    p_irr_below_hurdle: 0.24,           // fraction 0-1; display as 24%
    cvar5_yuan: -76_000_000,
    max_drawdown_yuan: 842_000_000,
    max_drawdown_year: 3,
    worst_year_cf_yuan: -12_000_000,
  },
};

/**
 * R1 finance result — M=1 single scenario (CORRECTED from v1.0.0):
 * CRITICAL: single_trajectory ONLY. IRR/MIRR/LCOE/payback are ABSENT at M=1.
 * irr_pct = null, npv_yuan = null, etc.
 * point_npv_yuan is labeled "NPV (single scenario)" NOT "P50".
 * downside_risk = null.
 */
const FINANCE_RESULT_R1: FinanceResultSummary = {
  regime: "R1",
  provenance: {
    sample_kind: "bootstrap",    // doesn't matter at R1 (distribution_valid=false)
    m_draws: 1,
    distribution_valid: false,   // KEY: this triggers R1 regime
  },
  single_trajectory: {
    point_npv_yuan: 142_000_000,  // labeled "NPV (single scenario)" — NOT "P50"
    max_drawdown_yuan: 842_000_000,
    max_drawdown_year: 3,
    worst_year_cf_yuan: -12_000_000,
  },
  irr_pct: null,             // ABSENT at M=1 — IRR not available
  npv_yuan: null,            // ABSENT at M=1 — use single_trajectory.point_npv_yuan
  mirr_pct: null,
  lcoe_yuan_per_mwh: null,
  payback_yr: null,
  downside_risk: null,       // ABSENT at M=1
};

/**
 * R3 finance result — M≈10 empirical years (CORRECTED from v1.0.0):
 * - P50 values are always indicative_low_confidence at R3
 * - downside_risk: worst_case_npv_yuan / best_of_n_npv_yuan (CORRECTED field names)
 * - p_irr_below_hurdle IS PRESENT at R3 (finance-expert correction; was null in v1.0.0)
 * - cvar5_yuan = null (PRESENT R2 ONLY; null at R3 — gate by regime, not truthiness)
 * - best_of_n_npv_yuan: PRESENT R3 ONLY (gate by regime, not truthiness)
 * - Round 3: single_trajectory non-null (finance-expert: backend provides at all M)
 */
const FINANCE_RESULT_R3: FinanceResultSummary = {
  regime: "R3",
  provenance: {
    sample_kind: "empirical",
    m_draws: 10,
    distribution_valid: true,
  },
  // Non-null at R3 (finance-expert precision note B)
  single_trajectory: {
    point_npv_yuan: 135_000_000,
    max_drawdown_yuan: 890_000_000,
    max_drawdown_year: 4,
    worst_year_cf_yuan: -15_000_000,
  },
  irr_pct: {
    p50: { value: 7.9, confidence: "indicative_low_confidence" },  // ALWAYS indicative at R3
    // p75/p90/p95/p99 absent at R3
  },
  npv_yuan: {
    p50: { value: 135_000_000, confidence: "indicative_low_confidence" },
  },
  mirr_pct: {
    p50: { value: 6.8, confidence: "indicative_low_confidence" },
  },
  lcoe_yuan_per_mwh: {
    p50: { value: 318, confidence: "indicative_low_confidence" },
  },
  payback_yr: {
    p50: { value: 8.7, confidence: "indicative_low_confidence" },
  },
  downside_risk: {
    worst_case_npv_yuan: -45_000_000,   // CORRECTED: was "worst_npv_yuan"
    best_of_n_npv_yuan: 195_000_000,    // CORRECTED: was "best_npv_yuan"; R3 only
    p_npv_neg: 0.20,                    // 2/10 runs; display as 20%
    p_irr_below_hurdle: 0.30,           // CORRECTED: WAS null in v1.0.0; IS present at R3 (3/10 runs)
    cvar5_yuan: null,                   // null at R3 (M≈10 too small for CVaR)
    max_drawdown_yuan: 890_000_000,
    max_drawdown_year: 4,
    worst_year_cf_yuan: -15_000_000,
  },
};

/** Default stub for FinanceParamSet (minimal; real implementation fills in all fields) */
const STUB_FINANCE_PARAMS: FinanceParamSet = {
  risk_free_rate_pct: { value: 2.5, scope: "common", unit: "%", min: 0, max: 10, step: 0.1 },
  equity_risk_premium_pct: { value: 6.0, scope: "common", unit: "%", min: 0, max: 15, step: 0.1 },
  beta: { value: 1.0, scope: "common", min: 0, max: 3, step: 0.05 },
  wacc_pct: { value: 7.0, scope: "common", unit: "%", min: 3, max: 20, step: 0.1 },
  hurdle_rate_pct: { value: 7.0, scope: "common", unit: "%", min: 3, max: 20, step: 0.1 },
  inflation_pct: { value: 2.5, scope: "common", unit: "%", min: 0, max: 10, step: 0.1 },
  gearing_pct: { value: 60, scope: "per_config", unit: "%", min: 0, max: 90, step: 1 },
  cost_of_debt_pct: { value: 4.5, scope: "per_config", unit: "%", min: 0, max: 15, step: 0.1 },
  loan_term_years: { value: 15, scope: "per_config", unit: "years", min: 5, max: 30, step: 1 },
  horizon_years: { value: 20, scope: "per_config", unit: "years", min: 10, max: 40, step: 1 },
  tax_enabled: { value: true, scope: "common" },
  corporate_tax_rate_pct: { value: 25, scope: "common", unit: "%", min: 0, max: 45, step: 1 },
};

function makeVariant(overrides: Partial<WorkbenchVariant> = {}): WorkbenchVariant {
  return {
    id: "var-baseline",
    label: "Baseline",
    is_baseline: true,
    config_id: "cfg-gansu-v1",
    config_hash: "#a1b2c3",
    policy: { kind: "trained", run_id: "run-001", step: 2_400_000 },
    eval_result_id: "eval-001",
    finance_params: null,     // uses shared params
    price_path_name: null,
    tier: "instant",
    tier_duration_estimate_s: null,
    run_id: null,
    finance_result: FINANCE_RESULT_R2,
    ...overrides,
  };
}

function makeSavedConfig(overrides: Partial<SavedConfig> = {}): SavedConfig {
  return {
    id: "cfg-gansu-v1",
    config_hash: "#a1b2c3",
    label: "Gansu-v1",
    created_at: "2026-06-10T00:00:00Z",
    site_summary: {
      site_id: "gansu",
      battery_energy_mwh: 300,
      battery_power_mw: 150,
      wind_count: 100,
      pv_count: 50,
      pcc_device_id: "pcc-substation-945mw",
      tariff_region: "cn-gansu",
    },
    finance_params: STUB_FINANCE_PARAMS,
    policy_count: 2,
    eval_count: 3,
    comment_thread: [],       // D43: empty thread by default
    ...overrides,
  };
}

function makeComment(overrides: Partial<ConfigComment> = {}): ConfigComment {
  return {
    id: "cmt-001",
    author: "agent",
    timestamp: "2026-06-10T12:00:00Z",
    text: "Optimal C-rate at this E/P ratio based on dispatch analysis.",
    ...overrides,
  };
}

// ─── §1. deriveRegime (pure function) ────────────────────────────────────────

describe("§1 deriveRegime — D39 regime derivation", () => {
  it("T-REGIME-1: distribution_valid=false → R1 regardless of sample_kind", () => {
    // R1 = M=1 (point estimate). Backend sets distribution_valid=false.
    // CORRECTED: sample_kind arg is now "bootstrap" | "empirical" (not "synthetic")
    expect(deriveRegime(false, "bootstrap")).toBe("R1");
    expect(deriveRegime(false, "empirical")).toBe("R1");
  });

  it("T-REGIME-2: distribution_valid=true + sample_kind=bootstrap → R2", () => {
    // R2 = M≥50 block-bootstrap synthetic draws
    // CORRECTED: was "synthetic" in v1.0.0; correct value is "bootstrap"
    expect(deriveRegime(true, "bootstrap")).toBe("R2");
  });

  it("T-REGIME-3: distribution_valid=true + sample_kind=empirical → R3", () => {
    // R3 = M≈10 real ERA5 years
    expect(deriveRegime(true, "empirical")).toBe("R3");
  });

  // reviewer: naming discipline guard
  it("T-REGIME-4: deriveRegime return is a regime label; sample_kind is NOT a regime label", () => {
    const regime = deriveRegime(true, "bootstrap");
    expect(regime).not.toBe("bootstrap");  // "bootstrap" is provenance, not regime
    expect(regime).not.toBe("empirical");
    expect(["R1", "R2", "R3"]).toContain(regime);
  });
});

// ─── §1bis. resolveComparisonRegime (B1 resolution) ─────────────────────────

describe("§1bis resolveComparisonRegime — B1: whole-table-min regime (R1 < R3 < R2)", () => {
  /**
   * resolveComparisonRegime returns the minimum regime across all variants.
   * Severity: R1 (most restrictive) < R3 < R2 (least restrictive).
   * Used to determine ComparisonTable suppression for the entire table.
   */

  it("T-RESOLVE-1: all R2 variants → effective regime = R2 (no suppression)", () => {
    const variants = [
      makeVariant({ id: "v1", is_baseline: true,  finance_result: FINANCE_RESULT_R2 }),
      makeVariant({ id: "v2", is_baseline: false, finance_result: FINANCE_RESULT_R2 }),
    ];
    expect(resolveComparisonRegime(variants)).toBe("R2");
  });

  it("T-RESOLVE-2: one R1 variant + rest R2 → effective regime = R1 (most restrictive wins)", () => {
    // Severity: R1=0 < R3=1 < R2=2; min(R2=2, R1=0) = R1
    const variants = [
      makeVariant({ id: "v1", is_baseline: true,  finance_result: FINANCE_RESULT_R2 }),
      makeVariant({ id: "v2", is_baseline: false, finance_result: FINANCE_RESULT_R1 }),
    ];
    expect(resolveComparisonRegime(variants)).toBe("R1");
  });

  it("T-RESOLVE-3: one R3 variant + rest R2 → effective regime = R3", () => {
    // Severity: min(R2=2, R3=1) = R3
    const variants = [
      makeVariant({ id: "v1", is_baseline: true,  finance_result: FINANCE_RESULT_R2 }),
      makeVariant({ id: "v2", is_baseline: false, finance_result: FINANCE_RESULT_R3 }),
    ];
    expect(resolveComparisonRegime(variants)).toBe("R3");
  });

  it("T-RESOLVE-4: R1 + R3 mixed → effective regime = R1 (R1 beats R3)", () => {
    // Severity: min(R1=0, R3=1) = R1
    const variants = [
      makeVariant({ id: "v1", is_baseline: true,  finance_result: FINANCE_RESULT_R1 }),
      makeVariant({ id: "v2", is_baseline: false, finance_result: FINANCE_RESULT_R3 }),
    ];
    expect(resolveComparisonRegime(variants)).toBe("R1");
  });

  it("T-RESOLVE-5: empty variants / no finance_result → default R2 (no suppression)", () => {
    // No variants have finance_result → default R2 (no suppression)
    expect(resolveComparisonRegime([])).toBe("R2");
    expect(resolveComparisonRegime([makeVariant({ finance_result: null })])).toBe("R2");
  });

  // reviewer: resolveComparisonRegime must NEVER produce per-column regime (B1 rule)
  it("T-RESOLVE-6: return type is a single FinanceRegime, not per-variant", () => {
    const result = resolveComparisonRegime([
      makeVariant({ finance_result: FINANCE_RESULT_R2 }),
    ]);
    // Must be a single string — one of the three regime labels
    expect(typeof result).toBe("string");
    expect(["R1", "R2", "R3"]).toContain(result);
  });
});

// ─── §2. WorkbenchModeSelector ───────────────────────────────────────────────

describe("§2 WorkbenchModeSelector — D42 two-mode discipline", () => {
  it("T-MODE-1: renders both mode buttons", () => {
    render(<WorkbenchModeSelector mode="compare_designs" onChange={vi.fn()} />);
    expect(screen.getByTestId("mode-compare-designs")).toBeTruthy();
    expect(screen.getByTestId("mode-press-test")).toBeTruthy();
  });

  it("T-MODE-2: active mode has aria-pressed=true; inactive has aria-pressed=false", () => {
    render(<WorkbenchModeSelector mode="compare_designs" onChange={vi.fn()} />);
    expect(screen.getByTestId("mode-compare-designs")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("mode-press-test")).toHaveAttribute("aria-pressed", "false");
  });

  it("T-MODE-3: clicking inactive mode calls onChange with the new mode", () => {
    const onChange = vi.fn();
    render(<WorkbenchModeSelector mode="compare_designs" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("mode-press-test"));
    expect(onChange).toHaveBeenCalledWith("press_test");
  });

  it("T-MODE-4: clicking active mode does NOT call onChange (already active)", () => {
    const onChange = vi.fn();
    render(<WorkbenchModeSelector mode="compare_designs" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("mode-compare-designs"));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("T-MODE-5: mode selector is always visible — not conditionally hidden", () => {
    const { rerender } = render(
      <WorkbenchModeSelector mode="compare_designs" onChange={vi.fn()} />
    );
    expect(screen.getByTestId("mode-compare-designs")).toBeTruthy();
    rerender(<WorkbenchModeSelector mode="press_test" onChange={vi.fn()} />);
    expect(screen.getByTestId("mode-press-test")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("mode-compare-designs")).toHaveAttribute("aria-pressed", "false");
  });
});

// ─── §3. ScenarioLockBar ─────────────────────────────────────────────────────

describe("§3 ScenarioLockBar — compare_designs locked scenario", () => {
  it("T-LOCKBAR-1: renders lock icon + scenario summary (price path, M, WACC)", () => {
    render(<ScenarioLockBar scenario={SHARED_SCENARIO_R2} onUnlock={vi.fn()} />);
    const bar = screen.getByTestId("scenario-lock-bar");
    expect(bar).toBeTruthy();
    expect(bar.textContent).toMatch(/declining-real/);
    expect(bar.textContent).toMatch(/M=50/);
    expect(bar.textContent).toMatch(/7\.0%/);
  });

  it("T-LOCKBAR-2: contains lock icon visual marker (🔒 or text 'locked')", () => {
    render(<ScenarioLockBar scenario={SHARED_SCENARIO_R2} onUnlock={vi.fn()} />);
    const bar = screen.getByTestId("scenario-lock-bar");
    expect(bar.textContent).toMatch(/🔒|locked/i);
  });

  it("T-LOCKBAR-3: Unlock button calls onUnlock", () => {
    const onUnlock = vi.fn();
    render(<ScenarioLockBar scenario={SHARED_SCENARIO_R2} onUnlock={onUnlock} />);
    const unlockBtn = screen.getByRole("button", { name: /unlock|press.test/i });
    fireEvent.click(unlockBtn);
    expect(onUnlock).toHaveBeenCalledTimes(1);
  });
});

// ─── §4. ExecutionPlanBadge ───────────────────────────────────────────────────

describe("§4 ExecutionPlanBadge — tier status chips", () => {
  it("T-TIER-1: instant tier shows ⚡", () => {
    render(<ExecutionPlanBadge tier="instant" />);
    expect(screen.getByText(/⚡/)).toBeTruthy();
  });

  it("T-TIER-2: eval_needed tier shows ▶", () => {
    render(<ExecutionPlanBadge tier="eval_needed" estimatedSeconds={120} />);
    expect(screen.getByText(/▶/)).toBeTruthy();
  });

  it("T-TIER-3: retrain_required tier shows ⚠", () => {
    render(<ExecutionPlanBadge tier="retrain_required" />);
    expect(screen.getByText(/⚠/)).toBeTruthy();
  });

  it("T-TIER-4: running tier shows ⏳", () => {
    render(<ExecutionPlanBadge tier="running" />);
    expect(screen.getByText(/⏳/)).toBeTruthy();
  });

  it("T-TIER-5: eval_needed with 120 s shows time estimate (~2 min)", () => {
    render(<ExecutionPlanBadge tier="eval_needed" estimatedSeconds={120} />);
    expect(screen.getByText(/min/i)).toBeTruthy();
  });
});

// ─── §5. ComparisonTable — R1 regime ─────────────────────────────────────────

describe("§5 ComparisonTable — R1 suppression (M=1)", () => {
  const baselineR1 = makeVariant({ finance_result: FINANCE_RESULT_R1 });

  it("T-R1-1: regime banner shown at R1", () => {
    render(
      <ComparisonTable
        variants={[baselineR1]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/M > 1 required|M=1|risk.*require/i)).toBeTruthy();
  });

  it("T-R1-2: P90 upside column suppressed — exact string '— (M > 1 required)'", () => {
    render(
      <ComparisonTable
        variants={[baselineR1]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    const cells = screen.getAllByText("— (M > 1 required)");
    expect(cells.length).toBeGreaterThanOrEqual(1);
  });

  it("T-R1-3: Worst NPV cell suppressed at R1 (downside_risk is null)", () => {
    render(
      <ComparisonTable
        variants={[baselineR1]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    const worstNpvLabel = screen.queryByText(/Worst NPV/i);
    expect(worstNpvLabel).toBeTruthy();
    // Value suppressed — the ¥-38M figure from FINANCE_RESULT_R2 should NOT appear
    expect(screen.queryByText(/-38|38,000/)).toBeNull();
  });

  /**
   * T-R1-4 CORRECTED (v1.1.0): At R1, IRR is NOT available (irr_pct=null).
   * Only single_trajectory fields are shown:
   *   point_npv_yuan labeled "NPV (single scenario)"
   *   max_drawdown_yuan, max_drawdown_year, worst_year_cf_yuan
   *
   * WRONG in v1.0.0: tested "IRR P50 = 8.2% should be visible at R1" — IRR is ABSENT at M=1.
   */
  it("T-R1-4: NPV single scenario shown at R1 as 'NPV (single scenario)' — NOT P50", () => {
    // single_trajectory.point_npv_yuan = ¥142M; label must be "NPV (single scenario)"
    render(
      <ComparisonTable
        variants={[baselineR1]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // The label "NPV (single scenario)" must appear
    expect(screen.getByText(/NPV.*single scenario|single scenario.*NPV/i)).toBeTruthy();
    // IRR must NOT appear at R1 (irr_pct is null in schema)
    expect(screen.queryByText(/IRR.*P50|IRR.*8\.2%/i)).toBeNull();
  });

  // reviewer: IRR P50 must be absent (not just hidden) at R1 — irr_pct=null in schema
  it("T-R1-4b: IRR P90, MIRR, LCOE, payback are all absent at R1", () => {
    render(
      <ComparisonTable
        variants={[baselineR1]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // MIRR and LCOE should not show values (their MetricPercentiles are null)
    expect(screen.queryByText(/MIRR.*7\.1|7\.1.*MIRR/i)).toBeNull();
    expect(screen.queryByText(/312.*MWh/)).toBeNull();
  });

  it("T-R1-5: worst-year cash flow from single_trajectory IS shown at R1", () => {
    // single_trajectory.worst_year_cf_yuan = -12M — shown even at R1
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R1 })]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/−?¥?12|worst.year/i)).toBeTruthy();
  });
});

// ─── §5 ComparisonTable — R2 ─────────────────────────────────────────────────

describe("§5 ComparisonTable — R2 no suppression (M≥50 bootstrap)", () => {
  const baselineR2 = makeVariant({ finance_result: FINANCE_RESULT_R2 });

  it("T-R2-1: no regime banner at R2", () => {
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.queryByText(/M > 1 required/i)).toBeNull();
    expect(screen.queryByText(/tail-suppressed/i)).toBeNull();
  });

  it("T-R2-2: IRR P90 shown at R2 (7.6%, confidence=sound)", () => {
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/7\.6%/)).toBeTruthy();
  });

  it("T-R2-3: Worst NPV shown at R2 (worst_case_npv_yuan = −38M)", () => {
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/−?¥?38|38,000/)).toBeTruthy();
  });

  it("T-R2-4: P(NPV<0) shown at R2 (p_npv_neg=0.18 → 18%)", () => {
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/18%/)).toBeTruthy();
  });

  it("T-R2-5: CVaR-5% shown at R2 (cvar5_yuan = −76M)", () => {
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/−?¥?76|76,000/)).toBeTruthy();
  });
});

// ─── §5 ComparisonTable — R3 ─────────────────────────────────────────────────

describe("§5 ComparisonTable — R3 partial suppression (M≈10 empirical)", () => {
  const baselineR3 = makeVariant({ finance_result: FINANCE_RESULT_R3 });

  it("T-R3-1: regime banner shown at R3 — references empirical / M≈10", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/empirical|M.*10|tail.*suppressed/i)).toBeTruthy();
  });

  it("T-R3-2: P90 upside cells show '— (tail-suppressed)' at R3", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    const suppressed = screen.getAllByText("— (tail-suppressed)");
    expect(suppressed.length).toBeGreaterThanOrEqual(1);
  });

  it("T-R3-3: worst_case_npv_yuan shown at R3 (= min of M=10 runs; −45M)", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/−?¥?45|45,000/)).toBeTruthy();
  });

  it("T-R3-4: best_of_n_npv_yuan shown at R3 (= max of M=10 runs; ¥195M)", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/¥?195|195,000/)).toBeTruthy();
  });

  it("T-R3-5: P(NPV<0) shown as frequency at R3 (2/10 = 20%)", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/20%/)).toBeTruthy();
  });

  it("T-R3-6: CVaR-5% suppressed at R3 (cvar5_yuan=null)", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // CVaR should be suppressed — not showing the value from R2 fixture
    expect(screen.queryByText(/CVaR.*76|−76/i)).toBeNull();
  });

  /**
   * T-R3-7 CORRECTED (v1.1.0): P(IRR<hurdle) IS present at R3 as a frequency count.
   * Finance-expert: frequency count is honest at M≈10; CVaR is not.
   *
   * WRONG in v1.0.0: tested "P(IRR<hurdle) suppressed at R3" — it IS present per finance-expert.
   * FIXTURE: FINANCE_RESULT_R3.downside_risk.p_irr_below_hurdle = 0.30 (30%)
   */
  it("T-R3-7: P(IRR<hurdle) IS shown at R3 as frequency count (3/10 = 30%)", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // p_irr_below_hurdle=0.30 → displayed as "30%" or "3/10"
    expect(screen.getByText(/30%|3\/10|3 of 10/i)).toBeTruthy();
  });

  /**
   * T-R3-8 (Round 3 — DV-8): R3 frequencies displayed as "X of N years" not smooth %.
   * Finance-expert: resolution = 1/M = 10pp at M≈10; "20.0%" falsely implies sub-1pp precision.
   * FIXTURE: p_npv_neg=0.20, m_draws=10 → compute X=round(0.20*10)=2 → "2 of 10 years"
   */
  it("T-R3-8: R3 p_npv_neg displayed as 'X of N years' count format — NOT smooth decimal %", () => {
    // p_npv_neg=0.20, m_draws=10 → X = round(0.20 * 10) = 2 → "2 of 10 years" or "2 of 10"
    // Must NOT render "20.0%" (which implies sub-1pp precision at M=10)
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // Count format must be present
    expect(screen.getByText(/2 of 10|2\/10 years/i)).toBeTruthy();
    // Decimal % format must NOT appear for R3 frequency cells
    // (bare "20%" is also undesirable — prefer "2 of 10 years = 20%" at most)
    // This tests the component does NOT render "20.0%" anywhere in the freq cells
    expect(screen.queryByText(/20\.0%/)).toBeNull();
  });

  // reviewer: best_of_n_npv_yuan MUST be gated by regime="R3", not by truthiness
  it("T-R3-9: best_of_n_npv_yuan only rendered at R3 — suppressed (or absent) at R2", () => {
    // R2 fixture does NOT have best_of_n_npv_yuan (R3-only field per contract)
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R2 })]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // ¥195M from R3 fixture should NOT appear at R2
    expect(screen.queryByText(/195M|195,000/)).toBeNull();
  });

  // reviewer: cvar5_yuan MUST be gated by regime="R2", not by truthiness
  it("T-R3-10: cvar5_yuan suppressed at R3 even though table switch could show R2 value", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // cvar5_yuan is null at R3; CVaR row should show "— (tail-suppressed)"
    expect(screen.getByText(/— \(tail-suppressed\)/)).toBeTruthy();
    // ¥76M from R2 fixture should NOT appear
    expect(screen.queryByText(/76M|76,000/)).toBeNull();
  });
});

// ─── §6. Mixed-regime comparison ─────────────────────────────────────────────

describe("§6 ComparisonTable — mixed-regime (baseline R2, variant R1)", () => {
  it("T-MIXED-1: table uses minimum regime (R1) when any variant is R1", () => {
    const baseline = makeVariant({ id: "var-baseline", is_baseline: true, finance_result: FINANCE_RESULT_R2 });
    const variantA = makeVariant({ id: "var-a", label: "A", is_baseline: false, finance_result: FINANCE_RESULT_R1 });
    render(
      <ComparisonTable
        variants={[baseline, variantA]}
        baselineId="var-baseline"
        regime="R1"  // caller resolves minimum regime before passing
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/some variants.*M=1|M=1.*all.*suppressed/i)).toBeTruthy();
  });

  it("T-MIXED-2: mixed-regime warning mentions re-running with M≥50", () => {
    const baseline = makeVariant({ finance_result: FINANCE_RESULT_R1 });
    render(
      <ComparisonTable
        variants={[baseline]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/M.*50|re.run.*M/i)).toBeTruthy();
  });
});

// ─── §7. Delta display ────────────────────────────────────────────────────────

describe("§7 ComparisonTable — delta display vs baseline", () => {
  it("T-DELTA-1: baseline column shows absolute values (no delta prefix)", () => {
    const baseline = makeVariant({ finance_result: FINANCE_RESULT_R2 });
    render(
      <ComparisonTable
        variants={[baseline]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // irr_pct.p50.value = 8.2 → rendered as "8.2%"; no "+0.0 pp" delta prefix
    expect(screen.getByText(/8\.2%/)).toBeTruthy();
    expect(screen.queryByText(/\+0\.0 pp/)).toBeNull();
  });

  it("T-DELTA-2: variant column shows delta for IRR — Baseline 8.2% vs Variant 8.7% → +0.5 pp", () => {
    // arithmetic: 8.7 - 8.2 = +0.5 pp
    const baseline = makeVariant({ id: "var-baseline", is_baseline: true, finance_result: FINANCE_RESULT_R2 });
    const variantA = makeVariant({
      id: "var-a",
      label: "A (SST)",
      is_baseline: false,
      finance_result: {
        ...FINANCE_RESULT_R2,
        irr_pct: {
          p50: { value: 8.7, confidence: "sound" },
          p90: { value: 8.1, confidence: "sound" },
        },
      },
    });
    render(
      <ComparisonTable
        variants={[baseline, variantA]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/\+0\.5 pp|\+0\.5pp/)).toBeTruthy();
  });

  it("T-DELTA-3: downside delta — Worst NPV −38M vs −22M → +16M (less exposed = positive)", () => {
    // arithmetic: -22_000_000 - (-38_000_000) = +16_000_000
    const baseline = makeVariant({ id: "var-baseline", is_baseline: true, finance_result: FINANCE_RESULT_R2 });
    const variantA = makeVariant({
      id: "var-a",
      label: "A (SST)",
      is_baseline: false,
      finance_result: {
        ...FINANCE_RESULT_R2,
        downside_risk: {
          ...FINANCE_RESULT_R2.downside_risk!,
          worst_case_npv_yuan: -22_000_000,  // CORRECTED field name from v1.0.0
        },
      },
    });
    render(
      <ComparisonTable
        variants={[baseline, variantA]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/\+¥?16M|\+16M|\+16,000/)).toBeTruthy();
  });

  /**
   * T-DELTA-5 (Round 3 — B3): LCOE delta — lower is better.
   * Baseline LCOE P50 = 312 ¥/MWh; Variant LCOE P50 = 300 ¥/MWh.
   * arithmetic: 300 - 312 = -12 ¥/MWh (improvement).
   * The cell must have data-direction="lower-better" so coloring renders negative = green.
   */
  it("T-DELTA-5: LCOE delta lower-better — negative delta cell has data-direction=lower-better", () => {
    // Baseline LCOE = 312 ¥/MWh; variant LCOE = 300 ¥/MWh → delta = -12 ¥/MWh (improvement)
    const baseline = makeVariant({ id: "var-baseline", is_baseline: true, finance_result: FINANCE_RESULT_R2 });
    const variantA = makeVariant({
      id: "var-a",
      label: "A (SST)",
      is_baseline: false,
      finance_result: {
        ...FINANCE_RESULT_R2,
        lcoe_yuan_per_mwh: { p50: { value: 300, confidence: "sound" } },
      },
    });
    render(
      <ComparisonTable
        variants={[baseline, variantA]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // Delta "-12 ¥/MWh" should be shown; the cell must carry data-delta-direction="good"
    // (lower-better metric AND negative delta → improvement → "good")
    // Mirrors §15 data-confidence convention: attribute encodes verdict, not raw value
    expect(screen.getByText(/−12.*¥\/MWh|-12.*¥\/MWh/)).toBeTruthy();
    const lcoeDeltaCell = screen.getByText(/−12.*¥\/MWh|-12.*¥\/MWh/).closest("[data-delta-direction]");
    expect(lcoeDeltaCell?.getAttribute("data-delta-direction")).toBe("good");
  });

  /**
   * T-DELTA-6 (Round 3 — B3 unit guard): LCOE must be shown in ¥/MWh, NOT ¥/kWh.
   * 312 ¥/MWh ≠ 0.312 ¥/kWh — the kWh form is a unit trap (factor-of-1000 error).
   */
  it("T-DELTA-6: LCOE unit guard — displayed in ¥/MWh not ¥/kWh (factor-of-1000 trap)", () => {
    // FINANCE_RESULT_R2.lcoe_yuan_per_mwh.p50.value = 312 (¥/MWh)
    // MUST show "312 ¥/MWh" or "312"; must NOT show "0.312" (kWh form)
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R2 })]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // 312 ¥/MWh should appear somewhere in the LCOE row
    expect(screen.getByText(/312.*¥\/MWh|¥\/MWh.*312|312/)).toBeTruthy();
    // 0.312 (kWh form) must NOT appear anywhere (unit trap guard)
    expect(screen.queryByText(/0\.312/)).toBeNull();
  });

  /**
   * T-DELTA-7 (Round 3 — B1+B3): mixed-regime delta cells are SUPPRESSED.
   * When table regime = R1 (baseline R2, one variant R1), IRR delta must NOT be shown.
   * Rule: no delta rendered when one column's metric is populated and another's is suppressed.
   */
  it("T-DELTA-7: mixed-regime — IRR delta suppressed when table regime=R1 (no pp delta rendered)", () => {
    // Baseline has R2 (irr_pct.p50=8.2%); one variant has R1 (irr_pct=null)
    // resolveComparisonRegime([R2, R1]) = R1 → entire table uses R1 → IRR cells suppressed
    // No "+0.X pp" or "-0.X pp" delta should appear in the IRR rows
    const baseline = makeVariant({ id: "var-baseline", is_baseline: true,  finance_result: FINANCE_RESULT_R2 });
    const variantR1 = makeVariant({ id: "var-r1", is_baseline: false, finance_result: FINANCE_RESULT_R1 });
    render(
      <ComparisonTable
        variants={[baseline, variantR1]}
        baselineId="var-baseline"
        regime="R1"  // resolveComparisonRegime([R2, R1]) = R1
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // No IRR delta in pp units should appear (metric suppressed at R1)
    expect(screen.queryByText(/\+.*pp|-.*pp/)).toBeNull();
  });

  it("T-DELTA-4: re-designating baseline flips all deltas", () => {
    // After re-designation: var-a (8.7%) is baseline; var-baseline (8.2%) shows -0.5 pp
    const v1 = makeVariant({
      id: "var-baseline",
      label: "Original",
      is_baseline: false,
      finance_result: { ...FINANCE_RESULT_R2, irr_pct: { p50: { value: 8.2, confidence: "sound" } } },
    });
    const v2 = makeVariant({
      id: "var-a",
      label: "A (SST)",
      is_baseline: true,
      finance_result: { ...FINANCE_RESULT_R2, irr_pct: { p50: { value: 8.7, confidence: "sound" } } },
    });
    render(
      <ComparisonTable
        variants={[v1, v2]}
        baselineId="var-a"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // var-a (baseline) shows absolute 8.7%
    expect(screen.getByText(/8\.7%/)).toBeTruthy();
    // var-baseline shows delta: 8.2 - 8.7 = -0.5 pp
    expect(screen.getByText(/−0\.5 pp|-0\.5 pp/)).toBeTruthy();
  });
});

// ─── §8. Workbench store ──────────────────────────────────────────────────────

describe("§8 useWorkbenchStore — state invariants", () => {
  beforeEach(() => {
    useWorkbenchStore.getState().clearAll();
  });

  it("T-STORE-1: initial state has mode=compare_designs", () => {
    expect(useWorkbenchStore.getState().mode).toBe("compare_designs");
  });

  it("T-STORE-2: after adding first variant, it is the baseline", () => {
    useWorkbenchStore.getState().addVariant({
      label: "Baseline",
      config_id: "cfg-1",
      config_hash: "#abc",
      policy: null,
      eval_result_id: null,
      finance_params: null,
      price_path_name: null,
    });
    const state = useWorkbenchStore.getState();
    expect(state.variants.length).toBe(1);
    expect(state.variants[0].is_baseline).toBe(true);
    expect(state.baselineId).toBe(state.variants[0].id);
  });

  it("T-STORE-3: exactly one baseline at all times after designateBaseline", () => {
    const store = useWorkbenchStore.getState();
    store.addVariant({ label: "A", config_id: "c1", config_hash: "#a", policy: null, eval_result_id: null, finance_params: null, price_path_name: null });
    store.addVariant({ label: "B", config_id: "c2", config_hash: "#b", policy: null, eval_result_id: null, finance_params: null, price_path_name: null });
    const [, varB] = useWorkbenchStore.getState().variants;

    store.designateBaseline(varB.id);
    const after = useWorkbenchStore.getState();
    const baselines = after.variants.filter(v => v.is_baseline);
    expect(baselines.length).toBe(1);
    expect(baselines[0].id).toBe(varB.id);
    expect(after.baselineId).toBe(varB.id);
  });

  it("T-STORE-4: setMode stores the new mode", () => {
    useWorkbenchStore.getState().setMode("press_test");
    expect(useWorkbenchStore.getState().mode).toBe("press_test");
  });

  it("T-STORE-5: showBands defaults to true", () => {
    expect(useWorkbenchStore.getState().showBands).toBe(true);
  });

  it("T-STORE-6: removeVariant with the only variant resets baselineId to null", () => {
    const store = useWorkbenchStore.getState();
    store.addVariant({ label: "A", config_id: "c1", config_hash: "#a", policy: null, eval_result_id: null, finance_params: null, price_path_name: null });
    const varId = useWorkbenchStore.getState().variants[0].id;
    store.removeVariant(varId);
    const after = useWorkbenchStore.getState();
    expect(after.variants.length).toBe(0);
    expect(after.baselineId).toBeNull();
  });

  it("T-STORE-7: removeVariant on baseline promotes next variant as baseline", () => {
    const store = useWorkbenchStore.getState();
    store.addVariant({ label: "A", config_id: "c1", config_hash: "#a", policy: null, eval_result_id: null, finance_params: null, price_path_name: null });
    store.addVariant({ label: "B", config_id: "c2", config_hash: "#b", policy: null, eval_result_id: null, finance_params: null, price_path_name: null });
    const [varA] = useWorkbenchStore.getState().variants;
    expect(varA.is_baseline).toBe(true);
    store.removeVariant(varA.id);
    const after = useWorkbenchStore.getState();
    expect(after.variants.length).toBe(1);
    expect(after.variants[0].is_baseline).toBe(true);
    expect(after.baselineId).toBe(after.variants[0].id);
  });

  // reviewer: compare_designs mode must not allow per-variant price path overrides
  it("T-STORE-8: in compare_designs mode, updateVariant price_path_name is blocked (no-op)", () => {
    const store = useWorkbenchStore.getState();
    store.setMode("compare_designs");
    store.addVariant({ label: "A", config_id: "c1", config_hash: "#a", policy: null, eval_result_id: null, finance_params: null, price_path_name: null });
    const varId = useWorkbenchStore.getState().variants[0].id;
    store.updateVariant(varId, { price_path_name: "stress" });
    const after = useWorkbenchStore.getState();
    expect(after.variants[0].price_path_name).toBeNull();
  });

  it("T-STORE-9: financeRecomputeLoading tracks per-variant loading state", () => {
    const store = useWorkbenchStore.getState();
    // Initially empty
    expect(store.financeRecomputeLoading).toEqual({});
    // After triggering recompute, the key should be set to true (mocked)
    // This is a structural test — implementation will manage this in recomputeFinance()
    expect(typeof store.recomputeFinance).toBe("function");
  });

  it("T-STORE-10: diffSummary is recomputed on addVariant", () => {
    const store = useWorkbenchStore.getState();
    expect(store.diffSummary).toBeNull();
    store.addVariant({ label: "A", config_id: "c1", config_hash: "#a", policy: null, eval_result_id: null, finance_params: null, price_path_name: null });
    // After adding a variant, diffSummary should be computed (not null)
    // With only 1 variant there can be no "differs" params but the summary exists
    const after = useWorkbenchStore.getState();
    expect(after.diffSummary).not.toBeNull();
  });
});

// ─── §9. SizingSweepPanel ────────────────────────────────────────────────────

describe("§9 SizingSweepPanel — 2D battery sizing", () => {
  const defaultConfig = {
    base_config_id: "cfg-gansu-v1",
    energy_mwh_min: 100, energy_mwh_max: 600, energy_steps: 6,
    power_mw_min: 50,   power_mw_max: 300,   power_steps: 6,
    metric: "npv_p50" as const,
  };

  it("T-SWEEP-1: renders sweep panel with run button", () => {
    render(
      <SizingSweepPanel
        sweepConfig={defaultConfig}
        sweepResult={null}
        sweepLoading={false}
        sweepError={null}
        onConfigChange={vi.fn()}
        onSubmit={vi.fn()}
        onAddPointAsVariant={vi.fn()}
      />
    );
    expect(screen.getByTestId("sizing-sweep-panel")).toBeTruthy();
    expect(screen.getByTestId("sweep-run-button")).toBeTruthy();
  });

  it("T-SWEEP-2: shows total config count: 6×6 = 36 configs", () => {
    render(
      <SizingSweepPanel
        sweepConfig={defaultConfig}
        sweepResult={null}
        sweepLoading={false}
        sweepError={null}
        onConfigChange={vi.fn()}
        onSubmit={vi.fn()}
        onAddPointAsVariant={vi.fn()}
      />
    );
    expect(screen.getByText(/36 configs/)).toBeTruthy();
  });

  it("T-SWEEP-3: while running, shows progress bar with X/N", () => {
    const partialResult = {
      run_id: "sweep-001",
      status: "running" as const,
      configs_total: 36,
      configs_done: 12,
    } as SizingSweepResult;
    render(
      <SizingSweepPanel
        sweepConfig={defaultConfig}
        sweepResult={partialResult}
        sweepLoading={true}
        sweepError={null}
        onConfigChange={vi.fn()}
        onSubmit={vi.fn()}
        onAddPointAsVariant={vi.fn()}
      />
    );
    expect(screen.getByTestId("sweep-progress")).toBeTruthy();
    expect(screen.getByText(/12\/36|12 of 36/)).toBeTruthy();
  });

  it("T-SWEEP-4: energy_steps < 2 shows validation error", () => {
    render(
      <SizingSweepPanel
        sweepConfig={{ ...defaultConfig, energy_steps: 1 }}
        sweepResult={null}
        sweepLoading={false}
        sweepError={null}
        onConfigChange={vi.fn()}
        onSubmit={vi.fn()}
        onAddPointAsVariant={vi.fn()}
      />
    );
    expect(screen.getByText(/at least 2|minimum.*2/i)).toBeTruthy();
  });

  it("T-SWEEP-5: energy_steps > 20 shows validation error", () => {
    render(
      <SizingSweepPanel
        sweepConfig={{ ...defaultConfig, energy_steps: 25 }}
        sweepResult={null}
        sweepLoading={false}
        sweepError={null}
        onConfigChange={vi.fn()}
        onSubmit={vi.fn()}
        onAddPointAsVariant={vi.fn()}
      />
    );
    expect(screen.getByText(/maximum.*20|no more than 20/i)).toBeTruthy();
  });

  it("T-SWEEP-6: at R1 regime, regime banner shown in sweep panel", () => {
    const r1Result: SizingSweepResult = {
      run_id: "sweep-001",
      status: "complete",
      configs_total: 36, configs_done: 36,
      energy_axis_mwh: [100, 200, 300, 400, 500, 600],
      power_axis_mw: [50, 110, 170, 230, 300, 360],
      surface: Array(6).fill(Array(6).fill(100_000_000)),
      surface_metric: "npv_p50",
      regime: "R1",
      recommended_energy_idx: 3,
      recommended_power_idx: 2,
    };
    render(
      <SizingSweepPanel
        sweepConfig={defaultConfig}
        sweepResult={r1Result}
        sweepLoading={false}
        sweepError={null}
        onConfigChange={vi.fn()}
        onSubmit={vi.fn()}
        onAddPointAsVariant={vi.fn()}
      />
    );
    expect(screen.getByTestId("sweep-regime-banner")).toBeTruthy();
  });

  it("T-SWEEP-7: clicking recommended point calls onAddPointAsVariant with correct indices", () => {
    const onAdd = vi.fn();
    const completeResult: SizingSweepResult = {
      run_id: "sweep-001",
      status: "complete",
      configs_total: 4, configs_done: 4,
      energy_axis_mwh: [100, 300],
      power_axis_mw: [50, 150],
      surface: [[90_000_000, 120_000_000], [100_000_000, 142_000_000]],
      surface_metric: "npv_p50",
      regime: "R2",
      recommended_energy_idx: 1,
      recommended_power_idx: 1,
    };
    render(
      <SizingSweepPanel
        sweepConfig={defaultConfig}
        sweepResult={completeResult}
        sweepLoading={false}
        sweepError={null}
        onConfigChange={vi.fn()}
        onSubmit={vi.fn()}
        onAddPointAsVariant={onAdd}
      />
    );
    const recPoint = screen.getByTestId("surface-recommended-point");
    fireEvent.click(recPoint);
    expect(onAdd).toHaveBeenCalledWith(1, 1);
  });
});

// ─── §10. AddToComparisonModal ────────────────────────────────────────────────

describe("§10 AddToComparisonModal — wizard entry points", () => {
  it("T-MODAL-1: renders dialog with label input and Add button", () => {
    render(<AddToComparisonModal config_id="cfg-1" onAdd={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByLabelText(/label/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /add/i })).toBeTruthy();
  });

  it("T-MODAL-2: onCancel called on Cancel button", () => {
    const onCancel = vi.fn();
    render(<AddToComparisonModal config_id="cfg-1" onAdd={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("T-MODAL-3: onAdd called with label and asBaseline=false by default", () => {
    const onAdd = vi.fn();
    render(<AddToComparisonModal config_id="cfg-1" onAdd={onAdd} onCancel={vi.fn()} />);
    const labelInput = screen.getByLabelText(/label/i) as HTMLInputElement;
    fireEvent.change(labelInput, { target: { value: "My variant" } });
    fireEvent.click(screen.getByRole("button", { name: /add/i }));
    expect(onAdd).toHaveBeenCalledWith("My variant", false);
  });
});

// ─── §11. ConfigCard ─────────────────────────────────────────────────────────

describe("§11 ConfigCard — config library card", () => {
  const config = makeSavedConfig();

  it("T-CARD-1: shows config label", () => {
    render(
      <ConfigCard config={config} selected={false}
        onToggleSelect={vi.fn()} onFork={vi.fn()} onEdit={vi.fn()}
        onDelete={vi.fn()} onPressTest={vi.fn()} />
    );
    expect(screen.getByText("Gansu-v1")).toBeTruthy();
  });

  it("T-CARD-2: shows battery sizing summary (300 MWh, 150 MW)", () => {
    render(
      <ConfigCard config={config} selected={false}
        onToggleSelect={vi.fn()} onFork={vi.fn()} onEdit={vi.fn()}
        onDelete={vi.fn()} onPressTest={vi.fn()} />
    );
    expect(screen.getByText(/300.*MWh|300 MWh/)).toBeTruthy();
    expect(screen.getByText(/150.*MW/)).toBeTruthy();
  });

  it("T-CARD-3: shows policy_count and eval_count", () => {
    render(
      <ConfigCard config={config} selected={false}
        onToggleSelect={vi.fn()} onFork={vi.fn()} onEdit={vi.fn()}
        onDelete={vi.fn()} onPressTest={vi.fn()} />
    );
    expect(screen.getByText(/2.*polic|polic.*2/i)).toBeTruthy();
    expect(screen.getByText(/3.*eval|eval.*3/i)).toBeTruthy();
  });

  it("T-CARD-4: onToggleSelect called when clicking the select checkbox", () => {
    const onToggleSelect = vi.fn();
    render(
      <ConfigCard config={config} selected={false}
        onToggleSelect={onToggleSelect} onFork={vi.fn()} onEdit={vi.fn()}
        onDelete={vi.fn()} onPressTest={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onToggleSelect).toHaveBeenCalledTimes(1);
  });

  it("T-CARD-5: forked config shows 'Forked from' / parent reference", () => {
    const forked = makeSavedConfig({
      parent_id: "cfg-gansu-v0",
      label: "Gansu-v1-SST",
      parent_param_delta: {
        "site_summary.battery_energy_mwh": { from: 300, to: 400, label: "Battery energy", unit: "MWh" },
      },
    });
    render(
      <ConfigCard config={forked} selected={false}
        onToggleSelect={vi.fn()} onFork={vi.fn()} onEdit={vi.fn()}
        onDelete={vi.fn()} onPressTest={vi.fn()} />
    );
    expect(screen.getByText(/forked from|parent/i)).toBeTruthy();
  });

  it("T-CARD-6: config with comment thread shows latest comment (D43)", () => {
    const configWithComments = makeSavedConfig({
      comment_thread: [
        makeComment({ id: "cmt-001", author: "agent", text: "Auto-tuned C-rate looks optimal." }),
        makeComment({ id: "cmt-002", author: "human", text: "Approved for bankable case.", timestamp: "2026-06-11T00:00:00Z" }),
      ],
    });
    render(
      <ConfigCard config={configWithComments} selected={false}
        onToggleSelect={vi.fn()} onFork={vi.fn()} onEdit={vi.fn()}
        onDelete={vi.fn()} onPressTest={vi.fn()} />
    );
    // Should show latest comment or "N comments" expander
    expect(screen.getByText(/2 comments|Approved for bankable/i)).toBeTruthy();
  });
});

// ─── §12. PerConfigDetail ────────────────────────────────────────────────────

describe("§12 PerConfigDetail — downside risk panel first", () => {
  it("T-PCD-1: DownsideRiskPanel appears before headline upside metrics in DOM order", () => {
    render(
      <PerConfigDetail
        variant={makeVariant()}
        regime="R2"
        onPressTest={vi.fn()}
        onNext={vi.fn()} onPrev={vi.fn()}
        hasPrev={false} hasNext={false}
      />
    );
    const worstNpv = screen.getByText(/Worst NPV/i);
    const irrP50 = screen.getByText(/IRR.*P50|IRR.*8\.2/i);
    // DOCUMENT_POSITION_FOLLOWING (4) set when worstNpv precedes irrP50
    expect(
      worstNpv.compareDocumentPosition(irrP50) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("T-PCD-2: Press-test button is present", () => {
    render(
      <PerConfigDetail
        variant={makeVariant()}
        regime="R2"
        onPressTest={vi.fn()}
        onNext={vi.fn()} onPrev={vi.fn()}
        hasPrev={false} hasNext={false}
      />
    );
    expect(screen.getByRole("button", { name: /press.test/i })).toBeTruthy();
  });

  it("T-PCD-3: Prev/Next navigation buttons disabled when not available", () => {
    render(
      <PerConfigDetail
        variant={makeVariant()}
        regime="R2"
        onPressTest={vi.fn()}
        onNext={vi.fn()} onPrev={vi.fn()}
        hasPrev={false} hasNext={false}
      />
    );
    expect(screen.getByRole("button", { name: /prev|←/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next|→/i })).toBeDisabled();
  });

  it("T-PCD-4: at R1, DownsideRiskPanel cells are suppressed", () => {
    render(
      <PerConfigDetail
        variant={makeVariant({ finance_result: FINANCE_RESULT_R1 })}
        regime="R1"
        onPressTest={vi.fn()}
        onNext={vi.fn()} onPrev={vi.fn()}
        hasPrev={false} hasNext={false}
      />
    );
    expect(screen.queryByText(/−38M/)).toBeNull();
    expect(screen.getAllByText("— (M > 1 required)").length).toBeGreaterThanOrEqual(1);
  });
});

// ─── §13. Naming discipline guard ────────────────────────────────────────────

describe("§13 Naming discipline — R1/R2/R3 must not label data source", () => {
  it("T-NAME-1: ScenarioLockBar does not render 'R1', 'R2', 'R3' as text", () => {
    render(<ScenarioLockBar scenario={SHARED_SCENARIO_R2} onUnlock={vi.fn()} />);
    const bar = screen.getByTestId("scenario-lock-bar");
    expect(bar.textContent).not.toMatch(/\bR2\b|\bR1\b|\bR3\b/);
  });

  it("T-NAME-2: RegimeBanner at R1 describes M=1 not 'R1 mode'", () => {
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R1 })]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    const banner = screen.getByText(/M=1|M > 1 required|single.*trajectory/i);
    expect(banner).toBeTruthy();
  });

  it("T-NAME-3: R3 banner references 'empirical' or 'M≈10', not 'R3 mode'", () => {
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R3 })]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    const banner = screen.getByText(/empirical|M.*10/i);
    expect(banner).toBeTruthy();
    expect(banner.textContent).not.toMatch(/\bR3 mode\b|\bR3 ensemble\b/i);
  });
});

// ─── §14. Workbench isolation ─────────────────────────────────────────────────

describe("§14 Workbench isolation — batch-only, no live telemetry", () => {
  // reviewer: workbench must never access the live telemetry store (D42)
  it("T-ISO-1: useWorkbenchStore does not expose telemetry fields", () => {
    const state = useWorkbenchStore.getState();
    expect((state as Record<string, unknown>).soc_pct).toBeUndefined();
    expect((state as Record<string, unknown>).power_flow_kw).toBeUndefined();
    expect((state as Record<string, unknown>).env_step).toBeUndefined();
    expect((state as Record<string, unknown>).websocket).toBeUndefined();
  });
});

// ─── §15. Per-percentile confidence styling ───────────────────────────────────

describe("§15 Per-percentile confidence styling — cross-cutting rule", () => {
  /**
   * Finance-expert cross-cutting rule: every PercentileResult carries confidence.
   * "indicative_low_confidence" → MUTED + "(indicative)" caveat; NEVER bold headline.
   */

  it("T-CONF-1: R3 P50 IRR rendered with '(indicative)' caveat (confidence=indicative_low_confidence)", () => {
    // FINANCE_RESULT_R3.irr_pct.p50.confidence = "indicative_low_confidence"
    // UI must show a muted style + "(indicative)" text near the value
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R3 })]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // Value "7.9%" should appear alongside "(indicative)" caveat
    expect(screen.getByText(/7\.9%/)).toBeTruthy();
    expect(screen.getByText(/indicative/i)).toBeTruthy();
  });

  it("T-CONF-2: R2 P50 IRR has no '(indicative)' tag (confidence=sound)", () => {
    // FINANCE_RESULT_R2.irr_pct.p50.confidence = "sound"
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R2 })]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    expect(screen.getByText(/8\.2%/)).toBeTruthy();
    // "indicative" should NOT appear for R2 sound metrics
    expect(screen.queryByText(/indicative/i)).toBeNull();
  });

  it("T-CONF-3: P99 at R2 is always rendered indicative_low_confidence (even if p99.value present)", () => {
    const withP99: FinanceResultSummary = {
      ...FINANCE_RESULT_R2,
      irr_pct: {
        ...FINANCE_RESULT_R2.irr_pct,
        p99: { value: 6.1, confidence: "indicative_low_confidence" },
      },
    };
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: withP99 })]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // 6.1% appears with "(indicative)" caveat
    expect(screen.getByText(/6\.1%/)).toBeTruthy();
    const p99Cell = screen.getByText(/6\.1%/).closest("[data-confidence]");
    expect(p99Cell?.getAttribute("data-confidence")).toBe("indicative_low_confidence");
  });

  // reviewer: indicative_low_confidence cells must not carry bold CSS or "headline" class
  it("T-CONF-4: indicative_low_confidence cells do not have data-headline=true", () => {
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R3 })]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
        sortMetric={null}
        sortDir="desc"
        onSort={vi.fn()}
      />
    );
    // Any element with data-confidence="indicative_low_confidence" must NOT have data-headline="true"
    const indicativeCells = document.querySelectorAll('[data-confidence="indicative_low_confidence"]');
    expect(indicativeCells.length).toBeGreaterThanOrEqual(1);
    indicativeCells.forEach(cell => {
      expect(cell.getAttribute("data-headline")).not.toBe("true");
    });
  });
});

// ─── §16. Input-diff highlighting ─────────────────────────────────────────────

describe("§16 ConfigDiffPanel — input-diff highlighting", () => {
  const makeParamDiff = (overrides: Partial<ConfigParamDiff> = {}): ConfigParamDiff => ({
    param_path: "site_summary.battery_energy_mwh",
    param_label: "Battery energy",
    param_tier: "re_sim",
    unit: "MWh",
    values: { "cfg-v1": 300, "cfg-v2": 400 },
    differs: true,
    ...overrides,
  });

  const makeDiffSummary = (overrides: Partial<WorkbenchDiffSummary> = {}): WorkbenchDiffSummary => ({
    differing_params: [
      makeParamDiff({
        param_path: "site_summary.battery_energy_mwh",
        param_label: "Battery energy",
        param_tier: "re_sim",
        differs: true,
      }),
      makeParamDiff({
        param_path: "finance_params.gearing_pct",
        param_label: "Gearing",
        param_tier: "instant",
        unit: "%",
        values: { "cfg-v1": 60, "cfg-v2": 70 },
        differs: true,
      }),
    ],
    common_params: [
      makeParamDiff({
        param_path: "site_summary.wind_count",
        param_label: "Wind turbines",
        param_tier: "re_sim",
        values: { "cfg-v1": 100, "cfg-v2": 100 },
        differs: false,
      }),
    ],
    finance_param_diffs: [
      makeParamDiff({
        param_path: "finance_params.gearing_pct",
        param_label: "Gearing",
        param_tier: "instant",
        differs: true,
      }),
    ],
    physical_param_diffs: [
      makeParamDiff({ param_path: "site_summary.battery_energy_mwh", differs: true }),
    ],
    ...overrides,
  });

  it("T-DIFF-1: renders data-testid=config-diff-panel", () => {
    render(
      <ConfigDiffPanel
        diffSummary={makeDiffSummary()}
        showAllParams={false}
        onToggleShowAll={vi.fn()}
      />
    );
    expect(screen.getByTestId("config-diff-panel")).toBeTruthy();
  });

  it("T-DIFF-2: differing params have data-testid=diff-param-{param_path}", () => {
    render(
      <ConfigDiffPanel
        diffSummary={makeDiffSummary()}
        showAllParams={false}
        onToggleShowAll={vi.fn()}
      />
    );
    expect(screen.getByTestId("diff-param-site_summary.battery_energy_mwh")).toBeTruthy();
    expect(screen.getByTestId("diff-param-finance_params.gearing_pct")).toBeTruthy();
  });

  it("T-DIFF-3: common params collapsed by default; count shown with toggle", () => {
    render(
      <ConfigDiffPanel
        diffSummary={makeDiffSummary()}
        showAllParams={false}
        onToggleShowAll={vi.fn()}
      />
    );
    // "1 param identical" or "1 params identical"
    expect(screen.getByTestId("common-param-count")).toBeTruthy();
    expect(screen.getByText(/1.*param.*identical|1.*identical/i)).toBeTruthy();
  });

  it("T-DIFF-4: [show all] toggle calls onToggleShowAll", () => {
    const onToggle = vi.fn();
    render(
      <ConfigDiffPanel
        diffSummary={makeDiffSummary()}
        showAllParams={false}
        onToggleShowAll={onToggle}
      />
    );
    const showAll = screen.getByRole("button", { name: /show all/i });
    fireEvent.click(showAll);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("T-DIFF-5: instant-tier finance params labeled with ⚡", () => {
    render(
      <ConfigDiffPanel
        diffSummary={makeDiffSummary()}
        showAllParams={false}
        onToggleShowAll={vi.fn()}
      />
    );
    // The gearing param is tier="instant"; should show ⚡
    const gearingRow = screen.getByTestId("diff-param-finance_params.gearing_pct");
    expect(gearingRow.textContent).toMatch(/⚡/);
  });
});

// ─── §17. Finance param instant tier ──────────────────────────────────────────

describe("§17 FinanceParamPanel — instant tier ⚡", () => {
  it("T-FINANCE-1: renders finance-param-panel with sliders", () => {
    render(
      <FinanceParamPanel
        params={STUB_FINANCE_PARAMS}
        mode="shared"
        onParamChange={vi.fn()}
        recomputeLoading={false}
      />
    );
    expect(screen.getByTestId("finance-param-panel")).toBeTruthy();
    // At least the WACC slider should appear
    expect(screen.getByTestId("finance-param-wacc_pct")).toBeTruthy();
  });

  it("T-FINANCE-2: panel shows INSTANT tier label with ⚡", () => {
    render(
      <FinanceParamPanel
        params={STUB_FINANCE_PARAMS}
        mode="shared"
        onParamChange={vi.fn()}
        recomputeLoading={false}
      />
    );
    expect(screen.getByText(/⚡.*INSTANT|INSTANT.*cached dispatch/i)).toBeTruthy();
  });

  it("T-FINANCE-3: slider onChange calls onParamChange with key and value", () => {
    const onParamChange = vi.fn();
    render(
      <FinanceParamPanel
        params={STUB_FINANCE_PARAMS}
        mode="shared"
        onParamChange={onParamChange}
        recomputeLoading={false}
      />
    );
    const waccSlider = screen.getByTestId("finance-param-slider-wacc_pct");
    fireEvent.change(waccSlider, { target: { value: "8.0" } });
    expect(onParamChange).toHaveBeenCalledWith("wacc_pct", 8.0, expect.any(String));
  });

  it("T-FINANCE-4: scope toggle exists for each param (data-testid=scope-toggle-{key})", () => {
    render(
      <FinanceParamPanel
        params={STUB_FINANCE_PARAMS}
        mode="shared"
        onParamChange={vi.fn()}
        recomputeLoading={false}
      />
    );
    expect(screen.getByTestId("scope-toggle-wacc_pct")).toBeTruthy();
    expect(screen.getByTestId("scope-toggle-gearing_pct")).toBeTruthy();
  });

  it("T-FINANCE-5: common-scope param shows data-scope=common", () => {
    render(
      <FinanceParamPanel
        params={STUB_FINANCE_PARAMS}
        mode="shared"
        onParamChange={vi.fn()}
        recomputeLoading={false}
      />
    );
    // wacc_pct has scope="common" in STUB_FINANCE_PARAMS
    expect(screen.getByTestId("finance-param-wacc_pct")).toHaveAttribute("data-scope", "common");
  });

  it("T-FINANCE-6: per_config-scope param shows data-scope=per_config", () => {
    render(
      <FinanceParamPanel
        params={STUB_FINANCE_PARAMS}
        mode="shared"
        onParamChange={vi.fn()}
        recomputeLoading={false}
      />
    );
    // gearing_pct has scope="per_config" in STUB_FINANCE_PARAMS
    expect(screen.getByTestId("finance-param-gearing_pct")).toHaveAttribute("data-scope", "per_config");
  });
});

// ─── §18. D43 config comment thread ───────────────────────────────────────────

describe("§18 ConfigCommentThread — D43 human+agent annotation", () => {
  const agentComment = makeComment({
    id: "cmt-a1",
    author: "agent",
    timestamp: "2026-06-10T10:00:00Z",
    text: "Dispatch analysis suggests C-rate 0.5 is near-optimal for this price regime.",
  });
  const humanComment = makeComment({
    id: "cmt-h1",
    author: "human",
    timestamp: "2026-06-10T11:00:00Z",
    text: "Approved. Matches our site constraints.",
  });

  it("T-COMMENT-1: renders comment-thread container", () => {
    render(
      <ConfigCommentThread
        config_id="cfg-gansu-v1"
        comments={[agentComment, humanComment]}
        onAddComment={vi.fn()}
        loading={false}
      />
    );
    expect(screen.getByTestId("comment-thread")).toBeTruthy();
  });

  it("T-COMMENT-2: agent comment shows 'AI' badge", () => {
    render(
      <ConfigCommentThread
        config_id="cfg-gansu-v1"
        comments={[agentComment]}
        onAddComment={vi.fn()}
        loading={false}
      />
    );
    const comment = screen.getByTestId("comment-cmt-a1");
    expect(comment.getAttribute("data-author")).toBe("agent");
    expect(comment.textContent).toMatch(/AI/i);
  });

  it("T-COMMENT-3: human comment has a textarea for new comment + Post button", () => {
    render(
      <ConfigCommentThread
        config_id="cfg-gansu-v1"
        comments={[]}
        onAddComment={vi.fn()}
        loading={false}
      />
    );
    expect(screen.getByRole("textbox")).toBeTruthy();
    expect(screen.getByRole("button", { name: /post/i })).toBeTruthy();
  });

  it("T-COMMENT-4: posting a comment calls onAddComment with the text", () => {
    const onAddComment = vi.fn();
    render(
      <ConfigCommentThread
        config_id="cfg-gansu-v1"
        comments={[]}
        onAddComment={onAddComment}
        loading={false}
      />
    );
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "Looks good to me." } });
    fireEvent.click(screen.getByRole("button", { name: /post/i }));
    expect(onAddComment).toHaveBeenCalledWith("Looks good to me.");
  });

  it("T-COMMENT-5: comments rendered in chronological order (oldest first)", () => {
    render(
      <ConfigCommentThread
        config_id="cfg-gansu-v1"
        comments={[agentComment, humanComment]}  // agentComment is older
        onAddComment={vi.fn()}
        loading={false}
      />
    );
    const agentEl = screen.getByTestId("comment-cmt-a1");
    const humanEl = screen.getByTestId("comment-cmt-h1");
    // agentComment (2026-06-10T10:00) should appear before humanComment (2026-06-10T11:00)
    expect(
      agentEl.compareDocumentPosition(humanEl) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("T-COMMENT-6: empty thread shows empty-state placeholder (no comments yet)", () => {
    render(
      <ConfigCommentThread
        config_id="cfg-gansu-v1"
        comments={[]}
        onAddComment={vi.fn()}
        loading={false}
      />
    );
    expect(screen.getByText(/no comments|be the first|add a note/i)).toBeTruthy();
  });
});
