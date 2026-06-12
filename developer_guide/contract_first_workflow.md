# Contract-first workflow

Every feature in Energy GO goes through a five-step gate before any implementation code is written. The worked example lives in `contracts/_example/` — read it before starting a new feature.

## The five steps

```
1. Write the contract   →   contracts/<area>/<feature>.md
2. Write the tests      →   tests/<area>/test_<area>_<feature>.py
3. Reviewer approves    →   contracts/reviews/<feature>.md  +  VERDICT: APPROVE on the PR
4. Implement            →   src/ (or frontend src/)
5. QA verifies          →   VERDICT: QA_PASS on the PR  →  team-lead merges
```

**No implementation before step 3.** This is enforced: a reviewer will reject an implementation PR that lands before tests are approved.

**Never modify a reviewer-approved test to make it pass.** If a test seems wrong, go back through review (step 3 again). Tests are locked once approved.

## Step 1: Write the contract

A contract is a Markdown file at `contracts/<area>/<feature>.md` that answers:

- **Interface** — function signatures, types, shapes (with units: MW, MWh, ¥/MWh).
- **Behaviour** — what the function computes, in terms of the spec (`§3.2`, `§5.1`).
- **Constraints** — limits, ordering rules, error conditions.
- **What is explicitly out of scope** — prevents scope creep.

Copy the structure from `contracts/_example/wind_power_curve.md`. Open a **draft PR** on branch `feat/<area>-<feature>` with just the contract + tests files.

## Step 2: Write the test cases

Tests live in `tests/<area>/test_<area>_<feature>.py`. They must:

- Assert **hand-computed expected numbers** with the arithmetic shown in a comment — "no exception raised" is not a test.
- Pin units in every assertion (a kW vs MW slip will fail the right test).
- Be red (failing) until the implementation exists — the reviewer checks they're testing the right thing by running them against no-code.

```python
# Good test: arithmetic in comment, exact value, unit clear
def test_degradation_cost_per_step():
    # §3.5: degradation = 0.5 * k_deg * (C_rate)^2 * dt * CAPEX_per_MWh
    # = 0.5 * 1e-4 * (0.5)^2 * 1.0 * 300_000 = 3.75 ¥
    result = compute_degradation_cost(c_rate=0.5, dt=1.0, k_deg=1e-4, capex=300_000)
    assert abs(result - 3.75) < 1e-6  # ¥
```

## Step 3: Reviewer approves

Push the draft PR. The reviewer:

1. Re-derives expected values hand-computed in the tests.
2. Checks all spec citations are accurate (`§N.M`).
3. Checks units are explicit.
4. Checks naming conventions.
5. Adds reviewer-marked test cases (`# reviewer:`) for missed edge cases.
6. Posts `VERDICT: APPROVE` (or `VERDICT: REQUEST_CHANGES`) as the **first line** of a top-level PR comment, with `reviewer: <name>` on the second line.

The PR gate (`scripts/check_pr_gate.sh`) reads these markers. See [Verdict markers & PR gate](verdict_markers.md) for the exact format.

Once APPROVE is posted, **mark the PR ready for review** and begin implementation.

## Step 4: Implement

Implement in `src/` (or the frontend). Rules:

- **One named function per spec behaviour** — no anonymous lambdas for physics.
- **JAX core**: pure functions, `jnp.where`/`clip` instead of data-dependent Python branching, explicit RNG key threading, fixed seed → identical trajectory.
- **Constraint enforcement order** is part of the spec (§3.6): parse/clip actions → battery/SOC → cap flows-to-load → PCC export limit → grid import limit → costs. Do not reorder.
- **Units conversions** live in one named, tested utility — never inline.
- Push implementation commits to the same PR branch; the gate re-checks that the latest marker still covers the head commit (CLAUDE.md head-coverage rule).

## Step 5: QA verifies

QA engineer runs the `qa-verification` skill against the reviewer-approved tests and the contract. They post `VERDICT: QA_PASS` or `VERDICT: QA_FAIL` (with specifics). The gate requires QA_PASS.

**Do not merge yourself.** The team lead merges after the gate passes.

## Reviewer routing quick-reference

| PR area | Required reviewer |
|---|---|
| `contracts/env/`, `contracts/training/`, `contracts/harness/`, `contracts/serving/` | backend-reviewer |
| `contracts/frontend/`, `contracts/frontend3d/` | frontend-reviewer |
| `contracts/shared/` | both for comment; locked by rl-architect |
| docs PRs | frontend-reviewer (docs-style rule) |

## Naming alignment reminder

Branch name, contract file, and test file must use the same `<feature>` string:

```
Branch:    feat/env-battery-dynamics
Contract:  contracts/env/battery_dynamics.md     ← underscores
Test:      tests/env/test_env_battery_dynamics.py
```

Hyphens in the branch name → underscores in filenames. The convention checker (`scripts/check_conventions.sh`) catches mismatches.
