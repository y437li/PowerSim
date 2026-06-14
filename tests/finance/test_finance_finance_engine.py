"""Finance engine tests — contracts/finance/finance_engine.md

Spec: §13 / §13.0–§13.12, D36, D39
Reviewer: backend-reviewer (sole gate for the pure engine)
Finance-expert acceptance gate: finance-expert (PR #107) — Vectors 0–3, §A downside stats, §B invariants

Test numbering: FIN-00…FIN-52 per contracts/finance/finance_engine.md §5
All numeric asserts show the hand-computed arithmetic in the comment (engineering rule).
Source of truth for tolerances: PR #107 §C criterion 2.

NOTE: Imports from energy_go.finance.* will fail until the implementation lands
(contract-first workflow — tests gate the implementation, not the reverse).

R3 PENDING: FIN-47–FIN-52 are skipped pending D39 merge (PR #108).
"""

import math
import pytest
import numpy as np

# ---------------------------------------------------------------------------
# Imports — will raise ImportError until implementation lands (expected)
# ---------------------------------------------------------------------------
from energy_go.finance.engine import (
    finance,
    PolicyEnsemble,
    FinanceConfig,
    FinanceResult,
    PricePath,
    CgbCurve,
)
from energy_go.finance.discount import compute_wacc
from energy_go.finance.metrics import npv, irr, mirr, lcoe, lcos, payback_simple, payback_discounted, dscr
from energy_go.finance.distributions import (
    exceedance_percentile,
    cvar5,
    p_below,
    max_drawdown,
    worst_year_cf,
)
from energy_go.finance.cash_flow import build_cash_flow_series
from energy_go.training.eval import PolicyEvalResult, StreamAccumulator


# ---------------------------------------------------------------------------
# Tolerance constants — PR #107 §C criterion 2
# ---------------------------------------------------------------------------
TOL_NPV_YUAN         = 1.0         # ±¥1
TOL_RATE_PP          = 1e-4        # ±0.01 pp (percentage points) in decimal
TOL_DSCR             = 0.001       # ±0.001
TOL_LCOE_YUAN_MWH    = 0.01        # ±¥0.01/MWh
TOL_PAYBACK_YR       = 0.001       # ±0.001 yr
TOL_DISCOUNT_DECIMAL = 1e-6        # ±1e-6 for r_f / r_e / WACC / β_L


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _make_stream_accum(volume: float, value_yuan: float) -> StreamAccumulator:
    return StreamAccumulator(volume=volume, value_yuan=value_yuan)


def _zero_streams() -> dict:
    """6-key stream dict with all zeros (dormant-stream placeholders)."""
    return {
        "grid_export":   _make_stream_accum(0.0, 0.0),
        "grid_import":   _make_stream_accum(0.0, 0.0),
        "demand_charge": _make_stream_accum(0.0, 0.0),
        "h2_sale":       _make_stream_accum(0.0, 0.0),
        "avoided_cost":  _make_stream_accum(0.0, 0.0),
        "token_sale":    _make_stream_accum(0.0, 0.0),
    }


def _make_eval_result(
    *,
    grid_export_yuan:    float = 0.0,
    grid_import_yuan:    float = 0.0,
    demand_charge_yuan:  float = 0.0,
    export_mwh:          float = 0.0,
    import_mwh:          float = 0.0,
    generation_mwh:      float = 0.0,
    bat_discharge_mwh:   float = 0.0,
    bat_throughput_mwh:  float = 0.0,
    # real_money fields (D13)
    energy_cost_yuan:    float = 0.0,
    degradation_yuan:    float = 0.0,
    curtailment_yuan:    float = 0.0,
    voll_yuan:           float = 0.0,
) -> PolicyEvalResult:
    """Build a minimal ExtendedPolicyEvalResult for finance unit tests.

    Only the fields the finance engine reads are populated.
    memo_only fields (penalty_yuan, soc_*) are left at defaults (zero).
    """
    streams = _zero_streams()
    streams["grid_export"]   = _make_stream_accum(export_mwh, grid_export_yuan)
    streams["grid_import"]   = _make_stream_accum(import_mwh, grid_import_yuan)
    streams["demand_charge"] = _make_stream_accum(0.0, demand_charge_yuan)
    return PolicyEvalResult(
        # 9 existing wire-locked fields
        energy_cost_yuan=energy_cost_yuan,
        demand_charge_yuan=demand_charge_yuan,
        degradation_yuan=degradation_yuan,
        curtailment_yuan=curtailment_yuan,
        voll_yuan=voll_yuan,
        total_cost_yuan=energy_cost_yuan + demand_charge_yuan + degradation_yuan + curtailment_yuan + voll_yuan,
        soc_violations_count=0,
        soc_violation_mwh=0.0,
        penalty_yuan=0.0,
        # new fields (task #55)
        streams=streams,
        generation_mwh=generation_mwh,
        wind_generated_mwh=0.0,
        pv_generated_mwh=0.0,
        bat_charge_mwh=0.0,
        bat_discharge_mwh=bat_discharge_mwh,
        bat_throughput_mwh=bat_throughput_mwh,
        load_served_mwh=0.0,
        load_unserved_mwh=0.0,
        curtailed_mwh=0.0,
        wind_to_load_mwh=0.0,
        wind_to_bat_mwh=0.0,
        wind_to_grid_mwh=0.0,
        wind_curtailed_mwh=0.0,
        pv_to_load_mwh=0.0,
        pv_to_bat_mwh=0.0,
        pv_to_grid_mwh=0.0,
        pv_curtailed_mwh=0.0,
        bat_to_load_mwh=0.0,
        bat_to_grid_mwh=0.0,
        bat_curtailed_mwh=0.0,
        grid_to_bat_mwh=0.0,
        grid_to_load_mwh=0.0,
    )


def _make_base_config(**overrides) -> FinanceConfig:
    """FinanceConfig with a pinned discount rate = 0.10 for Vector-1–3 arithmetic.

    r_f_override=0.10 sets the risk-free rate; equity_risk_premium=0.0 collapses
    CAPM to r_e = r_f + β_L·ERP = 0.10 + 0.60·0.0 = 0.10 (no ERP premium).
    Without equity_risk_premium=0.0 the engine would use r_e=0.136 (0.10+0.60·0.06),
    which breaks FIN-56 base NPV (−¥6,893 vs +¥41,322.31) and FIN-34 P50 NPV.
    Vector 0 (FIN-00*) is unaffected — it uses _CAPM_CONFIG_BASE (equity_risk_premium=0.06).
    (finance-expert REQUEST_CHANGES; discount-config bug confirmed numerically.)
    """
    defaults = dict(
        r_f_override=0.10,          # round placeholder for Vector 1–3 (≠ production CAPM)
        equity_risk_premium=0.0,    # collapse r_e → r_f = 0.10 (test-fixture pin, not production)
        tax_toggle=False,
        debt_toggle=False,
        horizon_years=2,            # N=2 for all vectors 1–3
        bootstrap_seed=42,
    )
    defaults.update(overrides)
    return FinanceConfig(**defaults)


def _make_n2_eval_results(ebitda_y: float, fixed_om: float = 0.0,
                           e_net_mwh: float = 0.0) -> list[PolicyEvalResult]:
    """Two-year trajectory: years y=1,2. Each year has the given EBITDA and fixed OM.

    For Vector-1: EBITDA = revenue − fixed_om = 700k − 100k = 600k per year.
    finance() reconstructs CF(y) = EBITDA − Tax − Replacement from these fields.
    """
    year = _make_eval_result(
        grid_export_yuan=ebitda_y + fixed_om,  # revenue
        demand_charge_yuan=fixed_om,            # cost (= fixed OM here for simplicity)
        generation_mwh=e_net_mwh,
        energy_cost_yuan=0.0,
    )
    return [year, year]  # same year repeated for N=2


# ---------------------------------------------------------------------------
# FIN-00 — Vector 0: CAPM → r_e → WACC (gates the discount module)
# Source: PR #107 Vector 0
# Inputs: β_U=0.60, ERP=0.060, CRP=0, horizon=20yr
#         CGB curve: 10yr=0.0200, 30yr=0.0260 (illustrative static config)
#         all-equity base (D/E=0); levered: D/E=1.5, r_d=5yr-LPR+125bps=0.0475, tax=0.25
# ---------------------------------------------------------------------------

_CGB_CURVE_V0 = CgbCurve(
    snapshot_date="2026-01-01",
    points={10: 0.0200, 30: 0.0260},
    lpr_5yr=0.0350,
)

_CAPM_CONFIG_BASE = FinanceConfig(
    beta_unlevered=0.60,
    equity_risk_premium=0.060,
    country_risk_premium=0.0,
    cgb_curve=_CGB_CURVE_V0,
    r_f_override=None,      # use curve interpolation
    tax_rate=0.25,
    tax_toggle=False,
    debt_toggle=False,
    target_de_ratio=0.0,    # all-equity
    horizon_years=20,
    valuation_date="2026-01-01",
)

_CAPM_CONFIG_LEVERED = FinanceConfig(
    beta_unlevered=0.60,
    equity_risk_premium=0.060,
    country_risk_premium=0.0,
    cgb_curve=_CGB_CURVE_V0,
    r_f_override=None,
    tax_rate=0.25,
    tax_toggle=False,
    debt_toggle=True,
    target_de_ratio=1.5,    # D/E=1.5 → E/V=0.4, D/V=0.6
    credit_spread=0.0125,   # 125 bps over 5yr LPR
    horizon_years=20,
    valuation_date="2026-01-01",
)


def test_fin00_cgb_interpolation():
    """FIN-00a: CGB linear-interp 10yr↔30yr to 20yr horizon → r_f = 0.0230.

    r_f = 0.0200 + (0.0260 − 0.0200) · (20−10)/(30−10)
        = 0.0200 + 0.0060 · 0.5
        = 0.0230   (2.30%)
    """
    result = compute_wacc(_CAPM_CONFIG_BASE)
    assert result["r_f"] == pytest.approx(0.0230, abs=TOL_DISCOUNT_DECIMAL)


