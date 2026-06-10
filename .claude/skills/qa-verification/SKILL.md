---
name: qa-verification
description: QA process for verifying Energy GO rebuild deliverables. Use when verifying any completed work item — env physics, training pipeline, serving API, or frontend — before it is accepted. Checks work against its contract and reviewer-approved test cases, runs parity/conservation/boundary tests, and produces a pass/fail report with evidence.
---

# QA Verification Process

You are verifying a deliverable for the Energy GO rebuild. REBUILD_SPEC.md is the source of truth. Never accept "it looks right" — every claim needs a command you ran and output you saw.

## Step 0 — Preconditions (reject immediately if missing)

1. The deliverable has a **contract** in `contracts/` (interface signatures, data schemas, units, value ranges).
2. Test cases exist and were **approved by code-reviewer BEFORE implementation** (check the review record in `contracts/reviews/`). If tests were written or modified after implementation without re-review, send it back.

## Step 1 — Test integrity

- Diff the test files against their reviewer-approved version. Any weakening (loosened tolerance, deleted assert, skipped case, widened expected range) is an automatic fail — implementation must satisfy the approved tests, not the other way around.
- Confirm tests assert **numerical values**, not just "no exception". A physics test without an expected number is not a test.

## Step 2 — Run the approved tests

Run the full suite. Report exact pass/fail counts and paste failing output verbatim. No summarizing failures away.

## Step 3 — Domain checks (always, regardless of what the tests cover)

For env/physics work:
- **Parity:** new JAX env vs. old Python env step-for-step on fixed seeds (where behavior wasn't deliberately fixed per §6 — deliberate fixes must be listed in the contract).
- **Energy conservation:** per source, P_x = to_load + to_bat + to_grid + curtailed, every step.
- **Constraint order** (§3.6): actions → battery/SOC → cap-to-load → PCC export → import → costs. Verify with a scenario that triggers multiple constraints in one step.
- **Boundary cases:** SOC exactly at 0.2/0.9, wind at 3.0 and 25.0 m/s, tariff boundaries 10:30/11:30, calendar month rollover, export exactly at the PCC limit, spread noise driving sell price toward buy price.
- **Units audit:** MW vs kW, ¥/MWh vs ¥/kWh, Δt consistency in every formula.

For training work:
- Checkpoint round-trip: save → load → identical actions on fixed obs.
- Normalization stats saved with checkpoint and applied at inference.
- RL agent vs. baselines (no-battery, rule-based TOU) on the full eval year — report the actual cost numbers.

For serving/frontend work:
- Validate every websocket/REST message against the contract schema (field names, units, types).
- Exported policy (ONNX/weights) produces the same actions as the training checkpoint on fixed inputs (tolerance in the contract).

## Step 4 — Report

```
VERDICT: PASS | FAIL | PASS-WITH-ISSUES
Contract: <path>  Tests approved: <review record>
Suite: X passed / Y failed
Domain checks: <each check, result, evidence (command + key output)>
Issues: <numbered, with reproduction steps>
```

FAIL goes back to the implementing agent. PASS-WITH-ISSUES requires rl-architect sign-off. You never fix code yourself — you verify.

## Step 5 — Post the verdict on the PR

The verdict is delivered as a PR comment (`gh pr comment`), which is the durable record — do not log it in LINEAGE.md. Verify the gate history on the PR itself: a PR with no stage-1 (contract+tests) APPROVE review in its timeline fails Step 0 preconditions. If verification surfaces a binding-decision conflict or leaves work blocked, append a DECISION-request or BLOCKED entry to LINEAGE.md.
