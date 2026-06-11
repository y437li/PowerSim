/**
 * tests/frontend/app_integration.test.tsx
 * Contract: contracts/frontend/app_integration.md
 *
 * Tests are grouped by contract section (§T1–§T9, §T_url, §T_wire).
 * Mock declarations are hoisted to module top per Vitest semantics.
 *
 * Mocked modules:
 *   - wsClientSingleton — prevents real WebSocket connections (§T3/§T4/§T5/§T6/§T7)
 *   - src/scene/SiteScene — prevents R3F / Three.js in jsdom
 *
 * §T2, §T_url, §T_wire use vi.importActual to test the REAL module shape/wiring.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

// ─── Golden fixtures ──────────────────────────────────────────────────────────
import envStepAGolden from "../../contracts/shared/telemetry_examples/env_step_a.json";
import trainMetricsGolden from "../../contracts/shared/telemetry_examples/train_metrics.json";

// ─── Store imports (used in §T_wire for direct state checks) ─────────────────
import { useTelemetryStore } from "../../src/stores/telemetryStore";
import { useTrainingStore } from "../../src/stores/trainingStore";

// ─── Module-level mocks (hoisted by Vitest) ──────────────────────────────────

// §T3/§T4: mock the TWO singletons so no real socket is opened in App/SiteView tests
const mockTelemetryConnect = vi.fn();
const mockTelemetryDisconnect = vi.fn();
const mockTrainingConnect = vi.fn();
const mockTrainingDisconnect = vi.fn();

vi.mock("../../src/clients/wsClientSingleton", () => ({
  telemetryWsClient: {
    connect: mockTelemetryConnect,
    disconnect: mockTelemetryDisconnect,
  },
  trainingWsClient: {
    connect: mockTrainingConnect,
    disconnect: mockTrainingDisconnect,
  },
  // handleEnvStep / handleTrainMetrics / handleStatusChange / URL constants
  // are intentionally NOT mocked — tested via vi.importActual in §T_wire / §T_url
}));

// §T7: mock SiteScene to expose containerEl via data attribute (avoids R3F in jsdom)
vi.mock("../../src/scene/SiteScene", () => ({
  SiteScene: ({
    containerEl,
  }: {
    containerEl: HTMLDivElement | null;
    [k: string]: unknown;
  }) => (
    <div
      data-testid="site-scene-mock"
      data-container-set={containerEl !== null ? "true" : "false"}
    />
  ),
}));

// ─── Lazy imports after vi.mock declarations ──────────────────────────────────
const { default: App } = await import("../../src/App");
const { default: SiteView } = await import("../../src/routes/SiteView");

// ─── §T1 — Vite proxy config ─────────────────────────────────────────────────
//
// Proxy config lives in src/config/viteProxy.ts (plain TS, no esbuild dep).
// vite.config.ts uses: server: { proxy: VITE_PROXY_CONFIG }

import { VITE_PROXY_CONFIG } from "../../src/config/viteProxy";

describe("§T1 — Vite proxy config (src/config/viteProxy.ts)", () => {
  it("has /api proxy entry defined", () => {
    expect(VITE_PROXY_CONFIG["/api"], "VITE_PROXY_CONFIG['/api'] must be defined").toBeTruthy();
  });

  it("has /api proxy targeting http://localhost:8000", () => {
    expect(VITE_PROXY_CONFIG["/api"]?.target).toBe("http://localhost:8000");
  });

  it("has /api proxy with changeOrigin: true", () => {
    expect(VITE_PROXY_CONFIG["/api"]?.changeOrigin).toBe(true);
  });

  it("has /ws proxy with ws: true", () => {
    expect(VITE_PROXY_CONFIG["/ws"], "VITE_PROXY_CONFIG['/ws'] must be defined").toBeTruthy();
    expect(VITE_PROXY_CONFIG["/ws"]?.ws).toBe(true);
  });
});

// ─── §T2 — wsClientSingleton exports two WsClients ───────────────────────────

describe("§T2 — wsClientSingleton exports two WsClients (real module)", () => {
  it("exports telemetryWsClient with connect and disconnect", async () => {
    // vi.importActual bypasses the mock to test the real module shape.
    const actual = await vi.importActual<
      typeof import("../../src/clients/wsClientSingleton")
    >("../../src/clients/wsClientSingleton");
    expect(typeof actual.telemetryWsClient.connect).toBe("function");
    expect(typeof actual.telemetryWsClient.disconnect).toBe("function");
  });

  it("exports trainingWsClient with connect and disconnect", async () => {
    const actual = await vi.importActual<
      typeof import("../../src/clients/wsClientSingleton")
    >("../../src/clients/wsClientSingleton");
    expect(typeof actual.trainingWsClient.connect).toBe("function");
    expect(typeof actual.trainingWsClient.disconnect).toBe("function");
  });
});

// ─── §T_url — Socket URL constants ───────────────────────────────────────────

describe("§T_url — WebSocket URL constants (serving endpoint paths)", () => {
  it("TELEMETRY_WS_URL is /ws/inference (contracts/serving/inference_stream.md:24)", async () => {
    const actual = await vi.importActual<
      typeof import("../../src/clients/wsClientSingleton")
    >("../../src/clients/wsClientSingleton");
    expect(actual.TELEMETRY_WS_URL).toBe("/ws/inference");
  });

  it("TRAINING_WS_URL is /ws/training/stream (contracts/serving/training_proxy.md:98)", async () => {
    const actual = await vi.importActual<
      typeof import("../../src/clients/wsClientSingleton")
    >("../../src/clients/wsClientSingleton");
    expect(actual.TRAINING_WS_URL).toBe("/ws/training/stream");
  });
});

// ─── §T_wire — Handler wiring (real stores, real handlers) ───────────────────
//
// Uses vi.importActual to get the real handleEnvStep / handleTrainMetrics /
// handleStatusChange, then calls them and checks the real Zustand stores updated.
// The stores are NOT mocked here — module-level vi.mock only mocks wsClientSingleton
// (the stores are left as real Zustand singletons).

describe("§T_wire — wsClientSingleton handler wiring", () => {
  beforeEach(() => {
    // Isolate store state between tests
    useTelemetryStore.getState().clearHistory();
    useTrainingStore.getState().clear();
  });

  it("handleEnvStep routes env_step to telemetryStore.receiveEnvStep (golden fixture)", async () => {
    const { handleEnvStep } = await vi.importActual<
      typeof import("../../src/clients/wsClientSingleton")
    >("../../src/clients/wsClientSingleton");

    // Feed golden fixture (schema-locked env_step envelope)
    handleEnvStep(envStepAGolden as any);

    // telemetryStore.envStep should be populated with the fixture's payload
    const state = useTelemetryStore.getState();
    expect(state.envStep).not.toBeNull();
    expect(state.envStep?.step).toBe((envStepAGolden.payload as any).step);
  });

  it("handleTrainMetrics routes train_metrics to trainingStore.receiveTrainMetrics (golden fixture)", async () => {
    const { handleTrainMetrics } = await vi.importActual<
      typeof import("../../src/clients/wsClientSingleton")
    >("../../src/clients/wsClientSingleton");

    handleTrainMetrics(trainMetricsGolden as any);

    const state = useTrainingStore.getState();
    expect(state.latest).not.toBeNull();
    expect(state.latest?.global_step).toBe(trainMetricsGolden.payload.global_step);
  });

  it("handleStatusChange routes to telemetryStore.setWsStatus", async () => {
    const { handleStatusChange } = await vi.importActual<
      typeof import("../../src/clients/wsClientSingleton")
    >("../../src/clients/wsClientSingleton");

    handleStatusChange("connected");
    expect(useTelemetryStore.getState().wsStatus).toBe("connected");

    handleStatusChange("stale");
    expect(useTelemetryStore.getState().wsStatus).toBe("stale");

    handleStatusChange("disconnected");
    expect(useTelemetryStore.getState().wsStatus).toBe("disconnected");
  });
});

// ─── §T3 — App connects BOTH clients on mount ────────────────────────────────

describe("§T3 — App connects both ws clients on mount", () => {
  beforeEach(() => {
    mockTelemetryConnect.mockClear();
    mockTelemetryDisconnect.mockClear();
    mockTrainingConnect.mockClear();
    mockTrainingDisconnect.mockClear();
  });

  it("calls telemetryWsClient.connect() exactly once when App mounts", () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );
    expect(mockTelemetryConnect).toHaveBeenCalledOnce();
  });

  it("calls trainingWsClient.connect() exactly once when App mounts", () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );
    expect(mockTrainingConnect).toHaveBeenCalledOnce();
  });
});

// ─── §T4 — App disconnects BOTH clients on unmount ───────────────────────────
//
// Note: under React 18 StrictMode (dev), the effect double-invokes:
//   connect → disconnect → connect (idempotent no-op) → [unmount] → disconnect
// wsClient.connect() is idempotent (no-op if ws !== null), and open() resets
// intentionalClose = false on remount, so reconnection after StrictMode's synthetic
// unmount works correctly. These tests use MemoryRouter without StrictMode so
// the "exactly once" assertion holds cleanly.

describe("§T4 — App disconnects both ws clients on unmount", () => {
  beforeEach(() => {
    mockTelemetryConnect.mockClear();
    mockTelemetryDisconnect.mockClear();
    mockTrainingConnect.mockClear();
    mockTrainingDisconnect.mockClear();
  });

  it("calls telemetryWsClient.disconnect() exactly once when App unmounts", () => {
    const { unmount } = render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );
    unmount();
    expect(mockTelemetryDisconnect).toHaveBeenCalledOnce();
  });

  it("calls trainingWsClient.disconnect() exactly once when App unmounts", () => {
    const { unmount } = render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );
    unmount();
    expect(mockTrainingDisconnect).toHaveBeenCalledOnce();
  });
});

// ─── §T5 — SiteView renders SceneMountPoint ──────────────────────────────────

describe("§T5 — SiteView renders SceneMountPoint", () => {
  it('renders an element with data-testid="scene-mount-point"', () => {
    render(
      <MemoryRouter>
        <SiteView />
      </MemoryRouter>
    );
    expect(screen.getByTestId("scene-mount-point")).toBeInTheDocument();
  });
});

// ─── §T6 — SiteView renders LiveDashboard ────────────────────────────────────

describe("§T6 — SiteView renders LiveDashboard", () => {
  it('renders an element with data-testid="live-dashboard"', () => {
    render(
      <MemoryRouter>
        <SiteView />
      </MemoryRouter>
    );
    expect(screen.getByTestId("live-dashboard")).toBeInTheDocument();
  });
});

// ─── §T7 — SiteScene receives containerEl from SceneMountPoint.onReady ───────

describe("§T7 — SiteScene receives non-null containerEl after mount", () => {
  it("SiteScene mock shows data-container-set=true after SceneMountPoint.onReady fires", () => {
    // SceneMountPoint calls onReady(ref.current) in useEffect([]) — fires on mount.
    // SiteScene.useEffect([containerEl]) re-runs when containerEl transitions null→div.
    render(
      <MemoryRouter>
        <SiteView />
      </MemoryRouter>
    );
    const sceneEl = screen.getByTestId("site-scene-mock");
    expect(sceneEl.dataset.containerSet).toBe("true");
  });
});

// ─── §T8 — GANSU_SITE_CONFIG shape ───────────────────────────────────────────

import { GANSU_SITE_CONFIG, ASSET_REGISTRY } from "../../src/config/gansuSiteConfig";

describe("§T8 — GANSU_SITE_CONFIG shape (§1 authoritative nameplates)", () => {
  it('has site_id "gansu"', () => {
    expect(GANSU_SITE_CONFIG.site_id).toBe("gansu");
  });

  it("has at least 1 turbine", () => {
    expect(GANSU_SITE_CONFIG.turbines.length).toBeGreaterThanOrEqual(1);
  });

  it("wind_capacity_mw is 615 (§1 nameplate; 400 = import limit D12, not wind)", () => {
    // Section 01 authoritative: Wind 615 MW. The value 400 is the import limit (D12).
    expect(GANSU_SITE_CONFIG.wind_capacity_mw).toBe(615);
  });

  it("solar_capacity_mw is 330 (§1 nameplate)", () => {
    expect(GANSU_SITE_CONFIG.solar_capacity_mw).toBe(330);
  });

  it("battery.capacity_mwh is 294.5 (§1: 294.5 MWh)", () => {
    expect(GANSU_SITE_CONFIG.battery.capacity_mwh).toBe(294.5);
  });

  it("battery.max_charge_mw is 98.16 (§1: 98.16 MW)", () => {
    expect(GANSU_SITE_CONFIG.battery.max_charge_mw).toBe(98.16);
  });

  it("battery.max_discharge_mw is 98.16 (§1: 98.16 MW)", () => {
    expect(GANSU_SITE_CONFIG.battery.max_discharge_mw).toBe(98.16);
  });

  it("battery assetId is a valid key in ASSET_REGISTRY", () => {
    expect(ASSET_REGISTRY.assets[GANSU_SITE_CONFIG.battery.assetId]).toBeDefined();
  });

  it("all turbine assetIds are valid keys in ASSET_REGISTRY", () => {
    for (const t of GANSU_SITE_CONFIG.turbines) {
      expect(
        ASSET_REGISTRY.assets[t.assetId],
        `turbine assetId "${t.assetId}" missing from registry`
      ).toBeDefined();
    }
  });

  it("all pv_array assetIds are valid keys in ASSET_REGISTRY", () => {
    for (const p of GANSU_SITE_CONFIG.pv_arrays) {
      expect(
        ASSET_REGISTRY.assets[p.assetId],
        `pv_array assetId "${p.assetId}" missing from registry`
      ).toBeDefined();
    }
  });
});

// ─── §T9 — ASSET_REGISTRY equals assets/3d/registry.json ────────────────────

describe("§T9 — ASSET_REGISTRY equals assets/3d/registry.json", () => {
  it("ASSET_REGISTRY deep-equals the raw JSON import of assets/3d/registry.json", async () => {
    const rawRegistry = await import("../../assets/3d/registry.json");
    const raw = (rawRegistry as any).default ?? rawRegistry;
    expect(ASSET_REGISTRY).toEqual(raw);
  });
});

// ─── reviewer (frontend-reviewer): §T1 /api rewrite — REST routing correctness ──
// §T1 pins target/changeOrigin/ws:true but NOT the /api rewrite. A wrong rewrite
// silently 404s every REST call (the FastAPI routes have no /api prefix). Pin the
// §1 rewrite rule: /^\/api(\/.*)?$/ → $1 || '/'.
describe("reviewer: §T1 /api proxy rewrite (strip prefix — REST routing)", () => {
  type ProxyEntry = { rewrite?: (p: string) => string };

  it("defines a rewrite function on the /api proxy (§1)", () => {
    const api = VITE_PROXY_CONFIG["/api"] as ProxyEntry;
    expect(typeof api.rewrite, "/api proxy must define a rewrite fn (§1)").toBe("function");
  });

  it("strips the /api prefix: /api/sites -> /sites", () => {
    const api = VITE_PROXY_CONFIG["/api"] as ProxyEntry;
    expect(api.rewrite!("/api/sites")).toBe("/sites");
  });

  it("maps bare /api -> / (root)", () => {
    const api = VITE_PROXY_CONFIG["/api"] as ProxyEntry;
    expect(api.rewrite!("/api")).toBe("/");
  });

  it("maps /api/ (trailing slash) -> /", () => {
    const api = VITE_PROXY_CONFIG["/api"] as ProxyEntry;
    expect(api.rewrite!("/api/")).toBe("/");
  });

  it("/ws proxy has no rewrite — paths pass through to serving endpoints verbatim", () => {
    const ws = VITE_PROXY_CONFIG["/ws"] as ProxyEntry;
    expect(ws.rewrite).toBeUndefined();
  });
});
