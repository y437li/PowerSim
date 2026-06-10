# STACK — Energy GO per-area stack registry

The single registry of the **binding stack choice per area** of the rebuild. Derived from `REBUILD_SPEC.md` (§5 training, §7 JAX/serving), the agent charters, and merged decisions.

**Maintenance rule (also in CLAUDE.md):** any PR that introduces or changes a stack element — language, framework, major library, test runner, build/CI tool, or an asset/runtime/data format — MUST update this file in the same PR. Reviewers check contracts and implementations against this registry; a stack choice not recorded here is not approved.

Version pins live in `pyproject.toml` (Python) and `package.json` (frontend); this file pins a version only where the *choice* depends on it (e.g. a CUDA/Metal jaxlib variant). "Set by" cites the PR or LINEAGE decision that bound the choice.

| Area | Chosen stack | Version / variant notes | Set by |
|---|---|---|---|
| **Env core** | Pure **JAX** (`jax`/`jnp`, `jit`, `vmap`), explicit RNG key threading | CPU or GPU jaxlib selected at install per server type (§9: `--accel cpu\|gpu`); no data-dependent Python branching | REBUILD_SPEC §7; D3 |
| **Parity reference** | Plain **Python + NumPy** (no JAX) | Independent 2nd implementation of §3/§4 for cross-impl parity | D11 (PR #2) |
| **Training** | **SAC** via **sbx** (SB3-in-JAX) or **purejaxrl**; `optax`, `flax`; vmapped parallel envs; replay buffer (`flashbax`-style) | Running-stat normalization saved with checkpoint (§5, §7) | REBUILD_SPEC §5/§7 |
| **Env API pattern** | `gymnax`-style pure functional env (state, obs, reward as arrays) | Pattern to copy, not a hard dependency | REBUILD_SPEC §7 |
| **Serving** | **FastAPI** + websocket streams (live inference + training metrics) + REST (configs, run history) | Python is the v1 default; optional Go/ONNX-Runtime binary is later polish (§7) | REBUILD_SPEC §6/§7 |
| **Policy export** | **ONNX** or raw MLP weights (actor is a plain MLP) | Consumed by the serving layer; ties to the checkpoint contract | REBUILD_SPEC §7 |
| **Frontend shell** | **React + Vite + TypeScript** | App shell, routing, websocket/REST clients | REBUILD_SPEC §6; charters |
| **Frontend state** | **Zustand** | Client state store (app shell + dashboard + 3D scene) | PR #5 app_shell contract; ratified PR #20 |
| **3D scene** | **Three.js / React Three Fiber** | `.glb` assets resolved only via `assets/3d/registry.json` (no hardcoded paths) | REBUILD_SPEC §8.5; charters |
| **Frontend tests** | **Vitest + React Testing Library** | `tests/frontend*/<feature>.test.tsx` | CLAUDE.md conventions |
| **Backend tests** | **pytest** | `tests/<area>/test_<area>_<feature>.py` | CLAUDE.md conventions |
| **Config** | **YAML** | `config/<site\|asset>_<name>.yaml`; site YAML composes assets and derives obs/action (§8.4) | REBUILD_SPEC §8; D2 |
| **Telemetry wire format** | JSON per `contracts/shared/telemetry_schema.md` v1.0.0 (semver) | LOCKED; env_step / train_metrics / eval_compare | LOCKED PR #6; D3–D13 |
| **Telemetry validation** | **JSON Schema** (draft 2020-12) `contracts/shared/telemetry_schema.json` + canonical examples; Python **`jsonschema`** ≥4.21; reference CLI `scripts/validate_telemetry.py`; frontend TS validator (ajv or zod) planned | machine-enforced field/identity conformance for all producers/consumers | PR #20 (D18) |
| **CI** | **GitHub Actions** (`.github/workflows/ci.yml`) | Runs `scripts/check_conventions.sh`; gate via `scripts/check_pr_gate.sh` | setup commits; this PR |
| **Install/launch** | `scripts/install_app.{sh,ps1}` + `run_app.{sh,ps1}`; Python via `uv`; Node LTS | macOS + Windows; server types dev/training/serving/full (§9) | REBUILD_SPEC §9 (PR #8) |

## Out of registry (deliberately not chosen / removed)
- **Rust (`rust_core`)** — superseded by the JAX core (REBUILD_SPEC §7); not part of the rebuild stack.
- **Go serving binary** — optional future polish only, not the v1 serving stack (REBUILD_SPEC §7).
