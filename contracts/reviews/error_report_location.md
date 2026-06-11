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

---

## Round 2 @ commit `41da186` — **APPROVE**

Must-fix resolved (verified):
- **`.claude/skills/qa-verification/SKILL.md:42`** now attaches `test-results/error-report.ndjson`
  (was `playwright-report/...`) — the operative QA instruction QA loads is corrected, so QA is no
  longer directed to the wiped/old path.
- **Contract "Amendment deliverables"** now explicitly lists the SKILL.md path update as
  implementation-scope item 3 (alongside reportPaths stub→test-results and errorCapture.ts).
- **`smoke.spec.ts`** header comment updated to `test-results/` with a task-#16 rationale.
- Path move + `reportPaths.ts` single-source + the §T9 content gate (unchanged) all stand.

### Stage-2 verification note (not gating)
`errorCapture.ts` doc comments (lines ~8, ~48) still say `playwright-report/error-report.ndjson`.
The functional write path is being switched to import `ERROR_REPORT_PATH` from `reportPaths` at
implementation; the doc comments must be updated in the same change so they don't mislead. I'll
confirm at stage-2 that errorCapture both writes to `test-results/` AND its comments match (and the
transient test-comment at playwright_harness.test.ts:94 is updated when the stub flips).

9/10 GREEN, 1 RED (stub still exports the old path) — correct gate state.

**Verdict: APPROVE** (stage-1 gate). Cleared for implementation. Mark ready for stage-2.

---

## Stage-2 implementation audit — PR #58 @ `2f74aff` — **APPROVE**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11 · No findings.

- **reportPaths.ts** — `ERROR_REPORT_DIR = "test-results"`, `ERROR_REPORT_PATH =
  test-results/error-report.ndjson`; gate-stage stub removed. ✓
- **errorCapture.ts** — imports `ERROR_REPORT_PATH` from `./reportPaths` and writes via
  `path.join(process.cwd(), ERROR_REPORT_PATH)` (no hardcoded path); both stale doc comments
  (~8, ~50) + the inline rationale updated to `test-results/`. Single source of truth honoured. ✓
- **playwright_harness.test.ts:94** stub-state comment flipped. ✓
- All active/operative paths migrated (reportPaths, errorCapture write, SKILL.md, contract §2/§7,
  smoke comment). The only residual `playwright-report/error-report` strings are in review-record
  markdown (historical audit text — my record + the PR #25 record), not functional. 10/10
  playwright_harness; 739/739 full suite.
- No execution-environment risk (standard ESM import wiring; the §2 test pins the constant,
  errorCapture derives the write path from it). The runtime confirmation that the NDJSON lands in
  `test-results/` and survives an HTML-reporter run is QA's §8 manual E2E check.

**Verdict: APPROVE** (stage-2). Mergeable on this + QA_PASS (incl. the §8 browser/E2E run confirming
the file lands in test-results/). Closes task #16.
