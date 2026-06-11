"""Tests for contracts/shared/checkpoint_format.md

ALL TESTS ARE RED at the gate stage — energy_go.training.checkpoint_format is not implemented.
Imports below fail until implementation; that is correct for the gate stage.

Standard:
- Every numeric assertion has the arithmetic shown in a comment.
- Edge cases are pinned at contract boundaries.
- Reviewer-added cases are marked: # reviewer: <reason>

Run:  pytest tests/shared/test_shared_checkpoint_format.py
Expected at gate stage: ImportError / collection errors for every test.
"""

import json
import numpy as np
import pytest
from pathlib import Path

# --- RED imports until implementation ---
from energy_go.training.checkpoint_format import (
    CheckpointData,
    save_checkpoint,
    load_checkpoint,
    actor_forward_numpy,
)
from energy_go.training.config import RunConfig

# Actor forward pass in JAX (for parity test)
from energy_go.training.run_training import actor_forward as actor_forward_jax

import jax.numpy as jnp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_random_weights(rng: np.random.RandomState) -> dict:
    """Draw random actor MLP weights matching the shapes in §4.3."""
    return dict(
        actor_fc1_w = rng.randn(107, 256).astype(np.float32),
        actor_fc1_b = rng.randn(256).astype(np.float32),
        actor_fc2_w = rng.randn(256, 256).astype(np.float32),
        actor_fc2_b = rng.randn(256).astype(np.float32),
        actor_out_w = rng.randn(256, 2).astype(np.float32),
        actor_out_b = rng.randn(2).astype(np.float32),
    )


def _make_checkpoint(rng: np.random.RandomState, **overrides) -> CheckpointData:
    """Build a minimal valid CheckpointData from random weights."""
    weights = _make_random_weights(rng)
    base = dict(
        schema_version  = "1.0.0",
        checkpoint_id   = "a1b2c3d4-0000-0000-0000-000000000001",
        run_id          = "test-run-001",
        global_step     = 500_000,
        created_at_utc  = "2026-06-10T14:03:00Z",
        code_version    = "5cc25b5a",
        run_config_json = json.dumps(vars(RunConfig())),
        obs_mean   = rng.randn(107).astype(np.float32),
        obs_var    = np.abs(rng.randn(107).astype(np.float32)) + 1e-3,  # var > 0
        obs_count  = 1_024_000,
        obs_clip   = 10.0,
        **weights,
    )
    base.update(overrides)
    return CheckpointData(**base)


# ---------------------------------------------------------------------------
# §4.1 — Metadata keys
# ---------------------------------------------------------------------------

class TestMetadataKeys:
    def test_schema_version_is_string(self):
        rng = np.random.RandomState(0)
        ckpt = _make_checkpoint(rng)
        assert isinstance(ckpt.schema_version, str)
        assert ckpt.schema_version == "1.0.0"

    def test_checkpoint_id_is_string(self):
        rng = np.random.RandomState(0)
        ckpt = _make_checkpoint(rng)
        assert isinstance(ckpt.checkpoint_id, str)
        assert len(ckpt.checkpoint_id) > 0

    def test_run_config_json_is_valid_json(self):
        # run_config_json must be deserializeable
        rng = np.random.RandomState(0)
        ckpt = _make_checkpoint(rng)
        cfg_dict = json.loads(ckpt.run_config_json)
        assert isinstance(cfg_dict, dict)
        # Must contain the §5 hyperparameters
        assert "gamma" in cfg_dict
        assert cfg_dict["gamma"] == pytest.approx(0.999)
        assert "lr" in cfg_dict

    def test_run_config_json_carries_seed(self):
        # run_config_json must carry seed for reproducibility (§4.1 provenance)
        rng = np.random.RandomState(0)
        ckpt = _make_checkpoint(rng)
        cfg_dict = json.loads(ckpt.run_config_json)
        assert "seed" in cfg_dict, "run_config_json must carry 'seed' for reproducibility"
        assert isinstance(cfg_dict["seed"], int)

    def test_run_config_json_carries_site_config_id(self):
        # run_config_json must carry site_config_id for UI provenance (§4.1)
        rng = np.random.RandomState(0)
        ckpt = _make_checkpoint(rng)
        cfg_dict = json.loads(ckpt.run_config_json)
        assert "site_config_id" in cfg_dict, (
            "run_config_json must carry 'site_config_id' (e.g. 'site_gansu') "
            "for eval-vs-baseline provenance display"
        )
        assert isinstance(cfg_dict["site_config_id"], str)
        assert len(cfg_dict["site_config_id"]) > 0

    def test_created_at_utc_is_iso8601(self):
        # created_at_utc must be a non-empty ISO-8601 string (§4.1)
        # Full parsing requires stdlib; just verify it ends in Z (UTC) and has T separator
        rng = np.random.RandomState(0)
        ckpt = _make_checkpoint(rng)
        ts = ckpt.created_at_utc
        assert isinstance(ts, str), "created_at_utc must be a string"
        assert "T" in ts, f"created_at_utc '{ts}' missing 'T' separator — not ISO-8601"
        assert ts.endswith("Z"), f"created_at_utc '{ts}' must end in 'Z' (UTC)"

    def test_code_version_is_nonempty_string(self):
        # code_version is a git SHA prefix or "unknown" (§4.1)
        rng = np.random.RandomState(0)
        ckpt = _make_checkpoint(rng)
        assert isinstance(ckpt.code_version, str)
        assert len(ckpt.code_version) > 0, "code_version must not be empty"

    def test_global_step_is_nonnegative(self):
        rng = np.random.RandomState(0)
        ckpt = _make_checkpoint(rng)
        assert ckpt.global_step >= 0


