"""energy_go.harness.types — shared dataclasses for the training & testing harness.

Contract: contracts/harness/env_harness.md §4
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# RunStatus
# ---------------------------------------------------------------------------

class RunStatus(str, enum.Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    PAUSED   = "paused"
    STOPPED  = "stopped"
    COMPLETE = "complete"
    ERROR    = "error"


# ---------------------------------------------------------------------------
# RunConfig
# ---------------------------------------------------------------------------

@dataclass
class RunConfig:
    # --- Env ---
    env_params: dict           # kwargs passed to EnvParams(**env_params); unknown keys raise ValueError
    data_seed: int             # RNG seed passed to generate_year()
    episode_len: int = 168     # D3: 168 for training; 8760 for eval-only runs

    # --- Training budget ---
    total_env_steps: int = 1_000_000

    # --- Logging / checkpointing ---
    log_every_steps: int = 1_000          # emit train_metrics every N env steps
    eval_every_steps: int = 50_000        # run eval + emit eval_compare every N steps
    checkpoint_every_steps: int = 50_000  # write checkpoint every N steps

    # --- Parallelism ---
    n_envs: int = 8  # number of vmapped envs

    # --- SAC hyperparams ---
    learning_rate: float = 3e-4
    gamma: float = 0.99
    batch_size: int = 256
    buffer_size: int = 1_000_000


# ---------------------------------------------------------------------------
# RunRecord
# ---------------------------------------------------------------------------

@dataclass
class RunRecord:
    run_id: str                      # UUID4 hex
    config: RunConfig
    status: RunStatus
    created_at: str                  # ISO-8601 UTC string (wall-clock)
    updated_at: str                  # ISO-8601 UTC string (wall-clock)
    total_steps_done: int            # env steps completed so far (across all envs)
    checkpoint_ids: list             # ordered list of checkpoint_ids written
    error_message: Optional[str]     # non-null iff status == ERROR


# ---------------------------------------------------------------------------
# StepInspection
# ---------------------------------------------------------------------------

@dataclass
class StepInspection:
    # === Input state (before action applied) ===
    soc_in: float
    t_in: int
    month_peak_in_mw: float

    # === Action ===
    action_raw: list            # length-6, as provided by caller
    action_clipped: list        # after clip to bounds

    # === Renewable generation (MW) ===
    p_pv_mw: float
    p_wind_mw: float

    # === Battery dynamics ===
    p_bat_commanded_ch_mw: float
    p_bat_commanded_dis_mw: float
    p_bat_ch_mw: float
    p_bat_dis_mw: float
    soc_out: float
    soc_violation_mwh: float

    # === Per-source power flows (MW) ===
    solar_to_load_mw: float
    solar_to_bat_mw: float
    solar_to_grid_mw: float
    solar_curtailed_mw: float
    wind_to_load_mw: float
    wind_to_bat_mw: float
    wind_to_grid_mw: float
    wind_curtailed_mw: float
    bat_to_load_mw: float
    bat_to_grid_mw: float
    bat_curtailed_mw: float
    grid_to_load_mw: float
    grid_to_bat_mw: float
    load_unserved_mw: float

    # === Aggregate PCC flows (MW) ===
    p_export_mw: float
    p_import_mw: float
    load_mw: float
    max_export_mw: float
    max_import_mw: float

    # === Time ===
    hour_of_day: int
    tariff_tier: str

    # === Prices (¥/MWh) ===
    price_buy_yuan_per_mwh: float
    price_sell_yuan_per_mwh: float

    # === Per-step costs (¥) ===
    c_import_yuan: float
    r_export_yuan: float
    c_energy_yuan: float
    c_demand_shape_yuan: float
    c_demand_charge_yuan: float
    c_degradation_yuan: float
    c_curtail_yuan: float
    c_voll_yuan: float
    penalty_yuan: float
    demand_rate_yuan_per_mw_month: float
    cost_total_real_yuan: float
    cost_total_reward_basis_yuan: float

    # === Reward ===
    reward: float

    # === Output state ===
    month_peak_out_mw: float
    t_out: int
    done: bool

    # === Observation (107-dim) ===
    obs: list

    # === Constraint flags ===
    constraint_action_clipped: bool
    constraint_soc_clipped: bool
    constraint_load_capped: bool
    constraint_export_capped: bool
    constraint_import_capped: bool

    # === Conservation checks ===
    solar_conservation_ok: bool
    wind_conservation_ok: bool
    bat_conservation_ok: bool


# ---------------------------------------------------------------------------
# TrajectoryStep / TrajectoryRecord
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryStep:
    seq: int                         # 0-indexed within this trajectory
    step_inspection: StepInspection


@dataclass
class TrajectoryRecord:
    run_id: str                      # UUID4 hex (generated by ScenarioReplay)
    data_seed: int
    start_t: int                     # inclusive
    end_t: int                       # inclusive; == start_t + n_steps - 1
    n_steps: int
    steps: list                      # list[TrajectoryStep], len == n_steps
    episode_reward_sum: float
    episode_real_cost_yuan: float


# ---------------------------------------------------------------------------
# SweepVariant / SweepResult
# ---------------------------------------------------------------------------

@dataclass
class SweepVariant:
    variant_id: str
    env_params_overrides: dict
    training_params_overrides: dict


@dataclass
class SweepResult:
    variant_id: str
    seed: int
    run_id: str
    n_eval_steps: int
    reward_mean: float
    cost_total_real_mean_yuan: float
    completed: bool
    error_message: Optional[str]
