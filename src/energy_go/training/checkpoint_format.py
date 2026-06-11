"""Checkpoint save/load and pure-NumPy actor inference — contracts/shared/checkpoint_format.md.

The checkpoint is a single .npz file containing:
  - Metadata (schema_version, checkpoint_id, run_id, global_step, created_at_utc,
    code_version, run_config_json)
  - Architecture identity (obs_dim, action_dim)
  - VecNormalize obs stats (obs_mean, obs_var, obs_count, obs_clip)
  - Actor MLP weights (actor_fc*_w/b, actor_out_w/b)
  - Optional critic weights and ent_coef/target_entropy (for training resume)

save_checkpoint and load_checkpoint are the ONLY supported I/O path — never call
np.savez / np.load directly.
"""

from __future__ import annotations

import os
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import jax.numpy as jnp


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"
_OBS_DIM    = 107
_ACTION_DIM = 6

# Required keys with expected (dtype, shape). Shape None = scalar.
_REQUIRED_KEYS: dict[str, tuple[type, tuple | None]] = {
    "schema_version":  (str,         None),
    "checkpoint_id":   (str,         None),
    "run_id":          (str,         None),
    "global_step":     (np.int64,    None),
    "created_at_utc":  (str,         None),
    "code_version":    (str,         None),
    "run_config_json": (str,         None),
    "obs_dim":         (np.int64,    None),
    "action_dim":      (np.int64,    None),
    "obs_mean":        (np.float32,  (_OBS_DIM,)),
    "obs_var":         (np.float32,  (_OBS_DIM,)),
    "obs_count":       (np.int64,    None),
    "obs_clip":        (np.float32,  None),
    "actor_fc1_w":     (np.float32,  (_OBS_DIM, 256)),
    "actor_fc1_b":     (np.float32,  (256,)),
    "actor_fc2_w":     (np.float32,  (256, 256)),
    "actor_fc2_b":     (np.float32,  (256,)),
    "actor_out_w":     (np.float32,  (256, 2 * _ACTION_DIM)),  # (256, 12)
    "actor_out_b":     (np.float32,  (2 * _ACTION_DIM,)),      # (12,)
}

_OPTIONAL_CRITIC_KEYS: dict[str, tuple[type, tuple]] = {
    "critic1_fc1_w": (np.float32, (_OBS_DIM + _ACTION_DIM, 256)),  # (113, 256)
    "critic1_fc1_b": (np.float32, (256,)),
    "critic1_fc2_w": (np.float32, (256, 256)),
    "critic1_fc2_b": (np.float32, (256,)),
    "critic1_out_w": (np.float32, (256, 1)),
    "critic1_out_b": (np.float32, (1,)),
    "critic2_fc1_w": (np.float32, (_OBS_DIM + _ACTION_DIM, 256)),
    "critic2_fc1_b": (np.float32, (256,)),
    "critic2_fc2_w": (np.float32, (256, 256)),
    "critic2_fc2_b": (np.float32, (256,)),
    "critic2_out_w": (np.float32, (256, 1)),
    "critic2_out_b": (np.float32, (1,)),
}


# ---------------------------------------------------------------------------
# CheckpointData dataclass
# ---------------------------------------------------------------------------

