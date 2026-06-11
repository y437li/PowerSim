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
