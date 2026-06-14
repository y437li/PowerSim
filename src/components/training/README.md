# `src/components/training`

<!-- curated -->
## Purpose

Training-panel components rendered by `routes/TrainingPanel.tsx` at the `/training` route. Components read from `stores/trainingStore` and `stores/evalStore`; they are display-only and perform no store mutations or network calls.

Current components: `CheckpointEventList` (ordered list of eval checkpoint events, newest first), `EvalCompareTable` (side-by-side policy metric comparison from the latest `eval_compare` payload), `MetricCurves` (SAC training metric curves over training steps, rendered with Recharts), `RunSelector` (compact run picker backed by `restClient.getRuns()`), `StreamStatusBanner` (indicates live/stale/disconnected state of the training metrics stream — stale threshold is 30 s wall-clock without a `train_metrics` message), and `ThroughputCard` (training throughput summary).

RL semantics (what SAC metrics mean, how eval scores are computed) are defined in the spec and backend; these components only render values they receive.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `CheckpointEventList.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `CheckpointEventList` | `function` | Ordered list of eval checkpoint events, newest first. |

### `EvalCompareTable.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `EvalCompareTable` | `function` | Comparison table: RL vs all baseline policies. |

### `MetricCurves.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `ChartPanel` | `interface` | — |
| `PANELS` | `const` | — |
| `MetricCurves` | `function` | Five line-chart panels driven by trainingStore.history. |

### `RunSelector.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `RunSelector` | `function` | Compact run picker backed by restClient.getRuns(). |

### `StreamStatusBanner.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `StreamStatusBanner` | `function` | Renders a status banner when the training stream is degraded. |

### `ThroughputCard.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `ThroughputCard` | `function` | Compact card showing training throughput metrics. |

<!-- generated:end -->
