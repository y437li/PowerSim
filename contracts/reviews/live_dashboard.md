# Review record — `live_dashboard` (frontend)

Contract: `contracts/frontend/live_dashboard.md`
Tests: `tests/frontend/live_dashboard.test.tsx`
PR: #34 (`feat/frontend-live-dashboard`)
Reviewer: frontend-reviewer
Gate: stage 1 (contract + test cases, pre-implementation)

## Verdict history

- 2026-06-10 — **REQUEST_CHANGES** @ commit `7df1d18`: 1 blocker (C1 rendered-band geometry
  untested) + 3 should-fix (epsilon alert guard, AlertList order undefined, MonthPeakCard inline
  formatting).
- 2026-06-10 — **APPROVE** @ commit `7b2ac3b`: all four findings resolved. Approved test-file
  version = `tests/frontend/live_dashboard.test.tsx` @ `7b2ac3b` (blob `a4cb70e`); approved
  contract version `contracts/frontend/live_dashboard.md` @ `7b2ac3b` (blob `6a1883f`).

## Resolution audit (commit `7b2ac3b`)

1. **[blocker] C1 band geometry — RESOLVED.** Contract §2.4 now mandates `data-tier` /
   `data-from-min` / `data-to-min` on each `<li>` of the accessible band list (9 `<li>`s, one per
   `TOU_SCHEDULE` entry). Three new `PriceTimeline` tests pin the *rendered* edges:
   morning critical-peak `data-from-min="630"` / `data-to-min="690"` (10:30–11:30, D8), 9-`<li>`
   count, and valley `0–420`. A naïve hourly-boundary implementation (660/720) fails immediately.
   Verified the asserted boundaries are byte-consistent with the contract `TOU_SCHEDULE` (lines
   66–75) and the `getTouTier` 16-boundary table (lines 96–111): 630→critical_peak, 690→mid,
   1140→critical_peak, 1260→peak — no second source of truth.

2. **[should] epsilon alert guard — RESOLVED.** Contract §4 adds `ALERT_EPSILON = 0.001` MW; all
   three thresholds changed `> 0` → `> ALERT_EPSILON`. Five new tests: 0.0005 (no fire), 0.001
   (no fire — exclusive boundary), 0.0011 (fires) for curtailment, plus sub-epsilon VOLL and SOC
   variants. Guards against sub-tolerance JAX float noise raising spurious alerts.

3. **[should] AlertList order — RESOLVED.** Contract §2.6 + §4 define newest-first (highest
   `stepIndex` at top); `deriveAlerts` returns `alerts.reverse()`. Two new ordering tests
   (multi-step descending + single-step). Note (non-blocking): within a single step, `reverse()`
   also flips the curtailment→voll→soc push order; cross-step ordering — the contract's stated
   guarantee — is correct and tested.

4. **[should] MonthPeakCard formatting — RESOLVED.** Contract §2.5 + §5 table mandate
   `formatPower(monthPeakMw)`; inline `${v.toFixed(1)} MW` removed. New test imports `formatPower`
   and asserts the rendered `month-peak-mw` text contains `formatPower(95.0)` — ties display to the
   shared utility rather than a hardcoded string.

## Telemetry conformance (validate-telemetry skill)

Consumer-side conformance preserved: Section 1 validates `env_step` golden fixtures A/B; D13 cost
identities tested as the real-money 5-summand additive identity (`cost_total_real == −52,700` A /
`3,050,400` B), `c_energy == c_import − r_export` display-only decomposition, and the
`reward = −(cost_total_reward_basis + penalty)×1e-5` formula. Field names/units match LOCKED
`telemetry_schema.md` v1.0.0.

## Approved suite

Developer cases + reviewer-marked C1/epsilon/ordering/formatPower edge cases (test file
`// reviewer:` block). This suite is the locked spec for stage-2 implementation; tests are red by
design (no `src/` impl yet) and become green under QA after implementation.

## Notes / non-blocking nits

- `live_dashboard.md` and `live_dashboard.test.tsx` carry the executable bit (mode 100755). Prefer
  `chmod 644` on the next commit — cosmetic, does not gate.

---

## Stage-2 implementation audit — PR #34 (marked ready)

- **Reviewer:** frontend-reviewer
- **Date:** 2026-06-10

### Round 1 @ commit `9f0779d` — **REQUEST_CHANGES**
1. **[BLOCKER] PriceTimeline TOU bands on the wrong axis.** `ReferenceArea`s shaded the y-axis at
   price levels (0/350/535/700/900 ¥/MWh) instead of x-axis time-of-day windows per §2.4;
   `sim_time_utc` dropped. The visible chart never showed *when* critical-peak occurs; the C1 test
   passed only via the hidden `<li>` proxy. Classic green-test/wrong-display.
2. **[should] Price line flat `#1d4ed8`**, not tier-coloured per §2.4.
3. **[note]** `lastMessageTsUtc={null}` — acceptable (contract requires no live stale-detection).

### Round 2 @ commit `1f55207` — **APPROVE**
- **Finding 1 resolved.** New `computeBandSegments(history)` (`touSchedule.ts`) groups contiguous
  same-tier steps via minute-aware `getTouTier(hour_of_day*60 + minute_of_hour)` (D8) and returns
  `BandSegment{tier,x1,x2}` step-index spans. `PriceTimeline` rewritten: `ReferenceArea x1/x2` from
  those segments — true x-axis time bands, no y-stripes. `hour_of_day`/`minute_of_hour` are LOCKED
  sim-clock wire fields (telemetry.ts:109–110), equivalent to and cleaner than parsing
  `sim_time_utc`. 6 new tests pin explicit x1/x2 incl. the D8 guard (11:00=660min → critical_peak,
  not mid) — geometry now tested at the data level, closing the `<li>`-proxy gap.
- **Finding 2 resolved.** Tier-coloured line: one `<Line>` per `BandSegment`,
  `stroke=getTouColor(seg.tier).text`, with a bridge point to avoid inter-segment gaps.
- **Contract §2.4 + §1 change reviewed:** legitimate refinement/strengthening — explicitly
  prohibits y-axis stripes, documents x-axis step-index geometry + `computeBandSegments`/`BandSegment`,
  and pins the 11:00→critical_peak D8 guard. Frontend-only contract (not the LOCKED shared schema);
  no weakening.

### Open should-fix (non-blocking, recorded for follow-up)
- **Single-hour TOU bands render zero-width/invisible.** `x1`/`x2` are inclusive step indices, so a
  1-step tier run (the morning critical-peak is exactly one step at Δt=1h — `x1===x2`) produces a
  zero-width `ReferenceArea` → not visibly shaded over a 7-day window. Data/position are correct and
  the tier-coloured line still conveys the hour, so this is a visibility-polish defect, not a
  data-correctness error. **Recommend:** render the band x2 to the next segment boundary
  (`nextSeg.x1`, or `lastStep+1` clamped to dataMax) so single-hour bands (esp. morning
  critical-peak) are visible; keep `computeBandSegments` inclusive-step data semantics. No test can
  catch this (jsdom has no SVG layout) — audit-only.

**Verdict: APPROVE** (stage-2). Mergeable on reviewer APPROVE + QA_PASS. Engineer reports 459/459
passing; QA confirms green.
