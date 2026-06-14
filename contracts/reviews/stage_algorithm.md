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

## Round 2 — `dee1b3f` — REQUEST_CHANGES (2026-06-14) — re-gate after rl-architect CALL 1 + CALL 2

Re-reviewed the amended contract + 78-case suite. **Two rl-architect rulings correctly applied** —
genuine progress:
- **CALL 1 (DV-3 resolved — §5 wins) ✓** — defaults corrected to canonical §5 values
  (`totalSteps=500_000`, `batchSize=512`, `lr=1e-4`, `gamma=0.999`, `nEnvs=4`); constants
  `tau`/`ent_coef="auto"`/`train_freq=1`/`gradient_steps=1` added; DV-3 struck in §8;
  T-HYPER-7/8 cross-field + T-BODY golden examples updated to the new defaults. Good.
- **CALL 2 (heuristic-first) ✓** — store default → `baseline_only`; SAC coming-soon copy mandated
  (§4.2) and **tested** (T-INIT-5 → `algo-sac-coming-soon-notice`); baseline notice on initial
  render; hyperparam section absent on initial render; ~20 tests flipped coherently (spot-checked
  T-INIT-1/4 — correct). DV-7 added; §12 records the PENDING-USER SAC-prominence call. Good.

**But CALL 1/CALL 2 were about default *values* and product direction — they did NOT address the
Round-1 structural blockers, which remain:**

- **C1 — STILL OPEN (primary).** The POST body still uses `total_steps` / `eval_freq` /
  `learning_rate` / `hidden_layers` (contract §3.8; tests L638-649, L1055-1067) — unchanged from
  Round 1; still diverges from `RunConfig`'s `total_env_steps` / `eval_every_steps` / `lr` /
  `hidden_sizes`. No serving contract for `/api/training/config` was added/cited. **New wrinkle:**
  the added constants `train_freq` / `gradient_steps` are **not fields in `RunConfig`** at all
  (RunConfig has `ent_coef` ✓ but no train_freq/gradient_steps), so the body now mixes
  canonical names, divergent names, AND fields absent from the canonical schema. CALL 1 ("§5 wins")
  fixed the *values*, not the *names/shape*. Resolution unchanged: (a) rename the 4 divergent keys
  to `RunConfig` names + reconcile train_freq/gradient_steps with training-engineer (do they belong
  in RunConfig, or not in the body?), OR (b) land + cite a serving `/api/training/config` contract
  defining the body + wizard→RunConfig mapping. Given SAC is now deferred (CALL 2), the sac_hyperparams
  wire shape is forward-compat — fine to defer the *serving contract*, but then §3.8 must mark the
  shape PROVISIONAL and the body tests must not assert it as final. As written, T-BODY-1/T-CONFIRM-1
  still lock divergent names. **Recommended:** the rename (cheap, permanent, D37-compatible).

- **C2 — PARTIALLY resolved; mechanism still open.** Default is now correctly `gamma=0.999` ✓.
  But gamma is **still a user-editable field with range `0 < γ ≤ 1`** (§3.2), and **T-HYPER-6 still
  pins `gamma=1.0` as VALID** (tests L306-309). The locked rule (`training_pipeline.md §3.1`) is
  `gamma` **MUST be 0.999** — so the wizard still accepts (and a test still blesses) values the
  training contract forbids. CALL 1 fixed the default but not the editability. **The fix the lock
  implies:** move `gamma` into the constants block (`=0.999`, non-editable — exactly like `tau`),
  remove it from `SacHyperparams`/the form, and replace T-HYPER-5/6 with a "body carries
  `gamma === 0.999`" assertion. (Alternative: an explicit rl-architect DECISION that the wizard may
  submit gamma≠0.999 — but CALL 1 did not say that; it set the default and called γ=0.999
  "§5-justified.") Until one of these, the contract + T-HYPER-6 cannot be approved against the lock.

- **C3 — downgraded to a standing condition.** `nEnvs` range is still 1–256 (T-HYPER-10 pins 512
  invalid), but the default is now 4 (valid) and SAC is deferred, so this is non-functional in v1.
  Confirm the intended UI cap with **training-engineer** before SAC ships (RunConfig allows up to
  4096, no 256 cap); T-HYPER-10 reopens then. Not gating this round.

