"""
Physics invariant helpers for Energy GO.

All helpers raise ``AssertionError`` with a diagnostic message on failure.
They are deliberately *framework-agnostic*: they access result fields by
attribute name (duck typing) so they work identically with the NumPy reference
implementation's ``StepResult`` dataclass and the future JAX implementation's
NamedTuple — as long as the field names match the locked telemetry schema.

Contract reference:  contracts/env/reference_implementation.md
Decisions in scope:  D3 (Δt=1h), D4 (SOC 0.2–0.9), D5 (export 945 MW),
                     D7 (spread clamp), D10 (demand charge once/month),
                     D12 (import 400 MW Gansu), D13 (cost accounting split)

Typical tolerance guidance
--------------------------
Power-flow assertions (float64 NumPy reference):   tol = 1e-5
Power-flow assertions (float32 JAX):               tol = 1e-4
Cost-identity assertions (algebraic, no approx):   tol = 1e-9
"""

from __future__ import annotations

from typing import Any, Callable


# ---------------------------------------------------------------------------
# 1. Per-source energy conservation (§3.6 row 14)
# ---------------------------------------------------------------------------

def assert_energy_conserved(result: Any, *, tol: float = 1e-5) -> None:
    """
    Assert per-source power balance for one env step.

    Wind conservation:  wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed
                        == p_wind_mw
    Solar conservation: solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed
                        == p_solar_mw
    Battery discharge:  bat_to_load + bat_to_grid + bat_curtailed
                        == p_bat_discharge_mw
    Grid import decomp: grid_to_load + grid_to_bat == p_import_mw

    Parameters
    ----------
    result:
        A step result object with the fields listed in
        contracts/env/reference_implementation.md ``StepResult``.
    tol:
        Relative tolerance for the equality checks.
        Use 1e-5 for float64 (NumPy reference), 1e-4 for float32 (JAX).
    """
    # --- wind ---
    wind_sum = (_f(result, "wind_to_load_mw") + _f(result, "wind_to_bat_mw")
                + _f(result, "wind_to_grid_mw") + _f(result, "wind_curtailed_mw"))
    p_wind = _f(result, "p_wind_mw")
    _assert_approx(wind_sum, p_wind, tol,
                   f"Wind conservation: {wind_sum:.6f} ≠ p_wind_mw={p_wind:.6f}")

    # --- solar ---
    solar_sum = (_f(result, "solar_to_load_mw") + _f(result, "solar_to_bat_mw")
                 + _f(result, "solar_to_grid_mw") + _f(result, "solar_curtailed_mw"))
    p_solar = _f(result, "p_solar_mw")
    _assert_approx(solar_sum, p_solar, tol,
                   f"Solar conservation: {solar_sum:.6f} ≠ p_solar_mw={p_solar:.6f}")

    # --- battery discharge ---
    bat_dis_sum = (_f(result, "bat_to_load_mw") + _f(result, "bat_to_grid_mw")
                   + _f(result, "bat_curtailed_mw"))
    p_bat_dis = _f(result, "p_bat_discharge_mw")
    _assert_approx(bat_dis_sum, p_bat_dis, tol,
                   f"Battery discharge conservation: {bat_dis_sum:.6f} ≠ "
                   f"p_bat_discharge_mw={p_bat_dis:.6f}")

    # --- grid import decomposition ---
    grid_sum = _f(result, "grid_to_load_mw") + _f(result, "grid_to_bat_mw")
    p_import = _f(result, "p_import_mw")
    _assert_approx(grid_sum, p_import, tol,
                   f"Grid import decomp: grid_to_load+grid_to_bat={grid_sum:.6f} ≠ "
                   f"p_import_mw={p_import:.6f}")

    # --- non-negativity of all flows ---
    flow_fields = [
        "p_wind_mw", "p_solar_mw",
        "wind_to_load_mw", "wind_to_bat_mw", "wind_to_grid_mw", "wind_curtailed_mw",
        "solar_to_load_mw", "solar_to_bat_mw", "solar_to_grid_mw", "solar_curtailed_mw",
        "bat_to_load_mw", "bat_to_grid_mw", "bat_curtailed_mw",
        "grid_to_load_mw", "grid_to_bat_mw",
        "p_bat_charge_mw", "p_bat_discharge_mw",
        "p_import_mw", "p_export_mw",
        "load_unserved_mw", "soc_violation_mwh",
    ]
    for field in flow_fields:
        val = _f(result, field)
        assert val >= -1e-9, (
            f"assert_energy_conserved: {field} = {val:.6f} is negative (floor −1e-9)")


