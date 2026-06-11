/**
 * tests/frontend3d/scene_graph.test.tsx
 *
 * Contract-gated test suite for the 3D scene graph.
 * Contract: contracts/frontend3d/scene_graph.md
 *
 * Tests are RED until implementation (SceneContent.tsx, isPayloadFinite.ts,
 * and SiteScene.tsx modifications). The import on line 22 will throw until
 * src/scene/SceneContent.tsx exists.
 *
 * Spec refs: REBUILD_SPEC §8 (3D visualization)
 * Decision refs: D4 (SOC 0.2–0.9), D5 (PCC 945 MW), D12 (import limit)
 * Telemetry: contracts/shared/telemetry_schema.md LOCKED v1.0.0 (PR #6)
 *
 * Reviewer-added cases are marked: // reviewer: <reason>
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
import React from "react";

// --- imports that are RED until implementation ---
import { SceneContent, glbUrl } from "../../src/scene/SceneContent";
import { SiteScene } from "../../src/scene/SiteScene";
import type {
  AssetRegistry,
  AssetRegistryEntry,
  SiteSceneConfig,
} from "../../src/scene/types";
import type { EnvStepPayload } from "../../src/types/telemetry";

// ─── R3F / drei mocks ─────────────────────────────────────────────────────────
// These must be hoisted before any module under test loads @react-three/fiber.
// createRoot().render and createRoot().unmount are the key wiring points.

const mockR3fRender = vi.fn();
const mockR3fUnmount = vi.fn();
const mockCreateRoot = vi.fn(() => ({
  render: mockR3fRender,
  unmount: mockR3fUnmount,
}));

vi.mock("@react-three/fiber", () => ({
  createRoot: mockCreateRoot,
  useFrame: vi.fn(),
  extend: vi.fn(),
}));

const mockUseGLTF = vi.fn(() => ({
  scene: {
    clone: vi.fn(() => ({
      traverse: vi.fn(),
      position: { set: vi.fn() },
      rotation: { set: vi.fn() },
    })),
  },
  nodes: {},
  materials: {},
}));

vi.mock("@react-three/drei", () => ({
  useGLTF: (url: string) => mockUseGLTF(url),
}));

// ─── Telemetry store mock ─────────────────────────────────────────────────────

type WsStatus = "connecting" | "connected" | "disconnected" | "stale";
let _mockEnvStep: EnvStepPayload | null = null;
let _mockWsStatus: WsStatus = "connecting";

vi.mock("../../src/stores/telemetryStore", () => ({
  useTelemetryStore: vi.fn((selector?: (s: unknown) => unknown) => {
    const state = { envStep: _mockEnvStep, wsStatus: _mockWsStatus };
    return selector ? selector(state) : state;
  }),
}));

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const ENTRY_TURBINE: AssetRegistryEntry = {
  path: "turbines/vestas-v150-4.2.glb",
  type: "turbine",
  dims_m: { x: 150, y: 166, z: 150 },
  pivot: { x: 0, y: 0, z: 0 },
  animation_hooks: { rotor_node: "Rotor" },
};

const ENTRY_PV: AssetRegistryEntry = {
  path: "pv/trina-vertex-n-670w.glb",
  type: "pv_array",
  dims_m: { x: 40, y: 3, z: 20 },
  pivot: { x: 0, y: 0, z: 0 },
  animation_hooks: { irradiance_material: "PVSurface" },
};

const ENTRY_BATTERY: AssetRegistryEntry = {
  path: "batteries/catl-lmp-300mwh.glb",
  type: "battery",
  dims_m: { x: 20, y: 5, z: 60 },
  pivot: { x: 0, y: 0, z: 0 },
  animation_hooks: { soc_fill_mesh: "SOCFillMesh" },
};

const ENTRY_PCC: AssetRegistryEntry = {
  path: "grid/pcc-substation-945mw.glb",
  type: "grid_pcc",
  dims_m: { x: 50, y: 15, z: 30 },
  pivot: { x: 0, y: 0, z: 0 },
};

/** LOCKED registry v1.0.1 fixture (Gansu parity entries). */
const GANSU_REGISTRY: AssetRegistry = {
  schema_version: "1.0.1",
  assets: {
    "vestas-v150-4.2": ENTRY_TURBINE,
    "trina-vertex-n-670w": ENTRY_PV,
    "catl-lmp-300mwh": ENTRY_BATTERY,
    "pcc-substation-945mw": ENTRY_PCC,
  },
};

