# Stage ④ — Eval: Per-Screen Layout

> **Owner:** ui-designer · **Task:** #65
> **Status:** DRAFT v0.1 (2026-06-12)
> **Gate:** frontend-reviewer verdict on PR #85 before frontend contract is authored.
> **Parent doc:** wizard_flow.md v0.5 (§7, §10) — this document deepens Stage ④ only.
> **Core model:** Eval is a DELIBERATE SELECTION stage. The operator picks a (policy, env config) pair and runs a full 8760-step evaluation. Results accumulate in the Eval Results Library. Finance (Stage ⑤) picks which eval result to use. Cross-eval (policy trained on config A, evaluated on config B) is a first-class robustness check, not a mistake.

---

## 1. Purpose and scope

Stage ④ decouples evaluation from training. The policy library (from Stage ③) feeds into a picker here; the operator selects any policy (SAC run or baseline), optionally swaps the env config to test cross-generalization, and launches a headless eval run. Multiple eval results can coexist; each row in the Eval Results Library is an independent result record.

This is also where the **observed mode** (D24 real-time pacing + streaming) is used — unlike Stage ③'s live training stream, an eval run in Stage ④ can be run in either observed mode (streaming, visible in live dashboard) or batch mode (fast, no stream) based on operator choice. For v1: observed mode only in Stage ④; batch mode is the workbench path.

---

## 2. Stage states

```
LOCKED       — Stage ③ Train has no completed policies yet
PENDING      — ≥1 policy exists in library; no eval has been run yet
RUNNING      — an eval is currently in progress
COMPLETE     — ≥1 eval result in the library
```

Stage ④ is never STALE — eval results are immutable records. A config change in Stage ① does NOT mark Stage ④ as stale (provenance-based model). Existing eval results retain their config_hash provenance and are shown as-is; a cross-eval notice appears if the current config differs from an eval result's config.

WizardBar badge: LOCKED → 🔒, PENDING → empty circle, RUNNING → ⏳, COMPLETE → ✓

---

## 3. Page-level layout

