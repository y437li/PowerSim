"""RunConfig — §5 training hyperparameters and logistics.

All defaults are the canonical §5 values. Override by passing keyword arguments:
    cfg = RunConfig(total_env_steps=100_000, seed=7)
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RunConfig:
    # ---- SAC hyperparameters (§5) ----------------------------------------
    lr: float = 1e-4               # Adam learning rate for actor, critics, ent_coef
    gamma: float = 0.999           # Discount factor — MUST stay 0.999 (demand charge is monthly)
    batch_size: int = 512          # Mini-batch size for SAC gradient updates
    buffer_size: int = 1_000_000   # Replay buffer capacity (1 M transitions)
    tau: float = 0.005             # Polyak target network update coefficient
    ent_coef: str | float = "auto" # Entropy coefficient: "auto" → log-alpha gradient, float → fixed
    total_env_steps: int = 500_000 # Total environment steps (counted across all vmapped envs)

    # ---- Parallelism (§7) ------------------------------------------------
    n_envs: int = 4096             # Number of vmapped parallel environments (on device)

    # ---- Episode lengths (D3) --------------------------------------------
    episode_len: int = 168         # Training episode: 7-day random-start slice
    eval_episode_len: int = 8760   # Eval: full year (no resets)

    # ---- VecNormalize (§4) -----------------------------------------------
    norm_obs: bool = True          # Enable obs normalisation
    norm_reward: bool = True       # Enable reward normalisation
    clip_obs: float = 10.0         # Obs clip after normalisation (±clip_obs)
    clip_reward: float = 10.0      # Reward clip after normalisation (±clip_reward)

    # ---- Network architecture (§5.2–5.3) ---------------------------------
    hidden_sizes: tuple[int, ...] = (256, 256)  # Hidden layer widths for actor and critic

    # ---- Telemetry / checkpointing cadence -------------------------------
    eval_every_steps: int = 10_000   # Emit eval_compare every N env steps
    log_every_steps: int = 1_000     # Emit train_metrics every N env steps

    # ---- Reproducibility -------------------------------------------------
    seed: int = 42                   # Master PRNG seed (JAX PRNGKey(seed))
    run_id: str = ""                 # Training run identifier (populated before train() is called)
    site_config_id: str = "site_gansu"  # Site YAML used for EnvParams (checkpoint provenance)
