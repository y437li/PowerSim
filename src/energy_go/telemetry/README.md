# `src/energy_go/telemetry`

<!-- curated -->
## Purpose

This package is the Python-side telemetry validator (see `contracts/shared/telemetry_validate.md`). Its single module, `validate.py`, exposes `validate(msg)` which checks an incoming message against three layers of correctness:

1. **Schema conformance**: the message must match the LOCKED telemetry schema v1.0.0 (`contracts/shared/telemetry_schema.md`, D18), whose JSON form is bundled in `data/telemetry_schema.json` within this package.
2. **Physics identities** (for `env_step` messages): D13 cost-accounting identities, the reward formula, and solar/wind energy-conservation checks via `check_env_step`.
3. **Finiteness**: every float field is checked for NaN and Inf via `check_finite`.

The `eval_compare` variant is checked separately by `check_eval_compare` for its own total-cost identities.

What does NOT live here: telemetry emission (that is `training/telemetry.py`, which builds the envelopes), and WebSocket transport (that is the `serving` package).
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `validate.py`

> energy_go.telemetry.validate — importable telemetry validator.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `check_finite` | `function` | Return errors for every non-finite (NaN or Inf) float in msg. |
| `check_env_step` | `function` | Return errors for D13 cost identities, reward formula, and solar/wind conservation. |
| `check_eval_compare` | `function` | Return errors for eval_compare total_cost identities. |
| `validate` | `function` | Validate a telemetry message against the LOCKED schema v1.0.0. |

<!-- generated:end -->
