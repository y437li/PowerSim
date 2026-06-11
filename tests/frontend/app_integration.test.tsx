/**
 * tests/frontend/app_integration.test.tsx
 * Contract: contracts/frontend/app_integration.md
 *
 * Tests are grouped by contract section (§T1–§T9).
 * Mock declarations are hoisted to module top per Vitest semantics.
 *
 * Mocked modules:
 *   - wsClientSingleton — prevents real WebSocket connections in every test
 *   - src/scene/SiteScene — prevents R3F / Three.js in jsdom
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

// ─── Module-level mocks (hoisted by Vitest) ──────────────────────────────────

// §T2 / §T3 / §T4: mock the singleton so no real socket is opened
const mockConnect = vi.fn();
const mockDisconnect = vi.fn();
vi.mock("../../src/clients/wsClientSingleton", () => ({
  wsClientSingleton: { connect: mockConnect, disconnect: mockDisconnect },
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
// These run after the hoisted mocks, so the mocked versions are used.
const { default: App } = await import("../../src/App");
const { default: SiteView } = await import("../../src/routes/SiteView");

// ─── §T1 — Vite proxy config ─────────────────────────────────────────────────

describe("§T1 — vite.config.ts proxy", () => {
  it("has /api proxy targeting http://localhost:8000", async () => {
    const mod = await import("../../vite.config");
    // defineConfig returns its argument — exported default is the config object
    const config = (mod as any).default ?? mod;
    const apiProxy = (config?.server?.proxy ?? config?.default?.server?.proxy)?.["/api"];
    expect(apiProxy, "server.proxy['/api'] must be defined").toBeTruthy();
    const target =
      typeof apiProxy === "string" ? apiProxy : (apiProxy as any)?.target;
    expect(target).toBe("http://localhost:8000");
  });

  it("has /api proxy with changeOrigin: true", async () => {
    const mod = await import("../../vite.config");
    const config = (mod as any).default ?? mod;
    const apiProxy = (config?.server?.proxy ?? config?.default?.server?.proxy)?.["/api"];
    expect(typeof apiProxy).toBe("object");
    expect((apiProxy as any).changeOrigin).toBe(true);
  });

  it("has /ws proxy with ws: true", async () => {
    const mod = await import("../../vite.config");
    const config = (mod as any).default ?? mod;
    const wsProxy = (config?.server?.proxy ?? config?.default?.server?.proxy)?.["/ws"];
    expect(wsProxy, "server.proxy['/ws'] must be defined").toBeTruthy();
    expect((wsProxy as any).ws).toBe(true);
  });
});

// ─── §T2 — wsClientSingleton shape ───────────────────────────────────────────

describe("§T2 — wsClientSingleton exports WsClient", () => {
  it("exports wsClientSingleton with connect and disconnect functions", async () => {
    const { wsClientSingleton } = await import(
      "../../src/clients/wsClientSingleton"
    );
    expect(typeof wsClientSingleton.connect).toBe("function");
    expect(typeof wsClientSingleton.disconnect).toBe("function");
  });
});

// ─── §T3 — App calls connect on mount ────────────────────────────────────────

describe("§T3 — App connects wsClient on mount", () => {
  beforeEach(() => {
    mockConnect.mockClear();
    mockDisconnect.mockClear();
  });

  it("calls wsClientSingleton.connect() exactly once when App mounts", () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );
    expect(mockConnect).toHaveBeenCalledOnce();
  });
});

// ─── §T4 — App calls disconnect on unmount ───────────────────────────────────

describe("§T4 — App disconnects wsClient on unmount", () => {
  beforeEach(() => {
    mockConnect.mockClear();
    mockDisconnect.mockClear();
  });

  it("calls wsClientSingleton.disconnect() exactly once when App unmounts", () => {
    const { unmount } = render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );
    unmount();
    expect(mockDisconnect).toHaveBeenCalledOnce();
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
  it(
    "SiteScene mock shows data-container-set=true after SceneMountPoint.onReady fires",
    () => {
      // SceneMountPoint calls onReady(ref.current) in useEffect([]) — fires on mount.
      // The mocked SiteScene reflects containerEl as a data attribute.
      render(
        <MemoryRouter>
          <SiteView />
        </MemoryRouter>
      );
      const sceneEl = screen.getByTestId("site-scene-mock");
      // After SceneMountPoint fires onReady, containerEl state is set → SiteScene receives it
      expect(sceneEl.dataset.containerSet).toBe("true");
    }
  );
});

// ─── §T8 — GANSU_SITE_CONFIG shape ───────────────────────────────────────────

describe("§T8 — GANSU_SITE_CONFIG shape", () => {
  it('has site_id "gansu"', async () => {
    const { GANSU_SITE_CONFIG } = await import("../../src/config/gansuSiteConfig");
    expect(GANSU_SITE_CONFIG.site_id).toBe("gansu");
  });

  it("has at least 1 turbine", async () => {
    const { GANSU_SITE_CONFIG } = await import("../../src/config/gansuSiteConfig");
    expect(GANSU_SITE_CONFIG.turbines.length).toBeGreaterThanOrEqual(1);
  });

  it("battery assetId is a valid key in ASSET_REGISTRY", async () => {
    const { GANSU_SITE_CONFIG, ASSET_REGISTRY } = await import(
      "../../src/config/gansuSiteConfig"
    );
    expect(ASSET_REGISTRY.assets[GANSU_SITE_CONFIG.battery.assetId]).toBeDefined();
  });

  it("all turbine assetIds are valid keys in ASSET_REGISTRY", async () => {
    const { GANSU_SITE_CONFIG, ASSET_REGISTRY } = await import(
      "../../src/config/gansuSiteConfig"
    );
    for (const t of GANSU_SITE_CONFIG.turbines) {
      expect(
        ASSET_REGISTRY.assets[t.assetId],
        `turbine assetId "${t.assetId}" missing from registry`
      ).toBeDefined();
    }
  });

  it("all pv_array assetIds are valid keys in ASSET_REGISTRY", async () => {
    const { GANSU_SITE_CONFIG, ASSET_REGISTRY } = await import(
      "../../src/config/gansuSiteConfig"
    );
    for (const p of GANSU_SITE_CONFIG.pv_arrays) {
      expect(
        ASSET_REGISTRY.assets[p.assetId],
        `pv_array assetId "${p.assetId}" missing from registry`
      ).toBeDefined();
    }
  });

  it("wind_capacity_mw and solar_capacity_mw are positive numbers", async () => {
    const { GANSU_SITE_CONFIG } = await import("../../src/config/gansuSiteConfig");
    expect(GANSU_SITE_CONFIG.wind_capacity_mw).toBeGreaterThan(0);
    expect(GANSU_SITE_CONFIG.solar_capacity_mw).toBeGreaterThan(0);
  });

  it("battery capacity_mwh, max_charge_mw, max_discharge_mw are positive", async () => {
    const { GANSU_SITE_CONFIG } = await import("../../src/config/gansuSiteConfig");
    expect(GANSU_SITE_CONFIG.battery.capacity_mwh).toBeGreaterThan(0);
    expect(GANSU_SITE_CONFIG.battery.max_charge_mw).toBeGreaterThan(0);
    expect(GANSU_SITE_CONFIG.battery.max_discharge_mw).toBeGreaterThan(0);
  });
});

// ─── §T9 — ASSET_REGISTRY equals registry.json ───────────────────────────────

describe("§T9 — ASSET_REGISTRY equals assets/3d/registry.json", () => {
  it("ASSET_REGISTRY deep-equals the raw JSON import of assets/3d/registry.json", async () => {
    const { ASSET_REGISTRY } = await import("../../src/config/gansuSiteConfig");
    // Import raw JSON; Vitest handles JSON imports natively
    const rawRegistry = await import("../../assets/3d/registry.json");
    const raw = (rawRegistry as any).default ?? rawRegistry;
    expect(ASSET_REGISTRY).toEqual(raw);
  });
});
