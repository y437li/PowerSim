# Review Record: Frontend App Shell (contract + tests gate)

- **Contract:** `contracts/frontend/app_shell.md`
- **Tests:** `tests/frontend/app_shell.test.tsx`
- **PR:** #5 (`feat/frontend-app-shell`, draft)
- **Reviewer:** frontend-reviewer
- **Stage:** 1 — contract + test-cases gate (pre-implementation)
- **Date:** 2026-06-10
- **Verdict:** **REQUEST_CHANGES** (3 must-fix contract items; reviewer edge-case tests pushed to branch)

---

## Scope of review

Held the contract to `contracts/shared/telemetry_schema.md` field names/units, hunted for
missed edge cases (ws reconnect / out-of-order / seq gaps / missing fields / version skew /
unit display), and pushed reviewer test cases. Telemetry schema is **DRAFT, mid-revision by
rl-architect** — all wire-format-dependent cases (mine and the developer's) are marked
`PENDING_LOCK` and **must be re-verified after the telemetry LOCK**; this approval, once the
must-fix items land, is conditional on that re-check.

## What is good (no change needed)

- Unit utilities pin the prime-directive cases: SOC fraction→% (D4 0.2/0.9), MW↔kW,
  `formatYuanPerMwh` = `¥/MWh` (not /kWh), signed `¥-52,700` matches the contract example.
- D-decisions are correctly threaded: D3 (168 / 8760 / Δt=1h), D4 SOC bounds, D5 945 MW,
  fixtures use canonical MW / MWh / ¥ wire units.
- Ring buffer (drop-oldest at 168), seq-gap-detected, reject-`2.0.0`, invalid-JSON,
  unknown-kind, NaN/Infinity→"—", error-boundary isolation, REST 4xx/5xx/network all covered.
- eval_compare fixture is internally consistent (each policy's components sum to total;
  RL ≤ both baselines).

## MUST-FIX (blocking — resolve before stage-2 ready)

1. **`TouBadge.showPrice` has no price source — duplicated/undefined source of truth.**
   §7.3 says `showPrice` "renders price from §3.7", but `TouBadgeProps` carries no price and
   the live price is already on the wire as `price_buy_yuan_per_mwh`. A hardcoded §3.7 table
   in the shell duplicates wire data and will silently drift — exactly the displayed-¥ class
   of bug this gate guards. **Fix:** either add `priceYuanPerMwh?: number` (fed from the
   telemetry store, formatted via `formatYuanPerMwh`), or drop `showPrice` from the shell and
   leave price rendering to the dashboard. Add a test pinning the chosen source. No test
   currently covers `showPrice` at all.

2. **`formatSimTime` must extract the UTC clock explicitly.** §8 says "formats the UTC clock
   as-is, no timezone conversions," but neither the signature nor §8 require `getUTCDay`/
   `getUTCHours`. A naive `getHours()`/`getDay()` impl renders a tz-shifted sim clock (wrong
   day/hour) and still passes the developer's loose `/08:00/` match on a UTC CI runner. The
   developer test is also mislabeled "Monday" — 2026-03-10 is a **Tuesday**. **Fix:** contract
   states UTC-based extraction; reviewer tests now pin exact `"Tue 08:00"` and a day-boundary
   `"Mon 23:30"` case.

3. **§12.3 "reconnect with new `run_id`" reset is uncontracted in the store API.** §12.3 is a
   listed testable commitment with no developer test, and §6.1 doesn't say which layer enforces
   it. `receiveEnvStep` must, on a `run_id` change, reset `history`/`lastSeq`/`seqGap` so the
   new run's low seq doesn't false-flag a gap and old-run history doesn't merge. **Fix:**
   contract specifies the enforcing layer (recommend store-internal on `run_id` change — keeps
   a single source of truth); reviewer test encodes the end state.

## SHOULD-FIX (reviewer tests pushed; make green during implementation)

- **seq tracking:** first message is never a gap; `clearHistory` resets `lastSeq`/`seqGap`.
- **Out-of-order / duplicate seq is undefined.** `seqGap` is defined only for a forward gap.
  Contract should state the behavior for a non-monotonic seq (backwards / duplicate delivery on
  the socket). Not hard-pinned by a test pending that decision — flag for the dev/architect.
- **wsClient:** missing-`kind` / missing-`payload` envelopes discarded (§4.3, was untested);
  minor-forward-compat (a `1.x` message with an unknown extra field still dispatches — §8.5
  `assets_ext` growth depends on this); `stale` recovers to `connected` on the next message
  (§4.1.5 leaves `stale` a dead-end state).
- **restClient:** timeout path (§5 `timeout:` was untested); `getSiteConfig` field-name/unit
  pinning (only `getRuns` was tested — `pcc_max_export_mw`/`battery_capacity_mwh` feed 3D scaling).
- **NumberDisplay:** negative finite values must pass the guard (cost/net can be negative).
- **formatPower(0):** zero-flow output defined as `"0 kW"`.
- **evalStore:** developer "stores all three policies" test depends on the prior test's leaked
  state — reviewer added a self-contained version; dev should fix theirs to dispatch its own
  fixture.

## Notes / advisory (non-blocking)

- **Store field mirroring (§6.1).** "all EnvStepPayload fields mirrored as store state" plus a
  full `envStep` invites derived-state drift. Prefer `envStep` as the single source and derive
  in selectors, or test that mirrors stay in sync. Recommend trimming the mirror in the contract.
- **Per-source flow conservation is NOT frontend-verifiable** from the schema: `ren_curtailed_mw`
  is aggregate, with no per-source `gross_*` fields, so `to_load+to_bat+to_grid+curtailed==gross`
  can't be asserted on the consumer side. That's a telemetry-contract observation for
  backend-reviewer, not a blocker here.
- **Zustand: RATIFIED.** Lightweight, supports the imperative `useStore.getState()` access the
  ws client needs from outside React, and the singleton + `clearHistory` reset pattern the tests
  rely on. Record it in STACK.md (task #19) once that registry lands.

## Reviewer-added test cases (pushed to branch, marked `// reviewer:`)

1. `formatSimTime` exact UTC `"Tue 08:00"` (day-of-week pinned)
2. `formatSimTime` day-boundary `"Mon 23:30"` (catches local-time impl)
3. `formatYuanPerMwh` ¥/MWh unit guard (not /kWh)
4. `formatPower(0)` → `"0 kW"` (zero-flow rendering)
5. `NumberDisplay` negative finite value renders
6. `telemetryStore.clearHistory` resets `lastSeq`/`seqGap`
7. `telemetryStore` first message is not a gap
8. `telemetryStore` §12.3 new `run_id` resets state (no merge, no false gap)
9. `wsClient` missing-`kind` envelope discarded (§4.3)
10. `wsClient` missing-`payload` envelope discarded (§4.3)
11. `wsClient` minor-forward-compat (`1.x` + unknown field dispatches)
12. `wsClient` `stale` → `connected` recovery on next message
13. `restClient` timeout rejects `/timeout/` (§5)
14. `restClient` `getSiteConfig` field-name/unit pinning (945 MW / 294.5 MWh)
15. `evalStore` self-contained dispatch (test-isolation fix)
16. `evalStore` cost components sum to `total_cost_yuan`

**Approved suite = developer's 70 cases + these 16 reviewer cases**, all conditional on the
telemetry LOCK re-check for the `PENDING_LOCK`-marked cases.

## Re-review trigger

Re-review on: (a) the 3 must-fix items addressed in a revised contract + tests, and
(b) the telemetry_schema.md LOCK (re-verify every `PENDING_LOCK` fixture against locked
field names/units). Stage-2 (implementation) audit happens when the PR is marked ready.

---

## Re-review (stage 1b) — 2026-06-10 — VERDICT: APPROVE

Re-reviewed after commits 2df39b8 (must-fix + should-fix) and 517af89 (post-LOCK
re-verification). Verified against the code, not the summary:

- **Must-fix 1 (TouBadge price source):** RESOLVED — `priceYuanPerMwh?: number` fed from the
  wire `price_buy_yuan_per_mwh`, formatted via `formatYuanPerMwh`, explicit "never a hardcoded
  table"; 3 tests pin render/absent/showPrice=false. Thread resolved.
- **Must-fix 2 (formatSimTime UTC):** RESOLVED — §8 mandates `getUTCDay/getUTCHours/getUTCMinutes`,
  states `getHours()/getDay()` is incorrect, returns `"Tue 08:00"`; dev test relabeled Tuesday and
  tightened to `toBe("Tue 08:00")`. Thread resolved.
- **Must-fix 3 (§12.3 run_id reset):** RESOLVED — §6.1 specifies store-internal reset before
  append; seqGap defined (`seq > lastSeq+1`; out-of-order/dup accepted; first never flags);
  clearHistory resets lastSeq/seqGap. Thread resolved.
- **Should-fix:** evalStore test self-contained; seqGap non-monotonic defined. Resolved.
- **Post-LOCK field conformance (telemetry_schema v1.0.0, PR #6):** COMPLETE and correct — §3
  types and all three fixtures migrated exactly: `BatteryState.p_max_*`, `GenerationBlock`,
  split `solar_/wind_curtailed_mw`, `c_demand_charge_yuan` + `demand_rate_yuan_per_mw_month` +
  the two cost totals, 9-field `cost_cum`, train_metrics reward triplet (`reward_norm_mean:
  number|null`), eval `cost_basis` + `soc_violation_mwh` + `penalty_yuan`. Golden-A arithmetic in
  the fixture hand-verified (c_energy −53100, cost_total_real −52700, reward 0.527, conservation
  30 / 92.5).
- **Reviewer tests:** my 16 cases intact; added 4 more (env_step two-cost-total identities,
  reward formula, per-source conservation) — locked-acceptance integrity guards for the golden
  fixture. Approved suite = developer cases + 20 reviewer cases.

**Non-blocking nit (clean up on merge):** Status/Spec line 4 and the `telemetry.ts` directory
comment (line 42) still read "DRAFT — PENDING TELEMETRY LOCK"; §3 and the body are correctly
LOCKED. Cosmetic metadata only.

**Verdict: APPROVE** (stage-1 contract+tests gate). Posted as a PR comment per the verdict-marker
convention. Implementation may proceed against these locked types; QA closes the task.