/** Minimal Gansu site config: 2 turbines (same assetId), 1 PV, 1 battery, 1 PCC. */
const GANSU_CONFIG: SiteSceneConfig = {
  site_id: "gansu",
  wind_capacity_mw: 615,
  solar_capacity_mw: 100,
  turbines: [
    {
      id: "t1", assetId: "vestas-v150-4.2",
      position_m: [0, 0, 0], rotation_rad: [0, 0, 0], capacity_mw: 4.2,
    },
    {
      id: "t2", assetId: "vestas-v150-4.2",
      position_m: [300, 0, 0], rotation_rad: [0, 0, 0], capacity_mw: 4.2,
    },
  ],
  pv_arrays: [
    {
      id: "pv1", assetId: "trina-vertex-n-670w",
      position_m: [500, 0, 0], rotation_rad: [0, 0, 0], capacity_mw: 100,
    },
  ],
  battery: {
    id: "bat1", assetId: "catl-lmp-300mwh",
    position_m: [0, 0, 200], rotation_rad: [0, 0, 0],
    capacity_mwh: 300, max_charge_mw: 150, max_discharge_mw: 150,
  },
  grid: {
    pcc: { assetId: "pcc-substation-945mw", position_m: [0, 0, 400] },
    pylons: [],
  },
  terrain: { assetId: "site-terrain" },
};

/** ZERO_FLOWS: all flow fields at 0. */
const ZERO_FLOWS = {
  solar_to_load_mw: 0, solar_to_bat_mw: 0, solar_to_grid_mw: 0,
  wind_to_load_mw: 0, wind_to_bat_mw: 0, wind_to_grid_mw: 0,
  bat_to_load_mw: 0, bat_to_grid_mw: 0,
  grid_to_load_mw: 0, grid_to_bat_mw: 0,
  solar_curtailed_mw: 0, wind_curtailed_mw: 0,
  bat_curtailed_mw: 0, load_unserved_mw: 0,
};

/** Full valid EnvStepPayload — override per test. */
const BASE_ENV_STEP: EnvStepPayload = {
  step: 1, episode: 1, dt_hours: 1.0,
  sim_time_utc: "2026-03-02T12:00:00Z",
  hour_of_day: 12, minute_of_hour: 0,
  wind_speed_mps: 6.4, irradiance_wm2: 540.0,
  temperature_c: 18.2, load_mw: 72.5,
  price_buy_yuan_per_mwh: 620.0, price_sell_yuan_per_mwh: 590.0,
  tariff_tier: "peak",
  battery: {
    soc: 0.55, p_charge_mw: 0.0, p_discharge_mw: 40.0,
    p_max_charge_mw: 98.16, p_max_discharge_mw: 98.16,
    soc_violation_mwh: 0.0, capacity_mwh: 294.5,
  },
  generation: { gross_solar_mw: 30.0, gross_wind_mw: 92.5 },
  flows: { ...ZERO_FLOWS },
  pcc: { export_mw: 0, import_mw: 0, max_export_mw: 945, max_import_mw: 400 },
  costs: {
    c_energy_yuan: 0, c_import_yuan: 0, r_export_yuan: 0,
    c_demand_charge_yuan: 0, c_demand_shape_yuan: 0,
    c_degradation_yuan: 0, c_curtail_yuan: 0, c_voll_yuan: 0,
    penalty_yuan: 0, cost_total_real_yuan: 0, cost_total_reward_basis_yuan: 0,
  },
  cost_cum: {
    c_energy_yuan_cum: 0, c_demand_charge_yuan_cum: 0,
    c_degradation_yuan_cum: 0, c_curtail_yuan_cum: 0, c_voll_yuan_cum: 0,
  },
  month_peak_mw: 0, reward: 0,
} as unknown as EnvStepPayload;

