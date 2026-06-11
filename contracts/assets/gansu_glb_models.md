# Contract: Gansu GLB Models

- **Status:** DRAFT — awaiting VERDICT: APPROVE from frontend-reviewer
- **Spec:** REBUILD_SPEC §8.4 (Gansu site), §8.5 (3D asset requirements)
- **Owner:** 3d-assets-engineer · **Reviewer:** frontend-reviewer
- **Area:** assets
- **Depends on LOCKED:** `assets/3d/registry.json` v1.0.1 (PR #38, LINEAGE LOCKED)

---

## Purpose

The four Gansu parity entries in `assets/3d/registry.json` v1.0.1 point to GLB files that
do not exist on disk. The 3D scene loads a black/empty canvas because Three.js
`GLTFLoader` silently 404s on the missing paths. This contract covers creating **visually
meaningful primitive GLB models** at the four registered paths so the scene renders.

---

## 1. Files to create

All four files must exist at their registered path under `assets/3d/`:

| Asset ID | Registered path | Dims (W×H×D m) | Animation hook |
|---|---|---|---|
| `vestas-v150-4.2` | `turbines/vestas-v150-4.2.glb` | 150×166×150 | `rotor_node: "Rotor"` |
| `trina-vertex-n-670w` | `pv/trina-vertex-n-670w.glb` | 40×3×20 | `irradiance_material: "PVSurface"` |
| `catl-lmp-300mwh` | `batteries/catl-lmp-300mwh.glb` | 20×5×60 | `soc_fill_mesh: "SOCFillMesh"` |
| `pcc-substation-945mw` | `grid/pcc-substation-945mw.glb` | 50×15×30 | _(none)_ |

No changes to `registry.json` — the paths are already correct. These are purely additive
file additions in the existing directories.

---

## 2. GLB format requirements

Each file must be a valid **GLB v2** binary:

1. First 4 bytes are the glTF magic `67 6C 54 46` ("glTF").
2. Bytes 4–7 are version `0x00000002` (little-endian uint32 = 2).
3. The file contains a valid JSON chunk (chunkType `0x4E4F534A`) with a well-formed
   glTF 2.0 document (`asset.version = "2.0"`).
4. The JSON chunk contains at least one `mesh` with at least one `primitive` that has
   an `POSITION` attribute accessor with `count ≥ 8` (confirming non-trivial geometry).
5. Total file size > 200 bytes (the 24-byte stubs used for §8 are not sufficient —
   those have no geometry data and will not render anything visible).

---

## 3. Visual geometry requirements

Primitives are acceptable; photorealism is out of scope. Each model is built from
**box mesh primitives** sized proportionally to the registered `dims_m`.

### 3.1 Wind turbine (`vestas-v150-4.2.glb`)

Two-part structure:

| Node name | Shape | Purpose |
|---|---|---|
| `Tower` | Tall box (narrow footprint, full height) | Tower shaft |
| `Rotor` | Flat disc / wide thin box at tower top | Rotor hub + blades |

**Requirement:** the glTF `nodes` array MUST contain a node with `"name": "Rotor"`.
This is the `rotor_node` the scene uses to spin at `omega ∝ wind_speed`.

### 3.2 PV array (`trina-vertex-n-670w.glb`)

Single flat box (wide, very shallow height, 40×3×20 m proportions).

**Requirement:** the glTF `materials` array MUST contain a material with
`"name": "PVSurface"`. This is the `irradiance_material` the scene uses to set
`emissiveIntensity ∝ irradiance`.

Suggested material base color: dark blue (`[0.02, 0.05, 0.25, 1.0]` RGBA).

### 3.3 Battery container (`catl-lmp-300mwh.glb`)

Two-part structure:

| Node name | Shape | Purpose |
|---|---|---|
| `Container` | Outer box (full dims) | Battery enclosure |
| `SOCFillMesh` | Inner box (slightly smaller, same base) | Fill mesh for SOC animation |

**Requirement:** the glTF `nodes` array MUST contain a node with `"name": "SOCFillMesh"`.
The scene drives `scale.y` on this node to reflect battery state of charge.

### 3.4 PCC substation (`pcc-substation-945mw.glb`)

Single box (50×15×30 m proportions). No named-node requirement.

Suggested material base color: grey (`[0.35, 0.35, 0.35, 1.0]` RGBA).

---

## 4. Generation approach

A checked-in script `scripts/generate_gansu_glbs.js` generates all four GLBs. This
ensures the models are reproducible from source and not opaque binary blobs.

The script:
- Runs under Node.js (no browser required).
- Writes GLB v2 binary (header + JSON chunk + BIN chunk) directly using `Buffer`.
- Each GLB uses a single `buffers[0]` with packed position data (Float32, no normals
  in v1 — Three.js renders with default flat shading).
- Named nodes and materials are in the JSON chunk as per §3.

---

## 5. Node.js GLB binary format reference

```
Header (12 bytes):
  [0–3]  magic:   0x67 0x6C 0x54 0x46  ("glTF")
  [4–7]  version: 0x02 0x00 0x00 0x00  (2, LE)
  [8–11] length:  <total file size, LE uint32>

Chunk 0 — JSON (variable):
  [0–3]  chunkLength: <JSON data byte count padded to 4, LE uint32>
  [4–7]  chunkType:   0x4A 0x53 0x4F 0x4E  ("JSON")
  [8..]  chunkData:   UTF-8 JSON, space-padded to 4-byte boundary

Chunk 1 — BIN (variable):
  [0–3]  chunkLength: <binary data byte count padded to 4, LE uint32>
  [4–7]  chunkType:   0x42 0x49 0x4E 0x00  ("BIN\0")
  [8..]  chunkData:   Float32LE vertex positions; UInt16LE indices
```

---

## 6. Registry non-regression

The four Gansu entries in `registry.json` are **unchanged** (IDs, paths, types, dims,
pivots, animation hook node/material names). This contract adds only the GLB files
themselves. No `schema_version` bump — the version is already `"1.0.1"`.

---

## 7. Validation requirements

1. All 4 GLB files exist at `assets/3d/<registered-path>`.
2. GLB magic bytes `67 6C 54 46` at bytes 0–3.
3. GLB version = 2 (bytes 4–7, LE uint32).
4. JSON chunk is valid UTF-8 JSON; `asset.version === "2.0"`.
5. `nodes` array contains at least one entry with `"name": "Rotor"` for the turbine.
6. `nodes` array contains at least one entry with `"name": "SOCFillMesh"` for battery.
7. `materials` array contains at least one entry with `"name": "PVSurface"` for PV.
8. Each model's `meshes` array contains at least 1 mesh with at least 1 primitive.
9. Total accessor count (across all models) ≥ 8 (confirming geometry is present).
10. Each file size > 200 bytes (no empty stubs).
11. `resolveAsset(registry, id)` still returns the same entries for all 4 Gansu IDs
    (non-regression — registry.json must not be modified).
12. The generation script `scripts/generate_gansu_glbs.js` exits 0 when run with
    `node scripts/generate_gansu_glbs.js` and re-produces identical files.

---

## 8. Browser render requirement

After implementation, the scene must render a non-black canvas in a browser with the
Gansu site config. Verification is **manual** in v1 (no automated browser 3D test):
run `npm run dev`, navigate to the site view, confirm the four asset types are visible
as primitive shapes.

---

## 9. Out of scope

- High-fidelity or textured models.
- Normal vectors on geometry (flat shading is acceptable in v1).
- UV coordinates / texture atlases.
- LOD levels.
- Animations baked into the GLB (driven at runtime from telemetry, not via glTF animation tracks).
- Physics or collision geometry.
