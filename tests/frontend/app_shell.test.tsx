/**
 * Test suite: app_shell
 *
 * Framework: Vitest + React Testing Library
 * Contract:  contracts/frontend/app_shell.md
 * Spec refs: REBUILD_SPEC.md §2, §3, §3.5, §3.7, §5; telemetry_schema.md v1.0.0 (LOCKED, PR #6)
 *
 * Wire-format fixtures have been verified against telemetry_schema.md v1.0.0 (LOCKED).
 * Tests previously marked PENDING_LOCK are now active against the locked schema.
 *
 * Tests are intentionally RED at this point — no implementation exists yet.
 * That is correct per the contract-first-dev workflow.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// ─── Fixture data ─────────────────────────────────────────────────────────────

/** Minimal valid env_step envelope fixture — verified against telemetry_schema.md v1.0.0 (LOCKED, PR #6).
 *  Matches golden step A from the locked schema: net-export, no demand activity.
 *  c_energy = c_import − r_export = 0 − 53100 = −53100; cost_total_real = −53100+0+400 = −52700; reward = 0.527.
 */
const FIXTURE_ENV_STEP = {
  schema_version: "1.0.0",
  kind: "env_step" as const,
  ts_utc: "2026-06-10T08:00:00Z",
  run_id: "run_abc123",
  seq: 42,
  payload: {
    step: 42,
    episode: 1,
    dt_hours: 1.0,
    sim_time_utc: "2026-03-10T08:00:00Z",
    hour_of_day: 8,
    minute_of_hour: 0,
    wind_speed_mps: 8.0,
    irradiance_wm2: 600.0,
    temperature_c: 20.0,
    load_mw: 75.0,
    price_buy_yuan_per_mwh: 620.0,
    price_sell_yuan_per_mwh: 590.0,
    tariff_tier: "peak" as const,
    battery: {
      soc: 0.55,
      p_charge_mw: 0.0,
      p_discharge_mw: 40.0,
      p_max_charge_mw: 98.16,     // §3.6 row 3; carried for 3D scaling
      p_max_discharge_mw: 98.16,  // §3.6 row 3
      soc_violation_mwh: 0.0,
      capacity_mwh: 294.5,
    },
    generation: {
      // conservation: solar_to_* + solar_curtailed = 30+0+0+0 = 30 ✓
      gross_solar_mw: 30.0,
      // conservation: wind_to_* + wind_curtailed = 12.5+0+80+0 = 92.5 ✓
      gross_wind_mw: 92.5,
    },
    flows: {
      solar_to_load_mw: 30.0,
      solar_to_bat_mw: 0.0,
      solar_to_grid_mw: 0.0,
      wind_to_load_mw: 12.5,
      wind_to_bat_mw: 0.0,
      wind_to_grid_mw: 80.0,
      bat_to_load_mw: 30.0,
      bat_to_grid_mw: 10.0,
      grid_to_load_mw: 0.0,
      grid_to_bat_mw: 0.0,
      solar_curtailed_mw: 0.0,  // per-source split (ren_curtailed_mw retired at LOCK)
      wind_curtailed_mw: 0.0,
      bat_curtailed_mw: 0.0,
      load_unserved_mw: 0.0,
    },
    pcc: {
      export_mw: 90.0,
      import_mw: 0.0,
      max_export_mw: 945.0,
      max_import_mw: 400.0,
    },
    costs: {
      // c_energy = c_import − r_export = 0 − 53100 = −53100 (§3.4)
      c_energy_yuan: -53100.0,
      c_import_yuan: 0.0,         // decomposition of c_energy — display only
      r_export_yuan: 53100.0,     // decomposition of c_energy — display only
      c_demand_charge_yuan: 0.0,  // 0 on non-month-boundary step (D10)
      c_demand_shape_yuan: 0.0,   // reward-shaping term (§3.4)
      c_degradation_yuan: 400.0,
      c_curtail_yuan: 0.0,
      c_voll_yuan: 0.0,
      penalty_yuan: 0.0,
      demand_rate_yuan_per_mw_month: 32000.0,
      // cost_total_real = −53100+0+400+0+0 = −52700
      cost_total_real_yuan: -52700.0,
      // cost_total_reward_basis = −53100+2.0·0+400+0+0 = −52700 (same here: no shaping)
      cost_total_reward_basis_yuan: -52700.0,
    },
    cost_cum: {
      c_energy_yuan_cum: 0.0,
      c_demand_charge_yuan_cum: 0.0,
      c_demand_shape_yuan_cum: 0.0,
      c_degradation_yuan_cum: 0.0,
      c_curtail_yuan_cum: 0.0,
      c_voll_yuan_cum: 0.0,
      penalty_yuan_cum: 0.0,
      cost_total_real_yuan_cum: 0.0,
      cost_total_reward_basis_yuan_cum: 0.0,
    },
    month_peak_mw: 95.0,
    reward: 0.527,  // = −(−52700 + 0) × 1e-5 = 0.527 ✓
    // assets_ext absent for Gansu parity config
  },
};

const FIXTURE_TRAIN_METRICS = {
  schema_version: "1.0.0",
  kind: "train_metrics" as const,
  ts_utc: "2026-06-10T08:01:00Z",
  run_id: "run_abc123",
  seq: 1,
  payload: {
    global_step: 250000,
    wall_seconds: 184.2,
    env_steps_per_sec: 1.35e6,
    actor_loss: 0.42,
    critic_loss: 1.31,
    ent_coef: 0.18,
    reward_scaled_mean: 0.61,           // ×1e-5-scaled env reward (was reward_mean in DRAFT)
    reward_norm_mean: 0.83,             // VecNorm-normalized; null when is_eval_checkpoint=true
    cost_total_real_mean_yuan: -61000.0,// mean per-episode real ¥ (was reward_unnorm_mean_yuan in DRAFT)
    is_eval_checkpoint: false,
    checkpoint_id: null,
  },
};

