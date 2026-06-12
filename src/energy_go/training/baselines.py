"""§5 baseline policies — NoBatteryPolicy and TouPolicy — §7 of training_pipeline contract.
§11 benchmark baselines — GreedyPolicy, DpOraclePolicy, MpcPolicy — §11.0–§11.5.

Both legacy baselines are JAX-native and run in the same JAX env for a fair comparison.
The 6-dim "Energy Router" action space per §2.2:
    a[0] = a_bat       ∈ [-1,1]  battery charge/discharge fraction
    a[1] = f_sol→load  ∈ [0,1]
    a[2] = f_sol→bat   ∈ [0,1]
    a[3] = f_wind→load ∈ [0,1]
    a[4] = f_wind→bat  ∈ [0,1]
    a[5] = f_bat→load  ∈ [0,1]
"""

from __future__ import annotations

import jax
import jax.numpy as jnp

from energy_go.training.eval import PolicyEvalResult


class NoBatteryPolicy:
    """No-battery baseline — §7.1.

    Always returns [0.0, 1.0, 0.0, 1.0, 0.0, 0.0]:
        a_bat      = 0.0  (idle — no battery activity)
        f_sol→load = 1.0  (all solar to load)
        f_sol→bat  = 0.0
        f_wind→load= 1.0  (all wind to load)
        f_wind→bat = 0.0
        f_bat→load = 0.0

    CRITICAL: allocating f_sol→load=f_wind→load=0 with a_bat=0 would serve ZERO load
    from renewable → maximum VOLL every step → "RL beats no-battery" trivially and
    misleadingly. The above vector is the correct no-battery baseline.

    Consequence: p_bat_ch=p_bat_dis=0 every step; c_degradation_yuan=0 for the year.
    """

    _ACTION = jnp.array([0.0, 1.0, 0.0, 1.0, 0.0, 0.0], dtype=jnp.float32)

    def action(self, t: jax.Array) -> jax.Array:
        """Return the 6-dim NoBattery action (constant, ignores t)."""
        return self._ACTION


class TouPolicy:
    """Rule-based time-of-use policy — §7.2.

    6-dim action based on price = PRICE_TABLE_YPW[t % 24]:

    | Price tier    | a_bat | f_sol→load | f_sol→bat | f_wind→load | f_wind→bat | f_bat→load |
    |---------------|-------|------------|-----------|-------------|------------|------------|
    | Valley (250)  | +1.0  | 0.0        | 1.0       | 0.0         | 1.0        | 0.0        |
    | Mid    (450)  |  0.0  | 1.0        | 0.0       | 1.0         | 0.0        | 0.0        |
    | Peak   (620+) | -1.0  | 1.0        | 0.0       | 1.0         | 0.0        | 1.0        |

    Rationale:
    - Valley: charge battery from renewable; load served from cheap grid import.
    - Mid:    no battery action; all renewable to load; grid imports shortfall.
    - Peak:   discharge battery to load; all renewable to load; no grid if possible.

    The policy is stateless.
    """

    def action(self, t: jax.Array) -> jax.Array:
        """Return the 6-dim TOU action for timestep t.

        Args:
            t: integer timestep (within the episode or year; hour = t % 24)

        Returns:
            (6,) float32 action vector
        """
        from energy_go.env.jax_env import PRICE_TABLE_YPW  # D22b import path

        price     = PRICE_TABLE_YPW[t % 24]
        is_valley = price < 450.0   # 250 ¥/MWh
        is_peak   = price > 450.0   # 620 or 780 ¥/MWh

        return jnp.array([
            jnp.where(is_valley, +1.0, jnp.where(is_peak, -1.0, 0.0)),  # a_bat
            jnp.where(is_valley,  0.0, 1.0),   # f_sol→load  (0 in valley, 1 otherwise)
            jnp.where(is_valley,  1.0, 0.0),   # f_sol→bat   (1 in valley, 0 otherwise)
            jnp.where(is_valley,  0.0, 1.0),   # f_wind→load
            jnp.where(is_valley,  1.0, 0.0),   # f_wind→bat
            jnp.where(is_peak,    1.0, 0.0),   # f_bat→load  (1 in peak, 0 otherwise)
        ], dtype=jnp.float32)


def run_baseline(
    policy_name: str,
    data: object,
    params=None,
) -> PolicyEvalResult:
    """Run one of the §5 baseline policies for a full eval year — §7.

    Args:
        policy_name: "no_battery" | "rule_based_tou"
        data:        SyntheticYear — same synthetic year used for RL eval
        params:      EnvParams | None — None → Gansu defaults

    Returns:
        PolicyEvalResult with real-money cost breakdown (no VecNormalize applied).
    """
    from energy_go.env.jax_env import EnvParams, reset, step  # D22b import path

    if policy_name == "no_battery":
        policy = NoBatteryPolicy()
    elif policy_name == "rule_based_tou":
        policy = TouPolicy()
    else:
        raise ValueError(
            f"Unknown policy_name {policy_name!r}. "
            "Use 'no_battery' or 'rule_based_tou'."
        )

    env_params = params if params is not None else EnvParams(episode_len=8760)

    # Deterministic rollout (no VecNormalize for baselines — §7 "no VecNormalize applied")
    @jax.jit
    def _step(carry, t):
        env_state = carry
        action = policy.action(t=env_state.t)
        new_state, new_obs, reward, done, info = step(env_state, action, env_params, data)
        return new_state, info

    key = jax.random.PRNGKey(0)
    init_state, _ = reset(key, env_params, data)
    # Use env_params.episode_len, not a hardcoded 8760 (eval passes episode_len=8760,
    # but callers may pass custom episode lengths for testing).
    _, infos = jax.lax.scan(_step, init_state, None, length=env_params.episode_len)

    energy_cost_yuan   = float(jnp.sum(infos.c_energy_yuan))
    demand_charge_yuan = float(jnp.sum(infos.c_demand_charge_yuan))
    degradation_yuan   = float(jnp.sum(infos.c_degradation_yuan))
    curtailment_yuan   = float(jnp.sum(infos.c_curtail_yuan))
    voll_yuan          = float(jnp.sum(infos.c_voll_yuan))
    total_cost_yuan    = (
        energy_cost_yuan + demand_charge_yuan + degradation_yuan
        + curtailment_yuan + voll_yuan
    )

    soc_violations_count = int(jnp.sum(infos.soc_violation_mwh > 0))
    soc_violation_mwh    = float(jnp.sum(infos.soc_violation_mwh))
    # LOCKED EnvInfo field name is penalty_yuan (not c_penalty_yuan).
    penalty_yuan = float(jnp.sum(infos.penalty_yuan))

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
    )


