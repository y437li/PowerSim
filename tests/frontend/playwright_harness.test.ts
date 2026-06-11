/**
 * Config-shape tests for playwright.config.ts
 * Runs with Vitest (no browser required — verifies the config object matches the contract).
 * Contract: contracts/frontend/playwright_harness.md §4
 *
 * These tests run as part of `npm test` and give fast CI feedback on config drift
 * without launching a real browser.
 */

import { describe, it, expect } from "vitest";

// Dynamic import so this file doesn't hard-fail if playwright.config.ts doesn't
// exist yet (the file is red until implementation — correct per contract-first-dev).
async function loadConfig() {
  const mod = await import("../../playwright.config");
  return mod.default;
}

describe("playwright.config.ts shape (contract: playwright_harness.md §4)", () => {
  it("testDir is ./tests/frontend_e2e", async () => {
    const config = await loadConfig();
    // Contract invariant: testDir must point at the E2E area, not the unit-test tree
    expect(config.testDir).toBe("./tests/frontend_e2e");
  });

  it("projects contains exactly one entry with name 'chromium'", async () => {
    const config = await loadConfig();
    // Contract: chromium only for v1 (Firefox/WebKit out of scope)
    expect(config.projects).toHaveLength(1);
    expect(config.projects![0].name).toBe("chromium");
  });

  it("screenshot is 'only-on-failure'", async () => {
    const config = await loadConfig();
    // Contract: screenshots must be captured on failure so QA can attach them to verdict
    expect(config.use?.screenshot).toBe("only-on-failure");
  });

  it("baseURL is http://localhost:5173 (default Vite dev port)", async () => {
    const config = await loadConfig();
    expect(config.use?.baseURL).toBe("http://localhost:5173");
  });

  it("reporter includes both 'html' and 'json' entries", async () => {
    const config = await loadConfig();
    const reporters = config.reporter as Array<[string, ...unknown[]]>;
    const names = reporters.map(([name]) => name);
    // Contract: both HTML (human browsable) and JSON (machine parseable for QA verdict)
    expect(names).toContain("html");
    expect(names).toContain("json");
  });

  it("webServer.command is 'npm run dev'", async () => {
    const config = await loadConfig();
    const ws = config.webServer as { command: string };
    // Contract: auto-starts the Vite dev server before the suite
    expect(ws.command).toBe("npm run dev");
  });

  it("json reporter writes to playwright-report/results.json", async () => {
    const config = await loadConfig();
    const reporters = config.reporter as Array<[string, Record<string, unknown>]>;
    const jsonEntry = reporters.find(([name]) => name === "json");
    // Contract: machine-readable output path for QA automation
    expect(jsonEntry?.[1]?.outputFile).toBe("playwright-report/results.json");
  });

  // reviewer: trace must be retained on failure — QA needs the trace to diagnose a
  // failed route load (it's named as a QA evidence artifact in §7).
  it("use.trace is 'retain-on-failure'", async () => {
    const config = await loadConfig();
    expect(config.use?.trace).toBe("retain-on-failure");
  });

  // reviewer: testMatch must scope to *.spec.ts so the Vitest config-shape file
  // (tests/frontend/*.test.ts) is never picked up by the Playwright runner.
  it("testMatch is '**/*.spec.ts' (does not collide with Vitest *.test.ts)", async () => {
    const config = await loadConfig();
    expect(config.testMatch).toBe("**/*.spec.ts");
  });
});
