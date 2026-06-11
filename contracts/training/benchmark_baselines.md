# Contract: §11 Benchmark Baselines — Greedy Myopic, DP Oracle, MPC

**Area:** training  
**Feature:** benchmark_baselines  
**Implements:** §11.0–§11.5 (section_11_benchmark_algorithms.md)  
**Test file:** `tests/training/test_training_benchmark_baselines.py`  
**Status:** DRAFT — awaiting backend-reviewer gate

---

## 1. Overview

This contract adds three principled optimization baselines that bracket the RL policy on the **information-set ladder** (§11.0):

```
no-battery  <  rule-based TOU  <  greedy myopic  <  MPC (≈RL information)  ≤  DP oracle
  (§5 floor)       (§5 floor)      (causal O(1))   (fair-information test)   (acausal ceiling)
```

All three baselines:
- Run in the **same JAX eval env** (`jax_env.step/reset`) as the RL policy (identical cost accounting)
- Evaluate over the **same 8760-step year** as the RL eval (`EnvParams(episode_len=8760)`)
- Produce a `PolicyEvalResult` on the **D13 real-money basis** (no VecNormalize)
- Are added as `eval_compare` policy keys `greedy`, `dp_oracle`, `mpc` — additive minor bump per §11.5 (`policies` object has `additionalProperties: true`, no re-review required)

**Honest reporting:** if RL does not beat MPC, the report states so with numbers.

---

## 2. Interface

### 2.1 `run_benchmark`

```python
def run_benchmark(
    policy_name: str,
    data: jax.Array,     # shape (8760, D) — same synthetic year used for RL eval
    params: EnvParams | None = None,  # None → Gansu defaults (episode_len=8760)
) -> PolicyEvalResult:
    """Run one §11 benchmark baseline over the full eval year.

    policy_name: "greedy" | "dp_oracle" | "mpc"
    Returns:     PolicyEvalResult with real-money cost breakdown.
    Raises:      ValueError for unknown policy_name.
    """
```

Reuses the existing `PolicyEvalResult` dataclass from `energy_go.training.eval`.

### 2.2 Module location

`src/energy_go/training/baselines.py` — extend the existing file.  
New public symbols: `GreedyPolicy`, `DpOraclePolicy`, `MpcPolicy`, `run_benchmark`.

The existing `run_baseline` function is **unchanged** — `run_benchmark` is the new entry point for §11 baselines.

### 2.3 Policy classes

```python
class GreedyPolicy:
    """§11.1 — closed-form, O(1) per step, no state other than EnvState."""
    def action(self, env_state: EnvState, step_data: jax.Array,
               params: EnvParams) -> jax.Array:  # (6,)
        ...

class DpOraclePolicy:
    """§11.2 — precomputed offline; replays a fixed trajectory."""
    def __init__(self, optimal_actions: jax.Array, ...): ...
    def action(self, env_state: EnvState, step_data: jax.Array,
               params: EnvParams) -> jax.Array:  # (6,)
        ...

class MpcPolicy:
    """§11.3 — per-step LP over 24-step horizon."""
    def action(self, env_state: EnvState, step_data: jax.Array,
               forecast_data: jax.Array, params: EnvParams) -> jax.Array:  # (6,)
        ...
```

---

## 3. Algorithm Specification

### 3.1 Greedy Myopic (§11.1)

**Decision rule — per step, closed form:**

Given: `P_wind` (MW), `P_pv` (MW), `load_mw` (MW), `price_buy` (¥/MWh), `soc`, `EnvParams`.

```
total_renewable = P_wind + P_pv
deficit   = max(0, load_mw - total_renewable)   # MW
surplus   = max(0, total_renewable - load_mw)    # MW

# Battery discharge: serve deficit before importing from grid
P_dis_max = min(params.bat_power_mw,
                (soc - params.soc_min) * params.bat_capacity_mwh * params.bat_eta_dis)
P_dis_actual = min(deficit, max(0, P_dis_max))

# Battery charge: only from would-be-curtailed surplus
# (export headroom = grid_max_export_mw − current_load_surplus_that_goes_to_grid)
# Approximate: curtail_surplus = max(0, surplus − params.grid_max_export_mw)
curtail_surplus = max(0, surplus - params.grid_max_export_mw)
P_ch_max = min(params.bat_power_mw,
               (params.soc_max - soc) * params.bat_capacity_mwh / params.bat_eta_ch)
P_ch_actual = min(curtail_surplus, max(0, P_ch_max))

# a_bat: charge if P_ch > 0, discharge if P_dis > 0, else idle
# Never both simultaneously (deficit XOR surplus, never both > 0).
a_bat = P_ch_actual / params.bat_power_mw     # ∈ [0, 1]  (charge)
     OR -P_dis_actual / params.bat_power_mw   # ∈ [-1, 0] (discharge)
     OR 0.0                                   # idle
```

**Renewable routing fractions:**

- **Deficit case** (`deficit > 0`, `surplus = 0`):
  - `f_wl = 1.0, f_sl = 1.0` (all renewables to load)
  - `f_wb = 0.0, f_sb = 0.0` (no charging)
  - `f_bl = 1.0` (all battery discharge to load)
  - `a_bat = -P_dis_actual / bat_power_mw`