# ---------------------------------------------------------------------------
# §11.1 — GreedyPolicy
# ---------------------------------------------------------------------------

class GreedyPolicy:
    """Greedy myopic baseline — §11.1.

    Closed-form, O(1) per step, JIT-compatible (all jnp.where, no Python branches).

    Decision rule:
    - Deficit (load > renewable): discharge battery to serve deficit, then import.
    - Surplus-no-curtailment (surplus ≤ grid_max_export): export surplus, battery idles.
    - Surplus-with-curtailment (surplus > grid_max_export): charge battery from
      would-be-curtailed renewable (wind first, then solar).

    No speculative arbitrage: never charges from grid.
    """

    def action(self, env_state, step_data, params) -> jax.Array:
        """Return the 6-dim greedy action for the current step.

        Args:
            env_state: EnvState (uses env_state.soc)
            step_data: 1-D array of shape (4,) — [wind_mps, irr, temp, load]
            params:    EnvParams

        Returns:
            (6,) float32 action: [a_bat, f_sl, f_sb, f_wl, f_wb, f_bl]
        """
        v_10m = step_data[0]
        irr   = step_data[1]
        temp  = step_data[2]
        load  = step_data[3]

        # Solar PV (mirror jax_env.py STEP 2)
        irr_factor  = irr / 1000.0
        temp_factor = jnp.clip(1.0 + params.pv_k_T * (temp - 25.0), 0.5, 1.2)
        P_pv = jnp.where(
            irr <= 0.0,
            0.0,
            params.pv_capacity_mw * irr_factor * temp_factor
            * params.pv_eta_inv * params.pv_degradation,
        )

        # Wind (mirror jax_env.py STEP 2)
        v_hub  = v_10m * (params.wind_hub_height_m / 10.0) ** 0.14
        p_frac = jnp.where(
            v_hub < params.wind_v_cutin,
            0.0,
            jnp.where(
                v_hub >= params.wind_v_cutout,
                0.0,
                jnp.where(
                    v_hub >= params.wind_v_rated,
                    1.0,
                    ((v_hub - params.wind_v_cutin)
                     / (params.wind_v_rated - params.wind_v_cutin)) ** 3,
                ),
            ),
        )
        P_wind = params.wind_rated_mw * p_frac

        total_ren     = P_wind + P_pv
        deficit       = jnp.maximum(0.0, load - total_ren)
        surplus       = jnp.maximum(0.0, total_ren - load)
        curtail_surplus = jnp.maximum(0.0, surplus - params.grid_max_export_mw)

        # Battery discharge for deficit
        soc = env_state.soc
        P_dis_max    = jnp.minimum(
            params.bat_power_mw,
            jnp.maximum(0.0, (soc - params.soc_min) * params.bat_capacity_mwh
                              * params.bat_eta_dis),
        )
        P_dis_actual = jnp.minimum(deficit, P_dis_max)

        # Battery charge from would-be-curtailed surplus only
        P_ch_max    = jnp.minimum(
            params.bat_power_mw,
            jnp.maximum(0.0, (params.soc_max - soc) * params.bat_capacity_mwh
                              / params.bat_eta_ch),
        )
        P_ch_actual = jnp.minimum(curtail_surplus, P_ch_max)

        in_deficit  = deficit > 0.0
        has_curtail = curtail_surplus > 0.0

        a_bat = jnp.where(
            in_deficit,
            -P_dis_actual / (params.bat_power_mw + 1e-9),
            jnp.where(
                has_curtail,
                P_ch_actual / (params.bat_power_mw + 1e-9),
                0.0,
            ),
        )

        # --- Renewable routing fractions ---
        P_wind_safe = jnp.maximum(P_wind, 1e-9)
        P_pv_safe   = jnp.maximum(P_pv,   1e-9)

        # DEFICIT case: all renewable to load, discharge to load
        f_wl_def = 1.0
        f_sl_def = 1.0
        f_wb_def = 0.0
        f_sb_def = 0.0
        f_bl_def = 1.0

        # SURPLUS-NO-CURTAILMENT case: all renewable to load (env load-caps); bat idles
        f_wl_surp = 1.0
        f_sl_surp = 1.0
        f_wb_surp = 0.0
        f_sb_surp = 0.0
        f_bl_surp = 0.0

        # CURTAILMENT case: charge from wind first, then solar; no bat-to-load
        bat_from_wind  = jnp.minimum(P_ch_actual, P_wind)
        bat_from_solar = jnp.maximum(0.0, P_ch_actual - bat_from_wind)
        f_wb_curt = jnp.minimum(1.0, bat_from_wind  / P_wind_safe)
        f_wl_curt = jnp.maximum(0.0, 1.0 - f_wb_curt)   # f_wl + f_wb = 1, no renorm
        f_sb_curt = jnp.minimum(1.0, bat_from_solar / P_pv_safe)
        f_sl_curt = jnp.maximum(0.0, 1.0 - f_sb_curt)
        f_bl_curt = 0.0

        f_wl = jnp.where(in_deficit, f_wl_def, jnp.where(has_curtail, f_wl_curt, f_wl_surp))
        f_sl = jnp.where(in_deficit, f_sl_def, jnp.where(has_curtail, f_sl_curt, f_sl_surp))
        f_wb = jnp.where(in_deficit, f_wb_def, jnp.where(has_curtail, f_wb_curt, f_wb_surp))
        f_sb = jnp.where(in_deficit, f_sb_def, jnp.where(has_curtail, f_sb_curt, f_sb_surp))
        f_bl = jnp.where(in_deficit, f_bl_def, jnp.where(has_curtail, f_bl_curt, f_bl_surp))

        # action = [a_bat, f_sol→load, f_sol→bat, f_wind→load, f_wind→bat, f_bat→load]
        return jnp.array([a_bat, f_sl, f_sb, f_wl, f_wb, f_bl], dtype=jnp.float32)


