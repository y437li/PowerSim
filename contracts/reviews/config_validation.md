# Review Record — `config_validation`

**Contract:** `contracts/shared/config_validation.md` v1.0.0  
**Feature branch:** `feat/env-config-validation`  
**PR:** #89

---

## Stage 1 — Contract + Tests Gate

### frontend-reviewer (advisory)
**Verdict:** VERDICT: COMMENT (advisory — shared contract; rl-architect locks)  
**Date:** 2026-06-12  
**Head:** `e9f19a1`  
**Summary:** `ValidationIssue` shape sufficient for Stage-① UI patterns. Single-source/no-TS-reimplementation guarantee correct. Advisory items on `§11.2 warning-ack` collapsing both batteries if rule_id alone used (deferred to future DECISION when device lists land), and `resolve_site()` error surface completeness (noted, non-blocking).

### backend-reviewer (advisory)
**Verdict:** VERDICT: COMMENT (advisory — all findings resolved; reviewer tests pushed @ `c06f951`)  
**Date:** 2026-06-12  
**Head:** `c06f951` (reviewer test commit)  
**Summary:** Contract amendment at `19770be` addresses all 6 advisory findings (division guard, NaN check, W-BAT-CRATE-2C independence, arithmetic correction, documentation). 7 reviewer test functions pushed.

**Reviewer-added test cases (@ `c06f951`, `tests/shared/test_shared_config_validation.py`):**

> Corrected by backend-reviewer @ review-record re-confirm: function/class names below now
> match the actual approved test file verbatim (the initial draft paraphrased them).

| Test function | Class | Rationale |
|---|---|---|
| `test_zero_capacity_with_models_no_crash_crate_skips` | `TestReviewerDivisionGuard` | cap=0 + device_models → no crash; E-CAP-POS fires; E-BAT-CRATE skips (§3.2 division guard) |
| `test_zero_power_with_models_no_crash_duration_skips` | `TestReviewerDivisionGuard` | power=0 + device_models → no crash; E-CAP-POS fires; W-BAT-DUR-10H skips (§3.2 division guard) |
| `test_nan_capacity_fires_e_cap_pos` | `TestReviewerDivisionGuard` | NaN capacity → E-CAP-POS via `not (x > 0)` (IEEE-754: nan>0 is False) |
| `test_2c_warning_fires_while_crate_error_passes` | `TestReviewerCrateIndependenceAndBoundary` | device 700/300=2.333C, fleet 650/294.5=2.207C → W-BAT-CRATE-2C fires, E-BAT-CRATE passes (independence) |
| `test_crate_exactly_equal_device_no_error` | `TestReviewerCrateIndependenceAndBoundary` | fleet_crate == device_crate (0.333C) → no error (strict `>`, no tolerance — equality is not "greater than") |
| `test_grid_export_zero_fires_e_cap_pos` | `TestReviewerGridCapPos` | resolved `max_export_mw`=0 → E-CAP-POS (§4 lists grid limits) |
| `test_grid_import_zero_fires_e_cap_pos` | `TestReviewerGridCapPos` | resolved `max_import_mw`=0 → E-CAP-POS (§4 lists grid limits) |

### rl-architect (LOCK)
**Verdict:** VERDICT: APPROVE — LOCK `contracts/shared/config_validation.md` v1.0.0  
**Date:** 2026-06-12  
**Head:** `c06f951`  
**Authority:** Shared-contract LOCK on rl-architect authority (both advisories resolved).  
**Lock terms:** implementation authorized; finance-expert owns econ namespace (E-ECON-NEG delegated to jax-env-engineer for this PR only); versioning rules stated; §11.2 warning-ack DECISION deferred.

---

## Stage 2 — Implementation Code Audit

