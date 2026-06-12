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

| Test function | Class | Rationale |
|---|---|---|
| `test_zero_capacity_division_guard_no_crash` | `TestNonRaising` | E-BAT-CRATE skip when cap=0 — denominator guard |
| `test_zero_power_division_guard_no_crash` | `TestNonRaising` | W-BAT-DUR-10H skip when power=0 — denominator guard |
| `test_nan_capacity_fires_e_cap_pos` | `TestErrors` | NaN capacity: `not (x > 0)` guard catches NaN |
| `test_w_bat_crate_2c_fires_independently` | `TestWarnings` | W-BAT-CRATE-2C when fleet>2C regardless of E-BAT-CRATE state |
| `test_e_bat_crate_boundary_strict` | `TestErrors` | fleet_crate == device_crate → no error (strict <, not ≤) |
| `test_e_cap_pos_resolved_grid_max_export_zero` | `TestErrors` | E-CAP-POS fires for max_export=0 (resolved grid limits) |
| `test_e_cap_pos_resolved_grid_max_import_zero` | `TestErrors` | E-CAP-POS fires for max_import=0 (resolved grid limits) |

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
