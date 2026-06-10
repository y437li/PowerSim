---
name: contract-first-dev
description: Mandatory development workflow for all Energy GO implementation work (env, training, harness, serving, frontend, 3D). Contract and test cases are written and reviewed by code-reviewer BEFORE any implementation code. Use at the start of every development task.
---

# Contract-First Development Workflow

No implementation code is written until steps 1–3 are complete. This is a hard gate, not a guideline.

## Step 0 — Read the lineage

Read `LINEAGE.md` (project root) before anything else: pick up binding DECISION entries, locked shared contracts, and open blockers that affect your feature. If a prior entry contradicts what you were asked to do, raise it (BLOCKED entry + escalate to rl-architect) instead of silently picking a side.

**Throughout this workflow, append a LINEAGE.md entry at every milestone** (format defined in that file): CONTRACT_DRAFTED after step 1, TESTS_WRITTEN after step 2, REVIEW_APPROVED/REJECTED after step 3 (the reviewer appends this one), IMPLEMENTED after step 4, and the handoff entry at step 5. Append-only — never rewrite history.

## Step 1 — Write the contract

Create `contracts/<area>/<feature>.md` containing:

- **Interfaces:** exact function/endpoint/component signatures with types.
- **Data schemas:** every message/state shape, field by field, with **units** (MW vs kW, ¥/MWh, hours vs steps) and valid ranges.
- **Behavior:** what happens on edge inputs (SOC at bounds, zero generation, limit overflow), error behavior, and which REBUILD_SPEC.md sections this implements (cite section numbers).
- **Deliberate deviations:** if you are fixing a §6 known bug, state the old behavior, the new behavior, and why — QA's parity tests depend on this list.
- **Out of scope:** what this feature deliberately does not handle (respect the §3.6 fidelity boundary).

For anything two agents share (telemetry messages, checkpoint format, REST/websocket API), the contract must be agreed with the consuming agent and locked by rl-architect before step 2.

## Step 2 — Define test cases (before any implementation)

All test files live under the single top-level `tests/` tree — never next to source code. Standard layout and naming:

```
tests/
  env/        test_env_<feature>.py        # physics, battery, costs, reward, generators
  training/   test_training_<feature>.py   # SAC loop, normalization, checkpoints, baselines
  harness/    test_harness_<feature>.py    # training/testing interface for the env
  serving/    test_serving_<feature>.py    # API, export, telemetry streams
  frontend/   <feature>.test.tsx           # React components, dashboard
  frontend3d/ <feature>.test.tsx           # 3D scene, power-flow animation
  contracts/  test_contract_<name>.py      # cross-agent schema validation
```

`<feature>` matches the contract filename: `contracts/env/battery_dynamics.md` → `tests/env/test_env_battery_dynamics.py`. One contract → one test file. Reviewer-added cases (step 3) go in the same file, marked with a `# reviewer:` comment.

Derive the cases from the contract and REBUILD_SPEC.md formulas:

- Each physics/cost test asserts a **hand-computed expected number** (show the arithmetic in a comment), not just shape or "no error".
- Cover the contract's edge cases explicitly — boundaries, limit hits, constraint interactions.
- Frontend/serving: schema-validation tests for every message type; component tests against fixture data matching the contract.
- Tests must fail at this point (nothing is implemented). That's correct — commit them red.

## Step 3 — Reviewer gate (mandatory)

Submit the contract + test cases to the responsible reviewer:
- `contracts/env|training|harness|serving/` → **backend-reviewer**
- `contracts/frontend|frontend3d/` → **frontend-reviewer**
- Shared contracts consumed by both sides (telemetry schema, checkpoint format, `assets/3d/registry.json`) → **both reviewers**, locked by rl-architect.

The reviewer checks:

- Test cases actually pin down the spec (would a wrong sign, wrong unit, or off-by-one slip through?).
- Expected values are correctly hand-derived from §3/§4 formulas.
- Test files follow the `tests/` layout and naming convention from step 2.
- The contract doesn't contradict REBUILD_SPEC.md or another locked contract.

The reviewer does not just approve/reject — it must **actively hunt for edge cases the developer missed and add test cases for them** directly to the same test file, marked with a `# reviewer: <reason>` comment (with hand-computed expected values, same standard as developer tests). Think adversarially: boundary values, constraint interactions, degenerate inputs (zero generation, zero load), unit traps, seasonal/calendar edges. The approved test suite = developer cases + reviewer cases.

Record the approval in `contracts/reviews/<feature>.md` (reviewer verdict, date, list of reviewer-added cases, the exact test-file versions approved). **No approval, no implementation.** If the reviewer rejects, revise and resubmit.

## Step 4 — Implement

Write code until the approved tests pass.

- **Never modify an approved test to make it pass.** If you believe a test is wrong, go back to step 3 — the change needs reviewer re-approval and a note in the review record.
- Stay inside the contract; if implementation reveals the contract is wrong, stop and revise the contract first (architect + reviewer re-approval if it's a shared contract).

## Step 5 — Hand off to QA

Submit to the **qa-engineer** agent (`qa-verification` skill) with: contract path, review record path, test suite location, and how to run it. QA's verdict — not your own test run — is what marks the task done.