function makeEnvStep(overrides: {
  wind_speed_mps?: number;
  irradiance_wm2?: number;
  battery?: Partial<typeof BASE_ENV_STEP.battery>;
}): EnvStepPayload {
  return {
    ...BASE_ENV_STEP,
    ...overrides,
    battery: { ...BASE_ENV_STEP.battery, ...(overrides.battery ?? {}) },
  } as unknown as EnvStepPayload;
}

// ─── beforeEach ───────────────────────────────────────────────────────────────

beforeEach(() => {
  _mockEnvStep = null;
  _mockWsStatus = "connecting";
  mockR3fRender.mockClear();
  mockR3fUnmount.mockClear();
  mockCreateRoot.mockClear();
  mockUseGLTF.mockClear();
});

// =============================================================================
// §1 — glbUrl utility (pure function, no hooks, no rendering)
// =============================================================================

describe("glbUrl()", () => {
  it("returns correct URL for vestas-v150-4.2", () => {
    // Arithmetic: entry.path = "turbines/vestas-v150-4.2.glb"
    //   → "/assets/3d/turbines/vestas-v150-4.2.glb"
    expect(glbUrl(GANSU_REGISTRY, "vestas-v150-4.2"))
      .toBe("/assets/3d/turbines/vestas-v150-4.2.glb");
  });

  it("returns correct URL for trina-vertex-n-670w", () => {
    expect(glbUrl(GANSU_REGISTRY, "trina-vertex-n-670w"))
      .toBe("/assets/3d/pv/trina-vertex-n-670w.glb");
  });

  it("returns correct URL for catl-lmp-300mwh", () => {
    expect(glbUrl(GANSU_REGISTRY, "catl-lmp-300mwh"))
      .toBe("/assets/3d/batteries/catl-lmp-300mwh.glb");
  });

  it("returns correct URL for pcc-substation-945mw", () => {
    expect(glbUrl(GANSU_REGISTRY, "pcc-substation-945mw"))
      .toBe("/assets/3d/grid/pcc-substation-945mw.glb");
  });

  it("returns null for unknown assetId", () => {
    // Unknown IDs must NOT produce a URL — the scene renders nothing, no error.
    expect(glbUrl(GANSU_REGISTRY, "does-not-exist")).toBeNull();
    expect(glbUrl(GANSU_REGISTRY, "")).toBeNull();
  });

  it("URL always begins with /assets/3d/ (no hardcoded path fragments)", () => {
    for (const id of Object.keys(GANSU_REGISTRY.assets)) {
      const url = glbUrl(GANSU_REGISTRY, id);
      expect(url).not.toBeNull();
      expect(url!.startsWith("/assets/3d/")).toBe(true);
    }
  });

  it("URL path suffix exactly matches registry entry.path", () => {
    // The URL is a verbatim join — no normalisation, no path traversal.
    const url = glbUrl(GANSU_REGISTRY, "vestas-v150-4.2");
    expect(url).toBe(`/assets/3d/${ENTRY_TURBINE.path}`);
  });

  // reviewer: extra registry entries added at runtime are also resolvable
  it("resolves entries added after initial registry construction", () => {
    const extended: AssetRegistry = {
      ...GANSU_REGISTRY,
      assets: {
        ...GANSU_REGISTRY.assets,
        "custom-tower-1mw": {
          path: "turbines/custom-tower-1mw.glb",
          type: "turbine",
          dims_m: { x: 30, y: 80, z: 30 },
          pivot: { x: 0, y: 0, z: 0 },
        },
      },
    };
    expect(glbUrl(extended, "custom-tower-1mw"))
      .toBe("/assets/3d/turbines/custom-tower-1mw.glb");
  });
});

// =============================================================================
// §2 — SceneContent module: existence and interface
// =============================================================================

