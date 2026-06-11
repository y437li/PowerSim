/**
 * Live Operations Dashboard — contract + tests
 * Contract: contracts/frontend/live_dashboard.md
 * Telemetry schema: contracts/shared/telemetry_schema.md v1.0.0 (LOCKED)
 * Golden fixtures:  contracts/shared/telemetry_examples/env_step_a.json
 *                   contracts/shared/telemetry_examples/env_step_b.json
 *
 * ALL tests are intentionally RED — no implementation exists yet.
 * validate-telemetry skill: tests include full-message validation against golden fixtures.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// ── Golden fixtures ──────────────────────────────────────────────────────────
import envStepAGolden from "../../contracts/shared/telemetry_examples/env_step_a.json";
import envStepBGolden from "../../contracts/shared/telemetry_examples/env_step_b.json";

// ── SUT imports (RED until implementation exists) ────────────────────────────
import { LiveDashboard }      from "../../src/routes/LiveDashboard";
import { CostBreakdownCard }  from "../../src/components/live/CostBreakdownCard";
import { MonthPeakCard }      from "../../src/components/live/MonthPeakCard";
import { AlertList }          from "../../src/components/live/AlertList";
import { SocTimeline }        from "../../src/components/live/SocTimeline";
import { PriceTimeline }      from "../../src/components/live/PriceTimeline";
import { PowerFlowsTable }    from "../../src/components/live/PowerFlowsTable";
import { getTouTier, getTouPrice, TOU_SCHEDULE, computeBandSegments } from "../../src/utils/touSchedule";
import { deriveAlerts }       from "../../src/utils/deriveAlerts";
import { socToPercent, formatYuan, formatPower } from "../../src/utils/units";
import type {
  EnvStepPayload,
  PerStepCosts,
  CumulativeCosts,
  PowerFlows,
  GenerationBlock,
  TelemetryEnvelope,
} from "../../src/types/telemetry";

// ── Store mock ───────────────────────────────────────────────────────────────
vi.mock("../../src/stores/telemetryStore", () => ({
  useTelemetryStore: vi.fn(),
}));
import { useTelemetryStore } from "../../src/stores/telemetryStore";

// ── Fixtures ─────────────────────────────────────────────────────────────────
const GOLDEN_A: EnvStepPayload = envStepAGolden.payload as EnvStepPayload;
const GOLDEN_B: EnvStepPayload = envStepBGolden.payload as EnvStepPayload;

function emptyTelemetryState() {
  return {
    wsStatus: "connected" as const,
    envStep: null,
    history: [],
    runId: null,
    lastSeq: null,
    seqGap: false,
    historyMaxLen: 168,
    // §13.2 additions — keep mock in sync with TelemetryState interface
    frameErrors: [] as any[],
    receiveEnvStep: vi.fn(),
    setWsStatus: vi.fn(),
    clearHistory: vi.fn(),
    pushFrameError: vi.fn(),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 1 — Golden-fixture validation (validate-telemetry skill requirement)
// ─────────────────────────────────────────────────────────────────────────────
describe("validate-telemetry: env_step golden fixture conformance", () => {
  it("env_step_a envelope — required fields present with correct types", () => {
    const msg = envStepAGolden as TelemetryEnvelope;
    expect(msg.schema_version).toBe("1.0.0");
    expect(msg.kind).toBe("env_step");
    expect(typeof msg.ts_utc).toBe("string");
    expect(typeof msg.run_id).toBe("string");
    expect(typeof msg.seq).toBe("number");
    expect(msg.payload).toBeDefined();
  });

  it("env_step_a payload — LOCKED numeric fields present and finite", () => {
    const p = GOLDEN_A;
    expect(typeof p.step).toBe("number");
    expect(typeof p.episode).toBe("number");
    expect(p.dt_hours).toBe(1.0);
    expect(typeof p.sim_time_utc).toBe("string");
    expect(Number.isFinite(p.wind_speed_mps)).toBe(true);
    expect(Number.isFinite(p.irradiance_wm2)).toBe(true);
    expect(Number.isFinite(p.temperature_c)).toBe(true);
    expect(Number.isFinite(p.load_mw)).toBe(true);
    expect(Number.isFinite(p.price_buy_yuan_per_mwh)).toBe(true);
    expect(Number.isFinite(p.price_sell_yuan_per_mwh)).toBe(true);
  });

  it("env_step_a — sell price ≤ buy price (D7 spread clamp ≥0)", () => {
    // D7: sell = max(0, buy − spread) — always ≤ buy; 590 ≤ 620
    expect(GOLDEN_A.price_sell_yuan_per_mwh).toBeLessThanOrEqual(
      GOLDEN_A.price_buy_yuan_per_mwh
    );
  });

  it("env_step_a — SOC within D4 bounds [0.2, 0.9]", () => {
    expect(GOLDEN_A.battery.soc).toBeGreaterThanOrEqual(0.2);
    expect(GOLDEN_A.battery.soc).toBeLessThanOrEqual(0.9);
  });

  it("env_step_a — D13 real-money additive identity: cost_total_real == sum of 5 summands", () => {
    // D13: cost_total_real = c_energy + c_demand_charge + c_degradation + c_curtail + c_voll
    // Step A: −53100 + 0 + 400 + 0 + 0 = −52700
    const { c_energy_yuan, c_demand_charge_yuan, c_degradation_yuan,
            c_curtail_yuan, c_voll_yuan, cost_total_real_yuan } = GOLDEN_A.costs;
    const computed = c_energy_yuan + c_demand_charge_yuan + c_degradation_yuan
                   + c_curtail_yuan + c_voll_yuan;
    expect(computed).toBeCloseTo(cost_total_real_yuan, 2);
    // Hand check: −53100 + 0 + 400 + 0 + 0 = −52700
    expect(cost_total_real_yuan).toBeCloseTo(-52700, 2);
  });

  it("env_step_a — c_energy decomposition: c_energy == c_import − r_export", () => {
    // D13: c_energy = c_import − r_export; display-only — NOT additional summands
    // Step A: 0 − 53100 = −53100
    const { c_energy_yuan, c_import_yuan, r_export_yuan } = GOLDEN_A.costs;
    expect(c_import_yuan - r_export_yuan).toBeCloseTo(c_energy_yuan, 2);
    // Hand check: 0 − 53100 = −53100; r_export = 90 MW × 1 h × 590 ¥/MWh = 53100
    expect(r_export_yuan).toBeCloseTo(53100, 2);
  });

  it("env_step_a — reward formula: reward == −(cost_total_reward_basis + penalty)×1e-5", () => {
    // §3.5: reward = −(cost_total_reward_basis_yuan + penalty_yuan) × 1e-5
    // Step A: −(−52700 + 0)×1e-5 = 0.527
    const { cost_total_reward_basis_yuan, penalty_yuan } = GOLDEN_A.costs;
    const expected = -(cost_total_reward_basis_yuan + penalty_yuan) * 1e-5;
    expect(GOLDEN_A.reward).toBeCloseTo(expected, 5);
    expect(GOLDEN_A.reward).toBeCloseTo(0.527, 3);
  });

  it("env_step_a — solar conservation: solar flows + curtailed == gross_solar_mw", () => {
    // §3.6 row 14: per-source energy conservation
    const { solar_to_load_mw, solar_to_bat_mw, solar_to_grid_mw, solar_curtailed_mw } = GOLDEN_A.flows;
    const sum = solar_to_load_mw + solar_to_bat_mw + solar_to_grid_mw + solar_curtailed_mw;
    expect(sum).toBeCloseTo(GOLDEN_A.generation.gross_solar_mw, 5);
  });

  it("env_step_a — wind conservation: wind flows + curtailed == gross_wind_mw", () => {
    const { wind_to_load_mw, wind_to_bat_mw, wind_to_grid_mw, wind_curtailed_mw } = GOLDEN_A.flows;
    const sum = wind_to_load_mw + wind_to_bat_mw + wind_to_grid_mw + wind_curtailed_mw;
    expect(sum).toBeCloseTo(GOLDEN_A.generation.gross_wind_mw, 5);
  });

  it("env_step_b — month-boundary: cost_total_real includes demand charge (D10)", () => {
    // Step B: c_energy=10000 + c_demand_charge=3040000 + c_degradation=400 = 3050400
    // month_peak=95 MW × rate=32000 ¥/MW·month = 3040000
    const { c_energy_yuan, c_demand_charge_yuan, c_degradation_yuan,
            c_curtail_yuan, c_voll_yuan, cost_total_real_yuan } = GOLDEN_B.costs;
    const computed = c_energy_yuan + c_demand_charge_yuan + c_degradation_yuan
                   + c_curtail_yuan + c_voll_yuan;
    expect(computed).toBeCloseTo(cost_total_real_yuan, 2);
    expect(cost_total_real_yuan).toBeCloseTo(3050400, 2);
  });

  it("env_step_b — reward-basis excludes demand charge but includes 2× demand-shape (D13)", () => {
    // Step B: cost_total_reward_basis = c_energy + 2×c_demand_shape + c_degradation + c_curtail + c_voll
    //       = 10000 + 2×5000 + 400 + 0 + 0 = 20400
    // NOTE: c_demand_charge (3040000) is NOT in reward basis
    const { c_energy_yuan, c_demand_shape_yuan, c_degradation_yuan,
            c_curtail_yuan, c_voll_yuan, cost_total_reward_basis_yuan } = GOLDEN_B.costs;
    const computed = c_energy_yuan + 2.0 * c_demand_shape_yuan + c_degradation_yuan
                   + c_curtail_yuan + c_voll_yuan;
    expect(computed).toBeCloseTo(cost_total_reward_basis_yuan, 2);
    expect(cost_total_reward_basis_yuan).toBeCloseTo(20400, 2);
  });

  it("env_step_b — demand charge = month_peak × demand_rate (D10)", () => {
    // 95 MW × 32000 ¥/MW·month = 3040000
    const { c_demand_charge_yuan, demand_rate_yuan_per_mw_month } = GOLDEN_B.costs;
    const expected = GOLDEN_B.month_peak_mw * demand_rate_yuan_per_mw_month;
    expect(c_demand_charge_yuan).toBeCloseTo(expected, 2);
    expect(c_demand_charge_yuan).toBeCloseTo(3040000, 2);
  });

  it("env_step_b — reward: −(20400 + 0)×1e-5 = −0.204", () => {
    expect(GOLDEN_B.reward).toBeCloseTo(-0.204, 3);
  });

  it("env_step_a — no NaN or Infinity in any numeric cost field", () => {
    const costs = GOLDEN_A.costs;
    for (const [key, val] of Object.entries(costs)) {
      expect(Number.isFinite(val), `${key} should be finite`).toBe(true);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 2 — TOU schedule: getTouTier() boundary tests (D8, C1)
// ALL 16 boundary points from contract §1 must be tested exactly.
// ─────────────────────────────────────────────────────────────────────────────
describe("TOU_SCHEDULE and getTouTier() — minute-accurate boundaries (D8)", () => {
  it("TOU_SCHEDULE exports 9 bands covering all 1440 minutes", () => {
    expect(TOU_SCHEDULE).toHaveLength(9);
    // Sum of all band durations must equal 1440 min (24 h)
    const totalMin = TOU_SCHEDULE.reduce((s, b) => s + (b.toMinutes - b.fromMinutes), 0);
    expect(totalMin).toBe(1440);
  });

  it("valley: 00:00 (min 0) → valley", () => {
    expect(getTouTier(0)).toBe("valley");
  });

  it("mid: 07:00 (min 420) → mid (transition from valley)", () => {
    // 420 min = 07:00; valley ends at 420 (exclusive), mid starts at 420 (inclusive)
    expect(getTouTier(420)).toBe("mid");
  });

  it("mid last minute: 07:59 (min 479) → mid", () => {
    expect(getTouTier(479)).toBe("mid");
  });

  it("peak: 08:00 (min 480) → peak (transition from mid)", () => {
    expect(getTouTier(480)).toBe("peak");
  });

  it("peak last before critical: 10:29 (min 629) → peak", () => {
    // 629 min = 10 h 29 min; critical-peak starts at 10:30 (630 min)
    expect(getTouTier(629)).toBe("peak");
  });

  it("critical_peak: 10:30 (min 630) → critical_peak (exact boundary, D8)", () => {
    // This is the KEY test — wrong boundary (660 = 11:00) would return "peak" here
    expect(getTouTier(630)).toBe("critical_peak");
  });

  it("critical_peak: 11:29 (min 689) → critical_peak", () => {
    expect(getTouTier(689)).toBe("critical_peak");
  });

  it("mid: 11:30 (min 690) → mid (transition from critical_peak, D8)", () => {
    // 690 min = 11:30; critical-peak ends at 690 (exclusive), mid resumes at 690
    expect(getTouTier(690)).toBe("mid");
  });

  it("mid: 17:59 (min 1079) → mid", () => {
    expect(getTouTier(1079)).toBe("mid");
  });

  it("peak: 18:00 (min 1080) → peak (afternoon peak)", () => {
    expect(getTouTier(1080)).toBe("peak");
  });

  it("peak: 18:59 (min 1139) → peak", () => {
    expect(getTouTier(1139)).toBe("peak");
  });

  it("critical_peak: 19:00 (min 1140) → critical_peak (evening window)", () => {
    expect(getTouTier(1140)).toBe("critical_peak");
  });

  it("critical_peak: 20:59 (min 1259) → critical_peak", () => {
    expect(getTouTier(1259)).toBe("critical_peak");
  });

  it("peak: 21:00 (min 1260) → peak (transition from evening critical)", () => {
    expect(getTouTier(1260)).toBe("peak");
  });

  it("peak: 22:59 (min 1379) → peak", () => {
    expect(getTouTier(1379)).toBe("peak");
  });

  it("valley: 23:00 (min 1380) → valley (late-night)", () => {
    expect(getTouTier(1380)).toBe("valley");
  });

  it("valley: 23:59 (min 1439) → valley", () => {
    expect(getTouTier(1439)).toBe("valley");
  });

  it("getTouPrice returns correct static buy prices per §3.7", () => {
    // §3.7: valley=250, mid=450, peak=620, critical_peak=780 ¥/MWh
    expect(getTouPrice("valley")).toBe(250);
    expect(getTouPrice("mid")).toBe(450);
    expect(getTouPrice("peak")).toBe(620);
    expect(getTouPrice("critical_peak")).toBe(780);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 3 — deriveAlerts() pure function
// ─────────────────────────────────────────────────────────────────────────────
describe("deriveAlerts() — pure alert derivation from history", () => {
  it("clean step (golden A) → no alerts", () => {
    // GOLDEN_A: all curtailed=0, load_unserved=0, soc_violation=0
    const alerts = deriveAlerts([GOLDEN_A]);
    expect(alerts).toHaveLength(0);
  });

  it("step with solar curtailment → curtailment alert with c_curtail_yuan penalty", () => {
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      flows: { ...GOLDEN_A.flows, solar_curtailed_mw: 12.5 },
      costs: { ...GOLDEN_A.costs, c_curtail_yuan: 10000.0 },
    };
    const alerts = deriveAlerts([step]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe("curtailment");
    expect(alerts[0].penaltyYuan).toBe(10000.0);
    // detail shows total curtailed: 12.5 MW
    expect(alerts[0].detail).toContain("12.5");
  });

  it("step with wind curtailment → curtailment alert; detail sums all curtailed sources", () => {
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      flows: {
        ...GOLDEN_A.flows,
        solar_curtailed_mw: 5.0,
        wind_curtailed_mw: 7.5,
        bat_curtailed_mw: 2.0,
      },
      costs: { ...GOLDEN_A.costs, c_curtail_yuan: 11600.0 },
    };
    const alerts = deriveAlerts([step]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe("curtailment");
    // total curtailed = 5 + 7.5 + 2 = 14.5 MW; detail contains "14.5"
    expect(alerts[0].detail).toContain("14.5");
  });

  it("step with unserved load → voll alert with c_voll_yuan penalty", () => {
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      flows: { ...GOLDEN_A.flows, load_unserved_mw: 3.0 },
      costs: { ...GOLDEN_A.costs, c_voll_yuan: 9000.0 },
    };
    const alerts = deriveAlerts([step]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe("voll");
    expect(alerts[0].penaltyYuan).toBe(9000.0);
    expect(alerts[0].detail).toContain("3.0");
  });

  it("step with SOC violation → soc_violation alert with penalty_yuan", () => {
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      battery: { ...GOLDEN_A.battery, soc_violation_mwh: 0.5 },
      costs: { ...GOLDEN_A.costs, penalty_yuan: 10000.0 },
    };
    const alerts = deriveAlerts([step]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe("soc_violation");
    expect(alerts[0].penaltyYuan).toBe(10000.0);
    // detail contains overshoot MWh
    expect(alerts[0].detail).toContain("0.50");
  });

  it("step with multiple event types → multiple alerts", () => {
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      flows: {
        ...GOLDEN_A.flows,
        solar_curtailed_mw: 10.0,
        load_unserved_mw: 2.0,
      },
      battery: { ...GOLDEN_A.battery, soc_violation_mwh: 1.0 },
      costs: {
        ...GOLDEN_A.costs,
        c_curtail_yuan: 8000.0,
        c_voll_yuan: 6000.0,
        penalty_yuan: 20000.0,
      },
    };
    const alerts = deriveAlerts([step]);
    expect(alerts).toHaveLength(3);
    const kinds = alerts.map((a) => a.kind);
    expect(kinds).toContain("curtailment");
    expect(kinds).toContain("voll");
    expect(kinds).toContain("soc_violation");
  });

  it("multi-step history → alert per step that triggers", () => {
    const clean = GOLDEN_A;
    const dirty: EnvStepPayload = {
      ...GOLDEN_A,
      step: 200,
      flows: { ...GOLDEN_A.flows, solar_curtailed_mw: 5.0 },
      costs: { ...GOLDEN_A.costs, c_curtail_yuan: 4000.0 },
    };
    const alerts = deriveAlerts([clean, dirty, clean]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].stepIndex).toBe(200);
  });

  // ── Epsilon guard (finding #2) ───────────────────────────────────────────────
  it("sub-epsilon curtailment (0.0005 MW) → no alert (JAX float noise guard)", () => {
    // ALERT_EPSILON = 0.001 MW; 0.0005 < epsilon → suppress
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      flows: { ...GOLDEN_A.flows, solar_curtailed_mw: 0.0005 },
      costs: { ...GOLDEN_A.costs, c_curtail_yuan: 0.4 },
    };
    expect(deriveAlerts([step])).toHaveLength(0);
  });

  it("at-epsilon curtailment (0.001 MW) → no alert (boundary is exclusive: > epsilon)", () => {
    // 0.001 is NOT > 0.001 → suppressed
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      flows: { ...GOLDEN_A.flows, solar_curtailed_mw: 0.001 },
      costs: { ...GOLDEN_A.costs, c_curtail_yuan: 0.8 },
    };
    expect(deriveAlerts([step])).toHaveLength(0);
  });

  it("above-epsilon curtailment (0.0011 MW) → alert fires", () => {
    // 0.0011 > 0.001 → real event, alert must fire
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      flows: { ...GOLDEN_A.flows, solar_curtailed_mw: 0.0011 },
      costs: { ...GOLDEN_A.costs, c_curtail_yuan: 0.88 },
    };
    const alerts = deriveAlerts([step]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].kind).toBe("curtailment");
  });

  it("sub-epsilon VOLL (0.0005 MW unserved) → no alert", () => {
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      flows: { ...GOLDEN_A.flows, load_unserved_mw: 0.0005 },
      costs: { ...GOLDEN_A.costs, c_voll_yuan: 1.5 },
    };
    expect(deriveAlerts([step])).toHaveLength(0);
  });

  it("sub-epsilon SOC violation (0.0005 MWh) → no alert", () => {
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      battery: { ...GOLDEN_A.battery, soc_violation_mwh: 0.0005 },
      costs: { ...GOLDEN_A.costs, penalty_yuan: 10.0 },
    };
    expect(deriveAlerts([step])).toHaveLength(0);
  });

  // ── Newest-first ordering (finding #3) ──────────────────────────────────────
  it("multi-alert history → returned newest-first (descending stepIndex)", () => {
    // step 10 (older) has curtailment; step 20 (newer) has VOLL
    // expected output: [step-20-voll, step-10-curtailment]
    const step10: EnvStepPayload = {
      ...GOLDEN_A,
      step: 10,
      flows: { ...GOLDEN_A.flows, solar_curtailed_mw: 5.0 },
      costs: { ...GOLDEN_A.costs, c_curtail_yuan: 4000.0 },
    };
    const step20: EnvStepPayload = {
      ...GOLDEN_A,
      step: 20,
      flows: { ...GOLDEN_A.flows, load_unserved_mw: 2.0 },
      costs: { ...GOLDEN_A.costs, c_voll_yuan: 6000.0 },
    };
    // history in chronological (oldest-first) order
    const alerts = deriveAlerts([step10, step20]);
    expect(alerts).toHaveLength(2);
    // Newest-first: step 20 at index 0, step 10 at index 1
    expect(alerts[0].stepIndex).toBe(20);
    expect(alerts[0].kind).toBe("voll");
    expect(alerts[1].stepIndex).toBe(10);
    expect(alerts[1].kind).toBe("curtailment");
  });

  it("single-step alert → order trivially correct (length 1, no reversal confusion)", () => {
    const step: EnvStepPayload = {
      ...GOLDEN_A,
      step: 42,
      flows: { ...GOLDEN_A.flows, solar_curtailed_mw: 3.0 },
      costs: { ...GOLDEN_A.costs, c_curtail_yuan: 2400.0 },
    };
    const alerts = deriveAlerts([step]);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].stepIndex).toBe(42);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 4 — CostBreakdownCard
// ─────────────────────────────────────────────────────────────────────────────
describe("CostBreakdownCard", () => {
  it("renders with testid cost-breakdown-card", () => {
    render(
      <CostBreakdownCard costs={GOLDEN_A.costs} costCum={GOLDEN_A.cost_cum} />
    );
    expect(screen.getByTestId("cost-breakdown-card")).toBeInTheDocument();
  });

  it("shows cumulative real-money total (headline) from golden A", () => {
    // cost_total_real_yuan_cum = −52700 → formatYuan → "¥-52,700"
    render(
      <CostBreakdownCard costs={GOLDEN_A.costs} costCum={GOLDEN_A.cost_cum} />
    );
    expect(screen.getByTestId("cost-breakdown-card").textContent).toContain("52,700");
  });

  it("renders c_energy row (data-field=c_energy_yuan)", () => {
    render(
      <CostBreakdownCard costs={GOLDEN_A.costs} costCum={GOLDEN_A.cost_cum} />
    );
    const row = document.querySelector('[data-field="c_energy_yuan"]');
    expect(row).toBeInTheDocument();
  });

  it("renders c_import sub-row with data-role=decomposition", () => {
    render(
      <CostBreakdownCard costs={GOLDEN_A.costs} costCum={GOLDEN_A.cost_cum} />
    );
    const row = document.querySelector('[data-field="c_import_yuan"][data-role="decomposition"]');
    expect(row).toBeInTheDocument();
  });

  it("renders r_export sub-row with data-role=decomposition", () => {
    render(
      <CostBreakdownCard costs={GOLDEN_A.costs} costCum={GOLDEN_A.cost_cum} />
    );
    const row = document.querySelector('[data-field="r_export_yuan"][data-role="decomposition"]');
    expect(row).toBeInTheDocument();
  });

  it("renders c_demand_charge row (data-field=c_demand_charge_yuan)", () => {
    render(
      <CostBreakdownCard costs={GOLDEN_A.costs} costCum={GOLDEN_A.cost_cum} />
    );
    expect(document.querySelector('[data-field="c_demand_charge_yuan"]')).toBeInTheDocument();
  });

  it("renders c_degradation, c_curtail, c_voll rows", () => {
    render(
      <CostBreakdownCard costs={GOLDEN_A.costs} costCum={GOLDEN_A.cost_cum} />
    );
    expect(document.querySelector('[data-field="c_degradation_yuan"]')).toBeInTheDocument();
    expect(document.querySelector('[data-field="c_curtail_yuan"]')).toBeInTheDocument();
    expect(document.querySelector('[data-field="c_voll_yuan"]')).toBeInTheDocument();
  });

  it("does NOT render c_demand_shape row (reward-basis only — D13)", () => {
    render(
      <CostBreakdownCard costs={GOLDEN_B.costs} costCum={GOLDEN_B.cost_cum} />
    );
    // c_demand_shape_yuan is reward-basis only; must not appear in the real-money breakdown
    expect(document.querySelector('[data-field="c_demand_shape_yuan"]')).not.toBeInTheDocument();
  });

  it("does NOT render penalty_yuan row (reward-shaping safety metric — D13)", () => {
    render(
      <CostBreakdownCard costs={GOLDEN_A.costs} costCum={GOLDEN_A.cost_cum} />
    );
    expect(document.querySelector('[data-field="penalty_yuan"]')).not.toBeInTheDocument();
  });

  it("step total matches cost_total_real_yuan from golden B (month-boundary step)", () => {
    // Golden B: cost_total_real = 3050400
    render(
      <CostBreakdownCard costs={GOLDEN_B.costs} costCum={GOLDEN_B.cost_cum} />
    );
    const stepTotalRow = document.querySelector('[data-field="cost_total_real_yuan"]');
    expect(stepTotalRow).toBeInTheDocument();
    // 3,050,400 should appear in the row text
    expect(stepTotalRow?.textContent).toContain("050,400");
  });

  it("additive identity: 5 summand rows sum to cost_total_real_yuan (not 6 with import/export)", () => {
    // D13: cost_total_real = c_energy + c_demand_charge + c_degradation + c_curtail + c_voll
    // c_import and r_export are display-only; do NOT include them in the total
    const c = GOLDEN_B.costs;
    const total = c.c_energy_yuan + c.c_demand_charge_yuan + c.c_degradation_yuan
                + c.c_curtail_yuan + c.c_voll_yuan;
    // This should equal cost_total_real_yuan (3050400), not wrongly include import/export
    expect(total).toBeCloseTo(c.cost_total_real_yuan, 2);
    // Guard: adding c_import again would give 3060400 — wrong
    expect(total).not.toBeCloseTo(c.cost_total_real_yuan + c.c_import_yuan, 2);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 5 — MonthPeakCard
// ─────────────────────────────────────────────────────────────────────────────
describe("MonthPeakCard", () => {
  it("renders with testid month-peak-card", () => {
    render(
      <MonthPeakCard
        monthPeakMw={GOLDEN_A.month_peak_mw}
        demandRateYuanPerMwMonth={GOLDEN_A.costs.demand_rate_yuan_per_mw_month}
      />
    );
    expect(screen.getByTestId("month-peak-card")).toBeInTheDocument();
  });

  it("shows month_peak_mw value (95.0 MW from golden A)", () => {
    render(
      <MonthPeakCard monthPeakMw={95.0} demandRateYuanPerMwMonth={32000} />
    );
    expect(screen.getByTestId("month-peak-mw").textContent).toContain("95.0");
  });

  it("exposure = monthPeakMw × demandRateYuanPerMwMonth (hand-computed: 95×32000=3,040,000)", () => {
    // 95 MW × 32000 ¥/MW·month = 3040000
    render(
      <MonthPeakCard monthPeakMw={95.0} demandRateYuanPerMwMonth={32000} />
    );
    const exposure = screen.getByTestId("demand-exposure");
    expect(exposure.textContent).toContain("040,000");  // "3,040,000" without "¥3" prefix assumption
  });

  it("exposure uses wire rate — different rate changes exposure proportionally", () => {
    // If rate were 64000 (double), exposure = 95 × 64000 = 6080000
    render(
      <MonthPeakCard monthPeakMw={95.0} demandRateYuanPerMwMonth={64000} />
    );
    const exposure = screen.getByTestId("demand-exposure");
    expect(exposure.textContent).toContain("080,000");  // 6,080,000
  });

  it("peak of 0 MW → exposure is ¥0", () => {
    render(
      <MonthPeakCard monthPeakMw={0} demandRateYuanPerMwMonth={32000} />
    );
    const exposure = screen.getByTestId("demand-exposure");
    expect(exposure.textContent).toContain("0");
  });

  // finding #4: peak MW must use formatPower — not inline ${v.toFixed(1)} MW
  it("peak MW rendered via formatPower: 95.0 MW matches formatPower(95)", () => {
    // formatPower(95) = "95.0 MW" (site-scale, always ≥1 MW → no kW conversion)
    // The rendered testid text must equal formatPower output exactly
    const formatted = formatPower(95.0);
    render(
      <MonthPeakCard monthPeakMw={95.0} demandRateYuanPerMwMonth={32000} />
    );
    expect(screen.getByTestId("month-peak-mw").textContent).toContain(formatted);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 6 — AlertList
// ─────────────────────────────────────────────────────────────────────────────
describe("AlertList", () => {
  it("empty alerts → renders 'No alerts'", () => {
    render(<AlertList alerts={[]} />);
    const list = screen.getByTestId("alert-list");
    expect(list).toBeInTheDocument();
    expect(list.textContent).toContain("No alerts");
  });

  it("curtailment alert → renders alert-curtailment row with penalty", () => {
    render(
      <AlertList
        alerts={[{
          kind: "curtailment",
          stepIndex: 168,
          penaltyYuan: 10000,
          detail: "12.5 MW curtailed",
        }]}
      />
    );
    expect(screen.getByTestId("alert-curtailment")).toBeInTheDocument();
    expect(screen.getByTestId("alert-list").textContent).toContain("12.5 MW curtailed");
    expect(screen.getByTestId("alert-list").textContent).toContain("10,000");
  });

  it("VOLL alert → renders alert-voll row", () => {
    render(
      <AlertList
        alerts={[{
          kind: "voll",
          stepIndex: 100,
          penaltyYuan: 9000,
          detail: "3.0 MW unserved",
        }]}
      />
    );
    expect(screen.getByTestId("alert-voll")).toBeInTheDocument();
  });

  it("SOC violation alert → renders alert-soc_violation row", () => {
    render(
      <AlertList
        alerts={[{
          kind: "soc_violation",
          stepIndex: 50,
          penaltyYuan: 20000,
          detail: "0.50 MWh overshoot",
        }]}
      />
    );
    expect(screen.getByTestId("alert-soc_violation")).toBeInTheDocument();
    expect(screen.getByTestId("alert-list").textContent).toContain("0.50 MWh");
  });

  it("multiple alerts all rendered", () => {
    render(
      <AlertList
        alerts={[
          { kind: "curtailment", stepIndex: 1, penaltyYuan: 1000, detail: "5.0 MW curtailed" },
          { kind: "voll",        stepIndex: 2, penaltyYuan: 2000, detail: "1.0 MW unserved" },
        ]}
      />
    );
    expect(screen.getByTestId("alert-curtailment")).toBeInTheDocument();
    expect(screen.getByTestId("alert-voll")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 7 — SocTimeline
// ─────────────────────────────────────────────────────────────────────────────
describe("SocTimeline", () => {
  it("empty history → data-testid=soc-timeline with data-state=empty", () => {
    render(<SocTimeline history={[]} />);
    const el = screen.getByTestId("soc-timeline");
    expect(el).toBeInTheDocument();
    expect(el).toHaveAttribute("data-state", "empty");
  });

  it("non-empty history → renders soc-timeline without empty state", () => {
    render(<SocTimeline history={[GOLDEN_A]} />);
    const el = screen.getByTestId("soc-timeline");
    expect(el).toBeInTheDocument();
    expect(el).not.toHaveAttribute("data-state", "empty");
  });

  it("SOC displayed as percent: wire 0.55 → 55.0 (socToPercent conversion)", () => {
    // socToPercent(0.55) = 55.0; must appear in accessible chart data or aria label
    expect(socToPercent(0.55)).toBe(55.0);
    expect(socToPercent(0.2)).toBe(20.0);  // D4 lower bound
    expect(socToPercent(0.9)).toBe(90.0);  // D4 upper bound
  });

  it("D4 lower bound label '20%' present in chart (accessible list or aria)", () => {
    render(<SocTimeline history={[GOLDEN_A]} />);
    // D4: lower bound = 0.2 = 20%; chart should have an accessible element showing "20"
    const el = screen.getByTestId("soc-timeline");
    expect(el.textContent).toMatch(/20/);
  });

  it("D4 upper bound label '90%' present in chart", () => {
    render(<SocTimeline history={[GOLDEN_A]} />);
    const el = screen.getByTestId("soc-timeline");
    expect(el.textContent).toMatch(/90/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 8 — PriceTimeline
// ─────────────────────────────────────────────────────────────────────────────
describe("PriceTimeline", () => {
  it("empty history → data-state=empty", () => {
    render(<PriceTimeline history={[]} />);
    expect(screen.getByTestId("price-timeline")).toHaveAttribute("data-state", "empty");
  });

  it("renders accessible TOU band list with all 4 tier names", () => {
    render(<PriceTimeline history={[GOLDEN_A]} />);
    const bandList = screen.getByRole("list", { name: /tou bands/i });
    const text = bandList.textContent ?? "";
    // All four tier names must appear (C1 — static schedule)
    expect(text.toLowerCase()).toContain("valley");
    expect(text.toLowerCase()).toContain("mid");
    expect(text.toLowerCase()).toContain("peak");
    expect(text.toLowerCase()).toContain("critical");
  });

  it("non-empty history → price-timeline rendered (not empty state)", () => {
    render(<PriceTimeline history={[GOLDEN_A]} />);
    expect(screen.getByTestId("price-timeline")).not.toHaveAttribute("data-state", "empty");
  });

  // reviewer: C1 blocker — pins rendered band geometry, not just tier name presence.
  // A naïve hourly-boundary implementation would emit 660/720 (11:00–12:00) instead of 630/690.
  it("critical-peak morning band: data-from-min=630 data-to-min=690 (C1, D8 — not 660/720)", () => {
    render(<PriceTimeline history={[GOLDEN_A]} />);
    const bandList = screen.getByRole("list", { name: /tou bands/i });
    // Find the critical_peak li that starts at 630 min (10:30) — there are two critical-peak bands
    const criticalItems = Array.from(
      bandList.querySelectorAll('li[data-tier="critical_peak"]')
    );
    // At least two critical-peak bands (morning 630–690, evening 1140–1260)
    expect(criticalItems.length).toBeGreaterThanOrEqual(2);
    const morningBand = criticalItems.find(
      (li) => li.getAttribute("data-from-min") === "630"
    );
    expect(morningBand).toBeTruthy(); // band exists at 630
    // Exact end boundary: 690 = 11:30 (not 720 = 12:00)
    expect(morningBand?.getAttribute("data-to-min")).toBe("690");
  });

  it("TOU_SCHEDULE produces 9 <li> items in accessible band list", () => {
    render(<PriceTimeline history={[GOLDEN_A]} />);
    const bandList = screen.getByRole("list", { name: /tou bands/i });
    // 9 bands from TOU_SCHEDULE: valley(0–420), mid(420–480), peak(480–630),
    // critical(630–690), mid(690–1080), peak(1080–1140), critical(1140–1260),
    // peak(1260–1380), valley(1380–1440)
    expect(bandList.querySelectorAll("li")).toHaveLength(9);
  });

  it("valley band: data-from-min=0 data-to-min=420 (midnight to 07:00)", () => {
    render(<PriceTimeline history={[GOLDEN_A]} />);
    const bandList = screen.getByRole("list", { name: /tou bands/i });
    const valleyBand = bandList.querySelector('li[data-tier="valley"][data-from-min="0"]');
    expect(valleyBand).toBeTruthy();
    expect(valleyBand?.getAttribute("data-to-min")).toBe("420");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 8b — computeBandSegments() — x-axis band geometry (stage-2 blocker fix)
// Asserts explicit x1/x2 step-index values — the <li> proxy alone cannot catch these.
// ─────────────────────────────────────────────────────────────────────────────
describe("computeBandSegments() — x-axis step-index spans (C1 geometry)", () => {
  it("empty history → empty segments array", () => {
    expect(computeBandSegments([])).toHaveLength(0);
  });

  it("single step at 08:00 (peak) → one peak segment spanning that step", () => {
    // GOLDEN_A: hour_of_day=8, minute_of_hour=0 → 480 min → peak (480–630 min)
    const segments = computeBandSegments([GOLDEN_A]);
    expect(segments).toHaveLength(1);
    expect(segments[0].tier).toBe("peak");
    expect(segments[0].x1).toBe(GOLDEN_A.step); // step=168
    expect(segments[0].x2).toBe(GOLDEN_A.step);
  });

  it("11:00 step (660 min) → critical_peak segment, NOT mid (D8 C1 geometry assertion)", () => {
    // D8 / C1 key test: at Δt=1h the 11:00 step (660 min) is inside 630–690 → critical_peak.
    // A minute-unaware implementation (treating 11:00 as boundary start) would return "mid"
    // because it would use the WRONG 11:00–12:00 critical-peak window (660–720 instead of 630–690).
    // This is the rendered-geometry equivalent of the <li> data-from-min=630 test.
    const step11 = { ...GOLDEN_A, step: 50, hour_of_day: 11, minute_of_hour: 0 } as EnvStepPayload;
    const segments = computeBandSegments([step11]);
    expect(segments).toHaveLength(1);
    expect(segments[0].tier).toBe("critical_peak"); // 660 ∈ [630, 690) — not mid
    expect(segments[0].x1).toBe(50);
    expect(segments[0].x2).toBe(50);
  });

  it("10:00→11:00 transition: peak x2=100, critical_peak x1=101 (exact boundary split)", () => {
    // 10:00 (600 min) → peak (480–630); 11:00 (660 min) → critical_peak (630–690)
    const peakStep = { ...GOLDEN_A, step: 100, hour_of_day: 10, minute_of_hour: 0 } as EnvStepPayload;
    const critStep = { ...GOLDEN_A, step: 101, hour_of_day: 11, minute_of_hour: 0 } as EnvStepPayload;
    const segments = computeBandSegments([peakStep, critStep]);
    expect(segments).toHaveLength(2);
    expect(segments[0].tier).toBe("peak");
    expect(segments[0].x1).toBe(100);
    expect(segments[0].x2).toBe(100); // ends at the last peak step
    expect(segments[1].tier).toBe("critical_peak");
    expect(segments[1].x1).toBe(101); // starts at the first critical_peak step
    expect(segments[1].x2).toBe(101);
  });

  it("multi-step same tier → one segment spanning all steps (x1=0, x2=2)", () => {
    // Steps at 08:00, 09:00, 10:00 — all peak (480–630 min)
    const steps = [
      { ...GOLDEN_A, step: 0, hour_of_day: 8,  minute_of_hour: 0 },
      { ...GOLDEN_A, step: 1, hour_of_day: 9,  minute_of_hour: 0 },
      { ...GOLDEN_A, step: 2, hour_of_day: 10, minute_of_hour: 0 },
    ] as EnvStepPayload[];
    const segments = computeBandSegments(steps);
    expect(segments).toHaveLength(1);
    expect(segments[0].tier).toBe("peak");
    expect(segments[0].x1).toBe(0);
    expect(segments[0].x2).toBe(2);
  });

  it("full 24h cycle (one representative step per band) → 9 segments in TOU order", () => {
    // One step per each of the 9 TOU_SCHEDULE windows — verifies every transition
    const daySteps = [
      { ...GOLDEN_A, step:  0, hour_of_day:  0, minute_of_hour: 0 }, // valley  (0 min)
      { ...GOLDEN_A, step:  7, hour_of_day:  7, minute_of_hour: 0 }, // mid     (420 min)
      { ...GOLDEN_A, step:  8, hour_of_day:  8, minute_of_hour: 0 }, // peak    (480 min)
      { ...GOLDEN_A, step: 11, hour_of_day: 11, minute_of_hour: 0 }, // critical_peak (660 min)
      { ...GOLDEN_A, step: 12, hour_of_day: 12, minute_of_hour: 0 }, // mid     (720 min, second window)
      { ...GOLDEN_A, step: 18, hour_of_day: 18, minute_of_hour: 0 }, // peak    (1080 min)
      { ...GOLDEN_A, step: 19, hour_of_day: 19, minute_of_hour: 0 }, // critical_peak (1140 min)
      { ...GOLDEN_A, step: 21, hour_of_day: 21, minute_of_hour: 0 }, // peak    (1260 min)
      { ...GOLDEN_A, step: 23, hour_of_day: 23, minute_of_hour: 0 }, // valley  (1380 min)
    ] as EnvStepPayload[];
    const segments = computeBandSegments(daySteps);
    expect(segments).toHaveLength(9);
    // Check tier sequence
    const tiers = segments.map((s) => s.tier);
    expect(tiers).toEqual([
      "valley", "mid", "peak", "critical_peak",
      "mid", "peak", "critical_peak", "peak", "valley",
    ]);
    // Check x-bounds for the critical-peak morning segment
    const critMorning = segments[3];
    expect(critMorning.tier).toBe("critical_peak");
    expect(critMorning.x1).toBe(11);
    expect(critMorning.x2).toBe(11);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 9 — PowerFlowsTable
// ─────────────────────────────────────────────────────────────────────────────
describe("PowerFlowsTable", () => {
  it("renders with testid power-flows-table", () => {
    render(
      <PowerFlowsTable flows={GOLDEN_A.flows} generation={GOLDEN_A.generation} />
    );
    expect(screen.getByTestId("power-flows-table")).toBeInTheDocument();
  });

  const FLOW_FIELDS = [
    "solar_to_load_mw", "solar_to_bat_mw", "solar_to_grid_mw",
    "wind_to_load_mw",  "wind_to_bat_mw",  "wind_to_grid_mw",
    "bat_to_load_mw",   "bat_to_grid_mw",
    "grid_to_load_mw",  "grid_to_bat_mw",
    "solar_curtailed_mw", "wind_curtailed_mw", "bat_curtailed_mw",
    "load_unserved_mw",
  ] as const;

  for (const field of FLOW_FIELDS) {
    it(`renders row with data-field="${field}"`, () => {
      render(
        <PowerFlowsTable flows={GOLDEN_A.flows} generation={GOLDEN_A.generation} />
      );
      expect(document.querySelector(`[data-field="${field}"]`)).toBeInTheDocument();
    });
  }

  it("renders gross_solar_mw row (from generation block)", () => {
    render(
      <PowerFlowsTable flows={GOLDEN_A.flows} generation={GOLDEN_A.generation} />
    );
    expect(document.querySelector('[data-field="gross_solar_mw"]')).toBeInTheDocument();
  });

  it("renders gross_wind_mw row (from generation block)", () => {
    render(
      <PowerFlowsTable flows={GOLDEN_A.flows} generation={GOLDEN_A.generation} />
    );
    expect(document.querySelector('[data-field="gross_wind_mw"]')).toBeInTheDocument();
  });

  it("non-zero flow values visible in table (solar_to_load = 30 MW from golden A)", () => {
    render(
      <PowerFlowsTable flows={GOLDEN_A.flows} generation={GOLDEN_A.generation} />
    );
    // solar_to_load_mw = 30 MW in golden A
    const row = document.querySelector('[data-field="solar_to_load_mw"]');
    expect(row?.textContent).toContain("30");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 10 — LiveDashboard integration
// ─────────────────────────────────────────────────────────────────────────────
describe("LiveDashboard", () => {
  beforeEach(() => {
    vi.mocked(useTelemetryStore).mockReturnValue(emptyTelemetryState());
  });

  it("empty + connected → shows 'Waiting' spinner (not disconnected)", () => {
    vi.mocked(useTelemetryStore).mockReturnValue({
      ...emptyTelemetryState(),
      wsStatus: "connected",
      envStep: null,
    });
    render(<LiveDashboard />);
    expect(screen.getByTestId("live-dashboard").textContent).toMatch(/waiting/i);
  });

  it("empty + disconnected → blank (no 'Waiting' text; banner is the signal)", () => {
    vi.mocked(useTelemetryStore).mockReturnValue({
      ...emptyTelemetryState(),
      wsStatus: "disconnected",
      envStep: null,
    });
    render(<LiveDashboard />);
    const dashboard = screen.getByTestId("live-dashboard");
    expect(dashboard.textContent).not.toMatch(/waiting/i);
  });

  it("with envStep → renders cost-breakdown-card", () => {
    vi.mocked(useTelemetryStore).mockReturnValue({
      ...emptyTelemetryState(),
      envStep: GOLDEN_A,
      history: [GOLDEN_A],
    });
    render(<LiveDashboard />);
    expect(screen.getByTestId("cost-breakdown-card")).toBeInTheDocument();
  });

  it("with envStep → renders month-peak-card", () => {
    vi.mocked(useTelemetryStore).mockReturnValue({
      ...emptyTelemetryState(),
      envStep: GOLDEN_A,
      history: [GOLDEN_A],
    });
    render(<LiveDashboard />);
    expect(screen.getByTestId("month-peak-card")).toBeInTheDocument();
  });

  it("with envStep → renders power-flows-table", () => {
    vi.mocked(useTelemetryStore).mockReturnValue({
      ...emptyTelemetryState(),
      envStep: GOLDEN_A,
      history: [GOLDEN_A],
    });
    render(<LiveDashboard />);
    expect(screen.getByTestId("power-flows-table")).toBeInTheDocument();
  });

  it("with envStep → renders alert-list", () => {
    vi.mocked(useTelemetryStore).mockReturnValue({
      ...emptyTelemetryState(),
      envStep: GOLDEN_A,
      history: [GOLDEN_A],
    });
    render(<LiveDashboard />);
    expect(screen.getByTestId("alert-list")).toBeInTheDocument();
  });

  it("golden B (month-boundary) — demand charge visible in cost breakdown", () => {
    // Step B has c_demand_charge_yuan = 3040000; it must appear in the rendered card
    vi.mocked(useTelemetryStore).mockReturnValue({
      ...emptyTelemetryState(),
      envStep: GOLDEN_B,
      history: [GOLDEN_B],
    });
    render(<LiveDashboard />);
    const card = screen.getByTestId("cost-breakdown-card");
    // 3040000 → "3,040,000" in formatYuan
    expect(card.textContent).toContain("040,000");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// reviewer: edge-case tests added per REQUEST_CHANGES findings (PR #34):
//   - PriceTimeline band geometry: data-from-min/data-to-min (Section 8, finding #1/C1)
//   - deriveAlerts epsilon guard: 0.0005/0.001/0.0011 MW (Section 3, finding #2)
//   - deriveAlerts newest-first ordering (Section 3, finding #3)
//   - MonthPeakCard formatPower (Section 5, finding #4)
// ─────────────────────────────────────────────────────────────────────────────
