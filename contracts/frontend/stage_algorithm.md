# Contract: `stage_algorithm` — Wizard Stage ② Algorithm Selection

**Area:** `frontend`
**Feature file:** `contracts/frontend/stage_algorithm.md`
**Branch:** `feat/frontend-stage-algorithm`
**REBUILD_SPEC sections:** §5 (training methodology), §10 (env enhancements)
**UX reference:** `docs/design/ux/stage_2_algorithm.md` v0.1 (2026-06-12), `docs/design/ux/wizard_flow.md` v0.6
**LINEAGE decisions:** D32 §(a)/(c) (algorithm registry; five-stage spine), D31 §(c) (foundation-first sequencing)
**Reviewer routing:** `contracts/frontend/` → **frontend-reviewer**
**Status:** DRAFT — awaiting frontend-reviewer APPROVE

---

## 1. Purpose

Stage ② is where the operator selects a training algorithm (`SAC` or `Baseline only`) and configures its hyperparameters and baseline policy inclusion. Once confirmed the configuration is persisted to `POST /api/training/config`; the stage transitions to COMPLETE and the operator advances to Stage ③ (Train).

Stage ② is intentionally short: one algorithm card pick, one (optionally expanded) hyperparam form, one baseline checklist.

**What this contract specifies:**
- `StageTwoAlgorithm` root component and all sub-components
- `useStageAlgorithmStore` Zustand persist store
- `POST /api/training/config` request/response shape (frontend perspective; serving-engineer implements the endpoint)
- All state-machine transitions, validation rules, and LOCKED-state DOM behavior

**Out of scope:**
- Stage ③ Train, Stage ④ Eval, Stage ⑤ Finance
- WizardBar (a separate shared component, contracted elsewhere)
- `GET /api/baselines` implementation (serving-engineer; frontend uses mock in tests)
- τ and hidden-layer dimensions are not surfaced in the v1 form (sent as constants); a future v1.1 contract may expose them

---

## 2. Stage ② state machine

```
LOCKED      → Stage ① Config is not COMPLETE; this stage is inaccessible
PENDING     → Stage ① is COMPLETE; Stage ② has never been visited
IN_PROGRESS → user has visited and is editing; no successful POST yet
COMPLETE    → POST /api/training/config succeeded; choice is persisted
STALE       → was COMPLETE; user returned and changed algorithm or hyperparams
```

**Transitions:**
- Any field edit while COMPLETE → STALE (Class A rule — D32 §c; no modal, no cascade to ④⑤)
- Successful POST response → COMPLETE
- Stage ① becomes non-COMPLETE → LOCKED (guard check on mount)

**WizardBar badge per state** (from UX doc §2):

| State | Badge |
|---|---|
| LOCKED | 🔒 padlock icon; step not clickable |
| PENDING | ○ empty circle |
| IN_PROGRESS | ● filled dot |
| COMPLETE | ✓ green check |
| STALE | ● amber dot |

---

## 3. Data schemas

### 3.1 Algorithm type

```typescript
type AlgorithmType = 'sac' | 'baseline_only';
```

Default on first visit: `'baseline_only'` (**CALL 2** — heuristic-first v1; rl-architect authority 2026-06-14; see §8).

### 3.2 SAC hyperparameters

```typescript
interface SacHyperparams {
  totalSteps:   number;   // Total env steps.   Default: 500_000.    Valid: ≥ 100_000
  evalFreq:     number;   // Eval every N steps. Default: 10_000.    Valid: ≥ 1_000
  batchSize:    number;   // Samples per update. Default: 512.        Valid: power of 2, 32–4096
  learningRate: number;   // Adam LR.            Default: 1e-4.       Valid: 1e-5 ≤ lr ≤ 1e-2
  bufferSize:   number;   // Replay buffer cap.  Default: 1_000_000.  Valid: ≥ batchSize × 4
  nEnvs:        number;   // Vmapped env count.  Default: 4.          Valid: power of 2, ≥ 1
}
```

