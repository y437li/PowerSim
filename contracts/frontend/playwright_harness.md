# Contract: Playwright Browser Test Harness

- **Status:** DRAFT — contract + tests gate
- **Area:** frontend (tooling)
- **Owner:** qa-engineer
- **Reviewer:** frontend-reviewer
- **Branch:** `feat/frontend-playwright-harness`
- **Tests:** `tests/frontend_e2e/smoke.spec.ts` (area pending rl-architect DECISION; D15-style)
- **Task:** #29 (user-requested 2026-06-10)
- **Spec ref:** REBUILD_SPEC §6 (frontend build order), CLAUDE.md (tests tree rule, D15, D16)

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
  to `playwright-report/error-report.ndjson` (one JSON line per test, appended).
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

Six tests. All import the `errorCapture` fixture so the error report is always populated.
The dev server is started by the `webServer` config block; no manual server setup.

### Test S1 — App boots (HTTP 200 + title)

```ts
test('S1: app boots with HTTP 200', async ({ page, errorCapture }) => {
  const response = await page.goto('/');
  // HTTP status from the dev server:
  expect(response?.status()).toBe(200);
  // Page title matches the app name:
  await expect(page).toHaveTitle(/Energy GO/i);
  // Zero console errors on initial load:
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
  expect(errorCapture.consoleErrors).toHaveLength(0);
  expect(errorCapture.pageErrors).toHaveLength(0);
});
```

### Test S3 — TrainingPanel route renders

```ts
test('S3: /training (TrainingPanel) renders without errors', async ({ page, errorCapture }) => {
  await page.goto('/training');
  await expect(page.locator('body')).not.toBeEmpty();
  expect(errorCapture.consoleErrors).toHaveLength(0);
  expect(errorCapture.pageErrors).toHaveLength(0);
});
```

### Test S4 — EvalComparison route renders

```ts
test('S4: /eval (EvalComparison) renders without errors', async ({ page, errorCapture }) => {
  await page.goto('/eval');
  await expect(page.locator('body')).not.toBeEmpty();
  expect(errorCapture.consoleErrors).toHaveLength(0);
  expect(errorCapture.pageErrors).toHaveLength(0);
});
```

### Test S5 — WebSocket graceful degradation (no backend)

The dev server starts without a FastAPI backend. The WS client (`src/clients/wsClient.ts`)
MUST NOT cause a fatal page error when the connection is refused or immediately closed.

```ts
test('S5: WS client degrades gracefully with no backend', async ({ page, errorCapture }) => {
  await page.goto('/');
  // Wait enough time for a WS connection attempt + failure to complete:
  await page.waitForTimeout(2000);
  // The page must remain functional — no unhandled exceptions:
  expect(errorCapture.pageErrors).toHaveLength(0);
  // WS errors may appear as console.error (acceptable) but MUST NOT be pageErrors:
  // (console.error from WS is informational; pageerror is a fatal crash)
});
```

Note: this test deliberately allows `consoleErrors` to be non-empty (the WS client may log
a connection-refused error). The binding contract is `pageErrors.length === 0` — the page
must not crash.

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
  with the dev server started. Attach the `playwright-report/error-report.ndjson`
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
