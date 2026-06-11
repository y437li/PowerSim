# Contract: Scene Graph — 3D Site Render

- **Status:** DRAFT — awaiting VERDICT: APPROVE from frontend-reviewer
- **Spec:** REBUILD_SPEC §8 (3D visualization)
- **Owner:** 3d-assets-engineer · **Reviewer:** frontend-reviewer
- **Area:** frontend3d
- **Branch:** feat/frontend3d-scene-graph
- **Depends on LOCKED:**
  - `contracts/frontend3d/site_scene.md` (PR #7 — data bridge + R3F root creation)
  - `assets/3d/registry.json` v1.0.1 (PR #38 — asset IDs and paths; `contracts/assets/registry_schema.md`)
  - `contracts/shared/telemetry_schema.md` v1.0.0 (PR #6 — telemetry fields consumed)

---

## Purpose

`SiteScene.tsx` (PR #7) creates an empty R3F root via `createRoot(canvas)` but never calls
`.render()`. The canvas is black because no scene content is mounted. This contract:

1. Defines a new `SceneContent` component (`src/scene/SceneContent.tsx`) — the actual 3D
   scene: lights, GLB instances placed from config, and animation drivers wired to live
   telemetry.
2. Specifies the minimal `SiteScene.tsx` modification that calls
   `r3fRoot.render(<SceneContent .../>)`.
3. Defines the GLB URL scheme and the Vite dev-server change needed to serve `assets/3d/`.
4. Extracts `isPayloadFinite` into a shared utility (`src/scene/isPayloadFinite.ts`) so both
   `SiteScene` and `SceneContent` can guard against NaN/Inf telemetry.

---

## 1. New utility: `src/scene/isPayloadFinite.ts`

Extract the inline `isPayloadFinite` function from `SiteScene.tsx` (lines 69–93 of the PR #7
implementation) into a named export:

```typescript
/** Returns true iff every numeric field in the payload is a finite number. */
export function isPayloadFinite(step: EnvStepPayload): boolean;
```

`SiteScene.tsx` replaces its inline definition with an import from `./isPayloadFinite`.
`SceneContent.tsx` imports and uses the same function.

No behaviour change to `SiteScene.tsx`'s existing logic.

---

## 2. New component: `src/scene/SceneContent.tsx`

### 2.1 Export

```typescript
export function SceneContent(props: SceneContentProps): React.ReactElement | null;
```

### 2.2 Props interface

```typescript
interface SceneContentProps {
  /** Immutable site configuration — asset IDs, positions, capacities. */
  config: SiteSceneConfig;
  /** LOCKED asset registry v1.0.1 — resolves asset IDs to GLB paths + animation hooks. */
  registry: AssetRegistry;
}
```

Both types are imported from `./types` (existing, unchanged).

### 2.3 Telemetry subscription

`SceneContent` calls `useTelemetryStore()` directly to receive live telemetry. This keeps
the animation frame-rate decoupled from `SiteScene`'s React render cycle.

**Last-valid-step guard (same semantics as `SiteScene`):** `SceneContent` stores the last
valid telemetry step in a `useRef`. On each store update it checks `isPayloadFinite`; if the
incoming step is not finite, it freezes on the last valid step. When `displayStep === null`
(no valid step ever received), all animation driver outputs are zero.

```typescript
const rawEnvStep = useTelemetryStore((s) => s.envStep);
const displayRef = useRef<EnvStepPayload | null>(null);
if (rawEnvStep && isPayloadFinite(rawEnvStep)) {
  displayRef.current = rawEnvStep;
}
const displayStep = displayRef.current;
```

### 2.4 GLB URL scheme

All GLB paths are resolved through the registry — no hardcoded paths:

```typescript
export function glbUrl(registry: AssetRegistry, assetId: string): string | null {
  const entry = resolveAsset(registry, assetId);
  return entry ? `/assets/3d/${entry.path}` : null;
}
```

`glbUrl` is a named export from `src/scene/SceneContent.tsx` so that tests can verify URL
construction without rendering Three.js.

URL format: `/assets/3d/<entry.path>` where `entry.path` is the verbatim registry value
(e.g. `turbines/vestas-v150-4.2.glb` → `/assets/3d/turbines/vestas-v150-4.2.glb`).

Unknown `assetId` (not in registry) → `glbUrl` returns `null`; the calling sub-component
returns `null` (renders nothing) and does **not** call `useGLTF`.

### 2.5 Scene structure

```
SceneContent
  <ambientLight intensity={0.5} />
  <directionalLight position={[100, 200, 100]} intensity={1.0} castShadow={false} />
  {Object.entries(turbineGroups).map(([assetId, turbines]) =>
    <TurbineGroup key={assetId} assetId={assetId} turbines={turbines}
                  registry={registry} displayStep={displayStep} />
  )}
  {config.pv_arrays.map(pv =>
    <PVArrayModel key={pv.id} pv={pv} registry={registry} displayStep={displayStep} />
  )}
  <BatteryModel battery={config.battery} registry={registry} displayStep={displayStep} />
  <GridModel pcc={config.grid.pcc} registry={registry} />
```

`turbineGroups` is derived inside `SceneContent` (same `useMemo` logic as the existing
`SiteScene` — group `config.turbines` by `assetId`).

### 2.6 Sub-components

Each sub-component is **not** exported (file-private); only `SceneContent` and `glbUrl` are
exported from `src/scene/SceneContent.tsx`.

#### TurbineGroup

```typescript
function TurbineGroup({
  assetId, turbines, registry, displayStep,
}: {
  assetId: string;
  turbines: TurbineInstance[];
  registry: AssetRegistry;
  displayStep: EnvStepPayload | null;
}): React.ReactElement | null
```

- Calls `glbUrl(registry, assetId)` once — returns `null` and renders nothing if
  `glbUrl` returns `null`.
- Calls `useGLTF(url)` **once for the group** — multiple turbine instances sharing the same
  `assetId` share the cached GLB scene.
- For each turbine: `<primitive object={scene.clone()} position={t.position_m} rotation={t.rotation_rad} />`
- **Rotor animation** (inside a `useFrame` callback): traverse the cloned scene, find the
  node named `entry.animation_hooks.rotor_node` (e.g. `"Rotor"`); increment
  `rotor.rotation.y += calcRotorOmega(wind_speed_mps, 3, 12, 25, 0.2) * delta`. If the node
  is absent: skip silently.

_Because rotor animation uses per-clone refs, `TurbineGroup` keeps an array of
`useRef<Object3D | null>` — one per turbine instance — set in the clone's `onUpdate` or via
traverse at first `useFrame` tick._

#### PVArrayModel

```typescript
function PVArrayModel({
  pv, registry, displayStep,
}: {
  pv: PvArrayInstance;
  registry: AssetRegistry;
  displayStep: EnvStepPayload | null;
}): React.ReactElement | null
```

- Calls `useGLTF(glbUrl(registry, pv.assetId)!)` — renders nothing if URL is null.
- `<primitive object={scene.clone()} position={pv.position_m} rotation={pv.rotation_rad} />`
- **Irradiance animation** (inside `useFrame`): traverse the clone, find the material named
  `entry.animation_hooks.irradiance_material` (e.g. `"PVSurface"`); set
  `material.emissiveIntensity = calcEmissive(displayStep?.irradiance_wm2 ?? 0)`. If the
  material is absent: skip silently.

#### BatteryModel

```typescript
function BatteryModel({
  battery, registry, displayStep,
}: {
  battery: BatteryInstance;
  registry: AssetRegistry;
  displayStep: EnvStepPayload | null;
}): React.ReactElement | null
```

- Calls `useGLTF(glbUrl(registry, battery.assetId)!)`.
- `<primitive object={scene.clone()} position={battery.position_m} rotation={battery.rotation_rad} />`
- **SOC animation** (inside `useFrame`): traverse the clone, find the node named
  `entry.animation_hooks.soc_fill_mesh` (e.g. `"SOCFillMesh"`); set
  `mesh.scale.y = calcSocFill(displayStep?.battery.soc ?? SOC_MIN, 0.2, 0.9)`. If absent:
  skip.

#### GridModel

```typescript
function GridModel({
  pcc, registry,
}: {
  pcc: { assetId: string; position_m: Position3 };
  registry: AssetRegistry;
}): React.ReactElement | null
```

- Calls `useGLTF(glbUrl(registry, pcc.assetId)!)`.
- `<primitive object={scene.clone()} position={pcc.position_m} />`
- No animation hook in v1 for the PCC substation.

### 2.7 Animation value formulas (golden constants — LOCKED from PR #7)

| Driver | Formula | Null telemetry |
|---|---|---|
| Rotor omega (rad/s) | `calcRotorOmega(wind_speed_mps, 3, 12, 25, 0.2)` | 0 |
| SOC fill [0,1] | `calcSocFill(battery.soc, 0.2, 0.9)` | 0 |
| PV emissive [0,1] | `calcEmissive(irradiance_wm2)` | 0 |

All three driver functions are imported from their existing modules (`turbineAnimation.ts`,
`batteryAnimation.ts`, `flowAnimation.ts`). No new animation formulas.

### 2.8 Hand-computed animation golden values (for test assertions)

| Input | Driver | Expected | Arithmetic |
|---|---|---|---|
| `wind_speed_mps=0` | `calcRotorOmega` | `0` | below cut-in (3 m/s) |
| `wind_speed_mps=3` | `calcRotorOmega` | `0` | at cut-in: ramp → `0.2*(3-3)/(12-3)=0` |
| `wind_speed_mps=7.5` | `calcRotorOmega` | `0.1` | ramp: `0.2*(7.5-3)/(12-3)=0.2*4.5/9=0.1` |
| `wind_speed_mps=12` | `calcRotorOmega` | `0.2` | at rated: plateau = `omegaMax=0.2` |
| `wind_speed_mps=24.9` | `calcRotorOmega` | `0.2` | below cut-out (25), plateau |
| `wind_speed_mps=25` | `calcRotorOmega` | `0` | at cut-out: off |
| `irradiance_wm2=0` | `calcEmissive` | `0` | `0/1000=0` |
| `irradiance_wm2=500` | `calcEmissive` | `0.5` | `500/1000=0.5` |
| `irradiance_wm2=1000` | `calcEmissive` | `1.0` | `1000/1000=1.0` |
| `irradiance_wm2=1500` | `calcEmissive` | `1.0` | `clamp(1500/1000,0,1)=1.0` |
| `battery.soc=0.2` | `calcSocFill` | `0` | `(0.2-0.2)/(0.9-0.2)=0/0.7=0` |
| `battery.soc=0.55` | `calcSocFill` | `0.5` | `(0.55-0.2)/(0.9-0.2)=0.35/0.7=0.5` |
| `battery.soc=0.9` | `calcSocFill` | `1.0` | `(0.9-0.2)/(0.9-0.2)=0.7/0.7=1.0` |

---

## 3. SiteScene.tsx modification

### 3.1 R3F root ref

Add a `useRef` for the R3F root (replaces the local `let r3fRoot` in the existing `useEffect`
closure):

```typescript
const r3fRootRef = useRef<{
  render(el: React.ReactElement): void;
  unmount(): void;
} | null>(null);
```

### 3.2 Effect 1 (deps: `[containerEl]`) — create canvas + R3F root

Replace the existing `useEffect` body with:

```typescript
useEffect(() => {
  if (!containerEl) return;
  const canvas = document.createElement("canvas");
  canvas.setAttribute("data-testid", "scene-canvas");
  containerEl.appendChild(canvas);

  let cancelled = false;
  (async () => {
    try {
      const { createRoot } = await import("@react-three/fiber");
      if (cancelled) return;
      r3fRootRef.current = createRoot(canvas);
      // Trigger initial render — subsequent updates come from Effect 2
      r3fRootRef.current.render(
        React.createElement(SceneContent, { config, registry })
      );
    } catch {
      // WebGL not available (JSDOM / headless) — canvas element still exists for DOM tests
    }
  })();

  return () => {
    cancelled = true;
    r3fRootRef.current?.unmount();
    r3fRootRef.current = null;
    if (canvas.parentNode === containerEl) containerEl.removeChild(canvas);
  };
}, [containerEl]); // eslint-disable-line react-hooks/exhaustive-deps
// config/registry omitted from deps intentionally — Effect 2 handles re-renders
```

### 3.3 Effect 2 (deps: `[config, registry]`) — re-render on config change

Add a new `useEffect` after Effect 1:

```typescript
useEffect(() => {
  if (!r3fRootRef.current) return;
  r3fRootRef.current.render(
    React.createElement(SceneContent, { config, registry })
  );
}, [config, registry]);
```

**Rationale:** Effect 1 fires only when the container changes (DOM lifecycle); Effect 2 fires
whenever the scene configuration changes. The two effects are independent — Effect 2 is a
no-op until Effect 1 has populated `r3fRootRef.current`.

### 3.4 Imports added to SiteScene.tsx

```typescript
import { SceneContent } from "./SceneContent";
// isPayloadFinite — replace inline definition with:
import { isPayloadFinite } from "./isPayloadFinite";
```

---

## 4. Vite dev-server: serve `assets/3d/` at `/assets/3d/`

GLB files in `assets/3d/` must be accessible at the URL `/assets/3d/<path>` in the dev server.

**Required change:** create `public/` directory and a relative symlink:

```
public/assets  →  ../assets
```

With Vite's default `publicDir: 'public'`, files under `public/` are served at `/`. So
`public/assets/3d/turbines/vestas-v150-4.2.glb` becomes accessible at
`/assets/3d/turbines/vestas-v150-4.2.glb`.

Alternative: use `vite-plugin-static-copy` with target `{ src: 'assets', dest: '' }` — same
net effect. The implementation may choose; either is conformant. The same PR that implements
the scene graph must also include whichever infrastructure change makes the URLs resolvable.

---

## 5. Out of scope (v1 / deferred)

- Animated power-flow tubes / lines (follow-up task).
- LOD (Level of Detail) levels — deferred.
- `InstancedMesh` for the turbine field — performance optimization deferred; v1 uses
  `scene.clone()` per instance (functionally correct; the data bridge draw-call counter from
  PR #7 counts unique assetIds, not Three.js draw calls, so the ≤50 data-bridge assertion
  is preserved).
- Shadows (`castShadow`, `receiveShadow`).
- Post-processing, bloom, ambient occlusion.
- Camera / orbit controls.
- Ground plane / terrain rendering (`config.terrain`).
- `config.grid.substation` and `config.grid.pylons` — only `config.grid.pcc` rendered in v1.
- §8 composable asset types (`gas_turbine`, `electrolyzer`, `load_building`) — only the 4
  Gansu parity asset IDs are exercised in the Gansu site config.

---

## 6. Validation requirements

1. `src/scene/isPayloadFinite.ts` exists and exports `isPayloadFinite` as a named function.
2. `src/scene/SceneContent.tsx` exists and exports `SceneContent` (function) and `glbUrl`.
3. `SceneContent` accepts `{ config: SiteSceneConfig; registry: AssetRegistry }`.
4. `glbUrl(registry, "vestas-v150-4.2")` returns `"/assets/3d/turbines/vestas-v150-4.2.glb"`.
5. `glbUrl(registry, "trina-vertex-n-670w")` returns `"/assets/3d/pv/trina-vertex-n-670w.glb"`.
6. `glbUrl(registry, "catl-lmp-300mwh")` returns `"/assets/3d/batteries/catl-lmp-300mwh.glb"`.
7. `glbUrl(registry, "pcc-substation-945mw")` returns `"/assets/3d/grid/pcc-substation-945mw.glb"`.
8. `glbUrl(registry, "unknown-asset")` returns `null`.
9. After mounting `SiteScene` with a valid `containerEl`, `r3fRoot.render()` is called with a
   React element whose `type === SceneContent`.
10. The element's props include `config` and `registry` matching the `SiteScene` props.
11. When `config` changes (new object reference), `r3fRoot.render()` is called again.
12. When the component unmounts, `r3fRoot.unmount()` is called (existing behaviour preserved).
13. `SceneContent` rendered with `GANSU_CONFIG` + `GANSU_REGISTRY` includes an `<ambientLight>`
    with `intensity={0.5}`.
14. `SceneContent` rendered with `GANSU_CONFIG` + `GANSU_REGISTRY` includes a
    `<directionalLight>` with `intensity={1.0}` and `position={[100, 200, 100]}`.
15. Null telemetry → `SceneContent` renders without error; animation drivers produce 0.
16. `SceneContent` with `wind_speed_mps=12` (rated): rotor omega driver = `0.2` rad/s.
17. `SceneContent` with `irradiance_wm2=500`: PV emissive driver = `0.5`.
18. `SceneContent` with `battery.soc=0.55`: SOC fill driver = `0.5`.
19. `SceneContent` with GANSU_CONFIG (2 turbines, same assetId) calls `useGLTF` exactly once
    for the turbine assetId — not once per instance.
20. `SceneContent` with an unknown `assetId` in config: does not crash; `useGLTF` is not
    called with an invalid URL; the unknown instance simply renders nothing.
