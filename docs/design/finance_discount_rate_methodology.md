<!--
  Finance discount-rate methodology — design note authored by finance-expert for §13 (project-finance SPEC)
  and the Workstream-D / C contracts. Formalizes the USER directive (2026-06-11, via team-lead):
  "project finance should set the rate via the CAPM model, with the treasury rate selected by time."
  This SUPERSEDES master-plan open-question §9-1 ("pick a default WACC"). DESIGN ONLY.
  All rates annualized, nominal, decimal (0.06 = 6%). Currency ¥ (CNY) for the Gansu base case.
-->

# Finance discount-rate methodology (CAPM, time-selected treasury r_f)

> **Status:** DESIGN — bound for the **§13 project-finance SPEC** (human-gated) and the **C/D contracts**. Supersedes the master plan's "default WACC" framing of open decision §9-1. Proposed default *values* below are citable starting points to confirm at the USER gate (§9-1 reframed) / contract stage; the **methodology** is the deliverable here.

## 1. Principle — the discount rate is *derived*, not hand-set

Per the USER directive, the discount rate comes from **CAPM → WACC**, anchored on a **time-selected, term-matched treasury yield**, not an arbitrary constant. It composes cleanly with the D31/§5.9b base case (pre-tax, all-equity unlevered):

```
r_f        = treasury_yield(valuation_date, term = horizon)        # §3 — the directive's core
β_levered  = β_unlevered · (1 + (1 − tax_rate)·(D/E))               # Hamada relever; = β_unlevered if all-equity
r_e        = r_f + β_levered · ERP + CRP                            # CAPM cost of equity
r_d        = reference_rate(valuation_date) + credit_spread         # cost of debt (LPR-anchored)
WACC       = (E/V)·r_e + (D/V)·r_d·(1 − tax_rate)

discount_rate (BASE = unlevered, pre-tax)  = r_e                    # all-equity ⇒ WACC collapses to r_e
discount_rate (levered toggle)             = WACC
```

Because the base case is **all-equity** (D31), the base discount rate **is `r_e`** (the CAPM cost of equity) — the debt/tax-shield terms only appear under the levered toggle (§5.9b). This makes the headline NPV/IRR discount rate a single, fully-derived number with explicit, overridable inputs.

## 2. Cost of equity via CAPM

```
r_e = r_f + β_levered · ERP + CRP
```

| Term | Meaning | Treatment |
|---|---|---|
| `r_f` | risk-free rate | **time-selected, term-matched treasury** — §3 (the directive) |
| `β_levered` | equity beta of the asset class, relevered to target D/E | unlevered asset beta × Hamada factor; = `β_unlevered` in the all-equity base |
| `ERP` | equity risk premium | named config default (§4) |
| `CRP` | country risk premium | **0 for a CNY/CGB-anchored analysis** (sovereign risk already in the CGB yield); non-zero only cross-border |

## 3. `r_f` — treasury rate selected by time (the directive's core)

Two dimensions, both explicit config:

**3a — Valuation-date dependence.** The analysis takes a **`valuation_date`** input and uses the treasury yield **as of that date** — never a hardcoded constant that goes stale. The `valuation_date` and the exact yield used **travel in the `/api/finance/compare` provenance** (same provenance-guard family as `dispatch_fidelity` and the mismatch-refuse guard), so a comparison built on a stale or mismatched rate is machine-visible.

