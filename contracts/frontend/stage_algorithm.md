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

Stage ② is where the operator selects a training algorithm and chooses which baseline policies to evaluate.

**v1 scope (rl-architect ruling 2026-06-14):** SAC RL training is deferred to a later release. v1 ships two things:

1. **Baseline selector** — operator picks which baseline agents to evaluate (`do_nothing`, `peak_shave`, `import_minimiser`). The list is fetched from `GET /api/baselines` on mount (static fallback on failure). The selection is carried as **wizard state** into stage-③/④ via the Zustand store; there is no config POST in v1.
2. **SAC stub card** — present in the UI as a secondary, de-emphasized "future capability" entry (Option B — USER decision 2026-06-14). Non-submitting; selecting it records `algorithmType = 'sac'` in the store but has no POST effect. The SAC card carries an explicit coming-soon notice and displays the §5 locked constants as a read-only preview (no editable form).

`POST /api/training/config` is PROVISIONAL/deferred — it ships when SAC un-defers (see §8 DV-8). This resolves all cross-area blockers for v1 (C1 dissolves — no POST body to reconcile; C2 dissolves — gamma is a display constant only; C3 is a standing condition for the SAC-deferred sprint).

**What this contract specifies:**
- `StageTwoAlgorithm` root component and all sub-components
- `useStageAlgorithmStore` Zustand persist store
- `GET /api/baselines` fetch on mount + static fallback
- All state-machine transitions, validation rules, and LOCKED-state DOM behavior

**Out of scope (v1):**
- `POST /api/training/config` — deferred with SAC (§8 DV-8)
- Editable SAC hyperparameters — deferred with SAC
- Stage ③ Train, Stage ④ Eval, Stage ⑤ Finance
- WizardBar (separate shared component)

---

## 2. Stage ② state machine

```
LOCKED      → Stage ① Config is not COMPLETE; this stage is inaccessible
PENDING     → Stage ① is COMPLETE; Stage ② has never been visited
IN_PROGRESS → user has visited and is editing; no Confirm yet this session
COMPLETE    → Confirm pressed with valid selection; wizard state persisted locally
STALE       → was COMPLETE; user returned and changed algorithm or baselines
```

**Transitions:**
- Any field edit while COMPLETE → STALE (Class A rule — D32 §c; no modal, no cascade to ④⑤)
- Confirm pressed (valid) → COMPLETE (local state only — no network call in v1)
- Stage ① becomes non-COMPLETE → LOCKED (guard on mount; `stageOneComplete` prop)

**WizardBar badge per state:**

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

Default on first visit: `'baseline_only'` (**CALL 2** — heuristic-first v1; rl-architect authority 2026-06-14).

In v1, selecting `'sac'` records the type in the store for informational carry-forward to stage-③/④. It has no POST effect.

### 3.2 SAC §5 locked constants (read-only display, not form fields)

If the SAC stub displays locked values, they are sourced from §5 constants — shown as a read-only preview panel, not an editable form:

| Param | Value | Source |
|---|---|---|
| `lr` | `1e-4` | §5 |
| `gamma` | `0.999` | §5 — LOCKED (`training_pipeline.md §3.1`) |
| `batch_size` | `512` | §5 |
| `buffer_size` | `1_000_000` | §5 |
| `tau` | `0.005` | §5 |
| `ent_coef` | `"auto"` | §5 |
| `total_env_steps` | `500_000` | §5 |
| `n_envs` | `4` | §5 / CALL 1 |
| `hidden_sizes` | `[256, 256]` | §5 |

No input elements, no validation, no user changes. Displayed purely to preview what SAC will use when it ships.

### 3.3 Baseline IDs

```typescript
type BaselineId = 'do_nothing' | 'peak_shave' | 'import_minimiser';
```