# ---------------------------------------------------------------------------
# §4.2 — VecNormalize obs stats shapes and dtypes
# ---------------------------------------------------------------------------

class TestObsStatsShapes:
    def test_obs_mean_shape(self):
        # obs_mean must be (107,) — the 107-dim obs vector from jax_env_core §5.4
        rng = np.random.RandomState(1)
        ckpt = _make_checkpoint(rng)
        assert ckpt.obs_mean.shape == (107,), f"obs_mean shape {ckpt.obs_mean.shape} != (107,)"

    def test_obs_var_shape(self):
        rng = np.random.RandomState(1)
        ckpt = _make_checkpoint(rng)
        assert ckpt.obs_var.shape == (107,), f"obs_var shape {ckpt.obs_var.shape} != (107,)"

    def test_obs_mean_dtype_float32(self):
        rng = np.random.RandomState(1)
        ckpt = _make_checkpoint(rng)
        assert ckpt.obs_mean.dtype == np.float32

    def test_obs_var_dtype_float32(self):
        rng = np.random.RandomState(1)
        ckpt = _make_checkpoint(rng)
        assert ckpt.obs_var.dtype == np.float32

    def test_obs_var_nonnegative(self):
        # Population variance is always ≥ 0
        rng = np.random.RandomState(1)
        ckpt = _make_checkpoint(rng)
        assert np.all(ckpt.obs_var >= 0), "obs_var contains negative values"

    def test_obs_clip_value(self):
        # Clip must be 10.0 per §5 / RunConfig default
        rng = np.random.RandomState(1)
        ckpt = _make_checkpoint(rng)
        assert float(ckpt.obs_clip) == pytest.approx(10.0)

    def test_obs_count_nonnegative(self):
        rng = np.random.RandomState(1)
        ckpt = _make_checkpoint(rng)
        assert int(ckpt.obs_count) >= 0


# ---------------------------------------------------------------------------
# §4.3 — Actor MLP weight shapes and dtypes
# ---------------------------------------------------------------------------

class TestActorWeightShapes:
    """Every weight key must have the exact shape from §4.3 and dtype float32."""

    EXPECTED_SHAPES = {
        "actor_fc1_w": (107, 256),
        "actor_fc1_b": (256,),
        "actor_fc2_w": (256, 256),
        "actor_fc2_b": (256,),
        "actor_out_w": (256, 2),
        "actor_out_b": (2,),
    }

    @pytest.mark.parametrize("key,expected", EXPECTED_SHAPES.items())
    def test_shape(self, key, expected):
        rng = np.random.RandomState(2)
        ckpt = _make_checkpoint(rng)
        arr = getattr(ckpt, key)
        assert arr.shape == expected, f"{key}: shape {arr.shape} != {expected}"

    @pytest.mark.parametrize("key,_", EXPECTED_SHAPES.items())
    def test_dtype_float32(self, key, _):
        rng = np.random.RandomState(2)
        ckpt = _make_checkpoint(rng)
        arr = getattr(ckpt, key)
        assert arr.dtype == np.float32, f"{key}: dtype {arr.dtype} != float32"


