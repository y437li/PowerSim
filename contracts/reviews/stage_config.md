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
