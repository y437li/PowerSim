# Energy GO — Rebuild Specification

Everything you need to rebuild the system from scratch: methodology, formulas, parameters, and a language/stack recommendation.

> Source of truth extracted from: `python/env/power_env.py`, `gym_energy_router/core/{reward,renewable_models,weather_generator,load_generator}.py`, `python/agents/train_sac.py`, `config/site_gansu.yaml`.

---

## How this spec is organized

The specification is split into per-section files under [`docs/spec/`](docs/spec/) for cleaner per-section maintenance as it grows. **This file is the index.** Section numbering is **stable and canonical** — every contract, LINEAGE decision, and agent charter cites `§N.M`, and those citations resolve to the headers inside the section files (which are unchanged). Each section has an **Owner** (maintains the file, first consult for its ambiguities); overall spec authority and the human merge gate are unchanged.

**Governing rules (unchanged):**
- When code and the spec disagree, the **spec wins**; when the spec is ambiguous, escalate to **rl-architect** — never guess.
- Any change to spec content is **human-gated** (open a PR, mark ready, route via team-lead to the user) — the same gate regardless of which section file it touches.
- Section numbers never change; a new section is appended with the next number and added to the table below.

## Sections

| § | Section | File | Owner |
|---|---|---|---|
| 1 | What the system is | [`docs/spec/section_01_overview.md`](docs/spec/section_01_overview.md) | rl-architect |
| 2 | MDP specification | [`docs/spec/section_02_mdp.md`](docs/spec/section_02_mdp.md) | rl-architect |
| 3 | Physics & cost formulas | [`docs/spec/section_03_physics_costs.md`](docs/spec/section_03_physics_costs.md) | jax-env-engineer |
| 4 | Synthetic data generators | [`docs/spec/section_04_generators.md`](docs/spec/section_04_generators.md) | jax-env-engineer |
| 5 | Training methodology | [`docs/spec/section_05_training.md`](docs/spec/section_05_training.md) | training-engineer (rl-architect interim until staffed) |
| 6 | System components (current architecture) | [`docs/spec/section_06_components.md`](docs/spec/section_06_components.md) | rl-architect |
| 7 | Language recommendation: JAX (core) — not Go | [`docs/spec/section_07_jax_architecture.md`](docs/spec/section_07_jax_architecture.md) | rl-architect |
| 8 | Composable asset library (extension) | [`docs/spec/section_08_composable_assets.md`](docs/spec/section_08_composable_assets.md) | rl-architect |
| 9 | Install & launch scripts (deployment) | [`docs/spec/section_09_install_launch_scripts.md`](docs/spec/section_09_install_launch_scripts.md) | serving-engineer |
| 10 | Env-logic enhancements (proposal — opt-in, parity-preserving) | [`docs/spec/section_10_env_enhancements.md`](docs/spec/section_10_env_enhancements.md) | jax-env-engineer |
| 11 | Benchmark algorithms for RL comparison (proposal — user approval) | [`docs/spec/section_11_benchmark_algorithms.md`](docs/spec/section_11_benchmark_algorithms.md) | rl-architect |
| 12 | Real-weather data pipeline (proposal — user approval) | [`docs/spec/section_12_weather_pipeline.md`](docs/spec/section_12_weather_pipeline.md) | env-harness-engineer (rl-architect interim until staffed) |