**3b — Term-matching.** The risk-free tenor is **matched to the project horizon** (standard valuation practice: anchor the risk-free duration to the cash-flow duration). For CNY, the **China Government Bond (CGB)** curve:
- 20-yr project → long-tenor CGB; **default convention: linearly interpolate the CGB curve to the exact `horizon_years`** (so 20 yr interpolates 10yr↔30yr); `nearest`-tenor is a config alternative.
- 10-yr project → ~10-yr CGB point.
- **Currency/region-keyed source:** CNY → CGB curve; future non-CNY regions → the corresponding **sovereign** curve (ties into task #58 currency layering — the curve table is keyed by currency).

```
r_f = interp( CGB_curve(snapshot ≤ valuation_date),  horizon_years )
```

## 4. Other parameters — named, overridable config with cited defaults

Every parameter is a named, overridable field with a recommended default + citation (same spirit as the device-econ library; all **proposed**, confirm at the §9-1/USER gate):

| Field | Proposed default | Basis / citation (to confirm) |
|---|---|---|
| `beta_unlevered` | **0.55** | utility-scale renewable IPP unlevered/asset beta (~0.5–0.6); Damodaran "Green & Renewable Energy" sector betas |
| beta levering | Hamada `β_L = β_U·(1+(1−tax)·D/E)` | standard; `= β_U` in the all-equity base |
| `equity_risk_premium` (ERP) | **0.060** | China total ERP ≈ mature-market ERP (~4.5–5%) + China country premium (~1–1.5%); Damodaran country ERP (China) |
| `country_risk_premium` (CRP) | **0.0** (CNY/CGB base) | sovereign risk already in the CGB `r_f`; non-zero only for cross-border valuation |
| `cost_of_debt` | **5yr LPR + 125 bps** | LPR-anchored (PBoC Loan Prime Rate), time-selected like `r_f`; spread = project credit margin |
| `target_de_ratio` (D/E) | **0.0** base · **1.5** (60/40) levered toggle | D31 base = all-equity; renewable project-finance gearing ~60% debt for the levered case |
| `tax_rate` | **0.25** (15% renewable-preferential alt) | §5.9b; only used in the debt tax-shield + levered WACC |

`cost_of_debt`'s reference rate (`LPR`) is **also time-selected** (valuation-date snapshot), mirroring `r_f` — both anchor to a dated curve, not a constant.

## 5. Sensitivity — sweep around the CAPM/curve-implied base

The interest-rate sensitivity the USER originally requested now sweeps **around the CAPM-derived base** (more defensible than an arbitrary WACC band):
- **Primary:** the §5.10 NPV-vs-discount-rate curve's base point is the **CAPM `r_e`** (or WACC); the sweep spans **`r_f ± Δ`** (e.g. ±100 bps around the term-matched CGB) and **`ERP ± Δ`** (e.g. ±150 bps).
- **Tornado bars** add `β`, and (levered) `cost_of_debt` / `D/E`, ranked by |ΔNPV|.
- Composes with the **weather-percentile** axis (§5.10 surface): (discount-parameter × weather-percentile).

This replaces the placeholder "discount rate ∈ [3%,12%] arbitrary" range — the swept band is now anchored and parameter-meaningful.

## 6. Data source — static, user-updatable treasury-curve config (v1)

**Decision (proposed): ship a small static, user-updatable curve table for v1; no live fetch.** Rationale: (a) **reproducibility** — same `valuation_date` + same table → identical `r_f`, deterministic; (b) the finance engine stays **offline/pure** (no network dependency — consistent with the off-wire REST design and the env's no-network ethos); (c) the user updates the snapshot when re-running and provenance records which snapshot was used. **Live fetch is a v2 option**, flagged.

```yaml
# config/treasury_curves.yaml  (user-updatable; keyed by currency for task #58)
CNY:
  source: "China Government Bond (CGB) — ChinaBond / MoF"
  snapshots:
    - curve_date: 2026-06-11           # engine selects the snapshot ≤ valuation_date
      yields_by_tenor_years:           # nominal annualized, decimal
        1: 0.0140
        3: 0.0155
        5: 0.0170
        7: 0.0185
        10: 0.0195
        30: 0.0230
  # LPR (for cost_of_debt) — same dated-snapshot pattern
  lpr:
    - curve_date: 2026-06-11
      tenor_years: {1: 0.0310, 5: 0.0350}
```

Engine: given `valuation_date`, `horizon_years`, `currency` → pick snapshot ≤ valuation_date → term-match/interpolate → `r_f` (and `LPR` for `r_d`). The selected `(curve_date, tenor, yield)` go into provenance. (Illustrative yields above — confirm the actual snapshot at contract/USER stage.)

## 7. Where this binds & open items

- **§13 SPEC + D contract:** §1–§6 above are the binding discount-rate methodology; the finance engine reads a `discount_rate_config` of the §4 fields + the §6 curve table.
- **Provenance (§3a):** `valuation_date`, currency, the selected `(curve_date, tenor, r_f)`, and the resolved `r_e`/WACC travel in `/api/finance/compare` so E can refuse / badge mismatched-assumption comparisons.
- **Supersedes** master-plan open-decision §9-1 (hand-set WACC) — the rate is now CAPM-derived; what remains for the USER is **confirming the §4 default values** (β, ERP, cost-of-debt spread, D/E) and the **v1 data-source** choice (§6 static-config — recommended).
- **Still open with USER** (unchanged): horizon (§9-2), v1 revenue streams (§9-3), CAPEX/econ defaults (§9-4). The discount-rate defaults (§4) fold into the same "shipped defaults vs configurable" question.
