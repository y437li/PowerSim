# Stage ③ — Train: Per-Screen Layout

> **Owner:** ui-designer · **Task:** #65
> **Status:** DRAFT v0.1 (2026-06-12)
> **Gate:** frontend-reviewer verdict on PR #85 before frontend contract is authored.
> **Parent doc:** wizard_flow.md v0.5 (§6, §10) — this document deepens Stage ③ only.
> **Prerequisite:** Stage ② Algorithm must be COMPLETE before Stage ③ is accessible.
> **Key design principle:** Train and Eval are DECOUPLED. Training produces artifacts into the policy library; Stage ④ Eval is a separate deliberate selection stage. No auto-evaluation after training completes.

---

## 1. Purpose and scope

Stage ③ executes the training run (or baseline-only evaluation) and accumulates the resulting policies into the **policy library**. The operator monitors progress, starts additional runs if desired, and proceeds to Stage ④ when they have the policies they want.

This stage wraps the existing `TrainingPanel` route components (StreamStatusBanner, RunSelector, ThroughputCard, MetricCurves, CheckpointEventList) inside the wizard's `StageShell`. The component mounting is unchanged; only the shell wrapper differs between `/training` (raw route) and Stage ③ (wizard context).

---

## 2. Stage states

```
LOCKED        — Stage ② Algorithm is not yet COMPLETE
PENDING       — Stage ② is COMPLETE; no run has been started yet
RUNNING       — a training run is currently in progress
COMPLETE      — at least one training run has finished (or baseline-only selected)
STALE-CONFIG  — was COMPLETE; Stage ① or ② was subsequently edited
                (policy library still visible; amber notice shown)
```

**STALE-CONFIG** is the key state unique to this stage. It signals: "Your current settings have changed since the last training run. The policy library still shows previous results — they are valid records of what was trained. Start a new run to get a policy for the current settings."

WizardBar badge:
- `LOCKED` → 🔒
- `PENDING` → empty circle
- `RUNNING` → ⏳ (pulse animation)
- `COMPLETE` → green ✓
- `STALE-CONFIG` → amber ● with a tooltip: "Config or algorithm changed since last run"

---

## 3. Page-level layout

