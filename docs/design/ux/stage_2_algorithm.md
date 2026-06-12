# Stage ② — Algorithm Selection: Per-Screen Layout

> **Owner:** ui-designer · **Task:** #65
> **Status:** DRAFT v0.1 (2026-06-12)
> **Gate:** frontend-reviewer verdict on PR #85 before frontend contract is authored.
> **Parent doc:** wizard_flow.md v0.5 (§5, §10) — this document deepens Stage ② only.
> **Prerequisite:** Stage ① Config must be COMPLETE before Stage ② is accessible.

---

## 1. Purpose and scope

Stage ② is where the operator selects a training algorithm (SAC or a baseline) and configures its hyperparameters. It is intentionally short: the operator makes a deliberate choice and proceeds. The algorithm choice is **Class A** (physical config) — changing it after training creates an amber notice in Stage ③ but does not block or cascade.

This document specifies the complete per-screen layout for Stage ②, including all states, the algorithm and baseline card designs, the hyperparameter form, and the footer.

---

## 2. Stage state machine at Algorithm

```
LOCKED       — Stage ① Config is not yet COMPLETE; this stage cannot be entered
PENDING      — Stage ① is COMPLETE but the user has not visited Stage ② yet
IN_PROGRESS  — user is editing algorithm choice or hyperparameters
COMPLETE     — an algorithm is selected and hyperparams are valid (no errors)
STALE        — was COMPLETE; user returned and changed algorithm/hyperparams
```

WizardBar badge per state:
- `LOCKED` → padlock icon 🔒, step is not clickable
- `PENDING` → empty circle (unfilled), not yet visited
- `IN_PROGRESS` → filled circle (in-progress dot)
- `COMPLETE` → green check ✓
- `STALE` → amber dot ●

Entering a STALE stage: the WizardBar subtitle under ② shows the previously selected algorithm name (e.g. `SAC · 2 M steps`) so the operator sees at a glance what was last saved.

---

## 3. Page-level layout

### 3.1 Desktop (≥ 1024 px) — single wide column

Stage ② is content-light; a two-column layout would leave one side empty. Single-column, max-width 760 px, centred.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  WIZARD BAR                                                                  │
│  ①Config ✓  →  ②Algorithm ●  →  ③Train  →  ④Eval  →  ⑤Finance              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─ ALGORITHM ─────────────────────────────────────────────────────────────┐ │
│  │  Choose the training algorithm.                                         │ │
│  │                                                                         │ │
│  │  ┌──────────────────────────────┐  ┌──────────────────────────────────┐ │ │
│  │  │  ● SAC  (recommended)        │  │  ○ Baseline only                │ │ │
│  │  │  Soft Actor-Critic           │  │  No training — run one or        │ │ │
│  │  │  Off-policy, continuous      │  │  more baseline agents directly   │ │ │
│  │  │  action space                │  │  to get a reference result.      │ │ │
│  │  │  [learn more ↗]              │  │  [learn more ↗]                  │ │ │
│  │  └──────────────────────────────┘  └──────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─ HYPERPARAMETERS  (SAC) ────────────────────────────────────────────────┐ │
│  │  (collapsed by default if defaults are accepted; expandable)            │ │
│  │                                                                         │ │
│  │  Training steps   [  2 000 000  ]   ← required                         │ │
│  │  Eval frequency   [    50 000   ]   evaluations per N steps            │ │
│  │  Batch size       [    256      ]   gradient steps per update          │ │
│  │  Learning rate    [ 3e-4        ]                                       │ │
│  │  γ (discount)     [ 0.99        ]                                       │ │
│  │  Buffer size      [1 000 000    ]   replay buffer capacity              │ │
│  │  N parallel envs  [   16        ]   vmapped env count                  │ │
│  │  [↺ Reset to defaults]                                                  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─ BASELINES ─────────────────────────────────────────────────────────────┐ │
│  │  Select which baseline agents to include in the policy library.         │ │
│  │  Baseline results appear alongside trained policies in Stage ④ Eval.   │ │
│  │                                                                         │ │
│  │  ☑  Do-nothing (no dispatch)                                            │ │
│  │  ☑  Peak-shave heuristic                                                │ │
│  │  ☐  Rule-based import minimiser                                         │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  [← Back to Config]                           [Confirm & Continue →]        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Tablet and mobile — same single column, stacked

No layout change needed vs desktop; all sections stack naturally. Card widths become full-width on mobile.

---

## 4. Algorithm selection cards

Two mutually exclusive cards with radio-button semantics (one must always be selected; `SAC` is the default on first visit).

### 4.1 SAC card (selected state)

