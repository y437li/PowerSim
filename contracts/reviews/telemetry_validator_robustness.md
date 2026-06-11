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