const FIXTURE_EVAL_COMPARE = {
  schema_version: "1.0.0",
  kind: "eval_compare" as const,
  ts_utc: "2026-06-10T09:00:00Z",
  run_id: "run_abc123",
  seq: 1,
  payload: {
    eval_horizon_steps: 8760,
    checkpoint_id: "ckpt_001",
    cost_basis: "real_money" as const,  // explicit: all *_yuan fields are real money
    policies: {
      // total_cost_yuan = energy+demand_charge+degradation+curtailment+voll (safety metrics excluded)
      rl: {
        energy_cost_yuan: 100_000, demand_charge_yuan: 20_000, degradation_yuan: 5_000,
        curtailment_yuan: 500, voll_yuan: 0,
        total_cost_yuan: 125_500,    // 100000+20000+5000+500+0 = 125500 ✓
        soc_violations_count: 0, soc_violation_mwh: 0.0, penalty_yuan: 0.0,
      },
      no_battery: {
        energy_cost_yuan: 200_000, demand_charge_yuan: 50_000, degradation_yuan: 0,
        curtailment_yuan: 1_000, voll_yuan: 100,
        total_cost_yuan: 251_100,    // 200000+50000+0+1000+100 = 251100 ✓
        soc_violations_count: 0, soc_violation_mwh: 0.0, penalty_yuan: 0.0,
      },
      rule_based_tou: {
        energy_cost_yuan: 160_000, demand_charge_yuan: 35_000, degradation_yuan: 4_000,
        curtailment_yuan: 800, voll_yuan: 50,
        total_cost_yuan: 199_850,    // 160000+35000+4000+800+50 = 199850 ✓
        soc_violations_count: 2, soc_violation_mwh: 0.5, penalty_yuan: 500.0,
      },
    },
  },
};

// ─── §8: units.ts ─────────────────────────────────────────────────────────────

describe("units.ts — socToPercent", () => {
  it("converts fraction 0.55 to 55.0", async () => {
    // 0.55 * 100 = 55.0
    const { socToPercent } = await import("../../src/utils/units");
    expect(socToPercent(0.55)).toBe(55.0);
  });

  it("converts SOC min bound 0.2 to 20.0", async () => {
    // D4: SOC lower bound = 0.2 → 20.0 %
    const { socToPercent } = await import("../../src/utils/units");
    expect(socToPercent(0.2)).toBe(20.0);
  });

  it("converts SOC max bound 0.9 to 90.0", async () => {
    // D4: SOC upper bound = 0.9 → 90.0 %
    const { socToPercent } = await import("../../src/utils/units");
    expect(socToPercent(0.9)).toBe(90.0);
  });
});

describe("units.ts — mwToKw / kwToMw", () => {
  it("1 MW = 1000 kW", async () => {
    const { mwToKw } = await import("../../src/utils/units");
    expect(mwToKw(1)).toBe(1000);
  });

  it("500 kW = 0.5 MW", async () => {
    const { kwToMw } = await import("../../src/utils/units");
    expect(kwToMw(500)).toBe(0.5);
  });

  it("round-trip 42 MW → kW → MW is exact", async () => {
    const { mwToKw, kwToMw } = await import("../../src/utils/units");
    expect(kwToMw(mwToKw(42))).toBe(42);
  });
});

describe("units.ts — formatYuan", () => {
  it("formats a positive ¥ value with thousands separator", async () => {
    // 53100 → "¥53,100"
    const { formatYuan } = await import("../../src/utils/units");
    expect(formatYuan(53100)).toBe("¥53,100");
  });

  it("formats a negative cost as ¥-52,700", async () => {
    // cost_total_yuan in fixture = -52700 (net revenue)
    const { formatYuan } = await import("../../src/utils/units");
    expect(formatYuan(-52700)).toBe("¥-52,700");
  });

  it("formats zero as ¥0", async () => {
    const { formatYuan } = await import("../../src/utils/units");
    expect(formatYuan(0)).toBe("¥0");
  });
});

describe("units.ts — formatYuanPerMwh", () => {
  it("formats 620 ¥/MWh correctly (D3 peak tariff)", async () => {
    // §3.7: peak = 620 ¥/MWh
    const { formatYuanPerMwh } = await import("../../src/utils/units");
    expect(formatYuanPerMwh(620)).toBe("¥620/MWh");
  });
});

describe("units.ts — formatPower", () => {
  it("values below 1 MW render in kW: 0.85 → '850 kW'", async () => {
    // 0.85 MW = 850 kW
    const { formatPower } = await import("../../src/utils/units");
    expect(formatPower(0.85)).toBe("850 kW");
  });

  it("values ≥1 MW render in MW: 40.0 → '40.0 MW'", async () => {
    const { formatPower } = await import("../../src/utils/units");
    expect(formatPower(40.0)).toBe("40.0 MW");
  });

  it("exactly 1 MW renders in MW, not kW", async () => {
    const { formatPower } = await import("../../src/utils/units");
    expect(formatPower(1.0)).toBe("1.0 MW");
  });
});

describe("units.ts — formatSimTime", () => {
  it("formats Tuesday 08:00 UTC correctly ('Tue 08:00')", async () => {
    // "2026-03-10T08:00:00Z" is a Tuesday (UTC). Implementation must use
    // getUTCDay/getUTCHours so the result is timezone-invariant on any runner.
    const { formatSimTime } = await import("../../src/utils/units");
    expect(formatSimTime("2026-03-10T08:00:00Z")).toBe("Tue 08:00");
  });
});

// ─── §9: touColors.ts ─────────────────────────────────────────────────────────

describe("touColors.ts — getTouColor", () => {
  it("critical_peak has a red background token", async () => {
    const { getTouColor } = await import("../../src/utils/touColors");
    const color = getTouColor("critical_peak");
    expect(color.bg).toBe("#fee2e2");
    expect(color.text).toBe("#991b1b");
  });

  it("valley has a green background token", async () => {
    const { getTouColor } = await import("../../src/utils/touColors");
    const color = getTouColor("valley");
    expect(color.bg).toBe("#dcfce7");
    expect(color.text).toBe("#166534");
  });

  it("all four TOU tiers return distinct bg colours", async () => {
    const { getTouColor } = await import("../../src/utils/touColors");
    const tiers = ["critical_peak", "peak", "mid", "valley"] as const;
    const bgs = tiers.map((t) => getTouColor(t).bg);
    const uniqueBgs = new Set(bgs);
    expect(uniqueBgs.size).toBe(4);
  });
});

// ─── §3: NumberDisplay component ──────────────────────────────────────────────

describe("NumberDisplay — normal values", () => {
  it("renders value and unit for a valid MW reading", async () => {
    const { NumberDisplay } = await import("../../src/components/NumberDisplay");
    const { container } = render(<NumberDisplay value={40.0} unit="MW" />);
    expect(container.textContent).toContain("40.0");
    expect(container.textContent).toContain("MW");
  });

  it("defaults to 1 decimal place", async () => {
    const { NumberDisplay } = await import("../../src/components/NumberDisplay");
    const { container } = render(<NumberDisplay value={40} unit="MW" />);
    expect(container.textContent).toContain("40.0");
  });

  it("respects custom decimals=0", async () => {
    const { NumberDisplay } = await import("../../src/components/NumberDisplay");
    const { container } = render(<NumberDisplay value={40.7} unit="MW" decimals={0} />);
    expect(container.textContent).toContain("41"); // rounded
    expect(container.textContent).not.toContain("40.7");
  });
});

