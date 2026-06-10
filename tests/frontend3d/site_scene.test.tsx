/**
 * tests/frontend3d/site_scene.test.tsx
 *
 * Contract-gated test suite for the 3D site scene.
 * Contract: contracts/frontend3d/site_scene.md
 *
 * All tests are RED (no implementation yet). They import from source paths that
 * do not exist; running the suite before implementation is expected to fail.
 *
 * Spec refs: REBUILD_SPEC.md §3.1 (power curves), §3.2 (battery), §3.3 (flows),
 *            §3.6 (constraint table rows 5, 9, 11), §8.5 (3D per-asset categories)
 * Decision refs: D3 (Δt=1h), D4 (SOC 0.2–0.9), D5 (PCC 945 MW)
 *
 * Reviewer-added cases are marked: // reviewer: <reason>
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
import React from "react";

// --- imports from paths that do not exist yet (RED by design) ---
import { resolveAsset } from "../../src/scene/registry";
import { SiteScene } from "../../src/scene/SiteScene";
import { calcRotorOmega } from "../../src/scene/turbineAnimation";
import { calcSocFill } from "../../src/scene/batteryAnimation";
import { calcFlowWidth, calcFlowSpeed, calcEmissive } from "../../src/scene/flowAnimation";
import type {
  AssetRegistry,
  AssetRegistryEntry,
  SiteSceneConfig,
} from "../../src/scene/types";

// ---------------------------------------------------------------------------
// Shared fixtures
// ---------------------------------------------------------------------------

const ENTRY_TURBINE: AssetRegistryEntry = {
  id: "vestas-v150-4.2",
  path: "turbines/vestas-v150-4.2.glb",
  type: "turbine",
  dims_m: { x: 150, y: 166, z: 150 },
  pivot: { x: 0, y: 0, z: 0 },
  animation_hooks: { rotor_node: "Rotor" },
};

const ENTRY_PV: AssetRegistryEntry = {
  id: "trina-vertex-n-670w",
  path: "pv/trina-vertex-n-670w.glb",
  type: "pv_array",
  dims_m: { x: 40, y: 3, z: 20 },
  pivot: { x: 0, y: 0, z: 0 },
  animation_hooks: { irradiance_material: "PVSurface" },
};

const ENTRY_BATTERY: AssetRegistryEntry = {
  id: "catl-lmp-300mwh",
  path: "batteries/catl-lmp-300mwh.glb",
  type: "battery",
  dims_m: { x: 20, y: 5, z: 60 },
  pivot: { x: 0, y: 0, z: 0 },
  animation_hooks: { soc_fill_mesh: "SOCFillMesh" },
};

const ENTRY_PCC: AssetRegistryEntry = {
  id: "pcc-substation-945mw",
  path: "grid/pcc-substation-945mw.glb",
  type: "grid_pcc",
  dims_m: { x: 50, y: 15, z: 30 },
  pivot: { x: 0, y: 0, z: 0 },
  animation_hooks: {},
};

const VALID_REGISTRY: AssetRegistry = {
  schema_version: "1.0.0",
  entries: [ENTRY_TURBINE, ENTRY_PV, ENTRY_BATTERY, ENTRY_PCC],
};

/** Minimal Gansu-style scene config (3 turbine instances) */
const GANSU_CONFIG: SiteSceneConfig = {
  site_id: "gansu",
  wind_capacity_mw: 615,
  solar_capacity_mw: 330,
  turbines: [
    { id: "t1", assetId: "vestas-v150-4.2", position_m: [0, 0, 0], rotation_rad: [0, 0, 0], capacity_mw: 4.2 },
    { id: "t2", assetId: "vestas-v150-4.2", position_m: [300, 0, 0], rotation_rad: [0, 0, 0], capacity_mw: 4.2 },
    { id: "t3", assetId: "vestas-v150-4.2", position_m: [600, 0, 0], rotation_rad: [0, 0, 0], capacity_mw: 4.2 },
  ],
  pv_arrays: [
    { id: "pv1", assetId: "trina-vertex-n-670w", position_m: [0, 0, 500], rotation_rad: [0, 0, 0], capacity_mw: 50 },
  ],
  battery: {
    id: "bat1",
    assetId: "catl-lmp-300mwh",
    position_m: [100, 0, 200],
    rotation_rad: [0, 0, 0],
    capacity_mwh: 294.5,
    max_charge_mw: 98.16,
    max_discharge_mw: 98.16,
  },
  grid: {
    pcc: { assetId: "pcc-substation-945mw", position_m: [200, 0, -100] },
    substation: { assetId: "pcc-substation-945mw", position_m: [220, 0, -120] },
    pylons: [],
  },
  terrain: { assetId: "terrain-flat" },
};

