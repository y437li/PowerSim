# Review record: Python Telemetry Validator (energy_go.telemetry.validate)

- **Contract:** `contracts/shared/telemetry_validate.md` · **Tests:** `tests/shared/test_shared_telemetry_validate.py`
- **PR:** #23 (`feat/shared-telemetry-validate`, task #23) · **Reviewer:** backend-reviewer
- **Verdict:** APPROVE — commit 7c8338d (+ reviewer commit)
  - R1: REQUEST_CHANGES — F1 (tol too tight for float32), F3 (no major-version reject), F4 (non-defensive checks), F2/F5.
  - R2 (7c8338d): all resolved.

## R2 verification
- F1 — `_approx` rel coeff 1e-9→1e-6 (float32-safe: ~0.36 ¥ err at 3e6 ¥ < 3 ¥ threshold; unit errors ~1e3 rel still caught). Verified.
- F3 — major-version guard: 2.0.0 rejected as error index 0; 1.1.0/1.0.99 accepted; absent→skip+schema error. TestMajorVersionGuard (5) + version-before-schema order test. Verified.
- F4 — defensive checks: missing costs/generation/policies/partial-policy/empty-payload/{} all return list, never raise; deviations documented. TestDefensiveChecks (6). Verified.
- F5 — comment c_energy decomposition fixed.
- Golden arithmetic re-derived: env_step_a (−53100/−52700/0.527), eval_compare (22.8M/32.9M/28.5M). Correct.

## Reviewer-added case
- `test_forward_compat_unknown_field_accepted` (# reviewer:) — F2: unknown field at envelope + payload → validate()==[] (pins the LOCKED schema additionalProperties:true minor-forward-compat rule). Approved suite = dev cases + this.
