"""Tests: energy_go.training package must be importable without JAX.

Regression fix for PR #59 deployment issue:
  `from energy_go.training.checkpoint_format import ...` crashed on serving boxes
  without JAX because energy_go/training/__init__.py eagerly imported the full JAX
  stack, and checkpoint_format.py had `import jax.numpy as jnp` at module level.

The §6 contract (contracts/shared/checkpoint_format.md) states that
`actor_forward_numpy` and `load_checkpoint` are pure-NumPy; this test suite pins
that guarantee at the import level.

Fix: PEP 562 lazy __getattr__ in training/__init__.py; module-level `import jnp`
moved inside the two JAX-only convenience properties (actor_params, obs_stats).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_in_clean_python(code: str) -> subprocess.CompletedProcess:
    """Run code in a fresh Python subprocess with jax/jaxlib blocked in sys.modules."""
    wrapped = textwrap.dedent(f"""\
        import sys
        # Block jax and jaxlib so any eager import of either raises ImportError
        sys.modules['jax'] = None
        sys.modules['jaxlib'] = None
        sys.modules['jax.numpy'] = None
        sys.modules['jax.nn'] = None
        {code}
    """)
    return subprocess.run(
        [sys.executable, "-c", wrapped],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# 1. checkpoint_format imports cleanly without JAX
# ---------------------------------------------------------------------------

def test_checkpoint_format_importable_without_jax():
    """Import checkpoint_format with JAX absent — must not raise.

    This is the direct regression test for the PR #59 deployment issue.
    The contract (§6) states actor_forward_numpy is pure-NumPy; the import
    must not require jax to be installed.
    """
    result = _run_in_clean_python(
        "from energy_go.training.checkpoint_format import "
        "load_checkpoint, actor_forward_numpy, CheckpointData; "
        "print('ok')"
    )
    assert result.returncode == 0, (
        "checkpoint_format import failed without jax:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# 2. energy_go.training package-level import is JAX-free
# ---------------------------------------------------------------------------

def test_training_package_importable_without_jax():
    """energy_go.training itself must be importable without jax.

    The training __init__ uses PEP 562 lazy __getattr__ so that
    `import energy_go.training` no longer triggers the JAX-heavy submodules.
    """
    result = _run_in_clean_python(
        "import energy_go.training; print('ok')"
    )
    assert result.returncode == 0, (
        "energy_go.training import failed without jax:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# 3. actor_forward_numpy runs end-to-end without JAX
# ---------------------------------------------------------------------------

def test_actor_forward_numpy_runs_without_jax():
    """actor_forward_numpy must execute on a JAX-free box.

    Verifies that the full import + construction + forward pass chain is
    jax-free.  Expected output: (6,) float32 array printed as a numpy array.
    """
    code = textwrap.dedent("""\
        import numpy as np
        from energy_go.training.checkpoint_format import CheckpointData, actor_forward_numpy
        rng = np.random.default_rng(0)
        ckpt = CheckpointData(
            schema_version="1.0.0",
            checkpoint_id="lazy-test-0000-0000-0000-000000000001",
            run_id="lazy_test",
            global_step=1,
            created_at_utc="2026-06-11T00:00:00Z",
            code_version="test",
            run_config_json="{}",
            obs_dim=107,
            action_dim=6,
            obs_count=1,
            obs_mean=np.zeros(107, dtype=np.float32),
            obs_var=np.ones(107, dtype=np.float32),
            obs_clip=np.float32(10.0),
            actor_fc1_w=rng.standard_normal((107, 256)).astype(np.float32),
            actor_fc1_b=np.zeros(256, dtype=np.float32),
            actor_fc2_w=rng.standard_normal((256, 256)).astype(np.float32),
            actor_fc2_b=np.zeros(256, dtype=np.float32),
            actor_out_w=rng.standard_normal((256, 12)).astype(np.float32),
            actor_out_b=np.zeros(12, dtype=np.float32),
        )
        obs = np.ones(107, dtype=np.float32)
        action = actor_forward_numpy(ckpt, obs)
        assert action.shape == (6,), f"expected (6,) got {action.shape}"
        assert action.dtype == np.float32, f"expected float32 got {action.dtype}"
        # a_bat in (-1, 1), fractions in (0, 1)
        assert -1.0 < float(action[0]) < 1.0, f"a_bat out of range: {action[0]}"
        assert all(0.0 < float(f) < 1.0 for f in action[1:6]), f"fractions out of range: {action[1:6]}"
        print('ok')
    """)
    result = _run_in_clean_python(code)
    assert result.returncode == 0, (
        "actor_forward_numpy failed without jax:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# 4. JAX-dependent symbols still accessible WITH jax (regression guard)
# ---------------------------------------------------------------------------

def test_training_public_api_accessible_with_jax():
    """energy_go.training public symbols remain reachable when jax IS present.

    The lazy __getattr__ must not break `from energy_go.training import train`.
    Skipped if jax is not installed (CI without jax would skip gracefully).
    """
    try:
        import jax  # noqa: F401
    except (ImportError, ModuleNotFoundError):
        pytest.skip("jax not installed — skipping JAX-dependent API check")

    # Import each public symbol that the lazy init defers
    from energy_go.training import RunConfig, RunningStats  # noqa: F401
    from energy_go.training import train, run_eval, run_baseline  # noqa: F401
    # If we got here without AttributeError, the lazy init resolves correctly.


# ---------------------------------------------------------------------------
# 5. checkpoint_format JAX-only properties still work WITH jax
# ---------------------------------------------------------------------------

def test_actor_params_and_obs_stats_require_jax():
    """actor_params and obs_stats properties work when jax is present.

    These convenience properties return JAX arrays and require jax; they
    should still function correctly after the local-import fix.
    Skipped if jax is not installed.
    """
    try:
        import jax.numpy as jnp  # noqa: F401
        import numpy as np
    except (ImportError, ModuleNotFoundError):
        pytest.skip("jax not installed — skipping jax-property check")

    from energy_go.training.checkpoint_format import CheckpointData
    rng = np.random.default_rng(0)
    ckpt = CheckpointData(
        schema_version="1.0.0",
        checkpoint_id="lazy-test-0000-0000-0000-000000000002",
        run_id="lazy_test",
        global_step=1,
        created_at_utc="2026-06-11T00:00:00Z",
        code_version="test",
        run_config_json="{}",
        obs_dim=107,
        action_dim=6,
        obs_count=1,
        obs_mean=np.zeros(107, dtype=np.float32),
        obs_var=np.ones(107, dtype=np.float32),
        obs_clip=np.float32(10.0),
        actor_fc1_w=rng.standard_normal((107, 256)).astype(np.float32),
        actor_fc1_b=np.zeros(256, dtype=np.float32),
        actor_fc2_w=rng.standard_normal((256, 256)).astype(np.float32),
        actor_fc2_b=np.zeros(256, dtype=np.float32),
        actor_out_w=rng.standard_normal((256, 12)).astype(np.float32),
        actor_out_b=np.zeros(12, dtype=np.float32),
    )

    # actor_params: should return dict of JAX arrays
    params = ckpt.actor_params
    assert set(params.keys()) == {"fc1_w", "fc1_b", "fc2_w", "fc2_b", "out_w", "out_b"}, (
        f"actor_params keys wrong: {set(params.keys())}"
    )

    # obs_stats: should return RunningStats NamedTuple with JAX arrays
    stats = ckpt.obs_stats
    assert hasattr(stats, "mean") and hasattr(stats, "var"), (
        f"obs_stats missing mean/var: {stats}"
    )