**`gamma` is NOT user-editable.** It is a LOCKED constant (training_pipeline.md §3.1): "gamma MUST be 0.999. Any PR that lowers it requires a new rl-architect DECISION (demand charge is a monthly signal; §5 'Why γ=0.999')." Sent in the POST body as a constant; no form field rendered.

Constants sent to API (not surfaced in v1 UI):
- `gamma`: 0.999 (**LOCKED** — training_pipeline.md §3.1; cannot be user-edited without rl-architect DECISION)
- `tau`: 0.005 (§5 τ — target network soft-update)
- `ent_coef`: `"auto"` (§5 — entropy coefficient; auto-tuned during training)
- `train_freq`: 1 (§5 — env steps between gradient updates)
- `gradient_steps`: 1 (§5 — gradient steps per env step)
- `hidden_sizes`: [256, 256] (actor/critic MLP dims; RunConfig field name `hidden_sizes`)

**Cross-field rules:**
- `bufferSize >= batchSize * 4` (hard constraint; error blocks Continue)
- `batchSize` must be a power of 2
- `nEnvs` must be a power of 2

**nEnvs cap:** RunConfig (training_pipeline.md §3) defines `n_envs` as "MUST be a power of 2 ≥ 1; implementations MAY reduce for CPU-only runs." No explicit maximum is stated (canonical JAX vmap target is 4096). The UI shows a default of 4 (DummyVecEnv — CALL 1) and validates power-of-2 ≥ 1 only; an explicit upper bound is pending training-engineer confirmation and will be locked before implementation.

**Defaults (CALL 1 — resolved 2026-06-14; rl-architect authority):** REBUILD_SPEC §5 is canonical. UX-design placeholders (`lr=3e-4`, `γ=0.99`, `batch=256`, `2M steps`, `16 envs` from stage_2_algorithm.md) are superseded. `evalFreq` default: 10 000 (matches RunConfig `eval_every_steps` in training_pipeline.md §3).

### 3.3 Baseline IDs

```typescript
type BaselineId = 'do_nothing' | 'peak_shave' | 'import_minimiser';
```

The v1 static list (from `GET /api/baselines`):

| ID | Label | Description |
|---|---|---|
| `'do_nothing'` | Do-nothing | Grid import fills all load; battery idle |
| `'peak_shave'` | Peak-shave | Discharge battery during tariff peak hours |
| `'import_minimiser'` | Import minimiser | Greedy rule: charge when PV > load, else dispatch |

Default selected: `['do_nothing', 'peak_shave']`.

### 3.4 Store state

```typescript
type StageTwoState = 'LOCKED' | 'PENDING' | 'IN_PROGRESS' | 'COMPLETE' | 'STALE';

interface StageTwoStoreState {
  stageState:         StageTwoState;
  algorithmType:      AlgorithmType;
  hyperparams:        SacHyperparams;
  hyperparmExpanded:  boolean;         // true when the form is expanded
  selectedBaselines:  BaselineId[];
  saveInProgress:     boolean;
  saveError:          string | null;
  configId:           string | null;   // set on successful POST
  configHash:         string | null;   // set on successful POST
  provenanceHash:     string | null;   // same as configHash for cross-stage linkage
}
```

### 3.5 Store actions

```typescript
interface StageTwoStoreActions {
  setAlgorithmType(type: AlgorithmType): void;
  setHyperparam<K extends keyof SacHyperparams>(key: K, value: SacHyperparams[K]): void;
  resetHyperparams(): void;
  setHyperparamExpanded(expanded: boolean): void;
  toggleBaseline(id: BaselineId): void;
  setAllBaselines(ids: BaselineId[]): void;
  setSaveInProgress(v: boolean): void;
  setSaveError(msg: string | null): void;
  onSaveSuccess(configId: string, configHash: string): void;
  lockStage(): void;     // called when Stage ① is no longer COMPLETE
  unlockStage(): void;   // called when Stage ① becomes COMPLETE again
  reset(): void;
}
```