describe("SceneContent module", () => {
  it("exports SceneContent as a function (component)", () => {
    expect(typeof SceneContent).toBe("function");
  });

  it("exports glbUrl as a function (utility)", () => {
    expect(typeof glbUrl).toBe("function");
  });

  it("SceneContent renders without throwing when telemetry is null", () => {
    _mockEnvStep = null;
    expect(() =>
      render(<SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />)
    ).not.toThrow();
  });

  it("SceneContent renders without throwing with valid telemetry", () => {
    _mockEnvStep = makeEnvStep({ wind_speed_mps: 12, irradiance_wm2: 500 });
    expect(() =>
      render(<SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />)
    ).not.toThrow();
  });

  it("SceneContent renders without throwing when an assetId is not in registry", () => {
    // reviewer: unknown-asset must not crash — renders nothing for that instance
    const config: SiteSceneConfig = {
      ...GANSU_CONFIG,
      turbines: [
        { id: "t-unknown", assetId: "no-such-glb",
          position_m: [0, 0, 0], rotation_rad: [0, 0, 0], capacity_mw: 1 },
      ],
    };
    expect(() =>
      render(<SceneContent config={config} registry={GANSU_REGISTRY} />)
    ).not.toThrow();
  });
});

// =============================================================================
// §3 — SiteScene wiring: r3fRoot.render(<SceneContent .../>)
// =============================================================================

describe("SiteScene → r3fRoot.render(<SceneContent …/>)", () => {
  /** Helper: mount SiteScene with a real div, await the async createRoot IIFE. */
  async function mountWithContainer(cfg = GANSU_CONFIG, reg = GANSU_REGISTRY) {
    const div = document.createElement("div");
    document.body.appendChild(div);
    await act(async () => {
      render(<SiteScene config={cfg} registry={reg} containerEl={div} />);
      // Flush the async (async () => { await import("@react-three/fiber"); ... })()
      await Promise.resolve();
    });
    return div;
  }

  it("calls r3fRoot.render() after createRoot — not just createRoot(canvas)", async () => {
    // RED until SiteScene.tsx is modified to call r3fRoot.render(...)
    await mountWithContainer();
    expect(mockR3fRender).toHaveBeenCalled();
  });

  it("passes a SceneContent React element to r3fRoot.render()", async () => {
    await mountWithContainer();
    expect(mockR3fRender).toHaveBeenCalled();
    const rendered = mockR3fRender.mock.calls[0][0] as React.ReactElement;
    expect(rendered.type).toBe(SceneContent);
  });

  it("render element has config prop matching SiteScene's config prop", async () => {
    await mountWithContainer();
    const rendered = mockR3fRender.mock.calls[0][0] as React.ReactElement<{
      config: SiteSceneConfig;
    }>;
    expect(rendered.props.config).toBe(GANSU_CONFIG);
  });

  it("render element has registry prop matching SiteScene's registry prop", async () => {
    await mountWithContainer();
    const rendered = mockR3fRender.mock.calls[0][0] as React.ReactElement<{
      registry: AssetRegistry;
    }>;
    expect(rendered.props.registry).toBe(GANSU_REGISTRY);
  });

  it("calls r3fRoot.render() again when config changes (Effect 2)", async () => {
    const div = document.createElement("div");
    document.body.appendChild(div);
    let rerender!: (ui: React.ReactElement) => void;
    await act(async () => {
      const result = render(
        <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
      );
      rerender = result.rerender;
      await Promise.resolve();
    });

    const callsBefore = mockR3fRender.mock.calls.length;

    const newConfig: SiteSceneConfig = {
      ...GANSU_CONFIG,
      site_id: "gansu-updated",
    };
    await act(async () => {
      rerender(
        <SiteScene config={newConfig} registry={GANSU_REGISTRY} containerEl={div} />
      );
    });

    // r3fRoot.render() must have been called at least once more with the new config
    expect(mockR3fRender.mock.calls.length).toBeGreaterThan(callsBefore);
    const latestCall = mockR3fRender.mock.calls[mockR3fRender.mock.calls.length - 1];
    const latestEl = latestCall[0] as React.ReactElement<{ config: SiteSceneConfig }>;
    expect(latestEl.props.config.site_id).toBe("gansu-updated");
  });

  it("calls r3fRoot.unmount() on component unmount (cleanup preserved from PR #7)", async () => {
    const div = document.createElement("div");
    document.body.appendChild(div);
    let unmountRTL!: () => void;
    await act(async () => {
      const result = render(
        <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
      );
      unmountRTL = result.unmount;
      await Promise.resolve();
    });
    await act(async () => { unmountRTL(); });
    expect(mockR3fUnmount).toHaveBeenCalled();
  });

  it("does NOT call render when containerEl is null (no canvas created)", async () => {
    await act(async () => {
      render(
        <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={null} />
      );
      await Promise.resolve();
    });
    expect(mockR3fRender).not.toHaveBeenCalled();
  });
});