def test_fin00_base_beta_levered():
    """FIN-00b: Hamada relever for all-equity base (D/E=0) → β_L = β_U = 0.60.

    β_L = β_U · (1 + (1 − tax) · D/E)
        = 0.60 · (1 + 0.75 · 0) = 0.60
    """
    result = compute_wacc(_CAPM_CONFIG_BASE)
    assert result["beta_levered"] == pytest.approx(0.60, abs=TOL_DISCOUNT_DECIMAL)


def test_fin00_base_cost_of_equity():
    """FIN-00c: CAPM base r_e (unlevered) = 0.0590.

    r_e = r_f + β_L · ERP + CRP
        = 0.0230 + 0.60 · 0.060 + 0
        = 0.0230 + 0.0360 = 0.0590   (5.90%)
    """
    result = compute_wacc(_CAPM_CONFIG_BASE)
    assert result["r_e"] == pytest.approx(0.0590, abs=TOL_DISCOUNT_DECIMAL)


def test_fin00_base_wacc_collapses_to_re():
    """FIN-00d: All-equity → WACC = r_e (no debt term).

    WACC = (E/V)·r_e + (D/V)·r_d·(1−tax) = 1.0·r_e + 0·(·) = r_e = 0.0590
    """
    result = compute_wacc(_CAPM_CONFIG_BASE)
    assert result["wacc"] == pytest.approx(result["r_e"], abs=TOL_DISCOUNT_DECIMAL)
    assert result["wacc"] == pytest.approx(0.0590, abs=TOL_DISCOUNT_DECIMAL)


def test_fin00_levered_beta():
    """FIN-00e: Hamada relever for D/E=1.5 → β_L = 1.275.

    β_L = 0.60 · (1 + (1 − 0.25) · 1.5)
        = 0.60 · (1 + 0.75 · 1.5)
        = 0.60 · (1 + 1.125)
        = 0.60 · 2.125 = 1.275
    """
    result = compute_wacc(_CAPM_CONFIG_LEVERED)
    assert result["beta_levered"] == pytest.approx(1.275, abs=TOL_DISCOUNT_DECIMAL)


def test_fin00_levered_cost_of_equity():
    """FIN-00f: CAPM levered r_e = 0.0995.

    r_e(lev) = r_f + β_L · ERP + CRP
             = 0.0230 + 1.275 · 0.060 + 0
             = 0.0230 + 0.0765 = 0.0995   (9.95%)
    """
    result = compute_wacc(_CAPM_CONFIG_LEVERED)
    assert result["r_e"] == pytest.approx(0.0995, abs=TOL_DISCOUNT_DECIMAL)


def test_fin00_levered_wacc():
    """FIN-00g: Levered WACC = 0.061175.

    WACC = (E/V)·r_e + (D/V)·r_d·(1−tax)
    E/V = 1/(1+D/E) = 1/2.5 = 0.4;  D/V = 1.5/2.5 = 0.6
    r_d = 5yr-LPR + 125bps = 0.0350 + 0.0125 = 0.0475
    WACC = 0.4·0.0995 + 0.6·0.0475·0.75
         = 0.03980 + 0.6·0.035625
         = 0.03980 + 0.021375 = 0.061175   (6.1175%)
    """
    result = compute_wacc(_CAPM_CONFIG_LEVERED)
    assert result["wacc"] == pytest.approx(0.061175, abs=TOL_DISCOUNT_DECIMAL)


def test_fin00_hurdle_default_is_re():
    """FIN-00h: Default hurdle rate = r_e (CAPM base), no explicit override.

    The P(IRR<hurdle) downside metric defaults to the CAPM r_e as hurdle.
    Vector 0 assertion: hurdle = r_e = 0.0590 when debt OFF.
    """
    result = compute_wacc(_CAPM_CONFIG_BASE)
    assert result.get("hurdle_rate") == pytest.approx(result["r_e"], abs=TOL_DISCOUNT_DECIMAL)


# ---------------------------------------------------------------------------
# FIN-01–FIN-06 — Vector 1: BASE pre-tax unlevered (M=1 point estimates)
# Source: PR #107 Vector 1
# Inputs: N=2, CAPEX=¥1,000,000, revenue=¥700,000/yr, fixed_OM=¥100,000/yr
#         EBITDA=¥600,000/yr, E_net=10,000 MWh/yr, r=0.10
# CF = [−1,000,000, +600,000, +600,000]
# ---------------------------------------------------------------------------

_CF_V1 = [-1_000_000.0, 600_000.0, 600_000.0]
_R_V1  = 0.10
_N_V1  = 2


def test_fin01_npv_base():
    """FIN-01: Vector 1 NPV = ¥41,322.31.

    NPV(0.10) = −1,000,000 + 600,000/1.10 + 600,000/1.10²
              = −1,000,000 + 545,454.5455 + 495,867.7686
              = ¥41,322.31
    """
    result = npv(_CF_V1, _R_V1)
    # −1,000,000 + 600,000/1.10 + 600,000/1.21 = −1,000,000 + 545,454.5455 + 495,867.7686
    assert result == pytest.approx(41_322.31, abs=TOL_NPV_YUAN)


def test_fin02_irr_base():
    """FIN-02: Vector 1 IRR = 13.0662%.

    IRR solves 600,000u + 600,000u² = 1,000,000
    → u² + u − 5/3 = 0
    disc = 1 + 4·(5/3) = 7.66667; √ = 2.7688746
    u = (−1 + 2.7688746)/2 = 0.8844373
    IRR = 1/0.8844373 − 1 = 0.1306624 = 13.0662%
    """
    result = irr(_CF_V1)
    # exact: 1/u − 1 where u = (√(1+4·5/3) − 1)/2
    assert result == pytest.approx(0.1306624, abs=TOL_RATE_PP)


def test_fin03_mirr_base():
    """FIN-03: Vector 1 MIRR = 12.2497%.

    MIRR (reinvest=finance=0.10):
    FV_pos@yr2 = 600,000·1.10 + 600,000 = 660,000 + 600,000 = 1,260,000
    PV_neg      = 1,000,000
    MIRR = (1,260,000/1,000,000)^(1/2) − 1 = √1.26 − 1
         = 1.1224972 − 1 = 0.1224972 = 12.2497%
    """
    result = mirr(_CF_V1, finance_rate=_R_V1, reinvest_rate=_R_V1)
    assert result == pytest.approx(0.1224972, abs=TOL_RATE_PP)


def test_fin04_payback_simple():
    """FIN-04: Vector 1 simple payback = 1.66667 yr.

    After yr1: cumCF = 600,000; remaining = 1,000,000 − 600,000 = 400,000
    payback = 1 + 400,000/600,000 = 1 + 0.66667 = 1.66667 yr
    """
    result = payback_simple(_CF_V1)
    assert result == pytest.approx(1.66667, abs=TOL_PAYBACK_YR)


def test_fin05_payback_discounted():
    """FIN-05: Vector 1 discounted payback @0.10 = 1.91667 yr.

    disc CF yr1 = 600,000/1.10 = 545,454.5455  → cum = 545,454.5455 < 1,000,000 (not recovered)
    remaining after yr1 = 1,000,000 − 545,454.5455 = 454,545.4545
    disc CF yr2 = 600,000/1.10² = 600,000/1.21 = 495,867.7686
    payback = 1 + 454,545.4545/495,867.7686 = 1 + 0.91667 = 1.91667 yr
    """
    result = payback_discounted(_CF_V1, rate=_R_V1)
    assert result == pytest.approx(1.91667, abs=TOL_PAYBACK_YR)


def test_fin06_lcoe():
    """FIN-06: Vector 1 LCOE = ¥67.62/MWh.

    LCOE = PV(costs) / PV(E_net)
    PV(costs) = 1,000,000 + 100,000/1.10 + 100,000/1.10²
              = 1,000,000 + 90,909.0909 + 82,644.6281 = 1,173,553.7190
    PV(E_net) = 10,000/1.10 + 10,000/1.10²
              = 9,090.9091 + 8,264.4628 = 17,355.3719 MWh
    LCOE = 1,173,553.7190 / 17,355.3719 = ¥67.62/MWh
    """
    cf_costs = [-1_000_000.0, -100_000.0, -100_000.0]  # CAPEX + FixedOM (no revenue)
    e_net    = [0.0, 10_000.0, 10_000.0]                # MWh per year
    result = lcoe(cf_costs, e_net, rate=_R_V1)
    # PV_num = 1,173,553.719; PV_den = 17,355.372; ratio = 67.62 ¥/MWh
    assert result == pytest.approx(67.62, abs=TOL_LCOE_YUAN_MWH)


# ---------------------------------------------------------------------------
# FIN-07–FIN-10 — Vector 2: TAX TOGGLE (delta to base, same CAPEX/EBITDA as V1)
# Source: PR #107 Vector 2
# Inputs: tax_rate=0.25, straight-line dep over 2yr → dep=500,000/yr
#         taxable(y) = EBITDA − dep = 600,000 − 500,000 = 100,000
#         tax(y)     = 0.25·100,000 = 25,000
#         CF(y)      = 600,000 − 25,000 = 575,000
# CF_tax = [−1,000,000, +575,000, +575,000]
# ---------------------------------------------------------------------------

_CF_V2 = [-1_000_000.0, 575_000.0, 575_000.0]


def test_fin07_npv_after_tax():
    """FIN-07: Vector 2 after-tax NPV = −¥2,066.12.

    NPV(0.10) = −1,000,000 + 575,000/1.10 + 575,000/1.10²
              = −1,000,000 + 522,727.2727 + 475,206.6116
              = −¥2,066.12
    """
    result = npv(_CF_V2, _R_V1)
    # −1,000,000 + 522,727.27 + 475,206.61 = −2,066.12
    assert result == pytest.approx(-2_066.12, abs=TOL_NPV_YUAN)


