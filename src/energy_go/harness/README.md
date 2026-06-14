# `src/energy_go/harness`

<!-- curated -->
## Purpose

This package is the control layer that sits between the JAX env core and the rest of the system (serving, dashboard training panel). It owns the training run lifecycle and the interactive/debugging interfaces; it does not contain env physics or training loop logic.

Its four modules cover distinct control concerns:

- **Run lifecycle** (`run_manager.py`): `RunManager` starts, pauses, resumes, and stops training runs by coordinating with the `training` package and streaming `train_metrics` / `eval_compare` telemetry to registered listeners (see `contracts/harness/env_harness.md`).
- **Interactive stepping** (`interactive_env.py`): `InteractiveEnv` wraps `jax_env.step` to support single-step debugging — each call returns a full `StepInspection` with observation, action, reward, cost breakdown, and physics quantities, without running a full episode.
- **Scenario replay** (`replay.py`): `ScenarioReplay` runs a deterministic trajectory over a chosen synthetic-year slice, driven by either a fixed action sequence or a policy callable, for regression testing and scenario analysis.
- **Hyperparameter sweeps** (`sweeper.py`): `Sweeper` runs vmapped hyperparameter or domain-randomisation sweeps, returning a `SweepResult` per variant.

Shared dataclasses (`RunStatus`, `StepInspection`, `TrajectoryStep`, `SweepResult`, etc.) are defined in `types.py` and used across all four modules.

What does NOT live here: JAX env physics (that is the `env` package), the SAC training loop (that is the `training` package), and HTTP/WebSocket serving (that is the `serving` package).
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `__init__.py`

> energy_go.harness — training & testing control layer for the Energy GO env.

_No public symbols exported._

### `interactive_env.py`

> energy_go.harness.interactive_env — single-step debugging interface.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `InteractiveEnv` | `class` | Debugging interface for the JAX env core. |

### `replay.py`

> energy_go.harness.replay — deterministic trajectory replay.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `ScenarioReplay` | `class` | Deterministic trajectory replay over a chosen synthetic-year slice. |

### `run_manager.py`

> energy_go.harness.run_manager — training run lifecycle management.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `RunManager` | `class` | Training run lifecycle manager. |

### `sweeper.py`

> energy_go.harness.sweeper — vmapped hyperparameter/domain-randomization sweeps.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `Sweeper` | `class` | Hyperparameter / domain-randomization sweep runner. |

### `types.py`

> energy_go.harness.types — shared dataclasses for the training & testing harness.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `RunStatus` | `class` | — |
| `RunConfig` | `class` | — |
| `RunRecord` | `class` | — |
| `StepInspection` | `class` | — |
| `TrajectoryStep` | `class` | — |
| `TrajectoryRecord` | `class` | — |
| `SweepVariant` | `class` | — |
| `SweepResult` | `class` | — |

<!-- generated:end -->
