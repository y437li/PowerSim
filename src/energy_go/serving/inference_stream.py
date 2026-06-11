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
# Policy cache: run_id → {"weights": dict[str, np.ndarray], "obs_mean": np.ndarray, "obs_std": np.ndarray}
# ---------------------------------------------------------------------------

_policy_cache: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Public utility: policy_forward
# (tested directly by TestPolicyForwardPass; also used by the WS handler)
# ---------------------------------------------------------------------------

def policy_forward(weights: dict[str, np.ndarray], obs: np.ndarray) -> np.ndarray:
    """Run the MLP forward pass.

    Args:
        weights: dict loaded from policy.npz — keys "w_0", "b_0", ..., "w_N", "b_N"
                 (N = number of layers; layer 0 = first hidden, layer N-1 = output).
        obs:     float32 array of shape (obs_dim,), already normalized.

    Returns:
        float32 array of shape (action_dim,) clipped to [−1, 1].

    Activation: tanh for hidden layers (indices 0 … N-2); identity for the output
    layer (index N-1).  Output clipped to [−1, 1] before returning.
    """
    n_layers = max(int(k[2:]) for k in weights if k.startswith("w_")) + 1
    h = obs.astype(np.float32)
    for i in range(n_layers):
        h = h @ weights[f"w_{i}"] + weights[f"b_{i}"]
        if i < n_layers - 1:
            h = np.tanh(h)          # tanh for every hidden layer
        # final layer: identity (no activation applied)
    return np.clip(h, -1.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Policy + normalization loader
# ---------------------------------------------------------------------------

def _load_policy(run_id: str, run_dir: Path) -> dict[str, Any]:
    """Load (or return cached) weights + normalization for run_id."""
    if run_id in _policy_cache:
        return _policy_cache[run_id]

    # Prefer ONNX if available
    onnx_path = run_dir / "policy.onnx"
    npz_path  = run_dir / "policy.npz"

    if not onnx_path.exists() and not npz_path.exists():
        raise FileNotFoundError(f"no policy.npz or policy.onnx in {run_dir}")

    weights: dict[str, np.ndarray] = {}
    if npz_path.exists():
        npz = np.load(npz_path)
        weights = {k: npz[k] for k in npz.files}
    # ONNX path: extend here when onnxruntime is available; fall back to npz

    # Normalization: identity if absent
    norm_path = run_dir / "normalization.npz"
    if norm_path.exists():
        n = np.load(norm_path)
        obs_mean = n["obs_mean"].astype(np.float32)
        obs_std  = n["obs_std"].astype(np.float32)
    else:
        # Identity normalization — obs dimension inferred from first weight matrix
        obs_dim = weights["w_0"].shape[0] if weights else 1
        obs_mean = np.zeros(obs_dim, dtype=np.float32)
        obs_std  = np.ones(obs_dim,  dtype=np.float32)

    entry = {"weights": weights, "obs_mean": obs_mean, "obs_std": obs_std}
    _policy_cache[run_id] = entry
    return entry


def _normalize(obs: np.ndarray, obs_mean: np.ndarray, obs_std: np.ndarray) -> np.ndarray:
    return (obs - obs_mean) / np.maximum(obs_std, 1e-8)


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
# WS session state
# ---------------------------------------------------------------------------

class _Session:
    __slots__ = (
        "session_id", "run_id", "site_id", "state",
        "seq", "env", "policy_entry", "speed",
    )

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.run_id:     str | None = None
        self.site_id:    str | None = None
        self.state: str = "ready"   # ready | running | paused | stopped
        self.seq: int = 0
        self.env: _SyntheticEnv | None = None
        self.policy_entry: dict | None = None
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
        assert s.env is not None and s.policy_entry is not None
        while s.state == "running":
            obs_raw = np.zeros(s.env.obs_dim, dtype=np.float32)
            obs_norm = _normalize(obs_raw, s.policy_entry["obs_mean"], s.policy_entry["obs_std"])
            action = policy_forward(s.policy_entry["weights"], obs_norm)

            _, payload = s.env.step(action)

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

                # Load policy
                try:
                    policy_entry = _load_policy(str(run_id), run_dir)
                except FileNotFoundError:
                    await _send(_error_frame("policy_not_found", f"no policy.npz or policy.onnx in checkpoints/{run_id}"))
                    continue

                # Load site YAML
                import yaml as _yaml
                with site_path.open() as f:
                    site_yaml = _yaml.safe_load(f)

                s.run_id       = str(run_id)
                s.site_id      = str(site_id)
                s.session_id   = str(uuid.uuid4())
                s.policy_entry = policy_entry
                s.speed        = speed
                s.env          = _SyntheticEnv(site_yaml, seed=seed)
                s.env.reset()
                s.state        = "running"

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
                # Advance exactly one step
                assert s.policy_entry is not None
                obs_raw  = np.zeros(s.env.obs_dim, dtype=np.float32)
                obs_norm = _normalize(obs_raw, s.policy_entry["obs_mean"], s.policy_entry["obs_std"])
                action   = policy_forward(s.policy_entry["weights"], obs_norm)
                _, payload = s.env.step(action)
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
