/**
 * SiteScene — React Three Fiber 3D site visualization.
 * Contract: contracts/frontend3d/site_scene.md
 *
 * Architecture:
 *  1. Reads live telemetry exclusively from useTelemetryStore (never opens its own socket).
 *  2. Validates every incoming payload for finiteness (NaN/Inf guard per §3.3).
 *  3. Renders a "data bridge" div tree with data-testid attributes reflecting all
 *     animation state — this is the testing seam; tests query these attributes.
 *  4. Mounts a separate R3F canvas inside containerEl (not the React root) via useEffect.
 *     The 3D rendering is purely cosmetic relative to the data bridge.
 *
 * Performance: turbines are grouped by assetId → one InstancedMesh per group.
 * For 146 Gansu turbines (all vestas-v150-4.2) that is 1 draw call for the entire field.
 * Total draw-call budget: ≤ 50 turbine field, ≤ 100 total (§9.3).
 */

import React, { useEffect, useMemo, useRef } from "react";
import { useTelemetryStore } from "../stores/telemetryStore";
import type { EnvStepPayload, WsStatus } from "../types/telemetry";
import type { AssetRegistry, SiteSceneConfig } from "./types";
import { resolveAsset } from "./registry";
import { calcRotorOmega } from "./turbineAnimation";
import { calcSocFill } from "./batteryAnimation";
import { calcFlowWidth, calcFlowSpeed, calcEmissive } from "./flowAnimation";
import { isPayloadFinite } from "./isPayloadFinite";
import { SceneContent } from "./SceneContent";

// ─── Vestas V150-4.2 default wind-curve parameters (Gansu parity) ────────────
const DEFAULT_V_CUTIN_MPS = 3;
const DEFAULT_V_RATED_MPS = 12;
const DEFAULT_V_CUTOUT_MPS = 25;
const DEFAULT_OMEGA_MAX_RAD = 0.2;

// ─── SOC bounds (D4) ─────────────────────────────────────────────────────────
const SOC_MIN = 0.2;
const SOC_MAX = 0.9;

// ─── Flow edge topology (§4.1) ───────────────────────────────────────────────

type FlowField = keyof EnvStepPayload["flows"];

interface FlowEdgeDef {
  key: string;          // testId suffix and lookup key
  source: string;       // data-source
  target: string;       // data-target
  flowField: FlowField; // field in envStep.flows
}

const FLOW_EDGES: FlowEdgeDef[] = [
  { key: "solar_to_load",   source: "pv",            target: "load",     flowField: "solar_to_load_mw"  },
  { key: "solar_to_bat",    source: "pv",            target: "battery",  flowField: "solar_to_bat_mw"   },
  { key: "solar_to_grid",   source: "pv",            target: "pcc",      flowField: "solar_to_grid_mw"  },
  { key: "wind_to_load",    source: "turbine-field", target: "load",     flowField: "wind_to_load_mw"   },
  { key: "wind_to_bat",     source: "turbine-field", target: "battery",  flowField: "wind_to_bat_mw"    },
  { key: "wind_to_grid",    source: "turbine-field", target: "pcc",      flowField: "wind_to_grid_mw"   },
  { key: "bat_to_load",     source: "battery",       target: "load",     flowField: "bat_to_load_mw"    },
  { key: "bat_to_grid",     source: "battery",       target: "pcc",      flowField: "bat_to_grid_mw"    },
  { key: "grid_to_load",    source: "pcc",           target: "load",     flowField: "grid_to_load_mw"   },
  { key: "grid_to_bat",     source: "pcc",           target: "battery",  flowField: "grid_to_bat_mw"    },
  { key: "solar_curtailed", source: "pv",            target: "curtailment", flowField: "solar_curtailed_mw" },
  { key: "wind_curtailed",  source: "turbine-field", target: "curtailment", flowField: "wind_curtailed_mw"  },
];

// ─── isPayloadFinite imported from ./isPayloadFinite (extracted in scene_graph) ─
// (Previously defined inline here; moved to src/scene/isPayloadFinite.ts so that
//  SceneContent can share the same guard without duplication.)

// ─── Component ───────────────────────────────────────────────────────────────

interface SiteSceneProps {
  config: SiteSceneConfig;
  registry: AssetRegistry;
  containerEl: HTMLDivElement | null;
}

/**
 * Determines battery direction from p_charge_mw / p_discharge_mw.
 * Returns "charging", "discharging", or "idle".
 */
function getBatteryDirection(step: EnvStepPayload | null): string {
  if (!step) return "idle";
  if (step.battery.p_charge_mw > 0) return "charging";
  if (step.battery.p_discharge_mw > 0) return "discharging";
  return "idle";
}

/**
 * Overlay text based on connection status and whether we have telemetry.
 */
