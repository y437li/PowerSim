"""energy_go.harness.replay — deterministic trajectory replay.

Contract: contracts/harness/env_harness.md §5.2
Runs a fixed action sequence or policy callable over a synthetic year slice.
"""
from __future__ import annotations

import uuid
from typing import Callable, Sequence

import jax
import numpy as np

from energy_go.env import jax_env
from energy_go.generators.synthetic import generate_year
from energy_go.harness.interactive_env import InteractiveEnv
from energy_go.harness.types import TrajectoryRecord, TrajectoryStep


class ScenarioReplay:
    """Deterministic trajectory replay over a chosen synthetic-year slice.

    Same (data_seed, start_t, n_steps, actions, state_seed) always produces a
    byte-identical TrajectoryRecord (§7 determinism guarantee).
    """

    def __init__(
        self,
        params: jax_env.EnvParams,
    ) -> None:
        self._params = params

    def run(
        self,
        data_seed: int,
        start_t: int,
        n_steps: int,
        actions: Sequence | None = None,
        policy_fn: Callable | None = None,
        state_seed: int = 0,
    ) -> TrajectoryRecord:
        """Run a deterministic trajectory.

        Exactly one of *actions* or *policy_fn* must be provided.

        Args:
            data_seed:  RNG seed for generate_year().
            start_t:    Episode start step index (inclusive).
            n_steps:    Number of steps to run (>= 1).
            actions:    Fixed action list of length n_steps, each a length-6 sequence.
            policy_fn:  Callable obs (107-element list/array) → action (length-6).
            state_seed: Seed for the initial EnvState RNG.

        Returns:
            TrajectoryRecord with n_steps TrajectoryStep entries.

        Raises:
            ValueError: if both or neither of actions/policy_fn are provided.
            ValueError: if len(actions) != n_steps.
            ValueError: if start_t + n_steps > 8760.
            ValueError: if n_steps < 1.
        """
        # --- Input validation ---
        if actions is None and policy_fn is None:
            raise ValueError(
                "Exactly one of 'actions' or 'policy_fn' must be provided (got neither)"
            )
        if actions is not None and policy_fn is not None:
            raise ValueError(
                "Exactly one of 'actions' or 'policy_fn' must be provided (got both)"
            )
        if n_steps < 1:
            raise ValueError(f"n_steps must be >= 1, got {n_steps}")
        if start_t < 0:
            raise ValueError(f"start_t must be >= 0, got {start_t}")
        if start_t + n_steps > 8760:
            raise ValueError(
                f"start_t={start_t} + n_steps={n_steps} = {start_t + n_steps} > 8760"
            )
        if actions is not None and len(actions) != n_steps:
            raise ValueError(
                f"len(actions)={len(actions)} != n_steps={n_steps}"
            )

        # --- Generate synthetic year data (fixed seed → deterministic) ---
        data = generate_year(jax.random.PRNGKey(data_seed))

        # --- Build InteractiveEnv ---
        ienv = InteractiveEnv(params=self._params, data=data)

        # --- Initial state: soc_init at start_t, month_peak=0, rng=state_seed ---
        state = ienv.make_state(
            soc=float(self._params.soc_init),
            t=start_t,
            month_peak_mw=0.0,
            seed=state_seed,
        )

        # --- Run steps ---
        traj_steps = []
        for seq in range(n_steps):
            if actions is not None:
                action = list(actions[seq])
            else:
                obs = ienv.get_obs(state)
                action = list(policy_fn(np.array(obs, dtype=np.float32)))

            # _step_raw returns (new_state, StepInspection) without double-stepping
            new_state, insp = ienv._step_raw(state, action)
            traj_steps.append(TrajectoryStep(seq=seq, step_inspection=insp))
            state = new_state

        episode_reward = sum(ts.step_inspection.reward for ts in traj_steps)
        episode_real_cost = sum(
            ts.step_inspection.cost_total_real_yuan for ts in traj_steps
        )

        return TrajectoryRecord(
            run_id=uuid.uuid4().hex,
            data_seed=data_seed,
            start_t=start_t,
            end_t=start_t + n_steps - 1,
            n_steps=n_steps,
            steps=traj_steps,
            episode_reward_sum=episode_reward,
            episode_real_cost_yuan=episode_real_cost,
        )
