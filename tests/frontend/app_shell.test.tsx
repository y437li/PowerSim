/**
 * Test suite: app_shell
 *
 * Framework: Vitest + React Testing Library
 * Contract:  contracts/frontend/app_shell.md
 * Spec refs: REBUILD_SPEC.md §2, §3, §3.5, §3.7, §5; telemetry_schema.md (DRAFT)
 *
 * ⚠ PENDING TELEMETRY LOCK: tests that parse wire messages are marked with the
 *   comment // PENDING_LOCK — they compile and run but the fixture shapes
 *   MUST be re-verified once rl-architect locks contracts/shared/telemetry_schema.md.
 *
 * Tests are intentionally RED at this point — no implementation exists yet.
 * That is correct per the contract-first-dev workflow.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// ─── Fixture data ─────────────────────────────────────────────────────────────

/** Minimal valid env_step envelope fixture (PENDING_LOCK — matches DRAFT telemetry schema) */
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
      soc_violation_mwh: 0.0,
      capacity_mwh: 294.5,
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
      ren_curtailed_mw: 0.0,
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
      c_energy_yuan: 0.0,
      c_import_yuan: 0.0,
      r_export_yuan: 53100.0,
      c_demand_shape_yuan: 0.0,
      c_degradation_yuan: 400.0,
      c_curtail_yuan: 0.0,
      c_voll_yuan: 0.0,
      penalty_yuan: 0.0,
      cost_total_yuan: -52700.0,
    },
    cost_cum: {
      c_energy_yuan_cum: 0.0,
      c_demand_charge_yuan_cum: 0.0,
      c_degradation_yuan_cum: 0.0,
      c_curtail_yuan_cum: 0.0,
      c_voll_yuan_cum: 0.0,
    },
    month_peak_mw: 95.0,
    reward: 0.527,
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
    reward_mean: 0.61,
    reward_unnorm_mean_yuan: -61000.0,
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
    policies: {
      rl:            { energy_cost_yuan: 100_000, demand_charge_yuan: 20_000, degradation_yuan: 5_000, curtailment_yuan: 500, voll_yuan: 0, soc_violations_count: 0, total_cost_yuan: 125_500 },
      no_battery:    { energy_cost_yuan: 200_000, demand_charge_yuan: 50_000, degradation_yuan: 0,     curtailment_yuan: 1_000, voll_yuan: 100, soc_violations_count: 0, total_cost_yuan: 251_100 },
      rule_based_tou:{ energy_cost_yuan: 160_000, demand_charge_yuan: 35_000, degradation_yuan: 4_000, curtailment_yuan: 800, voll_yuan: 50, soc_violations_count: 2, total_cost_yuan: 199_850 },
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
  it("formats Monday 08:00 UTC correctly", async () => {
    // "2026-03-10T08:00:00Z" is a Tuesday; function formats day-of-week + HH:MM
    const { formatSimTime } = await import("../../src/utils/units");
    const result = formatSimTime("2026-03-10T08:00:00Z");
    // Must include HH:MM part
    expect(result).toMatch(/08:00/);
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(4);
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

// ─── §4: Telemetry store — state shape & updates (PENDING_LOCK) ───────────────

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
    const { useEvalStore } = await import("../../src/stores/evalStore");
    const latest = useEvalStore.getState().latest;
    expect(latest?.policies.rl).toBeDefined();
    expect(latest?.policies.no_battery).toBeDefined();
    expect(latest?.policies.rule_based_tou).toBeDefined();
  });
});

// ─── §4: WebSocket client — lifecycle (PENDING_LOCK) ──────────────────────────

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
