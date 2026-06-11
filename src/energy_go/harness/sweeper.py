"""energy_go.harness.sweeper — vmapped hyperparameter/domain-randomization sweeps.

Contract: contracts/harness/env_harness.md §5.4
Runs len(variants) × n_seeds evaluations and returns SweepResult per (variant, seed).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Sequence

import jax

from energy_go.env import jax_env
from energy_go.harness.replay import ScenarioReplay
from energy_go.harness.types import RunConfig, SweepResult, SweepVariant

# Training-hyperParam fields that can be overridden (§4.7)
_TRAINING_PARAM_FIELDS = frozenset(
    {"learning_rate", "gamma", "batch_size", "buffer_size"}
)


class Sweeper:
    """Hyperparameter / domain-randomization sweep runner.

    Runs `len(variants) × n_seeds` independent evaluations deterministically.
    """

    def __init__(
        self,
        storage_dir: str | Path,
    ) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def run_sweep(
        self,
        variants: Sequence[SweepVariant],
        n_seeds: int,
        n_eval_steps: int = 8760,
        base_config: RunConfig | None = None,
    ) -> list:
        """Run all (variant, seed) evaluations and return list[SweepResult].

        Args:
            variants:      List of SweepVariant (>= 1, unique variant_ids).
            n_seeds:       Number of seeds per variant (>= 1).
            n_eval_steps:  Steps per eval rollout.
            base_config:   Overrideable base config. Uses defaults if None.

        Returns:
            list[SweepResult] with len(variants) × n_seeds entries.

        Raises:
            ValueError: if len(variants) == 0, n_seeds == 0, or duplicate variant_ids.
        """
        if len(variants) == 0:
            raise ValueError("variants must be non-empty")
        if n_seeds < 1:
            raise ValueError(f"n_seeds must be >= 1, got {n_seeds}")
        if n_eval_steps < 1:
            raise ValueError(f"n_eval_steps must be >= 1, got {n_eval_steps}")

        # Check unique variant_ids
        ids = [v.variant_id for v in variants]
        if len(ids) != len(set(ids)):
            dups = [i for i in ids if ids.count(i) > 1]
            raise ValueError(
                f"Duplicate variant_ids detected: {list(set(dups))}"
            )

        # Default base config
        if base_config is None:
            base_config = RunConfig(env_params={}, data_seed=0)

        results = []
        for variant in variants:
            for seed in range(n_seeds):
                result = self._eval_variant(
                    variant=variant,
                    seed=seed,
                    base_config=base_config,
                    n_eval_steps=n_eval_steps,
                )
                results.append(result)
        return results

    def _eval_variant(
        self,
        variant: SweepVariant,
        seed: int,
        base_config: RunConfig,
        n_eval_steps: int,
    ) -> SweepResult:
        """Run one (variant, seed) evaluation with fixed seed → deterministic result."""
        run_id = uuid.uuid4().hex
        try:
            # Merge env_params overrides on top of base
            env_params_merged = dict(base_config.env_params)
            env_params_merged.update(variant.env_params_overrides)

            # Build params (will raise on unknown keys → propagate as error)
            params = jax_env.EnvParams(**env_params_merged)

            # data_seed: use base config data_seed + seed for per-seed variation
            data_seed = base_config.data_seed + seed

            # Run a rollout with zero-action policy
            replay = ScenarioReplay(params=params)
            actions = [[0.0] * 6] * min(n_eval_steps, 8760)
            traj = replay.run(
                data_seed=data_seed,
                start_t=0,
                n_steps=min(n_eval_steps, 8760),
                actions=actions,
                state_seed=seed,
            )

            reward_mean = traj.episode_reward_sum / max(traj.n_steps, 1)
            cost_mean = traj.episode_real_cost_yuan / max(traj.n_steps, 1)

            return SweepResult(
                variant_id=variant.variant_id,
                seed=seed,
                run_id=run_id,
                n_eval_steps=traj.n_steps,
                reward_mean=float(reward_mean),
                cost_total_real_mean_yuan=float(cost_mean),
                completed=True,
                error_message=None,
            )

        except Exception as exc:
            return SweepResult(
                variant_id=variant.variant_id,
                seed=seed,
                run_id=run_id,
                n_eval_steps=0,
                reward_mean=0.0,
                cost_total_real_mean_yuan=0.0,
                completed=False,
                error_message=str(exc),
            )
