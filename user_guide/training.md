# Training

The **Training** tab (`/training`) shows live metrics from a SAC training run, plus checkpoints and an eval comparison. It reads the training-metrics websocket stream (`train_metrics`) and the run history over REST.

> **Important — current limitation.** An **end-to-end training run is not yet runnable from `main`.** The SAC training *library* (`energy_go.training`) is merged and unit-tested, but it depends on the pure-JAX environment core, which is still in review. The launch scripts' `training`/`full` launch path also targets the training/eval **harness** (`energy_go.harness.train`), which has not landed yet. Until those merge, the training panel renders correctly but will show "Waiting for training data…" with no live run to attach to. This page documents the panel as it exists today and how training launches once the back end is complete.

## Launching a training job (once available)

Training is launched by server type, not from the browser:

```bash
# Training-only box (no frontend):
bash scripts/install_app.sh --server-type training
# One box that both trains and serves:
bash scripts/install_app.sh --server-type full --checkpoint <id-or-path>
```

`training` installs the JAX core + training/eval/baseline dependencies and starts the training harness (logs to `/tmp/energy_go_training.log`); it installs **no** Node/frontend. `full` additionally runs the FastAPI backend and built frontend so you can watch the run in the Training tab. You can also control a run from the backend's REST endpoints (`POST /training/start|stop|pause|resume`, `GET /training/status`).

## Reading the training panel

When a run is streaming, the panel shows:

| Section | What it tells you |
|---|---|
| **Status banner** | Appears only when the stream is stale, has a sequence gap, or is disconnected. |
| **Run selector** | Pick which run to view (lists runs from `GET /runs`). |
| **Throughput card** | Training speed (steps/sec) and progress for the latest update. |
| **Metric curves** | The main view — training curves over time (rewards/losses and related SAC metrics). |
| **Checkpoint events** | A log of checkpoints saved during the run. |
| **Eval comparison** | Appears when an eval result exists for the run: RL vs. `no_battery` vs. `rule_based_tou` across energy/demand/degradation/curtailment/VOLL/total cost (¥). |

Before any data arrives the panel shows a "Waiting for training data…" spinner (or a blank area with just the status banner if the stream is disconnected).

## Baselines

Two baseline policies are run alongside the RL agent for context, so the eval table always has a reference point:

- **`no_battery`** — the plant operated with the battery disabled.
- **`rule_based_tou`** — a fixed time-of-use rule (charge in the valley, discharge in the peak).

A successful RL policy should beat both on total cost. See [The dashboard → Eval comparison](dashboard.md#eval-comparison-eval) for the same table on the Eval tab.