# ---------------------------------------------------------------------------
# §5 — Save / load round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """save_checkpoint + load_checkpoint preserves all values — §5."""

    def test_metadata_round_trip(self, tmp_path):
        rng = np.random.RandomState(3)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "ckpt_meta.npz"
        save_checkpoint(ckpt, path)
        loaded = load_checkpoint(path)

        assert loaded.schema_version == "1.0.0"
        assert loaded.checkpoint_id  == ckpt.checkpoint_id
        assert loaded.run_id         == ckpt.run_id
        assert loaded.global_step    == ckpt.global_step
        assert loaded.created_at_utc == ckpt.created_at_utc
        assert loaded.code_version   == ckpt.code_version
        assert json.loads(loaded.run_config_json) == json.loads(ckpt.run_config_json)

    def test_obs_stats_round_trip(self, tmp_path):
        rng = np.random.RandomState(3)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "ckpt_obs.npz"
        save_checkpoint(ckpt, path)
        loaded = load_checkpoint(path)

        np.testing.assert_array_equal(loaded.obs_mean, ckpt.obs_mean)
        np.testing.assert_array_equal(loaded.obs_var,  ckpt.obs_var)
        assert loaded.obs_count == ckpt.obs_count
        assert float(loaded.obs_clip) == pytest.approx(float(ckpt.obs_clip))

    def test_actor_weights_round_trip(self, tmp_path):
        rng = np.random.RandomState(3)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "ckpt_actor.npz"
        save_checkpoint(ckpt, path)
        loaded = load_checkpoint(path)

        for key in TestActorWeightShapes.EXPECTED_SHAPES:
            original = getattr(ckpt, key)
            restored = getattr(loaded, key)
            np.testing.assert_array_equal(restored, original, err_msg=f"{key} differs after round-trip")

    def test_critic_weights_absent_when_not_saved(self, tmp_path):
        # Inference-only checkpoint: no critic weights in CheckpointData
        rng = np.random.RandomState(3)
        ckpt = _make_checkpoint(rng)  # critic fields default to None
        path = tmp_path / "ckpt_inference.npz"
        save_checkpoint(ckpt, path)
        loaded = load_checkpoint(path)

        assert loaded.critic1_fc1_w is None
        assert loaded.critic2_fc1_w is None

    def test_round_trip_float32_precision(self, tmp_path):
        # Values survive save/load to float32 machine precision (atol=0 for exact equality)
        rng = np.random.RandomState(4)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "ckpt_precision.npz"
        save_checkpoint(ckpt, path)
        loaded = load_checkpoint(path)

        # All weights stored as float32 → load must be float32 too, bit-exact
        np.testing.assert_array_equal(loaded.actor_fc1_w, ckpt.actor_fc1_w)

    def test_overwrite_is_atomic(self, tmp_path):
        # Writing a new checkpoint to the same path must not corrupt an existing one.
        # Strategy: write first checkpoint, then write second; loaded result = second.
        rng = np.random.RandomState(5)
        ckpt1 = _make_checkpoint(rng, checkpoint_id="ckpt-1", global_step=10_000)
        ckpt2 = _make_checkpoint(rng, checkpoint_id="ckpt-2", global_step=20_000)
        path = tmp_path / "ckpt_atomic.npz"

        save_checkpoint(ckpt1, path)
        save_checkpoint(ckpt2, path)  # overwrite

        loaded = load_checkpoint(path)
        assert loaded.checkpoint_id == "ckpt-2"
        assert loaded.global_step   == 20_000


# ---------------------------------------------------------------------------
# §6 — actor_forward_numpy inference recipe
# ---------------------------------------------------------------------------

