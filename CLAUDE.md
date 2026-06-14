# Energy GO Rebuild — Project Rules

These rules apply to every agent working in this repo. They are non-negotiable.

## Source of truth
- The system spec is split into per-section files under `docs/spec/section_NN_<name>.md`; **`REBUILD_SPEC.md` (root) is the index/TOC** — section list, links, and the **Owner** of each section. Section numbering is **stable and canonical**: contracts, LINEAGE decisions, and charters cite `§N.M` (formulas §3, generators §4, training §5, resolved-bug ledger §6, JAX architecture §7, composable assets §8, install/launch §9, env enhancements §10, benchmarks §11, weather pipeline §12). When code and spec disagree, the spec wins; when the spec is ambiguous, escalate to rl-architect (or the section Owner for its specifics) — never guess. The section Owner maintains the file; overall spec authority and the human merge gate for any spec-content change are unchanged.

## Before any work
- **Check the three sources of record:** `git log --oneline -15` (what merged), `gh pr list --state open` (what's in flight and its gate status), and `LINEAGE.md` (binding decisions, locked contracts, open blockers — the things git can't tell you). PR state is the status record; LINEAGE.md gets entries only for DECISION / LOCKED / BLOCKED events, append-only.

## Workflow
- All implementation work follows the `contract-first-dev` skill: contract → test cases → reviewer approval → implement → QA. **No implementation before reviewer approval of the tests.**
- Reviewer routing: `contracts/env|training|harness|serving/` → backend-reviewer; `contracts/frontend|frontend3d/` → frontend-reviewer; shared contracts → both for comment, locked by rl-architect on its own authority (reviewer input is advisory, not a gate).
- **rl-architect authority:** rl-architect's decision and contract-lock PRs (area `meta`, no implementation code) merge on rl-architect's own authority — no reviewer APPROVE or QA_PASS required. Exception — these escalate to the human user for explicit approval before merge: changes to `REBUILD_SPEC.md`, altering or unlocking a LOCKED contract, and decisions that are costly to reverse (data formats already persisted, published APIs, cross-area architecture changes). When in doubt whether a decision is important enough, escalate.
- **Never modify a reviewer-approved test to make it pass.** If a test seems wrong, go back through review.
- QA (qa-engineer, `qa-verification` skill) issues the verdict that closes a task — not your own test run.
- **All changes go through GitHub PRs.** Never commit to `main`. Branch `feat/<area>-<feature>`, open a draft PR for the contract+tests gate, mark ready after implementation. Every review comment gets an answer (fixing commit or reasoned reply). Merge requires the required reviewer's latest verdict = APPROVE **and** QA's latest = QA_PASS — or QA_PASS_WITH_ISSUES **with** an rl-architect APPROVE sign-off (exception: rl-architect decision PRs — see **rl-architect authority** above).
- **Verdict markers (machine-checkable; shared-account constraint).** This repo's GitHub account is **shared** across all agents, so `gh pr review --approve`/`--request-changes` returns HTTP 422 on a PR you authored — it cannot be the verdict mechanism. Instead, **every review/QA verdict is a top-level PR comment** whose **first line is exactly** one of: `VERDICT: APPROVE`, `VERDICT: REQUEST_CHANGES`, `VERDICT: COMMENT`, `VERDICT: QA_PASS`, `VERDICT: QA_FAIL`, `VERDICT: QA_PASS_WITH_ISSUES`; the **second line** is `reviewer: <agent-name>` (optionally followed by scope text). The **newest marker per reviewer wins** — supersede by posting a new comment. The gate is checked by `scripts/check_pr_gate.sh <pr> --required <reviewer>`: the required reviewer's latest marker must be APPROVE, QA's latest must be QA_PASS (or QA_PASS_WITH_ISSUES + an rl-architect APPROVE marker), and no reviewer's latest may be REQUEST_CHANGES. Inline comments are still encouraged for specifics, but the top-level marker is the binding record.

