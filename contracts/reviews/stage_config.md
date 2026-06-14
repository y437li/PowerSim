# Review record — `stage_config` (Wizard Stage ①, PR #102)

**Reviewer:** frontend-reviewer · **Feature:** `contracts/frontend/stage_config.md` · **Task:** #2

## Round 1 — `cfeb8c1` — REQUEST_CHANGES (2026-06-13)
Pre-implementation contract+tests gate. 4 blockers + 2 must-fixes:
- **B1** §5.1 validate request body was `{assets:{fleet:[{model_id,count}]}, tariff_region}` — did NOT match the category-keyed MW/MWh site-config schema the validator consumes (`device_model_schema` §7, `config_validation` rules key on `assets.battery.fleet_capacity_mwh` etc.). Device rules would silently no-op → false "valid".
- **B2** No test pinned the validate request body (only URL+timing).
- **B3** Contract self-contradicted: §2/§6 "enabled iff COMPLETE" vs §4.6 + test "COMPLETE OR STALE".
- **B4** `MapPicker.onLatLonChange:(LatLon)=>void` could not express null, but §7 required `location→null` on clear.
- **M1** `TariffRegion` type used but undefined. **M2** state-machine cited the wrong five-state set (`wizard_flow` §2.2 = wizard-bar states, not the form machine).

## Round 2 — `e1c865d` — APPROVE (2026-06-13)
All B1–B4 + M1–M2 resolved; verified against the actual commit + the LOCKED contracts:
- **B1 ✓** §5.1 rebuilt category-keyed (`assets.wind.fleet_rated_mw` = Σ count×`rated_mw_per_unit`, etc.), tariff sent as the `(12,24)` `price_table_yuan_per_mwh`, grid model-only (limits resolved server-side). Verified conformant to `config_validation.md`: every stage-①-relevant rule (E-CAP-POS, E-BAT-CRATE/UNIT, W-BAT-CRATE-2C/DUR-10H, E-TAR-SHAPE) reads keys present in the body; `load`/`economics`/`location` are gated/irrelevant rules that correctly skip when absent. New `DeviceRowPhysics`, `tariffPriceTable`, `receiveTariffPriceTable`, and the §4.1 `GET /api/devices/models/{id}` resolve-on-add flow are coherent.
- **B2 ✓** `T-API-VAL-2` captures the POST body and asserts category keys, hand-computed `100×4.2=420.0 MW`, battery `300 MWh / 100 MW`, `(12,24)` tariff, `assets.fleet`/`tariff_region` ABSENT, and invalid (`valid:false`) rows excluded.
- **B3 ✓** §2 + §6 T-CONTINUE-1 → "COMPLETE || STALE"; matches the existing tests.
- **B4 ✓** `onLatLonChange:(LatLon|null)=>void`; `T-MAP-11`; `T-UNHAPPY-6` strengthened to assert `onLatLonChange(null)` on clear and never NaN/stale.
- **M1 ✓** `TariffRegion` interface added with explicit ¥/MWh units. **M2 ✓** §2 intro distinguishes form-state from wizard-bar state.
- Test integrity: diff vs `cfeb8c1` is additions + the T-UNHAPPY-6 strengthening only; no approved assertion weakened.