```
┌──────────────────────────────────────────────────────────────┐
│  ●  SAC  (recommended)                                       │
│     Soft Actor-Critic                                        │
│     ─────────────────────────────────────────────────────── │
│     Off-policy RL for continuous action spaces.             │
│     Entropy regularisation prevents over-fitting to a        │
│     specific weather pattern.                                │
│                                                              │
│     [learn more ↗]    (links to REBUILD_SPEC §5 or docs)    │
└──────────────────────────────────────────────────────────────┘
```

Selected state: `border: 1.5px solid #60a5fa` (active blue), background `#1e2533`, radio dot filled blue.
Unselected state: `border: 1px solid #2d3748`, background `#161b27`, radio dot empty grey.

### 4.2 Baseline-only card (unselected state)

```
┌──────────────────────────────────────────────────────────────┐
│  ○  Baseline only                                            │
│     No RL training                                           │
│     ─────────────────────────────────────────────────────── │
│     Skip training entirely. Run only the selected baseline   │
│     agents to build a performance reference point.           │
│     Useful for benchmarking without compute cost.            │
│                                                              │
│     [learn more ↗]                                           │
└──────────────────────────────────────────────────────────────┘
```

Selecting "Baseline only" collapses the HYPERPARAMETERS section entirely (it has no hyperparams) and shows a notice:
```
ℹ  No training will be run. Baseline agents will be evaluated in Stage ③
   and added to the policy library alongside any prior SAC runs.
```

---

## 5. Hyperparameters form

### 5.1 Collapsed default state

```
▸  HYPERPARAMETERS   Training steps: 2M · LR: 3e-4 · γ: 0.99 · 16 envs   [Edit ✎]
```

The collapsed header shows a compact summary of the 4 most user-visible params. `[Edit ✎]` or clicking anywhere on the header expands the form.

### 5.2 Expanded form

```
▾  HYPERPARAMETERS                                          [↺ Reset to defaults]

   Training steps      [ 2 000 000  ]   Total environment steps (≥ 100 000)
   Eval frequency      [    50 000  ]   Eval every N training steps
   Batch size          [   256      ]   Samples per gradient update
   Learning rate       [ 3e-4       ]   Adam optimizer LR (range: 1e-5 – 1e-2)
   γ (discount)        [ 0.99       ]   Reward discount factor (0 < γ ≤ 1)
   Replay buffer size  [ 1 000 000  ]   Transition capacity (≥ batch_size × 4)
   Parallel envs       [  16        ]   Vmapped env count (power of 2; 1–256)
```

**Field validation (client-side for range checks, not physics):**
- Each field has an inline range indicator (greyed text to the right of the input): `(range: 1e-5 – 1e-2)`
- Out-of-range values show an amber ⚠ inline: `"3 exceeds max 1e-2"` — treated as a soft error (blocks Continue with an explanatory tooltip on the button)
- Parallel envs: constrained to powers of 2; if non-power-of-2 is entered, an inline note suggests the nearest power: `"⚠ Not a power of 2 — nearest valid: 16 or 32"`

**[↺ Reset to defaults]:** resets all fields to the recommended defaults (defined in REBUILD_SPEC §5). Does not reset the algorithm card selection.

### 5.3 When "Baseline only" is selected

The HYPERPARAMETERS section is hidden entirely (not collapsed — removed from DOM). A note appears instead:
```
ℹ  No hyperparameters — baselines use deterministic heuristics only.
```

---

## 6. Baselines section

