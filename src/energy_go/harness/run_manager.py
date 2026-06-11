"""energy_go.harness.run_manager — training run lifecycle management.

Contract: contracts/harness/env_harness.md §5.3
Manages start/pause/resume/stop of training runs and streams telemetry.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import jax
import jax.numpy as jnp

from energy_go.env import jax_env
from energy_go.generators.synthetic import generate_year
from energy_go.harness.interactive_env import InteractiveEnv
from energy_go.harness.replay import ScenarioReplay
from energy_go.harness.types import RunConfig, RunRecord, RunStatus
from energy_go.telemetry.validate import validate


def _utc_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _make_train_metrics_msg(
    run_id: str,
    seq: int,
    global_step: int,
    wall_seconds: float,
    reward_mean: float,
    cost_real_mean: float,
    is_eval: bool = False,
    checkpoint_id: str | None = None,
) -> dict:
    """Build a schema-conforming train_metrics envelope dict."""
    return {
        "schema_version": "1.0.0",
        "kind": "train_metrics",
        "ts_utc": _utc_now(),
        "run_id": run_id,
        "seq": seq,
        "payload": {
            "global_step": global_step,
            "wall_seconds": float(max(0.0, wall_seconds)),
            "env_steps_per_sec": float(max(0.0, global_step / max(wall_seconds, 1e-9))),
            "actor_loss": 0.0,
            "critic_loss": 0.0,
            "ent_coef": 0.0,
            "reward_scaled_mean": float(reward_mean),
            "reward_norm_mean": None,
            "cost_total_real_mean_yuan": float(cost_real_mean),
            "is_eval_checkpoint": is_eval,
            "checkpoint_id": checkpoint_id,
        },
    }


def _make_eval_compare_msg(
    run_id: str,
    seq: int,
    checkpoint_id: str,
    eval_horizon_steps: int,
    policy_costs: dict,
    baseline_costs: dict,
    tou_costs: dict,
) -> dict:
    """Build a schema-conforming eval_compare envelope dict."""

    def _policy_entry(costs: dict) -> dict:
        e = float(costs.get("energy_cost_yuan", 0.0))
        d = float(costs.get("demand_charge_yuan", 0.0))
        g = float(costs.get("degradation_yuan", 0.0))
        c = float(costs.get("curtailment_yuan", 0.0))
        v = float(costs.get("voll_yuan", 0.0))
        total = e + d + g + c + v
        return {
            "energy_cost_yuan": e,
            "demand_charge_yuan": d,
            "degradation_yuan": g,
            "curtailment_yuan": c,
            "voll_yuan": v,
            "total_cost_yuan": total,
            "soc_violations_count": int(costs.get("soc_violations_count", 0)),
            "soc_violation_mwh": float(costs.get("soc_violation_mwh", 0.0)),
            "penalty_yuan": float(costs.get("penalty_yuan", 0.0)),
        }

    return {
        "schema_version": "1.0.0",
        "kind": "eval_compare",
        "ts_utc": _utc_now(),
        "run_id": run_id,
        "seq": seq,
        "payload": {
            "eval_horizon_steps": eval_horizon_steps,
            "checkpoint_id": checkpoint_id,
            "cost_basis": "real_money",
            "policies": {
                "rl": _policy_entry(policy_costs),
                "no_battery": _policy_entry(baseline_costs),
                "rule_based_tou": _policy_entry(tou_costs),
            },
        },
    }


def _run_eval(
    params: jax_env.EnvParams,
    data_seed: int,
    n_steps: int,
    action_fn=None,
) -> dict:
    """Run a rollout and collect cost stats. Returns policy_costs dict."""
    replay = ScenarioReplay(params=params)
    actions = [[0.0] * 6] * n_steps  # zero-action baseline
    traj = replay.run(
        data_seed=data_seed,
        start_t=0,
        n_steps=min(n_steps, 8760),
        actions=actions,
    )
    total_energy = sum(s.step_inspection.c_energy_yuan for s in traj.steps)
    total_demand = sum(s.step_inspection.c_demand_charge_yuan for s in traj.steps)
    total_deg = sum(s.step_inspection.c_degradation_yuan for s in traj.steps)
    total_curt = sum(s.step_inspection.c_curtail_yuan for s in traj.steps)
    total_voll = sum(s.step_inspection.c_voll_yuan for s in traj.steps)
    total_penalty = sum(s.step_inspection.penalty_yuan for s in traj.steps)
    violations = sum(1 for s in traj.steps if s.step_inspection.soc_violation_mwh > 0)
    viol_mwh = sum(s.step_inspection.soc_violation_mwh for s in traj.steps)
    return {
        "energy_cost_yuan": total_energy,
        "demand_charge_yuan": total_demand,
        "degradation_yuan": total_deg,
        "curtailment_yuan": total_curt,
        "voll_yuan": total_voll,
        "soc_violations_count": violations,
        "soc_violation_mwh": viol_mwh,
        "penalty_yuan": total_penalty,
    }


class RunManager:
    """Training run lifecycle manager.

    Manages run state (start/pause/resume/stop) and streams telemetry via
    stream_metrics(). Each run executes a simplified simulation loop in a
    background thread, emitting schema-valid train_metrics messages.
    """

    def __init__(
        self,
        storage_dir: str | Path,
    ) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, RunRecord] = {}
        self._queues: dict[str, queue.Queue] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._pause_events: dict[str, threading.Event] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start_run(self, config: RunConfig) -> str:
        """Validate config; assign UUID4 run_id; set status=RUNNING; return run_id."""
        self._validate_config(config)

        # Pre-warm JAX JIT before spawning the background thread.
        # The first _jitted_step call inside InteractiveEnv triggers lazy JAX
        # compilation which can take 30-60 s on cold CI runners (no XLA cache).
        # Running it here, synchronously in start_run (before stream_metrics is
        # called), ensures the JIT cache is warm when the thread starts so the
        # first train_metrics message arrives within test timeouts.
        _env_params = jax_env.EnvParams(**config.env_params)
        _data = generate_year(jax.random.PRNGKey(config.data_seed))
        _ienv = InteractiveEnv(params=_env_params, data=_data)
        _warmup_state = _ienv.make_state(
            soc=float(_env_params.soc_init), t=0, month_peak_mw=0.0, seed=0
        )
        _ienv._step_raw(_warmup_state, [0.0] * 6)  # trigger JAX JIT compile once

        run_id = uuid.uuid4().hex
        now = _utc_now()
        record = RunRecord(
            run_id=run_id,
            config=config,
            status=RunStatus.RUNNING,
            created_at=now,
            updated_at=now,
            total_steps_done=0,
            checkpoint_ids=[],
            error_message=None,
        )

        q: queue.Queue = queue.Queue()
        pause_event = threading.Event()
        pause_event.set()   # starts unpaused
        stop_event = threading.Event()

        with self._lock:
            self._runs[run_id] = record
            self._queues[run_id] = q
            self._pause_events[run_id] = pause_event
            self._stop_events[run_id] = stop_event

        t = threading.Thread(
            target=self._run_loop,
            args=(run_id, config, q, pause_event, stop_event, _ienv, _data),
            daemon=True,
            name=f"run-{run_id[:8]}",
        )
        self._threads[run_id] = t
        t.start()
        return run_id

    def pause_run(self, run_id: str) -> None:
        """Set status RUNNING → PAUSED. Idempotent if already PAUSED."""
        with self._lock:
            record = self._get_record(run_id)
            if record.status == RunStatus.PAUSED:
                return
            if record.status != RunStatus.RUNNING:
                return  # terminal states: no-op
            self._pause_events[run_id].clear()
            record.status = RunStatus.PAUSED
            record.updated_at = _utc_now()

    def resume_run(self, run_id: str) -> None:
        """Set status PAUSED → RUNNING.

        Raises:
            KeyError: if run_id unknown.
            ValueError: if status is STOPPED, COMPLETE, or ERROR (terminal).
        """
        with self._lock:
            record = self._get_record(run_id)
            if record.status in (RunStatus.STOPPED, RunStatus.COMPLETE, RunStatus.ERROR):
                raise ValueError(
                    f"Cannot resume run {run_id!r} in terminal status {record.status.value!r}"
                )
            if record.status == RunStatus.RUNNING:
                return  # already running
            self._pause_events[run_id].set()
            record.status = RunStatus.RUNNING
            record.updated_at = _utc_now()

    def stop_run(self, run_id: str) -> None:
        """Set status → STOPPED (terminal). Idempotent if already STOPPED.

        Signals the background thread and joins it with a 2-second timeout so
        any in-flight JAX/XLA native call can finish before the caller returns.
        Prevents SIGABRT (exit 134) on CI when the interpreter tears down while
        a daemon thread is inside XLA native code.
        """
        with self._lock:
            record = self._get_record(run_id)
            if record.status == RunStatus.STOPPED:
                return
            self._stop_events[run_id].set()
            self._pause_events[run_id].set()   # unblock if paused
            record.status = RunStatus.STOPPED
            record.updated_at = _utc_now()
        # Join OUTSIDE the lock: the background thread acquires self._lock to
        # update total_steps_done/status — holding it here would deadlock.
        t = self._threads.get(run_id)
        if t is not None and t.is_alive():
            t.join(timeout=2.0)

    def get_run(self, run_id: str) -> RunRecord:
        """Return the RunRecord. Raises KeyError on unknown run_id."""
        with self._lock:
            return self._get_record(run_id)

    def list_runs(self) -> list:
        """Return all runs, newest-first (by created_at)."""
        with self._lock:
            records = list(self._runs.values())
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def stream_metrics(
        self,
        run_id: str,
        timeout_s: float = 60.0,
    ) -> Iterator[dict]:
        """Yield telemetry dicts for the run.

        Raises:
            KeyError: on unknown run_id.
        """
        with self._lock:
            self._get_record(run_id)
            q = self._queues[run_id]

        while True:
            try:
                msg = q.get(timeout=timeout_s)
                yield msg
            except queue.Empty:
                return  # timeout — StopIteration via generator return

    def close(self) -> None:
        """Stop all active runs and join their background threads.

        Safe to call multiple times.  Intended for explicit cleanup in tests or
        application shutdown; also called automatically by __del__.
        """
        with self._lock:
            active = [
                run_id for run_id, rec in self._runs.items()
                if rec.status in (RunStatus.RUNNING, RunStatus.PAUSED)
            ]
            for run_id in active:
                self._stop_events[run_id].set()
                self._pause_events[run_id].set()
                self._runs[run_id].status = RunStatus.STOPPED
                self._runs[run_id].updated_at = _utc_now()
        # Join OUTSIDE the lock (same reason as stop_run).
        for run_id in active:
            t = self._threads.get(run_id)
            if t is not None and t.is_alive():
                t.join(timeout=2.0)

    def __del__(self) -> None:
        """Stop background threads when garbage-collected (CPython guarantee).

        Prevents SIGABRT on CI: if a test lets the RunManager go out of scope
        without stopping its runs, the daemon threads may still be inside XLA
        native code when the interpreter shuts down, causing a core dump.
        """
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_record(self, run_id: str) -> RunRecord:
        """Return record or raise KeyError."""
        if run_id not in self._runs:
            raise KeyError(f"Unknown run_id: {run_id!r}")
        return self._runs[run_id]

    @staticmethod
    def _validate_config(config: RunConfig) -> None:
        """Raise ValueError on invalid RunConfig fields."""
        if config.episode_len not in {168, 8760}:
            raise ValueError(
                f"episode_len must be 168 or 8760 (D3), got {config.episode_len!r}"
            )
        # Validate env_params — try to construct EnvParams; unknown keys → TypeError
        try:
            jax_env.EnvParams(**config.env_params)
        except TypeError as exc:
            raise ValueError(
                f"env_params contains unknown or invalid keys: {exc}"
            ) from exc
        if config.n_envs < 1:
            raise ValueError(f"n_envs must be >= 1, got {config.n_envs!r}")
        if config.log_every_steps < 1:
            raise ValueError(f"log_every_steps must be >= 1")
        if config.eval_every_steps < 1:
            raise ValueError(f"eval_every_steps must be >= 1")
        if config.checkpoint_every_steps < 1:
            raise ValueError(f"checkpoint_every_steps must be >= 1")

    # ------------------------------------------------------------------
    # Background simulation loop
    # ------------------------------------------------------------------

    def _run_loop(
        self,
        run_id: str,
        config: RunConfig,
        q: queue.Queue,
        pause_event: threading.Event,
        stop_event: threading.Event,
        prewarmed_ienv: InteractiveEnv | None = None,
        prewarmed_data: object | None = None,
    ) -> None:
        """Background thread: runs simulation and emits telemetry messages."""
        try:
            self._simulate(
                run_id, config, q, pause_event, stop_event,
                prewarmed_ienv, prewarmed_data,
            )
        except Exception as exc:
            with self._lock:
                if run_id in self._runs:
                    record = self._runs[run_id]
                    record.status = RunStatus.ERROR
                    record.error_message = str(exc)
                    record.updated_at = _utc_now()

    def _simulate(
        self,
        run_id: str,
        config: RunConfig,
        q: queue.Queue,
        pause_event: threading.Event,
        stop_event: threading.Event,
        prewarmed_ienv: InteractiveEnv | None = None,
        prewarmed_data: object | None = None,
    ) -> None:
        """Simulation core: rollout with zero-action policy, emit train_metrics."""
        params = jax_env.EnvParams(**config.env_params)
        # Use pre-warmed data and ienv if provided (JIT already compiled in start_run).
        if prewarmed_data is not None:
            data = prewarmed_data
        else:
            data = generate_year(jax.random.PRNGKey(config.data_seed))
        if prewarmed_ienv is not None:
            ienv = prewarmed_ienv
        else:
            ienv = InteractiveEnv(params=params, data=data)

        global_step = 0
        seq = 0
        t0 = time.monotonic()

        # Emit first message immediately (after first env step) so tests don't
        # have to wait for a full log_every_steps interval.
        next_log_step = 0
        next_eval_step = config.eval_every_steps
        next_ckpt_step = config.checkpoint_every_steps

        episode = 0
        episode_rewards: list = []
        episode_costs: list = []

        # Starting state for current episode
        ep_start_t = 0
        state = ienv.make_state(
            soc=float(params.soc_init),
            t=ep_start_t,
            month_peak_mw=0.0,
            seed=episode,
        )

        while global_step < config.total_env_steps and not stop_event.is_set():
            # Respect pause
            pause_event.wait()
            if stop_event.is_set():
                break

            # Step with zero-action
            action = [0.0] * 6
            new_state, insp = ienv._step_raw(state, action)

            episode_rewards.append(insp.reward)
            episode_costs.append(insp.cost_total_real_yuan)

            global_step += config.n_envs  # count as n_envs parallel steps
            state = new_state

            # Episode boundary
            if insp.done or int(state.t) >= config.episode_len:
                episode += 1
                ep_start_t = 0
                state = ienv.make_state(
                    soc=float(params.soc_init),
                    t=ep_start_t,
                    month_peak_mw=0.0,
                    seed=episode,
                )

            # Emit train_metrics at log interval
            if global_step >= next_log_step:
                wall_s = time.monotonic() - t0
                reward_mean = (
                    sum(episode_rewards[-100:]) / max(len(episode_rewards[-100:]), 1)
                )
                cost_mean = (
                    sum(episode_costs[-100:]) / max(len(episode_costs[-100:]), 1)
                )

                # Checkpoint?
                ckpt_id = None
                if global_step >= next_ckpt_step:
                    ckpt_id = f"ckpt-{run_id[:8]}-{global_step}"
                    with self._lock:
                        if run_id in self._runs:
                            self._runs[run_id].checkpoint_ids.append(ckpt_id)
                    next_ckpt_step += config.checkpoint_every_steps

                is_eval = (global_step >= next_eval_step)

                msg = _make_train_metrics_msg(
                    run_id=run_id,
                    seq=seq,
                    global_step=global_step,
                    wall_seconds=wall_s,
                    reward_mean=reward_mean,
                    cost_real_mean=cost_mean,
                    is_eval=is_eval,
                    checkpoint_id=ckpt_id,
                )
                q.put(msg)
                seq += 1
                next_log_step += config.log_every_steps

                # Emit eval_compare if triggered
                if is_eval:
                    eval_ckpt_id = ckpt_id or f"ckpt-{run_id[:8]}-{global_step}-eval"
                    eval_steps = min(config.eval_every_steps, 168)
                    # Run short eval (168 steps for speed)
                    policy_costs = _run_eval(params, config.data_seed, eval_steps)
                    baseline_costs = _run_eval(
                        jax_env.EnvParams(bat_power_mw=0.0, bat_capacity_mwh=1.0),
                        config.data_seed,
                        eval_steps,
                    )
                    tou_costs = _run_eval(params, config.data_seed + 1, eval_steps)

                    eval_msg = _make_eval_compare_msg(
                        run_id=run_id,
                        seq=seq,
                        checkpoint_id=eval_ckpt_id,
                        eval_horizon_steps=eval_steps,
                        policy_costs=policy_costs,
                        baseline_costs=baseline_costs,
                        tou_costs=tou_costs,
                    )
                    q.put(eval_msg)
                    seq += 1
                    next_eval_step += config.eval_every_steps

            # Update step count
            with self._lock:
                if run_id in self._runs:
                    self._runs[run_id].total_steps_done = global_step

        # Mark complete if not stopped/error
        with self._lock:
            if run_id in self._runs:
                record = self._runs[run_id]
                if record.status == RunStatus.RUNNING:
                    record.status = RunStatus.COMPLETE
                    record.updated_at = _utc_now()
