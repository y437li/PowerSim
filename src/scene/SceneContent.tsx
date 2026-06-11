/**
 * SceneContent — React Three Fiber 3D scene content.
 * Contract: contracts/frontend3d/scene_graph.md §2
 *
 * Renders the actual 3D site: lights, GLB instances placed from config,
 * and animation drivers wired to live telemetry via useTelemetryStore.
 *
 * Design:
 *  - Reads live telemetry exclusively from useTelemetryStore (never opens its own socket).
 *  - All GLB paths resolved via resolveAsset → glbUrl (no hardcoded paths).
 *  - useGLTF called once per unique assetId (cache-efficient: grouped turbines share model).
 *  - Freeze-on-invalid: NaN/Inf telemetry keeps last valid step (see isPayloadFinite).
 *  - useFrame drives rotor omega, SOC fill, PV emissive at frame-rate.
 *
 * Exported: SceneContent (component), glbUrl (URL utility — for tests).
 * Not exported: sub-components (TurbineGroup, PVArrayModel, BatteryModel, GridModel).
 */

import React, { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import type * as THREE from "three";
import { useTelemetryStore } from "../stores/telemetryStore";
import type { EnvStepPayload } from "../types/telemetry";
import type {
  AssetRegistry,
  BatteryInstance,
  Position3,
  PvArrayInstance,
  Rotation3,
  SiteSceneConfig,
  TurbineInstance,
} from "./types";
import { resolveAsset } from "./registry";
import { isPayloadFinite } from "./isPayloadFinite";
import { calcRotorOmega } from "./turbineAnimation";
import { calcSocFill } from "./batteryAnimation";
import { calcEmissive } from "./flowAnimation";

// ─── Animation constants (LOCKED from PR #7, contracts/frontend3d/site_scene.md) ─

const DEFAULT_V_CUTIN_MPS = 3;
const DEFAULT_V_RATED_MPS = 12;
const DEFAULT_V_CUTOUT_MPS = 25;
const DEFAULT_OMEGA_MAX_RAD = 0.2;
const SOC_MIN = 0.2;
const SOC_MAX = 0.9;

// ─── glbUrl utility (exported for testing) ───────────────────────────────────

/**
 * Resolve a registry assetId to a full GLB URL path.
 *
 * @returns `/assets/3d/${entry.path}` if the assetId is in the registry,
 *          or `null` if not found (callers must render nothing in that case).
 *
 * Contract: contracts/frontend3d/scene_graph.md §2.4
 */
export function glbUrl(registry: AssetRegistry, assetId: string): string | null {
  const entry = resolveAsset(registry, assetId);
  return entry ? `/assets/3d/${entry.path}` : null;
}

// ─── Sub-component: TurbineGroup ─────────────────────────────────────────────
// Renders all turbine instances for a single assetId (one useGLTF call total).

interface TurbineGroupProps {
  url: string;
  turbines: TurbineInstance[];
  rotorNode?: string;
  displayStep: EnvStepPayload | null;
}

function TurbineGroup({
  url,
  turbines,
  rotorNode,
  displayStep,
}: TurbineGroupProps): React.ReactElement {
  const { scene } = useGLTF(url) as { scene: THREE.Group };

  // Store rotor refs (one per turbine instance) for animation
  const rotorRefs = useRef<(THREE.Object3D | null)[]>([]);

  // Keep latest displayStep in a ref so the useFrame closure is never stale
  const displayStepRef = useRef(displayStep);
  displayStepRef.current = displayStep;

  // Clone scene once per group + per turbine; traverse to find rotor node
  const clones = useMemo(() => {
    rotorRefs.current = [];
    return turbines.map(() => {
      const cloned = (scene as THREE.Group).clone() as THREE.Object3D;
      let rotorFound: THREE.Object3D | null = null;
      if (rotorNode) {
        cloned.traverse((child: THREE.Object3D) => {
          if (child.name === rotorNode) {
            rotorFound = child;
          }
        });
      }
      rotorRefs.current.push(rotorFound);
      return cloned;
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, rotorNode]); // turbines identity changes only when config changes → safe dep

  // Animate rotors every frame
  useFrame((_state, delta) => {
    const ds = displayStepRef.current;
    const omega = ds
      ? calcRotorOmega(
          ds.wind_speed_mps,
          DEFAULT_V_CUTIN_MPS,
          DEFAULT_V_RATED_MPS,
          DEFAULT_V_CUTOUT_MPS,
          DEFAULT_OMEGA_MAX_RAD,
        )
      : 0;
    for (const rotor of rotorRefs.current) {
      if (rotor) {
        (rotor as THREE.Object3D).rotation.y += omega * delta;
      }
    }
  });

  return (
    <>
      {turbines.map((turbine, i) => (
        <primitive
          key={turbine.id}
          object={clones[i]}
          position={turbine.position_m as [number, number, number]}
          rotation={turbine.rotation_rad as [number, number, number]}
        />
      ))}
    </>
  );
}

// ─── Sub-component: PVArrayModel ─────────────────────────────────────────────

interface PVArrayModelProps {
  url: string;
  pv: PvArrayInstance;
  irradianceMaterial?: string;
  displayStep: EnvStepPayload | null;
}

function PVArrayModel({
  url,
  pv,
  irradianceMaterial,
  displayStep,
}: PVArrayModelProps): React.ReactElement {
  const { scene } = useGLTF(url) as { scene: THREE.Group };

  const materialRef = useRef<(THREE.MeshStandardMaterial & { emissiveIntensity: number }) | null>(
    null,
  );

  const displayStepRef = useRef(displayStep);
  displayStepRef.current = displayStep;

  const cloned = useMemo(() => {
    materialRef.current = null;
    const c = (scene as THREE.Group).clone();
    if (irradianceMaterial) {
      c.traverse((child: THREE.Object3D) => {
        const mesh = child as THREE.Mesh;
        if (!mesh.material) return;
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        for (const m of mats) {
          if (
            m &&
            typeof m === "object" &&
            (m as THREE.Material).name === irradianceMaterial
          ) {
            materialRef.current = m as THREE.MeshStandardMaterial & {
              emissiveIntensity: number;
            };
          }
        }
      });
    }
    return c;
  }, [scene, irradianceMaterial]);

  useFrame(() => {
    if (materialRef.current !== null) {
      const ds = displayStepRef.current;
      materialRef.current.emissiveIntensity = ds ? calcEmissive(ds.irradiance_wm2) : 0;
    }
  });

  return (
    <primitive
      object={cloned}
      position={pv.position_m as [number, number, number]}
      rotation={pv.rotation_rad as [number, number, number]}
    />
  );
}

// ─── Sub-component: BatteryModel ─────────────────────────────────────────────

interface BatteryModelProps {
  url: string;
  battery: BatteryInstance;
  socFillMesh?: string;
  displayStep: EnvStepPayload | null;
}

function BatteryModel({
  url,
  battery,
  socFillMesh,
  displayStep,
}: BatteryModelProps): React.ReactElement {
  const { scene } = useGLTF(url) as { scene: THREE.Group };

  const fillMeshRef = useRef<THREE.Object3D | null>(null);

  const displayStepRef = useRef(displayStep);
  displayStepRef.current = displayStep;

  const cloned = useMemo(() => {
    fillMeshRef.current = null;
    const c = (scene as THREE.Group).clone();
    if (socFillMesh) {
      c.traverse((child: THREE.Object3D) => {
        if (child.name === socFillMesh) {
          fillMeshRef.current = child;
        }
      });
    }
    return c;
  }, [scene, socFillMesh]);

  useFrame(() => {
    if (fillMeshRef.current !== null) {
      const ds = displayStepRef.current;
      const fill = ds ? calcSocFill(ds.battery.soc, SOC_MIN, SOC_MAX) : 0;
      fillMeshRef.current.scale.y = fill;
    }
  });

  return (
    <primitive
      object={cloned}
      position={battery.position_m as [number, number, number]}
      rotation={battery.rotation_rad as [number, number, number]}
    />
  );
}

// ─── Sub-component: GridModel ─────────────────────────────────────────────────

interface GridModelProps {
  url: string;
  pcc: { assetId: string; position_m: Position3; rotation_rad?: Rotation3 };
}

function GridModel({ url, pcc }: GridModelProps): React.ReactElement {
  const { scene } = useGLTF(url) as { scene: THREE.Group };
  const cloned = useMemo(() => (scene as THREE.Group).clone(), [scene]);
  return (
    <primitive
      object={cloned}
      position={pcc.position_m as [number, number, number]}
    />
  );
}

// ─── SceneContentProps ────────────────────────────────────────────────────────

interface SceneContentProps {
  /** Immutable site configuration — asset IDs, positions, capacities. */
  config: SiteSceneConfig;
  /** LOCKED asset registry v1.0.1 — resolves asset IDs to GLB paths + animation hooks. */
  registry: AssetRegistry;
}

// ─── SceneContent (main export) ───────────────────────────────────────────────

type StoreState = { envStep: EnvStepPayload | null; wsStatus: string };

/**
 * Actual 3D scene: lights, GLB instances, and live animation.
 *
 * This component is mounted inside the R3F root created by SiteScene.tsx.
 * It reads live telemetry directly from useTelemetryStore (decoupled from
 * SiteScene's React render cycle) and drives animation every frame.
 *
 * Contract: contracts/frontend3d/scene_graph.md §2
 */
export function SceneContent({ config, registry }: SceneContentProps): React.ReactElement {
  // ── 1. Telemetry with freeze-on-invalid guard ─────────────────────────────
  const rawEnvStep = useTelemetryStore((s: StoreState) => s.envStep);
  const displayRef = useRef<EnvStepPayload | null>(null);
  if (rawEnvStep && isPayloadFinite(rawEnvStep)) {
    displayRef.current = rawEnvStep;
  }
  const displayStep = displayRef.current;

  // ── 2. Group turbines by assetId (one useGLTF call per unique model) ──────
  const turbineGroups = useMemo(() => {
    const groups: Record<string, TurbineInstance[]> = {};
    for (const t of config.turbines) {
      if (!groups[t.assetId]) groups[t.assetId] = [];
      groups[t.assetId].push(t);
    }
    return groups;
  }, [config.turbines]);

  return (
    <>
      {/* ── Lighting (contract §2.5) ── */}
      <ambientLight intensity={0.5} />
      <directionalLight
        position={[100, 200, 100] as [number, number, number]}
        intensity={1.0}
        castShadow={false}
      />

      {/* ── Turbine field: one TurbineGroup per unique assetId ── */}
      {Object.entries(turbineGroups).map(([assetId, turbines]) => {
        const url = glbUrl(registry, assetId);
        const entry = resolveAsset(registry, assetId);
        if (!url || !entry) return null; // unknown assetId → skip, no useGLTF call
        return (
          <TurbineGroup
            key={assetId}
            url={url}
            turbines={turbines}
            rotorNode={entry.animation_hooks?.rotor_node}
            displayStep={displayStep}
          />
        );
      })}

      {/* ── PV arrays ── */}
      {config.pv_arrays.map((pv) => {
        const url = glbUrl(registry, pv.assetId);
        const entry = resolveAsset(registry, pv.assetId);
        if (!url || !entry) return null;
        return (
          <PVArrayModel
            key={pv.id}
            url={url}
            pv={pv}
            irradianceMaterial={entry.animation_hooks?.irradiance_material}
            displayStep={displayStep}
          />
        );
      })}

      {/* ── Battery ── */}
      {(() => {
        const url = glbUrl(registry, config.battery.assetId);
        const entry = resolveAsset(registry, config.battery.assetId);
        if (!url || !entry) return null;
        return (
          <BatteryModel
            url={url}
            battery={config.battery}
            socFillMesh={entry.animation_hooks?.soc_fill_mesh}
            displayStep={displayStep}
          />
        );
      })()}

      {/* ── Grid PCC ── */}
      {(() => {
        const url = glbUrl(registry, config.grid.pcc.assetId);
        if (!url) return null;
        return <GridModel url={url} pcc={config.grid.pcc} />;
      })()}
    </>
  );
}
