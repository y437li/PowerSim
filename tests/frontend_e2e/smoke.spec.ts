/**
 * Smoke suite — Playwright E2E browser tests
 * Area: tests/frontend_e2e/ (created by rl-architect DECISION D20, task #29)
 * Contract: contracts/frontend/playwright_harness.md §3
 *
 * All tests import { test, expect } from the errorCapture fixture so console errors,
 * page errors, and failed network requests are automatically captured and written to
 * test-results/error-report.ndjson after each test (not playwright-report/ — that dir is
 * cleared by Playwright's HTML reporter at run start; see task #16 / playwright_harness.md §2).
 *
 * Design note — WS auto-connect:
 * App.tsx calls telemetryWsClient.connect() + trainingWsClient.connect() on mount
 * (useEffect, added in task #27). With no backend running, the browser emits a native
 * "WebSocket connection to … failed" console.error per client — informational, not a crash.
 *  - S1–S4 filter that known WS-refused noise from consoleErrors and assert the remainder
 *    is 0. This catches real errors (e.g. a design_system token import regression that emits
 *    console.error without crashing) while tolerating expected WS connection noise.
 *    pageErrors === 0 (no unhandled JS exceptions) is the crash-safety invariant.
 *  - S5 explicitly drives a raw WS connection via page.evaluate(). Only pageErrors is
 *    asserted — consoleErrors intentionally not asserted (WS noise dominates; only crashes
 *    are fatal). S6r: same pageErrors-only pattern.
 *
 * Run: npm run test:e2e  (requires `npm run dev` or webServer config in playwright.config.ts)
 */

import { test, expect } from "./helpers/errorCapture";

// WS-refused console.error filter (shared by S1–S4).
// consoleErrors elements are ConsoleEntry objects { text, type, location }.
// The browser emits "WebSocket connection to 'ws://…' failed" per refused client;
// filter on .text so only that known noise is excluded.
const WS_REFUSED = /WebSocket connection to .* failed/i;

// ---------------------------------------------------------------------------
// S1 — App boots with HTTP 200 and the correct page title
// ---------------------------------------------------------------------------
test("S1: app boots with HTTP 200", async ({ page, errorCapture }) => {
  const response = await page.goto("/");

  // HTTP status from the Vite dev server must be 200
  expect(response?.status()).toBe(200);

  // Page title must contain "Energy GO" (case-insensitive)
  await expect(page).toHaveTitle(/Energy GO/i);

  // App auto-connects WS on mount (task #27); filter the known WS-refused noise and
  // assert NO OTHER console.error — catches real bugs (token import errors, etc.)
  // while tolerating expected connection-refused output. See file-level design note.
  const unexpected = errorCapture.consoleErrors.filter((e) => !WS_REFUSED.test(e.text));
  expect(unexpected, `unexpected console errors: ${JSON.stringify(unexpected)}`).toHaveLength(0);

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

  // App auto-connects WS on mount (task #27); filter the known WS-refused noise and
  // assert NO OTHER console.error — catches real bugs (token import errors, etc.)
  // while tolerating expected connection-refused output. See file-level design note.
  const unexpected = errorCapture.consoleErrors.filter((e) => !WS_REFUSED.test(e.text));
  expect(unexpected, `unexpected console errors: ${JSON.stringify(unexpected)}`).toHaveLength(0);

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

  // App auto-connects WS on mount (task #27); filter the known WS-refused noise and
  // assert NO OTHER console.error — catches real bugs (token import errors, etc.)
  // while tolerating expected connection-refused output. See file-level design note.
  const unexpected = errorCapture.consoleErrors.filter((e) => !WS_REFUSED.test(e.text));
  expect(unexpected, `unexpected console errors: ${JSON.stringify(unexpected)}`).toHaveLength(0);

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

  // App auto-connects WS on mount (task #27); filter the known WS-refused noise and
  // assert NO OTHER console.error — catches real bugs (token import errors, etc.)
  // while tolerating expected connection-refused output. See file-level design note.
  const unexpected = errorCapture.consoleErrors.filter((e) => !WS_REFUSED.test(e.text));
  expect(unexpected, `unexpected console errors: ${JSON.stringify(unexpected)}`).toHaveLength(0);

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

// reviewer (frontend-reviewer): a 404 route must render the app's fallback without a
// page crash, and the capture fixture must record zero pageErrors on it. Extends route
// coverage beyond S2–S4 (the happy routes) to the error-boundary/404 path.
test("S6r: unknown route renders 404 fallback without a page crash", async ({ page, errorCapture }) => {
  const response = await page.goto("/this-route-does-not-exist");
  // SPA serves index.html (200) and the router renders the 404 fallback — not a server 404.
  expect(response?.status()).toBe(200);
  await expect(page.locator("body")).not.toBeEmpty();
  // The app's own "Page not found" fallback (app_shell §2 routing) should be visible.
  await expect(page.getByText(/not found/i)).toBeVisible();
  // No unhandled exception on the fallback path.
  expect(errorCapture.pageErrors).toHaveLength(0);
});
