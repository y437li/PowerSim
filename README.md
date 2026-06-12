# Energy GO

Energy GO is a reinforcement-learning system for **dispatching a grid-connected wind + solar + battery plant** (modeled on the Gansu/Jiuquan site in China) to minimise total electricity cost. A Soft Actor-Critic (SAC) policy controls battery charge/discharge and renewable routing each hour to exploit:

- **Time-of-use arbitrage** — charge in the ¥0.25/kWh valley, discharge into the ¥0.78/kWh critical peak;
- **Peak shaving** — reduce the monthly demand charge (¥32/kW·month on peak grid import);
- **Renewable routing** — self-consume vs. sell to grid vs. store.

```
minimize  Σ_t [ Energy_Cost + Demand_Charge + Battery_Degradation + Penalties ]
```

**Gansu site totals:** Wind 615 MW · Solar 330 MW · Battery 294.5 MWh / 98.16 MW · Load 50–100 MW · PCC export limit 945 MW · import limit 400 MW. (See [`docs/spec/section_01_overview.md`](docs/spec/section_01_overview.md).)

This repository is a **ground-up rebuild** specified in [`REBUILD_SPEC.md`](REBUILD_SPEC.md). Units are explicit at every interface (MW, MWh, ¥/MWh) and the physics/cost formulas are fixed in [`docs/spec/section_03_physics_costs.md`](docs/spec/section_03_physics_costs.md).