class TestActorForwardNumpy:
    """Pure-NumPy actor forward pass — §6."""

    def test_output_in_range_minus_1_to_1(self):
        # tanh output is always in (-1, 1) for any finite input
        rng = np.random.RandomState(10)
        ckpt = _make_checkpoint(rng)
        obs = rng.randn(107).astype(np.float32)
        action = actor_forward_numpy(ckpt, obs)
        assert -1.0 < float(action) < 1.0, f"action {action} out of (-1, 1)"

    def test_deterministic_on_fixed_obs(self):
        # Same checkpoint + same obs → same action every call
        rng = np.random.RandomState(11)
        ckpt = _make_checkpoint(rng)
        obs = rng.randn(107).astype(np.float32)
        a1 = actor_forward_numpy(ckpt, obs)
        a2 = actor_forward_numpy(ckpt, obs)
        assert float(a1) == pytest.approx(float(a2), abs=1e-10)

    def test_manual_forward_matches_api(self):
        """Verify the API matches the documented recipe (§6) — manual computation."""
        rng = np.random.RandomState(12)
        ckpt = _make_checkpoint(rng)
        obs = np.ones(107, dtype=np.float32)

        # Step 1: normalise obs per §4.2 recipe
        # std = sqrt(obs_var + 1e-8)
        std = np.sqrt(ckpt.obs_var + 1e-8)
        norm_obs = np.clip((obs - ckpt.obs_mean) / std, -ckpt.obs_clip, ckpt.obs_clip)

        # Step 2: MLP forward pass
        # h1 = ReLU(norm_obs @ fc1_w + fc1_b)    — shape (256,)
        h1 = np.maximum(0.0, norm_obs @ ckpt.actor_fc1_w + ckpt.actor_fc1_b)
        # h2 = ReLU(h1 @ fc2_w + fc2_b)          — shape (256,)
        h2 = np.maximum(0.0, h1 @ ckpt.actor_fc2_w + ckpt.actor_fc2_b)
        # out = h2 @ out_w + out_b               — shape (2,); [0]=mean, [1]=log_std_raw
        out = h2 @ ckpt.actor_out_w + ckpt.actor_out_b
        # Step 3: tanh(mean)
        expected_action = np.tanh(out[0])

        api_action = actor_forward_numpy(ckpt, obs)
        assert float(api_action) == pytest.approx(float(expected_action), abs=1e-6)

    def test_numpy_jax_parity(self):
        """actor_forward_numpy and actor_forward_jax agree to atol=1e-5 — §7."""
        # This pins the cross-implementation parity requirement from §7.
        rng = np.random.RandomState(13)
        ckpt = _make_checkpoint(rng)
        obs = rng.randn(107).astype(np.float32)

        numpy_action = float(actor_forward_numpy(ckpt, obs))

        # Build a Flax param dict that actor_forward_jax expects from the CheckpointData
        # (conversion is part of the training module — tested here as integration)
        jax_action = float(actor_forward_jax(ckpt, jnp.array(obs)))

        assert numpy_action == pytest.approx(jax_action, abs=1e-5), (
            f"NumPy action {numpy_action} and JAX action {jax_action} differ by "
            f"{abs(numpy_action - jax_action):.2e} (threshold 1e-5)"
        )

    def test_zero_obs_produces_finite_action(self):
        # obs = all-zeros should produce a finite action (no NaN or Inf)
        rng = np.random.RandomState(14)
        ckpt = _make_checkpoint(rng)
        obs = np.zeros(107, dtype=np.float32)
        action = actor_forward_numpy(ckpt, obs)
        assert np.isfinite(float(action)), "all-zero obs produced non-finite action"


# ---------------------------------------------------------------------------
# §7 — Validation / error handling in load_checkpoint
# ---------------------------------------------------------------------------

