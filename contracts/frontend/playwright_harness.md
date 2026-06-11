# Contract: Playwright Browser Test Harness

- **Status:** AMENDED — task #16 amendment gate (fix/frontend-error-report-location)
- **Area:** frontend (tooling)
- **Owner:** qa-engineer
- **Reviewer:** frontend-reviewer
- **Branch:** `feat/frontend-playwright-harness`
- **Tests:** `tests/frontend_e2e/smoke.spec.ts` (area pending rl-architect DECISION; D15-style)
- **Task:** #29 (user-requested 2026-06-10)
- **Spec ref:** REBUILD_SPEC §6 (frontend build order), CLAUDE.md (tests tree rule, D15, D16)

## Task #16 Amendment — error-report.ndjson path relocation

**Problem:** `playwright-report/` is cleared by Playwright's HTML reporter at the start of
every run. Any file written there is wiped before tests run, losing prior error reports.

**Fix:** move `error-report.ndjson` to `test-results/` (Playwright's artifact directory,
not managed by any reporter plugin).

### Amendment deliverables (implementation scope for PR #58)

1. `tests/frontend_e2e/helpers/reportPaths.ts` — change stub constant from
   `"playwright-report/error-report.ndjson"` → `"test-results/error-report.ndjson"`
2. `tests/frontend_e2e/helpers/errorCapture.ts` — import `ERROR_REPORT_PATH` from
   `reportPaths.ts` (single source of truth) instead of hardcoding the path
3. `.claude/skills/qa-verification/SKILL.md` — line ~42: update the browser-run step's
   attachment path from `playwright-report/error-report.ndjson` → `test-results/error-report.ndjson`
   so QA instructions stay consistent with the actual output location
4. `tests/frontend_e2e/smoke.spec.ts` — update header comment path reference (cosmetic)

### Amendment gate test (task #16)

`tests/frontend/playwright_harness.test.ts` includes one new test:
- Imports `ERROR_REPORT_PATH` from `tests/frontend_e2e/helpers/reportPaths.ts`
- Asserts `ERROR_REPORT_PATH === "test-results/error-report.ndjson"`
- RED at gate stage (stub exports the old path); GREEN after implementation

---

## Purpose