> **Project status (accurate to `main`).** The full backend + frontend stack is on `main`: reference simulator, pure-JAX env core (PR #33), SAC training pipeline (PR #40), training/eval harness (PR #43), FastAPI serving layer, React/3D frontend, and `config/site_gansu.yaml` (PR #79). End-to-end training is runnable. See [Component status](#component-status) for the full table.

---

## Architecture

Energy GO is built around one canonical specification (`REBUILD_SPEC.md`, sections under [`docs/spec/`](docs/spec/)) and a LOCKED telemetry wire format that every producer and consumer conforms to.

| Layer | What it is | Stack | Where |
|---|---|---|---|
| **Parity reference** | From-scratch plain-Python/NumPy implementation of the §3 physics + §4 cost/tariff model. The correctness oracle for the JAX core (two independent implementations of the same spec). | Python + NumPy | `src/reference/` |
| **JAX env core** | Pure-JAX, jittable/vmappable env `step` and synthetic weather/load generators (§3, §4, §7). Validated against the reference for parity. | JAX (`jax`/`jnp`) | `src/energy_go/env/`, `src/energy_go/generators/` |
| **Training** | SAC pipeline (§5) — device-resident training loop ([D27](LINEAGE.md)), running-stat normalization, eval, and baseline agents. | `sbx-rl`, `flax`, `optax`, `flashbax` | `src/energy_go/training/` |
| **Serving** | FastAPI backend: REST config/run-history endpoints + websocket streams for live inference and training metrics. | FastAPI + uvicorn + websockets | `src/energy_go/serving/` |
| **Telemetry** | The LOCKED JSON wire format (`env_step` / `train_metrics` / `eval_compare`) plus a Python validator and a TypeScript (Zod) validator. | JSON Schema 2020-12 / `jsonschema` / Zod | `contracts/shared/telemetry_schema.md`, `src/energy_go/telemetry/`, `src/validators/` |
| **Frontend** | React + Vite app shell: live 3D site scene (Three.js / React Three Fiber), training dashboard (Recharts), eval comparison. | React + Vite + TypeScript + Zustand | `src/` (`App.tsx`, `routes/`, `scene/`, `components/`, `stores/`) |
| **3D assets** | `.glb` models resolved only through `assets/3d/registry.json` (LOCKED) — no hardcoded asset paths in scene code. | Three.js / R3F | `assets/3d/` |

The full per-area stack registry (with the PR/decision that bound each choice) is [`STACK.md`](STACK.md). Locked cross-area contracts — the telemetry schema, the checkpoint format, and the 3D asset registry — are recorded in [`LINEAGE.md`](LINEAGE.md).

### Component status

| Component | Status | Reference |
|---|---|---|
| Parity reference (`src/reference/`) | ✅ on `main` | PR #14, [D11](LINEAGE.md) |
| Telemetry schema (LOCKED v1.0.0) + Python/TS validators | ✅ on `main` | PR #6 (lock), #23, #56 |
| Checkpoint format (LOCKED v1.0.0) | ✅ on `main` | PR #41, [D25](LINEAGE.md) |
| Training pipeline (SAC, device-resident) | ✅ on `main` | PR #40, [D27](LINEAGE.md) |
| Serving (FastAPI REST + websockets) | ✅ on `main` | PR #29, #59, #60 |
| Frontend app shell + dashboard + 3D scene | ✅ on `main` | PR #5, #36, #45, #52 |
| 3D asset registry + Gansu GLB models | ✅ on `main` | PR #24 (lock), #38, #49 |
| Launch / install scripts (§9) | ✅ on `main` | PR #10, #61 |
| **Pure-JAX env core + generators** | ✅ on `main` | PR #33 |
| **Training/eval harness** (`energy_go.harness`) | ✅ on `main` | PR #43 |
| `config/site_gansu.yaml` at repo root | ✅ on `main` | PR #79 ([D2](LINEAGE.md)) |

> The full backend stack is now on `main`: JAX env core (PR #33), training pipeline (PR #40), training/eval harness (PR #43), and `config/site_gansu.yaml` (PR #79). **End-to-end training is runnable from `main`** — install with `--server-type training` or `full` and the harness starts immediately.

---

## Quickstart

Energy GO ships one-command install + launch scripts for **macOS** and **Windows**, selected by a `--server-type` flag that picks the machine's role (spec: [§9](docs/spec/section_09_install_launch_scripts.md), contract: `contracts/serving/launch_scripts.md`). Run them from the repository root.

- `scripts/install_app.sh` / `scripts/install_app.ps1` — idempotent dependency install, then optional launch.
- `scripts/run_app.sh` / `scripts/run_app.ps1` — launch an already-installed server type (no dependency work).

The `.sh` (macOS) and `.ps1` (Windows) variants are behavioural mirrors — same flags, same server-type taxonomy, same exit codes. Linux is best-effort only (CI installs `pyproject` extras directly rather than via these scripts).

### Server types (`--server-type`)

| Type | Installs | Launches |
|---|---|---|
| `dev` | full stack: JAX, training, serving, frontend dev server | FastAPI backend (reload) + Vite dev server (HMR) |
| `training` | JAX + training/eval/baselines; **no** Node/frontend | training harness (no web) |
| `serving` | JAX CPU (inference only) + FastAPI + **built** frontend bundle; **no** training deps | FastAPI serving the telemetry stream + static frontend |
| `full` | union of `training` + `serving` | training harness + FastAPI + built frontend |

`--accel cpu|gpu` is orthogonal and selects the jaxlib variant (CPU wheel, CUDA 12, or Apple-Silicon Metal); the default auto-detects a GPU and falls back to CPU. `serving` always uses CPU.

### Example: serving box (macOS)

```bash
# Install serving deps (CPU) and build the frontend, without launching:
bash scripts/install_app.sh --server-type serving --accel cpu --checkpoint <id-or-path> --no-launch

# Launch the installed serving box:
bash scripts/run_app.sh --server-type serving --checkpoint <id-or-path>
# → FastAPI on http://localhost:8000 ; GET /health responds.
```

Windows equivalents (`pwsh`):

```powershell
pwsh scripts/install_app.ps1 -ServerType serving -Accel cpu -Checkpoint <id-or-path> -NoLaunch
pwsh scripts/run_app.ps1 -ServerType serving -Checkpoint <id-or-path>
```

### Example: developer box

```bash
bash scripts/install_app.sh --server-type dev
# → FastAPI on http://localhost:8000 and Vite dev server on http://localhost:5173.
```

### Common flags

| Flag | Meaning | Default |
|---|---|---|
| `--server-type <dev\|training\|serving\|full>` | Machine role (required) | — |
| `--accel <cpu\|gpu>` | jaxlib variant | auto-detect (gpu→cpu) |
| `--site <PATH>` | Site YAML config | `config/site_gansu.yaml` *(see note)* |
| `--checkpoint <ID_OR_PATH>` | Policy checkpoint (required for `serving`/`full`) | `.run/last_checkpoint` if present |
| `--backend-port <PORT>` | FastAPI port | `8000` |
| `--frontend-port <PORT>` | Frontend dev/static port | `5173` |
| `--no-launch` | Install only | — |
| `--uninstall` [`--purge`] | Stop services; remove `.venv`/`node_modules`/`dist`/`.run` (and checkpoints with `--purge`) | — |

> **Note on `--site`:** the scripts default `--site` to `config/site_gansu.yaml`, but that file is **not yet checked into the repo** (the reference simulator currently sources Gansu parameters from `src/reference/gansu_params.py`, and the serving layer exposes site configs over `GET /config/sites`). Pass an explicit `--site <path>` if you need it, or expect a config-resolve error (exit code 4) for `serving`/`full` until a site YAML is added.

### Configurable ports (env vars)

Beyond the `--*-port` flags, the components honour two environment variables (contracts: `configurable_ports.md`, `backend_port.md`):

- `ENERGY_GO_BACKEND_PORT` — FastAPI port when launching the app module directly (`python -m energy_go.serving.app`, default `8000`); also read by the Vite dev proxy and by `run_app.sh` as the backend-port default.
- `ENERGY_GO_FRONTEND_PORT` — Vite dev-server port (default `5173`); also used by the Playwright E2E harness.

The flag takes precedence over the env var, which takes precedence over the default.

### Serving API surface

The FastAPI app (`energy_go.serving.app:app`) exposes:

- **REST:** `GET /health`, `/config/sites`, `/config/sites/{site_id}`, `/config/assets/{category}`, `/runs`, `/runs/latest`, `/runs/{run_id}`, `/runs/{run_id}/eval`, `/runs/{run_id}/train_curve`.
- **Websockets:** `/ws/inference` (live policy inference stream), `/ws/training/stream` (live training metrics), plus `/training/{status,start,stop,pause,resume}` controls.

All stream payloads conform to the LOCKED telemetry schema (`contracts/shared/telemetry_schema.md` v1.0.0).

---

## Development

This repo uses a **contract-first, PR-gated** workflow — every change is specified in a contract and covered by reviewer-approved tests *before* implementation. The rules are non-negotiable and live in [`CLAUDE.md`](CLAUDE.md). In brief:

- **Contracts** in `contracts/<area>/<feature>.md`; **tests** in a single `tests/` tree (`tests/<area>/test_<area>_<feature>.py`, frontend `tests/frontend*/<feature>.test.tsx`).
- All work goes through GitHub PRs on `feat/`/`fix/`/`chore/` branches — never commit to `main`.
- Merge requires the area reviewer's `VERDICT: APPROVE` **and** QA's `VERDICT: QA_PASS` (verdict-marker convention, [D14](LINEAGE.md)).

### Running tests locally

```bash
# Python (backend) — install dev extras first:
uv pip install -e ".[dev]"
pytest                       # full suite (tests/)
pytest -m "not slow"         # skip slow install/venv acceptance tests

# Frontend (Vitest + React Testing Library):
npm ci
npm test                     # vitest run
npm run test:e2e             # Playwright E2E (tests/frontend_e2e/)

# Convention + telemetry checks (also run in CI):
bash scripts/check_conventions.sh
python scripts/validate_telemetry.py
```

Continuous integration runs convention checks, telemetry-schema validation against the golden examples, the Python test suite, and the frontend tests ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

---

## Where to look

| You want… | Read |
|---|---|
| **To install, launch, and use the app** (operator/analyst guide) | [`user_guide/`](user_guide/index.md) |
| **To contribute** (contract-first workflow, worktrees, PR gate) | [`developer_guide/`](developer_guide/index.md) |
| The full system specification (formulas, generators, training, deployment) | [`REBUILD_SPEC.md`](REBUILD_SPEC.md) — the index; sections under [`docs/spec/`](docs/spec/) |
| Physics & cost formulas (§3), generators (§4), training (§5), JAX architecture (§7), install/launch (§9) | `docs/spec/section_03…`, `…_04…`, `…_05…`, `…_07…`, `…_09…` |
| Binding decisions, LOCKED contracts, open blockers | [`LINEAGE.md`](LINEAGE.md) |
| The per-area stack registry (chosen libraries/frameworks + why) | [`STACK.md`](STACK.md) |
| Project rules: workflow, naming, file locations, engineering rules | [`CLAUDE.md`](CLAUDE.md) |
| The telemetry wire format every component speaks | `contracts/shared/telemetry_schema.md` |
| Per-feature contracts and review records | `contracts/<area>/`, `contracts/reviews/` |
