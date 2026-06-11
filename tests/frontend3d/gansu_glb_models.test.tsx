/**
 * Tests: Gansu GLB models (task #26)
 * Contract: contracts/assets/gansu_glb_models.md
 *
 * RED until implementation creates 4 GLB files at registered paths.
 *
 * These tests cover:
 * 1. File existence at the registry-registered paths
 * 2. Valid GLB v2 binary format (magic + version)
 * 3. File size > 200 bytes (non-stub geometry present)
 * 4. Correct named nodes for animation hooks (Rotor, SOCFillMesh)
 * 5. Correct named material for irradiance hook (PVSurface)
 * 6. glTF JSON structure (asset.version, meshes, accessors)
 * 7. Registry non-regression (Gansu entries in registry.json unchanged)
 * 8. Generation script exists and is executable
 */

import { describe, it, expect } from "vitest";
import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const REPO_ROOT = join(__dirname, "../..");
const ASSETS_3D = join(REPO_ROOT, "assets/3d");

/** Registered Gansu paths from registry.json v1.0.1 (must not be changed). */
const GANSU_GLB_PATHS: Record<string, string> = {
  "vestas-v150-4.2": "turbines/vestas-v150-4.2.glb",
  "trina-vertex-n-670w": "pv/trina-vertex-n-670w.glb",
  "catl-lmp-300mwh": "batteries/catl-lmp-300mwh.glb",
  "pcc-substation-945mw": "grid/pcc-substation-945mw.glb",
};

const GLB_MAGIC = Buffer.from([0x67, 0x6c, 0x54, 0x46]); // "glTF"

/**
 * Parse the JSON chunk from a GLB binary.
 * Returns null if the file is missing or not a valid GLB.
 */
function parseGLBJson(filePath: string): Record<string, unknown> | null {
  if (!existsSync(filePath)) return null;
  const buf = readFileSync(filePath);
  if (buf.length < 20) return null;
  // Verify magic
  if (!buf.slice(0, 4).equals(GLB_MAGIC)) return null;
  // JSON chunk starts at byte 12
  const jsonChunkLength = buf.readUInt32LE(12);
  // chunkType at [16..19] should be 0x4E4F534A ("JSON")
  const chunkType = buf.readUInt32LE(16);
  if (chunkType !== 0x4e4f534a) return null;
  const jsonBytes = buf.slice(20, 20 + jsonChunkLength);
  try {
    return JSON.parse(jsonBytes.toString("utf8").trimEnd()) as Record<
      string,
      unknown
    >;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// 1. File existence
// ---------------------------------------------------------------------------
describe("Gansu GLB files exist at registered paths (contract §1)", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`${id}: file exists at assets/3d/${relPath}`, () => {
      const fullPath = join(ASSETS_3D, relPath);
      expect(existsSync(fullPath)).toBe(true);
    });
  }
});

// ---------------------------------------------------------------------------
// 2. GLB magic bytes (contract §2, rule 1)
// ---------------------------------------------------------------------------
describe("GLB magic bytes 'glTF' (0x67 0x6C 0x54 0x46) at bytes 0–3", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`${id}: first 4 bytes are glTF magic`, () => {
      const fullPath = join(ASSETS_3D, relPath);
      expect(existsSync(fullPath)).toBe(true);
      const buf = readFileSync(fullPath);
      expect(Buffer.compare(buf.slice(0, 4), GLB_MAGIC)).toBe(0);
    });
  }
});

// ---------------------------------------------------------------------------
// 3. GLB version = 2 (contract §2, rule 2)
// ---------------------------------------------------------------------------
describe("GLB version field is 2 (bytes 4–7 LE uint32, contract §2)", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`${id}: GLB version = 2`, () => {
      const fullPath = join(ASSETS_3D, relPath);
      expect(existsSync(fullPath)).toBe(true);
      const buf = readFileSync(fullPath);
      expect(buf.readUInt32LE(4)).toBe(2);
    });
  }
});