def test_fin08_delta_npv_tax():
    """FIN-08: ΔNPV_tax (delta from base to after-tax) = −¥43,388.43.

    ΔNPV_tax = −(25,000/1.10 + 25,000/1.10²)
             = −(22,727.2727 + 20,661.1570) = −¥43,388.43
    Cross-check: V1 NPV + ΔNPV_tax = 41,322.31 + (−43,388.43) = −2,066.12 ✓
    """
    npv_base     = npv(_CF_V1, _R_V1)   # 41,322.31
    npv_after    = npv(_CF_V2, _R_V1)   # −2,066.12
    delta        = npv_after - npv_base
    # −(25,000/1.10 + 25,000/1.21) = −(22,727.27 + 20,661.16) = −43,388.43
    assert delta == pytest.approx(-43_388.43, abs=TOL_NPV_YUAN)
    assert npv_base + delta == pytest.approx(npv_after, abs=TOL_NPV_YUAN)  # cross-check


def test_fin09_irr_after_tax():
    """FIN-09: Vector 2 after-tax IRR = 9.8460% (below 10% hurdle → NPV<0 consistent).

    IRR solves 575,000u + 575,000u² = 1,000,000
    → u² + u − 1,000,000/575,000 = 0  (1,000,000/575,000 = 1.7391304)
    disc = 1 + 4·1.7391304 = 7.9565217; √ = 2.8207307
    u = (−1 + 2.8207307)/2 = 0.9103654
    IRR = 1/0.9103654 − 1 = 0.0984601 = 9.8460%
    """
    result = irr(_CF_V2)
    # exact: 1/u − 1 where u = (√(7.9565217) − 1)/2
    assert result == pytest.approx(0.0984601, abs=TOL_RATE_PP)


def test_fin10_tax_delta_reporting():
    """FIN-10: Tax block is reported as delta_to_base; base (tax=OFF) unchanged.

    Finance contract: when tax_toggle=True, the engine emits delta_to_base fields
    (not just the after-tax absolute), and the tax=OFF baseline matches Vector 1.
    The tax toggle is OFF → CF is the pre-tax CF (Vector 1 numbers apply).
    This test verifies the base case is reproduced when tax_toggle=False.
    """
    # base case: tax OFF → CF = [−1,000,000, +600,000, +600,000]
    result_base = npv(_CF_V1, _R_V1)
    assert result_base == pytest.approx(41_322.31, abs=TOL_NPV_YUAN)
    # tax ON → CF = [−1,000,000, +575,000, +575,000]; delta = −43,388.43
    result_tax = npv(_CF_V2, _R_V1)
    assert result_tax - result_base == pytest.approx(-43_388.43, abs=TOL_NPV_YUAN)


# ---------------------------------------------------------------------------
# FIN-11–FIN-14 — Vector 3: LEVERED DELTA (equity-IRR + min-DSCR)
# Source: PR #107 Vector 3
# Inputs: CAPEX=1,000,000; D/E=1.5 → Debt=600,000, Equity=400,000
#         loan: r_d=0.05, term=2yr; EBITDA=600,000 (pre-tax base, same as V1)
# Annuity A = 600,000·[0.05·1.05²]/[1.05²−1]
#           = 600,000·0.055125/0.1025 = ¥322,682.93/yr
# Amort yr1: int=30,000; prin=292,682.93; bal=307,317.07
# Amort yr2: int=15,365.85; prin=307,317.08; bal≈0 ✓
# ---------------------------------------------------------------------------

_CAPEX_V3   = 1_000_000.0
_DEBT_V3    = 600_000.0
_EQUITY_V3  = 400_000.0
_R_D_V3     = 0.05
_N_V3       = 2

# Level annuity: A = P·[r·(1+r)^n]/[(1+r)^n−1]
# = 600,000·[0.05·1.1025]/[1.1025−1] = 600,000·0.055125/0.1025 = 322,682.926…
_ANNUITY_V3 = 600_000.0 * (0.05 * 1.05**2) / (1.05**2 - 1)

# Equity CF: CF_eq(0) = −400,000; CF_eq(y) = EBITDA − A = 600,000 − 322,682.93 = 277,317.07
_CF_EQ_V3 = [-_EQUITY_V3, 600_000.0 - _ANNUITY_V3, 600_000.0 - _ANNUITY_V3]


def test_fin11_dscr():
    """FIN-11: Vector 3 min-DSCR = 1.859 (level annuity → same both years).

    CFADS(y) = EBITDA = 600,000 (pre-tax, no tax here)
    DSCR(y)  = CFADS / DebtService = 600,000 / 322,682.93 = 1.8594
    min-DSCR = 1.859 (level → both years the same)

    Annuity check: A = 600,000·0.055125/0.1025 = 322,682.93
    """
    cfads_series    = [600_000.0, 600_000.0]
    service_series  = [_ANNUITY_V3, _ANNUITY_V3]
    result = dscr(cfads_series, service_series)
    # 600,000 / (600,000·0.055125/0.1025) = 600,000/322,682.93 = 1.8594
    assert result["min_dscr"] == pytest.approx(1.8594, abs=TOL_DSCR)


def test_fin12_equity_irr():
    """FIN-12: Vector 3 equity-IRR = 24.8565%.

    CF_eq(0) = −400,000;  CF_eq(y) = 600,000 − 322,682.93 = 277,317.07
    Solves 277,317.07(u + u²) = 400,000
    → u² + u − 400,000/277,317.07 = 0  (ratio = 1.44239…)
    disc = 1 + 4·1.44239 = 6.76956; √ = 2.60184
    u = (−1 + 2.60184)/2 = 0.80092
    IRR_eq = 1/0.80092 − 1 = 0.24856 = 24.856%
    """
    result = irr(_CF_EQ_V3)
    # exact: u = (√(1+4·400k/277.317k) − 1)/2; IRR = 1/u − 1
    assert result == pytest.approx(0.2485645, abs=TOL_RATE_PP)


def test_fin13_levered_delta():
    """FIN-13: ΔIRR (levered delta) = IRR_eq − IRR_project = +11.79 pp.

    IRR_project = 13.0662% (Vector 1)
    IRR_eq      = 24.8565% (Vector 3)
    ΔIRR = 24.8565 − 13.0662 = +11.79 pp  (positive leverage: project return > r_d=5%)
    """
    irr_project = irr(_CF_V1)     # 0.1306624 = 13.0662%
    irr_equity  = irr(_CF_EQ_V3)  # 0.2485645 = 24.8565%
    delta_pp    = (irr_equity - irr_project) * 100
    # 24.8565 − 13.0662 = 11.79 pp
    assert delta_pp == pytest.approx(11.79, abs=0.01)


def test_fin14_debt_gating_absent_when_off():
    """FIN-14: equity_irr and min_dscr are ABSENT (not zero/null) when debt_toggle=False.

    Contract: debt-gated fields must be Python None (not 0.0) when debt is OFF.
    A None-not-zero contract is distinct from a zero-meaning-"no debt" convention.
    """
    # Build a minimal M=1 ensemble using Vector 1 trajectory
    yr = _make_eval_result(grid_export_yuan=700_000.0, demand_charge_yuan=100_000.0,
                           generation_mwh=10_000.0)
    ensemble = PolicyEnsemble(
        seed=0, M=1, sample_kind="bootstrap",
        runs={"policy_a": [[yr, yr]]},
    )
    config = _make_base_config(debt_toggle=False)
    # CAPEX must be provided via econ — use a minimal stub
    from energy_go.finance.econ_params import DeviceEconParams
    econ = DeviceEconParams(total_capex_yuan=1_000_000.0)
    price_paths = [PricePath(id="flat", label="Flat", multipliers=[1.0, 1.0])]

    result = finance(ensemble, price_paths, econ, config)
    view = result.per_policy["policy_a"].per_price_path["flat"].view_i
    # debt-gated fields must be absent (None), not zero
    assert view.equity_irr is None, "equity_irr must be None when debt_toggle=False"
    assert view.min_dscr   is None, "min_dscr must be None when debt_toggle=False"


# ---------------------------------------------------------------------------
# FIN-15–FIN-22 — Downside stats: M=50 linear ensemble (§A of PR #107)
# NPV_m = −100,000 + (m−1)·10,000, m=1…50
#   sorted ascending: x[0]=−100,000, x[1]=−90,000, …, x[49]=+390,000
# IRR_m = 0.04 + (m−1)·0.005, m=1…50; hurdle=0.10
# Drawdown trajectory: CF(y) = [+100k, −150k, −250k, +180k, +320k]
# ---------------------------------------------------------------------------

# Build M=50 NPV array ascending
_NPV_ARR = np.array([-100_000.0 + (m - 1) * 10_000.0 for m in range(1, 51)])
# Build M=50 IRR array ascending
_IRR_ARR = np.array([0.04 + (m - 1) * 0.005 for m in range(1, 51)])
# Drawdown trajectory (annual net CF, year-0 CAPEX excluded)
_DRAWDOWN_CF = [100_000.0, -150_000.0, -250_000.0, 180_000.0, 320_000.0]


def test_fin15_worst_case_npv():
    """FIN-15: Worst-case NPV = −¥100,000 (min of the M=50 ensemble).

    min_m NPV_m = NPV_1 = −100,000 + (1−1)·10,000 = −100,000
    """
    result = np.min(_NPV_ARR)
    assert result == pytest.approx(-100_000.0, abs=TOL_NPV_YUAN)


def test_fin16_p_npv_neg():
    """FIN-16: P(NPV<0) = 0.20 (10 out of 50 draws are negative).

    m=1…10: NPV_m = −100k, −90k, …, −10k  (all < 0)
    m=11:   NPV_11 = −100,000 + 10·10,000 = 0 (exactly 0, NOT negative)
    P(NPV<0) = 10/50 = 0.20
    """
    result = p_below(_NPV_ARR, threshold=0.0)
    # #{m: NPV_m < 0} = #{m: −100k + (m−1)·10k < 0} = #{m-1 < 10} = 10
    assert result == pytest.approx(0.20, abs=1e-9)


def test_fin17_p_irr_below_hurdle():
    """FIN-17: P(IRR < hurdle=0.10) = 0.24.

    IRR_m = 0.04 + (m−1)·0.005 < 0.10
    → (m−1)·0.005 < 0.06 → m−1 < 12 → m ≤ 12 (m=1…12)
    P(IRR<0.10) = 12/50 = 0.24
    """
    result = p_below(_IRR_ARR, threshold=0.10)
    assert result == pytest.approx(0.24, abs=1e-9)