### backend-reviewer — REQUEST_CHANGES
**Verdict:** VERDICT: REQUEST_CHANGES  
**Date:** 2026-06-12  
**Head:** `e3b1d9b`  
**Issue [HIGH]:** `validate()` guarded `site_config` with `isinstance(..., dict)` but only `device_models is not None` — non-dict `device_models` reached `.get()`/`.items()` → `AttributeError`, violating §3.2 non-raising contract.  
**Issue [MED advisory]:** present-but-non-numeric capacity silently skips (deferred to E-SCHEMA, not blocking).  
**Required:** 3 isinstance guards + 3 adversarial `# reviewer:` tests.

### backend-reviewer — APPROVE (supersedes REQUEST_CHANGES)
**Verdict:** VERDICT: APPROVE  
**Date:** 2026-06-12  
**Head:** `f4ac01a`  
**Evidence:** Execution — re-ran adversarial probes at `f4ac01a`: `"not-a-dict"`, `{"models":"nope"}`, `{"models":{"x":"str"}}`, `{"models":[1,2,3]}`, `{physics:"x"}`, `[]`, `123` — all return clean `ValidationResult`, zero raises. Full suite: **63 passed / 1 skipped** (JAX ARM importorskip). Reviewer subset: **10/10**.

**Reviewer-added adversarial tests (@ `f4ac01a`, in `TestNonRaising`):**

| Test function | Input | Verifies |
|---|---|---|
| `test_malformed_device_models_string_no_crash` | `validate(GANSU_SITE, "not-a-dict")` | Top-level coercion guard |
| `test_malformed_device_models_models_not_dict_no_crash` | `validate(GANSU_SITE, {"models": "nope"})` | `_check_e_econ_neg` models guard |
| `test_malformed_device_models_model_entry_not_dict_no_crash` | `validate(GANSU_SITE, {"models": {"x": "str"}})` | `_check_e_econ_neg` model_def guard |

**[MED] deferral accepted:** `_safe_float()` returns `None` for non-numeric strings → rules silently skip. Contract explicitly defers to future E-SCHEMA rule. Not blocking v1.

---

## Approved test file versions

| Stage | Head | File | Verdict |
|---|---|---|---|
| Contract + tests | `c06f951` | `tests/shared/test_shared_config_validation.py` | LOCK (rl-architect) |
| Implementation | `f4ac01a` | `tests/shared/test_shared_config_validation.py` | APPROVE (backend-reviewer) |

**Current head at QA handoff:** `f4ac01a`  
**Test count:** 63 collected (60 pass + 3 new adversarial), 1 skipped (JAX ARM)

---

## D33 revision — E-TAR-SHAPE v2.0+ relaxation (PR #101)

