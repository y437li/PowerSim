# Five-Stage Pipeline Wizard — UX Flow & Interaction Design

> **Owner:** ui-designer · **Task:** #65
> **Status:** DRAFT v0.2 — incorporates rl-architect edit-class ruling (2026-06-12); pending USER aesthetic review before per-screen detail pass
> **Gate:** USER reviews aesthetic direction before frontend contracts are written against this.
> **Inputs:** master_plan_geo_finance.md (workstreams A/E), REBUILD_SPEC §3–§5, existing app at http://localhost:15174
> **Pending reference:** D32 product-spine amendment (task #64) — once landed in `docs/design/`, supersedes any conflicts here

---

## 1. Product intent

The wizard is the product's **primary flow** (USER directive). It guides the operator from a bare site config through to a project finance simulation, with five sequentially-dependent stages:

```
Config → Algorithm Select → Train → Eval → Finance
  (A)          (B)            (C)     (D)      (E)
```

The key design constraint: **upstream edits invalidate downstream results**. A sizing change means the training run is no longer valid; a new training run makes the eval stale. This must be legible at every point in the flow — not a hidden footgun.

The existing app has three isolated routes (`/`, `/training`, `/eval`). The wizard **replaces the flat nav** with a structured pipeline that preserves the same underlying components (TrainingPanel, EvalComparison, SiteView) and wraps them in the stage shell.

---

## 2. Stage dependency model — the core design rule

### 2.0 Two edit classes — the product asymmetry *(rl-architect ruling, 2026-06-12)*

The entire wizard UX is built on **one architectural asymmetry**:

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │  CLASS A — Physical config edits                                    │
 │  (fleet sizing · device model · tariff shape · algorithm choice)   │
 │  → Invalidate ③ Train + ④ Eval + ⑤ Finance                        │
 │  → Retraining REQUIRED — no shortcut                               │
 │  → Unmissable stale state: downstream stages visually greyed,      │
 │    stale banners on any existing results, "Re-train required"      │
 │    replaces every "Continue" button downstream                     │
 └─────────────────────────────────────────────────────────────────────┘
 ┌─────────────────────────────────────────────────────────────────────┐
 │  CLASS B — Finance-only edits                                       │
 │  (discount rate · escalation %/yr · currency · tax/debt toggles)   │
 │  → Invalidate ⑤ Finance ONLY                                       │
 │  → ⑤ recomputes INSTANTLY — no re-dispatch, no server roundtrip   │
 │    on slider drag; IRR/NPV/MIRR/LCOE update live                   │
 │  → ③ and ④ are UNAFFECTED and remain COMPLETE                     │
 └─────────────────────────────────────────────────────────────────────┘
```

This asymmetry *is* the product experience: the upstream pipeline is heavyweight and correct (physics drives economics); the downstream finance playground is instant and explorable. The UX must make both halves feel right — heavy consequences upstream, zero friction downstream.

**Algorithm choice is Class A** (not a separate class): choosing SAC vs. another algorithm, or changing SAC hyperparameters, is equivalent to a physical config change — it requires a new training run. The two-card "Algorithm" stage feeds directly into Train.

### 2.1 Dependency graph

```
 Config ──►  Algorithm ──►  Train ──►  Eval ──►  Finance
   (1)     CLASS A edits     (3)        (4)         (5)
             invalidate                          CLASS B edits
           ③ ④ ⑤ →                             only invalidate
           retrain req.                           ⑤ (instant)
```

| Edit trigger | Edit class | Stages invalidated | User action required |
|---|---|---|---|
| Config: fleet sizing, device model, tariff shape | **A — physical** | ③ ④ ⑤ | Two-step confirm → re-run train |
| Algorithm: choice or any hyperparam | **A — physical** | ③ ④ ⑤ | Two-step confirm → re-run train |
| Training re-launched | **A — physical** | ④ ⑤ | Re-run eval (auto or manual) |
| Eval re-run (new checkpoint) | **A — physical** | ⑤ | Finance auto-recalculates |
| Finance: discount rate, escalation, currency | **B — finance-only** | ⑤ internal only | None — instant client-side recompute |
| Finance: tax/debt toggles | **B — finance-only** | ⑤ internal only | None — instant recompute (slightly heavier) |

### 2.2 Stage state machine (per stage)

Each stage has one of five states, shown in the wizard bar:

```
  ┌──────────────────────────────────────────────────────┐
  │  State          │  Visual cue                        │
  ├─────────────────┼────────────────────────────────────┤
  │  LOCKED         │  Grey  + padlock icon              │
  │  PENDING        │  Dim blue + circle (unfilled)      │
  │  IN_PROGRESS    │  Amber + spinner animation         │
  │  COMPLETE       │  Green + checkmark                 │
  │  STALE          │  Amber + triangle-warning          │
  └──────────────────────────────────────────────────────┘
```

**LOCKED** — upstream prerequisite is not complete. Stage cannot be entered.
**PENDING** — prerequisites met, stage not yet started.
**IN_PROGRESS** — active work (training run / eval run / finance loading).
**COMPLETE** — output exists and upstream is unchanged.
**STALE** — output exists but an upstream stage was edited after it ran; results shown with amber banner "⚠ Config changed after this ran — results may not reflect current setup."

### 2.3 Stale vs. Locked distinction

This distinction is intentional and important:

- **STALE** = "you have results but they're from a different (Class A) config change." The user can still *view* stale results while deciding whether to re-run. They **cannot proceed** to the next stage using stale outputs — the "Continue →" button is **replaced by a disabled "Re-train required"** button. Stale results are shown behind a full-width amber banner: "⚠ Config changed after this ran — results may not reflect current setup." The banner is not dismissable; it clears only when the stage is re-run.
- **LOCKED** = "no results at all — upstream hasn't produced valid output yet." Stage is greyed and non-enterable (cursor: not-allowed on the wizard bar node).

The rl-architect ruling requires stale state to be **unmissable** — not a subtle badge that gets overlooked. Design treatment:
  - Wizard bar: STALE node shows amber ⚠ with strikethrough text (not just a colour change)
  - Stage header: full-width amber banner, always visible above the content area
  - Footer: "Continue →" replaced by "Re-train required ↑" (non-clickable, explains which stage to fix)
  - The *content* of a stale stage remains readable — the user can inspect old results — but every metric is overlaid with a translucent amber tint to reinforce "these numbers are from a prior run"

The same visual separation used for TOU price bands (amber = caution, green = clear, grey = unavailable) maps cleanly here.

---

## 3. Wizard chrome — the top stepper bar

The wizard bar persists across all routes, replacing the current flat NavLinks:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚡ Energy GO                                                        ▸ Docs │
├─────────────────────────────────────────────────────────────────────────────┤
│  ① Config       → ② Algorithm  → ③ Train       → ④ Eval        → ⑤ Finance │
│  ✓ Gansu-v1        ● SAC          ◌ Pending       🔒 Locked       🔒 Locked │
└─────────────────────────────────────────────────────────────────────────────┘
```

Each stage node in the bar:
- **Icon** — state icon (see §2.2)
- **Number badge** — always shown (①–⑤)
- **Stage name** — always shown
- **Summary subtitle** — one-liner when COMPLETE (e.g. "Gansu-v1", "SAC lr=3e-4", "3.2M steps", "−¥18.4M/yr", "IRR 11.2%")
- **Clickable** — only if COMPLETE or STALE (jump to that stage to review/edit)
- **Chevrons** (→) between stages — styled dim when the downstream stage is LOCKED

Color palette (consistent with existing dark theme):
- Background: `#1a1f2e` (same as current `app__nav`)
- Active/IN_PROGRESS: `#f59e0b` (amber) + spinner
- COMPLETE: `#22c55e` (green)
- STALE: `#f59e0b` (amber triangle)
- LOCKED: `#4b5563` (grey)
- PENDING: `#3b82f6` dim (blue, hollow)

---

## 4. Stage 1 — Config

### Purpose
Compose the site: geographic location, device fleet, weather source, tariff region, scenario type.

### Layout
```
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 1: SITE CONFIG                              [✓ Complete] [Edit]│
├──────────────────────────────────────────────────────────────────────┤
│                          │                                            │
│   MAP                    │  SITE DETAILS                             │
│                          │  Name: [Gansu Wind Farm      ]            │
│   [MapLibre tile view    │  Weather: [● Synthetic ○ Historical ...]  │
│    with lat/lon pin,     │  Lat: [38.00°N] Lon: [102.00°E]          │
│    drag-to-reposition]   │  ─────────────────────────────────────── │
│                          │  DEVICE FLEET                             │
│   Lat: [38.00°N]         │  ┌──────────────────────────────────────┐│
│   Lon: [102.00°E]        │  │ ID               Qty  Nameplate  Total││
│   [Locate on map]        │  │ vestas-v150-4.2  100  4.2 MW  420 MW ││
│                          │  │ trina-vertex-n   …    …       …      ││
│                          │  │ catl-lmp-300mwh  1    294.5MWh        ││
│                          │  │ pcc-substation   1    945 MW          ││
│                          │  │ [+ Add device]                       ││
│                          │  └──────────────────────────────────────┘│
│                          │  Site total: 615 MW wind + 330 MWp PV    │
│                          │             + 294.5 MWh storage          │
│                          │  ─────────────────────────────────────── │
│                          │  Tariff: [Gansu TOU v2024   ▼]           │
│                          │  Scenario: [● Power supply ○ (future)]   │
│                          │  ─────────────────────────────────────── │
│                          │  VALIDATION                               │
│                          │  ✓ Device IDs all resolve                 │
│                          │  ⚠ Lat/lon outside Open-Meteo coverage   │
│                          │    (historical weather unavailable)       │
├──────────────────────────────────────────────────────────────────────┤
│  [← Back]                                       [Save & Continue →] │
│                                      (disabled while hard errors)    │
└──────────────────────────────────────────────────────────────────────┘
```

### Key interaction rules
- **Lat/lon ↔ map pin** — bidirectional; typing updates the pin, dragging updates the fields
- **No-map fallback** — if tiles fail, lat/lon text fields remain the authoritative input (no degradation of function)
- **Validation source — backend endpoint, not TS** — the Config stage calls `POST /api/site/validate` on every meaningful change (debounced 300 ms) and renders the response. The endpoint returns `{errors: [{field, message}], warnings: [{field, message}]}` with **field-level, numbers-shown messages** — e.g.:
  ```
  { "field": "catl-lmp-300mwh.c_rate", "message": "98.16 MW / 294.5 MWh = 0.33 C — OK (limit 0.5 C)" }
  { "field": "vestas-v150-4.2.count", "message": "100 × 4.2 MW = 420 MW total — valid" }
  { "field": "lat", "message": "38.0°N — inside Open-Meteo coverage ✓" }
  ```
  The UI **never recomputes physics or constraint math client-side** — the backend is the single source of truth (no TS implementation of C-rate, SOC bounds, etc.).
- **Device ID validation** — device IDs must exist in `config/device_models.yaml`; a missing ID shows a hard error inline: `✗ "my-custom-turbine" not found in device library` — blocks Save. The validation endpoint surfaces this.
- **Fleet total preview** — site totals (MW wind, MWp PV, MWh storage) come from the **server-side resolver** (`GET /api/site/resolve`), not TS calculation, so the preview matches what the env actually builds (master_plan §3)
- **Validation tiers:**
  - **Hard errors** (red `✗`) — block "Save & Continue": missing device IDs, invalid lat/lon range, C-rate/SOC constraint violations, no devices of required type. Cannot proceed.
  - **Soft warnings** (amber `⚠`) — shown with a per-warning Acknowledge button; user must explicitly dismiss each before proceeding (not silently bypassed). Example: "Historical weather coverage: 2 years available (2022–2023) — short horizon may affect training diversity."
- **Edit mode (Class A confirmation)** — when stage is COMPLETE, any field change immediately triggers the two-step modal: "⚠ Changing Config will mark Train, Eval, and Finance as **stale** (results preserved but no longer current). Continue editing?" → [Cancel] [Edit Anyway]. If dismissed, the field reverts. If confirmed, STALE propagates to ③④⑤ immediately.
- **Weather mode** — three-way selector: Synthetic / Historical / Bootstrap (§2/§3 map modes from master_plan §3); historical/bootstrap gated on data-availability for the chosen lat/lon

### Units displayed
- Device capacity: MW (wind/solar generators), MWh (storage), MW (grid connection)
- Site totals: MW wind, MWp PV, MWh / MW battery, MW load range
- Tariff: ¥/MWh (shown in tooltip on tariff selector)
- Lat: decimal degrees (°N/°S), Lon: decimal degrees (°E/°W)

---

## 5. Stage 2 — Algorithm Select

### Purpose
Choose the training algorithm (SAC) and baseline policies to compare against. Configure hyperparameters.

### Layout
```
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 2: ALGORITHM                                    [● Pending]   │
├──────────────────────────────────────────────────────────────────────┤
│  SELECT TRAINING ALGORITHM                                           │
│                                                                      │
│  ┌───────────────────┐  ┌───────────────────┐  ┌─────────────────┐  │
│  │  ★ SAC            │  │  TOU Rule-based   │  │  No-Battery     │  │
│  │  (Recommended)    │  │  Baseline         │  │  Baseline       │  │
│  │                   │  │                   │  │                 │  │
│  │  Soft Actor-Critic│  │  Discharge peak,  │  │  No dispatch;   │  │
│  │  RL policy; learns│  │  charge valley —  │  │  grid-only      │  │
│  │  dispatch from    │  │  deterministic    │  │  reference.     │  │
│  │  experience.      │  │  rule.            │  │                 │  │
│  │                   │  │                   │  │  ☑ Include      │  │
│  │  ● Primary        │  │  ☑ Include        │  │    in eval      │  │
│  │    (train this)   │  │    in eval        │  │                 │  │
│  └─[Selected]────────┘  └───────────────────┘  └─────────────────┘  │
│                                                                      │
│  SAC HYPERPARAMETERS                              [Reset to default] │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Learning rate (actor/critic):  [3e-4     ]  (default: 3e-4)  │  │
│  │  Replay buffer capacity:        [1 000 000]  (steps)          │  │
│  │  Batch size:                    [256      ]  (samples)        │  │
│  │  Discount γ:                    [0.99     ]                   │  │
│  │  Target network τ:              [5e-3     ]                   │  │
│  │  Hidden layer dims:             [256, 256 ]  (neurons/layer)  │  │
│  │  Training steps (total):        [3 000 000]  (env steps)      │  │
│  │  Eval interval:                 [10 000   ]  (steps)          │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  EVAL BASELINES SELECTED: TOU Rule-based ✓, No-Battery ✓            │
├──────────────────────────────────────────────────────────────────────┤
│  [← Back to Config]                       [Confirm & Continue →]    │
└──────────────────────────────────────────────────────────────────────┘
```

### Key interaction rules
- **Algorithm cards** — currently SAC is the only trainable option; baselines are "include in eval" toggles, not trainable. Cards use the same `.card` component as the dashboard
- **Hyperparameter form** — tabular layout, one param per row with: label, input field (validated), unit label (steps/samples/none), default value in muted text
- **Validation** — numeric ranges checked inline (e.g. γ must be 0–1, buffer ≥ batch_size × 10); invalid field shows red border + message
- **Reset to default** — restores all SAC params to spec §5 defaults
- **Baseline selection** — checkboxes; at minimum one baseline must be selected for eval to be meaningful (soft warning if none; can override)
- **No destructive state** — navigating back and forward preserves selections
- **Class A confirmation** — algorithm and hyperparam changes are Class A (physical config) edits (rl-architect ruling). If stage is COMPLETE, any change triggers the same two-step modal as Config edits: "Changing algorithm will mark Train, Eval, and Finance as stale." Field reverts on Cancel.

---

## 6. Stage 3 — Train

### Purpose
Launch, monitor, and complete a training run. Long-running async process (minutes to hours).

### Sub-states
Stage 3 has three internal sub-states, each with a distinct view:

#### 6.1 Pre-launch (PENDING)
```
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 3: TRAIN                                         [◌ Pending]  │
├──────────────────────────────────────────────────────────────────────┤
│  READY TO TRAIN                                                      │
│                                                                      │
│  ┌──────────────────────────────┐  ┌────────────────────────────┐   │
│  │  SITE                        │  │  ALGORITHM                  │   │
│  │  Gansu Wind Farm             │  │  SAC — 3 000 000 steps     │   │
│  │  615 MW + 330 MWp + 294.5MWh │  │  lr=3e-4  γ=0.99  τ=5e-3  │   │
│  │  Gansu TOU tariff            │  │  buffer=1M  batch=256      │   │
│  │  Power-supply scenario       │  │  Baselines: TOU + NoBat    │   │
│  └──────────────────────────────┘  └────────────────────────────┘   │
│                                                                      │
│  Estimated time: ~45 min (CPU) / ~4 min (GPU)                       │
│                                                                      │
│                        [▶ Start Training]                            │
├──────────────────────────────────────────────────────────────────────┤
│  [← Back to Algorithm]                                               │
└──────────────────────────────────────────────────────────────────────┘
```

#### 6.2 Running (IN_PROGRESS)
The existing TrainingPanel components mount here directly:

```
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 3: TRAIN                            [◈ Training — 1.2M steps]│
├──────────────────────────────────────────────────────────────────────┤
│  [StreamStatusBanner — if WS stale/gap/disconnected]                 │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  PROGRESS          1 234 567 / 3 000 000 steps  ██████░░ 41%│   │
│  │  Throughput: 87 340 steps/s  ·  Elapsed: 14.1 min            │   │
│  │  ETA: ~20 min remaining                                      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  [ThroughputCard]                                                    │
│  [MetricCurves — reward, critic loss, entropy, etc.]                 │
│  [CheckpointEventList]                                               │
│  [EvalCompareTable — appears when first eval result arrives]         │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  [⏸ Pause]  [⏹ Stop & Save]                                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  NOTE: You can navigate away and return — training continues         │
│  in the background. Progress shown in wizard bar (⑤ amber spinner). │
└──────────────────────────────────────────────────────────────────────┘
```

#### 6.3 Complete (COMPLETE)
```
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 3: TRAIN                                        [✓ Complete]  │
├──────────────────────────────────────────────────────────────────────┤
│  TRAINING COMPLETE                                                   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Run ID: abc-123  ·  3 000 000 steps  ·  Completed 14:32     │   │
│  │  Best checkpoint: step 2 950 000  ·  Eval reward: −0.041     │   │
│  │  Throughput: 91 200 steps/s avg  ·  Duration: 32.8 min       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  [View full training history ▾] (collapsible — MetricCurves below)  │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│  [← Back]        [Re-train (new run)]      [Proceed to Eval →]      │
└──────────────────────────────────────────────────────────────────────┘
```

### Key interaction rules
- **Background training** — training runs independently; user can navigate away; wizard bar shows amber spinner on stage ③
- **Page reload persistence** — wizard state (run_id, checkpoint_id, stage statuses) stored in `localStorage` so a page reload resumes the in-progress view
- **Pause/Stop** — Pause suspends the training stream; Stop saves the latest checkpoint and transitions to the "Complete" sub-state with a "Stopped early" badge
- **Stale re-entry** — if user edits Config/Algorithm after training is COMPLETE, stage 3 shows a STALE banner; user must click "Re-train" to produce new results

---

## 7. Stage 4 — Eval

### Purpose
Compare the trained RL policy against baselines across operating metrics.

### Layout
```
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 4: EVAL                                          [● Pending]  │
│  (STALE banner if training was re-run)                               │
├──────────────────────────────────────────────────────────────────────┤
│  POLICY EVALUATION — 8 760-step full-year run                       │
│                                                                      │
│  Checkpoint: [run abc-123, step 2 950 000  ▼]  [▶ Run Evaluation]  │
│                                                                      │
│  ── OPERATING RESULTS ─────────────────────────────────────────────  │
│                                                                      │
│  ┌────────────────────┬──────────────────┬──────────────┬─────────┐  │
│  │ Metric             │ RL (SAC)         │ TOU Rule     │ No Bat  │  │
│  ├────────────────────┼──────────────────┼──────────────┼─────────┤  │
│  │ Total cost (¥/yr)  │ −18 420 000      │ −16 110 000  │ −22 880K│  │
│  │ Energy cost (¥)    │ −12 340 000      │ −10 920 000  │ −19 450K│  │
│  │ Demand charge (¥)  │  −3 210 000      │  −3 890 000  │  −3 430K│  │
│  │ Degradation (¥)    │    −870 000      │    −300 000  │       0 │  │
│  │ Curtailment (¥)    │           0      │           0  │    0    │  │
│  │ VOLL (¥)           │           0      │           0  │       0 │  │
│  │ Export (MWh/yr)    │   1 234 567      │  1 198 340   │  1 078K │  │
│  │ Import (MWh/yr)    │     123 456      │    145 670   │   234K  │  │
│  │ Bat throughput(MWh)│     234 567      │     89 340   │       0 │  │
│  ├────────────────────┼──────────────────┼──────────────┼─────────┤  │
│  │ vs No-Battery (¥)  │  ▲ +4 460 000   │ ▲ +6 770 000 │ baseline│  │
│  └────────────────────┴──────────────────┴──────────────┴─────────┘  │
│                                                                      │
│  (all monetary values in ¥ nominal; negative = cost, positive = rev)│
│                                                                      │
│  P50 / P90 / P99: [single-draw M=1, point estimate — ensemble      │
│  exceedances available when §12 historical weather feeds M>1 draws]  │
├──────────────────────────────────────────────────────────────────────┤
│  [← Back]        [Re-run Eval]           [Proceed to Finance →]     │
└──────────────────────────────────────────────────────────────────────┘
```

### Key interaction rules
- **Checkpoint selector** — dropdown of saved checkpoints from the current run (step, eval-reward, timestamp); default is the highest-eval-reward checkpoint
- **Run Evaluation button** — triggers a full 8760-step eval; shows progress (step count / 8760, elapsed time)
- **Negative = cost** convention — explicit note in the UI to prevent sign confusion (matches D13 where costs are positive but displayed as negative net-revenue for intuitive reading)
- **vs No-Battery row** — always shown as an incremental comparison; positive = battery adds value (View II from master_plan §5.2)
- **Best-in-column** — the best (lowest cost / highest revenue) cell in each metric row is highlighted with a subtle green tint
- **Stale results** — if upstream changed, existing results are shown with amber "⚠ Stale — from a previous config" banner; buttons "Use stale for Finance" (with warning) or "Re-run Eval"

---

## 8. Stage 5 — Finance

### Purpose
Interactive project finance simulation: IRR/NPV/MIRR/LCOE over 10–20 year horizon, with live sensitivity controls.

### Layout — dual-panel with instant recompute
```
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 5: FINANCE                                    [● In Progress] │
│  [PROVENANCE: Gansu-v1 · SAC run abc-123 · power-supply · M=1 draw] │
├──────────────────────────────────────────────────────────────────────┤
│  ASSUMPTIONS                  │  RESULTS                            │
│  ─────────────────────────    │  ──────────────────────────────────  │
│  View:  [● I — Absolute]      │  HEADLINE METRICS  (View I, P50)    │
│         [○ II — Incremental]  │                                     │
│                               │  IRR          11.2 %                │
│  Horizon: [● 20 yr  ○ 10 yr] │  MIRR          9.8 %                │
│                               │  NPV (r=7%)  ¥ 142 M               │
│  Discount rate (WACC):        │  LCOE          ¥ 312 /MWh           │
│  3% ──────●────────── 12%    │  LCOS          ¥ 840 /MWh           │
│           7.0%                │  Payback       8.3 yr               │
│                               │  (Discounted)  11.4 yr              │
│  Entity boundary:             │                                     │
│  [● Merchant exporter]        │  ── CASH FLOW (¥M, years 0–20) ──  │
│  [○ Self-supply w/ load]      │                                     │
│                               │  [Bar/waterfall chart               │
│  Tax:   [☐ Enable 25%]       │   Year 0: −¥1.2B (CAPEX)           │
│  Debt:  [☐ Enable]            │   Years 1–9: +¥140–180M/yr         │
│                               │   Year 10: −¥290M (bat replace)    │
│  CAPEX SUMMARY (read-only)    │   Years 11–20: +¥150–190M/yr]      │
│  Wind:   ¥ 924 M              │                                     │
│  Solar:  ¥ 495 M              │  ── NPV vs DISCOUNT RATE ────────   │
│  Battery:¥ 294 M (×2 repl.)  │                                     │
│  Grid:   ¥  85 M              │  [Line chart: RL SAC, TOU, NoBat   │
│  ──────────────────           │   x=3–12%, y=NPV ¥M                │
│  Total:  ¥ 1.80 B             │   IRR = x-intercept markers]       │
│  Soft costs (8%): ¥ 144 M     │                                     │
│  ─────────────────────────    │  ── SENSITIVITY TORNADO ─────────   │
│  [↺ Reset assumptions]        │  [Horizontal bars ±ΔNPV:           │
│                               │   CAPEX ±20%, tariff ±2pp,         │
│                               │   bat lifetime, discount ±2pp,     │
│                               │   O&M ±20%, weather P50↔P90]       │
├──────────────────────────────────────────────────────────────────────┤
│  [← Back to Eval]                                     [Export PDF]  │
└──────────────────────────────────────────────────────────────────────┘
```

### Key interaction rules

#### Rate slider — instant recompute
- Discount-rate slider triggers an immediate client-side recompute of NPV/payback/DSCR (the cash-flow series is already loaded; only the discount-rate application changes)
- IRR/MIRR are precomputed (not rate-dependent); LCOE/LCOS are also precomputed
- **No server roundtrip on slider drag** — finance math lives client-side, using the loaded cash-flow series from `GET /api/finance/compare`
- The NPV-vs-rate chart redraws live as the slider moves; the vertical marker showing "current r" tracks the slider

#### View I / View II toggle
- **View I (Absolute)** — CAPEX basis = full plant (¥1.80 B); benefit = total annual operating net revenue
- **View II (Incremental storage)** — CAPEX basis = battery only (¥294 M + replacement); benefit = Δ(operating result) vs No-Battery baseline; headline becomes "Does the battery pay?"
- Toggle switches the CAPEX summary, headline metrics, and cash-flow chart instantly

#### Entity boundary toggle
- **Merchant exporter** — revenue = export MWh × tariff; cost = import MWh × tariff + demand charge
- **Self-supply w/ load** — revenue includes avoided grid cost for factory load (50–100 MW); changes OPEX/revenue decomposition but not total (a reconciliation aid)

#### Provenance banner
- Always visible: checkpoint_id · weather_mode · scenario · M · discount-rate assumption · horizon
- **Comparison guard** — if two policies were evaluated under different weather modes or scenarios, the results panel shows a hard warning: "⚠ Mismatched assumptions — these results are not directly comparable" (per master_plan §5.11 correctness guard)

#### Tax & debt overlays
- Tax toggle shows: corporate tax rate (25% / 15% renewable), depreciation (straight-line, N years)
- Debt toggle shows: gearing %, interest rate %, term (years); adds Equity IRR and min-DSCR to headline
- Both shown as **deltas to the base case**: "with debt: equity IRR +2.1 pp vs unlevered"

#### Units
- Monetary: ¥ millions (¥M) on charts; ¥ full value on headline cards
- Rates: % (IRR, MIRR, WACC, tax rate)
- Energy metrics: ¥/MWh (LCOE, LCOS)
- Time: yr (payback, horizon, depreciation)
- Power/energy: MW, MWh (CAPEX breakdown, site totals)

---

## 9. Cross-cutting UX patterns

### 9.1 Navigation rules
- **Forward**: "Save & Continue" / "Confirm & Continue" / "Proceed to →" — only enabled when the current stage has valid output
- **Backward**: "← Back" — always available, no consequence (state preserved)
- **Direct stage jump** — clicking a COMPLETE or STALE stage in the wizard bar navigates directly; LOCKED stages are non-clickable (cursor: not-allowed)
- **Browser back/forward** — wizard stage is part of the URL (`/wizard/config`, `/wizard/algo`, `/wizard/train`, `/wizard/eval`, `/wizard/finance`); browser nav works correctly

### 9.2 Stale confirmation flow

**Class A edit** (physical config or algorithm change — the common path):
```
[User changes a Config or Algorithm field while that stage is COMPLETE]
         ↓
┌──────────────────────────────────────────────────┐
│  ⚠ Physical config change detected              │
│                                                  │
│  Changing [device count / tariff / algorithm]    │
│  will mark Train, Eval, and Finance as stale.    │
│  Their results remain visible but a new          │
│  training run is required before Finance         │
│  results can be trusted.                         │
│                                                  │
│  [Cancel — revert]         [Edit Anyway]         │
└──────────────────────────────────────────────────┘
         ↓ (on "Edit Anyway")
Stage 1 or 2 → EDIT mode (field change accepted)
Stages 3, 4, 5 → STALE (amber ⚠, unmissable banners)
```

**Class B edit** (finance assumptions — no confirmation needed):
```
[User moves discount-rate slider or toggles tax/debt in Finance stage]
         ↓
Finance results recompute instantly — no modal, no stale state
Stages 1–4 are UNAFFECTED (remain COMPLETE)
NPV/IRR/MIRR/payback update live as slider moves
```

**Why no modal for Class B:** the entire point of the finance playground is friction-free exploration. A confirmation modal on a slider drag would be the antithesis of the intended UX. Class B edits affect only the discount arithmetic on an already-loaded cash-flow series — they are reversible by moving the slider back, and no server data is invalidated.

### 9.3 Long-running operation feedback
Training can run for minutes to hours. The UX must survive:
- **Page reload** — wizard state persisted to localStorage (stage, run_id, checkpoint_id)
- **Navigation away** — wizard bar amber spinner persists; clicking stage ③ brings back the training monitor
- **WS reconnect** — existing StreamStatusBanner handles this; shown in the training stage view
- **Disconnect** — training runs server-side regardless; the WS reconnects automatically; final result fetched via REST on reconnect

### 9.4 Empty states
Each stage has a purposeful empty state when it's PENDING:
- Stage 1 PENDING: "Configure your site to begin." + starter content (Gansu defaults pre-filled)
- Stage 2 PENDING: Blocked by config — grey with "Complete Stage 1 first"
- Stage 3 PENDING: Pre-launch summary + Start Training button (see §6.1)
- Stage 4 PENDING: "Run evaluation to see policy comparison" + Run button
- Stage 5 PENDING: "Complete Eval to unlock Finance simulation"

### 9.5 Error surfaces
| Error type | Where shown | UX treatment |
|---|---|---|
| Config validation (hard) | Inline in Config form | Red `✗` badge, message, blocks Save |
| Config validation (warning) | Inline in Config form | Amber `⚠` badge + Acknowledge button |
| Device ID not in schema | Inline device row | Red `✗` "ID not found in library" |
| Training crash | Training monitor banner | StreamStatusBanner (existing) + "View log" |
| Eval timeout / API error | Eval stage banner | Error card (existing ErrorBoundary) |
| Finance API error | Finance results panel | Inline error card, "Retry" button |
| WS disconnected | Wizard bar + stage banner | Existing StreamStatusBanner |

---

## 10. Visual language — tokens and components

The wizard inherits the existing dark engineering-dashboard aesthetic unchanged. All new surfaces use the same design tokens:

| Token | Value | Usage |
|---|---|---|
| `--bg-app` | `#0f1117` | App background |
| `--bg-card` | `#1e2533` | Card/panel background |
| `--bg-nav` | `#1a1f2e` | Top bar, wizard bar |
| `--border` | `#2d3748` | Card borders, table rules |
| `--text-primary` | `#e2e8f0` | Body text |
| `--text-muted` | `#94a3b8` | Labels, nav links inactive |
| `--text-faint` | `#64748b` | Card titles, placeholders |
| `--accent-blue` | `#60a5fa` | Active links, PENDING state |
| `--accent-green` | `#22c55e` | COMPLETE state, positive delta |
| `--accent-amber` | `#f59e0b` | STALE, IN_PROGRESS, warnings |
| `--accent-red` | `#f87171` | Hard errors |
| `--accent-grey` | `#4b5563` | LOCKED state |

**Proposed visual evolution** (separate USER review required — not in v1):
- Stage card headers could use a subtle gradient border (amber→blue progression) to communicate pipeline flow direction
- Finance sliders could use a step-marked track showing the WACC typical range for China utility-scale renewables
- These are proposals only — the existing flat style ships first

### Components to reuse (no new primitives required for the flow)
- `.card` + `.card__title` — stage content panels
- `StreamStatusBanner` — in training stage
- `ThroughputCard`, `MetricCurves`, `CheckpointEventList`, `EvalCompareTable` — mounted directly in training stage
- `TouBadge` — tariff display in config and finance
- `NumberDisplay` — all numeric values in eval + finance
- `ErrorBoundary` — per-stage wrapper

### New components required (to be specced in contracts)
- `WizardBar` — top stepper (replaces NavLinks); stage state badges
- `StageShell` — wrapper for each stage: header, stale banner slot, content, footer nav
- `MapPicker` — lat/lon + MapLibre tile view (or fallback text input)
- `DeviceFleetTable` — device rows, validation, add/remove
- `AlgorithmCard` — algo + baseline cards in stage 2
- `HyperparamForm` — SAC config form
- `ProgressBar` — training step progress (% + ETA)
- `FinanceAssumptionsPanel` — sliders + toggles
- `CashFlowChart` — year-by-year bar/waterfall
- `NpvCurveChart` — NPV vs discount rate (overlaid lines, per policy)
- `TornadoChart` — sensitivity bar chart

---

## 11. Open questions for team-lead / USER review

**Resolved by rl-architect ruling (2026-06-12):**
- ~~Finance recompute mechanism~~ — **RESOLVED**: discount-rate slider = instant client-side recompute on the loaded cash-flow series (Class B edit, no server roundtrip on drag). Tax/debt toggles also client-side (reload from loaded series, no new dispatch). Both are Class B: zero upstream invalidation.
- ~~Algorithm edit class~~ — **RESOLVED**: algorithm choice and hyperparams are Class A (physical config). Same stale-propagation as Config edits: ③④⑤ marked STALE.
- ~~Validation source~~ — **RESOLVED**: backend validate endpoint (`POST /api/site/validate`) is the single source; returns `{errors[], warnings[]}` with field-level, numbers-shown messages. No TS reimplementation. (See also task #66 — `config_validation` sibling contract.)

**Still open — for USER:**

1. **Stale vs. reset on Config edit** — when a Config edit marks Algorithm (stage ②) stale, should the algorithm selection be preserved as-is (STALE) or cleared to defaults (PENDING)? Current proposal: STALE (preserve selection — the user made deliberate choices; they just need to re-confirm by re-running train). Alternative: clear to PENDING (cleaner but loses hyperparam work). USER preference?

2. **Auto-eval after training** — should training completion automatically trigger an eval run with the best checkpoint and default baselines, or always require explicit user action? Auto-eval is ergonomic; explicit is transparent (uses compute with consent). Proposal: offer a "Run eval automatically on completion" checkbox in the Stage 3 pre-launch screen.

3. **Multiple runs per config** — one canonical "current run" per config (v1 proposal), or side-by-side run comparison? Prior runs accessible via a collapsible Run History panel in stage ③, but Finance always uses the canonical/best checkpoint. Confirm scope for v1.

4. **Scenario selector display** — Config stage shows Scenario = "Power supply" (only v1 option). Show other scenarios greyed-out with "(Coming soon)" to communicate expansion roadmap, or hide entirely? Prefer visible-but-disabled (honest about future scope); confirm with USER.

5. **Raw `/training` and `/eval` routes** — preserve as power-user direct-access paths (debugging, CI runs) with a small "← Wizard" back-link? Or fully replace with wizard-only? Proposal: preserve (the existing TrainingPanel mounts unchanged inside the wizard stage and at the direct route — no duplication).

6. **D32 scope** — rl-architect is writing the product-spine amendment (D32, task #64). Once it lands, it may refine some details here (e.g. validation endpoint contract shape, wizard state persistence rules). This doc will be updated to align.

---

## 12. Next steps (pending USER/team-lead direction)

After this flow document is reviewed and course-corrections incorporated:

1. **Per-screen layout docs** — detailed wireframes for each stage in `docs/design/ux/stage_N_*.md`
2. **Component inventory doc** — prop specs for each new component listed in §10
3. **design_system.md coordination** — once task #59 (frontend-engineer codifying the design system) lands, integrate tokens and evolve style if USER approves
4. **Frontend contracts** — `contracts/frontend/wizard_shell.md`, `contracts/frontend/stage_config.md`, etc. (frontend-reviewer gates; authored AFTER USER design review)

---

*docs/design/ux/wizard_flow.md — ui-designer, task #65, 2026-06-11*