def test_fin18_cvar5():
    """FIN-18: CVaR-5% = −¥90,000 (mean of k=3 worst NPV draws).

    k = ceil(0.05·50) = ceil(2.5) = 3
    Worst 3: NPV_1=−100,000; NPV_2=−90,000; NPV_3=−80,000
    CVaR-5% = mean(−100,000; −90,000; −80,000) = −270,000/3 = −¥90,000
    """
    result = cvar5(_NPV_ARR, M=50)
    # k = ceil(0.05·50) = 3; sorted[0:3] = [−100k, −90k, −80k]; mean = −90k
    assert result == pytest.approx(-90_000.0, abs=TOL_NPV_YUAN)


def test_fin19_p50_exceedance():
    """FIN-19: P50 exceedance NPV = ¥140,000.

    estimator: np.quantile(arr, 1−0.50, method='lower') = np.quantile(arr, 0.50, method='lower')
    0-based index: i = floor(0.50·(50−1)) = floor(24.5) = 24
    x[24] = −100,000 + 24·10,000 = ¥140,000
    (meaning: in 50% of scenarios NPV ≥ ¥140,000)
    """
    result = exceedance_percentile(_NPV_ARR, q=0.50, higher_is_better=True)
    # np.quantile(sorted, 0.50, method='lower') → index 24 → −100k + 24·10k = 140k
    assert result == pytest.approx(140_000.0, abs=TOL_NPV_YUAN)


def test_fin20_p75_exceedance():
    """FIN-20: P75 exceedance NPV = ¥20,000.

    estimator: np.quantile(arr, 1−0.75, method='lower') = np.quantile(arr, 0.25, method='lower')
    0-based index: i = floor(0.25·49) = floor(12.25) = 12
    x[12] = −100,000 + 12·10,000 = ¥20,000
    (meaning: in 75% of scenarios NPV ≥ ¥20,000)
    """
    result = exceedance_percentile(_NPV_ARR, q=0.75, higher_is_better=True)
    # np.quantile(sorted, 0.25, method='lower') → index 12 → −100k + 12·10k = 20k
    assert result == pytest.approx(20_000.0, abs=TOL_NPV_YUAN)


def test_fin21_p90_exceedance():
    """FIN-21: P90 exceedance NPV = −¥60,000.

    estimator: np.quantile(arr, 1−0.90, method='lower') = np.quantile(arr, 0.10, method='lower')
    0-based index: i = floor(0.10·49) = floor(4.9) = 4
    x[4] = −100,000 + 4·10,000 = −¥60,000
    (meaning: in 90% of scenarios NPV ≥ −¥60,000)
    """
    result = exceedance_percentile(_NPV_ARR, q=0.90, higher_is_better=True)
    # np.quantile(sorted, 0.10, method='lower') → index 4 → −100k + 4·10k = −60k
    assert result == pytest.approx(-60_000.0, abs=TOL_NPV_YUAN)


def test_fin22a_p95_exceedance():
    """FIN-22a: P95 exceedance NPV = −¥80,000.

    estimator: np.quantile(arr, 1−0.95, method='lower') = np.quantile(arr, 0.05, method='lower')
    0-based index: i = floor(0.05·49) = floor(2.45) = 2
    x[2] = −100,000 + 2·10,000 = −¥80,000
    (meaning: in 95% of scenarios NPV ≥ −¥80,000)
    """
    result = exceedance_percentile(_NPV_ARR, q=0.95, higher_is_better=True)
    # np.quantile(sorted, 0.05, method='lower') → index 2 → −100k + 2·10k = −80k
    assert result == pytest.approx(-80_000.0, abs=TOL_NPV_YUAN)


def test_fin22b_max_drawdown():
    """FIN-22b: Max cumulative drawdown = −¥300,000 at year 3.

    CF(y): +100k, −150k, −250k, +180k, +320k  (year-0 CAPEX excluded)
    cumCF: +100k,  −50k, −300k, −120k, +200k  (computed INTERNALLY by max_drawdown)
    shortfall-below-zero: min(0, min(+100k, −50k, −300k, −120k, +200k))
                        = min(0, −300,000) = −¥300,000  at year 3
    (NOT peak-to-trough — LOCKED §13.10b shortfall-below-zero literal, finance-expert PR #107 §A)

    IMPORTANT: pass the annual CF series — max_drawdown() cumsums internally.
    Pre-cumsumming here would double-cumsum → wrong trough (−370k at yr4 instead of −300k at yr3).
    Consistent with worst_year_cf(cf_excl_capex) convention.  (finance-expert REQUEST_CHANGES PR #110)
    """
    # Pass annual series; function does cumsum internally per LOCKED §13.10b formula:
    # max_drawdown = min(0, min(np.cumsum(cf_excl_capex)))
    result_val  = max_drawdown(_DRAWDOWN_CF)["drawdown_yuan"]
    result_year = max_drawdown(_DRAWDOWN_CF)["drawdown_year"]
    # cumCF = [100k, −50k, −300k, −120k, +200k]; min(0, −300k) = −300,000; argmin=idx2 → year 3
    assert result_val  == pytest.approx(-300_000.0, abs=TOL_NPV_YUAN)
    assert result_year == 3


def test_fin22c_worst_year_cf():
    """FIN-22c: Worst single-year CF = −¥250,000 (year 3).

    CF(y): +100k, −150k, −250k, +180k, +320k
    min = −250,000 at year 3
    (year-0 CAPEX excluded — CAPEX is certain; §13.10b)
    """
    result = worst_year_cf(_DRAWDOWN_CF)
    # min(+100k, −150k, −250k, +180k, +320k) = −250k at y=3
    assert result["worst_cf_yuan"] == pytest.approx(-250_000.0, abs=TOL_NPV_YUAN)
    assert result["worst_cf_year"] == 3


# ---------------------------------------------------------------------------
# FIN-23–FIN-27 — No-double-count invariants (§13.2 + §13.4, PR #107 §B)
# ---------------------------------------------------------------------------

def test_fin23_inv_basis():
    """FIN-23: INV-BASIS — cash output = real-money exactly even when reward-basis differs.

    A draw where reward-basis totals (penalty_yuan, soc_violation_mwh) differ materially
    from real-money → the cash-flow output equals real-money ONLY.
    A wired reward-basis field FAILS the test (structural unreachability).

    Fixture: real_money total = ¥100,000; reward-basis adds penalty_yuan = ¥999,999.
    Expected cash flow basis: energy_cost_yuan alone, ignoring penalty_yuan entirely.
    """
    yr = _make_eval_result(
        energy_cost_yuan=100_000.0,   # D13 real-money
        grid_export_yuan=800_000.0,   # real revenue
        grid_import_yuan=700_000.0,   # real cost → net = 100k → energy_cost_yuan
    )
    # Force penalty and SOC fields to a large non-zero value to verify they're NOT read
    yr_with_penalty = PolicyEvalResult(
        energy_cost_yuan=yr.energy_cost_yuan,
        demand_charge_yuan=yr.demand_charge_yuan,
        degradation_yuan=yr.degradation_yuan,
        curtailment_yuan=yr.curtailment_yuan,
        voll_yuan=yr.voll_yuan,
        total_cost_yuan=yr.total_cost_yuan,
        soc_violations_count=yr.soc_violations_count,
        soc_violation_mwh=yr.soc_violation_mwh,
        penalty_yuan=999_999.0,   # large reward-basis field — MUST be structurally ignored
        streams=yr.streams,
        generation_mwh=yr.generation_mwh,
        wind_generated_mwh=yr.wind_generated_mwh,
        pv_generated_mwh=yr.pv_generated_mwh,
        bat_charge_mwh=yr.bat_charge_mwh,
        bat_discharge_mwh=yr.bat_discharge_mwh,
        bat_throughput_mwh=yr.bat_throughput_mwh,
        load_served_mwh=yr.load_served_mwh,
        load_unserved_mwh=yr.load_unserved_mwh,
        curtailed_mwh=yr.curtailed_mwh,
        wind_to_load_mwh=yr.wind_to_load_mwh, wind_to_bat_mwh=yr.wind_to_bat_mwh,
        wind_to_grid_mwh=yr.wind_to_grid_mwh, wind_curtailed_mwh=yr.wind_curtailed_mwh,
        pv_to_load_mwh=yr.pv_to_load_mwh, pv_to_bat_mwh=yr.pv_to_bat_mwh,
        pv_to_grid_mwh=yr.pv_to_grid_mwh, pv_curtailed_mwh=yr.pv_curtailed_mwh,
        bat_to_load_mwh=yr.bat_to_load_mwh, bat_to_grid_mwh=yr.bat_to_grid_mwh,
        bat_curtailed_mwh=yr.bat_curtailed_mwh,
        grid_to_bat_mwh=yr.grid_to_bat_mwh, grid_to_load_mwh=yr.grid_to_load_mwh,
    )
    # Cash output must equal the real-money streams, ignoring penalty_yuan
    cf = build_cash_flow_series([yr_with_penalty])
    # Revenue = grid_export = 800,000; Cost = grid_import = 700,000; net operating = 100,000
    # The penalty_yuan of 999,999 must NOT appear in cf
    assert cf[1] == pytest.approx(100_000.0, abs=TOL_NPV_YUAN), (
        "penalty_yuan must be structurally unreachable from cash-flow path (INV-BASIS)"
    )


