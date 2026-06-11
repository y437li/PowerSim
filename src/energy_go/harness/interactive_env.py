"""energy_go.harness.interactive_env — single-step debugging interface.

Contract: contracts/harness/env_harness.md §5.1
Wraps energy_go.env.jax_env.step(); exposes every internal quantity via StepInspection.
"""
from __future__ import annotations

from typing import Sequence

import jax
import jax.numpy as jnp
import numpy as np

from energy_go.env import jax_env
from energy_go.harness.types import StepInspection

# ---------------------------------------------------------------------------
# Module-level JIT functions — one compilation shared across all instances.
#
# Capturing params/data as closure constants (jax.jit(lambda: f(…, data)))
# forces a full XLA recompile per InteractiveEnv instance because each new data
# array becomes a distinct compile-time constant.  Passing them as explicit
# arguments lets JAX reuse the single compiled kernel for any (params, data)
# with the same shapes/dtypes — critical for CI where jax[cpu] is slow.
# ---------------------------------------------------------------------------

_STEP_JIT = jax.jit(jax_env.step)
_GET_OBS_JIT = jax.jit(jax_env.get_obs)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONSERVATION_TOL = 1e-3  # 1 kW in MW units

# Action clip bounds: (low, high) per dimension
_ACTION_BOUNDS = [(-1.0, 1.0)] + [(0.0, 1.0)] * 5

# Tariff tier lookup from price_buy (nearest 10 ¥/MWh)
_TIER_MAP = {
    250: "valley",
    450: "mid",
    620: "peak",
    780: "critical_peak",
}


def _tariff_tier(price_buy: float) -> str:
    """Determine tariff tier string from price_buy."""
    rounded = round(price_buy / 10.0) * 10
    return _TIER_MAP.get(rounded, "peak")


# ---------------------------------------------------------------------------
# InteractiveEnv
# ---------------------------------------------------------------------------

