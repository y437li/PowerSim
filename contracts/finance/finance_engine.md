# Contract: Finance Engine — `finance()` surface

**Area:** finance (new area; created by D39, precedent D15/D20)
**Feature:** finance_engine
**Test file:** `tests/finance/test_finance_finance_engine.py`
**Status:** DRAFT — awaiting backend-reviewer gate (finance-expert co-authors test cases, §5)
**Spec:** §13 / §13.0–§13.12 (section_13_project_finance.md, D36)
**Decisions:** D3 (Δt=1h), D13 (D13 real-money basis), D31 (CF formulas + F1 constant-real),
               D34 (M=50 / P95), D36 (§13 ratification), D39 (module boundaries + percentile regimes)
**Owners:** finance-engineer (implementation) · finance-expert (semantics + acceptance gate)
**Reviewer:** backend-reviewer (sole gate for the pure engine; `/api/finance/compare` REST shape
               additionally requires frontend-reviewer per §13.12; out of scope here)
**Prerequisite contracts:** `contracts/training/eval_result_extended.md` (task #55 —
               `PolicyEvalResult` with 6-stream accumulators + 22 physical quantities)

> **R3 PENDING:** The `empirical` small-sample percentile regime (R3, M≈10, `sample_kind="empirical"`)
> is architecturally defined but its test cases are **PENDING D39 merge** (PR #108).
> The D39 R3 ruling is: per-year trajectory strip + empirical P50 + empirical worst/best-of-N
> observed-year range + P(NPV<0); NO labeled P75/P90/P95/P99 or CVaR-5%. Test cases for
> R3 are stubbed with `pytest.mark.skip` and will be finalized when D39 lands. All other
> sections (R1/R2, Vectors 0–3, invariants) are stable and form the gate.

---

## 1. Overview

`finance()` is the workstream-D pure cash-flow engine: it turns an already-dispatched
`PolicyEnsemble` (M weather draws × N degraded years, built by workstream-C) into a
`FinanceResult` carrying NPV/IRR/MIRR/LCOE/LCOS/payback distributions (exceedance P50/P75/P90/P95
at M=50), a downside-risk panel, bootstrap CIs, and sensitivity surfaces — **off-wire, offline,
and pure** (no network, no filesystem, no clock).

**Load-bearing boundary (D39):** the M×N dispatch lives in workstream-C, OUTSIDE this engine.
`finance()` never calls `env.step`; the engine's purity is structural, not a convention.

**Data path:**
```
§11 heuristic dispatch  →  ExtendedPolicyEvalResult (per year)
  × M draws × N years  →  PolicyEnsemble  [workstream-C]
                           │
                           ▼
             finance(ensemble, price_paths, econ, finance_config)
                           │
                           ▼
                      FinanceResult
                           │
                  GET /api/finance/compare  [serving-engineer; separate contract]
```

---

## 2. Python API surface (§13.12)

### 2.1 Entry point

Location: `src/energy_go/finance/engine.py`

```python
def finance(
    ensemble:       "PolicyEnsemble",
    price_paths:    list["PricePath"],
    econ:           "DeviceEconParams",
    finance_config: "FinanceConfig",
) -> "FinanceResult":
    """Pure finance engine entry point (§13.12).

    Consumes an already-dispatched PolicyEnsemble and produces distributions of
    NPV/IRR/MIRR/LCOE/LCOS/payback over the M weather draws, a downside-risk
    panel, bootstrap CIs, and sensitivity surfaces.

    Invariants enforced:
    - Pure: no I/O, no network, no filesystem, no clock. The CGB curve and all
      econ params arrive via arguments.
    - CRN structural: every policy's runs[m] is the SAME draw across policies.
      Ragged ensembles (|runs[π]| ≠ M for any π) are rejected with ValueError.
    - econ is a single shared arg across all policies (P2, §13.1).
    - View II requires finance_config.baseline_policy_id ∈ ensemble.runs.keys();
      absent → View II omitted (never fabricated).
    """
```

### 2.2 Data types

All types live in `src/energy_go/finance/` sub-modules. Canonical structure:

```python
# src/energy_go/finance/engine.py (or types.py)
from dataclasses import dataclass, field
from typing import Literal

from energy_go.training.eval import PolicyEvalResult   # §13.7 / task #55

# ── Input types ────────────────────────────────────────────────────────────────

@dataclass
class PolicyEnsemble:
    """§13.12 input: M weather draws × N-year trajectories per policy. (D39)

    Leaf: PolicyEvalResult (verbatim task #55). Engine reads ONLY:
      - streams[*].{volume, value_yuan}  — 6-stream accumulators (D13 real ¥)
      - quantities (22 physical-qty fields: generation_mwh, bat_throughput_mwh…)
      - real_money fields (energy_cost_yuan, demand_charge_yuan, …)
    The memo_only block (penalty_yuan, soc_*) is structurally unreachable
    from the cash-flow path (INV-BASIS).
    """
    seed:        int                                       # shared CRN seed → provenance
    M:           int                                       # ensemble size (default 50, D34)
    sample_kind: Literal["bootstrap", "empirical"]         # selects percentile regime (D39 §4)
    runs: dict[str, list[list[PolicyEvalResult]]]          # runs[policy_id][m][n]; len(runs[π])=M, len(runs[π][m])=N

@dataclass
class PricePath:
    """§13.4 deterministic finance scenario — a per-year multiplier vector.

    m[y] is applied post-hoc: revenue_s(y, path) = m[y] · Σ_t q_{s,t}·p_{s,t}
    Requires m[0] == 1.0 (normalised to year-1 prices, D31/F1).
    Non-uniform m (or stream-specific paths) sets requires_retrain=True.
    """
    id:          str
    label:       str
    multipliers: list[float]   # length N; m[y-1] for year y=1…N; m[0]==1.0

@dataclass
class CgbCurve:
    """Static CGB yield curve snapshot (§13.5a). Keyed by tenor (years) → yield (decimal)."""
    snapshot_date: str          # ISO 8601 date; travels in provenance
    points: dict[int, float]    # e.g. {10: 0.020, 30: 0.026}
    lpr_5yr: float              # 5yr LPR (decimal) for cost-of-debt computation

@dataclass
class FinanceConfig:
    """Discount / tax / debt / horizon configuration for the finance engine (§13.5–§13.9).

    base case = pre-tax, all-equity (D31): discount_rate = r_e (CAPM); tax OFF; debt OFF.
    tax_toggle=True and debt_toggle=True add results as deltas to the base case.
    """
    # CAPM inputs (§13.5b — USER-confirmed 2026-06-13)
    beta_unlevered:          float = 0.60
    equity_risk_premium:     float = 0.060
    country_risk_premium:    float = 0.0
    cgb_curve:               "CgbCurve | None" = None   # None → test fixture overrides r_f directly
    r_f_override:            "float | None" = None       # for unit tests bypassing curve interpolation
    # Tax toggle (§13.9)
    tax_toggle:              bool  = False
    tax_rate:                float = 0.25
    depreciation_years:      int   = 20              # straight-line
    # Debt toggle (§13.9)
    debt_toggle:             bool  = False
    target_de_ratio:         float = 1.5
    credit_spread:           float = 0.0125          # 125 bps over 5yr LPR
    loan_term_years:         int   = 20
    r_d_override:            "float | None" = None   # for unit tests bypassing LPR + credit_spread lookup
    # Horizon / project
    horizon_years:           int   = 20
    valuation_date:          str   = "2026-01-01"    # ISO 8601
    # Bootstrap CI (§13.10a)
    bootstrap_seed:          int   = 42
    bootstrap_n_resamples:   int   = 2000
    bootstrap_ci_level:      float = 0.90            # 90% CI = (P5, P95)
    # Downside thresholds
    hurdle_rate_override:    "float | None" = None   # None → r_e (CAPM base)
    # View II
    baseline_policy_id:      "str | None" = None     # absent → View II omitted


# ── Output types ───────────────────────────────────────────────────────────────

@dataclass
class PercentileResult:
    """One exceedance-percentile row for one metric family."""
    npv_yuan:             float
    irr:                  float    # decimal (e.g. 0.131 = 13.1%)
    mirr:                 float    # decimal
    lcoe_yuan_per_mwh:    float
    lcos_yuan_per_mwh:    float
    payback_simple_yr:    float
    payback_disc_yr:      float
    bootstrap_ci:         tuple[float, float]   # (lower, upper) at bootstrap_ci_level
    confidence:           Literal["sound", "indicative_low_confidence"]

@dataclass
class DownsideRisk:
    """§13.10b — six downside metrics. Present only when distribution_valid=True."""
    worst_case_npv_yuan:    float      # min_m NPV_m
    p_npv_neg:              float      # #{NPV_m < 0} / M  ∈ [0,1]
    p_irr_below_hurdle:     float      # #{IRR_m < hurdle} / M  ∈ [0,1]
    cvar5_yuan:             float      # mean of ceil(0.05·M) worst NPV draws
    max_drawdown_yuan:      float      # min(0, min_y cumCF_excl_CAPEX) per §13.10b
    max_drawdown_year:      int        # argmin year (1-indexed)
    worst_year_cf_yuan:     float      # min annual net CF over y=1…N, all M draws

@dataclass
class SingleTrajectoryResult:
    """§13.10c — metrics present at ALL M (including M=1)."""
    max_drawdown_yuan:   float    # min(0, min_y cumCF_excl_CAPEX) of the deterministic/best trajectory
    max_drawdown_year:   int      # argmin year
    worst_year_cf_yuan:  float    # min annual net CF over y=1…N
    point_npv_yuan:      float    # single-scenario NPV (labelled "NPV (single scenario)")

@dataclass
class ViewResult:
    """Per-policy, per-price-path result for one View (I or II)."""
    # Present at all M:
    single_trajectory: SingleTrajectoryResult
    # Present only when distribution_valid=True:
    P50: "PercentileResult | None"
    P75: "PercentileResult | None"
    P90: "PercentileResult | None"
    P95: "PercentileResult | None"
    P99: "PercentileResult | None"     # indicative_low_confidence only; absent if not requested
    downside_risk: "DownsideRisk | None"
    # Debt-toggle-gated (absent, not zero/null, when debt_toggle=False):
    equity_irr:   "float | None" = None
    min_dscr:     "float | None" = None

@dataclass
class PolicyFinanceResult:
    """Per-policy finance results, one entry per price path."""
    per_price_path: dict[str, "PricePathResult"]   # keyed by PricePath.id

@dataclass
class PricePathResult:
    view_i:             ViewResult
    view_ii:            "ViewResult | None"         # None when baseline_policy_id absent
    cash_flow_series:   list[list[float]]           # [m][y] pre-price-path baseline ¥
    npv_vs_r_curve:     list[tuple[float, float]]   # [(r, npv_yuan), …] for NPV-vs-r fan
    sensitivity_surface: dict                       # §13.11 — shape TBD with backend-reviewer

@dataclass
class FinanceProvenance:
    """§13.12 — travels with every result. Mismatched assumptions refuse to compare."""
    seed:            int
    M:               int
    sample_kind:     str
    valuation_date:  str
    r_f:             float         # the interpolated/overridden r_f used
    r_f_tenor_yr:    int           # matched tenor
    r_f_curve_date:  str
    r_e:             float         # CAPM cost of equity (base / unlevered)
    wacc:            float         # WACC (= r_e when debt off)
    beta_levered:    float
    scenario_id:     str
    code_version:    str           # PEP 440 version string
    price_path_ids:  list[str]

@dataclass
class FinanceResult:
    """Top-level output of finance() — §13.12."""
    M:                  int
    distribution_valid: bool       # False when M=1 → distributional fields absent (§13.10c)
    requires_retrain:   bool       # True if non-uniform/stream-specific price_path (INV-FINLAYER)
    per_policy:         dict[str, PolicyFinanceResult]   # keyed by policy_id
    provenance:         FinanceProvenance
```

### 2.3 Sub-module locations (D39 §2)

| Module | Path | Responsibility |
|---|---|---|
| `discount.py` | `src/energy_go/finance/discount.py` | CAPM → r_e → WACC; CGB linear-interp (§13.5) |
| `cash_flow.py` | `src/energy_go/finance/cash_flow.py` | D13→cash mapping; CAPEX/OPEX/lifecycle/terminal (§13.2, §13.6) |
| `metrics.py` | `src/energy_go/finance/metrics.py` | NPV/IRR/MIRR/LCOE/LCOS/payback/DSCR on a single CF series (§13.8) |
| `price_path.py` | `src/energy_go/finance/price_path.py` | §13.4 post-hoc multiplier + preset library + `requires_retrain` |
| `distributions.py` | `src/energy_go/finance/distributions.py` | M-axis aggregation: exceedance, bootstrap CI, downside panel (§13.10) |
| `sensitivity.py` | `src/energy_go/finance/sensitivity.py` | §13.11 NPV-vs-r fan, tornado, sensitivity surface |
| `econ_params.py` | `src/energy_go/finance/econ_params.py` | `device_models.yaml` econ block (#103) → `DeviceEconParams` |
| `engine.py` | `src/energy_go/finance/engine.py` | `finance()` facade: orchestrates above; View I/II aggregation |

---

## 3. Behavioral requirements

### 3.1 Purity invariant

`finance()` is a **pure function**: no network access, no filesystem I/O, no `datetime.now()`,
no hidden global state. The CGB curve and all econ/CAPM params arrive via `finance_config`.
A test verifies this structurally (FIN-37).

### 3.2 CRN structural requirement

For every `π ∈ ensemble.runs.keys()`:
- `len(ensemble.runs[π]) == ensemble.M` (exact, checked at entry; `ValueError` if not)
- Index `m` is the **same weather draw** across all policies — this is the CRN contract.

Ragged ensembles (policies with different M-lengths) are rejected with `ValueError`.

### 3.3 Shared econ/scenario (P2, §13.1)

`econ`, `price_paths`, and the M weather draws are **identical across policies**. `econ` is a
single shared arg, not per-policy.

### 3.4 View II gating (§13.12 inv 3)

`finance_config.baseline_policy_id` present AND `∈ ensemble.runs.keys()` →
View II = `NPV(π) − NPV(baseline)` over CRN-shared draws (index-aligned m).
Absent → View I only; View II **omitted, never fabricated**.

### 3.5 INV-BASIS (§13.0 P3, §13.2)

Finance reads **only** D13 real-money fields from `PolicyEvalResult`:
- `streams[*].{volume, value_yuan}` (6-stream accumulators)
- Physical quantities (generation_mwh, bat_throughput_mwh, bat_discharge_mwh, …)
- `real_money.*` (energy_cost_yuan, demand_charge_yuan, degradation_yuan, curtailment_yuan, voll_yuan)

The `memo_only` block (`penalty_yuan`, `soc_violation_mwh`, `soc_violations_count`) is
**structurally unreachable** from the cash-flow path — not merely unused. A reviewer-grade
test fixture proves this (FIN-23).

### 3.6 INV-DEG (§13.2)

`degradation_yuan` is a dispatch-layer wear signal — **never** a period cash item.
The cash treatment is battery replacement CAPEX, scheduled at `first-to-fire(calendar,
throughput)` (§13.6). Test FIN-24 verifies no double-count.

### 3.7 INV-CURT (§13.2)

`curtailment_yuan` enters cash flow **only if** `scenario.curtailment_penalty_contract=True`.
When False, the cash loss of a curtailed MWh = foregone `grid_export` revenue only.
Test FIN-25 verifies.

### 3.8 INV-VOLL (§13.2)

`voll_yuan` enters cash flow **only if** `scenario.reliability_penalty_contract=True`.
In own-load scenarios, the cash hit = lost product revenue once (never VOLL + lost-product).
Test FIN-26 verifies.

### 3.9 INV-FINLAYER (§13.4)

Price paths and escalation are a finance-layer-only post-hoc transform (D31/F1). A
non-uniform or per-stream price path sets `requires_retrain=True` and badges the result.
No price-path/escalation field is reachable from the dispatch path.
Test FIN-27 verifies.

### 3.10 Debt-toggle gating (§13.9)

`equity_irr` and `min_dscr` are **absent** (not zero/null) in `ViewResult` when
`finance_config.debt_toggle=False`. They are present and non-None only when debt is ON.
Test FIN-43 verifies.

### 3.11 `distribution_valid` and M=1 honesty (§13.10c)

When `M=1` (or `distribution_valid=False`):
- `P50/P75/P90/P95/P99` fields are **absent** (None in Python)
- `downside_risk.distributional` fields are **absent** (DownsideRisk is None)
- Only `single_trajectory` metrics are emitted
- `FinanceResult.M=1` banner string present in `provenance`

Tests FIN-28–FIN-31 verify.

### 3.12 Percentile regimes — three regimes, ONE schema (D39 §4)

| Regime | Trigger | `distribution_valid` | Percentiles populated |
|---|---|---|---|
| **R1** | M=1 | False | none (point estimates only, §13.10c) |
| **R2** | `sample_kind="bootstrap"`, M≥50 | True | P50/P75/P90/P95 + bootstrap CI (D34) |
| **R3** | `sample_kind="empirical"`, M≈10 | True | **PENDING D39 merge** — per-year trajectory strip + empirical P50 + worst/best-of-N range + P(NPV<0); NO labeled tail percentile or CVaR |

### 3.13 Percentile estimator — LOCKED (finance-expert PR #107 §A)

For a **higher-is-better** metric (NPV, IRR, MIRR):
```python
P_q = np.quantile(sorted_ascending_array, 1 - q, method='lower')
```
("in q-fraction of scenarios the project achieves at least P_q").

For **lower-is-better** (LCOE, LCOS, payback): use `q` with `method='higher'`.

`method='lower'` / `method='higher'` (nearest-rank, no interpolation) — the headline number
is a **realized draw**, bit-reproducible across the server engine and client library.

**ONE estimator** serves R2 and R3 (R3 = same estimator, reduced output set). A second
estimator is a review-fail.

CVaR-5%: `k = ceil(0.05 · M)`; mean of the `k` lowest NPV draws.

Drawdown: **shortfall-below-zero** in cumulative annual CF excluding year-0 CAPEX:
```python
max_drawdown = min(0.0, min(np.cumsum(cf_excl_capex)))
```
(NOT peak-to-trough — LOCKED §13.10b literal, finance-expert PR #107 §A.)

### 3.14 Bootstrap CI determinism

Fixed `finance_config.bootstrap_seed` → identical CI across runs. Default B=2000 resamples.
Degenerate case (all M draws equal) → CI width=0. Property asserts in test FIN-45–FIN-46.

### 3.15 Provenance completeness

Every `FinanceResult.provenance` carries: `seed`, `M`, `sample_kind`, `valuation_date`,
`r_f` (value + tenor + curve_date), `r_e`, `wacc`, `beta_levered`, `scenario_id`,
`code_version`, `price_path_ids`. Results with mismatched assumptions must be refused
for comparison (the serving layer enforces this; the engine provides provenance).

---

## 4. Metrics — exact formulas (§13.8)

```
CF(0) = −Total_overnight_CAPEX
CF(y) = EBITDA(y) − Replacement(y) − Tax(y);  CF(N) adds Terminal
EBITDA(y) = Σ_streams (rev − cost) − FixedOM − VarOM − asset-mgmt  (P1, after price-path)

NPV(r)   = Σ_{y=0}^{N} CF(y) / (1+r)^y
IRR      : Σ CF(y) / (1+IRR)^y = 0          # numeric; MIRR reported alongside
MIRR     = [FV_pos(reinvest=r) / (−PV_neg(finance=r))]^(1/N) − 1
LCOE     = PV(CAPEX + FixedOM + VarOM + Replacement − Residual) / PV(E_net MWh)   # ¥/MWh
LCOS     = PV(bat_CAPEX + bat_O&M + replacement − residual + charging_cost) / PV(bat_discharge_mwh)
Payback  : simple (linear interp); discounted (at r, linear interp)
DSCR(y)  = CFADS(y) / DebtService(y)    # levered toggle only; CFADS ≈ EBITDA − Tax
```

---

## 5. Test cases

Finance-expert (task #4, PR #107) supplies the hand-computed vectors and is the acceptance gate.
Tests in `tests/finance/test_finance_finance_engine.py` encode every vector with **arithmetic
shown in comments** (engineering rule). The tolerance table (from PR #107 §C criterion 2):

| Metric | Tolerance |
|---|---|
| NPV | ±¥1 |
| IRR, MIRR, equity-IRR | ±0.01 pp (±1e-4 decimal) |
| DSCR | ±0.001 |
| LCOE, LCOS | ±¥0.01/MWh |
| Payback | ±0.001 yr |
| r_f, r_e, WACC, β_L | ±1e-6 (decimal) |

### 5.1 Stable test groups (gate-blocking)

| ID range | Group | Source |
|---|---|---|
| FIN-00 | **Vector 0:** CAPM → r_e → WACC — discount module | PR #107 Vector 0 |
| FIN-01–FIN-06 | **Vector 1:** BASE pre-tax unlevered (NPV, IRR, MIRR, simple payback, discounted payback, LCOE) | PR #107 Vector 1 |
| FIN-07–FIN-10 | **Vector 2:** TAX TOGGLE — delta NPV, after-tax NPV, after-tax IRR, delta-only reporting | PR #107 Vector 2 |
| FIN-11–FIN-14 | **Vector 3:** LEVERED DELTA — DSCR, equity-IRR, delta, debt-gating (absent when off) | PR #107 Vector 3 |
| FIN-15–FIN-22 | **Downside stats (§A):** M=50 linear ensemble — worst-case NPV, P(NPV<0), P(IRR<hurdle), CVaR-5%, P50/P75/P90/P95, max drawdown, worst-year CF | PR #107 §A |
| FIN-23–FIN-27 | **No-double-count invariants:** INV-BASIS, INV-DEG, INV-CURT, INV-VOLL, INV-FINLAYER | PR #107 §B |
| FIN-28–FIN-31 | **R1 regime (M=1) honesty:** distributional fields absent, banner present, single_trajectory present | §13.10c |
| FIN-32–FIN-36 | **R2 regime (bootstrap M≥50):** percentile estimator, bootstrap CI, convergence hint, P99 indicative-only | D34 / §13.10a |
| FIN-37 | **Purity:** no I/O reachable from `finance()` | §13.12 |
| FIN-38–FIN-40 | **CRN structural:** index-aligned draws, ragged-ensemble rejection, seed in provenance | §13.12 inv 1 |
| FIN-41–FIN-42 | **View II gating:** present when baseline_policy_id matches; omitted (not fabricated) when absent | §13.12 inv 3 |
| FIN-43 | **Debt-toggle gating:** equity_irr/min_dscr absent when debt OFF | §13.9 |
| FIN-44 | **Provenance completeness:** all required fields present | §13.12 |
| FIN-45–FIN-46 | **Bootstrap CI properties:** determinism, degenerate width=0, CI contains point estimate | §13.10a |
| FIN-53–FIN-55 | **Reviewer edge cases** (backend-reviewer): drawdown no-shortfall clamp (FIN-53), CVaR k=ceil at integer boundaries M=20/40 (FIN-54), MIRR single-valued on multi-sign CF (FIN-55) | backend-reviewer (commit 69650b3) |
| FIN-56 | **Tax assembly end-to-end:** `finance(tax_toggle=True, depreciation_years=2)` on Vector-1 ensemble → after-tax NPV = −¥2,066.12 AND delta = −¥43,388.43 | finance-expert REQUEST_CHANGES PR #110 |
| FIN-57 | **Debt assembly end-to-end:** `finance(debt_toggle=True, target_de_ratio=1.5, loan_term_years=2, r_d_override=0.05)` on Vector-1 ensemble → equity_irr = 24.8565% AND min_dscr = 1.8594 | finance-expert REQUEST_CHANGES PR #110 |

### 5.2 Pending test group (R3 — PENDING D39 merge)

| ID range | Group | Status |
|---|---|---|
| FIN-47–FIN-52 | **R3 regime (empirical M≈10):** per-year strip, empirical P50, worst/best-of-N range, P(NPV<0); NO labeled P75/P90/P95/P99 or CVaR (FIN-48 asserts P75+P90+P95+P99+CVaR all absent) | `pytest.mark.skip` — PENDING D39 |

---

## 6. Out of scope (v1 — §13.14)

1. RL training run (deferred; heuristic-first v1, D39)
2. Hydrogen / aluminum / token stream activation (design-proven config-only)
3. Live CGB/LPR treasury fetch (static user-editable curve in v1; live-fetch v2, §13.5)
4. VAT, deferred-tax, incentive timing (§13.9/§13.14)
5. Forced-outage stochastics (availability_factor knob only)
6. Real-option value
7. Debt sculpting / DSRA / refinancing / tranches
8. Non-power action-space extensions
9. `/api/finance/compare` REST endpoint (separate contract, serving-engineer + both reviewers)
10. Client-side finance lib parity (D5 — `financeClient.ts`, frontend contract)

---

## 7. Implementation checklist (for QA)

- [ ] `PolicyEnsemble` dataclass with `seed`, `M`, `sample_kind`, `runs`; ragged check on entry
- [ ] `FinanceConfig` dataclass with all fields + defaults per §13.5b
- [ ] `discount.py`: `compute_wacc()` — CGB linear-interp → r_f → Hamada → r_e → WACC; Vector 0 passes
- [ ] `cash_flow.py`: D13→cash mapping with all 5 named invariants (INV-BASIS/DEG/CURT/VOLL/FINLAYER)
- [ ] `metrics.py`: NPV/IRR/MIRR/LCOE/LCOS/payback/DSCR; exact formulas §13.8; Vectors 1–3 pass
- [ ] `distributions.py`: LOCKED estimator (`np.quantile(...,'lower'/'higher')`); CVaR k=ceil(0.05·M); shortfall-below-zero drawdown; M=50 §A worked ensemble passes
- [ ] `price_path.py`: preset library + `requires_retrain=True` for non-uniform paths; INV-FINLAYER guard
- [ ] `sensitivity.py`: NPV-vs-r curve; tornado; §13.11 surface shape agreed with backend-reviewer
- [ ] `econ_params.py`: loads from `config/device_models.yaml` (#103) with per-value provenance
- [ ] `engine.py` facade: orchestrates sub-modules; View I/II aggregation; View II omitted when baseline absent
- [ ] `FinanceResult` carries `distribution_valid=False` at M=1; all distributional fields absent (not None-fabricated)
- [ ] Debt-toggle: `equity_irr` / `min_dscr` absent (not zero) when `debt_toggle=False`; `r_d_override` bypasses LPR+credit_spread when set (pins r_d directly)
- [ ] Bootstrap CI: seeded; B=2000 default; deterministic; degenerate width=0
- [ ] Provenance block: all 12 required fields
- [ ] `finance` area added to CLAUDE.md `<area>` list + `check_conventions.sh` (D39)
- [ ] `finance` added to STACK.md as a new area with stack = "pure Python + NumPy"
- [ ] All FIN-00–FIN-46, FIN-53–FIN-57 tests pass; FIN-47–FIN-52 remain skipped until D39 lands
- [ ] No hardcoded Gansu constants — works for any `PolicyEnsemble` + `DeviceEconParams`
