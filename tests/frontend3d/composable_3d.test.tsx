/**
 * tests/frontend3d/composable_3d.test.tsx
 *
 * Contract-gated test suite for §8 composable 3D assets.
 * Contract: contracts/assets/composable_3d.md
 *
 * All tests are RED until implementation adds:
 *   1. 9 new entries to assets/3d/registry.json (schema_version → "1.0.1")
 *   2. New AssetType values in src/scene/types.ts
 *   3. New AnimationHooks fields in src/scene/types.ts
 *   4. Stub GLB files in assets/3d/gas/, electrolyzers/, loads/
 *
 * Spec refs: REBUILD_SPEC §8.2 (generation models), §8.3 (load archetypes), §8.5 (3D)
 * Decision refs: D2 (§8 after baseline parity), D23 (asset/visual side cleared)
 * Registry: assets/3d/registry.json LOCKED v1.0.0 (PR #24); this PR is additive → v1.0.1
 *
 * Reviewer-added cases are marked: // reviewer: <reason>
 */

import { describe, it, expect } from "vitest";
import { existsSync } from "node:fs";
import { resolve, join } from "node:path";

// Import the live registry.json — RED until the 9 new entries are added.
import registry from "../../assets/3d/registry.json";

// Import types — RED until new AssetType values and AnimationHooks fields are added.
import type { AssetRegistry, AssetRegistryEntry, AnimationHooks } from "../../src/scene/types";

// Import resolveAsset — already implemented in PR #7.
import { resolveAsset } from "../../src/scene/registry";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** The 9 new §8 composable asset IDs (contract §1). */
const NEW_ASSET_IDS = [
  "gas-turbine-30mw",
  "pem-electrolyzer-20mw",
  "alkaline-electrolyzer-20mw",
  "load-commercial",
  "load-residential",
  "load-industrial-continuous",
  "load-industrial-two-shift",
  "load-data-center",
  "load-ev-fleet",
] as const;

/** The 4 Gansu parity IDs that must remain untouched (non-regression). */
const GANSU_ASSET_IDS = [
  "vestas-v150-4.2",
  "trina-vertex-n-670w",
  "catl-lmp-300mwh",
  "pcc-substation-945mw",
] as const;

/** ID key format from registry LOCK. */
const ID_FORMAT = /^[a-z0-9][a-z0-9.-]*$/;

/** Root of assets/3d/, resolved from repo root. */
const ASSETS_3D = resolve(__dirname, "../../assets/3d");

// Cast registry to the typed interface for compile-time checks.
const typedRegistry: AssetRegistry = registry as unknown as AssetRegistry;

// ---------------------------------------------------------------------------
// 1. Schema version
// ---------------------------------------------------------------------------
describe("registry.json schema_version", () => {
  it("schema_version is '1.0.1' after additive bump (contract §6)", () => {
    // Minor bump: additive entries only → 1.0.0 → 1.0.1 (no re-LOCK needed)
    expect(typedRegistry.schema_version).toBe("1.0.1");
  });

  it("schema_version is non-empty and semver-shaped", () => {
    // Must be parseable as semver
    expect(typedRegistry.schema_version).toMatch(/^\d+\.\d+\.\d+$/);
  });
});

// ---------------------------------------------------------------------------
// 2. Gansu parity entries — non-regression
// ---------------------------------------------------------------------------
describe("Gansu parity entries (non-regression, contract §1)", () => {
  for (const id of GANSU_ASSET_IDS) {
    it(`'${id}' still resolves correctly after the additive bump`, () => {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry).not.toBeNull();
      expect(entry!.id).toBe(id);
    });
  }

  it("all 4 Gansu entries have their original fields unchanged", () => {
    // vestas-v150-4.2: turbine, 150×166×150 m, rotor_node=Rotor
    const vestas = resolveAsset(typedRegistry, "vestas-v150-4.2");
    expect(vestas!.type).toBe("turbine");
    expect(vestas!.dims_m).toEqual({ x: 150, y: 166, z: 150 });
    expect(vestas!.animation_hooks?.rotor_node).toBe("Rotor");

    // catl-lmp-300mwh: battery, 20×5×60 m, soc_fill_mesh=SOCFillMesh
    const catl = resolveAsset(typedRegistry, "catl-lmp-300mwh");
    expect(catl!.type).toBe("battery");
    expect(catl!.dims_m).toEqual({ x: 20, y: 5, z: 60 });
    expect(catl!.animation_hooks?.soc_fill_mesh).toBe("SOCFillMesh");
  });
});

