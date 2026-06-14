# Agentic Co-pilot — Execution-Flow Design

**Status:** DESIGN / contract-first — **v1.0 LOCKED** (both reviewers folded + USER reviewed & approved §4–§8 governance, 2026-06-14; rl-architect lock). Surface-independent core (§1, §3–§8, §J) locked; **§2/§K PENDING #18/#19**; BUILD deferred. **Owner:** rl-architect. Cite under D44.
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

- **`evaluate_config(config, scenario) -> scored result` is the agent's core tool** and is the **#18 search-engine foundation** (the sizing-sweep callable, made agent-ready). It MUST be a clean **programmatic callable** (not a script), **batched/vmappable** (the optimizer evaluates many configs), and return a **machine-readable** result carrying the #135 summary **plus the `BankabilityVerdict` block** (the B1–B4 evaluator output — `contracts/finance/bankability_bar.md`, finance-expert; §7). These are the agent-readiness guard-rails this doc places on #18 (see §K1–K3).
- **The agent gets NO privileged action** beyond this table. Same actions, same validation (`config_validation`, #133 allow-sets), same audit — just a different invoker tag.

> **§2 is SURFACE-DEPENDENT → finalize against #18/#19 (team-lead sequencing).** The action *names* here are an abstracted vocabulary; the **authoritative typed command-pattern action API (shared by UI + agent) is itself a #19 deliverable** (#133 §9 "action-command defs → #19 contract" — NOT an existing surface; #132 today has hooks + store actions, not one typed command layer; frontend-reviewer #139). The `cost_tier` column is likewise pending (§K7). Treat §2's signatures/metadata as **PENDING #18/#19**; §1, §3–§8, §J (the surface-independent execution flow + permission/honesty model) are designed now.

---

## 3. Compute-tier-aware evaluation (D43 / D41)

Every `evaluate_config` carries a declared **`cost_tier`** derived from *what changed*:

- **`instant` (finance-only recompute):** the design delta touches ONLY finance params (the #133 `finance_overrides` allow-set: `debt_toggle`, `target_de_ratio`, `credit_spread`, `loan_term_years`) → `finance()` recomputes from the **cached ensemble + new `FinanceConfig`**, **NO re-sim** (D43 INSTANT tier). Cheap → the broad-search workhorse.
- **`expensive` (full re-sim):** the design delta changes the **physical dispatch** (battery energy/power, fleet sizing) → the ensemble must be **re-dispatched** (D41 re-sim rule: "battery sizing affects the simulation") before `finance()`. Costly → rationed by the permission model (§4) and the two-stage optimizer (§I).

**Two-stage search (compute control):** Stage 1 sweeps the finance-only axes broadly on the `instant` tier over a cached ensemble; Stage 2 spends `expensive` re-sims only where Stage 1 + the surrogate indicate promising physical-design regions. CRN-paired throughout (D41/D42) so every pairwise candidate delta is a clean per-draw difference, not diff-of-noise.

> **⚠ COMPARISON-MODE AXIS RESTRICTION (backend-reviewer #139, finding 1 — the D42 apples-to-apples guard, BINDING).** The `instant` finance-only axis available to a **per-config comparison sweep** is **ONLY the #133 `finance_overrides` allow-set** `{debt_toggle, target_de_ratio, credit_spread, loan_term_years}`; the market-rate / CAPM knobs (`risk_free`, `erp`, `beta`, `wacc`, `gearing`, `tax_*` — the #134 `FinanceParamSet` request surface) are **COMMON across all compared configs** (`ComparisonSession.common_finance`, #133 §4), NEVER a per-config sweep axis. Sweeping a CAPM knob per-config would rank two candidates under *different discount rates* → the per-draw delta is no longer apples-to-apples and the "winner" is an artifact. **`evaluate_config` in comparison mode MUST reject a per-config CAPM/market override** (reuse #133's reject — reviewer-case 14). The full `FinanceParamSet` is a **single-config what-if** exploration (one config, vary its own CAPM), **NOT a comparison axis** — a distinct mode the agent must not conflate with cross-config ranking.

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
- **"Follow" levels (human-set session policy, layered ON TOP):** the human may set how closely they shadow the agent — `manual` (confirm every action incl. act-then-log), `assisted` (auto act-then-log, confirm expensive + destructive, per the table), `autonomous-within-budget` (auto through expensive up to a pre-approved compute budget; destructive still confirmed). The follow-level only ever makes the gate *stricter or looser within these bounds* — it can **never** auto-approve a destructive action or the (non-existent) invest action.

**Governance defaults (USER-confirmed, BINDING — user reviewed & approved §4–§8, 2026-06-14):**
1. **Default follow-level = `assisted`.** A fresh session is `assisted` — cheap+reversible acts auto-log; every expensive (re-sim) and destructive action is confirmed. The documented default.
2. **`autonomous-within-budget` is OPT-IN, DEFAULT-OFF.** NOT active unless the human explicitly turns it on; and even when on, **destructive actions and the (non-existent) invest decision stay human-confirmed** — autonomy only ever covers cheap + expensive *within the pre-approved budget*, never destructive/invest. (User is cost-conscious; auto-spend is opt-in only.)
3. **Budget caps (re-sim count / wall-clock / token-$) are USER-SET, with CONSERVATIVE defaults, and are HARD ceilings the agent never exceeds.** Hitting any cap is a hard stop (§8); the agent cannot raise or bypass them. Actual default numbers are set at #20 build time; the design enshrines only that the caps are **user-set, conservative, and hard**.

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
3. **Search within hard constraints.** Infeasible configs (C-rate outside realistic bounds, any bankability bar B1–B4 `fail`) are **dropped from candidate output**, never surfaced as a "winner". The bankability verdict is read from the machine-readable `BankabilityVerdict` block (`contracts/finance/bankability_bar.md`, §2/§K2), **never re-derived by the LLM**. **Per-bar status is 4-state `{pass, fail, not_applicable, indeterminate}` (regime-aware, finance-expert + backend-reviewer #139):** a distribution-dependent bar (e.g. B3 `P(NPV<0)≤T1`) is **`indeterminate` at R1/M=1** (no distribution) and B4 (DSCR/equity-IRR) is **`not_applicable` when debt is off** — these are **NEVER** silently treated as `pass`. **Honesty extension:** "never surface a bar-*failing* config" extends to **"never surface an *unassessable* one as bankable"** — a candidate with any `indeterminate` bar is labelled "bankability not confirmable at this regime (needs M≥… for B3)", not promoted as bankable.
4. **No "optimal" claims.** The agent reports "best found within the searched space + budget", with the search bounds + stop reason (§8) stated. It is a heuristic search over real runs, not a global optimizer.
5. **Attribution.** Every agent-authored artifact/annotation is tagged `author=agent` with the originating NL command + the result ids it relied on (§K audit).

---

## 8. Stop conditions

The loop terminates (and always returns the best feasible candidates found + an honest status) on the **first** of:
- **Budget exhausted** — re-sim count cap, wall-clock cap, or LLM token/$ cap reached (§K caps).
- **No improvement** — objective improves < ε over the last *k* proposals (convergence); reported as "converged". **ε is measured on the CRN-paired per-draw delta** (D41/#135 rule 7), **NOT** a difference-of-percentiles — otherwise the loop can "converge on noise" (backend-reviewer #139, finding 4).
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

- **(K1) `evaluate_config(config, scenario) -> scored result` — clean programmatic CALLABLE** (not a script), returning a stable **`result_id`** (for §7.1 traceability + §7.5 attribution; backend-reviewer #139). Owner: **#18** (the sizing-sweep IS this callable's first consumer). *Status: embed as #18 acceptance criterion.*
- **(K2) Machine-readable `BankabilityVerdict` in the scored result** — **RESOLVED to a shared evaluator, NOT a #135 retrofit** (finance-expert + backend-reviewer #139, same conclusion). `contracts/finance/bankability_bar.md` (finance-expert authors) defines the canonical B1–B4 evaluator: thresholds-as-explicit-config (`bar_config_id`), per-bar **4-state `{pass, fail, not_applicable, indeterminate}`** + regime-gating, self-contained `BankabilityVerdict{per-bar status, bar_values{threshold,actual}, thresholds, bar_config_id}`. A pure function; the verdict **rides at the #18 eval layer** (and #15 cert runs); **#135 is untouched.** Single-sources the bar *logic* (anti-drift) without putting policy-judgment on the metric wire. *Status: finance-expert authoring; must land before #18 consumes it.*
- **(K3) Batched/vmapped eval** so the optimizer scores many configs efficiently — **vmap axis = configs at a FIXED shared seed (CRN broadcast)**; per-config independent seeds would make pairwise deltas diff-of-noise (backend-reviewer #139). Owner: **#18**. *Status: #18 acceptance criterion.*
- **(K4) Config-as-serializable-data** — DONE (`config_artifact_schema` #133 + D43).
- **(K5) Compute-tier-aware eval (instant finance-only vs expensive re-sim)** — DONE (D43 + D41).
- **(K6) CRN/shared-seed common-reference comparison** — DONE (D41/D42).
- **(K7) Per-action `(cost_tier, reversibility)` metadata** (the §4 derive-don't-enumerate input). **#19 does NOT currently carry it** (frontend-reviewer #139, answering open-Q4):
  - `run_eval`'s cost_tier **already exists dynamically** as #132's `ExecutionTier` (`instant`/`fast`/`eval_needed`/`retrain_required`) resolved by `/api/compare/plan` → **REUSE it**, coarsened to §3's `{instant, expensive}` (`{instant,fast}`→instant, `{eval_needed,retrain}`→expensive); the UI keeps the finer 4-value tier for its badge. Do NOT add a parallel cost field for `run_eval`.
  - the OTHER actions (`fork`/`edit`/`add_to_comparison`/`annotate`/`delete`) have **no declared cost_tier and no per-action reversibility flag** (#133 gives the undo mechanism + author tag, not a per-action declaration) → **a minor #19 addition is required** (each command-pattern action declares `(cost_tier, reversibility)`). **HARD prereq for §4** (no input → no permission gate) — required #19 work, not fast-follow.
- **(K8) The unified typed command-pattern action API itself** (one layer UI + agent both invoke) **is a #19 deliverable** (#133 §9 "action-command defs → #19 contract"), **NOT an existing surface** — #132 today has hooks + store actions, not one typed command layer (frontend-reviewer #139). §0's "no special agent path" depends on this layer existing. *Status: #19 deliverable; explicit dependency.*

**Reused (no new build):** the §4 PROPOSE-PLAN compute estimate is already available via #134 `/api/compare/plan` (`tier` + `tier_duration_estimate_s`) + the `ExecutionPlanBadge` — reuse, don't rebuild. Follow-levels + budget tracker + the agent-authored-config visual distinction are net-new #20-build workbench UX (frontend-reviewer build-note).

**Sequencing verdict:** §1, §3–§8, §J (the surface-independent execution flow + permission/honesty/stop model + adapter) are **finalizable now**. **§2 is surface-dependent → PENDING #18/#19.** Gated surfaces: #18 (K1–K3, incl. the `BankabilityVerdict` + CRN-broadcast vmap + `result_id`) and #19 (K7 per-action metadata + K8 the command API itself). No agent code until this doc is locked AND K1–K3/K7/K8 exist.

---

## Open questions
**Still open (deferred to the #20 build, with finance-expert input):**
1. **Objective set** — are `{max-NPV, best-capital-efficiency, most-robust}` the right default candidate labels, or user-declared per run? (Lean: small fixed default + user-extensible.)
2. **Pareto axes** — which 2–3 objectives define the frontier by default (NPV × CAPEX? NPV × P(NPV<0)?).

**Resolved in review (v0.2):**
3. **`cost_tier` granularity** — **RESOLVED: two-value `{instant, expensive}` is enough for the permission gate** (frontend-reviewer #139) — it's a coarsening of #132's 4-value `ExecutionTier`; the UI keeps the finer tier for its badge. No middle `cheap` tier unless a real mid-cost action appears.
4. **#19 action-metadata** — **RESOLVED: #19 does NOT currently carry `(cost_tier, reversibility)`** (frontend-reviewer #139). `run_eval` reuses #132's `ExecutionTier`; the other actions need a **minor #19 addition** (K7) — a HARD prereq for §4, requested now (not fast-follow).

---

### Review fold (v0.2 — both reviewers + finance-expert, #139)
- **§3** — comparison-mode axis restricted to #133 `finance_overrides`; CAPM/market knobs COMMON-only; `evaluate_config` rejects per-config CAPM in comparison mode (backend-reviewer finding 1 — the D42 apples-to-apples guard).
- **§2/§K2** — bankability resolved to a shared **`bankability_bar.md`** evaluator (finance-expert) with 4-state `{pass,fail,not_applicable,indeterminate}`; verdict rides at the #18 eval layer; **#135 untouched**.
- **§7.3** — `na`/`indeterminate` never treated as `pass`; "never surface an unassessable config as bankable."
- **§8** — convergence ε is CRN-paired per-draw, not diff-of-percentiles.
- **§K** — K1 adds `result_id`; K3 CRN-broadcast vmap; K7 reuse `ExecutionTier` + minor #19 addition (HARD prereq); K8 the command API itself is a #19 deliverable; §2 marked PENDING #18/#19 (team-lead sequencing).