**Reviewer:** backend-reviewer · **Date:** 2026-06-13 · **Classification:** MINOR (rl-architect; relaxes an existing rule's accepted set; no rule_id/result-shape change → no re-LOCK)

**Live bug fixed:** validator demanded strict `(12,24)` under device_model_schema v2.0+, but `resolver.py` accepts flat `(24,)` (broadcast ×12) → the flagship Gansu site (flat tariff + device_models@2.0.0) hard-failed E-TAR-SHAPE end-to-end.

**Resolution (option a, rl-architect ruling):** both `config_validation._check_e_tar_shape` and `resolver.resolve_site` inline path accept exactly `{flat (24,) scalars, (12,24)}`. Validator: `flat_ok OR seasonal_ok`. Resolver: flat→×12 broadcast, seasonal→passthrough, else `ValueError`. Contract §4/§9 + binding parity-invariant note.

**Findings raised & resolved:**
- **F1** (round 1): `seasonal_ok` accepted `(12,24)` that the resolver then rejected → validator/resolver disagreement. Resolved by extending the resolver inline path to passthrough `(12,24)`.
- **F2** (round 2): resolver flat branch checked `len==24` without the validator's scalar guard → a 24-length list-of-lists (`[[v]]*24`, `(24,24)`) was rejected by the validator but accepted by the resolver → silent `(12,24,24)` price_table. Resolved by adding `and not any(isinstance(row,list) …)` to the resolver flat branch (mirrors validator `flat_ok` exactly).

**Parity invariant now tested both directions:**
- `test_resolver_inline_seasonal_passthrough` — resolve_site() succeeds on inline `(12,24)` (positive parity).
- `test_v2_flat_24_nested_rejected_by_both` — validator AND resolver both reject `[[v]]*24` (negative parity; fails loudly if resolver silently accepts).
- `test_real_gansu_config_validates_no_tar_shape` — loads on-disk `config/site_gansu.yaml` + `config/device_models.yaml`; pins `schema_version` 2.x (immune to the #63 → 2.1.0 drift); validate→no E-TAR-SHAPE + resolve_site() no-raise.

**Reviewer-added cases (backend-reviewer, this revision):**
- `test_v2_flat_12_scalars_errors` — len==12 of scalars is never mistaken for a seasonal table → E-TAR-SHAPE.
- `test_malformed_schema_version_uses_v1_path` — non-numeric `schema_version` falls back to v1 flat path without crashing.

**Suite state:** 76 collected; all pass except `test_error_not_raised_on_valid_gansu` (pre-existing x86-jaxlib-AVX-on-ARM import failure; environmental, unrelated; CI/QA validates the JAX-gated resolver halves).

| Stage | Head | Verdict |
|---|---|---|
| D33 implementation | `f5e7ae3` | APPROVE (backend-reviewer) |

---

## E-SCHEMA activation (v1.1.0, task #8 / PR #106) — backend-reviewer

**Reviewer:** backend-reviewer · **Date:** 2026-06-13 · **Classification:** MINOR (rl-architect; activates a contracted-but-deferred gated rule; no `ValidationResult`/`ValidationIssue` shape change → no re-LOCK). Shared contract → rl-architect holds the v1.1.0 LOCK after this gate.

### Round 1 → REQUEST_CHANGES (F1 grid gap + F2 test name), Round 2 @ 501911e → resolved
- **F1 (resolved):** `assets.grid` added to the v1 power-composite required set (present AND dict). I traced + flagged that the original "covered by E-CAP-POS" rationale was false — `_resolve_grid_limits` returns `(None,None)` on a missing grid and E-CAP-POS skips it, so a grid-less config passed both E-SCHEMA and E-CAP-POS → broke at `resolve_site()`. rl-architect agreed (overrode own ruling). The false rationale is replaced with the accurate explanation; required-set = `battery` + (`wind` OR `solar`) + `grid`, D32(d)-framed as v1-power-composite. 3 grid tests added (missing/None/present-ok).
- **F2 (resolved):** `test_e_schema_does_not_fire_device_models_none` → `test_e_schema_fires_when_device_models_none` (name now matches the assertion).

### Verified sound
- Battery required (6-dim action space, D32(d)); at-least-one of {wind,solar}; grid required; structural check independent of `device_models`; one issue per missing section; `≥2 issues` when multiple missing. §9 v1.1.0 changelog documents the observable behavior change; §6 rule-table row; §12 checklist. 1.1.0 MINOR / no re-LOCK correct.

### Reviewer-added cases (`# reviewer:`; CLAUDE.md — I own these)
- `test_wind_none_but_solar_valid_no_e_schema` — `assets.wind=None` + valid solar → **no** E-SCHEMA (at-least-one boundary; guards against firing on ANY non-dict generation key). PASSES pre- and post-impl.
- `test_grid_string_fires_e_schema` — `assets.grid="<str>"` (present, not a dict) → E-SCHEMA, paralleling `battery=str` (the grid tests covered absent+None but not str). RED pre-impl, green post-impl.

### Suite state
17 TestESchema cases (15 dev + 2 reviewer): 11 RED pre-impl (assert E-SCHEMA fires; go green when E-SCHEMA lands), 6 green pre-impl. Correct for the contract-first gate.

**Verdict: APPROVE.** Implementation may proceed; rl-architect holds the v1.1.0 D25 LOCK; QA verifies post-impl. When E-SCHEMA lands, the #105 strict-xfail `test_no_battery` auto-flips → backend-engineer un-xfails it in the same change.