### 3.6 Validation error shape

```typescript
interface HyperparamError {
  field: keyof SacHyperparams;
  message: string;   // human-readable, e.g. "3 exceeds max 1e-2"
  type: 'error';     // all hyperparam range failures are hard errors (block Continue)
}
```

Computed from store state (not persisted). The `getHyperparamErrors(hyperparams: SacHyperparams): HyperparamError[]` pure function is exported from the store module.

### 3.7 Confirm button enabled predicate

```typescript
function isConfirmEnabled(state: StageTwoStoreState): boolean {
  // Hyperparam errors only block confirm in SAC mode — hyperparams are not
  // sent in baseline_only POST bodies. A user who set invalid params in SAC mode
  // then switched to baseline_only must still be able to confirm.
  const hyperparamsOk =
    state.algorithmType !== 'sac' ||
    getHyperparamErrors(state.hyperparams).length === 0;

  return (
    state.selectedBaselines.length >= 1 &&
    hyperparamsOk &&
    !state.saveInProgress
  );
}
```

Note: `algorithmType` is always set (`baseline_only` is the default), so no "no algorithm selected" case.

### 3.8 POST /api/training/config — request

**Field names match `RunConfig` in `training_pipeline.md §3` exactly (C1 fix — frontend-reviewer Round 1).**

> **Serving contract dependency:** `POST /api/training/config` does not yet have a serving-side contract (serving-engineer). Per D37 + D32(b), wizard→canonical-config assembly is single server-side. A `contracts/serving/training_config.md` (the stage-② analog of `site_assemble.md`) is required before implementation — it will document the server-side assembly, validation, and response. The field names below are determined by `RunConfig` (training_pipeline.md §3) regardless.

```typescript
// POST /api/training/config
// Body field names must match RunConfig (training_pipeline.md §3) exactly.
interface TrainingConfigRequest {
  algorithm_type: 'sac' | 'baseline_only';
  // Present when algorithm_type === 'sac'; absent (field omitted) when baseline_only
  sac_hyperparams?: {
    // User-editable (6 fields):
    total_env_steps:  number;   // RunConfig: total_env_steps
    eval_every_steps: number;   // RunConfig: eval_every_steps
    batch_size:       number;   // RunConfig: batch_size
    lr:               number;   // RunConfig: lr
    buffer_size:      number;   // RunConfig: buffer_size
    n_envs:           number;   // RunConfig: n_envs
    // Constants (not user-editable — sent as fixed values; see §3.2):
    gamma:            number;   // constant: 0.999  (LOCKED — training_pipeline.md §3.1)
    tau:              number;   // constant: 0.005   (§5)
    ent_coef:         string;   // constant: "auto"  (§5)
    train_freq:       number;   // constant: 1       (§5)
    gradient_steps:   number;   // constant: 1       (§5)
    hidden_sizes:     number[]; // constant: [256, 256] — RunConfig field name
  };
  baselines: BaselineId[];   // ≥ 1 required
}
```

### 3.9 POST /api/training/config — response

```typescript
// 200 OK
interface TrainingConfigResponse {
  config_id:   string;   // server-assigned UUID
  config_hash: string;   // content hash of the full config (for provenance)
}

// 422 Unprocessable Entity
interface TrainingConfigError {
  error:    string;
  field?:   string;
  message?: string;
}
```

---

## 4. Component interfaces

### 4.1 Root — `StageTwoAlgorithm`

```typescript
interface StageTwoAlgorithmProps {
  // Stage ① state injected by the wizard shell; if not COMPLETE, render LOCKED state
  stageOneComplete: boolean;
  // Navigation callbacks (injected by wizard shell / router)
  onBack:     () => void;   // navigate to Stage ①
  onContinue: () => void;   // navigate to Stage ③ (called after successful save)
}
```

**DOM structure and test IDs:**