// ---------------------------------------------------------------------------
// 4. File size > 200 bytes — confirms real geometry, not a stub (contract §2 rule 5)
// ---------------------------------------------------------------------------
describe("GLB files are larger than 200 bytes (non-stub geometry, contract §2)", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`${id}: file size > 200 bytes`, () => {
      const fullPath = join(ASSETS_3D, relPath);
      expect(existsSync(fullPath)).toBe(true);
      const size = statSync(fullPath).size;
      // Arithmetic: minimal non-trivial box (8 vertices × 12 bytes + 36 indices × 2 bytes
      // + JSON chunk ~150 bytes + headers) ≈ 350 bytes minimum
      expect(size).toBeGreaterThan(200);
    });
  }
});

// ---------------------------------------------------------------------------
// 5. glTF JSON chunk is valid and has asset.version = "2.0" (contract §2 rule 3)
// ---------------------------------------------------------------------------
describe("glTF JSON chunk: valid JSON with asset.version = '2.0' (contract §2)", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`${id}: JSON chunk parses and asset.version = "2.0"`, () => {
      const gltf = parseGLBJson(join(ASSETS_3D, relPath));
      expect(gltf).not.toBeNull();
      const asset = gltf!["asset"] as Record<string, unknown>;
      expect(asset).toBeDefined();
      expect(asset["version"]).toBe("2.0");
    });
  }
});

// ---------------------------------------------------------------------------
// 6. Named node "Rotor" in turbine (contract §3.1, §7 rule 5)
// ---------------------------------------------------------------------------
describe("Wind turbine has node named 'Rotor' (rotor_node hook, contract §3.1)", () => {
  it("vestas-v150-4.2: glTF nodes array contains a node named 'Rotor'", () => {
    const gltf = parseGLBJson(join(ASSETS_3D, GANSU_GLB_PATHS["vestas-v150-4.2"]));
    expect(gltf).not.toBeNull();
    const nodes = gltf!["nodes"] as Array<Record<string, unknown>>;
    expect(Array.isArray(nodes)).toBe(true);
    const names = nodes.map((n) => n["name"]);
    expect(names).toContain("Rotor");
  });

  it("vestas-v150-4.2: glTF nodes array also contains a node named 'Tower'", () => {
    const gltf = parseGLBJson(join(ASSETS_3D, GANSU_GLB_PATHS["vestas-v150-4.2"]));
    expect(gltf).not.toBeNull();
    const nodes = gltf!["nodes"] as Array<Record<string, unknown>>;
    const names = nodes.map((n) => n["name"]);
    expect(names).toContain("Tower");
  });
});

// ---------------------------------------------------------------------------
// 7. Named node "SOCFillMesh" in battery (contract §3.3, §7 rule 6)
// ---------------------------------------------------------------------------
describe("Battery has node named 'SOCFillMesh' (soc_fill_mesh hook, contract §3.3)", () => {
  it("catl-lmp-300mwh: glTF nodes array contains a node named 'SOCFillMesh'", () => {
    const gltf = parseGLBJson(join(ASSETS_3D, GANSU_GLB_PATHS["catl-lmp-300mwh"]));
    expect(gltf).not.toBeNull();
    const nodes = gltf!["nodes"] as Array<Record<string, unknown>>;
    expect(Array.isArray(nodes)).toBe(true);
    const names = nodes.map((n) => n["name"]);
    expect(names).toContain("SOCFillMesh");
  });

  it("catl-lmp-300mwh: glTF nodes array also contains a node named 'Container'", () => {
    const gltf = parseGLBJson(join(ASSETS_3D, GANSU_GLB_PATHS["catl-lmp-300mwh"]));
    expect(gltf).not.toBeNull();
    const nodes = gltf!["nodes"] as Array<Record<string, unknown>>;
    const names = nodes.map((n) => n["name"]);
    expect(names).toContain("Container");
  });
});

