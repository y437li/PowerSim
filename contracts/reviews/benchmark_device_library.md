# Review record — benchmark_device_library

**Contract:** `contracts/shared/benchmark_device_library.md` v1.0.0
**PR:** #103 (`feat/config-benchmark-device-library`)
**Reviewer:** backend-reviewer
**Date:** 2026-06-13
**Scope of this approval:** wind / PV / BESS / grid model entries + the `provenance` field standard + Gansu provenance backfill + the test suite. **The electrolyzer device type (contract §2, §3.5, §4.5, T11, T12) is HELD and explicitly OUT of this approval** — it introduces a new device type to the LOCKED `device_model_schema` and requires an rl-architect ruling (minor additive vs superseding DECISION + re-LOCK).

## Verdict: APPROVE (backend-correctness, scoped as above)

`config/device_models.yaml` ships 13 models (4 Gansu untouched + 3 wind + 2 PV + 2 BESS + 2 grid). Verified against the spec/LOCKED values, not the developer summary:

- **Schema validity:** `schema_version` 2.0.0 → 2.1.0 minor bump is justified — the `provenance` field is an additive schema-level field and the entries are additive data. Compatible with PR #101's `>= (2,0,0)` E-TAR-SHAPE gating and its `startswith("2.")` schema pin (verified — no cross-PR break).
- **Field-name consistency:** new entries use the exact field names the LOCKED Gansu entries use (`v_cutin_mps`/`v_rated_mps`/`v_cutout_mps`/`hub_height_m`/`rated_mw_per_unit`, `k_T_per_c`/`eta_inverter`/`degradation_yr1`, `eta_ch`/`eta_dis`/`soc_min`/`soc_max`/`capacity_mwh_per_unit`/`power_mw_per_unit`, `max_export_mw`/`max_import_mw`). T6 pins the Gansu values bit-identically.
- **Physics invariants (T7-T10):** all hold against the data — wind `0<v_cutin<v_rated<v_cutout`, PV `k_T<0`, battery `0≤soc_min<soc_max≤1`, grid limits ≥0. Hand-checks shown in the test docstrings are correct.
- **Provenance (§1):** all public entries start `public; …`; SST stub is exactly `USER-provided, pending`. No proprietary values committed (T5/T14/T14b; CLAUDE.md public-repo rule satisfied).
- **Gansu untouched:** T6 + T15 confirm physics LOCKED and provenance added without modifying physics.

## Reviewer-added test cases (pushed to the branch; suite = developer + reviewer cases)

Audited gap: T7-T10 select models by **hardcoded ID lists**, not the `type` field — so `type` is never validated and a future entry omitted from a list silently escapes physics validation (the PR #101 fixture-drift class). Added (all hand-verified passing, 95/95):

1. `test_every_model_has_valid_type` — every model declares a `type` in `{wind_turbine, pv_panel, battery, grid_connection}`; electrolyzer must NOT appear (held).
2. `test_per_type_coverage_exhaustive` — the per-type ID lists must exhaustively cover every YAML model (and reference no absent model); fails on either drift direction.
3. `test_provenance_access_keyword` — enforces the §1 access-keyword format, not just non-empty (T4).
4. `test_wind_rated_mw_unit_sanity` — `0 < rated_mw_per_unit < 50` MW/kW unit-slip guard (§6 silent-unit-mismatch class).

## Advisory notes (non-blocking)

- **A — contract/test mechanism mismatch:** contract T7-T10 say "for each `type==X`" but the tests select by hardcoded ID. My added coverage test closes the safety gap; consider driving the per-type selection from the `type` field directly in a follow-up.
- **B — contract §5 labels T11/T12 as active** while the test file correctly HOLDS them. Mark T11/T12 HELD in the contract text so the doc matches the shipped suite.
- **C — provenance field home:** §1 defines a schema-wide `provenance` field inside a benchmark/data contract. For a LOCKED shared schema, the field definition arguably belongs in `device_model_schema.md` (with the minor bump) and should be referenced here. Flagged for rl-architect (shared-contract lock authority).
- **D — routing:** this is a `contracts/shared/` contract; per the shared-contract convention (D25 precedent) the LOCK is rl-architect's on its own authority after backend-reviewer + finance-expert comment. The `schema_version` bump and the new field touch the LOCKED schema. My APPROVE + finance-expert's APPROVE feed that lock; merge should follow the shared-contract path, not a plain backend-only gate.

## Gates still required before merge
- **finance-expert APPROVE** — the economics *values* (CAPEX/OPEX/lifetime benchmarks) are finance-expert's domain, not audited here.
- **rl-architect** — electrolyzer device-type ruling (held) + shared-contract lock + notes C/D.
- **QA** — qa-engineer verdict closes the task.