```
<div data-testid="stage-two-algorithm">
  <div data-testid="stage-two-locked">          ← only in LOCKED state (§4.5)
  <div data-testid="stage-two-content">         ← only when NOT LOCKED
    <section data-testid="algorithm-section">
    <section data-testid="hyperparam-section">  ← absent from DOM when baseline_only
    <section data-testid="baselines-section">
  </div>
  <footer data-testid="stage-two-footer">
    <span data-testid="stage-two-back">         ← <span>, NOT <button> (per T-A11Y-6 precedent)
    <button data-testid="stage-two-confirm">    ← Confirm & Continue →
  </footer>
</div>
```

### 4.2 `AlgorithmCard`

```typescript
interface AlgorithmCardProps {
  id:          'sac' | 'baseline_only';
  selected:    boolean;
  onSelect:    (id: AlgorithmType) => void;
  disabled?:   boolean;
}
```

**Accessibility:** `role="radio"` + `aria-checked={selected}`. Both cards are wrapped in a `role="radiogroup"` with `aria-label="Training algorithm"`.

**Test IDs:** `data-testid="algo-card-sac"`, `data-testid="algo-card-baseline-only"`.

Selected card: `data-testid="algo-card-selected"` also present on the currently selected card.

**SAC card — coming-soon treatment (**CALL 2** — rl-architect authority 2026-06-14):**
> v1 ships heuristic baselines only; RL training (SAC) is deferred to a later release. The SAC card MUST carry an explicit label making this clear — NOT an un-caveated "Recommended" treatment. Exact copy:
> - Card subtitle/badge: `"Coming soon — RL training ships in a later release"`
> - Selecting SAC shows an informational notice: `data-testid="algo-sac-coming-soon-notice"` with text explaining that SAC will be available in a future version; the current run will evaluate baseline agents.
> - SAC is selectable in v1 (for UI testing / forward compatibility) but the coming-soon copy is mandatory.

**Visual prominence — OPTION B APPLIED (USER decision 2026-06-14; relayed via team-lead):**
> - **Baseline-only** is the **clear visual primary**: rendered as the prominently-styled default card (blue accent border, full-size, left/top position, default-selected).
> - **SAC** is a **secondary / de-emphasized "future capability" entry**: smaller, lower visual weight, greyed border (use `TOKEN.border` not `TOKEN.accentBlue`), positioned after/below Baseline-only, labelled `"Future"` or `"Coming soon"` in the card header.
> - The intent: the operator's eye naturally lands on the functional path; SAC sits in the background as an honest future item.
> - `data-testid="algo-card-sac-future-badge"` on the future/coming-soon badge element.

**Baseline-only notice** (`data-testid="algo-baseline-notice"`): rendered below the cards when `baseline_only` is selected. Since `baseline_only` is the v1 functional default, this notice is visible on initial render (no interaction required to trigger it).

### 4.3 `HyperparamForm`

```typescript
interface HyperparamFormProps {
  hyperparams:  SacHyperparams;
  expanded:     boolean;
  errors:       HyperparamError[];
  onChange:     <K extends keyof SacHyperparams>(key: K, value: SacHyperparams[K]) => void;
  onToggle:     () => void;   // toggle expanded/collapsed
  onReset:      () => void;   // reset to defaults
}
```

**Collapsed header** (`data-testid="hyperparam-header"`) shows compact summary; `aria-expanded={expanded}`.

**Expanded form fields**: each field has:
- `data-testid="hyperparam-{fieldName}"` on the `<input>`
- `data-testid="hyperparam-error-{fieldName}"` on the error text (only when error exists); `role="alert"`
- `data-testid="hyperparam-range-{fieldName}"` on the range hint text
- `aria-describedby` linking input to its range-hint span

**Reset button:** `data-testid="hyperparam-reset"`.

When collapsed, all inputs are NOT rendered (absent from DOM, not hidden with CSS); only the header/summary is rendered.

