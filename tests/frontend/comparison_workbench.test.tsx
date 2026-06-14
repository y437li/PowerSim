/**
 * Test suite: comparison_workbench.test.tsx
 * Contract: contracts/frontend/comparison_workbench.md
 *
 * Tests must be RED until implementation. Do NOT modify approved tests to make them pass.
 * Reviewer-added cases marked: // reviewer:
 */

import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { act } from "react-dom/test-utils";
import { describe, it, expect, beforeEach, vi, type Mock } from "vitest";

// Import under test (will fail until implemented)
import {
  deriveRegime,
  type FinanceRegime,
  type WorkbenchMode,
  type WorkbenchVariant,
  type FinanceResultSummary,
  type SavedConfig,
  type SizingSweepResult,
  type SharedScenario,
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

// ─── Fixtures ────────────────────────────────────────────────────────────────

const SHARED_SCENARIO_R2: SharedScenario = {
  price_path_name: "declining-real",
  m_draws: 50,
  sample_kind: "synthetic",
  wacc_pct: 7.0,
  horizon_years: 20,
};

const FINANCE_RESULT_R2: FinanceResultSummary = {
  regime: "R2",
  sample_kind: "synthetic",
  m_draws: 50,
  irr_p50_pct: 8.2,
  irr_p90_pct: 7.6,
  npv_p50_yuan: 142_000_000,    // ¥142M
  npv_p90_yuan: 118_000_000,
  mirr_p50_pct: 7.1,
  lcoe_yuan_per_mwh: 312,
  payback_p50_yr: 8.3,
  worst_year_cashflow_yuan: -12_000_000,
  max_drawdown_yuan: 842_000_000,
  worst_npv_yuan: -38_000_000,
  best_npv_yuan: 200_000_000,
  p_npv_negative_pct: 18,
  p_irr_below_hurdle_pct: 24,
  cvar_5pct_yuan: -76_000_000,
};

const FINANCE_RESULT_R1: FinanceResultSummary = {
  regime: "R1",
  sample_kind: "synthetic",
  m_draws: 1,
  irr_p50_pct: 8.2,
  irr_p90_pct: null,
  npv_p50_yuan: 142_000_000,
  npv_p90_yuan: null,
  mirr_p50_pct: 7.1,
  lcoe_yuan_per_mwh: 312,
  payback_p50_yr: 8.3,
  worst_year_cashflow_yuan: -12_000_000,
  max_drawdown_yuan: 842_000_000,
  worst_npv_yuan: null,
  best_npv_yuan: null,
  p_npv_negative_pct: null,
  p_irr_below_hurdle_pct: null,
  cvar_5pct_yuan: null,
};

const FINANCE_RESULT_R3: FinanceResultSummary = {
  regime: "R3",
  sample_kind: "empirical",
  m_draws: 10,
  irr_p50_pct: 7.9,
  irr_p90_pct: null,          // tail-suppressed at R3
  npv_p50_yuan: 135_000_000,
  npv_p90_yuan: null,          // tail-suppressed
  mirr_p50_pct: 6.8,
  lcoe_yuan_per_mwh: 318,
  payback_p50_yr: 8.7,
  worst_year_cashflow_yuan: -15_000_000,
  max_drawdown_yuan: 890_000_000,
  worst_npv_yuan: -45_000_000,  // min of 10 runs
  best_npv_yuan: 195_000_000,   // max of 10 runs
  p_npv_negative_pct: 20,       // 2/10 runs = 20%
  p_irr_below_hurdle_pct: null, // tail-suppressed
  cvar_5pct_yuan: null,         // tail-suppressed
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
    finance: null,
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
    policy_count: 2,
    eval_count: 3,
    ...overrides,
  };
}

// ─── §1. deriveRegime (pure function) ────────────────────────────────────────