// ---------------------------------------------------------------------------
// 3. New entry presence
// ---------------------------------------------------------------------------
describe("new §8 entries are present in registry (contract §1)", () => {
  for (const id of NEW_ASSET_IDS) {
    it(`resolveAsset returns a non-null entry for '${id}'`, () => {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry).not.toBeNull();
      expect(entry!.id).toBe(id);
    });
  }

  it("registry now has 13 total entries (4 Gansu + 9 new §8)", () => {
    // 4 Gansu parity + 9 composable = 13
    expect(Object.keys(typedRegistry.assets)).toHaveLength(13);
  });
});

// ---------------------------------------------------------------------------
// 4. Asset ID format compliance
// ---------------------------------------------------------------------------
describe("asset ID format compliance — ^[a-z0-9][a-z0-9.-]*$ (registry LOCK)", () => {
  for (const id of NEW_ASSET_IDS) {
    it(`'${id}' matches the LOCKED key format`, () => {
      expect(id).toMatch(ID_FORMAT);
    });
  }

  // reviewer: IDs must also not have trailing dots or hyphens
  it("no new ID ends with '.' or '-'", () => {
    for (const id of NEW_ASSET_IDS) {
      expect(id).not.toMatch(/[.-]$/);
    }
  });
});

// ---------------------------------------------------------------------------
// 5. AssetType values for new entries
// ---------------------------------------------------------------------------
describe("new AssetType values (contract §2)", () => {
  it("gas-turbine-30mw has type 'gas_turbine'", () => {
    const entry = resolveAsset(typedRegistry, "gas-turbine-30mw");
    expect(entry!.type).toBe("gas_turbine");
  });

  it("pem-electrolyzer-20mw has type 'electrolyzer'", () => {
    const entry = resolveAsset(typedRegistry, "pem-electrolyzer-20mw");
    expect(entry!.type).toBe("electrolyzer");
  });

  it("alkaline-electrolyzer-20mw has type 'electrolyzer'", () => {
    const entry = resolveAsset(typedRegistry, "alkaline-electrolyzer-20mw");
    expect(entry!.type).toBe("electrolyzer");
  });

  it("all 6 load archetype entries have type 'load_building'", () => {
    const loadIds = NEW_ASSET_IDS.filter((id) => id.startsWith("load-"));
    expect(loadIds).toHaveLength(6);
    for (const id of loadIds) {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry!.type).toBe("load_building");
    }
  });
});

// ---------------------------------------------------------------------------
// 6. Animation hooks for new entries
// ---------------------------------------------------------------------------
describe("animation hooks on new entries (contract §3)", () => {
  it("gas-turbine-30mw has flame_node='ExhaustFlame'", () => {
    const entry = resolveAsset(typedRegistry, "gas-turbine-30mw");
    expect(entry!.animation_hooks?.flame_node).toBe("ExhaustFlame");
  });

  it("pem-electrolyzer-20mw has h2_fill_mesh='H2TankFill'", () => {
    const entry = resolveAsset(typedRegistry, "pem-electrolyzer-20mw");
    expect(entry!.animation_hooks?.h2_fill_mesh).toBe("H2TankFill");
  });

  it("alkaline-electrolyzer-20mw has h2_fill_mesh='H2TankFill'", () => {
    const entry = resolveAsset(typedRegistry, "alkaline-electrolyzer-20mw");
    expect(entry!.animation_hooks?.h2_fill_mesh).toBe("H2TankFill");
  });

  it("all 6 load archetype entries have activity_material='BuildingLights'", () => {
    const loadIds = NEW_ASSET_IDS.filter((id) => id.startsWith("load-"));
    for (const id of loadIds) {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry!.animation_hooks?.activity_material).toBe("BuildingLights");
    }
  });

  // reviewer: new hooks must NOT appear on existing Gansu entries (no cross-contamination)
  it("Gansu entries do not have new §8 animation hooks", () => {
    for (const id of GANSU_ASSET_IDS) {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry!.animation_hooks).not.toHaveProperty("h2_fill_mesh");
      expect(entry!.animation_hooks).not.toHaveProperty("activity_material");
      expect(entry!.animation_hooks).not.toHaveProperty("flame_node");
    }
  });
});