Add a Playwright browser test harness so QA can run tests in a real Chromium browser and
capture the error messages. Error visibility (console errors, page crashes, failed network
requests) is a **first-class artifact** that every QA verdict on a frontend deliverable must
quote verbatim. This harness is the prerequisite for task #10's frontend QA and the
app-shell implementation audit (PR #5).

## Deliverables (all in this PR)

1. `playwright.config.ts` — Playwright configuration at the repo root
2. `tests/frontend_e2e/smoke.spec.ts` — smoke suite (see §3)
3. `tests/frontend_e2e/helpers/errorCapture.ts` — per-test error-capture fixture
4. `package.json` update — add `@playwright/test`, add `"test:e2e"` script
5. `STACK.md` update — Playwright as the frontend E2E/browser layer (D16 rule)
6. `.claude/skills/qa-verification/SKILL.md` update — browser-run step for frontend QA
7. `tests/frontend_e2e/.gitkeep` — area scaffold (pending the DECISION from rl-architect;
   the `.gitkeep` is replaced by the spec file once the DECISION lands)

## 1. Playwright configuration (`playwright.config.ts`)

```ts
// playwright.config.ts — root of repo (same level as package.json)
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/frontend_e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,          // smoke suite is small; sequential is fine
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['html', { open: 'never' }],
    ['json', { outputFile: 'playwright-report/results.json' }],
  ],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
```

### Config invariants (asserted by the config-shape test):
- `testDir` is `./tests/frontend_e2e`
- `projects` contains exactly one entry with `name === 'chromium'`
- `use.screenshot` is `'only-on-failure'`
- `use.baseURL` is `'http://localhost:5173'`
- `reporter` includes both `'html'` and `'json'` entries
- `webServer.command` is `'npm run dev'`

## 2. Error-capture fixture (`tests/frontend_e2e/helpers/errorCapture.ts`)

The fixture wraps every test with listeners that collect errors into a structured report.
QA quotes the report verbatim in verdict comments.

### Fixture interface

```ts
export type ConsoleEntry = {
  type: 'error' | 'warning';
  text: string;
  location: string;           // "url:line:col" or empty string
};

export type FailedRequest = {
  url: string;
  method: string;
  status: number;             // HTTP status code; 0 for network-level failure
};

export type ErrorReport = {
  testTitle: string;
  consoleErrors: ConsoleEntry[];    // console.error() calls only
  consoleWarnings: ConsoleEntry[];  // console.warn() calls only
  pageErrors: string[];             // pageerror events (unhandled JS exceptions)
  failedRequests: FailedRequest[];  // HTTP 4xx, 5xx, or network failure
};
```

### Fixture behaviour (binding):
- Attaches listeners to `page.on('console', ...)`, `page.on('pageerror', ...)`,
  `page.on('requestfailed', ...)`, `page.on('response', ...)` **before** any page
  navigation in the test.
- `console` listener: records entries with `type === 'error'` into `consoleErrors`;
  entries with `type === 'warning'` into `consoleWarnings`; all other types ignored.
- `pageerror` listener: records the error's `.message` string into `pageErrors`.
- `response` listener: records responses with `status >= 400` into `failedRequests`.
- `requestfailed` listener: records `{ url, method, status: 0 }` into `failedRequests`.
- After the test body (in fixture teardown), writes the `ErrorReport` as a JSON object
  to `test-results/error-report.ndjson` (one JSON line per test, appended).
  **Amendment (task #16):** moved out of `playwright-report/` because Playwright's HTML
  reporter clears that directory at the start of each run, which would wipe the file before
  any test writes to it. `test-results/` is the conventional Playwright artifact directory
  and is not cleared by the HTML reporter plugin.
- The `ErrorReport` is also returned to the test body so assertions can reference it
  inline: `const { errors } = await useErrorCapture(page)`.

### `errorCapture` test fixture export:

```ts
// extends Playwright's base `test` with an `errorCapture` fixture
export const test = base.extend<{ errorCapture: ErrorReport }>({
  errorCapture: async ({ page }, use) => {
    // ... attach listeners, run test, detach, write report, yield report
  },
});
export { expect } from '@playwright/test';
```

All smoke tests import `{ test, expect }` from `./helpers/errorCapture` instead of
`@playwright/test` directly, so error capture is active in every test.

## 3. Smoke suite (`tests/frontend_e2e/smoke.spec.ts`)

Five tests (S1–S5). All import the `errorCapture` fixture so the error report is always
populated. The dev server is started by the `webServer` config block; no manual server setup.

### Design note — app-shell WS auto-connect

`src/clients/wsClient.ts` (PR #5) exposes `createWsClient()` and a `.connect()` method, but
the app shell does **not** call `.connect()` on mount (no `createWsClient`/`connect` in
`App.tsx`, `main.tsx`, or `SiteView.tsx`). This has two consequences for the smoke suite:

- **S2–S4 `consoleErrors === 0` is a correct, non-brittle assertion** — because the page
  makes no WS attempt, the browser generates no native "WebSocket connection failed"
  `console.error` on those routes. Framework noise (Vite HMR, React DevTools) does not
  generate `console.error` on an idle route load in a standard dev build.
- **S5 must explicitly drive a WS connection** so it actually exercises the browser's
  behaviour under a refused connection, rather than trivially passing with no WS activity.
  S5 uses `page.evaluate()` to open a raw WebSocket to the absent backend endpoint
  (`ws://localhost:8000/ws/telemetry`), waits for close/error, then asserts no pageerror.

### Test S1 — App boots (HTTP 200 + title)

```ts
test('S1: app boots with HTTP 200', async ({ page, errorCapture }) => {
  const response = await page.goto('/');
  // HTTP status from the dev server:
  expect(response?.status()).toBe(200);
  // Page title matches the app name:
  await expect(page).toHaveTitle(/Energy GO/i);
  // Zero console errors on initial load (no WS attempt on mount — see design note):
  expect(errorCapture.consoleErrors).toHaveLength(0);
  // Zero page errors:
  expect(errorCapture.pageErrors).toHaveLength(0);
});
```

### Test S2 — SiteView route renders

```ts
test('S2: / (SiteView) renders without errors', async ({ page, errorCapture }) => {
  await page.goto('/');
  // The root route renders some visible content — the SiteView mounts:
  await expect(page.locator('body')).not.toBeEmpty();
  // No WS attempt on mount → no WS-originated console.error (see design note):
  expect(errorCapture.consoleErrors).toHaveLength(0);
  expect(errorCapture.pageErrors).toHaveLength(0);
});
```

### Test S3 — TrainingPanel route renders

```ts
test('S3: /training (TrainingPanel) renders without errors', async ({ page, errorCapture }) => {
  await page.goto('/training');
  await expect(page.locator('body')).not.toBeEmpty();
  // No WS attempt on mount → no WS-originated console.error (see design note):
  expect(errorCapture.consoleErrors).toHaveLength(0);
  expect(errorCapture.pageErrors).toHaveLength(0);
});
```

### Test S4 — EvalComparison route renders

```ts
test('S4: /eval (EvalComparison) renders without errors', async ({ page, errorCapture }) => {
  await page.goto('/eval');
  await expect(page.locator('body')).not.toBeEmpty();
  // No WS attempt on mount → no WS-originated console.error (see design note):
  expect(errorCapture.consoleErrors).toHaveLength(0);
  expect(errorCapture.pageErrors).toHaveLength(0);
});
```

### Test S5 — WebSocket graceful degradation (no backend)

The dev server starts without a FastAPI backend. The test explicitly opens a raw WebSocket
to the absent backend (`ws://localhost:8000/ws/telemetry`) via `page.evaluate()`, waits for
the browser to close/error the connection, then asserts the page has not crashed. This drives
real browser WS error-handling behaviour (native "connection refused" path) without requiring
the app shell to auto-connect on mount.

```ts
test('S5: WS client degrades gracefully with no backend', async ({ page, errorCapture }) => {
  await page.goto('/');

  // Explicitly drive a WS connection to the absent backend so S5 is not vacuous.
  // The app shell does not auto-connect on mount (see design note above).
  // page.evaluate runs in the browser context — any unhandled exception here would
  // surface as a pageerror and fail the test.
  await page.evaluate(() =>
    new Promise<void>((resolve) => {
      const ws = new WebSocket('ws://localhost:8000/ws/telemetry');
      ws.addEventListener('error', () => { ws.close(); resolve(); });
      ws.addEventListener('close', () => resolve());
    })
  );

  // Allow a short window for async error handlers to fire:
  await page.waitForTimeout(500);

  // BINDING CONTRACT: a refused WS connection MUST NOT crash the page.
  // A browser-native "WebSocket connection failed" console.error is acceptable;
  // an unhandled JS exception (pageerror) means the page crashed — hard failure.
  expect(errorCapture.pageErrors).toHaveLength(0);

  // The page must remain interactive after the WS failure:
  await expect(page.locator('body')).not.toBeEmpty();
});
```

Note: `consoleErrors` is intentionally NOT asserted in S5 — the browser always emits a
native `console.error` when a WS connection is refused. The binding contract is
`pageErrors.length === 0`.

### Test S6 — Screenshot on failure (implicit)

No explicit test body required. The `use.screenshot: 'only-on-failure'` config captures a
PNG automatically when any test fails; the file appears in `playwright-report/` alongside
the HTML report. This is verified by the config-shape test (§4).

## 4. Configuration-shape test (non-browser, run with Vitest)

To verify the config contract without launching a browser, add one Vitest test:

```ts
// tests/frontend/playwright_harness.test.ts  (NOT .tsx — no React; no JSX)
// Verifies the shape of playwright.config.ts matches this contract's invariants.
import config from '../../playwright.config';

test('playwright config: testDir is tests/frontend_e2e', () => {
  expect(config.testDir).toBe('./tests/frontend_e2e');
});
test('playwright config: single chromium project', () => {
  expect(config.projects).toHaveLength(1);
  expect(config.projects![0].name).toBe('chromium');
});
test('playwright config: screenshot only-on-failure', () => {
  expect(config.use?.screenshot).toBe('only-on-failure');
});
test('playwright config: webServer uses npm run dev', () => {
  expect((config.webServer as any).command).toBe('npm run dev');
});
```

These run as part of `npm test` (Vitest) without a browser, providing fast CI feedback on
config drift.

## 5. `package.json` changes

Add to `devDependencies`:
```json
"@playwright/test": "^1.46.0"
```

Add to `scripts`:
```json
"test:e2e": "playwright test",
"test:e2e:report": "playwright show-report"
```

Note: `@playwright/test` includes the Playwright runner; Chromium browser binary is
downloaded separately via `npx playwright install chromium`. The install step is recorded
in `STACK.md` and must be run after `npm ci` in CI (see §6 STACK.md entry).

## 6. STACK.md entry

Add row to the STACK table (D16 rule — same PR as the stack-element introduction):

| Area | Chosen stack | Version notes | Set by |
|---|---|---|---|
| **Frontend E2E / browser tests** | **Playwright** (`@playwright/test`) + Chromium | `^1.46.0`; browser binary via `npx playwright install chromium`; config at `playwright.config.ts`; tests under `tests/frontend_e2e/*.spec.ts` | task #29 |

## 7. `qa-verification` skill update

Add the following step to the "For serving/frontend work" domain-checks section of
`.claude/skills/qa-verification/SKILL.md`:

```
- **Browser run (frontend deliverables):** run `npm run test:e2e` against the PR branch
  with the dev server started. Attach the `test-results/error-report.ndjson`
  content verbatim as evidence in the verdict comment. A QA_PASS requires:
  (a) all smoke tests pass, (b) zero `pageErrors` on any route load, and
  (c) the error report shows no unexpected console.error on initial route navigation.
  Attach the Playwright HTML report path and the full NDJSON report.
```

## Acceptance criteria

1. `npm run test:e2e` runs the smoke suite (S1–S5) against a live Vite dev server and
   all five tests pass.
2. Running with a deliberate console.error injected into any route (test helper)
   surfaces the error in `error-report.ndjson` and causes S2/S3/S4 to fail.
3. Running with a fatal `throw` in a React component populates `pageErrors` and causes
   the relevant smoke test to fail.
4. `npm test` (Vitest) includes the config-shape tests (§4) and they pass without
   launching a browser.
5. `playwright-report/` contains `results.json` + HTML report after every run; on any
   failure, a `<testname>-failed.png` screenshot is present.
   `test-results/error-report.ndjson` exists and is not wiped between runs (task #16 fix).
6. `STACK.md` has the Playwright row in the same commit.
7. `qa-verification` SKILL.md has the browser-run step in the same commit.
8. The `tests/frontend_e2e/` area exists on disk (`.gitkeep` or the first `.spec.ts`);
   the rl-architect DECISION naming this area is cited in the PR body.

## Out of scope

- CI integration (GitHub Actions step for E2E) — tracked separately.
- Firefox / WebKit / mobile viewports — Chromium only for v1.
- Visual regression / pixel diffing — not a QA requirement.
- Authenticated flows — app shell has no auth.
- Performance budgets / Lighthouse — out of scope for this harness.
- The §8 composable asset library routes (gas/electrolyzer panels) — not yet implemented;
  smoke suite tests only the routes currently in src/routes/.