### 3.1 Desktop (≥ 1024 px) — two-panel split

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  WIZARD BAR                                                                  │
│  ①Config ✓  →  ②Algorithm ✓  →  ③Train ✓  →  ④Eval ●  →  ⑤Finance         │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─ LEFT: EVAL PICKER (45%) ──────────────┐  ┌─ RIGHT: EVAL RESULTS (55%) ─┐ │
│  │                                        │  │                             │ │
│  │  ── POLICY ─────────────────────────── │  │  ── EVAL RESULTS LIBRARY ── │ │
│  │  [PolicyLibrary picker — §4]           │  │  [EvalResultLibrary — §5]   │ │
│  │                                        │  │                             │ │
│  │  ── ENV CONFIG ─────────────────────── │  │  Empty:                     │ │
│  │  [● Current config (Gansu-v1 #a1b2c3)] │  │  "No evaluations yet.       │ │
│  │  [○ Select saved config ▼]             │  │   Select a policy and       │ │
│  │                                        │  │   run an eval to start."    │ │
│  │  ── COMPATIBILITY ─────────────────── ─│  │                             │ │
│  │  [CompatibilityBadge — §6]             │  │                             │ │
│  │                                        │  │                             │ │
│  │  [▶ Run eval]                          │  │                             │ │
│  │  (disabled until compatible pair)      │  │                             │ │
│  └────────────────────────────────────────┘  └─────────────────────────────┘ │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  [← Back to Train]                                      [Go to Finance →]   │
│                                                          (disabled until     │
│                                                           ≥1 result)         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Mobile / tablet — stacked

Left picker panel appears first (above); right results panel below. User completes the picker and runs eval; results populate below without navigating away.

---

## 4. Policy picker

```
┌─ POLICY ────────────────────────────────────────────────────────────────────┐
│  [Search or select policy ▼]                                                 │
│                                                                              │
│  ● SAC run-a1b2c3  ✓ Done    Config #a1b2c3  step 1.8M  −¥312/MWh          │
│    (best checkpoint, 2026-06-10)                                             │
│                                                                              │
│  ○ Do-nothing baseline        Config #a1b2c3  deterministic                 │
│  ○ Peak-shave baseline        Config #a1b2c3  deterministic                 │
│                                                                              │
│  ○ SAC run-b3c4d5  ⏳ Running  Config #a1b2c3  step 600k / 2M              │
│    (not yet selectable — completes in ~2h)                                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Policy entries:**
- All COMPLETE and STOPPED runs from the policy library are selectable.
- RUNNING runs appear in the list as greyed, non-selectable, with an ETA indicator.
- Each entry shows: label, config hash, step (or "deterministic" for baselines), best reward.
- Entries are sorted: most recent first, baselines at the bottom.

**Selection:** radio-button semantics — one policy selected at a time.

---

## 5. Env config picker

```
┌─ ENV CONFIG ────────────────────────────────────────────────────────────────┐
│  [● Current wizard config  (Gansu-v1 #a1b2c3)]                              │
│  [○ Select saved config ▼]                                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Current wizard config** (default): uses the current Stage ① saved config. If Stage ① is STALE (user has edited since last save), shows: `"(current config has unsaved changes — save in Stage ① to use it)"`.
- **Select saved config:** dropdown listing all previously saved site configs (by name or hash). Selecting a config other than the policy's training config → cross-eval path.

**Cross-eval indicator:**
When the selected policy's training config ≠ the selected eval env config, a blue `ℹ` info notice appears between the Env Config picker and the Compatibility badge:

```
ℹ  Cross-eval: this policy was trained on config #a1b2c3 but will be
   evaluated on #e5f6a7. This measures out-of-distribution generalisation.
   Results will be labelled "[cross-eval]" in the library.
   This is intentional — not an error.
```

Not a warning, not amber — blue info. Cross-eval is a first-class deliberate action.

---

## 6. Compatibility badge

```
┌─ COMPATIBILITY ─────────────────────────────────────────────────────────────┐
│                                                                              │
│  Checking…  ⟳         ← while GET /api/eval/check-compat is in flight      │
│                                                                              │
│  OR:                                                                         │
│                                                                              │
│  ✓ Compatible           obs_dim 24 ✓ · action_dim 4 ✓                       │
│    Ready to run eval.                                                        │
│                                                                              │
│  OR:                                                                         │
│                                                                              │
│  ⊗ Incompatible                                                              │
│    Policy expects obs_dim 6, env resolves to obs_dim 24.                    │
│    (Policy was trained on a single-device config; this config has 4         │
│     device types.)                                                           │
│    [← Go to Stage ① to adjust config]   [← Select a different policy]      │
└──────────────────────────────────────────────────────────────────────────────┘
```

The compat check calls `GET /api/eval/check-compat?policy_id=…&config_hash=…` when either picker changes. Result:
- `{compatible: true, obs_dim: 24, action_dim: 4}` → green ✓, [▶ Run eval] enabled
- `{compatible: false, reason: "obs_dim mismatch: policy=6, env=24"}` → red ⊗, [▶ Run eval] disabled, reason shown

---

## 7. Run eval action

```
[▶ Run eval]
   ↳ enabled when: policy selected + env config selected + compat ✓

Pre-run confirmation slip (inline, not modal):
┌───────────────────────────────────────────────────────────────────────────┐
│  Policy:   SAC run-a1b2c3 (best ckpt, step 1.8M)                         │
│  Env:      Gansu-v1 #a1b2c3 (current config)                             │
│  Duration: 8760 steps (~2–5 min with 16 envs)                            │
│  Mode:     Observed  [● Observed  ○ Batch]                                │
│            (Observed: live in dashboard + 3D · Batch: fast, no stream)   │
│                                                                           │
│  [▶ Confirm & Start]   [Cancel ✕]                                        │
└───────────────────────────────────────────────────────────────────────────┘
```

**Eval mode selector:**
- **Observed** (default in Stage ④): telemetry WS stream active; D24 pacing applied; run appears in live dashboard and 3D scene; real-time metric output. This is the "observed mode" from the two-mode spec.
- **Batch**: fast vmapped run, no stream, no 3D; result available sooner. Appropriate when the operator just wants the number, not the experience. This is the "batch mode" — same as the workbench path.

For v1, both options are surfaced here. The default (Observed) gives the premium experience for a first eval run. Batch is available for quick re-evals.

**During eval (RUNNING sub-state):**

```
┌─ LEFT: EVAL PICKER ────────────────────────────────┐
│  [Policy and env config grayed out — locked        │
│   during active eval run]                          │
│                                                    │
│  CURRENT EVAL                                      │
│  Policy:   SAC run-a1b2c3                          │
│  Env:      Gansu-v1 #a1b2c3                        │
│  Mode:     Observed                                │
│  Progress: ████████░░░░  step 4 380 / 8 760        │
│            50% · ~2 min remaining                  │
│                                                    │
│  [Stop eval ■]                                     │
└────────────────────────────────────────────────────┘
```

The Eval Results Library on the right shows the in-progress run as a pending row with a shimmer/skeleton state.

---

## 8. Eval Results Library

```
┌─ EVAL RESULTS LIBRARY ──────────────────────────────────────────────────────┐
│                                                                              │
│  #   Policy               Env config   Mode   Date       Status   Actions   │
│  ─────────────────────────────────────────────────────────────────────────  │
│  1   SAC run-a1b2c3       #a1b2c3      Obs    2026-06-10  ✓ Done  [View]    │
│      (cross-eval) [ℹ]     #e5f6a7              2026-06-11         [→Finance] │
│                                                                   [+Compare] │
│                                                                              │
│  2   SAC run-a1b2c3       #a1b2c3      Obs    2026-06-10  ✓ Done  [View]    │
│                                                                   [→Finance] │
│                                                                   [+Compare] │
│                                                                              │
│  3   Peak-shave           #a1b2c3      Batch  2026-06-10  ✓ Done  [View]    │
│                                                                   [→Finance] │
│                                                                   [+Compare] │
│                                                                              │
│  (running) ────────────────────────────────────────────────────────────── ⏳ │
│  4   Do-nothing           #a1b2c3      Obs    —           ⏳ 50%  [Stop ■]  │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Result row anatomy:**

| Field | Content |
|-------|---------|
| # | Sequential result number (library-local, not global) |
| Policy | Policy label + run ID; `[cross-eval] [ℹ]` badge if trained on different config |
| Env config | Config hash(es); for cross-eval shows trained-on / evaluated-on as two hashes |
| Mode | Obs (observed) or Batch |
| Date | ISO date of eval run |
| Status | ✓ Done / ⏳ N% / ✗ Failed |

**Per-row actions:**
- `[View]`: expands the row inline (or navigates to a detail panel) showing: all metrics (net cost, export/import MWh/yr, peak demand MW, violations, comparison vs baselines), action histograms, time-series sample plots.
- `[→ Finance]`: sends this eval result to Stage ⑤ Finance and navigates there. Pre-populates Stage ⑤ with this result.
- `[+ Compare]`: opens `AddToComparisonModal` with this `(policy, env config, eval result)` tuple.

**Expanded row (inline view):**

```
▾  SAC run-a1b2c3 · Gansu-v1 · 2026-06-10                          [Collapse]
   ──────────────────────────────────────────────────────────────────────────
   Assumptions: config #a1b2c3 · 8760 steps · M=1 (no ensemble)
   
   METRIC                  SAC run-a1b2c3      Do-nothing         Peak-shave
   ────────────────────────────────────────────────────────────────────────
   Net cost (¥/MWh)           −312               −430 (ref)         −361
   Grid import (MWh/yr)        780 K              940 K              820 K
   Grid export (MWh/yr)        120 K               40 K               90 K
   Battery cycles/yr            180                  0               140
   Peak import (MW)              210                320               250
   Violations                     0                  0                 0
   
   Best in row: green tint on each best value
   
   [→ Finance]    [+ Compare]    [Export metrics (CSV)]
```

---

## 9. Provenance banner per result

Each eval result carries full provenance that is shown in the expanded row and propagated to Stage ⑤ and the workbench:

```
Config hash:    #a1b2c3   (training config)
Eval env hash:  #a1b2c3   (eval config; same as training = standard eval)
Policy:         SAC run-a1b2c3 · best checkpoint · step 1 800 000
Algorithm:      SAC
Weather mode:   Synthetic M=1
Date:           2026-06-10
Cross-eval:     No
```

When cross-eval (training config ≠ eval config):
```
Config hash:    #a1b2c3   (training config, blue label "trained on")
Eval env hash:  #e5f6a7   (eval config, blue label "evaluated on")
Cross-eval:     Yes  [ℹ generalisation check]
```

---

## 10. Raw `/eval` route coexistence

Per wizard_flow.md Q6 (resolved: keep raw routes):
- `/eval` continues to mount `EvalComparison` unchanged.
- The `EvalComparison` component shows only the most recent eval result vs baselines — the accumulating library is a wizard-only concept in v1.
- `/eval` route shows a `[← Wizard]` back-link at the top.

The full Eval Results Library (multiple results, accumulating) is a Stage ④ feature. The `/eval` route remains the simple comparison table it has always been. No deprecation in v1.

---

## 11. Footer

```
[← Back to Train]                          [Go to Finance →]
                                            (enabled when ≥1 eval result
                                             exists in the library)
```

`[Go to Finance →]` — enabled as soon as the library has at least one COMPLETE result. Does NOT auto-select a result; Stage ⑤ starts with an "EVAL BASIS" picker (see stage_5_finance.md). If the operator clicked `[→ Finance]` on a specific result row, that result is pre-selected in Stage ⑤.

---

## 12. LOCKED state

```
Stage ③ Train has no completed policies.

┌─ LOCKED ────────────────────────────────────────────────────────────────────┐
│  Complete at least one training run in Stage ③ to unlock Eval.             │
│  [← Go to Train]                                                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 13. Accessibility notes

- Policy picker: `role="radiogroup"` with `role="radio"` entries; label includes policy summary for screen readers.
- Env config selector: `role="radio"` pair for "current / saved"; saved config dropdown is a standard `<select>` with option labels.
- CompatibilityBadge: `role="status"` while checking (announced when it changes); `role="alert"` when incompatible (announced immediately).
- CrossEval notice: `role="note"` (not an alert — intentional, not a problem).
- Eval Results Library table: `role="table"`; sort controls with `aria-sort`; action buttons include row context in `aria-label`.
- Running progress bar: `role="progressbar"` with `aria-valuenow`, `aria-valuemin`, `aria-valuemax`.

---

## 14. Component checklist

| Component | Role |
|-----------|------|
| `WizardBar` | Shared |
| `StageShell` | Shared |
| `PolicyLibrary` | Re-used from Stage ③ in picker mode (radio-select, shows all library entries) |
| `EvalPicker` | New: combines policy picker + env config selector + cross-eval notice |
| `CompatibilityBadge` | New: ✓/⊗ with reason; checking state |
| `EvalResultLibrary` | New: accumulating results table with expandable rows |
| `AddToComparisonModal` | Shared (from comparison_workbench.md §6) |
| `RunConfirmationSlip` | Shared (from Stage ③) — eval pre-run confirmation |

---

## 15. Open questions

**Q1 — Observed mode in Stage ④ vs live dashboard:** When eval runs in Observed mode, the live dashboard (`/`) shows the eval replay in 3D. Should Stage ④ show a "View in dashboard →" link during a running observed-mode eval? For v1: yes, a subtle `[View in dashboard ↗]` link during RUNNING Observed state. Not a primary CTA — just a navigation shortcut.

**Q2 — Eval result retention:** Are eval results persisted server-side indefinitely, or only for the current session? V1 assumption: server-side persistent (same as checkpoints). Flag in serving contract.

**Q3 — Batch mode vs Observed in Stage ④:** For v1, both modes are available in Stage ④ (the pre-run confirmation slip shows a mode toggle). Should batch mode be the default for re-evals of the same policy (e.g. second run after first was Observed)? Design decision: Observed remains the default regardless; the operator can switch to Batch explicitly. Flag in contract.

**Q4 — P50/P90/P99 ensemble in eval:** wizard_flow.md §7 says "P50/P90/P99: v1 = point estimate (M=1 draw). Ensemble exceedances activate when §12 historical weather feeds M>1 draws." The eval results library should show P50/P90/P99 columns as `—` in v1 with a tooltip "Available when §12 weather pipeline is integrated." Flag in contract.

---

*docs/design/ux/stage_4_eval.md — ui-designer, task #65 — v0.1 2026-06-12 (initial per-screen layout: two-panel split, policy picker, env config selector, cross-eval flow, compatibility badge, run confirmation, eval mode selector, eval results library with expandable rows, provenance, raw-route coexistence, footer, a11y, component checklist)*