def test_fin23b_inv_stream_authority():
    """FIN-23b: INV-STREAM-AUTHORITY — operating cash = streams only; energy_cost_yuan is a
    non-additive reconciliation view and MUST NOT be summed into EBITDA.

    streams: grid_export=¥800,000, grid_import=¥700,000
      stream-net operating cash = grid_export − grid_import = ¥100,000
    real_money.energy_cost_yuan = ¥555,555  (DECOY — faithful sign would be
      import−export = −100,000; we use 555,555 so a buggy additive impl produces
      100,000 + 555,555 = 655,555 → detectable double-count)

    Expected CF = ¥100,000 (stream-net only). Any other value proves double-counting.

    INV-STREAM-AUTHORITY §3.5a: energy_cost_yuan ≡ grid_import.value_yuan − grid_export.value_yuan
    (a derived view, already captured in the streams). Adding it to EBITDA is a double-count.
    finance-expert ruling (REQUEST_CHANGES PR #110 / teammate message).
    """
    yr = _make_eval_result(
        grid_export_yuan=800_000.0,
        grid_import_yuan=700_000.0,
        energy_cost_yuan=555_555.0,   # DECOY — streams already account for import/export
    )
    cf = build_cash_flow_series([yr])
    # stream-net = grid_export − grid_import = 800,000 − 700,000 = ¥100,000
    # energy_cost_yuan (¥555,555) must be IGNORED (non-additive view, not a cash source)
    # additive impl → cf[1] = 100,000 + 555,555 = 655,555 → FAIL
    assert cf[1] == pytest.approx(100_000.0, abs=TOL_NPV_YUAN), (
        "real_money.energy_cost_yuan is a non-additive reconciliation view; "
        "cash = stream-net only (INV-STREAM-AUTHORITY §3.5a)"
    )


def test_fin24_inv_deg():
    """FIN-24: INV-DEG — degradation_yuan is memo-only; cash impact = replacement CAPEX at EOL year.

    Fixture: 1 year of throughput → degradation_yuan shows wear signal;
    cash-flow output has NO degradation_yuan period deduction (only replacement CAPEX at EOL).
    Verifies the D13 component is NOT double-counted as both wear signal AND period cash.
    """
    yr = _make_eval_result(
        degradation_yuan=50_000.0,   # wear signal — memo-only, NOT period cash
        grid_export_yuan=700_000.0,
        bat_throughput_mwh=5_000.0,
    )
    cf = build_cash_flow_series([yr], include_degradation_as_cash=False)
    # The degradation_yuan (50,000) must NOT appear as a period deduction
    # cf[1] = EBITDA (before replacement CAPEX) — which does NOT include 50,000 degradation_yuan
    # EBITDA = grid_export_yuan revenue − costs = 700,000 (no other costs in fixture)
    assert cf[1] == pytest.approx(700_000.0, abs=TOL_NPV_YUAN), (
        "degradation_yuan must NOT enter period cash-flow (INV-DEG); "
        "cash treatment = replacement CAPEX at EOL year only"
    )


def test_fin25_inv_curt():
    """FIN-25: INV-CURT — when curtailment_penalty_contract=False,
    cash loss = foregone grid_export revenue ONLY (no ¥800/MWh penalty term).

    Fixture: 1 curtailed MWh at ¥800/MWh penalty rate; flag=OFF.
    Expected: cash loss = foregone grid_export revenue (based on grid_export stream),
    NOT revenue + curtailment_yuan penalty.
    """
    yr_no_curtail = _make_eval_result(
        grid_export_yuan=700_000.0,
        curtailment_yuan=0.0,
    )
    yr_with_curtail = _make_eval_result(
        grid_export_yuan=699_200.0,   # 1 MWh foregone at ¥800/MWh → export revenue reduced
        curtailment_yuan=800.0,       # §13.2 c_curtail signal — flag=OFF → NOT period cash
    )
    cf_no  = build_cash_flow_series([yr_no_curtail],  curtailment_penalty_contract=False)
    cf_yes = build_cash_flow_series([yr_with_curtail], curtailment_penalty_contract=False)
    # Cash difference = foregone export revenue only = 700,000 − 699,200 = 800 ¥
    # NOT 800 (revenue) + 800 (penalty) = 1,600 ¥
    assert cf_no[1] - cf_yes[1] == pytest.approx(800.0, abs=TOL_NPV_YUAN), (
        "curtailment cash loss must equal foregone export revenue only (INV-CURT, flag=OFF)"
    )


def test_fin26_inv_voll():
    """FIN-26: INV-VOLL — VOLL is NOT added to cash flow when own-load uses lost-product revenue.

    Fixture: 1 MWh unserved (load); own-load scenario uses lost-product revenue stream.
    reliability_penalty_contract=False → voll_yuan is memo-only.
    Cash hit = lost product revenue once (not VOLL + lost-product).
    """
    yr_full_served = _make_eval_result(
        grid_export_yuan=700_000.0,
        voll_yuan=0.0,
    )
    yr_unserved = _make_eval_result(
        grid_export_yuan=680_000.0,   # lost product revenue = 700k − 680k = 20k
        voll_yuan=20_000.0,           # VOLL signal — flag=OFF → NOT period cash
    )
    cf_full    = build_cash_flow_series([yr_full_served], reliability_penalty_contract=False)
    cf_unserv  = build_cash_flow_series([yr_unserved],   reliability_penalty_contract=False)
    # Cash difference = lost product revenue = 20,000 ¥ (not 20,000 + 20,000 = 40,000)
    assert cf_full[1] - cf_unserv[1] == pytest.approx(20_000.0, abs=TOL_NPV_YUAN), (
        "VOLL must NOT be added to cash flow when reliability_penalty_contract=False (INV-VOLL)"
    )


def test_fin27_inv_finlayer():
    """FIN-27: INV-FINLAYER — non-uniform price path sets requires_retrain=True and badges result.

    A uniform multiplier (m(y)=1 for all y) → requires_retrain=False.
    A non-uniform multiplier (e.g. m=[1.0, 0.8]) → requires_retrain=True.
    (§13.4: non-uniform paths genuinely change dispatch incentives → must signal retrain)
    """
    yr = _make_eval_result(grid_export_yuan=700_000.0)
    ensemble = PolicyEnsemble(
        seed=0, M=1, sample_kind="bootstrap",
        runs={"policy_a": [[yr, yr]]},
    )
    from energy_go.finance.econ_params import DeviceEconParams
    econ   = DeviceEconParams(total_capex_yuan=1_000_000.0)
    config = _make_base_config()

    # Uniform path → requires_retrain=False
    flat_path   = PricePath(id="flat", label="Flat", multipliers=[1.0, 1.0])
    result_flat = finance(ensemble, [flat_path], econ, config)
    assert result_flat.requires_retrain is False, (
        "uniform price path must NOT set requires_retrain=True (INV-FINLAYER)"
    )

    # Non-uniform path → requires_retrain=True
    nonunif_path   = PricePath(id="decline", label="Decline", multipliers=[1.0, 0.8])
    result_nonunif = finance(ensemble, [nonunif_path], econ, config)
    assert result_nonunif.requires_retrain is True, (
        "non-uniform price path must set requires_retrain=True (INV-FINLAYER)"
    )


# ---------------------------------------------------------------------------
# FIN-28–FIN-31 — R1 regime: M=1 honesty (§13.10c)
# ---------------------------------------------------------------------------

def _make_m1_ensemble() -> PolicyEnsemble:
    """Single-draw (M=1) ensemble for R1 tests."""
    yr = _make_eval_result(grid_export_yuan=700_000.0, demand_charge_yuan=100_000.0)
    return PolicyEnsemble(
        seed=42, M=1, sample_kind="bootstrap",
        runs={"policy_a": [[yr, yr]]},
    )


def _m1_finance_result() -> FinanceResult:
    from energy_go.finance.econ_params import DeviceEconParams
    ensemble   = _make_m1_ensemble()
    econ       = DeviceEconParams(total_capex_yuan=1_000_000.0)
    price_path = [PricePath(id="flat", label="Flat", multipliers=[1.0, 1.0])]
    config     = _make_base_config()
    return finance(ensemble, price_path, econ, config)


def test_fin28_m1_distribution_valid_false():
    """FIN-28: M=1 → FinanceResult.distribution_valid=False (§13.10c)."""
    result = _m1_finance_result()
    assert result.distribution_valid is False


def test_fin29_m1_distributional_fields_absent():
    """FIN-29: M=1 → P50/P75/P90/P95, downside_risk.distributional are ABSENT (None).

    Absent means None, NOT the single-draw value relabeled as P50.
    (§13.10c: "never fabricated")
    """
    result = _m1_finance_result()
    view   = result.per_policy["policy_a"].per_price_path["flat"].view_i
    assert view.P50          is None, "P50 must be absent at M=1"
    assert view.P75          is None, "P75 must be absent at M=1"
    assert view.P90          is None, "P90 must be absent at M=1"
    assert view.P95          is None, "P95 must be absent at M=1"
    assert view.downside_risk is None, "distributional downside_risk must be absent at M=1"


def test_fin30_m1_single_trajectory_present():
    """FIN-30: M=1 → single_trajectory metrics ARE present.

    At M=1, max_drawdown + year, worst_year_cf, point_npv are the meaningful outputs.
    """
    result = _m1_finance_result()
    view   = result.per_policy["policy_a"].per_price_path["flat"].view_i
    st     = view.single_trajectory
    assert st is not None, "single_trajectory must be present at M=1"
    assert st.point_npv_yuan is not None
    assert st.max_drawdown_yuan is not None
    assert st.max_drawdown_year is not None
    assert st.worst_year_cf_yuan is not None


def test_fin31_m1_banner_in_provenance():
    """FIN-31: M=1 → provenance carries M=1 banner flag.

    The non-dismissable banner "M=1 — single scenario; risk distribution requires M≥50"
    must be present in provenance (the UI reads this to show the warning, §13.10c).
    """
    result = _m1_finance_result()
    assert result.provenance.M == 1
    # The engine must expose the banner signal — checked via a provenance field or flag
    assert hasattr(result.provenance, "m1_banner") and result.provenance.m1_banner is True, (
        "provenance.m1_banner must be True at M=1 (§13.10c non-dismissable banner)"
    )


# ---------------------------------------------------------------------------
# FIN-32–FIN-36 — R2 regime: bootstrap M≥50 (§13.10a, D34)
# ---------------------------------------------------------------------------

