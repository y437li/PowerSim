# LINEAGE — Decisions, Locked Contracts, Open Blockers

This file holds ONLY what git and GitHub cannot tell you. For everything else, read the source of record at the start of every session:

- `git log --oneline -15` — what has merged recently
- `gh pr list --state open` — what's in flight and its gate status (draft = contract+tests stage; ready = implementation stage; reviews and QA verdicts are on the PR)
- This file — binding decisions, locked shared contracts, open blockers

Do **not** log work milestones here — PR state is the status record. Append-only, three entry kinds:

- **DECISION** — binding choice by rl-architect: one line + the PR/commit where it was made. Supersede with a new entry referencing the old ID; never edit.
- **LOCKED** — a shared contract is locked: path + PR ref. Consumers may not deviate without a superseding DECISION.
- **BLOCKED** — work stuck on input: who/what is needed. Remove when resolved, citing the resolving PR.

## Decisions

- [D1] 2026-06-09 — Team, workflow (contract-first-dev / qa-verification), naming conventions, and PR-gated process established; see CLAUDE.md. (setup commits 3e9fdd8…)

## Locked shared contracts

- none yet

## Open blockers

- [B1] 2026-06-09 — rl-architect must make the binding REBUILD_SPEC.md §6 decisions (Δt 15 min vs 1 h, SOC bounds, export limit 945 vs 200 MW) and draft the telemetry shared contract before env work can start.
- [B2] 2026-06-09 — Legacy Python env (`python/env/power_env.py` + gym_energy_router) is not in this repo; QA parity testing is impossible until it is vendored under `legacy/` (read-only) or otherwise made available. Needs the old project's path from the user.
