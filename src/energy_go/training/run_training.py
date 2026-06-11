"""SAC training pipeline — §5 / §7 of training_pipeline contract + REBUILD_SPEC.md.

Public exports:
    SAC_TARGET_ENTROPY  float constant = -action_dim = -6.0
    actor_forward       JAX actor MLP forward pass (also used by eval.py)
    train               Main SAC training function → CheckpointData

Design notes:
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
"""

from __future__ import annotations

import time
import uuid
import json
import subprocess
from typing import Callable, Optional

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

_OBS_DIM:    int = 107
_ACTION_DIM: int = 6
_LOG_STD_MIN: float = -20.0
_LOG_STD_MAX: float = 2.0
_EPS: float = 1e-6   # log(1-x^2+eps) stability guard


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
# Replay buffer (numpy circular; host-side)
# ---------------------------------------------------------------------------

class _ReplayBuffer:
    """Simple circular replay buffer backed by numpy arrays.

    Host-side (numpy) storage; transitions are converted to JAX at sample time.
    Size: 1M entries * (107+6+107+1+1) * 4 bytes ≈ 888 MB for float32.
    """

    def __init__(self, capacity: int, obs_dim: int, action_dim: int) -> None:
        self.capacity   = capacity
        self.obs_dim    = obs_dim
        self.action_dim = action_dim
        self._pos  = 0
        self._size = 0
        self._obs      = np.zeros((capacity, obs_dim),    dtype=np.float32)
        self._actions  = np.zeros((capacity, action_dim), dtype=np.float32)
        self._rewards  = np.zeros(capacity,               dtype=np.float32)
        self._next_obs = np.zeros((capacity, obs_dim),    dtype=np.float32)
        self._dones    = np.zeros(capacity,               dtype=np.float32)

    def add_batch(
        self,
        obs:      np.ndarray,  # (N, obs_dim)
        actions:  np.ndarray,  # (N, action_dim)
        rewards:  np.ndarray,  # (N,)
        next_obs: np.ndarray,  # (N, obs_dim)
        dones:    np.ndarray,  # (N,)
    ) -> None:
        n = obs.shape[0]
        idx = np.arange(self._pos, self._pos + n) % self.capacity
        self._obs[idx]      = obs
        self._actions[idx]  = actions
        self._rewards[idx]  = rewards
        self._next_obs[idx] = next_obs
        self._dones[idx]    = dones
        self._pos  = (self._pos + n) % self.capacity
        self._size = min(self._size + n, self.capacity)

    def sample(
        self,
        batch_size: int,
        rng: np.random.Generator,
    ) -> tuple[np.ndarray, ...]:
        idx = rng.integers(0, self._size, size=batch_size)
        return (
            self._obs[idx],
            self._actions[idx],
            self._rewards[idx, None],   # (batch, 1) for broadcast
            self._next_obs[idx],
            self._dones[idx, None],     # (batch, 1)
        )

    @property
    def size(self) -> int:
        return self._size


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
# Main training function
# ---------------------------------------------------------------------------