**nEnvs non-power-of-2 hint** (`data-testid="hyperparam-hint-nEnvs"`): shown inline when nEnvs is out of range, suggesting nearest valid power of 2 above and below.

### 4.4 `BaselineSelector`

```typescript
interface BaselineSelectorProps {
  baselines:  Array<{ id: BaselineId; label: string; description: string }>;
  selected:   BaselineId[];
  onChange:   (id: BaselineId) => void;
}
```

**Accessibility:** `role="group"` + `aria-label="Baseline agents"`.

**Test IDs:**
- `data-testid="baseline-{id}"` on each checkbox wrapper div
- `data-testid="baseline-checkbox-{id}"` on the `<input type="checkbox">`
- `data-testid="baseline-none-error"` when `selected.length === 0` (role="alert")

### 4.5 LOCKED state DOM

When `stageOneComplete === false`:
- `data-testid="stage-two-locked"` is rendered; `data-testid="stage-two-content"` is **absent from DOM** (not hidden — a screen reader must not announce form fields).
- `data-testid="stage-two-locked-go-config"` — `[← Go to Config]` link (calls `onBack`).
- Hyperparam form, algorithm cards, baseline checkboxes: **absent from DOM entirely**.

### 4.6 Confirm button states

| Condition | `aria-disabled` | Label |
|---|---|---|
| saveInProgress | not applicable | `Saving… ⟳` |
| validation errors or no baseline | `"true"` | `Confirm & Continue →` |
| valid, not saving | `"false"` | `Confirm & Continue →` |