// =============================================================================
// §4 — SceneContent scene structure: lights
// =============================================================================

describe("SceneContent scene structure — lights", () => {
  it("renders an ambientLight element with intensity=0.5", () => {
    const { container } = render(
      <SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />
    );
    // In JSDOM, <ambientLight intensity={0.5} /> renders as an unknown DOM element.
    // React uses the lowercase tag name for HTML rendering.
    const el = container.querySelector("ambientlight");
    expect(el).not.toBeNull();
    // intensity is passed as a prop; React serialises numeric props as strings on DOM elements
    expect(el!.getAttribute("intensity")).toBe("0.5");
  });

  it("renders a directionalLight element with intensity=1.0", () => {
    const { container } = render(
      <SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />
    );
    const el = container.querySelector("directionallight");
    expect(el).not.toBeNull();
    expect(el!.getAttribute("intensity")).toBe("1");
  });

  // reviewer: directionalLight must have castShadow=false (no shadow pass in v1)
  it("directionalLight has castShadow set to false", () => {
    const { container } = render(
      <SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />
    );
    const el = container.querySelector("directionallight");
    expect(el).not.toBeNull();
    // castShadow={false} serialises as "false" or the attribute is absent (React omits falsy bool attrs)
    const val = el!.getAttribute("castshadow");
    expect(val === null || val === "false").toBe(true);
  });
});

// =============================================================================
// §5 — SceneContent useGLTF caching: one call per unique assetId
// =============================================================================

describe("SceneContent — useGLTF called once per unique assetId", () => {
  it("GANSU_CONFIG with 2 turbines (same assetId) → useGLTF called once for that assetId", () => {
    render(<SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />);
    const turbineUrl = "/assets/3d/turbines/vestas-v150-4.2.glb";
    const turbineCalls = mockUseGLTF.mock.calls.filter(
      (c) => c[0] === turbineUrl
    );
    // 2 turbines sharing the same assetId → exactly 1 useGLTF call for the turbine GLB
    expect(turbineCalls.length).toBe(1);
  });

  it("calls useGLTF for the PV array assetId", () => {
    render(<SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />);
    expect(mockUseGLTF).toHaveBeenCalledWith(
      "/assets/3d/pv/trina-vertex-n-670w.glb"
    );
  });

  it("calls useGLTF for the battery assetId", () => {
    render(<SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />);
    expect(mockUseGLTF).toHaveBeenCalledWith(
      "/assets/3d/batteries/catl-lmp-300mwh.glb"
    );
  });

  it("calls useGLTF for the PCC assetId", () => {
    render(<SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />);
    expect(mockUseGLTF).toHaveBeenCalledWith(
      "/assets/3d/grid/pcc-substation-945mw.glb"
    );
  });

  it("does NOT call useGLTF for an unknown assetId", () => {
    const config: SiteSceneConfig = {
      ...GANSU_CONFIG,
      turbines: [
        {
          id: "t-unknown", assetId: "no-such-glb",
          position_m: [0, 0, 0], rotation_rad: [0, 0, 0], capacity_mw: 1,
        },
      ],
    };
    render(<SceneContent config={config} registry={GANSU_REGISTRY} />);
    // The unknown assetId resolves to null → glbUrl returns null → useGLTF not called
    const allUrls = mockUseGLTF.mock.calls.map((c) => c[0] as string);
    expect(allUrls.every((url) => url.startsWith("/assets/3d/"))).toBe(true);
    // No call with null or the unknown id string
    expect(allUrls).not.toContain(null);
    expect(allUrls).not.toContain("no-such-glb");
  });

  // reviewer: only the 4 distinct assetIds from GANSU_CONFIG are loaded (no duplicates)
  it("total useGLTF call count equals the number of distinct assetIds in GANSU_CONFIG", () => {
    const uniqueIds = new Set([
      ...GANSU_CONFIG.turbines.map((t) => t.assetId),
      ...GANSU_CONFIG.pv_arrays.map((pv) => pv.assetId),
      GANSU_CONFIG.battery.assetId,
      GANSU_CONFIG.grid.pcc.assetId,
    ]);
    // GANSU_CONFIG: 2 turbines share vestas-v150-4.2 → 4 unique IDs total
    expect(uniqueIds.size).toBe(4);
    render(<SceneContent config={GANSU_CONFIG} registry={GANSU_REGISTRY} />);
    expect(mockUseGLTF).toHaveBeenCalledTimes(4);
  });
});

