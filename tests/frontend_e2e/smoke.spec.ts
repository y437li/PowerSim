/**
 * Smoke suite — Playwright E2E browser tests
 * Area: tests/frontend_e2e/ (created by rl-architect DECISION D20, task #29)
 * Contract: contracts/frontend/playwright_harness.md §3
 *
 * All tests import { test, expect } from the errorCapture fixture so console errors,
 * page errors, and failed network requests are automatically captured and written to
 * playwright-report/error-report.ndjson after each test.
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

  // Zero console.error calls on initial load — the app must boot cleanly
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

  // No console.error on the SiteView route
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

  // No console.error on the training route
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

  // No console.error on the eval route
  expect(errorCapture.consoleErrors).toHaveLength(0);

  // No unhandled JS exceptions
  expect(errorCapture.pageErrors).toHaveLength(0);
});

// ---------------------------------------------------------------------------
// S5 — WebSocket client degrades gracefully with no backend
// ---------------------------------------------------------------------------
test(
  "S5: WS client degrades gracefully with no backend",
  async ({ page, errorCapture }) => {
    await page.goto("/");

    // Wait long enough for a WebSocket connection attempt to fail and
    // for any async error handlers to fire (2 s is sufficient for a
    // refused-connection timeout cycle at localhost).
    await page.waitForTimeout(2000);

    // BINDING CONTRACT (from playwright_harness.md §3/S5):
    // The WS client MAY log a console.error (connection refused is informational).
    // The WS client MUST NOT cause an unhandled JS exception (pageerror).
    // A pageerror means the app crashed — that is a hard failure.
    expect(errorCapture.pageErrors).toHaveLength(0);

    // Verify the page is still interactive — a basic DOM query must succeed
    await expect(page.locator("body")).not.toBeEmpty();
  }
);