// ---------------------------------------------------------------------------
// 7. Registry entry dimensions (contract §4)
// ---------------------------------------------------------------------------
describe("registry entry dimensions are positive numbers (contract §4)", () => {
  for (const id of NEW_ASSET_IDS) {
    it(`'${id}' has all dims_m > 0`, () => {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry!.dims_m.x).toBeGreaterThan(0);
      expect(entry!.dims_m.y).toBeGreaterThan(0);
      expect(entry!.dims_m.z).toBeGreaterThan(0);
    });
  }

  it("gas-turbine-30mw dims are 30×12×20 m (§8.2 reference params)", () => {
    // 30 MW aeroderivative GT hall footprint: 30 m length × 12 m height × 20 m width
    const entry = resolveAsset(typedRegistry, "gas-turbine-30mw");
    expect(entry!.dims_m).toEqual({ x: 30, y: 12, z: 20 });
  });

  it("pem-electrolyzer-20mw dims are 30×10×15 m (§8.2 20 MW system + H₂ tank)", () => {
    const entry = resolveAsset(typedRegistry, "pem-electrolyzer-20mw");
    expect(entry!.dims_m).toEqual({ x: 30, y: 10, z: 15 });
  });

  it("alkaline-electrolyzer-20mw dims are 30×10×18 m (slightly wider than PEM)", () => {
    const entry = resolveAsset(typedRegistry, "alkaline-electrolyzer-20mw");
    expect(entry!.dims_m).toEqual({ x: 30, y: 10, z: 18 });
  });
});

// ---------------------------------------------------------------------------
// 8. File paths (contract §5)
// ---------------------------------------------------------------------------
describe("file paths follow contract §5 directory structure", () => {
  it("gas-turbine-30mw path is 'gas/gas-turbine-30mw.glb'", () => {
    expect(resolveAsset(typedRegistry, "gas-turbine-30mw")!.path).toBe(
      "gas/gas-turbine-30mw.glb"
    );
  });

  it("pem-electrolyzer-20mw path is 'electrolyzers/pem-electrolyzer-20mw.glb'", () => {
    expect(resolveAsset(typedRegistry, "pem-electrolyzer-20mw")!.path).toBe(
      "electrolyzers/pem-electrolyzer-20mw.glb"
    );
  });

  it("all load archetype paths are under 'loads/'", () => {
    const loadIds = NEW_ASSET_IDS.filter((id) => id.startsWith("load-"));
    for (const id of loadIds) {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry!.path).toMatch(/^loads\//);
    }
  });

  it("no path contains '..' (path traversal guard, registry schema §5 rule 5)", () => {
    for (const id of [...NEW_ASSET_IDS, ...GANSU_ASSET_IDS]) {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry!.path).not.toContain("..");
    }
  });

  // reviewer: path must end in .glb (all §8 assets are GLB models)
  it("all new paths end in '.glb'", () => {
    for (const id of NEW_ASSET_IDS) {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry!.path).toMatch(/\.glb$/);
    }
  });
});

// ---------------------------------------------------------------------------
// 9. GLB stub files exist on disk (contract §7 rule 5)
// ---------------------------------------------------------------------------
describe("stub GLB files exist at the specified paths (contract §7)", () => {
  for (const id of NEW_ASSET_IDS) {
    it(`assets/3d/${resolveAsset({ schema_version: "1.0.1", assets: registry.assets as never } as AssetRegistry, id)?.path ?? id} exists`, () => {
      const entry = resolveAsset(typedRegistry, id);
      // entry is null until implementation; existsSync check enforces file creation
      expect(entry).not.toBeNull();
      const fullPath = join(ASSETS_3D, entry!.path);
      expect(existsSync(fullPath)).toBe(true);
    });
  }

  // reviewer: GLB stubs must have the correct magic header (contract §7 rule 6)
  it("all new GLB stub files start with GLB magic bytes 'glTF' (0x67 0x6C 0x54 0x46)", () => {
    const GLB_MAGIC = Buffer.from([0x67, 0x6C, 0x54, 0x46]);
    for (const id of NEW_ASSET_IDS) {
      const entry = resolveAsset(typedRegistry, id);
      if (!entry) continue; // RED guard — fails at entry check above already
      const fullPath = join(ASSETS_3D, entry.path);
      if (!existsSync(fullPath)) continue; // RED guard
      const { readFileSync } = require("node:fs");
      const header = readFileSync(fullPath).slice(0, 4);
      expect(Buffer.compare(header, GLB_MAGIC)).toBe(0);
    }
  });
});

// ---------------------------------------------------------------------------
// 10. resolveAsset edge cases for new IDs
// ---------------------------------------------------------------------------
describe("resolveAsset correctness for new IDs", () => {
  it("returns null for a partial match of a new ID (no prefix matching)", () => {
    // 'gas-turbine' is a prefix of 'gas-turbine-30mw' — must NOT match
    expect(resolveAsset(typedRegistry, "gas-turbine")).toBeNull();
  });

  it("returns null for case-variant of a new ID", () => {
    expect(resolveAsset(typedRegistry, "Gas-Turbine-30MW")).toBeNull();
    expect(resolveAsset(typedRegistry, "PEM-Electrolyzer-20MW")).toBeNull();
  });

  it("returns null for an unknown §8 ID not in the contract", () => {
    expect(resolveAsset(typedRegistry, "load-hospital")).toBeNull();
  });

  // reviewer: resolveAsset returns the injected id string on the returned object
  it("returned entry.id equals the lookup key for each new asset", () => {
    for (const id of NEW_ASSET_IDS) {
      const entry = resolveAsset(typedRegistry, id);
      if (!entry) continue; // RED guard
      expect(entry.id).toBe(id);
    }
  });
});