describe("NumberDisplay — null / NaN / Infinity edge cases", () => {
  it("renders '—' for null value, no unit shown", async () => {
    const { NumberDisplay } = await import("../../src/components/NumberDisplay");
    const { container } = render(<NumberDisplay value={null} unit="MW" />);
    expect(container.textContent).toContain("—");
    expect(container.textContent).not.toContain("MW");
  });

  it("renders nullText for NaN value", async () => {
    const { NumberDisplay } = await import("../../src/components/NumberDisplay");
    const { container } = render(<NumberDisplay value={NaN} unit="MW" />);
    expect(container.textContent).toContain("—");
  });

  it("renders nullText for Infinity value", async () => {
    const { NumberDisplay } = await import("../../src/components/NumberDisplay");
    const { container } = render(<NumberDisplay value={Infinity} unit="MW" />);
    expect(container.textContent).toContain("—");
  });

  it("renders custom nullText prop when provided", async () => {
    const { NumberDisplay } = await import("../../src/components/NumberDisplay");
    const { container } = render(<NumberDisplay value={null} unit="MW" nullText="N/A" />);
    expect(container.textContent).toContain("N/A");
  });
});

// ─── §3.7: TouBadge component ─────────────────────────────────────────────────

describe("TouBadge — all four tiers", () => {
  it.each([
    ["critical_peak", "Critical Peak"],
    ["peak", "Peak"],
    ["mid", "Mid"],
    ["valley", "Valley"],
  ] as const)("tier %s renders label %s", async (tier, label) => {
    const { TouBadge } = await import("../../src/components/TouBadge");
    const { container } = render(<TouBadge tier={tier} />);
    expect(container.textContent?.toLowerCase()).toContain(label.toLowerCase());
  });

  it("null tier renders '—' with neutral styling", async () => {
    const { TouBadge } = await import("../../src/components/TouBadge");
    const { container } = render(<TouBadge tier={null} />);
    expect(container.textContent).toContain("—");
  });

  it("applies the tier CSS class to the badge element", async () => {
    const { TouBadge } = await import("../../src/components/TouBadge");
    const { container } = render(<TouBadge tier="valley" />);
    expect(container.querySelector(".tou-valley")).toBeTruthy();
  });
});

describe("TouBadge — showPrice renders wire value via formatYuanPerMwh", () => {
  it("showPrice=true with priceYuanPerMwh renders formatted price string", async () => {
    // Source of price: wire value price_buy_yuan_per_mwh from telemetryStore,
    // formatted via formatYuanPerMwh() — never a hardcoded §3.7 table.
    // 620 ¥/MWh is the peak tier price (§3.7 / D8); the component must render
    // whatever is passed in, formatted as "¥620/MWh".
    const { TouBadge } = await import("../../src/components/TouBadge");
    const { container } = render(<TouBadge tier="peak" showPrice priceYuanPerMwh={620} />);
    expect(container.textContent).toContain("¥620/MWh");
  });

  it("showPrice=true without priceYuanPerMwh does not crash and shows no price", async () => {
    // When no price is supplied (WS not yet connected), showPrice must be a no-op.
    const { TouBadge } = await import("../../src/components/TouBadge");
    const { container } = render(<TouBadge tier="peak" showPrice />);
    expect(container.textContent).not.toMatch(/¥\d/);
  });

  it("showPrice=false does not render price even when priceYuanPerMwh is supplied", async () => {
    const { TouBadge } = await import("../../src/components/TouBadge");
    const { container } = render(<TouBadge tier="peak" showPrice={false} priceYuanPerMwh={620} />);
    expect(container.textContent).not.toContain("¥620/MWh");
  });
});

// ─── §7: SceneMountPoint component ────────────────────────────────────────────

describe("SceneMountPoint — mount and callback", () => {
  it("renders a div with class scene-mount-point", async () => {
    const { SceneMountPoint } = await import("../../src/components/SceneMountPoint");
    const { container } = render(<SceneMountPoint />);
    expect(container.querySelector(".scene-mount-point")).toBeTruthy();
  });

  it("calls onReady with the container div element after mount", async () => {
    const { SceneMountPoint } = await import("../../src/components/SceneMountPoint");
    const onReady = vi.fn();
    const { container } = render(<SceneMountPoint onReady={onReady} />);
    expect(onReady).toHaveBeenCalledOnce();
    expect(onReady.mock.calls[0][0]).toBe(container.querySelector(".scene-mount-point"));
  });

  it("does not contain any 3D/canvas children of its own", async () => {
    const { SceneMountPoint } = await import("../../src/components/SceneMountPoint");
    const { container } = render(<SceneMountPoint />);
    expect(container.querySelector("canvas")).toBeNull();
  });
});

// ─── §6: Routing ──────────────────────────────────────────────────────────────

