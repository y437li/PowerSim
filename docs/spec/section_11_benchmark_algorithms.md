## 11. Benchmark algorithms for RL comparison (proposal — user approval)
> **Owner:** rl-architect

**Status: PROPOSAL for user approval.** §5 compares the RL policy only against two heuristics (no-battery, rule-based TOU). This section adds **principled optimization baselines** so "RL beats the baselines" means "RL beats optimization given the same information," not just "RL beats two heuristics." The whole point is the **information-set ladder**: bracket the RL policy between a causal-myopic floor, a fair-information optimizer, and an acausal oracle ceiling.

All baselines run in the **same JAX eval env** (the D11 parity env), over the **same realized 365-day year** (8760 steps at Δt=1 h, D3) with the **same weather/price/load seed**, so every comparison is apples-to-apples **real money** (the `cost_total_real_yuan` basis, D13). Each baseline emits one `eval_compare` policy entry (see §11.5).

### 11.0 The information-set ladder

| Baseline | Information set | Causal? | Role |
|---|---|---|---|
| no-battery (§5) | — | causal | trivial floor |
| rule-based TOU (§5) | tariff schedule only | causal | heuristic floor |
| **greedy myopic** | current realized step only, no lookahead | causal | reactive-optimization floor |
| **MPC (receding horizon)** | current + the **same noisy 24-step forecast the RL sees** (D6) | causal | **fair-information baseline — the real test** |
| **DP oracle** | the **entire** realized year (perfect foresight) | acausal | **unreachable upper bound** |
| RL policy (§5) | current obs + noisy 24-step forecast (D6) | causal | the system under test |

RL and MPC share an information set, so **MPC is the baseline RL must beat to justify itself**; greedy/rule-based/no-battery are floors it must clear comfortably; the DP oracle is the ceiling — RL can never beat it, and `(RL_cost − oracle_cost)/oracle_cost` is the headline "money left on the table."

### 11.1 Greedy myopic dispatch (NEW)

- **Decision variables:** the §2.2 action at the current step — renewable flow fractions `f_s→·`, battery `a_bat ∈ [−1,1]`, `f_bat→load`.
- **Objective:** minimize **this step's** `cost_total_real` given the realized prices/weather/load now; no value placed on future SOC.
- **Information:** causal, current step only.
- **Solve:** closed-form / tiny per-step rule — serve load from the cheapest available source, charge only from otherwise-curtailed surplus (no lookahead → no speculative arbitrage), discharge when `price_buy` is high. O(1) per step.
- **Demand charge:** greedy is **blind** to the monthly peak (no lookahead) — it sets new peaks freely. This intended weakness separates it from MPC/DP and shows the value of foresight.

### 11.2 Perfect-foresight DP oracle (NEW) — the upper bound

- **State:** battery `SOC`, **discretized** on `[0.2, 0.9]` (D4) at a default grid of **Δsoc = 0.01 → 71 states** (configurable; coarser for speed, finer for tightness). Stage = step (Δt = 1 h, D3).
- **Decision variable:** per-step battery power (charge/discharge), from which the §3.3 dispatch and `cost_total_real` follow deterministically under known exogenous data.
- **Objective:** minimize **total** real-money cost over the horizon, **including the monthly demand charge**.
- **The demand-charge coupling (key subtlety):** the monthly peak makes cost **non-separable** across steps, so plain per-step DP is invalid. Resolve by **augmenting the state with the running month-peak** (peak discretized too) **or** by decomposition: for each calendar month, sweep a candidate peak cap `P̄`, run SOC-DP that forbids import > `P̄`, add `P̄·demand_rate`, minimize over `P̄`. Default = augmented-state; per-month sweep noted as the cheaper approximation.
- **Information:** perfect foresight over the whole realized year (acausal) — **not achievable online**; the bound, computed **offline once per eval**.
- **Compute:** O(steps × SOC-states × actions) per month × the peak sweep/augmentation. Heaviest baseline but run once; report wall-time. Exact within the SOC/peak discretization — the reported oracle is an upper bound on achievable performance **up to grid resolution**.

