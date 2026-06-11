# Review Record: Inference Session Control (contract + tests gate)

- **Contract:** `contracts/frontend/inference_session.md`
- **Tests:** `tests/frontend/inference_session.test.tsx`
- **PR:** #50 (`feat/frontend-inference-session`, draft) · task #27
- **Reviewer:** frontend-reviewer · **Stage:** 1 (contract + test-cases gate)
- **Date:** 2026-06-11
- **Verdict:** **REQUEST_CHANGES** (2 should-fix contract items; reviewer regression tests pushed)

## What is good (verified against serving)

Cross-checked the session protocol against `contracts/serving/inference_stream.md` and
`rest_api.md` — strong conformance:
- **status frame** shape exact (kind/state `ready|running|paused|stopped`/session_id/step/
  episode/run_id/site_id) — matches inference_stream.md:165–182.
- **error frame** — all 9 codes match serving verbatim (run_not_found … internal),
  inference_stream.md:191–209.
- **cmd:start** field names (`run_id`, `site_id`, `speed`) + `site_id="gansu"` match; `speed`
  default 1.0 = D24 (inference_stream.md:273–280).
- **GET /runs/latest** exists, returns RunInfo (`id`, `has_policy`, `created_at`), 404
  `{"error":"no runs found"}` → `no_runs_found` — matches rest_api.md:139–142. `/api` baseUrl +
  proxy rewrite (PR #45) routes it correctly.
- send() no-op-when-disconnected, pause/resume/setSpeed clamp [0,100], SessionControlStrip per-state
  UI, SiteView mount — all well-specified.

## MUST-FIX (resolve pre-implementation)

1. **`session_id` is stored but never used to reset telemetry history — same-run restart mixes
   sessions.** Serving assigns a fresh `session_id` per `start` *specifically* to let the client
   distinguish a new session from a resumed one and "prevent history mixing"
   (inference_stream.md:180–182). `_autoStart()` fires on **every** `ready` (incl. reconnect) and
   always picks the latest run — so a restart of the **same** `run_id` yields a new `session_id`
   but, because telemetryStore only resets on `run_id` change (§12.3), the new session's step-0
   frames **append to the old session's history** → the timeline jumps back to step 0 and the ring
   buffer/scene mix two sessions. **Fix:** on a `session_id` change, call
   `telemetryStore.clearHistory()` (wire it in `handleServerStatus`), OR add an explicit
   Out-of-scope note documenting the run_id-only reliance + this same-run-restart limitation.
2. **§1.3 payload-guard relaxation must be unambiguously kind-specific.** "skip the guard before
   the kind switch" can be misread as dropping the guard for ALL kinds — which would let a malformed
   `env_step`/`train_metrics` with no `payload` reach the stores and crash the dashboard (the
   D18 load-bearing guard). Tighten §1.3: relax ONLY for `status`/`error`; `env_step`/
   `train_metrics`/`eval_compare` still require `payload`.

## Reviewer tests pushed (this commit)

Added to the §IS1–§IS5 block (share the WebSocket mock):
- `env_step` WITHOUT payload still discarded (`onEnvStep` NOT called) — enforces the kind-specific
  relaxation; a "skip guard for all" impl would pass §IS4/§IS5 but fail this.
- `train_metrics` WITHOUT payload still discarded.
- `status` frame (no payload) IS dispatched — relaxation works for control frames.

## Notes (non-blocking)

- serving's `cmd:start` also accepts optional `seed` (default 0); the frontend omits it → server
  default. Fine for v1 (no seed control); worth a one-line note.

## Approved suite (on re-request)
Developer §IS1–§IS25 + my 3 payload-guard regression cases. Re-request when the two must-fix items
land.

---

## Round 2 @ commit `b776a80` — **APPROVE**

Both must-fix items resolved (verified against the diff):

1. **§1.3 payload-guard — resolved.** Reworded to be explicitly kind-specific: only `status`/`error`
   bypass the `payload === undefined` check; `env_step`/`train_metrics`/`eval_compare` still require
   payload (load-bearing per D18). Added an implementation note (branch on control-vs-data frame; do
   NOT drop the guard globally). My 3 reviewer regression tests pin it (intact).
2. **`session_id` → `clearHistory()` — resolved.** §3.3 "running" row now calls
   `telemetryStore.clearHistory()` when `frame.session_id !== current sessionId`, before the state
   update, with the rationale (inference_stream.md:180–182, reconnect/same-run risk) inline. §IS13b
   (new session_id → clearHistory called once + sessionId updated) and §IS13c (same session_id →
   not called + step updates) test both branches correctly (spy on the real
   `telemetryStore.clearHistory`).
3. **seed** out-of-scope note added.

Both prior inline threads resolved; 0 unresolved.

### Non-blocking integration note (verify at stage-2)
`session_id` is delivered only via **status** frames, so the clear fires in time only if serving
emits a `status` (running) frame carrying the new `session_id` **at session start, before** it
streams `env_step` frames. If serving streams `env_step` first, the new session's opening frames
briefly mix into the old history until the first status frame arrives. The contract's mechanism is
correct (this is a serving emit-order detail) — recommend confirming with serving-engineer / in the
integration pass. A belt-and-suspenders fallback (also reset on same-run step regression) is
optional, not required.

### Approved suite
Developer §IS1–§IS25 + §IS13b/§IS13c + my 3 payload-guard regression cases. Cleared for
implementation; mark ready for the stage-2 audit (real wsClient guard branch, session_id reset
wiring, cmd:start shape, REST endpoint).

**Verdict: APPROVE** (stage-1 gate).

---

## Stage-2 implementation audit — PR #50 @ `5c8c413` (marked ready) — **APPROVE**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

Audited the implementation against the approved contract. No findings.

- **wsClient payload-guard (D18) — correct & kind-specific.** `isControlFrame = kind==="status" ||
  kind==="error"`; `if (!isControlFrame && msg.payload === undefined) discard` — data frames
  (env_step/train_metrics/eval_compare) still require payload; schema-version check also gated to
  data frames. Exactly §1.3; passes my 3 regression tests. The D18 hole is NOT reopened.
- **`session_id` → `clearHistory()` — correct.** `handleServerStatus` "running" branch:
  `if (frame.session_id !== null && frame.session_id !== currentSessionId) clearHistory()` BEFORE
  the state update. Guards null (no clear at ready/stopped). Matches §3.3 + §IS13b/§IS13c.
- **`cmd:start` shape** `{cmd:"start", run_id, site_id:"gansu", speed: get().speed}` via
  `telemetryWsClient.send()`; speed default 1.0 (D24). **setSpeed** clamps [0,100]. **send()** is a
  no-op when `ws===null`, else `ws.send(JSON.stringify(msg))`.
- **`_autoStart`** fetches `restClient.getLatestRun()` → `startSession(run.id, "gansu")`; errors →
  `serverState="error"`. **restClient.getLatestRun** → `GET /api/runs/latest`, 404→`no_runs_found`.
  **handleServerError** → `serverState="error"`, `errorMsg = code: message`.
- **Singleton** wires onServerStatus/onServerError on `telemetryWsClient` ONLY (training client
  excluded) → inferenceSessionStore. **No rogue sockets** (grep: only the singleton + wsClient).
- **SessionControlStrip** all 6 states + testids; retry resets to idle + re-fires ready→_autoStart.
  **SiteView** renders `<SessionControlStrip />`. 628/628 pass (incl. my regression + §IS13b/c + the
  reviewer §IS22 harness fix).

### Carried-forward integration note (non-blocking)
session_id arrives only via status frames → the history-clear fires in time only if serving emits a
`status:running` (with the new session_id) at session start before `env_step` streams.
frontend-engineer will confirm the emit order with serving-engineer during integration (optional
fallback: also reset on same-run step regression). Not gating.

**Verdict: APPROVE** (stage-2). Mergeable on this APPROVE + QA_PASS.