## File locations (no exceptions)
- Contracts: `contracts/<area>/<feature>.md`; review records: `contracts/reviews/<feature>.md`. Worked example: `contracts/_example/`.
- Tests: single `tests/` tree only — `tests/<area>/test_<area>_<feature>.py`, frontend `tests/frontend*/<feature>.test.tsx`. `<feature>` matches the contract filename. Reviewer-added cases marked `# reviewer:`. Never put tests next to source code. There is **no `tests/contracts/`** directory (PR #4 scaffolding correctly omitted it); tests for shared contracts live under `tests/shared/`, an area defined by a future DECISION when its first feature lands (see LINEAGE D15).
- 3D assets: single `assets/3d/` tree organized by function, resolved only through `assets/3d/registry.json` — no hardcoded asset paths in scene code.

## Naming conventions (no exceptions)

**Branches** — `<type>/<area>-<feature>`, all lowercase, hyphens within the feature name:
- `feat/env-battery-dynamics` — new feature (the contract-first-dev flow)
- `fix/training-checkpoint-roundtrip` — bug fix on merged work (still goes through the full review+QA gates)
- `chore/<topic>` — tooling/config/docs with no behavior change (still via PR)
- `<area>` is one of: `env`, `training`, `harness`, `serving`, `finance`, `frontend`, `frontend3d`, `assets`, `config`, `meta`
- `<feature>` matches the contract filename: branch `feat/env-battery-dynamics` ↔ `contracts/env/battery_dynamics.md` (hyphens in branch, underscores in filename)

**Files:**
- Python modules & packages: `snake_case.py` / `snake_case/` — descriptive nouns (`battery_dynamics.py`, not `utils2.py`)
- Python tests: `tests/<area>/test_<area>_<feature>.py` (feature matches the contract filename)
- Contracts: `contracts/<area>/<feature>.md` in `snake_case`; review records: `contracts/reviews/<feature>.md`
- React components: `PascalCase.tsx` (one component per file, filename = component name); hooks: `useCamelCase.ts`; non-component TS (utils, stores, clients): `camelCase.ts`
- Frontend unit tests: `tests/frontend*/<feature>.test.tsx` (Vitest+RTL) where `<feature>` matches the file under test
- Frontend E2E tests: `tests/frontend_e2e/<scenario>.spec.ts` (Playwright; D20) — `<scenario>` is the browser scenario (e.g. `smoke`), not a component name; harness contract `contracts/frontend/playwright_harness.md`
- 3D assets: `kebab-case.glb` under `assets/3d/<function>/` (e.g. `assets/3d/turbines/vestas-v150-4.2.glb`); `registry.json` keys = the asset IDs used in config YAML, verbatim
- Config: `config/<site|asset>_<name>.yaml` in `snake_case` (e.g. `site_gansu.yaml`)
- Markdown docs: root-level project docs are `SCREAMING_CASE.md` (CLAUDE.md, LINEAGE.md, REBUILD_SPEC.md); all other docs `snake_case.md`
- Scripts: `scripts/<verb>_<object>.(sh|py)` (e.g. `scripts/check_conventions.sh`)
- Never encode versions or dates in filenames (`_v2`, `_final`, `_new`) — git history is the version record

## Engineering rules
- Units are part of every interface: state MW vs kW, MWh, ¥/MWh explicitly in contracts, schemas, and displayed values. Unit conversions live in one named, tested utility.
- Physics/cost tests assert hand-computed expected numbers with the arithmetic shown in a comment — "no exception" is not a test.
- JAX core: pure functions, `jnp.where`/`clip` instead of data-dependent branching, explicit RNG key threading, fixed seed → identical trajectory.
- Constraint enforcement order is part of the spec (§3.6): parse/clip actions → battery/SOC → cap flows-to-load → PCC export limit → grid import limit → costs.
- Report results honestly: failing tests, unmet baselines, and skipped steps are reported as such, with output.
- **Stack registry:** `STACK.md` is the single registry of the binding stack choice per area. Any PR that introduces or changes a stack element (language, framework, major library, test runner, build/CI tool, or an asset/runtime/data format) MUST update `STACK.md` in the same PR; reviewers check contracts and implementations against it.
- **Public repo — never commit proprietary data (USER directive; LINEAGE D32):** this repository is **PUBLIC**. Proprietary or partner/customer-confidential data — negotiated tariffs, contract terms, unpublished partner device specs (e.g. a company's SST solution) — **MUST NEVER be committed**. Such data lives ONLY in a **gitignored private overlay** (path via the `ENERGY_GO_PRIVATE_CONFIG` env var) that the resolver merges over the public `config/*.yaml` at load time (overlay wins on ID collision; absent overlay = public-only behavior, unchanged). Public config carries only public data plus **provisional stubs** for pending proprietary entries (provenance: `USER-provided, pending`). Reviewers reject any PR that commits confidential values; treat a suspected proprietary commit as a stop-the-line item.