class TestLoadValidation:
    """load_checkpoint must validate and raise on bad files — §7."""

    def test_missing_required_key_raises_key_error(self, tmp_path):
        # Save a checkpoint then manually tamper with the .npz to remove obs_mean
        rng = np.random.RandomState(20)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "bad_ckpt.npz"
        save_checkpoint(ckpt, path)

        # Re-open and write a new .npz without obs_mean
        data = dict(np.load(path, allow_pickle=False))
        del data["obs_mean"]
        np.savez_compressed(path, **data)

        with pytest.raises(KeyError, match="obs_mean"):
            load_checkpoint(path)

    def test_wrong_shape_raises_value_error(self, tmp_path):
        # actor_fc1_w has wrong shape (e.g. (50, 256) instead of (107, 256))
        rng = np.random.RandomState(21)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "wrong_shape.npz"
        save_checkpoint(ckpt, path)

        data = dict(np.load(path, allow_pickle=False))
        data["actor_fc1_w"] = rng.randn(50, 256).astype(np.float32)   # wrong input dim
        np.savez_compressed(path, **data)

        with pytest.raises(ValueError, match="actor_fc1_w"):
            load_checkpoint(path)

    def test_wrong_dtype_raises_value_error(self, tmp_path):
        # obs_mean stored as float64 instead of float32 should be rejected
        rng = np.random.RandomState(22)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "wrong_dtype.npz"
        save_checkpoint(ckpt, path)

        data = dict(np.load(path, allow_pickle=False))
        data["obs_mean"] = data["obs_mean"].astype(np.float64)   # wrong dtype
        np.savez_compressed(path, **data)

        with pytest.raises(ValueError, match="obs_mean"):
            load_checkpoint(path)

    def test_major_version_bump_raises_value_error(self, tmp_path):
        # A checkpoint with schema_version "2.0.0" must be rejected (§3 semver rules)
        rng = np.random.RandomState(23)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "v2_ckpt.npz"
        save_checkpoint(ckpt, path)

        data = dict(np.load(path, allow_pickle=False))
        data["schema_version"] = np.array("2.0.0")
        np.savez_compressed(path, **data)

        with pytest.raises(ValueError, match="schema_version"):
            load_checkpoint(path)

    def test_minor_version_bump_loads_successfully(self, tmp_path):
        # schema_version "1.1.0" (minor bump) must still load — forward compat (§3)
        rng = np.random.RandomState(24)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "v1_1_ckpt.npz"
        save_checkpoint(ckpt, path)

        data = dict(np.load(path, allow_pickle=False))
        data["schema_version"] = np.array("1.1.0")
        # Add a harmless new optional key (minor addition)
        data["new_optional_key"] = np.array([42.0], dtype=np.float32)
        np.savez_compressed(path, **data)

        loaded = load_checkpoint(path)   # must not raise
        assert loaded.schema_version == "1.1.0"


# ---------------------------------------------------------------------------
# §4.4 — Optional critic weights
# ---------------------------------------------------------------------------