**Test additions:** still pending (correctly held). **TQ13 NOT addressed** — `T-PERSIST-3` still
fakes the downgrade (`store.setState('COMPLETE')` + manual `if` mimic) instead of exercising the real
`persist.rehydrate()` / `onRehydrateStorage` (tests L884-893). The other algorithm-agnostic additions
(TQ2 batchSize 16/32/4096/8192, TQ3/TQ4/TQ6 exact bounds, TQ7 NaN-parse, TQ8 cross-field-vs-changed-
batchSize, TQ9 aria-disabled interception, TQ10 double-submit, TQ11 disabled-reason priority, TQ15 lock
flip) can now be added — they no longer depend on C1/C2 resolution (TQ1/TQ5 still wait on C1/C3).
TQ14 is moot (T-INIT-5 was repurposed for the coming-soon notice).

**Verdict: REQUEST_CHANGES.** CALL 1/CALL 2 well applied, but C1 (field-name/serving-contract — primary)
and C2 (gamma editability mechanism) remain; C3 becomes a standing condition; TQ13 + the held TQ
additions still required. Re-review on the next revision.

## Round 3 — `3a1964b` (+ reviewer tests) — APPROVE (2026-06-14) — contract + tests gate

Re-reviewed the amended contract + suite against the diff (`dee1b3f..3a1964b`), code-verified (not
claim-verified). **All three blockers resolved:**

- **C1 ✓** — §3.8 body now uses `RunConfig` canonical names exactly: `total_env_steps`,
  `eval_every_steps`, `lr`, `buffer_size`, `n_envs` (editable) + `gamma`/`tau`/`ent_coef`/`train_freq`/
  `gradient_steps`/`hidden_sizes` (constants). `T-CONFIRM-2` + `T-BODY-2` assert the new names present
  **and** the 4 old names (`total_steps`/`eval_freq`/`learning_rate`/`hidden_layers`) absent. Serving
  dependency documented (§3.8, §12 Q3, DV-8). → carried as **SC1** (standing condition).
- **C2 ✓** — `gamma` removed from `SacHyperparams` entirely; now a LOCKED constant (=0.999) in §3.2 +
  the §3.8 constants block; absent from `DEFAULT_HYPERPARAMS`. `T-HYPER-5` asserts absence from
  `getHyperparamErrors`; `T-HYPER-19` asserts no `hyperparam-gamma` DOM input even in SAC mode;
  `T-BODY-2` asserts the body carries `gamma === 0.999` as a constant. Exactly the lock-honoring fix.
- **C3 ✓** — 256 cap removed; valid = power of 2 ≥ 1 (RunConfig). `T-HYPER-6` (512 valid),
  `T-HYPER-10` (4096 valid). UI display cap → **SC2** (training-engineer, §12 Q2). Validation is
  correct now.

**Other amendments verified:** TQ12 (`isConfirmEnabled` gates hyperparam errors on
`algorithmType==='sac'`; `T-HYPER-20`) ✓; `T-PERSIST-3` rewritten to call the real `onRehydrate`
downgrade hook ✓; `T-LOCK-PROP-4` false→true→false flip (TQ15) ✓; `T-INIT-8` Option-B future-badge ✓;
Q1 (SAC visual prominence) resolved → Option B (USER decision). evalFreq default 50_000→10_000 (matches
RunConfig `eval_every_steps`) ✓.

**Reviewer test additions (pushed this round, marked `// reviewer:`, §T15):** TQ1 `T-BODY-3`
(exact 12-key set + no camelCase leakage); TQ2 `T-HYPER-21..24` (batchSize 16 invalid / 32 valid /
4096 valid / 8192 invalid); TQ3 `T-HYPER-25` (evalFreq=1000 valid); TQ4 `T-HYPER-26`
(totalSteps=100_000 valid); TQ6 `T-HYPER-27` (lr=1e-5 & 1e-2 valid); TQ7 `T-HYPER-28` (NaN flagged)
+ `T-HYPER-29` (non-numeric UI parse error blocks confirm); TQ8 `T-HYPER-30` (cross-field bufferSize
vs **changed** batchSize=1024: 4095 invalid / 4096 valid); TQ9 `T-CONFIRM-6` (aria-disabled click is
a no-op — no POST); TQ10 `T-CONFIRM-7` (no double-submit while saving); TQ11 `T-REASON-1/2`
(disabled-reason: hyperparam message when baselines OK; baseline message wins when both fail).
**TQ5 moot** (nEnvs cap removed — `T-HYPER-10` covers 4096). **TQ13/TQ15** delivered by the engineer
(T-PERSIST-3 / T-LOCK-PROP-4). **TQ14 moot** (T-INIT-5 repurposed). esbuild parse-check clean; suite
remains red-first (no `src/` yet), as expected at this gate.

