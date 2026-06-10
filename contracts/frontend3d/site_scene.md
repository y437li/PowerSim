# Contract: 3D Site Scene

- **Status:** DRAFT — awaiting VERDICT: APPROVE from frontend-reviewer
- **Spec:** REBUILD_SPEC.md §1 (site totals), §3.1 (wind/PV power curves), §3.2 (battery), §3.3 (power balance flows), §3.6 (constraint table), §8.5 (per-asset 3D category)
- **Owner:** 3d-assets-engineer · **Reviewer:** frontend-reviewer
- **Area:** frontend3d
- **Depends on DECISIONS:** D3 (Δt=1h), D4 (SOC 0.2–0.9), D5 (PCC export 945 MW), D12 (import limit per-site field)
- **Depends on contracts:** `contracts/shared/telemetry_schema.md` (**LOCKED v1.0.0, PR #6, 98beee0**); `contracts/frontend/app_shell.md` — `SceneMountPoint.tsx` provides the container div

---

## Purpose

React Three Fiber (R3F) + Three.js scene that renders the Energy GO site as a live 3D visualization. The scene:

1. Composes the 3D asset instances (turbines, PV arrays, battery bank, grid connection) from a `SiteSceneConfig` derived from the site YAML — no asset paths hardcoded in scene code.
2. Resolves every asset through `assets/3d/registry.json` (the single source of truth).
3. Animates rotor spin, SOC fill, PV irradiance brightness, and power-flow lines driven by `telemetryStore.envStep` (the Zustand store owned by frontend-engineer). It never opens a WebSocket or REST connection.
4. Targets 60 fps on a mid-range GPU for the full Gansu site (~146 turbines, 330 MW PV, battery bank, grid connection) via instancing + LOD.
5. Attaches its R3F canvas to the `HTMLDivElement` provided by `SceneMountPoint`'s `onReady` callback — it owns zero layout.

---

## 1. Asset registry (`assets/3d/registry.json`)

> This file is a **shared contract** (consumed by scene code and referenced by QA). It must be agreed with rl-architect before any asset file paths are treated as stable. Currently DRAFT alongside the telemetry schema.

### 1.1 File layout

All assets live under the single `assets/3d/` tree, organized by function:

```
assets/3d/
  turbines/          # wind turbine GLBs (up to 12 models per §6)
  pv/                # PV array GLBs (up to 10)
  batteries/         # battery bank GLBs (up to 12)
  grid/              # PCC, substation, pylon GLBs
  site/              # terrain, environment GLBs
  effects/           # power-flow materials, shader assets
  registry.json      # single source of truth
```

### 1.2 Registry schema

```typescript
interface AssetRegistryEntry {
  id: string;           // config YAML asset ID (registry key, verbatim)
  path: string;         // path relative to assets/3d/ e.g. "turbines/vestas-v150-4.2.glb"
  type: "turbine" | "pv_array" | "battery" | "grid_pcc" | "grid_substation"
       | "grid_pylon" | "terrain" | "effect";
  dims_m: {             // real-world bounding box in metres
    x: number;
    y: number;
    z: number;
  };
  pivot: {              // pivot/anchor offset relative to centre of dims_m, metres
    x: number;          // + = right, − = left
    y: number;          // + = up, − = down
    z: number;          // + = toward viewer
  };
  animation_hooks: {
    rotor_node?: string;       // GLTF node name — spin axis is local +Y
    soc_fill_mesh?: string;    // GLTF mesh name — Y-scale driven by SOC fill fraction
    irradiance_material?: string;  // GLTF material name — emissiveIntensity driven by irradiance
  };
}

// registry.json root shape
interface AssetRegistry {
  schema_version: string;     // semver (this contract's version)
  entries: AssetRegistryEntry[];
}
```

**Keys** — the `id` field of each entry equals the asset ID string used in the site YAML (e.g. `"vestas-v150-4.2"`, `"trina-vertex-n-670w"`, `"catl-lmp-300mwh"`). Scene code resolves paths as `registry.entries.find(e => e.id === assetId)`. **No hardcoded `assets/3d/` paths anywhere in scene code.**

### 1.3 Failure behaviour

- Asset ID present in `SiteSceneConfig` but **absent from registry** → scene renders a 1×1×1 magenta cube placeholder for that instance; logs a warning; does **not** throw or crash the scene.
- Asset ID present in registry but **GLB file 404** → same placeholder; error surfaced via R3F `onError`; does not crash.
- `registry.json` itself fails to parse → scene mounts with an empty asset library; all instances render placeholders; surface error in `SceneMountPoint`'s error boundary.

---

## 2. Component interface

### 2.1 `SiteScene` (main export)

```typescript
interface SiteSceneProps {
  config: SiteSceneConfig;           // composed from site YAML at route level
  registry: AssetRegistry;           // loaded once at startup; passed as prop
  containerEl: HTMLDivElement;       // from SceneMountPoint.onReady — R3F canvas attaches here
  className?: string;
}

function SiteScene(props: SiteSceneProps): React.ReactElement;
```

The component:
- Creates an R3F `Canvas` portalled into `containerEl` (not rendered into the React tree location of `SiteScene`).
- Reads `telemetryStore.envStep` via `useTelemetryStore()` hook (from frontend-engineer's store); subscribes with a selector to avoid re-rendering on irrelevant store changes.
- Calls `resolveAsset(registry, assetId)` for every instance in `config`.

### 2.2 `resolveAsset`

```typescript
function resolveAsset(
  registry: AssetRegistry,
  assetId: string
): AssetRegistryEntry | null;
// Returns null if assetId not found; caller renders placeholder.
```

### 2.3 `SiteSceneConfig`

```typescript
interface TurbineInstance {
  id: string;                  // unique instance ID
  assetId: string;             // registry lookup key
  position_m: [number, number, number];   // [x, y, z] metres, site-local frame
  rotation_rad: [number, number, number]; // [rx, ry, rz] Euler
  capacity_mw: number;         // MW, for flow attribution
}

interface PvArrayInstance {
  id: string;
  assetId: string;
  position_m: [number, number, number];
  rotation_rad: [number, number, number];
  capacity_mw: number;
}

interface BatteryInstance {
  id: string;
  assetId: string;
  position_m: [number, number, number];
  rotation_rad: [number, number, number];
  capacity_mwh: number;        // MWh; 294.5 for Gansu
  max_charge_mw: number;       // MW; 98.16 for Gansu
  max_discharge_mw: number;    // MW; 98.16 for Gansu
}

interface GridConnectionInstance {
  pcc: { assetId: string; position_m: [number, number, number] };
  substation: { assetId: string; position_m: [number, number, number] };
  pylons: Array<{ assetId: string; position_m: [number, number, number] }>;
}

interface SiteSceneConfig {
  site_id: string;
  wind_capacity_mw: number;      // MW, site total (615 for Gansu)
  solar_capacity_mw: number;     // MW (330 Gansu)
  turbines: TurbineInstance[];
  pv_arrays: PvArrayInstance[];
  battery: BatteryInstance;
  grid: GridConnectionInstance;
  terrain: { assetId: string };
}
```

---

## 3. Telemetry binding (LOCKED v1.0.0, PR #6)

Fields cited below are from `contracts/shared/telemetry_schema.md` **LOCKED v1.0.0 (PR #6, 98beee0)**. All field names and units below are stable.

The scene reads **only** from `useTelemetryStore()`. It never calls `fetch`, `WebSocket`, or any other I/O primitive.

### 3.1 `EnvStepPayload` fields consumed

| Field | Used for |
|---|---|
| `flows.solar_to_load_mw` … `flows.bat_to_grid_mw` | Power-flow line visibility/magnitude (§4) |
| `flows.solar_curtailed_mw` | Solar curtailment visual (§4.3) |
| `flows.wind_curtailed_mw` | Wind curtailment visual (§4.3) |
| `flows.bat_curtailed_mw` | Battery curtailment (available but not separately visualised in v1) |
| `flows.load_unserved_mw` | VOLL alert visual (§4.3) |
| `generation.gross_solar_mw` | PV source label (total before curtailment/dispatch) |
| `generation.gross_wind_mw` | Wind source label (total before curtailment/dispatch) |
| `battery.soc` | SOC fill animation (§5) |
| `battery.p_charge_mw`, `battery.p_discharge_mw` | Battery direction indicator |
| `battery.p_max_charge_mw`, `battery.p_max_discharge_mw` | Battery wire scaling (98.16 MW Gansu) |
| `wind_speed_mps` | Rotor spin rate (§6) |
| `irradiance_wm2` | PV emissive intensity (§7) |
| `pcc.export_mw`, `pcc.import_mw` | Grid line thickness / direction |
| `pcc.max_export_mw`, `pcc.max_import_mw` | Grid wire scaling (per-site, D5/D12) |
| `sim_time_utc`, `step` | Sim clock display — **never use envelope `ts_utc`** (emit clock only) |

### 3.2 Stale / null telemetry

- `envStep === null` (not yet connected or store cleared): **freeze** — all animated values stay at their initial/last-known state. Do **not** reset to zero. Show a `<Html>` overlay label "Waiting for telemetry…" in the canvas.
- `wsStatus === "stale"` (from telemetryStore): show a `<Html>` overlay label "Stale — last update: …" in the canvas. Freeze all animation.
- `wsStatus === "disconnected"`: show "Disconnected" overlay. Freeze.
- Receiving a new `envStep` clears the overlay immediately.

### 3.3 Finiteness guard

The locked telemetry schema guarantees all numeric fields are finite (no `NaN`, `+Inf`, `−Inf`). If a message arrives containing any non-finite number, the scene **silently discards** that message (does not apply it to any animated value) and logs a warning to the console. This prevents a single corrupt message from breaking flow-line width/speed calculations or causing Three.js geometry errors.

---

## 4. Power-flow lines

### 4.1 Flow topology

Every power flow in `flows.*` maps to a directed animated line between two node positions in the scene:

| `flows` field | Source node | Target node |
|---|---|---|
| `solar_to_load_mw` | PV array centroid | Load zone marker |
| `solar_to_bat_mw` | PV array centroid | Battery bank |
| `solar_to_grid_mw` | PV array centroid | PCC |
| `wind_to_load_mw` | Turbine field centroid | Load zone marker |
| `wind_to_bat_mw` | Turbine field centroid | Battery bank |
| `wind_to_grid_mw` | Turbine field centroid | PCC |
| `bat_to_load_mw` | Battery bank | Load zone marker |
| `bat_to_grid_mw` | Battery bank | PCC |
| `grid_to_load_mw` | PCC | Load zone marker |
| `grid_to_bat_mw` | PCC | Battery bank |
| `solar_curtailed_mw` | PV array centroid | Curtailment sink marker |
| `wind_curtailed_mw` | Turbine field centroid | Curtailment sink marker |

### 4.2 Animation mapping

```
site_max_mw = wind_capacity_mw + solar_capacity_mw    // e.g. 945 MW Gansu
normalized  = site_max_mw > 0
              ? clamp(flow_mw / site_max_mw, 0, 1)    // ∈ [0, 1]
              : 0                                       // guard: degenerate config

line_width (canvas units) = 0.5 + normalized × 5.5    // range [0.5, 6.0]
particle_speed (units/s)  = 0.2 + normalized × 2.8    // range [0.2, 3.0]
```

The clamp serves two purposes:
- `flow_mw < 0` (physically impossible, §3.3) → clamped to 0 → line hidden.
- `flow_mw > site_max_mw` (possible during curtailment transients) → clamped to 1 → line at maximum width/speed.

**Grid connection lines use different denominators** (contract §8):
- Export line: `normalized = clamp(pcc.export_mw / pcc.max_export_mw, 0, 1)` (945 MW Gansu)
- Import line: `normalized = clamp(pcc.import_mw / pcc.max_import_mw, 0, 1)` (400 MW Gansu, D12)

These are **not** normalized by `site_max_mw`. Using `site_max_mw` for import would be a 2× visual error at Gansu (945 vs 400 MW).

- `flow_mw = 0` → line is **hidden** (not removed from scene graph; opacity=0 for instant re-show).
- Particle direction follows the arrow: source → target.

### 4.3 Event visuals

| Condition | Visual |
|---|---|
| `solar_curtailed_mw > 0` | Dedicated solar-curtailment line from PV array centroid to "curtailed" sink marker; colour red-orange `#ef4444`; `line_width = 0.5 + (solar_curtailed_mw / site_max_mw) × 5.5` |
| `wind_curtailed_mw > 0` | Dedicated wind-curtailment line from turbine field centroid to "curtailed" sink marker; same colour scheme; `line_width = 0.5 + (wind_curtailed_mw / site_max_mw) × 5.5` |
| Both curtailment fields > 0 | Both lines shown simultaneously (each independently sized) |
| `load_unserved_mw > 0` | Load zone marker flashes amber/red; a VOLL indicator label shows the unserved MW |
| `battery.soc_violation_mwh > 0` | Battery mesh briefly flashes red (one render cycle, no blinking loop) |

### 4.4 Colour scheme

| Flow type | Line colour |
|---|---|
| Solar flows | Amber `#f59e0b` |
| Wind flows | Cyan `#06b6d4` |
| Battery flows | Violet `#8b5cf6` |
| Grid flows | Green `#10b981` |
| Curtailment | Red-orange `#ef4444` |
| VOLL | Red `#dc2626` |

---

## 5. Battery SOC visualization

SOC display fraction (`soc_fill`) maps the raw `battery.soc` (D4: physical range [0.2, 0.9]) to a visual fill [0, 1]:

```
soc_fill = (soc − soc_min) / (soc_max − soc_min)
         = (soc − 0.2) / (0.7)                    // D4 bounds
```

- `soc = 0.2` → `soc_fill = 0.0` (empty)
- `soc = 0.9` → `soc_fill = 1.0` (full)
- `soc = 0.55` → `soc_fill = (0.55−0.2)/0.7 = 0.5` (half)

The SOC fill mesh (`animation_hooks.soc_fill_mesh` from registry) is Y-scaled: `scale.y = soc_fill`. Clamp input: `soc < 0.2 → soc_fill = 0`; `soc > 0.9 → soc_fill = 1` (defensive against malformed telemetry).

A numeric label rendered via R3F `<Html>` shows `{(soc * 100).toFixed(1)}%` and `{p_charge_mw > 0 ? "↑ Charging" : p_discharge_mw > 0 ? "↓ Discharging" : "Idle"}`.

---

## 6. Turbine rotor animation

Rotor spin rate (rad/s) derived from `wind_speed_mps`. **Note:** §3.1 uses a cubic curve for electrical power output; the visual rotor speed uses a **linear** formula in `(v − v_cutin)` — this is the physically correct mapping for RPM and avoids the near-zero region being invisible at low wind speeds:

```
v       = wind_speed_mps
v_cutin = 3 m/s     (§3.1 / §3.6 row 11)
v_rated = 12 m/s    (§3.1 Vestas V150-4.2)
v_cutout= 25 m/s    (§3.1)
omega_max = 0.2 rad/s   // reference max visual spin (visual, not physical RPM)

omega = 0                                  if v < v_cutin OR v >= v_cutout
      = omega_max * ((v − v_cutin) / (v_rated − v_cutin))   if v_cutin ≤ v < v_rated
      = omega_max                           if v_rated ≤ v < v_cutout
```

Spin is applied each frame to the `animation_hooks.rotor_node` rotation around the node's local +Y axis. If `rotor_node` is not in the registry entry, no rotation is applied (graceful degradation, not a crash).

All turbine instances share the same `wind_speed_mps` from `telemetryStore.envStep` (site-wide, not per-turbine — the env is a lumped model per §1).

**Instancing:** all turbine instances of the same `assetId` MUST be rendered via a single Three.js `InstancedMesh` per LOD level. See §9 for the LOD + draw-call budget.

---

## 7. PV array irradiance visualization

Irradiance-to-emissive mapping:

```
irradiance_wm2 ∈ [0, ~1200]   (§4.1 G_peak up to 1200 W/m²)
emissive_intensity = clamp(irradiance_wm2 / 1000.0, 0.0, 1.0)
```

- `irradiance = 0` → `emissive_intensity = 0.0` (no glow, night)
- `irradiance = 1000` → `emissive_intensity = 1.0` (full glow)
- `irradiance = 540` → `emissive_intensity = 0.54`

Applied to `animation_hooks.irradiance_material` emissiveIntensity property of every PV array instance. If `irradiance_material` is absent from the registry entry, no material update is applied.

---

## 8. Grid connection visualization

| Condition | Visual |
|---|---|
| `pcc.export_mw > 0` | PCC → substation line: direction outward, width ∝ export_mw / max_export_mw |
| `pcc.import_mw > 0` | Substation → PCC line: direction inward, width ∝ import_mw / max_import_mw (400 MW) |
| Both = 0 | Grid lines hidden |

Grid line colour: green `#10b981`.

---

## 9. Performance constraints

The Gansu site has ~146 Vestas V150-class turbines (615 MW / 4.2 MW per turbine = 146.4).

### 9.1 Instancing

- All turbines of the same `assetId` MUST use a single `InstancedMesh` (per LOD level).
- PV arrays similarly instanced per `assetId`.
- No more than **one** R3F `<Canvas>` created.

### 9.2 LOD levels per turbine

| LOD | Condition (camera distance) | Detail |
|---|---|---|
| LOD0 | < 200 m | Full mesh, rotor blades visible, normal map |
| LOD1 | 200–1000 m | Simplified mesh (~50% polygon reduction), no normal map |
| LOD2 | > 1000 m | Oriented billboard sprite |

### 9.3 Draw call budget

- Turbine field (146 turbines): ≤ **50 draw calls** total (instanced LOD batching).
- Battery bank + substation + terrain: ≤ **20 draw calls**.
- Power-flow lines (all 10 + curtailment + VOLL): ≤ **15 draw calls** (one material per colour).
- **Total scene**: ≤ **100 draw calls** at steady state.

These are enforced in tests via a draw-call counter hook (not a runtime GPU profiler — just counting Three.js render calls in a test renderer).

### 9.4 Telemetry gap handling

If `envStep` is not updated for > 2 × `dt_hours` (i.e. > 2 h simulated cadence; in practice a wall-clock threshold set to 10 s for the test environment): **freeze** current render state. Do not interpolate toward zero. Show stale overlay (§3.2). On reconnect (new `envStep` arrives), unfreeze and update immediately.

---

## 10. Camera & controls

- Default camera: perspective, positioned at site overview angle.
- Orbit controls (via `@react-three/drei`'s `OrbitControls`): enabled; user can rotate/zoom.
- `autoRotate`: disabled by default.
- Camera position is NOT driven by telemetry — it is pure user interaction state.

---

## 11. Integration with `SceneMountPoint`

The `SceneMountPoint` component (from `contracts/frontend/app_shell.md` §7.5) emits `onReady(el: HTMLDivElement)`. The parent route (`SiteView`) forwards `el` to `SiteScene` as the `containerEl` prop.

```typescript
// SiteView.tsx (sketch — app_shell owns the actual component)
function SiteView() {
  const [containerEl, setContainerEl] = React.useState<HTMLDivElement | null>(null);
  return (
    <>
      <SceneMountPoint onReady={setContainerEl} className="scene-pane" />
      {containerEl && (
        <SiteScene
          config={GANSU_SCENE_CONFIG}
          registry={ASSET_REGISTRY}
          containerEl={containerEl}
        />
      )}
    </>
  );
}
```

`SiteScene` must not render anything until `containerEl` is non-null. It must clean up (destroy the R3F canvas) when `containerEl` becomes null or when the component unmounts.

---

## 12. Edge cases and unhappy paths

1. **`envStep === null`** — scene renders, all animated values frozen at initial state, stale overlay shown.
2. **`wind_speed_mps` exactly at cut-in (3.0)** — omega > 0 (turbine starts spinning at v_cutin inclusive, per formula: `(3−3)/(12−3)=0` → omega = 0). Clarification: `v_cutin ≤ v < v_rated` starts the power curve; at exactly `v_cutin`, omega = 0 (no power, no spin).
3. **`wind_speed_mps` exactly at cut-out (25.0)** — omega = 0 (`v >= v_cutout` → off).
4. **`battery.soc` outside [0.2, 0.9]** — clamped to [0, 1] fill (no visual over-extension).
5. **All flows zero** — all power-flow lines hidden; no NaN or division-by-zero in width/speed calc.
6. **`ren_curtailed_mw > 0` and all other flows zero** — curtailment line visible only.
7. **Unknown `assetId` in SiteSceneConfig** — placeholder rendered, no crash, warning logged.
8. **Registry `path` missing (404 on GLB)** — placeholder rendered, no crash.
9. **`registry.json` fails to load** — all instances are placeholders; scene still mounts.
10. **Resize of `containerEl`** — R3F canvas responds to container resize via `ResizeObserver`; no fixed pixel dimensions.
11. **Component unmount** — R3F canvas is disposed; `InstancedMesh` buffers freed; no memory leak.
12. **`irradiance_wm2 > 1000`** — emissive clamped at 1.0; no over-bright artifact.
13. **`load_unserved_mw < 0`** — physically impossible, treat as 0 (defensive; no negative penalty display).
14. **Multiple turbine `assetId` values** — one `InstancedMesh` per unique `assetId`; still within budget.

---

## 13. Deliberate deviations

- **Site-wide lumped telemetry only.** `wind_speed_mps` is a single site value. Per-turbine speed variation is not modeled in the env (§1), so the 3D scene applies the same spin rate to all turbines of all asset types. If per-turbine telemetry is added later, the `TurbineInstance` struct gains an optional `id`-keyed override map.
- **No physics in scene code.** The scene animates values already computed by the env; it does not re-implement §3.1 power-curve logic for display purposes. Spin rate is derived directly from `wind_speed_mps` via the formula in §6.
- **No shadow maps for the turbine field** (draw call budget). Ambient occlusion baked into LOD0 textures; dynamic shadows limited to terrain + battery + substation only.

---

## 14. Out of scope (v1)

- Per-turbine individual spin tracking.
- Gas turbine hall / electrolyzer skid models (§8 assets — defined in `assets_ext`; scene uses `assetId` lookup from registry when those entries exist; rendering is not contracted here).
- Weather particle effects (rain, wind streamlines).
- Night/day skybox transitions (static HDR background only).
- VR/AR mode.
- Camera animations / cinematic flythrough.
