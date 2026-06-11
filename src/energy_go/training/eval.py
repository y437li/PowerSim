"""Deterministic full-year eval loop — §8 of training_pipeline contract.

run_eval() rolls out the policy over 8760 steps, reports real-money costs from
EnvInfo (D13 real-money basis), and does NOT update obs_stats (frozen during eval).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

import jax
import jax.numpy as jnp

from energy_go.training.normalizer import normalize_obs

if TYPE_CHECKING:
    from energy_go.training.checkpoint_format import CheckpointData


@dataclass
class PolicyEvalResult:
    """Real-money cost breakdown over a full evaluation year — §8.

    All ¥ fields are real money (cost_total_real_yuan basis, D13).
    Additive identity:
        total_cost_yuan = energy_cost_yuan + demand_charge_yuan
                        + degradation_yuan + curtailment_yuan + voll_yuan

    SOC/penalty fields are safety/reporting metrics; NOT in total_cost_yuan.
    """
    energy_cost_yuan:     float   # Σ c_energy_yuan over 8760 steps (§3.4)
    demand_charge_yuan:   float   # Σ c_demand_charge_yuan (month-boundary steps, D10)
    degradation_yuan:     float   # Σ c_degradation_yuan
    curtailment_yuan:     float   # Σ c_curtail_yuan
    voll_yuan:            float   # Σ c_voll_yuan
    total_cost_yuan:      float   # = sum of the 5 above (must satisfy additive identity)
    soc_violations_count: int     # steps where soc_violation_mwh > 0
    soc_violation_mwh:    float   # total SOC overshoot energy (MWh)
    penalty_yuan:         float   # total reward-shaping penalty (NOT in total_cost_yuan)


def _actor_forward(params: dict, norm_obs: jax.Array) -> tuple[jax.Array, jax.Array]:
    """Pure-JAX 2-hidden-layer MLP actor forward pass.

    Uses params keys:  fc1_w, fc1_b, fc2_w, fc2_b, out_w, out_b
    Returns: (mean (6,), log_std_raw (6,))
    """
    h = jnp.maximum(0.0, norm_obs @ params["fc1_w"] + params["fc1_b"])  # ReLU
    h = jnp.maximum(0.0, h        @ params["fc2_w"] + params["fc2_b"])  # ReLU
    out = h @ params["out_w"] + params["out_b"]                          # (12,)
    mean       = out[:6]    # first 6 = mean per action dim
    log_std_raw = out[6:]   # last  6 = log_std before clipping
    return mean, log_std_raw


def _deterministic_action(params: dict, norm_obs: jax.Array) -> jax.Array:
    """Per-component squash of actor mean — §5.2 / §8.1.

    action[0]   = tanh(mean[0])       a_bat  ∈ (-1, 1)
    action[1:6] = sigmoid(mean[1:6])  fractions ∈ (0, 1)
    """
    mean, _ = _actor_forward(params, norm_obs)
    a_bat     = jnp.tanh(mean[:1])            # (1,)
    fractions = jax.nn.sigmoid(mean[1:])      # (5,)
    return jnp.concatenate([a_bat, fractions])  # (6,)


def run_eval(
    checkpoint: "CheckpointData",
    data: object,
    params=None,
) -> PolicyEvalResult:
    """Deterministic policy rollout over the full 8760-step year — §8.

    - Uses actor weights and obs_stats from checkpoint.
    - Normalises obs using FROZEN obs_stats (no stat updates during eval).
    - Reports RAW (un-normalised) real-money costs from EnvInfo.
    - eval_episode_len = 8760; no episode resets (the year runs to completion).
    - EnvParams.episode_len = 8760 so done fires only at t=8759.

    Args:
        checkpoint: CheckpointData — actor weights + obs_stats from save_checkpoint/load_checkpoint
        data:       SyntheticYear  — same synthetic year used for training
        params:     EnvParams | None — None → Gansu defaults

    Returns:
        PolicyEvalResult with real-money cost breakdown.
    """
    from energy_go.env.jax_env import EnvParams, reset, step, get_obs  # D22b import path

    env_params = params if params is not None else EnvParams(episode_len=8760)

    # Build actor params dict from checkpoint numpy arrays
    actor_params = {
        "fc1_w": jnp.array(checkpoint.actor_fc1_w),
        "fc1_b": jnp.array(checkpoint.actor_fc1_b),
        "fc2_w": jnp.array(checkpoint.actor_fc2_w),
        "fc2_b": jnp.array(checkpoint.actor_fc2_b),
        "out_w": jnp.array(checkpoint.actor_out_w),
        "out_b": jnp.array(checkpoint.actor_out_b),
    }

    # Freeze obs_stats from checkpoint (NOT updated during eval)
    import numpy as np
    from energy_go.training.normalizer import RunningStats
    obs_stats = RunningStats(
        mean  = jnp.array(checkpoint.obs_mean),
        var   = jnp.array(checkpoint.obs_var),
        count = jnp.int32(checkpoint.obs_count),
    )
    obs_clip = float(checkpoint.obs_clip)

    # Deterministic rollout — jit-compiled step function
    @jax.jit
    def _step(carry, _):
        env_state = carry
        raw_obs = get_obs(env_state, env_params, data)  # §5.4: obs from input state
        norm_obs = normalize_obs(raw_obs, obs_stats, clip=obs_clip)
        action = _deterministic_action(actor_params, norm_obs)
        new_state, new_obs, reward, done, info = step(env_state, action, env_params, data)
        return new_state, info

    # Reset to start of year (t=0)
    key = jax.random.PRNGKey(0)  # deterministic: same key every eval
    init_state, _ = reset(key, env_params, data)

    # Scan over 8760 steps
    _, infos = jax.lax.scan(_step, init_state, None, length=8760)

    # Accumulate costs from EnvInfo (real-money basis, D13)
    energy_cost_yuan   = float(jnp.sum(infos.c_energy_yuan))
    demand_charge_yuan = float(jnp.sum(infos.c_demand_charge_yuan))
    degradation_yuan   = float(jnp.sum(infos.c_degradation_yuan))
    curtailment_yuan   = float(jnp.sum(infos.c_curtail_yuan))
    voll_yuan          = float(jnp.sum(infos.c_voll_yuan))
    total_cost_yuan    = (
        energy_cost_yuan + demand_charge_yuan + degradation_yuan
        + curtailment_yuan + voll_yuan
    )

    # SOC violations (safety metric, not in total_cost)
    soc_violations_count = int(jnp.sum(infos.soc_violation_mwh > 0))
    soc_violation_mwh    = float(jnp.sum(infos.soc_violation_mwh))

    # Penalty (reward-shaping, not in total_cost, D13).
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