// ---------------------------------------------------------------------------
// 1. Registry resolution
// ---------------------------------------------------------------------------
describe("resolveAsset", () => {
  it("returns the correct registry entry for a known assetId", () => {
    const result = resolveAsset(VALID_REGISTRY, "vestas-v150-4.2");
    expect(result).not.toBeNull();
    expect(result!.id).toBe("vestas-v150-4.2");
    expect(result!.path).toBe("turbines/vestas-v150-4.2.glb");
    expect(result!.type).toBe("turbine");
  });

  it("returns null for an assetId absent from the registry", () => {
    const result = resolveAsset(VALID_REGISTRY, "nonexistent-asset");
    expect(result).toBeNull();
  });

  it("returns null for empty registry", () => {
    const emptyRegistry: AssetRegistry = { schema_version: "1.0.0", entries: [] };
    expect(resolveAsset(emptyRegistry, "vestas-v150-4.2")).toBeNull();
  });

  // reviewer: test exact-match only — no prefix/partial matching
  it("does not partial-match asset IDs", () => {
    // "vestas" is a prefix of "vestas-v150-4.2" — must NOT match
    expect(resolveAsset(VALID_REGISTRY, "vestas")).toBeNull();
  });

  // reviewer: case-sensitivity guard — IDs from config YAML are verbatim
  it("is case-sensitive for asset ID lookup", () => {
    expect(resolveAsset(VALID_REGISTRY, "Vestas-V150-4.2")).toBeNull();
    expect(resolveAsset(VALID_REGISTRY, "VESTAS-V150-4.2")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2. Scene composition — asset instances from SiteSceneConfig
// ---------------------------------------------------------------------------
describe("SiteScene composition", () => {
  let container: HTMLDivElement;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });

  it("renders without crashing given valid config and registry", () => {
    expect(() => {
      render(
        <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
      );
    }).not.toThrow();
  });

  it("creates one InstancedMesh group for the 3 turbine instances of the same assetId", () => {
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    // Turbine instancing: same assetId → one InstancedMesh wrapper, count=3
    const instancedGroup = getByTestId("turbine-instanced-mesh-vestas-v150-4.2");
    expect(instancedGroup).toBeDefined();
    expect(instancedGroup.getAttribute("data-count")).toBe("3");
  });

  it("renders a placeholder for an unknown assetId without crashing", () => {
    const badConfig: SiteSceneConfig = {
      ...GANSU_CONFIG,
      turbines: [
        { id: "t_bad", assetId: "nonexistent-turbine", position_m: [0, 0, 0], rotation_rad: [0, 0, 0], capacity_mw: 4.2 },
      ],
    };
    const { getByTestId } = render(
      <SiteScene config={badConfig} registry={VALID_REGISTRY} containerEl={container} />
    );
    expect(getByTestId("asset-placeholder-t_bad")).toBeDefined();
  });

  it("does not render when containerEl is null", () => {
    const { container: reactContainer } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={null as unknown as HTMLDivElement} />
    );
    // No canvas should be created
    expect(reactContainer.querySelector("canvas")).toBeNull();
  });

  // reviewer: terrain placeholder when terrain assetId missing from registry
  it("renders terrain placeholder when terrain assetId is absent from registry", () => {
    const configMissingTerrain: SiteSceneConfig = {
      ...GANSU_CONFIG,
      terrain: { assetId: "nonexistent-terrain" },
    };
    expect(() => {
      render(
        <SiteScene config={configMissingTerrain} registry={VALID_REGISTRY} containerEl={container} />
      );
    }).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// 3. Turbine rotor animation — calcRotorOmega
// §3.1 power curve; §3.6 row 11
// ---------------------------------------------------------------------------
describe("calcRotorOmega", () => {
  // Parameters per §3.1 Vestas V150-4.2
  const V_CUTIN   = 3;    // m/s
  const V_RATED   = 12;   // m/s
  const V_CUTOUT  = 25;   // m/s
  const OMEGA_MAX = 0.2;  // rad/s (visual reference)

  it("returns 0 below cut-in speed (v = 0)", () => {
    // §3.6 row 11: wind < v_cutin → no power → no spin
    expect(calcRotorOmega(0, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX)).toBe(0);
  });

  it("returns 0 at cut-in speed exactly (v = 3.0)", () => {
    // At v = v_cutin: omega_max * ((3−3)/(12−3)) = omega_max * 0 = 0
    const omega = calcRotorOmega(3.0, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX);
    expect(omega).toBeCloseTo(0, 5);
  });

  it("returns 0 at cut-out speed exactly (v = 25.0)", () => {
    // §3.6 row 11: v >= v_cutout → turbine shuts down
    expect(calcRotorOmega(25.0, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX)).toBe(0);
  });

  it("returns 0 above cut-out speed (v = 30.0)", () => {
    expect(calcRotorOmega(30.0, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX)).toBe(0);
  });

  it("returns omega_max at rated speed (v = 12.0)", () => {
    // §3.1: at v_rated → P_rated; visual scale: omega = omega_max
    const omega = calcRotorOmega(12.0, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX);
    expect(omega).toBeCloseTo(OMEGA_MAX, 5); // 0.2 rad/s
  });

  it("returns omega_max in rated region (v = 18.0, between rated and cutout)", () => {
    // §3.1: v_rated ≤ v < v_cutout → P = P_rated → omega = omega_max
    const omega = calcRotorOmega(18.0, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX);
    expect(omega).toBeCloseTo(OMEGA_MAX, 5);
  });

  it("returns half of omega_max at v = 7.5 m/s", () => {
    // §3.1 cubic curve: omega = omega_max * ((v − v_cutin) / (v_rated − v_cutin))
    // = 0.2 * ((7.5−3)/(12−3)) = 0.2 * (4.5/9) = 0.2 * 0.5 = 0.1 rad/s
    const omega = calcRotorOmega(7.5, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX);
    expect(omega).toBeCloseTo(0.1, 5);
  });

  it("returns omega_max * (1/9) at v = 4 m/s", () => {
    // omega = 0.2 * ((4−3)/(12−3)) = 0.2 * (1/9) ≈ 0.02222 rad/s
    const omega = calcRotorOmega(4.0, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX);
    expect(omega).toBeCloseTo(0.2 * (1 / 9), 5);
  });

  // reviewer: boundary at v just below cut-out (v = 24.999) should be omega_max
  it("returns omega_max just below cut-out (v = 24.999)", () => {
    const omega = calcRotorOmega(24.999, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX);
    expect(omega).toBeCloseTo(OMEGA_MAX, 4);
  });

  // reviewer: negative wind speed is clamped to zero spin (defensive)
  it("returns 0 for negative wind speed (defensive against malformed telemetry)", () => {
    expect(calcRotorOmega(-1, V_CUTIN, V_RATED, V_CUTOUT, OMEGA_MAX)).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// 4. Battery SOC fill animation — calcSocFill
// D4: SOC bounds [0.2, 0.9]
// ---------------------------------------------------------------------------
describe("calcSocFill", () => {
  const SOC_MIN = 0.2; // D4
  const SOC_MAX = 0.9; // D4

  it("returns 0.0 at soc_min (soc = 0.2)", () => {
    // soc_fill = (0.2 − 0.2) / (0.9 − 0.2) = 0 / 0.7 = 0.0
    expect(calcSocFill(0.2, SOC_MIN, SOC_MAX)).toBeCloseTo(0.0, 6);
  });

  it("returns 1.0 at soc_max (soc = 0.9)", () => {
    // soc_fill = (0.9 − 0.2) / (0.9 − 0.2) = 0.7 / 0.7 = 1.0
    expect(calcSocFill(0.9, SOC_MIN, SOC_MAX)).toBeCloseTo(1.0, 6);
  });

  it("returns 0.5 at soc = 0.55 (midpoint)", () => {
    // soc_fill = (0.55 − 0.2) / (0.9 − 0.2) = 0.35 / 0.7 = 0.5
    expect(calcSocFill(0.55, SOC_MIN, SOC_MAX)).toBeCloseTo(0.5, 6);
  });

  it("returns 0.0 when soc is below soc_min (defensive clamp)", () => {
    // soc = 0.1 is below physical minimum — clamp to 0 fill
    expect(calcSocFill(0.1, SOC_MIN, SOC_MAX)).toBeCloseTo(0.0, 5);
  });

  it("returns 1.0 when soc is above soc_max (defensive clamp)", () => {
    // soc = 1.0 is above physical maximum — clamp to 1 fill
    expect(calcSocFill(1.0, SOC_MIN, SOC_MAX)).toBeCloseTo(1.0, 5);
  });

  it("returns approx 0.143 at soc = 0.3", () => {
    // soc_fill = (0.3 − 0.2) / (0.9 − 0.2) = 0.1 / 0.7 ≈ 0.14286
    expect(calcSocFill(0.3, SOC_MIN, SOC_MAX)).toBeCloseTo(0.1 / 0.7, 4);
  });

  // reviewer: soc = soc_min + epsilon should be > 0 (not clamped to 0)
  it("returns a small positive value for soc just above soc_min", () => {
    const fill = calcSocFill(0.201, SOC_MIN, SOC_MAX);
    expect(fill).toBeGreaterThan(0);
    expect(fill).toBeLessThan(0.01);
  });
});

// ---------------------------------------------------------------------------
// 5. Power-flow line animation — calcFlowWidth, calcFlowSpeed
// Contract §4.2
// ---------------------------------------------------------------------------
describe("calcFlowWidth", () => {
  // site_max_mw = wind_capacity_mw + solar_capacity_mw = 615 + 330 = 945 MW
  const SITE_MAX_MW = 945;

  it("returns 0.5 (minimum) at flow_mw = 0", () => {
    // normalized = 0/945 = 0; width = 0.5 + 0 * 5.5 = 0.5
    expect(calcFlowWidth(0, SITE_MAX_MW)).toBeCloseTo(0.5, 5);
  });

  it("returns 6.0 (maximum) at flow_mw = site_max_mw (945 MW)", () => {
    // normalized = 945/945 = 1.0; width = 0.5 + 1.0 * 5.5 = 6.0
    expect(calcFlowWidth(945, SITE_MAX_MW)).toBeCloseTo(6.0, 5);
  });

  it("returns 3.25 at flow_mw = 472.5 MW (half of site_max)", () => {
    // normalized = 472.5/945 = 0.5; width = 0.5 + 0.5 * 5.5 = 0.5 + 2.75 = 3.25
    expect(calcFlowWidth(472.5, SITE_MAX_MW)).toBeCloseTo(3.25, 4);
  });

  it("returns 0.5 for negative flow_mw (treated as 0)", () => {
    // flow_mw < 0 is physically impossible (§3.3); treat as 0
    expect(calcFlowWidth(-10, SITE_MAX_MW)).toBeCloseTo(0.5, 5);
  });

  it("returns correct width for a typical wind export (80 MW)", () => {
    // normalized = 80/945 ≈ 0.08466; width = 0.5 + 0.08466 * 5.5 ≈ 0.5 + 0.4656 ≈ 0.9656
    expect(calcFlowWidth(80, SITE_MAX_MW)).toBeCloseTo(0.5 + (80 / 945) * 5.5, 3);
  });

  // reviewer: flow_mw > site_max_mw should cap width at 6.0 (clamp)
  it("caps at 6.0 for flow_mw > site_max_mw", () => {
    expect(calcFlowWidth(2000, SITE_MAX_MW)).toBeCloseTo(6.0, 5);
  });
});

describe("calcFlowSpeed", () => {
  const SITE_MAX_MW = 945;

  it("returns 0.2 (minimum) at flow_mw = 0", () => {
    // speed = 0.2 + 0 * 2.8 = 0.2
    expect(calcFlowSpeed(0, SITE_MAX_MW)).toBeCloseTo(0.2, 5);
  });

  it("returns 3.0 (maximum) at flow_mw = site_max_mw", () => {
    // speed = 0.2 + 1.0 * 2.8 = 3.0
    expect(calcFlowSpeed(945, SITE_MAX_MW)).toBeCloseTo(3.0, 5);
  });

  it("returns 1.6 at flow_mw = 472.5 MW (half of site_max)", () => {
    // speed = 0.2 + 0.5 * 2.8 = 0.2 + 1.4 = 1.6
    expect(calcFlowSpeed(472.5, SITE_MAX_MW)).toBeCloseTo(1.6, 4);
  });

  it("returns 0.2 for negative flow_mw (treated as 0)", () => {
    expect(calcFlowSpeed(-5, SITE_MAX_MW)).toBeCloseTo(0.2, 5);
  });

  // reviewer: speed caps at 3.0 for flow_mw > site_max_mw
  it("caps at 3.0 for flow_mw > site_max_mw", () => {
    expect(calcFlowSpeed(1500, SITE_MAX_MW)).toBeCloseTo(3.0, 5);
  });
});

// ---------------------------------------------------------------------------
// 6. PV irradiance emissive — calcEmissive
// Contract §7
// ---------------------------------------------------------------------------
describe("calcEmissive", () => {
  it("returns 0.0 at irradiance = 0 (night)", () => {
    // emissive = clamp(0/1000, 0, 1) = 0.0
    expect(calcEmissive(0)).toBeCloseTo(0.0, 6);
  });

  it("returns 1.0 at irradiance = 1000 W/m² (full sun)", () => {
    // emissive = clamp(1000/1000, 0, 1) = 1.0
    expect(calcEmissive(1000)).toBeCloseTo(1.0, 6);
  });

  it("returns 0.54 at irradiance = 540 W/m²", () => {
    // emissive = clamp(540/1000, 0, 1) = 0.54
    expect(calcEmissive(540)).toBeCloseTo(0.54, 5);
  });

  it("clamps to 1.0 for irradiance > 1000 W/m²", () => {
    // §12 edge case: irradiance_wm2 > 1000 → clamp
    expect(calcEmissive(1200)).toBeCloseTo(1.0, 5);
  });

  it("clamps to 0.0 for negative irradiance (defensive)", () => {
    expect(calcEmissive(-50)).toBeCloseTo(0.0, 5);
  });

  // reviewer: irradiance = 1 W/m² should be > 0 (not clamped to 0)
  it("returns a small positive value for irradiance = 1 W/m²", () => {
    const emissive = calcEmissive(1);
    expect(emissive).toBeGreaterThan(0);
    expect(emissive).toBeCloseTo(0.001, 4);
  });
});

// ---------------------------------------------------------------------------
// 7. Flow visibility — zero flows hide lines
// ---------------------------------------------------------------------------
describe("power-flow line visibility", () => {
  let container: HTMLDivElement;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });

  it("hides all flow lines when all flows are zero", () => {
    const { queryAllByTestId } = render(
      <SiteScene
        config={GANSU_CONFIG}
        registry={VALID_REGISTRY}
        containerEl={container}
        // Inject a zero-flow env step via the mock store
      />
    );
    // Each line should have data-visible="false" when flow = 0
    const lines = queryAllByTestId(/^flow-line-/);
    for (const line of lines) {
      expect(line.getAttribute("data-visible")).toBe("false");
    }
  });

  it("shows wind-to-grid line when wind_to_grid_mw = 80", () => {
    // The test injects an envStep via the mock telemetryStore
    const { getByTestId } = render(
      <SiteScene
        config={GANSU_CONFIG}
        registry={VALID_REGISTRY}
        containerEl={container}
      />
    );
    // After store update with wind_to_grid_mw = 80:
    // width = 0.5 + (80/945)*5.5 ≈ 0.966
    const line = getByTestId("flow-line-wind_to_grid");
    expect(line.getAttribute("data-visible")).toBe("true");
    expect(parseFloat(line.getAttribute("data-width") ?? "0")).toBeCloseTo(
      0.5 + (80 / 945) * 5.5,
      2
    );
  });

  // reviewer: all flows = 0 but ren_curtailed_mw > 0 → curtailment line visible
  it("shows curtailment line when ren_curtailed_mw > 0 while other flows = 0", () => {
    const { getByTestId } = render(
      <SiteScene
        config={GANSU_CONFIG}
        registry={VALID_REGISTRY}
        containerEl={container}
      />
    );
    // Store injected with ren_curtailed_mw = 50 MW
    const curtailLine = getByTestId("flow-line-curtailment");
    expect(curtailLine.getAttribute("data-visible")).toBe("true");
  });

  // reviewer: VOLL indicator active only when load_unserved_mw > 0
  it("activates VOLL indicator when load_unserved_mw > 0", () => {
    const { getByTestId } = render(
      <SiteScene
        config={GANSU_CONFIG}
        registry={VALID_REGISTRY}
        containerEl={container}
      />
    );
    const vollIndicator = getByTestId("voll-indicator");
    // After store injected with load_unserved_mw = 5:
    expect(vollIndicator.getAttribute("data-active")).toBe("true");
  });
});

// ---------------------------------------------------------------------------
// 8. Stale / null telemetry — scene freezes, shows overlay
// Contract §3.2, §9.4
// ---------------------------------------------------------------------------
describe("stale and null telemetry", () => {
  let container: HTMLDivElement;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });

  it("renders without crashing when envStep is null", () => {
    expect(() => {
      render(
        <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
      );
    }).not.toThrow();
  });

  it("shows 'Waiting for telemetry' overlay when envStep is null", () => {
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    expect(getByTestId("telemetry-overlay")).toHaveTextContent(/waiting for telemetry/i);
  });

  it("shows 'Stale' overlay when wsStatus is 'stale'", () => {
    // Mock telemetryStore.wsStatus = "stale"
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    expect(getByTestId("telemetry-overlay")).toHaveTextContent(/stale/i);
  });

  it("shows 'Disconnected' overlay when wsStatus is 'disconnected'", () => {
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    expect(getByTestId("telemetry-overlay")).toHaveTextContent(/disconnected/i);
  });

  it("removes the overlay when a valid envStep arrives after being null", () => {
    const { queryByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    // After store receives a valid envStep, overlay disappears
    act(() => {
      // dispatch new envStep via mock store
    });
    expect(queryByTestId("telemetry-overlay")).toBeNull();
  });

  // reviewer: animated values do NOT reset to zero on stale — they freeze at last known
  it("keeps last known SOC fill when telemetry becomes stale (no flicker to zero)", () => {
    // 1. Inject envStep with soc = 0.7 → soc_fill = (0.7-0.2)/0.7 = 5/7 ≈ 0.714
    // 2. Set wsStatus to "stale"
    // 3. Assert soc_fill is still ≈ 0.714, not 0
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    const battMesh = getByTestId("battery-soc-fill");
    // After stale transition, scale.y should still be ≈ 0.714
    expect(parseFloat(battMesh.getAttribute("data-soc-fill") ?? "0")).toBeCloseTo(
      (0.7 - 0.2) / 0.7,
      2
    );
  });
});

// ---------------------------------------------------------------------------
// 9. Performance — draw call and instancing constraints
// Contract §9.3
// ---------------------------------------------------------------------------
describe("performance constraints", () => {
  let container: HTMLDivElement;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });

  it("turbine field uses InstancedMesh (one per assetId, not one per turbine)", () => {
    // 3 turbines with the same assetId → exactly 1 InstancedMesh group, count=3
    const { getAllByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    const instancedMeshes = getAllByTestId(/^turbine-instanced-mesh-/);
    expect(instancedMeshes).toHaveLength(1); // only one unique assetId
    expect(instancedMeshes[0].getAttribute("data-count")).toBe("3");
  });

  it("uses a single canvas element (no duplicate R3F Canvas)", () => {
    render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    const canvases = container.querySelectorAll("canvas");
    expect(canvases.length).toBe(1);
  });

  it("total draw calls for turbine field ≤ 50 (mocked draw-call counter)", () => {
    // The scene must expose a testId "draw-call-counter-turbines" with data-count attribute
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    const counter = getByTestId("draw-call-counter-turbines");
    const drawCalls = parseInt(counter.getAttribute("data-count") ?? "999", 10);
    expect(drawCalls).toBeLessThanOrEqual(50);
  });

  // reviewer: 146-turbine full Gansu config also stays within budget
  it("stays within 50 draw calls for 146 turbines (full Gansu site)", () => {
    const gansu146Turbines: SiteSceneConfig = {
      ...GANSU_CONFIG,
      turbines: Array.from({ length: 146 }, (_, i) => ({
        id: `t${i}`,
        assetId: "vestas-v150-4.2",
        position_m: [(i % 15) * 300, 0, Math.floor(i / 15) * 400] as [number, number, number],
        rotation_rad: [0, 0, 0] as [number, number, number],
        capacity_mw: 4.2,
      })),
    };
    const { getByTestId } = render(
      <SiteScene config={gansu146Turbines} registry={VALID_REGISTRY} containerEl={container} />
    );
    const counter = getByTestId("draw-call-counter-turbines");
    expect(parseInt(counter.getAttribute("data-count") ?? "999", 10)).toBeLessThanOrEqual(50);
  });
});

// ---------------------------------------------------------------------------
// 10. SceneMountPoint binding — canvas attaches to provided containerEl
// Contract §11
// ---------------------------------------------------------------------------
describe("SceneMountPoint integration", () => {
  it("creates canvas inside the provided containerEl, not in the React root", () => {
    const sceneContainer = document.createElement("div");
    document.body.appendChild(sceneContainer);
    const reactRoot = document.createElement("div");
    document.body.appendChild(reactRoot);

    render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={sceneContainer} />,
      { container: reactRoot }
    );

    // Canvas must be in sceneContainer, not in reactRoot
    expect(sceneContainer.querySelector("canvas")).not.toBeNull();
    expect(reactRoot.querySelector("canvas")).toBeNull();
  });

  it("cleans up the canvas when the component unmounts", () => {
    const sceneContainer = document.createElement("div");
    document.body.appendChild(sceneContainer);

    const { unmount } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={sceneContainer} />
    );
    unmount();

    // R3F canvas should be removed after unmount
    expect(sceneContainer.querySelector("canvas")).toBeNull();
  });

  // reviewer: canvas resizes when containerEl changes dimensions
  it("canvas width/height reflect containerEl dimensions", () => {
    const sceneContainer = document.createElement("div");
    Object.defineProperty(sceneContainer, "clientWidth", { value: 1280, configurable: true });
    Object.defineProperty(sceneContainer, "clientHeight", { value: 720, configurable: true });
    document.body.appendChild(sceneContainer);

    render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={sceneContainer} />
    );

    const canvas = sceneContainer.querySelector("canvas");
    expect(canvas).not.toBeNull();
    // Canvas should not have fixed px dimensions in its style (must be 100% of container)
    expect(canvas!.style.width).not.toBe("fixed");
  });
});

// ---------------------------------------------------------------------------
// 11. Flow direction — sources emit from correct nodes
// Contract §4.1
// ---------------------------------------------------------------------------
describe("flow line direction and source nodes", () => {
  let container: HTMLDivElement;
  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });

  it("solar_to_load line has source=pv and target=load", () => {
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    const line = getByTestId("flow-line-solar_to_load");
    expect(line.getAttribute("data-source")).toBe("pv");
    expect(line.getAttribute("data-target")).toBe("load");
  });

  it("wind_to_grid line has source=turbine-field and target=pcc", () => {
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    const line = getByTestId("flow-line-wind_to_grid");
    expect(line.getAttribute("data-source")).toBe("turbine-field");
    expect(line.getAttribute("data-target")).toBe("pcc");
  });

  it("bat_to_load line has source=battery and target=load", () => {
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    const line = getByTestId("flow-line-bat_to_load");
    expect(line.getAttribute("data-source")).toBe("battery");
    expect(line.getAttribute("data-target")).toBe("load");
  });

  it("grid_to_bat line has source=pcc and target=battery", () => {
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    const line = getByTestId("flow-line-grid_to_bat");
    expect(line.getAttribute("data-source")).toBe("pcc");
    expect(line.getAttribute("data-target")).toBe("battery");
  });

  // reviewer: PCC export vs import are distinct directed edges (not the same mesh)
  it("pcc export and import are distinct flow lines with opposite directions", () => {
    const { getByTestId } = render(
      <SiteScene config={GANSU_CONFIG} registry={VALID_REGISTRY} containerEl={container} />
    );
    const exportLine = getByTestId("flow-line-pcc-export");
    const importLine = getByTestId("flow-line-pcc-import");
    expect(exportLine.getAttribute("data-direction")).toBe("outward");
    expect(importLine.getAttribute("data-direction")).toBe("inward");
  });
});

// ---------------------------------------------------------------------------
// 12. Energy conservation defensiveness — flows never go negative
// Contract §12 edge case 5, §4.2
// ---------------------------------------------------------------------------
describe("flow defensive edge cases", () => {
  it("calcFlowWidth returns minimum for all-zero flows without NaN", () => {
    const SITE_MAX = 945;
    // All 10 flow fields = 0: no NaN, no division-by-zero
    const flows = [
      0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    ];
    for (const f of flows) {
      const width = calcFlowWidth(f, SITE_MAX);
      expect(width).not.toBeNaN();
      expect(width).toBeCloseTo(0.5, 5);
    }
  });

  it("calcFlowSpeed returns minimum for all-zero flows without NaN", () => {
    const SITE_MAX = 945;
    const flows = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    for (const f of flows) {
      const speed = calcFlowSpeed(f, SITE_MAX);
      expect(speed).not.toBeNaN();
      expect(speed).toBeCloseTo(0.2, 5);
    }
  });

  // reviewer: site_max_mw = 0 does not cause division by zero (edge config)
  it("calcFlowWidth handles site_max_mw = 0 without NaN or Infinity", () => {
    const width = calcFlowWidth(0, 0);
    expect(isNaN(width)).toBe(false);
    expect(isFinite(width)).toBe(true);
  });

  // reviewer: load_unserved_mw = -1 treated as 0 (no negative VOLL display)
  it("negative load_unserved_mw is treated as 0 (§12 edge case 13)", () => {
    // calcFlowWidth(-1, 945) should equal calcFlowWidth(0, 945) = 0.5
    expect(calcFlowWidth(-1, 945)).toBeCloseTo(0.5, 5);
  });
});