describe("App routing — route → component mapping", () => {
  it("renders SiteView at '/'", async () => {
    const { default: App } = await import("../../src/App");
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );
    // SiteView must render a scene mount point
    expect(screen.getByTestId("site-view") ?? document.querySelector(".scene-mount-point")).toBeTruthy();
  });

  it("renders TrainingPanel at '/training'", async () => {
    const { default: App } = await import("../../src/App");
    render(
      <MemoryRouter initialEntries={["/training"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId("training-panel")).toBeTruthy();
  });

  it("renders EvalComparison at '/eval'", async () => {
    const { default: App } = await import("../../src/App");
    render(
      <MemoryRouter initialEntries={["/eval"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByTestId("eval-comparison")).toBeTruthy();
  });

  it("renders a 404 fallback for unknown routes", async () => {
    const { default: App } = await import("../../src/App");
    render(
      <MemoryRouter initialEntries={["/this-does-not-exist"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText(/not found/i)).toBeTruthy();
  });

  it("nav bar is present on every route (does not crash)", async () => {
    const { default: App } = await import("../../src/App");
    const { container } = render(
      <MemoryRouter initialEntries={["/eval"]}>
        <App />
      </MemoryRouter>
    );
    expect(container.querySelector("nav")).toBeTruthy();
  });
});

// ─── §11: ErrorBoundary component ─────────────────────────────────────────────

describe("ErrorBoundary — catches render errors", () => {
  // Suppress console.error for these tests
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

  afterEach(() => consoleError.mockClear());

  it("renders fallback when child throws", async () => {
    const { ErrorBoundary } = await import("../../src/components/ErrorBoundary");
    const Bomb = () => { throw new Error("test explosion"); };
    const { container } = render(
      <ErrorBoundary fallback={<div>Caught!</div>}>
        <Bomb />
      </ErrorBoundary>
    );
    expect(container.textContent).toContain("Caught!");
  });

  it("renders default fallback message when no fallback prop given", async () => {
    const { ErrorBoundary } = await import("../../src/components/ErrorBoundary");
    const Bomb = () => { throw new Error("boom"); };
    const { container } = render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    );
    expect(container.textContent?.toLowerCase()).toContain("something went wrong");
  });

  it("a sibling route's ErrorBoundary does not affect the nav bar", async () => {
    // This verifies per-route isolation: crashing route != crashing shell
    const { ErrorBoundary } = await import("../../src/components/ErrorBoundary");
    const Bomb = () => { throw new Error("route crash"); };
    const { container } = render(
      <div>
        <nav data-testid="nav">Navigation</nav>
        <ErrorBoundary><Bomb /></ErrorBoundary>
      </div>
    );
    expect(screen.getByTestId("nav")).toBeTruthy();
    expect(container.textContent?.toLowerCase()).toContain("something went wrong");
  });
});

// ─── §4: Telemetry store — state shape & updates ─────────────────────────────

describe("telemetryStore — initial state", () => {
  it("starts with null envStep and connected status 'disconnected'", async () => {
    // PENDING_LOCK: field names match DRAFT telemetry schema
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    const state = useTelemetryStore.getState();
    expect(state.envStep).toBeNull();
    expect(state.wsStatus).toBe("disconnected");
    expect(state.runId).toBeNull();
    expect(state.history).toHaveLength(0);
  });
});

describe("telemetryStore — receiveEnvStep", () => {
  beforeEach(async () => {
    // Reset store before each test
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().clearHistory();
  });

  it("stores the latest env_step payload", async () => {
    // PENDING_LOCK
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    act(() => {
      useTelemetryStore.getState().receiveEnvStep(FIXTURE_ENV_STEP as any);
    });
    expect(useTelemetryStore.getState().envStep?.step).toBe(42);
  });

  it("appends to history ring buffer", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    act(() => {
      useTelemetryStore.getState().receiveEnvStep(FIXTURE_ENV_STEP as any);
    });
    expect(useTelemetryStore.getState().history).toHaveLength(1);
  });

  it("ring buffer drops oldest entry when full (historyMaxLen=168)", async () => {
    // D3: 168 steps per episode
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    const maxLen = 168;
    // Fill to capacity + 1
    for (let i = 0; i <= maxLen; i++) {
      const msg = { ...FIXTURE_ENV_STEP, seq: i, payload: { ...FIXTURE_ENV_STEP.payload, step: i } };
      act(() => { useTelemetryStore.getState().receiveEnvStep(msg as any); });
    }
    const history = useTelemetryStore.getState().history;
    expect(history.length).toBe(maxLen);
    // Oldest (step=0) should have been dropped; newest (step=168) should be last
    expect(history[0].step).toBe(1);
    expect(history[history.length - 1].step).toBe(maxLen);
  });

  it("detects a sequence gap", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    act(() => {
      useTelemetryStore.getState().receiveEnvStep({ ...FIXTURE_ENV_STEP, seq: 10 } as any);
    });
    act(() => {
      useTelemetryStore.getState().receiveEnvStep({ ...FIXTURE_ENV_STEP, seq: 15 } as any); // gap of 4
    });
    expect(useTelemetryStore.getState().seqGap).toBe(true);
  });

  it("no gap when seq is consecutive", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    act(() => {
      useTelemetryStore.getState().receiveEnvStep({ ...FIXTURE_ENV_STEP, seq: 10 } as any);
    });
    act(() => {
      useTelemetryStore.getState().receiveEnvStep({ ...FIXTURE_ENV_STEP, seq: 11 } as any);
    });
    expect(useTelemetryStore.getState().seqGap).toBe(false);
  });

  it("clearHistory resets history and envStep to null", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    act(() => {
      useTelemetryStore.getState().receiveEnvStep(FIXTURE_ENV_STEP as any);
      useTelemetryStore.getState().clearHistory();
    });
    expect(useTelemetryStore.getState().history).toHaveLength(0);
    expect(useTelemetryStore.getState().envStep).toBeNull();
  });
});

// ─── §4: Training store ────────────────────────────────────────────────────────

describe("trainingStore — receiveTrainMetrics", () => {
  it("stores latest train_metrics payload", async () => {
    const { useTrainingStore } = await import("../../src/stores/trainingStore");
    act(() => {
      useTrainingStore.getState().receiveTrainMetrics(FIXTURE_TRAIN_METRICS as any);
    });
    expect(useTrainingStore.getState().latest?.global_step).toBe(250_000);
  });

  it("appends to history (no cap)", async () => {
    const { useTrainingStore } = await import("../../src/stores/trainingStore");
    useTrainingStore.getState().clear();
    act(() => {
      useTrainingStore.getState().receiveTrainMetrics(FIXTURE_TRAIN_METRICS as any);
      useTrainingStore.getState().receiveTrainMetrics({ ...FIXTURE_TRAIN_METRICS, seq: 2 } as any);
    });
    expect(useTrainingStore.getState().history).toHaveLength(2);
  });
});

// ─── §4: Eval store ────────────────────────────────────────────────────────────

describe("evalStore — receiveEvalCompare", () => {
  it("stores latest eval_compare payload", async () => {
    const { useEvalStore } = await import("../../src/stores/evalStore");
    act(() => {
      useEvalStore.getState().receiveEvalCompare(FIXTURE_EVAL_COMPARE as any);
    });
    expect(useEvalStore.getState().latest?.checkpoint_id).toBe("ckpt_001");
    // eval_horizon_steps must match D3: 8760 at Δt=1h
    expect(useEvalStore.getState().latest?.eval_horizon_steps).toBe(8760);
  });

  it("stores all three policy entries", async () => {
    // Dispatch own fixture — do not rely on prior-test store state
    const { useEvalStore } = await import("../../src/stores/evalStore");
    useEvalStore.getState().clear();
    act(() => { useEvalStore.getState().receiveEvalCompare(FIXTURE_EVAL_COMPARE as any); });
    const latest = useEvalStore.getState().latest;
    expect(latest?.policies.rl).toBeDefined();
    expect(latest?.policies.no_battery).toBeDefined();
    expect(latest?.policies.rule_based_tou).toBeDefined();
  });
});

// ─── §4: WebSocket client — lifecycle ────────────────────────────────────────