describe("§1 deriveRegime — D39 regime derivation", () => {
  it("T-REGIME-1: distribution_valid=false → R1 regardless of sample_kind", () => {
    // R1 is M=1 (point estimate). Backend sets distribution_valid=false.
    expect(deriveRegime(false, "synthetic")).toBe("R1");
    expect(deriveRegime(false, "empirical")).toBe("R1");
  });

  it("T-REGIME-2: distribution_valid=true + sample_kind=synthetic → R2", () => {
    // R2 = M≥50 bootstrap (synthetic draws)
    expect(deriveRegime(true, "synthetic")).toBe("R2");
  });

  it("T-REGIME-3: distribution_valid=true + sample_kind=empirical → R3", () => {
    // R3 = M≈10 real ERA5 years
    expect(deriveRegime(true, "empirical")).toBe("R3");
  });

  // reviewer: naming discipline — function must NOT reference the strings "R1/R2/R3"
  // as data-source labels (only M-regime labels)
  it("T-REGIME-4: sample_kind is the data-source axis, NOT a regime label", () => {
    // The return value "R1"/"R2"/"R3" is the M-regime only.
    // The sample_kind input uses "synthetic"/"empirical" — never "R1"/"r1" etc.
    const regime = deriveRegime(true, "synthetic");
    // sample_kind itself is NOT "R2"; regime is
    expect(regime).not.toBe("synthetic");
    expect(regime).not.toBe("empirical");
  });
});

// ─── §2. WorkbenchModeSelector ───────────────────────────────────────────────

describe("§2 WorkbenchModeSelector — D42 two-mode discipline", () => {
  it("T-MODE-1: renders both mode buttons", () => {
    render(
      <WorkbenchModeSelector
        mode="compare_designs"
        onChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("mode-compare-designs")).toBeTruthy();
    expect(screen.getByTestId("mode-press-test")).toBeTruthy();
  });

  it("T-MODE-2: active mode has aria-pressed=true", () => {
    render(
      <WorkbenchModeSelector mode="compare_designs" onChange={vi.fn()} />
    );
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
  });
});

// ─── §3. ScenarioLockBar ─────────────────────────────────────────────────────

describe("§3 ScenarioLockBar — compare_designs locked scenario", () => {
  it("T-LOCKBAR-1: renders lock icon + scenario summary", () => {
    render(
      <ScenarioLockBar
        scenario={SHARED_SCENARIO_R2}
        onUnlock={vi.fn()}
      />
    );
    const bar = screen.getByTestId("scenario-lock-bar");
    expect(bar).toBeTruthy();
    // shows price path, M, WACC
    expect(bar.textContent).toMatch(/declining-real/);
    expect(bar.textContent).toMatch(/M=50/);
    expect(bar.textContent).toMatch(/7\.0%/);
  });

  it("T-LOCKBAR-2: contains lock icon visual marker", () => {
    render(<ScenarioLockBar scenario={SHARED_SCENARIO_R2} onUnlock={vi.fn()} />);
    const bar = screen.getByTestId("scenario-lock-bar");
    // 🔒 or text "locked" must be present
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

  it("T-TIER-5: eval_needed shows estimate when provided", () => {
    // 120 s = ~2 min
    render(<ExecutionPlanBadge tier="eval_needed" estimatedSeconds={120} />);
    // should mention "2 min" or ">1 min" or similar
    expect(screen.getByText(/min/i)).toBeTruthy();
  });
});

// ─── §5. ComparisonTable — Regime display ────────────────────────────────────

describe("§5 ComparisonTable — R1 suppression (M=1)", () => {
  const baselineR1 = makeVariant({ finance_result: FINANCE_RESULT_R1 });

  it("T-R1-1: regime banner shown at R1", () => {
    render(
      <ComparisonTable
        variants={[baselineR1]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
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
      />
    );
    // At least one cell with the exact suppression string for P90
    const cells = screen.getAllByText("— (M > 1 required)");
    expect(cells.length).toBeGreaterThanOrEqual(1);
  });

  it("T-R1-3: Worst NPV cell suppressed at R1", () => {
    render(
      <ComparisonTable
        variants={[baselineR1]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
      />
    );
    // Worst NPV row should show suppressed value
    // The row label "Worst NPV" should exist but its value cell = suppressed
    const worstNpvLabel = screen.queryByText(/Worst NPV/i);
    expect(worstNpvLabel).toBeTruthy();
    // Value should be suppressed, not a number
    expect(screen.queryByText(/-38|38,000/)).toBeNull();
  });

  it("T-R1-4: P50 IRR is shown at R1 (not suppressed)", () => {
    // IRR P50 = 8.2% should be visible at R1
    render(
      <ComparisonTable
        variants={[baselineR1]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
      />
    );
    expect(screen.getByText(/8\.2%/)).toBeTruthy();
  });

  it("T-R1-5: worst-year cash flow is shown at R1 (single-trajectory, always available)", () => {
    // worst_year_cashflow_yuan = -12M — this should appear even at R1
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R1 })]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
      />
    );
    // Should show worst single-year cash flow
    expect(screen.getByText(/−?¥?12|worst.year/i)).toBeTruthy();
  });
});

describe("§5 ComparisonTable — R2 no suppression (M≥50)", () => {
  const baselineR2 = makeVariant({ finance_result: FINANCE_RESULT_R2 });

  it("T-R2-1: no regime banner at R2", () => {
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
      />
    );
    expect(screen.queryByText(/M > 1 required/i)).toBeNull();
    expect(screen.queryByText(/tail-suppressed/i)).toBeNull();
  });

  it("T-R2-2: IRR P90 shown at R2", () => {
    // 7.6%
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
      />
    );
    expect(screen.getByText(/7\.6%/)).toBeTruthy();
  });

  it("T-R2-3: Worst NPV shown at R2", () => {
    // -38M
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
      />
    );
    expect(screen.getByText(/−?¥?38|38,000/)).toBeTruthy();
  });

  it("T-R2-4: P(NPV<0) shown at R2", () => {
    // 18%
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
      />
    );
    expect(screen.getByText(/18%/)).toBeTruthy();
  });

  it("T-R2-5: CVaR-5% shown at R2", () => {
    // -76M
    render(
      <ComparisonTable
        variants={[baselineR2]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
      />
    );
    expect(screen.getByText(/−?¥?76|76,000/)).toBeTruthy();
  });
});

