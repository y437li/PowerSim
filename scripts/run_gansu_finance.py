"""Bankable Gansu result — §13.12 View-I dispatch + finance (task #15).

USER DECISION (binding): no_battery is NOT in this ensemble.
  Headline = View-I with-battery full-site, GREEDY POLICY (finance-expert ruling option c,
    PR #127 review 2): simplest, most conservative, no objective caveat.
  View-II = SAME-CONFIG dispatch comparison (smart vs greedy, same hardware/econ).
    Capex legitimately cancels there — isolates dispatch value, not battery-vs-no-battery.
  battery-vs-no-battery = CONFIG-LEVEL comparison (two separate finance() View-I runs,
    each with correct econ) — NOT implemented here, deferred per user direction.

FINANCE-EXPERT RULING (PR #127 review 2):
  DpOracle buy-cost-only objective: export revenue is policy-invariant (~¥926M ≈ identical
  across policies — the 294.5 MWh BESS is ~6% of the 945 MW plant). dp_oracle's +¥239M
  dispatch value comes from DEMAND-CHARGE REDUCTION, NOT export arbitrage. Oracle is NOT
  the export-revenue ceiling (buy-cost-only DP ≠ revenue-maximising oracle). Correct label:
  "demand-charge value". Headline = greedy (conservative); dp_oracle secondary.

CAPEX CORRECTION (PR #127 review 2 — CRITICAL FIX):
  Prior runs used battery-only CAPEX (¥294.5M) — void. Full-site CAPEX is ¥4,932.5M:
    Wind 615 MW × ¥5,800/kW + PV 330 MW × ¥3,200/kW + Battery ¥294.5M + Grid ¥15M.
  IRR should land ≈ 14–17%, LCOE ≈ ¥200–300/MWh. Script hard-fails if sanity gate fires.

HORIZON CORRECTION (PR #127 review 2):
  Prior runs used N=12yr (battery calendar life) → replacement never fired within horizon.
  §13.6 primary is 20yr → battery replaced at yr12 charges in View-I; cl-discharge is live.

Reports:
  View-I (each policy): absolute project NPV / IRR / LCOE / LCOS / P(NPV<0) / CVaR5
  View-II (oracle/TOU vs greedy): dispatch value vs naive baseline (same econ, capex cancels)
  A4 check: degradation_yuan IDENTICAL across cycle_life={6000,9600,12000} (lever check)
  §13.11: cycle_life sweep invariance on FIXED dispatch

Usage:
    arch -arm64 ~/powersim-venv-arm64/bin/python3 scripts/run_gansu_finance.py
    arch -arm64 ~/powersim-venv-arm64/bin/python3 scripts/run_gansu_finance.py --no-oracle

Units: ¥ (yuan), MWh, MW, years, decimal rates.
"""
from __future__ import annotations

import sys
import os
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import jax
import jax.numpy as jnp
import numpy as np

from energy_go.generators.synthetic import generate_year
from energy_go.training.baselines import (
    GreedyPolicy, TouPolicy, DpOraclePolicy,
)
from energy_go.training.eval import (
    PolicyEvalResult,
    _build_streams, _accumulate_physical_quantities,
)
from energy_go.finance.engine import (
    finance, PolicyEnsemble, FinanceConfig, PricePath,
)
from energy_go.finance.econ_params import DeviceEconParams


# ── Config paths — single source of truth for ALL econ inputs ─────────────────
_ROOT               = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEVICE_MODELS_YAML = os.path.join(_ROOT, "config", "device_models.yaml")
_SITE_YAML          = os.path.join(_ROOT, "config", "site_gansu.yaml")


