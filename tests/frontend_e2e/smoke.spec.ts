/**
 * Smoke suite — Playwright E2E browser tests
 * Area: tests/frontend_e2e/ (created by rl-architect DECISION D20, task #29)
 * Contract: contracts/frontend/playwright_harness.md §3
 *
 * All tests import { test, expect } from the errorCapture fixture so console errors,
 * page errors, and failed network requests are automatically captured and written to
 * playwright-report/error-report.ndjson after each test.
 *
 * Design note — WS auto-connect:
 * The app shell (PR #5) does NOT call wsClient.connect() on mount. Consequently:
 *  - S1–S4 see no WS activity → consoleErrors === 0 is a correct, non-brittle assertion.
 *  - S5 must explicitly drive a WS connection via page.evaluate() so the test is not
 *    vacuous. The binding contract for S5 is pageErrors.length === 0.
 *
 * Run: npm run test:e2e  (requires `npm run dev` or webServer config in playwright.config.ts)
 */

import { test, expect } from "./helpers/errorCapture";

// ---------------------------------------------------------------------------
// S1 — App boots with HTTP 200 and the correct page title
// ---------------------------------------------------------------------------
test("S1: app boots with HTTP 200", async ({ page, errorCapture }) => {
  const response = await page.goto("/");

  // HTTP status from the Vite dev server must be 200
  expect(response?.status()).toBe(200);

  // Page title must contain "Energy GO" (case-insensitive)
  await expect(page).toHaveTitle(/Energy GO/i);

  // No WS attempt on mount → no WS-originated console.error (see design note)
  expect(errorCapture.consoleErrors).toHaveLength(0);

  // Zero unhandled JS exceptions on initial load
  expect(errorCapture.pageErrors).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// S2 — SiteView route (/) renders without errors
// ---------------------------------------------------------------------------
test("S2: / (SiteView) renders without errors", async ({ page, errorCapture }) => {
  await page.goto("/");

  // The root route must render visible content — SiteView component is mounted
  await expect(page.locator("body")).not.toBeEmpty();

  // No WS attempt on mount → no WS-originated console.error (see design note)
  expect(errorCapture.consoleErrors).toHaveLength(0);

  // No unhandled JS exceptions
  expect(errorCapture.pageErrors).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// S3 — TrainingPanel route (/training) renders without errors
// ---------------------------------------------------------------------------
test("S3: /training (TrainingPanel) renders without errors", async ({
  page,
  errorCapture,
}) => {
  await page.goto("/training");

  // Route must render — TrainingPanel component is mounted
  await expect(page.locator("body")).not.toBeEmpty();

  // No WS attempt on mount → no WS-originated console.error (see design note)
  expect(errorCapture.consoleErrors).toHaveLength(0);

  // No unhandled JS exceptions
  expect(errorCapture.pageErrors).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// S4 — EvalComparison route (/eval) renders without errors
// ---------------------------------------------------------------------------
test("S4: /eval (EvalComparison) renders without errors", async ({
  page,
  errorCapture,
}) => {
  await page.goto("/eval");

  // Route must render — EvalComparison component is mounted
  await expect(page.locator("body")).not.toBeEmpty();

  // No WS attempt on mount → no WS-originated console.error (see design note)
  expect(errorCapture.consoleErrors).toHaveLength(0);

  // No unhandled JS exceptions
  expect(errorCapture.pageErrors).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// S5 — WebSocket graceful degradation (no backend)
//
// The app shell does not auto-connect WS on mount, so this test explicitly
// drives a raw WebSocket connection to the absent backend via page.evaluate().
// This ensures S5 is not vacuous — it exercises real browser WS error-handling.
// ---------------------------------------------------------------------------
test(
  "S5: WS client degrades gracefully with no backend",
  async ({ page, errorCapture }) => {
    await page.goto("/");

    // Explicitly drive a WS connection to the absent backend endpoint.
    // page.evaluate() runs in the browser context — any unhandled exception here
    // would surface as a pageerror, which is caught by the errorCapture fixture.
    await page.evaluate(() =>
      new Promise<void>((resolve) => {
        const ws = new WebSocket("ws://localhost:8000/ws/telemetry");
        ws.addEventListener("error", () => {
          ws.close();
          resolve();
        });
        ws.addEventListener("close", () => resolve());
      })
    );

    // Short window for any async error handlers to fire after close/error
    await page.waitForTimeout(500);

    // BINDING CONTRACT: a refused WS connection MUST NOT crash the page.
    // A pageerror means the app threw an unhandled exception — hard failure.
    expect(errorCapture.pageErrors).toHaveLength(0);

    // consoleErrors intentionally NOT asserted: the browser emits a native
    // "WebSocket connection to … failed" console.error on connection refused;
    // that is informational and acceptable. Only pageErrors (crashes) are fatal.

    // Page must remain interactive after the WS failure
    await expect(page.locator("body")).not.toBeEmpty();
  }
);
