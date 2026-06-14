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
| `checkFiniteness` | `function` | telemetryValidator.ts |
| `checkD13Identities` | `function` | telemetryValidator.ts |
| `checkConservation` | `function` | telemetryValidator.ts |
| `validate` | `function` | telemetryValidator.ts |

<!-- generated:end -->
