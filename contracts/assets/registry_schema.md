# Contract: assets/3d/registry.json schema

- **Status:** DRAFT — pending rl-architect LOCK (shared contract; advisory review by both frontend-reviewer + backend-reviewer)
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

```json
{
  "id": "<string>",
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
| `id` | `string` | ✓ | Verbatim key used in site YAML / SiteSceneConfig. Case-sensitive. Unique within the registry. |
| `path` | `string` | ✓ | Relative to `assets/3d/`. File must exist at `assets/3d/<path>`. Kebab-case GLB: e.g. `turbines/vestas-v150-4.2.glb`. |
| `type` | `AssetType` | ✓ | See §1.1 below. |
| `dims_m.x` | `number > 0` | ✓ | Width in metres (world X axis). |
| `dims_m.y` | `number > 0` | ✓ | Height in metres (world Y axis, up). |
| `dims_m.z` | `number > 0` | ✓ | Depth in metres (world Z axis). |
| `pivot.x/y/z` | `number` | ✓ | Pivot offset from geometry centre in metres. `{x:0,y:0,z:0}` for base-centred origin. |
| `animation_hooks.rotor_node` | `string` | opt | Three.js mesh/group node name within the GLB to spin for wind-driven rotation. |
| `animation_hooks.soc_fill_mesh` | `string` | opt | Mesh whose `scale.y` reflects `calcSocFill` output [0,1]. |
| `animation_hooks.irradiance_material` | `string` | opt | Material name whose `emissiveIntensity` reflects `calcEmissive` output [0,1]. |

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

---

## 2. Registry file format

```json
{
  "schema_version": "1.0.0",
  "entries": [
    { /* AssetRegistryEntry */ },
    ...
  ]
}
```

- `schema_version`: semver. Breaking changes (rename/remove field, type change) → major bump + re-LOCK.
- `entries`: array of `AssetRegistryEntry`; order has no semantic meaning.
- Duplicate IDs are invalid; validator must reject.

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

## 4. Future entries (§8 asset library)

When gas turbines, electrolyzers, and load archetypes from REBUILD_SPEC §8 are added:
- New entries are **additive** (semver minor) — no re-LOCK required.
- Removing or renaming an existing entry is a **breaking change** (semver major) — requires a new rl-architect DECISION + re-LOCK + re-review by both reviewers.
- The IDs in the registry must exactly match the keys in the corresponding `config/asset_*.yaml` files.

---

## 5. Validation requirements

Any tool that reads the registry MUST validate:
1. `schema_version` is present and parses as semver.
2. All `id` values are unique (no duplicates).
3. Each `path` is non-empty and does not contain `..` (path traversal).
4. `dims_m` values are all `> 0`.
5. `type` is one of the `AssetType` enum values.

A message / file that fails validation MUST be rejected with a descriptive error.

---

## 6. Out of scope (v1.0.0)

- LOD level definitions (LOD 0/1/2 paths) — deferred to future minor version.
- Physics metadata (mass, drag coefficient) — not needed for 3D visualization.
- Texture atlas manifests — assets ship with embedded textures.
