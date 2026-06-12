"""Deterministic full-year eval loop — §8 of training_pipeline contract.

run_eval() rolls out the policy over 8760 steps, reports real-money costs from
EnvInfo (D13 real-money basis), and does NOT update obs_stats (frozen during eval).

Extended in task #55: PolicyEvalResult gains per-stream StreamAccumulator dict
(6 rev4 streams, all pre-declared) plus physical-quantity and per-source MWh
accumulators for workstream D project finance (LCOE/LCOS/OPEX inputs).
Contract: contracts/training/eval_result_extended.md
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

import numpy as np

if TYPE_CHECKING:
    import jax
    from energy_go.training.checkpoint_format import CheckpointData


# ---------------------------------------------------------------------------
# StreamAccumulator — 2-leaf NamedTuple (rl-architect D31/F1 ruling, PR #82)
# ---------------------------------------------------------------------------

class StreamAccumulator(NamedTuple):
    """Per-stream annual accumulator for workstream D project finance.

    volume:
        Physical volume. Units are stream-specific:
          grid_export / grid_import → MWh (Δt=1h, D3)
          demand_charge             → MW (annual peak, D31/F1)
          h2_sale / avoided_cost / token_sale → MWh when activated; 0.0 in v1
        Always ≥ 0.

    value_yuan:
        Real year-1 ¥ magnitude (D31/F1 constant-real-price; escalation is
        finance-layer post-eval).  Always ≥ 0.
        Sign convention: finance applies cash-flow signs by stream type.
          inflow (+): grid_export, h2_sale, token_sale, avoided_cost
          outflow (−): grid_import, demand_charge
    """
    volume:     float
    value_yuan: float


# ---------------------------------------------------------------------------
# PolicyEvalResult — 32 fields (9 wire-locked + 23 new)
# ---------------------------------------------------------------------------

@dataclass
class PolicyEvalResult:
    """Real-money cost breakdown over a full evaluation year — §8.

    All ¥ fields are real money (cost_total_real_yuan basis, D13).
    Additive identity (existing 5 cost fields):
        total_cost_yuan = energy_cost_yuan + demand_charge_yuan
                        + degradation_yuan + curtailment_yuan + voll_yuan

    SOC/penalty fields are safety/reporting metrics; NOT in total_cost_yuan.

    Extended fields (task #55, contract eval_result_extended.md):
      streams          — 6-key StreamAccumulator dict (all rev4 streams)
      *_mwh            — physical-quantity + per-source accumulators for finance

    Wire isolation: _policy_dict() in telemetry.py explicitly enumerates only
    the 9 LOCKED keys below; new fields can NEVER leak to the eval_compare wire.
    """
    # -----------------------------------------------------------------------
    # EXISTING 9 FIELDS — WIRE-LOCKED (eval_compare payload, D13 real money)
    # _policy_dict() in telemetry.py serialises ONLY these 9 to the wire.
    # DO NOT REMOVE or RENAME any of these.
    # -----------------------------------------------------------------------
    energy_cost_yuan:     float   # Σ c_energy_yuan over 8760 steps (§3.4)
    demand_charge_yuan:   float   # Σ c_demand_charge_yuan (month-boundary steps, D10)
    degradation_yuan:     float   # Σ c_degradation_yuan
    curtailment_yuan:     float   # Σ c_curtail_yuan
    voll_yuan:            float   # Σ c_voll_yuan
    total_cost_yuan:      float   # = sum of the 5 above (must satisfy additive identity)
    soc_violations_count: int     # steps where soc_violation_mwh > 0
    soc_violation_mwh:    float   # total SOC overshoot energy (MWh)
    penalty_yuan:         float   # total reward-shaping penalty (NOT in total_cost_yuan)

    # -----------------------------------------------------------------------
    # NEW: 6-stream keyed dict — all rev4 streams pre-declared
    # Fixed keys: grid_export, grid_import, demand_charge,
    #             h2_sale, avoided_cost, token_sale
    # v1 active: grid_export, grid_import, demand_charge
    # v1 zero placeholders: h2_sale, avoided_cost, token_sale
    # -----------------------------------------------------------------------
    streams: dict  # dict[str, StreamAccumulator]

    # -----------------------------------------------------------------------
    # NEW: physical-quantity accumulators (MWh) — required by finance for
    # LCOE/LCOS/OPEX/replacement.  Δt=1h (D3) → Σ p_X_mw = MWh.  All ≥ 0.
    # -----------------------------------------------------------------------
    generation_mwh:     float   # Σ (p_wind_mw + p_pv_mw)  ← LCOE denominator
    wind_generated_mwh: float   # Σ p_wind_mw
    pv_generated_mwh:   float   # Σ p_pv_mw
    bat_charge_mwh:     float   # Σ (wind_to_bat + pv_to_bat + grid_to_bat)
    bat_discharge_mwh:  float   # Σ (bat_to_load + bat_to_grid + bat_curtailed)  ← LCOS denominator
    bat_throughput_mwh: float   # bat_charge + bat_discharge  ← VarOM / cycle-life
    load_served_mwh:    float   # Σ (wind_to_load + pv_to_load + bat_to_load + grid_to_load)
    load_unserved_mwh:  float   # Σ p_load_unserved_mw  ← INV-VOLL reliability
    curtailed_mwh:      float   # Σ p_curtailed_mw  ← INV-CURT

    # -----------------------------------------------------------------------
    # NEW: per-source flow breakdown (13 fields, MWh = MW × 1h per step)
    # Conservation identities:
    #   wind_generated = wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed
    #   pv_generated   = pv_to_load   + pv_to_bat   + pv_to_grid   + pv_curtailed
    #   bat_discharge  = bat_to_load  + bat_to_grid  + bat_curtailed
    #   grid_import.volume = grid_to_bat + grid_to_load  (§3.6 F-IMPORT)
    # All ≥ 0.
    # -----------------------------------------------------------------------
    wind_to_load_mwh:   float   # Σ p_wind_to_load_mw
    wind_to_bat_mwh:    float   # Σ p_wind_to_bat_mw
    wind_to_grid_mwh:   float   # Σ p_wind_to_grid_mw
    wind_curtailed_mwh: float   # Σ p_wind_curtailed_mw
    pv_to_load_mwh:     float   # Σ p_sol_to_load_mw  (EnvInfo naming: "sol")
    pv_to_bat_mwh:      float   # Σ p_sol_to_bat_mw
    pv_to_grid_mwh:     float   # Σ p_sol_to_grid_mw
    pv_curtailed_mwh:   float   # Σ p_sol_curtailed_mw
    bat_to_load_mwh:    float   # Σ p_bat_to_load_mw
    bat_to_grid_mwh:    float   # Σ p_bat_to_grid_mw
    bat_curtailed_mwh:  float   # Σ p_bat_curtailed_mw
    grid_to_bat_mwh:    float   # Σ p_grid_to_bat_mw
    grid_to_load_mwh:   float   # Σ p_grid_to_load_mw


# ---------------------------------------------------------------------------
# Private helpers — called post-scan in run_eval()
# ---------------------------------------------------------------------------

_ZERO_STREAM = StreamAccumulator(volume=0.0, value_yuan=0.0)
_DORMANT_KEYS = ("h2_sale", "avoided_cost", "token_sale")


def _build_streams(infos, params) -> "dict[str, StreamAccumulator]":
    """Build the 6-key streams dict from per-step EnvInfo batch and EnvParams.

    Called once after jax.lax.scan on the (8760,)-shaped infos batch.
    Works with both JAX and numpy arrays (used in tests with numpy mocks).
    Uses np.sum/np.max which accept both numpy and JAX arrays via __array__.

    demand_charge.volume = annual peak MW = max(c_demand_charge_yuan) / demand_rate.
    h2_sale / avoided_cost / token_sale = zero placeholders in v1.
    Pure accumulation — no new physics.

    Args:
        infos:  EnvInfo with (T,)-shaped array fields (T = eval episode length).
        params: EnvParams-like object with demand_rate_yuan_per_mw_month field.

    Returns:
        dict[str, StreamAccumulator] with exactly the 6 rev4 keys.
    """
    demand_rate = float(params.demand_rate_yuan_per_mw_month)
    peak_booking = float(np.max(infos.c_demand_charge_yuan))
    # D31/F1: annual peak = max single-step booking / rate (not Σ monthly peaks)
    peak_mw = (peak_booking / demand_rate) if demand_rate != 0.0 else 0.0

    return {
        "grid_export": StreamAccumulator(
            volume    = float(np.sum(infos.p_export_mw)),
            value_yuan= float(np.sum(infos.r_export_yuan)),
        ),
        "grid_import": StreamAccumulator(
            volume    = float(np.sum(infos.p_import_mw)),
            value_yuan= float(np.sum(infos.c_import_yuan)),
        ),
        "demand_charge": StreamAccumulator(
            volume    = peak_mw,
            value_yuan= float(np.sum(infos.c_demand_charge_yuan)),
        ),
        # v1 zero placeholders — pre-declared so future activation needs no structural change
        "h2_sale":      _ZERO_STREAM,
        "avoided_cost": _ZERO_STREAM,
        "token_sale":   _ZERO_STREAM,
    }


def _accumulate_physical_quantities(infos) -> "dict[str, float]":
    """Accumulate (T,)-shaped EnvInfo batch into 22 physical-quantity totals.

    Called once after jax.lax.scan on the (8760,)-shaped infos batch.
    Works with both JAX and numpy arrays.

    Returns exactly 22 keys:
      9 aggregate  (generation_mwh, wind_generated_mwh, pv_generated_mwh,
                    bat_charge_mwh, bat_discharge_mwh, bat_throughput_mwh,
                    load_served_mwh, load_unserved_mwh, curtailed_mwh)
      13 per-source (wind × 4, pv × 4, bat × 3, grid × 2)

    Battery charge/discharge are accumulated from per-source paths rather than
    the aggregate p_bat_ch_mw / p_bat_dis_mw fields — the per-source sums equal
    the aggregates by conservation, and are robust to test mocks that set them
    independently.

    Pure accumulation — no new physics.
    """
    # np.sum/np.max work for both numpy and JAX arrays (via __array__ protocol)
    s = np.sum

    # Battery charge: total power flowing INTO the battery each step
    bat_charge_mwh = float(s(
        infos.p_wind_to_bat_mw
        + infos.p_sol_to_bat_mw
        + infos.p_grid_to_bat_mw
    ))

    # Battery discharge: total power flowing OUT OF the battery each step
    bat_discharge_mwh = float(s(
        infos.p_bat_to_load_mw
        + infos.p_bat_to_grid_mw
        + infos.p_bat_curtailed_mw
    ))

    # Load served: sum of all paths delivering power to load each step
    load_served_mwh = float(s(
        infos.p_wind_to_load_mw
        + infos.p_sol_to_load_mw
        + infos.p_bat_to_load_mw
        + infos.p_grid_to_load_mw
    ))

    wind_generated_mwh = float(s(infos.p_wind_mw))
    pv_generated_mwh   = float(s(infos.p_pv_mw))

    return {
        # ---- 9 aggregate physical-quantity fields ----
        "generation_mwh":     wind_generated_mwh + pv_generated_mwh,
        "wind_generated_mwh": wind_generated_mwh,
        "pv_generated_mwh":   pv_generated_mwh,
        "bat_charge_mwh":     bat_charge_mwh,
        "bat_discharge_mwh":  bat_discharge_mwh,
        "bat_throughput_mwh": bat_charge_mwh + bat_discharge_mwh,
        "load_served_mwh":    load_served_mwh,
        "load_unserved_mwh":  float(s(infos.p_load_unserved_mw)),
        "curtailed_mwh":      float(s(infos.p_curtailed_mw)),
        # ---- 13 per-source breakdown fields ----
        "wind_to_load_mwh":   float(s(infos.p_wind_to_load_mw)),
        "wind_to_bat_mwh":    float(s(infos.p_wind_to_bat_mw)),
        "wind_to_grid_mwh":   float(s(infos.p_wind_to_grid_mw)),
        "wind_curtailed_mwh": float(s(infos.p_wind_curtailed_mw)),
        "pv_to_load_mwh":     float(s(infos.p_sol_to_load_mw)),   # "sol" in EnvInfo
        "pv_to_bat_mwh":      float(s(infos.p_sol_to_bat_mw)),
        "pv_to_grid_mwh":     float(s(infos.p_sol_to_grid_mw)),
        "pv_curtailed_mwh":   float(s(infos.p_sol_curtailed_mw)),
        "bat_to_load_mwh":    float(s(infos.p_bat_to_load_mw)),
        "bat_to_grid_mwh":    float(s(infos.p_bat_to_grid_mw)),
        "bat_curtailed_mwh":  float(s(infos.p_bat_curtailed_mw)),
        "grid_to_bat_mwh":    float(s(infos.p_grid_to_bat_mw)),
        "grid_to_load_mwh":   float(s(infos.p_grid_to_load_mw)),
    }


def result_to_physical_quantities_entry(result: PolicyEvalResult) -> dict:
    """Serialise the physical_quantities section for one policy in eval_results.json.

    Produces the per-policy entry for the `physical_quantities.{policy}` key.
    The caller assembles the full eval_results.json dict.

    Returns a JSON-serializable dict with `streams` (6-key dict) plus 22 flat
    MWh fields.
    """
    return {
        "streams": {
            k: {"volume": v.volume, "value_yuan": v.value_yuan}
            for k, v in result.streams.items()
        },
        # 9 aggregate
        "generation_mwh":     result.generation_mwh,
        "wind_generated_mwh": result.wind_generated_mwh,
        "pv_generated_mwh":   result.pv_generated_mwh,
        "bat_charge_mwh":     result.bat_charge_mwh,
        "bat_discharge_mwh":  result.bat_discharge_mwh,
        "bat_throughput_mwh": result.bat_throughput_mwh,
        "load_served_mwh":    result.load_served_mwh,
        "load_unserved_mwh":  result.load_unserved_mwh,
        "curtailed_mwh":      result.curtailed_mwh,
        # 13 per-source
        "wind_to_load_mwh":   result.wind_to_load_mwh,
        "wind_to_bat_mwh":    result.wind_to_bat_mwh,
        "wind_to_grid_mwh":   result.wind_to_grid_mwh,
        "wind_curtailed_mwh": result.wind_curtailed_mwh,
        "pv_to_load_mwh":     result.pv_to_load_mwh,
        "pv_to_bat_mwh":      result.pv_to_bat_mwh,
        "pv_to_grid_mwh":     result.pv_to_grid_mwh,
        "pv_curtailed_mwh":   result.pv_curtailed_mwh,
        "bat_to_load_mwh":    result.bat_to_load_mwh,
        "bat_to_grid_mwh":    result.bat_to_grid_mwh,
        "bat_curtailed_mwh":  result.bat_curtailed_mwh,
        "grid_to_bat_mwh":    result.grid_to_bat_mwh,
        "grid_to_load_mwh":   result.grid_to_load_mwh,
    }


# ---------------------------------------------------------------------------
# Actor helpers — defined inside run_eval() so JAX is only needed there.
# These are module-level helpers for readability; they use `jnp` which is
# passed in as an argument from run_eval's local scope.
# ---------------------------------------------------------------------------

def _actor_forward(jnp, params: dict, norm_obs) -> tuple:
    """Pure-JAX 2-hidden-layer MLP actor forward pass.

    Uses params keys:  fc1_w, fc1_b, fc2_w, fc2_b, out_w, out_b
    Returns: (mean (6,), log_std_raw (6,))
    """
    h = jnp.maximum(0.0, norm_obs @ params["fc1_w"] + params["fc1_b"])  # ReLU
    h = jnp.maximum(0.0, h        @ params["fc2_w"] + params["fc2_b"])  # ReLU
    out = h @ params["out_w"] + params["out_b"]                          # (12,)
    mean        = out[:6]   # first 6 = mean per action dim
    log_std_raw = out[6:]   # last  6 = log_std before clipping
    return mean, log_std_raw


def _deterministic_action(jax, jnp, params: dict, norm_obs):
    """Per-component squash of actor mean — §5.2 / §8.1.

    action[0]   = tanh(mean[0])       a_bat  ∈ (-1, 1)
    action[1:6] = sigmoid(mean[1:6])  fractions ∈ (0, 1)
    """
    mean, _ = _actor_forward(jnp, params, norm_obs)
    a_bat     = jnp.tanh(mean[:1])             # (1,)
    fractions = jax.nn.sigmoid(mean[1:])       # (5,)
    return jnp.concatenate([a_bat, fractions])  # (6,)


# ---------------------------------------------------------------------------
# run_eval — extended to populate all 32 fields
# ---------------------------------------------------------------------------

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

    Extended fields (task #55):
    - streams dict (6 rev4 keys) via _build_streams(infos, env_params)
    - physical-qty + per-source MWh via _accumulate_physical_quantities(infos)

    Args:
        checkpoint: CheckpointData — actor weights + obs_stats from save_checkpoint/load_checkpoint
        data:       SyntheticYear  — same synthetic year used for training
        params:     EnvParams | None — None → Gansu defaults

    Returns:
        PolicyEvalResult with real-money cost breakdown + streams + physical quantities.
    """
    import jax                              # lazy: not needed for helper-only imports
    import jax.numpy as jnp                # lazy: same
    from energy_go.env.jax_env import EnvParams, reset, step, get_obs  # D22b import path
    from energy_go.training.normalizer import normalize_obs, RunningStats

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
        action = _deterministic_action(jax, jnp, actor_params, norm_obs)
        new_state, new_obs, reward, done, info = step(env_state, action, env_params, data)
        return new_state, info

    # Reset to start of year (t=0)
    key = jax.random.PRNGKey(0)  # deterministic: same key every eval
    init_state, _ = reset(key, env_params, data)

    # Scan over 8760 steps; infos has fields of shape (8760,)
    _, infos = jax.lax.scan(_step, init_state, None, length=8760)

    # ---- Existing 9 wire-locked fields (unchanged semantics) ----
    # Using np.sum here (works for JAX arrays via __array__); could also use jnp.sum.
    energy_cost_yuan   = float(np.sum(infos.c_energy_yuan))
    demand_charge_yuan = float(np.sum(infos.c_demand_charge_yuan))
    degradation_yuan   = float(np.sum(infos.c_degradation_yuan))
    curtailment_yuan   = float(np.sum(infos.c_curtail_yuan))
    voll_yuan          = float(np.sum(infos.c_voll_yuan))
    total_cost_yuan    = (
        energy_cost_yuan + demand_charge_yuan + degradation_yuan
        + curtailment_yuan + voll_yuan
    )
    soc_violations_count = int(np.sum(np.asarray(infos.soc_violation_mwh) > 0))
    soc_violation_mwh    = float(np.sum(infos.soc_violation_mwh))
    # LOCKED EnvInfo field name is penalty_yuan (not c_penalty_yuan).
    penalty_yuan = float(np.sum(infos.penalty_yuan))

    # ---- New: streams dict + physical-quantity accumulators ----
    streams = _build_streams(infos, env_params)
    phys    = _accumulate_physical_quantities(infos)

    return PolicyEvalResult(
        # existing 9 (wire-locked, unchanged)
        energy_cost_yuan     = energy_cost_yuan,
        demand_charge_yuan   = demand_charge_yuan,
        degradation_yuan     = degradation_yuan,
        curtailment_yuan     = curtailment_yuan,
        voll_yuan            = voll_yuan,
        total_cost_yuan      = total_cost_yuan,
        soc_violations_count = soc_violations_count,
        soc_violation_mwh    = soc_violation_mwh,
        penalty_yuan         = penalty_yuan,
        # streams dict
        streams              = streams,
        # physical-qty (9 fields from phys dict)
        generation_mwh       = phys["generation_mwh"],
        wind_generated_mwh   = phys["wind_generated_mwh"],
        pv_generated_mwh     = phys["pv_generated_mwh"],
        bat_charge_mwh       = phys["bat_charge_mwh"],
        bat_discharge_mwh    = phys["bat_discharge_mwh"],
        bat_throughput_mwh   = phys["bat_throughput_mwh"],
        load_served_mwh      = phys["load_served_mwh"],
        load_unserved_mwh    = phys["load_unserved_mwh"],
        curtailed_mwh        = phys["curtailed_mwh"],
        # per-source (13 fields from phys dict)
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