v1 static list (also returned by `GET /api/baselines`):

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
  algorithmType:      AlgorithmType;     // carried forward to stage-③/④
  selectedBaselines:  BaselineId[];
  baselinesLoading:   boolean;           // GET /api/baselines in flight
  baselinesError:     string | null;     // null when static fallback in use
}
```

### 3.5 Store actions

```typescript
interface StageTwoStoreActions {
  setAlgorithmType(type: AlgorithmType): void;
  toggleBaseline(id: BaselineId): void;
  setAllBaselines(ids: BaselineId[]): void;
  loadBaselines(): Promise<void>;        // fires GET /api/baselines; populates or falls back
  confirm(): void;                       // sets stageState → COMPLETE (local; no POST)
  lockStage(): void;                     // called when Stage ① is no longer COMPLETE
  unlockStage(): void;                   // called when Stage ① becomes COMPLETE again
  reset(): void;
  onRehydrate(state: StageTwoStoreState): void;  // Zustand onRehydrateStorage hook
}
```

### 3.6 Confirm button enabled predicate

```typescript
function isConfirmEnabled(state: StageTwoStoreState): boolean {
  return state.selectedBaselines.length >= 1;
}
```

No hyperparam validation (no editable hyperparams in v1). No network-in-progress guard (no POST).

---

## 4. API

### 4.1 `GET /api/baselines` (read on mount)

**Purpose:** Fetch the list of available baseline agents. On failure, fall back to the v1 static list (`['do_nothing', 'peak_shave', 'import_minimiser']`) silently.

**Response 200:**
```json
[
  { "id": "do_nothing",       "label": "Do-nothing",       "description": "Grid import fills all load; battery idle" },
  { "id": "peak_shave",       "label": "Peak-shave",       "description": "Discharge battery during tariff peak hours" },
  { "id": "import_minimiser", "label": "Import minimiser", "description": "Greedy rule: charge when PV > load, else dispatch" }
]
```

**Failure handling:**
- Network error or non-200: set `baselinesError` to the error message, use static fallback list; `baselinesLoading = false`.
- `data-testid="baselines-load-error"` rendered when `baselinesError` is non-null (informational — does not block confirm).
- The selected checkboxes from `selectedBaselines` are preserved across the load (no reset).

### 4.2 `POST /api/training/config` — PROVISIONAL / DEFERRED

This endpoint ships when SAC un-defers. See §8 DV-8. **Not implemented in v1.** Body shape and serving contract (`contracts/serving/training_config.md`) will be defined at that time, using RunConfig canonical field names (`total_env_steps`, `eval_every_steps`, `lr`, `hidden_sizes`, etc. from `training_pipeline.md §3`).

---

## 5. Component interfaces

### 5.1 Root — `StageTwoAlgorithm`

```typescript
interface StageTwoAlgorithmProps {
  stageOneComplete: boolean;   // from wizard shell; if false → LOCKED
  onBack:     () => void;      // navigate to Stage ①
  onContinue: () => void;      // navigate to Stage ③ (called after Confirm)
}
```

**DOM structure and test IDs:**

```
<div data-testid="stage-two-algorithm">
  <div data-testid="stage-two-locked">            ← only in LOCKED state (§5.5)
  <div data-testid="stage-two-content">           ← only when NOT LOCKED
    <section data-testid="algorithm-section">
      data-testid="algo-card-baseline-only"        ← visual PRIMARY (selected by default)
      data-testid="algo-card-sac"                  ← secondary stub (Option B)
        data-testid="algo-card-sac-future-badge"   ← "Future" / "Coming soon" badge
        data-testid="algo-sac-coming-soon-notice"  ← shown when SAC selected
        data-testid="algo-sac-constants-preview"   ← read-only §5 values (when SAC selected)
      data-testid="algo-baseline-notice"           ← shown when baseline_only selected
    </section>
    <section data-testid="baselines-section">
      data-testid="baselines-load-error"           ← when GET /api/baselines failed (optional)
    </section>
  </div>
  <footer data-testid="stage-two-footer">
    <span data-testid="stage-two-back">            ← <span>, NOT <button> (DV-1)
    <button data-testid="stage-two-confirm">       ← Confirm & Continue →
      data-testid="confirm-disabled-reason"        ← visually hidden; shown on hover
  </footer>
