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

**Store-boundary robustness (post-D26 wiring, per §10 amendment):**
- env_step frame with `payload.battery` omitted → `validate()` returns `ok: false` (Zod) → `receiveEnvStep` skips state update; last-good `envStep` preserved; `droppedFrameCount` incremented; no crash
- env_step frame with `payload.reward: NaN` → `non_finite:reward` → same skip semantics
- D13 identity violation (costs don't sum) → `d13_real:…` → skipped + `telemetry_invalid` alert surfaced
- valid frame after bad one → accepted; store updates; recovery is per-frame, not sticky

---

## §10 Integration: store-boundary validation (amended — task #29, post-D26)

### §10.1 Primary wiring: validate() at the store boundary

`validate()` MUST be called inside **`telemetryStore.receiveEnvStep`** (for `env_step` frames)
and **`trainingStore.receiveTrainMetrics`** (for `train_metrics` frames) **before any state
update**, on every frame the respective store method receives.

The store boundary is the correct validation point because:
- The payload type is known here (`EnvStepPayload` / `TrainMetricsPayload`)
- The validator's design says "consumers call `validate()`" — the store IS the consumer
- This is symmetric with the 3D scene's §3.3 keep-last-valid finiteness guard
- Per D26, `wsClient` forwards frames (envelope-only awareness); stores are the last
  enforcement point for payload content

### §10.2 wsClient envelope checks remain unchanged

`wsClient.ts` MUST NOT call `validate()` on payload content.  Its existing envelope-level
checks are kept as-is: discard non-JSON, missing-`kind`, future-major-version, and
`payload === undefined` on data frames.  Routing to store callbacks (`onEnvStep`,
`onTrainMetrics`) is unconditional once those checks pass.

### §10.3 Skip semantics in receiveEnvStep

When `validate(msg)` returns `ok: false` for an env_step frame:

1. State update **SKIPPED** — `envStep` and `history` retain their last-good values
2. `droppedFrameCount` incremented by 1
3. `lastValidationErrors` replaced with the returned error array
4. A `"telemetry_invalid"` alert MUST be surfaced via `deriveAlerts` (§13.2)

Structured console warning (always logged for dropped frames):
```
[telemetryStore] INVALID env_step dropped seq=<seq>: [<error_codes>]
```

> **Keep-last-valid, not field-clamping:** a frame failing finiteness or D13 is untrustworthy
> as a whole.  Clamping individual NaN/Inf fields would display physically inconsistent state.
> Preserving the last valid snapshot is the correct behaviour — mirroring the 3D scene's guard.

### §10.4 Skip semantics in receiveTrainMetrics

When `validate(msg)` returns `ok: false` for a train_metrics frame:

1. `trainingStore` state update SKIPPED
2. `trainingStore.droppedFrameCount` incremented
3. `trainingStore.lastValidationErrors` updated

### §10.5 Recovery (per-frame, not sticky)

A valid frame arriving after one or more invalid frames MUST be accepted and update state
normally.  The skip is purely per-frame — there is no "poisoned" mode.

---

## §11 Test fixtures

Tests import the golden examples from `contracts/shared/telemetry_examples/`:
- `env_step_a.json` (golden A: net export, no demand activity)
- `env_step_b.json` (golden B: month-boundary demand charge)
- `train_metrics.json`
- `eval_compare.json`

These files are the authoritative passing cases; if `validate()` returns `ok: false` for any
of them, the implementation is wrong.

The robustness store-boundary tests (TV.ROB series) live in
`tests/frontend/telemetry_validator.test.tsx` alongside the existing unit tests.

---

## §12 Runtime drop semantics (post-D26)

Per LINEAGE D26 the *serving* layer is resilient — it forwards validation-failing frames
rather than terminating the stream.  The frontend store's `validate()` call is therefore
the **last enforcement point** for payload content.

When the store drops a frame (§10.3–§10.4):
- `wsClient` connection MUST remain open (drop is in the store, not the transport layer)
- Store state MUST NOT change — the previous `envStep` / `history` values remain intact
- `droppedFrameCount` is incremented and `lastValidationErrors` is updated for UI surfacing
- The store MUST remain capable of processing the *next* frame correctly

This is the D26 inverse: serving sends the frame on ("resilience-first"); the store is the
terminal consumer and discards it ("defense-in-depth").

---

## §13 Dropped-frame surfacing

### §13.1 telemetryStore additions

`useTelemetryStore` (file: `src/stores/telemetryStore.ts`) gains:

```typescript
/** Count of env_step frames rejected by validate() since last clearHistory(). */
droppedFrameCount: number;

/** Error codes from the most recently rejected env_step frame; [] if none dropped. */
lastValidationErrors: string[];
```

`clearHistory()` MUST reset both: `droppedFrameCount → 0`, `lastValidationErrors → []`.
Initial state: both at their zero values.

### §13.2 "telemetry_invalid" AlertEvent kind

`AlertEvent.kind` (file: `src/utils/deriveAlerts.ts`) gains the new variant:

```typescript
kind: "curtailment" | "voll" | "soc_violation" | "telemetry_invalid"
```

`deriveAlerts(history, droppedFrameCount, lastValidationErrors)` is amended to accept the
two new arguments.  When `droppedFrameCount > 0` it prepends a `"telemetry_invalid"` entry:

```typescript
{
  kind: "telemetry_invalid",
  stepIndex: -1,           // no valid step number for a dropped frame
  penaltyYuan: 0,          // not applicable
  detail: `${droppedFrameCount} frame(s) dropped: ${lastValidationErrors.join("; ")}`,
}
```

The alert appears at the top of the alert list (prepended, not sorted with physics alerts).
It is cleared when `clearHistory()` resets `droppedFrameCount` to 0.

### §13.3 trainingStore additions

`trainingStore` gains the symmetric fields:

```typescript
droppedFrameCount: number;
lastValidationErrors: string[];
```

---

## §14 ErrorBoundary defense-in-depth (A4)

The top-level `ErrorBoundary` (file: `src/components/ErrorBoundary.tsx`) MUST gain a
`resetKey` prop so that a component crash self-heals when session state changes — instead of
locking the whole UI permanently until manual reload.

```typescript
interface ErrorBoundaryProps {
  children: ReactNode;
  resetKey?: string | number;  // boundary resets when this value changes
}
```

When `resetKey` changes (componentDidUpdate detects `prevProps.resetKey !== this.props.resetKey`),
the boundary MUST reset its error state and re-render children.

**Wiring in `App.tsx`:** the `ErrorBoundary` is given a `resetKey` derived from
`useTelemetryStore(s => s.wsStatus + s.runId)` (or similar) so that WS reconnection or a
new inference session automatically clears a crashed boundary.

This is the defense-in-depth layer; the primary fix (§10.3) prevents most crashes.
A residual crash from unforeseen edge cases is now self-healing.

---

## §15 Acceptance criteria (TV.ROB series)

| ID | Test | Must verify |
|----|------|-------------|
| TV.ROB.1 | NaN field → receiveEnvStep skips | `payload.reward: NaN` → envStep unchanged, history unchanged, droppedFrameCount=1 |
| TV.ROB.2 | Infinity field → skipped | `Infinity` in any numeric field → same skip semantics |
| TV.ROB.3 | Missing sub-object → no throw | `payload.battery` absent → receiveEnvStep does NOT throw; store unchanged |
| TV.ROB.4 | Recovery — valid after bad | Bad frame skipped, next valid frame accepted; store updates correctly |
| TV.ROB.5 | Golden regression | env_step_a.json → validate ok:true → envStep updated, history grows |
| TV.ROB.6 | droppedFrameCount surfaces | bad frame → droppedFrameCount=1, lastValidationErrors non-empty |
| TV.ROB.7 | D13 violation → skipped + alerted | costs don't sum → ok:false → skipped; `deriveAlerts` includes `"telemetry_invalid"` entry |
| TV.ROB.8 | ErrorBoundary resetKey | child throws; resetKey changes → boundary resets, children re-render |
| TV.ROB.9 | Render integration | Component reads `envStep.battery.soc` from store; bad frame rejected → renders last-good value, not "NaN MW", no crash |
| TV.ROB.10 | trainingStore symmetric | invalid train_metrics → trainingStore skips state update |
