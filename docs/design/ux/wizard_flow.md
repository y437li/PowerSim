# Five-Stage Pipeline Wizard — UX Flow & Interaction Design

> **Owner:** ui-designer · **Task:** #65
> **Status:** DRAFT v0.4 — adds full finance assumptions panel (all params front-loaded, CAPM decomposition, provenance badges, assumptions strip); closes Q1 stale-preserve + Q6 raw routes; all 6 questions resolved (2026-06-12)
> **Gate:** USER reviews aesthetic direction before frontend contracts are written against this.
> **Inputs:** master_plan_geo_finance.md (workstreams A/E), REBUILD_SPEC §3–§5, existing app at http://localhost:15174
> **Pending reference:** D32 product-spine amendment (task #64) — once landed in `docs/design/`, supersedes any conflicts here

---

## 1. Product intent

The wizard is the product's **primary flow** (USER directive). It guides the operator from a bare site config through to a project finance simulation, with five sequentially-dependent stages:

```
Config → Algorithm → Train → Eval → Finance
  (1)       (2)       (3)     (4)      (5)
```

**Core model (USER revision 2026-06-12):** Train and Eval are **decoupled**. Training produces artifacts (checkpoints + baselines) into a persistent **policy library**. Eval is a deliberate selection stage: pick a (policy, environment config) pair and run a full evaluation. Multiple eval results can coexist; Finance picks which eval result feeds it. This makes cross-eval (running a policy trained on config A against env config B) a first-class robustness check, not a mistake.

The existing app has three isolated routes (`/`, `/training`, `/eval`). The wizard **replaces the flat nav** with a structured pipeline that preserves the same underlying components (TrainingPanel, EvalComparison, SiteView) and wraps them in the stage shell.

---

## 2. Stage dependency model — the core design rule

### 2.0 Two edit classes — the product asymmetry *(rl-architect ruling + USER revision, 2026-06-12)*

The entire wizard UX is built on **one architectural asymmetry**:

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │  CLASS A — Physical config edits                                    │
 │  (fleet sizing · device model · tariff shape · algorithm choice)   │
 │  → ③ Train is the primary concern: new training needed to get a   │
 │    policy reflecting the new config                                 │
 │  → ④ Eval + ⑤ Finance surface provenance but are NOT auto-stale   │
 │    (eval is an explicit selection; old eval results remain valid   │
 │     for their recorded config, shown in provenance banners)        │
 │  → Unmissable notice in ③: "Current config differs from            │
 │    policies in library — train a new policy to reflect it"         │
 └─────────────────────────────────────────────────────────────────────┘
 ┌─────────────────────────────────────────────────────────────────────┐
 │  CLASS B — Finance-only edits                                       │
 │  (discount rate · escalation %/yr · currency)                      │
 │  → ⑤ Finance recomputes INSTANTLY, client-side, no re-dispatch     │
 │    IRR/NPV/MIRR/LCOE update live as the slider moves               │
 │  → ALL OTHER stages unaffected                                      │
 └─────────────────────────────────────────────────────────────────────┘
 ┌─────────────────────────────────────────────────────────────────────┐
 │  CLASS C — Finance structure edits                                  │
 │  (tax/debt toggle, gearing %, interest rate — structural changes)  │
 │  → ⑤ Finance recomputes server-side (heavier, not slider-speed)    │
 │  → Shows loading state in results panel; all other stages unchanged │
 └─────────────────────────────────────────────────────────────────────┘
```

This asymmetry *is* the product experience: the upstream pipeline is heavyweight and correct (physics drives economics); eval is deliberate and provenance-visible; finance is an instant-playground downstream. The UX must make all three tiers feel right.

**Algorithm choice is Class A** (not a separate class): choosing SAC vs. another algorithm, or changing SAC hyperparameters, is equivalent to a physical config change — it requires a new training run. The two-card "Algorithm" stage feeds directly into Train.

**Eval is NOT in the stale cascade** (USER revision): because eval is a deliberate (policy × env) selection with explicit provenance, a Config change does not auto-cascade to ④⑤. Old eval results are valid records — they still tell you exactly what they measured. The design surfaces mismatches through provenance labels, not blocking stale states.

### 2.1 Dependency graph

```
 Config → Algorithm → [Policy Library] ← Train (adds policies)
              ↑                ↓
        Class A edit   Eval picks (policy × env)
        notes mismatch         ↓
                          Finance picks eval result
                               ↓
                       Class B/C edits recompute ⑤ only
```

| Edit trigger | Edit class | Primary effect | UX treatment |
|---|---|---|---|
| Config: fleet sizing, device model, tariff | **A — physical** | ③ Train notes config mismatch | Amber notice in ③: "Train a new policy to reflect current config" |
| Algorithm: choice or any hyperparam | **A — physical** | ③ Train notes algo mismatch | Amber notice in ③: "Current settings differ from library policies" |
| Train run completes | — | New checkpoint enters policy library | ③ shows "Added to library: run-xyz" |
| Eval: different (policy, env) selection | — | Previous eval result remains; new result added | ④ shows list of all eval results; ⑤ picks which one |
| Finance: discount rate, escalation, currency | **B — finance-only** | ⑤ instant client-side recompute | No modal; IRR/NPV/LCOE update live on drag |
| Finance: tax/debt structure toggle | **C — finance structure** | ⑤ server-side recompute | Loading state in results panel; ~1–3 s |

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

### 2.3 State semantics per stage

With decoupled eval, the state model differs by stage:

**Stages ③ Train, ④ Eval, ⑤ Finance — distinct semantics:**

| Stage | STALE means | LOCKED means |
|---|---|---|
| ③ Train | Current config/algo differs from all policies in the library; no policy matches the current setup | No policy library yet (never trained) |
| ④ Eval | — (eval results are explicit records; they don't become stale — their provenance is fixed) | No policy in the library to select from |
| ⑤ Finance | — (same — Finance is based on a selected eval result; its provenance is fixed) | No eval result to select from |

**Provenance banners replace the stale cascade for ④⑤:**
Rather than auto-marking ④⑤ stale when config changes, the design uses prominent provenance labels on eval and finance results:
- "Evaluated: policy run-abc-123 (SAC, 3M steps) · Gansu-v1 config #a1b2c3d4 · synthetic weather"
- If the user selects an eval result that was run against a different config than current: "ℹ Cross-eval: this policy was trained on config #old123, evaluated on config #new456. This is a valid robustness check."

**The unmissable alert stays in ③ Train** — when the current config/algorithm differs from existing library policies, the Train stage shows an amber notice (not blocking): "⚠ Current config differs from all trained policies — start a new run to train a policy with the current setup."

**LOCKED** = no upstream output yet; stage is greyed and non-enterable (cursor: not-allowed in wizard bar).
**PENDING** = prerequisites met, not yet started.
**IN_PROGRESS** = actively running.
**COMPLETE** = at least one result exists for this stage.

The same visual language applies: amber = informational/mismatch, green = clean/current, grey = unavailable.

---

## 3. Wizard chrome — the top stepper bar

The wizard bar persists across all routes, replacing the current flat NavLinks:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚡ Energy GO                                                        ▸ Docs │
├─────────────────────────────────────────────────────────────────────────────┤
│  ① Config       → ② Algorithm  → ③ Train       → ④ Eval        → ⑤ Finance │
│  ✓ Gansu-v1        ✓ SAC          ✓ 3 policies   ● Running       🔒 Locked │
└─────────────────────────────────────────────────────────────────────────────┘
```

Each stage node in the bar:
- **Icon** — state icon (see §2.3)
- **Number badge** — always shown (①–⑤)
- **Stage name** — always shown
- **Summary subtitle** — one-liner when COMPLETE (e.g. "Gansu-v1", "SAC lr=3e-4", "3 policies in library", "2 eval results", "IRR 11.2%")
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
│                          │  SCENARIO COMPOSITION                     │
│                          │  ☑ Power supply  [base — always active]  │
│                          │  (additional scenarios appear as they     │
│                          │   activate in future versions)            │
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
- **Edit mode (Class A notice)** — when stage is COMPLETE, any field change triggers an amber notice in Stage ③ (not a blocking modal): "Current config differs from trained policies — start a new run to train a policy with the current setup." Stage ③ is NOT hard-blocked; ④ and ⑤ retain their existing results with provenance labels. (No stale cascade to ④⑤ per the decoupled-eval model.)
- **Weather mode** — three-way selector: Synthetic / Historical / Bootstrap (§2/§3 map modes from master_plan §3); historical/bootstrap gated on data-availability for the chosen lat/lon
- **Scenario composition — multi-select composable toggles** (USER revision): scenario is not a single exclusive choice but a set of enabled device/stream groups composed onto the power base. For v1, only the power base is active and shown. When H₂ or datacenter scenarios activate in later versions, they appear as additional toggleable cards — each adding its device config section (e.g. electrolyzer fleet row, load_data_center row) and revenue streams. **Unactivated scenarios are HIDDEN entirely** (not greyed-out "coming soon") per USER decision. The layout must be designed to accommodate future toggles additively — no single-choice assumption baked in.

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
│  [← Back]   [+ Start another run]      [Go to Eval →]              │
└──────────────────────────────────────────────────────────────────────┘
```

The policy library sub-panel lists every run in the current session:
```
POLICY LIBRARY
┌────────────────────────────────────────────────────────────────────┐
│ #  Type    Name          Config    Algorithm  Steps   Best score   │
│ 1  RL      run-abc-123   #a1b2c3  SAC        3.0M    −0.041       │
│ 2  RL      run-def-456   #a1b2c3  SAC        2.0M    −0.049       │
│ ─  Base    TOU rule      —        —          —       (always avail)│
│ ─  Base    No-battery    —        —          —       (always avail)│
└────────────────────────────────────────────────────────────────────┘
```

### Key interaction rules
- **Policy library** — every completed training run's checkpoints are stored persistently; baselines are always available. The library is keyed by `(run_id, checkpoint_step)` and carries full provenance: `{config_hash, algorithm, hyperparams, steps, train_date, best_eval_reward}`.
- **Config-mismatch notice** — when the current Config/Algorithm differs from the most recent library entry, an amber notice appears (not blocking): "⚠ Current config differs from library policies (#a1b2c3 vs current #e5f6a7) — start a new run to train a policy with the current setup."
- **Background training** — training runs independently; user can navigate away; wizard bar shows amber spinner on stage ③
- **Page reload persistence** — wizard state (run_id, checkpoint_id, stage statuses) stored in `localStorage` so a page reload resumes the in-progress view
- **Pause/Stop** — Pause suspends the training stream; Stop saves the latest checkpoint and adds it to the policy library with a "Stopped early" badge

---

## 7. Stage 4 — Eval

### Purpose
**Evaluation workbench**: pick a (policy, environment config) pair and run a full 8760-step evaluation. Results accumulate — multiple eval results can coexist. Finance picks which eval result it uses. Cross-eval (a policy vs. a different env than it was trained on) is a first-class robustness check.

### Layout
```
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 4: EVAL                                       [✓ 2 results]  │
├──────────────────────────────────────────────────────────────────────┤
│  NEW EVALUATION RUN                                                  │
│                                                                      │
│  POLICY SELECTOR                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ ● RL    run-abc-123  SAC  3.0M steps  config #a1b2  −0.041  │   │
│  │ ○ RL    run-def-456  SAC  2.0M steps  config #a1b2  −0.049  │   │
│  │ ○ Base  TOU rule-based                                       │   │
│  │ ○ Base  No-battery                                           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ENVIRONMENT CONFIG                                                  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ ● Current config (Gansu-v1 · #a1b2c3d4 · synthetic)         │   │
│  │ ○ Gansu-v1 · historical weather 2022                         │   │
│  │ ○ Other saved config...                                      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  COMPATIBILITY CHECK                                                 │
│  ✓ run-abc-123 obs_dim=107, action_dim=6 matches env               │
│    (power scenario, 6-action power dispatch)                        │
│                                                                      │
│  PROVENANCE PREVIEW                                                  │
│  Policy trained on: Gansu-v1 config #a1b2c3d4 (synthetic)          │
│  Evaluating on:     Gansu-v1 config #a1b2c3d4 (synthetic) [same]   │
│  ℹ Cross-eval? Different configs selected — results show            │
│    how the policy generalises beyond its training distribution.     │
│                                                                      │
│  [▶ Run Evaluation — 8 760 steps, ~3 min]                          │
├──────────────────────────────────────────────────────────────────────┤
│  EVAL RESULTS LIBRARY                                                │
│                                                                      │
│  ┌──────────────┬───────────┬──────────┬──────────────┬──────────┐  │
│  │ # Policy      │ Env       │ Date     │ Total ¥/yr   │         │  │
│  ├──────────────┼───────────┼──────────┼──────────────┼──────────┤  │
│  │ 1 SAC abc-123 │ Gansu syn │ Jun 11   │ −18 420 000  │ [View]  │  │
│  │              │           │          │              │ [→ Fin.] │  │
│  │ 2 SAC abc-123 │ Gansu his │ Jun 11   │ −17 890 000  │ [View]  │  │
│  │              │           │          │              │ [→ Fin.] │  │
│  └──────────────┴───────────┴──────────┴──────────────┴──────────┘  │
│                                                                      │
│  (click [View] to expand full metric table below)                   │
│                                                                      │
│  ── EXPANDED: Eval #1 — SAC run-abc-123 · Gansu-v1 synthetic ─────  │
│  ┌─────────────────────┬──────────────┬──────────────┬───────────┐  │
│  │ Metric              │ RL (SAC)     │ TOU Rule     │ No Bat    │  │
│  ├─────────────────────┼──────────────┼──────────────┼───────────┤  │
│  │ Total cost (¥/yr)   │ −18 420 000  │ −16 110 000  │ −22 880K  │  │
│  │ Energy cost (¥)     │ −12 340 000  │ −10 920 000  │ −19 450K  │  │
│  │ Demand charge (¥)   │  −3 210 000  │  −3 890 000  │  −3 430K  │  │
│  │ Degradation (¥)     │    −870 000  │    −300 000  │        0  │  │
│  │ Curtailment (¥)     │          0   │          0   │        0  │  │
│  │ VOLL (¥)            │          0   │          0   │        0  │  │
│  │ Export (MWh/yr)     │  1 234 567   │  1 198 340   │  1 078K   │  │
│  │ Import (MWh/yr)     │    123 456   │    145 670   │    234K   │  │
│  │ Bat throughput (MWh)│    234 567   │     89 340   │        0  │  │
│  ├─────────────────────┼──────────────┼──────────────┼───────────┤  │
│  │ vs No-Battery (¥)   │ ▲+4 460 000 │ ▲+6 770 000  │ baseline  │  │
│  └─────────────────────┴──────────────┴──────────────┴───────────┘  │
│  (¥ nominal; negative = net cost; positive vs No-Bat = value added) │
│                                                                      │
│  P50/P90/P99: v1 = point estimate (M=1 draw). Ensemble              │
│  exceedances activate when §12 historical weather feeds M>1 draws.  │
├──────────────────────────────────────────────────────────────────────┤
│  [← Back to Train]                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

### Key interaction rules
- **Policy selector** — shows all policies in the library (all training runs' best checkpoints + baselines). Keyed by `(run_id, step)` with provenance labels.
- **Env config selector** — defaults to current config; can also select any previously-saved config. The pair `(policy, env_config)` is the unit of an eval run.
- **Compatibility check** — **backend-validated**: when a (policy, env) pair is selected, `GET /api/eval/check-compat?policy_id=…&config_hash=…` returns `{compatible: bool, reason: string}`. Incompatible pairs (obs_dim mismatch, action_dim mismatch, scenario mismatch) are shown greyed with the reason: "⊗ Policy trained on 6-action power scenario; env resolves to 8-action H₂ scenario — incompatible." Compatible pairs with dimension match are immediately runnable.
- **Cross-eval provenance** — when trained-on config ≠ eval env config, a blue `ℹ` notice explains: "Cross-eval: policy generalisation check. Results show how this policy performs on a different site/weather/tariff than its training distribution." Not a warning — cross-eval is intentional.
- **Accumulating results** — each eval run appends to the Eval Results Library; results are never overwritten. `[→ Finance]` button sends a specific eval result to Stage ⑤.
- **Auto-select in Finance** — clicking `[→ Finance]` on any result pre-populates Stage ⑤ with that result and navigates there.
- **Best-in-column** — in the expanded metric table, the best value per row is highlighted with a subtle green tint (lowest net cost / highest net value).
- **Units** — all monetary values in ¥ nominal; sign convention: negative = cost/expense, positive = revenue added.

---

## 8. Stage 5 — Finance

### Purpose
Interactive project finance simulation: IRR/NPV/MIRR/LCOE over 10–20 year horizon, with live sensitivity controls.

### Design principle — full transparency of assumptions (USER directive)

**Every finance parameter is displayed and editable in the Finance panel — nothing is buried in config files or a settings page.** The compute-residency split (client-side vs server-side) is invisible plumbing; the user-facing rule is: adjust any assumption and the results update (some instantly, some after a brief compute). Each field shows its current value, its editable control, the default it came from (with a provenance badge), and a one-click ↺ reset. Grouped collapsible sections prevent overwhelm — but nothing is hidden, only collapsed.

Provenance badge system:
- `[USER-set]` — user explicitly typed or dragged this value
- `[benchmark-cited]` — default from the task #63 benchmark library (Chinese-market 2024/25 CAPEX/OPEX)
- `[CAPM-derived]` — computed from other parameters (e.g. WACC = r_f + β × ERP)
- `[tariff-default]` — derived from the site's tariff library entry
- `↺` — one-click reset to the tagged default; resets only that field

### Layout — full assumptions panel + results (dual-column)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 5: FINANCE                                           [✓ Complete]   │
│  EVAL BASIS: Eval #1 — SAC run-abc-123 · Gansu-v1 syn · Jun 11            │
│  [Change eval basis ▼]                                                     │
├──────────────────────────────┬──────────────────────────────────────────────┤
│  ASSUMPTIONS  [↺ Reset all] │  RESULTS                                    │
│  ─────────────────────────  │  ─────────────────────────────────────────  │
│                              │  HEADLINE METRICS (View I · 20yr · 7% WACC)│
│  ▾ DISCOUNT RATE (CAPM)     │  IRR           11.2 %                       │
│  ┌────────────────────────┐  │  MIRR           9.8 %                       │
│  │r_f  [10yr CNY ▼][2.85%]│  │  NPV @ 7%     ¥ 142 M                     │
│  │     [tariff-default] ↺ │  │  LCOE          ¥ 312 /MWh                  │
│  │β    [0.75] [bm-cited]↺ │  │  LCOS          ¥ 840 /MWh                  │
│  │ERP  [5.50%][CAPM-der.] │  │  Payback        8.3 yr  (disc.: 11.4 yr)   │
│  │─────────────────────── │  │                                             │
│  │WACC [8.96%][CAPM-der.] │  │  ── CURRENT ASSUMPTIONS ─────────────────  │
│  │Override WACC:           │  │  r_f 2.85% · β 0.75 · ERP 5.50%          │
│  │  3% ──●──── 12%  7.0%  │  │  → WACC 8.96%  (override: none)           │
│  │  (live drag, instant)   │  │  Horizon 20yr · View I · Merchant          │
│  └────────────────────────┘  │  Pre-tax · Synthetic weather · M=1         │
│                              │  Config #a1b2c3d4 · run-abc-123 · Jun 11   │
│  ▾ CAPITAL STRUCTURE        │  [Export assumptions sheet]                  │
│  ┌────────────────────────┐  │                                             │
│  │Tax [☐ Enable]          │  │  ── CASH FLOW (¥M, years 0–20) ──────────  │
│  │  (on: rate 25%, depr.) │  │  [Year 0: −¥1.80B CAPEX                    │
│  │Debt [☐ Enable]         │  │   Yrs 1–9: +¥140–180M/yr                   │
│  │  (on: D/E%, cost, term)│  │   Yr 10: −¥290M bat.replacement            │
│  └────────────────────────┘  │   Yrs 11–20: +¥150–190M/yr]                │
│                              │                                             │
│  ▾ ESCALATION / CURRENCY    │  ── NPV vs DISCOUNT RATE ──────────────────  │
│  ┌────────────────────────┐  │  [Overlaid lines: SAC · TOU · NoBat        │
│  │Tariff  [2.0 %/yr][U]↺ │  │   x=3–12%, IRR = x-intercept markers]     │
│  │OPEX    [3.0 %/yr][B]↺ │  │                                             │
│  │Currency[¥ nominal][B]↺ │  │  ── SENSITIVITY TORNADO ──────────────────  │
│  └────────────────────────┘  │  [±ΔNPV bars: CAPEX±20%, tariff±2pp,       │
│                              │   bat.lifetime, discount±2pp,              │
│  ▾ LIFECYCLE COSTS          │   O&M±20%, weather P50↔P90]                │
│  ┌────────────────────────┐  │                                             │
│  │Bat.repl. yr:[10][B] ↺  │  │                                             │
│  │Bat.repl. cost:          │  │                                             │
│  │  [¥ 294 M][B] ↺        │  │                                             │
│  │Overhaul [per device ▾] │  │                                             │
│  └────────────────────────┘  │                                             │
│                              │                                             │
│  ▾ CAPEX / OPEX OVERRIDES   │                                             │
│  ┌────────────────────────┐  │                                             │
│  │Wind    [9 240 ¥/kW][B]↺│  │                                             │
│  │Solar   [5 000 ¥/kW][B]↺│  │                                             │
│  │Battery [5 678¥/kWh][B]↺│  │                                             │
│  │Grid    [¥ 85 M ][B] ↺  │  │                                             │
│  │FixedOM [1.5 %/yr][B] ↺ │  │                                             │
│  │Soft c. [8.0 %  ][B] ↺  │  │                                             │
│  └────────────────────────┘  │                                             │
│                              │                                             │
│  ▾ ACCOUNTING               │                                             │
│  ┌────────────────────────┐  │                                             │
│  │View  [●I Abs.○II Incr.]│  │                                             │
│  │Horiz.[● 20yr  ○ 10yr]  │  │                                             │
│  │Bndry.[●Merch.○Self-sup]│  │                                             │
│  └────────────────────────┘  │                                             │
├──────────────────────────────┴──────────────────────────────────────────────┤
│  [← Back to Eval]                            [Export results + assumptions] │
└─────────────────────────────────────────────────────────────────────────────┘
```
Provenance badge key in wireframe: `[U]`=USER-set · `[B]`=benchmark-cited · `[C]`=CAPM-derived · `[T]`=tariff-default · `↺`=one-click reset

### Key interaction rules

#### Full assumptions transparency (USER directive, supersedes any prior design)
- **Every parameter is visible and editable in this panel** — no parameter lives only in a config file or a server-only settings page. CAPEX defaults come from the benchmark library (task #63); they are surfaced here with `[benchmark-cited]` badges and are fully overridable.
- **Provenance badge + reset on every field**: each editable control shows which default it came from, and a `↺` icon resets that single field to its tagged default. A global `[↺ Reset all]` button at the top restores all fields to their tagged defaults.
- **Grouped collapsible sections** (`▾ /▸` toggle): sections collapse to their header + key summary value. On first open, DISCOUNT RATE and ACCOUNTING are expanded; others collapsed. User can expand any section.

#### Eval basis picker
- Finance begins by selecting which eval result from Stage ④ to use (pre-selected if user clicked `[→ Finance]` from the Eval library). A compact "EVAL BASIS" strip at the top shows the selected eval + `[Change ▼]` dropdown. Switching triggers a full server-side recalculation of the finance model from the new eval result's operating data.
- **Provenance guard** — if the eval result was run against a different config than the current Config stage, a blue `ℹ` shows: "Eval was run against config #a1b2c3; your current config is #e5f6a7. Finance reflects that eval's results." Not blocking — the eval is a valid record.

#### Response behaviour per parameter (invisible plumbing — user sees instant vs "a beat")
| Parameter group | Response | Why |
|---|---|---|
| WACC override slider, escalation %, View I/II, horizon toggle, entity boundary | **Instant** (client-side) | Only discount arithmetic on loaded cash-flow series changes |
| r_f, β, ERP (→ WACC recompute), currency basis | **Instant** (WACC recomputed client-side, same series) | Derived discount-rate change |
| Tax enable/disable, debt enable/disable | **~1–3 s** (server-side) | Structural cash-flow change |
| CAPEX/OPEX overrides, lifecycle costs | **~1–3 s** (server-side) | Changes the cash-flow series itself |
| Eval basis switch | **~2–5 s** (server-side) | Full finance recompute from new operating data |

The panel never disables controls during computation — the loading state appears in the results panel only.

#### CAPM decomposition — WACC build-up visible to the user
- `r_f` (risk-free rate): selectable treasury tenor (1yr/5yr/10yr/30yr CNY, date-anchored); current value shown
- `β` (equity beta): editable; default from benchmark library for China utility-scale renewable
- `ERP` (equity risk premium): editable; benchmark default; auto-recomputes when `r_f` changes
- `WACC` readout: `= r_f + β × ERP`, shown with formula tooltip; not directly editable while CAPM is active
- **Override WACC** slider: when user drags it, the CAPM fields dim (shown as "overridden") and a `[↺ Restore CAPM]` button appears to re-derive WACC from r_f/β/ERP
- The user always sees exactly what discount rate is driving the NPV — no opaque single-number

#### Current assumptions strip — the investment-committee guard
- Always visible on the results side, above the headline metrics
- One-liner format: `r_f 2.85% · β 0.75 · ERP 5.50% → WACC 8.96% · 20yr · View I · Merchant · Pre-tax · Synthetic M=1 · Config #a1b2c3`
- **This strip appears on every exported result** (PDF, CSV) — finance results without visible assumptions are how mistakes get presented to investment committees
- If any field has been overridden from default, the strip shows the override: `WACC 7.0% (overridden, CAPM would give 8.96%)`

#### Comparison-assumptions guard (from master_plan §5.11)
- If two policies' finance results are shown side-by-side and their assumptions differ (different WACC, horizon, or eval basis weather-mode), a hard warning appears: "⚠ Mismatched assumptions — direct comparison unreliable." The strip makes the mismatch explicit; the user must acknowledge before proceeding.

#### Export
- `[Export results + assumptions]` produces a self-contained file (CSV or PDF) containing: headline metrics table, cash-flow series by year, NPV-vs-rate data, sensitivity inputs, **and the full current assumptions as a structured block**. A result without its assumptions is not a valid deliverable.

#### Units
- Monetary: ¥ millions (¥M) on charts; ¥ full value on headline cards and assumption overrides
- Rates: % (IRR, MIRR, WACC, r_f, ERP, tax rate, escalation)
- Energy metrics: ¥/MWh (LCOE, LCOS)
- Time: yr (payback, horizon, depreciation, lifecycle)
- CAPEX: ¥/kW (wind, solar), ¥/kWh (battery), ¥ lump (grid, soft costs)

---

## 9. Cross-cutting UX patterns

### 9.1 Navigation rules
- **Forward**: "Save & Continue" / "Confirm & Continue" / "Proceed to →" — only enabled when the current stage has valid output
- **Backward**: "← Back" — always available, no consequence (state preserved)
- **Direct stage jump** — clicking a COMPLETE or STALE stage in the wizard bar navigates directly; LOCKED stages are non-clickable (cursor: not-allowed)
- **Browser back/forward** — wizard stage is part of the URL (`/wizard/config`, `/wizard/algo`, `/wizard/train`, `/wizard/eval`, `/wizard/finance`); browser nav works correctly

### 9.2 Edit-class flow summary

**Class A edit** (physical config or algorithm change):
```
[User changes Config or Algorithm field]
         ↓
Change accepted immediately — NO blocking modal
         ↓
Stage ③ Train: amber informational notice appears
  "⚠ Current config differs from library policies (#a1b2c3 vs #e5f6a7)
   Start a new run to train a policy with the current setup."
Stage ④ Eval: unaffected — existing results stay valid with provenance
Stage ⑤ Finance: unaffected — provenance banner shows which eval/config it used
```

*Why no modal:* with decoupled eval, existing eval/finance results are records of what was measured — they don't become wrong. Only future training is affected. The amber notice in ③ is sufficient signal.

**Class B edit** (discount rate, escalation, currency — finance playground):
```
[User moves discount-rate slider or adjusts escalation]
         ↓
Finance ⑤ results recompute instantly — client-side only, no modal
All other stages UNAFFECTED (remain at their current state)
NPV/IRR/MIRR/payback/LCOE update live as slider moves
```

**Class C edit** (tax/debt structure toggle — heavier finance change):
```
[User toggles Tax Enable or Debt Enable]
         ↓
Finance ⑤ results show loading state (~1–3 s) — server-side recompute
All other stages UNAFFECTED
New results replace the current finance view for this eval basis
```

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
- `WizardBar` — top stepper (replaces NavLinks); stage state badges; provenance subtitle per stage
- `StageShell` — wrapper for each stage: header, provenance/mismatch notice slot, content, footer nav
- `MapPicker` — lat/lon + MapLibre tile view (or fallback text input)
- `DeviceFleetTable` — device rows, validation, add/remove; scenario-group layout (composable)
- `ScenarioComposer` — multi-select composable scenario toggles (v1: single "power supply" always-on; additive for future groups)
- `PolicyLibrary` — list of training runs + baselines with provenance; used in Stage ③ and Stage ④
- `EvalPicker` — (policy × env config) selector with backend compatibility check; provenance preview
- `EvalResultLibrary` — accumulating list of eval results; each row has [View] + [→ Finance] actions
- `CompatibilityBadge` — shows ✓ / ⊗ + reason for (policy, env) compatibility
- `ProvenanceBanner` — shows config hash, algo, weather mode, date for any result; highlights cross-eval
- `AlgorithmCard` — algo + baseline cards in stage 2
- `HyperparamForm` — SAC config form
- `ProgressBar` — training step progress (% + ETA)
- `FinanceAssumptionsPanel` — full collapsible assumptions panel: six grouped sections (Discount Rate / Capital Structure / Escalation / Lifecycle / CAPEX-OPEX / Accounting), each field with value + provenance badge + ↺ reset; global reset-all
- `CAPMBuilder` — r_f (tenor picker) + β + ERP → WACC build-up with override slider; shows formula tooltip; `[↺ Restore CAPM]` when overridden
- `AssumptionField` — single-field primitive: editable control + provenance badge + ↺; used throughout `FinanceAssumptionsPanel`
- `AssumptionsStrip` — always-visible one-liner summary of current assumptions (appears on results panel AND on every export); highlights overrides; mismatch warning
- `CashFlowChart` — year-by-year bar/waterfall with replacement-year markers
- `NpvCurveChart` — NPV vs discount rate (overlaid lines, per policy), IRR x-intercept markers
- `TornadoChart` — sensitivity bar chart, ±ΔNPV ranked

---

## 11. Open questions — resolution log

**Resolved by rl-architect ruling (2026-06-12):**
- ~~Finance recompute mechanism~~ — **RESOLVED** (Class B/C split): discount-rate/escalation/sensitivity = client-side instant; tax/debt structure = server-side (~1–3 s). Updated throughout.
- ~~Algorithm edit class~~ — **RESOLVED**: algorithm + hyperparams = Class A (physical config). Amber notice in ③, no cascade to ④⑤.
- ~~Validation source~~ — **RESOLVED**: `POST /api/site/validate` backend endpoint, `{errors[], warnings[]}` with field-level numbers-shown messages. No TS reimplementation.

**Resolved by USER revision (2026-06-12):**
- ~~Auto-eval after training (Q2)~~ — **RESOLVED: NO, manual, decoupled by design.** Eval is an explicit (policy × env) selection stage, not auto-chained. Eval workbench updated.
- ~~Multiple runs per config (Q3)~~ — **RESOLVED: YES, policy library is the model.** All training runs accumulate in the policy library; Finance picks from Eval Results Library. Not one canonical run.
- ~~Finance residency split (Q4)~~ — **RESOLVED: CONFIRMED SPLIT.** Client-side for sliders (Class B); server-side for tax/debt (Class C). Updated in §8 and §9.2.
- ~~Scenario selector (Q5)~~ — **RESOLVED: HIDE unactivated scenarios entirely.** No "coming soon" placeholders. v1 shows only power supply. When H₂/datacenter activate they appear. Updated §4.
- ~~Scenario selection model~~ — **RESOLVED: multi-select composable toggles** (USER: "有可能氢和数据中心都有"). Not single-choice radio. Each activated group adds device config + revenue streams. Layout must not assume single-choice. Updated §4 and ScenarioComposer in §10.

**Resolved by USER (2026-06-12, "保留吧"):**
- ~~Stale vs. reset on Config/Algorithm edit (Q1)~~ — **RESOLVED: stale-preserve.** Upstream edits mark downstream training-run entries as mismatched (amber notice in ③) but do not reset or clear Algorithm selection. The user's deliberate hyperparam choices are preserved — they re-confirm by starting a new training run, not by re-typing.
- ~~Raw `/training` and `/eval` routes (Q6)~~ — **RESOLVED: keep both routes.** The raw routes remain as power-user direct-access paths (debugging, CI runs) with a small "← Wizard" back-link. The existing TrainingPanel mounts unchanged in both contexts — no code duplication.

**✅ All six questions resolved. No outstanding USER design questions remain.**

**Always pending:** D32 product-spine amendment (task #64) — once landed in `docs/design/`, it is the fixed reference and may refine details here (wizard state persistence, validation endpoint contract shape, policy-library storage). Alignment pass after D32 merges.

---

## 12. Next steps (pending USER/team-lead direction)

After this flow document is reviewed and course-corrections incorporated:

1. **Per-screen layout docs** — detailed wireframes for each stage in `docs/design/ux/stage_N_*.md`
2. **Component inventory doc** — prop specs for each new component listed in §10
3. **design_system.md coordination** — once task #59 (frontend-engineer codifying the design system) lands, integrate tokens and evolve style if USER approves
4. **Frontend contracts** — `contracts/frontend/wizard_shell.md`, `contracts/frontend/stage_config.md`, etc. (frontend-reviewer gates; authored AFTER USER design review)

---

*docs/design/ux/wizard_flow.md — ui-designer, task #65 — v0.1 2026-06-11 · v0.2 (rl-architect ruling) · v0.3 (USER: decouple eval, policy library, composable scenarios, finance split) · v0.4 2026-06-12 (USER: full finance assumptions panel, CAPM decomposition, provenance badges, assumptions strip; Q1+Q6 closed — all 6 resolved)*