</div>
```

### 5.2 `AlgorithmCard`

```typescript
interface AlgorithmCardProps {
  id:        'sac' | 'baseline_only';
  selected:  boolean;
  onSelect:  (id: AlgorithmType) => void;
  disabled?: boolean;
}
```

**Accessibility:** `role="radio"` + `aria-checked={selected}`. Wrapper: `role="radiogroup"` + `aria-label="Training algorithm"`.

**Option B visual treatment (USER decision 2026-06-14):**
- **Baseline-only** card: visually PRIMARY — blue accent border (`TOKEN.accentBlue`), full-size, default-selected.
- **SAC** card: visually SECONDARY — greyed border (`TOKEN.border`), smaller weight, "Future" badge (`data-testid="algo-card-sac-future-badge"`).
- Selecting SAC: renders `data-testid="algo-sac-coming-soon-notice"` (coming-soon copy) + `data-testid="algo-sac-constants-preview"` (read-only §5 values — no inputs).
- Selecting baseline_only: renders `data-testid="algo-baseline-notice"`. Visible on initial render (default is baseline_only).

### 5.3 `BaselineSelector`

```typescript
interface BaselineSelectorProps {
  baselines: Array<{ id: BaselineId; label: string; description: string }>;
  selected:  BaselineId[];
  onChange:  (id: BaselineId) => void;
  loading:   boolean;
  error:     string | null;
}
```

**Accessibility:** `role="group"` + `aria-label="Baseline agents"`.

**Test IDs:**
- `data-testid="baseline-{id}"` on each checkbox wrapper
- `data-testid="baseline-checkbox-{id}"` on `<input type="checkbox">`
- `data-testid="baseline-none-error"` when `selected.length === 0` (role="alert")
- `data-testid="baselines-load-error"` when `error` is non-null (role="status")

### 5.4 LOCKED state DOM

When `stageOneComplete === false`:
- `data-testid="stage-two-locked"` rendered; `data-testid="stage-two-content"` **absent from DOM**.
- `data-testid="stage-two-locked-go-config"` — `[← Go to Config]` link (calls `onBack`).
- All form elements absent from DOM entirely (screen readers must not announce them).

### 5.5 Confirm button states

| Condition | `aria-disabled` | Label |
|---|---|---|
| No baselines selected | `"true"` | `Confirm & Continue →` |
| Valid (≥ 1 baseline) | `"false"` | `Confirm & Continue →` |

Button uses `aria-disabled` (NOT HTML `disabled`) — matching the StageSaveButton pattern from stage_config (PR #98). When `aria-disabled="true"`, click events are intercepted and not forwarded to the confirm handler.

Disabled tooltip text (`data-testid="confirm-disabled-reason"`): visually hidden span, shown on hover:
- `"Select at least one baseline"` — when `selectedBaselines.length === 0`

### 5.6 localStorage / persistence

**Key:** `"energygo.stage2"`

**Persisted fields:**
```
stageState, algorithmType, selectedBaselines
```

**NOT persisted** (transient):
```
baselinesLoading, baselinesError
```

**Rehydration rule:** if persisted `stageState` is `'COMPLETE'`, immediately downgrade to `'IN_PROGRESS'` via `onRehydrateStorage`. Forces a re-confirm on page reload.

---

## 6. Behavioral specification

### 6.1 On mount

1. If `!stageOneComplete`: render LOCKED; do not fire `loadBaselines()`.
2. If stageOneComplete and state is PENDING: set to IN_PROGRESS; fire `loadBaselines()`.
3. If stageOneComplete and state is IN_PROGRESS/COMPLETE/STALE: fire `loadBaselines()` (refresh list).
4. If LOCKED: render `stage-two-locked` only.

### 6.2 Algorithm card selection

Clicking `AlgorithmCard` (SAC or Baseline-only):
1. Store: `setAlgorithmType(id)` → if COMPLETE was true, transitions to STALE.
2. `baseline_only` selected: `algo-baseline-notice` shown; SAC stub sections hidden.
3. `sac` selected: `algo-sac-coming-soon-notice` and `algo-sac-constants-preview` shown (read-only); baseline-notice hidden.

### 6.3 Baseline toggle

Clicking a baseline checkbox:
1. Store: `toggleBaseline(id)`.
2. If COMPLETE: transitions to STALE.
3. If `selectedBaselines` becomes empty: `baseline-none-error` shown.

### 6.4 Confirm & Continue

When `aria-disabled="false"` and button is clicked:
1. Store: `confirm()` → `stageState = 'COMPLETE'`.
2. `onContinue()` called immediately.
3. No network call. No loading state. No error state.

When `aria-disabled="true"`: click event is intercepted; confirm handler is NOT called.

### 6.5 Back button

`data-testid="stage-two-back"` is a `<span>` (NOT `<button>`), always enabled, calls `onBack()`. Store state preserved.

### 6.6 Class A edit rule (D32 §c)

Changing `algorithmType` or `selectedBaselines` while `stageState === 'COMPLETE'`:
- Stage ② → STALE immediately.
- No modal. No cascade to ④⑤.

---

## 7. Accessibility

- Algorithm cards: `role="radio"` + `aria-checked="true|false"`; wrapper: `role="radiogroup"` + `aria-label="Training algorithm"`. Keyboard: Space to select.
- Baselines: `role="group"` + `aria-label="Baseline agents"`; standard checkboxes.
- Error messages: `role="alert"` on `baseline-none-error`; `role="status"` on `baselines-load-error`.
- LOCKED state: all form elements absent from DOM — screen readers must not announce them.
- Confirm uses `aria-disabled`; click interception when disabled.

---

## 8. Design tokens

All visual values use tokens from `contracts/frontend/design_system.md` (PR #98, `src/styles/tokenValues.ts`):
- Selected card border (baseline-only): `TOKEN.accentBlue` (`#60a5fa`)
- Unselected / SAC card border: `TOKEN.border` (`#2d3748`)
- Error text: `TOKEN.accentRed` (`#f87171`)
- STALE/warning: `TOKEN.accentAmber` (`#f59e0b`)
- Card background: `TOKEN.bgSurface` (`#1e2533`)

