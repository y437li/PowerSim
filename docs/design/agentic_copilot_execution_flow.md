# Agentic Co-pilot — Execution-Flow Design

**Status:** DESIGN / contract-first — review before any implementation. **Owner:** rl-architect.
**Realizes:** task #20 (D44 §"tiered permission/'follow' model DESIGNED in the #20 phase").
**Phase:** v1 **fast-follow** — design now (USER-authorized), build after #18 + #19 land.
**Reviewers (cross-area → both, advisory; rl-architect locks):** frontend-reviewer (action-API client, permission/confirm UX, NL surface, handoffs, audit thread) · backend-reviewer (eval tool, model-interface adapter, optimizer, honesty guardrails, budget caps).

> **What this doc IS:** the execution flow, the permission/"follow" model, the agent's tool surface (by reference), honesty/budget guardrails, and the dependencies on #18/#19 that must exist before the loop can run. **What it is NOT:** a build spec for the agent, a new action API (that is #19/#132 — single-source), or a re-definition of the finance/result/config schemas (D45/#135, #133). It composes existing locked surfaces; it does not redefine them.

---

## 0. Framing (from D44 — binding)

The co-pilot is **(a) an instructable in-system actor AND (b) an autonomous optimizer**, and in both modes it is **just another CLIENT of the shared, scriptable, typed action API** the UI uses (D44; the D18/D37 single-source principle applied to *actions* — one action implementation, no UI-vs-agent dialect, no special agent path). Two structural consequences are already LOCKED on #19 by D44: every action is **(i) auditable + author-attributed (`human` | `agent`)** in the config comment thread, and **(ii) reversible** via the shared undo. This doc designs the layer *above* those actions: when the agent may invoke each, with what confirmation, and how it searches.

**Prime directive — propose-not-commit:** the agent proposes; the **investment decision is always the human's**. The agent never commits capital, never finalizes an "invest" action (no such agent action exists), and never claims an "optimal" answer (§7).

---

## 1. Agent loop

```
                ┌─────────────────────────── human ───────────────────────────┐
                │ objective + constraints + reference scenario (or NL command) │
                └───────────────────────────────┬──────────────────────────────┘
                                                 ▼
   ┌─────────────────────────── AGENT ORCHESTRATOR (LLM, §J adapter) ───────────────────────────┐
   │  (1) PLAN: parse objective/command → search plan (which DESIGN params to vary, D42)         │
   │  (2) PROPOSE: pick next config(s) — classical optimizer (Bayesian-opt / grid-refine)        │
   │  (3) EVALUATE: call evaluate_config(config, scenario) [§2 tool] — tier-aware (§3, D43)        │
   │  (4) READ: parse the machine-readable scored result (#135 + bankability flag)               │
   │  (5) FEASIBILITY: drop constraint-violating configs (C-rate, bankability bars B1–B4)        │
   │  (6) REFINE: update the optimizer's surrogate / grid from scored feasible results           │
   │  (7) CONVERGE?: stop-condition check (§8) → loop to (2) or exit                              │
   │  (8) OUTPUT: N labeled candidates + Pareto frontier + per-candidate LLM rationale           │
   └─────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                 ▼
            human reviews candidates → fine-tunes in workbench → makes the invest call
```

