# `src/energy_go/finance`

<!-- curated -->
## Purpose

The `finance` package is the **stage-⑤ project-finance engine** (REBUILD_SPEC §13, D39). It converts a dispatched operating result — a `PolicyEvalResult`-grade object from `training.eval` — into a full economic picture: NPV, IRR, MIRR, LCOE, LCOS, payback (simple and discounted), and DSCR, reported as **distributions over a weather ensemble** of M draws and N project years, with downside-risk metrics at the centre (§13.10).

**Entry point:** `engine.finance(ensemble, config, price_paths)` (§13.12). Takes a `PolicyEnsemble` (M weather draws × N-year trajectories per policy), a `FinanceConfig` (discount / tax / debt / horizon), and one or more `PricePath` multiplier vectors (§13.4, D31/F1). Returns a `FinanceResult` covering two economic views per policy and price path:
- **View (I) — Absolute project:** full-plant CAPEX basis; answers "Is the whole plant a good investment?"
- **View (II) — Incremental storage:** battery-CAPEX-only basis; answers "Does the battery pay, and which policy maximises its value?" (§13.1)

**Module responsibilities:**
- `engine.py` — `finance()` facade; all public types (`PolicyEnsemble`, `PricePath`, `FinanceConfig`, `FinanceResult`, etc.)
- `cash_flow.py` — D13-to-cash-flow mapping (`build_cash_flow_series`); enforces 5 named anti-double-count invariants (§13.2): INV-STREAM-AUTHORITY (operating cash from 6 stream accumulators only), INV-BASIS (penalty/SOC fields structurally unreachable), INV-DEG (degradation never both proxy and replacement CAPEX), INV-CURT (curtailment cash only under explicit contract flag), INV-VOLL (VOLL cash XOR lost-product revenue)
- `metrics.py` — scalar metrics for a single cash-flow series (NPV, IRR, MIRR, LCOE, LCOS, payback, DSCR); self-contained Brent's-method IRR, pure NumPy, no scipy
- `distributions.py` — M-axis distribution functions: `exceedance_percentile` (LOCKED estimator D39: `np.quantile(..., method='lower')`), `cvar5`, `p_below`, `max_drawdown`, `worst_year_cf`
- `discount.py` — CAPM → r\_e → WACC via `compute_wacc()` (§13.5, CGB yield-curve interpolation)
- `price_path.py` — price-path utilities; INV-FINLAYER enforced: non-uniform paths set `requires_retrain=True` (§13.9)
- `sensitivity.py` — NPV-vs-discount-rate curve for fan-chart display; sensitivity surface (§13.11)
- `econ_params.py` — `DeviceEconParams` dataclass (CAPEX, O&M, asset-management, lifecycle); loaded by serving and passed verbatim to `finance()`

**Key design constraints:**
- **Pure** (FIN-37, §3.1): no network access, no filesystem I/O, no clock reads inside `finance()`. Stack: plain Python + NumPy only — no JAX, no scipy (see STACK.md, finance row).
- **Hourly-resolved revenue** (§13.0 P1): revenue integrated at the hourly level from D13 stream accumulators; annual-average-price × annual-quantity is prohibited.
- **D31/F1 constant-real dispatch**: trained policy runs at year-1 tariffs; all price escalation applied post-hoc via `PricePath` multipliers (§13.4).
- **v1 scope**: power-composite scenario (grid export/import/demand-charge streams) is wired. Hydrogen, aluminium, and AI-token scenarios are design-proven at schema level but not built in v1 (§13.3).

**Boundaries:** no JAX, no RL training logic, no WebSocket/HTTP serving, no env physics. Finance is the last stage of the product spine (`config → algorithm → train → eval → finance`) and is always called after a `PolicyEvalResult` is available from `training.eval`.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `__init__.py`

> Energy GO finance engine — pure cash-flow analytics (§13 / D39).

_No public symbols exported._