---

## 9. Deliberate deviations

| # | Deviation | Reason |
|---|---|---|
| DV-1 | Back button is `<span>`, not `<button>` | Consistent with stage-1 (T-A11Y-6 pattern; PR #102) |
| DV-2 | Confirm button uses `aria-disabled`, not HTML `disabled` | Same pattern as `StageSaveButton` (stage-1 contract); keeps button focusable for tooltip/screen reader |
| DV-3 | ~~Hyperparam defaults differ from REBUILD_SPEC §5~~ | **RESOLVED** (CALL 1 — rl-architect 2026-06-14). Moot in v1 (no editable hyperparams). |
| DV-4 | SAC hyperparameters shown as read-only constants, not a form | SAC RL training deferred (CALL 2 + rl-architect scope ruling 2026-06-14). Editable form ships when SAC un-defers. |
| DV-5 | COMPLETE → IN_PROGRESS on rehydrate | Forces re-confirm on page reload to guard against stale selection |
| DV-6 | No `POST /api/training/config` in v1 | **PROVISIONAL/DEFERRED** (rl-architect ruling 2026-06-14 — C1/C2/C3 dissolve with SAC deferral). POST ships with the SAC-undefer sprint. Field names will use RunConfig canonical names (`total_env_steps`, `eval_every_steps`, `lr`, `hidden_sizes`) per `training_pipeline.md §3`. |
| DV-7 | Default algorithm = `baseline_only` | **CALL 2** (rl-architect 2026-06-14). SAC-default would route into non-functional Stage ③. |
| DV-8 | SAC card is non-submitting "coming soon" stub | Option B (USER decision 2026-06-14). SAC is secondary/de-emphasized; no hyperparam form; selecting SAC records algorithmType for carry-forward only. |

---

## 10. Open questions

All previously open questions resolved or deferred:
- **Q1 (SAC visual prominence):** RESOLVED — Option B (USER decision 2026-06-14): baseline-only is visual primary; SAC is secondary/de-emphasized (§5.2, DV-8).
- **Q2 (nEnvs UI cap):** DEFERRED with SAC. Will be resolved in the SAC-undefer sprint before implementing the hyperparam form.
- **Q3 (POST /api/training/config serving contract):** DEFERRED with SAC (DV-6). `contracts/serving/training_config.md` ships in the SAC-undefer sprint.

---

*contracts/frontend/stage_algorithm.md — frontend-engineer, feat/frontend-stage-algorithm*
*Round 1 (2026-06-14): CALL 1 (§5 defaults); CALL 2 (baseline_only default + SAC coming-soon). rl-architect authority.*
*Round 2 (2026-06-14): C1 (RunConfig field names); C2 (gamma LOCKED constant); C3 (nEnvs cap removed); §3.7 TQ12; Option B visual. frontend-reviewer REQUEST_CHANGES.*
*Round 3 (2026-06-14): rl-architect scope ruling — SAC deferred; POST deferred; editable hyperparams deferred. v1 = baseline selector + SAC stub only. C1/C2/C3 dissolved.*
