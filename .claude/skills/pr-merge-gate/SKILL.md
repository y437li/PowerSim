---
name: pr-merge-gate
description: Check whether an Energy GO PR is mergeable under the verdict-marker convention. Use before merging any PR, or when asked whether a PR's gates have passed.
---

# PR Merge Gate Check

All agents share one GitHub account, so formal `gh pr review --approve/--request-changes` is impossible on our own PRs. Verdicts are **top-level PR comments**; this skill is how to read them.

## Marker grammar

- First line exactly one of: `VERDICT: APPROVE` | `VERDICT: REQUEST_CHANGES` | `VERDICT: COMMENT` | `VERDICT: QA_PASS` | `VERDICT: QA_FAIL` | `VERDICT: QA_PASS_WITH_ISSUES`
- Second line: `reviewer: <agent-name>`
- **Newest marker per distinct reviewer wins** (supersession by re-posting).

## Merge requirements

| PR type | Requirement |
|---|---|
| Implementation PR (feat/fix) | Required reviewer's latest = `APPROVE` **and** QA's latest = `QA_PASS` (or `QA_PASS_WITH_ISSUES` + rl-architect sign-off comment) |
| Contract gate (draft PR stage) | Reviewer `APPROVE` lets implementation begin — the PR does NOT merge at gate stage |
| rl-architect meta PR (area `meta`, no implementation code) | Merges on rl-architect authority — no reviewer/QA gate |
| REBUILD_SPEC.md or LOCKED-contract changes | Human user approval, surfaced via team-lead — never self-merged |

Plus always: CI green, zero unresolved review threads (every comment answered by fixing commit or reasoned reply), branch up to date with main (no reverse-diffs of merged work).

## How

- Run `scripts/check_pr_gate.sh <pr-number>` if it exists (task #12); otherwise read markers manually: `gh pr view <n> --json comments` (or REST `gh api repos/{owner}/{repo}/issues/<n>/comments` if GraphQL 401s) and apply newest-wins per reviewer.
- Merge style: **squash** (`gh pr merge <n> --squash --delete-branch`) — main history is linear, one commit per PR.
- After merging: remove the branch worktree (`git worktree remove ...`), and verify the task list reflects the completion.
