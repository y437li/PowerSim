# `src/scene`

<!-- curated -->
## Purpose

React Three Fiber 3D site visualization (REBUILD_SPEC §8). This folder owns everything required to render the animated Gansu site scene: canvas setup, GLB asset loading, animation drivers, and the asset registry resolver. It reads telemetry from `useTelemetryStore` exclusively and never mutates any store.

`SiteScene.tsx` is the top-level R3F entry point: it mounts the canvas into a provided `containerEl`, renders the configured Gansu wind turbines as a single `InstancedMesh` (one draw call; built for the full 146-turbine layout but currently ships a representative single turbine — full layout is a future config concern), and exposes a data-bridge `div` tree for testing. `SceneContent.tsx` places lights and GLB instances inside the R3F canvas and drives animation on each frame. All GLB paths are resolved through `registry.ts` (`resolveAsset`) — asset paths are never hardcoded in scene code; they are looked up from the LOCKED `assets/3d/registry.json` v1.0.0.

Animation modules are pure functions over telemetry values: `batteryAnimation.ts` computes the SOC fill level (clamp formula: `(soc − 0.2) / (0.9 − 0.2)`, D4); `flowAnimation.ts` computes power-flow line width, particle speed, and PV emissive intensity per §4.2/§7; `turbineAnimation.ts` computes rotor angular velocity from wind speed. `isPayloadFinite.ts` guards against NaN/Infinity in `EnvStepPayload` — the scene freezes rather than rendering corrupted geometry on invalid data.

This folder does not perform data-fetching, does not connect to WebSockets, and does not interpret physics or RL semantics.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `SceneContent.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `glbUrl` | `function` | SceneContent — React Three Fiber 3D scene content. |
| `SceneContent` | `function` | SceneContent — React Three Fiber 3D scene content. |

### `SiteScene.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `SiteScene` | `function` | — |

### `batteryAnimation.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `calcSocFill` | `function` | Battery SOC fill animation. |

### `flowAnimation.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `calcFlowWidth` | `function` | Power-flow line animation: width, particle speed, and PV emissive intensity. |
| `calcFlowSpeed` | `function` | Power-flow line animation: width, particle speed, and PV emissive intensity. |
| `calcEmissive` | `function` | Power-flow line animation: width, particle speed, and PV emissive intensity. |

### `isPayloadFinite.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `isPayloadFinite` | `function` | isPayloadFinite — NaN/Inf guard for EnvStepPayload. |

### `registry.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `resolveAsset` | `function` | Asset registry resolution. |

### `turbineAnimation.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `calcRotorOmega` | `function` | Turbine rotor angular velocity from wind speed. |

### `types.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `AssetType` | `type` | — |
| `Vec3` | `interface` | 3D scene type definitions. |
| `AnimationHooks` | `interface` | 3D scene type definitions. |
| `AssetRegistryEntry` | `interface` | 3D scene type definitions. |
| `AssetRegistry` | `interface` | 3D scene type definitions. |
| `Position3` | `type` | — |
| `Rotation3` | `type` | — |
| `TurbineInstance` | `interface` | — |
| `PvArrayInstance` | `interface` | — |
| `BatteryInstance` | `interface` | — |
| `GridConfig` | `interface` | — |
| `TerrainConfig` | `interface` | — |
| `SiteSceneConfig` | `interface` | 3D scene type definitions. |

<!-- generated:end -->