# ---------------------------------------------------------------------------
# 2. D13 cost accounting identities
# ---------------------------------------------------------------------------

def assert_cost_identities(result: Any, params: Any, *, tol: float = 1e-9,
                            check_formulas: bool = False) -> None:
    """
    Assert all D13 cost-accounting algebraic identities for one step.

    Identities checked (always)
    ---------------------------
    1.  c_energy == c_import − r_export
    2.  cost_total_reward_basis ==
            c_energy + 2·c_demand_shape + c_degradation + c_curtail + c_voll
    3.  cost_total_real ==
            c_energy + c_demand_charge + c_degradation + c_curtail + c_voll
    4.  reward == −(cost_total_reward_basis + penalty) × reward_scale
    5.  penalty == 20 000 × soc_violation_mwh   (§3.5 formula — GAP 1 confirmed ✓)
    6.  c_curtail == (solar_curtailed + wind_curtailed + bat_curtailed)
                     × curtail_penalty × Δt                (GAP 6 rate check ✓)
    7.  c_voll == load_unserved × voll × Δt                (GAP 6 rate check ✓)
    8.  r_export ≥ 0  (D7: price_sell ≥ 0 → no negative revenue)
    9.  c_degradation == c_deg_rate × (p_ch + p_dis) × Δt  (GAP 6 rate check ✓)

    Additional formula checks (only when check_formulas=True, GAP 6)
    ----------------------------------------------------------------
    10. c_import == price_buy × p_import × Δt
    11. r_export == price_sell × p_export × Δt

    Parameters
    ----------
    result:
        Step result with all fields from ``StepResult``, including
        ``price_buy_yuan_per_mwh`` and ``price_sell_yuan_per_mwh``.
    params:
        Parameter object providing: ``reward_scale``, ``c_deg_yuan_per_mwh``,
        ``voll_yuan_per_mwh``, ``curtail_penalty_yuan_per_mwh``.
    tol:
        Relative tolerance.  Default 1e-9 (algebraic identity, float64).
        Use 1e-6 for float32 JAX outputs.
    check_formulas:
        If True, also verify c_import and r_export against their rate formulas
        (identities 10–11).  Requires ``price_buy_yuan_per_mwh`` and
        ``price_sell_yuan_per_mwh`` in result.  Default False for callers
        that only want algebraic-total verification.
    """
    dt = 1.0  # Δt = 1 h (D3)
    r_scale = _p(params, "reward_scale")
    voll = _p(params, "voll_yuan_per_mwh")
    c_deg_rate = _p(params, "c_deg_yuan_per_mwh")
    curtail_rate = _p(params, "curtail_penalty_yuan_per_mwh")

    c_import     = _f(result, "c_import_yuan")
    r_export     = _f(result, "r_export_yuan")
    c_energy     = _f(result, "c_energy_yuan")
    c_ds         = _f(result, "c_demand_shape_yuan")     # RAW (no ×2 pre-applied, D13)
    c_dc         = _f(result, "c_demand_charge_yuan")    # month-boundary charge
    c_deg        = _f(result, "c_degradation_yuan")
    c_curtail    = _f(result, "c_curtail_yuan")
    c_voll       = _f(result, "c_voll_yuan")
    penalty      = _f(result, "penalty_yuan")
    soc_viol     = _f(result, "soc_violation_mwh")
    reward       = _f(result, "reward")
    cost_rb      = _f(result, "cost_total_reward_basis_yuan")
    cost_real    = _f(result, "cost_total_real_yuan")
    p_ch         = _f(result, "p_bat_charge_mw")
    p_dis        = _f(result, "p_bat_discharge_mw")
    solar_curt   = _f(result, "solar_curtailed_mw")
    wind_curt    = _f(result, "wind_curtailed_mw")
    bat_curt     = _f(result, "bat_curtailed_mw")
    load_unsv    = _f(result, "load_unserved_mw")

    # 1. c_energy = c_import − r_export
    _assert_approx(c_energy, c_import - r_export, tol,
                   f"Identity 1 (c_energy): {c_energy:.4f} ≠ c_import−r_export="
                   f"{c_import - r_export:.4f}")

    # 2. cost_total_reward_basis reconstruction
    rb_expected = c_energy + 2.0 * c_ds + c_deg + c_curtail + c_voll
    _assert_approx(cost_rb, rb_expected, tol,
                   f"Identity 2 (cost_total_reward_basis): {cost_rb:.4f} ≠ "
                   f"C_E+2·C_DS+C_deg+C_curtail+C_VOLL={rb_expected:.4f}  "
                   f"[c_ds={c_ds:.2f} stored RAW per D13]")

    # 3. cost_total_real reconstruction
    real_expected = c_energy + c_dc + c_deg + c_curtail + c_voll
    _assert_approx(cost_real, real_expected, tol,
                   f"Identity 3 (cost_total_real): {cost_real:.4f} ≠ "
                   f"C_E+C_DC+C_deg+C_curtail+C_VOLL={real_expected:.4f}")

    # 4. reward formula (D13)
    reward_expected = -(cost_rb + penalty) * r_scale
    _assert_approx(reward, reward_expected, tol,
                   f"Identity 4 (reward): {reward:.8f} ≠ "
                   f"−(cost_rb+penalty)×scale={reward_expected:.8f}")

    # 5. penalty = 20_000 × soc_violation_mwh
    penalty_expected = 20_000.0 * soc_viol
    _assert_approx(penalty, penalty_expected, tol,
                   f"Identity 5 (penalty): {penalty:.4f} ≠ 20000×soc_viol={penalty_expected:.4f}")

    # 6. c_curtail = total_curtailed × rate × dt
    total_curt = solar_curt + wind_curt + bat_curt
    c_curtail_expected = total_curt * curtail_rate * dt
    _assert_approx(c_curtail, c_curtail_expected, tol,
                   f"Identity 6 (c_curtail): {c_curtail:.4f} ≠ "
                   f"curtailed×rate×dt={c_curtail_expected:.4f}")

    # 7. c_voll = load_unserved × voll × dt
    c_voll_expected = load_unsv * voll * dt
    _assert_approx(c_voll, c_voll_expected, tol,
                   f"Identity 7 (c_voll): {c_voll:.4f} ≠ "
                   f"unserved×voll×dt={c_voll_expected:.4f}")

    # 8. r_export ≥ 0 (D7: sell price is clamped ≥ 0)
    assert r_export >= -1e-9, (
        f"assert_cost_identities: r_export = {r_export:.6f} is negative "
        "(D7 sell-price clamp violated)")

    # 9. c_degradation = c_deg_rate × (p_ch + p_dis) × dt  (GAP 6 ✓)
    c_deg_expected = c_deg_rate * (p_ch + p_dis) * dt
    _assert_approx(c_deg, c_deg_expected, tol,
                   f"Identity 9 (c_degradation): {c_deg:.4f} ≠ "
                   f"rate×(ch+dis)×dt={c_deg_expected:.4f}")

    # 10–11. Formula-level rate checks (opt-in, GAP 6)
    if check_formulas:
        p_import  = float(_f(result, "p_import_mw"))
        p_export  = float(_f(result, "p_export_mw"))
        price_buy  = float(_f(result, "price_buy_yuan_per_mwh"))
        price_sell = float(_f(result, "price_sell_yuan_per_mwh"))

        # 10. c_import = price_buy × p_import × Δt
        c_import_expected = price_buy * p_import * dt
        _assert_approx(c_import, c_import_expected, tol,
                       f"Identity 10 (c_import formula): {c_import:.4f} ≠ "
                       f"price_buy×p_import×dt={c_import_expected:.4f}")

        # 11. r_export = price_sell × p_export × Δt
        r_export_expected = price_sell * p_export * dt
        _assert_approx(r_export, r_export_expected, tol,
                       f"Identity 11 (r_export formula): {r_export:.4f} ≠ "
                       f"price_sell×p_export×dt={r_export_expected:.4f}")


