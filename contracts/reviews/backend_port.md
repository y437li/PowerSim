# Review record — `contracts/serving/backend_port.md` (task #32, PR #61)

**Reviewer:** backend-reviewer
**Spec basis:** REBUILD_SPEC.md §9.3; companion `contracts/frontend/configurable_ports.md` (defines `ENERGY_GO_BACKEND_PORT`).

## Stage 1 — contract + tests gate

### Verdict: REQUEST_CHANGES → (pending re-APPROVE after snippet fix)

### Blocking finding
- **Contract snippet (L28) contradicts its own test.** The contract shows
  `port = int(os.environ.get("ENERGY_GO_BACKEND_PORT", "8000"))`. `os.environ.get`
  returns the *default only when the key is absent*; for an **empty-string** value
  the key exists, so it returns `""`, and `int("")` raises `ValueError`. That
  violates §36 ("Default 8000 when the var is absent **or empty string**") and
  fails `test_empty_string_uses_default_8000` — whose own docstring already
  prescribes the correct form. Fix the snippet to:
  `port = int(os.environ.get("ENERGY_GO_BACKEND_PORT") or "8000")`
  (None→falsy→default; ""→falsy→default; "9000"→truthy→9000). The binding test is
  correct; only the contract prose is wrong — but a contract must not show a snippet
  its own test calls buggy.

### Developer cases reviewed (16) — coverage assessment
- app.py: absent→8000, 9001, 8888, empty→8000, non-int→ValueError, port 1, port 65535. ✓
- run_app.sh: invalid→exit1, 99999→exit1, absent→exit4, 9001→exit4, cli-beats-invalid-env→exit4,
  cli-beats-oor-env→exit4. Priority order (CLI > env > 8000) is pinned via the exit-code
  discriminator (exit 1 = port-validation fail, exit 4 = passed validation / site-YAML missing). ✓
- run_app.ps1: 3 Windows-only mirrors. ✓
- Naming/layout: `tests/serving/test_serving_backend_port.py`, `<feature>`=contract filename. ✓

### Reviewer-added cases (5) — pushed to the PR branch, all `# reviewer:`-marked, hand-derived
TestAppMainPort:
1. `test_negative_int_parsed_not_rejected_by_app` — env=-1 → `int("-1")==-1`, app.py does NO
   range check (§34/35: OS/scripts validate range) → PORT:-1, exit 0. Pins the layer boundary.
2. `test_whitespace_padded_port_parsed` — env=" 9000 " → `int(" 9000 ")==9000` (int strips
   surrounding ws) → PORT:9000, exit 0.
3. `test_whitespace_only_raises_value_error` — env="   " → "   " is truthy → `int("   ")`
   ValueError → non-zero exit. ADVERSARIAL: guards against an over-eager `.strip() or "8000"`
   impl that would wrongly map whitespace-only → 8000 (§36 is "absent or empty", not "blank").

TestRunAppShEnvPort:
4. `test_zero_env_port_fails_validation` — env=0 → `0 < 1` below range → exit 1 (lower
   out-of-range boundary; complements the existing 99999 upper case).
5. `test_port_65536_env_fails_validation` — env=65536 = 65535+1 → exit 1 (tight upper edge;
   catches an off-by-one in the range guard that 99999 would miss).

**Approved suite = developer's 16 + reviewer's 5 = 21 cases** (re-APPROVE conditional on the
L28 snippet fix landing).

### Notes
- All tests are RED until implementation — correct at the gate.
- Implementation audit (stage 2) deferred to PR-marked-ready.