describe("wsClient — connection lifecycle", () => {
  let server: WebSocket & { readyState: number };
  let MockWebSocket: typeof WebSocket;

  beforeEach(() => {
    // Mock WebSocket
    MockWebSocket = vi.fn().mockImplementation((url: string) => {
      const ws = {
        url,
        readyState: WebSocket.CONNECTING,
        send: vi.fn(),
        close: vi.fn(),
        onopen: null as any,
        onmessage: null as any,
        onerror: null as any,
        onclose: null as any,
      };
      server = ws as any;
      return ws;
    }) as any;
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens a WebSocket connection to the given URL", async () => {
    const { createWsClient } = await import("../../src/clients/wsClient");
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    });
    client.connect();
    expect(MockWebSocket).toHaveBeenCalledWith("ws://localhost:8000/ws");
  });

  it("calls onStatusChange('connected') on WebSocket open", async () => {
    // PENDING_LOCK
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onStatusChange = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange,
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    expect(onStatusChange).toHaveBeenCalledWith("connected");
  });

  it("calls onStatusChange('disconnected') on WebSocket close", async () => {
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onStatusChange = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange,
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    act(() => { server.onclose?.(new CloseEvent("close")); });
    expect(onStatusChange).toHaveBeenCalledWith("disconnected");
  });

  it("dispatches env_step message to onEnvStep callback (PENDING_LOCK)", async () => {
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onEnvStep = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep,
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    act(() => {
      server.onmessage?.({ data: JSON.stringify(FIXTURE_ENV_STEP) } as MessageEvent);
    });
    expect(onEnvStep).toHaveBeenCalledOnce();
    expect(onEnvStep.mock.calls[0][0].payload.step).toBe(42);
  });

  it("dispatches train_metrics message to onTrainMetrics callback (PENDING_LOCK)", async () => {
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onTrainMetrics = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep: vi.fn(),
      onTrainMetrics,
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    act(() => {
      server.onmessage?.({ data: JSON.stringify(FIXTURE_TRAIN_METRICS) } as MessageEvent);
    });
    expect(onTrainMetrics).toHaveBeenCalledOnce();
    expect(onTrainMetrics.mock.calls[0][0].payload.global_step).toBe(250_000);
  });

  it("discards invalid JSON without throwing", async () => {
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onEnvStep = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep,
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    expect(() => {
      act(() => {
        server.onmessage?.({ data: "not valid json {{" } as MessageEvent);
      });
    }).not.toThrow();
    expect(onEnvStep).not.toHaveBeenCalled();
  });

  it("discards message with unknown kind without throwing", async () => {
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onEnvStep = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep,
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    expect(() => {
      act(() => {
        server.onmessage?.({
          data: JSON.stringify({ ...FIXTURE_ENV_STEP, kind: "completely_unknown" }),
        } as MessageEvent);
      });
    }).not.toThrow();
    expect(onEnvStep).not.toHaveBeenCalled();
  });

  it("emits 'disconnected' and stops parsing on schema_version major > 1 (PENDING_LOCK)", async () => {
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onEnvStep = vi.fn();
    const onStatusChange = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep,
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange,
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    act(() => {
      server.onmessage?.({
        data: JSON.stringify({ ...FIXTURE_ENV_STEP, schema_version: "2.0.0" }),
      } as MessageEvent);
    });
    expect(onStatusChange).toHaveBeenCalledWith("disconnected");
    expect(onEnvStep).not.toHaveBeenCalled();
  });

  it("marks status 'stale' after staleAfterMs with no messages", async () => {
    vi.useFakeTimers();
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onStatusChange = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange,
      staleAfterMs: 5000,
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    act(() => { vi.advanceTimersByTime(5001); });
    expect(onStatusChange).toHaveBeenCalledWith("stale");
    vi.useRealTimers();
  });

  it("disconnect() closes the socket cleanly", async () => {
    const { createWsClient } = await import("../../src/clients/wsClient");
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    });
    client.connect();
    client.disconnect();
    expect(server.close).toHaveBeenCalled();
  });
});

// ─── §4: WebSocket client — reconnect backoff ─────────────────────────────────

describe("wsClient — reconnect backoff", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("reconnects after disconnect with initial delay ≥ reconnectBaseMs", async () => {
    vi.useFakeTimers();
    let wsCallCount = 0;
    vi.stubGlobal("WebSocket", vi.fn().mockImplementation(() => {
      wsCallCount++;
      return {
        readyState: WebSocket.CONNECTING,
        close: vi.fn(),
        onopen: null, onmessage: null, onerror: null,
        onclose: null,
      };
    }));

    const { createWsClient } = await import("../../src/clients/wsClient");
    const onStatusChange = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange,
      reconnectBaseMs: 100,
      reconnectMaxMs: 30000,
    });
    client.connect();
    // simulate close
    const firstWs = (WebSocket as any).mock.results[0].value;
    act(() => { firstWs.onclose?.(new CloseEvent("close")); });
    // advance less than base — no reconnect yet
    act(() => { vi.advanceTimersByTime(50); });
    expect(wsCallCount).toBe(1);
    // advance past base
    act(() => { vi.advanceTimersByTime(200); });
    expect(wsCallCount).toBeGreaterThanOrEqual(2);
  });
});

// ─── §5: REST client ───────────────────────────────────────────────────────────

describe("restClient — getRuns", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns parsed run list on 200 OK", async () => {
    const mockRuns = [
      { run_id: "run_001", started_at: "2026-06-10T00:00:00Z", status: "running", checkpoint_count: 3 },
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockRuns,
    }));
    const { createRestClient } = await import("../../src/clients/restClient");
    const client = createRestClient({ baseUrl: "http://localhost:8000" });
    const runs = await client.getRuns();
    expect(runs).toHaveLength(1);
    expect(runs[0].run_id).toBe("run_001");
    vi.unstubAllGlobals();
  });

  it("rejects with http_5xx error on 500 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      url: "http://localhost:8000/runs",
    }));
    const { createRestClient } = await import("../../src/clients/restClient");
    const client = createRestClient({ baseUrl: "http://localhost:8000" });
    await expect(client.getRuns()).rejects.toThrow(/http_5xx/);
    vi.unstubAllGlobals();
  });

  it("rejects with http_4xx error on 404 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      url: "http://localhost:8000/runs",
    }));
    const { createRestClient } = await import("../../src/clients/restClient");
    const client = createRestClient({ baseUrl: "http://localhost:8000" });
    await expect(client.getRuns()).rejects.toThrow(/http_4xx/);
    vi.unstubAllGlobals();
  });

  it("rejects with network_error on fetch throw", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Failed to fetch")));
    const { createRestClient } = await import("../../src/clients/restClient");
    const client = createRestClient({ baseUrl: "http://localhost:8000" });
    await expect(client.getRuns()).rejects.toThrow(/network_error/);
    vi.unstubAllGlobals();
  });
});

// ─── §12: Unhappy paths (edge cases from contract §12) ────────────────────────