- **Surplus-no-curtailment case** (`surplus > 0`, `surplus ≤ grid_max_export_mw`):
  - `f_wl = 1.0, f_sl = 1.0` (all renewables to load; env clips to actual load)
  - `f_wb = 0.0, f_sb = 0.0` (no battery charging — surplus is exported, not wasted)
  - `f_bl = 0.0, a_bat = 0.0` (battery idles)

- **Surplus-with-curtailment case** (`curtail_surplus > 0`):
  - `a_bat = P_ch_actual / bat_power_mw`
  - Charge from wind first, fall back to solar for remainder:
    - `bat_from_wind  = min(P_ch_actual, P_wind)`
    - `bat_from_solar = max(0, P_ch_actual − bat_from_wind)`
    - `f_wb = min(1.0, bat_from_wind  / max(P_wind, 1e-9))`  (wind fraction to battery)
    - `f_wl = max(0.0, 1.0 − f_wb)`                          (remaining wind to load)
    - `f_sb = min(1.0, bat_from_solar / max(P_pv,  1e-9))`   (solar fraction to battery; 0 when wind covers all of P_ch_actual)
    - `f_sl = max(0.0, 1.0 − f_sb)`                          (remaining solar to load)
  - `f_bl = 0.0`

**Properties (invariants):**
- Never imports from grid to charge battery: if `a_bat > 0` then `f_wb + f_sb > 0` (renewable source).
- Always discharges to load (not to grid): `f_bl = 1.0` when `a_bat < 0`.
- No speculative arbitrage: `a_bat > 0` only when `curtail_surplus > 0`.
- Greedy is **blind to monthly peak** — it never modifies behaviour to avoid setting a new peak.

### 3.2 DP Oracle (§11.2)

**Offline algorithm — runs once before `run_benchmark` returns.**

**State space:**
- SOC discretized to `N_soc` states: `soc_grid = linspace(soc_min, soc_max, N_soc)`  
  Default: `N_soc = 71` → `Δsoc = 0.01` over `[0.2, 0.9]`.
- Augmented state: `(soc_idx, month_peak_idx)` — but default implementation uses the **per-month peak sweep** (cheaper, approximate):
  - For each calendar month `m` (12 months):
    - For each candidate peak cap `P̄ ∈ linspace(0, grid_max_import_mw, N_peak=41)`:
      - Run backward-induction SOC DP over the month's steps, forbidding `P_import > P̄`.
      - Month cost = optimal in-month cost + `P̄ × demand_rate_yuan_per_mw_month`.
    - Choose the `P̄*` that minimises total month cost.
  - Terminal boundary condition: `V[T+1, soc_idx] = 0` for all SOC states.
  - Cross-month boundary: SOC continuity — the SOC at end of month `m` is the start SOC for month `m+1`.

**Action discretization:**
- Battery actions `a_bat ∈ linspace(-1, 1, N_act=21)` per step.

**Renewable routing for DP:** same as Greedy (renewables to load first, export surplus, charge only when curtailment would occur without battery); battery action is the only optimized variable.

**Replay:** the DP oracle pre-computes an optimal `a_bat` trajectory of length 8760. `DpOraclePolicy.action(t)` returns the precomputed action at step `t`.

**Notes:**
- The oracle is exact up to SOC discretization error (Δsoc = 0.01) and action grid resolution (N_act=21).
- Reports wall-time in the `DpOraclePolicy.metadata` dict (keys: `"dp_wall_time_s"`, `"n_soc_states"`, `"n_peak_candidates"`, `"mean_optimality_gap_vs_coarser"` — optional quality check).

### 3.3 MPC Receding Horizon (§11.3)

**Per-step algorithm — horizon H = 24 steps.**

At each step `t`:
1. Use realized data at step `t` and the RL forecast (D6) for steps `t+1, …, t+H-1`.
   - Forecast `data_fc[h]` for `h > 0` is the same noisy forward projection the RL obs slice carries.
2. Solve LP over battery action sequence `{a_bat_h}_{h=0}^{H-1}` ∈ [-1, 1]^H:

```
minimize:    Σ_{h=0}^{H-1} C_h(a_bat_h, soc_h, data_h)
             + λ_terminal * (soc_H - soc_target)^2    [soft terminal SOC penalty]
             + μ_peak * max(0, P_import_h - running_month_peak_so_far)   [soft peak penalty]

subject to:
  soc_0 = current_soc
  soc_{h+1} = soc_h + eta_ch * max(0, a_bat_h) * bat_power_mw / bat_capacity_mwh
             - max(0, -a_bat_h) * bat_power_mw / (eta_dis * bat_capacity_mwh)
  soc_min ≤ soc_h ≤ soc_max  ∀h
  a_bat_h ∈ [-1, 1]           ∀h
```

where `C_h` is the step cost using greedy renewable routing (same as §3.1) and:
- `λ_terminal = demand_rate_yuan_per_mw_month / (bat_capacity_mwh * 1.0)` (default)
- `soc_target = 0.5` (default mid-range)
- `μ_peak = demand_rate_yuan_per_mw_month` (penalise exceeding running peak)