# ---------------------------------------------------------------------------
# §11.2 — DpOraclePolicy
# ---------------------------------------------------------------------------

class DpOraclePolicy:
    """DP oracle baseline — §11.2.

    Offline backward induction with per-month peak sweep.
    Pre-computes an optimal a_bat trajectory of length episode_len; at inference
    time, returns the pre-computed action for step t (plus greedy fractions).

    Grid dimensions: N_soc=71, N_act=21, N_peak=41.
    """

    def __init__(self, optimal_actions, metadata: dict):
        """
        Args:
            optimal_actions: jax.Array shape (episode_len,) float32 — a_bat per step
            metadata:        dict with keys "dp_wall_time_s", "n_soc_states",
                             "n_peak_candidates"
        """
        self.optimal_actions = optimal_actions
        self.metadata        = metadata

    @classmethod
    def from_data(cls, data, params=None) -> "DpOraclePolicy":
        """Solve backward-induction DP offline and return a DpOraclePolicy.

        Args:
            data:   shape (>=ep_len, 4) — synthetic year data
            params: EnvParams | None — None → Gansu defaults (episode_len=8760)

        Returns:
            DpOraclePolicy with .optimal_actions and .metadata set.
        """
        import time
        import numpy as np
        from energy_go.env.jax_env import EnvParams, MONTH_OF_STEP, PRICE_TABLE_YPW

        if params is None:
            params = EnvParams(episode_len=8760)

        ep_len = int(params.episode_len)
        N_soc  = 71
        N_act  = 21
        N_peak = 41

        soc_grid  = np.linspace(float(params.soc_min), float(params.soc_max), N_soc)
        a_grid    = np.linspace(-1.0, 1.0, N_act)
        delta_soc = soc_grid[1] - soc_grid[0]

        # Clamp data to episode length
        data_np       = np.array(data)[:ep_len]    # (ep_len, 4)
        month_of_step = np.array(MONTH_OF_STEP)[:ep_len]  # (ep_len,)
        price_table   = np.array(PRICE_TABLE_YPW)          # (24,)

        # Precompute P_wind and P_pv for all steps
        v_10m = data_np[:, 0]
        irr   = data_np[:, 1]
        temp  = data_np[:, 2]
        load  = data_np[:, 3]

        v_hub  = v_10m * (float(params.wind_hub_height_m) / 10.0) ** 0.14
        p_frac = np.where(v_hub < float(params.wind_v_cutin), 0.0,
                 np.where(v_hub >= float(params.wind_v_cutout), 0.0,
                 np.where(v_hub >= float(params.wind_v_rated),  1.0,
                          ((v_hub - float(params.wind_v_cutin)) /
                           (float(params.wind_v_rated) - float(params.wind_v_cutin))) ** 3)))
        P_wind_all = float(params.wind_rated_mw) * p_frac

        irr_f   = irr / 1000.0
        temp_f  = np.clip(1.0 + float(params.pv_k_T) * (temp - 25.0), 0.5, 1.2)
        P_pv_all = np.where(
            irr <= 0.0,
            0.0,
            float(params.pv_capacity_mw) * irr_f * temp_f
            * float(params.pv_eta_inv) * float(params.pv_degradation),
        )

        t0 = time.time()

        # Scalar params
        bat_pow   = float(params.bat_power_mw)
        bat_cap   = float(params.bat_capacity_mwh)
        eta_ch    = float(params.bat_eta_ch)
        eta_dis   = float(params.bat_eta_dis)
        soc_min_f = float(params.soc_min)
        soc_max_f = float(params.soc_max)
        grid_exp  = float(params.grid_max_export_mw)
        grid_imp  = float(params.grid_max_import_mw)
        c_deg     = float(params.c_deg_yuan_per_mwh)
        curtail_c = float(params.curtail_yuan_per_mwh)
        dr        = float(params.demand_rate_yuan_per_mw_month)
        voll_c    = float(params.voll_yuan_per_mwh)

        # Broadcast grids: (N_soc, 1), (1, N_act)
        soc_b = soc_grid[:, None]   # (N_soc, 1)
        a_b   = a_grid[None, :]     # (1, N_act)

        # SOC delta per action: (1, N_act)
        # charging (a >= 0): dsoc = eta_ch * a * bat_pow / bat_cap
        # discharging (a < 0): dsoc = a * bat_pow / (eta_dis * bat_cap)  (negative)
        dsoc_b = np.where(
            a_b >= 0,
            eta_ch * a_b * bat_pow / bat_cap,
            a_b * bat_pow / (eta_dis * bat_cap),
        )  # (1, N_act)

        # Next-SOC continuous and index: (N_soc, N_act)
        soc_next_cont = np.clip(soc_b + dsoc_b, soc_min_f, soc_max_f)
        soc_next_idx  = np.clip(
            np.round((soc_next_cont - soc_min_f) / delta_soc).astype(int),
            0, N_soc - 1,
        )  # (N_soc, N_act)

        # Max feasible charge/discharge per SOC state: (N_soc, 1)
        max_P_ch_soc  = np.maximum(0.0, (soc_max_f - soc_b) * bat_cap / eta_ch)
        max_P_dis_soc = np.maximum(0.0, (soc_b - soc_min_f) * bat_cap * eta_dis)

        # P_ch and P_dis per action: (1, N_act)
        P_ch_raw  = np.maximum(0.0,  a_b) * bat_pow
        P_dis_raw = np.maximum(0.0, -a_b) * bat_pow

        # Feasible actual power: (N_soc, N_act)
        P_ch_actual  = np.minimum(P_ch_raw,  np.minimum(bat_pow, max_P_ch_soc))
        P_dis_actual = np.minimum(P_dis_raw, np.minimum(bat_pow, max_P_dis_soc))

        # SOC infeasibility: action would be clipped (infeasible state-action pair)
        # We mark actions infeasible if the desired power significantly exceeds what's allowed.
        ch_infeas  = P_ch_raw  > max_P_ch_soc  + 1e-6   # (N_soc, N_act)
        dis_infeas = P_dis_raw > max_P_dis_soc + 1e-6   # (N_soc, N_act)
        is_infeas  = np.where(a_b >= 0, ch_infeas, dis_infeas)  # (N_soc, N_act)

        # Find billing period boundaries (months)
        period_ends   = []
        period_starts = [0]
        for t_idx in range(1, ep_len):
            if month_of_step[t_idx] != month_of_step[t_idx - 1]:
                period_ends.append(t_idx - 1)
                period_starts.append(t_idx)
        period_ends.append(ep_len - 1)

        opt_actions = np.zeros(ep_len, dtype=np.float32)

        # Track actual SOC as we move through periods (continuous replay)
        current_soc = float(params.soc_init)

        for per_idx, (ps, pe) in enumerate(zip(period_starts, period_ends)):
            T = pe - ps + 1   # steps in this period

            # --- Per-step cost matrices for each peak candidate ---
            # For each step t in [ps, pe], for each (soc, action):
            # compute cost given the greedy renewable routing and a peak cap P_bar.

            # Step-level renewable data for this period
            P_wind_t = P_wind_all[ps:pe+1]   # (T,)
            P_pv_t   = P_pv_all[ps:pe+1]     # (T,)
            load_t   = load[ps:pe+1]          # (T,)
            hour_idx  = np.arange(ps, pe+1, dtype=int) % 24
            price_t   = price_table[hour_idx]  # (T,)

            # Precompute step-level scalars: (T,)
            total_ren_t    = P_wind_t + P_pv_t
            surplus_t      = np.maximum(0.0, total_ren_t - load_t)
            deficit_t      = np.maximum(0.0, load_t - total_ren_t)
            curtail_avail_t = np.maximum(0.0, surplus_t - grid_exp)

            # P_ch_from_ren and P_ch_grid for each (soc, action, step):
            # P_ch_from_ren[si, ai, t] = min(P_ch_actual[si,ai], curtail_avail[t])
            # grid_for_bat[si, ai, t]  = max(0, P_ch_actual[si,ai] - P_ch_from_ren)

            # Expand dims for broadcasting:
            # P_ch_actual: (N_soc, N_act, 1) via [..., None]
            # curtail_avail_t: (1, 1, T) via [None, None, :]
            P_ch_a3   = P_ch_actual[:, :, None]         # (N_soc, N_act, 1)
            P_dis_a3  = P_dis_actual[:, :, None]        # (N_soc, N_act, 1)
            isinfeas3 = is_infeas[:, :, None]           # (N_soc, N_act, 1)

            cav3  = curtail_avail_t[None, None, :]      # (1, 1, T)
            def3  = deficit_t[None, None, :]            # (1, 1, T)
            ren3  = total_ren_t[None, None, :]          # (1, 1, T)
            load3 = load_t[None, None, :]               # (1, 1, T)
            pr3   = price_t[None, None, :]              # (1, 1, T)

            P_ch_from_ren = np.minimum(P_ch_a3, cav3)              # (N_soc, N_act, T)
            grid_for_bat  = np.maximum(0.0, P_ch_a3 - P_ch_from_ren)  # (N_soc, N_act, T)

            # Grid for load: load deficit after renewable and battery discharge
            load_deficit_after_ren = def3                          # (1, 1, T)
            residual_after_bat     = np.maximum(0.0, load_deficit_after_ren - P_dis_a3)
            grid_for_load          = np.minimum(residual_after_bat, grid_imp)  # (N_soc, N_act, T)

            P_import_raw = grid_for_load + grid_for_bat            # (N_soc, N_act, T)
            P_import     = np.minimum(P_import_raw, grid_imp)

            # VOLL: load not served
            load_unserved = np.maximum(0.0, load3 - ren3 - P_dis_a3 - grid_for_load)  # (N_soc, N_act, T)

            # Curtailment: surplus not exported and not charged
            # actual export from surplus = surplus - P_ch_from_ren (capped at 0)
            surplus_to_grid = np.maximum(0.0, surplus_t[None, None, :] - P_ch_from_ren)
            P_curtail       = np.maximum(0.0, surplus_to_grid - grid_exp)  # (N_soc, N_act, T)

            # Degradation: on actual power (charge + discharge)
            C_deg_base = c_deg * (P_ch_actual[:, :, None] + P_dis_actual[:, :, None])  # (N_soc, N_act, 1)

            # Energy cost (buy only — sell revenue negligible for DP; consistent with greedy)
            C_energy_base = pr3 * P_import                          # (N_soc, N_act, T)
            C_curtail_base = curtail_c * P_curtail                  # (N_soc, N_act, T)
            C_voll_base    = voll_c * load_unserved                 # (N_soc, N_act, T)

            # Base cost (no demand charge — handled via peak sweep): (N_soc, N_act, T)
            cost_base = C_energy_base + C_deg_base + C_curtail_base + C_voll_base

            # Mark infeasible state-action pairs with large cost
            INF_COST = 1e15
            cost_base = np.where(isinfeas3, INF_COST, cost_base)

            # --- Peak sweep: for each peak cap P_bar, run backward induction ---
            peak_candidates = np.linspace(0.0, grid_imp, N_peak)

            best_total_cost  = np.full(1, np.inf)
            best_P_bar       = peak_candidates[0]
            best_opt_a_local = np.zeros(T, dtype=np.float32)

            # For the first step, start from current_soc
            start_soc_idx = int(np.clip(
                np.round((current_soc - soc_min_f) / delta_soc), 0, N_soc - 1
            ))

            for P_bar in peak_candidates:
                # Mark (soc, action) pairs where P_import > P_bar as infeasible
                # P_import is (N_soc, N_act, T) — infeasible if max over T exceeds P_bar
                # Actually: for DP, we want each step's import <= P_bar
                # (infeasibility per step, per (soc, action))
                peak_viol = P_import > P_bar + 1e-6  # (N_soc, N_act, T)

                # Adjusted cost: mark peak-violating (soc,action,t) as INF
                cost_adj = np.where(peak_viol | isinfeas3, INF_COST, cost_base)  # (N_soc, N_act, T)

                # Backward induction: V[si] = min_a { cost[si,ai,t] + V_next[soc_next_idx[si,ai]] }
                # Initialize terminal value to 0
                V_next = np.zeros(N_soc, dtype=np.float64)
                opt_ai = np.zeros((T, N_soc), dtype=np.int32)

                for t_rev in range(T - 1, -1, -1):
                    # Q: (N_soc, N_act) = cost_adj[:,:,t_rev] + V_next[soc_next_idx]
                    q_vals = cost_adj[:, :, t_rev] + V_next[soc_next_idx]  # (N_soc, N_act)
                    best_ai_t = np.argmin(q_vals, axis=1)   # (N_soc,)
                    opt_ai[t_rev] = best_ai_t
                    # New V for this step
                    V_next = q_vals[np.arange(N_soc), best_ai_t]  # (N_soc,)

                # Total cost from start_soc: V_next[start_soc_idx] + demand charge
                in_period_cost = V_next[start_soc_idx]
                demand_charge  = P_bar * dr
                total_cost_candidate = in_period_cost + demand_charge

                if total_cost_candidate < best_total_cost[0]:
                    best_total_cost[0] = total_cost_candidate
                    best_P_bar         = P_bar
                    # Replay optimal trajectory from start_soc to extract a_bat sequence
                    soc_idx = start_soc_idx
                    traj = np.zeros(T, dtype=np.float32)
                    for t_fwd in range(T):
                        ai = opt_ai[t_fwd, soc_idx]
                        traj[t_fwd] = a_grid[ai]
                        soc_idx = soc_next_idx[soc_idx, ai]
                    best_opt_a_local = traj
                    # Update current_soc for next period (continuous, not grid)
                    # We'll re-compute after the loop using actual DSoC
                    _final_soc_idx = soc_idx

            opt_actions[ps:pe+1] = best_opt_a_local

            # Advance current_soc through the period using the best actions
            # (use continuous SOC for better accuracy across periods)
            soc_running = current_soc
            for t_fwd in range(T):
                a = float(best_opt_a_local[t_fwd])
                if a >= 0:
                    dsoc = eta_ch * a * bat_pow / bat_cap
                else:
                    dsoc = a * bat_pow / (eta_dis * bat_cap)
                soc_running = float(np.clip(soc_running + dsoc, soc_min_f, soc_max_f))
            current_soc = soc_running

        wall_time = time.time() - t0

        return cls(
            optimal_actions = jax.numpy.array(opt_actions, dtype=jax.numpy.float32),
            metadata        = {
                "dp_wall_time_s":    wall_time,
                "n_soc_states":      N_soc,
                "n_peak_candidates": N_peak,
            },
        )

    def action(self, env_state, step_data, params) -> jax.Array:
        """Return the DP-optimal a_bat for step t, with greedy renewable fractions.

        Args:
            env_state: EnvState (uses env_state.t and env_state.soc)
            step_data: (4,) array — [wind, irr, temp, load]
            params:    EnvParams

        Returns:
            (6,) float32 action
        """
        # JAX dynamic indexing — valid inside lax.scan / @jax.jit
        # (do NOT use int(env_state.t): concretizing a traced value fails in jit)
        a_bat = self.optimal_actions[env_state.t].astype(jnp.float32)

        # Clip to the SOC-feasible window using the actual env_state.soc.
        # The DP was solved on a discretized float64 SOC grid; the JAX env uses
        # float32 — trajectories diverge over 8760 steps, causing SOC bound
        # violations.
        #
        # Formula: a * bat_power → env receives a * bat_power MW.
        # Naive a_ch_max = P_ch / bat_power leads to round-trip float32 error:
        # (P_ch / bat_power) * bat_power can be 1 ULP above P_ch (≈3.5e-6 MWh
        # violation per step).  Applying a (1-1e-5) relative margin (≈250 W on
        # 50 MW, 80× float32 epsilon) absorbs all such rounding without affecting
        # DP optimality.
        _max_P_ch  = jnp.maximum(
            0.0,
            (params.soc_max - env_state.soc) * params.bat_capacity_mwh
            / params.bat_eta_ch,
        )
        _max_P_dis = jnp.maximum(
            0.0,
            (env_state.soc - params.soc_min) * params.bat_capacity_mwh
            * params.bat_eta_dis,
        )
        a_ch_max  = jnp.minimum(1.0, _max_P_ch  * (1.0 - 1e-5) / params.bat_power_mw)
        a_dis_max = jnp.minimum(1.0, _max_P_dis * (1.0 - 1e-5) / params.bat_power_mw)
        a_bat = jnp.clip(a_bat, -a_dis_max, a_ch_max)

        # Use greedy renewable routing fractions; override only a_bat with DP value
        greedy = GreedyPolicy()
        greedy_action = greedy.action(env_state, step_data, params)
        return greedy_action.at[0].set(a_bat)