### Reviewer-added cases (this commit, marked `// reviewer:`)
- `[T-MAP-COV-ERR]` §5.2 coverage-error fail-safe — `coverageError` set ⇒ Historical & Bootstrap disabled (closes the gap where T-MAP-6/7's predicate omits the error/null case).
- `[T-MAP-10-LON]` symmetric lon range guard ([-180,180] ⇒ `lon-range-error`, no `onLatLonChange`) — only lat was tested.

**Approved suite = developer cases (incl. T-API-VAL-2) + the 2 reviewer cases above.**

### Non-blocking should-fix (fold into implementation; flagged, not gating)
1. **Multi-model-per-category limitation.** The §5.1 builder uses `windRows[0].id` and sums MW across rows — two *distinct* models of the same type would lose the 2nd model id (site schema names one model per category). Fine for v1 (one model/category), but document the v1 limitation.
2. **Tariff dropdown units test.** §5.4 displays `¥{min}–{max}/MWh` — a prime-directive units string with no contracted testid or test. Add a `tariff-region-option-{region_id}` testid + an assertion that the summary shows `/MWh` (not `/kWh`).
3. **S1 — ack-clearing rule.** §4.5 T-VAL-9 / §6 T-CONTINUE-3 require clearing acks "for that rule_id" with no `rule_id→field` map. State the rule (simplest correct: any meaningful edit clears ALL `acknowledgedWarnings`).
4. **S2 — rehydrate persisted COMPLETE.** §3.2 persists `stageState`+`lastValidation`; define whether rehydrate forces a re-validate (recommended) vs trusting a stale COMPLETE; add a test.
5. **T-SAVE-5 STALE-click** fires `onClick` is stated but not directly tested (T-SAVE-3 only checks the label).
6. **T-MAP-6/7 wording** — reword to "enabled ONLY when `coverage.historical_available === true`" so the error/null/pending cases are unambiguously disabling (my T-MAP-COV-ERR pins this).

## Round 3 — `9a9d445` — REQUEST_CHANGES (2026-06-13) — D37 re-gate
Team-lead ruling **D37** moved fleet assembly server-side: `POST /api/site/validate` (client-assembled body) → `POST /api/site/assemble` (raw wizard form; server resolves count→fleet MW/MWh + tariff_region→table). §5.1 rewritten, PV-by-capacity row added, all 6 prior should-fixes folded in. Verified the rewrite against the actual commit + PR #105 (`/api/site/assemble`) + LOCKED config_validation — **approved in substance** (body matches #105 field-for-field; T-API-VAL-2 pins it; guard matches #105's frontend-gate; my reviewer tests intact). **One blocker:** `T-S2-REHYDRATE` injected `setState({stageState:"COMPLETE"})` then asserted `!=="COMPLETE"` — but plain setState fires no rehydrate path, so a correct `onRehydrateStorage` impl fails it; only a wrong "downgrade-on-every-setState" hack passes. Unsatisfiable by a correct impl → must-fix.

## Round 4 — `a553425` — APPROVE (2026-06-13)
- **T-S2-REHYDRATE fixed ✓** — now seeds `localStorage["energygo.stage1"]` with a persisted COMPLETE snapshot, calls `await useStageOneStore.persist.rehydrate()` (the real path that runs `onRehydrateStorage`), asserts `stageState === "IN_PROGRESS"`, cleans up. Satisfiable only by a correct rehydrate-downgrade impl. Comment nit (`fleet_capacity_mw` "¥/MWh"→"MW direct") fixed. Diff `9a9d445..a553425` is those two changes only — no other approved assertion touched.
- **D37 §5.1 body** verified to match PR #105 `/api/site/assemble` §3 (wind/battery `{model_id,count}`, pv `{model_id,fleet_capacity_mw}`, grid `{model_id}`, `tariff_region` string, optional `site_meta`; `fleet.length>0 && tariffRegion!==""` guard). `FLEET_MIXED_MODEL` (server-side, #105) covers the v1 one-model-per-category note.

### Approved suite (Round 4) = developer cases (incl. T-API-VAL-1/2, T-FLEET-PV-1/2, T-VAL-TARIFF-REQ, T-TARIFF-1, T-S1-ACK-CLEAR, T-S1-STALE-CLICK, T-S2-REHYDRATE) + the 2 reviewer cases (T-MAP-COV-ERR, T-MAP-10-LON).

### Standing conditions (carried to implementation / code-audit, NOT blocking the gate)
- **§5.1 is CONTINGENT on PR #105 (`/api/site/assemble`) locking with the same body shape.** #105 is an unlocked draft; if it diverges (field names, or `costs`/`forecast` turning out to be *required* vs server-defaulted), §5.1 + T-API-VAL-1/2 reopen through frontend-reviewer. Dev to confirm costs/forecast optionality with serving-engineer.
- T-TARIFF-1 renders a stub `<option>`; strengthen to a real `<select>`/SiteMetaSection render at implementation.
- D37 to be recorded in LINEAGE.md (team-lead/rl-architect).

---

## Round 5 — `4d7e42b` — REQUEST_CHANGES (2026-06-13) — IMPLEMENTATION review (stage 2)

Rounds 1–4 gated only the red-first contract+tests; those markers are **VOID for the
implementation**. This is the full code audit of the StageOneConfig wizard at HEAD `4d7e42b`.

### Dispute adjudication — `T-API-RACE-1` (the 1 failing test) → **TEST bug; corrected + re-approved**
frontend-engineer routed a test-vs-impl dispute (T-API-RACE-1 timed out at 5 s) and proposed a
timer-reorder fix. **Verified against the impl — the engineer's diagnosis is WRONG and its proposed
fix would still time out.** Root cause: the test added devices with **no `valid: true`** and **never
set `tariffRegion`**, so the §5.1 assemble guard (`validCount > 0 && tariffRegion !== ''`,
`stageOneStore.ts` L59–67) was **never met** → `_scheduleAssemble` returns early at L67 → **no
debounce timer is ever scheduled and `fetch` never fires** → there was no in-flight request to abort,
so `firstAborted` could never become true. The race-guard itself is **contract-§5.1-compliant**: the
store aborts the active `AbortController` on every meaningful change (`_scheduleAssemble` L65) and
discards `AbortError` responses (catch L98); only the latest response is applied. As the approving
reviewer I corrected the test (marked `# reviewer:`) to (a) satisfy the guard, (b) drive request #1
genuinely in-flight before the 2nd change aborts it, and (c) **strengthen** coverage — it now asserts
the **latest** (clean) response is the one applied to the store, not the stale one. Also fixed a
latent stale-snapshot read in `T-CONTINUE-2` (`expect(store.stageState)` → `useStageOneStore.getState()`)
that my corrected race test exposed via cross-test store leakage. **82/82 prior tests now green.**

### BLOCKERS (implementation)
- **B5 — Assemble-failure path is dead at runtime (§5.1 "Error handling" + §7 T-UNHAPPY-2 + §4.5
  `apiError` VIOLATED).** On a non-200/network error from `POST /api/site/assemble` the store catch
  (`stageOneStore.ts` L97–102) sets only `validationPending=false` and never sets an error field —
  there is **no** `assembleError`/`validationError` in the store. `StageOneConfig` wires
  `ValidationPanel apiError={store.saveError}` (`StageOneConfig.tsx` L269) — `saveError` is the
  **footer-save** error (§3.2), a different flow, never set by the assemble path. Net effect: an
  assemble failure shows **no error and no Retry UI** (panel silently blanks). The store comment at
  L101 ("ValidationPanel shows apiError") is aspirational — nothing implements it. Masked because
  T-UNHAPPY-2 / T-VAL-7 render `ValidationPanel` in **isolation** with `apiError` passed directly; the
  store→panel wiring is untested. Conflation bug too: a future real save failure would wrongly render
  "Validation unavailable" inside the ValidationPanel.
  *Fix:* add a store field (e.g. `assembleError`) set in the catch with the message; wire
  `apiError={store.assembleError}`; keep `stageState` from advancing to COMPLETE on failure (already true).
- **B6 — `Retry` does not re-attempt the assemble call (§5.1 retry intent; §4.5 T-VAL-7 wiring).**
  `handleRetry` (`StageOneConfig.tsx` L100–103) toggles `validationPending` true→false in a
  `setTimeout(0)` and never re-issues `POST /api/site/assemble` / re-runs the debounce. Even with B5
  fixed, Retry cannot recover. *Fix:* `handleRetry` must clear `assembleError` and re-fire assemble.

Reviewer test **`[T-API-FAIL-1]`** (added this round, marked `# reviewer:`) pins B5+B6 end-to-end
through the real store→panel wiring (assemble 500 → `validation-api-error` shown, `stageState` not
COMPLETE; Retry → clean). It is **RED at `4d7e42b`** and is the definition-of-done for this round.

### Should-fix (non-blocking; fold into the B5/B6 fix commit or a follow-up)
- **S3 — `coverage-indicator` DOM anchor missing.** §4.2 DOM anchors require
  `data-testid="coverage-indicator"` on the availability line block; `MapPicker` renders the coverage
  text but never tags it. No approved test enforces it, but a future consumer of the documented anchor
  would break. Add the testid.
- **S4 — MapPicker is a placeholder, not a real MapLibre map.** §4.2 (T-MAP-2 zoom-9 fly-to, T-MAP-1
  China-centred zoom-4) and §9 a11y describe a real map; the impl renders a static box and documents
  it only in a code comment. No approved test requires the real map (non-data-critical), but this is a
  deliberate deviation — record it in contract §12 or file a follow-up so it isn't silently lost.
- **S5 — `handleSave` stub sticks the button in "Saving…".** Save persistence is out of scope (§11),
  but `handleSave` sets `saveInProgress=true` with no path to clear it, permanently disabling the
  button after one click. Prefer a no-op (with comment) until `site_config_persistence.md` lands.
- **S6 — Test isolation.** The suite leans on the module-singleton store's leftover state across
  tests (the T-CONTINUE-2 break this round was a symptom). A global
  `afterEach(() => useStageOneStore.getState().reset())` would harden it. Optional.

### Verified-correct (no action)
- `_scheduleAssemble` debounce + abort race-guard (§5.1) — compliant; latest-wins.
- `buildAssembleBody` (§5.1 / D37) — per-type entries, `tariff_region` string, optional `site_meta`,
  `valid !== true` rows excluded; matches PR #105 field-for-field. T-API-VAL-1/2 pin it.
- Tariff dropdown summary renders `…/MWh · 12×24 TOU` — **prime-directive units correct** (¥/MWh, not /kWh).
- `MapPicker` N/S/E/W parsing + [-90,90]/[-180,180] range guards + `onLatLonChange(null)` on clear (§4.2).
- `DeviceFleetTable` PV-by-capacity vs count-by-unit split, clamp [1,999], search debounce, no-match error (§4.3).
- `ValidationPanel` errors/warnings/ack/clean/tariff-required/still-checking states (§4.5); `StageSaveButton`
  COMPLETE/STALE labels + `aria-disabled` (§4.6); `useSiteMetaForm` province→tariff default + reset (§4.7).
- All colours via `TOKEN.*` (§8); a11y combobox/alert/aria-disabled anchors present (§9).

**Verdict: REQUEST_CHANGES** — B5 + B6 must be fixed (with `[T-API-FAIL-1]` green). The dispute is
resolved (T-API-RACE-1 + T-CONTINUE-2 corrected, 82/82 prior green). Re-review on the fix commit.

---

## Round 6 — `f94b174` — APPROVE (2026-06-13) — IMPLEMENTATION (B5+B6 fix)

Re-audit of the B5/B6 fix. Diff `a329e6b..f94b174` touches **only** `src/stores/stageOneStore.ts`
and `src/components/wizard/StageOneConfig.tsx` — the test file is **untouched** (no approved test
weakened to pass; verified `git diff --stat -- tests/` is empty). Code-verified, not claim-verified:

- **B5 ✓** — New `assembleError: string | null` field added to `StageOneStoreState` (initialized
  `null`, reset in `reset()`, not persisted — correct; transient errors must not survive reload).
  The assemble catch now sets `{ validationPending: false, assembleError: msg }`; `receiveValidation`
  clears `assembleError: null` on success. `StageOneConfig` wires `apiError={store.assembleError ?? null}`
  (was the unrelated `saveError`). An assemble 500/network error now reaches `ValidationPanel` and
  renders `validation-api-error` (panel shows it on `apiError && !pending`, which the catch satisfies).
- **B6 ✓** — New `retryAssemble()` action: `set({ assembleError: null }); _scheduleAssemble()` —
  re-fires the real debounced assemble fetch when the §5.1 guard holds. `handleRetry` now calls it
  (was a no-op pending-toggle). Retry genuinely recovers.
- **`[T-API-FAIL-1]` integrity ✓** — was RED at `a329e6b`/`4d7e42b` (both paths broken) and is GREEN
  at `f94b174`, so it genuinely exercises BOTH fixed paths (api-error surfaced + Retry re-fires →
  clean). It also still asserts `stageState` does NOT advance to COMPLETE on failure (§5.1 deviation #2).
- **Full suite 83/83 green.** `src/` feature files type-clean (`tsc --noEmit`: 0 errors in
  stageOneStore/stageConfig/wizard/useSiteMetaForm). The 156 jest-dom matcher `tsc` errors are
  repo-wide test-typing noise across all frontend suites (pre-existing, runtime-harmless), not in scope.

### Carried non-blocking should-fix (NOT gating — fold into a follow-up)
S3 `coverage-indicator` anchor (§4.2) still absent · S4 MapPicker is a placeholder, not a real
MapLibre map — record the deviation in §12 or file a follow-up · S5 `handleSave` still sticks the
button in "Saving…" (save persistence is out of scope, §11) · S6 add a global store-reset `afterEach`
for test isolation. None block this gate.

**Verdict: APPROVE** (implementation) covering `f94b174`. B5+B6 resolved and code-verified; dispute
resolved; no test weakened; 83/83 green. Ready for QA re-verification on `f94b174`.
