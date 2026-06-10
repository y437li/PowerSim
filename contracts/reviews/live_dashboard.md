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
