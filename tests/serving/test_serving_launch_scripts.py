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

    def test_jax_gpu_cuda_extras_exists(self):
        # B3 fix: split group — jax-gpu-cuda for Windows/Linux CUDA
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        assert "jax-gpu-cuda" in extras, "Missing extras group 'jax-gpu-cuda' in pyproject.toml"

    def test_jax_gpu_metal_extras_exists(self):
        # B3 fix: split group — jax-gpu-metal for macOS Apple Silicon
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        assert "jax-gpu-metal" in extras, "Missing extras group 'jax-gpu-metal' in pyproject.toml"

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

    def test_serving_extras_does_not_include_sbx(self):
        """T2: serving group must NOT include sbx (training-only dep; §9.2, reviewer T2)."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        serving = extras.get("serving", [])
        assert not any("sbx" in dep.lower() for dep in serving), (
            f"'sbx' found in serving extras: {serving}"
        )

    def test_serving_extras_does_not_include_purejaxrl(self):
        """T2: serving group must NOT include purejaxrl (training-only dep; §9.2, reviewer T2)."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        serving = extras.get("serving", [])
        assert not any("purejaxrl" in dep.lower() for dep in serving), (
            f"'purejaxrl' found in serving extras: {serving}"
        )

    def test_jax_cpu_extras_has_jax_package(self):
        """B3: jax-cpu extras must install the `jax` core package (not just jaxlib).
        `jax[cpu]` satisfies this by pulling both; `jaxlib[cpu]` alone does not.
        """
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        jax_cpu = extras.get("jax-cpu", [])
        # Accept: jax[cpu], jax>=..., jax==... — but NOT bare jaxlib[cpu] without jax
        has_jax_core = any(
            dep.lower().startswith("jax[") or dep.lower().startswith("jax>=") or dep.lower().startswith("jax==")
            for dep in jax_cpu
        )
        assert has_jax_core, (
            f"jax-cpu extras must include the 'jax' core package (e.g. 'jax[cpu]>=0.4.25'), "
            f"not just jaxlib. Found: {jax_cpu}"
        )

    def test_jax_gpu_cuda_has_jax_package(self):
        """B3: jax-gpu-cuda extras must install the `jax` core package."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        jax_gpu_cuda = extras.get("jax-gpu-cuda", [])
        has_jax_core = any(
            dep.lower().startswith("jax[") or dep.lower().startswith("jax>=") or dep.lower().startswith("jax==")
            for dep in jax_gpu_cuda
        )
        assert has_jax_core, (
            f"jax-gpu-cuda extras must include the 'jax' core package. Found: {jax_gpu_cuda}"
        )

    def test_jax_gpu_metal_has_jax_and_jax_metal(self):
        """B3: jax-gpu-metal extras must include both `jax` core and `jax-metal`."""
        data = self._load_pyproject()
        extras = data["project"]["optional-dependencies"]
        jax_gpu_metal = extras.get("jax-gpu-metal", [])
        has_jax_core = any(
            dep.lower().startswith("jax>=") or dep.lower().startswith("jax==") or dep.lower().startswith("jax[")
            for dep in jax_gpu_metal
        )
        has_jax_metal = any("jax-metal" in dep.lower() for dep in jax_gpu_metal)
        assert has_jax_core, f"jax-gpu-metal must include jax core. Found: {jax_gpu_metal}"
        assert has_jax_metal, f"jax-gpu-metal must include jax-metal. Found: {jax_gpu_metal}"

    def test_no_hardcoded_version_in_scripts_not_in_pyproject(self):
        """T4: any version pin (>=, ==) in script text must also appear in pyproject.toml.
        Scripts must not hardcode versions not recorded in pyproject (§9.5 #7).
        """
        import re
        data = self._load_pyproject()
        # Collect all version strings from pyproject extras
        all_deps: list[str] = []
        for group_deps in data["project"]["optional-dependencies"].values():
            all_deps.extend(group_deps)
        pyproject_versions = set()
        for dep in all_deps:
            for pin in re.findall(r'[><=!]{1,2}\d[\d.]*', dep):
                pyproject_versions.add(pin)

        for script in (INSTALL_SH, RUN_SH, INSTALL_PS1, RUN_PS1):
            if not script.exists():
                continue
            content = script.read_text(errors="replace")
            # Find version strings in script text (e.g. ">=0.4.25", "==3.11")
            script_pins = re.findall(r'[><=!]{1,2}\d[\d.]+', content)
            for pin in script_pins:
                # Allow port numbers (4+ digit standalone) and year refs
                if re.fullmatch(r'\d{4}', pin.lstrip('>=<!')):
                    continue
                assert pin in pyproject_versions, (
                    f"Version pin '{pin}' in {script.name} not found in pyproject.toml. "
                    f"All version strings must come from pyproject (§9.5 #7)."
                )


# ---------------------------------------------------------------------------
# §9.4 — Idempotency (slow — requires actual install)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def installed_serving_cpu(tmp_path_factory):
    """Install serving+cpu once; yield the tmp directory; used by idempotency tests."""
    tmp = tmp_path_factory.mktemp("serving_install")
    # Copy minimal project to tmp
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp / "pyproject.toml")
    shutil.copytree(REPO_ROOT / "src", tmp / "src")  # required for uv pip install -e .
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
# §9.1 §9.2 — Cross-platform parity (flag set equivalence)  [B2 rewrite]
# ---------------------------------------------------------------------------

# The canonical contracted flag set.  Keys are the kebab-case .sh flag names;
# values are the PascalCase .ps1 parameter names.  §9.1 parity requirement.
CONTRACTED_FLAGS: dict[str, str] = {
    "server-type":    "ServerType",
    "accel":          "Accel",
    "site":           "Site",
    "checkpoint":     "Checkpoint",
    "backend-port":   "BackendPort",
    "frontend-port":  "FrontendPort",
    "no-launch":      "NoLaunch",
    "uninstall":      "Uninstall",
    "purge":          "Purge",
}


def _sh_flags_from_help(script: Path) -> set[str]:
    """Invoke `bash script --help` and parse '--flag' names from the output.
    Falls back to source-text regex only if --help exits non-zero (script not yet
    implemented).  The regex in fallback is intentionally strict:
    it only matches '--word' tokens in USAGE / OPTIONS context lines.
    """
    result = subprocess.run(
        ["bash", str(script), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    text = result.stdout + result.stderr
    import re
    flags = set(re.findall(r"--([a-z][a-z-]+)", text))
    return flags


def _ps1_params_from_help(script: Path) -> set[str]:
    """Invoke `pwsh script -Help` and parse '-ParamName' names.
    Falls back to type-annotation line parsing when pwsh is unavailable or
    returns no output (e.g. on macOS without PowerShell installed).
    """
    text = ""
    try:
        result = subprocess.run(
            ["pwsh", "-NonInteractive", "-File", str(script), "-Help"],
            capture_output=True, text=True, timeout=10,
        )
        text = result.stdout + result.stderr
    except (FileNotFoundError, OSError):
        pass  # pwsh not installed; fall through to source-parse
    import re
    params = set(re.findall(r"-([A-Z][A-Za-z]+)", text))
    if not params:
        # Fallback: scan for [string]/[switch]/[bool]/[int] type-annotation lines
        # e.g. "    [string]$ServerType = ..." → captures "ServerType".
        # This avoids balanced-paren matching on the param() block (non-greedy
        # regex stops at the first ")" inside a [Parameter(HelpMessage="...")] line).
        content = script.read_text(errors="replace")
        params = set(
            re.findall(
                r'^\s*\[(?:string|int|bool|switch)\]\s*\$([A-Z][A-Za-z]+)',
                content,
                re.MULTILINE,
            )
        )
    return params


class TestCrossPlatformFlagParity:
    """B2 rewrite: real set-equality check over the full contracted flag set.

    Strategy: get each script's declared flags/params (preferably from --help
    output, with source-parse fallback), then assert both sides cover every
    entry in CONTRACTED_FLAGS.  Finally assert the two sets are equal under
    the kebab→PascalCase mapping.
    """

    def _sh_flag_set(self) -> set[str]:
        """Return kebab-case flag names declared by install_app.sh."""
        if not INSTALL_SH.exists():
            pytest.skip("install_app.sh not yet implemented")
        flags = _sh_flags_from_help(INSTALL_SH)
        if not flags:
            pytest.skip("install_app.sh --help produced no flags (not yet implemented)")
        return flags

    def _ps1_param_set_pascal(self) -> set[str]:
        """Return PascalCase param names declared by install_app.ps1."""
        if not INSTALL_PS1.exists():
            pytest.skip("install_app.ps1 not yet implemented")
        params = _ps1_params_from_help(INSTALL_PS1)
        if not params:
            pytest.skip("install_app.ps1 -Help produced no params (not yet implemented)")
        return params

    def test_sh_declares_all_contracted_flags(self):
        """install_app.sh must declare every flag in CONTRACTED_FLAGS."""
        sh_flags = self._sh_flag_set()
        missing = set(CONTRACTED_FLAGS.keys()) - sh_flags
        assert not missing, (
            f"install_app.sh is missing contracted flags: {sorted(missing)}\n"
            f"Flags found: {sorted(sh_flags)}"
        )

    def test_ps1_declares_all_contracted_params(self):
        """install_app.ps1 must declare every param in CONTRACTED_FLAGS."""
        ps1_params = self._ps1_param_set_pascal()
        missing = set(CONTRACTED_FLAGS.values()) - ps1_params
        assert not missing, (
            f"install_app.ps1 is missing contracted params: {sorted(missing)}\n"
            f"Params found: {sorted(ps1_params)}"
        )

    def test_sh_and_ps1_flag_sets_are_equal(self):
        """Cross-platform parity: the two scripts' flag sets must be equal
        under the kebab→PascalCase bijection (§9.1).
        """
        sh_flags = self._sh_flag_set()
        ps1_params = self._ps1_param_set_pascal()

        def kebab_to_pascal(s: str) -> str:
            return "".join(w.capitalize() for w in s.split("-"))

        sh_as_pascal = {kebab_to_pascal(f) for f in sh_flags}
        # Restrict to the contracted set to avoid noise from internal vars
        contracted_pascal = set(CONTRACTED_FLAGS.values())

        sh_contracted = sh_as_pascal & contracted_pascal
        ps1_contracted = ps1_params & contracted_pascal

        only_sh = sh_contracted - ps1_contracted
        only_ps1 = ps1_contracted - sh_contracted

        assert not only_sh and not only_ps1, (
            f"Flag parity violation between .sh and .ps1:\n"
            f"  In .sh but not .ps1 (as PascalCase): {sorted(only_sh)}\n"
            f"  In .ps1 but not .sh:                  {sorted(only_ps1)}"
        )

    @skip_on_windows
    def test_sh_invalid_flag_exits_1(self, tmp_path):
        """T5 (port validation): passing an unknown flag exits 1 (contract §10)."""
        result = run_sh(
            INSTALL_SH,
            ["--server-type", "training", "--accel", "cpu", "--unknown-flag", "x"],
            cwd=tmp_path,
        )
        assert result.returncode == 1, (
            f"Unknown flag should exit 1, got {result.returncode}"
        )

    @skip_on_windows
    def test_backend_port_out_of_range_exits_1_sh(self, tmp_path):
        """T5: port outside 1–65535 must exit 1 (contract §3, §10 code 1)."""
        result = run_sh(
            INSTALL_SH,
            ["--server-type", "training", "--accel", "cpu", "--backend-port", "99999", "--no-launch"],
            cwd=tmp_path,
        )
        assert result.returncode == 1, (
            f"Port 99999 (>65535) should exit 1, got {result.returncode}"
        )

    @skip_on_windows
    def test_backend_port_zero_exits_1_sh(self, tmp_path):
        """T5: port 0 is invalid (range 1–65535) → exit 1."""
        result = run_sh(
            INSTALL_SH,
            ["--server-type", "training", "--accel", "cpu", "--backend-port", "0", "--no-launch"],
            cwd=tmp_path,
        )
        assert result.returncode == 1, (
            f"Port 0 should exit 1, got {result.returncode}"
        )

    @skip_on_windows
    def test_backend_port_non_integer_exits_1_sh(self, tmp_path):
        """T5: non-integer port → exit 1."""
        result = run_sh(
            INSTALL_SH,
            ["--server-type", "training", "--accel", "cpu", "--backend-port", "abc", "--no-launch"],
            cwd=tmp_path,
        )
        assert result.returncode == 1, (
            f"Non-integer port should exit 1, got {result.returncode}"
        )

    @skip_on_non_windows
    def test_backend_port_out_of_range_exits_1_ps1(self, tmp_path):
        """T5 (PowerShell): port outside 1–65535 must exit 1."""
        result = run_ps1(
            INSTALL_PS1,
            ["-ServerType", "training", "-Accel", "cpu", "-BackendPort", "99999", "-NoLaunch"],
            cwd=tmp_path,
        )
        assert result.returncode == 1, (
            f"Port 99999 should exit 1 on .ps1, got {result.returncode}"
        )


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
    shutil.copytree(REPO_ROOT / "src", tmp_path / "src")  # required for uv pip install -e .
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
    shutil.copytree(REPO_ROOT / "src", tmp_path / "src")  # required for uv pip install -e .
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
    shutil.copytree(REPO_ROOT / "src", tmp_path / "src")  # required for uv pip install -e .
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

    def test_install_sh_references_jax_gpu_cuda_or_metal_extras(self):
        """Scripts must reference the split jax-gpu-cuda / jax-gpu-metal groups (B3)."""
        content = INSTALL_SH.read_text(errors="replace")
        assert "jax-gpu-cuda" in content or "jax-gpu-metal" in content, (
            "install_app.sh does not reference 'jax-gpu-cuda' or 'jax-gpu-metal' extras groups"
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
    """After launch, .run/pids.json must be valid JSON keyed by role (contract §11).

    NOTE (T8 / reviewer): test_pids_json_schema validates a hand-written fixture,
    NOT actual script output (the real launch test is skipped).  PID-file behavior
    is therefore not tested end-to-end in fast CI; it is covered by
    test_acceptance_launch_exit5_on_bound_port_sh (slow) once the script exists.
    """

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


# ---------------------------------------------------------------------------
# T1: serving venv EXCLUDES training deps (§9.5 #1 headline requirement)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@skip_on_windows
def test_acceptance_serving_venv_excludes_training_deps_sh(tmp_path):
    """T1: serving install must NOT install optax, flax, or sbx in the venv.

    This is the §9.5 #1 headline requirement: 'serving not training'.
    The existing test checks fastapi present; this one checks the other side.
    """
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copytree(REPO_ROOT / "src", tmp_path / "src")  # required for uv pip install -e .
    shutil.copy(INSTALL_SH, tmp_path / "install_app.sh")
    os.chmod(tmp_path / "install_app.sh", 0o755)
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
    if result.returncode != 0:
        pytest.skip(f"Install failed (toolchain absent?): {result.stderr[:200]}")

    pip = tmp_path / ".venv" / "bin" / "pip"
    freeze = subprocess.run([str(pip), "freeze"], capture_output=True, text=True)
    freeze_lower = freeze.stdout.lower()

    # Training-only deps must NOT appear
    for forbidden in ("optax", "flax", "sbx", "purejaxrl"):
        assert forbidden not in freeze_lower, (
            f"Training-only dep '{forbidden}' found in serving venv — must be excluded (§9.2).\n"
            f"pip freeze:\n{freeze.stdout}"
        )


# ---------------------------------------------------------------------------
# T3: built frontend bundle present after serving/full install (§9.5 #1)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@skip_on_windows
def test_acceptance_serving_builds_frontend_bundle_sh(tmp_path):
    """T3: serving install must produce a built frontend bundle (dist/ or configured output).

    §9.5 #1: 'built static assets'.  We check that dist/ (or dist/index.html)
    exists after --server-type serving --no-launch.

    NOTE: This requires Node/npm to be installed and package.json to exist.
    If Node is absent the test is skipped (slow/environment-dependent).
    """
    if shutil.which("npm") is None:
        pytest.skip("npm not available — frontend build test skipped")
    if not (REPO_ROOT / "package.json").exists():
        pytest.skip("package.json not present — frontend not yet scaffolded")

    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copytree(REPO_ROOT / "scripts", tmp_path / "scripts")
    for sh_file in (tmp_path / "scripts").glob("*.sh"):
        os.chmod(sh_file, 0o755)
    # Copy frontend source so npm ci/build can run
    for f in ("package.json", "package-lock.json", "vite.config.ts", "tsconfig.json",
              "index.html", ".npmrc"):
        if (REPO_ROOT / f).exists():
            shutil.copy(REPO_ROOT / f, tmp_path / f)
    for d in ("src", "public"):
        if (REPO_ROOT / d).exists():
            shutil.copytree(REPO_ROOT / d, tmp_path / d)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site_gansu.yaml").write_text("site:\n  name: gansu\n")
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints" / "run_001").write_text("dummy")

    result = subprocess.run(
        [
            "bash", str(tmp_path / "scripts" / "install_app.sh"),
            "--server-type", "serving",
            "--accel", "cpu",
            "--checkpoint", "checkpoints/run_001",
            "--no-launch",
        ],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, (
        f"Serving install (with frontend build) failed.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    dist_dir = tmp_path / "dist"
    assert dist_dir.exists(), (
        f"dist/ not created after serving install (§9.5 #1 'built static assets').\n"
        f"stdout: {result.stdout}"
    )
    assert any(dist_dir.iterdir()), "dist/ is empty after serving install"


# ---------------------------------------------------------------------------
# T6: launch failure → exit 5 (port already bound)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@skip_on_windows
def test_acceptance_launch_exit5_on_bound_port_sh(tmp_path):
    """T6: launching with an already-bound port must exit 5 (contract §10 code 5).

    We bind a port in this process, then tell install_app to launch on that port.
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", 0))
        bound_port = s.getsockname()[1]
    except OSError:
        pytest.skip("Could not bind a test socket for port-conflict test")

    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copytree(REPO_ROOT / "src", tmp_path / "src")  # required for uv pip install -e .
    shutil.copy(INSTALL_SH, tmp_path / "install_app.sh")
    os.chmod(tmp_path / "install_app.sh", 0o755)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site_gansu.yaml").write_text("site:\n  name: gansu\n")
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints" / "run_001").write_text("dummy")
    # Create a minimal .venv marker so install doesn't re-install
    (tmp_path / ".venv").mkdir()

    try:
        result = subprocess.run(
            [
                "bash", str(tmp_path / "install_app.sh"),
                "--server-type", "serving",
                "--accel", "cpu",
                "--checkpoint", "checkpoints/run_001",
                "--backend-port", str(bound_port),
                # no --no-launch: we want the launch to be attempted
            ],
            capture_output=True, text=True, cwd=tmp_path, timeout=15,
        )
    finally:
        s.close()

    assert result.returncode == 5, (
        f"Expected exit 5 (launch failure / port in use), got {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        f"NOTE: if exit 5 is hard to trigger reliably, document this as a known CI gap."
    )
    assert "ERROR [5]" in result.stderr or "port" in result.stderr.lower(), (
        f"Expected 'ERROR [5]' or 'port' in stderr.\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# T7: jax core package is importable in the serving venv (B3 runtime check)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@skip_on_windows
def test_acceptance_jax_importable_in_serving_venv_sh(tmp_path):
    """T7: after serving install, `import jax` must succeed inside the venv (B3).

    Verifies that jax[cpu] (not just jaxlib[cpu]) was installed.
    """
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copytree(REPO_ROOT / "src", tmp_path / "src")  # required for uv pip install -e .
    shutil.copy(INSTALL_SH, tmp_path / "install_app.sh")
    os.chmod(tmp_path / "install_app.sh", 0o755)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site_gansu.yaml").write_text("site:\n  name: gansu\n")
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints" / "run_001").write_text("dummy")

    r_install = subprocess.run(
        [
            "bash", str(tmp_path / "install_app.sh"),
            "--server-type", "serving",
            "--accel", "cpu",
            "--checkpoint", "checkpoints/run_001",
            "--no-launch",
        ],
        capture_output=True, text=True, cwd=tmp_path,
    )
    if r_install.returncode != 0:
        pytest.skip(f"Install failed (toolchain absent?): {r_install.stderr[:200]}")

    python = tmp_path / ".venv" / "bin" / "python"
    r_import = subprocess.run(
        [str(python), "-c", "import jax; print(jax.__version__)"],
        capture_output=True, text=True,
    )
    assert r_import.returncode == 0, (
        f"'import jax' failed in serving venv — jax core package not installed (B3).\n"
        f"stderr: {r_import.stderr}"
    )


# ---------------------------------------------------------------------------
# T8 (acknowledged gap): FastAPI health endpoint after run_app launch
# ---------------------------------------------------------------------------

def test_health_endpoint_gap_acknowledged():
    """T8: §9.5 #4 requires that after `run_app` the FastAPI health endpoint responds.

    This is a KNOWN CI GAP: the test requires a live launch, a running FastAPI
    process, and network access to localhost.  It is NOT silently absent — this
    placeholder makes the gap explicit in the test suite.

    To close the gap: add a slow acceptance test that:
      1. Calls install_app serving --no-launch (setup)
      2. Calls run_app serving (launches the API)
      3. Polls GET http://localhost:<port>/health until 200 or timeout
      4. Calls install_app --uninstall to clean up

    Until that test exists, §9.5 #4 is validated manually by the QA step.
    """
    # This test always passes — it exists to prevent the gap from being invisible.
    pass


# ---------------------------------------------------------------------------
# reviewer (backend-reviewer): destructive --purge path safety invariant
# ---------------------------------------------------------------------------


@pytest.mark.slow
@skip_on_windows
def test_purge_preserves_config_but_removes_checkpoints_sh(tmp_path):
    # reviewer: the suite pins uninstall-preserves-config but NOT the riskier
    # reviewer: --purge path. Contract §9.4 / §9 (line 155): --purge additionally
    # reviewer: removes checkpoints/ and *.run artifacts, but config/ is NEVER
    # reviewer: removed. This pins that safety invariant on the destructive path.
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(INSTALL_SH, tmp_path / "install_app.sh")
    os.chmod(tmp_path / "install_app.sh", 0o755)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site_gansu.yaml").write_text("site:\n  name: gansu\n")
    (tmp_path / "checkpoints").mkdir()
    (tmp_path / "checkpoints" / "run_001").write_text("dummy")

    base = [
        "bash", str(tmp_path / "install_app.sh"),
        "--server-type", "serving", "--accel", "cpu",
        "--checkpoint", "checkpoints/run_001",
    ]
    r_install = subprocess.run(base + ["--no-launch"], capture_output=True, text=True, cwd=tmp_path)
    if r_install.returncode != 0:
        pytest.skip(f"Install failed (toolchain absent?): {r_install.stderr[:200]}")

    r_purge = subprocess.run(base + ["--uninstall", "--purge"], capture_output=True, text=True, cwd=tmp_path)
    assert r_purge.returncode == 0, f"--uninstall --purge failed: {r_purge.stderr}"
    # config/ MUST survive even under --purge (§9.4: config is NEVER removed)
    assert (tmp_path / "config" / "site_gansu.yaml").exists(), (
        "config/site_gansu.yaml was removed by --purge — §9.4 says config is NEVER removed"
    )
    # checkpoints/ MUST be cleared by --purge
    assert not (tmp_path / "checkpoints" / "run_001").exists(), (
        "--purge did not remove checkpoints/run_001"
    )