describe("contract §12 — unhappy paths", () => {
  it("§12.5 — env_step without assets_ext does not crash any component", async () => {
    // assets_ext is absent for Gansu parity config
    expect(FIXTURE_ENV_STEP.payload).not.toHaveProperty("assets_ext");
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    expect(() => {
      act(() => { useTelemetryStore.getState().receiveEnvStep(FIXTURE_ENV_STEP as any); });
    }).not.toThrow();
  });

  it("§12.6 — env_step with all-zero flows stores correctly", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().clearHistory();
    const zeroFlows = {
      ...FIXTURE_ENV_STEP,
      payload: {
        ...FIXTURE_ENV_STEP.payload,
        flows: Object.fromEntries(
          Object.keys(FIXTURE_ENV_STEP.payload.flows).map((k) => [k, 0.0])
        ),
      },
    };
    act(() => { useTelemetryStore.getState().receiveEnvStep(zeroFlows as any); });
    expect(useTelemetryStore.getState().envStep?.flows.solar_to_load_mw).toBe(0.0);
  });

  it("§12.7 — NumberDisplay renders '—' for NaN (guard on all numeric props)", async () => {
    const { NumberDisplay } = await import("../../src/components/NumberDisplay");
    const { container } = render(<NumberDisplay value={NaN} unit="MW" />);
    expect(container.textContent).not.toContain("NaN");
    expect(container.textContent).toContain("—");
  });

  it("§12.10 — EvalComparison renders placeholder when no eval run yet", async () => {
    const { EvalComparison } = await import("../../src/routes/EvalComparison");
    // Ensure store is empty
    const { useEvalStore } = await import("../../src/stores/evalStore");
    useEvalStore.getState().clear();
    const { container } = render(<EvalComparison />);
    expect(container.textContent?.toLowerCase()).toContain("no eval");
  });

  it("§12.11 — history buffer exactly at historyMaxLen=168 drops oldest, no crash", async () => {
    // Same as the ring buffer test above; duplicated here as the §12 commitment
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().clearHistory();
    for (let i = 0; i < 169; i++) {
      const msg = { ...FIXTURE_ENV_STEP, seq: i, payload: { ...FIXTURE_ENV_STEP.payload, step: i } };
      act(() => { useTelemetryStore.getState().receiveEnvStep(msg as any); });
    }
    expect(useTelemetryStore.getState().history.length).toBe(168);
  });
});

// ─── §2: TimeAxis component ────────────────────────────────────────────────────

describe("TimeAxis — rendering", () => {
  it("renders sim time string when provided", async () => {
    const { TimeAxis } = await import("../../src/components/TimeAxis");
    const { container } = render(
      <TimeAxis simTimeUtc="2026-03-10T08:00:00Z" step={42} dtHours={1.0} />
    );
    expect(container.textContent).toMatch(/08:00/);
  });

  it("renders step number", async () => {
    const { TimeAxis } = await import("../../src/components/TimeAxis");
    const { container } = render(
      <TimeAxis simTimeUtc="2026-03-10T08:00:00Z" step={168} dtHours={1.0} />
    );
    // D3: max training episode = 168 steps
    expect(container.textContent).toContain("168");
  });

  it("renders '—' when simTimeUtc is null", async () => {
    const { TimeAxis } = await import("../../src/components/TimeAxis");
    const { container } = render(<TimeAxis simTimeUtc={null} step={null} dtHours={1.0} />);
    expect(container.textContent).toContain("—");
  });
});

// ─── §3: Card component ────────────────────────────────────────────────────────

describe("Card — rendering", () => {
  it("renders children inside the card", async () => {
    const { Card } = await import("../../src/components/Card");
    const { container } = render(<Card>Hello Card</Card>);
    expect(container.textContent).toContain("Hello Card");
  });

  it("renders a title when provided", async () => {
    const { Card } = await import("../../src/components/Card");
    const { container } = render(<Card title="SOC">55%</Card>);
    expect(container.textContent).toContain("SOC");
  });

  it("applies the 'card' CSS class", async () => {
    const { Card } = await import("../../src/components/Card");
    const { container } = render(<Card>content</Card>);
    expect(container.querySelector(".card")).toBeTruthy();
  });
});

// ─── Type safety sanity checks (compile-time, via runtime instanceof assertions) ─

describe("type guard: TariffTier exhaustiveness", () => {
  it("every known TOU tier has a colour defined", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const expectedTiers = ["critical_peak", "peak", "mid", "valley"];
    for (const tier of expectedTiers) {
      expect(TOU_COLORS[tier as keyof typeof TOU_COLORS]).toBeDefined();
    }
  });
});

// ════════════════════════════════════════════════════════════════════════════
// REVIEWER-ADDED EDGE CASES (frontend-reviewer, 2026-06-10)
// Each case below is marked `// reviewer: <reason>`. These are part of the
// approved suite and must be green before implementation passes QA.
// PENDING_LOCK markers carry the same meaning as in the developer suite: the
// wire-format fixtures are conditional on the telemetry_schema.md LOCK.
// ════════════════════════════════════════════════════════════════════════════

// ─── units.ts — formatSimTime: exact day-of-week + UTC extraction ─────────────

describe("reviewer: formatSimTime — UTC clock, exact day + minutes", () => {
  // reviewer: §8 says "formats the UTC clock as-is, no timezone conversions". The
  // developer test only matched /08:00/ and never pinned the day-of-week, so an
  // off-by-one day, a wrong locale, or a getHours()/getDay() (local-time) impl
  // would slip through and display the wrong sim clock. These pin exact UTC output.
  it("2026-03-10T08:00:00Z renders 'Tue 08:00' (2026-03-10 is a Tuesday in UTC)", async () => {
    const { formatSimTime } = await import("../../src/utils/units");
    expect(formatSimTime("2026-03-10T08:00:00Z")).toBe("Tue 08:00");
  });

  it("2026-03-09T23:30:00Z renders 'Mon 23:30' — UTC-based; a local-time impl shifts day/hour", async () => {
    // reviewer: 23:30Z near the day boundary catches a getHours()/getDay() impl:
    // in any tz ahead of UTC a local-time impl rolls into Tue and a different hour.
    // A correct getUTC*-based impl returns this value regardless of runner tz.
    const { formatSimTime } = await import("../../src/utils/units");
    expect(formatSimTime("2026-03-09T23:30:00Z")).toBe("Mon 23:30");
  });
});

// ─── units.ts — formatYuanPerMwh: ¥/MWh unit guard (NOT ¥/kWh) ────────────────

