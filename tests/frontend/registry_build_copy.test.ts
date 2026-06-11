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
 * Note: RB.1/RB.2 are RED until scripts/registryBuildPlugin.ts is created.
 * RB.3/RB.4 are RED until scripts/copy_registry.js is created.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { readFileSync, writeFileSync, mkdirSync, rmSync, mkdtempSync } from "fs";
import { resolve, join } from "path";
import { tmpdir } from "os";
import { execSync } from "child_process";

// ─── RB.1 / RB.2: Vite plugin shape ─────────────────────────────────────────
// RED until scripts/registryBuildPlugin.ts is created.
describe("RB.1 — registryBuildPlugin.name", () => {
  it("is 'copy-registry'", async () => {
    const { registryBuildPlugin } = await import("../../scripts/registryBuildPlugin");
    expect(registryBuildPlugin.name).toBe("copy-registry");
  });
});

describe("RB.2 — registryBuildPlugin.configResolved", () => {
  it("is a function", async () => {
    const { registryBuildPlugin } = await import("../../scripts/registryBuildPlugin");
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

// ─── RB.7: copy script and plugin have the existsSync guard (partial-checkout safe) ─
// Guards the CI constraint: builds from sandboxed fixtures without assets/3d/ must not
// abort. Both the script and plugin must have an existsSync check so they fall back to
// the committed copy rather than hard-failing when assets/3d/registry.json is absent.
describe("RB.7 — existsSync guard present in script and plugin (partial-checkout safe)", () => {
  it("scripts/copy_registry.js contains existsSync guard", () => {
    const scriptPath = resolve(__dirname, "../../scripts/copy_registry.js");
    const content = readFileSync(scriptPath, "utf8");
    expect(content).toContain("existsSync");
  });

  it("scripts/registryBuildPlugin.ts contains existsSync guard", () => {
    const pluginPath = resolve(__dirname, "../../scripts/registryBuildPlugin.ts");
    const content = readFileSync(pluginPath, "utf8");
    expect(content).toContain("existsSync");
  });
});

// ─── RB.6: scripts/copy_registry.js actually RUNS (exit 0 + content correct) ──
// RB.5 covers the plugin's configResolved() path — but the script (npm pre-hooks) had
// no functional test. The script uses ESM `import` syntax (required by "type":"module");
// this test confirms it exits 0 and that the output deep-equals the canonical registry.
describe("RB.6 — node scripts/copy_registry.js exits 0 and output matches canonical", () => {
  it("executes without error and src/config/registryData.json deep-equals assets/3d/registry.json", () => {
    // Run the script — execSync throws on non-zero exit, so no throw = exit 0
    execSync("node scripts/copy_registry.js", { stdio: "pipe" });
    const copied = JSON.parse(readFileSync("src/config/registryData.json", "utf8"));
    const canonical = JSON.parse(readFileSync("assets/3d/registry.json", "utf8"));
    expect(copied).toEqual(canonical);
  });
});

// ─── RB.8: copyRegistryIfNeeded — functional three-branch test ───────────────
// Tests all three conditional branches using temp directories so nothing is
// assumed about the real filesystem (no race conditions, no side effects).
describe("RB.8 — copyRegistryIfNeeded: functional three-branch test", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = mkdtempSync(join(tmpdir(), "rbc-test-"));
  });

  afterEach(() => {
    rmSync(tmpDir, { recursive: true, force: true });
  });

  it("branch 1 (source present): copies to dest and returns 'copied'", async () => {
    const { copyRegistryIfNeeded } = await import("../../scripts/registryBuildPlugin");
    const src = join(tmpDir, "registry.json");
    const dest = join(tmpDir, "out", "registryData.json");
    const payload = JSON.stringify({ version: "1.0.0", assets: [] });
    writeFileSync(src, payload);

    const result = copyRegistryIfNeeded(src, dest);
    expect(result).toBe("copied");
    expect(readFileSync(dest, "utf8")).toBe(payload);
  });

  it("branch 2 (source absent, dest exists): no-op, returns 'skipped', dest unchanged", async () => {
    const { copyRegistryIfNeeded } = await import("../../scripts/registryBuildPlugin");
    const src = join(tmpDir, "registry.json"); // intentionally absent
    const dest = join(tmpDir, "registryData.json");
    const fallback = JSON.stringify({ version: "fallback", assets: [] });
    writeFileSync(dest, fallback);

    const result = copyRegistryIfNeeded(src, dest);
    expect(result).toBe("skipped");
    // dest must be unchanged — this is the committed-fallback path
    expect(readFileSync(dest, "utf8")).toBe(fallback);
  });

  it("branch 3 (neither exists): throws", async () => {
    const { copyRegistryIfNeeded } = await import("../../scripts/registryBuildPlugin");
    const src = join(tmpDir, "registry.json");  // absent
    const dest = join(tmpDir, "registryData.json"); // absent
    expect(() => copyRegistryIfNeeded(src, dest)).toThrow(/copy-registry/);
  });
});

// ─── reviewer (frontend-reviewer): RB.5 — the copy MECHANISM actually works ──
// RB.1–4 are structural (plugin name, hook-is-a-function, script source contains path strings) —
// none execute the copy. §T9 verifies content only indirectly (and only if the plugin/hook ran in
// that test invocation). RB.5 invokes the hook directly and asserts the produced registryData.json
// is byte-equal content to the canonical registry — the behaviour the whole PR exists to provide.
describe("RB.5 (reviewer) — configResolved() copies registry.json → registryData.json (content identical)", () => {
  it("after configResolved(), src/config/registryData.json deep-equals assets/3d/registry.json", async () => {
    const { registryBuildPlugin } = await import("../../scripts/registryBuildPlugin");
    const { readFileSync } = await import("fs");
    // Invoke the plugin's copy hook directly — no Vite/Vitest config wiring needed.
    (registryBuildPlugin.configResolved as () => void)();
    const copied = JSON.parse(readFileSync("src/config/registryData.json", "utf8"));
    const canonical = JSON.parse(readFileSync("assets/3d/registry.json", "utf8"));
    expect(copied).toEqual(canonical);
  });
});
