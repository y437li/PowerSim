# Review record — `contracts/harness/env_harness.md`

**Reviewer:** backend-reviewer · **Area:** harness · **PR:** #43 (`feat/harness-env-harness`)
**Stage:** contract + tests gate (Stage 1, draft PR)

## Verdict: APPROVE (round-2, commit e499f48)

Approved suite = developer cases + the 4 reviewer-added case groups below.

## Round history

- **Round 1** (9a2f2eb) — REQUEST_CHANGES. F1 (physics): `bat_curtailed_mw` hardcoded 0 contradicted jax_env_core §5.3.5 (which scales `P_bat_to_grid` by `scale_export` under the PCC export cap) and the per-source conservation invariant omitted the battery. F2 (telemetry): conformance tests asserted only that valid messages pass — no negative test proving an invalid message is rejected, so the gate had no teeth. F4 (minor): T1 comment arithmetic slips. F3: EnvInfo extension is an additive amendment to the approved jax_env_core contract (coordination).
- **Round 2** (e499f48) — **APPROVE.**
  - **F1 fixed:** `p_bat_curtailed_mw` added as the 13th EnvInfo field; "always 0" note removed and replaced with the correct §5.3.5 explanation; `bat_conservation_ok` added (`|bat_to_load + bat_to_grid + bat_curtailed − p_bat_dis| < 1e-3`). New `TestBatteryCurtailmentConservation` (T5c): soc=0.7, max_export=20, a_bat=−1, no renewables → `scale_export = 20/98.16 = 0.20375`, `bat_curtailed = 98.16×(1−0.20375) = 78.166 MW`, conservation `0 + 20 + 78.166 = 98.16` ✓. Hand-values verified; fixture correctly isolates battery-only export (wind=0, irr=0). c_curtail includes the battery share; conservation-all-steps extended to the battery.
  - **F2 fixed:** `TestValidateMessageNegative` — 6 non-vacuous cases each asserting `errors != []`: missing envelope field, NaN, +Inf, invalid kind, missing payload field, and an eval_compare D13 cost-identity violation (total=999 vs components=350). Gives the conformance gate teeth.
  - **F4 fixed:** comments corrected (max_P_ch=121.443, soc_delta=0.161656); binding asserts were always formula-derived.
  - **F3:** EnvInfo extension is now the correct 13-field set; env-harness-engineer coordinates the additive amendment with jax-env-engineer (I re-review on jax_env_core, additive ⇒ minor). Physics question resolved: §5.3.5 applies one `scale_export` uniformly to all three grid channels → battery curtailed proportionally.

## Reviewer-added cases (pushed to branch, `# reviewer:`, hand-derived)

Class `TestReviewerAddedHarness` in `tests/harness/test_harness_env_harness.py`:

1. **Mixed 3-channel export curtailment** (`insp_mixed_export`): solar + wind + battery all exporting under a binding PCC cap (t=8, wind=12, irr=1000, load=5, a_bat=−1, max_export=200). Verifies one `scale_export` applies uniformly (identical curtailed fraction across all three channels: `sol_curtailed/p_pv == wind_curtailed/p_wind == bat_curtailed/p_bat_dis`), export pinned at cap, all three per-source conservation flags hold, and `c_curtail` sums all three. Combines the previously-separate T5b (renewable-only) and T5c (battery-only) into the simultaneous case.
2. **Valley-hour sell-price clamp** (`insp_valley`): t=0 (every hand-cost test T1–T6 ran at peak h=8). Pins D7 `price_sell = max(0, price_buy − 30)` against `PRICE_TABLE_YPW[0]` (source of truth, not a hardcoded tariff), the `price_sell ≤ price_buy` invariant, and `tariff_tier == "valley"`.
3. **Charge-mode battery conservation** (`test_bat_conservation_charge_mode`): a_bat=0.5 → `p_bat_dis=0`, all `bat_*` flows 0, `bat_curtailed=0`, `bat_conservation_ok` True — pins the charge-mode branch of §4.4 (T5c only covers discharge).
4. **C_DC_shape boundary** (`test_demand_shape_zero_at_exact_boundary`): month_peak == P_import (99.08) → `32000 × max(0, 0) = 0` ¥ — pins the exact clamp boundary that T1 (above) and T2 (below) bracket.

## Notes for QA

- Red-phase: the whole file is `pytest.importorskip`-guarded until `energy_go.harness` exists. `py_compile` clean.
- Harness implementation is blocked on the additive EnvInfo 13-field amendment to jax_env_core landing first.
- Post-implementation, run the per-source conservation battery (solar/wind/**battery**), D13 cost identities, the telemetry positive + negative validator cases, and fixed-seed determinism (InteractiveEnv / ScenarioReplay / Sweeper).

---

## Stage-2 re-review — B-CONSTRAINT fixes (PR #43 @ e5a99b9)

**Reviewer:** backend-reviewer · **Verdict:** APPROVE (harness substance) · merge-order condition below.

Both REQUEST_CHANGES items resolved by deriving the flags from canonical EnvInfo signals (the §1 no-recompute rule):

- **B-CONSTRAINT/2 — `constraint_load_capped = bool(info.load_capped)`** (interactive_env.py L207). Reads the JAX `load_capped` signal directly; the divergent Python fraction-renorm recompute is gone. ✓
- **B-CONSTRAINT/1 — `constraint_import_capped = f(info.p_load_unserved_mw) > _CONSERVATION_TOL or bool(info.import_cap_active)`** (L218–220). Covers both F-IMPORT regimes: load-shed (`load_unserved > tol`) and cap-reduced-battery-with-load-served (`import_cap_active`). The two branches are mutually exclusive (import_cap_active is defined with `load_unserved < 1e-6`); their union = "the import cap forced a change," which is the correct constraint semantics. When import == max but nothing was reduced/shed, both correctly stay False (cap touched but not binding). ✓

Fix commit `e5a99b9` is scoped to interactive_env.py only (10+/16−). `validate_message = validate` (telemetry/validate.py) is a harmless name alias, not a schema change. Env files in this branch are **byte-identical** to #33's approved HEAD `2f38439` (no fork).

**Merge-order condition (binding):** this branch merged `feat/env-jax-env-core` (#33) into itself to obtain the EnvInfo fields, so PR #43's diff-vs-main currently includes all of #33's env-core. **#43 must merge strictly AFTER #33**, then be **rebased onto main** so its final diff collapses to harness-only. Merging #43 before #33 would land #33's env-core under this PR and bypass #33's QA gate — not permitted. Flagged to team-lead.
