# Repository layout

The repo has a fixed directory structure; deviations from it are rejected at review. All locations are documented in [`CLAUDE.md`](../CLAUDE.md) §"File locations" — this page explains the *why* and shows the tree.

## Top-level tree

```
PowerSim/
├── CLAUDE.md               # project rules — non-negotiable
├── LINEAGE.md              # binding decisions, LOCKED contracts, blockers
├── REBUILD_SPEC.md         # spec index/TOC (section list + owners)
├── STACK.md                # per-area stack registry
├── README.md               # one-page overview + quickstart + where-to-look
│
├── docs/
│   └── spec/               # canonical specification ONLY (section_NN_<name>.md)
│   └── design/             # design studies, UX flows, product docs (not specs)
│
├── user_guide/             # operator/analyst guide (top-level, USER directive)
├── developer_guide/        # contributor guide (top-level, USER directive)
│
├── contracts/
│   ├── _example/           # worked example — copy this structure for new features
│   ├── <area>/             # per-feature contracts (env|training|harness|serving|frontend|frontend3d|shared)
│   └── reviews/            # reviewer-signed review records per feature
│
├── tests/
│   ├── <area>/             # test_<area>_<feature>.py — mirrors contracts/<area>/
│   ├── frontend*/          # <feature>.test.tsx (Vitest + RTL)
│   └── frontend_e2e/       # <scenario>.spec.ts (Playwright)
│
├── src/
│   ├── energy_go/          # Python package (env, training, harness, serving, generators, data, telemetry)
│   └── reference/          # plain-Python parity reference (§3/§4 oracle)
│
├── assets/
│   └── 3d/                 # .glb models + registry.json (LOCKED)
│
├── config/                 # site and asset YAML configs
│   ├── site_gansu.yaml
│   ├── device_models.yaml
│   └── tariff_model_schema.yaml
│
└── scripts/                # bash/Python utilities (verb_object.sh naming)
    ├── install_app.sh / install_app.ps1
    ├── run_app.sh / run_app.ps1
    ├── check_pr_gate.sh
    └── check_conventions.sh
```

## Key naming conventions

These are hard rules (CLAUDE.md), checked by `scripts/check_conventions.sh`:

| Thing | Convention | Example |
|---|---|---|
| Branches | `<type>/<area>-<feature>` — hyphens, all lowercase | `feat/env-battery-dynamics` |
| Contract files | `snake_case.md` under `contracts/<area>/` | `contracts/env/battery_dynamics.md` |
| Python tests | `tests/<area>/test_<area>_<feature>.py` | `tests/env/test_env_battery_dynamics.py` |
| Python modules | `snake_case.py` | `battery_dynamics.py` |
| React components | `PascalCase.tsx` (one per file) | `BatteryPanel.tsx` |
| Frontend unit tests | `tests/frontend*/<feature>.test.tsx` | `tests/frontend/battery_panel.test.tsx` |
| E2E tests | `tests/frontend_e2e/<scenario>.spec.ts` | `tests/frontend_e2e/smoke.spec.ts` |
| 3D assets | `kebab-case.glb` under `assets/3d/<function>/` | `assets/3d/turbines/vestas-v150-4.2.glb` |
| Config files | `config/<site|asset>_<name>.yaml` | `config/site_gansu.yaml` |

**The `<feature>` in branch, contract, and test names must match.** Branch `feat/env-battery-dynamics` ↔ contract `contracts/env/battery_dynamics.md` ↔ test `tests/env/test_env_battery_dynamics.py`.

**Never encode versions or dates in filenames.** `_v2`, `_final`, `_2026` are banned — git history is the version record.

## Reviewer routing

Contracts route to reviewers by area (CLAUDE.md):

| Contract area | Required reviewer |
|---|---|
| `env`, `training`, `harness`, `serving` | backend-reviewer |
| `frontend`, `frontend3d` | frontend-reviewer |
| `shared` | both for comment; locked by rl-architect |
| Cross-cutting docs (guides, README) | frontend-reviewer; area reviewers cc'd |

## Spec sections (stable citation keys)

Cite spec content as `§N.M`. The section numbering is canonical:

| §N | Content |
|---|---|
| §3 | Physics, battery dynamics, costs |
| §4 | Synthetic weather / load generators |
| §5 | Training pipeline (SAC) |
| §6 | Resolved-bug ledger |
| §7 | JAX architecture |
| §8 | Composable assets |
| §9 | Install / launch scripts |
| §10 | Env enhancements |
| §11 | Benchmarks |
| §12 | Historical weather pipeline |

Full index: [`REBUILD_SPEC.md`](../REBUILD_SPEC.md).
