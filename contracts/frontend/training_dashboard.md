# Contract: Frontend Training Dashboard

- **Status:** DRAFT — awaiting VERDICT: APPROVE from frontend-reviewer
- **Spec:** REBUILD_SPEC.md §5 (training/eval), §7 (serving), §11 (baselines/comparison); telemetry schema `contracts/shared/telemetry_schema.md` v1.0.0 (LOCKED, PR #6)
- **Owner:** dashboard-engineer · **Reviewer:** frontend-reviewer
- **Area:** frontend
- **Route:** `/training` (shell's `TrainingPanel` route)
- **Depends on DECISIONS:** D3 (Δt=1h, ep 168/8760), D10 (demand charge monthly), D13 (real-money vs reward-basis split), D16 (STACK.md), D18 (machine-readable schema + golden fixtures), D19 (load params ×100)
- **Depends on contracts:** `contracts/frontend/app_shell.md` (APPROVED, PR #5) — stores, clients, shared types, `units.ts`; `contracts/shared/telemetry_schema.md` v1.0.0 (LOCKED)

## Purpose

A focused training process monitor that plugs into the shell's `/training` route. It surfaces the three questions a practitioner asks during a SAC run:

1. **Is training progressing?** (loss curves, entropy, reward trend, throughput)
2. **How does the trained policy compare to baselines?** (eval comparison table — RL vs no-battery, rule-based TOU, and any future §11 benchmark policies)
3. **Which run am I watching, and can I switch?** (run history via REST)

**Explicitly excluded:** the 3D simulator, per-step env telemetry (`env_step`), live power flows, battery state, TOU bands. Those belong to `SiteView`. This view consumes only `train_metrics` and `eval_compare` messages.

---

## 1. File layout (within shell's `src/`)

```
src/
  routes/
    TrainingPanel.tsx       # Top-level route component (mounted at /training by shell)
  components/training/
    RunSelector.tsx         # REST-backed run picker
    MetricCurves.tsx        # Loss / reward / entropy line charts
    ThroughputCard.tsx      # Steps/s, global_step, wall time
    CheckpointEventList.tsx # Sorted list of eval checkpoint events
    EvalCompareTable.tsx    # RL vs baselines — all policy keys
    StreamStatusBanner.tsx  # Stale / gap / disconnected warning
```

All tests live under `tests/frontend/training_dashboard.test.tsx` (not next to source).

---

## 2. Types consumed (LOCKED — telemetry_schema.md v1.0.0)

All types are imported from the shell's `src/types/telemetry.ts`; they are reproduced here for contract clarity. **Do not redeclare them in the dashboard component files.** Any deviation from these exact field names is a contract violation.

### 2.1 `TrainMetricsPayload` (kind = "train_metrics")

```typescript
interface TrainMetricsPayload {
  global_step: number;                 // env steps consumed (x-axis for all curves)
  wall_seconds: number;                // producer wall-clock seconds since run start
  env_steps_per_sec: number;           // throughput; §7 target 1e6–1e7
  actor_loss: number;
  critic_loss: number;
  ent_coef: number;                    // SAC entropy coefficient (auto-tuned, §5)
  reward_scaled_mean: number;          // batch mean ×1e-5-scaled reward (unitless)
  reward_norm_mean: number | null;     // VecNormalize-normalized reward; NULL on eval checkpoints
  cost_total_real_mean_yuan: number;   // mean per-episode REAL-money cost (¥; negative = net revenue)
  is_eval_checkpoint: boolean;
  checkpoint_id: string | null;        // set when a checkpoint is written; null otherwise
  // Minor-compat note: future minor bumps may add replay_buffer_fill_fraction (number [0,1])
  // and other scalars. Components render optional fields when present; they never crash on absence.
  [key: string]: unknown;              // additionalProperties:true per schema minor-compat rule
}
```

### 2.2 `EvalComparePayload` (kind = "eval_compare")

```typescript
interface PolicyResult {
  energy_cost_yuan: number;
  demand_charge_yuan: number;
  degradation_yuan: number;
  curtailment_yuan: number;
  voll_yuan: number;
  total_cost_yuan: number;      // == energy_cost + demand_charge + degradation + curtailment + voll (real money)
  soc_violations_count: number; // safety metric — NOT in total_cost_yuan
  soc_violation_mwh: number;    // safety metric — NOT in total_cost_yuan
  penalty_yuan: number;         // reward-basis penalty — NOT in total_cost_yuan
}

interface EvalComparePayload {
  eval_horizon_steps: number;   // D3: 8760 at Δt=1h
  checkpoint_id: string;
  cost_basis: "real_money";     // always "real_money" per LOCKED schema
  policies: Record<string, PolicyResult>;
  // Known keys at v1.0.0: "rl", "no_battery", "rule_based_tou"
  // §11 baselines (greedy, dp_oracle, mpc, simulated_annealing, ant_colony) arrive as NEW KEYS;
  // the table MUST render any present key without code changes (iterate Object.keys, not a hardcoded list)
}
```

### 2.3 Shell store interfaces consumed (from `app_shell.md` §6)

```typescript
// trainingStore — import useTrainingStore from 'src/stores/trainingStore'
interface TrainingState {
  history: TrainMetricsPayload[];   // all received train_metrics, newest last
  latest: TrainMetricsPayload | null;
  receiveTrainMetrics(msg: TelemetryEnvelope & { payload: TrainMetricsPayload }): void;
  clear(): void;
}

// evalStore — import useEvalStore from 'src/stores/evalStore'
interface EvalState {
  latest: EvalComparePayload | null;
  history: EvalComparePayload[];    // ordered, newest last
  receiveEvalCompare(msg: TelemetryEnvelope & { payload: EvalComparePayload }): void;
  clear(): void;
}

// telemetryStore — read wsStatus only (NO env_step data consumed by this dashboard)
type WsStatus = "connecting" | "connected" | "disconnected" | "error";
interface TelemetryState {
  wsStatus: WsStatus;
  // (remaining fields not consumed by training dashboard)
}
```

---

## 3. Component interfaces

### 3.1 `TrainingPanel.tsx` (route component)

```typescript
// No props — reads directly from Zustand stores and restClient
function TrainingPanel(): JSX.Element;
```

Layout (top-to-bottom):
1. `StreamStatusBanner` — pinned below nav; only visible when stale/gap/disconnected
2. `RunSelector` — compact row at top
3. `ThroughputCard` — compact row below RunSelector
4. `MetricCurves` — main content area (charts)
5. `CheckpointEventList` — sidebar or below MetricCurves; shows checkpoint events
6. `EvalCompareTable` — below MetricCurves; shown only when `evalStore.latest !== null`

Empty state: when `trainingStore.history.length === 0` AND `wsStatus !== "error"`, render a centered placeholder: `"Waiting for training data…"` with a subtle spinner. No charts or table are rendered in this state.

### 3.2 `RunSelector`

```typescript
interface RunSelectorProps {
  restClient: RestClient;   // injected; from app_shell restClient.ts
}
function RunSelector({ restClient }: RunSelectorProps): JSX.Element;
```

Behavior:
- On mount, calls `restClient.getRuns()`. Renders a `<select>` with each `RunInfo.run_id` as an option, showing `run_id` + `status` badge.
- While loading: renders `"Loading runs…"` label.
- On REST error: renders `"Could not load runs"` with a retry button that calls `getRuns()` again.
- Empty list: renders `"No runs available"`.
- Run selection is display-only at this stage (the websocket stream is not re-targeted by this component; harness-engineer owns run switching).

### 3.3 `MetricCurves`

```typescript
interface MetricCurvesProps {
  history: TrainMetricsPayload[];  // from trainingStore.history
  // Chart library is dashboard-engineer's choice (Recharts recommended per STACK rationale;
  // any Vite-compatible tree-shakeable library is acceptable — record in STACK.md update)
}
function MetricCurves({ history }: MetricCurvesProps): JSX.Element;
```

Renders four panels, each a line chart with `global_step` on the x-axis:

| Panel | Y-axis field | Unit label | Notes |
|---|---|---|---|
| **Actor Loss** | `actor_loss` | (unitless) | |
| **Critic Loss** | `critic_loss` | (unitless) | |
| **Entropy Coeff** | `ent_coef` | (unitless) | |
| **Reward (scaled)** | `reward_scaled_mean` | (unitless, ×1e-5) | |

Additional series displayed together on a fifth panel:
| Panel | Y-axis fields | Unit label | Notes |
|---|---|---|---|
| **Episode Cost** | `cost_total_real_mean_yuan` | ¥ | Negative values = net revenue; axis must not clamp at 0 |

`reward_norm_mean` is NOT plotted — it uses a different normalization basis and is null on eval checkpoints, making it unsuitable for a continuous curve.

**Checkpoint markers:** at every point where `is_eval_checkpoint === true`, all four panels display a vertical reference line with a small label showing `checkpoint_id` (truncated to 10 chars). The marker color is distinct from line colors.

**Sparse/null handling:** `reward_norm_mean` is null on eval checkpoints — but since we don't plot it, no action needed. If future minor-compat additions introduce nullable fields on a plotted series, individual null points are rendered as gaps (not zero) to avoid misleading trend lines.

**Empty history:** renders the placeholder text `"No training data yet"` with no chart axes (not empty axes with NaN ticks).

**Buffer fill:** if a future train_metrics minor bump adds `replay_buffer_fill_fraction: number` (a [0,1] fraction), `MetricCurves` renders it as a background fill area or a sixth chart panel. Until it appears, the panel is absent.

### 3.4 `ThroughputCard`

```typescript
interface ThroughputCardProps {
  latest: TrainMetricsPayload | null;
}
function ThroughputCard({ latest }: ThroughputCardProps): JSX.Element;
```

Renders a `Card` with three `NumberDisplay` rows:

| Label | Field | Format | Unit |
|---|---|---|---|
| **Steps/s** | `env_steps_per_sec` | `formatThroughput(v)` | steps/s |
| **Total Steps** | `global_step` | `formatSteps(v)` | steps |
| **Wall Time** | `wall_seconds` | `formatWallSeconds(v)` | — |

When `latest === null`: all three rows render `"—"`.

**Formatting functions** (live in `src/utils/units.ts` — this contract defines the required signatures; tests pin the outputs):

```typescript
// Format env_steps_per_sec: ≥1,000,000 → "1.35M/s"; ≥1,000 → "1,350k/s"; else → "850/s"
function formatThroughput(stepsPerSec: number): string;

// Format global_step: ≥1,000,000 → "1.35M steps"; ≥1,000 → "250k steps"; else → "999 steps"
function formatSteps(steps: number): string;

// Format wall_seconds: <60 → "45s"; <3600 → "3m 4s"; else → "1h 2m"
function formatWallSeconds(seconds: number): string;
```

These functions are added to the existing `src/utils/units.ts` (app_shell.md §8). No unit conversions elsewhere.

### 3.5 `CheckpointEventList`

```typescript
interface CheckpointEventListProps {
  history: TrainMetricsPayload[];  // full history; this component filters is_eval_checkpoint=true
}
function CheckpointEventList({ history }: CheckpointEventListProps): JSX.Element;
```

- Filters `history` to entries where `is_eval_checkpoint === true`.
- Renders a `Card` titled "Checkpoints" with an ordered list (newest first).
- Each row: `checkpoint_id` (monospace) + `global_step` (formatted via `formatSteps`) + `cost_total_real_mean_yuan` (formatted via `formatYuan`).
- Empty list: renders `"No checkpoints yet"`.
- Clicking a checkpoint row is a no-op at this stage (checkpoint detail view is out of scope).

### 3.6 `EvalCompareTable`

```typescript
interface EvalCompareTableProps {
  latest: EvalComparePayload | null;
  // Previous evals for trend (optional future enhancement — not contracted here)
}
function EvalCompareTable({ latest }: EvalCompareTableProps): JSX.Element;
```

Renders a `Card` titled "Policy Comparison (latest eval)" with a responsive table.

**Columns (fixed):**
| Column | Field | Format | Notes |
|---|---|---|---|
| Policy | key from `policies` | Display name (see mapping below) | Row header |
| Energy Cost | `energy_cost_yuan` | `formatYuan(v, 0)` | ¥ |
| Demand Charge | `demand_charge_yuan` | `formatYuan(v, 0)` | ¥ |
| Degradation | `degradation_yuan` | `formatYuan(v, 0)` | ¥ |
| Curtailment | `curtailment_yuan` | `formatYuan(v, 0)` | ¥ |
| VOLL | `voll_yuan` | `formatYuan(v, 0)` | ¥ |
| **Total Cost** | `total_cost_yuan` | `formatYuan(v, 0)` | ¥ bold |
| SOC Violations | `soc_violations_count` | integer | count (not ¥) |
| SOC Penalty (¥) | `penalty_yuan` | `formatYuan(v, 0)` | footnote: "excluded from total" |

**Policy display names** (mapping from key → label). UNKNOWN keys are displayed with the raw key capitalized:

| Key | Display label |
|---|---|
| `rl` | RL Agent |
| `no_battery` | No Battery |
| `rule_based_tou` | Rule-Based TOU |
| `greedy` | Greedy |
| `dp_oracle` | DP Oracle |
| `mpc` | MPC |
| `simulated_annealing` | Sim. Annealing |
| `ant_colony` | Ant Colony |
| *(unknown)* | key (title-cased) |

**Row ordering:** `rl` is always first; remaining policies sorted by `total_cost_yuan` ascending (best to worst, after rl).

**Best-policy highlight:** the row with the lowest `total_cost_yuan` (regardless of SOC violations) receives a `data-best="true"` attribute and a distinct CSS class `row-best` for styling. If the RL agent has the lowest total cost, the RL row is highlighted (§5 acceptance criterion). If another policy beats RL, RL is NOT highlighted, and the better policy row is highlighted — a visual signal that the RL agent has NOT met the §5 baseline.

**SOC footnote:** a `<tfoot>` row renders `"† SOC penalty excluded from Total Cost (reward-basis safety metric)"`.

**`null` case:** renders `"No eval run yet — waiting for first 365-day eval"` placeholder (not an empty table with no rows).

**Extensibility requirement:** the table MUST iterate `Object.keys(latest.policies)` to render rows; it MUST NOT hardcode the policy key list. A new policy key in `policies` auto-appears as a row without code changes.

### 3.7 `StreamStatusBanner`

```typescript
// Stale threshold: no train_metrics received in > STALE_THRESHOLD_MS (30_000ms default)
// measured by comparing Date.now() to the last-received message's ts_utc
const STALE_THRESHOLD_MS = 30_000;

interface StreamStatusBannerProps {
  wsStatus: WsStatus;
  lastMessageTsUtc: string | null;  // envelope ts_utc of most recent train_metrics
  seqGap: boolean;                  // from trainingStore (if tracked) or detected locally
  // Note: trainingStore does not expose seqGap directly (that's telemetryStore, for env_step).
  // TrainingPanel tracks the last-seen seq for train_metrics locally and computes seqGap.
}
function StreamStatusBanner({ wsStatus, lastMessageTsUtc, seqGap }: StreamStatusBannerProps): JSX.Element | null;
```

- Returns `null` (renders nothing) when: `wsStatus === "connected"` AND NOT stale AND NOT seqGap.
- Stale condition: `wsStatus === "connected"` AND `lastMessageTsUtc !== null` AND `Date.now() - Date.parse(lastMessageTsUtc) > STALE_THRESHOLD_MS`.
- Stale banner text: `"Training stream stale — no update in >30s"` with `severity="warning"`.
- Disconnected banner text: `"Training stream disconnected"` with `severity="error"`.
- Seq gap banner text: `"Sequence gap detected — some training steps may be missing"` with `severity="warning"`.
- When multiple conditions are true, show only the highest severity banner (disconnected > gap > stale).

---

## 4. Formatting utilities (additions to `src/utils/units.ts`)

All new formatting functions are added to the EXISTING `src/utils/units.ts`. Dashboard components MUST import from there; no inline formatting.

```typescript
// Throughput: steps/second
// ≥1,000,000 → "1.35M/s"; ≥1,000 → "350k/s"; else → "850/s"
function formatThroughput(stepsPerSec: number): string;

// Step count
// ≥1,000,000 → "1.35M steps"; ≥1,000 → "250k steps"; else → "999 steps"
function formatSteps(steps: number): string;

// Wall seconds
// <60 → "45s"; <3600 → "3m 4s"; else → "1h 2m"
function formatWallSeconds(seconds: number): string;
```

Existing `formatYuan(yuan, decimals?)` is already in `units.ts`; no change needed for ¥ display.

---

## 5. Seq-gap detection for train_metrics

`TrainingPanel` maintains a local React ref `lastTrainSeq: number | null` to detect gaps in the `train_metrics` stream (separate from `telemetryStore.seqGap` which tracks `env_step`):

```typescript
// In TrainingPanel, on each new train_metrics message msg:
if (lastTrainSeq.current !== null && msg.seq > lastTrainSeq.current + 1) {
  setTrainSeqGap(true);
} else {
  setTrainSeqGap(false); // clear gap once a contiguous message arrives
}
lastTrainSeq.current = msg.seq;
```

Gap semantics: same as telemetryStore — only FORWARD gaps (missed messages) set `seqGap=true`; out-of-order / duplicate delivery does not.

---

## 6. REST integration

`RunSelector` calls `restClient.getRuns()` which returns `RunInfo[]` (defined in `app_shell.md` §5):

```typescript
interface RunInfo {
  run_id: string;
  started_at: string;        // ISO-8601 UTC
  status: "running" | "completed" | "failed";
  checkpoint_count: number;
}
```

No other REST calls are made by the training dashboard.

---

## 7. Static data — policy display name table

The display name mapping (§3.6) is a pure static object in `EvalCompareTable.tsx`:

```typescript
const POLICY_DISPLAY_NAMES: Record<string, string> = {
  rl:                  "RL Agent",
  no_battery:          "No Battery",
  rule_based_tou:      "Rule-Based TOU",
  greedy:              "Greedy",
  dp_oracle:           "DP Oracle",
  mpc:                 "MPC",
  simulated_annealing: "Sim. Annealing",
  ant_colony:          "Ant Colony",
};

function policyDisplayName(key: string): string {
  return POLICY_DISPLAY_NAMES[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}
```

---

## 8. Behavior on edge and failure inputs

All of the following MUST be handled without crashing and without rendering incorrect data:

| # | Condition | Expected behavior |
|---|---|---|
| E1 | `trainingStore.history === []` | `MetricCurves` + `CheckpointEventList` show empty-state placeholders; `ThroughputCard` shows "—" |
| E2 | `evalStore.latest === null` | `EvalCompareTable` shows "No eval run yet" placeholder; no crash |
| E3 | `train_metrics` with `reward_norm_mean: null` | Field is not plotted; no NaN on chart |
| E4 | `cost_total_real_mean_yuan = -61000` (negative) | Formatted as "¥-61,000"; y-axis allows negative range; not clamped to 0 |
| E5 | `is_eval_checkpoint: true, checkpoint_id: null` | Checkpoint marker still drawn; label shows "—" |
| E6 | `policies` with unknown future key (e.g. `"greedy"`) | New row rendered with fallback display name; no crash |
| E7 | `restClient.getRuns()` rejects | `RunSelector` shows error state with retry button |
| E8 | `getRuns()` returns `[]` | `RunSelector` shows "No runs available" |
| E9 | Seq gap in `train_metrics` (msg.seq > lastSeq + 1) | `StreamStatusBanner` shows gap warning |
| E10 | `wsStatus === "disconnected"` | `StreamStatusBanner` shows disconnection banner |
| E11 | `lastMessageTsUtc` > 30s ago | `StreamStatusBanner` shows stale warning |
| E12 | All-zero `train_metrics` values | Charts render `0.0` values correctly; no NaN ticks |
| E13 | `evalStore.policies.rl.total_cost_yuan` > all baselines | RL row NOT highlighted as best; no crash; the baseline with lowest cost is highlighted |
| E14 | `eval_compare` with only one policy | Table renders that one row correctly |
| E15 | `history` with a single point | Charts render single-point (dot, not line); no axis scale errors |
| E16 | `wall_seconds = 0` | Formatted as "0s" |
| E17 | Very large `global_step` (1e9) | Formatted as "1,000M steps" or "1B steps"; no overflow display |

---

## 9. Deliberate deviations

- **No `env_step` consumption:** the training dashboard deliberately does not read `telemetryStore.envStep` or any `flows.*`, `battery.*`, `costs.*` per-step fields. These belong to the `SiteView` dashboard.
- **No 3D scene or `SceneMountPoint`:** `TrainingPanel` contains no `SceneMountPoint` or any canvas element.
- **No training controls:** start/pause/resume/hyperparameter sweep UI is env-harness-engineer's domain. This view is read-only.
- **`reward_norm_mean` not plotted:** its null-on-eval-checkpoint behavior and VecNormalize-specific scaling make it unsuitable for a continuous trend; `reward_scaled_mean` (always present, consistent basis) is used instead.
- **Chart library:** not specified at this contract stage; recorded in `STACK.md` when chosen (see implementation step).

---

## 10. Out of scope

- Training controls (start/pause/resume/hyperparameter sweep) — env-harness-engineer.
- Checkpoint detail view / model download — serving-engineer.
- Per-step `env_step` live dashboard — SiteView (separate dashboard route).
- §8 gas/electrolyzer asset columns in `EvalCompareTable` — future minor bump.
- Multi-run overlay charts — future enhancement.
- Authentication / user sessions.
