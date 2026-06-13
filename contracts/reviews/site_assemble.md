# Review record: `site_assemble`

**Contract:** `contracts/serving/site_assemble.md` v1.0.0
**Tests:** `tests/serving/test_serving_site_assemble.py`
**Required reviewer:** backend-reviewer (gate)
**Advisory reviewer:** frontend-engineer (wizard-form input shape — consulted pre-contract; green-lit)
**Task:** #6

## Pre-contract consultations

- **frontend-engineer (2026-06-13):** green-lit the proposed input/response shapes.
  Confirmed: `tariff_region` string sufficient (no 12×24 table needed from wizard);
  `costs`/`forecast` omitted from stage ①; `site_config` always present in response.
  Follow-up F1/F2/F3 answers recorded in contract §3.2–§3.3.

## Open for backend-reviewer

Awaiting backend-reviewer verdict (APPROVE / REQUEST_CHANGES).

---

## backend-reviewer gate — APPROVE (2026-06-13)

**Contract:** `contracts/serving/site_assemble.md` v1.0.0 · **PR #105** · stage: contract + tests (pre-implementation).

### Round 1 → REQUEST_CHANGES (3 items), Round 2 @ 45567a7 → all resolved
- **F1 (resolved):** §3.2/§8 rationale rewritten — E-TAR-SHAPE is now correctly stated as **N/A** for assembled region-keyed configs (no inline price_table to check); the real guards are the 400 `TARIFF_REGION_NOT_FOUND` boundary check + `resolve_site()`'s region-path requirement.
- **F2 (resolved):** §10.1 now uses the honest count×per-unit values (613.2/300/100) + an explicit limitation that the wizard form **cannot reproduce** site_gansu.yaml's sub-nominal/rounded overrides (615/294.5/98.16) — parity-critical sites use direct YAML.
- **F3 (resolved):** `TestResolverRoundTrip.test_assembled_gansu_resolves_via_region_path` added — assembles Gansu, confirms region-only (no inline table), writes temp YAML, asserts `resolve_site()` does not raise (importorskip-guarded, D33 pattern). The real validate≠resolve end-to-end guard.

### Verified sound
- The #102 trap handled correctly: `pv_panel` → `assets.solar.fleet_capacity_mw` (key `solar`, not `pv`); all category keys match the validator's actual read paths.
- Aggregation arithmetic correct (146×4.2=613.2; merges sum); `count` required for wind/battery, absent for pv/grid (internally consistent with the fixture).
- All 7 HTTP-400 codes defined + tested; tariff costs region-sourced (not overridable); `site_config` always present in 200; single-source `site_assembly.py` (D37); `POST /api/site/validate` untouched.

### Reviewer-added cases (`TestReviewerAddedCases`; CLAUDE.md — I own these)
- `test_fleet_count_non_integer_rejected` — count=2.5 → 400 `FLEET_COUNT_INVALID` (§5 "not an integer"; pins no-silent-coercion).
- `test_assembled_battery_no_unit_count_no_e_bat_unit` — assembler emits no `unit_count` → E-BAT-UNIT must not fire (guards a future impl emitting an inconsistent one).
Both collect cleanly; they fail-at-run until the endpoint is implemented (expected for the pre-impl gate).

**Verdict: APPROVE** @ test head with reviewer cases. Implementation may proceed; QA verifies the full suite (incl. F3 + reviewer cases) post-implementation.
