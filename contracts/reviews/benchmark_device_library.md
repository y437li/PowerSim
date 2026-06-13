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

---

## D35 electrolyzer follow-up (PR #104) — backend-reviewer

**Reviewer:** backend-reviewer · **Date:** 2026-06-13 · **Scope:** schema (device_model_schema v2.2.0 electrolyzer type) + electrolyzer physics + tests. Economics values (capex/stack_life) = finance-expert's gate.

### Verified sound
- **Schema (device_model_schema.md v2.2.0):** `electrolyzer` added to the type enum + §1.2 physics catalogue (6 fields, invariants `0<min_load≤1`, `0≤standby<min_load`, …); resolver-INERT note; v2.2.0 versioning row. Additive-minor, no re-LOCK (D35). Clean.
- **§8.2-verbatim (ALK/PEM):** ALK `min_load=0.20, standby=0.02, e_spec=52, degrad=4, rated=20` and PEM `0.05, 0.01, 55, 8, rated=10` — match the §8.2 (PEM|Alkaline) table **exactly** (rated_mw is a sizing field, not a §8.2 table value; warmup_minutes provisional per D35 cond. 1).
- **AEM/SOEC (benchmark-sourced):** all 6 invariants hold; IDs match rated MW (`-aem-2.4mw`, `-soec-5mw`); provenance `public; Enapter…` / `public; Sunfire/Bloom…`.
- **D35 guardrails:** all 4 under the `# H₂ SCENARIO — GATED, INERT REFERENCE DATA (LINEAGE D35)` subsection; `type: electrolyzer`; all provenance `public;`; resolver.py + site_gansu.yaml **untouched** (INERT preserved; no site `assets:` reference).
- **T11/T12:** restored; hand-computed invariants + monotonics (e_spec SOEC 40 < ALK 52 < PEM 55; degrad 4<8<10<15; ALK min_load 0.20 > PEM 0.05) match the YAML.

### Reviewer-added test updates (this PR; CLAUDE.md — I own these)
- `test_every_model_has_valid_type`: `VALID_TYPES += "electrolyzer"` (D35).
- `test_per_type_coverage_exhaustive`: `covered |= set(ELY_IDS)` — the 4 electrolyzer entries now covered (exhaustive coverage preserved; `dangling` guard confirms all 4 IDs exist). Suite 118/118.

### REQUEST_CHANGES — contract-text staleness (contract contradicts shipped YAML/tests)
1. **L363** — T2 `EXPECTED_IDS` lists `"electrolyzer-aem-1mw"`, a non-existent id; the entry + `ELY_IDS` + YAML use `electrolyzer-aem-2.4mw`. Fix to `-2.4mw`.
2. **L345** — T1 says `schema_version: "2.1.0"`, but `test_schema_version` asserts `"2.2.0"`. Fix to `2.2.0`.
3. **L37** — "schema_version bumps from `2.0.0` to `2.1.0`" is stale (this PR is `2.1.0`→`2.2.0`). Fix the range.
