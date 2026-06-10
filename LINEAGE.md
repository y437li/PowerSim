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
- [D2] 2026-06-09 — Composable asset library added to the spec (REBUILD_SPEC.md §8): gas combustion, PEM + alkaline electrolyzers, 6 load archetypes; obs/action derived from site YAML; Gansu config is the parity special case. Build order: §3 plant first, §8 after baseline parity.
- [D3] 2026-06-10 — Δt = 1 hour (binding). Episodes 168 steps (7-day train) / 8760 steps (365-day eval); forecast = 24 steps at 1-step stride = next 24 h; tariff boundaries resolved at minute resolution (D8). Resolves the §6 15-min/1-h split and the ×4 stride bug at the source; §8 gas/electrolyzer asset distinctions survive at ≥15 min so 1 h loses no modeled physics. (PR #2)
- [D4] 2026-06-10 — SOC bounds = [0.2, 0.9] (binding). Hard-clip P_ch/P_dis so SOC lands exactly on the bound; overshoot → soc_violation_mwh, penalized 20 000 ¥/MWh (§3.6 row 5). Adopts the code-faithful value the §3 numbers and 294.5 MWh sizing are written against; "10–90%" was a stale doc note. (PR #2)
- [D5] 2026-06-10 — PCC export limit = single configurable site field grid_connection.max_export_mw; Gansu parity default 945 MW (the GridParams physics value §3.6 row 8 scaling/curtailment math was authored against). The YAML 200 MW figure is reclassified as an optional interconnection/contractual cap, out of scope v1 — NOT the physics export limit. (PR #2)
- [D6] 2026-06-10 — Forecast noise = horizon-scaled multiplicative Gaussian, applied in _get_obs. For horizon h=1..24 steps: x̂_h = x_true_h·(1+ε_h), ε_h~N(0, σ_h), σ_h = σ_max·(h/H_max), σ_max=0.10, H_max=24; clip each noised feature to its physical range; keys threaded explicitly per env (§7). Implements §2.1 "grows linearly with horizon, 10% at max" and fixes §6 "noise never applied". (PR #2)
- [D7] 2026-06-10 — Spread clamp ≥ 0. price_sell = max(0, price_buy − max(0, spread + N(0, σ_spread))), spread=30, σ_spread=10 ¥/MWh; clamp on both the spread and the final sell price. Closes the §6 risk-free-arbitrage hole while preserving the ¥30 mean discount. (PR #2)
- [D8] 2026-06-10 — Forecast/live price lookup is minute-aware (_get_price(hour, minute)). The 10:30 and 11:30 mid-tier boundaries are correct in both realized and forecast prices; at Δt=1 h steps land on :00 but the function stays correct under a future 15-min Δt. Fixes the §6 hour-only lookup bug. (PR #2)
- [D9] 2026-06-10 — Forecast stride = 1 step (no ×4), no episode-end wraparound. Samples t+1…t+24 steps; near episode end the window is clamped/truncated to the synthetic-year device array (lax.dynamic_slice), never % len(episode_data) — no cross-season leakage. Fixes both §6 stride bugs. (PR #2)
- [D10] 2026-06-10 — Demand charge booked once per calendar month; no terminal double-count. month_peak·demand_rate charged at each month boundary plus a single terminal flush for the final partial month; the terminal step does not re-book an already-charged month. cost_cum.c_demand_charge_yuan_cum reflects each month exactly once. Fixes the §6 terminal double-count. (PR #2)
- [D11] 2026-06-10 — B2 parity strategy: build a from-scratch plain-Python/NumPy reference implementation of §3 physics + §4 generators, not vendored legacy (per direct user direction: legacy code is unavailable and is to be recreated from scratch). Lives under reference/ (NOT legacy/), built independently of the JAX core so JAX-vs-reference parity is two independent implementations of the same spec; §6 fixes D6–D10 are applied in BOTH. Gansu config (§8.4, D2) is the parity special case. Owner jax-env-engineer; contract contracts/env/reference_implementation.md, tests tests/env/test_env_reference_implementation.py + tests/env/test_env_parity_gansu.py. Recorded limitation: this validates spec-conformance and cross-implementation agreement, not behavioral equivalence with the original (unavailable) system. (PR #2)

## Locked shared contracts

- none yet

## Open blockers

- none — [B1] resolved by [D3]–[D10] (PR #2); the telemetry shared contract `contracts/shared/telemetry_schema.md` remains DRAFT pending APPROVE from BOTH backend-reviewer and frontend-reviewer (LOCKED entry to follow). [B2] resolved by [D11] (PR #2): parity reference is a from-scratch NumPy implementation under `reference/`, not vendored legacy.
