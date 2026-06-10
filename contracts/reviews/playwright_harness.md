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