// ---------------------------------------------------------------------------
// 8. Named material "PVSurface" in PV array (contract §3.2, §7 rule 7)
// ---------------------------------------------------------------------------
describe("PV array has material named 'PVSurface' (irradiance_material hook, contract §3.2)", () => {
  it("trina-vertex-n-670w: glTF materials array contains a material named 'PVSurface'", () => {
    const gltf = parseGLBJson(join(ASSETS_3D, GANSU_GLB_PATHS["trina-vertex-n-670w"]));
    expect(gltf).not.toBeNull();
    const materials = gltf!["materials"] as Array<Record<string, unknown>>;
    expect(Array.isArray(materials)).toBe(true);
    const names = materials.map((m) => m["name"]);
    expect(names).toContain("PVSurface");
  });
});

// ---------------------------------------------------------------------------
// 9. Each GLB has at least 1 mesh with at least 1 primitive (contract §7 rule 8)
// ---------------------------------------------------------------------------
describe("Each GLB has at least 1 mesh with at least 1 primitive (contract §7)", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`${id}: meshes array has ≥1 mesh with ≥1 primitive`, () => {
      const gltf = parseGLBJson(join(ASSETS_3D, relPath));
      expect(gltf).not.toBeNull();
      const meshes = gltf!["meshes"] as Array<Record<string, unknown>>;
      expect(Array.isArray(meshes)).toBe(true);
      expect(meshes.length).toBeGreaterThanOrEqual(1);
      for (const mesh of meshes) {
        const prims = mesh["primitives"] as unknown[];
        expect(Array.isArray(prims)).toBe(true);
        expect(prims.length).toBeGreaterThanOrEqual(1);
      }
    });
  }
});

// ---------------------------------------------------------------------------
// 10. Accessors confirm geometry is present (contract §2 rule 4 + §7 rule 9)
// ---------------------------------------------------------------------------
describe("Accessors confirm non-trivial geometry (POSITION count ≥ 8, contract §2 rule 4)", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`${id}: at least one POSITION accessor with count ≥ 8`, () => {
      const gltf = parseGLBJson(join(ASSETS_3D, relPath));
      expect(gltf).not.toBeNull();
      const accessors = gltf!["accessors"] as Array<Record<string, unknown>>;
      expect(Array.isArray(accessors)).toBe(true);
      expect(accessors.length).toBeGreaterThanOrEqual(1);
      // At least one accessor must have count >= 8 (8 vertices minimum for a box)
      const maxCount = Math.max(...accessors.map((a) => Number(a["count"] ?? 0)));
      // Arithmetic: box with unique vertices = 8; with per-face normals = 24
      expect(maxCount).toBeGreaterThanOrEqual(8);
    });
  }
});

// ---------------------------------------------------------------------------
// 11. Registry non-regression: Gansu entries in registry.json unchanged
//     (contract §6, §7 rule 11)
// ---------------------------------------------------------------------------
describe("registry.json Gansu entries unchanged (contract §6)", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const registry = require("../../assets/3d/registry.json") as {
    schema_version: string;
    assets: Record<
      string,
      {
        path: string;
        type: string;
        dims_m: { x: number; y: number; z: number };
        pivot: { x: number; y: number; z: number };
        animation_hooks: Record<string, string>;
      }
    >;
  };

  it("vestas-v150-4.2: path, type, dims, pivot, rotor_node unchanged", () => {
    const e = registry.assets["vestas-v150-4.2"];
    expect(e).toBeDefined();
    expect(e.path).toBe("turbines/vestas-v150-4.2.glb");
    expect(e.type).toBe("turbine");
    expect(e.dims_m).toEqual({ x: 150, y: 166, z: 150 });
    expect(e.pivot).toEqual({ x: 0, y: 0, z: 0 });
    expect(e.animation_hooks.rotor_node).toBe("Rotor");
  });

  it("trina-vertex-n-670w: path, type, dims, pivot, irradiance_material unchanged", () => {
    const e = registry.assets["trina-vertex-n-670w"];
    expect(e).toBeDefined();
    expect(e.path).toBe("pv/trina-vertex-n-670w.glb");
    expect(e.type).toBe("pv_array");
    expect(e.dims_m).toEqual({ x: 40, y: 3, z: 20 });
    expect(e.pivot).toEqual({ x: 0, y: 0, z: 0 });
    expect(e.animation_hooks.irradiance_material).toBe("PVSurface");
  });

  it("catl-lmp-300mwh: path, type, dims, pivot, soc_fill_mesh unchanged", () => {
    const e = registry.assets["catl-lmp-300mwh"];
    expect(e).toBeDefined();
    expect(e.path).toBe("batteries/catl-lmp-300mwh.glb");
    expect(e.type).toBe("battery");
    expect(e.dims_m).toEqual({ x: 20, y: 5, z: 60 });
    expect(e.pivot).toEqual({ x: 0, y: 0, z: 0 });
    expect(e.animation_hooks.soc_fill_mesh).toBe("SOCFillMesh");
  });

  it("pcc-substation-945mw: path, type, dims, pivot unchanged", () => {
    const e = registry.assets["pcc-substation-945mw"];
    expect(e).toBeDefined();
    expect(e.path).toBe("grid/pcc-substation-945mw.glb");
    expect(e.type).toBe("grid_pcc");
    expect(e.dims_m).toEqual({ x: 50, y: 15, z: 30 });
    expect(e.pivot).toEqual({ x: 0, y: 0, z: 0 });
  });

  it("schema_version is still '1.0.1' (no bump from GLB additions)", () => {
    expect(registry.schema_version).toBe("1.0.1");
  });
});

