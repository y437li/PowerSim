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