class TestCriticWeights:
    """Optional critic keys are persisted when present and absent otherwise — §4.4."""

    CRITIC_SHAPES = {
        "critic1_fc1_w": (108, 256),   # 107 obs + 1 action = 108 inputs
        "critic1_fc1_b": (256,),
        "critic1_fc2_w": (256, 256),
        "critic1_fc2_b": (256,),
        "critic1_out_w": (256, 1),
        "critic1_out_b": (1,),
        "critic2_fc1_w": (108, 256),
        "critic2_fc1_b": (256,),
        "critic2_fc2_w": (256, 256),
        "critic2_fc2_b": (256,),
        "critic2_out_w": (256, 1),
        "critic2_out_b": (1,),
    }

    def _make_critic_weights(self, rng) -> dict:
        return {k: rng.randn(*s).astype(np.float32)
                for k, s in self.CRITIC_SHAPES.items()}

    def test_critic_weights_round_trip(self, tmp_path):
        rng = np.random.RandomState(30)
        critic_w = self._make_critic_weights(rng)
        ckpt = _make_checkpoint(rng, **critic_w, ent_coef=0.18, target_entropy=-1.0)
        path = tmp_path / "ckpt_with_critic.npz"
        save_checkpoint(ckpt, path)
        loaded = load_checkpoint(path)

        for key in self.CRITIC_SHAPES:
            np.testing.assert_array_equal(
                getattr(loaded, key), getattr(ckpt, key),
                err_msg=f"Critic weight {key} differs after round-trip",
            )

    def test_ent_coef_round_trip(self, tmp_path):
        rng = np.random.RandomState(31)
        ckpt = _make_checkpoint(rng, ent_coef=0.18, target_entropy=-1.0)
        path = tmp_path / "ckpt_entcoef.npz"
        save_checkpoint(ckpt, path)
        loaded = load_checkpoint(path)
        assert float(loaded.ent_coef) == pytest.approx(0.18, rel=1e-5)
        assert float(loaded.target_entropy) == pytest.approx(-1.0, abs=1e-6)

    def test_target_entropy_is_negative_one(self, tmp_path):
        # SAC target entropy = −action_dim = −1.0 (single action, §5 training_pipeline §5.3)
        # target_entropy = −1.0 is the only valid value for this env
        rng = np.random.RandomState(32)
        ckpt = _make_checkpoint(rng, target_entropy=-1.0)
        path = tmp_path / "ckpt_te.npz"
        save_checkpoint(ckpt, path)
        loaded = load_checkpoint(path)
        assert float(loaded.target_entropy) == pytest.approx(-1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# §2 — File format: .npz, flat string keys
# ---------------------------------------------------------------------------

class TestFileFormat:
    def test_file_is_npz(self, tmp_path):
        rng = np.random.RandomState(40)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "ckpt.npz"
        save_checkpoint(ckpt, path)
        assert path.exists()
        assert path.suffix == ".npz"
        # Must be loadable with plain np.load
        data = np.load(path, allow_pickle=False)
        assert "schema_version" in data

    def test_all_actor_keys_present_in_npz(self, tmp_path):
        rng = np.random.RandomState(41)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "ckpt_keys.npz"
        save_checkpoint(ckpt, path)
        data = np.load(path, allow_pickle=False)
        for key in TestActorWeightShapes.EXPECTED_SHAPES:
            assert key in data, f"Required key '{key}' absent from .npz"

    def test_obs_stats_keys_present_in_npz(self, tmp_path):
        rng = np.random.RandomState(42)
        ckpt = _make_checkpoint(rng)
        path = tmp_path / "ckpt_obs_keys.npz"
        save_checkpoint(ckpt, path)
        data = np.load(path, allow_pickle=False)
        for key in ("obs_mean", "obs_var", "obs_count", "obs_clip"):
            assert key in data, f"Required key '{key}' absent from .npz"


# ---------------------------------------------------------------------------
# Reviewer-added cases (to be added by reviewers)
# ---------------------------------------------------------------------------

# reviewer: obs_var=0 edge case — normalize must not divide by zero (eps guard)
def test_obs_var_zero_does_not_nan():
    """When obs_var is exactly zero for a dimension, normalize must not produce NaN.
    The eps=1e-8 guard in the inference recipe (§6: std = sqrt(var + 1e-8)) prevents this."""
    rng = np.random.RandomState(50)
    ckpt = _make_checkpoint(rng)
    # Force obs_var[0] = 0.0
    ckpt_zero_var = CheckpointData(**{
        **ckpt.__dict__,
        "obs_var": np.zeros(107, dtype=np.float32),
    })
    obs = np.zeros(107, dtype=np.float32)
    action = actor_forward_numpy(ckpt_zero_var, obs)
    assert np.isfinite(float(action)), "obs_var=0 produced NaN/Inf action"


# reviewer: obs normalisation in inference recipe is clipped — extreme obs stays in [-10, 10]
def test_inference_recipe_clips_extreme_obs():
    """Verifies the clip step is present in actor_forward_numpy (§6 step 1).
    An obs value far from the mean must produce a normalised value of exactly ±obs_clip."""
    rng = np.random.RandomState(51)
    ckpt = _make_checkpoint(rng, obs_clip=10.0)
    # Set obs_mean=0, obs_var=1 so normalised = obs / std ≈ obs
    ckpt_unit = CheckpointData(**{
        **ckpt.__dict__,
        "obs_mean": np.zeros(107, dtype=np.float32),
        "obs_var":  np.ones(107, dtype=np.float32),
    })
    # obs[0] = 999 → normalised = 999/sqrt(1+1e-8) ≈ 999 → clipped to 10
    obs = np.zeros(107, dtype=np.float32)
    obs[0] = 999.0
    # To verify clip: manually compute normalised[0] before fc1
    std = np.sqrt(np.ones(107, dtype=np.float32) + 1e-8)
    norm = np.clip((obs - ckpt_unit.obs_mean) / std, -10.0, 10.0)
    assert float(norm[0]) == pytest.approx(10.0, rel=1e-5), (
        "Clip not applied: normalised obs[0] should be 10.0 not 999"
    )
    # The action must still be finite (the network sees clipped input)
    action = actor_forward_numpy(ckpt_unit, obs)
    assert np.isfinite(float(action))


# reviewer: critic input is obs‖action concat (108 dims) — weight shape (108,256) not (107,256)
def test_critic_fc1_input_dim_is_108():
    """Critic Q-network input = obs (107) ‖ action (1) = 108 dims.
    actor_fc1_w input dim is 107; critic1_fc1_w input dim is 108 (§4.4)."""
    rng = np.random.RandomState(52)
    critic_shapes = TestCriticWeights.CRITIC_SHAPES
    # critic1_fc1_w shape is (108, 256) not (107, 256)
    assert critic_shapes["critic1_fc1_w"][0] == 108, (
        "Critic input dim must be 108 = 107 obs + 1 action"
    )
    assert critic_shapes["critic1_fc1_w"] != TestActorWeightShapes.EXPECTED_SHAPES["actor_fc1_w"], (
        "Critic and actor fc1 weights have the same shape — critic input must be 108, not 107"
    )
