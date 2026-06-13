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