### 11.3 MPC / receding horizon (NEW) — the fair-information baseline

- **Decision variables:** the action **sequence** over a horizon `H = 24` steps (matching the RL forecast horizon, D6/D9).
- **Objective:** minimize predicted `cost_total_real` over the horizon (with a terminal SOC value/penalty to avoid end-of-horizon myopia), **apply only the first action**, advance one step, re-solve (receding horizon).
- **Information:** **causal** — current realized state + the **same horizon-scaled noisy 24-step forecast the RL consumes** (D6). This is what makes it the fair comparison.
- **Demand charge:** the 24-step horizon cannot see the full month, so MPC needs a **peak-aware terminal/soft-constraint term** (penalize import above the running month-peak); document that MPC, like RL, only partially solves the monthly-peak credit-assignment problem — which is precisely why it's the honest baseline rather than the oracle.
- **Solve:** per-step linear/quadratic program over 24 steps (the env is piecewise-linear: flows, clips, proportional scaling). Use a fast LP/QP solver; vmappable across the parallel eval envs if linearized. Note the per-step solve cost vs greedy.

### 11.4 What "RL is good" means against this ladder

- **Must clear comfortably:** no-battery, rule-based TOU, greedy.
- **Must beat or match:** **MPC** (same information) — the decisive result. RL beating MPC means the learned policy captures structure (esp. the monthly-peak long-horizon credit assignment, γ=0.999) better than a 24-step optimizer.
- **Cannot beat:** the **DP oracle** — report the optimality gap. Small gap = little left on the table; large gap = the policy or the information bottleneck (forecast noise) is the limiter.

### 11.5 Eval-harness & telemetry integration

- Each baseline is an `agents/baseline_agent.py`-style policy (greedy, MPC) or an offline solver (DP oracle) producing a per-step action stream consumed by the **same eval env**; the DP oracle's optimal SOC trajectory is replayed through the env for identical cost accounting.
- **`eval_compare` telemetry:** add policy keys `greedy`, `mpc`, `dp_oracle` alongside `rl`/`no_battery`/`rule_based_tou`. Per the LOCKED schema's versioning this is an **additive (minor) bump** — the `policies` object already allows additional keys (`additionalProperties: true`), no field removed/retyped, **no re-review required** (minor bump + a one-line note in the telemetry contract that these keys may appear). Each entry uses the existing `policy_costs` shape (five real-money components summing to `total_cost_yuan`, plus SOC/penalty metrics). The headline panel renders RL vs the full ladder with the oracle gap highlighted.

### 11.6 Open questions for the user

1. Include all three (greedy + DP oracle + MPC), or defer MPC (most implementation-heavy)? Recommend **all three** — MPC is the most informative comparison.
2. DP oracle: augmented-state (SOC × running-peak) formulation, or the cheaper per-month peak-sweep approximation? Default proposed: augmented state, sweep as documented fallback.
3. SOC discretization for the oracle — Δsoc = 0.01 (71 states) a good speed/tightness default, or coarser?
4. Confirm baselines run in the JAX eval env (not a separate solver env) so cost accounting is identical to RL — proposed yes.

### 11.7 Metaheuristic schedule optimizers — SA + ACO (proposal — user approval)

**Status: PROPOSAL for user approval.** Extends the §11.0 ladder with two **perfect-foresight metaheuristics** that optimize the **full episode/year dispatch schedule offline against realized data**. They sit **between MPC and the exact DP oracle**:

```
greedy  <  rule-based  <  MPC (causal)  <  [ SA, ACO ]  ≤  DP oracle (exact bound)
                                            approximate oracles (acausal, heuristic)
```

