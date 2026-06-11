# Review Record: Playwright Browser Test Harness (contract + tests gate)

- **PR:** #25 (`feat/frontend-playwright-harness`) · **Reviewer:** frontend-reviewer
- **Date:** 2026-06-10 · **Stage:** 1 (contract + tests)
- **Verdict:** REQUEST_CHANGES

## Findings (blockers first)
1. **[blocker] S5 is vacuous** — app shell (PR #5) never calls `wsClient.connect()` (no `createWsClient`/`connect` in App/main/SiteView), so S5 triggers no WS attempt and trivially passes without exercising degradation. Fix: have the app auto-connect the WS on mount (then S5 is real), OR make S5 drive an explicit connection.
2. **[blocker] S2/S3/S4 `consoleErrors===0` vs S5 tolerance are inconsistent under (1)** — once the app auto-connects, a backend-less dev server makes the browser log a `WebSocket connection … failed` console error on every route; S2–S4 must apply the same ws-failure allowlist S5 uses, or they'll fail on their happy path.
3. [should] S2–S4 absolute `consoleErrors.length===0` is brittle to framework/source-map console noise — assert "no app-origin console.error" / allowlist rather than zero.
4. [should] Smoke spec `tests/frontend_e2e/smoke.spec.ts` not committed (area pending rl-architect D15 DECISION) — approved-now suite = the 7 config-shape Vitest tests + my 2; the §3 smoke spec must return for reviewer cases when written.

## Answers to author questions
- Q1 (ErrorReport split): sufficient for QA visibility — console.error/warn + pageerror + failed requests cover it.
- Q2 (S5 boundary `pageErrors===0`, consoleErrors tolerant): correct boundary — *conditional on S5 actually connecting* (finding 1).

## Reviewer-added tests (`// reviewer:`)
1. `use.trace === 'retain-on-failure'` (QA evidence artifact, §7)
2. `testMatch === '**/*.spec.ts'` (no collision with Vitest `*.test.ts`)

Approved suite = author's 7 config-shape tests + these 2. Re-request when findings 1–2 land; smoke spec returns post-DECISION.

---

## Re-review (stage 1b) — 2026-06-10 — VERDICT: APPROVE (gate); functional acceptance deferred

Re-review of 06a5b92. Both blockers resolved:
1. S5 no longer vacuous — opens a real `new WebSocket(...)` via `page.evaluate()`, awaits error/close, asserts `pageErrors===0` (native connection-refused path).
2. S2–S4 `consoleErrors===0` consistent — app shell doesn't auto-connect, so route loads see no WS activity; S5 drives its own isolated connection. Design note (smoke header) documents it; answers should-fix 3.
- e2e area is sanctioned (D20 / PR #26) — team-lead correction noted; `smoke.spec.ts` has its home.
- +1 reviewer smoke case (S6r: unknown route → 404 fallback, `pageErrors===0`).

**Sole-gate note (QA-tooling, my APPROVE = acceptance):** functional evidence cannot run at this gate — no harness impl yet (`playwright.config.ts`/`errorCapture.ts` RED) and the app shell (PR #5) is unmerged, so nothing is servable. Final acceptance is conditional on, at the implementation commit (which also comes to me): `npm ci` + `npx playwright install chromium` succeed; `npm run test:e2e` runs S1–S5+S6r green vs the live dev server; an injected `console.error` surfaces in `error-report.ndjson` and fails S2/S3/S4; a fatal `throw` populates `pageErrors`; `playwright-report/` has results.json + HTML + on-failure screenshot.

Verdict: APPROVE the contract+tests gate; I run the functional acceptance at implementation.

---

## Stage-2 implementation audit — PR #25 @ `0ddcd13` (marked ready)

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11
- **Verdict:** **APPROVE** — honours the stage-1b acceptance conditions above.

### Audited against the contract (no findings)
- **`playwright.config.ts` (§1):** `testDir: './tests/frontend_e2e'`, `testMatch: '**/*.spec.ts'`
  (D20), `baseURL: 'http://localhost:5173'`, html + json reporters, `webServer.command: 'npm run
  dev'` — matches §1 acceptance bullets exactly.
- **`errorCapture.ts` (§2):** `ErrorReport` shape (consoleErrors / consoleWarnings / pageErrors /
  failedRequests) and all four listeners match §2 verbatim — `console` (error→errors,
  warning→warnings, others dropped), `pageerror`→`.message`, `response` status≥400→failedRequests,
  `requestfailed`→`{url,method,status:0}`. Fixture `base.extend<{errorCapture: ErrorReport}>`;
  teardown appends one JSON line per test to `playwright-report/error-report.ndjson`; report
  yielded to the test body for inline assertions. Listeners attach in fixture setup → active
  before the test's first `goto` (initial-load console errors are captured).
- **`smoke.spec.ts` (§3):** S1 (200 + `/Energy GO/i` title + consoleErrors 0 + pageErrors 0),
  S2–S4 (route renders + consoleErrors 0 + pageErrors 0), S5 (explicit WS drive to absent backend
  via `page.evaluate`, asserts pageErrors 0; consoleErrors deliberately not asserted — documented)
  match §3. S6r (my gate reviewer case — 404 fallback, 200 SPA, "not found" visible, pageErrors 0)
  present. All import `{ test, expect }` from the errorCapture fixture.
- **Wiring:** `test:e2e: "playwright test"` + `test:e2e:report`; `@playwright/test ^1.46.0`
  (devDep); **STACK.md** row present (D16) — `^1.46.0`, chromium via `npx playwright install`,
  config + `tests/frontend_e2e/*.spec.ts` location (D20).
- **`qa-verification/SKILL.md`:** additive note on running `npm run test:e2e` and attaching
  `error-report.ndjson` as QA evidence — coordinated with QA, consistent with the harness purpose.
- **QA evidence:** QA_PASS @ 0ddcd13 — Vitest 9/9 (config-shape) + smoke 6/6 with the NDJSON
  report attached.

### Non-blocking observation + recommended follow-up amendment
- **`error-report.ndjson` lives in `playwright-report/`, which the HTML reporter clears at run
  start** (QA flagged). The implementation is **correct per contract §2** (which names that path),
  and within a run the NDJSON is written in fixture teardown *after* the reporter's start-of-run
  clean, so the current run's report is intact (QA confirmed). The only loss is the *previous*
  run's file. **Recommend a follow-up contract amendment (§2):** write the NDJSON to a directory
  the HTML reporter does not manage (e.g. `test-results/error-report.ndjson` or repo root) so it
  persists across runs and can never be race-clobbered by the reporter. Not gating — the contract
  currently specifies `playwright-report/`, and the harness works as specified for single-run QA.

**Verdict: APPROVE** (stage-2). Mergeable on this APPROVE + the existing QA_PASS.