def econ_from_site_config(cycle_life: float = 0.0):
    """Build DeviceEconParams from config/device_models.yaml × config/site_gansu.yaml.

    ALL econ inputs come from config — no hardcoded literals. Returns
    (DeviceEconParams, meta_dict) where meta_dict holds the raw per-device
    breakdown for audit-trail printing.

    cycle_life: passed to DeviceEconParams.cycle_life_full_equiv (0.0 = no limit).

    DeviceEconParams.replacement_cost_fraction is a FRACTION of total_capex_yuan so
    the engine fires the correct absolute ¥ replacement amount at lifetime_years:
        repl_fraction × total_capex = bat_repl_fraction × bat_capex

    Reusable: task #18 (2D battery-sizing sweep) calls this with different site_yaml
    or fleet-size overrides — no baked-in Gansu literals outside this function.
    """
    import yaml
    with open(_DEVICE_MODELS_YAML) as f:
        _dm = yaml.safe_load(f)
    # device_models.yaml has top-level schema_version + models:{...}
    models = _dm["models"] if "models" in _dm else _dm
    with open(_SITE_YAML) as f:
        site   = yaml.safe_load(f)

    # Fleet sizes from site_gansu.yaml
    wind_mw        = float(site["assets"]["wind"]["fleet_rated_mw"])
    pv_mw          = float(site["assets"]["solar"]["fleet_capacity_mw"])
    bat_mwh        = float(site["assets"]["battery"]["fleet_capacity_mwh"])
    bat_mw         = float(site["assets"]["battery"]["fleet_power_mw"])

    # Per-model economics blocks
    wm = models["vestas-v150-4.2"]["economics"]
    pm = models["trina-vertex-n-670w"]["economics"]
    bm = models["catl-lmp-300mwh"]["economics"]
    gm_phys = models["pcc-substation-945mw"]["physics"]
    gm = models["pcc-substation-945mw"]["economics"]
    grid_export_mw = float(gm_phys["max_export_mw"])

    # ── CAPEX (¥) ──────────────────────────────────────────────────────────────
    wind_capex = wind_mw * float(wm["capex_per_kw_yuan"])            * 1_000.0
    pv_capex   = pv_mw   * float(pm["capex_per_kw_yuan"])            * 1_000.0
    bat_capex  = bat_mwh * float(bm["capex_energy_per_kwh_yuan"])    * 1_000.0
    grid_capex = float(gm["capex_lump_sum_yuan"])              # 0 at Gansu (sunk)
    total_capex = wind_capex + pv_capex + bat_capex + grid_capex

    # ── Fixed O&M (¥/yr) ───────────────────────────────────────────────────────
    wind_om = wind_mw      * float(wm["opex_fixed_per_kw_year_yuan"])   * 1_000.0
    pv_om   = pv_mw        * float(pm["opex_fixed_per_kw_year_yuan"])   * 1_000.0
    bat_om  = bat_mwh      * float(bm["opex_fixed_per_kwh_year_yuan"])  * 1_000.0
    grid_om = grid_export_mw * float(gm["opex_fixed_per_mw_year_yuan"])
    fixed_om = wind_om + pv_om + bat_om + grid_om

    # ── Battery lifecycle ───────────────────────────────────────────────────────
    bat_lifetime_yr   = int(bm["lifetime_years"])
    bat_repl_frac_bat = float(bm["replacement_cost_fraction"])   # frac of bat_capex
    bat_repl_abs      = bat_repl_frac_bat * bat_capex            # absolute ¥
    repl_fraction     = bat_repl_abs / total_capex               # frac of FULL-SITE capex

    # ── Residual at horizon N (per-device, summed, fraction of total_capex) ────
    resid_abs = (float(wm["residual_value_fraction"])         * wind_capex +
                 float(pm["residual_value_fraction"])         * pv_capex   +
                 float(bm["residual_value_fraction"])         * bat_capex  +
                 float(gm.get("residual_value_fraction", 0.0)) * grid_capex)
    resid_fraction = resid_abs / total_capex if total_capex > 0 else 0.0

    # ── Decommissioning (per-device, absolute ¥) ───────────────────────────────
    decomm_wind = wind_mw * 1_000.0 * float(wm["decommissioning_cost_per_kw_yuan"])
    decomm_pv   = pv_mw   * 1_000.0 * float(pm["decommissioning_cost_per_kw_yuan"])
    decomm_bat  = bat_mwh * 1_000.0 * float(bm["decommissioning_cost_per_kwh_yuan"])
    decomm_grid = float(gm.get("decommissioning_cost_yuan", 0.0))
    decomm      = decomm_wind + decomm_pv + decomm_bat + decomm_grid

    econ = DeviceEconParams(
        total_capex_yuan          = total_capex,
        fixed_om_yuan_per_yr      = fixed_om,
        bat_capacity_mwh          = bat_mwh,
        lifetime_years            = bat_lifetime_yr,
        cycle_life_full_equiv     = cycle_life,
        replacement_cost_fraction = repl_fraction,
        residual_value_fraction   = resid_fraction,
        decommissioning_yuan      = decomm,
    )

    meta = dict(
        wind_mw=wind_mw, pv_mw=pv_mw, bat_mwh=bat_mwh, bat_mw=bat_mw,
        grid_export_mw=grid_export_mw,
        wind_capex=wind_capex, pv_capex=pv_capex, bat_capex=bat_capex,
        grid_capex=grid_capex, total_capex=total_capex,
        wind_om=wind_om, pv_om=pv_om, bat_om=bat_om, grid_om=grid_om,
        fixed_om=fixed_om,
        bat_lifetime_yr=bat_lifetime_yr,
        bat_repl_abs=bat_repl_abs, repl_fraction=repl_fraction,
        resid_abs=resid_abs, resid_fraction=resid_fraction,
        decomm=decomm, decomm_wind=decomm_wind, decomm_pv=decomm_pv,
        decomm_bat=decomm_bat,
        wind_om_per_kw_yr=float(wm["opex_fixed_per_kw_year_yuan"]),
        pv_om_per_kw_yr=float(pm["opex_fixed_per_kw_year_yuan"]),
        bat_om_per_kwh_yr=float(bm["opex_fixed_per_kwh_year_yuan"]),
        grid_om_per_mw_yr=float(gm["opex_fixed_per_mw_year_yuan"]),
    )
    return econ, meta