# ---------------------------------------------------------------------------
# 3. Physical bounds (D4, D5, D12)
# ---------------------------------------------------------------------------

def assert_physical_bounds(result: Any, params: Any) -> None:
    """
    Assert all hard physical limits are respected.

    Checks
    ------
    SOC:
      - new_state.soc ∈ [soc_min, soc_max] = [0.2, 0.9]  (D4)
    Battery:
      - p_bat_charge_mw ≥ 0 and ≤ bat_power_mw
      - p_bat_discharge_mw ≥ 0 and ≤ bat_power_mw
      - charge XOR discharge (both cannot be > 0 simultaneously)
    PCC:
      - p_export_mw ≤ grid_max_export_mw  (D5: 945 MW Gansu)
      - p_import_mw ≤ grid_max_import_mw  (D12: 400 MW Gansu)
    Costs:
      - soc_violation_mwh ≥ 0
      - load_unserved_mw ≥ 0
      - penalty_yuan ≥ 0
    """
    soc_min = _p(params, "soc_min")
    soc_max = _p(params, "soc_max")
    bat_pmax = _p(params, "bat_power_mw")
    max_export = _p(params, "grid_max_export_mw")
    max_import = _p(params, "grid_max_import_mw")

    soc = _f(_f(result, "new_state"), "soc")
    p_ch = _f(result, "p_bat_charge_mw")
    p_dis = _f(result, "p_bat_discharge_mw")
    p_export = _f(result, "p_export_mw")
    p_import = _f(result, "p_import_mw")
    soc_viol = _f(result, "soc_violation_mwh")
    load_unsv = _f(result, "load_unserved_mw")
    penalty = _f(result, "penalty_yuan")

    # SOC bounds (D4)
    assert soc >= soc_min - 1e-9, (
        f"assert_physical_bounds: SOC {soc:.6f} < soc_min={soc_min} (D4)")
    assert soc <= soc_max + 1e-9, (
        f"assert_physical_bounds: SOC {soc:.6f} > soc_max={soc_max} (D4)")

    # Battery power limits
    assert p_ch >= -1e-9, (
        f"assert_physical_bounds: p_bat_charge_mw = {p_ch:.6f} is negative")
    assert p_ch <= bat_pmax + 1e-6, (
        f"assert_physical_bounds: p_bat_charge_mw={p_ch:.2f} > bat_power_mw={bat_pmax}")
    assert p_dis >= -1e-9, (
        f"assert_physical_bounds: p_bat_discharge_mw = {p_dis:.6f} is negative")
    assert p_dis <= bat_pmax + 1e-6, (
        f"assert_physical_bounds: p_bat_discharge_mw={p_dis:.2f} > bat_power_mw={bat_pmax}")

    # Charge XOR discharge (§3.6 row 4)
    assert not (p_ch > 1e-9 and p_dis > 1e-9), (
        f"assert_physical_bounds: simultaneous charge={p_ch:.4f} MW and "
        f"discharge={p_dis:.4f} MW (XOR constraint violated)")

    # PCC limits
    assert p_export <= max_export + 1e-6, (
        f"assert_physical_bounds: p_export_mw={p_export:.2f} > "
        f"grid_max_export_mw={max_export} (D5)")
    assert p_import <= max_import + 1e-6, (
        f"assert_physical_bounds: p_import_mw={p_import:.2f} > "
        f"grid_max_import_mw={max_import} (D12)")
    assert p_export >= -1e-9, (
        f"assert_physical_bounds: p_export_mw = {p_export:.6f} is negative")
    assert p_import >= -1e-9, (
        f"assert_physical_bounds: p_import_mw = {p_import:.6f} is negative")

    # Non-negative scalar invariants
    assert soc_viol >= -1e-9, (
        f"assert_physical_bounds: soc_violation_mwh = {soc_viol:.6f} is negative")
    assert load_unsv >= -1e-9, (
        f"assert_physical_bounds: load_unserved_mw = {load_unsv:.6f} is negative")
    assert penalty >= -1e-9, (
        f"assert_physical_bounds: penalty_yuan = {penalty:.6f} is negative")

    # D7 sell-price explicit checks (GAP 3): both clamps must hold
    #   price_sell = max(0, price_buy − max(0, spread + noise))
    price_sell = float(_f(result, "price_sell_yuan_per_mwh"))
    price_buy  = float(_f(result, "price_buy_yuan_per_mwh"))
    assert price_sell >= -1e-9, (
        f"assert_physical_bounds: price_sell={price_sell:.4f} < 0 "
        "(D7 outer-clamp violated)")
    assert price_sell <= price_buy + 1e-9, (
        f"assert_physical_bounds: price_sell={price_sell:.4f} > price_buy={price_buy:.4f} "
        "(D7 spread must be ≥ 0, sell ≤ buy)")