// ---------------------------------------------------------------------------
// 12. Generation script exists (contract §4, §7 rule 12)
// ---------------------------------------------------------------------------
describe("Generation script exists at scripts/generate_gansu_glbs.js (contract §4)", () => {
  it("scripts/generate_gansu_glbs.js exists in the repo", () => {
    const scriptPath = join(REPO_ROOT, "scripts/generate_gansu_glbs.js");
    expect(existsSync(scriptPath)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// reviewer: additional edge cases
// ---------------------------------------------------------------------------

// reviewer: GLB length field in header matches actual file size
describe("reviewer: GLB header length field matches actual file size", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`reviewer: ${id}: header totalLength equals file byte length`, () => {
      const fullPath = join(ASSETS_3D, relPath);
      expect(existsSync(fullPath)).toBe(true);
      const buf = readFileSync(fullPath);
      const headerLength = buf.readUInt32LE(8);
      expect(headerLength).toBe(buf.length);
    });
  }
});

// reviewer: JSON chunk length must be a multiple of 4 (GLB alignment rule)
describe("reviewer: GLB JSON chunk length is 4-byte aligned", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`reviewer: ${id}: JSON chunkLength is divisible by 4`, () => {
      const fullPath = join(ASSETS_3D, relPath);
      expect(existsSync(fullPath)).toBe(true);
      const buf = readFileSync(fullPath);
      const jsonChunkLength = buf.readUInt32LE(12);
      // GLB spec §5.1.3: chunkLength must be 4-byte aligned
      expect(jsonChunkLength % 4).toBe(0);
    });
  }
});

// reviewer: BIN chunk present and its length is also 4-byte aligned
describe("reviewer: BIN chunk present and 4-byte aligned", () => {
  for (const [id, relPath] of Object.entries(GANSU_GLB_PATHS)) {
    it(`reviewer: ${id}: BIN chunk (0x42494E00) exists after JSON chunk`, () => {
      const fullPath = join(ASSETS_3D, relPath);
      expect(existsSync(fullPath)).toBe(true);
      const buf = readFileSync(fullPath);
      const jsonChunkLength = buf.readUInt32LE(12);
      const binOffset = 12 + 8 + jsonChunkLength; // header + JSON header + JSON data
      expect(buf.length).toBeGreaterThan(binOffset + 8);
      const binChunkLength = buf.readUInt32LE(binOffset);
      const binChunkType = buf.readUInt32LE(binOffset + 4);
      // 0x004E4942 = "BIN\0"
      expect(binChunkType).toBe(0x004e4942);
      // BIN length also 4-byte aligned
      expect(binChunkLength % 4).toBe(0);
    });
  }
});

