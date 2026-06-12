# Stack registry

The single binding record of every stack choice is **[`STACK.md`](../STACK.md)** at the repository root. This page explains how to read it and what to do when you add or change a stack element.

## Why STACK.md exists

Individual PRs choose libraries, frameworks, and tools in isolation; without a registry those choices scatter across PR comments and LINEAGE entries and become impossible to audit. `STACK.md` is the one place that answers "what library/tool is approved for area X, which PR chose it, and why?".

Reviewers check implementations against `STACK.md` during code review. A stack choice not recorded there is **not approved**.

## Reading STACK.md

Each row covers one area. Columns:

| Column | What it means |
|---|---|
| **Area** | The energy_go subsystem (env core, training, serving, frontend, etc.) |
| **Chosen stack** | The binding choice — library, framework, pattern, data format |
| **Version / variant notes** | Where the choice is version-sensitive (e.g. drei v9 vs v10) |
| **Set by** | The PR number or LINEAGE decision that bound the choice |

The "Out of registry" section at the bottom records things explicitly **not** in the stack, so a contributor doesn't accidentally re-propose them.

## Adding or changing a stack element

Any PR that **introduces or changes** a stack element — language, framework, major library, test runner, build/CI tool, asset/runtime/data format — **must update `STACK.md` in the same PR**. The change is:

1. Add a new row (if new) or update the existing row (if changing a version/variant).
2. Fill in the "Set by" column with the PR number of this PR.
3. If removing a choice, move it to the "Out of registry" section with a note.

Reviewers check `STACK.md` is updated and will leave `VERDICT: REQUEST_CHANGES` if it isn't.

## Current stack at a glance

See [`STACK.md`](../STACK.md) for the full, up-to-date table. Key choices as of the last update:

| Area | Stack |
|---|---|
| Env core | Pure JAX (`jax`/`jnp`), jit/vmap, explicit RNG threading |
| Parity reference | Plain Python + NumPy (no JAX — independent 2nd implementation) |
| Training | SAC via `sbx-rl` (PyPI package `sbx-rl`, NOT `sbx`); `optax`, `flax`, `flashbax` |
| Serving | FastAPI + uvicorn + websockets |
| Frontend shell | React + Vite + TypeScript + Zustand |
| 3D scene | Three.js / React Three Fiber (`@react-three/fiber@^8`) + `drei@^9` |
| Dashboard charts | Recharts |
| Backend tests | pytest |
| Frontend unit tests | Vitest + React Testing Library |
| E2E tests | Playwright (`@playwright/test`) + Chromium |
| Config format | YAML (`config/<site|asset>_<name>.yaml`) |
| Telemetry wire format | JSON per `contracts/shared/telemetry_schema.md` v1.0.0 (LOCKED) |
| Install/launch | `scripts/install_app.{sh,ps1}` + `run_app.{sh,ps1}` via `uv` + Node LTS |

> Always read `STACK.md` directly — the table above is a snapshot and may lag the latest changes.

## Locked contracts

Certain shared contracts are **LOCKED** — they have a version number and may not be changed without a superseding DECISION:

- `contracts/shared/telemetry_schema.md` v1.0.0 — the JSON wire format (LOCKED PR #6)
- `contracts/shared/checkpoint_format.md` v1.0.0 — checkpoint layout (LOCKED PR #41)
- `assets/3d/registry.json` — 3D asset IDs (LOCKED PR #24)
- `contracts/shared/device_model_schema.md` v2.0.0 — site/device YAML schema (LOCKED PR #87)
- `contracts/shared/tariff_model_schema.md` v1.0.0 — tariff YAML schema (LOCKED PR #91)
- `contracts/shared/config_validation.md` v1.0.0 — two-tier site-config validator (LOCKED PR #89)

**Authoritative record:** [`LINEAGE.md`](../LINEAGE.md) is the definitive list of LOCKED entries. The above is a snapshot; when in doubt, read LINEAGE directly. A PR that deviates from a LOCKED contract without a superseding DECISION is a stop-the-line item.