3. Apply only `a_bat_0` (receding horizon). Renewable fractions follow §3.1.
4. Re-solve at `t+1`.

**Solver:** `scipy.optimize.linprog` (via `jax.pure_callback` wrapper) — LP is piecewise-linear in `a_bat_h` after fixing greedy renewable routing. Implementation may also use a JAX-native LP if available.

**Note:** MPC partially captures monthly-peak credit assignment (via `μ_peak` soft constraint on H=24 horizon) but cannot fully resolve a 720-step month credit assignment — this is the honest limitation reported alongside results.

---

## 4. Telemetry Integration

### 4.1 eval_compare message update

Adds three policy keys to the existing `eval_compare` message (additive minor bump; `additionalProperties: true`):

```jsonc
{
  "type": "eval_compare",
  "step": 500000,
  "policies": {
    "rl":            { "energy_cost_yuan": -12.3e6, ... "total_cost_yuan": -8.1e6 },
    "no_battery":    { ... },
    "rule_based_tou":{ ... },
    "greedy":        { "energy_cost_yuan": ..., "demand_charge_yuan": ...,
                       "degradation_yuan": ..., "curtailment_yuan": ...,
                       "voll_yuan": ..., "total_cost_yuan": ...,
                       "soc_violations_count": 0, "soc_violation_mwh": 0.0,
                       "penalty_yuan": 0.0 },
    "dp_oracle":     { /* same shape */ },
    "mpc":           { /* same shape */ }
  }
}
```

Each new key uses the identical `policy_costs` shape. No field removed or retyped.

### 4.2 Telemetry note in `contracts/shared/telemetry_schema.md`

Append a one-line note in the `eval_compare` section:
```
# §11.5: policy keys "greedy", "dp_oracle", "mpc" may appear alongside the three
# base policies; they carry the identical policy_costs shape. Minor additive bump.
```

---

## 5. Invariants and Ordering

The following **must hold** over the full 8760-step eval year (same realized data, same seed):

| Invariant | Description |
|---|---|
| **I1** | `dp_oracle.total_cost_yuan ≤ greedy.total_cost_yuan` (oracle ≤ greedy, all-else-equal) |
| **I2** | `dp_oracle.total_cost_yuan ≤ rule_based_tou.total_cost_yuan` |
| **I3** | `greedy.total_cost_yuan ≤ no_battery.total_cost_yuan` (greedy beats no-battery) |
| **I4** | `greedy.soc_violations_count == 0` and `greedy.voll_yuan == 0` (greedy always serves load and respects SOC bounds when greedy algorithm is feasible) |
| **I5** | Additive identity: `total_cost_yuan = energy + demand + degradation + curtailment + voll` for every policy, within 0.1 ¥ |

**Non-guaranteed orderings** (report as informational, not asserted):
- MPC vs greedy: MPC should be ≤ but not guaranteed on every instance (horizon effects).
- RL vs MPC: the decisive comparison; reported honestly with exact numbers.

---

## 6. Data Schemas

### 6.1 DpOraclePolicy constructor inputs

```python
DpOraclePolicy(
    optimal_actions: jax.Array,  # shape (8760,) float32 — a_bat for each step
    metadata: dict,              # keys: "dp_wall_time_s", "n_soc_states", "n_peak_candidates"
)
```

### 6.2 MpcPolicy constructor inputs

```python
MpcPolicy(
    horizon: int = 24,           # steps ahead; must be ≥ 1
    lambda_terminal: float | None = None,   # None → derive from EnvParams
    soc_target: float = 0.5,
    mu_peak: float | None = None,           # None → demand_rate_yuan_per_mw_month
)
```

---

## 7. Out of Scope

- SA and ACO metaheuristics (§11.7 — deferred until after §8 composable assets, per spec).
- Online demand-charge forecasting enhancements to MPC.
- GPU-accelerated DP (single-battery Gansu is feasible with CPU scipy/numpy).
- Unit commitment or multi-asset extensions.

---

## 8. Deliberate Deviations from Default Behaviour

| Item | Old (RL/§5) | New (§11) |
|---|---|---|
| `run_benchmark` vs `run_baseline` | `run_baseline("no_battery"\|"rule_based_tou")` | `run_benchmark("greedy"\|"dp_oracle"\|"mpc")` — separate function to avoid confusion |
| Forecast data for MPC | N/A | MpcPolicy uses the same 24-step noisy forecast slice the RL observation carries (D6); realized data at t=0 |
| DP oracle wall-time | N/A | Reported in DpOraclePolicy.metadata; expected < 300s on a standard CPU |

---

## 9. Implementation Sequence

1. **Greedy** — implement first (O(1), no external solvers, fully jittable)
2. **DP oracle** — implement second (numpy/scipy offline, non-JAX-jitted)
3. **MPC** — implement last (scipy LP; `jax.pure_callback` or Python loop)

Each passes independently reviewable tests in the single `test_training_benchmark_baselines.py` file.
