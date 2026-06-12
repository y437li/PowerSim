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

  it("has include array with 'src'", () => {
    const json = readJson(".config/tsconfig.app.json");
    expect(json.include).toContain("src");
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
  it("testDir is '.' (config is now co-located with tests)", () => {
    const src = readFile("tests/frontend_e2e/playwright.config.ts");
    // testDir: '.' or testDir: "./"
    expect(src).toMatch(/testDir\s*:\s*['"]\.[\/'"]?['"]/);
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