# ---------------------------------------------------------------------------
# §11.3 — MpcPolicy
# ---------------------------------------------------------------------------

class MpcPolicy:
    """MPC receding-horizon baseline — §11.3.

    Per-step LP over H=24 horizon using scipy.optimize.linprog.
    Only a_bat[0] is applied; the rest of the trajectory is discarded (receding horizon).
    Renewable routing fractions follow the greedy §11.1 rule.
    """

    def __init__(
        self,
        horizon: int = 24,
        lambda_terminal: float | None = None,
        soc_target: float = 0.5,
        mu_peak: float | None = None,
    ):
        """
        Args:
            horizon:         Look-ahead steps (default 24).
            lambda_terminal: Terminal SOC penalty coefficient (None → derived from params).
            soc_target:      Target SOC at end of horizon (default 0.5).
            mu_peak:         Peak-import penalty (None → demand_rate_yuan_per_mw_month).
        """
        self.horizon          = horizon
        self.lambda_terminal  = lambda_terminal
        self.soc_target       = soc_target
        self.mu_peak          = mu_peak

    def action(
        self,
        env_state,
        step_data,
        forecast_data,
        params,
    ) -> jax.Array:
        """Solve the H-step LP and return the first-step action.

        Args:
            env_state:     EnvState — uses soc and month_peak
            step_data:     (4,) — realized data at current step
            forecast_data: full data array (8760, 4) — forecast for future steps
            params:        EnvParams

        Returns:
            (6,) float32 action
        """
        import numpy as np
        from scipy.optimize import linprog

        H = self.horizon
        t = int(env_state.t)
        soc_0 = float(env_state.soc)
        running_peak = float(env_state.month_peak)

        # Derived penalty coefficients
        bat_pow   = float(params.bat_power_mw)
        bat_cap   = float(params.bat_capacity_mwh)
        eta_ch    = float(params.bat_eta_ch)
        eta_dis   = float(params.bat_eta_dis)
        soc_min_f = float(params.soc_min)
        soc_max_f = float(params.soc_max)
        grid_imp  = float(params.grid_max_import_mw)
        grid_exp  = float(params.grid_max_export_mw)
        c_deg     = float(params.c_deg_yuan_per_mwh)
        curtail_c = float(params.curtail_yuan_per_mwh)
        dr        = float(params.demand_rate_yuan_per_mw_month)
        voll_c    = float(params.voll_yuan_per_mwh)

        mu_peak = self.mu_peak if self.mu_peak is not None else dr
        lambda_terminal = (
            self.lambda_terminal if self.lambda_terminal is not None
            else dr / (bat_cap * 1.0)
        )

        ep_len = int(params.episode_len)

        # Build horizon data: clip at episode end
        from energy_go.env.jax_env import PRICE_TABLE_YPW
        price_table = np.array(PRICE_TABLE_YPW)

        data_np = np.array(forecast_data)
        hor_data = np.zeros((H, 4), dtype=np.float64)
        for h in range(H):
            idx = min(t + h, ep_len - 1)
            hor_data[h] = data_np[idx]

        # Compute P_wind, P_pv, price per horizon step
        v_10m_h = hor_data[:, 0]
        irr_h   = hor_data[:, 1]
        temp_h  = hor_data[:, 2]
        load_h  = hor_data[:, 3]

        v_hub_h = v_10m_h * (float(params.wind_hub_height_m) / 10.0) ** 0.14
        p_frac_h = np.where(v_hub_h < float(params.wind_v_cutin), 0.0,
                   np.where(v_hub_h >= float(params.wind_v_cutout), 0.0,
                   np.where(v_hub_h >= float(params.wind_v_rated),  1.0,
                            ((v_hub_h - float(params.wind_v_cutin)) /
                             (float(params.wind_v_rated) - float(params.wind_v_cutin))) ** 3)))
        P_wind_h = float(params.wind_rated_mw) * p_frac_h

        irr_f_h  = irr_h / 1000.0
        temp_f_h = np.clip(1.0 + float(params.pv_k_T) * (temp_h - 25.0), 0.5, 1.2)
        P_pv_h   = np.where(irr_h <= 0.0, 0.0,
                             float(params.pv_capacity_mw) * irr_f_h * temp_f_h
                             * float(params.pv_eta_inv) * float(params.pv_degradation))

        hour_idx_h = np.array([(t + h) % 24 for h in range(H)], dtype=int)
        price_h    = price_table[hour_idx_h]

        total_ren_h    = P_wind_h + P_pv_h
        surplus_h      = np.maximum(0.0, total_ren_h - load_h)
        deficit_h      = np.maximum(0.0, load_h - total_ren_h)
        curtail_avail_h = np.maximum(0.0, surplus_h - grid_exp)

        # --- LP formulation ---
        # Variables (per horizon step h=0..H-1):
        #   c[h]   = charge fraction [0,1] * bat_pow
        #   d[h]   = discharge fraction [0,1] * bat_pow
        #   il[h]  = grid import for load [0, grid_imp]
        #   ib[h]  = grid import for battery [0, grid_imp]
        #   cv[h]  = curtailment MW [0, inf]
        #   pe[h]  = peak excess MW [0, inf]  (max(0, import - running_peak))
        # Plus terminal SOC slack: se_p, se_n  (soc_H - soc_target = se_p - se_n)
        #
        # Total variables: 6*H + 2
        # Indices:
        #   c:  [0, H)
        #   d:  [H, 2H)
        #   il: [2H, 3H)
        #   ib: [3H, 4H)
        #   cv: [4H, 5H)
        #   pe: [5H, 6H)
        #   se_p: 6H
        #   se_n: 6H + 1

        n_vars = 6 * H + 2
        idx_c  = np.arange(0, H)
        idx_d  = np.arange(H, 2*H)
        idx_il = np.arange(2*H, 3*H)
        idx_ib = np.arange(3*H, 4*H)
        idx_cv = np.arange(4*H, 5*H)
        idx_pe = np.arange(5*H, 6*H)
        idx_sep = 6*H
        idx_sen = 6*H + 1

        # Objective: Σ [price*il + price*ib + c_deg*bat_pow*(c+d) + curtail_c*cv + mu_peak*pe]
        #            + lambda_terminal * (se_p + se_n)
        obj = np.zeros(n_vars)
        obj[idx_il] = price_h
        obj[idx_ib] = price_h
        obj[idx_c]  = c_deg * bat_pow
        obj[idx_d]  = c_deg * bat_pow
        obj[idx_cv] = curtail_c
        obj[idx_pe] = mu_peak
        obj[idx_sep] = lambda_terminal * bat_cap
        obj[idx_sen] = lambda_terminal * bat_cap

        # Bounds
        bounds = []
        for h in range(H):
            bounds.append((0.0, 1.0))   # c[h]
        for h in range(H):
            bounds.append((0.0, 1.0))   # d[h]
        for h in range(H):
            bounds.append((0.0, grid_imp))  # il[h]
        for h in range(H):
            bounds.append((0.0, grid_imp))  # ib[h]
        for h in range(H):
            bounds.append((0.0, None))   # cv[h]
        for h in range(H):
            bounds.append((0.0, None))   # pe[h]
        bounds.append((0.0, None))  # se_p
        bounds.append((0.0, None))  # se_n

        # Inequality constraints A_ub @ x <= b_ub
        A_ub_rows = []
        b_ub_rows = []

        # 1. c[h] + d[h] <= 1  (mutual exclusion)
        for h in range(H):
            row = np.zeros(n_vars)
            row[idx_c[h]] = 1.0
            row[idx_d[h]] = 1.0
            A_ub_rows.append(row)
            b_ub_rows.append(1.0)

        # 2. il[h] >= deficit[h] - bat_pow * d[h]
        #    i.e. -il[h] + (-bat_pow) * d[h] <= -deficit[h]
        #    Wait: il serves the load deficit after renewable and battery.
        #    Greedy routing: renewable serves load first; deficit is what's left.
        #    Battery discharge fills part of deficit; il fills the rest.
        #    il[h] >= max(0, deficit[h] - bat_pow * d[h])  (hard: must serve load)
        #    => -il[h] - bat_pow * d[h] <= -deficit[h]
        #    but il[h] >= 0 already, so this is sufficient.
        for h in range(H):
            row = np.zeros(n_vars)
            row[idx_il[h]] = -1.0
            row[idx_d[h]]  = -bat_pow
            A_ub_rows.append(row)
            b_ub_rows.append(-deficit_h[h])

        # 3. ib[h] >= bat_pow * c[h] - curtail_avail[h]
        #    (grid charges battery if renewable curtailment insufficient)
        #    => -ib[h] + bat_pow * c[h] <= curtail_avail[h]
        for h in range(H):
            row = np.zeros(n_vars)
            row[idx_ib[h]] = -1.0
            row[idx_c[h]]  =  bat_pow
            A_ub_rows.append(row)
            b_ub_rows.append(curtail_avail_h[h])

        # 4. cv[h] >= surplus[h] - bat_pow * c[h] - grid_exp
        #    => -cv[h] - bat_pow * c[h] <= grid_exp - surplus[h]
        for h in range(H):
            row = np.zeros(n_vars)
            row[idx_cv[h]] = -1.0
            row[idx_c[h]]  = -bat_pow
            A_ub_rows.append(row)
            b_ub_rows.append(grid_exp - surplus_h[h])

        # 5. pe[h] >= il[h] + ib[h] - running_peak
        #    => -pe[h] + il[h] + ib[h] <= running_peak
        for h in range(H):
            row = np.zeros(n_vars)
            row[idx_pe[h]] = -1.0
            row[idx_il[h]] =  1.0
            row[idx_ib[h]] =  1.0
            A_ub_rows.append(row)
            b_ub_rows.append(running_peak)

        # 6. SOC upper bounds: for each h=0..H-1,
        #    sum_{k=0}^{h} (eta_ch*c[k] - (1/eta_dis)*d[k]) * bat_pow / bat_cap
        #    <= soc_max - soc_0
        #    => cumulative SOC change <= soc_max - soc_0
        delta_ch_frac  = eta_ch * bat_pow / bat_cap
        delta_dis_frac = bat_pow / (eta_dis * bat_cap)

        for h in range(H):
            row = np.zeros(n_vars)
            for k in range(h + 1):
                row[idx_c[k]] =  delta_ch_frac
                row[idx_d[k]] = -delta_dis_frac   # discharge reduces SOC (d >= 0, sign is -)
            A_ub_rows.append(row)
            b_ub_rows.append(soc_max_f - soc_0)

        # 7. SOC lower bounds: for each h=0..H-1,
        #    -sum (delta_ch*c[k] - delta_dis*d[k]) <= soc_0 - soc_min
        for h in range(H):
            row = np.zeros(n_vars)
            for k in range(h + 1):
                row[idx_c[k]] = -delta_ch_frac
                row[idx_d[k]] =  delta_dis_frac
            A_ub_rows.append(row)
            b_ub_rows.append(soc_0 - soc_min_f)

        A_ub = np.array(A_ub_rows, dtype=np.float64)
        b_ub = np.array(b_ub_rows, dtype=np.float64)

        # Equality constraints A_eq @ x == b_eq
        # Terminal SOC: sum(delta_ch*c[k] - delta_dis*d[k]) - se_p + se_n = soc_target - soc_0
        A_eq_rows = []
        b_eq_rows = []
        row = np.zeros(n_vars)
        for k in range(H):
            row[idx_c[k]] =  delta_ch_frac
            row[idx_d[k]] = -delta_dis_frac
        row[idx_sep] = -1.0
        row[idx_sen] =  1.0
        A_eq_rows.append(row)
        b_eq_rows.append(self.soc_target - soc_0)

        A_eq = np.array(A_eq_rows, dtype=np.float64)
        b_eq = np.array(b_eq_rows, dtype=np.float64)

        # Solve LP
        try:
            result = linprog(
                obj, A_ub=A_ub, b_ub=b_ub,
                A_eq=A_eq, b_eq=b_eq,
                bounds=bounds,
                method="highs",
            )
            if result.success:
                x = result.x
            else:
                # Fallback: greedy action
                x = None
        except Exception:
            x = None

        if x is not None:
            c0 = float(x[idx_c[0]])
            d0 = float(x[idx_d[0]])
            a_bat_lp = c0 - d0  # ∈ [-1, 1]
        else:
            a_bat_lp = 0.0

        # Clip to SOC-feasible window derived from actual env_state.soc.
        # Same (1-1e-5) relative margin as DpOraclePolicy: the LP is float64 but
        # the JAX env stores SOC in float32 — even a float64→float32 conversion
        # in a_bat * bat_power can land 1 ULP above max_P_ch.  The margin
        # (≈250 W on 50 MW, 80× float32 epsilon) absorbs that without affecting
        # the LP objective.
        soc_now    = float(env_state.soc)
        _max_P_ch  = max(0.0, (soc_max_f - soc_now) * bat_cap / eta_ch)
        _max_P_dis = max(0.0, (soc_now - soc_min_f) * bat_cap * eta_dis)
        a_ch_max   = min(1.0, _max_P_ch  * (1.0 - 1e-5) / bat_pow)
        a_dis_max  = min(1.0, _max_P_dis * (1.0 - 1e-5) / bat_pow)
        a_bat_lp   = float(np.clip(a_bat_lp, -a_dis_max, a_ch_max))

        # Apply greedy renewable routing with LP's a_bat
        greedy = GreedyPolicy()
        greedy_action = greedy.action(env_state, step_data, params)
        return greedy_action.at[0].set(jax.numpy.float32(a_bat_lp))


