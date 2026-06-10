# Energy GO Rebuild — Project Rules

These rules apply to every agent working in this repo. They are non-negotiable.

## Source of truth
- `REBUILD_SPEC.md` defines the system: formulas (§3), generators (§4), training (§5), known bugs to fix (§6), JAX architecture (§7). When code and spec disagree, the spec wins; when the spec is ambiguous, escalate to rl-architect — never guess.

## Before any work
- **Check the three sources of record:** `git log --oneline -15` (what merged), `gh pr list --state open` (what's in flight and its gate status), and `LINEAGE.md` (binding decisions, locked contracts, open blockers — the things git can't tell you). PR state is the status record; LINEAGE.md gets entries only for DECISION / LOCKED / BLOCKED events, append-only.

## Workflow
- All implementation work follows the `contract-first-dev` skill: contract → test cases → reviewer approval → implement → QA. **No implementation before reviewer approval of the tests.**
- Reviewer routing: `contracts/env|training|harness|serving/` → backend-reviewer; `contracts/frontend|frontend3d/` → frontend-reviewer; shared contracts → both, locked by rl-architect.
- **Never modify a reviewer-approved test to make it pass.** If a test seems wrong, go back through review.
- QA (qa-engineer, `qa-verification` skill) issues the verdict that closes a task — not your own test run.
- **All changes go through GitHub PRs.** Never commit to `main`. Branch `feat/<area>-<feature>`, open a draft PR for the contract+tests gate, mark ready after implementation. Reviewers verdict with `gh pr review` (inline comments, approve/request-changes); QA posts its verdict as a PR comment; every review comment gets an answer (fixing commit or reasoned reply). Merge requires reviewer APPROVE + QA_PASS.

## File locations (no exceptions)
- Contracts: `contracts/<area>/<feature>.md`; review records: `contracts/reviews/<feature>.md`. Worked example: `contracts/_example/`.
- Tests: single `tests/` tree only — `tests/<area>/test_<area>_<feature>.py`, frontend `tests/frontend*/<feature>.test.tsx`. `<feature>` matches the contract filename. Reviewer-added cases marked `# reviewer:`. Never put tests next to source code.
- 3D assets: single `assets/3d/` tree organized by function, resolved only through `assets/3d/registry.json` — no hardcoded asset paths in scene code.

## Naming conventions (no exceptions)

**Branches** — `<type>/<area>-<feature>`, all lowercase, hyphens within the feature name:
- `feat/env-battery-dynamics` — new feature (the contract-first-dev flow)
- `fix/training-checkpoint-roundtrip` — bug fix on merged work (still goes through the full review+QA gates)
- `chore/<topic>` — tooling/config/docs with no behavior change (still via PR)
- `<area>` is one of: `env`, `training`, `harness`, `serving`, `frontend`, `frontend3d`, `assets`, `config`, `meta`
- `<feature>` matches the contract filename: branch `feat/env-battery-dynamics` ↔ `contracts/env/battery_dynamics.md` (hyphens in branch, underscores in filename)

**Files:**
- Python modules & packages: `snake_case.py` / `snake_case/` — descriptive nouns (`battery_dynamics.py`, not `utils2.py`)
- Python tests: `tests/<area>/test_<area>_<feature>.py` (feature matches the contract filename)
- Contracts: `contracts/<area>/<feature>.md` in `snake_case`; review records: `contracts/reviews/<feature>.md`
- React components: `PascalCase.tsx` (one component per file, filename = component name); hooks: `useCamelCase.ts`; non-component TS (utils, stores, clients): `camelCase.ts`
- Frontend tests: `tests/frontend*/<feature>.test.tsx` where `<feature>` matches the file under test
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