describe("reviewer: formatYuanPerMwh — price unit is ¥/MWh, never ¥/kWh", () => {
  // reviewer: prime-directive unit guard. Prices on the wire are ¥/MWh
  // (telemetry_schema Units table). A ÷1000 (per-kWh) slip is exactly the kind of
  // critical unit bug this gate exists to catch.
  it("formats the sell price 590 as '¥590/MWh' with no /kWh anywhere", async () => {
    const { formatYuanPerMwh } = await import("../../src/utils/units");
    expect(formatYuanPerMwh(590)).toBe("¥590/MWh");
    expect(formatYuanPerMwh(590)).not.toMatch(/kWh/);
  });
});

// ─── units.ts — formatPower: zero-flow rendering is defined ───────────────────

describe("reviewer: formatPower — zero flow has defined output", () => {
  // reviewer: zero-flow rendering is a contracted §12.6 concern and the 3D scene
  // reads many flows that are 0.0. The <1 MW rule (§8) makes 0 fall in the kW
  // branch → "0 kW". Pin it so 0 never renders as "NaN", "" or "0.0 MW".
  it("formatPower(0) renders '0 kW' (0 < 1 MW → kW branch)", async () => {
    const { formatPower } = await import("../../src/utils/units");
    expect(formatPower(0)).toBe("0 kW");
  });
});

// ─── NumberDisplay — negative finite values must pass the guard ───────────────

describe("reviewer: NumberDisplay — negative finite value renders", () => {
  // reviewer: §12.7's guard rejects NaN/Infinity, but cost/net values are legitimately
  // negative (cost_total_yuan = -52700 in the fixture = net revenue). A guard that
  // accepts only value > 0 would wrongly blank a real reading. Pin that -52.7 renders.
  it("renders a negative finite value, not nullText", async () => {
    const { NumberDisplay } = await import("../../src/components/NumberDisplay");
    const { container } = render(<NumberDisplay value={-52.7} unit="MW" />);
    expect(container.textContent).toContain("-52.7");
    expect(container.textContent).not.toContain("—");
  });
});

// ─── telemetryStore — clearHistory fully resets seq tracking ──────────────────

describe("reviewer: telemetryStore — clearHistory resets seq tracking", () => {
  // reviewer: the developer clearHistory test checks history+envStep only. If
  // clearHistory does not also reset lastSeq/seqGap, the FIRST message after a
  // reconnect is compared against a stale lastSeq and false-flags a gap.
  it("clearHistory resets lastSeq to null and seqGap to false", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    act(() => {
      useTelemetryStore.getState().receiveEnvStep({ ...FIXTURE_ENV_STEP, seq: 10 } as any);
      useTelemetryStore.getState().receiveEnvStep({ ...FIXTURE_ENV_STEP, seq: 20 } as any); // gap → seqGap true
    });
    expect(useTelemetryStore.getState().seqGap).toBe(true);
    act(() => { useTelemetryStore.getState().clearHistory(); });
    expect(useTelemetryStore.getState().lastSeq).toBeNull();
    expect(useTelemetryStore.getState().seqGap).toBe(false);
  });
});

// ─── telemetryStore — first message is never a seq gap (PENDING_LOCK) ─────────

describe("reviewer: telemetryStore — first message is not a gap", () => {
  // reviewer: with lastSeq=null there is no prior seq to diff against. The first
  // env_step (which may have any seq, e.g. mid-episode reconnect) must NOT set seqGap.
  it("first receiveEnvStep with seq=5 leaves seqGap false", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().clearHistory();
    act(() => {
      useTelemetryStore.getState().receiveEnvStep({ ...FIXTURE_ENV_STEP, seq: 5 } as any);
    });
    expect(useTelemetryStore.getState().seqGap).toBe(false);
  });
});

// ─── telemetryStore — §12.3 reconnect with new run_id (PENDING_LOCK) ──────────

describe("reviewer: telemetryStore — §12.3 new run_id resets state", () => {
  // reviewer: §12.3 ("Reconnect with new run_id → clearHistory; old run not merged")
  // is a contracted commitment with NO developer test. This pins the observable
  // outcome: a message whose run_id differs from the current run must NOT merge into
  // the prior run's history and must NOT false-flag a seq gap when the new run's seq
  // resets low. NOTE TO DEV/ARCHITECT: the contract must state which layer enforces
  // this (store-internal on run_id change vs wsClient calling clearHistory) — this
  // test encodes the end state regardless of layer.
  it("a new run_id drops prior-run history and does not flag a seq gap", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().clearHistory();
    act(() => {
      useTelemetryStore.getState().receiveEnvStep({ ...FIXTURE_ENV_STEP, run_id: "run_A", seq: 167 } as any);
    });
    act(() => {
      useTelemetryStore.getState().receiveEnvStep({ ...FIXTURE_ENV_STEP, run_id: "run_B", seq: 0 } as any);
    });
    const state = useTelemetryStore.getState();
    expect(state.runId).toBe("run_B");
    expect(state.history).toHaveLength(1);      // only the new run's step, not merged
    expect(state.history[0].step).toBe(FIXTURE_ENV_STEP.payload.step);
    expect(state.seqGap).toBe(false);           // seq reset on new run is not a gap
  });
});

// ─── wsClient — missing required envelope fields (§4.3) (PENDING_LOCK) ─────────