**Honesty point (the reason they're not redundant with the DP oracle):** SA and ACO are **acausal** (perfect foresight, like the oracle) but **heuristic** — they may be suboptimal, so they are **not** bounds. Each is reported with its **gap to the exact DP oracle**, `(metaheuristic_cost − oracle_cost)/oracle_cost ≥ 0`, which doubles as a check that the metaheuristic is implemented correctly (a negative gap means a bug — nothing beats the exact oracle within its discretization). Their **real value is scalability**: when the §8 composable asset library grows the state (multi-battery, gas, electrolyzer + H₂ tank), exact DP's state space explodes and these approximate oracles remain tractable. For the single-battery Gansu plant the exact DP oracle is feasible, so SA/ACO are primarily a **scalability hedge + cross-check** there.

Both optimize the **D13 real-money total including the monthly demand charge**, evaluated by **rolling the candidate schedule through the same JAX eval env** (identical cost accounting to RL/oracle). The demand-charge non-separability is handled **for free**: both score a *complete* schedule, so the monthly peak enters the objective directly — no state augmentation needed (their advantage over DP's augmented state).

**Simulated Annealing (SA)**
- **Decision encoding:** the continuous battery action schedule `a_bat,t ∈ [−1,1]`, t = 1…T (T = episode length; renewable/curtailment flows follow structurally from §3.3 given `a_bat`). Continuous — no discretization.
- **Neighborhood:** perturb a random step or temporal block by Gaussian Δ (clipped to [−1,1]); optionally anneal the perturbation scale with temperature.
- **Objective:** `cost_total_real` of the full rolled-out schedule (incl. demand charge). Minimize.
- **Schedule:** T0 initial temperature, geometric cooling α ≈ 0.95 (configurable; log-cooling noted), N iterations, M random restarts → report best-of-M. Accept worse moves with prob `exp(−Δcost/T)`.
- **Compute:** O(iterations × env-rollout); each rollout is one vmappable eval pass. Report iteration budget + wall-time.
- **Determinism:** seeded RNG → reproducible; report best-of-restarts and the seed.

**Ant Colony Optimization (ACO)**
- **Construction graph:** a layered DAG over **discretized SOC** (reuse the DP oracle's Δsoc = 0.01 → 71 states, §11.2) × time steps. A node = (SOC bin, t); an edge (SOC_t → SOC_{t+1}) = the feasible battery action realizing that SOC transition under §3.2. A complete path = an SOC trajectory = a dispatch schedule.
- **Pheromone model:** τ on edges; each ant builds a path choosing the next edge with prob ∝ `τ^α · η^β` where heuristic `η` = inverse step cost. After all ants finish, deposit `Q / total_schedule_cost` (the **complete-tour** real-money cost incl. demand charge — so peak-friendly tours are reinforced) and evaporate `τ ← (1−ρ)τ`.
- **Objective:** same D13 real-money total via env rollout of the constructed schedule.
- **Hyperparameters:** #ants, #iterations, α/β (pheromone/heuristic), ρ evaporation, Q deposit. **Compute:** O(iterations × ants × T × SOC-branching) — heaviest of the metaheuristics; report budget. **Determinism:** seeded.

**Eval integration:** add `eval_compare` policy keys **`sa`** and **`aco`** (additive/minor, same as the §11.5 ruling — `policies` is `additionalProperties: true`, reuse the `policy_costs` shape). The headline panel shows them on the ladder with their oracle gaps.

#### 11.7 Open questions for the user
1. **Sequencing (not whether — SA and ACO were explicitly requested):** the exact DP oracle (already greenlit) dominates these, so SA/ACO's distinct value is as **scalable approximate oracles for the §8 compositions** where exact DP's state explodes. Recommend **implementing them after §8**; for the single-battery Gansu plant they serve as a cross-check against the exact oracle.
2. SA continuous-schedule encoding + ACO reusing the Δsoc = 0.01 SOC graph — acceptable, or prefer a different encoding?
3. OK to report each as an **oracle gap** (never as a bound)?

---