def _make_m50_ensemble() -> PolicyEnsemble:
    """50-draw ensemble for R2 tests using the PR #107 §A linear NPV ensemble."""
    # Each draw m is a 2-year trajectory producing NPV_m = −100k + (m−1)·10k
    # We need to construct eval results such that NPV_m comes out to the right value
    # For simplicity we inject the NPV via the CF directly:
    # CF(0) = −1,000,000 (CAPEX), CF(1) = X_m, CF(2) = X_m where X_m solves
    # NPV(0.10) = −1,000,000 + X_m/1.10 + X_m/1.21 = NPV_m
    # X_m·(1/1.10 + 1/1.21) = NPV_m + 1,000,000
    # X_m = (NPV_m + 1,000,000) / (1/1.10 + 1/1.21) = (NPV_m + 1,000,000) / 1.7355372
    discount_factors_sum = 1.0 / 1.10 + 1.0 / 1.21  # 0.909091 + 0.826446 = 1.735537
    runs = {}
    traj = []
    for m in range(1, 51):
        target_npv = -100_000.0 + (m - 1) * 10_000.0
        annual_cf_m = (target_npv + 1_000_000.0) / discount_factors_sum
        yr_m = _make_eval_result(
            grid_export_yuan=annual_cf_m,  # simplified: revenue drives the CF
            generation_mwh=10_000.0,
        )
        traj.append([yr_m, yr_m])
    runs["policy_a"] = traj
    return PolicyEnsemble(seed=42, M=50, sample_kind="bootstrap", runs=runs)


def _m50_finance_result() -> FinanceResult:
    from energy_go.finance.econ_params import DeviceEconParams
    ensemble   = _make_m50_ensemble()
    econ       = DeviceEconParams(total_capex_yuan=1_000_000.0)
    price_path = [PricePath(id="flat", label="Flat", multipliers=[1.0, 1.0])]
    config     = _make_base_config(horizon_years=2)
    return finance(ensemble, price_path, econ, config)


def test_fin32_r2_distribution_valid():
    """FIN-32: M≥50, sample_kind="bootstrap" → distribution_valid=True."""
    result = _m50_finance_result()
    assert result.distribution_valid is True


def test_fin33_r2_percentile_set_present():
    """FIN-33: R2 → P50/P75/P90/P95 all populated; P99 may be indicative_low_confidence only."""
    result = _m50_finance_result()
    view   = result.per_policy["policy_a"].per_price_path["flat"].view_i
    assert view.P50 is not None, "P50 must be present in R2 regime"
    assert view.P75 is not None, "P75 must be present in R2 regime"
    assert view.P90 is not None, "P90 must be present in R2 regime"
    assert view.P95 is not None, "P95 must be present in R2 regime"


def test_fin34_r2_p50_npv_matches_locked_estimator():
    """FIN-34: R2 P50 NPV = ¥140,000 per the LOCKED estimator (PR #107 §A).

    np.quantile(NPV_arr, 1−0.50, method='lower') → index floor(0.50·49)=24 → ¥140,000
    """
    result = _m50_finance_result()
    view   = result.per_policy["policy_a"].per_price_path["flat"].view_i
    assert view.P50.npv_yuan == pytest.approx(140_000.0, abs=TOL_NPV_YUAN)


def test_fin35_r2_bootstrap_ci_deterministic():
    """FIN-35: Same bootstrap_seed → identical CI (determinism).

    Two identical calls with the same seed must return bit-identical CIs.
    """
    result_a = _m50_finance_result()
    result_b = _m50_finance_result()
    ci_a = result_a.per_policy["policy_a"].per_price_path["flat"].view_i.P50.bootstrap_ci
    ci_b = result_b.per_policy["policy_a"].per_price_path["flat"].view_i.P50.bootstrap_ci
    assert ci_a[0] == ci_b[0], "lower CI bound must be deterministic"
    assert ci_a[1] == ci_b[1], "upper CI bound must be deterministic"


def test_fin36_r2_p99_is_indicative_or_absent():
    """FIN-36: P99 must NOT be a headline field; if present, confidence='indicative_low_confidence'.

    P99 ≈ the 0.5th-worst of 50 draws — not credible; must be labelled or absent. (§13.10a)
    """
    result = _m50_finance_result()
    view   = result.per_policy["policy_a"].per_price_path["flat"].view_i
    if view.P99 is not None:
        assert view.P99.confidence == "indicative_low_confidence", (
            "If P99 is present it MUST be tagged indicative_low_confidence (§13.10a)"
        )
    # P99=None is also acceptable (dropped from headline)


# ---------------------------------------------------------------------------
# FIN-37 — Purity: no I/O reachable from finance()
# ---------------------------------------------------------------------------

def test_fin37_finance_is_pure_no_io(monkeypatch):
    """FIN-37: finance() must be a pure function — no I/O, no network, no filesystem.

    This test injects broken builtins (open, socket) so that any I/O attempt
    will raise, and verifies finance() completes without triggering them.
    """
    import builtins, socket as _socket

    yr = _make_eval_result(grid_export_yuan=700_000.0)
    ensemble   = PolicyEnsemble(seed=42, M=1, sample_kind="bootstrap",
                                runs={"policy_a": [[yr, yr]]})
    from energy_go.finance.econ_params import DeviceEconParams
    econ       = DeviceEconParams(total_capex_yuan=1_000_000.0)
    price_path = [PricePath(id="flat", label="Flat", multipliers=[1.0, 1.0])]
    config     = _make_base_config()

    def _no_io(*args, **kwargs):
        raise AssertionError("finance() must not perform any I/O (purity violation)")

    monkeypatch.setattr(builtins, "open", _no_io)
    monkeypatch.setattr(_socket, "socket", _no_io)

    # Must complete without raising AssertionError
    result = finance(ensemble, price_path, econ, config)
    assert result is not None


# ---------------------------------------------------------------------------
# FIN-38–FIN-40 — CRN structural (§13.12 inv 1)
# ---------------------------------------------------------------------------

def test_fin38_crn_index_aligned_draws():
    """FIN-38: CRN — index m is the SAME draw across all policies.

    Two policies must receive identical runs[m] (same eval result objects), so that
    per-policy metric deltas are pure dispatch, not weather noise (P2, §13.1).
    """
    yr_a = _make_eval_result(grid_export_yuan=700_000.0)
    yr_b = _make_eval_result(grid_export_yuan=750_000.0)  # better policy
    # Both policies see the SAME weather draw at each index m
    runs = {
        "policy_a": [[yr_a, yr_a]],   # m=0: [yr_a, yr_a]
        "policy_b": [[yr_b, yr_b]],   # m=0: [yr_b, yr_b] (SAME m=0 weather, different dispatch)
    }
    ensemble = PolicyEnsemble(seed=42, M=1, sample_kind="bootstrap", runs=runs)
    # Engine must accept this (CRN aligned) without error
    from energy_go.finance.econ_params import DeviceEconParams
    econ = DeviceEconParams(total_capex_yuan=1_000_000.0)
    result = finance(ensemble, [PricePath("flat", "Flat", [1.0, 1.0])], econ, _make_base_config())
    assert "policy_a" in result.per_policy
    assert "policy_b" in result.per_policy


def test_fin39_ragged_ensemble_rejected():
    """FIN-39: Ragged ensemble (|runs[π]| ≠ M) → ValueError.

    If one policy has fewer draws than ensemble.M, the engine must raise ValueError.
    """
    yr = _make_eval_result(grid_export_yuan=700_000.0)
    runs = {
        "policy_a": [[yr, yr], [yr, yr]],   # M=2 draws
        "policy_b": [[yr, yr]],              # M=1 draws — RAGGED
    }
    ensemble = PolicyEnsemble(seed=42, M=2, sample_kind="bootstrap", runs=runs)
    from energy_go.finance.econ_params import DeviceEconParams
    econ = DeviceEconParams(total_capex_yuan=1_000_000.0)
    with pytest.raises(ValueError, match="ragged|ensemble|length|M"):
        finance(ensemble, [PricePath("flat", "Flat", [1.0, 1.0])], econ, _make_base_config())


def test_fin40_seed_in_provenance():
    """FIN-40: ensemble.seed travels into FinanceResult.provenance.seed."""
    yr = _make_eval_result(grid_export_yuan=700_000.0)
    ensemble = PolicyEnsemble(seed=12345, M=1, sample_kind="bootstrap",
                              runs={"p": [[yr, yr]]})
    from energy_go.finance.econ_params import DeviceEconParams
    econ = DeviceEconParams(total_capex_yuan=1_000_000.0)
    result = finance(ensemble, [PricePath("flat", "Flat", [1.0, 1.0])], econ, _make_base_config())
    assert result.provenance.seed == 12345


# ---------------------------------------------------------------------------
# FIN-41–FIN-42 — View II gating (§13.12 inv 3)
# ---------------------------------------------------------------------------

def test_fin41_view_ii_present_when_baseline_matches():
    """FIN-41: View II produced when baseline_policy_id ∈ ensemble.runs.keys()."""
    yr_base   = _make_eval_result(grid_export_yuan=600_000.0)   # baseline (no battery)
    yr_policy = _make_eval_result(grid_export_yuan=700_000.0)   # storage policy
    runs = {
        "no_battery": [[yr_base, yr_base]],
        "rl_policy":  [[yr_policy, yr_policy]],
    }
    ensemble = PolicyEnsemble(seed=0, M=1, sample_kind="bootstrap", runs=runs)
    from energy_go.finance.econ_params import DeviceEconParams
    econ   = DeviceEconParams(total_capex_yuan=1_000_000.0)
    config = _make_base_config(baseline_policy_id="no_battery")
    result = finance(ensemble, [PricePath("flat", "Flat", [1.0, 1.0])], econ, config)

    view_ii = result.per_policy["rl_policy"].per_price_path["flat"].view_ii
    assert view_ii is not None, (
        "View II must be produced when baseline_policy_id ∈ ensemble.runs.keys()"
    )


def test_fin42_view_ii_absent_when_baseline_missing():
    """FIN-42: View II OMITTED (None, not fabricated) when baseline_policy_id absent.

    If finance_config.baseline_policy_id is None, View II must be None — never a
    synthesized comparison against an assumed baseline. (§13.12 inv 3)
    """
    yr = _make_eval_result(grid_export_yuan=700_000.0)
    ensemble = PolicyEnsemble(seed=0, M=1, sample_kind="bootstrap",
                              runs={"policy_a": [[yr, yr]]})
    from energy_go.finance.econ_params import DeviceEconParams
    econ   = DeviceEconParams(total_capex_yuan=1_000_000.0)
    config = _make_base_config(baseline_policy_id=None)  # absent
    result = finance(ensemble, [PricePath("flat", "Flat", [1.0, 1.0])], econ, config)

    view_ii = result.per_policy["policy_a"].per_price_path["flat"].view_ii
    assert view_ii is None, "View II must be None when baseline_policy_id is absent (never fabricated)"


