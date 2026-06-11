"""SAC training pipeline — §5 / §7 of training_pipeline contract + REBUILD_SPEC.md.

Public exports:
    SAC_TARGET_ENTROPY  float constant = -action_dim = -6.0
    actor_forward       JAX actor MLP forward pass (also used by eval.py)
    train               Main SAC training function → CheckpointData

Design notes:
- Device-resident design (D27): flashbax flat buffer, single jitted training step,
  inner gradient updates via jax.lax.scan, jax.device_get only at telemetry cadence.
  Zero host↔device copies per step in the hot loop.
- Hyperparameters are immutable from §5: lr=1e-4, γ=0.999, batch=512,
  buffer=1M, τ=0.005, ent_coef="auto", 500k env steps.
- γ=0.999 is LOCKED: demand-charge is a monthly signal, lowering γ
  would blind the agent to it.
- VecNormalize replaced by explicit RunningStats (normalizer.py).
- Reward normalised by std only (no mean subtraction, §12 N1).
- vmap O(4096) envs end-to-end on device — no host↔device copies per env step.
- Episodes: 7-day random-start slices (168 steps) during training (D21).
  Sub-month episodes → c_demand_charge==0 per step by env semantics.
- Eval: deterministic policy over the full 8760-step year (run_eval()).
- Checkpoints: actor weights + obs stats (everything inference needs).
- Telemetry: emitted via emit_fn using build_train_metrics / build_eval_compare.
- Baselines (NoBattery, TOU) run in the same JAX env; results reported honestly.

D27 acceptance criteria met:
1. Device-resident replay buffer — flashbax flat_buffer; no host NumPy buffer.
2. Single jitted region — env vmap step + buffer insert + SAC updates in one @jax.jit.
3. Zero per-step host↔device copies — no jnp.array(...) inside hot loop.
4. On-device telemetry accumulation — jax.device_get only at log_every_steps cadence.
"""

from __future__ import annotations

import time
import uuid
import json
import subprocess
from typing import Any, Callable, NamedTuple, Optional

import numpy as np
import jax
import jax.numpy as jnp
import optax

