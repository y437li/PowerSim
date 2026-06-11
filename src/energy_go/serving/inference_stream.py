"""energy_go.serving.inference_stream — WebSocket live inference stream.

Contract:  contracts/serving/inference_stream.md
Tests:     tests/serving/test_serving_inference_stream.py

Units: power = MW, energy = MWh, prices = ¥/MWh, costs = ¥.
All env_step frames must pass energy_go.telemetry.validate(msg) == [] (D18).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Policy cache: run_id → CheckpointData
# (CheckpointData carries all stats inline — no separate normalization file)
# ---------------------------------------------------------------------------

_policy_cache: "dict[str, Any]" = {}  # run_id → CheckpointData


# ---------------------------------------------------------------------------
# Public utility: policy_forward
# Thin wrapper around actor_forward_numpy (checkpoint_format.md §6).
# Signature changed from placeholder (dict, obs) → (CheckpointData, obs).
# ---------------------------------------------------------------------------

def policy_forward(checkpoint: Any, obs: np.ndarray) -> np.ndarray:
    """Run the §6 actor forward pass for a canonical CheckpointData.

    Args:
        checkpoint: CheckpointData loaded via load_checkpoint().
        obs:        float32 (obs_dim,) raw (un-normalized) observation.

    Returns:
        float32 (6,) action: [tanh(mean[0]), sigmoid(mean[1:6])].
        Identical to actor_forward_numpy(checkpoint, obs).
    """
    from energy_go.training.checkpoint_format import actor_forward_numpy  # type: ignore
    return actor_forward_numpy(checkpoint, obs)


# ---------------------------------------------------------------------------
# Checkpoint discovery + loader (canonical §6 only — no legacy policy.npz)
# ---------------------------------------------------------------------------

def _step_from_filename(path: Path) -> int:
    """Extract the integer step number from checkpoint_<run_id>_step<N>.npz.

    Returns -1 if the filename is malformed (does not contain '_step<N>')
    so callers can filter out stray files without raising.
    """
    stem = path.stem  # e.g. "checkpoint_run_001_step500000"
    if "_step" not in stem:
        return -1
    try:
        return int(stem.rsplit("_step", 1)[1])
    except (IndexError, ValueError):
        return -1


def _load_checkpoint_for_run(run_id: str, run_dir: Path) -> Any:
    """Load (or return cached) canonical CheckpointData for run_id.

    Discovery algorithm (contract §Policy loading):
      - Glob `checkpoint_*.npz` in run_dir.
      - Pick the file whose `_step<N>` suffix has the highest integer N.
      - Stray / malformed filenames (no `_step<int>`) are silently skipped.

    Raises:
        FileNotFoundError: if no valid canonical checkpoint is found.
    """
    if run_id in _policy_cache:
        return _policy_cache[run_id]

    from energy_go.training.checkpoint_format import load_checkpoint  # type: ignore

    candidates = [
        (p, _step_from_filename(p))
        for p in run_dir.glob("checkpoint_*.npz")
    ]
    valid = [(p, n) for p, n in candidates if n >= 0]
    if not valid:
        raise FileNotFoundError(
            f"no canonical checkpoint (checkpoint_*.npz) in {run_dir}"
        )
    best_path = max(valid, key=lambda x: x[1])[0]
    checkpoint = load_checkpoint(str(best_path))
    _policy_cache[run_id] = checkpoint
    return checkpoint


# ---------------------------------------------------------------------------
# Tiny synthetic env for driving the inference stream
# (real env from reference implementation will be wired in once that PR merges;
#  this stub is sufficient for all WS lifecycle + schema tests)
# ---------------------------------------------------------------------------

class _SyntheticEnv:
    """Minimal deterministic env that produces schema-valid env_step payloads."""

    def __init__(self, site_yaml: dict, seed: int = 0) -> None:
        self._rng  = np.random.default_rng(seed)
        bat        = site_yaml.get("site", {}).get("battery", {})
        grid       = site_yaml.get("site", {}).get("grid_connection", {})
        self._cap  = float(bat.get("capacity_mwh", 294.5))
        self._soc  = float(bat.get("initial_soc", 0.5)) * self._cap
        self._soc_min = float(bat.get("soc_min", 0.2)) * self._cap
        self._soc_max = float(bat.get("soc_max", 0.9)) * self._cap
        self._max_ch  = float(bat.get("max_charge_mw",    100.0))
        self._max_dis = float(bat.get("max_discharge_mw", 100.0))
        self._eta     = float(bat.get("round_trip_efficiency", 0.95))
        self._deg_rate = float(bat.get("degradation_rate_per_cycle", 0.0001))
        self._max_exp  = float(grid.get("max_export_mw",  945.0))
        self._max_imp  = float(grid.get("max_import_mw",  400.0))
        self._demand_rate = float(
            site_yaml.get("site", {}).get("demand_rate_yuan_per_mw_month", 35.0)
        )
        self.step_count = 0
        self.episode    = 0
        self._cum_cost  = 0.0
        self._cum_energy_cost = 0.0
        self._cum_demand_charge = 0.0
        self._month_peak = 0.0

    @property
    def obs_dim(self) -> int:
        return 107  # canonical Gansu obs dimension

    def reset(self) -> np.ndarray:
        self.step_count = 0
        self.episode    = 0
        self._soc       = 0.5 * self._cap
        self._cum_cost  = 0.0
        return self._obs()

    def _obs(self) -> np.ndarray:
        return self._rng.standard_normal(self.obs_dim).astype(np.float32)

    def step(self, action: np.ndarray) -> tuple[np.ndarray, dict]:
        """Apply action, advance env by 1 step, return (obs, payload_dict).

        All six validator identities (D13 + conservation) are satisfied by
        deriving dependent values from primaries — no independent rounding of
        identity-participating fields.
        """
        # --- basic physics ---
        a_ch = float(np.clip(action[0], -1.0, 1.0))   # [-1,1] → charge command

        p_ch  = max(0.0,  a_ch) * self._max_ch
        p_dis = max(0.0, -a_ch) * self._max_dis

        # SOC update (clipped)
        new_soc = self._soc + p_ch * self._eta - p_dis / self._eta
        new_soc = float(np.clip(new_soc, self._soc_min, self._soc_max))
        p_ch    = max(0.0, (new_soc - self._soc) / self._eta) if new_soc > self._soc else 0.0
        p_dis   = max(0.0, (self._soc - new_soc) * self._eta) if new_soc < self._soc else 0.0
        self._soc = new_soc

        # Synthetic generation + load (raw floats — no early rounding)
        p_wind = abs(float(self._rng.normal(150.0, 30.0)))
        p_pv   = abs(float(self._rng.normal(40.0,  10.0)))
        p_load = abs(float(self._rng.normal(75.0,  10.0)))

        p_gen    = p_wind + p_pv
        p_net    = p_gen - p_load - p_ch + p_dis
        p_export = float(np.clip(p_net,  0.0, self._max_exp))
        p_import = float(np.clip(-p_net, 0.0, self._max_imp))

        # Prices: synthetic TOU
        hour = self.step_count % 24
        if 9 <= hour < 11 or 14 <= hour < 17 or 19 <= hour < 22:
            price_buy = 120.0
        elif 11 <= hour < 14 or 17 <= hour < 19:
            price_buy = 80.0
        else:
            price_buy = 40.0
        price_sell = max(0.0, price_buy - 30.0)

        # ---------- Costs — derive dependent values for identity checks ----------
        # Identity #3: c_energy_yuan == c_import_yuan - r_export_yuan
        c_import_yuan  = max(0.0, p_import * price_buy)
        r_export_yuan  = max(0.0, p_export * price_sell)
        c_energy_yuan  = c_import_yuan - r_export_yuan   # identity #3 holds exactly

        c_demand_shape_yuan  = 0.0
        c_demand_charge_yuan = 0.0
        c_degradation_yuan   = p_ch * self._deg_rate * self._cap * 100.0
        c_curtail_yuan       = 0.0
        c_voll_yuan          = 0.0
        penalty_yuan         = 0.0

        # Identity #1: cost_total_real_yuan == c_energy + c_demand_charge + c_deg + c_curtail + c_voll
        cost_total_real_yuan = (c_energy_yuan + c_demand_charge_yuan
                                + c_degradation_yuan + c_curtail_yuan + c_voll_yuan)
        # Identity #2: cost_total_reward_basis_yuan == c_energy + 2·c_demand_shape + c_deg + c_curtail + c_voll
        cost_total_reward_basis_yuan = (c_energy_yuan + 2.0 * c_demand_shape_yuan
                                        + c_degradation_yuan + c_curtail_yuan + c_voll_yuan)
        # Identity #4: reward == -(cost_total_reward_basis_yuan + penalty_yuan) * 1e-5
        reward = -(cost_total_reward_basis_yuan + penalty_yuan) * 1e-5  # identity #4 holds exactly

        self._month_peak        = max(self._month_peak, p_import)
        self._cum_cost         += cost_total_real_yuan
        self._cum_energy_cost  += c_energy_yuan

        self.step_count += 1
        # Episode boundary at 168 steps (D3: 7-day train episodes)
        if self.step_count % 168 == 0:
            self.episode += 1

        obs = self._obs()

        # SOC fraction [soc_min_frac, soc_max_frac] = [0.2, 0.9]
        soc_frac = self._soc / self._cap  # in [0.2, 0.9] due to SOC clipping above

        # ---------- Flow decomposition — ensure solar & wind conservation --------
        # Renewable generation first serves load, surplus to battery / grid.
        # Identities #5 & #6: sum of per-source flows == gross_*_mw.
        # Use residual for *_to_grid to guarantee conservation to float precision.
        gen_avail   = p_wind + p_pv  # == gross_wind + gross_solar
        gen_to_load = min(gen_avail, p_load)
        gen_surplus = max(0.0, gen_avail - p_load)
        gen_to_bat  = min(gen_surplus, p_ch)
        # Do NOT round wind_frac / solar_frac — keep full float precision
        wind_frac  = p_wind / max(gen_avail, 1e-30)
        solar_frac = p_pv   / max(gen_avail, 1e-30)

        # Primary splits (computed from raw floats)
        solar_to_load = gen_to_load * solar_frac
        solar_to_bat  = gen_to_bat  * solar_frac
        wind_to_load  = gen_to_load * wind_frac
        wind_to_bat   = gen_to_bat  * wind_frac

        # Residual to_grid guarantees conservation: sum(solar_*) == p_pv exactly
        solar_to_grid = p_pv  - solar_to_load - solar_to_bat  # identity #5 holds exactly
        wind_to_grid  = p_wind - wind_to_load  - wind_to_bat   # identity #6 holds exactly

        bat_to_load  = min(p_dis, max(0.0, p_load - gen_to_load))
        bat_to_grid  = max(0.0, p_dis - bat_to_load)
        grid_to_load = max(0.0, p_load - gen_to_load - p_dis)
        grid_to_bat  = max(0.0, p_ch  - gen_to_bat)

        payload = {
            "step":        self.step_count - 1,
            "episode":     self.episode,
            "dt_hours":    1.0,
            "sim_time_utc": f"2026-01-01T{(self.step_count - 1) % 24:02d}:00:00Z",
            "hour_of_day":  (self.step_count - 1) % 24,
            "minute_of_hour": 0,
            "wind_speed_mps":   float(self._rng.uniform(3.0, 15.0)),
            "irradiance_wm2":   float(self._rng.uniform(0.0, 800.0)),
            "temperature_c":    float(self._rng.uniform(-5.0, 35.0)),
            "load_mw":          p_load,
            "price_buy_yuan_per_mwh":  price_buy,
            "price_sell_yuan_per_mwh": price_sell,
            "tariff_tier": ("peak" if price_buy >= 120.0 else
                            "mid"  if price_buy >= 80.0  else "valley"),
            "battery": {
                # LOCKED schema: 'soc' = fraction [0.2, 0.9]
                "soc":                soc_frac,
                "p_charge_mw":        p_ch,
                "p_discharge_mw":     p_dis,
                "p_max_charge_mw":    self._max_ch,
                "p_max_discharge_mw": self._max_dis,
                "soc_violation_mwh":  0.0,   # synthetic env enforces SOC bounds
                "capacity_mwh":       self._cap,
            },
            "generation": {
                # LOCKED: gross_solar_mw / gross_wind_mw (pre-curtailment raw floats)
                "gross_solar_mw": p_pv,
                "gross_wind_mw":  p_wind,
            },
            "flows": {
                # LOCKED: 14 required fields.
                # solar/wind_to_grid are residuals → conservation holds exactly.
                "solar_to_load_mw":    solar_to_load,
                "solar_to_bat_mw":     solar_to_bat,
                "solar_to_grid_mw":    solar_to_grid,
                "wind_to_load_mw":     wind_to_load,
                "wind_to_bat_mw":      wind_to_bat,
                "wind_to_grid_mw":     wind_to_grid,
                "bat_to_load_mw":      bat_to_load,
                "bat_to_grid_mw":      bat_to_grid,
                "grid_to_load_mw":     grid_to_load,
                "grid_to_bat_mw":      grid_to_bat,
                "solar_curtailed_mw":  0.0,
                "wind_curtailed_mw":   0.0,
                "bat_curtailed_mw":    0.0,
                "load_unserved_mw":    0.0,
            },
            "pcc": {
                # LOCKED: export_mw / import_mw (no 'p_' prefix)
                "export_mw":     p_export,
                "import_mw":     p_import,
                "max_export_mw": self._max_exp,
                "max_import_mw": self._max_imp,
            },
            "costs": {
                # All derived consistently — identities #1–#4 hold exactly.
                "c_energy_yuan":               c_energy_yuan,
                "c_import_yuan":               c_import_yuan,
                "r_export_yuan":               r_export_yuan,
                "c_demand_shape_yuan":          c_demand_shape_yuan,
                "c_demand_charge_yuan":         c_demand_charge_yuan,
                "c_degradation_yuan":           c_degradation_yuan,
                "c_curtail_yuan":               c_curtail_yuan,
                "c_voll_yuan":                  c_voll_yuan,
                "penalty_yuan":                 penalty_yuan,
                "cost_total_real_yuan":         cost_total_real_yuan,
                "cost_total_reward_basis_yuan":  cost_total_reward_basis_yuan,
                "demand_rate_yuan_per_mw_month": self._demand_rate,  # LOCKED required
            },
            "cost_cum": {
                "c_energy_yuan_cum":             self._cum_energy_cost,
                "c_demand_shape_yuan_cum":        0.0,
                "c_degradation_yuan_cum":         0.0,
                "c_curtail_yuan_cum":             0.0,
                "c_voll_yuan_cum":                0.0,
                "c_demand_charge_yuan_cum":       0.0,
                "penalty_yuan_cum":               0.0,
                "cost_total_real_yuan_cum":         self._cum_cost,
                "cost_total_reward_basis_yuan_cum": self._cum_cost,
            },
            "month_peak_mw": self._month_peak,
            "reward":        reward,
        }
        return obs, payload


# ---------------------------------------------------------------------------
# Real JAX env session (task #48 — replaces _SyntheticEnv placeholder)
# ---------------------------------------------------------------------------

class _JaxEnvSession:
    """Real JAX env session driven by energy_go.env.jax_env.

    Interface: identical to _SyntheticEnv — drop-in replacement.
      reset() → np.ndarray          (107-dim float32 initial obs)
      step(action) → (next_obs, payload_dict)
      .step_count, .episode, .obs_dim attributes

    Design notes:
    - All JAX imports are LAZY (inside __init__) — no top-level import (PR #60 pattern).
    - EnvParams defaults are used (YAML → EnvParams mapping is out of scope per contract).
    - generate_year(PRNGKey(seed)) provides the synthetic year data; fixed seed → deterministic.
    - cost_cum accumulates across ALL steps in a session — NEVER reset on env.reset() (contract).
    - done returned by jax_env.step() is used directly (single source of truth).
    - Episode semantics: terminal step (done=True, t=167) belongs to its episode.
      episode counter increments AFTER building that step's payload (standard convention).
    """

    def __init__(self, site_yaml: dict, seed: int = 0) -> None:  # noqa: ARG002
        # Lazy JAX imports — keep module importable without JAX (PR #60)
        import jax
        import jax.numpy as jnp
        from energy_go.env import jax_env as _jax_env_mod
        from energy_go.generators.synthetic import generate_year  # type: ignore

        self._jax = jax
        self._jnp = jnp
        self._mod = _jax_env_mod

        # Default EnvParams — Gansu parity (YAML → EnvParams mapping is out of scope)
        self._params = _jax_env_mod.EnvParams()

        # Generate synthetic year data (fixed seed → deterministic trajectory)
        key = jax.random.PRNGKey(seed)
        key, data_key = jax.random.split(key)
        self._data = generate_year(data_key)  # (8760, 4) float32 [wind_mps, irr_wm2, temp_c, load_mw]
        self._key = key

        # Mutable session state
        self._state: Any = None  # EnvState, set by reset()
        self.step_count: int = 0   # global step counter (never resets within session)
        self.episode: int = 0      # episode counter (increments at each done=True boundary)

        # Running cost totals — NEVER reset within a session (including across episode boundaries)
        # Contract invariant: cost_cum[k+1] == cost_cum[k] + per_step_cost[k+1] for ALL k
        self._cost_cum: dict[str, float] = {
            "c_energy_yuan_cum": 0.0,
            "c_demand_shape_yuan_cum": 0.0,
            "c_demand_charge_yuan_cum": 0.0,
            "c_degradation_yuan_cum": 0.0,
            "c_curtail_yuan_cum": 0.0,
            "c_voll_yuan_cum": 0.0,
            "penalty_yuan_cum": 0.0,
            "cost_total_real_yuan_cum": 0.0,
            "cost_total_reward_basis_yuan_cum": 0.0,
        }

    @property
    def obs_dim(self) -> int:
        return 107  # canonical Gansu obs dimension (confirmed in jax_env.get_obs)

    def reset(self) -> np.ndarray:
        """Initialise env for episode 0.  Returns initial obs (float32, shape (107,)).

        cost_cum is NOT reset here — it accumulates for the session lifetime.
        """
        self._key, reset_key = self._jax.random.split(self._key)
        state, obs = self._mod.reset(reset_key, self._params, self._data)
        self._state = state
        self.step_count = 0
        self.episode = 0
        # cost_cum intentionally NOT reset — contract invariant
        return np.asarray(obs)

    def step(self, action: np.ndarray) -> tuple[np.ndarray, dict]:
        """Apply action to the real JAX env and return (next_obs, payload_dict).

        Matches _SyntheticEnv.step interface exactly.

        next_obs: float32 (107,) observation of the state AFTER this step
                  (or after env.reset() if done=True on this step).
        payload:  telemetry payload dict conforming to LOCKED telemetry schema.
        """
        assert self._state is not None, "call reset() before step()"

        # Input-state step index for data lookup and payload.step
        t_idx: int = int(self._state.t)

        # Convert action (numpy) → JAX array
        action_jax = self._jnp.array(action, dtype=self._jnp.float32)

        # Step the env.
        # NOTE: obs returned by jax_env.step() is from the INPUT state (§5.4).
        # We derive next_obs via get_obs(new_state, ...) to get the correct carry.
        new_state, _obs_input, reward, done, info = self._mod.step(
            self._state, action_jax, self._params, self._data
        )
        done_bool: bool = bool(done)  # use done from jax_env.step directly (single source)

        def _f(x: Any) -> float:
            return float(x)

        # ── Weather (raw generator data at the input state's step index) ──
        wind_mps = _f(self._data[t_idx, 0])
        irr_wm2  = _f(self._data[t_idx, 1])
        temp_c   = _f(self._data[t_idx, 2])
        load_mw  = _f(self._data[t_idx, 3])

        # ── Prices ──
        price_buy  = _f(info.price_buy_yuan_per_mwh)
        price_sell = _f(info.price_sell_yuan_per_mwh)

        # Tariff tier (contract §EnvInfo → telemetry payload)
        if price_buy >= 780.0:
            tariff_tier = "critical_peak"
        elif price_buy >= 620.0:
            tariff_tier = "peak"
        elif price_buy >= 450.0:
            tariff_tier = "mid"
        else:
            tariff_tier = "valley"

        # ── Per-step costs ──
        c_energy_yuan                = _f(info.c_energy_yuan)
        c_import_yuan                = _f(info.c_import_yuan)
        r_export_yuan                = _f(info.r_export_yuan)
        c_demand_shape_yuan          = _f(info.c_demand_shape_yuan)
        c_demand_charge_yuan         = _f(info.c_demand_charge_yuan)
        c_degradation_yuan           = _f(info.c_degradation_yuan)
        c_curtail_yuan               = _f(info.c_curtail_yuan)
        c_voll_yuan                  = _f(info.c_voll_yuan)
        penalty_yuan                 = _f(info.penalty_yuan)
        cost_total_real_yuan         = _f(info.cost_total_real_yuan)
        cost_total_reward_basis_yuan = _f(info.cost_total_reward_basis_yuan)

        # ── Accumulate cost_cum (NEVER reset — even at episode boundaries) ──
        self._cost_cum["c_energy_yuan_cum"]               += c_energy_yuan
        self._cost_cum["c_demand_shape_yuan_cum"]         += c_demand_shape_yuan
        self._cost_cum["c_demand_charge_yuan_cum"]        += c_demand_charge_yuan
        self._cost_cum["c_degradation_yuan_cum"]          += c_degradation_yuan
        self._cost_cum["c_curtail_yuan_cum"]              += c_curtail_yuan
        self._cost_cum["c_voll_yuan_cum"]                 += c_voll_yuan
        self._cost_cum["penalty_yuan_cum"]                += penalty_yuan
        self._cost_cum["cost_total_real_yuan_cum"]        += cost_total_real_yuan
        self._cost_cum["cost_total_reward_basis_yuan_cum"] += cost_total_reward_basis_yuan

        # ── sim_time_utc: continuous UTC from session start (2026-01-01T00:00:00Z) ──
        from datetime import timedelta
        hour_of_day = self.step_count % 24
        sim_time_utc = (
            datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(hours=self.step_count)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        # ── SOC from new_state (post-step battery update, before any episode reset) ──
        soc_frac = _f(new_state.soc)  # fraction ∈ [soc_min, soc_max] ⊂ [0, 1]

        # ── Build LOCKED telemetry payload ──
        # episode = CURRENT episode (standard: terminal step stays in its episode)
        payload: dict[str, Any] = {
            "step":          self.step_count,   # 0-based; payload built before increment
            "episode":       self.episode,       # NOT yet incremented for done=True (step 167 → 0)
            "dt_hours":      1.0,
            "sim_time_utc":  sim_time_utc,
            "hour_of_day":   hour_of_day,
            "minute_of_hour": 0,
            "wind_speed_mps":    wind_mps,
            "irradiance_wm2":    irr_wm2,
            "temperature_c":     temp_c,
            "load_mw":           load_mw,
            "price_buy_yuan_per_mwh":  price_buy,
            "price_sell_yuan_per_mwh": price_sell,
            "tariff_tier": tariff_tier,
            "battery": {
                # LOCKED: 'soc' is fraction [soc_min, soc_max] (post-step value)
                "soc":                soc_frac,
                "p_charge_mw":        _f(info.p_bat_ch_mw),
                "p_discharge_mw":     _f(info.p_bat_dis_mw),
                "p_max_charge_mw":    float(self._params.bat_power_mw),
                "p_max_discharge_mw": float(self._params.bat_power_mw),
                "soc_violation_mwh":  _f(info.soc_violation_mwh),
                "capacity_mwh":       float(self._params.bat_capacity_mwh),
            },
            "generation": {
                # LOCKED: gross_ values are pre-curtailment raw power
                "gross_solar_mw": _f(info.p_pv_mw),
                "gross_wind_mw":  _f(info.p_wind_mw),
            },
            "flows": {
                # LOCKED: 14 required fields (13 per-source + load_unserved, §3.3 amendment)
                "solar_to_load_mw":   _f(info.p_sol_to_load_mw),
                "solar_to_bat_mw":    _f(info.p_sol_to_bat_mw),
                "solar_to_grid_mw":   _f(info.p_sol_to_grid_mw),
                "solar_curtailed_mw": _f(info.p_sol_curtailed_mw),
                "wind_to_load_mw":    _f(info.p_wind_to_load_mw),
                "wind_to_bat_mw":     _f(info.p_wind_to_bat_mw),
                "wind_to_grid_mw":    _f(info.p_wind_to_grid_mw),
                "wind_curtailed_mw":  _f(info.p_wind_curtailed_mw),
                "bat_to_load_mw":     _f(info.p_bat_to_load_mw),
                "bat_to_grid_mw":     _f(info.p_bat_to_grid_mw),
                "bat_curtailed_mw":   _f(info.p_bat_curtailed_mw),
                "grid_to_bat_mw":     _f(info.p_grid_to_bat_mw),
                "grid_to_load_mw":    _f(info.p_grid_to_load_mw),
                "load_unserved_mw":   _f(info.p_load_unserved_mw),
            },
            "pcc": {
                "export_mw":     _f(info.p_export_mw),
                "import_mw":     _f(info.p_import_mw),
                "max_export_mw": float(self._params.grid_max_export_mw),
                "max_import_mw": float(self._params.grid_max_import_mw),
            },
            "costs": {
                "c_energy_yuan":               c_energy_yuan,
                "c_import_yuan":               c_import_yuan,
                "r_export_yuan":               r_export_yuan,
                "c_demand_shape_yuan":         c_demand_shape_yuan,
                "c_demand_charge_yuan":        c_demand_charge_yuan,
                "c_degradation_yuan":          c_degradation_yuan,
                "c_curtail_yuan":              c_curtail_yuan,
                "c_voll_yuan":                 c_voll_yuan,
                "penalty_yuan":                penalty_yuan,
                "cost_total_real_yuan":        cost_total_real_yuan,
                "cost_total_reward_basis_yuan": cost_total_reward_basis_yuan,
                "demand_rate_yuan_per_mw_month": float(self._params.demand_rate_yuan_per_mw_month),
            },
            "cost_cum": dict(self._cost_cum),   # snapshot of running totals (NOT reset on episode)
            "month_peak_mw": _f(new_state.month_peak),   # post-step peak (0.0 at month-end per D21)
            "reward": _f(reward),
        }

        # ── Advance global step counter (AFTER building payload so payload.step is 0-based) ──
        self.step_count += 1

        # ── Episode reset — standard convention: terminal step belongs to its episode ──
        # Frame 167 (done=True) payload already carries episode=0 (built above).
        # NOW reset the env and increment episode for the next frame.
        if done_bool:
            self._key, reset_key = self._jax.random.split(self._key)
            new_state, reset_obs = self._mod.reset(reset_key, self._params, self._data)
            # Episode increments AFTER building the terminal step's payload (D3 convention)
            self.episode += 1
            next_obs = np.asarray(reset_obs)
        else:
            # next_obs = get_obs(new_state, ...) — obs of the POST-step state for the next call
            next_obs = np.asarray(self._mod.get_obs(new_state, self._params, self._data))

        # Update internal state for next step() call
        self._state = new_state

        return next_obs, payload


def _make_env_session(site_yaml: dict, seed: int = 0) -> "_JaxEnvSession | _SyntheticEnv":
    """Factory: use real JAX env if available; fall back to synthetic placeholder.

    The real JAX env is preferred for authentic Gansu physics, deterministic weather
    from generate_year(), and all 13+2 per-source flow fields.  The synthetic env is
    kept as a fallback for environments without JAX/jaxlib (e.g. CI without GPU wheels).
    """
    try:
        return _JaxEnvSession(site_yaml, seed=seed)
    except ImportError:
        log.warning(
            "energy_go.env.jax_env not importable — falling back to _SyntheticEnv placeholder. "
            "Real env physics will NOT be active."
        )
        return _SyntheticEnv(site_yaml, seed=seed)


# ---------------------------------------------------------------------------
# WS session state
# ---------------------------------------------------------------------------

class _Session:
    __slots__ = (
        "session_id", "run_id", "site_id", "state",
        "seq", "env", "checkpoint", "obs", "speed",
    )

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.run_id:     str | None = None
        self.site_id:    str | None = None
        self.state: str = "ready"   # ready | running | paused | stopped
        self.seq:  int = 0
        self.env:  _SyntheticEnv | None = None
        self.checkpoint: Any = None   # CheckpointData; Any avoids a top-level import
        self.obs:  np.ndarray | None = None   # current obs (carried between steps)
        self.speed: float = 1.0  # Hz; 0.0 = no sleep (D24)


def _ts_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _work_dir() -> Path:
    return Path.cwd()


def _status_frame(s: _Session, message: str | None = None) -> str:
    d: dict[str, Any] = {
        "kind": s.state,  # used as kind temporarily — overridden below
        "state": s.state,
        "step": s.env.step_count if s.env else 0,
        "episode": s.env.episode if s.env else 0,
        "run_id": s.run_id,
        "site_id": s.site_id,
        "session_id": s.session_id,
    }
    if message:
        d["message"] = message
    d["kind"] = "status"
    return json.dumps(d)


def _error_frame(code: str, message: str) -> str:
    return json.dumps({"kind": "error", "code": code, "message": message})


# ---------------------------------------------------------------------------
# WS /ws/inference
# ---------------------------------------------------------------------------

@router.websocket("/ws/inference")
async def ws_inference(websocket: WebSocket) -> None:
    await websocket.accept()
    s = _Session()
    step_task: asyncio.Task | None = None

    async def _send(text: str) -> None:
        await websocket.send_text(text)

    async def _send_validated(frame: dict) -> None:
        """D18 producer obligation: validate before sending; log warning if invalid.

        Never blocks or raises — stream resilience is preserved.
        """
        try:
            from energy_go.telemetry.validate import validate  # type: ignore
            errs = validate(frame)
            if errs:
                log.warning(
                    "D18 validate kind=%s seq=%s: %s",
                    frame.get("kind"), frame.get("seq"), errs,
                )
        except ImportError:
            pass
        await _send(json.dumps(frame))

    async def _step_loop() -> None:
        """Async loop: step env → build env_step frame → send."""
        assert s.env is not None and s.checkpoint is not None
        while s.state == "running":
            # Use obs from env.reset() / previous step; fall back to zeros on first
            # call if reset somehow wasn't stored (defensive — reset is always called
            # in the start handler before this loop begins).
            obs_raw = s.obs if s.obs is not None else np.zeros(s.env.obs_dim, dtype=np.float32)

            # §6 canonical forward pass: normalization (obs_var/obs_clip) + ReLU MLP
            # + D28 mean-clip ± 8 + tanh(a_bat) / sigmoid(fractions)
            action = policy_forward(s.checkpoint, obs_raw)

            next_obs, payload = s.env.step(action)
            s.obs = next_obs  # carry obs for the next step

            # Build LOCKED env_step frame
            frame: dict = {
                "schema_version": "1.0.0",
                "kind": "env_step",
                "ts_utc": _ts_now(),
                "run_id": s.run_id,
                "seq": s.seq,
                "payload": payload,
            }
            s.seq += 1

            await _send_validated(frame)
            # Honour the speed control (D24): speed=0 → yield only to asyncio (no OS
            # sleep); speed>0 → real sleep of 1/speed seconds.  A real sleep suspends
            # the event-loop thread so the OS can schedule the test-client / browser
            # thread to push control commands before the next frame is emitted.
            sleep_s = 0.0 if s.speed == 0.0 else 1.0 / s.speed
            await asyncio.sleep(sleep_s)

    # Send initial ready status
    await _send(_status_frame(s))

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            # Parse command
            try:
                cmd_msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await _send(_error_frame("invalid_message", "message is not valid JSON"))
                continue

            cmd = cmd_msg.get("cmd")
            if cmd is None:
                await _send(_error_frame("invalid_message", "missing 'cmd' field"))
                continue

            # ── start ──────────────────────────────────────────────────────
            if cmd == "start":
                if s.state in ("running", "paused"):
                    await _send(_error_frame("already_running", "a session is already active"))
                    continue

                run_id  = cmd_msg.get("run_id")
                site_id = cmd_msg.get("site_id")
                seed    = int(cmd_msg.get("seed", 0))
                # D24: default=1.0 Hz; clamp to [0, 100]; negative → 0
                speed   = max(0.0, min(100.0, float(cmd_msg.get("speed", 1.0))))

                # Validate run
                run_dir = _work_dir() / "checkpoints" / str(run_id)
                if not run_dir.is_dir():
                    await _send(_error_frame("run_not_found", f"no checkpoints/{run_id}"))
                    continue

                # Validate site
                site_path = _work_dir() / "config" / f"site_{site_id}.yaml"
                if not site_path.exists():
                    await _send(_error_frame("site_not_found", f"no config/site_{site_id}.yaml"))
                    continue

                # Load canonical checkpoint (§6 recipe; no legacy policy.npz)
                try:
                    checkpoint = _load_checkpoint_for_run(str(run_id), run_dir)
                except FileNotFoundError:
                    await _send(_error_frame(
                        "policy_not_found",
                        f"no canonical checkpoint in checkpoints/{run_id}",
                    ))
                    continue

                # Load site YAML
                import yaml as _yaml
                with site_path.open() as f:
                    site_yaml = _yaml.safe_load(f)

                s.run_id     = str(run_id)
                s.site_id    = str(site_id)
                s.session_id = str(uuid.uuid4())
                s.checkpoint = checkpoint
                s.speed      = speed
                s.env        = _make_env_session(site_yaml, seed=seed)
                s.obs        = s.env.reset()   # initial obs for step 0
                s.state      = "running"

                await _send(_status_frame(s))
                # Start stepping asynchronously
                step_task = asyncio.ensure_future(_step_loop())

            # ── pause ──────────────────────────────────────────────────────
            elif cmd == "pause":
                if s.state == "ready" or s.env is None:
                    await _send(_error_frame("no_session", "no active session to pause"))
                    continue
                if s.state != "running":
                    continue  # already paused — ignore
                s.state = "paused"
                if step_task and not step_task.done():
                    step_task.cancel()
                    try:
                        await step_task
                    except asyncio.CancelledError:
                        pass
                await _send(_status_frame(s))

            # ── resume ─────────────────────────────────────────────────────
            elif cmd == "resume":
                if s.state == "ready" or s.env is None:
                    await _send(_error_frame("no_session", "no active session to resume"))
                    continue
                if s.state != "paused":
                    continue  # already running — ignore
                s.state = "running"
                await _send(_status_frame(s))
                step_task = asyncio.ensure_future(_step_loop())

            # ── step ───────────────────────────────────────────────────────
            elif cmd == "step":
                if s.state == "ready" or s.env is None:
                    await _send(_error_frame("no_session", "no active session"))
                    continue
                if s.state != "paused":
                    await _send(_error_frame("bad_state", "step command only valid when paused"))
                    continue
                # Advance exactly one step (canonical §6 forward pass)
                assert s.checkpoint is not None
                obs_raw  = s.obs if s.obs is not None else np.zeros(s.env.obs_dim, dtype=np.float32)
                action   = policy_forward(s.checkpoint, obs_raw)
                next_obs, payload = s.env.step(action)
                s.obs = next_obs
                frame = {
                    "schema_version": "1.0.0",
                    "kind": "env_step",
                    "ts_utc": _ts_now(),
                    "run_id": s.run_id,
                    "seq": s.seq,
                    "payload": payload,
                }
                s.seq += 1
                await _send_validated(frame)

            # ── stop ───────────────────────────────────────────────────────
            elif cmd == "stop":
                if step_task and not step_task.done():
                    step_task.cancel()
                    try:
                        await step_task
                    except asyncio.CancelledError:
                        pass
                s.state      = "stopped"
                s.session_id = None
                await _send(_status_frame(s))
                await websocket.close()
                return

            # ── unknown command ────────────────────────────────────────────
            else:
                await _send(_error_frame("bad_command", f"unrecognised command: {cmd!r}"))

    except WebSocketDisconnect:
        pass
    finally:
        if step_task and not step_task.done():
            step_task.cancel()
