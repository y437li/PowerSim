# Verdict markers & PR gate

This repo's GitHub account is **shared across all agents**, so `gh pr review --approve` returns HTTP 422 on any PR you authored — it cannot be the verdict mechanism. Instead, all review and QA verdicts are posted as **top-level PR comments** with a machine-readable first line.

## Verdict format

Every review or QA verdict is a top-level PR comment whose **first line is exactly** one of:

```
VERDICT: APPROVE
VERDICT: REQUEST_CHANGES
VERDICT: COMMENT
VERDICT: QA_PASS
VERDICT: QA_FAIL
VERDICT: QA_PASS_WITH_ISSUES
```

The **second line** is `reviewer: <agent-name>` (optionally followed by scope text). The **newest marker per reviewer wins** — supersede a prior verdict by posting a new comment; do not edit old comments.

Example of a valid verdict comment:

```
VERDICT: APPROVE
reviewer: backend-reviewer @ a0a9e70
Battery dynamics physics checks out — arithmetic in test_degradation_cost_per_step verified.
Reviewer-added cases added; all pass.
```

Inline PR comments are still encouraged for specifics, but **only the top-level marker is the binding record** the gate reads.

## The gate: `scripts/check_pr_gate.sh`

The gate script reads verdict markers from PR comments via the GitHub API and checks:

1. The **required reviewer's latest marker** is `APPROVE` (no `REQUEST_CHANGES` from any reviewer).
2. The **latest QA marker** is `QA_PASS` (or `QA_PASS_WITH_ISSUES` with an rl-architect `APPROVE`).
3. All **gate-deciding markers post-date the head commit** (head-coverage rule — see below).

```bash
# Check a PR's gate status:
scripts/check_pr_gate.sh 95 --required frontend-reviewer

# Exit 0 = mergeable; exit 1 = blocked; exit 2 = usage/lookup error
```

> **⚠️ Never pipe this script.** A pipe replaces the script's exit code with the downstream command's, so a BLOCKED gate silently looks like success. This caused two merge breaches. Use the bare form:
>
> ```bash
> # CORRECT — gate is checked by exit code:
> if scripts/check_pr_gate.sh <pr> --required <reviewer>; then
>   echo "Gate passes — team-lead merges"
> fi
>
> # WRONG — pipe discards exit code:
> scripts/check_pr_gate.sh <pr> --required <reviewer> | tail -5
> ```
>
> To capture output without a pipe: `out=$(scripts/check_pr_gate.sh ...); rc=$?`

## Head-coverage rule

Verdict markers must **post-date the current head commit**. A verdict posted before the last code push does not cover the new code. This was added after the PR #10 incident (LINEAGE).

**Consequence:** if you push a new commit after receiving APPROVE or QA_PASS, those markers are invalidated — you must re-request review and re-QA. The gate script checks timestamps and blocks if a gate-deciding marker is older than the head commit's `committedDate`.

## What merge requires

| Situation | Required markers |
|---|---|
| Normal feature PR | Required reviewer's latest = `APPROVE` **and** QA's latest = `QA_PASS` |
| QA_PASS_WITH_ISSUES | QA_PASS_WITH_ISSUES + rl-architect `APPROVE` sign-off |
| rl-architect decision PR (area `meta`, no implementation code) | rl-architect's own authority — no reviewer APPROVE or QA_PASS required |

**You do not merge.** Only the team lead merges, after confirming the gate is PASS.

## Exceptions that escalate to the human user

Even rl-architect's own authority does not cover:

- Changes to `REBUILD_SPEC.md`
- Altering or unlocking a LOCKED contract
- Decisions that are costly to reverse (persisted data formats, published APIs, cross-area architecture changes)

These escalate to the human user for explicit approval before merge.

## Self-checking before pinging team-lead

Use the `pr-merge-gate` skill to verify the gate status yourself before asking for a merge:

```bash
# Via Claude Code (checks gate + reports blocking issues):
/pr-merge-gate
```

This runs `check_pr_gate.sh` and explains any blocking issues so you can fix them before escalating.