# ---------------------------------------------------------------------------
# 4. Demand-charge timing (D10) — GAP 2
# ---------------------------------------------------------------------------

def assert_demand_charge_timing(
    result: Any,
    *,
    is_month_boundary: bool,
    prev_month_peak_mw: float,
    params: Any,
    tol: float = 1e-9,
) -> None:
    """
    Assert D10 demand-charge booking is correct for one step.

    Contract rules (D10, §6 fix):
    - On any step that is NOT a month boundary: ``c_demand_charge_yuan == 0``
    - On a month-boundary (or terminal) step: ``c_demand_charge_yuan == prev_month_peak_mw × demand_rate``
    - No double-count: the booking happens ONCE even if the step is both the
      last step of a month AND the last step of the episode.

    Parameters
    ----------
    result:
        Step result containing ``c_demand_charge_yuan``.
    is_month_boundary:
        True if this step is the last step of a calendar month (or the last
        step of the episode for the terminal flush).
    prev_month_peak_mw:
        The ``month_peak_mw`` of the *state going into this step*, i.e. the
        peak that gets charged at a boundary.  Pass ``state.month_peak_mw``
        BEFORE calling ``env_step``.
    params:
        GansuParams providing ``demand_rate_yuan_per_mw_month``.
    tol:
        Relative tolerance.  Default 1e-9 (algebraic identity).
    """
    demand_rate = _p(params, "demand_rate_yuan_per_mw_month")
    c_dc = float(_f(result, "c_demand_charge_yuan"))

    if not is_month_boundary:
        # Mid-month: no demand charge booked (D10)
        assert abs(c_dc) <= 1e-9, (
            f"assert_demand_charge_timing: c_demand_charge_yuan={c_dc:.4f} on "
            f"non-boundary step (D10: must be 0 mid-month)")
    else:
        # Month boundary: book previous month's peak × rate
        expected = prev_month_peak_mw * demand_rate
        _assert_approx(c_dc, expected, tol,
                       f"assert_demand_charge_timing (boundary): {c_dc:.4f} ≠ "
                       f"prev_peak×rate={prev_month_peak_mw:.2f}×{demand_rate:.0f}="
                       f"{expected:.4f}")


