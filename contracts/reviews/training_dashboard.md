# Review Record: Frontend Training Dashboard (contract + tests gate)

- **Contract:** `contracts/frontend/training_dashboard.md`
- **Tests:** `tests/frontend/training_dashboard.test.tsx`
- **PR:** #21 (`feat/frontend-training-dashboard`, draft)
- **Reviewer:** frontend-reviewer
- **Stage:** 1 — contract + test-cases gate (pre-implementation)
- **Date:** 2026-06-10
- **Verdict:** **REQUEST_CHANGES** (2 must-fix; reviewer tests pushed)

---

## Scope

Held the contract to the LOCKED telemetry schema v1.0.0, the APPROVED app_shell contract
(stores/clients/types/`units.ts`, `WsStatus`), D13 cost accounting, and the `validate-telemetry`
golden-fixture requirement. Verified the golden fixtures exist and match the assertions.

## What is excellent (no change)

- **validate-telemetry coverage (Section 1) is exemplary.** Full-message golden validation:
  envelope fields, every payload field + type, NaN/Inf finiteness, the **D13 additive identity
  per policy** (`total_cost_yuan == energy+demand_charge+degradation+curtailment+voll`), SOC
  violations/penalty **excluded** from the total, RL-is-best (§5), and round-trip. I confirmed the
  golden fixtures (`contracts/shared/telemetry_examples/{train_metrics,eval_compare}.json`) exist
  and their values match every assertion (rl 22.8M = 12M+9M+1.5M+0.3M+0; rule_based 28.5M with
  penalty 30,000 excluded; cost_basis "real_money"; horizon 8760).
- **D13 displayed-cost correctness:** the cost panel/checkpoint list plot `cost_total_real_mean_yuan`
  (real money, negative allowed, never the reward-basis), and the eval table sums exactly the five
  real-money components with the SOC footnote. No `c_import`/`r_export` confusion (those aren't in
  these payloads). Reward-basis (`reward_norm_mean`) deliberately not plotted — correct.
- **Extensibility:** `Object.keys(policies)` iteration + `POLICY_DISPLAY_NAMES` fallback covers the
  §11 baselines and unknown keys (greedy/dp_oracle/title-cased) — well tested.
- Empty/null/placeholder states, negative-cost axis, single-point history, checkpoint markers,
  REST error+retry, minor-forward-compat — all covered.

## MUST-FIX (blocking)

1. **`WsStatus` contradicts the APPROVED app_shell contract.** §2.3 and §3.7 declare
   `WsStatus = "connecting"|"connected"|"disconnected"|"error"`, but the dependency contract
   (`app_shell.md` §4, approved on PR #5 — the stable boundary this dashboard consumes) defines it
   as `…|"stale"`. The shell store **never emits `"error"`**, so §3.1's empty-state guard
   `wsStatus !== "error"` is dead (always true), and the union omits the real `"stale"` value.
   **Fix:** use the app_shell union verbatim (`connecting|connected|disconnected|stale`); replace
   the §3.1 `!== "error"` guard with the intended condition (likely `!== "disconnected"`); and
   decide how the banner reacts to the store's `"stale"` (today it recomputes stale locally from
   `ts_utc`, which is a legitimate wall-clock use of the emit clock — but the type must not lie).

2. **`train_metrics` seq-gap has no real data source; the test fakes it with a non-schema `_seq`.**
   §5/§3.7 require `TrainingPanel` to compute `seqGap` from `msg.seq`, but the APPROVED
   `trainingStore` exposes only `history: TrainMetricsPayload[]` + `latest` — no envelope `seq`,
   and `TrainMetricsPayload` has no seq field. The Section-10 "gap" test injects a fictional
   `{ ...GOLDEN_TRAIN, _seq: 12 }` property, and the "no gap" test maps envelopes to `.payload`
   (discarding seq) — so the mechanism can't exist in implementation and the tests don't pin a real
   path (a "sequence gap" banner that can fire off an impossible field, or never fire). **Fix:**
   give `seqGap` a real source — extend `trainingStore` to track `lastTrainSeq`/`trainSeqGap`
   (mirroring `telemetryStore`'s env_step gap; this is an app_shell §6.2 change — coordinate with
   frontend-engineer and amend that contract), or have the wsClient thread `seq` into the store.
   Then rewrite the Section-10 tests to drive that real mechanism, not a `_seq` payload field.

## SHOULD-FIX (non-blocking; reviewer tests pushed where unambiguous)

- **§3.4 `formatThroughput` doc example is wrong:** `≥1,000 → "1,350k/s"` (1,350k = 1.35M, which is
  the ≥1M case). §4 and the tests correctly say `"350k/s"`. Fix the §3.4 example.
- **E17 (`formatSteps(1e9)`) has no test and an ambiguous spec** ("1,000M steps" *or* "1B steps").
  Pick one and add a test. Likewise define rounding for non-exact thousands (e.g. `formatThroughput(1500)`,
  `formatSteps(1500)` — floor vs round) so the displayed number is deterministic.
- **Best-policy tie:** if two policies share the lowest `total_cost_yuan` (incl. RL tying a baseline),
  which row gets `data-best`? The §5 criterion is "RL ≤ both baselines" (RL passes on a tie) — define
  tie handling (recommend RL wins ties, so a tie isn't shown as an RL failure) and add a test.
- **Empty + disconnected:** with `history === []` AND disconnected, specify whether the placeholder,
  the banner, or both render (ties into must-fix 1's §3.1 condition).

## Reviewer-added tests (pushed, `// reviewer:`)

1. EvalCompareTable renders a zero-¥ component as `"¥0"`, not a blank cell.
2. `formatThroughput(0)` → `"0/s"` (startup).
3. `formatThroughput(999)` → `"999/s"` (sub-k boundary).
4. `formatWallSeconds(59.9)` → `"59s"` (sub-second floor in the <60 branch).

**Approved suite = developer cases + these 4 reviewer cases.**

## Re-review trigger

Re-request when must-fix 1 (WsStatus alignment + §3.1 condition) and must-fix 2 (real seqGap data
source + de-fictionalized Section-10 tests) land. Stage-2 implementation audit on PR-ready — I'll
run `validate-telemetry` against the implementation and re-check D13 in the rendered cost table.

---

## Re-review (stage 1b) — 2026-06-10 — VERDICT: APPROVE

Re-reviewed e140d94 against code:
- Must-fix 1 (WsStatus): RESOLVED — §2.3 = app_shell union verbatim; §3.1 guard `!== "disconnected"`; §3.7 store-stale + precedence.
- Must-fix 2 (seqGap): RESOLVED — `trainingStore` amended with `lastTrainSeq`/`trainSeqGap` (forward-only, first-never, clear-resets); §5 store-based; Section-10 tests store-mock (no `_seq`).
- Should-fix: RESOLVED — `formatThroughput` doc fix + B-tier (1e9→"1B/s") + floor (1500→"1k/s"); `formatSteps(1e9)="1B steps"`; tie-break test. My 4 reviewer tests intact.

Tracked dependency (note, not a gate blocker): the app_shell `trainingStore` implementation must gain `lastTrainSeq`/`trainSeqGap` before the dashboard implementation — coordinated with frontend-engineer.

Verdict: APPROVE (stage-1 gate). Stage-2 implementation audit on PR-ready — I'll run validate-telemetry and re-check D13 in the rendered table.