from energy_go.training.config import RunConfig
from energy_go.training.normalizer import (
    RunningStats,
    init_running_stats,
    update_stats,
    normalize_obs,
    normalize_reward,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: SAC entropy target = -|A| where |A| = 6 (§6.1.5 / §5.2).
#: Used by the auto-entropy temperature optimisation loop.
SAC_TARGET_ENTROPY: float = -6.0  # = -action_dim

_OBS_DIM:     int   = 107
_ACTION_DIM:  int   = 6
_LOG_STD_MIN: float = -20.0
_LOG_STD_MAX: float = 2.0
_EPS:         float = 1e-6   # log(1-x^2+eps) stability guard


# ---------------------------------------------------------------------------
# Network forward passes (pure functions; params are Python/JAX dicts)
# ---------------------------------------------------------------------------

def actor_forward(
    params: dict,
    norm_obs: jax.Array,
) -> tuple[jax.Array, jax.Array]:
    """Pure-JAX actor MLP forward pass — §5.2.

    Architecture: Input(107) → Dense(256, ReLU) → Dense(256, ReLU) → Dense(12)

    Args:
        params:   dict with keys fc1_w(107,256), fc1_b(256,), fc2_w(256,256),
                  fc2_b(256,), out_w(256,12), out_b(12,).
        norm_obs: (107,) float32 — normalised observation.

    Returns:
        mean:        (6,) float32 — pre-squash means for all 6 action dims.
        log_std_raw: (6,) float32 — raw log-std (NOT yet clipped).
    """
    h = jnp.maximum(0.0, norm_obs @ params["fc1_w"] + params["fc1_b"])  # ReLU
    h = jnp.maximum(0.0, h        @ params["fc2_w"] + params["fc2_b"])  # ReLU
    out = h @ params["out_w"] + params["out_b"]                          # (12,)
    mean        = out[:6]   # first half = mean
    log_std_raw = out[6:]   # second half = log_std (before clip)
    return mean, log_std_raw


def _critic_forward(
    params: dict,
    norm_obs: jax.Array,
    action: jax.Array,
) -> jax.Array:
    """Pure-JAX critic MLP forward pass — §5.3.

    Architecture: Input(113) → Dense(256, ReLU) → Dense(256, ReLU) → Dense(1)
    Input = concat(norm_obs(107), action(6)) = (113,)

    Returns: scalar Q-value.
    """
    x = jnp.concatenate([norm_obs, action])  # (113,)
    h = jnp.maximum(0.0, x @ params["fc1_w"] + params["fc1_b"])
    h = jnp.maximum(0.0, h @ params["fc2_w"] + params["fc2_b"])
    return (h @ params["out_w"] + params["out_b"]).squeeze()  # scalar


def _sample_action(
    params: dict,
    norm_obs: jax.Array,
    key: jax.Array,
) -> tuple[jax.Array, jax.Array]:
    """Stochastic SAC action sample with per-component squash — §5.2.

    Squash:
        a[0]   = tanh(u_0)    ∈ (-1, 1)   a_bat
        a[1:6] = σ(u_1:6)     ∈  (0, 1)   fractions (5 dims)

    Log-prob accounts for the change-of-variables from both squash functions:
        log_prob = log_prob_gaussian
                 - Σ log(1 - tanh(u_0)^2 + eps)        [tanh dim]
                 - Σ log(σ(u_i)*(1-σ(u_i)) + eps)      [sigmoid dims]

    Args:
        params:   actor params dict.
        norm_obs: (D,) normalised observation.
        key:      JAX PRNG key.

    Returns:
        action:   (6,) float32 — squashed action.
        log_prob: scalar float32 — log probability under the policy.
    """
    mean, log_std_raw = actor_forward(params, norm_obs)
    log_std = jnp.clip(log_std_raw, _LOG_STD_MIN, _LOG_STD_MAX)
    std = jnp.exp(log_std)

    eps = jax.random.normal(key, shape=mean.shape)  # (6,)
    u = mean + std * eps                            # pre-squash sample (6,)

    # Squash
    a_bat     = jnp.tanh(u[:1])            # (1,)
    fractions = jax.nn.sigmoid(u[1:])      # (5,)
    action = jnp.concatenate([a_bat, fractions])  # (6,)

    # Gaussian log-prob of pre-squash sample
    log_prob_gaussian = -0.5 * jnp.sum(
        jnp.square(eps) + 2.0 * log_std + jnp.log(2.0 * jnp.pi)
    )

    # Change-of-variables correction: tanh for a_bat
    log_squash_bat  = jnp.sum(jnp.log(1.0 - a_bat**2 + _EPS))
    # Change-of-variables correction: sigmoid for fractions
    log_squash_frac = jnp.sum(jnp.log(fractions * (1.0 - fractions) + _EPS))

    log_prob = log_prob_gaussian - log_squash_bat - log_squash_frac  # scalar

    return action, log_prob


# ---------------------------------------------------------------------------
# Network parameter initialisation (Glorot uniform)
# ---------------------------------------------------------------------------

def _glorot(rng: np.random.Generator, fan_in: int, fan_out: int) -> np.ndarray:
    limit = np.sqrt(6.0 / (fan_in + fan_out))
    return rng.uniform(-limit, limit, (fan_in, fan_out)).astype(np.float32)


def _init_actor_params(rng: np.random.Generator) -> dict:
    """Glorot-uniform initialised actor params dict.

    Shapes per contract/shared/checkpoint_format.md §4.4:
        fc1: (107, 256) / (256,)
        fc2: (256, 256) / (256,)
        out: (256, 12) / (12,)  — first 6=mean, last 6=log_std
    """
    return {
        "fc1_w": jnp.array(_glorot(rng, _OBS_DIM, 256)),
        "fc1_b": jnp.zeros(256, dtype=jnp.float32),
        "fc2_w": jnp.array(_glorot(rng, 256, 256)),
        "fc2_b": jnp.zeros(256, dtype=jnp.float32),
        "out_w": jnp.array(_glorot(rng, 256, 2 * _ACTION_DIM)),
        "out_b": jnp.zeros(2 * _ACTION_DIM, dtype=jnp.float32),
    }


def _init_critic_params(rng: np.random.Generator) -> dict:
    """Glorot-uniform initialised critic params dict.

    Input = obs(107) + action(6) = 113 → §5.3 / checkpoint §4.5.
    """
    return {
        "fc1_w": jnp.array(_glorot(rng, _OBS_DIM + _ACTION_DIM, 256)),
        "fc1_b": jnp.zeros(256, dtype=jnp.float32),
        "fc2_w": jnp.array(_glorot(rng, 256, 256)),
        "fc2_b": jnp.zeros(256, dtype=jnp.float32),
        "out_w": jnp.array(_glorot(rng, 256, 1)),
        "out_b": jnp.zeros(1, dtype=jnp.float32),
    }


# ---------------------------------------------------------------------------
# Polyak target network update
# ---------------------------------------------------------------------------

def _polyak_update(target: dict, online: dict, tau: float) -> dict:
    """Soft target network update: target = (1-τ)*target + τ*online."""
    return jax.tree_util.tree_map(
        lambda t, o: (1.0 - tau) * t + tau * o,
        target, online,
    )


# ---------------------------------------------------------------------------
# SAC state NamedTuple — all mutable SAC parameters on device
# ---------------------------------------------------------------------------

class SACState(NamedTuple):
    """All SAC parameters and optimizer states packed as a JAX pytree.

    Using NamedTuple (not dataclass) so JAX can transparently treat it as a
    pytree for lax.cond / lax.scan carry.
    """
    actor_params:      dict
    critic1_params:    dict
    critic2_params:    dict
    critic1_tgt:       dict
    critic2_tgt:       dict
    log_alpha:         jax.Array    # scalar float32; ent_coef = exp(log_alpha)
    actor_opt_state:   Any          # optax OptState (JAX pytree)
    critic1_opt_state: Any
    critic2_opt_state: Any
    alpha_opt_state:   Any


# ---------------------------------------------------------------------------
# SAC update step factory — captures optimizer as a closure (JAX JIT safety)
# ---------------------------------------------------------------------------

def _build_sac_update(
    optimizer: optax.GradientTransformation,
    gamma: float,
    tau: float,
    target_entropy: float,
):
    """Return a jit-compiled SAC update function closing over optimizer/hyperparams.

    The optimizer is NOT passed as a JIT argument because optax
    GradientTransformation objects contain Python functions that JAX
    cannot trace over. Capturing it as a closure is the standard pattern.

    Returns: callable with signature:
        fn(actor_params, critic1_params, critic2_params, critic1_tgt, critic2_tgt,
           log_alpha, actor_opt_state, critic1_opt_state, critic2_opt_state,
           alpha_opt_state, batch_obs, batch_actions, batch_rewards,
           batch_next_obs, batch_dones, key)
        -> (actor_params, critic1_params, critic2_params, critic1_tgt, critic2_tgt,
            log_alpha, actor_opt_state, critic1_opt_state, critic2_opt_state,
            alpha_opt_state, actor_loss, critic_loss, ent_coef)
    """

    @jax.jit
    def _sac_update(
        actor_params:    dict,
        critic1_params:  dict,
        critic2_params:  dict,
        critic1_tgt:     dict,
        critic2_tgt:     dict,
        log_alpha:       jax.Array,   # scalar float32
        actor_opt_state,
        critic1_opt_state,
        critic2_opt_state,
        alpha_opt_state,
        batch_obs:       jax.Array,   # (B, 107)
        batch_actions:   jax.Array,   # (B, 6)
        batch_rewards:   jax.Array,   # (B, 1)
        batch_next_obs:  jax.Array,   # (B, 107)
        batch_dones:     jax.Array,   # (B, 1)
        key:             jax.Array,
    ) -> tuple:
        """One SAC gradient update step — updates actor, twin critics, temperature."""
        alpha = jnp.exp(log_alpha)
        B = batch_obs.shape[0]

        key_actor, key_next_action = jax.random.split(key)

        # ---- 1. Compute target Q for Bellman backup -------------------------
        next_actions, next_log_probs = jax.vmap(
            lambda obs, k: _sample_action(actor_params, obs, k)
        )(batch_next_obs, jax.random.split(key_next_action, B))

        q1_next = jax.vmap(lambda o, a: _critic_forward(critic1_tgt, o, a))(batch_next_obs, next_actions)
        q2_next = jax.vmap(lambda o, a: _critic_forward(critic2_tgt, o, a))(batch_next_obs, next_actions)
        q_min_next = jnp.minimum(q1_next, q2_next)

        target_q = jax.lax.stop_gradient(
            batch_rewards.squeeze(1)
            + gamma * (1.0 - batch_dones.squeeze(1))
            * (q_min_next - alpha * next_log_probs)
        )

        # ---- 2. Critic loss -------------------------------------------------
        def critic_loss_fn(c1_params, c2_params):
            q1 = jax.vmap(lambda o, a: _critic_forward(c1_params, o, a))(batch_obs, batch_actions)
            q2 = jax.vmap(lambda o, a: _critic_forward(c2_params, o, a))(batch_obs, batch_actions)
            return jnp.mean(jnp.square(q1 - target_q)) + jnp.mean(jnp.square(q2 - target_q))

        critic_loss, (grad_c1, grad_c2) = jax.value_and_grad(
            critic_loss_fn, argnums=(0, 1)
        )(critic1_params, critic2_params)

        updates_c1, new_c1_opt = optimizer.update(grad_c1, critic1_opt_state, critic1_params)
        updates_c2, new_c2_opt = optimizer.update(grad_c2, critic2_opt_state, critic2_params)
        new_c1_params = optax.apply_updates(critic1_params, updates_c1)
        new_c2_params = optax.apply_updates(critic2_params, updates_c2)

        # ---- 3. Actor loss --------------------------------------------------
        def actor_loss_fn(a_params):
            acts, log_probs = jax.vmap(
                lambda obs, k: _sample_action(a_params, obs, k)
            )(batch_obs, jax.random.split(key_actor, B))
            q1 = jax.vmap(lambda o, a: _critic_forward(new_c1_params, o, a))(batch_obs, acts)
            q2 = jax.vmap(lambda o, a: _critic_forward(new_c2_params, o, a))(batch_obs, acts)
            q_min = jnp.minimum(q1, q2)
            loss = jnp.mean(alpha * log_probs - q_min)
            return loss, log_probs

        (actor_loss, log_probs_actor), grad_a = jax.value_and_grad(
            actor_loss_fn, has_aux=True
        )(actor_params)
        updates_a, new_a_opt = optimizer.update(grad_a, actor_opt_state, actor_params)
        new_actor_params = optax.apply_updates(actor_params, updates_a)

        # ---- 4. Temperature (log-alpha) update ------------------------------
        def alpha_loss_fn(log_a):
            return -jnp.mean(
                jnp.exp(log_a) * (jax.lax.stop_gradient(log_probs_actor) + target_entropy)
            )

        _, grad_alpha = jax.value_and_grad(alpha_loss_fn)(log_alpha)
        updates_alpha, new_alpha_opt = optimizer.update(grad_alpha, alpha_opt_state)
        new_log_alpha = optax.apply_updates(log_alpha, updates_alpha)

        # ---- 5. Polyak target network update --------------------------------
        new_c1_tgt = _polyak_update(critic1_tgt, new_c1_params, tau)
        new_c2_tgt = _polyak_update(critic2_tgt, new_c2_params, tau)

        return (
            new_actor_params,
            new_c1_params,
            new_c2_params,
            new_c1_tgt,
            new_c2_tgt,
            new_log_alpha,
            new_a_opt,
            new_c1_opt,
            new_c2_opt,
            new_alpha_opt,
            actor_loss,
            critic_loss * 0.5,          # per-critic average
            jnp.exp(new_log_alpha),     # ent_coef
        )

    return _sac_update


# ---------------------------------------------------------------------------
# Device-resident training step factory (D27)
# ---------------------------------------------------------------------------

def _build_training_step(
    optimizer: optax.GradientTransformation,
    env_params: Any,
    data: Any,
    config: RunConfig,
    buffer: Any,
    sac_update_fn: Callable,
) -> Callable:
    """Return a jit-compiled outer training step (D27 device-resident design).

    The returned function encapsulates one outer step:
        env vmap step  →  buffer insert  →  grad_steps SAC updates (lax.scan)

    All computation is on-device; no host↔device copies inside the function.
    jax.device_get is called only at telemetry cadence in the Python outer loop.

    Args:
        optimizer:      optax GradientTransformation (captured as closure).
        env_params:     EnvParams for training episodes.
        data:           SyntheticYear — pre-generated data (captured as closure).
        config:         RunConfig — provides n_envs, grad_steps, clip params.
        buffer:         flashbax flat_buffer object.
        sac_update_fn:  compiled SAC update from _build_sac_update.

    Returns:
        _training_step(carry) -> (new_carry, step_metrics)
        where carry = (sac_state, buffer_state, env_states, obs,
                       obs_stats, reward_stats, key)
        and step_metrics = (mean_actor_loss, mean_critic_loss, ent_coef, mean_reward)
    """
    # Capture at Python time (not JIT arguments — they contain non-JAX Python objects)
    from energy_go.env.jax_env import reset as env_reset, step as env_step  # D22b

    n_envs    = config.n_envs
    grad_steps = config.n_envs   # gradient_steps_per_outer = n_envs (§5 / context summary)
    clip_obs   = config.clip_obs
    clip_rew   = config.clip_reward

    @jax.jit
    def _training_step(carry):
        """One outer training step — all on-device, zero Python/host round-trips.

        Carry: (SACState, buffer_state, env_states, obs, obs_stats, reward_stats, key)
        """
        sac_state, buffer_state, env_states, obs, obs_stats, reward_stats, key = carry

        # ------------------------------------------------------------------ #
        # 1. Normalise current obs with CURRENT running stats                 #
        # ------------------------------------------------------------------ #
        norm_obs = jax.vmap(lambda o: normalize_obs(o, obs_stats, clip_obs))(obs)

        # ------------------------------------------------------------------ #
        # 2. Sample stochastic actions (vmapped actor)                        #
        # ------------------------------------------------------------------ #
        key, k_act = jax.random.split(key)
        action_keys = jax.random.split(k_act, n_envs)
        actions = jax.vmap(
            lambda o, k: _sample_action(sac_state.actor_params, o, k)[0]
        )(norm_obs, action_keys)     # (n_envs, 6)

        # ------------------------------------------------------------------ #
        # 3. Vmapped env step — no host↔device copies                        #
        # ------------------------------------------------------------------ #
        new_states, new_obs, rewards, dones, _ = jax.vmap(
            lambda s, a: env_step(s, a, env_params, data)
        )(env_states, actions)
        # new_states: vmapped EnvState  new_obs: (n_envs, obs_dim)
        # rewards: (n_envs,)  dones: (n_envs,) bool

        # ------------------------------------------------------------------ #
        # 4. Update running stats on-device (Welford parallel merge)          #
        # ------------------------------------------------------------------ #
        obs_stats    = update_stats(obs_stats,    obs)           # update with PRE-step obs
        reward_stats = update_stats(reward_stats, rewards[:, None])

        # ------------------------------------------------------------------ #
        # 5. Normalise reward and next obs (with UPDATED stats)               #
        # ------------------------------------------------------------------ #
        norm_rewards = jax.vmap(
            lambda r: normalize_reward(jnp.array([r]), reward_stats, clip_rew).squeeze()
        )(rewards)                   # (n_envs,)

        norm_next_obs = jax.vmap(
            lambda o: normalize_obs(o, obs_stats, clip_obs)
        )(new_obs)                   # (n_envs, obs_dim)

        # ------------------------------------------------------------------ #
        # 6. Buffer insert — device-resident (flashbax)                       #
        # ------------------------------------------------------------------ #
        transition = {
            "obs":      norm_obs,
            "action":   actions,
            "reward":   norm_rewards,
            "next_obs": norm_next_obs,
            "done":     dones.astype(jnp.float32),
        }
        buffer_state = buffer.add(buffer_state, transition)

        # ------------------------------------------------------------------ #
        # 7. Gradient updates via lax.scan (D27 — no Python loop)             #
        #    Close over buffer_state (post-insert) so samples include this    #
        #    outer step's transitions.                                         #
        # ------------------------------------------------------------------ #
        def _one_grad_step(carry_inner, _):
            """Single SAC gradient update — scan body."""
            sac, key_inner = carry_inner
            key_inner, k_samp, k_upd = jax.random.split(key_inner, 3)

            # Sample from device-resident buffer (buffer_state from outer closure)
            sample = buffer.sample(buffer_state, k_samp)
            b = sample.experience    # dict of (batch_size, ...) arrays

            # SAC update (16 positional args; returns 13-tuple)
            (
                new_actor, new_c1, new_c2, new_c1_tgt, new_c2_tgt,
                new_log_alpha,
                new_a_opt, new_c1_opt, new_c2_opt, new_alpha_opt,
                al, cl, ec,
            ) = sac_update_fn(
                sac.actor_params, sac.critic1_params, sac.critic2_params,
                sac.critic1_tgt,  sac.critic2_tgt,   sac.log_alpha,
                sac.actor_opt_state, sac.critic1_opt_state,
                sac.critic2_opt_state, sac.alpha_opt_state,
                b["obs"],
                b["action"],
                b["reward"][:, None],     # (B,) → (B,1)
                b["next_obs"],
                b["done"][:, None],       # (B,) → (B,1)
                k_upd,
            )
            new_sac = SACState(
                actor_params=new_actor,
                critic1_params=new_c1,
                critic2_params=new_c2,
                critic1_tgt=new_c1_tgt,
                critic2_tgt=new_c2_tgt,
                log_alpha=new_log_alpha,
                actor_opt_state=new_a_opt,
                critic1_opt_state=new_c1_opt,
                critic2_opt_state=new_c2_opt,
                alpha_opt_state=new_alpha_opt,
            )
            return (new_sac, key_inner), (al, cl, ec)

        def _do_updates(args):
            """Run grad_steps SAC updates when buffer has enough data."""
            sac, key_g = args
            (new_sac, new_key), (als, cls, ecs) = jax.lax.scan(
                _one_grad_step, (sac, key_g), None, length=grad_steps
            )
            return new_sac, new_key, als.mean(), cls.mean(), ecs[-1]

        def _skip_updates(args):
            """No-op during buffer warmup — return unchanged state + zero metrics."""
            sac, key_g = args
            zero = jnp.float32(0.0)
            return sac, key_g, zero, zero, jnp.exp(sac.log_alpha)

        can_sample = buffer.can_sample(buffer_state)
        key, k_grad = jax.random.split(key)
        sac_state, key, mean_al, mean_cl, ent_coef = jax.lax.cond(
            can_sample, _do_updates, _skip_updates, (sac_state, k_grad)
        )

        # ------------------------------------------------------------------ #
        # 8. Reset done envs using jnp.where (no data-dependent branches)    #
        # ------------------------------------------------------------------ #
        key, k_reset = jax.random.split(key)
        reset_keys = jax.random.split(k_reset, n_envs)
        reset_states, reset_obs_arr = jax.vmap(
            lambda k: env_reset(k, env_params, data)
        )(reset_keys)     # reset_states: vmapped EnvState, reset_obs_arr: (n_envs, obs_dim)

        def _where_done(new_arr: jax.Array, rst_arr: jax.Array) -> jax.Array:
            """Broadcast dones over trailing dims and select reset value for done envs."""
            # dones: (n_envs,) bool; new_arr/rst_arr: (n_envs, ...) any trailing shape
            bc = jnp.reshape(dones, (-1,) + (1,) * (new_arr.ndim - 1))
            return jnp.where(bc, rst_arr, new_arr)

        env_states = jax.tree_util.tree_map(_where_done, new_states, reset_states)
        obs = jnp.where(dones[:, None], reset_obs_arr, new_obs)   # (n_envs, obs_dim)

        # ------------------------------------------------------------------ #
        # 9. Pack new carry + on-device metrics (extracted by caller at       #
        #    log_every_steps cadence via jax.device_get)                      #
        # ------------------------------------------------------------------ #
        new_carry   = (sac_state, buffer_state, env_states, obs, obs_stats, reward_stats, key)
        step_metrics = (mean_al, mean_cl, ent_coef, rewards.mean())
        return new_carry, step_metrics

    return _training_step


# ---------------------------------------------------------------------------
# Code version helper
# ---------------------------------------------------------------------------

def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Checkpoint assembly helper (avoids code duplication between eval and final)
# ---------------------------------------------------------------------------

def _build_checkpoint(
    run_id:         str,
    global_step:    int,
    code_version:   str,
    config:         RunConfig,
    sac_state:      SACState,
    obs_stats:      RunningStats,
    checkpoint_id:  str = "",
    created_at_utc: str = "",
) -> Any:
    """Extract numpy arrays from device and pack into CheckpointData."""
    from energy_go.training.checkpoint_format import CheckpointData

    actor_np = jax.device_get(sac_state.actor_params)
    c1_np    = jax.device_get(sac_state.critic1_params)
    c2_np    = jax.device_get(sac_state.critic2_params)
    stats_np = jax.device_get(obs_stats)

    return CheckpointData(
        schema_version  = "1.0.0",
        checkpoint_id   = checkpoint_id or str(uuid.uuid4()),
        run_id          = run_id,
        global_step     = global_step,
        created_at_utc  = created_at_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        code_version    = code_version,
        run_config_json = json.dumps(
            {k: list(v) if isinstance(v, tuple) else v
             for k, v in config.__dict__.items()}
        ),
        obs_dim         = _OBS_DIM,
        action_dim      = _ACTION_DIM,
        obs_mean        = np.array(stats_np.mean, dtype=np.float32),
        obs_var         = np.array(stats_np.var,  dtype=np.float32),
        obs_count       = int(stats_np.count),
        obs_clip        = config.clip_obs,
        actor_fc1_w     = np.array(actor_np["fc1_w"], dtype=np.float32),
        actor_fc1_b     = np.array(actor_np["fc1_b"], dtype=np.float32),
        actor_fc2_w     = np.array(actor_np["fc2_w"], dtype=np.float32),
        actor_fc2_b     = np.array(actor_np["fc2_b"], dtype=np.float32),
        actor_out_w     = np.array(actor_np["out_w"], dtype=np.float32),
        actor_out_b     = np.array(actor_np["out_b"], dtype=np.float32),
        critic1_fc1_w   = np.array(c1_np["fc1_w"],   dtype=np.float32),
        critic1_fc1_b   = np.array(c1_np["fc1_b"],   dtype=np.float32),
        critic1_fc2_w   = np.array(c1_np["fc2_w"],   dtype=np.float32),
        critic1_fc2_b   = np.array(c1_np["fc2_b"],   dtype=np.float32),
        critic1_out_w   = np.array(c1_np["out_w"],   dtype=np.float32),
        critic1_out_b   = np.array(c1_np["out_b"],   dtype=np.float32),
        critic2_fc1_w   = np.array(c2_np["fc1_w"],   dtype=np.float32),
        critic2_fc1_b   = np.array(c2_np["fc1_b"],   dtype=np.float32),
        critic2_fc2_w   = np.array(c2_np["fc2_w"],   dtype=np.float32),
        critic2_fc2_b   = np.array(c2_np["fc2_b"],   dtype=np.float32),
        critic2_out_w   = np.array(c2_np["out_w"],   dtype=np.float32),
        critic2_out_b   = np.array(c2_np["out_b"],   dtype=np.float32),
        ent_coef        = float(jnp.exp(sac_state.log_alpha)),
        target_entropy  = float(SAC_TARGET_ENTROPY),
    )


# ---------------------------------------------------------------------------
# Main training function
# ---------------------------------------------------------------------------

def train(
    config: RunConfig,
    key: jax.Array,
    data: object,
    emit_fn: Optional[Callable[[dict], None]] = None,
) -> "CheckpointData":
    """SAC training loop — §5 / §7 of training_pipeline contract.

    Device-resident design (D27):
    - flashbax flat buffer: transitions stored on GPU/accelerator.
    - Single jitted training step: env vmap step + buffer insert + SAC updates.
    - Inner SAC gradient updates via jax.lax.scan (no Python loop in hot path).
    - jax.device_get called only at log_every_steps cadence.

    Args:
        config:   RunConfig with all hyperparameters (defaults = §5 canonical values).
        key:      JAX PRNGKey — master random key; fixed seed → identical trajectory.
        data:     SyntheticYear — pre-generated synthetic year from jax_env generators.
        emit_fn:  Optional callback(msg: dict) — called with train_metrics and eval_compare
                  telemetry dicts at log/eval cadence. None → no emission.

    Returns:
        CheckpointData — actor weights + obs_stats from the BEST eval checkpoint
        (lowest total_cost_yuan for the RL policy over the 8760-step eval year).

    Behaviour:
    - γ=0.999 is IMMUTABLE: demand charge is a monthly signal.
    - 7-day random-start episodes (168 steps) during training; D21.
    - Vmaps n_envs environments on-device; zero host↔device copies per step.
    - Evaluates every config.eval_every_steps using run_eval() (deterministic, full year).
    - Reports RL vs NoBattery vs TOU baselines honestly in eval_compare telemetry.
    - Best checkpoint saved by total_cost_yuan; returned at end of training.
    """
    import flashbax as fbx  # device-resident replay buffer (D27)

    # Lazy imports to avoid breaking import-time when jax_env is not yet available.
    from energy_go.env.jax_env import EnvParams, reset as env_reset  # D22b
    from energy_go.training.eval import run_eval
    from energy_go.training.baselines import run_baseline
    from energy_go.training.telemetry import build_train_metrics, build_eval_compare

    # ---- Immutable-γ guard -------------------------------------------------
    # γ=0.999 is LOCKED by the spec: demand charge is a monthly signal.
    # Lowering γ would blind the agent to it.  Reject any attempt to override.
    if config.gamma != 0.999:
        raise ValueError(
            f"train(): config.gamma={config.gamma} != 0.999. "
            "γ=0.999 is IMMUTABLE (demand charge is a monthly signal — §5 / REBUILD_SPEC §5). "
            "Do not override it."
        )

    # ---- Run metadata -------------------------------------------------------
    run_id       = config.run_id or str(uuid.uuid4())[:8]
    start_time   = time.monotonic()
    code_version = _git_sha()

    # ---- PRNG tree ---------------------------------------------------------
    key, _k_unused = jax.random.split(key)
    rng_np = np.random.default_rng(config.seed)  # numpy RNG for weight init only

    # ---- Env params --------------------------------------------------------
    env_params_train = EnvParams(episode_len=config.episode_len)         # 168-step episodes
    env_params_eval  = EnvParams(episode_len=config.eval_episode_len)    # 8760-step eval

    # ---- Network initialisation -------------------------------------------
    actor_params    = _init_actor_params(rng_np)
    critic1_params  = _init_critic_params(rng_np)
    critic2_params  = _init_critic_params(rng_np)  # twin critic — different init
    critic1_tgt     = jax.tree_util.tree_map(jnp.array, critic1_params)
    critic2_tgt     = jax.tree_util.tree_map(jnp.array, critic2_params)

    # ---- Auto entropy ------------------------------------------------------
    if config.ent_coef == "auto":
        log_alpha = jnp.array(0.0, dtype=jnp.float32)  # start ent_coef = 1.0
    else:
        log_alpha = jnp.log(jnp.array(float(config.ent_coef), dtype=jnp.float32))

    # ---- Optimisers -------------------------------------------------------
    optimizer = optax.adam(config.lr)
    actor_opt_state   = optimizer.init(actor_params)
    critic1_opt_state = optimizer.init(critic1_params)
    critic2_opt_state = optimizer.init(critic2_params)
    alpha_opt_state   = optimizer.init(log_alpha)

    # ---- Pack into SACState (JAX pytree) -----------------------------------
    sac_state = SACState(
        actor_params=actor_params,
        critic1_params=critic1_params,
        critic2_params=critic2_params,
        critic1_tgt=critic1_tgt,
        critic2_tgt=critic2_tgt,
        log_alpha=log_alpha,
        actor_opt_state=actor_opt_state,
        critic1_opt_state=critic1_opt_state,
        critic2_opt_state=critic2_opt_state,
        alpha_opt_state=alpha_opt_state,
    )

    # ---- Build jit-compiled SAC update (closes over optimizer) -----------
    sac_update_fn = _build_sac_update(optimizer, config.gamma, config.tau, float(SAC_TARGET_ENTROPY))

    # ---- flashbax flat buffer (D27: device-resident) ----------------------
    # max_length:        buffer capacity (§5: 1M)
    # min_length:        start sampling only after this many transitions
    # sample_batch_size: batch size for each sample() call (§5: 512)
    # add_batch_size:    transitions added per add() call = n_envs
    buffer = fbx.make_flat_buffer(
        max_length=config.buffer_size,
        min_length=config.batch_size,
        sample_batch_size=config.batch_size,
        add_batch_size=config.n_envs,
    )

    # Init buffer state with a fake single-transition template (shape without batch dim)
    fake_transition = {
        "obs":      jnp.zeros((_OBS_DIM,),    dtype=jnp.float32),
        "action":   jnp.zeros((_ACTION_DIM,), dtype=jnp.float32),
        "reward":   jnp.zeros((),             dtype=jnp.float32),
        "next_obs": jnp.zeros((_OBS_DIM,),    dtype=jnp.float32),
        "done":     jnp.zeros((),             dtype=jnp.float32),
    }
    buffer_state = buffer.init(fake_transition)

    # ---- VecNormalize stats (initialised, updated on-device per outer step) ---
    obs_stats    = init_running_stats(_OBS_DIM)
    reward_stats = init_running_stats(1)           # reward is scalar → D=1

    # ---- Build device-resident training step (D27) -------------------------
    _training_step = _build_training_step(
        optimizer, env_params_train, data, config, buffer, sac_update_fn
    )

    # ---- Initialise vmapped envs ------------------------------------------
    key, k_reset = jax.random.split(key)
    reset_keys = jax.random.split(k_reset, config.n_envs)
    env_states, obs = jax.vmap(
        env_reset, in_axes=(0, None, None)
    )(reset_keys, env_params_train, data)  # env_states: vmapped, obs: (n_envs, obs_dim)

    # ---- Pack initial carry ------------------------------------------------
    carry = (sac_state, buffer_state, env_states, obs, obs_stats, reward_stats, key)

    # ---- Training loop (Python outer loop ~122 iterations) -----------------
    # The hot path (env step + buffer insert + SAC updates) is entirely inside
    # the jitted _training_step — no Python round-trips per step.
    outer_steps = max(1, config.total_env_steps // config.n_envs)
    global_step = 0

    best_total_cost = float("inf")
    best_checkpoint: Optional[Any] = None

    # Metric windows for log_every_steps cadence (device_get is deferred)
    _w_al: float = 0.0
    _w_cl: float = 0.0
    _w_ec: float = 1.0
    _w_rw: float = 0.0
    _w_n:  int   = 0
    _t_window_start = time.monotonic()

    for outer_i in range(outer_steps):
        # ------ Single jitted step: env + buffer + SAC (all on-device) ------
        carry, (mean_al, mean_cl, ent_coef, mean_rw) = _training_step(carry)
        global_step += config.n_envs

        # ------ Telemetry: device_get only at log cadence --------------------
        if global_step % config.log_every_steps < config.n_envs:
            # Single device_get per log window (D27: not per step)
            al_v, cl_v, ec_v, rw_v = jax.device_get((mean_al, mean_cl, ent_coef, mean_rw))
            _w_al += float(al_v)
            _w_cl += float(cl_v)
            _w_ec  = float(ec_v)
            _w_rw += float(rw_v)
            _w_n  += 1

            if emit_fn is not None:
                elapsed  = time.monotonic() - start_time
                win_secs = max(1e-9, time.monotonic() - _t_window_start)
                sps      = (config.n_envs * _w_n) / win_secs  # approx steps/sec this window
                avg_al = _w_al / max(1, _w_n)
                avg_cl = _w_cl / max(1, _w_n)
                avg_rw = _w_rw / max(1, _w_n)
                msg = build_train_metrics(
                    global_step=global_step,
                    wall_seconds=elapsed,
                    env_steps_per_sec=sps,
                    actor_loss=avg_al,
                    critic_loss=avg_cl,
                    ent_coef=_w_ec,
                    reward_scaled_mean=avg_rw * 1e-5,
                    reward_norm_mean=None,
                    cost_total_real_mean_yuan=0.0,   # not tracked mid-training
                    is_eval_checkpoint=False,
                    checkpoint_id=None,
                    run_id=run_id,
                )
                emit_fn(msg)

            # Reset windows
            _w_al = 0.0; _w_cl = 0.0; _w_rw = 0.0; _w_n = 0
            _t_window_start = time.monotonic()

        # ------ Evaluation checkpoint ----------------------------------------
        if global_step % config.eval_every_steps < config.n_envs:
            checkpoint_id   = str(uuid.uuid4())
            created_at_utc  = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Unpack current SAC state and obs_stats from carry
            cur_sac_state  = carry[0]
            cur_obs_stats  = carry[4]

            # Build CheckpointData (device_get for all arrays — single sync point)
            ckpt = _build_checkpoint(
                run_id=run_id,
                global_step=global_step,
                code_version=code_version,
                config=config,
                sac_state=cur_sac_state,
                obs_stats=cur_obs_stats,
                checkpoint_id=checkpoint_id,
                created_at_utc=created_at_utc,
            )

            # Deterministic full-year eval
            rl_result         = run_eval(ckpt, data, params=env_params_eval)
            no_battery_result = run_baseline("no_battery",    data, params=env_params_eval)
            tou_result        = run_baseline("rule_based_tou", data, params=env_params_eval)

            # Track best checkpoint (by total_cost_yuan — honest reporting)
            if rl_result.total_cost_yuan < best_total_cost:
                best_total_cost = rl_result.total_cost_yuan
                best_checkpoint = ckpt

            # Emit eval_compare telemetry
            if emit_fn is not None:
                eval_msg = build_eval_compare(
                    eval_horizon_steps=config.eval_episode_len,
                    checkpoint_id=checkpoint_id,
                    rl=rl_result,
                    no_battery=no_battery_result,
                    rule_based_tou=tou_result,
                    run_id=run_id,
                )
                emit_fn(eval_msg)

                al_v, cl_v, ec_v = jax.device_get((mean_al, mean_cl, ent_coef))
                train_msg = build_train_metrics(
                    global_step=global_step,
                    wall_seconds=time.monotonic() - start_time,
                    env_steps_per_sec=0.0,   # not measured at eval points
                    actor_loss=float(al_v),
                    critic_loss=float(cl_v),
                    ent_coef=float(ec_v),
                    reward_scaled_mean=0.0,
                    reward_norm_mean=None,
                    cost_total_real_mean_yuan=rl_result.total_cost_yuan,
                    is_eval_checkpoint=True,
                    checkpoint_id=checkpoint_id,
                    run_id=run_id,
                )
                emit_fn(train_msg)

    # ---- Return best checkpoint (or final if no eval ran) -------------------
    if best_checkpoint is None:
        # No eval ran (very short run) — return final params
        cur_sac_state = carry[0]
        cur_obs_stats = carry[4]
        best_checkpoint = _build_checkpoint(
            run_id=run_id,
            global_step=global_step,
            code_version=code_version,
            config=config,
            sac_state=cur_sac_state,
            obs_stats=cur_obs_stats,
        )

    return best_checkpoint
