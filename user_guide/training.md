# Training

The **Training** tab (`/training`) shows live metrics from a SAC training run, plus checkpoints and an eval comparison. It reads the training-metrics websocket stream (`train_metrics`) and the run history over REST.

Training is stage ③ of the five-stage pipeline (`config → algorithm → **train** → eval → finance`). The pure-JAX environment core (PR #33), the SAC training pipeline (PR #40), and the training/eval harness (PR #43) are all merged on `main` — end-to-end training is now runnable.

## Launching a training job

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