describe("reviewer: wsClient — missing envelope fields discarded", () => {
  let server: any;
  beforeEach(() => {
    vi.stubGlobal("WebSocket", vi.fn().mockImplementation((url: string) => {
      server = { url, readyState: WebSocket.CONNECTING, send: vi.fn(), close: vi.fn(),
        onopen: null, onmessage: null, onerror: null, onclose: null };
      return server;
    }) as any);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("§4.3 — message missing `kind` is discarded without throwing or dispatching", async () => {
    // reviewer: §4.3 "Missing required envelope fields → log warning, discard" was
    // untested. A malformed message must never crash the socket or reach a callback.
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onEnvStep = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep, onTrainMetrics: vi.fn(), onEvalCompare: vi.fn(), onStatusChange: vi.fn(),
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    const { kind, ...noKind } = FIXTURE_ENV_STEP as any;
    expect(() => {
      act(() => { server.onmessage?.({ data: JSON.stringify(noKind) } as MessageEvent); });
    }).not.toThrow();
    expect(onEnvStep).not.toHaveBeenCalled();
  });

  it("§4.3 — message missing `payload` is discarded without dispatching", async () => {
    // reviewer: a kind present but payload absent must not reach the typed callback.
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onEnvStep = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep, onTrainMetrics: vi.fn(), onEvalCompare: vi.fn(), onStatusChange: vi.fn(),
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    const { payload, ...noPayload } = FIXTURE_ENV_STEP as any;
    expect(() => {
      act(() => { server.onmessage?.({ data: JSON.stringify(noPayload) } as MessageEvent); });
    }).not.toThrow();
    expect(onEnvStep).not.toHaveBeenCalled();
  });
});

// ─── wsClient — minor-version forward compatibility (PENDING_LOCK) ────────────

describe("reviewer: wsClient — minor-forward-compat", () => {
  let server: any;
  beforeEach(() => {
    vi.stubGlobal("WebSocket", vi.fn().mockImplementation((url: string) => {
      server = { url, readyState: WebSocket.CONNECTING, send: vi.fn(), close: vi.fn(),
        onopen: null, onmessage: null, onerror: null, onclose: null };
      return server;
    }) as any);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("a 1.x message carrying an unknown extra field is still dispatched (ignore unknown fields)", async () => {
    // reviewer: telemetry_schema Versioning — "Consumers MUST ignore unknown fields
    // and SHOULD warn-and-continue on a higher minor." The dev suite tests reject-2.0.0
    // but never the forward-compat half, so a consumer that hard-rejects any version
    // mismatch (breaking additive minor bumps / §8.5 assets_ext growth) would pass.
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onEnvStep = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep, onTrainMetrics: vi.fn(), onEvalCompare: vi.fn(), onStatusChange: vi.fn(),
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    const fwd = { ...FIXTURE_ENV_STEP, schema_version: "1.5.0",
      payload: { ...FIXTURE_ENV_STEP.payload, some_future_field: 123 } };
    act(() => { server.onmessage?.({ data: JSON.stringify(fwd) } as MessageEvent); });
    expect(onEnvStep).toHaveBeenCalledOnce();
    expect(onEnvStep.mock.calls[0][0].payload.step).toBe(42);
  });
});

// ─── wsClient — recovery from stale on next message ───────────────────────────

describe("reviewer: wsClient — stale recovers to connected on next message", () => {
  let server: any;
  beforeEach(() => {
    vi.stubGlobal("WebSocket", vi.fn().mockImplementation((url: string) => {
      server = { url, readyState: WebSocket.CONNECTING, send: vi.fn(), close: vi.fn(),
        onopen: null, onmessage: null, onerror: null, onclose: null };
      return server;
    }) as any);
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("a message arriving after 'stale' returns status to 'connected'", async () => {
    // reviewer: §4.1.5 makes 'stale' a sticky state with no defined exit. Without a
    // recovery transition the status indicator stays "stale" forever even though data
    // is flowing again. Pin that the next message clears stale back to connected.
    vi.useFakeTimers();
    const { createWsClient } = await import("../../src/clients/wsClient");
    const onStatusChange = vi.fn();
    const client = createWsClient({
      url: "ws://localhost:8000/ws",
      onEnvStep: vi.fn(), onTrainMetrics: vi.fn(), onEvalCompare: vi.fn(),
      onStatusChange, staleAfterMs: 5000,
    });
    client.connect();
    act(() => { server.onopen?.(new Event("open")); });
    act(() => { vi.advanceTimersByTime(5001); });
    expect(onStatusChange).toHaveBeenCalledWith("stale");
    onStatusChange.mockClear();
    act(() => { server.onmessage?.({ data: JSON.stringify(FIXTURE_ENV_STEP) } as MessageEvent); });
    expect(onStatusChange).toHaveBeenCalledWith("connected");
  });
});

// ─── restClient — timeout path (§5) ───────────────────────────────────────────

describe("reviewer: restClient — timeout rejects with 'timeout:'", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("a request that exceeds timeoutMs rejects with a timeout error", async () => {
    // reviewer: §5 defines `timeout: <url>` but no test exercised it. A client that
    // never times out hangs the dashboard on a dead server.
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise(() => {}))); // never resolves
    const { createRestClient } = await import("../../src/clients/restClient");
    const client = createRestClient({ baseUrl: "http://localhost:8000", timeoutMs: 1000 });
    const p = client.getRuns();
    const assertion = expect(p).rejects.toThrow(/timeout/);
    await act(async () => { await vi.advanceTimersByTimeAsync(1001); });
    await assertion;
  });
});

// ─── restClient — getSiteConfig field names + units (feeds 3D scaling) ────────

describe("reviewer: restClient — getSiteConfig pins field names and units", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns SiteConfig with MW/MWh fields intact (945 MW export, 294.5 MWh battery)", async () => {
    // reviewer: only getRuns was tested. getSiteConfig.pcc_max_export_mw is what the 3D
    // scene scales the PCC wire against (D5=945) and battery_capacity_mwh (294.5) sizes
    // the SOC bank — wrong field name or a kW/MW mixup here silently mis-scales the scene.
    const mockCfg = {
      site_id: "gansu",
      wind_capacity_mw: 800, solar_capacity_mw: 500,
      battery_capacity_mwh: 294.5, battery_max_charge_mw: 100, battery_max_discharge_mw: 100,
      pcc_max_export_mw: 945, pcc_max_import_mw: 400,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => mockCfg }));
    const { createRestClient } = await import("../../src/clients/restClient");
    const client = createRestClient({ baseUrl: "http://localhost:8000" });
    const cfg = await client.getSiteConfig("gansu");
    expect(cfg.pcc_max_export_mw).toBe(945);   // D5 physics export limit, MW
    expect(cfg.pcc_max_import_mw).toBe(400);
    expect(cfg.battery_capacity_mwh).toBe(294.5);
  });
});

// ─── evalStore — self-contained (no cross-test state leak) + cost integrity ───

describe("reviewer: evalStore — self-contained dispatch + cost-sum integrity", () => {
  // reviewer: the developer "stores all three policy entries" test reads `latest`
  // without dispatching, depending on the previous test leaving store state — it
  // breaks under test reordering/isolation. This version dispatches its own fixture.
  it("stores all three policies after its own dispatch", async () => {
    const { useEvalStore } = await import("../../src/stores/evalStore");
    useEvalStore.getState().clear();
    act(() => { useEvalStore.getState().receiveEvalCompare(FIXTURE_EVAL_COMPARE as any); });
    const latest = useEvalStore.getState().latest;
    expect(latest?.policies.rl).toBeDefined();
    expect(latest?.policies.no_battery).toBeDefined();
    expect(latest?.policies.rule_based_tou).toBeDefined();
  });

  it("each policy's cost components sum to total_cost_yuan", async () => {
    // reviewer: cost-breakdown integrity (acceptance: components add to the headline
    // total). Guards the fixture and any store-side total against drift.
    const { policies } = FIXTURE_EVAL_COMPARE.payload;
    for (const p of Object.values(policies)) {
      const sum = p.energy_cost_yuan + p.demand_charge_yuan + p.degradation_yuan
        + p.curtailment_yuan + p.voll_yuan;
      expect(sum).toBe(p.total_cost_yuan);
    }
  });
});
