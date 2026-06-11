"""VecNormalize reimplemented as pure JAX arrays — §4 of training_pipeline contract.

RunningStats is a NamedTuple so it is a valid JAX pytree (can be carried through jit).
All operations are functional (no mutation); update_stats returns a new RunningStats.

Welford parallel (batch) update algorithm:
    For two sets A (count_a, mean_a, var_a) and B (count_b, mean_b, var_b):
        delta = mean_b - mean_a
        tot   = count_a + count_b
        new_mean = mean_a + delta * count_b / tot
        M2_a = var_a * count_a
        M2_b = var_b * count_b
        M2   = M2_a + M2_b + delta^2 * count_a * count_b / tot
        new_var  = M2 / tot

Reward normalisation follows SB3 convention: divide by std only, do NOT subtract the
mean (§12 N1 deliberate deviation from the return-std variant; see training_pipeline §12).
"""

from __future__ import annotations
from typing import NamedTuple

import jax
import jax.numpy as jnp

_EPS: float = 1e-8  # division-by-zero guard (var=0 → std=sqrt(eps))


class RunningStats(NamedTuple):
    """Running mean and population variance for a D-dimensional observation/reward.

    Attributes:
        mean:  (D,) float32 — running mean (zeros at init)
        var:   (D,) float32 — running population variance (ones at init to avoid /0)
        count: () int32    — number of samples seen
    """
    mean:  jax.Array   # float32, (D,)
    var:   jax.Array   # float32, (D,)
    count: jax.Array   # int32,  scalar


def init_running_stats(dim: int) -> RunningStats:
    """Initialise RunningStats for a D-dimensional vector.

    Initial mean=0, var=1 (prevents division by zero before the first update),
    count=0.
    """
    return RunningStats(
        mean  = jnp.zeros(dim, dtype=jnp.float32),
        var   = jnp.ones(dim,  dtype=jnp.float32),
        count = jnp.int32(0),
    )


def update_stats(stats: RunningStats, batch: jax.Array) -> RunningStats:
    """Welford parallel batch update — §4.2.

    Args:
        stats: current RunningStats (D,)
        batch: (N, D) float32 — a batch of N new observations

    Returns:
        Updated RunningStats with Welford-merged mean and population variance.
    """
    batch = batch.astype(jnp.float32)
    n = jnp.int32(batch.shape[0])

    # Batch statistics
    batch_mean = jnp.mean(batch, axis=0)           # (D,)
    batch_var  = jnp.var(batch,  axis=0)           # (D,) — population variance

    # Welford parallel merge
    count_old = stats.count
    count_new = count_old + n

    delta    = batch_mean - stats.mean             # (D,)
    new_mean = stats.mean + delta * (n / count_new.astype(jnp.float32))  # (D,)

    m_a = stats.var * count_old.astype(jnp.float32)      # (D,)
    m_b = batch_var * n.astype(jnp.float32)               # (D,)
    # Combined M2 (Welford sum of squared deviations from new mean):
    m2  = m_a + m_b + jnp.square(delta) * (
        count_old.astype(jnp.float32) * n.astype(jnp.float32)
        / count_new.astype(jnp.float32)
    )
    new_var = m2 / count_new.astype(jnp.float32)  # population variance

    return RunningStats(mean=new_mean, var=new_var, count=count_new)


def normalize_obs(
    obs: jax.Array,
    stats: RunningStats,
    clip: float = 10.0,
) -> jax.Array:
    """Normalise a (D,) observation using running stats, clip to ±clip.

    norm_obs = clip((obs - mean) / sqrt(var + _EPS), -clip, +clip)

    Args:
        obs:   (D,) float32 — raw observation from env.step()
        stats: RunningStats — current normalisation statistics
        clip:  float — clip bound (default 10.0 per §5 / RunConfig.clip_obs)

    Returns:
        (D,) float32 — normalised and clipped observation
    """
    std      = jnp.sqrt(stats.var + _EPS)          # (D,) — _EPS guards var=0
    norm_obs = (obs - stats.mean) / std
    return jnp.clip(norm_obs, -clip, clip)


def normalize_reward(
    reward: jax.Array,
    stats: RunningStats,
    clip: float = 10.0,
) -> jax.Array:
    """Normalise a reward scalar by std only (SB3 convention, §12 N1).

    norm_reward = clip(reward / sqrt(var + _EPS), -clip, +clip)
    Mean is NOT subtracted (SB3 VecNormalize convention for rewards).

    Args:
        reward: (1,) or scalar float32 — raw reward from env.step()
        stats:  RunningStats (D=1) — reward running statistics
        clip:   float — clip bound (default 10.0 per RunConfig.clip_reward)

    Returns:
        Normalised reward, same shape as input.
    """
    std  = jnp.sqrt(stats.var + _EPS)              # (D,) — typically D=1 for rewards
    norm = reward / std
    return jnp.clip(norm, -clip, clip)