# ---------------------------------------------------------------------------
# Helper: accumulate infos list to PolicyEvalResult
# ---------------------------------------------------------------------------

def _infos_to_eval_result(infos) -> PolicyEvalResult:
    """Accumulate stacked EnvInfo (from lax.scan) into a PolicyEvalResult."""
    energy_cost_yuan   = float(jnp.sum(infos.c_energy_yuan))
    demand_charge_yuan = float(jnp.sum(infos.c_demand_charge_yuan))
    degradation_yuan   = float(jnp.sum(infos.c_degradation_yuan))
    curtailment_yuan   = float(jnp.sum(infos.c_curtail_yuan))
    voll_yuan          = float(jnp.sum(infos.c_voll_yuan))
    total_cost_yuan    = (
        energy_cost_yuan + demand_charge_yuan + degradation_yuan
        + curtailment_yuan + voll_yuan
    )
    soc_violations_count = int(jnp.sum(infos.soc_violation_mwh > 0))
    soc_violation_mwh    = float(jnp.sum(infos.soc_violation_mwh))
    penalty_yuan         = float(jnp.sum(infos.penalty_yuan))
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
    )


def _infos_from_list(infos_list: list) -> PolicyEvalResult:
    """Accumulate a Python list of scalar EnvInfo dicts/namedtuples into PolicyEvalResult."""
    energy_cost_yuan   = sum(float(i.c_energy_yuan)        for i in infos_list)
    demand_charge_yuan = sum(float(i.c_demand_charge_yuan) for i in infos_list)
    degradation_yuan   = sum(float(i.c_degradation_yuan)   for i in infos_list)
    curtailment_yuan   = sum(float(i.c_curtail_yuan)       for i in infos_list)
    voll_yuan          = sum(float(i.c_voll_yuan)          for i in infos_list)
    total_cost_yuan    = (
        energy_cost_yuan + demand_charge_yuan + degradation_yuan
        + curtailment_yuan + voll_yuan
    )
    soc_violations_count = sum(1 for i in infos_list if float(i.soc_violation_mwh) > 0)
    soc_violation_mwh    = sum(float(i.soc_violation_mwh) for i in infos_list)
    penalty_yuan         = sum(float(i.penalty_yuan)       for i in infos_list)
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
    )