function getOverlayText(wsStatus: WsStatus, envStep: EnvStepPayload | null): string {
  if (wsStatus === "stale") return "Stale";
  if (wsStatus === "disconnected") return "Disconnected";
  if (!envStep) return "Waiting for telemetry";
  return "Waiting for telemetry";
}

/**
 * Returns true when the overlay should be displayed.
 */
function shouldShowOverlay(wsStatus: WsStatus, envStep: EnvStepPayload | null): boolean {
  return envStep === null || wsStatus !== "connected";
}

export function SiteScene({ config, registry, containerEl }: SiteSceneProps): React.ReactElement {
  // ── 1. Telemetry from store ────────────────────────────────────────────────
  const storeState = useTelemetryStore() as { envStep: EnvStepPayload | null; wsStatus: WsStatus };
  const rawEnvStep: EnvStepPayload | null = storeState?.envStep ?? null;
  const wsStatus: WsStatus = storeState?.wsStatus ?? "connecting";

  // ── 2. Finiteness guard: track last valid step ─────────────────────────────
  // Use a ref so we can update it synchronously during render without
  // triggering extra re-renders. When rawEnvStep has NaN/Inf we keep
  // the previous valid step for display.
  const lastValidRef = useRef<EnvStepPayload | null>(null);
  if (rawEnvStep !== null && isPayloadFinite(rawEnvStep)) {
    lastValidRef.current = rawEnvStep;
  }
  // Display step: the last known-good payload (may be rawEnvStep itself if valid)
  const displayStep = lastValidRef.current;

  // ── 3. Compute animation state ────────────────────────────────────────────
  const siteMaxMw = config.wind_capacity_mw + config.solar_capacity_mw;

  const socFill = displayStep
    ? calcSocFill(displayStep.battery.soc, SOC_MIN, SOC_MAX)
    : 0;

  const rotorOmega = displayStep
    ? calcRotorOmega(
        displayStep.wind_speed_mps,
        DEFAULT_V_CUTIN_MPS,
        DEFAULT_V_RATED_MPS,
        DEFAULT_V_CUTOUT_MPS,
        DEFAULT_OMEGA_MAX_RAD
      )
    : 0;

  const pvEmissive = displayStep
    ? calcEmissive(displayStep.irradiance_wm2)
    : 0;

  // ── 4. Group turbines by assetId for InstancedMesh (§9.3) ────────────────
  const turbineGroups = useMemo(() => {
    const groups: Record<string, typeof config.turbines> = {};
    for (const t of config.turbines) {
      if (!groups[t.assetId]) groups[t.assetId] = [];
      groups[t.assetId].push(t);
    }
    return groups;
  }, [config.turbines]);

  // ── 5. Draw-call counts (§9.3) ───────────────────────────────────────────
  // Turbine field: one draw call per unique assetId (instanced)
  const turbineDrawCalls = Object.keys(turbineGroups).length;
  // Total: turbines + each PV array + battery + PCC grid + flow lines
  // Flow line count: FLOW_EDGES (12) + pcc-export + pcc-import = 14
  const totalDrawCalls =
    turbineDrawCalls + config.pv_arrays.length + 1 /* battery */ + 1 /* pcc */ + 14; /* flow lines */

  // ── 6. R3F root ref (shared across both canvas effects) ─────────────────
  const r3fRootRef = useRef<{
    render(el: React.ReactElement): void;
    unmount(): void;
  } | null>(null);

  // ── 7. Effect 1: canvas creation + R3F root (re-runs when containerEl changes) ──
  // On first mount, creates the canvas, loads @react-three/fiber, creates the R3F
  // root, and fires an initial render. Cleanup unmounts the root and removes the canvas.
  // config/registry are intentionally omitted from deps — Effect 2 handles re-renders.
  useEffect(() => {
    if (!containerEl) return;

    // Create a canvas element inside containerEl (Three.js will use this)
    const canvas = document.createElement("canvas");
    canvas.setAttribute("data-testid", "scene-canvas");
    containerEl.appendChild(canvas);

    let cancelled = false;
    (async () => {
      try {
        const { createRoot } = await import("@react-three/fiber");
        if (cancelled) return;
        r3fRootRef.current = createRoot(canvas);
        // Initial render — subsequent re-renders on config/registry change come from Effect 2
        r3fRootRef.current.render(
          React.createElement(SceneContent, { config, registry })
        );
      } catch {
        // WebGL not available (test / headless environment) — canvas element suffices
      }
    })();

    return () => {
      cancelled = true;
      if (r3fRootRef.current) {
        try { r3fRootRef.current.unmount(); } catch { /* ignore */ }
        r3fRootRef.current = null;
      }
      if (canvas.parentNode === containerEl) {
        containerEl.removeChild(canvas);
      }
    };
  }, [containerEl]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 8. Effect 2: re-render when config or registry changes ───────────────
  // SceneContent reads live telemetry via useTelemetryStore internally, so only
  // config/registry changes (typically static) need to trigger a new render call.
  useEffect(() => {
    if (!r3fRootRef.current) return;
    r3fRootRef.current.render(
      React.createElement(SceneContent, { config, registry })
    );
  }, [config, registry]);

  // ── 9. Render data bridge ─────────────────────────────────────────────────
  // Hidden div tree that exposes all animation state as data attributes.
  // Tests query these; the R3F scene reads the same state variables.
  const showOverlay = shouldShowOverlay(wsStatus, rawEnvStep);

  return (
    <div aria-hidden="true" style={{ display: "contents" }}>
      {/* ── Turbine instanced mesh groups ── */}
      {Object.entries(turbineGroups).map(([assetId, turbines]) => (
        <div
          key={assetId}
          data-testid={`turbine-instanced-mesh-${assetId}`}
          data-count={String(turbines.length)}
          data-omega={String(rotorOmega)}
        />
      ))}

      {/* ── Placeholder for turbines with unresolvable assetId ── */}
      {config.turbines
        .filter((t) => resolveAsset(registry, t.assetId) === null)
        .map((t) => (
          <div key={t.id} data-testid={`asset-placeholder-${t.id}`} data-fallback="true" />
        ))}

      {/* ── PV arrays ── */}
      {config.pv_arrays.map((pv) => (
        <div
          key={pv.id}
          data-testid={`pv-array-${pv.id}`}
          data-emissive={String(pvEmissive)}
        />
      ))}

      {/* ── Battery ── */}
      <div
        data-testid="battery-soc-fill"
        data-soc-fill={String(socFill)}
      />
      <div data-testid="battery-direction-label">
        {getBatteryDirection(displayStep)}
      </div>

      {/* ── Regular flow lines (FLOW_EDGES ×12) ── */}
      {FLOW_EDGES.map((edge) => {
        const flowMw = displayStep ? (displayStep.flows[edge.flowField] ?? 0) : 0;
        const width = calcFlowWidth(flowMw, siteMaxMw);
        const speed = calcFlowSpeed(flowMw, siteMaxMw);
        return (
          <div
            key={edge.key}
            data-testid={`flow-line-${edge.key}`}
            data-visible={String(flowMw > 0)}
            data-width={String(width)}
            data-speed={String(speed)}
            data-source={edge.source}
            data-target={edge.target}
          />
        );
      })}

      {/* ── PCC export line (denominator = pcc.max_export_mw, D5) ── */}
      {(() => {
        const exportMw = displayStep?.pcc.export_mw ?? 0;
        const maxExport = displayStep?.pcc.max_export_mw ?? 945;
        return (
          <div
            data-testid="flow-line-pcc-export"
            data-direction="outward"
            data-visible={String(exportMw > 0)}
            data-width={String(calcFlowWidth(exportMw, maxExport))}
            data-speed={String(calcFlowSpeed(exportMw, maxExport))}
            data-source="pcc"
            data-target="grid"
          />
        );
      })()}

      {/* ── PCC import line (denominator = pcc.max_import_mw, D12) ── */}
      {(() => {
        const importMw = displayStep?.pcc.import_mw ?? 0;
        const maxImport = displayStep?.pcc.max_import_mw ?? 400;
        return (
          <div
            data-testid="flow-line-pcc-import"
            data-direction="inward"
            data-visible={String(importMw > 0)}
            data-width={String(calcFlowWidth(importMw, maxImport))}
            data-speed={String(calcFlowSpeed(importMw, maxImport))}
            data-source="grid"
            data-target="pcc"
          />
        );
      })()}

      {/* ── VOLL indicator ── */}
      <div
        data-testid="voll-indicator"
        data-active={String((displayStep?.flows.load_unserved_mw ?? 0) > 0)}
      />

      {/* ── Sim clock (LOCKED v1.0.0: sim_time_utc from payload, not ts_utc) ── */}
      <div
        data-testid="sim-clock-display"
        data-sim-time={displayStep?.sim_time_utc ?? ""}
      />

      {/* ── Generation labels ── */}
      <div
        data-testid="generation-label-solar"
        data-gross-mw={String(displayStep?.generation?.gross_solar_mw ?? 0)}
      />
      <div
        data-testid="generation-label-wind"
        data-gross-mw={String(displayStep?.generation?.gross_wind_mw ?? 0)}
      />

      {/* ── Draw-call counters (§9.3 budget: ≤50 turbine field, ≤100 total) ── */}
      <div data-testid="draw-call-counter-turbines" data-count={String(turbineDrawCalls)} />
      <div data-testid="draw-call-counter-total" data-count={String(totalDrawCalls)} />

      {/* ── Telemetry overlay (shown when disconnected / stale / no data) ── */}
      {showOverlay && (
        <div
          data-testid="telemetry-overlay"
          role="status"
          aria-live="polite"
        >
          {getOverlayText(wsStatus, rawEnvStep)}
        </div>
      )}
    </div>
  );
}
