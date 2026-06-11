# Contract: frontend/telemetry_validator

**Status:** AMENDMENT-DRAFT  
**Area:** frontend  
**Schema ref:** contracts/shared/telemetry_schema.md v1.0.0 (LOCKED, PR #6)  
**Task:** #24 (original) / #29 (robustness amendment)  
**Branch:** feat/frontend-telemetry-validator-robustness  
**Amendment rationale:** LINEAGE D26 — serving now deliberately forwards validation-failing
frames at runtime (resilience-first: don't crash a multi-hour session). The frontend
`validate()` call is therefore the **last enforcement point**. Frontend-reviewer system-coupling
check (PR #46) confirmed the gap: `telemetryValidator.ts` was implemented but not wired into
`wsClient.ts`, so a frame with a missing inner field (`payload.battery`) propagates to the
store, throws in a dashboard component, and the single app-level `ErrorBoundary` (no reset
mechanism) takes down the entire UI until manual reload.  

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

**validate() return values:**
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

**wsClient robustness (post-D26 wiring):**
- env_step frame with `payload.battery` omitted → `ok: false` (Zod) → `onEnvStep` NOT called; `pushFrameError()` called; WS alive; next valid frame processes normally
- env_step frame with `battery.soc: null` → `ok: false` (Zod) → same drop semantics
- `status` frame → bypasses `validate()` entirely → `onServerStatus` called regardless
- `validate()` throws internally → frame dropped, no exception propagated, session alive

---

## §10 Integration with wsClient (amended — task #29)

### §10.1 Mandatory wiring

`validate()` MUST be called inside `wsClient.handleMessage` on every **data frame**
(`kind ∈ {env_step, train_metrics, eval_compare}`) **before** any store callback is invoked.

Control frames (`kind ∈ {status, error}`) and unrecognised kind values MUST bypass
`validate()` and be handled by their dedicated dispatch paths (`onServerStatus` /
`onServerError`).  This is required because control frames have no `payload` envelope field
and `validate()` would always reject them with `missing_field:payload`.

### §10.2 Exception safety

The call to `validate()` MUST be wrapped in a `try/catch`.  Any synchronous exception thrown
by `validate()` is treated identically to a `{ ok: false }` result: the frame is dropped,
`pushFrameError()` is called with `errors: ["validate_threw"]`, and no dispatch callback is
invoked.  The exception MUST NOT propagate and MUST NOT close the WebSocket connection.

### §10.3 Dispatch rules

| `validate()` outcome | Dispatch to store callback? | `pushFrameError()` called? |
|----------------------|----------------------------|---------------------------|
| `ok: true`, no warnings | ✅ Yes | ❌ No |
| `ok: true`, warnings present | ✅ Yes | ✅ Yes (one entry; `errors = warnings`) |
| `ok: false` | ❌ No | ✅ Yes |
| Exception thrown | ❌ No | ✅ Yes (`errors: ["validate_threw"]`) |

Structured log for any dropped frame (console.warn):
```
[wsClient] INVALID frame dropped kind=<kind> seq=<seq>: [<error_codes>]
```

### §10.4 Effect on consumers

After this wiring the dashboard stores (`telemetryStore`, `trainingStore`) only ever receive
frames that passed full validation.  Dashboard and 3D scene components that access fields like
`envStep.battery.soc` can rely on the field being present and finite — no per-component
try/catch required.

The existing ad-hoc `payload === undefined` guard in `wsClient.handleMessage` MUST be kept
for forward-compatibility (control frames still pass through that code path before the
kind-specific branch).  For data frames it is superseded by §4.5 (`missing_field:payload`).

---

## §11 Test fixtures

Tests import the golden examples from `contracts/shared/telemetry_examples/`:
- `env_step_a.json` (golden A: net export, no demand activity)
- `env_step_b.json` (golden B: month-boundary demand charge)
- `train_metrics.json`
- `eval_compare.json`

These files are the authoritative passing cases; if `validate()` returns `ok: false` for any
of them, the implementation is wrong.

The robustness integration tests (TV.ROB.*) live in
`tests/frontend/telemetry_validator.test.tsx` alongside the existing unit tests.

---

## §12 Runtime drop semantics (post-D26)

Per LINEAGE D26 the *serving* layer is resilient — it forwards validation-failing frames
rather than terminating the stream.  The frontend's `validate()` call in `wsClient` is
therefore the **last enforcement point**.

When the frontend drops a frame (§10.3):
- The WebSocket connection MUST remain open.
- Store state MUST NOT change — the previous `envStep` / `history` values remain intact.
- `pushFrameError()` MUST be called so the UI can alert the operator (§13).
- The client MUST remain capable of processing the *next* frame correctly.

This is the inverse of D26 serving behaviour: serving sends the frame on ("resilience-first");
the frontend is the terminal consumer and drops it ("defense-in-depth").

---

## §13 FrameError surfacing API

### §13.1 FrameError type

```typescript
export interface FrameError {
  /** ISO-8601 timestamp: msg.ts_utc if parseable, else new Date().toISOString() */
  ts_utc: string;
  /** msg.kind, or "unknown" if the message was not parseable */
  kind: string;
  /** msg.seq, or -1 if the message was not parseable */
  seq: number;
  /** Validation error codes from ValidationResult.errors, or ["validate_threw"] */
  errors: string[];
}
```

### §13.2 telemetryStore additions

`useTelemetryStore` (file: `src/stores/telemetryStore.ts`) gains two members:

```typescript
/** Ring buffer of recent frame validation failures — most-recent-first. Capacity: 10. */
frameErrors: FrameError[];

/** Prepend a new FrameError entry; trim the buffer to cap (10). */
pushFrameError(err: FrameError): void;
```

`clearHistory()` MUST also reset `frameErrors` to `[]`.  Initial state: `frameErrors: []`.

Prepend-to-front ensures `frameErrors[0]` is always the most recent error, consistent
with the newest-first ordering of `deriveAlerts`.

### §13.3 UI surfacing

The `AlertList` component (or a new `FrameErrorBanner` component placed adjacent to it) MUST
render `frameErrors` so the operator can see that invalid frames were received.

Rendering requirements:
- Each `FrameError` MUST be reachable by `data-testid="frame-error-<index>"` (0-based).
- The rendered text MUST include the `kind`, `seq`, and at least one error code.
- An empty `frameErrors` array MUST produce no frame-error DOM nodes.

> **Implementation choice delegated to implementer:** extending `AlertList` with a separate
> prop `frameErrors: FrameError[]`, or creating a standalone `FrameErrorBanner` component,
> are both conformant.  The test pin is the `data-testid` requirement above.

---

## §14 Acceptance criteria (TV.ROB series)

| ID | Test | Must verify |
|----|------|-------------|
| TV.ROB.1 | wsClient gate — valid env_step dispatched | Real golden A passes validate(), onEnvStep called |
| TV.ROB.2 | wsClient gate — missing battery drops frame | `payload.battery` absent → onEnvStep NOT called |
| TV.ROB.3 | wsClient gate — pushFrameError called on drop | frameErrors.length === 1 after invalid frame |
| TV.ROB.4 | FrameError shape | kind, seq populated; errors contains `payload_invalid:*` |
| TV.ROB.5 | null field drop | `battery.soc: null` → onEnvStep NOT called |
| TV.ROB.6 | valid train_metrics dispatched | Real golden train_metrics → onTrainMetrics called |
| TV.ROB.7 | invalid train_metrics dropped | missing global_step → onTrainMetrics NOT called |
| TV.ROB.8 | valid eval_compare dispatched | Real golden eval_compare → onEvalCompare called |
| TV.ROB.9 | status bypass | status frame → onServerStatus called (no payload → bypass confirmed) |
| TV.ROB.10 | session survives bad frame | invalid → valid → valid frame dispatched correctly |
| TV.ROB.11 | store state preserved | envStep unchanged after invalid frame |
| TV.ROB.12 | no false positives | valid env_step → frameErrors stays empty |
| TV.ROB.13 | exception safety — no dispatch | validate() throws → onEnvStep NOT called, no thrown exception |
| TV.ROB.14 | exception safety — pushFrameError | validate() throws → frameErrors[0].errors === ["validate_threw"] |
| TV.ROB.15 | initial state | frameErrors: [] on fresh store |
| TV.ROB.16 | prepend ordering | second pushFrameError → newest at index 0 |
| TV.ROB.17 | ring buffer cap | 11th push evicts oldest; length stays 10 |
| TV.ROB.18 | clearHistory resets errors | clearHistory() → frameErrors: [] |
| TV.ROB.19 | golden pipeline A | env_step_a.json end-to-end: validate ok:true → dispatched with correct run_id, seq |
| TV.ROB.20 | golden pipeline B | env_step_b.json end-to-end: validate ok:true → dispatched |