// =============================================================================
// §6 — SceneContent animation drivers: null telemetry freezes at 0
// =============================================================================

describe("SceneContent — null telemetry → animation frozen at 0", () => {
  it("rotor omega is 0 when displayStep is null (no telemetry)", () => {
    // The animation driver calcRotorOmega(0, 3, 12, 25, 0.2) = 0 (below cut-in 3 m/s)
    // but SceneContent must ALSO freeze when telemetry is absent (null displayStep).
    // The data bridge already exposes omega; here we test via the SiteScene bridge
    // to avoid needing to inspect Three.js refs directly.
    _mockEnvStep = null;
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const turbineBridge = sc.querySelector(
      '[data-testid="turbine-instanced-mesh-vestas-v150-4.2"]'
    );
    expect(turbineBridge).not.toBeNull();
    expect(turbineBridge!.getAttribute("data-omega")).toBe("0");
  });

  it("SOC fill is 0 when displayStep is null", () => {
    _mockEnvStep = null;
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const batt = sc.querySelector('[data-testid="battery-soc-fill"]');
    expect(batt).not.toBeNull();
    expect(batt!.getAttribute("data-soc-fill")).toBe("0");
  });

  it("PV emissive is 0 when displayStep is null", () => {
    _mockEnvStep = null;
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const pv = sc.querySelector('[data-testid="pv-array-pv1"]');
    expect(pv).not.toBeNull();
    expect(pv!.getAttribute("data-emissive")).toBe("0");
  });
});

// =============================================================================
// §7 — Animation driver golden values (contract §2.8 arithmetic)
// =============================================================================