# ---------------------------------------------------------------------------
# 5. SOC dynamics consistency (§3.2)
# ---------------------------------------------------------------------------

def assert_soc_dynamics(old_soc: float, result: Any, params: Any,
                         *, tol: float = 1e-5) -> None:
    """
    Assert that the SOC update in *result* is consistent with §3.2 dynamics.

    If no SOC violation occurred:
        soc_new = old_soc + (η_ch·P_ch − P_dis/η_dis) · Δt / E_cap
    If SOC violation occurred and battery was charging:
        soc_new == soc_max  (clipped to bound)
    If SOC violation occurred and battery was discharging:
        soc_new == soc_min  (clipped to bound)
    Also checks that soc_violation_mwh is consistent with the overshoot magnitude.

    Parameters
    ----------
    old_soc:
        SOC at the *start* of this step (i.e., state.soc before step was called).
    result:
        Step result for this step.
    params:
        GansuParams.
    tol:
        Relative tolerance for the SOC equality checks.
    """
    dt = 1.0  # Δt = 1 h (D3)
    eta_ch = _p(params, "bat_eta_ch")
    eta_dis = _p(params, "bat_eta_dis")
    E_cap = _p(params, "bat_capacity_mwh")
    soc_min = _p(params, "soc_min")
    soc_max = _p(params, "soc_max")

    p_ch = _f(result, "p_bat_charge_mw")
    p_dis = _f(result, "p_bat_discharge_mw")
    soc_new = _f(_f(result, "new_state"), "soc")
    soc_viol = _f(result, "soc_violation_mwh")

    # Unconstrained SOC update
    soc_unconstrained = old_soc + (eta_ch * p_ch - p_dis / eta_dis) * dt / E_cap

    if soc_viol < 1e-9:
        # No violation: actual SOC should match unconstrained
        _assert_approx(soc_new, soc_unconstrained, tol,
                       f"assert_soc_dynamics (no violation): soc_new={soc_new:.6f} ≠ "
                       f"soc_unconstrained={soc_unconstrained:.6f}")
    else:
        # Violation: SOC must be at the boundary
        if p_ch > 1e-9:
            # Overcharge → clipped to soc_max
            _assert_approx(soc_new, soc_max, 1e-9,
                           f"assert_soc_dynamics (overcharge violation): "
                           f"soc_new={soc_new:.6f} ≠ soc_max={soc_max}")
            # violation_mwh = (soc_unconstrained - soc_max) × E_cap
            viol_expected = (soc_unconstrained - soc_max) * E_cap
            _assert_approx(soc_viol, viol_expected, tol,
                           f"assert_soc_dynamics (overcharge violation energy): "
                           f"soc_violation_mwh={soc_viol:.4f} ≠ expected={viol_expected:.4f}")
        else:
            # Over-discharge → clipped to soc_min
            _assert_approx(soc_new, soc_min, 1e-9,
                           f"assert_soc_dynamics (over-discharge violation): "
                           f"soc_new={soc_new:.6f} ≠ soc_min={soc_min}")
            # violation_mwh = (soc_min - soc_unconstrained) × E_cap
            viol_expected = (soc_min - soc_unconstrained) * E_cap
            _assert_approx(soc_viol, viol_expected, tol,
                           f"assert_soc_dynamics (over-discharge violation energy): "
                           f"soc_violation_mwh={soc_viol:.4f} ≠ expected={viol_expected:.4f}")


