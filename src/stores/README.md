# `src/stores`

<!-- curated -->
## Purpose

Client-side state stores built with Zustand (STACK: Zustand, established in PRs #5 and #20). Stores own all runtime state; they do not open network connections — that is `clients/` responsibility. Components and scene code subscribe to stores read-only.

Current stores: `telemetryStore` — holds the rolling `env_step` frame history (cap: `HISTORY_MAX_LEN` = 168 steps), a frame-error ring buffer of up to 10 validation failures, and the WebSocket connection status; `inferenceSessionStore` — manages the inference session lifecycle: auto-starts on server `status:ready`, exposes pause/resume/speed actions (contract `contracts/frontend/inference_session.md §3`); `trainingStore` — holds the latest and historical `train_metrics` frames plus sequence-gap detection; `evalStore` — holds the latest `eval_compare` payload; `stageOneStore` — wizard state for the Stage-① site configuration flow.

No store contains network transport logic. No store should be written to from rendering code — mutations go through the action methods exposed by each store.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `evalStore.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `EvalState` | `interface` | — |
| `useEvalStore` | `const` | — |

### `inferenceSessionStore.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `InferenceServerState` | `type` | — |
| `InferenceSessionState` | `interface` | — |
| `inferenceSessionStore` | `const` | — |
| `useInferenceSessionStore` | `const` | inferenceSessionStore — inference session state and control actions. |

### `stageOneStore.ts`

> src/stores/stageOneStore.ts

| Symbol | Kind | Purpose |
|--------|------|---------|
| `StageOneStoreState` | `interface` | — |
| `StageOneStoreActions` | `interface` | — |
| `useStageOneStore` | `const` | — |

### `telemetryStore.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `FrameError` | `interface` | One entry in the frame-validation failure ring buffer. |
| `TelemetryState` | `interface` | — |
| `useTelemetryStore` | `const` | — |

### `trainingStore.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `TrainingState` | `interface` | — |
| `useTrainingStore` | `const` | — |

<!-- generated:end -->
