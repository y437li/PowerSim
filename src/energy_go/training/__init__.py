"""Energy GO training package — §5 SAC pipeline.

Public API:
    train           — main SAC training loop (run_training.train)
    run_eval        — deterministic full-year evaluation
    run_baseline    — NoBattery / TOU baseline rollout
    RunConfig       — hyperparameter and logistics dataclass
    RunningStats    — VecNormalize as pure JAX arrays
    PolicyEvalResult — real-money cost breakdown from eval
"""

from energy_go.training.config import RunConfig
from energy_go.training.normalizer import (
    RunningStats,
    init_running_stats,
    update_stats,
    normalize_obs,
    normalize_reward,
)
from energy_go.training.eval import PolicyEvalResult, run_eval
from energy_go.training.baselines import run_baseline
from energy_go.training.run_training import train

__all__ = [
    "RunConfig",
    "RunningStats",
    "init_running_stats",
    "update_stats",
    "normalize_obs",
    "normalize_reward",
    "PolicyEvalResult",
    "run_eval",
    "run_baseline",
    "train",
]