// reviewer: substation has at least 1 mesh even with no named hook
describe("reviewer: PCC substation has at least 1 mesh (no hook required but must render)", () => {
  it("pcc-substation-945mw: meshes array has ≥1 entry", () => {
    const gltf = parseGLBJson(join(ASSETS_3D, GANSU_GLB_PATHS["pcc-substation-945mw"]));
    expect(gltf).not.toBeNull();
    const meshes = gltf!["meshes"] as Array<unknown>;
    expect(Array.isArray(meshes)).toBe(true);
    expect(meshes.length).toBeGreaterThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// reviewer (frontend-reviewer): animation-hook targets must be RENDERABLE/animatable,
// not merely present by name. A named node with no mesh (empty group) spins/scales
// nothing; a material no primitive references shows no emissive. These pin §3's
// box-mesh design so the rotor-spin / SOC-fill / irradiance animations actually display.
// ---------------------------------------------------------------------------
describe("reviewer: animation-hook targets reference renderable geometry", () => {
  function findNodeByName(
    gltf: Record<string, unknown>,
    name: string,
  ): Record<string, unknown> | undefined {
    const nodes = (gltf["nodes"] as Array<Record<string, unknown>>) ?? [];
    return nodes.find((n) => n["name"] === name);
  }
  // The hook target must drive a visible mesh: either node.mesh is set, or it has
  // (mesh-bearing) children. An empty node would animate nothing visible.
  function nodeRendersGeometry(node: Record<string, unknown>): boolean {
    if (typeof node["mesh"] === "number") return true;
    const children = node["children"];
    return Array.isArray(children) && children.length > 0;
  }

  it("reviewer: vestas-v150-4.2 'Rotor' node references a mesh (rotor spin must be visible)", () => {
    const gltf = parseGLBJson(join(ASSETS_3D, GANSU_GLB_PATHS["vestas-v150-4.2"]));
    expect(gltf).not.toBeNull();
    const rotor = findNodeByName(gltf!, "Rotor");
    expect(rotor, "'Rotor' node must exist (§3.1)").toBeDefined();
    expect(
      nodeRendersGeometry(rotor!),
      "'Rotor' must reference a mesh or have mesh children — an empty node spins nothing",
    ).toBe(true);
  });

  it("reviewer: catl-lmp-300mwh 'SOCFillMesh' node references a mesh (SOC fill must be visible)", () => {
    const gltf = parseGLBJson(join(ASSETS_3D, GANSU_GLB_PATHS["catl-lmp-300mwh"]));
    expect(gltf).not.toBeNull();
    const fill = findNodeByName(gltf!, "SOCFillMesh");
    expect(fill, "'SOCFillMesh' node must exist (§3.3)").toBeDefined();
    expect(
      nodeRendersGeometry(fill!),
      "'SOCFillMesh' must reference a mesh — scale.y on an empty node shows no SOC fill",
    ).toBe(true);
  });

  it("reviewer: trina-vertex-n-670w 'PVSurface' material is used by ≥1 primitive (emissive must show)", () => {
    const gltf = parseGLBJson(join(ASSETS_3D, GANSU_GLB_PATHS["trina-vertex-n-670w"]));
    expect(gltf).not.toBeNull();
    const materials = (gltf!["materials"] as Array<Record<string, unknown>>) ?? [];
    const pvIdx = materials.findIndex((m) => m["name"] === "PVSurface");
    expect(pvIdx, "'PVSurface' material must exist (§3.2)").toBeGreaterThanOrEqual(0);
    const meshes = (gltf!["meshes"] as Array<Record<string, unknown>>) ?? [];
    const used = meshes.some((mesh) => {
      const prims = (mesh["primitives"] as Array<Record<string, unknown>>) ?? [];
      return prims.some((p) => p["material"] === pvIdx);
    });
    expect(
      used,
      "a mesh primitive must reference 'PVSurface' — an unused material renders no emissive",
    ).toBe(true);
  });
});