Button uses `aria-disabled` (NOT HTML `disabled`) — matching the StageSaveButton pattern from stage_config (PR #98). When `aria-disabled="true"`, clicks are intercepted and not forwarded to the save handler.

Disabled tooltip text (`data-testid="confirm-disabled-reason"`): rendered as a visually hidden span with the reason string; shown on hover via CSS (not JS tooltip).

Reasons:
- `"Select at least one baseline"` — when selectedBaselines.length === 0
- `"Fix hyperparameter errors"` — when hyperparamErrors.length > 0
- (both conditions: baseline message takes priority)

### 4.7 localStorage / persistence

**Key:** `"energygo.stage2"`

**Persisted fields** (partialize — excludes transient state):
```
stageState, algorithmType, hyperparams, selectedBaselines, hyperparmExpanded,
configId, configHash, provenanceHash
```

**NOT persisted** (reset to defaults on each app load):
```
saveInProgress, saveError
```

**Rehydration rule (parallel to stage-1 S2 rule):** if persisted `stageState` is `'COMPLETE'`, immediately downgrade to `'IN_PROGRESS'` (same `onRehydrateStorage` pattern as stage-1). Forces a re-confirm on page reload — the persisted config may not match the current Stage ① config.

---

## 5. Behavioral specification

### 5.1 Algorithm card selection

Clicking `AlgorithmCard` (SAC or Baseline-only):
1. Store: `setAlgorithmType(id)` → triggers STALE if COMPLETE was previously true
2. If `baseline_only` selected: `HyperparamForm` section is removed from the DOM
3. If `sac` selected: `HyperparamForm` section is added to the DOM; hyperparam values are unchanged (not reset)
4. `baseline_only` notice (`data-testid="algo-baseline-notice"`) shown when baseline_only is active

### 5.2 Hyperparam field edit

On blur of any `HyperparamForm` input:
1. Parse the entered value to a number
2. If `NaN` or empty: treat as a parse error (invalid); show `"Must be a number"` as the field error
3. Apply range validation immediately
4. Store: `setHyperparam(key, value)` with the raw parsed number
5. If COMPLETE: transitions to STALE

Input `type="text"` (not `type="number"`) to allow scientific notation entry (`3e-4`). Parse with `parseFloat`.

### 5.3 Reset to defaults

Clicking `data-testid="hyperparam-reset"` restores all seven SAC fields to their contract defaults (see §3.2). Does NOT change algorithmType or selectedBaselines. If COMPLETE, transitions to STALE.

### 5.4 Baseline toggle

Clicking a baseline checkbox:
1. If the baseline is currently selected and it's the LAST selected one: deselect, triggering the `baseline-none-error` (baseline-none state blocks Continue but does not revert the click — the user can re-select a different baseline)
2. Store: `toggleBaseline(id)`
3. If COMPLETE: transitions to STALE

### 5.5 Confirm & Continue

When `aria-disabled="false"` and button is clicked:
1. Store: `setSaveInProgress(true)`, `setSaveError(null)`
2. `POST /api/training/config` with body per §3.8
3. On 200: `onSaveSuccess(config_id, config_hash)` → stageState = COMPLETE; `onContinue()` called
4. On non-200: `setSaveError(errorMessage)`, `setSaveInProgress(false)` → `data-testid="confirm-api-error"` rendered with retry semantics (same as ValidationPanel pattern from stage-1)
5. `data-testid="confirm-retry"` when saveError is non-null — clicking re-fires the POST

### 5.6 Back button

`data-testid="stage-two-back"` is a `<span>` (NOT `<button>`), always enabled, calls `onBack()`. State is preserved in the store — returning to Stage ② shows the user's prior selections unchanged.

### 5.7 STALE entry

If the user navigates to Stage ② when `stageState === 'STALE'`: the WizardBar subtitle shows the previously confirmed algorithm name (e.g. `SAC · 2 M steps`). The form shows the current (potentially edited) values, not the last-confirmed values. An amber indicator is expected at the WizardBar layer (out of scope for this component).

### 5.8 Class A edit rule (D32 §c)

Changing `algorithmType` or any `hyperparams` field while `stageState === 'COMPLETE'`:
- Stage ② transitions to STALE immediately
- The wizard shell propagates a "Class A change" signal to Stage ③ (Train) which shows an amber notice: *"Algorithm or hyperparameters changed since the last run. Start a new run to train with the current settings."*
- Stages ④ and ⑤ are NOT affected (decoupled eval model per D32 §g)
- This contract governs Stage ② only; the Stage ③ amber notice is out of scope here (flagged for the stage_three contract)

---

## 6. Accessibility

Per UX design §10 (binding):
- Algorithm cards: `role="radio"` + `aria-checked="true|false"`; wrapper: `role="radiogroup"` + `aria-label="Training algorithm"`. Keyboard: Space to select; Tab/Shift-Tab to navigate.
- Hyperparam inputs: standard `<label>`+`<input>` pairs; range hints via `aria-describedby`.
- Out-of-range errors: `role="alert"` on the inline error span.
- Baselines: `role="group"` + `aria-label="Baseline agents"`; standard checkboxes.
- Collapsed/expanded hyperparams: `aria-expanded` on the header button; section content uses `hidden` when collapsed.

**LOCKED state a11y:** all form elements absent from the DOM — screen readers must not announce them (not just `aria-hidden`).

---

## 7. Design tokens

All visual values must use the tokens from `contracts/frontend/design_system.md` (merged PR #98, `src/styles/tokenValues.ts`). No direct hex literals in component source.

Key token usages for Stage ②:
- Selected card border: `TOKEN.accentBlue` (`#60a5fa`)
- Unselected card border: `TOKEN.border` (`#2d3748`)
- Error text: `TOKEN.accentRed` (`#f87171`)
- STALE/warning: `TOKEN.accentAmber` (`#f59e0b`)
- Card background: `TOKEN.bgSurface` (`#1e2533`)

---

## 8. Deliberate deviations

| # | Deviation | Reason |
|---|---|---|
| DV-1 | Back button is `<span>`, not `<button>` | Consistent with stage-1 (T-A11Y-6 pattern; established PR #102) |
| DV-2 | Confirm button uses `aria-disabled`, not HTML `disabled` | Same pattern as `StageSaveButton` (stage-1 contract); keeps button focusable for tooltip/screen reader |
| ~~DV-3~~ | ~~Hyperparam defaults differ from REBUILD_SPEC §5~~ | **RESOLVED** (CALL 1 — rl-architect authority 2026-06-14): §5 wins; defaults updated in §3.2. evalFreq matches `eval_every_steps` in RunConfig (10_000). |
| DV-4 | γ, τ, ent_coef, train_freq, gradient_steps, hidden_sizes not in v1 UI form | γ=0.999 LOCKED (training_pipeline.md §3.1); others per UX design §5.2. All sent as constants in POST body. Surfacing deferred to v1.1. |
| DV-5 | COMPLETE → IN_PROGRESS on rehydrate | Same as stage-1 S2 rule; forces re-confirm on page reload to guard against stale config_hash |
| DV-6 | Collapsed hyperparam inputs absent from DOM (not hidden) | Prevents tabbing into invisible fields; reduces DOM noise for screen readers |
| DV-7 | Default algorithm = `baseline_only`, not `sac` | **CALL 2** (rl-architect authority 2026-06-14): v1 is heuristic-first; RL training deferred. SAC-default would route into non-functional Stage ③. SAC card carries explicit coming-soon copy. Visual prominence: **Option B applied** (USER decision 2026-06-14): SAC is secondary/de-emphasized; Baseline-only is the clear visual primary (see §4.2). |
| DV-8 | POST body field names = RunConfig canonical names from training_pipeline.md §3 | Fixes C1 (frontend-reviewer Round 1). Serving contract `contracts/serving/training_config.md` required before implementation (analog of `site_assemble.md`). |

---

## 9. Out of scope (v1)

- WizardBar component (separate contract)
- StageShell (separate contract)
- `GET /api/baselines` dynamic fetch (v1: frontend uses static list; `GET /api/baselines` is called for future extensibility; if the call fails, fall back to the static v1 list silently)
- PPO, TD3, or other RL algorithm cards (v1: SAC only)
- Hyperparameter presets ("Fast/balanced/thorough") — see UX Q2
- Compute-duration estimate endpoint — see UX Q3
- Baseline-only flow difference in Stage ③ — see UX Q4
- Training-speed estimate based on GPU count (UX §5.2 note)
- Hidden-layer / τ fields in UI

---

## 12. Open questions

**Q1 — SAC visual prominence: RESOLVED (USER decision 2026-06-14, relayed via team-lead).**
Option B applied. Baseline-only is the clear visual primary; SAC is secondary/de-emphasized "future capability." See §4.2 and DV-7.

**Q2 — nEnvs upper bound:** RunConfig (training_pipeline.md §3) specifies "power of 2 ≥ 1" with no explicit max; canonical JAX vmap target is 4096. Explicit UI cap PENDING training-engineer confirmation. Tracked as C3 (frontend-reviewer Round 1). Resolution required before implementation.

**Q3 — Serving contract for POST /api/training/config:** A `contracts/serving/training_config.md` (the stage-② analog of `site_assemble.md`) is required. Tracked as C1 dependency (frontend-reviewer Round 1). Must be created by serving-engineer and locked before implementation.

---

*contracts/frontend/stage_algorithm.md — frontend-engineer, feat/frontend-stage-algorithm — 2026-06-14*
*Amended 2026-06-14 (Round 1): CALL 1 (§5 defaults win — §3.2 updated); CALL 2 (baseline_only default + SAC coming-soon — §3.1, §4.2, §8 updated). Both rl-architect authority.*
*Amended 2026-06-14 (Round 2): C1 — POST body field names corrected to RunConfig canonical (§3.8); C2 — gamma removed from SacHyperparams, LOCKED constant (§3.2, §3.8); C3 — nEnvs 256 cap removed (§3.2, cap pending training-engineer); §3.7 isConfirmEnabled gates hyperparam errors on algorithmType=sac (TQ12); §4.2 Option B visual treatment applied (USER decision); §8 DV-7/DV-8 updated; §12 Q1 resolved.*