```
┌─ BASELINES ─────────────────────────────────────────────────────────────────┐
│  These agents run without training and appear in the policy library           │
│  alongside SAC results. Used as performance benchmarks in Stage ④ Eval.      │
│                                                                              │
│  ☑  Do-nothing         Grid import fills all load; battery idle              │
│  ☑  Peak-shave         Discharge battery during tariff peak hours           │
│  ☐  Import minimiser   Greedy rule: charge when PV > load, else dispatch    │
│                                                                              │
│  (At least one baseline must be selected)                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Rules:**
- At least one baseline must be selected regardless of algorithm choice (hard constraint — blocks Continue if deselected all).
- Baselines are added to the policy library when Stage ③ runs. For "Baseline only" algorithm choice: baselines are the only items in the policy library.
- Baseline list is static in v1 (no custom upload). The full list comes from the `GET /api/baselines` endpoint; v1 exposes these three.

**Why baselines are here, not in Stage ③:**
The operator's decision about which baselines to include is an algorithmic/policy choice, not a training execution detail. Surfacing it in Stage ② means the policy library composition is fully visible at plan time.

---

## 7. Edit-class interaction rule (Class A — amber notice in Stage ③)

Per wizard_flow.md §2.0:
> Algorithm choice + hyperparameter values are **Class A** (physical config). Changing them after a training run creates an amber notice in Stage ③ (Train), but does NOT block or cascade to Stage ④ Eval or Stage ⑤ Finance.

**What this means in Stage ②:**
- If Stage ③ (Train) has results (COMPLETE), and the user returns to Stage ② and changes the algorithm or hyperparams:
  - Stage ② transitions from COMPLETE → STALE
  - Stage ③ shows: `"Algorithm or hyperparameters changed since the last run. Start a new run to train with the current settings."`
  - **Stage ③ is NOT blocked**. The operator can still view existing training runs. They must start a new run to produce a policy under the updated settings.
  - Stage ④ and ⑤ are unaffected (decoupled model).

- Stage ② does NOT show this notice itself. It only transitions to STALE (amber dot on WizardBar). No modal, no blocking.

---

## 8. Footer

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [← Back to Config]                           [Confirm & Continue →]        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 8.1 [← Back to Config]
Always enabled. Navigates to Stage ① without saving any changes to Stage ②. State is preserved in-memory (if the user returns to Stage ②, their work is still there) but not persisted to the server until `[Confirm & Continue →]` is clicked.

### 8.2 [Confirm & Continue →]
- **Enabled when:** an algorithm is selected AND at least one baseline is selected AND all hyperparameter fields are in range.
- **Label:** `Confirm & Continue →` (deliberate "Confirm" — the operator is committing to a training configuration, not just saving a draft).
- **On click:**
  1. Calls `POST /api/training/config` (or `PATCH`) to persist the algorithm choice + hyperparams + selected baselines.
  2. Transitions Stage ② to COMPLETE.
  3. Navigates to Stage ③ (Train).
- **Disabled tooltip:** when disabled, hovering the button shows a brief reason: `"Select at least one baseline"` / `"Fix hyperparameter range errors"`.

---

## 9. Stage ② in LOCKED state (Stage ① not yet COMPLETE)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  WIZARD BAR                                                                  │
│  ①Config ●  →  ②Algorithm 🔒  →  ③Train  →  ④Eval  →  ⑤Finance              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─ LOCKED ────────────────────────────────────────────────────────────────┐ │
│  │                                                                         │ │
│  │  Complete Stage ① (Site Configuration) to unlock Algorithm selection.  │ │
│  │                                                                         │ │
│  │  [← Go to Config]                                                       │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

The WizardBar step ② shows a padlock icon. The stage body shows a single lock notice. The user cannot interact with any form elements. All cards and inputs are absent from the DOM (not just disabled) — a screen reader should not announce them.

---

## 10. Accessibility notes

- Algorithm cards: `role="radio"` with `aria-checked="true/false"`; grouped under a `role="radiogroup"` with `aria-label="Training algorithm"`. Keyboard: Space to select; Tab/Shift-Tab to navigate between cards.
- Hyperparameter form: standard `<label>` + `<input>` pairs; range hints as `aria-describedby` referencing the range text span.
- Out-of-range errors: `role="alert"` on the inline error text so screen readers announce immediately on input.
- Baselines: `role="group"` with `aria-label="Baseline agents"` containing standard checkboxes.
- Collapsed/expanded hyperparams: controlled via `aria-expanded` on the section header button; section content uses `hidden` attribute when collapsed.

---

## 11. Component checklist

Components required for this stage:

| Component | Role |
|-----------|------|
| `WizardBar` | Top stepper (shared across all stages) |
| `StageShell` | Outer wrapper (shared) |
| `AlgorithmCard` | Radio-style card (SAC / Baseline-only); new |
| `HyperparamForm` | Collapsible field group with range validation; new |
| `BaselineSelector` | Multi-checkbox baseline list; new |
| `StageSaveButton` | Footer "Confirm & Continue" with loading state (shared primitive from §15 of stage_1_config.md) |

---

## 12. Open questions

**Q1 — Future algorithms:** Will PPO, TD3, or other algorithms be offered in v2? If so, each algorithm needs its own HyperparamForm variant. For v1, only SAC is implemented and the card list is hard-coded. The card layout should accommodate 3–4 cards without horizontal scrolling (current design: 2 cards side-by-side = fine for up to 4).

**Q2 — Hyperparameter presets:** Should there be a "preset" selector (e.g. "Fast/balanced/thorough" that sets step count and buffer size)? Not in v1; noted here for future USER review.

**Q3 — N parallel envs vs compute:** The operator picks N envs without knowing the available GPU count. Should the form show a compute estimate (e.g. "~4 h on A100 with 16 envs, 2M steps")? If the serving layer can provide a duration estimate from `POST /api/training/config/estimate`, this would be a useful affordance. Flag in contract — not blocking.

**Q4 — Baseline-only flow Stage ③:** When "Baseline only" is selected, Stage ③ (Train) shows only the baseline evaluation progress, not a SAC training curve. Stage ③ per-screen layout will cover this sub-state.

---

*docs/design/ux/stage_2_algorithm.md — ui-designer, task #65 — v0.1 2026-06-12 (initial per-screen layout: algorithm cards, hyperparameter form, baselines section, LOCKED state, Class A interaction rule, footer, a11y, component checklist)*
