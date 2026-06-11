/**
 * tests/frontend/registry_build_copy.test.ts
 * Contract: contracts/frontend/registry_build_copy.md §5 (§T_RBC)
 *
 * Tests for the registry build-copy mechanism:
 *  - registryBuildPlugin shape (name + configResolved hook)
 *  - scripts/copy_registry.js references correct source and dest paths
 *
 * These are structural/shape tests — the content-correctness invariant is already
 * covered by app_integration §T9 (deep-equals ASSET_REGISTRY vs registry.json).
 *
 * Note: RB.1/RB.2 are RED until src/config/registryBuildPlugin.ts is created.
 * RB.3/RB.4 are RED until scripts/copy_registry.js is created.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

// ─── RB.1 / RB.2: Vite plugin shape ─────────────────────────────────────────
// RED until src/config/registryBuildPlugin.ts is created.
describe("RB.1 — registryBuildPlugin.name", () => {
  it("is 'copy-registry'", async () => {
    const { registryBuildPlugin } = await import("../../src/config/registryBuildPlugin");
    expect(registryBuildPlugin.name).toBe("copy-registry");
  });
});

describe("RB.2 — registryBuildPlugin.configResolved", () => {
  it("is a function", async () => {
    const { registryBuildPlugin } = await import("../../src/config/registryBuildPlugin");
    expect(typeof registryBuildPlugin.configResolved).toBe("function");
  });
});

// ─── RB.3 / RB.4: copy script path references ────────────────────────────────
// RED until scripts/copy_registry.js is created.
describe("RB.3 — scripts/copy_registry.js mentions source path", () => {
  it("contains 'assets/3d/registry.json'", () => {
    const scriptPath = resolve(__dirname, "../../scripts/copy_registry.js");
    const content = readFileSync(scriptPath, "utf8");
    expect(content).toContain("assets/3d/registry.json");
  });
});

describe("RB.4 — scripts/copy_registry.js mentions dest path", () => {
  it("contains 'src/config/registryData.json'", () => {
    const scriptPath = resolve(__dirname, "../../scripts/copy_registry.js");
    const content = readFileSync(scriptPath, "utf8");
    expect(content).toContain("src/config/registryData.json");
  });
});

// ─── reviewer (frontend-reviewer): RB.5 — the copy MECHANISM actually works ──
// RB.1–4 are structural (plugin name, hook-is-a-function, script source contains path strings) —
// none execute the copy. §T9 verifies content only indirectly (and only if the plugin/hook ran in
// that test invocation). RB.5 invokes the hook directly and asserts the produced registryData.json
// is byte-equal content to the canonical registry — the behaviour the whole PR exists to provide.
describe("RB.5 (reviewer) — configResolved() copies registry.json → registryData.json (content identical)", () => {
  it("after configResolved(), src/config/registryData.json deep-equals assets/3d/registry.json", async () => {
    const { registryBuildPlugin } = await import("../../src/config/registryBuildPlugin");
    const { readFileSync } = await import("fs");
    // Invoke the plugin's copy hook directly — no Vite/Vitest config wiring needed.
    (registryBuildPlugin.configResolved as () => void)();
    const copied = JSON.parse(readFileSync("src/config/registryData.json", "utf8"));
    const canonical = JSON.parse(readFileSync("assets/3d/registry.json", "utf8"));
    expect(copied).toEqual(canonical);
  });
});
