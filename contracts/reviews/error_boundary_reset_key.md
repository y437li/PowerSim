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

---

## Stage-2 implementation audit — PR #54 @ `e8de034` — **APPROVE**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11 · No findings.

- **`getDerivedStateFromProps` matches §2.3 exactly.** Branch 1 (`hasError && key !== prevKey`) →
  reset (`hasError:false, error:null, prevResetKey:key`); branch 2 (`key !== prevKey`, reached only
  when `!hasError`) → advance `prevResetKey` only; else → null. The implicit `!hasError` on branch 2
  is sound (branch 1 already handled the errored case).
- **First-mount init is correct.** On first render `getDerivedStateFromProps` advances
  `prevResetKey` from `undefined` to the initial key (`""`), so a crash on that key does NOT
  spuriously self-reset — the exact case my reviewer EB.RK.8 guards; it passes.
- `getDerivedStateFromError` returns `Partial<ErrorBoundaryState>` (merges cleanly), correctly
  leaving `prevResetKey` to the props handler. `prevResetKey` initial `undefined` (§2.2). Render /
  fallback unchanged (§4).
- **App.tsx** wires `resetKey={runId ?? ""}` via a `useTelemetryStore((s)=>s.runId)` selector (App
  re-renders only on runId change). §3 satisfied.
- 8/8 GREEN incl. EB.RK.8; 691/691.

**Verdict: APPROVE** (stage-2). Mergeable on this + QA_PASS. Closes the A4 follow-up (task #30).
