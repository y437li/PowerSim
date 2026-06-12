/**
 * Tests for contracts/frontend/root_config_consolidation.md (task #62)
 *
 * Structural tests that verify the 9→6 root config file migration completed
 * correctly. These tests are FILESYSTEM-BASED (no React, no DOM) and run
 * in a Node environment via Vitest.
 *
 * Tests FAIL until implementation — correct at contract+tests gate stage.
 *
 * All paths are resolved relative to the repo root (two levels up from
 * tests/frontend/).
 */
import { describe, it, expect } from "vitest";
import * as fs from "fs";
import * as path from "path";

const REPO_ROOT = path.resolve(__dirname, "../../");

function exists(relPath: string): boolean {
  return fs.existsSync(path.join(REPO_ROOT, relPath));
}

function readFile(relPath: string): string {
  return fs.readFileSync(path.join(REPO_ROOT, relPath), "utf8");
}

function readJson(relPath: string): Record<string, unknown> {
  return JSON.parse(readFile(relPath));
}

// ---------------------------------------------------------------------------
// 1. Deleted files — must NOT exist at old root paths
// ---------------------------------------------------------------------------
describe("deleted root files — must not exist at old locations (§2, §3.1)", () => {
  it("vitest.config.ts does NOT exist at repo root", () => {
    expect(exists("vitest.config.ts")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 2. Moved files — must NOT exist at old root paths
// ---------------------------------------------------------------------------
describe("moved files — must not exist at old root locations (§2, §3.2–§3.4)", () => {
  it("tsconfig.app.json does NOT exist at repo root", () => {
    expect(exists("tsconfig.app.json")).toBe(false);
  });

  it("tsconfig.node.json does NOT exist at repo root", () => {
    expect(exists("tsconfig.node.json")).toBe(false);
  });

  it("playwright.config.ts does NOT exist at repo root", () => {
    expect(exists("playwright.config.ts")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 3. New file locations — must exist at new paths
// ---------------------------------------------------------------------------
describe("new file locations — must exist (§2, §3.2–§3.4)", () => {
  it(".config/ directory exists", () => {
    expect(exists(".config")).toBe(true);
  });

  it(".config/tsconfig.app.json exists", () => {
    expect(exists(".config/tsconfig.app.json")).toBe(true);
  });

  it(".config/tsconfig.node.json exists", () => {
    expect(exists(".config/tsconfig.node.json")).toBe(true);
  });

  it("tests/frontend_e2e/playwright.config.ts exists", () => {
    expect(exists("tests/frontend_e2e/playwright.config.ts")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 4. Protected root files — must NOT have been moved
// ---------------------------------------------------------------------------
describe("protected root files — must still exist at root (§4)", () => {
  it("package.json exists at root", () => {
    expect(exists("package.json")).toBe(true);
  });

  it("package-lock.json exists at root", () => {
    expect(exists("package-lock.json")).toBe(true);
  });

  it("tsconfig.json exists at root", () => {
    expect(exists("tsconfig.json")).toBe(true);
  });

  it("vite.config.ts exists at root", () => {
    expect(exists("vite.config.ts")).toBe(true);
  });

  it("index.html exists at root", () => {
    expect(exists("index.html")).toBe(true);
  });

  it("pyproject.toml exists at root", () => {
    expect(exists("pyproject.toml")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 5. vite.config.ts — merged test block (§3.1)
// ---------------------------------------------------------------------------
describe("vite.config.ts — merged vitest configuration (§3.1)", () => {
  it("vite.config.ts contains a 'test:' block (vitest config merged)", () => {
    const src = readFile("vite.config.ts");
    expect(src).toMatch(/\btest\s*:/);
  });

  it("vite.config.ts has vitest reference triple-slash OR imports from vitest/config", () => {
    const src = readFile("vite.config.ts");
    const hasTripleSlash = src.includes('/// <reference types="vitest');
    const hasVitestImport = src.includes('"vitest/config"') || src.includes("'vitest/config'");
    expect(
      hasTripleSlash || hasVitestImport,
      "vite.config.ts must have /// <reference types=\"vitest/config\" /> OR import from \"vitest/config\""
    ).toBe(true);
  });

  it("vite.config.ts test block has environment: jsdom", () => {
    const src = readFile("vite.config.ts");
    expect(src).toMatch(/environment\s*:\s*["']jsdom["']/);
  });

  it("vite.config.ts test block has globals: true", () => {
    const src = readFile("vite.config.ts");
    expect(src).toMatch(/globals\s*:\s*true/);
  });

  it("vite.config.ts test block includes tests/**/*.test.tsx pattern", () => {
    const src = readFile("vite.config.ts");
    expect(src).toMatch(/tests\/\*\*\/\*\.test\.tsx/);
  });

  it("vite.config.ts test block includes tests/**/*.test.ts pattern", () => {
    const src = readFile("vite.config.ts");
    expect(src).toMatch(/tests\/\*\*\/\*\.test\.ts/);
  });

  it("vite.config.ts test block references tests/setup.ts setupFile", () => {
    const src = readFile("vite.config.ts");
    expect(src).toMatch(/setup.*\.ts/);
  });
});

// ---------------------------------------------------------------------------
// 6. .config/tsconfig.app.json — path updates (§3.2)
// ---------------------------------------------------------------------------
describe(".config/tsconfig.app.json — internal paths updated (§3.2)", () => {
  it("extends ../tsconfig.json (not ./tsconfig.json)", () => {
    const json = readJson(".config/tsconfig.app.json");
    expect(json.extends).toBe("../tsconfig.json");
  });

  it("does NOT extend ./tsconfig.json (old root-relative path)", () => {
    const json = readJson(".config/tsconfig.app.json");
    expect(json.extends).not.toBe("./tsconfig.json");
  });

  it("has include array with '../src' (not bare 'src' — resolves relative to .config/)", () => {
    // tsconfig include resolves relative to the tsconfig file. After moving to .config/,
    // bare "src" → .config/src (nonexistent) → tsc errors "No inputs found" → build breaks.
    // Correct value is "../src" (climbs from .config/ to repo root, then into src/).
    const json = readJson(".config/tsconfig.app.json");
    expect(json.include).toContain("../src");
    expect(json.include).not.toContain("src");
  });
});

// ---------------------------------------------------------------------------
// 7. .config/tsconfig.node.json — path updates (§3.3)
// ---------------------------------------------------------------------------
describe(".config/tsconfig.node.json — internal paths updated (§3.3)", () => {
  it("include contains ../vite.config.ts (not vite.config.ts)", () => {
    const json = readJson(".config/tsconfig.node.json");
    const include = json.include as string[];
    expect(include).toContain("../vite.config.ts");
  });

  it("does NOT include bare vite.config.ts (old root-relative path)", () => {
    const json = readJson(".config/tsconfig.node.json");
    const include = json.include as string[];
    expect(include).not.toContain("vite.config.ts");
  });

  it("has composite: true (project reference support)", () => {
    const json = readJson(".config/tsconfig.node.json");
    const compilerOptions = json.compilerOptions as Record<string, unknown>;
    expect(compilerOptions?.composite).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 8. tests/frontend_e2e/playwright.config.ts — path updates (§3.4)
// ---------------------------------------------------------------------------
describe("tests/frontend_e2e/playwright.config.ts — internal paths updated (§3.4)", () => {
  it("testDir is '.' or './' (config is now co-located with tests)", () => {
    const src = readFile("tests/frontend_e2e/playwright.config.ts");
    // Matches: testDir: '.'  or  testDir: "./"  or  testDir: './'
    // Pattern: key, colon, whitespace, opening-quote, dot, optional-slash, closing-quote
    expect(src).toMatch(/testDir\s*:\s*['"]\.\/?\s*['"]/);
  });

  it("does NOT have testDir: './tests/frontend_e2e' (old root-relative path)", () => {
    const src = readFile("tests/frontend_e2e/playwright.config.ts");
    expect(src).not.toMatch(/testDir\s*:\s*['"]\.\/tests\/frontend_e2e['"]/);
  });

  it("still references the ENERGY_GO_FRONTEND_PORT env var", () => {
    const src = readFile("tests/frontend_e2e/playwright.config.ts");
    expect(src).toContain("ENERGY_GO_FRONTEND_PORT");
  });

  it("still has webServer block with npm run dev", () => {
    const src = readFile("tests/frontend_e2e/playwright.config.ts");
    expect(src).toContain("npm run dev");
  });

  it("webServer sets an explicit cwd climbing to repo root (§3.4)", () => {
    // Playwright webServer.cwd defaults to the config file's directory (tests/frontend_e2e/),
    // NOT the process CWD. Without an explicit cwd, `npm run dev` fails to find root
    // vite.config.ts/index.html after the move. cwd must point two levels up to repo root.
    // ESM-safe: "type": "module" means Playwright loads the config in ESM mode;
    // the CJS global for current directory is not available. Vitest polyfills it for
    // test files, hiding the runtime failure — so we explicitly forbid it here and
    // require the fileURLToPath(import.meta.url) pattern instead.
    const src = readFile("tests/frontend_e2e/playwright.config.ts");
    expect(/cwd\s*:/.test(src)).toBe(true);                          // cwd must be set
    expect(src).toMatch(/fileURLToPath\s*\(\s*import\.meta\.url\s*\)/); // ESM-safe dir resolution
    expect(src).not.toMatch(/\b__dirname\b/);                        // forbid bare CJS global (crashes in ESM)
    expect(/['"]\.\.\/\.\.\/?['"]/.test(src)).toBe(true);            // climbs two levels to repo root
  });
});

// ---------------------------------------------------------------------------
// 9. package.json — script updates (§3.2, §3.4)
// ---------------------------------------------------------------------------
describe("package.json — npm scripts updated (§3.2, §3.4)", () => {
  it("build script references .config/tsconfig.app.json", () => {
    const pkg = readJson("package.json");
    const scripts = pkg.scripts as Record<string, string>;
    expect(scripts.build).toContain(".config/tsconfig.app.json");
  });

  it("build script does NOT reference bare tsconfig.app.json", () => {
    const pkg = readJson("package.json");
    const scripts = pkg.scripts as Record<string, string>;
    // should not have `tsc -p tsconfig.app.json` (without .config/ prefix)
    expect(scripts.build).not.toMatch(/tsc\s+-p\s+tsconfig\.app\.json\b/);
  });

  it("test:e2e script has --config flag", () => {
    const pkg = readJson("package.json");
    const scripts = pkg.scripts as Record<string, string>;
    expect(scripts["test:e2e"]).toContain("--config");
  });

  it("test:e2e script references tests/frontend_e2e/playwright.config.ts", () => {
    const pkg = readJson("package.json");
    const scripts = pkg.scripts as Record<string, string>;
    expect(scripts["test:e2e"]).toContain("tests/frontend_e2e/playwright.config.ts");
  });

  it("test script unchanged — still 'vitest run'", () => {
    const pkg = readJson("package.json");
    const scripts = pkg.scripts as Record<string, string>;
    expect(scripts.test).toBe("vitest run");
  });

  it("dev script unchanged — still 'vite'", () => {
    const pkg = readJson("package.json");
    const scripts = pkg.scripts as Record<string, string>;
    expect(scripts.dev).toBe("vite");
  });
});

// ---------------------------------------------------------------------------
// 10. CI workflow — no hardcoded paths to moved files (§6)
// ---------------------------------------------------------------------------
describe("CI workflow — no hardcoded references to moved file paths (§6)", () => {
  const CI_FILE = ".github/workflows/ci.yml";

  it("ci.yml does not hardcode tsconfig.app.json", () => {
    const src = readFile(CI_FILE);
    expect(src).not.toContain("tsconfig.app.json");
  });

  it("ci.yml does not hardcode tsconfig.node.json", () => {
    const src = readFile(CI_FILE);
    expect(src).not.toContain("tsconfig.node.json");
  });

  it("ci.yml does not hardcode vitest.config.ts", () => {
    const src = readFile(CI_FILE);
    expect(src).not.toContain("vitest.config.ts");
  });

  it("ci.yml does not hardcode playwright.config.ts", () => {
    const src = readFile(CI_FILE);
    // playwright.config.ts was never in the CI workflow — this test confirms
    // neither old nor new paths appear (CI uses npm scripts only)
    expect(src).not.toContain("playwright.config.ts");
  });
});

// ---------------------------------------------------------------------------
// 11. STACK.md — tooling notes updated (§5)
// ---------------------------------------------------------------------------
describe("STACK.md — build tooling notes reflect new structure (§5)", () => {
  it("STACK.md mentions .config/ for tsconfigs", () => {
    const src = readFile("STACK.md");
    expect(src).toMatch(/\.config\//);
  });

  it("STACK.md notes vitest config is in vite.config.ts (merged)", () => {
    const src = readFile("STACK.md");
    // Should mention merged or combined vitest/vite config
    const hasMerged = src.includes("vite.config.ts") &&
      (src.includes("merged") || src.includes("test:") || src.includes("vitest"));
    expect(hasMerged).toBe(true);
  });
});

// ===========================================================================
// reviewer: added cases — frontend-reviewer (PR #99 contract+tests gate)
// ===========================================================================

// reviewer: MUST-FIX #1. The contract §3.2 and the developer test (suite 6, "has
// include array with 'src'") both miss that tsconfig `include` paths resolve
// RELATIVE TO THE TSCONFIG FILE. After moving to .config/, `include: ["src"]`
// resolves to `.config/src` (nonexistent) -> `tsc -p .config/tsconfig.app.json`
// errors "No inputs were found" -> `npm run build` BREAKS in CI (the PR #62/#70
// guard). The correct value is `["../src"]`. These tests resolve each include
// entry relative to .config/ and require it to point at a real directory — which
// a bare toContain("src") assertion (suite 6) would wave straight through while
// actually enforcing the broken value.
describe("reviewer: .config/tsconfig.app.json include resolves to a real source tree", () => {
  it("reviewer: every include entry resolves (relative to .config/) to an existing path", () => {
    const json = readJson(".config/tsconfig.app.json") as { include?: string[] };
    const include = json.include ?? [];
    expect(include.length).toBeGreaterThan(0);
    for (const entry of include) {
      const resolved = path.resolve(REPO_ROOT, ".config", entry);
      expect(
        fs.existsSync(resolved),
        'include entry "' + entry + '" resolves to ' + resolved +
        ' which does not exist - after the move it must be "../src" (relative to .config/), not "src"'
      ).toBe(true);
    }
  });

  it("reviewer: include contains ../src and NOT bare src (suite-6 assertion must be corrected to match)", () => {
    const json = readJson(".config/tsconfig.app.json") as { include?: string[] };
    expect(json.include).toContain("../src");
    expect(json.include).not.toContain("src");
  });
});

// reviewer: MUST-FIX #2. Playwright's webServer.cwd "defaults to the directory of
// the configuration file" (node_modules/playwright/types/test.d.ts) — NOT the
// process CWD, as the contract §3.4 claims. After moving the config to
// tests/frontend_e2e/, the default cwd becomes tests/frontend_e2e/, so
// `npm run dev` launches vite from there and fails to find vite.config.ts /
// index.html (both root-mandated) -> the e2e dev server is misconfigured. CI does
// NOT run test:e2e, so this would merge green and break e2e silently. The moved
// config MUST set webServer.cwd back to the repo root.
describe("reviewer: playwright webServer runs from repo root after the move", () => {
  it("reviewer: webServer sets an explicit cwd (Playwright default is the config dir, not repo root)", () => {
    const src = readFile("tests/frontend_e2e/playwright.config.ts");
    expect(
      /cwd\s*:/.test(src),
      "webServer must set an explicit cwd: Playwright defaults it to the config dir (tests/frontend_e2e/), which cannot run `npm run dev` correctly"
    ).toBe(true);
  });

  it("reviewer: webServer.cwd climbs two levels back to repo root", () => {
    // WHY the CJS global is forbidden: "type": "module" means Playwright loads
    // playwright.config.ts in ESM mode; the CJS directory global is NOT defined
    // there. Vitest polyfills it for test files, hiding this failure from structural
    // tests that only read the source as text. This test catches the gap: it asserts
    // the ESM-safe fileURLToPath(import.meta.url) pattern is used and the CJS global
    // does not appear anywhere in the file (not even in comments or variable names).
    const src = readFile("tests/frontend_e2e/playwright.config.ts");
    expect(/cwd\s*:/.test(src)).toBe(true);                          // cwd is set
    expect(src).toMatch(/fileURLToPath\s*\(\s*import\.meta\.url\s*\)/); // ESM-safe dir resolution
    expect(src).not.toMatch(/\b__dirname\b/);                        // forbid bare CJS global (crashes in ESM)
    expect(/['"]\.\.\/\.\.\/?['"]/.test(src)).toBe(true);            // climbs two levels to repo root
  });
});
