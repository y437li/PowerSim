# Energy GO Rebuild — Project Rules

These rules apply to every agent working in this repo. They are non-negotiable.

## Source of truth
- `REBUILD_SPEC.md` defines the system: formulas (§3), generators (§4), training (§5), known bugs to fix (§6), JAX architecture (§7). When code and spec disagree, the spec wins; when the spec is ambiguous, escalate to rl-architect — never guess.

## Before any work
- **Read `LINEAGE.md` first.** It holds binding DECISION entries, locked shared contracts, and open blockers. Append an entry at every milestone of your work (format defined in the file). Append-only — never edit past entries.

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

## Engineering rules
- Units are part of every interface: state MW vs kW, MWh, ¥/MWh explicitly in contracts, schemas, and displayed values. Unit conversions live in one named, tested utility.
- Physics/cost tests assert hand-computed expected numbers with the arithmetic shown in a comment — "no exception" is not a test.
- JAX core: pure functions, `jnp.where`/`clip` instead of data-dependent branching, explicit RNG key threading, fixed seed → identical trajectory.
- Constraint enforcement order is part of the spec (§3.6): parse/clip actions → battery/SOC → cap flows-to-load → PCC export limit → grid import limit → costs.
- Report results honestly: failing tests, unmet baselines, and skipped steps are reported as such, with output.