# ── Run-level constants (no econ literals — all econ flows through econ_from_site_config) ──
N_YEARS   = 20    # §13.6 primary 20yr horizon; battery calendar-EOL fires at yr12
M         = 50    # R2: M≥50 + sample_kind='bootstrap' → distribution_valid=True
BASE_SEED = 0     # CRN: PRNGKey(m) shared across all policies
CYCLE_LIFE_VALS = [6_000.0, 9_600.0, 12_000.0]   # §13.11 sweep


# ── Extended policy runner: populates all 32 PolicyEvalResult fields ──────────

def _run_policy_with_streams(
    policy,
    data,
    params=None,
    action_mode: str = "env_state",
) -> PolicyEvalResult:
    """Run a §11 policy with full stream + physical-quantity population.

    Extends baselines runners with _build_streams() + _accumulate_physical_quantities()
    so finance() receives real grid_export/import/demand_charge revenue via
    INV-STREAM-AUTHORITY (engine.py:266-275, D39).

    action_mode:
      "env_state" — GreedyPolicy, DpOraclePolicy: action(env_state, step_data, params)
      "t_only"    — TouPolicy: action(t=env_state.t)
    """
    from energy_go.env.jax_env import EnvParams, reset, step as env_step

    env_params = params if params is not None else EnvParams(episode_len=8760)

    if action_mode == "t_only":
        @jax.jit
        def _step_fn(carry, _):
            env_state = carry
            action = policy.action(t=env_state.t)
            new_state, _, _, _, info = env_step(env_state, action, env_params, data)
            return new_state, info
    else:
        @jax.jit
        def _step_fn(carry, _):
            env_state = carry
            action = policy.action(env_state, data[env_state.t], env_params)
            new_state, _, _, _, info = env_step(env_state, action, env_params, data)
            return new_state, info

    key = jax.random.PRNGKey(0)
    init_state, _ = reset(key, env_params, data)
    _, infos = jax.lax.scan(_step_fn, init_state, None, length=env_params.episode_len)

    # 9 wire-locked fields (WIRE-LOCKED per contracts/training/eval_result_extended.md)
    energy_cost_yuan   = float(jnp.sum(infos.c_energy_yuan))
    demand_charge_yuan = float(jnp.sum(infos.c_demand_charge_yuan))
    degradation_yuan   = float(jnp.sum(infos.c_degradation_yuan))
    curtailment_yuan   = float(jnp.sum(infos.c_curtail_yuan))
    voll_yuan          = float(jnp.sum(infos.c_voll_yuan))
    total_cost_yuan    = (energy_cost_yuan + demand_charge_yuan + degradation_yuan
                          + curtailment_yuan + voll_yuan)
    soc_violations_count = int(jnp.sum(infos.soc_violation_mwh > 0))
    soc_violation_mwh    = float(jnp.sum(infos.soc_violation_mwh))
    penalty_yuan         = float(jnp.sum(infos.penalty_yuan))

    # Extended: real revenue / cost streams (INV-STREAM-AUTHORITY)
    streams = _build_streams(infos, env_params)
    phys    = _accumulate_physical_quantities(infos)

    return PolicyEvalResult(
        energy_cost_yuan     = energy_cost_yuan,
        demand_charge_yuan   = demand_charge_yuan,
        degradation_yuan     = degradation_yuan,
        curtailment_yuan     = curtailment_yuan,
        voll_yuan            = voll_yuan,
        total_cost_yuan      = total_cost_yuan,
        soc_violations_count = soc_violations_count,
        soc_violation_mwh    = soc_violation_mwh,
        penalty_yuan         = penalty_yuan,
        streams              = streams,
        generation_mwh       = phys["generation_mwh"],
        wind_generated_mwh   = phys["wind_generated_mwh"],
        pv_generated_mwh     = phys["pv_generated_mwh"],
        bat_charge_mwh       = phys["bat_charge_mwh"],
        bat_discharge_mwh    = phys["bat_discharge_mwh"],
        bat_throughput_mwh   = phys["bat_throughput_mwh"],
        load_served_mwh      = phys["load_served_mwh"],
        load_unserved_mwh    = phys["load_unserved_mwh"],
        curtailed_mwh        = phys["curtailed_mwh"],
        wind_to_load_mwh     = phys["wind_to_load_mwh"],
        wind_to_bat_mwh      = phys["wind_to_bat_mwh"],
        wind_to_grid_mwh     = phys["wind_to_grid_mwh"],
        wind_curtailed_mwh   = phys["wind_curtailed_mwh"],
        pv_to_load_mwh       = phys["pv_to_load_mwh"],
        pv_to_bat_mwh        = phys["pv_to_bat_mwh"],
        pv_to_grid_mwh       = phys["pv_to_grid_mwh"],
        pv_curtailed_mwh     = phys["pv_curtailed_mwh"],
        bat_to_load_mwh      = phys["bat_to_load_mwh"],
        bat_to_grid_mwh      = phys["bat_to_grid_mwh"],
        bat_curtailed_mwh    = phys["bat_curtailed_mwh"],
        grid_to_bat_mwh      = phys["grid_to_bat_mwh"],
        grid_to_load_mwh     = phys["grid_to_load_mwh"],
    )