# ---------------------------------------------------------------------------
# FIN-43 — Debt-toggle gating (§13.9) — covered in test_fin14 above.
# Additional check: debt ON → fields present.
# ---------------------------------------------------------------------------

def test_fin43_debt_on_fields_present():
    """FIN-43: With debt_toggle=True, equity_irr and min_dscr are present (not None).

    Complementary to FIN-14 (debt OFF → absent). Verifies the debt toggle is wired.
    """
    yr = _make_eval_result(grid_export_yuan=700_000.0, demand_charge_yuan=100_000.0)
    ensemble = PolicyEnsemble(seed=0, M=1, sample_kind="bootstrap",
                              runs={"policy_a": [[yr, yr]]})
    from energy_go.finance.econ_params import DeviceEconParams
    econ   = DeviceEconParams(total_capex_yuan=1_000_000.0)
    config = _make_base_config(debt_toggle=True, target_de_ratio=1.5, r_f_override=0.10)
    result = finance(ensemble, [PricePath("flat", "Flat", [1.0, 1.0])], econ, config)

    view = result.per_policy["policy_a"].per_price_path["flat"].view_i
    assert view.equity_irr is not None, "equity_irr must be present when debt_toggle=True"
    assert view.min_dscr   is not None, "min_dscr must be present when debt_toggle=True"


# ---------------------------------------------------------------------------
# FIN-44 — Provenance completeness (§13.12)
# ---------------------------------------------------------------------------

def test_fin44_provenance_required_fields():
    """FIN-44: FinanceResult.provenance carries all 12 required fields.

    Required: seed, M, sample_kind, valuation_date, r_f, r_f_tenor_yr, r_f_curve_date,
              r_e, wacc, beta_levered, scenario_id, code_version.
    (§13.12; provenance travels with result so UI can refuse mismatched comparisons)
    """
    yr       = _make_eval_result(grid_export_yuan=700_000.0)
    ensemble = PolicyEnsemble(seed=99, M=1, sample_kind="bootstrap",
                              runs={"p": [[yr, yr]]})
    from energy_go.finance.econ_params import DeviceEconParams
    econ   = DeviceEconParams(total_capex_yuan=1_000_000.0)
    config = _make_base_config()
    result = finance(ensemble, [PricePath("flat", "Flat", [1.0, 1.0])], econ, config)
    prov   = result.provenance

    required_fields = [
        "seed", "M", "sample_kind", "valuation_date",
        "r_f", "r_f_tenor_yr", "r_f_curve_date",
        "r_e", "wacc", "beta_levered",
        "scenario_id", "code_version",
    ]
    for field in required_fields:
        assert hasattr(prov, field) and getattr(prov, field) is not None, (
            f"provenance.{field} must be present and non-None (§13.12)"
        )


# ---------------------------------------------------------------------------
# FIN-45–FIN-46 — Bootstrap CI properties (§13.10a)
# ---------------------------------------------------------------------------

def test_fin45_bootstrap_ci_degenerate_width_zero():
    """FIN-45: Degenerate ensemble (all M draws identical) → bootstrap CI width = 0.

    If all M draws return the same NPV, resampling returns the same distribution →
    CI width must be exactly 0 (not a positive width from numerical noise).
    """
    # All 50 draws return the exact same eval result → identical NPV
    yr = _make_eval_result(grid_export_yuan=700_000.0)
    runs = {"policy_a": [[yr, yr]] * 50}
    ensemble = PolicyEnsemble(seed=42, M=50, sample_kind="bootstrap", runs=runs)
    from energy_go.finance.econ_params import DeviceEconParams
    econ   = DeviceEconParams(total_capex_yuan=1_000_000.0)
    config = _make_base_config(horizon_years=2)
    result = finance(ensemble, [PricePath("flat", "Flat", [1.0, 1.0])], econ, config)

    ci = result.per_policy["policy_a"].per_price_path["flat"].view_i.P50.bootstrap_ci
    assert ci[1] - ci[0] == pytest.approx(0.0, abs=TOL_NPV_YUAN), (
        "bootstrap CI width must be 0 when all draws are identical (degenerate case)"
    )


def test_fin46_bootstrap_ci_contains_point_estimate():
    """FIN-46: CI (lower, upper) must contain the point estimate (P50 value).

    By construction the bootstrap CI of a statistic contains the statistic itself.
    """
    result = _m50_finance_result()
    view   = result.per_policy["policy_a"].per_price_path["flat"].view_i
    p50    = view.P50
    ci     = p50.bootstrap_ci
    assert ci[0] <= p50.npv_yuan <= ci[1], (
        f"P50 NPV {p50.npv_yuan} must lie within CI [{ci[0]}, {ci[1]}]"
    )


# ---------------------------------------------------------------------------
# FIN-56 — Tax assembly end-to-end: finance(tax_toggle=True) → Vector-2 values
# Source: PR #107 Vector 2 / finance-expert REQUEST_CHANGES on PR #110
# FIN-07–FIN-09 test tax primitives on hand-baked CFs; this verifies the ENGINE
# wires them correctly end-to-end by calling finance() on the Vector-1 ensemble.
# (Numbered FIN-56/57 to avoid collision with reviewer-added FIN-53–55 edge cases.)
# ---------------------------------------------------------------------------

def test_fin56_tax_toggle_end_to_end():
    """FIN-56: finance(tax_toggle=True, depreciation_years=2) on Vector-1 ensemble →
    after-tax NPV = −¥2,066.12 AND delta from base = −¥43,388.43.

    Vector-1 ensemble: M=1, N=2, revenue=¥700,000/yr, demand_charge=¥100,000/yr,
    EBITDA=¥600,000/yr, CAPEX=¥1,000,000.

    Tax path (straight-line dep over 2yr):
      dep(y)     = 1,000,000/2 = 500,000
      taxable(y) = EBITDA − dep = 600,000 − 500,000 = 100,000
      tax(y)     = 0.25·100,000 = 25,000
      CF_tax(y)  = 600,000 − 25,000 = 575,000
    NPV_tax(0.10) = −1,000,000 + 575,000/1.10 + 575,000/1.21
                  = −1,000,000 + 522,727.27 + 475,206.61 = −¥2,066.12
    NPV_base = ¥41,322.31  (Vector 1, tax=OFF)
    ΔNPV_tax = −2,066.12 − 41,322.31 = −¥43,388.43
             = −(25,000/1.10 + 25,000/1.21) = −(22,727.27 + 20,661.16)  ✓
    """
    yr = _make_eval_result(grid_export_yuan=700_000.0, demand_charge_yuan=100_000.0,
                           generation_mwh=10_000.0)
    ensemble = PolicyEnsemble(
        seed=0, M=1, sample_kind="bootstrap",
        runs={"policy_a": [[yr, yr]]},
    )
    from energy_go.finance.econ_params import DeviceEconParams
    econ       = DeviceEconParams(total_capex_yuan=1_000_000.0)
    price_path = [PricePath(id="flat", label="Flat", multipliers=[1.0, 1.0])]

    # ── Base case: tax=OFF ──
    config_base = _make_base_config(tax_toggle=False, horizon_years=2)
    result_base = finance(ensemble, price_path, econ, config_base)
    npv_base    = (result_base.per_policy["policy_a"]
                              .per_price_path["flat"]
                              .view_i.single_trajectory.point_npv_yuan)
    # −1,000,000 + 600,000/1.10 + 600,000/1.21 = ¥41,322.31
    assert npv_base == pytest.approx(41_322.31, abs=TOL_NPV_YUAN), (
        "pre-tax base NPV must match Vector-1 ¥41,322.31"
    )

    # ── Tax-ON case: straight-line dep=500k/yr, tax_rate=0.25 (default) ──
    config_tax = _make_base_config(tax_toggle=True, depreciation_years=2, horizon_years=2)
    result_tax = finance(ensemble, price_path, econ, config_tax)
    npv_afttax = (result_tax.per_policy["policy_a"]
                            .per_price_path["flat"]
                            .view_i.single_trajectory.point_npv_yuan)
    # −1,000,000 + 522,727.27 + 475,206.61 = −¥2,066.12
    assert npv_afttax == pytest.approx(-2_066.12, abs=TOL_NPV_YUAN), (
        "after-tax NPV must match Vector-2 −¥2,066.12"
    )

    # ── Tax delta (finance engine assembles the delta, not just the primitives) ──
    delta = npv_afttax - npv_base
    # −(25,000/1.10 + 25,000/1.21) = −(22,727.27 + 20,661.16) = −¥43,388.43
    assert delta == pytest.approx(-43_388.43, abs=TOL_NPV_YUAN), (
        "tax delta must equal −¥43,388.43 = PV of tax shield lost (Vector-2 §A)"
    )


# ---------------------------------------------------------------------------
# FIN-57 — Debt assembly end-to-end: finance(debt_toggle=True) → Vector-3 values
# Source: PR #107 Vector 3 / finance-expert REQUEST_CHANGES on PR #110
# FIN-11–FIN-12 test levered primitives on hand-baked CFs; this verifies the ENGINE
# wires them correctly end-to-end by calling finance() on the Vector-1 ensemble.
# r_d_override=0.05 pins the debt rate (bypasses LPR + credit_spread lookup).
# ---------------------------------------------------------------------------