def _run_policy_jax(policy, data, params) -> PolicyEvalResult:
    """Run a JAX-compatible policy (GreedyPolicy or DpOraclePolicy) via lax.scan."""
    from energy_go.env.jax_env import reset, step

    @jax.jit
    def _step(carry, _):
        env_state = carry
        action = policy.action(env_state, data[env_state.t], params)
        new_state, new_obs, reward, done, info = step(env_state, action, params, data)
        return new_state, info

    key = jax.random.PRNGKey(0)
    init_state, _ = reset(key, params, data)
    _, infos = jax.lax.scan(_step, init_state, None, length=params.episode_len)
    return _infos_to_eval_result(infos)


def _run_policy_mpc(policy, data, params) -> PolicyEvalResult:
    """Run MpcPolicy via a Python loop (scipy LP cannot be jitted)."""
    from energy_go.env.jax_env import reset, step as env_step

    key = jax.random.PRNGKey(0)
    env_state, _ = reset(key, params, data)

    infos_list = []
    for _t in range(int(params.episode_len)):
        action_np = policy.action(env_state, data[env_state.t], data, params)
        action_jnp = jnp.array(action_np, dtype=jnp.float32)
        new_state, _, _, _, info = env_step(env_state, action_jnp, params, data)
        infos_list.append(info)
        env_state = new_state

    return _infos_from_list(infos_list)


