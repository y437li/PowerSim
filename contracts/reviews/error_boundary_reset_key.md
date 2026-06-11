# Review Record: ErrorBoundary resetKey (contract + tests gate)

- **Contract:** `contracts/frontend/error_boundary_reset_key.md`
- **Tests:** `tests/frontend/error_boundary_reset_key.test.tsx`
- **PR:** #54 (`feat/frontend-error-boundary-reset-key`, draft) · task #30
- **Reviewer:** frontend-reviewer · **Stage:** 1 (contract + test-cases gate)
- **Date:** 2026-06-11 · **Verdict:** **APPROVE** (1 reviewer test pushed)
- **Origin:** my A4 finding from the PR #53 review (deferred there as a non-blocking follow-up).

## What is good (verified)
- **§2.3 reset logic is correct** — reset only when `hasError && key changed`; the
  `elif (!hasError && key changed → update prevResetKey)` branch tracks the key *while healthy*,
  which prevents a stale-`prevResetKey` spurious self-reset on a later crash. `else → null`
  avoids needless re-renders. Uses `getDerivedStateFromProps` (synchronous, no flash) — correct.
- **§3 wiring uses `runId`, not `seq` — the sounder choice.** Per-frame `seq` reset would risk a
  catch→reset→re-crash render storm on a *persistent* crash; `runId` scopes self-heal to the safe
  new-run boundary, which matches the stated failure mode (stale state at a new-run boundary).
  `resetKey={runId ?? ""}` coalesce is correct (avoids a null key). `re-crash → re-catch` (EB.RK.5)
  confirms no error suppression.
- Existing fallback unchanged (§4); 7 EB.RK tests map to the §5 acceptance criteria.

## Reviewer test pushed (this commit)
- **EB.RK.8 — healthy key-change then crash → clean catch, stays errored.** Targets the §2.3
  healthy-tracking elif: an impl that updates `prevResetKey` only on reset would loop
  (reset→re-throw→re-catch) on a crash whose key already changed while healthy. Green for a correct
  impl, red for that specific bug.

## Approved suite
Developer EB.RK.1–7 + my EB.RK.8. Cleared for implementation (ErrorBoundary prop + getDerivedStateFromProps
+ App.tsx wiring). Mark ready for stage-2.

**Verdict: APPROVE** (stage-1 gate).
