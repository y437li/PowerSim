# Contract: assets/3d/registry.json schema

- **Status:** LOCKED (2026-06-10, PR #24 + lock PR) — rl-architect LOCK on `assets/3d/registry.json` v1.0.0. Additive entries (new GLB models) are minor bumps; field removal/rename/retype is breaking → superseding DECISION + re-LOCK + re-review by both reviewers.
- **Owner:** 3d-assets-engineer (schema); rl-architect (LOCK authority)
- **Reviewers:** frontend-reviewer (scene consumer), backend-reviewer (config YAML producer — asset IDs must match)
- **Area:** assets (shared)
- **Lock target:** `assets/3d/registry.json` v1.0.0

---

## Purpose

`assets/3d/registry.json` is the **single source of truth** that maps config-YAML asset IDs to:
- file paths under `assets/3d/`
- real-world dimensions and pivot offsets
- Three.js node names for driven animations (rotor, SOC fill mesh, PV emissive material)

**Hard rules (from CLAUDE.md §3D assets):**
1. ALL assets live under `assets/3d/` allocated by function (`turbines/`, `pv/`, `batteries/`, `grid/`, `site/`, `effects/`).
2. Scene code NEVER hardcodes an asset path — it resolves exclusively through `resolveAsset(registry, assetId)`.
3. Swapping an asset in the site YAML changes the scene with zero code edits.

---

## 1. Schema — `AssetRegistryEntry`

Each entry is the **value** in the `assets` map (see §2). The map key IS the asset ID — there is no redundant `id` field inside the entry.

```json
{
  "path": "<string — relative to assets/3d/>",
  "type": "<AssetType>",
  "dims_m": { "x": "<number>", "y": "<number>", "z": "<number>" },
  "pivot": { "x": "<number>", "y": "<number>", "z": "<number>" },
  "animation_hooks": {
    "rotor_node": "<string — optional>",
    "soc_fill_mesh": "<string — optional>",
    "irradiance_material": "<string — optional>"
  }
}
```

### Field definitions

| Field | Type | Required | Description |
|---|---|---|---|
| _(map key)_ | `string` | ✓ | The asset ID — verbatim key used in site YAML / SiteSceneConfig. Case-sensitive. Must match `^[a-z0-9][a-z0-9.-]*$`. Uniqueness is structural (JSON object keys). |
| `path` | `string` | ✓ | Relative to `assets/3d/`. File must exist at `assets/3d/<path>`. Kebab-case GLB: e.g. `turbines/vestas-v150-4.2.glb`. |
| `type` | `AssetType` | ✓ | See §1.1 below. |
| `dims_m.x` | `number > 0` | ✓ | Width in metres (world X axis). |
| `dims_m.y` | `number > 0` | ✓ | Height in metres (world Y axis, up). |
| `dims_m.z` | `number > 0` | ✓ | Depth in metres (world Z axis). |
| `pivot.x/y/z` | `number` | ✓ | Pivot offset from geometry centre in metres. `{x:0,y:0,z:0}` for base-centred origin. |
| `animation_hooks.rotor_node` | `string` | opt | Three.js mesh/group node name within the GLB to spin for wind-driven rotation. |
| `animation_hooks.soc_fill_mesh` | `string` | opt | Mesh whose `scale.y` reflects `calcSocFill` output [0,1]. |
| `animation_hooks.irradiance_material` | `string` | opt | Material name whose `emissiveIntensity` reflects `calcEmissive` output [0,1]. |
| `animation_hooks.h2_fill_mesh` | `string` | opt | Mesh whose `scale.y` = `h2_level_kg / h2_tank_capacity_kg` ∈ [0,1] (forward-spec v1.0.1). |
| `animation_hooks.activity_material` | `string` | opt | Material whose `emissiveIntensity` = `current_load_mw / base_mw` ∈ [0,1] (forward-spec v1.0.1). |
| `animation_hooks.flame_node` | `string` | opt | Node whose `visible` = `p_dispatch_mw > ALERT_EPSILON` (forward-spec v1.0.1). |

### 1.1 `AssetType` enum

| Value | Asset category | `assets/3d/` subdirectory |
|---|---|---|
| `"turbine"` | Wind turbine (nacelle + tower + rotor) | `turbines/` |
| `"pv_array"` | Photovoltaic panel array | `pv/` |
| `"battery"` | Battery energy storage container | `batteries/` |
| `"grid_pcc"` | Point of Common Coupling substation | `grid/` |
| `"grid_connection"` | Generic grid connection element (pylons, switchgear) | `grid/` |
| `"site_element"` | Site infrastructure (terrain, buildings, roads) | `site/` |
| `"effect"` | Visual effect material / shader (power-flow tubes etc.) | `effects/` |
| `"gas_turbine"` | Gas combustion turbine hall + enclosure | `gas/` |
| `"electrolyzer"` | H₂ electrolyzer skid + pressurised storage tank | `electrolyzers/` |
| `"load_building"` | Load-archetype building / facility | `loads/` |

_Rows 8–10 added in v1.0.1 (contracts/assets/composable_3d.md, PR #38). Additive — no re-LOCK required._

---

## 2. Registry file format

```json
{
  "schema_version": "1.0.0",
  "assets": {
    "<asset-id>": { /* AssetRegistryEntry — no id field inside */ },
    "<asset-id>": { /* ... */ }
  }
}
```

- `schema_version`: semver. Breaking changes (rename/remove field, type change, array→object) → major bump + re-LOCK.
- `assets`: object keyed by asset ID. Key uniqueness is enforced structurally by JSON object semantics.
- Key format: each key MUST match `^[a-z0-9][a-z0-9.-]*$` (lowercase alphanumeric, dots and hyphens allowed after the first character).
- `resolveAsset(registry, id)` is O(1): `registry.assets[id] ?? null`.
- **Binding invariant (CLAUDE.md):** `assets.<key>` == `entry.id` == config YAML asset ID — verbatim, case-sensitive.

---

## 3. Gansu parity entries (v1.0.0)

These four entries are the minimum needed for the Gansu site config (REBUILD_SPEC §8.4, D2). The IDs are **locked** — they are used verbatim in `tests/frontend3d/site_scene.test.tsx` (approved by frontend-reviewer, PR #7) and in `config/site_gansu.yaml`.

| ID | Type | File | Dims (W×H×D m) | Animation hook |
|---|---|---|---|---|
| `vestas-v150-4.2` | `turbine` | `turbines/vestas-v150-4.2.glb` | 150×166×150 | `rotor_node: "Rotor"` |
| `trina-vertex-n-670w` | `pv_array` | `pv/trina-vertex-n-670w.glb` | 40×3×20 | `irradiance_material: "PVSurface"` |
| `catl-lmp-300mwh` | `battery` | `batteries/catl-lmp-300mwh.glb` | 20×5×60 | `soc_fill_mesh: "SOCFillMesh"` |
| `pcc-substation-945mw` | `grid_pcc` | `grid/pcc-substation-945mw.glb` | 50×15×30 | _(none)_ |

---

## 4. §8 entries (v1.0.1)

Added in `schema_version` `"1.0.1"` (contracts/assets/composable_3d.md, PR #38).
All 9 IDs satisfy `^[a-z0-9][a-z0-9.-]*$` and are verbatim config-YAML usable.

| ID | Type | File | Dims (W×H×D m) | Animation hook |
|---|---|---|---|---|
| `gas-turbine-30mw` | `gas_turbine` | `gas/gas-turbine-30mw.glb` | 30×12×20 | `flame_node: "ExhaustFlame"` |
| `pem-electrolyzer-20mw` | `electrolyzer` | `electrolyzers/pem-electrolyzer-20mw.glb` | 30×10×15 | `h2_fill_mesh: "H2TankFill"` |
| `alkaline-electrolyzer-20mw` | `electrolyzer` | `electrolyzers/alkaline-electrolyzer-20mw.glb` | 30×10×18 | `h2_fill_mesh: "H2TankFill"` |
| `load-commercial` | `load_building` | `loads/load-commercial.glb` | 50×20×40 | `activity_material: "BuildingLights"` |
| `load-residential` | `load_building` | `loads/load-residential.glb` | 40×12×40 | `activity_material: "BuildingLights"` |
| `load-industrial-continuous` | `load_building` | `loads/load-industrial-continuous.glb` | 80×25×60 | `activity_material: "BuildingLights"` |
| `load-industrial-two-shift` | `load_building` | `loads/load-industrial-two-shift.glb` | 80×20×60 | `activity_material: "BuildingLights"` |
| `load-data-center` | `load_building` | `loads/load-data-center.glb` | 50×10×35 | `activity_material: "BuildingLights"` |
| `load-ev-fleet` | `load_building` | `loads/load-ev-fleet.glb` | 40×6×60 | `activity_material: "BuildingLights"` |

Versioning rules remain:
- New entries are **additive** (semver minor) — no re-LOCK required.
- Removing or renaming an existing entry is a **breaking change** (semver major) — requires a new rl-architect DECISION + re-LOCK + re-review by both reviewers.
- IDs in the registry must exactly match keys in the corresponding `config/asset_*.yaml` files.

---

## 5. Validation requirements

Any tool that reads the registry MUST validate:
1. `schema_version` is present and parses as semver.
2. `assets` is a non-null object (not an array).
3. Each key in `assets` matches `^[a-z0-9][a-z0-9.-]*$` (key-format check).
4. Key uniqueness is structural; parsers that silently drop duplicate JSON keys MUST be treated as invalid input at the loader level.
5. Each `path` is non-empty and does not contain `..` (path traversal).
6. `dims_m` values are all `> 0`.
7. `type` is one of the `AssetType` enum values.

A file that fails any check MUST be rejected with a descriptive error (no silent fallback).

---

## 6. Out of scope (v1.0.0)

- LOD level definitions (LOD 0/1/2 paths) — deferred to future minor version.
- Physics metadata (mass, drag coefficient) — not needed for 3D visualization.
- Texture atlas manifests — assets ship with embedded textures.