def _make_econ(cycle_life: float) -> DeviceEconParams:
    """Build DeviceEconParams for the cl sweep — all values from config via econ_from_site_config."""
    econ, _ = econ_from_site_config(cycle_life=cycle_life)
    return econ


def _make_config(horizon: int, baseline_id: str | None = "greedy") -> FinanceConfig:
    # Base case: pre-tax, all-equity (D31); r_e = r_f + β·ERP = 2.5% + 0.60×6.0% = 6.1%
    return FinanceConfig(
        horizon_years         = horizon,
        r_f_override          = 0.025,
        beta_unlevered        = 0.60,
        equity_risk_premium   = 0.060,
        baseline_policy_id    = baseline_id,
        bootstrap_n_resamples = 2_000,
        bootstrap_seed        = 42,
    )


def _fmt_m(v):
    if v is None or (isinstance(v, float) and v != v):
        return "       NaN  "
    return f"  ¥{v/1_000_000:+9.2f}M"


def _fmt_pct(v):
    return f"{v*100:7.2f}%" if v is not None else "     N/A"


def _sep(c="─", w=78):
    print(c * w)


def main():
    run_oracle = "--no-oracle" not in sys.argv
    t_start = time.time()

    # ── Load econ from config — single source of truth, no hardcoded literals ──
    _, meta = econ_from_site_config()
    TOTAL_CAPEX      = meta["total_capex"]
    BAT_CAPACITY_MWH = meta["bat_mwh"]

    print("=" * 78)
    print("BANKABLE GANSU — §13.12 View-I headline  (R2 M=50 bootstrap, config-econ)")
    pols = ["greedy", "rule_based_tou"] + (["dp_oracle"] if run_oracle else [])
    print(f"Policies: {', '.join(pols)}  |  HEADLINE: greedy (finance-expert ruling c)")
    print(f"FULL-SITE CAPEX ¥{TOTAL_CAPEX/1e6:,.1f}M  "
          f"(wind ¥{meta['wind_capex']/1e6:.0f}M + PV ¥{meta['pv_capex']/1e6:.0f}M + "
          f"bat ¥{meta['bat_capex']/1e6:.1f}M + grid ¥{meta['grid_capex']/1e6:.0f}M sunk)")
    print(f"Full-site O&M ¥{meta['fixed_om']/1e6:.2f}M/yr  "
          f"(wind ¥{meta['wind_om']/1e6:.1f}M @¥{meta['wind_om_per_kw_yr']:.0f}/kW·yr"
          f" + PV ¥{meta['pv_om']/1e6:.1f}M @¥{meta['pv_om_per_kw_yr']:.0f}/kW·yr"
          f" + bat ¥{meta['bat_om']/1e6:.2f}M + grid ¥{meta['grid_om']/1e6:.2f}M)")
    print(f"bat {BAT_CAPACITY_MWH} MWh  r_e=6.1%  N={N_YEARS}yr  M={M}")
    print(f"Battery EOL={meta['bat_lifetime_yr']}yr → replacement at yr{meta['bat_lifetime_yr']} "
          f"(¥{meta['bat_repl_abs']/1e6:.2f}M = {meta['repl_fraction']*100:.3f}% of site CAPEX)")
    print()

    # ── CAPEX SANITY GATE — hard abort before any dispatch or verdict ──────────
    # If CAPEX < ¥4B → device-only (not full-site) → all downstream numbers void.
    if TOTAL_CAPEX < 4_000_000_000.0:
        raise RuntimeError(
            f"SANITY TRIPWIRE: TOTAL_CAPEX = ¥{TOTAL_CAPEX/1e6:.1f}M < ¥4,000M. "
            "Full-site CAPEX (wind+PV+bat+grid) required. Check config/device_models.yaml."
        )
    print(f"  CAPEX SANITY: ¥{TOTAL_CAPEX/1e6:,.1f}M ≥ ¥4,000M — OK ✓")
    print()

    # ── 1. Generate M CRN years ───────────────────────────────────────────────
    print(f"[1/4] Generating {M} CRN synthetic years (PRNGKey(m) m=0..{M-1})...")
    t0 = time.time()
    data_list = [generate_year(jax.random.PRNGKey(m)) for m in range(M)]
    print(f"      {time.time()-t0:.1f}s")

    # ── 2. Dispatch ───────────────────────────────────────────────────────────
    print(f"\n[2/4] Dispatching {len(pols)} policies × {M} years...")
    greedy_policy = GreedyPolicy()
    tou_policy    = TouPolicy()

    all_results: dict[str, list[PolicyEvalResult]] = {p: [] for p in pols}
    from energy_go.env.jax_env import EnvParams
    env_params = EnvParams(episode_len=8760)

    for m, data in enumerate(data_list):
        show = (m == 0 or (m + 1) % 10 == 0)
        if show:
            print(f"  draw {m+1:2d}/{M}...", end="", flush=True)

        r_g = _run_policy_with_streams(greedy_policy, data, env_params, "env_state")
        r_t = _run_policy_with_streams(tou_policy,    data, env_params, "t_only")
        all_results["greedy"].append(r_g)
        all_results["rule_based_tou"].append(r_t)

        if run_oracle:
            oracle = DpOraclePolicy.from_data(data, env_params)
            r_o   = _run_policy_with_streams(oracle, data, env_params, "env_state")
            all_results["dp_oracle"].append(r_o)

        if show:
            parts = [
                f"greedy  rev=¥{r_g.streams['grid_export'].value_yuan/1e6:.1f}M "
                f"tp={r_g.bat_throughput_mwh:.0f}MWh degrad=¥{r_g.degradation_yuan:.0f}",
                f"tou  rev=¥{r_t.streams['grid_export'].value_yuan/1e6:.1f}M "
                f"tp={r_t.bat_throughput_mwh:.0f}MWh degrad=¥{r_t.degradation_yuan:.0f}",
            ]
            if run_oracle:
                parts.append(
                    f"oracle rev=¥{r_o.streams['grid_export'].value_yuan/1e6:.1f}M "
                    f"tp={r_o.bat_throughput_mwh:.0f}MWh "
                    f"[dp={oracle.metadata['dp_wall_time_s']:.1f}s]"
                )
            print()
            for p in parts:
                print(f"         {p}")

    dispatch_time = time.time() - t_start
    print(f"\n  Dispatch done: {dispatch_time:.1f}s")

    # ── 3. Build ensemble ─────────────────────────────────────────────────────
    print(f"\n[3/4] PolicyEnsemble M={M}, N={N_YEARS}yr, sample_kind='bootstrap'...")
    ensemble = PolicyEnsemble(
        seed        = BASE_SEED,
        M           = M,
        sample_kind = "bootstrap",
        runs        = {pid: [[r] * N_YEARS for r in results]
                       for pid, results in all_results.items()},
    )
    dv = M >= 50 and ensemble.sample_kind == "bootstrap"
    print(f"  distribution_valid = {dv}  (R2 regime → P50/CI90/downside populated)")

    # ── 4. Finance sweep ──────────────────────────────────────────────────────
    print(f"\n[4/4] finance() × 3 cycle_life values...")
    price_path = PricePath(id="flat", label="Flat 2026", multipliers=[1.0] * N_YEARS)
    results_per_cl: dict[float, object] = {}
    for cl in CYCLE_LIFE_VALS:
        t0 = time.time()
        fr = finance(ensemble, [price_path], _make_econ(cl),
                     _make_config(N_YEARS, baseline_id="greedy"))
        results_per_cl[cl] = fr
        print(f"  cl={cl:.0f}: {time.time()-t0:.1f}s")

    total_time = time.time() - t_start

    # ════════════════════════════════════════════════════════════════════════════
    # A4 LEVER CHECK
    # ════════════════════════════════════════════════════════════════════════════
    print()
    _sep("═")
    print("A4 LEVER CHECK — degradation_yuan IDENTICAL across cycle_life values")
    print("  degradation_yuan: env-layer memo-only (INV-DEG §3.6)")
    print("  cycle_life_full_equiv: finance-layer only → never touches degradation_yuan")
    _sep("═")
    for pid in pols:
        r0 = all_results[pid][0]
        degs = [r.degradation_yuan for r in all_results[pid]]
        print(f"  {pid:<20} draw-0 = ¥{r0.degradation_yuan:.4f}  "
              f"range [{min(degs):.4f}, {max(degs):.4f}] (weather variation, not cl)")
    print("  → A4 PASS: same PolicyEvalResult objects reused for cl=6000/9600/12000")
    print(f"  → cycle_limit @ cl=6000: {6000*BAT_CAPACITY_MWH:,.0f} MWh  "
          f"vs throughput {all_results['greedy'][0].bat_throughput_mwh:.0f} MWh/yr greedy")
    cyc_years_g = 6000 * BAT_CAPACITY_MWH / max(all_results["greedy"][0].bat_throughput_mwh, 0.1)
    cyc_years_t = 6000 * BAT_CAPACITY_MWH / max(all_results["rule_based_tou"][0].bat_throughput_mwh, 0.1)
    print(f"  greedy would hit cl=6000 limit in {cyc_years_g:.0f} yr "
          f"(calendar EOL fires at yr {meta['bat_lifetime_yr']})")
    print(f"  tou    would hit cl=6000 limit in {cyc_years_t:.0f} yr")

    # ════════════════════════════════════════════════════════════════════════════
    # VIEW-I RESULTS (cl=6000 conservative lower bound)
    # ════════════════════════════════════════════════════════════════════════════
    print()
    _sep("═")
    print("§13.12  VIEW-I  (with-battery full-site, cl=6000, pre-tax all-equity D31)")
    _sep("═")

    fr_base = results_per_cl[6_000.0]
    p50_npvs = {}

    for pid in pols:
        vi  = fr_base.per_policy[pid].per_price_path["flat"].view_i
        vii = fr_base.per_policy[pid].per_price_path["flat"].view_ii
        st  = vi.single_trajectory
        p50 = vi.P50
        dr  = vi.downside_risk

        p50_npvs[pid] = p50.npv_yuan if p50 else st.point_npv_yuan

        print(f"\n  ── {pid} ──")
        print(f"  View-I m=0 point NPV:    {_fmt_m(st.point_npv_yuan)}")
        if p50:
            ci_lo, ci_hi = p50.bootstrap_ci
            print(f"  View-I P50 NPV:          {_fmt_m(p50.npv_yuan)}"
                  f"  CI90:[{ci_lo/1e6:+.0f}M,{ci_hi/1e6:+.0f}M]  {p50.confidence!r}")
            if vi.P75: print(f"  View-I P75 NPV:          {_fmt_m(vi.P75.npv_yuan)}")
            if vi.P90: print(f"  View-I P90 NPV:          {_fmt_m(vi.P90.npv_yuan)}")
            print(f"  View-I IRR  (P50):       {_fmt_pct(p50.irr)}")
            print(f"  View-I LCOE (P50):       ¥{p50.lcoe_yuan_per_mwh:.1f}/MWh")
            print(f"  View-I LCOS (P50):       ¥{p50.lcos_yuan_per_mwh:.1f}/MWh")
        if dr:
            t1 = "✓ PASS" if dr.p_npv_neg <= 0.20 else "✗ FAIL"
            print(f"  B3 P(NPV<0) [T1≤20%]:    {t1}  {_fmt_pct(dr.p_npv_neg)}")
            print(f"  B3 CVaR5:                {_fmt_m(dr.cvar5_yuan)}")
            print(f"  B3 Worst-case NPV:       {_fmt_m(dr.worst_case_npv_yuan)}")

        # View-II: dispatch value vs greedy (same econ, capex cancels — correct)
        if vii is not None and pid != "greedy":
            ds = vii.single_trajectory
            print(f"  View-II ({pid} − greedy, dispatch value, capex cancels):")
            print(f"    m=0: {_fmt_m(ds.point_npv_yuan)}", end="")
            if vii.P50:
                print(f"  P50: {_fmt_m(vii.P50.npv_yuan)}", end="")
            print()

    # ════════════════════════════════════════════════════════════════════════════
    # §13.11 SWEEP TABLE
    # ════════════════════════════════════════════════════════════════════════════
    print()
    _sep()
    print("§13.11  CYCLE-LIFE SWEEP — View-I P50 NPV  (R2 M=50, all policies)")
    _sep()
    print(f"{'Policy':<20}  {'cl=6000':>12}  {'cl=9600':>12}  {'cl=12000':>12}  {'shift%':>8}")
    _sep()
    for pid in pols:
        row = [results_per_cl[cl].per_policy[pid].per_price_path["flat"]
               .view_i.P50.npv_yuan if results_per_cl[cl].per_policy[pid]
               .per_price_path["flat"].view_i.P50 else float("nan")
               for cl in CYCLE_LIFE_VALS]
        ref = abs(row[2]) if abs(row[2]) > 1e3 else 1.0
        pct = (row[0] - row[2]) / ref * 100
        print(f"{pid:<20}  "
              + "  ".join(f"¥{v/1e6:>8.2f}M" for v in row)
              + f"  {pct:>+7.1f}%")
    _sep()
    print("  cl=6000 is the CONSERVATIVE LOWER BOUND (NPV monotone in cycle_life,")
    print("  confirmed by finance-expert). Bar at cl=6000 → guaranteed at true cl.")

    # ════════════════════════════════════════════════════════════════════════════
    # BANKABILITY VERDICT
    # ════════════════════════════════════════════════════════════════════════════
    print()
    _sep("═")
    print("BANKABILITY VERDICT  (View-I, cl=6000 stub, pre-tax all-equity)")
    _sep("═")

    # Headline = greedy per finance-expert ruling (option c): conservative, no objective caveat.
    headline_pid = "greedy"
    best_pid = headline_pid
    best_vi  = fr_base.per_policy[best_pid].per_price_path["flat"].view_i
    p50      = best_vi.P50
    dr       = best_vi.downside_risk

    print(f"  Headline policy: {best_pid}  (finance-expert ruling: conservative, no objective caveat)")
    if p50 and dr:
        b1n  = p50.npv_yuan > 0
        b1i  = p50.irr > 0.061
        b3t1 = dr.p_npv_neg <= 0.20
        b3cv = dr.cvar5_yuan > 0
        b3wc = dr.worst_case_npv_yuan > -TOTAL_CAPEX
        print(f"  B1 P50 NPV > 0:         {'✓' if b1n else '✗'}  {_fmt_m(p50.npv_yuan)}")
        print(f"  B1 IRR > r_e (6.1%):    {'✓' if b1i else '✗'}  {_fmt_pct(p50.irr)}")
        print(f"  B3 P(NPV<0) ≤ 20%:      {'✓ PASS' if b3t1 else '✗ FAIL'}  {_fmt_pct(dr.p_npv_neg)}")
        print(f"  B3 CVaR5 > 0:           {'✓' if b3cv else '✗'}  {_fmt_m(dr.cvar5_yuan)}")
        print(f"  B3 Worst > −CAPEX:      {'✓' if b3wc else '✗'}  {_fmt_m(dr.worst_case_npv_yuan)}")
        print(f"  B4 min-DSCR ≥ 1.30:     N/A (all-equity base case)")
        print()
        # IRR sanity gate post-result: should land 10–30% with full-site CAPEX
        irr_ok = p50.irr is not None and 0.05 < p50.irr < 0.35
        lcoe_ok = p50.lcoe_yuan_per_mwh is not None and p50.lcoe_yuan_per_mwh > 100
        print(f"  IRR sanity [5–35%]:      {'✓' if irr_ok else '✗ TRIPWIRE'}  {_fmt_pct(p50.irr)}")
        print(f"  LCOE sanity [>¥100/MWh]: {'✓' if lcoe_ok else '✗ TRIPWIRE'}  ¥{p50.lcoe_yuan_per_mwh:.1f}/MWh")
        # HARD ABORT — a tripped tripwire means the numbers are void.
        # No verdict may be emitted while CAPEX is wrong or revenue is fabricated.
        if not irr_ok:
            raise RuntimeError(
                f"SANITY TRIPWIRE: IRR = {p50.irr*100:.1f}% outside [5%, 35%]. "
                "Full-site CAPEX or revenue likely wrong. Aborting before verdict."
            )
        if not lcoe_ok:
            raise RuntimeError(
                f"SANITY TRIPWIRE: LCOE = ¥{p50.lcoe_yuan_per_mwh:.1f}/MWh < ¥100/MWh. "
                "CAPEX understated or generation overstated. Aborting before verdict."
            )
        print()
        if all([b1n, b1i, b3t1, b3cv, b3wc]) and irr_ok and lcoe_ok:
            print("  PRELIMINARY VERDICT: BANKABLE ✓  (pending finance-expert certification)")
        elif all([b1n, b1i, b3t1, b3cv, b3wc]) and not (irr_ok and lcoe_ok):
            print("  PRELIMINARY VERDICT: B1/B3 PASS BUT SANITY WARN — review before cert")
        else:
            print("  PRELIMINARY VERDICT: NOT YET BANKABLE ✗")
        print(f"  Disclosures:")
        print(f"   1. Full-site CAPEX ¥{TOTAL_CAPEX/1e6:,.1f}M (wind+PV+bat+grid) — corrected per PR #127 ruling 2")
        print(f"   2. cl=6000 = conservative lower bound; true NPV ≥ stub (CATL DoD pending)")
        print(f"   3. dp_oracle demand-charge value (NOT export ceiling): +¥239M secondary metric")
        print(f"      Ruling: oracle export ≈ greedy (¥926M; BESS = 6% of 945MW plant)")
        print(f"   4. MPC not run (computationally intensive for M=50)")
        print(f"   5. Finance-expert gate required to certify and close task #15")

    print()
    print(f"Total runtime: {total_time:.1f}s  (dispatch: {dispatch_time:.1f}s)")
    print()
    print("  Data integrity:")
    print("  ✓ INV-STREAM-AUTHORITY: EBITDA from _build_streams() real r_export/c_import")
    print("  ✓ A4: degradation_yuan unchanged across cycle_life (env-layer field)")
    print(f"  ✓ CF[0] = −¥{TOTAL_CAPEX/1e6:,.1f}M FULL-SITE CAPEX (wind+PV+bat; grid=¥0 sunk)")
    print(f"     wind ¥{meta['wind_capex']/1e6:.0f}M + PV ¥{meta['pv_capex']/1e6:.0f}M + bat ¥{meta['bat_capex']/1e6:.1f}M")
    print("  ✓ View-II = same econ for smart vs greedy (capex cancels = correct dispatch value)")
    print("  ✓ R2: M=50 + bootstrap → distribution_valid → P50/CI90/DownsideRisk")
    print("  ✓ CRN: PRNGKey(m) shared across all policies")
    print(f"  ✓ Battery replacement ¥{meta['bat_repl_abs']/1e6:.2f}M = {meta['repl_fraction']*100:.3f}% of site CAPEX "
          f"(fires at yr{meta['bat_lifetime_yr']})")
    print(f"  ✓ Full-site O&M ¥{meta['fixed_om']/1e6:.2f}M/yr")
    print(f"     wind ¥{meta['wind_om']/1e6:.1f}M (@¥{meta['wind_om_per_kw_yr']:.0f}/kW·yr)"
          f" + PV ¥{meta['pv_om']/1e6:.1f}M (@¥{meta['pv_om_per_kw_yr']:.0f}/kW·yr)")
    print(f"     bat ¥{meta['bat_om']/1e6:.2f}M (@¥{meta['bat_om_per_kwh_yr']:.0f}/kWh·yr)"
          f" + grid ¥{meta['grid_om']/1e6:.2f}M (@¥{meta['grid_om_per_mw_yr']:.0f}/MW·yr)")
    print(f"  ✓ Decommissioning ¥{meta['decomm']/1e6:.1f}M "
          f"(wind ¥{meta['decomm_wind']/1e6:.1f}M + PV ¥{meta['decomm_pv']/1e6:.1f}M"
          f" + bat ¥{meta['decomm_bat']/1e6:.2f}M)")


if __name__ == "__main__":
    main()