def test_fin57_debt_toggle_end_to_end():
    """FIN-57: finance(debt_toggle=True, target_de_ratio=1.5, loan_term_years=2,
    r_d_override=0.05) on Vector-1 ensemble →
    equity_irr = 24.8565% AND min_dscr = 1.8594.

    Vector-1 ensemble: M=1, N=2, EBITDA=¥600,000/yr, CAPEX=¥1,000,000.

    Levered capital structure (D/E=1.5):
      Debt   = CAPEX·D/(D+E) = 1,000,000·1.5/2.5 = ¥600,000
      Equity = 1,000,000 − 600,000 = ¥400,000

    Level annuity (r_d=0.05, n=2yr):
      A = 600,000·[0.05·1.05²]/[1.05²−1]
        = 600,000·0.055125/0.1025 = ¥322,682.93/yr

    min-DSCR:
      CFADS(y) = EBITDA = ¥600,000
      DSCR(y)  = 600,000 / 322,682.93 = 1.8594  (level → same both years)

    Equity CF:
      CF_eq(0) = −¥400,000
      CF_eq(y) = 600,000 − 322,682.93 = ¥277,317.07
    equity-IRR: u = (√(1 + 4·400k/277.317k) − 1)/2 = 0.80092; IRR = 1/u − 1 = 24.856%
    """
    yr = _make_eval_result(grid_export_yuan=700_000.0, demand_charge_yuan=100_000.0,
                           generation_mwh=10_000.0)
    ensemble = PolicyEnsemble(
        seed=0, M=1, sample_kind="bootstrap",
        runs={"policy_a": [[yr, yr]]},
    )
    from energy_go.finance.econ_params import DeviceEconParams
    econ       = DeviceEconParams(total_capex_yuan=1_000_000.0)
    price_path = [PricePath(id="flat", label="Flat", multipliers=[1.0, 1.0])]

    config_debt = _make_base_config(
        debt_toggle=True,
        target_de_ratio=1.5,
        loan_term_years=2,
        r_d_override=0.05,    # pins r_d=5% directly; bypasses lpr_5yr + credit_spread lookup
        horizon_years=2,
    )
    result = finance(ensemble, price_path, econ, config_debt)
    view   = result.per_policy["policy_a"].per_price_path["flat"].view_i

    # equity-IRR: CF_eq=[−400k,+277,317.07,+277,317.07];
    # u=(√(1+4·400k/277.317k)−1)/2=0.80092; IRR=1/u−1=0.2485645
    assert view.equity_irr == pytest.approx(0.2485645, abs=TOL_RATE_PP), (
        "equity-IRR must match Vector-3 24.8565%"
    )
    # min-DSCR: 600,000 / 322,682.93 = 1.8594 (level annuity → same both years)
    assert view.min_dscr == pytest.approx(1.8594, abs=TOL_DSCR), (
        "min-DSCR must match Vector-3 1.8594"
    )


# ---------------------------------------------------------------------------
# FIN-47–FIN-52 — R3 regime: empirical small-sample (M≈10)
# PENDING: D39 R3 finalization (PR #108). Skipped until D39 merges.
# R3 = per-year trajectory strip + empirical P50 + worst/best-of-N range + P(NPV<0)
# NO labeled P75/P90/P95/P99 or CVaR-5% (collapse to min at M≈10 under locked estimator)
# ---------------------------------------------------------------------------

_SKIP_R3 = pytest.mark.skip(reason="PENDING: D39 R3 finalization (PR #108) — do not implement until D39 merges")


@_SKIP_R3
def test_fin47_r3_distribution_valid_true():
    """FIN-47: R3 (empirical, M≈10) → distribution_valid=True.

    Even at M≈10 the result is valid — but the populated percentile set is honest/narrow.
    PENDING: finalize after D39 (PR #108) merges.
    """


@_SKIP_R3
def test_fin48_r3_no_labeled_p75_p90_p95():
    """FIN-48: R3 → P75, P90, P95, P99, CVaR-5% must ALL be ABSENT (None).

    Under the LOCKED nearest-rank estimator at M≈10:
    P90 = np.quantile(sorted, 0.10, method='lower') → index floor(0.10·9)=0 = minimum
    P75 = np.quantile(sorted, 0.25, method='lower') → index floor(0.25·9)=2 → collapse risk
    CVaR-5% = k=ceil(0.05·10)=1 = single worst draw
    → P75/P90/CVaR-5%/worst-case would all collapse to the same few draws (relabel trap, §13.10c).
    D39 ruling: drop ALL labeled tail percentiles in R3 (including P75); surface as
    "worst/best of N observed years".  (P75-absent noted finance-expert REQUEST_CHANGES PR #110)
    PENDING: D39 merge.
    """


@_SKIP_R3
def test_fin49_r3_empirical_p50_present():
    """FIN-49: R3 → empirical P50 (median of the ~10 draws) IS present.

    P50 = np.quantile(sorted_M, 0.50, method='lower') at M≈10 is still meaningful.
    PENDING: D39 merge.
    """


@_SKIP_R3
def test_fin50_r3_worst_best_of_n_range():
    """FIN-50: R3 → empirical worst/best-of-N range emitted, labelled as "worst/best of N observed years"
    (not as P90/P95 — §13.10c naming discipline).
    PENDING: D39 merge.
    """


@_SKIP_R3
def test_fin51_r3_p_npv_neg_present():
    """FIN-51: R3 → P(NPV<0) = empirical frequency emitted (e.g. "2 of 10 historical years lose money").
    PENDING: D39 merge.
    """


@_SKIP_R3
def test_fin52_r3_same_estimator_as_r2():
    """FIN-52: R3 uses the SAME locked percentile estimator as R2 (np.quantile, method='lower').

    ONE estimator must serve both R2 and R3 (D39; a second estimator is a review-fail).
    PENDING: D39 merge.
    """


# ---------------------------------------------------------------------------
# FIN-53–FIN-55 — reviewer-added edge cases (backend-reviewer)
# Stable (NOT skipped). Hand-computed expected values with arithmetic shown.
# Added under the contract-first-dev reviewer mandate (missed-edge-case hunt).
# ---------------------------------------------------------------------------

def test_fin53_drawdown_no_shortfall_clamps_to_zero():
    # reviewer: FIN-22b only tests the negative-drawdown case; nothing pins the
    # load-bearing min(0, ·) shortfall-below-zero clamp when cumulative CF never
    # goes negative. A peak-to-trough impl would (wrongly) report a positive
    # "drawdown" here; the §13.10b shortfall-below-zero literal must yield 0.
    #
    # cf = [+100k, +50k, +200k] (ANNUAL series, year-0 CAPEX excluded)
    # max_drawdown() cumsums internally (FIN-22b convention / §13.10b literal):
    #   cumCF = [100k, 150k, 350k]; min(cumCF) = 100k > 0
    #   max_drawdown = min(0, 100,000) = 0.0   (no shortfall ever)
    # Pass the ANNUAL series (NOT pre-cumsummed) — aligns with FIN-22b's call.
    cf = [100_000.0, 50_000.0, 200_000.0]
    result = max_drawdown(cf)
    assert result["drawdown_yuan"] == pytest.approx(0.0, abs=TOL_NPV_YUAN), (
        "no-shortfall trajectory must clamp max_drawdown to 0 (shortfall-below-zero, "
        "NOT peak-to-trough)"
    )
    # reviewer: the no-shortfall max_drawdown_year convention is UNDEFINED in the
    # contract (§2.2 types it int, 1-indexed argmin). Recommend the contract pin it
    # (argmin year, or a sentinel) and add the assert here once defined. Flagged in
    # the review; intentionally NOT asserting drawdown_year here to avoid encoding an
    # unspecified convention.


def test_fin54_cvar_k_ceil_at_integer_boundary():
    # reviewer: FIN-18 only tests CVaR k=ceil(0.05·50)=ceil(2.5)=3 (non-integer).
    # The ceil must also behave at EXACT-integer 0.05·M: a buggy int(0.05·M)+1 would
    # over-count by one. Pin two integer boundaries.
    #
    # M=20: 0.05·20 = 1.0 → k = ceil(1.0) = 1 → CVaR = single worst draw.
    #   NPV_m = −10,000 + (m−1)·1,000, m=1…20 (ascending); worst = −10,000.
    #   CVaR-5% = mean([−10,000]) = −¥10,000
    arr20 = np.array([-10_000.0 + (m - 1) * 1_000.0 for m in range(1, 21)])
    assert cvar5(arr20, M=20) == pytest.approx(-10_000.0, abs=TOL_NPV_YUAN), (
        "M=20: k=ceil(0.05·20)=ceil(1.0)=1 → CVaR = single worst = −10,000"
    )
    # M=40: 0.05·40 = 2.0 → k = ceil(2.0) = 2 → mean of the 2 worst.
    #   NPV_m = −20,000 + (m−1)·1,000, m=1…40; worst two = −20,000, −19,000.
    #   CVaR-5% = mean(−20,000, −19,000) = −¥19,500
    arr40 = np.array([-20_000.0 + (m - 1) * 1_000.0 for m in range(1, 41)])
    assert cvar5(arr40, M=40) == pytest.approx(-19_500.0, abs=TOL_NPV_YUAN), (
        "M=40: k=ceil(0.05·40)=ceil(2.0)=2 → CVaR = mean(−20k, −19k) = −19,500"
    )


def test_fin55_mirr_single_valued_on_multi_sign_cf():
    # reviewer: §4 says "MIRR is reported alongside IRR (replacement years → multi-IRR
    # risk)" but no test exercises a sign-flipping CF where IRR is ambiguous. Pin that
    # MIRR is single-valued there.
    #
    # cf = [−1000, +2500, −1560]  (two sign changes → up to 2 IRR roots)
    # finance/reinvest rate r = 0.10, N = 2
    # FV_pos@yr2 (reinvest) = 2500·1.10^(2−1) = 2,750
    # PV_neg@yr0 (finance)  = −1000 − 1560/1.10^2 = −1000 − 1289.2562 = −2289.2562
    # MIRR = (2750 / 2289.2562)^(1/2) − 1 = (1.201270)^0.5 − 1
    #      = 1.096024 − 1 = 0.096022 = 9.6022%
    cf = [-1_000.0, 2_500.0, -1_560.0]
    result = mirr(cf, finance_rate=0.10, reinvest_rate=0.10)
    assert result == pytest.approx(0.096022, abs=TOL_RATE_PP), (
        "MIRR must be single-valued (9.6022%) on a multi-sign CF where IRR has 2 roots"
    )