### 3.1 Sub-state A — PENDING (no run started yet)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  WIZARD BAR                                                                  │
│  ①Config ✓  →  ②Algorithm ✓  →  ③Train ●  →  ④Eval  →  ⑤Finance             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─ READY TO TRAIN ────────────────────────────────────────────────────────┐ │
│  │  Algorithm:  SAC · 2 000 000 steps · 16 envs                           │ │
│  │  Config:     Gansu-v1 (#a1b2c3) · Tariff: Gansu-TOU-2024               │ │
│  │  Baselines:  Do-nothing · Peak-shave                                   │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─ POLICY LIBRARY ─────────────────────────────────────────────────────── ┐ │
│  │  No policies yet. Start a training run to add one.                      │ │
│  │  [▶ Start training run]   ← primary action                             │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  [← Back to Algorithm]                         [Go to Eval →]               │
│                                                 (disabled — no policies yet) │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Sub-state B — RUNNING (training in progress)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  WIZARD BAR                                                                  │
│  ①Config ✓  →  ②Algorithm ✓  →  ③Train ⏳  →  ④Eval  →  ⑤Finance            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ─── existing TrainingPanel components (mounted here as in /training) ──── │
│                                                                              │
│  [StreamStatusBanner]  ← shows only when WS stale / gap / disconnected      │
│  [RunSelector]         ← compact header; shows active run + past runs       │
│  [ThroughputCard]      ← current steps/sec, ETA                             │
│  [MetricCurves]        ← 5-panel metric charts (reward, Q-loss, etc.)       │
│  [CheckpointEventList] ← checkpoint saves with step + reward                │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  ┌─ POLICY LIBRARY ────────────────────────────────────────────────────────┐ │
│  │  Run #1  SAC  Gansu-v1 #a1b2c3  ⏳ Running  step 420k / 2M  ETA 3h22m  │ │
│  │  [Pause ⏸]  [Stop ■]                                                    │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  [← Back to Algorithm]              [+ Start another run]  [Go to Eval →]  │
│                                                             (disabled while  │
│                                                              no completed)   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Sub-state C — COMPLETE (≥ 1 run finished)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  WIZARD BAR                                                                  │
│  ①Config ✓  →  ②Algorithm ✓  →  ③Train ✓  →  ④Eval  →  ⑤Finance            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  [StreamStatusBanner]  (hidden — no active run)                              │
│  [RunSelector]                                                               │
│  [ThroughputCard]      (shows last run's final stats)                        │
│  [MetricCurves]        (shows selected run's curves)                         │
│  [CheckpointEventList]                                                       │
│                                                                              │
│  ┌─ POLICY LIBRARY ────────────────────────────────────────────────────────┐ │
│  │  Label                  Algorithm  Config   Status    Best reward        │ │
│  │  ─────────────────────────────────────────────────────────────────────  │ │
│  │  SAC run-a1b2c3         SAC        #a1b2c3  ✓ Done    −¥312/MWh         │ │
│  │  (best ckpt step 1.8M)  2M steps   Gansu    2026-06-10                  │ │
│  │                                                                          │ │
│  │  Do-nothing baseline    Baseline   #a1b2c3  ✓ Done    −¥430/MWh         │ │
│  │  Peak-shave baseline    Baseline   #a1b2c3  ✓ Done    −¥361/MWh         │ │
│  │                                                                          │ │
│  │  [+ Start another run]                                                  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  [← Back to Algorithm]            [+ Start another run]  [Go to Eval →]    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.4 STALE-CONFIG notice (amber banner, shown above content when triggered)

When Stage ① or Stage ② was edited after a COMPLETE training run, an amber notice appears at the top of the stage content area (between WizardBar and the TrainingPanel components):

```
┌─ AMBER NOTICE ──────────────────────────────────────────────────────────────┐
│  ⚠  Config or algorithm changed since the last training run.               │
│     Current config: #e5f6a7  |  Last trained on: #a1b2c3                   │
│     Previous policies are still valid records — they are shown in the       │
│     Policy Library below. Start a new run to train with the current setup. │
│     [▶ Start new run]  ← shortcut button (does the same as "Start another") │
└──────────────────────────────────────────────────────────────────────────────┘
```

**This notice is NOT a modal, NOT a blocking wall.** The operator can proceed to Stage ④ without starting a new run — they can evaluate an existing policy. The notice only communicates the mismatch; the human decides what to do about it.

---

## 4. Training run lifecycle controls

### 4.1 Starting a run

`[▶ Start training run]` (first run) or `[+ Start another run]` (subsequent) opens a **run confirmation slip** — an inline panel just above the Policy Library, not a modal:

```
┌─ NEW TRAINING RUN ─────────────────────────────────────────────────────────┐
│  Algorithm:  SAC                                                            │
│  Config:     Gansu-v1 (#a1b2c3)                                             │
│  Steps:      2 000 000  [edit ✎]  ← quick override without going back      │
│  Envs:       16                                                             │
│                                                                             │
│  [▶ Confirm & Start]   [Cancel ✕]                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

The "Steps" field has a quick-override (`[edit ✎]`) so the operator can kick off a shorter or longer run without navigating back to Stage ②. This does NOT update the saved Stage ② hyperparams — it's a run-level one-off. After the run, Stage ② hyperparams remain at their saved value.

On `[Confirm & Start]`:
1. Calls `POST /api/training/run` with the confirmed config
2. Training panel transitions to RUNNING sub-state
3. StreamStatusBanner connects; metrics begin populating

### 4.2 Pausing and resuming

During a run, the Policy Library row for the active run shows:
```
Run #1 · step 420k / 2M · ETA 3h22m   [Pause ⏸]  [Stop ■]
```

- `[Pause ⏸]`: calls `POST /api/training/run/{id}/pause`; run state becomes PAUSED; button changes to `[Resume ▶]`
- `[Stop ■]`: calls `POST /api/training/run/{id}/stop`; a confirmation popover appears: `"Stop training? The best checkpoint so far will be saved."` — `[Stop & Save]` or `[Cancel]`.
- `[Resume ▶]`: calls `POST /api/training/run/{id}/resume`; run transitions back to RUNNING.

### 4.3 Policy library row states

| State | Display | Controls |
|-------|---------|----------|
| RUNNING | `⏳ Running · step N/M · ETA T` | [Pause ⏸] [Stop ■] |
| PAUSED | `⏸ Paused · step N/M · best so far` | [Resume ▶] [Stop ■] |
| COMPLETE | `✓ Done · step M · best ckpt @ step K` | — (read-only) |
| STOPPED | `■ Stopped · step N · best ckpt @ step K` | — |
| FAILED | `✗ Failed · reason` | [Retry ↺] |

---

## 5. Policy library

The Policy Library is the primary output of Stage ③. It persists across wizard sessions — policies accumulate here until explicitly deleted (v2 feature).

### 5.1 Policy entry structure

Each entry in the library shows:
```
  Label          run-a1b2c3 · SAC
  Config         Gansu-v1 #a1b2c3 · 2026-06-10
  Steps          2 000 000 (best checkpoint: step 1 800 000)
  Best reward    −¥312/MWh (training metric — not finance)
  Status         ✓ Complete
```

**Provenance fields** (for Stage ④ compatibility check and Stage ⑤ finance provenance):
- `config_hash` — which site config this policy was trained on
- `algo` — SAC, Baseline/do-nothing, etc.
- `hyperparams_hash` — uniquely identifies the hyperparam set
- `train_date` — ISO date
- `best_step` — checkpoint step with highest eval reward during training
- `obs_dim`, `action_dim` — used for compatibility check in Stage ④

### 5.2 Policy entry actions

Each row has a `[⋯]` overflow menu:
- **View training curves** — navigates to the RunSelector for this run (scrolls MetricCurves to this run's data)
- **Delete** — soft delete with confirmation: `"Delete this policy entry? The checkpoint file is preserved; only the library reference is removed."` (v1: checkpoint files are not deleted from disk)
- (Future v2: **Rename**, **Export checkpoint**)

### 5.3 Baseline entries

Baselines (do-nothing, peak-shave) appear in the library after their first evaluation. They show:
```
  Label       Do-nothing baseline
  Type        Heuristic (no training)
  Config      Gansu-v1 #a1b2c3
  Result      −¥430/MWh (deterministic — same result every eval)
  Status      ✓ Available
```

Baselines don't have training curves, checkpoints, or step counts. They have no `[Pause/Stop]` controls.

---

## 6. "Baseline only" algorithm flow in Stage ③

When Stage ② has "Baseline only" selected:
- The TrainingPanel training-curve components (MetricCurves, ThroughputCard) are hidden — no training to monitor.
- The PENDING state shows: `"No training — baselines will be evaluated and added to the policy library."` with a `[▶ Run baselines]` button.
- The RUNNING state shows only a simple progress indicator: `"Evaluating baselines… Do-nothing ✓ · Peak-shave ⏳"`.
- The COMPLETE state shows the policy library with only baseline entries. `[Go to Eval →]` becomes available.

---

## 7. Raw `/training` route coexistence

Per wizard_flow.md Q6 (resolved: keep raw routes):
- `/training` continues to mount `TrainingPanel` unchanged (same components as in Stage ③).
- Stage ③ mounts the same `TrainingPanel` inside `StageShell`.
- The raw `/training` route shows a small `[← Wizard]` back-link in the top-left that navigates to Stage ③ in the wizard.
- No code duplication: `TrainingPanel` is a shared component; `StageShell` is purely a wrapper.

---

## 8. Footer

```
[← Back to Algorithm]         [+ Start another run]         [Go to Eval →]
                               (always shown once ≥1          (enabled when ≥1
                                policy exists)                 policy in library)
```

### 8.1 [← Back to Algorithm]
Always enabled. Navigates to Stage ② without side effects. Any in-progress run continues in the background.

### 8.2 [+ Start another run]
Visible once at least one run has been started (not in pure PENDING state). Opens the run confirmation slip (§4.1). Does not navigate away.

### 8.3 [Go to Eval →]
- Enabled when: the policy library has at least one complete entry (SAC or baseline).
- Disabled tooltip if not yet enabled: `"Complete at least one training run to proceed."` / `"Wait for the current run to complete, or use an existing policy."`
- A running run does NOT block navigation to Stage ④ — the operator can start a run and go explore Stage ④ while it runs. The policy library in Stage ④ will show the partial run as `⏳ Running`.

---

## 9. Accessibility notes

- Policy Library table: `role="table"` with `role="row"` / `role="cell"`; sorting controls use `aria-sort`.
- Run status chips: `role="status"` (live region) for `⏳ Running · step N/M` so screen readers announce step progress updates.
- `[Pause/Stop/Resume]` buttons: `aria-label="Pause run: run-a1b2c3"` to identify which run is affected.
- STALE-CONFIG notice: `role="alert"` so it's announced on appearance.
- MetricCurves charts: each chart has an `aria-label` description of what it shows; a `[View as table]` toggle (v2) would provide a data table equivalent.

---

## 10. Component checklist

Components required for this stage:

| Component | Role |
|-----------|------|
| `WizardBar` | Top stepper (shared) |
| `StageShell` | Outer wrapper (shared) |
| `StreamStatusBanner` | WS status (re-used from TrainingPanel) |
| `RunSelector` | Run picker header (re-used) |
| `ThroughputCard` | Current speed / ETA (re-used) |
| `MetricCurves` | 5-panel training metric charts (re-used) |
| `CheckpointEventList` | Checkpoint saves list (re-used) |
| `PolicyLibrary` | New: replaces the informal policy list; shows all runs + baselines with provenance; mounted in Stage ③ (output view) and Stage ④ (input selector) |
| `RunConfirmationSlip` | New: inline pre-run summary + step override; not a modal |
| `StaleConfigNotice` | New: amber notice for Class A changes; `role="alert"` |

---

## 11. Open questions

**Q1 — Run concurrency in Stage ③:** Can the operator start a second run while one is already in progress? The backend (sbx/purejaxrl with vmapped envs) supports parallel runs. For v1, assume single active run at a time; policy library shows RUNNING for the active run. Multi-run concurrency is a v2 feature. Flag in contract.

**Q2 — Checkpoint surfacing:** The Policy Library shows "best checkpoint (step K)" per run. Should it also allow the operator to select a non-best checkpoint (e.g. step 500K vs 1M for early-stage policy)? V1: best checkpoint only. V2: intermediate checkpoint selector. Flag for Stage ④ eval contract — Stage ④ picker needs to decide what it shows.

**Q3 — Training run from a different config:** The "Start another run" flow always uses the current Stage ① config. If the operator wants to train a policy on a different site config (for the comparison workbench), they'd go back to Stage ① and change the config. Is there a shortcut to train on a saved config without changing the active wizard config? Not in v1 — the workbench handles the variant-with-different-config case via its Retrain badge + wizard shortcut. No change to Stage ③.

**Q4 — Baseline eval trigger:** When are baselines added to the policy library? Options: (a) when the operator explicitly starts the baseline evaluation from Stage ③ (current design), or (b) automatically when Stage ③ is first entered. Option (a) is preferred (operator in control) but baseline eval is fast (< 1 min); flag for contract.

---

*docs/design/ux/stage_3_train.md — ui-designer, task #65 — v0.1 2026-06-12 (initial per-screen layout: three sub-states (pending/running/complete), STALE-CONFIG notice, training run lifecycle controls, policy library, baseline-only flow, raw-route coexistence, footer, a11y, component checklist)*
