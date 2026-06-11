"""Energy GO training package — §5 SAC pipeline.

Public API:
    train           — main SAC training loop (run_training.train)
    run_eval        — deterministic full-year evaluation
    run_baseline    — NoBattery / TOU baseline rollout
    RunConfig       — hyperparameter and logistics dataclass
    RunningStats    — VecNormalize as pure JAX arrays
    PolicyEvalResult — real-money cost breakdown from eval

All submodule imports are **deferred** via PEP 562 module __getattr__ so that
`from energy_go.training.checkpoint_format import ...` (used by the serving
layer) works on JAX-free serving boxes.  JAX-dependent symbols are only
materialised when actually accessed.

Note: `from energy_go.training import *` materialises all __all__ names and
therefore still requires JAX.  Serving code must use the direct submodule
import (`from energy_go.training.checkpoint_format import ...`), not import *.
"""

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


def __getattr__(name: str):
    """PEP 562 lazy attribute resolution — defers all JAX-heavy submodule imports."""
    if name == "RunConfig":
        from energy_go.training.config import RunConfig
        return RunConfig
    if name in ("RunningStats", "init_running_stats", "update_stats",
                "normalize_obs", "normalize_reward"):
        import energy_go.training.normalizer as _normalizer
        return getattr(_normalizer, name)
    if name in ("PolicyEvalResult", "run_eval"):
        import energy_go.training.eval as _eval
        return getattr(_eval, name)
    if name == "run_baseline":
        from energy_go.training.baselines import run_baseline
        return run_baseline
    if name == "train":
        from energy_go.training.run_training import train
        return train
    raise AttributeError(f"module 'energy_go.training' has no attribute {name!r}")