// ---------------------------------------------------------------------------
// 11. TypeScript type-level checks for new AnimationHooks fields
// ---------------------------------------------------------------------------
describe("AnimationHooks interface has new §8 hook fields (contract §3)", () => {
  // These compile-time checks verify the interface exists with the right shape.
  // If the interface doesn't have these fields, TypeScript compilation fails,
  // and the test file itself is RED (import type fails).

  it("h2_fill_mesh is a valid optional string field on AnimationHooks", () => {
    const hooks: AnimationHooks = { h2_fill_mesh: "H2TankFill" };
    expect(hooks.h2_fill_mesh).toBe("H2TankFill");
  });

  it("activity_material is a valid optional string field on AnimationHooks", () => {
    const hooks: AnimationHooks = { activity_material: "BuildingLights" };
    expect(hooks.activity_material).toBe("BuildingLights");
  });

  it("flame_node is a valid optional string field on AnimationHooks", () => {
    const hooks: AnimationHooks = { flame_node: "ExhaustFlame" };
    expect(hooks.flame_node).toBe("ExhaustFlame");
  });

  it("all 6 AnimationHooks fields can coexist (no mutual exclusion)", () => {
    const hooks: AnimationHooks = {
      rotor_node: "Rotor",
      soc_fill_mesh: "SOCFillMesh",
      irradiance_material: "PVSurface",
      h2_fill_mesh: "H2TankFill",
      activity_material: "BuildingLights",
      flame_node: "ExhaustFlame",
    };
    expect(Object.keys(hooks)).toHaveLength(6);
  });

  // reviewer: empty AnimationHooks ({}) is valid for assets with no driven animation
  it("AnimationHooks can be an empty object (all hooks optional)", () => {
    const hooks: AnimationHooks = {};
    expect(Object.keys(hooks)).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// reviewer: in-scope edge cases added at the contract+tests gate (frontend-reviewer, PR #38)
//   - pivot present & finite (schema requires pivot.x/y/z; NaN/missing breaks placement)
//   - dims_m FINITE (the existing `> 0` check admits Infinity: Infinity > 0 === true)
//   - new IDs disjoint from the 4 LOCKED Gansu IDs (§8 edge case 3 — no collision)
//   - each new entry uses one of the 3 NEW §8 AssetType values (no stray legacy type)
// ---------------------------------------------------------------------------
describe("reviewer: new §8 registry-metadata robustness", () => {
  // reviewer: every new entry must carry a finite, base-centred pivot (contract §4)
  for (const id of NEW_ASSET_IDS) {
    it(`reviewer: '${id}' has a finite, base-centre pivot {0,0,0} (contract §4)`, () => {
      const entry = resolveAsset(typedRegistry, id);
      expect(entry).not.toBeNull();
      const p = entry!.pivot;
      expect(Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.z)).toBe(true);
      expect(p).toEqual({ x: 0, y: 0, z: 0 });
    });
  }

  // reviewer: dims must be FINITE — `> 0` alone passes Infinity (Infinity > 0 === true),
  // which would blow up bounding-box / placement math in the scene.
  for (const id of NEW_ASSET_IDS) {
    it(`reviewer: '${id}' dims_m are finite (Infinity/NaN must not slip past the >0 check)`, () => {
      const d = resolveAsset(typedRegistry, id)!.dims_m;
      expect(Number.isFinite(d.x)).toBe(true);
      expect(Number.isFinite(d.y)).toBe(true);
      expect(Number.isFinite(d.z)).toBe(true);
    });
  }

  // reviewer: no new ID may collide with a LOCKED Gansu ID (§8 edge case 3) — sets are disjoint
  it("reviewer: new §8 IDs are disjoint from the 4 LOCKED Gansu IDs (no collision)", () => {
    const gansu = new Set<string>(GANSU_ASSET_IDS as readonly string[]);
    for (const id of NEW_ASSET_IDS) {
      expect(gansu.has(id)).toBe(false);
    }
  });

  // reviewer: each new entry's type is one of the 3 NEW §8 values — guards against a new entry
  // accidentally carrying a legacy/Gansu AssetType.
  it("reviewer: each new entry uses one of the 3 new §8 AssetType values", () => {
    const allowed = new Set<string>(["gas_turbine", "electrolyzer", "load_building"]);
    for (const id of NEW_ASSET_IDS) {
      expect(allowed.has(resolveAsset(typedRegistry, id)!.type as string)).toBe(true);
    }
  });
});