**Approved suite = developer cases (T-INIT/T-ALGO/T-HYPER-1..20/T-COLLAPSE/T-BASE/T-CONFIRM-1..5/
T-API-ERR/T-BACK/T-STALE/T-PERSIST/T-A11Y/T-BODY-1..2/T-LOCK-PROP) + the 13 reviewer cases in §T15
(T-BODY-3, T-HYPER-21..30, T-CONFIRM-6/7, T-REASON-1/2).**

### Standing conditions (carried to the IMPLEMENTATION gate — NOT blocking this gate; mirrors stage-1 §5.1)
- **SC1 — serving contract for `POST /api/training/config` is a prerequisite to implementation.**
  No `contracts/serving/training_config.md` exists yet (serving-engineer; the stage-② analog of
  `site_assemble.md`, per D37/D32(b)). §3.8's body **shape** (the `sac_hyperparams` nesting + exact
  12-key set + the `train_freq`/`gradient_steps` constants, which are **not** `RunConfig` fields) is
  **CONTINGENT** on that contract locking with the same shape. Field *names* are RunConfig-canonical
  and settled; if the serving contract's structure diverges, §3.8 + T-CONFIRM-2/T-BODY-2/T-BODY-3
  reopen through frontend-reviewer. Backend-reviewer gates the serving mapping.
- **SC2 — nEnvs UI upper bound (§12 Q2)** — RunConfig has no max (canonical vmap 4096); training-engineer
  to confirm the wizard's display cap before implementation. Validation logic (power-of-2 ≥ 1) is correct
  regardless; if a cap is added, add the boundary test then.

**Verdict: APPROVE** (contract + tests gate). C1/C2/C3 resolved and code-verified; all required test
additions present (developer + reviewer); two standing conditions carried to the implementation gate.
Implementation may proceed once SC1's serving contract is locked (and SC2 confirmed). I re-review the
implementation against the locked serving contract + this suite.

## Round 4 — `9745918` (+ reviewer tests) — APPROVE (2026-06-14) — re-gate after rl-architect v1 scope ruling

**My Round-3 APPROVE (8d27b77) was superseded:** the engineer pushed `9745918` — a major
**v1 scope simplification** per a fresh rl-architect ruling (cited on the PR; relayed via team-lead
2026-06-14). SAC RL training is **deferred to a later release**. This re-gate reviews the new (smaller)
scope from scratch; my prior APPROVE no longer covers the head.

**New v1 scope (verified against the diff `8d27b77..9745918`):**
- SAC is a **non-submitting stub** card (Option B secondary/de-emphasized): coming-soon notice +
  **read-only §5 constants PREVIEW** (no editable form, no validation). Selecting it only records
  `algorithmType='sac'` for carry-forward.
