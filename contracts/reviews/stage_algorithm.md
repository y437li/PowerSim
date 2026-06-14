# Review record — `stage_algorithm` (Wizard Stage ②, PR #115)

**Reviewer:** frontend-reviewer · **Feature:** `contracts/frontend/stage_algorithm.md` · **Branch:** `feat/frontend-stage-algorithm`

## Round 1 — `a62adff` — REQUEST_CHANGES (2026-06-14) — contract + tests gate (pre-implementation)

Reviewed the contract + the 84-case suite against REBUILD_SPEC §5, the LOCKED training schema
(`contracts/training/training_pipeline.md` `RunConfig`), the serving training contract
(`contracts/serving/training_proxy.md`), and binding decisions D32(b)/(c) + D37. The component
design, state machine, a11y coverage, STALE/persist structure, and most validation tests are
solid — but the **POST `/api/training/config` body diverges from the only canonical SAC config
schema**, and the suite would *lock in* that divergence. This is the same class as stage-1 B1
(a request body that doesn't match the schema the backend consumes → silent field drops / a
constraint bypass). Gating before tests are approved.

### Blockers

- **C1 — POST body field names do NOT match the canonical `RunConfig`, and no serving contract
  for `/api/training/config` exists.** §3.8 defines the wire body; `training_pipeline.md §3`
  `RunConfig` is the canonical SAC config consumed downstream. Five mismatches:

  | §3.8 body key | `RunConfig` field | |
  |---|---|---|
  | `total_steps` | `total_env_steps` | ❌ name |
  | `eval_freq` | `eval_every_steps` | ❌ name |
  | `learning_rate` | `lr` | ❌ name |
  | `hidden_layers` | `hidden_sizes` | ❌ name |
  | `gamma`,`batch_size`,`buffer_size`,`n_envs`,`tau` | same | ✓ names |

  The only serving training contract (`training_proxy.md`) exposes **`POST /training/start`**
  (a different path/purpose) and explicitly says (L231) its body "will be aligned when that
  contract lands." So `/api/training/config` is an **uncontracted endpoint**, and §3.8 picks
  names that conflict with `RunConfig`. **D37 + D32(b) are binding here:** wizard-form →
  canonical-config assembly must be a **single server-side implementation, no client/TS dialect**
  ("no stage may require a config field the others don't share"). As written, §3.8 spawns a second
  dialect for the algorithm config — exactly what D37 forbade for the site config.
  Tests `T-CONFIRM-1` and `T-BODY-1` hard-code `total_steps`/`learning_rate`/`hidden_layers`, so
  approving them locks the wrong wire format.
  **Resolve before tests lock (pick one, with the named owners):** (a) §3.8 adopts the `RunConfig`
  names; OR (b) a serving contract for `/api/training/config` (the stage-② analog of
  `site_assemble.md`) is locked, defining the exact body **and** the wizard→`RunConfig` mapping,
  and §3.8 cites it. Either way this is a **frontend↔serving producer/consumer boundary** —
  coordinate with **serving-engineer** (endpoint/mapping) and **training-engineer** (field
  semantics). frontend-reviewer gates the wizard-form input shape; backend-reviewer gates the
  serving mapping.

- **C2 — the wizard lets the operator violate the LOCKED `gamma` constraint (escalate to
  rl-architect).** `training_pipeline.md §3.1`: *"`gamma` MUST be 0.999. Any PR that lowers it
  requires a new rl-architect DECISION (demand charge is a monthly signal)."* The contract
  defaults `gamma = 0.99` (§3.2) and exposes it as a **user-editable field with range (0, 1]**, and
  `T-HYPER-6` pins `gamma = 1.0` as **valid** — all three directly contradict the binding 0.999
  rule. Options: (i) treat `gamma` as a **constant 0.999** (like `tau`/`hidden_sizes`, not a UI
  field); (ii) hard-pin validation to `gamma === 0.999`; or (iii) obtain an **rl-architect
  DECISION** explicitly permitting the wizard to override `gamma`. As written the contract +
  `T-HYPER-6` cannot both be approved and honor the lock. **Escalated to rl-architect.**

- **C3 — `n_envs` range conflicts with the training config (training-engineer sign-off).** §3.2
  restricts `nEnvs` to power-of-2 **1–256**; `T-HYPER-10` pins **512 as invalid**. But `RunConfig`
  defaults `n_envs = 4096` (§7 "vmap 4096 envs"), constraint "power of 2 ≥ 1" with **no 256 cap**.
  The operator therefore **cannot request the canonical parallelism**, and the form would reject
  valid training values. Confirm the intended UI cap with **training-engineer**; likely the upper
  bound should be 4096 (or removed). `T-HYPER-10`/`T-HYPER-5`(nEnvs) reopen with the resolved range.

