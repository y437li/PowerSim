# Contract: env_harness — Training & Testing Control Layer

- **Area:** harness
- **Branch:** `feat/harness-env-harness`
- **Spec sections:** §2 (MDP), §3 (physics & costs), §4 (synthetic generators), §5 (training/eval), §7 (JAX architecture)
- **Decisions:** D3 (Δt=1 h, 168/8760 steps), D4 (SOC [0.2,0.9]), D5 (export 945 MW), D12 (import 400 MW), D13 (real/reward-basis cost split), D18 (machine-readable telemetry schema), D21 (sub-month demand charge = 0), D22(c) (harness authored in parallel against locked env-step signature)
- **Status:** DRAFT — awaiting backend-reviewer APPROVE before implementation
- **Review record:** `contracts/reviews/env_harness.md` (to be created by reviewer)
- **Depends on:**
  - `contracts/env/jax_env_core.md` (APPROVED PR #33, commit 4fd668a) — `energy_go.env.jax_env.{EnvState, EnvParams, EnvInfo, step, reset, get_obs, PRICE_TABLE_YPW, MONTH_OF_STEP}`
  - `energy_go.generators.synthetic.generate_year` (PR #33)
  - `contracts/shared/telemetry_schema.md` v1.0.0 (LOCKED PR #6) — all emitted messages
  - `energy_go.telemetry.validate` (merged PR #23) — validator utility
  - Training loop (`energy_go.training.*`) — TBD by training-engineer (PR #19); harness wraps it via a hook interface

---

## 1. Scope

The env harness is the **controllable interface** between the JAX env core and the rest of the system (dashboard, training pipeline, serving, tests). It does **not** re-implement physics, cost accounting, or the SAC update — those live in the env and training layers respectively. If a required hook is absent, a contract-change request is filed (see §2).

Four capabilities:

1. **`InteractiveEnv`** — debugging interface: explicit state construction (`make_state`), single-step inspection (`step`), observation query (`get_obs`), full env reset.
2. **`ScenarioReplay`** — deterministic trajectory replay: run a fixed action sequence or a policy callable over a chosen synthetic-year slice; return the complete trajectory for analysis.
3. **`RunManager`** — training run lifecycle: start/pause/resume/stop; track run history, configs, and checkpoints; stream `train_metrics` / `eval_compare` telemetry conforming to the LOCKED schema.
4. **`Sweeper`** — vmapped hyperparameter/domain-randomization sweeps; collect per-variant metrics.

---

## 2. Required EnvInfo extension (dependency note)

The LOCKED telemetry `env_step` payload (§2 / `contracts/shared/telemetry_schema.md`) requires **per-source power flows** (`solar_to_load_mw`, `wind_to_bat_mw`, `grid_to_load_mw`, etc.). The APPROVED `EnvInfo` NamedTuple (PR #33) carries only **aggregate** flows.

**The harness MUST NOT recompute per-source flows itself** (that would duplicate physics — charter violation). Therefore the following additive fields are required on `EnvInfo` (a minor amendment to the jax_env_core contract, no signature change to `step()`):

| Required new field | Meaning (see §5.3.5 of jax_env_core) |
|---|---|
| `p_sol_to_load_mw` | P_sol_to_load after load cap and load-scale (MW, ≥ 0) |
| `p_sol_to_bat_mw` | P_sol_to_bat after load cap (MW, ≥ 0) |
| `p_sol_to_grid_mw` | P_pv − P_sol_to_load − P_sol_to_bat (MW, ≥ 0) |
| `p_sol_curtailed_mw` | P_pv share of P_curtailed at PCC export cap (MW, ≥ 0) |
| `p_wind_to_load_mw` | P_wind_to_load after load cap and load-scale (MW, ≥ 0) |
| `p_wind_to_bat_mw` | P_wind_to_bat after load cap (MW, ≥ 0) |
| `p_wind_to_grid_mw` | P_wind − P_wind_to_load − P_wind_to_bat (MW, ≥ 0) |
| `p_wind_curtailed_mw` | P_wind share of P_curtailed at PCC export cap (MW, ≥ 0) |
| `p_bat_to_load_mw` | Battery discharge routed to load (MW, ≥ 0) |
| `p_bat_to_grid_mw` | Battery discharge routed to grid **after** PCC export cap (MW, ≥ 0) |
| `p_bat_curtailed_mw` | Battery share of P_curtailed at PCC export cap (MW, ≥ 0); **non-zero** when a discharging battery contributes to grid export that exceeds max_export_mw (§5.3.5: scale_export applied to P_bat_to_grid) |
| `p_grid_to_bat_mw` | Grid power for battery charging (MW, ≥ 0) |
| `p_grid_to_load_mw` | Grid power for load (= P_import − P_grid_to_bat_mw, ≥ 0) |

These 13 fields are all computed internally in §5.3.5 of the jax_env_core contract but not yet exposed in `EnvInfo`. Adding them is a minor additive amendment (no existing field changes, no step() signature change). The harness implementation is **blocked** on this amendment being merged.

**Battery curtailment clarification (F1 from backend-reviewer):** `P_bat_curtailed_mw` can be positive whenever a discharging battery pushes total grid export above the PCC cap. The jax_env_core §5.3.5 export-cap formula scales all three grid channels (`P_sol_to_grid`, `P_wind_to_grid`, `P_bat_to_grid`) by the same `scale_export` factor — so the battery share of curtailment = `P_bat_to_grid_pre × (1 − scale_export)`. This is NOT a §3.6 fidelity-boundary item; it is a consequence of the existing physics. The earlier note "always 0" was incorrect and has been removed.

---

## 3. Module structure

```
src/energy_go/harness/
  __init__.py
  types.py            — RunConfig, RunRecord, RunStatus, StepInspection,
                        TrajectoryStep, TrajectoryRecord, SweepVariant, SweepResult
  interactive_env.py  — InteractiveEnv
  replay.py           — ScenarioReplay
  run_manager.py      — RunManager
  sweeper.py          — Sweeper
```

Import paths: `energy_go.harness.{InteractiveEnv, ScenarioReplay, RunManager, Sweeper}` and
`energy_go.harness.types.{RunConfig, RunRecord, RunStatus, StepInspection, ...}`.

---

## 4. Types

### 4.1 `RunStatus` (str enum)

```python
class RunStatus(str, enum.Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    PAUSED    = "paused"
    STOPPED   = "stopped"
    COMPLETE  = "complete"
    ERROR     = "error"
```

### 4.2 `RunConfig` (dataclass, all fields serialisable to JSON)

```python
@dataclass
class RunConfig:
    # --- Env ---
    env_params: dict        # kwargs passed to EnvParams(**env_params); unknown keys raise ValueError
    data_seed: int          # RNG seed passed to generate_year()
    episode_len: int = 168  # D3: 168 for training; 8760 for eval-only runs

    # --- Training budget ---
    total_env_steps: int = 1_000_000

    # --- Logging / checkpointing ---
    log_every_steps: int = 1_000          # emit train_metrics every N env steps
    eval_every_steps: int = 50_000        # run eval + emit eval_compare every N steps
    checkpoint_every_steps: int = 50_000  # write checkpoint every N steps

    # --- Parallelism ---
    n_envs: int = 8  # number of vmapped envs

    # --- SAC hyperparams (passed to training-engineer's loop hook) ---
    learning_rate: float = 3e-4
    gamma: float = 0.99
    batch_size: int = 256
    buffer_size: int = 1_000_000
```

**Validation** (enforced by `RunManager.start_run`):
- `episode_len ∈ {168, 8760}` (D3)
- `total_env_steps ≥ episode_len × n_envs`
- `n_envs ≥ 1`
- `log_every_steps ≥ 1`, `eval_every_steps ≥ 1`, `checkpoint_every_steps ≥ 1`
- Unknown keys in `env_params` raise `ValueError`

### 4.3 `RunRecord` (dataclass)

```python
@dataclass
class RunRecord:
    run_id: str                 # UUID4 hex
    config: RunConfig
    status: RunStatus
    created_at: str             # ISO-8601 UTC string (wall-clock)
    updated_at: str             # ISO-8601 UTC string (wall-clock)
    total_steps_done: int       # env steps completed so far (across all envs)
    checkpoint_ids: list[str]   # ordered list of checkpoint_ids written (matches train_metrics.checkpoint_id)
    error_message: str | None   # non-null iff status == ERROR
```

### 4.4 `StepInspection` (dataclass — the primary debugging type)

One instance per harness `InteractiveEnv.step()` call. Exposes **every intermediate quantity** computed during the env step. All MW / ¥ / fraction fields are Python `float`; arrays are `list[float]`.

**Units follow the project rule and LOCKED telemetry schema exactly** (MW for power, ¥ for costs, fraction [0,1] for SOC, ¥/MWh for prices, ¥/MW·month for demand rate).

```python
@dataclass
class StepInspection:
    # === Input state (before action applied) ===
    soc_in: float                        # SOC fraction, [soc_min, soc_max]
    t_in: int                            # step index [0, 8759]
    month_peak_in_mw: float              # running monthly import peak before this step (MW)

    # === Action ===
    action_raw: list[float]              # length-6, as provided by caller
    action_clipped: list[float]          # after jnp.clip to bounds
                                         # a_bat ∈ [−1,1]; f_* ∈ [0,1]

    # === Renewable generation (MW) ===
    p_pv_mw: float                       # gross solar, §3.1
    p_wind_mw: float                     # gross wind, §3.1

    # === Battery dynamics ===
    p_bat_commanded_ch_mw: float         # a_bat × bat_power_mw (before SOC cap); ≥ 0
    p_bat_commanded_dis_mw: float        # |a_bat| × bat_power_mw (discharge mode, before SOC cap); ≥ 0
    p_bat_ch_mw: float                   # actual charge after SOC cap (≥ 0)
    p_bat_dis_mw: float                  # actual discharge after SOC cap (≥ 0)
    soc_out: float                       # new SOC fraction after step
    soc_violation_mwh: float             # overshoot energy (≥ 0); > 0 triggers penalty

    # === Per-source power flows (MW) — requires EnvInfo extension (§2) ===
    solar_to_load_mw: float              # post load-cap
    solar_to_bat_mw: float
    solar_to_grid_mw: float
    solar_curtailed_mw: float            # PCC export cap share; ≥ 0
    wind_to_load_mw: float               # post load-cap
    wind_to_bat_mw: float
    wind_to_grid_mw: float
    wind_curtailed_mw: float             # PCC export cap share; ≥ 0
    bat_to_load_mw: float
    bat_to_grid_mw: float                # after PCC export cap
    bat_curtailed_mw: float              # battery share of PCC export curtailment (≥ 0);
                                         # non-zero when discharging battery contributes to
                                         # export that exceeds max_export_mw (§5.3.5)
    grid_to_load_mw: float
    grid_to_bat_mw: float
    load_unserved_mw: float              # VOLL trigger; ≥ 0

    # === Aggregate PCC flows (MW) ===
    p_export_mw: float                   # ≤ max_export_mw
    p_import_mw: float                   # ≤ max_import_mw
    load_mw: float                       # site load demand for this step (MW)
    max_export_mw: float                 # site param (D5)
    max_import_mw: float                 # site param (D12)

    # === Time ===
    hour_of_day: int                     # t % 24; 0–23
    tariff_tier: str                     # "valley" | "mid" | "peak" | "critical_peak"

    # === Prices (¥/MWh) ===
    price_buy_yuan_per_mwh: float
    price_sell_yuan_per_mwh: float       # D7: ≤ price_buy

    # === Per-step costs (¥) — D13 cost accounting ===
    c_import_yuan: float                 # C_import = price_buy × P_import × Δt
    r_export_yuan: float                 # R_export = price_sell × P_export × Δt
    c_energy_yuan: float                 # C_E = C_import − R_export; can be negative
    c_demand_shape_yuan: float           # raw C_DC_shape (demand_rate × max(0, P_import − month_peak_in)); reward-only
    c_demand_charge_yuan: float          # real monthly ¥; 0 except at month boundary or t=8759 (D10/D21)
    c_degradation_yuan: float            # 10 ¥/MWh × (P_ch + P_dis) × 1 h
    c_curtail_yuan: float                # 800 ¥/MWh × P_curtailed × 1 h
    c_voll_yuan: float                   # 20 000 ¥/MWh × P_load_unserved × 1 h
    penalty_yuan: float                  # 20 000 ¥/MWh × soc_violation_mwh
    demand_rate_yuan_per_mw_month: float # carried from params (32 000 by default)
    cost_total_real_yuan: float          # D13: C_E + c_demand_charge + C_deg + C_curtail + C_VOLL
    cost_total_reward_basis_yuan: float  # D13: C_E + 2·c_demand_shape + C_deg + C_curtail + C_VOLL

    # === Reward ===
    reward: float                        # −(cost_total_reward_basis + penalty) × reward_scale

    # === Output state ===
    month_peak_out_mw: float             # updated running monthly import peak (MW)
    t_out: int                           # state.t + 1
    done: bool                           # t_in == episode_len − 1

    # === Observation (107-dim, §2.1 / §5.4 of jax_env_core) ===
    obs: list[float]                     # length 107; raw/lightly-normalised

    # === Constraint flags (derived by harness from EnvInfo) ===
    constraint_action_clipped: bool      # any action dimension was clipped to its bound
    constraint_soc_clipped: bool         # soc_violation_mwh > 0
    constraint_load_capped: bool         # load-cap scale < 1 (flows-to-load > load_mw before cap)
    constraint_export_capped: bool       # export-cap scale < 1 (export_raw > max_export_mw)
    constraint_import_capped: bool       # P_import_raw > max_import_mw (load_unserved > 0
                                         #   OR grid_to_bat was reduced)

    # === Conservation checks (computed by harness, tol = 1e-3 MW) ===
    solar_conservation_ok: bool          # |solar_to_load + solar_to_bat + solar_to_grid
                                         #   + solar_curtailed − p_pv_mw| < 1e-3
    wind_conservation_ok: bool           # |wind_to_load + wind_to_bat + wind_to_grid
                                         #   + wind_curtailed − p_wind_mw| < 1e-3
    bat_conservation_ok: bool            # |bat_to_load + bat_to_grid + bat_curtailed
                                         #   − p_bat_dis_mw| < 1e-3 (discharge mode);
                                         # in charge mode: p_bat_dis_mw=0 and all bat_ flows=0
```

### 4.5 `TrajectoryStep` (dataclass)

```python
@dataclass
class TrajectoryStep:
    seq: int                        # 0-indexed within this trajectory (0 = first step)
    step_inspection: StepInspection
```

### 4.6 `TrajectoryRecord` (dataclass)

```python
@dataclass
class TrajectoryRecord:
    run_id: str                         # UUID4 hex (generated by ScenarioReplay)
    data_seed: int
    start_t: int                        # inclusive
    end_t: int                          # inclusive; == start_t + n_steps − 1
    n_steps: int
    steps: list[TrajectoryStep]         # len == n_steps
    episode_reward_sum: float           # Σ step_inspection.reward over all steps
    episode_real_cost_yuan: float       # Σ step_inspection.cost_total_real_yuan
```

### 4.7 `SweepVariant` (dataclass)

```python
@dataclass
class SweepVariant:
    variant_id: str                         # caller-assigned, unique within a sweep
    env_params_overrides: dict              # subset of EnvParams fields to override
    training_params_overrides: dict         # subset of RunConfig training-hyperParam fields to override
                                            # (learning_rate, gamma, batch_size, buffer_size)
```

### 4.8 `SweepResult` (dataclass)

```python
@dataclass
class SweepResult:
    variant_id: str
    seed: int
    run_id: str
    n_eval_steps: int
    reward_mean: float                      # mean per-episode reward over the eval
    cost_total_real_mean_yuan: float        # mean per-episode real-money cost (¥)
    completed: bool
    error_message: str | None
```

---

## 5. Interface specifications

### 5.1 `InteractiveEnv`

```python
class InteractiveEnv:
    def __init__(
        self,
        params: energy_go.env.jax_env.EnvParams,
        data: energy_go.generators.synthetic.SyntheticYear,  # shape (8760, 4)
    ) -> None: ...

    def make_state(
        self,
        soc: float,
        t: int,
        month_peak_mw: float = 0.0,
        seed: int = 0,
    ) -> energy_go.env.jax_env.EnvState:
        """Construct an explicit EnvState. Validates inputs; raises ValueError on bad args."""

    def step(
        self,
        state: energy_go.env.jax_env.EnvState,
        action: Sequence[float],            # length 6
    ) -> StepInspection:
        """Apply one env step. Returns full StepInspection with every internal quantity."""

    def get_obs(
        self,
        state: energy_go.env.jax_env.EnvState,
    ) -> list[float]:                       # length 107
        """Compute observation for state without stepping (wraps jax_env.get_obs)."""

    def reset(
        self,
        seed: int = 0,
    ) -> tuple[energy_go.env.jax_env.EnvState, list[float]]:
        """Full env reset using jax_env.reset. Returns (state, obs)."""
```

**Error behaviour:**
- `make_state`: `ValueError` if `soc` ∉ `[params.soc_min, params.soc_max]`; `ValueError` if `t` ∉ `[0, 8759]`; `ValueError` if `month_peak_mw < 0`.
- `step`: `ValueError` if `len(action) != 6`; converts `action` to float32 internally (no error on int input).
- `get_obs`, `reset`: no additional input validation beyond what jax_env provides.

**Determinism:** same `(params, data, state, action)` → identical `StepInspection`.

**Jit behaviour:** the `step()` call internally invokes `jax.jit(jax_env.step)` with the fixed `(params, data)` as static args (compiled on first call, cached thereafter). The resulting `StepInspection` is a plain Python dataclass (not a JAX pytree).

### 5.2 `ScenarioReplay`

```python
class ScenarioReplay:
    def __init__(
        self,
        params: energy_go.env.jax_env.EnvParams,
    ) -> None: ...

    def run(
        self,
        data_seed: int,
        start_t: int,
        n_steps: int,
        actions: Sequence[Sequence[float]] | None = None,  # fixed action list; len == n_steps
        policy_fn: Callable[[np.ndarray], np.ndarray] | None = None,  # obs (107,) → action (6,)
        state_seed: int = 0,                                # seed for EnvState.rng at start_t
    ) -> TrajectoryRecord:
        """Run a deterministic trajectory. Exactly one of actions or policy_fn must be provided."""
```

**Constraints:**
- Exactly one of `actions`, `policy_fn` must be non-None; both non-None or both None raise `ValueError`.
- `len(actions) == n_steps` if `actions` provided; else `ValueError`.
- `start_t ≥ 0`, `start_t + n_steps ≤ 8760`; else `ValueError`.
- `n_steps ≥ 1`; else `ValueError`.

**Determinism:** same `(data_seed, start_t, n_steps, actions, state_seed)` → byte-identical `TrajectoryRecord`.

**Initial state:** `EnvState(soc=params.soc_init, month_peak=0.0, t=start_t, rng=jax.random.PRNGKey(state_seed))`.

### 5.3 `RunManager`

```python
class RunManager:
    def __init__(
        self,
        storage_dir: str | Path,       # directory for run records and checkpoints
    ) -> None: ...

    def start_run(self, config: RunConfig) -> str:
        """Validate config; assign UUID4 run_id; set status=RUNNING; return run_id."""

    def pause_run(self, run_id: str) -> None:
        """Set status RUNNING → PAUSED. Idempotent if already PAUSED. Raises KeyError on unknown run_id."""

    def resume_run(self, run_id: str) -> None:
        """Set status PAUSED → RUNNING. Raises KeyError on unknown run_id.
        Raises ValueError if status is STOPPED or COMPLETE (terminal)."""

    def stop_run(self, run_id: str) -> None:
        """Set status → STOPPED (terminal). Idempotent if already STOPPED.
        Raises KeyError on unknown run_id."""

    def get_run(self, run_id: str) -> RunRecord:
        """Return the RunRecord. Raises KeyError on unknown run_id."""

    def list_runs(self) -> list[RunRecord]:
        """Return all runs, newest-first (by created_at)."""

    def stream_metrics(
        self,
        run_id: str,
        timeout_s: float = 60.0,
    ) -> Iterator[dict]:
        """Yield telemetry dicts for the run. Raises KeyError on unknown run_id.
        Times out (StopIteration) if no message arrives within timeout_s."""
```

**Telemetry protocol (stream_metrics):**
- Each yielded dict is a **valid telemetry envelope** per `contracts/shared/telemetry_schema.md` v1.0.0.
- `kind` is `"train_metrics"` or `"eval_compare"`.
- `run_id` in the envelope equals the argument.
- `seq` increments by exactly 1 per `(run_id, kind)` pair across the entire run (not reset at episode boundaries per LOCKED schema).
- All numeric fields are finite (no NaN/Inf).
- `schema_version == "1.0.0"`.

**Status transitions:**

```
PENDING → RUNNING   (start_run)
RUNNING → PAUSED    (pause_run; idempotent)
PAUSED  → RUNNING   (resume_run)
RUNNING → STOPPED   (stop_run; idempotent from STOPPED)
RUNNING → COMPLETE  (training loop completes total_env_steps)
RUNNING → ERROR     (unrecoverable exception in training loop)
STOPPED is terminal (resume_run raises ValueError)
COMPLETE is terminal (pause/resume raise ValueError)
ERROR   is terminal (pause/resume raise ValueError)
```

**run_id uniqueness:** each `start_run` call generates a fresh UUID4; no two runs in the same `RunManager` share a `run_id`.

### 5.4 `Sweeper`

```python
class Sweeper:
    def __init__(
        self,
        storage_dir: str | Path,
    ) -> None: ...

    def run_sweep(
        self,
        variants: Sequence[SweepVariant],
        n_seeds: int,
        n_eval_steps: int = 8760,       # steps per eval; D3: 8760 for full-year
        base_config: RunConfig | None = None,  # overrides applied on top; defaults used if None
    ) -> list[SweepResult]:
        """Run len(variants) × n_seeds evaluations. Returns list[SweepResult] length len(variants)×n_seeds."""
```

**Constraints:**
- `len(variants) ≥ 1`; `n_seeds ≥ 1`; `n_eval_steps ≥ 1`.
- variant_ids must be unique within the sweep; else `ValueError`.
- Evaluations use `jax.vmap` over seeds for each variant when possible.
- Determinism: same `(variant, seed, base_config)` → identical `SweepResult`.

---

## 6. Telemetry emission contract

`RunManager.stream_metrics()` produces the telemetry consumed by the dashboard's training panel and the 3D scene. All emitted messages MUST pass `energy_go.telemetry.validate` (D18).

### 6.1 `train_metrics` payload (kind = "train_metrics")

Fields match `contracts/shared/telemetry_schema.md` Kind 2 exactly:

```jsonc
{
  "global_step": 1000,
  "wall_seconds": 0.84,
  "env_steps_per_sec": 1.19e6,
  "actor_loss": 0.42,
  "critic_loss": 1.31,
  "ent_coef": 0.18,
  "reward_scaled_mean": 0.61,
  "reward_norm_mean": null,       // null at eval checkpoints
  "cost_total_real_mean_yuan": -61000.0,
  "is_eval_checkpoint": false,
  "checkpoint_id": null           // non-null when checkpoint written
}
```

### 6.2 `eval_compare` payload (kind = "eval_compare")

Fields match `contracts/shared/telemetry_schema.md` Kind 3 exactly:

```jsonc
{
  "eval_horizon_steps": 8760,
  "checkpoint_id": "string",
  "cost_basis": "real_money",
  "policies": {
    "rl":             { "energy_cost_yuan": 0, ... , "total_cost_yuan": 0, "soc_violations_count": 0, "soc_violation_mwh": 0.0, "penalty_yuan": 0.0 },
    "no_battery":     { ... },
    "rule_based_tou": { ... }
  }
}
```

**Additive identity** (per policy): `total_cost_yuan = energy_cost_yuan + demand_charge_yuan + degradation_yuan + curtailment_yuan + voll_yuan`.

### 6.3 Envelope invariants

- `schema_version = "1.0.0"`
- `run_id` matches the started run
- `seq` strictly monotonic per `(run_id, kind)` — does NOT reset at episode boundaries
- `ts_utc` is the wall-clock emit time (ISO-8601 UTC)
- Every numeric field is finite (producer MUST clip/guard before emit)

---

## 7. Determinism guarantee

All four components are deterministic under fixed seeds:

| Component | Seed inputs | Invariant |
|---|---|---|
| `InteractiveEnv.step` | `(params, data, state)` | Same inputs → identical `StepInspection` |
| `ScenarioReplay.run` | `data_seed, start_t, actions, state_seed` | Same inputs → byte-identical `TrajectoryRecord` |
| `RunManager` | `config.data_seed` | Same config → same eval metrics trajectory |
| `Sweeper.run_sweep` | `variant, seed, base_config` | Same variant+seed → identical `SweepResult` |

JAX stochastic draws (sell-price spread, forecast noise) are threaded via explicit `jax.random.PRNGKey`; fixing the key in `make_state`/`replay.run` fixes all draws downstream.

---

## 8. Deliberate deviations

None. The harness applies the same §6 fixes as the env core (via delegation — it calls `jax_env.step` directly without any physics override).

---

## 9. Out of scope

- Physics, cost accounting, SAC update — implemented by env/training layers
- VecNormalize (running mean/std normalization) — training layer; harness exposes raw obs
- ONNX export — serving layer
- §8 composable assets (gas, electrolyzers) — D2/D23 sequencing; harness will naturally support them when `EnvInfo` is extended for §8
- §10 Tier-1 enhancements (E2/E5) — D17 sequencing; default-OFF toggles in env params
- HTTP/WebSocket transport — serving layer wraps the harness; `stream_metrics` is a Python iterator
- Multi-site scenarios