describe("Animation driver golden values (via SiteScene data bridge)", () => {
  // These exercise the SAME calcRotorOmega / calcSocFill / calcEmissive that
  // SceneContent uses, visible via the existing data bridge (PR #7).

  it("wind_speed_mps=3 → rotorOmega=0 (at cut-in, ramp = 0)", () => {
    // calcRotorOmega(3, 3, 12, 25, 0.2): v == cutIn → omega = 0.2*(3-3)/(12-3) = 0
    _mockEnvStep = makeEnvStep({ wind_speed_mps: 3 });
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const el = sc.querySelector('[data-testid="turbine-instanced-mesh-vestas-v150-4.2"]');
    expect(Number(el!.getAttribute("data-omega"))).toBeCloseTo(0, 6);
  });

  it("wind_speed_mps=7.5 → rotorOmega=0.1 (mid-ramp)", () => {
    // calcRotorOmega(7.5, 3, 12, 25, 0.2): ramp = 0.2*(7.5-3)/(12-3) = 0.2*4.5/9 = 0.1
    _mockEnvStep = makeEnvStep({ wind_speed_mps: 7.5 });
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const el = sc.querySelector('[data-testid="turbine-instanced-mesh-vestas-v150-4.2"]');
    expect(Number(el!.getAttribute("data-omega"))).toBeCloseTo(0.1, 6);
  });

  it("wind_speed_mps=12 → rotorOmega=0.2 (rated, plateau)", () => {
    // calcRotorOmega(12, 3, 12, 25, 0.2): v >= rated → omegaMax = 0.2
    _mockEnvStep = makeEnvStep({ wind_speed_mps: 12 });
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const el = sc.querySelector('[data-testid="turbine-instanced-mesh-vestas-v150-4.2"]');
    expect(Number(el!.getAttribute("data-omega"))).toBeCloseTo(0.2, 6);
  });

  it("wind_speed_mps=25 → rotorOmega=0 (at cut-out, turbine off)", () => {
    // calcRotorOmega(25, 3, 12, 25, 0.2): v >= cutOut → 0
    _mockEnvStep = makeEnvStep({ wind_speed_mps: 25 });
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const el = sc.querySelector('[data-testid="turbine-instanced-mesh-vestas-v150-4.2"]');
    expect(Number(el!.getAttribute("data-omega"))).toBeCloseTo(0, 6);
  });

  it("irradiance_wm2=500 → pvEmissive=0.5", () => {
    // calcEmissive(500): clamp(500/1000, 0, 1) = 0.5
    _mockEnvStep = makeEnvStep({ irradiance_wm2: 500 });
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const pv = sc.querySelector('[data-testid="pv-array-pv1"]');
    expect(Number(pv!.getAttribute("data-emissive"))).toBeCloseTo(0.5, 6);
  });

  it("irradiance_wm2=1500 → pvEmissive=1.0 (clamped)", () => {
    // calcEmissive(1500): clamp(1500/1000, 0, 1) = 1.0
    _mockEnvStep = makeEnvStep({ irradiance_wm2: 1500 });
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const pv = sc.querySelector('[data-testid="pv-array-pv1"]');
    expect(Number(pv!.getAttribute("data-emissive"))).toBeCloseTo(1.0, 6);
  });

  it("battery.soc=0.55 → socFill=0.5 (D4 bounds 0.2–0.9)", () => {
    // calcSocFill(0.55, 0.2, 0.9): (0.55-0.2)/(0.9-0.2) = 0.35/0.70 = 0.5
    _mockEnvStep = makeEnvStep({ battery: { soc: 0.55 } });
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const batt = sc.querySelector('[data-testid="battery-soc-fill"]');
    expect(Number(batt!.getAttribute("data-soc-fill"))).toBeCloseTo(0.5, 6);
  });

  it("battery.soc=0.2 → socFill=0.0 (lower bound D4)", () => {
    // calcSocFill(0.2, 0.2, 0.9): (0.2-0.2)/(0.9-0.2) = 0
    _mockEnvStep = makeEnvStep({ battery: { soc: 0.2 } });
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const batt = sc.querySelector('[data-testid="battery-soc-fill"]');
    expect(Number(batt!.getAttribute("data-soc-fill"))).toBeCloseTo(0.0, 6);
  });

  it("battery.soc=0.9 → socFill=1.0 (upper bound D4)", () => {
    // calcSocFill(0.9, 0.2, 0.9): (0.9-0.2)/(0.9-0.2) = 0.7/0.7 = 1.0
    _mockEnvStep = makeEnvStep({ battery: { soc: 0.9 } });
    const div = document.createElement("div");
    const { container: sc } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    const batt = sc.querySelector('[data-testid="battery-soc-fill"]');
    expect(Number(batt!.getAttribute("data-soc-fill"))).toBeCloseTo(1.0, 6);
  });

  // reviewer: NaN telemetry must freeze (isPayloadFinite guard), not flash 0 → NaN → 0
  it("NaN in telemetry → animation values freeze at last valid step (not NaN)", () => {
    // Step 1: valid telemetry → omega = 0.2 (wind=12, rated)
    _mockEnvStep = makeEnvStep({ wind_speed_mps: 12 });
    const div = document.createElement("div");
    const { container: sc, rerender } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );

    // Step 2: corrupt telemetry (NaN wind speed)
    _mockEnvStep = makeEnvStep({ wind_speed_mps: NaN });
    rerender(<SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />);

    // Omega must still be 0.2 (frozen at last valid), not NaN
    const el = sc.querySelector('[data-testid="turbine-instanced-mesh-vestas-v150-4.2"]');
    const omega = Number(el!.getAttribute("data-omega"));
    expect(Number.isFinite(omega)).toBe(true);
    expect(omega).toBeCloseTo(0.2, 6);
  });

  // reviewer (frontend-reviewer): the NaN/Inf freeze must be TRANSIENT, not sticky — after a
  // bad-telemetry gap, a subsequent valid step must RESUME animation at the new value (the
  // last-valid ref updates on recovery). Mirrors the non-sticky-gap semantics on other consumers;
  // a "latched freeze" would leave the scene stuck on the pre-gap value forever.
  it("telemetry recovers after a NaN gap → animation resumes at the new valid value (freeze is transient)", () => {
    // Step 1: valid (wind=12 → omega 0.2)
    _mockEnvStep = makeEnvStep({ wind_speed_mps: 12 });
    const div = document.createElement("div");
    const { container: sc, rerender } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );
    // Step 2: NaN gap → frozen at 0.2
    _mockEnvStep = makeEnvStep({ wind_speed_mps: NaN });
    rerender(<SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />);
    // Step 3: telemetry recovers with a DIFFERENT valid value (wind=7.5 → omega 0.1)
    _mockEnvStep = makeEnvStep({ wind_speed_mps: 7.5 });
    rerender(<SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />);

    const el = sc.querySelector('[data-testid="turbine-instanced-mesh-vestas-v150-4.2"]');
    const omega = Number(el!.getAttribute("data-omega"));
    expect(Number.isFinite(omega)).toBe(true);
    // Resumed at the post-gap value (0.1), NOT stuck on the pre-gap 0.2.
    expect(omega).toBeCloseTo(0.1, 6);
  });

  // reviewer: Inf irradiance must also be guarded (isPayloadFinite)
  it("Inf in irradiance → emissive freezes at last valid value", () => {
    _mockEnvStep = makeEnvStep({ irradiance_wm2: 500 }); // initial: 0.5
    const div = document.createElement("div");
    const { container: sc, rerender } = render(
      <SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />
    );

    _mockEnvStep = makeEnvStep({ irradiance_wm2: Infinity });
    rerender(<SiteScene config={GANSU_CONFIG} registry={GANSU_REGISTRY} containerEl={div} />);

    const pv = sc.querySelector('[data-testid="pv-array-pv1"]');
    const emissive = Number(pv!.getAttribute("data-emissive"));
    expect(Number.isFinite(emissive)).toBe(true);
    expect(emissive).toBeCloseTo(0.5, 6);
  });
});

// =============================================================================
// §8 — Golden telemetry message validation (LOCKED telemetry schema, PR #6)
// =============================================================================

describe("Telemetry schema golden example", () => {
  it("BASE_ENV_STEP passes isPayloadFinite (all numeric fields finite)", async () => {
    // Import the extracted utility — RED until src/scene/isPayloadFinite.ts is created.
    const { isPayloadFinite } = await import("../../src/scene/isPayloadFinite");
    expect(isPayloadFinite(BASE_ENV_STEP)).toBe(true);
  });

  it("step with NaN wind speed fails isPayloadFinite", async () => {
    const { isPayloadFinite } = await import("../../src/scene/isPayloadFinite");
    const bad = makeEnvStep({ wind_speed_mps: NaN });
    expect(isPayloadFinite(bad)).toBe(false);
  });

  it("step with Infinity in a flow field fails isPayloadFinite", async () => {
    const { isPayloadFinite } = await import("../../src/scene/isPayloadFinite");
    const bad: EnvStepPayload = {
      ...BASE_ENV_STEP,
      flows: { ...ZERO_FLOWS, wind_to_grid_mw: Infinity },
    } as unknown as EnvStepPayload;
    expect(isPayloadFinite(bad)).toBe(false);
  });
});