# ---------------------------------------------------------------------------
# 6. Determinism harness
# ---------------------------------------------------------------------------

def run_determinism_check(
    step_fn: Callable,
    make_state_fn: Callable,
    action,
    weather: tuple,
    load: float,
    params: Any,
    *,
    n_runs: int = 3,
    tol: float = 1e-12,
) -> None:
    """
    Assert that ``step_fn`` is deterministic: n_runs calls with identical inputs
    (fresh state from ``make_state_fn`` each time) must produce identical results.

    Parameters
    ----------
    step_fn:
        Callable with signature ``step_fn(state, action, weather, load, params) → result``.
    make_state_fn:
        Called n_runs times; must return a fresh state with identical RNG seed.
        Example: ``lambda: EnvState(soc=0.5, month_peak_mw=0.0, t=100,
                                    rng=np.random.default_rng(42))``
    action:
        Fixed action (array-like, shape (6,)).
    weather:
        (wind_mps, irradiance_wm2, temperature_c).
    load:
        Load in MW.
    params:
        GansuParams.
    n_runs:
        Number of independent runs.
    tol:
        Tolerance for float comparisons (default 1e-12: near-exact equality).
    """
    results = [step_fn(make_state_fn(), action, weather, load, params)
               for _ in range(n_runs)]

    ref = results[0]
    _check_fields = [
        "p_wind_mw", "p_solar_mw", "p_bat_charge_mw", "p_bat_discharge_mw",
        "p_import_mw", "p_export_mw", "soc_violation_mwh",
        "c_energy_yuan", "c_demand_shape_yuan", "c_degradation_yuan",
        "c_curtail_yuan", "c_voll_yuan", "penalty_yuan",
        "cost_total_reward_basis_yuan", "cost_total_real_yuan", "reward",
    ]

    for run_idx, res in enumerate(results[1:], start=1):
        for field in _check_fields:
            ref_val = float(_f(ref, field))
            res_val = float(_f(res, field))
            abs_err = abs(ref_val - res_val)
            rel_err = abs_err / (abs(ref_val) + 1e-30)
            assert rel_err <= tol or abs_err <= tol, (
                f"run_determinism_check: run {run_idx} vs run 0 differ on "
                f"'{field}': {ref_val} vs {res_val} (rel_err={rel_err:.2e})")


# ---------------------------------------------------------------------------
# 7. Episode runner
# ---------------------------------------------------------------------------