class InteractiveEnv:
    """Debugging interface for the JAX env core.

    Wraps jax_env.step() with full StepInspection output including every
    intermediate quantity, conservation checks, and constraint flags.
    """

    def __init__(
        self,
        params: jax_env.EnvParams,
        data: jax.Array,
    ) -> None:
        self._params = params
        self._data = jnp.asarray(data, dtype=jnp.float32)
        # Module-level _STEP_JIT / _GET_OBS_JIT are shared across all instances.

    # ------------------------------------------------------------------
    # Public API (§5.1 contract)
    # ------------------------------------------------------------------

    def make_state(
        self,
        soc: float,
        t: int,
        month_peak_mw: float = 0.0,
        seed: int = 0,
    ) -> jax_env.EnvState:
        """Construct an explicit EnvState.

        Raises:
            ValueError: if soc ∉ [params.soc_min, params.soc_max]
            ValueError: if t ∉ [0, 8759]
            ValueError: if month_peak_mw < 0
        """
        soc_min = float(self._params.soc_min)
        soc_max = float(self._params.soc_max)
        if soc < soc_min - 1e-9 or soc > soc_max + 1e-9:
            raise ValueError(
                f"soc={soc!r} is outside valid range [{soc_min}, {soc_max}]"
            )
        if t < 0 or t > 8759:
            raise ValueError(f"t={t!r} is outside valid range [0, 8759]")
        if month_peak_mw < 0.0:
            raise ValueError(f"month_peak_mw={month_peak_mw!r} must be >= 0")
        return jax_env.EnvState(
            soc=jnp.float32(soc),
            month_peak=jnp.float32(month_peak_mw),
            t=jnp.int32(t),
            rng=jax.random.PRNGKey(seed),
        )

    def step(
        self,
        state: jax_env.EnvState,
        action: Sequence[float],
    ) -> StepInspection:
        """Apply one env step and return full StepInspection.

        Raises:
            ValueError: if len(action) != 6
        """
        insp, _new_state = self._step_impl(state, action)
        return insp

    def get_obs(
        self,
        state: jax_env.EnvState,
    ) -> list:
        """Compute observation for state without stepping (length 107)."""
        obs = _GET_OBS_JIT(state, self._params, self._data)
        return [float(v) for v in obs]

    def reset(
        self,
        seed: int = 0,
    ) -> tuple:
        """Full env reset using jax_env.reset. Returns (state, obs)."""
        key = jax.random.PRNGKey(seed)
        state, obs = jax_env.reset(key, self._params, self._data)
        return state, [float(v) for v in obs]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _step_raw(
        self,
        state: jax_env.EnvState,
        action: Sequence[float],
    ) -> tuple:
        """Apply one env step and return (new_state, StepInspection).

        Uses a single JAX kernel call. Used internally by ScenarioReplay and
        RunManager to chain steps without redundant compilation.

        Raises:
            ValueError: if len(action) != 6
        """
        insp, new_state = self._step_impl(state, action)
        return new_state, insp

    def _step_impl(
        self,
        state: jax_env.EnvState,
        action: Sequence[float],
    ) -> tuple:
        """Core step: single JIT call → (StepInspection, new_state).

        Called by both step() and _step_raw() so the JAX kernel runs exactly once.
        """
        if len(action) != 6:
            raise ValueError(
                f"action must have length 6, got {len(action)}"
            )
        action_raw = [float(a) for a in action]

        # Clip action to bounds
        action_clipped = [
            float(np.clip(action_raw[i], lo, hi))
            for i, (lo, hi) in enumerate(_ACTION_BOUNDS)
        ]
        constraint_action_clipped = any(
            abs(action_raw[i] - action_clipped[i]) > 1e-9 for i in range(6)
        )

        # Battery commanded power (before SOC cap)
        a_bat = action_clipped[0]
        bat_power_mw = float(self._params.bat_power_mw)
        if a_bat >= 0.0:
            p_bat_commanded_ch_mw = a_bat * bat_power_mw
            p_bat_commanded_dis_mw = 0.0
        else:
            p_bat_commanded_ch_mw = 0.0
            p_bat_commanded_dis_mw = abs(a_bat) * bat_power_mw

        # Single JIT call — the only JAX kernel invocation for this step.
        # Uses module-level _STEP_JIT (shared across all instances) to avoid
        # per-instance XLA recompilation on CI.
        action_jax = jnp.array(action_clipped, dtype=jnp.float32)
        new_state, obs_arr, reward_arr, done_arr, info = _STEP_JIT(
            state, action_jax, self._params, self._data
        )

        def f(x) -> float:
            return float(jnp.asarray(x))

        # Tariff tier
        price_buy = f(info.price_buy_yuan_per_mwh)
        tier = _tariff_tier(price_buy)

        # Read renewable + battery discharge for conservation checks below
        p_pv = f(info.p_pv_mw)
        p_wind = f(info.p_wind_mw)
        p_bat_dis = f(info.p_bat_dis_mw)

        load_mw_val = float(self._data[int(state.t), 3])

        # Load cap constraint: derived directly from EnvInfo signal (§1 no-recompute rule)
        constraint_load_capped = bool(info.load_capped)

        # Export cap: non-zero curtailment (sum of exposed per-source curtailment fields)
        total_curtailed = (
            f(info.p_sol_curtailed_mw)
            + f(info.p_wind_curtailed_mw)
            + f(info.p_bat_curtailed_mw)
        )
        constraint_export_capped = total_curtailed > _CONSERVATION_TOL

        # Import cap: load unserved OR cap reduced grid_to_bat with load fully served
        constraint_import_capped = (
            f(info.p_load_unserved_mw) > _CONSERVATION_TOL
            or bool(info.import_cap_active)
        )

        # SOC violation
        constraint_soc_clipped = f(info.soc_violation_mwh) > 0.0

        # Per-source conservation checks
        solar_sum = (
            f(info.p_sol_to_load_mw)
            + f(info.p_sol_to_bat_mw)
            + f(info.p_sol_to_grid_mw)
            + f(info.p_sol_curtailed_mw)
        )
        solar_conservation_ok = abs(solar_sum - p_pv) < _CONSERVATION_TOL

        wind_sum = (
            f(info.p_wind_to_load_mw)
            + f(info.p_wind_to_bat_mw)
            + f(info.p_wind_to_grid_mw)
            + f(info.p_wind_curtailed_mw)
        )
        wind_conservation_ok = abs(wind_sum - p_wind) < _CONSERVATION_TOL

        bat_to_load = f(info.p_bat_to_load_mw)
        bat_to_grid = f(info.p_bat_to_grid_mw)
        bat_curtailed = f(info.p_bat_curtailed_mw)
        bat_sum = bat_to_load + bat_to_grid + bat_curtailed
        bat_conservation_ok = abs(bat_sum - p_bat_dis) < _CONSERVATION_TOL

        # Costs — pre-extract as Python floats so D13 identities hold exactly.
        # Module-level JIT uses abstract XLA tracing whose float32 op-ordering
        # differs from the Python sums the tests check.  Computing the totals as
        # pure Python sums guarantees bit-exact agreement.
        c_import_yuan = f(info.c_import_yuan)
        r_export_yuan = f(info.r_export_yuan)
        c_energy_yuan = f(info.c_energy_yuan)
        c_demand_shape_yuan = f(info.c_demand_shape_yuan)
        c_demand_charge_yuan = f(info.c_demand_charge_yuan)
        c_degradation_yuan = f(info.c_degradation_yuan)
        c_curtail_yuan = f(info.c_curtail_yuan)
        c_voll_yuan = f(info.c_voll_yuan)
        # D13: real = c_energy + c_demand_charge + c_deg + c_curtail + c_voll
        cost_total_real_yuan = (
            c_energy_yuan + c_demand_charge_yuan + c_degradation_yuan
            + c_curtail_yuan + c_voll_yuan
        )
        # D13: reward_basis = c_energy + 2·c_demand_shape + c_deg + c_curtail + c_voll
        cost_total_reward_basis_yuan = (
            c_energy_yuan + 2.0 * c_demand_shape_yuan + c_degradation_yuan
            + c_curtail_yuan + c_voll_yuan
        )

        insp = StepInspection(
            # Input state
            soc_in=float(state.soc),
            t_in=int(state.t),
            month_peak_in_mw=float(state.month_peak),
            # Action
            action_raw=action_raw,
            action_clipped=action_clipped,
            # Renewables
            p_pv_mw=p_pv,
            p_wind_mw=p_wind,
            # Battery
            p_bat_commanded_ch_mw=p_bat_commanded_ch_mw,
            p_bat_commanded_dis_mw=p_bat_commanded_dis_mw,
            p_bat_ch_mw=f(info.p_bat_ch_mw),
            p_bat_dis_mw=p_bat_dis,
            soc_out=float(new_state.soc),
            soc_violation_mwh=f(info.soc_violation_mwh),
            # Per-source flows
            solar_to_load_mw=f(info.p_sol_to_load_mw),
            solar_to_bat_mw=f(info.p_sol_to_bat_mw),
            solar_to_grid_mw=f(info.p_sol_to_grid_mw),
            solar_curtailed_mw=f(info.p_sol_curtailed_mw),
            wind_to_load_mw=f(info.p_wind_to_load_mw),
            wind_to_bat_mw=f(info.p_wind_to_bat_mw),
            wind_to_grid_mw=f(info.p_wind_to_grid_mw),
            wind_curtailed_mw=f(info.p_wind_curtailed_mw),
            bat_to_load_mw=bat_to_load,
            bat_to_grid_mw=bat_to_grid,
            bat_curtailed_mw=bat_curtailed,
            grid_to_load_mw=f(info.p_grid_to_load_mw),
            grid_to_bat_mw=f(info.p_grid_to_bat_mw),
            load_unserved_mw=f(info.p_load_unserved_mw),
            # Aggregate PCC
            p_export_mw=f(info.p_export_mw),
            p_import_mw=f(info.p_import_mw),
            load_mw=load_mw_val,
            max_export_mw=float(self._params.grid_max_export_mw),
            max_import_mw=float(self._params.grid_max_import_mw),
            # Time
            hour_of_day=int(state.t) % 24,
            tariff_tier=tier,
            # Prices
            price_buy_yuan_per_mwh=price_buy,
            price_sell_yuan_per_mwh=f(info.price_sell_yuan_per_mwh),
            # Costs (pre-extracted above for exact D13 identity)
            c_import_yuan=c_import_yuan,
            r_export_yuan=r_export_yuan,
            c_energy_yuan=c_energy_yuan,
            c_demand_shape_yuan=c_demand_shape_yuan,
            c_demand_charge_yuan=c_demand_charge_yuan,
            c_degradation_yuan=c_degradation_yuan,
            c_curtail_yuan=c_curtail_yuan,
            c_voll_yuan=c_voll_yuan,
            penalty_yuan=f(info.penalty_yuan),
            demand_rate_yuan_per_mw_month=float(
                self._params.demand_rate_yuan_per_mw_month
            ),
            cost_total_real_yuan=cost_total_real_yuan,
            cost_total_reward_basis_yuan=cost_total_reward_basis_yuan,
            # Reward
            reward=float(reward_arr),
            # Output state
            month_peak_out_mw=float(new_state.month_peak),
            t_out=int(new_state.t),
            done=bool(done_arr),
            # Observation
            obs=[float(v) for v in obs_arr],
            # Constraint flags
            constraint_action_clipped=constraint_action_clipped,
            constraint_soc_clipped=constraint_soc_clipped,
            constraint_load_capped=constraint_load_capped,
            constraint_export_capped=constraint_export_capped,
            constraint_import_capped=constraint_import_capped,
            # Conservation
            solar_conservation_ok=solar_conservation_ok,
            wind_conservation_ok=wind_conservation_ok,
            bat_conservation_ok=bat_conservation_ok,
        )
        return insp, new_state