- **Input:** an **objective** (e.g. maximize P50 NPV; maximize capital efficiency = NPV/CAPEX; maximize robustness = minimize P(NPV<0) or maximize min-DSCR), a set of **hard constraints** (bankability bars B1–B4, realistic C-rate, export-cap, any user-pinned params), and a **fixed reference scenario** (D42 — uncertainties held common so the per-draw CRN-diff isolates the design choice).
- **Search space = DESIGN params only** (D42 controllable: battery energy/power, fleet sizing, and the finance-overrides allow-set #133). UNCERTAINTY params are NOT search axes — they are fixed at the reference scenario (varying them is the separate *robustness* analysis, surfaced per-candidate, not optimized over).
- **Output:** a SMALL set (default 3) of **labeled** candidates — e.g. `max-npv`, `best-capital-efficiency`, `most-robust` — plus the **Pareto frontier** over the chosen objectives, plus a per-candidate **rationale** (LLM-explained, grounded in the scored results). Candidates become **first-class configs in the library** (D43) for human fine-tuning. Each candidate carries its **regime/confidence** (§7) and **bankability pass/fail** verbatim from its scored result.

---

## 2. Tool / action surface (BY REFERENCE — single-source, D44)

The agent invokes **exactly the #19 shared action API** (the command-pattern actions; frontend #132 + serving #134 endpoints). This doc does **not** define new actions — it lists the ones the agent uses and what each returns, referencing their owning contract. **If an action's signature is needed, read #19/#132/#134, not here.**

| Action (from #19 action API) | Returns | cost_tier | reversibility |
|---|---|---|---|
| `create_config` / `fork_config(base, param_delta)` | new config id (D43 artifact, #133) | instant | reversible |
| `edit_params(config, delta)` | updated config (new version, OCC #133) | instant | reversible |
| `run_eval(config, scenario)` = **`evaluate_config`** | scored `FinanceResultSummary` (#135) **+ bankability B1–B4 pass/fail** | **instant** (finance-only) **or** **expensive** (full re-sim) — §3 | reversible (read-only compute) |
| `add_to_comparison(config, session)` | updated `ComparisonSession` (#133) | instant | reversible |
| `annotate(config, text, author=agent)` | comment id (#133 thread) | instant | reversible |
| `delete_config` / `overwrite` (no-fork) | — | instant | **destructive** |

- **`evaluate_config(config, scenario) -> scored result` is the agent's core tool** and is the **#18 search-engine foundation** (the sizing-sweep callable, made agent-ready). It MUST be a clean **programmatic callable** (not a script), **batched/vmappable** (the optimizer evaluates many configs), and return a **machine-readable** result carrying the #135 summary **plus an explicit bankability-bar B1–B4 pass/fail block** (§7). These three are the agent-readiness guard-rails this doc places on #18 (see §K).
- **The agent gets NO privileged action** beyond this table. Same actions, same validation (`config_validation`, #133 allow-sets), same audit — just a different invoker tag.

---

## 3. Compute-tier-aware evaluation (D43 / D41)

Every `evaluate_config` carries a declared **`cost_tier`** derived from *what changed*:

- **`instant` (finance-only recompute):** the design delta touches ONLY finance params (the #133 `finance_overrides` allow-set: `debt_toggle`, `target_de_ratio`, `credit_spread`, `loan_term_years`) → `finance()` recomputes from the **cached ensemble + new `FinanceConfig`**, **NO re-sim** (D43 INSTANT tier). Cheap → the broad-search workhorse.
- **`expensive` (full re-sim):** the design delta changes the **physical dispatch** (battery energy/power, fleet sizing) → the ensemble must be **re-dispatched** (D41 re-sim rule: "battery sizing affects the simulation") before `finance()`. Costly → rationed by the permission model (§4) and the two-stage optimizer (§I).

**Two-stage search (compute control):** Stage 1 sweeps the finance-only axes broadly on the `instant` tier over a cached ensemble; Stage 2 spends `expensive` re-sims only where Stage 1 + the surrogate indicate promising physical-design regions. CRN-paired throughout (D41/D42) so every pairwise candidate delta is a clean per-draw difference, not diff-of-noise.

---

## 4. Permission / confirmation model — the "follow" model (CORE)

**Derive-don't-enumerate (D44):** the tier is a pure function of each action's declared **`(cost_tier, reversibility)`** metadata — NOT a hardcoded per-action allowlist. New actions get a tier for free by declaring their metadata. The function:

| `(cost_tier, reversibility)` | Permission tier | Behavior |
|---|---|---|
| `instant`/`cheap` **&** `reversible` | **ACT-THEN-LOG** | agent acts immediately; logged + author-attributed (`agent`) in the config thread; reversible via shared undo. No prompt. |
| `expensive` (any reversibility) | **PROPOSE-PLAN + CONFIRM** | agent presents a plan + a **compute estimate** (# re-sims, est. wall-clock, est. token/$ cost) and **waits for human confirm** before spending. Protects the compute budget. Batched plans confirm once for the batch. |
| any `cost_tier` **&** `destructive` | **ALWAYS-HUMAN-CONFIRM** | delete/overwrite-without-fork → explicit human confirm every time, never auto. (The agent's default for "replace" is **fork**, which is reversible → act-then-log; destructive ops are an explicit escalation.) |

- **The invest decision is not in this table** — it is not an agent action at all (propose-not-commit, §0).
- **Tier is evaluated at invocation** from the action's metadata; a `run_eval` that resolves to `instant` is act-then-log, the same call resolving to `expensive` (re-sim) escalates to propose-plan+confirm. So the *same* tool auto-tiers by its realized cost.
- **"Follow" levels (human-set session policy, layered ON TOP):** the human may set how closely they shadow the agent — `manual` (confirm every action incl. act-then-log), `assisted` (default — auto act-then-log, confirm expensive + destructive, per the table), `autonomous-within-budget` (auto through expensive up to a pre-approved compute budget; destructive still confirmed). The follow-level only ever makes the gate *stricter or looser within these bounds* — it can **never** auto-approve a destructive action or the (non-existent) invest action.

---

## 5. Human-in-loop handoffs

The human enters at exactly these points (and the agent **blocks** at the confirm/handoff ones):

1. **Objective / command** — sets objective + constraints + reference scenario, or issues an NL command (§6).
2. **Expensive-run confirm** — approves (or declines/edits) the agent's propose-plan before any full re-sim batch (§4).
3. **Destructive confirm** — approves any delete/overwrite (rare; agent prefers fork).
4. **Candidate review** — inspects the N labeled candidates + Pareto + rationale; promotes/forks any into the workbench for hands-on fine-tuning (D43).
5. **Final invest call** — always the human, outside the agent (§0).

Between handoffs the agent operates autonomously *within* the follow-level + budget. A **human interrupt** (stop/pause) is honored at the next loop boundary (§8).

---

## 6. NL command surface

Human NL instruction → the orchestrator **parses to a plan of typed action calls** (§2) → executes under the permission model (§4) → **reports + annotates** (author=agent) in the config thread.

Examples (illustrative — the parse is the LLM's job; the *executed* calls are the shared API):
- *"compare 300 vs 400 MWh battery at the base scenario"* → `fork_config(base, {battery_energy_mwh:300})`, `fork_config(base, {battery_energy_mwh:400})`, `run_eval` each (expensive — sizing change → propose-plan+confirm), `add_to_comparison` both, `annotate` with the per-draw CRN-diff summary.
- *"build a lower-leverage variant of candidate A"* → `fork_config(A, {target_de_ratio: <lower>})`, `run_eval` (instant — finance-only → act-then-log), `annotate` rationale.
- *"which sizing maximizes capital efficiency while passing all bankability bars?"* → full autonomous search loop (§1) within constraints, returns the labeled candidate + rationale.

The NL layer adds **no new actions** — it is a parser/orchestrator over §2. Ambiguous commands → the agent asks a clarifying question (a handoff), never guesses on an expensive/destructive path.

---

## 7. Honesty guardrails (binding)

1. **Every claim is backed by a real engine run.** No fabricated metrics; a number the agent reports must trace to an `evaluate_config` result id. (The schema-conformance + the #135 contract make the result trustworthy; the agent must not synthesize values the engine didn't produce.)
2. **Honest regime/confidence (§13.10c / #135).** The agent reads `provenance.distribution_valid` + `regime` + per-percentile `confidence`. At **R1 / M=1** there is NO distribution → the agent must NOT say "optimal", "P90", or rank by a percentile it doesn't have; it labels a point estimate as such. "max-NPV" as a *label* is only valid when a distribution exists (R2/R3); at R1 it is "highest point-NPV (single trajectory, no distribution)". R3 percentiles beyond p50 are absent by #135 — the agent must not invent them.
3. **Search within hard constraints.** Infeasible configs (C-rate outside realistic bounds, any bankability bar B1–B4 failing) are **dropped from candidate output**, never surfaced as a "winner". The bankability pass/fail is read from the machine-readable result (§2/§K), not re-derived by the LLM.
4. **No "optimal" claims.** The agent reports "best found within the searched space + budget", with the search bounds + stop reason (§8) stated. It is a heuristic search over real runs, not a global optimizer.
5. **Attribution.** Every agent-authored artifact/annotation is tagged `author=agent` with the originating NL command + the result ids it relied on (§K audit).

---

## 8. Stop conditions

The loop terminates (and always returns the best feasible candidates found + an honest status) on the **first** of:
- **Budget exhausted** — re-sim count cap, wall-clock cap, or LLM token/$ cap reached (§K caps).
- **No improvement** — objective improves < ε over the last *k* proposals (convergence); reported as "converged".
- **Constraint-infeasible** — no feasible point found within the search space → returns "no feasible config found under constraints {…}", with the closest near-misses + which bar failed (honest, not a forced winner).
- **Human interrupt** — stop/pause command honored at the next loop boundary; returns work-so-far.

Every termination states the **stop reason**, the **search bounds covered**, and the **compute spent** (no silent truncation — same discipline as the CI "wired-but-near-empty" honesty).

---

## J. Model-interface adapter

- A **provider-agnostic adapter** sits between the orchestrator and the LLM: `{provider, model, endpoint, params}` configurable; **Claude latest** the recommended default. Swappable so orchestration logic is provider-independent.
- **API keys / credentials live ONLY in the gitignored private overlay** (`ENERGY_GO_PRIVATE_CONFIG`, D32) — **never** in public config. This composes with #133's `agent_config` block, which already **excludes credentials** by schema (D32 recursive secret-reject): public `agent_config` carries provider/model/endpoint *references*, the secret resolves from the overlay at runtime.
- The adapter is a serving-layer concern (backend-reviewer-gated when built); its contract is authored in the build phase.

## K. Agent-readiness dependencies (what #18/#19 MUST provide before the loop runs)

This flow is designed against **contracted** surfaces and can be reviewed now, but it **cannot be finalized/run** until these real surfaces exist (flagged per team-lead's sequencing note):

- **(K1) `evaluate_config(config, scenario) -> scored result` — clean programmatic CALLABLE** (not a script). Owner: **#18** (the sizing-sweep IS this callable's first consumer). *Status: guard-rail to embed in #18's contract.*
- **(K2) Machine-readable bankability B1–B4 pass/fail** in the scored result. #135 carries the metrics (min_dscr, equity_irr, npv, …) + regime/confidence but **not** an explicit bar pass/fail flag — **this is the one genuine schema gap.** Add it at the #18 eval layer (a small `bankability: {B1..B4: pass|fail, bar_values}` block on the scored result), NOT retrofit later. *Status: guard-rail + the gap flagged to team-lead.*
- **(K3) Batched/vmapped eval** so the optimizer can score many configs efficiently. Owner: **#18**. *Status: guard-rail.*
- **(K4) Config-as-serializable-data** — DONE (`config_artifact_schema` #133 + D43).
- **(K5) Compute-tier-aware eval (instant finance-only vs expensive re-sim)** — DONE (D43 + D41).
- **(K6) CRN/shared-seed common-reference comparison** — DONE (D41/D42).
- **(K7) Scriptable typed action API with `(cost_tier, reversibility)` metadata per action** — Owner: **#19** (D44 locks the command-pattern API + author-attribution + reversibility; this doc additionally requires each action to **declare `cost_tier`** so §4's derive-don't-enumerate works). *Status: confirm #19's action-metadata includes `cost_tier`; if not, a minor #19 addition.*

**Sequencing verdict:** the flow, permission model, NL surface, honesty guardrails, stop conditions, and model adapter (§1–§8, §J) are **finalizable on review now**. §2/§K are **gated** on #18 (K1–K3) and #19 (K7) implementing the agent-ready surfaces — those are the spots where the real surface must exist before the loop is wired. No agent code until this doc is approved AND K1–K3/K7 exist.

---

## Open questions for review
1. **Objective set** — are `{max-NPV, best-capital-efficiency, most-robust}` the right default candidate labels, or should the objective set be user-declared per run? (Lean: a small fixed default + user-extensible.)
2. **Pareto axes** — which 2–3 objectives define the frontier by default (NPV × CAPEX? NPV × P(NPV<0)?).
3. **`cost_tier` granularity** — is a two-value `{instant, expensive}` enough, or is a middle `cheap` tier (small batched re-sim) worth declaring? (Lean: start with two; add `cheap` only if a real mid-cost action appears.)
4. **#19 action-metadata** — does the #19 action API already carry `cost_tier`, or is that a minor addition I should request now so §4 has its input?