### `cash_flow.py`

> D13 → cash-flow mapping for the Energy GO finance engine.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `build_cash_flow_series` | `function` | Build CF series [cf[0], cf[1], …, cf[N]] from a policy trajectory. |

### `discount.py`

> CAPM → r_e → WACC computation for the Energy GO finance engine.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `compute_wacc` | `function` | Compute discount rates from FinanceConfig. |

### `distributions.py`

> M-axis distribution functions for the finance engine.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `exceedance_percentile` | `function` | P-q exceedance percentile of a metric distribution. |
| `cvar5` | `function` | Conditional Value at Risk at 5% (mean of worst k draws). |
| `p_below` | `function` | Fraction of draws strictly below threshold. |
| `max_drawdown` | `function` | Shortfall-below-zero maximum cumulative drawdown. |
| `worst_year_cf` | `function` | Worst single-year cash flow (minimum annual CF, year-0 CAPEX excluded). |

### `econ_params.py`

> DeviceEconParams — project economics from config/device_models.yaml (#103).

| Symbol | Kind | Purpose |
|--------|------|---------|
| `DeviceEconParams` | `class` | Per-site economics block extracted from a benchmark_device_library entry. |

### `engine.py`

> Finance engine — `finance()` facade (§13.12, D39).

| Symbol | Kind | Purpose |
|--------|------|---------|
| `PolicyEnsemble` | `class` | §13.12 input: M weather draws × N-year trajectories per policy. |
| `PricePath` | `class` | §13.4 deterministic finance scenario — per-year revenue multiplier. |
| `CgbCurve` | `class` | Static CGB yield-curve snapshot (§13.5a). |
| `FinanceConfig` | `class` | Discount / tax / debt / horizon configuration (§13.5–§13.9). |
| `PercentileResult` | `class` | One exceedance-percentile row. |
| `DownsideRisk` | `class` | §13.10b — six downside metrics; present only when distribution_valid=True. |
| `SingleTrajectoryResult` | `class` | §13.10c — metrics present at ALL M (including M=1). |
| `ViewResult` | `class` | Per-policy, per-price-path result for one View (I or II). |
| `PricePathResult` | `class` | — |
| `PolicyFinanceResult` | `class` | — |
| `FinanceProvenance` | `class` | §13.12 — travels with every result. |
| `FinanceResult` | `class` | Top-level output of finance() — §13.12. |
| `finance` | `function` | Pure finance engine entry point (§13.12). |

### `metrics.py`

> Scalar financial metrics for a single cash-flow series.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `npv` | `function` | Net Present Value. |
| `irr` | `function` | Internal Rate of Return (no external dependencies — pure Python/NumPy). |
| `mirr` | `function` | Modified Internal Rate of Return. |
| `lcoe` | `function` | Levelised Cost of Energy (¥/MWh). |
| `lcos` | `function` | Levelised Cost of Storage (¥/MWh discharged). |
| `payback_simple` | `function` | Simple payback period (years) — fractional. |
| `payback_discounted` | `function` | Discounted payback period (years) — fractional. |
| `dscr` | `function` | Debt-Service Coverage Ratio per year and the minimum over the series. |

### `price_path.py`

> Price-path utilities for the Energy GO finance engine.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `is_uniform` | `function` | Return True iff all multipliers == 1.0 (constant-real, D31/F1). |
| `any_nonuniform` | `function` | Return True iff ANY price path in the list is non-uniform. |
| `get_multiplier` | `function` | Get the multiplier for year index `year_idx` (0-based, year 1 = index 0). |

### `sensitivity.py`

> Sensitivity analysis for the Energy GO finance engine.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `npv_vs_r_curve` | `function` | Compute (r, NPV) pairs for a range of discount rates. |
| `compute_sensitivity_surface` | `function` | Sensitivity surface (§13.11). Shape TBD with backend-reviewer. |

<!-- generated:end -->
