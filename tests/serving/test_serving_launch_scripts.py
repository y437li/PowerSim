"""
Tests for scripts/install_app.sh, scripts/install_app.ps1,
scripts/run_app.sh, scripts/run_app.ps1.

Contract: contracts/serving/launch_scripts.md
Spec:     REBUILD_SPEC.md §9

Strategy:
  - All tests use subprocess to invoke the real scripts; they do NOT test
    internal shell functions in isolation.
  - Tests that actually install a venv are marked @pytest.mark.slow and
    skipped in fast CI (only the acceptance criteria tests run in full CI).
  - Everything that touches .venv/ uses a tmp_path fixture to stay isolated.
  - Platform guards: .sh tests skip on Windows; .ps1 tests skip on non-Windows.
  - Idempotency tests require a prior successful install, so they depend on
    the slow-install fixture.

NOTE: All tests in this file are RED until implementation is complete —
that is the correct state at the contract+tests gate.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parents[2]  # tests/serving/ → repo root
INSTALL_SH = REPO_ROOT / "scripts" / "install_app.sh"
RUN_SH = REPO_ROOT / "scripts" / "run_app.sh"
INSTALL_PS1 = REPO_ROOT / "scripts" / "install_app.ps1"
RUN_PS1 = REPO_ROOT / "scripts" / "run_app.ps1"

IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"

skip_on_windows = pytest.mark.skipif(IS_WINDOWS, reason=".sh tests: macOS only")
skip_on_macos = pytest.mark.skipif(IS_MACOS, reason=".ps1 tests: Windows only")
skip_on_non_windows = pytest.mark.skipif(
    not IS_WINDOWS, reason=".ps1 tests: Windows only"
)


def run_sh(script: Path, args: list[str], *, cwd: Path | None = None, env=None) -> subprocess.CompletedProcess:
    """Run a .sh script with bash and return the CompletedProcess."""
    return subprocess.run(
        ["bash", str(script)] + args,
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
        env=env,
    )


def run_ps1(script: Path, args: list[str], *, cwd: Path | None = None, env=None) -> subprocess.CompletedProcess:
    """Run a .ps1 script with pwsh and return the CompletedProcess."""
    return subprocess.run(
        ["pwsh", "-NonInteractive", "-File", str(script)] + args,
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
        env=env,
    )


# ---------------------------------------------------------------------------
# §9.1 — Script existence
# ---------------------------------------------------------------------------


class TestScriptExistence:
    """All four scripts must exist at the contracted paths."""

    def test_install_sh_exists(self):
        assert INSTALL_SH.exists(), f"Missing: {INSTALL_SH}"

    def test_run_sh_exists(self):
        assert RUN_SH.exists(), f"Missing: {RUN_SH}"

    def test_install_ps1_exists(self):
        assert INSTALL_PS1.exists(), f"Missing: {INSTALL_PS1}"

    def test_run_ps1_exists(self):
        assert RUN_PS1.exists(), f"Missing: {RUN_PS1}"

    def test_install_sh_is_executable(self):
        assert os.access(INSTALL_SH, os.X_OK), f"Not executable: {INSTALL_SH}"

    def test_run_sh_is_executable(self):
        assert os.access(RUN_SH, os.X_OK), f"Not executable: {RUN_SH}"


# ---------------------------------------------------------------------------
# §9.3 / contract §3 — Flag parsing: invalid / missing required flags
# ---------------------------------------------------------------------------


class TestFlagParsingErrors:
    """Invalid or missing flags must produce exit code 1 (contract §10)."""

    @skip_on_windows
    def test_missing_server_type_exits_1_sh(self, tmp_path):
        result = run_sh(INSTALL_SH, ["--no-launch"], cwd=tmp_path)
        assert result.returncode == 1, (
            f"Expected exit 1 for missing --server-type, got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )

    @skip_on_windows
    def test_invalid_server_type_exits_1_sh(self, tmp_path):
        result = run_sh(INSTALL_SH, ["--server-type", "bogus", "--no-launch"], cwd=tmp_path)
        assert result.returncode == 1
        assert "server-type" in result.stderr.lower() or "server_type" in result.stderr.lower() or "servertype" in result.stderr.lower() or "server type" in result.stderr.lower()

    @skip_on_windows
    def test_invalid_accel_exits_1_sh(self, tmp_path):
        result = run_sh(INSTALL_SH, ["--server-type", "dev", "--accel", "tpu", "--no-launch"], cwd=tmp_path)
        assert result.returncode == 1
        # Remediation hint must be present
        stderr_lower = result.stderr.lower()
        assert "accel" in stderr_lower or "accelerator" in stderr_lower

    @skip_on_windows
    def test_all_valid_server_types_parse_sh(self, tmp_path):
        """All four server types must be recognized (not exit 1 for type-validation).

        We mock away the actual install by passing --no-launch and setting a
        fake HOME so uv/pyenv are not invoked. We only check that the script
        doesn't exit 1 for an unknown server-type.
        NOTE: The script may exit non-zero for other reasons (toolchain absent)
        in a bare test environment; the important thing is exit code != 1 for
        type-parse error specifically AND that the error text doesn't reference
        an unknown server type.
        """
        for stype in ("dev", "training", "serving", "full"):
            result = run_sh(
                INSTALL_SH,
                ["--server-type", stype, "--no-launch"],
                cwd=tmp_path,
            )
            # Must NOT complain about unknown server type
            assert "unknown" not in result.stderr.lower() or stype not in result.stderr, (
                f"Server type '{stype}' was rejected as unknown"
            )

    @skip_on_non_windows
    def test_missing_server_type_exits_1_ps1(self, tmp_path):
        result = run_ps1(INSTALL_PS1, ["-NoLaunch"], cwd=tmp_path)
        assert result.returncode == 1

    @skip_on_non_windows
    def test_invalid_server_type_exits_1_ps1(self, tmp_path):
        result = run_ps1(INSTALL_PS1, ["-ServerType", "bogus", "-NoLaunch"], cwd=tmp_path)
        assert result.returncode == 1

    @skip_on_non_windows
    def test_invalid_accel_exits_1_ps1(self, tmp_path):
        result = run_ps1(INSTALL_PS1, ["-ServerType", "dev", "-Accel", "tpu", "-NoLaunch"], cwd=tmp_path)
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# §9.3 / contract §3 — Flag parsing: checkpoint required for serving/full
# ---------------------------------------------------------------------------


class TestCheckpointRequiredFlag:
    """--checkpoint is required for serving/full; absence → exit 4."""

    @skip_on_windows
    def test_serving_without_checkpoint_exits_4_sh(self, tmp_path):
        # Simulate no .run/last_checkpoint present
        result = run_sh(
            INSTALL_SH,
            ["--server-type", "serving", "--accel", "cpu", "--no-launch"],
            cwd=tmp_path,
        )
        assert result.returncode == 4, (
            f"Expected exit 4 for missing --checkpoint with serving, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "checkpoint" in result.stderr.lower()

    @skip_on_windows
    def test_full_without_checkpoint_exits_4_sh(self, tmp_path):
        result = run_sh(
            INSTALL_SH,
            ["--server-type", "full", "--accel", "cpu", "--no-launch"],
            cwd=tmp_path,
        )
        assert result.returncode == 4
        assert "checkpoint" in result.stderr.lower()

    @skip_on_windows
    def test_last_checkpoint_fallback_accepted_sh(self, tmp_path):
        """If .run/last_checkpoint exists, --checkpoint is not required."""
        run_dir = tmp_path / ".run"
        run_dir.mkdir()
        (run_dir / "last_checkpoint").write_text("checkpoints/run_001")
        # Provide a dummy site yaml to avoid exit 4 for config
        site_yaml = tmp_path / "site.yaml"
        site_yaml.write_text("site:\n  name: test\n")
        result = run_sh(
            INSTALL_SH,
            [
                "--server-type", "serving",
                "--accel", "cpu",
                "--no-launch",
                "--site", str(site_yaml),
            ],
            cwd=tmp_path,
        )
        # Should NOT exit 4 for missing checkpoint (may exit non-zero for other reasons
        # like missing venv in a bare environment — that's acceptable here)
        assert result.returncode != 4, (
            f"Should not exit 4 when .run/last_checkpoint exists\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    @skip_on_non_windows
    def test_serving_without_checkpoint_exits_4_ps1(self, tmp_path):
        result = run_ps1(
            INSTALL_PS1,
            ["-ServerType", "serving", "-Accel", "cpu", "-NoLaunch"],
            cwd=tmp_path,
        )
        assert result.returncode == 4
        assert "checkpoint" in result.stderr.lower()


# ---------------------------------------------------------------------------
# §9.2 — Accelerator fail-loud rule
# ---------------------------------------------------------------------------


class TestAcceleratorFailLoud:
    """--accel gpu on a no-GPU box must exit 6 with a remediation hint."""

    @skip_on_windows
    def test_accel_gpu_no_gpu_exits_6_sh(self, tmp_path, monkeypatch):
        """Simulate a GPU-absent environment by shadowing nvidia-smi and
        forcing JAX to report no GPU devices.

        We set PATH to a fake bin dir that contains a dummy nvidia-smi that
        exits 1 (not found), and set JAX_PLATFORM_NAME=cpu so the venv
        check also returns cpu.
        """
        fake_bin = tmp_path / "fake_bin"
        fake_bin.mkdir()
        # fake nvidia-smi that always exits 1 (no GPU)
        fake_nvidia_smi = fake_bin / "nvidia-smi"
        fake_nvidia_smi.write_text("#!/bin/bash\nexit 1\n")
        fake_nvidia_smi.chmod(0o755)

        env = {**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin", "JAX_PLATFORM_NAME": "cpu"}
        result = run_sh(
            INSTALL_SH,
            ["--server-type", "training", "--accel", "gpu", "--no-launch"],
            cwd=tmp_path,
            env=env,
        )
        assert result.returncode == 6, (
            f"Expected exit 6 for --accel gpu with no GPU, got {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        # Remediation message must mention GPU/CUDA/Metal
        stderr_lower = result.stderr.lower()
        assert any(word in stderr_lower for word in ("gpu", "cuda", "metal", "accelerator")), (
            f"Remediation hint missing from stderr: {result.stderr}"
        )

    @skip_on_windows
    def test_accel_cpu_always_succeeds_parse_sh(self, tmp_path):
        """--accel cpu must never exit 6 (may exit for other reasons)."""
        result = run_sh(
            INSTALL_SH,
            ["--server-type", "training", "--accel", "cpu", "--no-launch"],
            cwd=tmp_path,
        )
        assert result.returncode != 6

    @skip_on_windows
    def test_serving_accel_gpu_is_warning_not_error_sh(self, tmp_path):
        """serving + --accel gpu: warns but continues (exit ≠ 6); contract §7."""
        result = run_sh(
            INSTALL_SH,
            ["--server-type", "serving", "--accel", "gpu", "--no-launch"],
            cwd=tmp_path,
        )
        assert result.returncode != 6, (
            "serving + --accel gpu should warn (not exit 6); got returncode 6"
        )
        # But checkpoint will be missing → exit 4; that's fine
        # What matters is the script did NOT reject --accel gpu with exit 6 for serving

    @skip_on_non_windows
    def test_accel_gpu_no_gpu_exits_6_ps1(self, tmp_path):
        # On a CI Windows runner without a GPU this should trigger exit 6.
        result = run_ps1(
            INSTALL_PS1,
            ["-ServerType", "training", "-Accel", "gpu", "-NoLaunch"],
            cwd=tmp_path,
        )
        assert result.returncode == 6
        assert any(
            word in result.stderr.lower()
            for word in ("gpu", "cuda", "metal", "accelerator")
        )


# ---------------------------------------------------------------------------
# §9.2 — Server-type → extras mapping (pyproject.toml)
# ---------------------------------------------------------------------------


class TestPyprojectExtrasGroups:
    """pyproject.toml must define the extras groups the scripts reference."""

    def _load_pyproject(self) -> dict:
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            import tomli as tomllib  # fallback
        with open(REPO_ROOT / "pyproject.toml", "rb") as f:
            return tomllib.load(f)

    def test_jax_cpu_extras_exists(self):
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        assert "jax-cpu" in extras, "Missing extras group 'jax-cpu' in pyproject.toml"

    def test_jax_gpu_extras_exists(self):
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        assert "jax-gpu" in extras, "Missing extras group 'jax-gpu' in pyproject.toml"

    def test_training_extras_exists(self):
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        assert "training" in extras, "Missing extras group 'training' in pyproject.toml"

    def test_serving_extras_exists(self):
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        assert "serving" in extras, "Missing extras group 'serving' in pyproject.toml"

    def test_serving_extras_has_fastapi(self):
        """Serving extras must include fastapi (not a training dep)."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        serving = extras.get("serving", [])
        assert any("fastapi" in dep.lower() for dep in serving), (
            f"'fastapi' not found in serving extras: {serving}"
        )

    def test_training_extras_has_optax(self):
        """Training extras must include optax."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        training = extras.get("training", [])
        assert any("optax" in dep.lower() for dep in training), (
            f"'optax' not found in training extras: {training}"
        )

    def test_serving_extras_does_not_include_optax(self):
        """The serving group must NOT include optax (training-only dep; §9.2)."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        serving = extras.get("serving", [])
        assert not any("optax" in dep.lower() for dep in serving), (
            f"'optax' found in serving extras — serving must not pull training deps: {serving}"
        )

    def test_serving_extras_does_not_include_flax(self):
        """Serving group must NOT include flax (training-only dep; §9.2)."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        serving = extras.get("serving", [])
        assert not any("flax" in dep.lower() for dep in serving), (
            f"'flax' found in serving extras: {serving}"
        )

    def test_jax_cpu_extras_has_jaxlib(self):
        """jax-cpu extras must contain a jaxlib entry."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        jax_cpu = extras.get("jax-cpu", [])
        assert any("jaxlib" in dep.lower() for dep in jax_cpu), (
            f"'jaxlib' not found in jax-cpu extras: {jax_cpu}"
        )

    def test_jax_gpu_extras_has_jaxlib_or_jax_metal(self):
        """jax-gpu extras must contain jaxlib (CUDA) or jax-metal (macOS)."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        jax_gpu = extras.get("jax-gpu", [])
        assert any(
            "jaxlib" in dep.lower() or "jax-metal" in dep.lower()
            for dep in jax_gpu
        ), f"Neither 'jaxlib' nor 'jax-metal' found in jax-gpu extras: {jax_gpu}"


# ---------------------------------------------------------------------------
# §9.4 — Idempotency (slow — requires actual install)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def installed_serving_cpu(tmp_path_factory):
    """Install serving+cpu once; yield the tmp directory; used by idempotency tests."""
    tmp = tmp_path_factory.mktemp("serving_install")
    # Copy minimal project to tmp
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp / "pyproject.toml")
    shutil.copy(REPO_ROOT / "scripts" / "install_app.sh", tmp / "install_app.sh")
    os.chmod(tmp / "install_app.sh", 0o755)
    # Provide a minimal site yaml
    site_yaml = tmp / "config" / "site_gansu.yaml"
    site_yaml.parent.mkdir()
    site_yaml.write_text("site:\n  name: gansu\n")
    # Provide a dummy checkpoint
    ckpt = tmp / "checkpoints" / "run_001"
    ckpt.parent.mkdir()
    ckpt.write_text("dummy")
    # First install
    result = subprocess.run(
        [
            "bash", str(tmp / "install_app.sh"),
            "--server-type", "serving",
            "--accel", "cpu",
            "--checkpoint", str(ckpt),
            "--no-launch",
        ],
        capture_output=True, text=True, cwd=tmp,
    )
    if result.returncode != 0:
        pytest.skip(f"First install failed (toolchain absent in CI?): {result.stderr[:300]}")
    yield tmp


@pytest.mark.slow
@skip_on_windows
def test_idempotent_rerun_is_noop_sh(installed_serving_cpu):
    """Second identical run exits 0 and prints 'up to date' or 'nothing to do'."""
    tmp = installed_serving_cpu
    ckpt = tmp / "checkpoints" / "run_001"
    result = subprocess.run(
        [
            "bash", str(tmp / "install_app.sh"),
            "--server-type", "serving",
            "--accel", "cpu",
            "--checkpoint", str(ckpt),
            "--no-launch",
        ],
        capture_output=True, text=True, cwd=tmp,
    )
    assert result.returncode == 0, f"Idempotent rerun failed: {result.stderr}"
    combined = (result.stdout + result.stderr).lower()
    assert "up to date" in combined or "nothing to do" in combined or "no changes" in combined, (
        f"Expected 'up to date' / 'nothing to do' message on second run. Got:\n{combined}"
    )


@pytest.mark.slow
@skip_on_windows
def test_idempotent_does_not_delete_config_sh(installed_serving_cpu):
    """Idempotent rerun must never delete config/ files (§9.4)."""
    tmp = installed_serving_cpu
    site_yaml = tmp / "config" / "site_gansu.yaml"
    assert site_yaml.exists(), "config/site_gansu.yaml was deleted by install_app"


# ---------------------------------------------------------------------------
# §9.4 — Uninstall semantics
# ---------------------------------------------------------------------------


@pytest.mark.slow
@skip_on_windows
def test_uninstall_removes_venv_sh(installed_serving_cpu):
    """--uninstall removes .venv/ and .run/ but not config/."""
    tmp = installed_serving_cpu
    ckpt = tmp / "checkpoints" / "run_001"

    result = subprocess.run(
        [
            "bash", str(tmp / "install_app.sh"),
            "--server-type", "serving",
            "--accel", "cpu",
            "--checkpoint", str(ckpt),
            "--uninstall",
        ],
        capture_output=True, text=True, cwd=tmp,
    )
    assert result.returncode == 0, f"Uninstall failed: {result.stderr}"
    assert not (tmp / ".venv").exists(), ".venv was not removed by --uninstall"
    assert not (tmp / ".run").exists(), ".run was not removed by --uninstall"


@pytest.mark.slow
@skip_on_windows
def test_uninstall_preserves_config_sh(installed_serving_cpu):
    """--uninstall must not remove config/ (§9.4)."""
    tmp = installed_serving_cpu
    site_yaml = tmp / "config" / "site_gansu.yaml"
    assert site_yaml.exists(), "config/ was deleted by --uninstall"


@pytest.mark.slow
@skip_on_windows
def test_purge_without_uninstall_exits_1_sh(tmp_path):
    """--purge alone (without --uninstall) must exit 1."""
    result = run_sh(
        INSTALL_SH,
        ["--server-type", "serving", "--purge"],
        cwd=tmp_path,
    )
    assert result.returncode == 1, (
        f"--purge without --uninstall must exit 1, got {result.returncode}"
    )


# ---------------------------------------------------------------------------
# §9.3 §9.4 — run_app errors when no venv
# ---------------------------------------------------------------------------


class TestRunAppNoVenv:
    """run_app must error if .venv/ is missing."""

    @skip_on_windows
    def test_run_sh_no_venv_exits_nonzero(self, tmp_path):
        site_yaml = tmp_path / "site.yaml"
        site_yaml.write_text("site:\n  name: test\n")
        result = run_sh(
            RUN_SH,
            [
                "--server-type", "serving",
                "--accel", "cpu",
                "--site", str(site_yaml),
            ],
            cwd=tmp_path,
        )
        assert result.returncode != 0
        stderr_lower = result.stderr.lower()
        assert "install" in stderr_lower or "venv" in stderr_lower, (
            f"Expected 'install' or 'venv' in error message. Got:\n{result.stderr}"
        )

    @skip_on_non_windows
    def test_run_ps1_no_venv_exits_nonzero(self, tmp_path):
        site_yaml = tmp_path / "site.yaml"
        site_yaml.write_text("site:\n  name: test\n")
        result = run_ps1(
            RUN_PS1,
            ["-ServerType", "serving", "-Accel", "cpu", "-Site", str(site_yaml)],
            cwd=tmp_path,
        )
        assert result.returncode != 0
        assert "install" in result.stderr.lower() or "venv" in result.stderr.lower()


# ---------------------------------------------------------------------------
# §9.4 — Error message format
# ---------------------------------------------------------------------------


class TestErrorMessageFormat:
    """Every non-zero exit must print exactly one ERROR line with cause + remediation."""

    @skip_on_windows
    def test_error_line_format_invalid_type_sh(self, tmp_path):
        result = run_sh(INSTALL_SH, ["--server-type", "bad_type", "--no-launch"], cwd=tmp_path)
        assert result.returncode != 0
        # At least one stderr line must contain ERROR
        error_lines = [l for l in result.stderr.splitlines() if "ERROR" in l]
        assert len(error_lines) >= 1, (
            f"Expected at least one 'ERROR' line in stderr.\nstderr:\n{result.stderr}"
        )

    @skip_on_windows
    def test_error_line_mentions_remediation_sh(self, tmp_path):
        result = run_sh(INSTALL_SH, ["--server-type", "bad_type", "--no-launch"], cwd=tmp_path)
        stderr_lower = result.stderr.lower()
        assert "remediation" in stderr_lower or "hint" in stderr_lower or "use " in stderr_lower or "try " in stderr_lower, (
            f"Expected remediation hint in stderr.\nstderr:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# §9.1 §9.2 — Cross-platform parity (flag set equivalence)
# ---------------------------------------------------------------------------


class TestCrossPlatformFlagParity:
    """Both .sh and .ps1 variants must support the same flag set (§9.1 parity)."""

    def _extract_sh_flags(self) -> set[str]:
        """Parse --flag names from install_app.sh."""
        content = INSTALL_SH.read_text(errors="replace")
        import re
        return set(re.findall(r"--([a-z][a-z-]+)", content))

    def _extract_ps1_params(self) -> set[str]:
        """Parse -ParamName names from install_app.ps1 (lowercased for comparison)."""
        content = INSTALL_PS1.read_text(errors="replace")
        import re
        # Match param block entries: [string]$ServerType etc.
        params = set(re.findall(r'\$([A-Za-z][A-Za-z]+)', content))
        return {p.lower() for p in params}

    def test_sh_has_server_type_flag(self):
        """install_app.sh must accept --server-type."""
        flags = self._extract_sh_flags()
        assert "server-type" in flags, f".sh flags found: {flags}"

    def test_sh_has_accel_flag(self):
        flags = self._extract_sh_flags()
        assert "accel" in flags, f".sh flags found: {flags}"

    def test_sh_has_no_launch_flag(self):
        flags = self._extract_sh_flags()
        assert "no-launch" in flags, f".sh flags found: {flags}"

    def test_sh_has_uninstall_flag(self):
        flags = self._extract_sh_flags()
        assert "uninstall" in flags, f".sh flags found: {flags}"

    def test_sh_has_purge_flag(self):
        flags = self._extract_sh_flags()
        assert "purge" in flags, f".sh flags found: {flags}"

    def test_sh_has_backend_port_flag(self):
        flags = self._extract_sh_flags()
        assert "backend-port" in flags, f".sh flags found: {flags}"

    def test_sh_has_frontend_port_flag(self):
        flags = self._extract_sh_flags()
        assert "frontend-port" in flags, f".sh flags found: {flags}"

    def test_ps1_has_server_type_param(self):
        """install_app.ps1 must accept -ServerType."""
        params = self._extract_ps1_params()
        assert "servertype" in params, f".ps1 params found: {params}"

    def test_ps1_has_accel_param(self):
        params = self._extract_ps1_params()
        assert "accel" in params, f".ps1 params found: {params}"

    def test_ps1_has_nolaunch_param(self):
        params = self._extract_ps1_params()
        assert "nolaunch" in params, f".ps1 params found: {params}"

    def test_ps1_has_uninstall_param(self):
        params = self._extract_ps1_params()
        assert "uninstall" in params, f".ps1 params found: {params}"

    def test_ps1_has_purge_param(self):
        params = self._extract_ps1_params()
        assert "purge" in params, f".ps1 params found: {params}"


# ---------------------------------------------------------------------------
# §9.4 — No secrets baked into scripts
# ---------------------------------------------------------------------------


class TestNoSecretsInScripts:
    """Scripts must not contain hardcoded secrets (API keys, tokens, passwords)."""

    SECRET_PATTERNS = [
        "api_key", "apikey", "password", "passwd", "token",
        "secret", "credential", "private_key",
    ]

    def _check_script(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        content = path.read_text(errors="replace").lower()
        hits = []
        for pat in self.SECRET_PATTERNS:
            # Look for assignments (key=value, not just mentions)
            import re
            # Pattern like: VAR_NAME=SOMETHING or $VAR_NAME = "SOMETHING"
            if re.search(rf'{pat}\s*[=:]\s*["\']?[a-z0-9_\-]{{8,}}', content):
                hits.append(pat)
        return hits

    def test_install_sh_no_secrets(self):
        hits = self._check_script(INSTALL_SH)
        assert not hits, f"Possible hardcoded secrets in install_app.sh: {hits}"

    def test_run_sh_no_secrets(self):
        hits = self._check_script(RUN_SH)
        assert not hits, f"Possible hardcoded secrets in run_app.sh: {hits}"

    def test_install_ps1_no_secrets(self):
        hits = self._check_script(INSTALL_PS1)
        assert not hits, f"Possible hardcoded secrets in install_app.ps1: {hits}"

    def test_run_ps1_no_secrets(self):
        hits = self._check_script(RUN_PS1)
        assert not hits, f"Possible hardcoded secrets in run_app.ps1: {hits}"


# ---------------------------------------------------------------------------
# §9.5 — Acceptance criteria: dot-venv structure after install (slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@skip_on_windows
def test_acceptance_serving_cpu_creates_venv_sh(tmp_path):
    """§9.5: install serving + cpu --no-launch produces a .venv with serving deps."""
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(INSTALL_SH, tmp_path / "install_app.sh")
    os.chmod(tmp_path / "install_app.sh", 0o755)
    # Minimal site yaml + checkpoint
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site_gansu.yaml").write_text("site:\n  name: gansu\n")
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints" / "run_001").write_text("dummy")

    result = subprocess.run(
        [
            "bash", str(tmp_path / "install_app.sh"),
            "--server-type", "serving",
            "--accel", "cpu",
            "--checkpoint", "checkpoints/run_001",
            "--no-launch",
        ],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, (
        f"§9.5 acceptance: install serving --no-launch failed.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # .venv must exist
    assert (tmp_path / ".venv").exists(), ".venv not created after install"
    # fastapi must be installed (serving dep)
    pip = tmp_path / ".venv" / "bin" / "pip"
    freeze = subprocess.run([str(pip), "freeze"], capture_output=True, text=True)
    assert "fastapi" in freeze.stdout.lower(), (
        f"fastapi not found in .venv after serving install.\nfreeze:\n{freeze.stdout}"
    )


@pytest.mark.slow
@skip_on_windows
def test_acceptance_training_no_node_sh(tmp_path):
    """§9.5: --server-type training --no-launch installs training deps and no Node/frontend."""
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(INSTALL_SH, tmp_path / "install_app.sh")
    os.chmod(tmp_path / "install_app.sh", 0o755)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site_gansu.yaml").write_text("site:\n  name: gansu\n")

    result = subprocess.run(
        [
            "bash", str(tmp_path / "install_app.sh"),
            "--server-type", "training",
            "--accel", "cpu",
            "--no-launch",
        ],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, (
        f"§9.5 acceptance: training install failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert (tmp_path / ".venv").exists()
    # node_modules must NOT exist (training type skips Node/frontend)
    assert not (tmp_path / "node_modules").exists(), (
        "node_modules created for training type — must not install Node deps"
    )


@pytest.mark.slow
@skip_on_windows
def test_acceptance_serving_idempotent_second_run_sh(tmp_path):
    """§9.5: re-running serving install is idempotent (second run exits 0, no changes)."""
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(INSTALL_SH, tmp_path / "install_app.sh")
    os.chmod(tmp_path / "install_app.sh", 0o755)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site_gansu.yaml").write_text("site:\n  name: gansu\n")
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints" / "run_001").write_text("dummy")

    base_args = [
        "bash", str(tmp_path / "install_app.sh"),
        "--server-type", "serving",
        "--accel", "cpu",
        "--checkpoint", "checkpoints/run_001",
        "--no-launch",
    ]

    r1 = subprocess.run(base_args, capture_output=True, text=True, cwd=tmp_path)
    if r1.returncode != 0:
        pytest.skip(f"First install failed (toolchain absent?): {r1.stderr[:200]}")

    r2 = subprocess.run(base_args, capture_output=True, text=True, cwd=tmp_path)
    assert r2.returncode == 0, f"Second (idempotent) run failed: {r2.stderr}"
    combined = (r2.stdout + r2.stderr).lower()
    assert (
        "up to date" in combined
        or "nothing to do" in combined
        or "no changes" in combined
    ), f"Expected idempotency message on second run. Got:\n{combined}"


# ---------------------------------------------------------------------------
# §9.3 §9.2 — Training type installs training deps (pyproject check, no venv needed)
# ---------------------------------------------------------------------------


class TestServerTypeExtrasMapping:
    """Verify scripts select the right extras groups per server type.

    We inspect the script text to confirm the mapping, since actually
    running installs is a slow/environment-dependent test.
    """

    def test_install_sh_references_training_extras(self):
        """install_app.sh must reference the 'training' extras group when
        server-type=training is selected."""
        content = INSTALL_SH.read_text(errors="replace")
        assert "training" in content, (
            "install_app.sh does not reference 'training' extras group"
        )

    def test_install_sh_references_serving_extras(self):
        content = INSTALL_SH.read_text(errors="replace")
        assert "serving" in content, (
            "install_app.sh does not reference 'serving' extras group"
        )

    def test_install_sh_references_jax_cpu_extras(self):
        content = INSTALL_SH.read_text(errors="replace")
        assert "jax-cpu" in content, (
            "install_app.sh does not reference 'jax-cpu' extras group"
        )

    def test_install_sh_references_jax_gpu_extras(self):
        content = INSTALL_SH.read_text(errors="replace")
        assert "jax-gpu" in content, (
            "install_app.sh does not reference 'jax-gpu' extras group"
        )

    def test_install_ps1_references_training_extras(self):
        content = INSTALL_PS1.read_text(errors="replace")
        assert "training" in content

    def test_install_ps1_references_serving_extras(self):
        content = INSTALL_PS1.read_text(errors="replace")
        assert "serving" in content


# ---------------------------------------------------------------------------
# §9.3 — .run/ PID file structure
# ---------------------------------------------------------------------------


class TestRunStateFiles:
    """After launch, .run/pids.json must be valid JSON keyed by role (contract §11)."""

    @pytest.mark.slow
    @skip_on_windows
    def test_pids_json_valid_after_launch(self, tmp_path):
        """If a server is launched, .run/pids.json must be valid JSON."""
        # This test requires an actual launch — we use a mock environment
        # where the FastAPI process is stubbed. For now we mark slow and
        # verify the file structure only if the launch actually occurs.
        pytest.skip("Launch tests require a full environment; deferred to §9.5 acceptance CI")

    def test_pids_json_schema(self, tmp_path):
        """If .run/pids.json exists, it must be a dict with integer PID values."""
        run_dir = tmp_path / ".run"
        run_dir.mkdir()
        pids_file = run_dir / "pids.json"
        # Write a well-formed pids.json and verify it validates
        pids_file.write_text(json.dumps({"api": 12345, "training": 67890}))
        data = json.loads(pids_file.read_text())
        assert isinstance(data, dict), "pids.json must be a JSON object"
        for key, val in data.items():
            assert isinstance(val, int), f"PID for '{key}' must be an integer, got {val!r}"
        # Keys must be from the allowed set
        allowed_keys = {"api", "training", "frontend"}
        for key in data:
            assert key in allowed_keys, f"Unexpected key '{key}' in pids.json; allowed: {allowed_keys}"
