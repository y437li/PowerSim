# `src/validators`

<!-- curated -->
## Purpose

TypeScript telemetry validator. The single module here, `telemetryValidator.ts`, implements the 12-step validation pipeline defined in `contracts/frontend/telemetry_validator.md`. It validates every incoming WebSocket message against the LOCKED telemetry schema v1.0.0 (D18, `contracts/shared/telemetry_schema.md`) using Zod (STACK: zod@^3.x), returning a `ValidationResult` with an `ok` flag and, on failure, structured error details.

`wsClient.ts` calls `validate()` before dispatching any message to the stores; frames that fail validation are rejected and recorded in the `telemetryStore` frame-error ring buffer instead of being applied to state.

This folder is validation-only. It does not render, does not mutate stores, and does not perform network I/O.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `telemetryValidator.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `ValidationOk` | `interface` | — |
| `ValidationFail` | `interface` | — |
| `ValidationResult` | `type` | — |
| `checkFiniteness` | `function` | Returns dotted paths of all non-finite numeric fields (NaN, ±Infinity) found |
| `checkD13Identities` | `function` | Checks the three monetary D13 cost identities for an env_step payload's costs. |
| `checkConservation` | `function` | Checks per-source (solar, wind) conservation for an env_step payload. |
| `validate` | `function` | Validates an incoming WebSocket telemetry message against the LOCKED schema. |

<!-- generated:end -->