@dataclass
class CheckpointData:
    """All-in-one checkpoint carrying actor weights + VecNormalize stats — §5.1.

    Produced by save_checkpoint / consumed by load_checkpoint, run_eval, and
    the serving layer via actor_forward_numpy.
    """
    # ---- Metadata
    schema_version:  str
    checkpoint_id:   str    # UUID v4; join key for telemetry + serving
    run_id:          str
    global_step:     int
    created_at_utc:  str    # ISO-8601 UTC write time
    code_version:    str    # git SHA prefix or "unknown"
    run_config_json: str    # JSON; must carry seed + site_config_id (tuples→lists in JSON)

    # ---- Architecture identity
    obs_dim:    int = _OBS_DIM     # always 107
    action_dim: int = _ACTION_DIM  # always 6

    # ---- VecNormalize obs stats
    obs_mean:   np.ndarray = field(default_factory=lambda: np.zeros(_OBS_DIM, dtype=np.float32))
    obs_var:    np.ndarray = field(default_factory=lambda: np.ones(_OBS_DIM, dtype=np.float32))
    obs_count:  int = 0       # saved as np.int64 (save_checkpoint casts explicitly)
    obs_clip:   float = 10.0

    # ---- Actor MLP weights
    actor_fc1_w: Optional[np.ndarray] = None   # (107, 256)
    actor_fc1_b: Optional[np.ndarray] = None   # (256,)
    actor_fc2_w: Optional[np.ndarray] = None   # (256, 256)
    actor_fc2_b: Optional[np.ndarray] = None   # (256,)
    actor_out_w: Optional[np.ndarray] = None   # (256, 12)
    actor_out_b: Optional[np.ndarray] = None   # (12,)

    # ---- Optional critic weights (None → inference-only checkpoint)
    critic1_fc1_w: Optional[np.ndarray] = None  # (113, 256)
    critic1_fc1_b: Optional[np.ndarray] = None
    critic1_fc2_w: Optional[np.ndarray] = None
    critic1_fc2_b: Optional[np.ndarray] = None
    critic1_out_w: Optional[np.ndarray] = None
    critic1_out_b: Optional[np.ndarray] = None
    critic2_fc1_w: Optional[np.ndarray] = None  # (113, 256)
    critic2_fc1_b: Optional[np.ndarray] = None
    critic2_fc2_w: Optional[np.ndarray] = None
    critic2_fc2_b: Optional[np.ndarray] = None
    critic2_out_w: Optional[np.ndarray] = None
    critic2_out_b: Optional[np.ndarray] = None
    ent_coef:       Optional[float] = None
    target_entropy: Optional[float] = None   # = -action_dim = -6.0

    # ------------------------------------------------------------------
    # Convenience properties (for inference and training_pipeline tests)
    # ------------------------------------------------------------------

    @property
    def actor_params(self) -> dict:
        """Actor MLP params dict — compatible with actor_forward(params, obs).

        Keys: fc1_w, fc1_b, fc2_w, fc2_b, out_w, out_b (JAX arrays).
        """
        return {
            "fc1_w": jnp.array(self.actor_fc1_w),
            "fc1_b": jnp.array(self.actor_fc1_b),
            "fc2_w": jnp.array(self.actor_fc2_w),
            "fc2_b": jnp.array(self.actor_fc2_b),
            "out_w": jnp.array(self.actor_out_w),
            "out_b": jnp.array(self.actor_out_b),
        }

    @property
    def obs_stats(self):
        """VecNormalize stats as a RunningStats NamedTuple (JAX arrays).

        Compatible with normalize_obs(obs, ckpt.obs_stats, clip=...).
        """
        from energy_go.training.normalizer import RunningStats
        return RunningStats(
            mean  = jnp.array(self.obs_mean),
            var   = jnp.array(self.obs_var),
            count = jnp.int32(self.obs_count),
        )

    @property
    def run_config(self) -> dict:
        """Parsed run_config_json as a Python dict.

        Note: tuple fields (e.g. hidden_sizes) are deserialized as lists.
        """
        return json.loads(self.run_config_json)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_checkpoint(data: CheckpointData, path: str | Path) -> None:
    """Serialise CheckpointData to a .npz file atomically — §5.

    - Converts JAX arrays to numpy before saving.
    - Writes via a temp file in the SAME DIRECTORY as path, then os.replace
      (same-filesystem rename → POSIX-atomic; cross-filesystem moves are not).
    - obs_count is explicitly cast to np.int64 (JAX defaults to int32 on CPU).
    - Raises ValueError if any required key has wrong dtype or shape.
    """
    path = Path(path)
    arrays: dict[str, np.ndarray] = {}

    def _to_np(v):
        """Convert JAX / Python scalars to numpy."""
        try:
            import jax.numpy as jnp
            if isinstance(v, jnp.ndarray):
                return np.array(v)
        except ImportError:
            pass
        return v

    # ---- Metadata (stored as 0-d numpy string arrays)
    arrays["schema_version"]  = np.array(data.schema_version)
    arrays["checkpoint_id"]   = np.array(data.checkpoint_id)
    arrays["run_id"]          = np.array(data.run_id)
    arrays["global_step"]     = np.int64(data.global_step)
    arrays["created_at_utc"]  = np.array(data.created_at_utc)
    arrays["code_version"]    = np.array(data.code_version)
    arrays["run_config_json"] = np.array(data.run_config_json)
    arrays["obs_dim"]         = np.int64(data.obs_dim)
    arrays["action_dim"]      = np.int64(data.action_dim)

    # ---- Obs stats
    arrays["obs_mean"]  = np.array(_to_np(data.obs_mean),  dtype=np.float32)
    arrays["obs_var"]   = np.array(_to_np(data.obs_var),   dtype=np.float32)
    arrays["obs_count"] = np.int64(int(data.obs_count))   # explicit int64 cast
    arrays["obs_clip"]  = np.float32(data.obs_clip)

    # ---- Actor weights
    for key in ("actor_fc1_w", "actor_fc1_b", "actor_fc2_w", "actor_fc2_b",
                "actor_out_w", "actor_out_b"):
        v = getattr(data, key)
        if v is None:
            raise ValueError(f"save_checkpoint: required actor key '{key}' is None")
        arr = np.array(_to_np(v), dtype=np.float32)
        # Shape validation
        _, expected_shape = _REQUIRED_KEYS[key]
        if expected_shape is not None and arr.shape != expected_shape:
            raise ValueError(
                f"save_checkpoint: {key} shape {arr.shape} != expected {expected_shape}"
            )
        arrays[key] = arr

    # ---- Optional critic weights
    for key in _OPTIONAL_CRITIC_KEYS:
        v = getattr(data, key, None)
        if v is not None:
            arrays[key] = np.array(_to_np(v), dtype=np.float32)

    if data.ent_coef is not None:
        arrays["ent_coef"] = np.float32(data.ent_coef)
    if data.target_entropy is not None:
        arrays["target_entropy"] = np.float32(data.target_entropy)

    # ---- Atomic write: temp file in the same directory
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".npz.tmp")
    try:
        os.close(fd)
        np.savez_compressed(tmp_path, **arrays)
        os.replace(tmp_path, path)  # POSIX-atomic rename (same filesystem)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_checkpoint(path: str | Path) -> CheckpointData:
    """Load a .npz checkpoint and return a CheckpointData — §5.

    - Validates schema_version: raises ValueError if major version > 1.
    - Raises KeyError with a descriptive message for any missing required key.
    - Validates dtypes and shapes of all required array keys.
    - Returns arrays as numpy (float32 / int64); callers convert to JAX if needed.
    """
    path = Path(path)
    raw = np.load(str(path), allow_pickle=False)

    # ---- Required key presence + schema version
    for key in _REQUIRED_KEYS:
        if key not in raw:
            raise KeyError(
                f"load_checkpoint: required key '{key}' absent from '{path}'. "
                f"This checkpoint may be from a different schema version."
            )

    # ---- Schema version
    schema_version = str(raw["schema_version"])
    major = int(schema_version.split(".")[0])
    if major > 1:
        raise ValueError(
            f"load_checkpoint: schema_version '{schema_version}' has major version {major} > 1. "
            "This checkpoint requires a newer loader."
        )

    # ---- Dtype + shape validation for array keys
    for key, (expected_dtype, expected_shape) in _REQUIRED_KEYS.items():
        if expected_dtype in (str,):
            continue  # string scalars validated separately
        arr = raw[key]
        # Scalar keys — just check dtype
        if expected_shape is None:
            if arr.dtype != expected_dtype:
                raise ValueError(
                    f"load_checkpoint: '{key}' dtype {arr.dtype} != expected {expected_dtype}"
                )
        else:
            if arr.dtype != expected_dtype:
                raise ValueError(
                    f"load_checkpoint: '{key}' dtype {arr.dtype} != expected {expected_dtype}"
                )
            if arr.shape != expected_shape:
                raise ValueError(
                    f"load_checkpoint: '{key}' shape {arr.shape} != expected {expected_shape}"
                )

    # ---- Build CheckpointData
    def _opt(key: str) -> Optional[np.ndarray]:
        return raw[key] if key in raw else None

    return CheckpointData(
        schema_version  = str(raw["schema_version"]),
        checkpoint_id   = str(raw["checkpoint_id"]),
        run_id          = str(raw["run_id"]),
        global_step     = int(raw["global_step"]),
        created_at_utc  = str(raw["created_at_utc"]),
        code_version    = str(raw["code_version"]),
        run_config_json = str(raw["run_config_json"]),
        obs_dim         = int(raw["obs_dim"]),
        action_dim      = int(raw["action_dim"]),
        obs_mean        = raw["obs_mean"],
        obs_var         = raw["obs_var"],
        obs_count       = int(raw["obs_count"]),
        obs_clip        = float(raw["obs_clip"]),
        actor_fc1_w     = raw["actor_fc1_w"],
        actor_fc1_b     = raw["actor_fc1_b"],
        actor_fc2_w     = raw["actor_fc2_w"],
        actor_fc2_b     = raw["actor_fc2_b"],
        actor_out_w     = raw["actor_out_w"],
        actor_out_b     = raw["actor_out_b"],
        # ---- Optional critic
        critic1_fc1_w   = _opt("critic1_fc1_w"),
        critic1_fc1_b   = _opt("critic1_fc1_b"),
        critic1_fc2_w   = _opt("critic1_fc2_w"),
        critic1_fc2_b   = _opt("critic1_fc2_b"),
        critic1_out_w   = _opt("critic1_out_w"),
        critic1_out_b   = _opt("critic1_out_b"),
        critic2_fc1_w   = _opt("critic2_fc1_w"),
        critic2_fc1_b   = _opt("critic2_fc1_b"),
        critic2_fc2_w   = _opt("critic2_fc2_w"),
        critic2_fc2_b   = _opt("critic2_fc2_b"),
        critic2_out_w   = _opt("critic2_out_w"),
        critic2_out_b   = _opt("critic2_out_b"),
        ent_coef        = float(raw["ent_coef"])       if "ent_coef"       in raw else None,
        target_entropy  = float(raw["target_entropy"]) if "target_entropy" in raw else None,
    )