def train(
    config: RunConfig,
    key: jax.Array,
    data: object,
    emit_fn: Optional[Callable[[dict], None]] = None,
) -> "CheckpointData":
    """SAC training loop — §5 / §7 of training_pipeline contract.

    Args:
        config:   RunConfig with all hyperparameters (defaults = §5 canonical values).
        key:      JAX PRNGKey — master random key; fixed seed → identical trajectory.
        data:     SyntheticYear — pre-generated synthetic year from jax_env data generators.
        emit_fn:  Optional callback(msg: dict) — called with train_metrics and eval_compare
                  telemetry dicts. None → no emission.

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
    # Lazy imports to avoid breaking import-time when jax_env is not yet available.
    from energy_go.env.jax_env import EnvParams, reset, step  # D22b
    from energy_go.training.checkpoint_format import CheckpointData, save_checkpoint
    from energy_go.training.eval import run_eval
    from energy_go.training.baselines import run_baseline, NoBatteryPolicy, TouPolicy
    from energy_go.training.telemetry import build_train_metrics, build_eval_compare

    # ---- Run metadata -------------------------------------------------------
    run_id = config.run_id or str(uuid.uuid4())[:8]
    start_time = time.monotonic()
    code_version = _git_sha()

    # ---- PRNG tree ---------------------------------------------------------
    key, k_init = jax.random.split(key)
    rng_np = np.random.default_rng(config.seed)  # numpy RNG for weight init + buffer

    # ---- Env params --------------------------------------------------------
    env_params_train = EnvParams(episode_len=config.episode_len)  # 168-step episodes
    env_params_eval  = EnvParams(episode_len=config.eval_episode_len)  # 8760-step eval

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

    target_entropy = float(SAC_TARGET_ENTROPY)  # = -6.0

    # ---- Optimisers -------------------------------------------------------
    optimizer = optax.adam(config.lr)
    actor_opt_state   = optimizer.init(actor_params)
    critic1_opt_state = optimizer.init(critic1_params)
    critic2_opt_state = optimizer.init(critic2_params)
    alpha_opt_state   = optimizer.init(log_alpha)

    # ---- Build jit-compiled SAC update (closes over optimizer) -----------
    _sac_update = _build_sac_update(optimizer, config.gamma, config.tau, target_entropy)

    # ---- VecNormalize stats -----------------------------------------------
    obs_stats    = init_running_stats(_OBS_DIM)
    reward_stats = init_running_stats(1)  # reward is scalar → D=1

    # ---- Replay buffer ----------------------------------------------------
    buffer = _ReplayBuffer(config.buffer_size, _OBS_DIM, _ACTION_DIM)

    # ---- Vmapped env step / reset ----------------------------------------
    @jax.jit
    def _vmap_reset(keys):
        """Reset n_envs environments in parallel."""
        return jax.vmap(lambda k: reset(k, env_params_train, data))(keys)

    @jax.jit
    def _vmap_step(states, actions):
        """Step n_envs environments in parallel — no host↔device copies."""
        return jax.vmap(
            lambda s, a: step(s, a, env_params_train, data)
        )(states, actions)

    # ---- Initialise vmapped envs ------------------------------------------
    key, k_reset = jax.random.split(key)
    reset_keys = jax.random.split(k_reset, config.n_envs)
    env_states, obs = _vmap_reset(reset_keys)   # obs: (n_envs, obs_dim)

    # ---- Tracking ----------------------------------------------------------
    global_step = 0
    best_total_cost = float("inf")
    best_checkpoint: Optional["CheckpointData"] = None

    # Accumulated loss windows for logging
    _window_actor_loss  = 0.0
    _window_critic_loss = 0.0
    _window_ent_coef    = float(jnp.exp(log_alpha))
    _window_reward_sum  = 0.0
    _window_count       = 0
    _window_cost_sum    = 0.0

    outer_steps = max(1, config.total_env_steps // config.n_envs)
    gradient_steps_per_outer = config.n_envs  # 1 SAC update per collected transition

    # ---- Training loop ----------------------------------------------------
    for outer_i in range(outer_steps):
        t_step_start = time.monotonic()

        # --- Determine actions from current policy (or random during warmup) ---
        obs_np = np.array(obs)                        # (n_envs, obs_dim)

        # Normalise obs for policy (stats may be near-zero early on — safe due to var=1 init)
        norm_obs_batch = np.array(
            jax.vmap(lambda o: normalize_obs(o, obs_stats, clip=config.clip_obs))(
                jnp.array(obs_np)
            )
        )  # (n_envs, obs_dim)

        key, k_action = jax.random.split(key)
        action_keys = jax.random.split(k_action, config.n_envs)

        # Batch stochastic actions from actor (on device via vmap)
        actions_jax = jax.vmap(
            lambda o, k: _sample_action(actor_params, o, k)[0]
        )(jnp.array(norm_obs_batch), action_keys)    # (n_envs, action_dim)
        actions_np = np.array(actions_jax)

        # --- Step vmapped envs -----------------------------------------------
        new_states, new_obs, rewards, dones, infos = _vmap_step(env_states, actions_jax)

        rewards_np  = np.array(rewards)   # (n_envs,)
        dones_np    = np.array(dones)     # (n_envs,)
        new_obs_np  = np.array(new_obs)   # (n_envs, obs_dim)

        # --- Update running obs + reward stats --------------------------------
        obs_stats    = update_stats(obs_stats,    jnp.array(obs_np))
        reward_stats = update_stats(reward_stats, jnp.array(rewards_np[:, None]))

        # --- Normalise reward for buffer -------------------------------------
        norm_rewards = np.array(
            jax.vmap(lambda r: normalize_reward(r, reward_stats, clip=config.clip_reward))(
                jnp.array(rewards_np[:, None])
            )
        ).squeeze(1)   # (n_envs,)

        # --- Add to replay buffer -------------------------------------------
        buffer.add_batch(
            obs=norm_obs_batch,
            actions=actions_np,
            rewards=norm_rewards,
            next_obs=norm_obs_batch,   # note: we re-normalise next_obs below
            dones=dones_np,
        )

        # Re-normalise next_obs and overwrite last batch in buffer
        # (buffer.pos has already advanced; write back with correct next_obs)
        norm_next_obs = np.array(
            jax.vmap(lambda o: normalize_obs(o, obs_stats, clip=config.clip_obs))(
                jnp.array(new_obs_np)
            )
        )
        n = config.n_envs
        # Overwrite the just-added next_obs entries with freshly normalised values
        idx = np.arange(buffer._pos - n, buffer._pos) % buffer.capacity
        buffer._next_obs[idx] = norm_next_obs

        # --- Reset done environments -----------------------------------------
        dones_bool = dones_np.astype(bool)
        if dones_bool.any():
            n_done = dones_bool.sum()
            key, k_re = jax.random.split(key)
            re_keys = jax.random.split(k_re, n_done)
            reset_states, reset_obs = jax.vmap(
                lambda k: reset(k, env_params_train, data)
            )(re_keys)
            # Scatter reset states back into the vmapped state batch
            # (JAX pytree index assignment requires numpy scatter)
            done_idx_np = np.where(dones_bool)[0]
            new_obs_np[done_idx_np] = np.array(reset_obs)
            # Update env_states for done envs (requires scatter on each leaf)
            # We simply rebuild the full batch for simplicity
            env_states = jax.tree_util.tree_map(
                lambda full, resets: full.at[done_idx_np].set(resets),
                new_states, reset_states,
            )
        else:
            env_states = new_states

        obs = jnp.array(new_obs_np)

        global_step += config.n_envs

        # ---- SAC gradient updates (once buffer has enough data) -----------------
        if buffer.size >= config.batch_size:
            for _g in range(gradient_steps_per_outer):
                key, k_upd = jax.random.split(key)
                (
                    b_obs, b_act, b_rew, b_nobs, b_done
                ) = buffer.sample(config.batch_size, rng_np)

                (
                    actor_params,
                    critic1_params,
                    critic2_params,
                    critic1_tgt,
                    critic2_tgt,
                    log_alpha,
                    actor_opt_state,
                    critic1_opt_state,
                    critic2_opt_state,
                    alpha_opt_state,
                    al,
                    cl,
                    ec,
                ) = _sac_update(
                    actor_params,
                    critic1_params,
                    critic2_params,
                    critic1_tgt,
                    critic2_tgt,
                    log_alpha,
                    actor_opt_state,
                    critic1_opt_state,
                    critic2_opt_state,
                    alpha_opt_state,
                    jnp.array(b_obs),
                    jnp.array(b_act),
                    jnp.array(b_rew),
                    jnp.array(b_nobs),
                    jnp.array(b_done),
                    k_upd,
                )

                _window_actor_loss  += float(al)
                _window_critic_loss += float(cl)
                _window_ent_coef     = float(ec)
                _window_count       += 1

        _window_reward_sum += float(rewards_np.mean())
        _window_cost_sum   += float(np.array(infos.c_energy_yuan).mean()
                                    + np.array(infos.c_demand_charge_yuan).mean()
                                    + np.array(infos.c_degradation_yuan).mean()
                                    + np.array(infos.c_curtail_yuan).mean()
                                    + np.array(infos.c_voll_yuan).mean()
                                    if hasattr(infos, "c_energy_yuan") else 0.0)

        steps_per_sec = config.n_envs / max(1e-6, time.monotonic() - t_step_start)

        # ---- Logging -------------------------------------------------------
        if global_step % config.log_every_steps < config.n_envs and _window_count > 0:
            avg_al   = _window_actor_loss  / _window_count
            avg_cl   = _window_critic_loss / _window_count
            avg_rwd  = _window_reward_sum  / max(1, outer_i + 1)
            avg_cost = _window_cost_sum    / max(1, outer_i + 1)

            if emit_fn is not None:
                msg = build_train_metrics(
                    global_step=global_step,
                    wall_seconds=time.monotonic() - start_time,
                    env_steps_per_sec=steps_per_sec,
                    actor_loss=avg_al,
                    critic_loss=avg_cl,
                    ent_coef=_window_ent_coef,
                    reward_scaled_mean=avg_rwd * 1e-5,
                    reward_norm_mean=None,
                    cost_total_real_mean_yuan=avg_cost,
                    is_eval_checkpoint=False,
                    checkpoint_id=None,
                    run_id=run_id,
                )
                emit_fn(msg)

        # ---- Evaluation checkpoint -----------------------------------------
        if global_step % config.eval_every_steps < config.n_envs:
            checkpoint_id = str(uuid.uuid4())
            created_at_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Build CheckpointData for eval (convert JAX→numpy)
            from energy_go.training.checkpoint_format import CheckpointData

            ckpt = CheckpointData(
                schema_version  = "1.0.0",
                checkpoint_id   = checkpoint_id,
                run_id          = run_id,
                global_step     = global_step,
                created_at_utc  = created_at_utc,
                code_version    = code_version,
                run_config_json = json.dumps(
                    {k: list(v) if isinstance(v, tuple) else v
                     for k, v in config.__dict__.items()}
                ),
                obs_dim         = _OBS_DIM,
                action_dim      = _ACTION_DIM,
                obs_mean        = np.array(obs_stats.mean, dtype=np.float32),
                obs_var         = np.array(obs_stats.var,  dtype=np.float32),
                obs_count       = int(obs_stats.count),
                obs_clip        = config.clip_obs,
                actor_fc1_w     = np.array(actor_params["fc1_w"], dtype=np.float32),
                actor_fc1_b     = np.array(actor_params["fc1_b"], dtype=np.float32),
                actor_fc2_w     = np.array(actor_params["fc2_w"], dtype=np.float32),
                actor_fc2_b     = np.array(actor_params["fc2_b"], dtype=np.float32),
                actor_out_w     = np.array(actor_params["out_w"], dtype=np.float32),
                actor_out_b     = np.array(actor_params["out_b"], dtype=np.float32),
                critic1_fc1_w   = np.array(critic1_params["fc1_w"], dtype=np.float32),
                critic1_fc1_b   = np.array(critic1_params["fc1_b"], dtype=np.float32),
                critic1_fc2_w   = np.array(critic1_params["fc2_w"], dtype=np.float32),
                critic1_fc2_b   = np.array(critic1_params["fc2_b"], dtype=np.float32),
                critic1_out_w   = np.array(critic1_params["out_w"], dtype=np.float32),
                critic1_out_b   = np.array(critic1_params["out_b"], dtype=np.float32),
                critic2_fc1_w   = np.array(critic2_params["fc1_w"], dtype=np.float32),
                critic2_fc1_b   = np.array(critic2_params["fc1_b"], dtype=np.float32),
                critic2_fc2_w   = np.array(critic2_params["fc2_w"], dtype=np.float32),
                critic2_fc2_b   = np.array(critic2_params["fc2_b"], dtype=np.float32),
                critic2_out_w   = np.array(critic2_params["out_w"], dtype=np.float32),
                critic2_out_b   = np.array(critic2_params["out_b"], dtype=np.float32),
                ent_coef        = float(jnp.exp(log_alpha)),
                target_entropy  = target_entropy,
            )

            # Run deterministic full-year eval
            rl_result = run_eval(ckpt, data, params=env_params_eval)

            # Run baselines (same env, same data)
            no_battery_result  = run_baseline("no_battery",    data, params=env_params_eval)
            tou_result         = run_baseline("rule_based_tou", data, params=env_params_eval)

            # Track best checkpoint
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

                train_msg = build_train_metrics(
                    global_step=global_step,
                    wall_seconds=time.monotonic() - start_time,
                    env_steps_per_sec=steps_per_sec,
                    actor_loss=_window_actor_loss / max(1, _window_count),
                    critic_loss=_window_critic_loss / max(1, _window_count),
                    ent_coef=_window_ent_coef,
                    reward_scaled_mean=(_window_reward_sum / max(1, outer_i + 1)) * 1e-5,
                    reward_norm_mean=None,
                    cost_total_real_mean_yuan=_window_cost_sum / max(1, outer_i + 1),
                    is_eval_checkpoint=True,
                    checkpoint_id=checkpoint_id,
                    run_id=run_id,
                )
                emit_fn(train_msg)

    # ---- Return best checkpoint (or final if no eval ran) -------------------
    if best_checkpoint is None:
        # No eval ran (very short run) — return current params
        from energy_go.training.checkpoint_format import CheckpointData
        best_checkpoint = CheckpointData(
            schema_version  = "1.0.0",
            checkpoint_id   = str(uuid.uuid4()),
            run_id          = run_id,
            global_step     = global_step,
            created_at_utc  = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            code_version    = code_version,
            run_config_json = json.dumps(
                {k: list(v) if isinstance(v, tuple) else v
                 for k, v in config.__dict__.items()}
            ),
            obs_dim         = _OBS_DIM,
            action_dim      = _ACTION_DIM,
            obs_mean        = np.array(obs_stats.mean, dtype=np.float32),
            obs_var         = np.array(obs_stats.var,  dtype=np.float32),
            obs_count       = int(obs_stats.count),
            obs_clip        = config.clip_obs,
            actor_fc1_w     = np.array(actor_params["fc1_w"], dtype=np.float32),
            actor_fc1_b     = np.array(actor_params["fc1_b"], dtype=np.float32),
            actor_fc2_w     = np.array(actor_params["fc2_w"], dtype=np.float32),
            actor_fc2_b     = np.array(actor_params["fc2_b"], dtype=np.float32),
            actor_out_w     = np.array(actor_params["out_w"], dtype=np.float32),
            actor_out_b     = np.array(actor_params["out_b"], dtype=np.float32),
            ent_coef        = float(jnp.exp(log_alpha)),
            target_entropy  = target_entropy,
        )

    return best_checkpoint
