# Agent Lineage — Energy GO Rebuild

Append-only ledger shared by all agents. This is the team's memory: every agent **reads it before starting work** (to pick up prior decisions, locked contracts, and open blockers) and **appends an entry** whenever it starts, hands off, gets a review verdict, or closes work.

Rules:
- Append-only. Never edit or delete a past entry — corrections get a new entry referencing the old one by seq number.
- One entry per event, newest at the bottom of the Ledger.
- Every handoff names the receiving agent; every status change names the entry it follows.
- rl-architect decisions are recorded here with status DECISION — they are binding until superseded by a later DECISION entry.

## Entry format

```
### [seq] YYYY-MM-DD — <agent> — <feature>
- Status: DECISION | CONTRACT_DRAFTED | TESTS_WRITTEN | REVIEW_APPROVED | REVIEW_REJECTED |
          IMPLEMENTED | QA_PASS | QA_PASS_WITH_ISSUES | QA_FAIL | BLOCKED | SUPERSEDES [seq]
- Contract: contracts/<area>/<feature>.md (or "n/a" for decisions)
- Artifacts: <files created/changed>
- Follows: [seq] (the entry this continues; "none" if new thread)
- Handoff: <agent name> | none
- Notes: 1–3 lines — what was decided/found and why. For REVIEW_APPROVED, count of reviewer-added
  cases. For QA_FAIL, the issue numbers. For BLOCKED, exactly what input is needed and from whom.
```

## Open blockers & pending decisions

(Running list. Add items here when raising them; remove when resolved, citing the resolving entry seq.)

- none

## Locked shared contracts

(Listed when rl-architect locks one; consumers may not deviate without a new DECISION entry.)

- none yet

## Ledger

### [1] 2026-06-09 — (setup) — project scaffolding
- Status: DECISION
- Contract: n/a
- Artifacts: .claude/agents/ (11 agents), .claude/skills/contract-first-dev/, .claude/skills/qa-verification/, LINEAGE.md
- Follows: none
- Handoff: rl-architect
- Notes: Team, workflow skills, and conventions established. First task: rl-architect makes the binding Δt / SOC-bounds / export-limit decisions (REBUILD_SPEC.md §6) and drafts the telemetry shared contract.

### [2] 2026-06-09 — (setup) — project rules & worked example
- Status: DECISION
- Contract: n/a
- Artifacts: CLAUDE.md, contracts/_example/ (wind_power_curve.md, test_env_wind_power_curve.py, review_record_wind_power_curve.md)
- Follows: [1]
- Handoff: rl-architect
- Notes: CLAUDE.md carries the non-negotiable rules loaded by every agent. contracts/_example/ is the reference standard for contract + test + review-record quality — copy its structure for real features.
