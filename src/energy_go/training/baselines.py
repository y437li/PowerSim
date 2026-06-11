"""§5 baseline policies — NoBatteryPolicy and TouPolicy — §7 of training_pipeline contract.

Both baselines are JAX-native and run in the same JAX env for a fair comparison.
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