describe("§5 ComparisonTable — R3 partial suppression (M≈10 empirical)", () => {
  const baselineR3 = makeVariant({ finance_result: FINANCE_RESULT_R3 });

  it("T-R3-1: regime banner shown at R3", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
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
      />
    );
    const suppressed = screen.getAllByText("— (tail-suppressed)");
    expect(suppressed.length).toBeGreaterThanOrEqual(1);
  });

  it("T-R3-3: Worst NPV shown at R3 (= min of M=10 runs)", () => {
    // worst_npv_yuan = -45M
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
      />
    );
    expect(screen.getByText(/−?¥?45|45,000/)).toBeTruthy();
  });

  it("T-R3-4: Best NPV shown at R3 (= max of M=10 runs)", () => {
    // best_npv_yuan = 195M
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
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
      />
    );
    expect(screen.getByText(/20%/)).toBeTruthy();
  });

  it("T-R3-6: CVaR-5% suppressed at R3", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
      />
    );
    // CVaR should be suppressed (not showing null value as a number)
    expect(screen.queryByText(/CVaR.*76|−76/i)).toBeNull();
  });

  it("T-R3-7: P(IRR<hurdle) suppressed at R3", () => {
    render(
      <ComparisonTable
        variants={[baselineR3]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
      />
    );
    // p_irr_below_hurdle_pct is null at R3; should not show a number
    expect(screen.queryByText(/IRR.*24%|24%.*IRR/i)).toBeNull();
  });
});

// ─── §6. Mixed-regime comparison ─────────────────────────────────────────────

