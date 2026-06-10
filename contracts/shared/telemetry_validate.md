# Contract: Python Telemetry Validator Utility

- **Status:** DRAFT
- **Area:** shared (Python utility consumed by env, training, harness, serving producers)
- **Spec:** REBUILD_SPEC.md §2–§3; LOCKED `contracts/shared/telemetry_schema.md` v1.0.0 (D18)
- **Depends on decisions:** D13 (cost identities), D18 (machine-readable schema + reference validator)
- **Reviewer:** backend-reviewer (APPROVE gate before implementation)

## Purpose

An importable Python module `energy_go.telemetry.validate` that wraps the LOCKED JSON Schema
(`contracts/shared/telemetry_schema.json`) plus the D13 cost-identity checks, per-source energy
conservation, and finiteness checks from `scripts/validate_telemetry.py`. Producers (env harness,
training loop, serving) import this in their telemetry-emit tests per the D18 producer/consumer
obligation. The CLI script `scripts/validate_telemetry.py` is refactored to import its check logic
from this module (the script's `main()` and file I/O stay in the script).

This contract also **births** `tests/shared/` per D15.

## Module location

```
src/energy_go/telemetry/__init__.py
src/energy_go/telemetry/validate.py
src/energy_go/telemetry/data/telemetry_schema.json   ← symlink or copy of contracts/shared/telemetry_schema.json
```

`telemetry_schema.json` is bundled as package data so the module works from an installed wheel as
well as an editable `pip install -e .` checkout.  `pyproject.toml` MUST declare
`[tool.setuptools.package-data]  "energy_go.telemetry" = ["data/*.json"]`.

## Public API

```python
# energy_go/telemetry/validate.py

SCHEMA_VERSION: str = "1.0.0"
TOL: float = 1e-6   # absolute tolerance for numeric identities

def validate(message: dict | str | bytes) -> list[str]:
    """Validate a telemetry message against the LOCKED schema v1.0.0.

    Args:
        message: A telemetry message as a dict, a JSON-encoded str, or UTF-8 bytes.

    Returns:
        An empty list if the message is fully valid.
        A non-empty list of human-readable error strings (one per violation) if invalid.
        Errors are ordered: schema errors first, then finiteness, then kind-specific identities.

    Raises:
        TypeError  — if `message` is not dict | str | bytes.
        ValueError — if `message` is str/bytes that is not valid JSON.
    """

def check_finite(msg: dict) -> list[str]:
    """Return a list of errors for every non-finite (NaN or Inf) float in msg.

    Walks the entire message tree recursively (dicts + lists).
    booleans are not numbers; integer values are not checked for finiteness.
    Error format: "non-finite numeric at <dot-path>: <value>"
    """

def check_env_step(payload: dict) -> list[str]:
    """Return errors for D13 cost identities, reward formula, solar/wind conservation.

    Checks (tolerance TOL = 1e-6 absolute + 1e-6 relative — float32-safe):
      1. Real-money identity:
            cost_total_real_yuan == c_energy + c_demand_charge + c_degradation + c_curtail + c_voll
      2. Reward-basis identity:
            cost_total_reward_basis_yuan == c_energy + 2·c_demand_shape + c_degradation + c_curtail + c_voll
      3. c_energy decomposition:
            c_energy_yuan == c_import_yuan - r_export_yuan
      4. Reward formula (§3.5):
            reward == -(cost_total_reward_basis_yuan + penalty_yuan) * 1e-5
      5. Solar conservation:
            solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed == gross_solar_mw
      6. Wind conservation:
            wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed == gross_wind_mw

    **Defensive:** each check is silently skipped if its required fields are absent from the
    payload.  The function never raises; callers detect missing fields via schema errors.
    """

def check_eval_compare(payload: dict) -> list[str]:
    """Return errors for eval_compare total_cost identities.

    For each policy entry in payload["policies"]:
        total_cost_yuan == energy_cost + demand_charge + degradation + curtailment + voll

    **Defensive:** skipped entirely if `payload["policies"]` is absent.  Per-policy checks
    are skipped when any of the six required fields is absent from that policy dict.
    """
```

### Error string format

- Schema errors: `"schema: <jsonschema message> (at <path>)"`
  - path is `/`-joined, e.g. `"schema: 'bogus' is not valid (at kind)"`
- Finiteness errors: `"non-finite numeric at <dot-path>: <value>"`
  - dot-path: `.payload.costs.c_energy_yuan`, `.payload.flows.solar_to_load_mw[0]`
- Cost identity errors (D13): begin with `"D13 real identity:"`, `"D13 reward-basis identity:"`, `"D13: c_energy_yuan != ..."`
- Reward formula error: begins with `"reward identity:"`
- Conservation errors: begin with `"solar conservation:"`, `"wind conservation:"`
- eval_compare errors: begin with `"<policy_name>: "`

## Major-version guard

`validate()` returns a version-mismatch error **before** JSON-Schema validation if
`schema_version` is present and its major component ≠ 1:

```
"version mismatch: expected major 1, got <major> (schema_version=<value>)"
```

This implements the LOCKED contract's versioning acceptance rule: minor/patch additions
(1.x.y) are forward-compatible and accepted; a breaking major bump (2.x.y) must be
explicitly rejected so a consumer does not silently mis-interpret a wire-format change.
If `schema_version` is absent or not a semver string, the guard is skipped (the schema
validator will report the missing/malformed field through the normal schema-error path).

## Validation order (guaranteed)

1. **Major-version guard** — version-mismatch error first, if applicable.
2. JSON-Schema (Draft 2020-12) field conformance — schema errors listed next.
3. Finiteness — all numeric fields.
4. Kind-specific checks — only if `kind` field is present:
   - `env_step` → `check_env_step(payload)`
   - `eval_compare` → `check_eval_compare(payload)`
   - `train_metrics` → no additional checks (no numeric identities defined)

Kind-specific checks run even when schema errors are present (they operate on the payload dict
as-is); callers interpret errors holistically.

## Numeric tolerance

```
_approx(a, b)  ≡  |a − b| ≤ TOL + 1e-6 · max(|a|, |b|)
```

where `TOL = 1e-6`.  The `1e-6` relative coefficient is **float32-safe**: the JAX env core
produces float32 values; at site-scale totals (~3 × 10⁶ ¥) float32 rounding error can reach
~0.36 ¥, which exceeds a stricter `1e-9·max` (~0.003 ¥) but is well within `1e-6·max` (~3 ¥).
The tolerance does NOT absorb large unit-scale errors (kW/MW confusion ≈ ×1000 → ~3 × 10³ ¥
at site scale, far above 3 ¥).

## Schema loading

The module loads the schema at **first import** (module-level) from the bundled package data file.
Subsequent calls share the pre-loaded `Draft202012Validator` instance (no re-reading on each call).

Loading path (in order of preference):
1. `importlib.resources.files("energy_go.telemetry").joinpath("data/telemetry_schema.json")`
2. Fallback to the repo-root path `contracts/shared/telemetry_schema.json` if the above fails
   (supports running tests directly without an editable install).

`jsonschema>=4.0` (Draft202012Validator) is a REQUIRED import-time dependency.  The module raises
`ImportError` with a helpful message if `jsonschema` is missing.

## CLI refactor obligation

`scripts/validate_telemetry.py` MUST be refactored in the same PR to import from this module:

```python
from energy_go.telemetry.validate import check_finite, check_env_step, check_eval_compare
```

The script's own helper `validate_message()` and `main()` remain in the script.  The three check
functions are **not** duplicated; they come exclusively from the module after this refactor.

## Producer/consumer obligation (D18)

Any test that exercises a telemetry-emitting code path MUST call `validate(message)` and assert
`== []`.  This includes:
- env harness step tests — `validate(step_msg)`
- training loop checkpoint tests — `validate(train_metrics_msg)`
- serving inference stream tests — `validate(env_step_msg)`

## Out of scope

- Frontend TypeScript validator (task #24 — separate PR).
- Any wire format change to the LOCKED `telemetry_schema.md` v1.0.0.
- Extending validation checks beyond what is defined in the LOCKED contract + D13.

## Deliberate deviations from validate_telemetry.py

1. **Float32-safe tolerance (F1):** `_approx` uses `1e-6` relative coefficient instead of the
   script's `1e-9`.  Rationale: the JAX env core is float32; at million-¥ site-scale totals,
   float32 reconstruction error can reach ~1 ¥, which is safe under `1e-6·rel` (~3 ¥ at 3 × 10⁶)
   but would false-reject under the script's `1e-9·rel` (~0.003 ¥).

2. **Major-version guard (F3):** `validate()` rejects messages with `schema_version` major ≠ 1.
   The reference script has no such guard (it was authored as a one-shot tool, not a
   producer/consumer boundary enforcer).

3. **Defensive check functions (F4):** `check_env_step` and `check_eval_compare` skip individual
   checks when required fields are absent; neither function raises.  The reference script
   functions crash on missing fields since they are called only after the schema validator
   confirms presence.  The module functions are callable independently (e.g. unit tests) so
   they must be safe on partial payloads.
