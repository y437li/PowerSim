# Review Record: telemetry_validator Robustness Amendment (contract + tests gate)

- **Contract:** `contracts/frontend/telemetry_validator.md` (§9 amended; §10/§12/§13/§14 added)
- **Tests:** `tests/frontend/telemetry_validator.test.tsx` (TV.ROB.1–20)
- **PR:** #53 (`feat/frontend-telemetry-validator-robustness`, draft) · task #29
- **Reviewer:** frontend-reviewer · **Stage:** 1 (contract + test-cases gate)
- **Date:** 2026-06-11
- **Verdict:** **APPROVE** (1 reviewer test pushed; 1 follow-up recommendation)

## Origin
Implements the finding list I gave frontend-engineer from my PR #46/D26 system-coupling audit.

## What is good (verified)
- **`validate()` wired at `wsClient.handleMessage` before dispatch (§10)** — a *better* single
  chokepoint than the store boundary I'd suggested: it protects BOTH telemetryStore and
  trainingStore at once, and `validate()` is **kind-aware** (schema map for
  env_step/train_metrics/eval_compare, lines 190–192) so it picks the right schema per kind.
  Control frames (status/error) correctly bypass (no `payload` envelope). The PR #50 payload-guard
  is preserved for control frames — no conflict.
- **The exact PR #46 crash path is closed:** invalid env_step (missing `payload.battery`) →
  `validate() ok:false` → dropped → never reaches the store → component never derefs
  `envStep.battery.soc`. Tested (TV.ROB.2).
- **Exception safety (§10.2):** `validate()` wrapped in try/catch → throw treated as `ok:false`,
  `errors:["validate_threw"]`, no propagation, WS stays alive (TV.ROB.13/14).
- **Surfacing, not silent drop (§13 = my A2):** `FrameError` {kind, seq, errors[]} +
  `telemetryStore.frameErrors` ring buffer (cap 10, prepend) + `pushFrameError` + `clearHistory`
  reset + AlertList/FrameErrorBanner UI (`frame-error-<index>`). Tested (TV.ROB.3/4/15–18).
- **Drop = keep-last-good:** dropped frames simply aren't dispatched, so the store keeps its prior
  envStep (TV.ROB.11), and a subsequent valid frame is dispatched (recovery — TV.ROB.10).
- **Coverage maps to my finding list T1–T10:** all-three-kinds accept + reject (env_step/
  train_metrics; status bypass), recovery, keep-last-good, exception safety, ring buffer, golden
  pipeline (TV.ROB.19/20, validate-telemetry skill).

## Reviewer test pushed (this commit)
- **Wrong-type field** (`battery.soc` as a string) through the gate → dropped. Distinct Zod
  rejection path vs missing (TV.ROB.2) / null (TV.ROB.5); completes the missing/null/wrong-type
  matrix. (Note: a literal NaN/Inf over the wire is already handled upstream — JSON.parse throws →
  wsClient's existing invalid-JSON discard — or arrives as `null` per JSON, i.e. TV.ROB.5; so a
  NaN test would be redundant.)

## Follow-up recommendation (NOT blocking this gate)
- **A4 — ErrorBoundary `resetKeys` (defense-in-depth).** The contract names the sticky, no-reset
  app-level ErrorBoundary as the crash *amplifier* (motivation), and §10 removes the *trigger*
  (malformed frames no longer reach components). With that, the ErrorBoundary stickiness now only
  bites on a NON-telemetry component crash — a different, lower-priority failure class, genuinely
  out of scope for "malformed-frame handling." Recommend a small follow-up (resetKeys on
  run_id/seq so any residual render crash self-heals) tracked as its own task. Not required here.

## Approved suite
Developer §9 + TV.ROB.1–20 + my wrong-type reviewer test. Cleared for implementation (wsClient
wiring + telemetryStore.frameErrors API + the FrameError UI). Currently 54/74 green, RED pending
implementation — expected gate state.

**Verdict: APPROVE** (stage-1 gate). Should ship before the task #23 real-checkpoint cutover.

---

## Stage-2 implementation audit — PR #53 @ `ab49fc4` (wsClient-gate version) — **REQUEST_CHANGES**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

### Correct (no findings)
- **wsClient §10 gate.** `validate()` called in `handleMessage` for data frames only
  (`!isControlFrame`); control frames (status/error) bypass. try/catch → `validate_threw` drop
  (no propagation); `ok:false` → drop + `console.warn(kind/seq/errors)` + `pushFrameError`;
  `ok:true` + warnings → dispatch AND record. Existing envelope checks (JSON / kind / payload /
  version) preserved. **The PR #46 crash path is closed** — missing `payload.battery` →
  `ok:false` → dropped → never dispatched. My wrong-type reviewer test passes against this.
- **telemetryStore §13.** `FrameError {ts_utc,kind,seq,errors[]}`; `frameErrors:[]` initial;
  `pushFrameError` prepends + caps at 10 (`next.length = FRAME_ERRORS_CAP`); `clearHistory`
  resets. Correct.
- 75/75 telemetry_validator tests; 704/704 overall (engineer-reported).

### MUST-FIX
1. **`FrameErrorBanner` is built but NOT mounted → the §13.3 "MUST render" surfacing is dead.**
   `git grep FrameErrorBanner` finds no usage outside the component file; LiveDashboard / SiteView /
   AlertList / App are untouched. Dropped frames are recorded in `telemetryStore.frameErrors` but
   never displayed → the operator never sees that frames were dropped (A2 defeated). Contract §13.3
   requires `frameErrors` to be **rendered** (AlertList or a FrameErrorBanner adjacent to it).
   **Fix:** mount `<FrameErrorBanner />` in the dashboard (SiteView/LiveDashboard, adjacent to
   AlertList) + add a render-integration test (non-empty frameErrors → `frame-error-0` visible with
   kind/seq/error; empty → no nodes). There is currently **no banner render-test anywhere**.

### Observation (not my area — flag to team-lead/backend-reviewer)
- The diff vs `main` includes unrelated training files (`src/energy_go/training/*`,
  `training_pipeline.*`, `pyproject.toml`, `ci.yml`). Likely branch-base divergence rather than
  scope creep, but worth a glance to ensure this PR isn't carrying unintended changes.

**Verdict: REQUEST_CHANGES.** The drop/safety is correct and well-tested; mount the banner +
add the render-integration test so the dropped-frame surfacing actually reaches the operator,
then re-request.