- **No `POST /api/training/config` in v1** — `confirm()` sets `stageState=COMPLETE` locally (no network);
  the endpoint is PROVISIONAL/deferred with SAC (§4.2; serving contract tracked as PR #117).
- **`GET /api/baselines`** on mount + silent static fallback on failure (`baselines-load-error`,
  role=status, non-blocking).
- Store slimmed: `stageState`, `algorithmType`, `selectedBaselines`, `baselinesLoading`,
  `baselinesError`; actions `loadBaselines`/`confirm`/`lockStage`/`unlockStage`/`onRehydrate`/`reset`.
  `isConfirmEnabled = selectedBaselines.length >= 1`.

**This legitimately dissolves C1/C2/C3:** no POST body → no field-name conformance issue (C1);
gamma is a display-only LOCKED constant shown read-only (C2); nEnvs has no editable input — the cap
becomes a standing condition for the SAC-deferred sprint (C3). Authorization: rl-architect ruling on
own authority (a scope deferral, not a spec/irreversible change) — acceptable; **recommend a LINEAGE
entry** recording the SAC-deferral decision (process note, non-blocking).

**Reviewer-test handling under the scope change:** my Round-3 §T15 cases that referenced the now-removed
`getHyperparamErrors`/POST were correctly dropped (they would not compile), and the engineer **preserved
the still-applicable ones** under the new scope, marked `reviewer:`: T-CONFIRM-4 + T-A11Y-7
(aria-disabled click interception, TQ9), T-CONFIRM-5 (double-submit idempotent, TQ10), T-PERSIST-3 (real
`onRehydrate`, TQ13), T-LOCK-PROP-4 (false→true→false flip, TQ15). Process note: test-file edits should
be coordinated with the reviewer (test-file owner), but here the outcome is correct — moot cases removed,
applicable concerns retained — so accepted.

**New suite coverage verified (code-read):** LOCKED incl. no-fetch-when-locked (T-LOCK-5) + unlock→load
(T-LOCK-6); baseline_only default + Option-B SAC future-badge (T-INIT-1/5); SAC stub coming-soon +
**read-only constants preview with no inputs** (T-ALGO-1/2) + **gamma=0.999 displayed** (T-ALGO-3); no
POST on any action (T-INIT-8/T-ALGO-8/T-CONFIRM-1/2); `GET /api/baselines` mount/success/fallback/
load-error/non-blocking/selection-preserved (T-BASE-FETCH-1..7); baseline ≥1 + none-error role=alert
(T-BASE-3/4); confirm local-only → COMPLETE + onContinue (T-CONFIRM-1..3); STALE on algo/baseline change
(T-ALGO-6/T-BASE-7/T-STALE-1..3); persistence + real rehydrate (T-PERSIST-1..5); a11y (T-A11Y-1..8).

**Reviewer additions (pushed this round, §T12, marked `reviewer:`):**
- **T-ALGO-9** — pins the read-only §5 constants preview values: `lr` shows 1e-4 (and NOT the superseded
  UX placeholder 3e-4), `batch_size` 512, `total_env_steps` 500_000. The preview is now the stage's main
  data-display surface; T-ALGO-3 only pinned gamma. A wrong displayed constant is a prime-directive bug.
- **T-BASE-FETCH-8** — a server `/api/baselines` payload is actually consumed (distinguishing label
  reaches the DOM), guarding against an impl that ignores the fetch and always renders the static list
  (T-BASE-FETCH-2/3 can't catch that since their mock == the static fallback).

esbuild parse-check clean; suite remains red-first (no `src/`), as expected at this gate.

**Approved suite = developer cases (§T1–§T11) + the 2 reviewer cases in §T12 (T-ALGO-9, T-BASE-FETCH-8),
plus the retained `reviewer:`-marked cases (T-CONFIRM-4/5, T-A11Y-7, T-PERSIST-3, T-LOCK-PROP-4).**

**Standing conditions for implementation:** SC1/SC2 from Round 3 are **superseded/dissolved for v1**
(no POST, no nEnvs input). Carried forward only: when SAC un-defers, the POST + `training_config.md`
serving contract (PR #117) + the nEnvs cap re-enter through a future contract round. No standing
condition blocks the v1 implementation.

**Verdict: APPROVE** (contract + tests gate, v1 scope). Clean re-gate of the simplified scope;
data-display correctness pinned; no blockers. Implementation of the v1 stub may proceed.

## Round 5 — `ed418c7` — APPROVE (2026-06-14) — IMPLEMENTATION audit

Audited the v1 implementation (`src/stores/stageAlgorithmStore.ts` + `src/components/wizard/
StageTwoAlgorithm.tsx`; +508 lines). The impl commit added **only** the two `src/` files — the
approved test file is **untouched** (`git diff cccfe55..ed418c7 -- tests/` empty → no approved test
weakened to pass). **Full suite 66/66 green** against the impl (incl. my §T12 + retained reviewer cases).

**Data path / display correctness (prime directive) — code-verified, not claim-verified:**
- **§5 constants preview values are CORRECT** — `SAC_CONSTANTS` displays the canonical RunConfig
  (`training_pipeline.md §3`) values exactly: lr=1e-4, gamma=0.999 (marked LOCKED), batch_size=512,
  total_env_steps=500,000, buffer_size=1,000,000, n_envs=4, hidden_sizes=[256,256], tau=0.005,
  ent_coef="auto". This is v1's main data-display surface; T-ALGO-3/9 pin gamma/lr/batch/steps and the
  remaining values are correct on inspection. No wrong/placeholder values (no 3e-4, no batch 256).
- **No POST anywhere (DV-6)** — the only network call is `GET /api/baselines` in the store's
  `loadBaselines`; the component issues no fetch. `confirm()` is local (`stageState→COMPLETE`).
- **Single store source, no derived drift** — component reads state via hooks; `enabled` is re-derived
  from the reactive `selectedBaselines` via the shared `isConfirmEnabled` (no duplicated state).
- **No rogue sockets / duplicated parsing** — all I/O is the one GET in the store.

**Behavior conformance:**
- `confirm()` + `onContinue` fire **exactly once** — `handleConfirm` guards `!enabled` (aria-disabled
  interception, T-CONFIRM-4/T-A11Y-7) AND `stageState==='COMPLETE'` (double-submit, T-CONFIRM-5), and
  the store `confirm()` re-guards both. STALE→COMPLETE re-confirm path works (T-STALE-3).
- Class A STALE rule (`_editStateTransition`): COMPLETE/STALE→STALE, PENDING→IN_PROGRESS, applied on
  `setAlgorithmType`/`toggleBaseline` (§5.8) ✓.
- `loadBaselines`: GET success → `availableBaselines` only (no `selectedBaselines` reset, T-BASE-FETCH-7);
  failure → static fallback + `baselinesError` ✓. Server payload is rendered (`availableBaselines.map`
  → server labels, T-BASE-FETCH-8) ✓.
- LOCKED gate: `!stageOneComplete` returns a view with **no** `stage-two-content` (content absent from
  DOM, T-LOCK-1/2/A11Y-6); `loadBaselines` fires only on the unlock transition (no fetch when locked,
  T-LOCK-5/6) ✓.
- `onRehydrate` COMPLETE→IN_PROGRESS, transient flags reset, persisted fields survive; wired into
  `onRehydrateStorage` + exposed for T-PERSIST-3 ✓. `partialize` persists only
  stageState/algorithmType/selectedBaselines ✓.
- a11y: radiogroup/radio, role=group baselines, role=status load-error, role=alert none-error,
  `aria-disabled` (not HTML disabled), back-as-`<span>` (DV-1) ✓. Zero hex literals (§7 hard rule met).

### Should-fix (non-blocking — visual polish; no test covers it; data/behavior unaffected)
- **Option B visual treatment is only partially implemented.** §5.2 specifies token-based card styling
  (Baseline-only `TOKEN.accentBlue` accent; SAC greyed `TOKEN.border`) and §7 requires design tokens for
  visual values. The impl applies only `opacity:0.75` on the SAC card + the "Future" badge — no
  `TOKEN.*` usage, no accent/greyed borders, minimal card styling. Functionally correct (selection +
  badge + which-is-primary all work; all tests pass) but the visual spec isn't met. Recommend a
  token-styling polish pass before the stage is considered visually done. (Consistent with how #102's
  S3/S4 cosmetic gaps were handled — noted, not gated.)

### Minor nits (non-blocking)
- `baseline.id as "do_nothing"|...` cast on server ids is unsafe if the server ever returns an
  out-of-enum id (v1 server returns the 3 known ids; harmless now — consider a runtime filter when SAC/
  dynamic baselines land).
- `baseline-none-error` (role=alert) and `confirm-disabled-reason` both render when no baseline is
  selected — redundant but both are contracted and harmless.
- `act()` warnings in test stderr are cosmetic (async `loadBaselines` store updates in sync tests);
  66/66 still pass. Optional: wrap the unlock effect's async update to silence them.

**Verdict: APPROVE** (implementation). Data-display correctness verified, all 66 approved tests pass,
no approved test weakened, no POST/rogue I/O, behavior matches the contract. The only gap is an
untested cosmetic Option-B token-styling polish (should-fix follow-up). Ready for QA on `ed418c7`.

### Round 5 addendum — `1c0ef6d` — APPROVE holds (Option-B should-fix resolved)
frontend-engineer applied the §5.2/§7 token-styling should-fix (`1c0ef6d`, on top of the Round-5
record commit). Diff `56e9e45..1c0ef6d` touches **only** `StageTwoAlgorithm.tsx` (+44; no tests, no
store): Baseline-only card border = `TOKEN.accentBlue` when selected / `TOKEN.borderDefault` otherwise;
SAC card border always `TOKEN.borderDefault` (greyed) + opacity 0.8; Future badge `TOKEN.textFaint` +
`TOKEN.accentGrey`; cards on `TOKEN.bgSurface`. All seven TOKEN keys verified present in
`tokenValues.ts`; **zero hex literals (§7 ✓)**; pure-presentational (no data/behavior change). Suite
**66/66 green** on `1c0ef6d`. The should-fix is resolved — Option-B visual treatment now matches §5.2.
**Implementation APPROVE stands, now covering `1c0ef6d`** (the final head for QA).
