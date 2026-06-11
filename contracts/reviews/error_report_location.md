# Review Record: error-report.ndjson relocation (contract amendment + tests gate)

- **Contract:** `contracts/frontend/playwright_harness.md` (amended §2/§7) · **Tests:**
  `tests/frontend/playwright_harness.test.ts` + `tests/frontend_e2e/helpers/reportPaths.ts`
- **PR:** #58 (`fix/frontend-error-report-location`, draft) · task #16
- **Reviewer:** frontend-reviewer · **Stage:** 1 · **Date:** 2026-06-11
- **Verdict:** **REQUEST_CHANGES** (1 must-fix: consumer instruction not updated)
- **Origin:** my non-blocking follow-up from the PR #25 stage-2 review.

## What is good
- **Path move is correct.** `playwright-report/error-report.ndjson` →
  `test-results/error-report.ndjson`. The HTML reporter manages/clears `playwright-report/`;
  `test-results/` is Playwright's artifact dir, not owned by the HTML reporter — the right target.
- **`reportPaths.ts` single source of truth** (`ERROR_REPORT_PATH`) consumed by both the writer
  (`errorCapture.ts`, per impl plan) and the verifier test — drift caught immediately. Stub
  correctly RED (exports the old path) at the gate.
- Test pins `ERROR_REPORT_PATH === "test-results/error-report.ndjson"`.

## MUST-FIX
1. **The operative QA instruction is not updated → QA gets directed to the wiped/old path.** The
   contract §7 text in `playwright_harness.md` was changed, but the **actual skill file QA loads**,
   `.claude/skills/qa-verification/SKILL.md:42`, still says
   `Attach the playwright-report/error-report.ndjson`. PR #58 doesn't include that file, and the
   impl plan (errorCapture.ts + stub) doesn't mention it. No test catches this (doc text). When the
   artifact moves to `test-results/`, QA following SKILL.md looks in the old/wiped location —
   defeating the fix. **Fix:** the implementation MUST also update
   `.claude/skills/qa-verification/SKILL.md` (line ~42) to `test-results/error-report.ndjson`
   (the contract already lists SKILL.md as a deliverable in §1 — the amendment just needs to update
   the path inside it). Add it to the implementation scope.

## SHOULD-FIX
- Update the `tests/frontend_e2e/smoke.spec.ts` header comment (line 8) referencing the old path
  for consistency. (`errorCapture.ts` is already in the engineer's plan — confirm at stage-2.)

The path-move + reportPaths + test are sound; this is purely scope-completeness so the consumer
(QA) instruction matches the new path. Re-request once SKILL.md is in scope.