# ---------------------------------------------------------------------------
# Pure-NumPy actor forward pass (inference recipe) — §6
# ---------------------------------------------------------------------------

def actor_forward_numpy(checkpoint: CheckpointData, raw_obs: np.ndarray) -> np.ndarray:
    """Deterministic actor action from a raw (107,) observation — §6.

    Returns: (6,) float32 action with per-component squash:
        action[0]   = tanh(mean[0])       a_bat  ∈ (-1, 1)
        action[1:6] = sigmoid(mean[1:6])  fractions ∈ (0, 1)

    This pure-NumPy recipe reproduces actor_forward() in JAX to atol=1e-5.
    """
    # Step 1: normalise obs with VecNormalize stats (§4.3 inference recipe)
    std      = np.sqrt(checkpoint.obs_var + 1e-8)
    norm_obs = np.clip(
        (raw_obs - checkpoint.obs_mean) / std,
        -checkpoint.obs_clip,
        checkpoint.obs_clip,
    )

    # Step 2: MLP forward pass (y = ReLU(x @ W + b))
    h1  = np.maximum(0.0, norm_obs             @ checkpoint.actor_fc1_w + checkpoint.actor_fc1_b)  # (256,)
    h2  = np.maximum(0.0, h1                   @ checkpoint.actor_fc2_w + checkpoint.actor_fc2_b)  # (256,)
    out = h2 @ checkpoint.actor_out_w + checkpoint.actor_out_b  # (12,)

    # Step 3: split mean(6) from log_std_raw(6); per-component squash
    mean = out[:6]                                           # first 6 = mean
    a_bat     = np.tanh(mean[0:1])                          # a_bat ∈ (-1, 1)
    fractions = 1.0 / (1.0 + np.exp(-mean[1:6]))           # sigmoid; fractions ∈ (0, 1)
    return np.concatenate([a_bat, fractions]).astype(np.float32)  # (6,)
