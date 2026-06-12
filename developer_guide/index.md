# Energy GO — Developer Guide

This guide is for **contributors** to the Energy GO codebase: understanding the repository layout, following the contract-first workflow, keeping worktrees clean, and navigating the PR gate. For **using** the app, see [`user_guide/`](../user_guide/index.md). For the system specification, see [`REBUILD_SPEC.md`](../REBUILD_SPEC.md).

> **Read [`CLAUDE.md`](../CLAUDE.md) first.** This guide elaborates on those rules and shows them in action — it does not duplicate them. CLAUDE.md is authoritative; this guide is the walkthrough.

## Contents

| Page | What it covers |
|---|---|
| [Repository layout](repo_layout.md) | Top-level tree, per-area directory conventions, file naming |
| [Contract-first workflow](contract_first_workflow.md) | The full contract → tests → review → implement → QA cycle, with examples |
| [Worktree discipline](worktrees.md) | Where to put worktrees, naming, when to remove them |
| [Verdict markers & PR gate](verdict_markers.md) | How to leave review verdicts, how `check_pr_gate.sh` reads them, what merge requires |
| [Stack registry](stack.md) | Pointer to `STACK.md`, how to add or change a stack element |

## Quick orientation

Energy GO is a **spec-driven, contract-gated rebuild**. Every piece of behaviour is pinned by:

1. **Spec** — `REBUILD_SPEC.md` (index/TOC) + `docs/spec/section_NN_<name>.md` (the authoritative physics / costs / training / architecture).
2. **Decisions** — `LINEAGE.md`: binding choices that git can't tell you (e.g. Δt = 1 h, SAC on JAX, LOCKED contract versions).
3. **Contracts** — `contracts/<area>/<feature>.md`: per-feature interface specs. Contracts come **before** any implementation.
4. **Reviewer-approved tests** — `tests/<area>/test_<area>_<feature>.py`: locked after reviewer APPROVE; implementations must pass them, never modify them to make them pass.
5. **PR gate** — `scripts/check_pr_gate.sh`: machine-checks that the required reviewer's verdict is APPROVE and QA's is QA_PASS before merge.

The three sources of record at session start (from [`CLAUDE.md`](../CLAUDE.md)):

```bash
git log --oneline -15          # what merged
gh pr list --state open        # what's in flight
cat LINEAGE.md                 # binding decisions and locked contracts
```