### Note on DV-3
DV-3 flags only that *default values* differ from §5 and to "confirm with training-engineer." It
**undersells** the problem: the issues above are **field-name divergence (C1)**, a **locked-
constraint violation (C2)**, and a **range conflict (C3)** — structural conformance failures, not
just defaults. DV-3 should be split/expanded to cover all three, and the resolution recorded before
implementation.

### Required test additions (fold into the reworked suite; verified on re-review)
Not pushed now — several depend on resolving C1/C2/C3 (field names, gamma, nEnvs range), and adding
them against disputed names/ranges would churn. All are required before APPROVE:

- **TQ1** — POST body: assert the **exact key set** and **no camelCase leakage** (a swapped or
  duplicated field, or the raw store object being serialized, currently passes `T-BODY-1`). [after C1]
- **TQ2** — `batchSize` boundaries: 16 (power-of-2 but < 32 → error), 32 (min → valid), 4096 (max →
  valid), 8192 (power-of-2 but > 4096 → error). Only 256/300 are tested → an impl that checks
  power-of-2 but omits the 32–4096 bound (or vice-versa) passes.
- **TQ3** — `evalFreq = 1000` exact min (valid) — off-by-one (`>` vs `>=`); only 999 tested.
- **TQ4** — `totalSteps = 100_000` exact min (valid) — off-by-one; only 99_999 tested.
- **TQ5** — `nEnvs` = resolved max exact (valid) — off-by-one; only 512/15/1 tested. [after C3]
- **TQ6** — `learningRate = 1e-5` and `= 1e-2` exact inclusive bounds (valid) — only 5e-6/0.02 tested.
- **TQ7** — NaN/empty parse (§5.2 "Must be a number"): **no test**. A non-numeric blur must show the
  parse error and block confirm; `getHyperparamErrors` must treat NaN as an error. Risk: `NaN`
  serializes to `null` in the POST body — a silent data-corruption path. (High priority.)
- **TQ8** — cross-field `bufferSize ≥ batchSize × 4` against a **changed** batchSize: set
  batchSize=512 → bufferSize 2047 invalid / 2048 valid. Current `T-HYPER-7/8` only use the default
  256, so an impl hardcoding `≥ 1024` passes.
- **TQ9** — `aria-disabled` click interception (DV-2): clicking confirm while `aria-disabled="true"`
  must **not** fire fetch nor change state. Not tested (only the attribute is asserted).
- **TQ10** — double-submit guard: a second confirm click while `saveInProgress` must not fire a
  second POST.
- **TQ11** — `confirm-disabled-reason` priority (§4.6): "Fix hyperparameter errors" when baselines
  OK but a hyperparam is invalid; baseline message wins when both fail. Only the baseline message
  is tested.
- **TQ12** — `baseline_only` + invalid hyperparam: §3.7 `isConfirmEnabled` evaluates
  `getHyperparamErrors` **regardless of algorithmType**, so an invalid (and unsent) hyperparam would
  block confirm in baseline_only mode. Clarify intent; if hyperparams should be ignored in
  baseline_only, §3.7 + a pinning test must change. (Logic gap.)
- **TQ13** — `T-PERSIST-3` does **not** exercise the real `onRehydrateStorage` (it manually mimics
  the downgrade), so a missing/broken rehydrate hook passes — repeating the stage-1 Round-3 mistake.
  Rewrite to seed `localStorage["energygo.stage2"]` with a COMPLETE snapshot, call
  `await useStageAlgorithmStore.persist.rehydrate()`, and assert downgrade to IN_PROGRESS (DV-5).
- **TQ14** — `T-INIT-5` title says "disabled" but asserts **enabled** — fix the misleading title.
- **TQ15** — LOCKED flip `false → true → false`: content restores then re-locks; store state
  preserved across the flip. Only `true → false` (`T-LOCK-PROP-3`) is tested.

### Verified-good (no action)
State machine + WizardBar badge table (§2); algorithm radio semantics + Space-key (T-INIT-2/T-ALGO-5);
baseline-only DOM removal of HyperparamForm (T-ALGO-1/3); collapsed-inputs-absent-from-DOM (T-COLLAPSE-3,
DV-6); LOCKED content absent from DOM + no SR-announceable controls (T-LOCK-1/2, T-A11Y-8); confirm
`aria-disabled` not HTML-disabled (T-A11Y-5, DV-2); back-as-span (T-BACK-1, DV-1); API-error + Retry
re-fire (T-API-ERR-1/2/3, mirrors stage-1 B5/B6 — good); baseline ≥1 required + role=alert (T-BASE-3/4/6);
gamma=0 vs 1.0 boundary structure (T-HYPER-5/6, modulo C2); bufferSize exact-min structure (T-HYPER-8).

**Verdict: REQUEST_CHANGES.** Blockers C1 (field-name/serving-contract conformance), C2 (gamma lock —
rl-architect), C3 (n_envs range — training-engineer) must be resolved, then the 15 test additions
folded in. Re-review on the reworked contract + suite.
