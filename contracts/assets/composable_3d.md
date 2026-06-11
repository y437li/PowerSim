# Contract: §8 Composable 3D Assets

- **Status:** DRAFT — awaiting VERDICT: APPROVE from frontend-reviewer
- **Spec:** REBUILD_SPEC §8.2 (generation models), §8.3 (load archetypes), §8.5 (3D implications)
- **Owner:** 3d-assets-engineer · **Reviewer:** frontend-reviewer
- **Area:** assets
- **Depends on DECISIONS:** D2 (§8 after baseline parity; §8 asset/visual side cleared per D23), D23 (asset/visual side cleared now)
- **Depends on LOCKED:** `assets/3d/registry.json` v1.0.0 (PR #24, LINEAGE LOCKED)

---

## Purpose

Add **9 new GLB models + registry entries** for the §8 composable asset library:
- 1 gas combustion turbine hall (§8.2)
- 2 hydrogen electrolyzer skids — PEM and alkaline (§8.2)
- 6 load archetype buildings (§8.3)

Changes are **purely additive** to `assets/3d/registry.json` (schema v1.0.0 → v1.0.1,
minor bump per the registry LOCK versioning rule). The 4 Gansu parity entries are
**untouched**. No re-LOCK required.

---

## 1. Asset taxonomy and IDs

Asset IDs are derived from REBUILD_SPEC §8's named taxonomy (D23 guardrail). They are
verbatim-usable as config-YAML IDs and satisfy `^[a-z0-9][a-z0-9.-]*$`.

| Asset ID | §8 Section | Asset category | File path |
|---|---|---|---|
| `gas-turbine-30mw` | §8.2 gas combustion | `gas_turbine` | `gas/gas-turbine-30mw.glb` |
| `pem-electrolyzer-20mw` | §8.2 PEM electrolyzer | `electrolyzer` | `electrolyzers/pem-electrolyzer-20mw.glb` |
| `alkaline-electrolyzer-20mw` | §8.2 alkaline electrolyzer | `electrolyzer` | `electrolyzers/alkaline-electrolyzer-20mw.glb` |
| `load-commercial` | §8.3 commercial archetype | `load_building` | `loads/load-commercial.glb` |
| `load-residential` | §8.3 residential archetype | `load_building` | `loads/load-residential.glb` |
| `load-industrial-continuous` | §8.3 industrial_continuous archetype | `load_building` | `loads/load-industrial-continuous.glb` |
| `load-industrial-two-shift` | §8.3 industrial_two_shift archetype | `load_building` | `loads/load-industrial-two-shift.glb` |
| `load-data-center` | §8.3 data_center archetype | `load_building` | `loads/load-data-center.glb` |
| `load-ev-fleet` | §8.3 ev_fleet archetype | `load_building` | `loads/load-ev-fleet.glb` |

The capacity suffix in gas/electrolyzer IDs (e.g. `30mw`, `20mw`) reflects the
**reference params in §8.2**: aeroderivative class P_max 30 MW, electrolyzer P_max 20 MW.
When the §8 env models ship, config YAMLs that compose these assets use these IDs
verbatim.

---

## 2. New `AssetType` values

The following values are added to the `AssetType` union in `src/scene/types.ts`
(additive — existing 7 values unchanged):

| New value | Asset category | `assets/3d/` subdirectory |
|---|---|---|
| `"gas_turbine"` | Gas combustion turbine hall + enclosure | `gas/` |
| `"electrolyzer"` | H₂ electrolyzer skid + pressurised storage tank | `electrolyzers/` |
| `"load_building"` | Load-archetype building / facility | `loads/` |

---

## 3. New animation hooks

The following optional fields are added to `AnimationHooks` in `src/scene/types.ts`
(additive — existing 3 fields unchanged):

```typescript
interface AnimationHooks {
  // existing (unchanged)
  rotor_node?: string;
  soc_fill_mesh?: string;
  irradiance_material?: string;

  // NEW §8 hooks
  h2_fill_mesh?: string;       // H₂ tank mesh — scale.y = h2_fill ∈ [0,1]
  activity_material?: string;  // Load building material — emissiveIntensity = activity ∈ [0,1]
  flame_node?: string;         // Gas turbine exhaust/flame node — visible when P_dispatch > 0
}
```

**Scope note — §3.1–3.3 are forward-spec for the future telemetry-binding PR.**
This PR ships only the `animation_hooks` node-name fields in `registry.json` (so the
scene knows *which mesh/material* to drive). The actual driver functions
(`calcH2Fill`, `calcActivity`, `calcFlameVisible`) and their per-asset telemetry
bindings are deferred to the first PR that adds per-asset H₂/load/dispatch fields to
the LOCKED telemetry schema. Until then, the hooks are wired but inert — meshes render
at their initial GLB pose, no animation applied.

**Deferred obligation (recorded here for the future telemetry-binding PR):**
When `calcH2Fill`, `calcActivity`, and `calcFlameVisible` are implemented, their test
suite MUST cover:
- NaN / Infinity input → defined output (no propagation to the DOM/scene)
- Output clamped to [0, 1] for fill/intensity drivers
- `base_mw == 0` division-by-zero → 0 (activity driver)
- `h2_tank_capacity_kg == 0` division-by-zero → 0 (H₂ fill driver)
- Flame epsilon: `p_dispatch_mw > ε` (analogous to `deriveAlerts` `ALERT_EPSILON`) so
  float noise near zero does not flicker the flame node's visibility

### 3.1 `h2_fill_mesh` mapping (forward-spec)

```
h2_fill = h2_level_kg / h2_tank_capacity_kg    // ∈ [0, 1], clamp defensive
scale.y  = h2_fill                              // analog of calcSocFill for battery
```

- `h2_level_kg = 0` → `h2_fill = 0.0` (empty tank)
- `h2_level_kg = h2_tank_capacity_kg` (2000 kg reference, §8.2) → `h2_fill = 1.0` (full)
- Defensive clamp: if `h2_level_kg < 0` → 0; `> capacity` → 1.

### 3.2 `activity_material` mapping (forward-spec)

```
activity = clamp(current_load_mw / base_mw, 0.0, 1.0)   // load fraction
material.emissiveIntensity = activity
```

- Load = 0 → `activity = 0.0` (building dark / idle)
- Load = base_mw → `activity = 1.0` (building fully lit / active)
- Defensive: `current_load_mw < 0` → 0; division by zero (`base_mw = 0`) → 0.

Same driver pattern as `irradiance_material` for PV arrays.

### 3.3 `flame_node` mapping (forward-spec)

```
visible = p_dispatch_mw > ALERT_EPSILON   // float-safe: no flicker near zero
flame_node.visible = visible
```

- `p_dispatch_mw ≤ ALERT_EPSILON` (turbine off or noise floor) → flame hidden.
- `p_dispatch_mw > ALERT_EPSILON` (any meaningful dispatch) → flame visible.
- No intensity gradation in v1 (binary on/off). `ALERT_EPSILON` value from
  `deriveAlerts` utility (shared constant).

---

## 4. Registry entry specifications

All entries use `"pivot": {"x": 0, "y": 0, "z": 0}` (base-centre origin).
Dimensions are real-world bounding boxes in metres (W×H×D = x×y×z).

### 4.1 Gas turbine hall

```json
"gas-turbine-30mw": {
  "path": "gas/gas-turbine-30mw.glb",
  "type": "gas_turbine",
  "dims_m": { "x": 30, "y": 12, "z": 20 },
  "pivot": { "x": 0, "y": 0, "z": 0 },
  "animation_hooks": {
    "flame_node": "ExhaustFlame"
  }
}
```

Reference: aeroderivative class open-cycle GT, 30 MW nameplate (§8.2). The 30×12×20 m
bounding box represents the engine enclosure + control room footprint.

### 4.2 PEM electrolyzer skid

```json
"pem-electrolyzer-20mw": {
  "path": "electrolyzers/pem-electrolyzer-20mw.glb",
  "type": "electrolyzer",
  "dims_m": { "x": 30, "y": 10, "z": 15 },
  "pivot": { "x": 0, "y": 0, "z": 0 },
  "animation_hooks": {
    "h2_fill_mesh": "H2TankFill"
  }
}
```

Reference: 20 MW PEM system (§8.2). Covers the PEM skid + pressurised H₂ storage vessel
(2000 kg tank capacity per §8.2).

### 4.3 Alkaline electrolyzer skid

```json
"alkaline-electrolyzer-20mw": {
  "path": "electrolyzers/alkaline-electrolyzer-20mw.glb",
  "type": "electrolyzer",
  "dims_m": { "x": 30, "y": 10, "z": 18 },
  "pivot": { "x": 0, "y": 0, "z": 0 },
  "animation_hooks": {
    "h2_fill_mesh": "H2TankFill"
  }
}
```

Slightly wider footprint than PEM (alkaline stacks are larger); otherwise same topology.

### 4.4 Load archetype buildings

All load buildings carry `activity_material: "BuildingLights"`.

| ID | dims_m (x×y×z) | Description |
|---|---|---|
| `load-commercial` | 50×20×40 | Mid-rise commercial block; day-peak load profile |
| `load-residential` | 40×12×40 | Residential cluster; evening-peak load profile |
| `load-industrial-continuous` | 80×25×60 | Heavy industrial plant; flat high load |
| `load-industrial-two-shift` | 80×20×60 | Two-shift plant; on at 06:00–22:00, reduced night |
| `load-data-center` | 50×10×35 | Dense data-center building; flat cooling-dominated |
| `load-ev-fleet` | 40×6×60 | EV fleet charging depot; peaks 18:00–23:00 |

```json
"load-commercial": {
  "path": "loads/load-commercial.glb",
  "type": "load_building",
  "dims_m": { "x": 50, "y": 20, "z": 40 },
  "pivot": { "x": 0, "y": 0, "z": 0 },
  "animation_hooks": { "activity_material": "BuildingLights" }
}
// … (same structure for all 6 archetypes with IDs and dims from the table above)
```

---

## 5. Directory structure

```
assets/3d/
  turbines/              # existing (Gansu parity, untouched)
  pv/                    # existing
  batteries/             # existing
  grid/                  # existing
  site/                  # existing
  effects/               # existing
  gas/                   # NEW: gas turbine hall
    gas-turbine-30mw.glb
  electrolyzers/         # NEW: H₂ electrolyzer skids
    pem-electrolyzer-20mw.glb
    alkaline-electrolyzer-20mw.glb
  loads/                 # NEW: load archetype buildings
    load-commercial.glb
    load-residential.glb
    load-industrial-continuous.glb
    load-industrial-two-shift.glb
    load-data-center.glb
    load-ev-fleet.glb
  registry.json          # updated: schema_version "1.0.1"
```

---

## 6. Schema version and authoritative schema doc update

`assets/3d/registry.json` `schema_version` bumps from `"1.0.0"` to `"1.0.1"`:

- Minor bump (additive entries only — no field removal, rename, or retype).
- No re-LOCK required per registry LOCK versioning rule.
- All existing v1.0.0 consumers continue to work: scene code ignores unknown asset IDs.

**`contracts/assets/registry_schema.md` must also be updated in the implementation PR
(additive, stays in frontend-reviewer gate per D23):**

- §1.1 `AssetType` enum table: add three rows:
  - `"gas_turbine"` | Gas combustion turbine hall + enclosure | `gas/`
  - `"electrolyzer"` | H₂ electrolyzer skid + pressurised storage tank | `electrolyzers/`
  - `"load_building"` | Load-archetype building / facility | `loads/`
- §1 `AssetRegistryEntry` / animation_hooks schema block: add three optional fields:
  - `animation_hooks.h2_fill_mesh` — `string` | opt | Three.js mesh name; `scale.y` = H₂ fill [0,1]
  - `animation_hooks.activity_material` — `string` | opt | Material name; `emissiveIntensity` = load activity [0,1]
  - `animation_hooks.flame_node` — `string` | opt | Node name; `visible` = `p_dispatch > ALERT_EPSILON`
- §4 `Future entries` placeholder note is replaced by §4 `§8 entries (v1.0.1)` listing the 9 IDs.

This keeps `registry_schema.md` as the authoritative reviewed document that `src/scene/types.ts`
mirrors. No field removal or rename → no re-LOCK, but both reviewers should see the update.

---

## 7. Validation requirements

All existing registry validation rules (§5 of `contracts/assets/registry_schema.md`)
apply to the new entries. Additionally:

1. New `AssetType` values (`gas_turbine`, `electrolyzer`, `load_building`) are recognised
   by the `AssetType` union in `src/scene/types.ts` **and** recorded in
   `contracts/assets/registry_schema.md` §1.1.
2. New animation hook field names (`h2_fill_mesh`, `activity_material`, `flame_node`)
   are present in the `AnimationHooks` interface in `src/scene/types.ts` **and** recorded
   in `contracts/assets/registry_schema.md` §1.
3. `resolveAsset(registry, id)` returns a non-null entry for each of the 9 new IDs.
4. `resolveAsset(registry, id)` continues to return correct entries for all 4 Gansu IDs
   (non-regression).
5. All new file paths (`gas/…`, `electrolyzers/…`, `loads/…`) point to files that
   actually exist under `assets/3d/`.
6. GLB stubs are valid binary files (minimum: proper GLB magic header `67 6C 54 46`).
7. `dims_m` x/y/z values are all finite (not Infinity or NaN) — `> 0` alone admits
   `Infinity > 0 === true`; implementation must use `Number.isFinite` in the validator.
8. `pivot` x/y/z values are all finite numbers (not NaN/missing).

---

## 8. Edge cases

1. **Unknown hook field in scene consumer** — scene code uses `animation_hooks.h2_fill_mesh`
   etc.; if the consuming scene version predates these fields (e.g. the v1 scene from PR #7)
   the field is simply absent and no animation is applied. No crash.
2. **Asset used in config but env model not yet implemented** — registry entries are additive;
   their presence does not require the §8 env models to be shipped. The scene shows the GLB
   model with no telemetry-driven animation until the env ships.
3. **Duplicate IDs** — JSON object key uniqueness prevents structural duplicates; validator
   must also check that no new ID collides with an existing Gansu entry.
4. **New type in old consumer** — `resolveAsset` returns the entry; old consumers that
   switch on `type` and hit an unknown case fall through to their default (no crash required
   by this contract — handled by caller).

---

## 9. Out of scope (v1)

- Actual high-fidelity 3D models (GLBs are stub files; placeholder geometry is acceptable).
- Per-instance telemetry binding for H₂ level or load activity (v1 scene is lumped).
- LOD level definitions for new asset types (deferred to future minor version).
- Gas turbine exhaust particle effects, animated flames (binary show/hide only in v1).
- Physics metadata (mass, drag coefficient).
- Additional asset types beyond the 9 listed here.