# ---------------------------------------------------------------------------
# §11 entry point
# ---------------------------------------------------------------------------

def run_benchmark(
    policy_name: str,
    data,
    params=None,
) -> PolicyEvalResult:
    """Run one §11 benchmark baseline over the full eval year.

    Args:
        policy_name: "greedy" | "dp_oracle" | "mpc"
        data:        array shape (>=episode_len, 4) — synthetic year data
        params:      EnvParams | None — None → Gansu defaults (episode_len=8760)

    Returns:
        PolicyEvalResult with real-money cost breakdown.

    Raises:
        ValueError for unknown policy_name.
    """
    from energy_go.env.jax_env import EnvParams

    if policy_name not in ("greedy", "dp_oracle", "mpc"):
        raise ValueError(
            f"Unknown policy_name {policy_name!r}. Use 'greedy', 'dp_oracle', or 'mpc'."
        )
    if params is None:
        params = EnvParams(episode_len=8760)

    if policy_name == "greedy":
        policy = GreedyPolicy()
        return _run_policy_jax(policy, data, params)
    elif policy_name == "dp_oracle":
        policy = DpOraclePolicy.from_data(data, params)
        return _run_policy_jax(policy, data, params)
    else:  # mpc
        policy = MpcPolicy()
        return _run_policy_mpc(policy, data, params)