def run_episode(
    step_fn: Callable,
    initial_state: Any,
    action_or_actions,
    data: dict,
    params: Any,
    *,
    n_steps: int,
    start_t: int = 0,
) -> list:
    """
    Run n_steps of ``step_fn`` from ``initial_state`` and return a list of results.

    Parameters
    ----------
    step_fn:
        ``step_fn(state, action, weather, load, params) → result``.
    initial_state:
        Starting env state.
    action_or_actions:
        Either a single action (applied every step) or a list of per-step actions.
    data:
        Dict with keys 'wind_mps', 'irradiance_wm2', 'temperature_c', 'load_mw'
        (shape (8760,)) as returned by ``generate_year``.
    params:
        GansuParams.
    n_steps:
        How many steps to run.
    start_t:
        Index into data arrays for the first step.

    Returns
    -------
    list[result]
        Length n_steps; each element is the step result (includes new_state).
    """
    import numpy as np

    state = initial_state
    results = []

    single_action = not _is_sequence_of_actions(action_or_actions)

    for i in range(n_steps):
        t = (start_t + i) % len(data["wind_mps"])
        action = action_or_actions if single_action else action_or_actions[i]
        weather = (
            float(data["wind_mps"][t]),
            float(data["irradiance_wm2"][t]),
            float(data["temperature_c"][t]),
        )
        load = float(data["load_mw"][t])
        result = step_fn(state, action, weather, load, params)
        results.append(result)
        state = _f(result, "new_state")

    return results


def assert_episode_invariants(
    results: list,
    params: Any,
    *,
    energy_tol: float = 1e-5,
    cost_tol: float = 1e-9,
    check_formulas: bool = False,
) -> None:
    """
    Run all invariant assertions on every step of an episode.

    Calls assert_energy_conserved + assert_cost_identities + assert_physical_bounds
    on each element of results.  Fails immediately on the first violated invariant,
    reporting which step failed.

    Parameters
    ----------
    results:
        List of step results from ``run_episode`` or a manual rollout.
    params:
        GansuParams.
    energy_tol:
        Passed to assert_energy_conserved.
    cost_tol:
        Passed to assert_cost_identities.
    check_formulas:
        If True, also run formula-level c_import/r_export checks via assert_cost_identities.
        Requires ``price_buy_yuan_per_mwh`` and ``price_sell_yuan_per_mwh`` in each result.
    """
    for i, result in enumerate(results):
        try:
            assert_energy_conserved(result, tol=energy_tol)
        except AssertionError as exc:
            raise AssertionError(f"Step {i}: energy conservation violated\n{exc}") from exc

        try:
            assert_cost_identities(result, params, tol=cost_tol,
                                   check_formulas=check_formulas)
        except AssertionError as exc:
            raise AssertionError(f"Step {i}: cost identity violated\n{exc}") from exc

        try:
            assert_physical_bounds(result, params)
        except AssertionError as exc:
            raise AssertionError(f"Step {i}: physical bounds violated\n{exc}") from exc


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _f(obj: Any, attr: str) -> Any:
    """Get attribute attr from obj (supports dotted paths for nested access)."""
    return getattr(obj, attr)


def _p(params: Any, attr: str) -> float:
    """Get a numeric parameter field."""
    return float(getattr(params, attr))


def _assert_approx(actual: float, expected: float, tol: float, msg: str) -> None:
    """Assert |actual − expected| / max(|expected|, 1e-30) ≤ tol  OR  |actual − expected| ≤ tol."""
    actual = float(actual)
    expected = float(expected)
    abs_err = abs(actual - expected)
    rel_err = abs_err / (abs(expected) + 1e-30)
    if not (rel_err <= tol or abs_err <= tol):
        raise AssertionError(
            f"{msg}\n  actual={actual:.10g}  expected={expected:.10g} "
            f"  abs_err={abs_err:.3e}  rel_err={rel_err:.3e}  tol={tol:.3e}")


def _is_sequence_of_actions(x: Any) -> bool:
    """Return True if x looks like a list/tuple of per-step actions (not a single action)."""
    try:
        import numpy as np
        if isinstance(x, np.ndarray):
            return x.ndim == 2
        if isinstance(x, (list, tuple)) and len(x) > 0:
            first = x[0]
            return hasattr(first, "__len__") or hasattr(first, "__iter__")
    except Exception:
        pass
    return False
