# Contract: frontend/telemetry_validator

**Status:** DRAFT  
**Area:** frontend  
**Schema ref:** contracts/shared/telemetry_schema.md v1.0.0 (LOCKED, PR #6)  
**Task:** #24  
**Branch:** feat/frontend-telemetry-validator  

---

## §1 Purpose

A pure TypeScript validation module that validates incoming WebSocket messages against the
LOCKED telemetry schema before they are rendered by the dashboard or 3D scene. It is the
frontend counterpart of `scripts/validate_telemetry.py` and must enforce identical semantic
rules.

Consumers (dashboard, 3D scene) call `validate()` on each raw message and only proceed to
render on `ValidationResult.ok === true`. The exported helper functions (`checkD13Identities`,
`checkFiniteness`, `checkConservation`) are also usable in consumer unit tests.

---

## §2 Library choice

**Zod** (`zod@^3.x`) — TypeScript-first runtime validation, no JSON bundling required. 
Recorded in `STACK.md` under "Telemetry validation" in the same PR. Zod's inferred types
serve as a second layer of conformance against `src/types/telemetry.ts`.

---

## §3 Module location and exports

**File:** `src/validators/telemetryValidator.ts`

```typescript
// §3.1 Result types
export interface ValidationOk {
  ok: true;
  envelope: TelemetryEnvelope;  // typed + passed-through as-is (no mutation)
  warnings: string[];           // non-empty only for forward-compat version warnings
}
export interface ValidationFail {
  ok: false;
  errors: string[];   // at least one entry; machine-checkable codes (see §5)
  warnings: string[];
}
export type ValidationResult = ValidationOk | ValidationFail;

// §3.2 Primary entry point
export function validate(msg: unknown): ValidationResult;

// §3.3 Exported helpers (for consumer tests)
/** Returns error strings for D13 cost-identity violations; [] on pass. */
export function checkD13Identities(costs: PerStepCosts): string[];

/** Returns paths of non-finite numeric fields (NaN, ±Infinity); [] on pass. */
export function checkFiniteness(payload: unknown, path?: string): string[];

/** Returns error strings for per-source conservation violations; [] on pass. */
export function checkConservation(generation: GenerationBlock, flows: PowerFlows): string[];
```

---

## §4 Validation pipeline (in order)

`validate(msg)` applies these steps in sequence. On the FIRST failing step the function
returns `{ ok: false, errors, warnings }`. Steps that produce only warnings accumulate into
`warnings` without stopping the pipeline.

| Step | Check | On failure |
|------|-------|-----------|
| 4.1 | `msg` is a non-null object | `ok: false`, error `"not_object"` |
| 4.2 | `schema_version` present and matches semver pattern `^[0-9]+\.[0-9]+\.[0-9]+$` | `ok: false`, error `"bad_schema_version"` |
| 4.3 | Parse major from `schema_version`; if `major > 1` → reject | `ok: false`, error `"version_rejected:<schema_version>"` |
| 4.4 | If `major === 1` and `minor > 0` → add warning `"version_forward_compat:<schema_version>"`, continue. **Patch-only change (`minor === 0`, `patch > 0`) emits no warning.** | warning only, pipeline continues |
| 4.5 | Required envelope fields present: `kind`, `ts_utc`, `run_id`, `seq`, `payload` | `ok: false`, error `"missing_field:<fieldname>"` per absent field |
| 4.6 | `kind` is one of `"env_step"`, `"train_metrics"`, `"eval_compare"` | `ok: false`, error `"unknown_kind:<kind>"` |
| 4.7 | `payload` is a non-null object | `ok: false`, error `"bad_payload"` |
| 4.8 | `seq` is a non-negative integer | `ok: false`, error `"bad_seq"` |
| 4.9 | Finiteness: `checkFiniteness(payload)` — all number-typed fields must be finite. **Runs before Zod** so NaN/±Infinity yields `non_finite:` codes rather than `payload_invalid:` codes (Zod `z.number()` rejects NaN). | `ok: false`, errors `"non_finite:<path>"` per non-finite field |
| 4.10 | Payload field conformance via Zod schema for the `kind` (required fields present, types correct). All number fields are guaranteed finite at this point. | `ok: false`, error `"payload_invalid:<zod_error_path>"` per Zod issue |
| 4.11 | **env_step only:** D13 identities: `checkD13Identities(payload.costs)` | `ok: false`, errors from `checkD13Identities` |
| 4.12 | **env_step only:** Per-source conservation: `checkConservation(payload.generation, payload.flows)` | `ok: false`, errors from `checkConservation` |
| 4.13 | **eval_compare only:** Per-policy additive identity: for each key in `payload.policies`, verify `total_cost_yuan = energy_cost_yuan + demand_charge_yuan + degradation_yuan + curtailment_yuan + voll_yuan` (tol ≤ 1.0 ¥) | `ok: false`, error `"eval_total:<policy_key>:<delta>"` per violating policy |

Unknown fields in the envelope or payload are **silently ignored** (forward-compat rule — §3.7 / Versioning section of the locked schema).

---

## §5 Error code catalogue

All error strings are stable tokens for machine-checking in tests:

| Code | Meaning |
|------|---------|
| `not_object` | msg is not a non-null object |
| `bad_schema_version` | `schema_version` absent, not a string, or doesn't match semver |
| `version_rejected:<v>` | `major(v) > 1`; message discarded |
| `missing_field:<f>` | Required envelope field `f` absent |
| `unknown_kind:<k>` | `kind` is `k`, not a known telemetry kind |
| `bad_payload` | `payload` absent or not an object |
| `bad_seq` | `seq` not a non-negative integer |
| `payload_invalid:<path>` | Zod validation failure at field path `path` |
| `non_finite:<path>` | Numeric field at dotted `path` is NaN or ±Infinity |
| `d13_real:<delta>` | `cost_total_real_yuan` identity violated; `delta` = computed − stored |
| `d13_reward:<delta>` | `cost_total_reward_basis_yuan` identity violated |
| `d13_energy:<delta>` | `c_energy_yuan = c_import − r_export` identity violated |
| `d13_reward_formula:<delta>` | `reward = −(cost_total_reward_basis + penalty)×1e-5` violated |
| `conservation_solar:<delta>` | Solar source conservation violated |
| `conservation_wind:<delta>` | Wind source conservation violated |
| `eval_total:<policy>:<delta>` | Per-policy cost total identity violated in eval_compare; `policy` is the key (e.g. `rl`, `no_battery`); `delta` = computed − stored |

**Warning codes:**

| Code | Meaning |
|------|---------|
| `version_forward_compat:<v>` | `major = 1`, `minor > 0`; unknown fields silently ignored |

---

## §6 D13 identity tolerances

Monetary tolerance: **`|computed − stored| ≤ 1.0` ¥** (absolute).  
Reward formula tolerance: **`|computed − stored| ≤ 1e-6`** (the reward is dimensionless ×1e-5 scaled).

```
cost_total_real_yuan:
  computed = c_energy_yuan + c_demand_charge_yuan + c_degradation_yuan
             + c_curtail_yuan + c_voll_yuan
  |computed − cost_total_real_yuan| ≤ 1.0

cost_total_reward_basis_yuan:
  computed = c_energy_yuan + 2.0 × c_demand_shape_yuan + c_degradation_yuan
             + c_curtail_yuan + c_voll_yuan
  |computed − cost_total_reward_basis_yuan| ≤ 1.0

c_energy_yuan:
  computed = c_import_yuan − r_export_yuan
  |computed − c_energy_yuan| ≤ 1.0

reward:
  computed = −(cost_total_reward_basis_yuan + penalty_yuan) × 1e-5
  |computed − reward| ≤ 1e-6
```

### eval_compare per-policy identity (§4.13)

Monetary tolerance: **`|computed − stored| ≤ 1.0` ¥** (absolute).

Applied to every key in `payload.policies` (current schema: `rl`, `no_battery`,
`rule_based_tou`; forward-compat: unknown policy keys are also checked if they
have all five addend fields):

```
per-policy identity:
  computed = energy_cost_yuan + demand_charge_yuan + degradation_yuan
             + curtailment_yuan + voll_yuan
  |computed − total_cost_yuan| ≤ 1.0
  error: eval_total:<policy_key>:<delta>
```

---

## §7 Per-source conservation tolerances

```
solar conservation:
  computed = solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed_mw
  |computed − gross_solar_mw| ≤ 0.001 MW

wind conservation:
  computed = wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed_mw
  |computed − gross_wind_mw| ≤ 0.001 MW
```

---

## §8 Finiteness scope

`checkFiniteness` recursively traverses the payload object. Any JSON `number` value that
is `NaN`, `Infinity`, or `-Infinity` at any depth is reported with its dotted path.

Traversal rules:
- **Plain object** — recurse into each value; key appended to path.
- **Array** — recurse into each element; index appended as `[i]` (e.g. `assets_ext.gas[0].capacity_mwh`).
- **Primitive `number`** — checked for finiteness; non-finite → path reported.
- **Strings, booleans, `null`** — not number-typed, skipped.

This ensures numeric fields inside future `assets_ext.gas[]` / `electrolyzer[]` arrays
(§8 composable-asset extensions) are covered by the same check without a schema update.

Note: standard JSON does not permit NaN/Infinity literals, but the JS runtime may produce
them through arithmetic and `JSON.parse` does not guard against hand-constructed objects.

---

## §9 Unhappy paths guaranteed handled

- `msg` is `null`, `undefined`, a string, number, or array → `not_object`
- `schema_version` is `"2.0.0"` → `version_rejected:2.0.0`, `ok: false`
- `schema_version` is `"1.5.0"` → `ok: true`, `warnings: ["version_forward_compat:1.5.0"]`
- Missing `kind` → `missing_field:kind`
- Missing `payload` → `missing_field:payload`
- `kind: "completely_unknown"` → `unknown_kind:completely_unknown`
- `payload.costs.cost_total_real_yuan` off by 2000 → `d13_real:…`
- `payload.reward` is NaN → `non_finite:reward`
- `payload.battery.soc` is Infinity → `non_finite:battery.soc`
- `payload.generation.gross_solar_mw` off by 5 MW → `conservation_solar:…`
- eval_compare `policies.rl.total_cost_yuan` off by 1000 → `eval_total:rl:…`, `ok: false`

---

## §10 Integration with wsClient

`validate()` is called by `wsClient` on every incoming message. On `ok: false`, the client
logs the errors and does NOT dispatch to any store callback. On `ok: true`, the envelope is
dispatched typed. This replaces the ad-hoc checks in the current wsClient (§4.3 envelope
check, version check).

> **Migration note (post-merge):** Once this module is merged, `wsClient.ts` should delegate
> its existing version check and missing-field guard to `validate()` rather than duplicating
> the logic. This is a non-breaking refactor and can happen in the same PR as this contract
> or a follow-up.

---

## §11 Test fixtures

Tests import the golden examples from `contracts/shared/telemetry_examples/`:
- `env_step_a.json` (golden A: net export, no demand activity)
- `env_step_b.json` (golden B: month-boundary demand charge)
- `train_metrics.json`
- `eval_compare.json`

These files are the authoritative passing cases; if `validate()` returns `ok: false` for any
of them, the implementation is wrong.