describe("§6 ComparisonTable — mixed-regime (baseline R2, variant R1)", () => {
  it("T-MIXED-1: table uses minimum regime (R1) when any variant is R1", () => {
    // Baseline = R2, Variant A = R1 → whole table uses R1 suppression
    const baseline = makeVariant({
      id: "var-baseline",
      is_baseline: true,
      finance_result: FINANCE_RESULT_R2,
    });
    const variantA = makeVariant({
      id: "var-a",
      label: "A",
      is_baseline: false,
      finance_result: FINANCE_RESULT_R1,
    });
    render(
      <ComparisonTable
        variants={[baseline, variantA]}
        baselineId="var-baseline"
        regime="R1"  // caller resolves minimum regime
        hurdle_rate_pct={7.0}
      />
    );
    // The "⚠ Some variants have M=1" warning banner
    expect(screen.getByText(/some variants.*M=1|M=1.*all.*suppressed/i)).toBeTruthy();
  });

  it("T-MIXED-2: suppression warning mentions re-running with M≥50", () => {
    const baseline = makeVariant({ finance_result: FINANCE_RESULT_R1 });
    render(
      <ComparisonTable
        variants={[baseline]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
      />
    );
    expect(screen.getByText(/M.*50|re.run.*M/i)).toBeTruthy();
  });
});

// ─── §7. Delta display ────────────────────────────────────────────────────────

describe("§7 ComparisonTable — delta display vs baseline", () => {
  it("T-DELTA-1: baseline column shows absolute values (no delta)", () => {
    // IRR P50 = 8.2% for baseline → shown as "8.2%", NOT "+0.0 pp"
    const baseline = makeVariant({ finance_result: FINANCE_RESULT_R2 });
    render(
      <ComparisonTable
        variants={[baseline]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
      />
    );
    // absolute value present
    expect(screen.getByText(/8\.2%/)).toBeTruthy();
    // no delta prefix on baseline
    expect(screen.queryByText(/\+0\.0 pp/)).toBeNull();
  });

  it("T-DELTA-2: variant column shows delta + absolute for IRR", () => {
    // Baseline IRR P50 = 8.2%; Variant IRR P50 = 8.7% → delta = +0.5 pp
    const baseline = makeVariant({
      id: "var-baseline",
      is_baseline: true,
      finance_result: FINANCE_RESULT_R2,
    });
    const variantA = makeVariant({
      id: "var-a",
      label: "A (SST)",
      is_baseline: false,
      finance_result: { ...FINANCE_RESULT_R2, irr_p50_pct: 8.7, irr_p90_pct: 8.1 },
    });
    render(
      <ComparisonTable
        variants={[baseline, variantA]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
      />
    );
    // Variant A column: should show +0.5 pp delta
    expect(screen.getByText(/\+0\.5 pp|\+0\.5pp/)).toBeTruthy();
  });

  it("T-DELTA-3: downside delta — better = positive (less loss is better)", () => {
    // Baseline Worst NPV = -38M; Variant A Worst NPV = -22M
    // Delta = -22 - (-38) = +16M (variant is LESS exposed → positive = green)
    const baseline = makeVariant({
      id: "var-baseline",
      is_baseline: true,
      finance_result: FINANCE_RESULT_R2,
    });
    const variantA = makeVariant({
      id: "var-a",
      label: "A (SST)",
      is_baseline: false,
      finance_result: { ...FINANCE_RESULT_R2, worst_npv_yuan: -22_000_000 },
    });
    render(
      <ComparisonTable
        variants={[baseline, variantA]}
        baselineId="var-baseline"
        regime="R2"
        hurdle_rate_pct={7.0}
      />
    );
    // +¥16M (less exposed) should appear for the Worst NPV row
    expect(screen.getByText(/\+¥?16M|\+16M|\+16,000/)).toBeTruthy();
  });

  it("T-DELTA-4: re-designation of baseline flips all deltas", () => {
    // After re-designating baseline from "var-baseline" to "var-a",
    // "var-a" column should show absolute values and "var-baseline" should show delta.
    const v1 = makeVariant({
      id: "var-baseline",
      is_baseline: false,  // no longer baseline
      finance_result: { ...FINANCE_RESULT_R2, irr_p50_pct: 8.2 },
    });
    const v2 = makeVariant({
      id: "var-a",
      label: "A (SST)",
      is_baseline: true,   // now the baseline
      finance_result: { ...FINANCE_RESULT_R2, irr_p50_pct: 8.7 },
    });
    render(
      <ComparisonTable
        variants={[v1, v2]}
        baselineId="var-a"  // var-a is now the baseline
        regime="R2"
        hurdle_rate_pct={7.0}
      />
    );
    // var-a column shows absolute 8.7%
    expect(screen.getByText(/8\.7%/)).toBeTruthy();
    // var-baseline column shows delta: 8.2 - 8.7 = -0.5 pp
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
    // First added = baseline by default (D42 §7.2)
    useWorkbenchStore.getState().addVariant({
      label: "Baseline",
      config_id: "cfg-1",
      config_hash: "#abc",
      policy: null,
      eval_result_id: null,
      finance: null,
      price_path_name: null,
    });
    const state = useWorkbenchStore.getState();
    expect(state.variants.length).toBe(1);
    expect(state.variants[0].is_baseline).toBe(true);
    expect(state.baselineId).toBe(state.variants[0].id);
  });

  it("T-STORE-3: exactly one baseline at all times after designateBaseline", () => {
    const store = useWorkbenchStore.getState();
    store.addVariant({ label: "A", config_id: "c1", config_hash: "#a", policy: null, eval_result_id: null, finance: null, price_path_name: null });
    store.addVariant({ label: "B", config_id: "c2", config_hash: "#b", policy: null, eval_result_id: null, finance: null, price_path_name: null });
    const state = useWorkbenchStore.getState();
    const [varA, varB] = state.variants;

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
    // NpvFanChart bands shown by default
    expect(useWorkbenchStore.getState().showBands).toBe(true);
  });

  it("T-STORE-6: removeVariant with the only variant resets baselineId to null", () => {
    const store = useWorkbenchStore.getState();
    store.addVariant({ label: "A", config_id: "c1", config_hash: "#a", policy: null, eval_result_id: null, finance: null, price_path_name: null });
    const varId = useWorkbenchStore.getState().variants[0].id;
    store.removeVariant(varId);
    const after = useWorkbenchStore.getState();
    expect(after.variants.length).toBe(0);
    expect(after.baselineId).toBeNull();
  });

  it("T-STORE-7: removeVariant on baseline promotes next variant as baseline", () => {
    const store = useWorkbenchStore.getState();
    store.addVariant({ label: "A", config_id: "c1", config_hash: "#a", policy: null, eval_result_id: null, finance: null, price_path_name: null });
    store.addVariant({ label: "B", config_id: "c2", config_hash: "#b", policy: null, eval_result_id: null, finance: null, price_path_name: null });
    const [varA] = useWorkbenchStore.getState().variants;
    expect(varA.is_baseline).toBe(true); // A is baseline
    store.removeVariant(varA.id);
    const after = useWorkbenchStore.getState();
    expect(after.variants.length).toBe(1);
    expect(after.variants[0].is_baseline).toBe(true); // B promoted
    expect(after.baselineId).toBe(after.variants[0].id);
  });

  // reviewer: compare_designs mode must not allow per-variant price path overrides
  it("T-STORE-8: in compare_designs mode, updateVariant price_path_name is blocked", () => {
    const store = useWorkbenchStore.getState();
    store.setMode("compare_designs");
    store.addVariant({ label: "A", config_id: "c1", config_hash: "#a", policy: null, eval_result_id: null, finance: null, price_path_name: null });
    const varId = useWorkbenchStore.getState().variants[0].id;
    // Attempting to set a per-variant price path in compare_designs mode should have no effect
    store.updateVariant(varId, { price_path_name: "stress" });
    const after = useWorkbenchStore.getState();
    expect(after.variants[0].price_path_name).toBeNull(); // unchanged
  });
});

// ─── §9. SizingSweepPanel ────────────────────────────────────────────────────

describe("§9 SizingSweepPanel — 2D battery sizing", () => {
  const defaultConfig = {
    base_config_id: "cfg-gansu-v1",
    energy_mwh_min: 100,
    energy_mwh_max: 600,
    energy_steps: 6,
    power_mw_min: 50,
    power_mw_max: 300,
    power_steps: 6,
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

  it("T-SWEEP-2: shows config count: 6×6=36 configs", () => {
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

  it("T-SWEEP-3: while running, shows progress bar", () => {
    const partialResult: Partial<SizingSweepResult> = {
      status: "running",
      configs_total: 36,
      configs_done: 12,
    };
    render(
      <SizingSweepPanel
        sweepConfig={defaultConfig}
        sweepResult={partialResult as SizingSweepResult}
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
      configs_total: 36,
      configs_done: 36,
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

  it("T-SWEEP-7: clicking a point calls onAddPointAsVariant with correct indices", () => {
    // This test is structural — the actual click on SurfaceChart is tested via
    // the chart component's onPointSelect callback being forwarded correctly.
    const onAdd = vi.fn();
    const completeResult: SizingSweepResult = {
      run_id: "sweep-001",
      status: "complete",
      configs_total: 4,
      configs_done: 4,
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
    // The SurfaceChart stub should render with a data-testid for the recommended point
    const recPoint = screen.getByTestId("surface-recommended-point");
    fireEvent.click(recPoint);
    expect(onAdd).toHaveBeenCalledWith(1, 1); // recommended_energy_idx, recommended_power_idx
  });
});

// ─── §10. AddToComparisonModal ────────────────────────────────────────────────

describe("§10 AddToComparisonModal — wizard entry points", () => {
  it("T-MODAL-1: renders with label input and Add button", () => {
    render(
      <AddToComparisonModal
        config_id="cfg-1"
        onAdd={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByLabelText(/label/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /add/i })).toBeTruthy();
  });

  it("T-MODAL-2: onCancel called on Cancel button", () => {
    const onCancel = vi.fn();
    render(
      <AddToComparisonModal config_id="cfg-1" onAdd={vi.fn()} onCancel={onCancel} />
    );
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("T-MODAL-3: onAdd called with label and asBaseline=false by default", () => {
    const onAdd = vi.fn();
    render(
      <AddToComparisonModal config_id="cfg-1" onAdd={onAdd} onCancel={vi.fn()} />
    );
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
      <ConfigCard
        config={config}
        selected={false}
        onToggleSelect={vi.fn()}
        onFork={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onPressTest={vi.fn()}
      />
    );
    expect(screen.getByText("Gansu-v1")).toBeTruthy();
  });

  it("T-CARD-2: shows battery sizing summary (MWh and MW)", () => {
    render(
      <ConfigCard
        config={config}
        selected={false}
        onToggleSelect={vi.fn()}
        onFork={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onPressTest={vi.fn()}
      />
    );
    // 300 MWh, 150 MW
    expect(screen.getByText(/300.*MWh|300 MWh/)).toBeTruthy();
    expect(screen.getByText(/150.*MW/)).toBeTruthy();
  });

  it("T-CARD-3: shows policy_count and eval_count", () => {
    render(
      <ConfigCard
        config={config}
        selected={false}
        onToggleSelect={vi.fn()}
        onFork={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onPressTest={vi.fn()}
      />
    );
    expect(screen.getByText(/2.*polic|polic.*2/i)).toBeTruthy();
    expect(screen.getByText(/3.*eval|eval.*3/i)).toBeTruthy();
  });

  it("T-CARD-4: onToggleSelect called when clicking the select toggle", () => {
    const onToggleSelect = vi.fn();
    render(
      <ConfigCard
        config={config}
        selected={false}
        onToggleSelect={onToggleSelect}
        onFork={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onPressTest={vi.fn()}
      />
    );
    const toggle = screen.getByRole("checkbox");
    fireEvent.click(toggle);
    expect(onToggleSelect).toHaveBeenCalledTimes(1);
  });

  it("T-CARD-5: forked config shows parent reference", () => {
    const forked = makeSavedConfig({ parent_id: "cfg-gansu-v0", label: "Gansu-v1-SST" });
    render(
      <ConfigCard
        config={forked}
        selected={false}
        onToggleSelect={vi.fn()}
        onFork={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onPressTest={vi.fn()}
      />
    );
    expect(screen.getByText(/forked from|parent/i)).toBeTruthy();
  });
});

// ─── §12. PerConfigDetail ────────────────────────────────────────────────────

describe("§12 PerConfigDetail — downside risk panel first", () => {
  it("T-PCD-1: DownsideRiskPanel appears before headline upside metrics", () => {
    render(
      <PerConfigDetail
        variant={makeVariant()}
        regime="R2"
        onPressTest={vi.fn()}
        onNext={vi.fn()}
        onPrev={vi.fn()}
        hasPrev={false}
        hasNext={false}
      />
    );
    const container = screen.getByRole("main") || document.body;
    // Downside risk section must come before IRR P50 upside section
    const worstNpv = screen.getByText(/Worst NPV/i);
    const irrP50 = screen.getByText(/IRR.*P50|IRR.*8\.2/i);
    // compareDocumentPosition: downside before upside in DOM order
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
        onNext={vi.fn()}
        onPrev={vi.fn()}
        hasPrev={false}
        hasNext={false}
      />
    );
    expect(screen.getByRole("button", { name: /press.test/i })).toBeTruthy();
  });

  it("T-PCD-3: Prev/Next navigation buttons present and disabled when not available", () => {
    render(
      <PerConfigDetail
        variant={makeVariant()}
        regime="R2"
        onPressTest={vi.fn()}
        onNext={vi.fn()}
        onPrev={vi.fn()}
        hasPrev={false}
        hasNext={false}
      />
    );
    const prevBtn = screen.getByRole("button", { name: /prev|←/i });
    const nextBtn = screen.getByRole("button", { name: /next|→/i });
    expect(prevBtn).toBeDisabled();
    expect(nextBtn).toBeDisabled();
  });

  it("T-PCD-4: at R1, DownsideRiskPanel cells are suppressed", () => {
    render(
      <PerConfigDetail
        variant={makeVariant({ finance_result: FINANCE_RESULT_R1 })}
        regime="R1"
        onPressTest={vi.fn()}
        onNext={vi.fn()}
        onPrev={vi.fn()}
        hasPrev={false}
        hasNext={false}
      />
    );
    // Worst NPV cell should be suppressed
    expect(screen.queryByText(/−38M/)).toBeNull();
    expect(screen.getAllByText("— (M > 1 required)").length).toBeGreaterThanOrEqual(1);
  });
});

// ─── §13. Naming discipline guard ────────────────────────────────────────────

describe("§13 Naming discipline — R1/R2/R3 must not appear as data-source labels", () => {
  // reviewer: guard that no visible UI text uses "R1"/"R2"/"R3" to label a data SOURCE
  // (like "R1 = synthetic"). Those labels are exclusively for M-regime display.

  it("T-NAME-1: ScenarioLockBar does not render 'R1', 'R2', or 'R3' as text", () => {
    render(<ScenarioLockBar scenario={SHARED_SCENARIO_R2} onUnlock={vi.fn()} />);
    const bar = screen.getByTestId("scenario-lock-bar");
    // The bar may show M=50 or sample_kind but NOT the label "R2"
    expect(bar.textContent).not.toMatch(/\bR2\b|\bR1\b|\bR3\b/);
  });

  it("T-NAME-2: RegimeBanner at R1 shows 'M=1' not 'R1' to describe data source", () => {
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R1 })]}
        baselineId="var-baseline"
        regime="R1"
        hurdle_rate_pct={7.0}
      />
    );
    // Banner must NOT read "R1 mode" — it must describe M=1
    const banner = screen.getByText(/M=1|M > 1 required|single.*trajectory/i);
    expect(banner).toBeTruthy();
  });

  it("T-NAME-3: R3 banner references 'empirical' or 'M≈10' not 'R3 mode'", () => {
    render(
      <ComparisonTable
        variants={[makeVariant({ finance_result: FINANCE_RESULT_R3 })]}
        baselineId="var-baseline"
        regime="R3"
        hurdle_rate_pct={7.0}
      />
    );
    const banner = screen.getByText(/empirical|M.*10/i);
    expect(banner).toBeTruthy();
    // Must not use "R3" as a visible user-facing label
    expect(banner.textContent).not.toMatch(/\bR3 mode\b|\bR3 ensemble\b/i);
  });
});

// ─── §14. Workbench — no WebSocket, no telemetry store ───────────────────────

describe("§14 Workbench isolation — batch-only, no live telemetry", () => {
  // reviewer: workbench must never access the live telemetry store (D42 architectural invariant)
  it("T-ISO-1: useWorkbenchStore does not expose any telemetry fields", () => {
    const state = useWorkbenchStore.getState();
    // Telemetry store fields that must NOT exist here
    expect((state as Record<string, unknown>).soc_pct).toBeUndefined();
    expect((state as Record<string, unknown>).power_flow_kw).toBeUndefined();
    expect((state as Record<string, unknown>).env_step).toBeUndefined();
    expect((state as Record<string, unknown>).websocket).toBeUndefined();
  });
});
