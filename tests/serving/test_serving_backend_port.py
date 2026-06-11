"""Tests for backend port configuration (ENERGY_GO_BACKEND_PORT env var).

Contract: contracts/serving/backend_port.md
Spec:     REBUILD_SPEC.md §9.3
Companion: contracts/frontend/configurable_ports.md (defines the env var)

Tests cover:
  1. app.py __main__ block — reads ENERGY_GO_BACKEND_PORT, default 8000.
  2. scripts/run_app.sh  — env var feeds BACKEND_PORT default (Bash only).
  3. scripts/run_app.ps1 — env var feeds $BackendPort default (Windows only).

Priority order (highest wins): CLI flag > env var > hardcoded 8000.

NOTE: All tests in this file are RED until implementation is complete —
that is the correct state at the contract+tests gate.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parents[2]
RUN_SH    = REPO_ROOT / "scripts" / "run_app.sh"
RUN_PS1   = REPO_ROOT / "scripts" / "run_app.ps1"

IS_WINDOWS = platform.system() == "Windows"

skip_on_windows = pytest.mark.skipif(IS_WINDOWS, reason=".sh tests: non-Windows only")
skip_on_non_windows = pytest.mark.skipif(
    not IS_WINDOWS, reason=".ps1 tests: Windows only"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_APP_MAIN_CODE = (
    "import sys\n"
    "class _FakeUvicorn:\n"
    "    def run(self, *a, **kw):\n"
    "        print(f'PORT:{kw[\"port\"]}')\n"
    "sys.modules['uvicorn'] = _FakeUvicorn()\n"
    "import runpy\n"
    "runpy.run_module('energy_go.serving.app', run_name='__main__')\n"
)


def _run_app_as_main(
    *,
    extra_env: dict[str, str] | None = None,
    remove_keys: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Run energy_go.serving.app as __main__ with uvicorn.run stubbed.

    The stub replaces uvicorn in sys.modules so the local `import uvicorn`
    inside the __main__ block picks it up; the fake records which port it
    was asked to bind and prints PORT:<n> to stdout.

    Args:
        extra_env:   key/value pairs merged on top of os.environ.
        remove_keys: keys to remove from os.environ before merging extra_env.
    """
    env = dict(os.environ)
    for k in remove_keys or []:
        env.pop(k, None)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", _APP_MAIN_CODE],
        capture_output=True,
        text=True,
        env=env,
    )


def _make_fake_venv(base: Path) -> Path:
    """Create a minimal .venv directory that satisfies run_app.sh's existence check."""
    venv_dir = base / ".venv"
    venv_dir.mkdir(parents=True, exist_ok=True)
    (venv_dir / "bin").mkdir(exist_ok=True)
    # run_app.sh sources .venv/bin/activate — create a no-op stub
    activate = venv_dir / "bin" / "activate"
    activate.write_text("# stub activate\n")
    return venv_dir


def _run_sh(args: list[str], *, cwd: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run run_app.sh with bash and return the CompletedProcess."""
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run(
        ["bash", str(RUN_SH)] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


def _run_ps1(args: list[str], *, cwd: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run run_app.ps1 with pwsh and return the CompletedProcess."""
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run(
        ["pwsh", "-NonInteractive", "-File", str(RUN_PS1)] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


# ---------------------------------------------------------------------------
# §1 — app.py __main__ block: port resolution
# ---------------------------------------------------------------------------

class TestAppMainPort:
    """app.py __main__ block honours ENERGY_GO_BACKEND_PORT (contract §1)."""

    def test_default_port_8000_when_env_var_absent(self):
        """No ENERGY_GO_BACKEND_PORT in env → port 8000.

        Hand-computed: os.environ.get('ENERGY_GO_BACKEND_PORT', '8000') returns '8000',
        int('8000') == 8000.
        """
        result = _run_app_as_main(remove_keys=["ENERGY_GO_BACKEND_PORT"])
        assert result.returncode == 0, (
            f"app.__main__ crashed with env var absent.\n"
            f"stderr: {result.stderr}"
        )
        assert "PORT:8000" in result.stdout, (
            f"Expected PORT:8000 in stdout, got: {result.stdout!r}\n"
            f"(ENERGY_GO_BACKEND_PORT was removed from env)"
        )

    def test_env_var_9001_used_as_port(self):
        """ENERGY_GO_BACKEND_PORT=9001 → port 9001.

        Hand-computed: int("9001") == 9001.
        """
        result = _run_app_as_main(extra_env={"ENERGY_GO_BACKEND_PORT": "9001"})
        assert result.returncode == 0, (
            f"app.__main__ crashed.\nstderr: {result.stderr}"
        )
        assert "PORT:9001" in result.stdout, (
            f"Expected PORT:9001 in stdout, got: {result.stdout!r}\n"
            f"(ENERGY_GO_BACKEND_PORT=9001)"
        )

    def test_env_var_8888_used_as_port(self):
        """ENERGY_GO_BACKEND_PORT=8888 → port 8888 (boundary away from default 8000).

        Hand-computed: int("8888") == 8888.
        """
        result = _run_app_as_main(extra_env={"ENERGY_GO_BACKEND_PORT": "8888"})
        assert result.returncode == 0, (
            f"app.__main__ crashed.\nstderr: {result.stderr}"
        )
        assert "PORT:8888" in result.stdout, (
            f"Expected PORT:8888, got: {result.stdout!r}"
        )

    def test_empty_string_uses_default_8000(self):
        """ENERGY_GO_BACKEND_PORT="" → falls back to default 8000.

        os.environ.get('ENERGY_GO_BACKEND_PORT', '8000') returns "" for empty string,
        then int("") raises ValueError.  The contract says empty string → default 8000.
        So the implementation must treat empty string specially:
          port = int(os.environ.get("ENERGY_GO_BACKEND_PORT") or "8000")
        This test enforces that contract provision.

        Hand-computed: empty str → "8000" sentinel → int("8000") == 8000.
        """
        result = _run_app_as_main(extra_env={"ENERGY_GO_BACKEND_PORT": ""})
        assert result.returncode == 0, (
            f"app.__main__ crashed on empty ENERGY_GO_BACKEND_PORT.\n"
            f"stderr: {result.stderr}"
        )
        assert "PORT:8000" in result.stdout, (
            f"Expected PORT:8000 for empty env var, got: {result.stdout!r}"
        )

    def test_non_integer_raises_value_error(self):
        """ENERGY_GO_BACKEND_PORT=abc → ValueError, non-zero exit.

        Contract: non-integer values raise ValueError (stdlib int() semantics).
        Hand-computed: int("abc") raises ValueError.
        """
        result = _run_app_as_main(extra_env={"ENERGY_GO_BACKEND_PORT": "abc"})
        assert result.returncode != 0, (
            f"Expected non-zero exit for ENERGY_GO_BACKEND_PORT=abc but got 0.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_port_1_accepted(self):
        """ENERGY_GO_BACKEND_PORT=1 → port 1 (minimum valid OS port).

        Hand-computed: int("1") == 1.
        """
        result = _run_app_as_main(extra_env={"ENERGY_GO_BACKEND_PORT": "1"})
        assert result.returncode == 0, (
            f"app.__main__ rejected ENERGY_GO_BACKEND_PORT=1.\nstderr: {result.stderr}"
        )
        assert "PORT:1" in result.stdout, (
            f"Expected PORT:1, got: {result.stdout!r}"
        )

    def test_port_65535_accepted(self):
        """ENERGY_GO_BACKEND_PORT=65535 → port 65535 (maximum valid OS port).

        Hand-computed: int("65535") == 65535.
        """
        result = _run_app_as_main(extra_env={"ENERGY_GO_BACKEND_PORT": "65535"})
        assert result.returncode == 0, (
            f"app.__main__ rejected ENERGY_GO_BACKEND_PORT=65535.\nstderr: {result.stderr}"
        )
        assert "PORT:65535" in result.stdout, (
            f"Expected PORT:65535, got: {result.stdout!r}"
        )

    # reviewer: app.py must NOT range-validate — contract §34/35 says the port is
    # passed straight to uvicorn and "the OS rejects out-of-range at bind(); the
    # launch scripts validate the range explicitly." So a negative *integer* parses
    # cleanly here (no rejection at the app.py layer); only non-integers raise.
    # Hand-computed: int("-1") == -1 (valid int, no ValueError); app.py prints PORT:-1
    # and exits 0. (uvicorn/OS would later reject at bind — outside this layer's job.)
    def test_negative_int_parsed_not_rejected_by_app(self):
        result = _run_app_as_main(extra_env={"ENERGY_GO_BACKEND_PORT": "-1"})
        assert result.returncode == 0, (
            f"app.__main__ must parse a negative int without raising (range is the "
            f"scripts' job, contract §34/35); got rc={result.returncode}.\n"
            f"stderr: {result.stderr}"
        )
        assert "PORT:-1" in result.stdout, (
            f"Expected PORT:-1 (int('-1') == -1, no range check in app.py), "
            f"got: {result.stdout!r}"
        )

    # reviewer: stdlib int() strips surrounding ASCII whitespace, so a padded value
    # parses to the inner integer. Pins that the impl uses bare int(...) (not a
    # stricter custom parser that would reject the spaces).
    # Hand-computed: int(" 9000 ") == 9000 → PORT:9000, exit 0.
    def test_whitespace_padded_port_parsed(self):
        result = _run_app_as_main(extra_env={"ENERGY_GO_BACKEND_PORT": " 9000 "})
        assert result.returncode == 0, (
            f"app.__main__ rejected a whitespace-padded port; int(' 9000 ')==9000.\n"
            f"stderr: {result.stderr}"
        )
        assert "PORT:9000" in result.stdout, (
            f"Expected PORT:9000 for ' 9000 ' (int strips surrounding ws), "
            f"got: {result.stdout!r}"
        )

    # reviewer: ADVERSARIAL — a whitespace-ONLY value is neither absent nor the empty
    # string, so contract §36 ("absent or empty string → 8000") does NOT apply; it is
    # a non-integer and must raise per §33. This guards against an over-eager impl
    # using `(os.environ.get(...) or "").strip() or "8000"`, which would WRONGLY map
    # "   " → "8000". The correct `int(os.environ.get(...) or "8000")` form leaves the
    # truthy "   " intact and lets int() raise.
    # Hand-computed: "   " is truthy → int("   ") → ValueError (strip→"" → invalid)
    # → non-zero exit. (Contrast test_empty_string_uses_default_8000: "" is falsy.)
    def test_whitespace_only_raises_value_error(self):
        result = _run_app_as_main(extra_env={"ENERGY_GO_BACKEND_PORT": "   "})
        assert result.returncode != 0, (
            f"Expected non-zero exit for whitespace-only ENERGY_GO_BACKEND_PORT='   ' "
            f"(int('   ') raises ValueError; whitespace-only is NOT the empty-string "
            f"default case per §36); got rc=0.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# §2 — run_app.sh: ENERGY_GO_BACKEND_PORT env-var resolution
# ---------------------------------------------------------------------------

class TestRunAppShEnvPort:
    """run_app.sh reads ENERGY_GO_BACKEND_PORT as the port default (contract §2)."""

    @skip_on_windows
    def test_invalid_env_port_fails_validation(self, tmp_path):
        """ENERGY_GO_BACKEND_PORT=abc → exit 1 (port validation fails).

        Without the fix, BACKEND_PORT stays 8000 and validation passes → exit 4
        (site YAML not found).  After the fix, BACKEND_PORT=abc fails the
        `[[ "$port" =~ ^[0-9]+$ ]]` guard → exit 1.

        Pre-condition: .venv/ exists so the venv check doesn't fire first.
        """
        _make_fake_venv(tmp_path)
        result = _run_sh(
            ["--server-type", "dev"],
            cwd=tmp_path,
            extra_env={"ENERGY_GO_BACKEND_PORT": "abc"},
        )
        assert result.returncode == 1, (
            f"Expected exit 1 for ENERGY_GO_BACKEND_PORT=abc; got {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}\n"
            f"(If exit 4, the env var was not read — BACKEND_PORT defaulted to 8000.)"
        )
        assert "not an integer" in result.stderr.lower() or "invalid" in result.stderr.lower(), (
            f"Expected 'not an integer'/'invalid' in stderr; got: {result.stderr!r}"
        )

    @skip_on_windows
    def test_out_of_range_env_port_fails_validation(self, tmp_path):
        """ENERGY_GO_BACKEND_PORT=99999 → exit 1 (99999 > 65535).

        Without the fix, BACKEND_PORT stays 8000 → validation passes → exit 4.
        After the fix, BACKEND_PORT=99999 fails range check → exit 1.
        """
        _make_fake_venv(tmp_path)
        result = _run_sh(
            ["--server-type", "dev"],
            cwd=tmp_path,
            extra_env={"ENERGY_GO_BACKEND_PORT": "99999"},
        )
        assert result.returncode == 1, (
            f"Expected exit 1 for ENERGY_GO_BACKEND_PORT=99999; got {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        assert "out of range" in result.stderr.lower() or "65535" in result.stderr, (
            f"Expected range-error message in stderr; got: {result.stderr!r}"
        )

    @skip_on_windows
    def test_absent_env_var_uses_8000_default(self, tmp_path):
        """No ENERGY_GO_BACKEND_PORT → BACKEND_PORT=8000 → port validation passes.

        Port 8000 is valid, so the script proceeds past port validation.
        It will next fail because site_gansu.yaml is absent → exit 4.
        This distinguishes 'port validation passed with default 8000' from exit 1.
        """
        _make_fake_venv(tmp_path)
        env = {k: v for k, v in os.environ.items() if k != "ENERGY_GO_BACKEND_PORT"}
        result = subprocess.run(
            ["bash", str(RUN_SH), "--server-type", "dev"],
            capture_output=True, text=True, cwd=tmp_path, env=env,
        )
        # Exits 4 (site YAML not found) — port validation was NOT the failure.
        assert result.returncode == 4, (
            f"Expected exit 4 (site YAML missing) when no ENERGY_GO_BACKEND_PORT set; "
            f"got {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}"
        )

    @skip_on_windows
    def test_env_var_9001_uses_9001_not_default(self, tmp_path):
        """ENERGY_GO_BACKEND_PORT=9001 → BACKEND_PORT=9001 → passes validation.

        Port 9001 is valid; script proceeds past port validation to site YAML check
        → exit 4.  The environment variable was read and used.
        """
        _make_fake_venv(tmp_path)
        result = _run_sh(
            ["--server-type", "dev"],
            cwd=tmp_path,
            extra_env={"ENERGY_GO_BACKEND_PORT": "9001"},
        )
        # Port 9001 valid → reaches site YAML check → exit 4
        assert result.returncode == 4, (
            f"Expected exit 4 (site YAML) for ENERGY_GO_BACKEND_PORT=9001; "
            f"got {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}\n"
            f"(If exit 1, port validation rejected 9001 — env var may not be read correctly.)"
        )

    @skip_on_windows
    def test_cli_flag_beats_invalid_env_var(self, tmp_path):
        """--backend-port 8001 overrides ENERGY_GO_BACKEND_PORT=abc (priority §2).

        CLI flag (8001) takes precedence over env var (abc).  Port 8001 is valid,
        so validation passes → reaches site YAML check → exit 4.
        """
        _make_fake_venv(tmp_path)
        result = _run_sh(
            ["--server-type", "dev", "--backend-port", "8001"],
            cwd=tmp_path,
            extra_env={"ENERGY_GO_BACKEND_PORT": "abc"},
        )
        # CLI flag 8001 wins over env var abc → validation passes → site YAML → exit 4
        assert result.returncode == 4, (
            f"Expected exit 4 (CLI flag 8001 overrides env abc); "
            f"got {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}"
        )

    @skip_on_windows
    def test_cli_flag_beats_out_of_range_env_var(self, tmp_path):
        """--backend-port 8001 overrides ENERGY_GO_BACKEND_PORT=99999 (priority §2).

        CLI flag (8001) is valid; env var (99999) would fail validation alone.
        This confirms CLI flag has highest priority.
        """
        _make_fake_venv(tmp_path)
        result = _run_sh(
            ["--server-type", "dev", "--backend-port", "8001"],
            cwd=tmp_path,
            extra_env={"ENERGY_GO_BACKEND_PORT": "99999"},
        )
        assert result.returncode == 4, (
            f"Expected exit 4 (CLI flag 8001 overrides env 99999); "
            f"got {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}"
        )

    # reviewer: LOWER out-of-range boundary. The existing test exercises 99999 (far
    # above max); 0 pins the bottom edge of the 1–65535 range. validate_port must
    # reject 0 (0 < 1). Same pre/post-fix discriminator as the other shell tests:
    # pre-fix the env var is ignored → BACKEND_PORT=8000 (valid) → exit 4; post-fix
    # BACKEND_PORT=0 → range check fails → exit 1.
    # Hand-computed: 0 matches ^[0-9]+$ but 0 < 1 → out of range → exit 1.
    @skip_on_windows
    def test_zero_env_port_fails_validation(self, tmp_path):
        _make_fake_venv(tmp_path)
        result = _run_sh(
            ["--server-type", "dev"],
            cwd=tmp_path,
            extra_env={"ENERGY_GO_BACKEND_PORT": "0"},
        )
        assert result.returncode == 1, (
            f"Expected exit 1 for ENERGY_GO_BACKEND_PORT=0 (0 < 1, below range); "
            f"got {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}\n"
            f"(If exit 4, the env var was not read — BACKEND_PORT defaulted to 8000.)"
        )
        assert "out of range" in result.stderr.lower() or "65535" in result.stderr, (
            f"Expected range-error message in stderr; got: {result.stderr!r}"
        )

    # reviewer: TIGHT upper boundary. 99999 is far over; 65536 is exactly one past the
    # max valid port and must still be rejected — this catches an off-by-one in the
    # range guard (e.g. `-le 65536` or `-lt 65535` instead of `-le 65535`/`-gt 65535`).
    # Hand-computed: 65536 = 65535 + 1 → out of range → exit 1.
    @skip_on_windows
    def test_port_65536_env_fails_validation(self, tmp_path):
        _make_fake_venv(tmp_path)
        result = _run_sh(
            ["--server-type", "dev"],
            cwd=tmp_path,
            extra_env={"ENERGY_GO_BACKEND_PORT": "65536"},
        )
        assert result.returncode == 1, (
            f"Expected exit 1 for ENERGY_GO_BACKEND_PORT=65536 (65535 + 1, just over "
            f"max); got {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}"
        )
        assert "out of range" in result.stderr.lower() or "65535" in result.stderr, (
            f"Expected range-error message in stderr; got: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# §3 — run_app.ps1: ENERGY_GO_BACKEND_PORT env-var resolution
# ---------------------------------------------------------------------------

class TestRunAppPs1EnvPort:
    """run_app.ps1 reads ENERGY_GO_BACKEND_PORT as the port default (contract §2)."""

    @skip_on_non_windows
    def test_invalid_env_port_fails_validation(self, tmp_path):
        """ENERGY_GO_BACKEND_PORT=abc → error exit (port validation fails)."""
        _make_fake_venv(tmp_path)
        result = _run_ps1(
            ["-ServerType", "dev"],
            cwd=tmp_path,
            extra_env={"ENERGY_GO_BACKEND_PORT": "abc"},
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit for ENERGY_GO_BACKEND_PORT=abc; got 0.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )

    @skip_on_non_windows
    def test_out_of_range_env_port_fails_validation(self, tmp_path):
        """ENERGY_GO_BACKEND_PORT=99999 → error exit (99999 > 65535)."""
        _make_fake_venv(tmp_path)
        result = _run_ps1(
            ["-ServerType", "dev"],
            cwd=tmp_path,
            extra_env={"ENERGY_GO_BACKEND_PORT": "99999"},
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit for ENERGY_GO_BACKEND_PORT=99999; got 0.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )

    @skip_on_non_windows
    def test_absent_env_var_proceeds_past_port_validation(self, tmp_path):
        """No ENERGY_GO_BACKEND_PORT → port 8000 used, validation passes."""
        _make_fake_venv(tmp_path)
        env = {k: v for k, v in os.environ.items() if k != "ENERGY_GO_BACKEND_PORT"}
        result = subprocess.run(
            ["pwsh", "-NonInteractive", "-File", str(RUN_PS1), "-ServerType", "dev"],
            capture_output=True, text=True, cwd=tmp_path, env=env,
        )
        # On Windows, script errors past port validation (site YAML, etc.) — just not exit 1
        # from port validation.  Exact exit code depends on next failing check.
        # We only assert it's not the "invalid port" error.
        assert "not an integer" not in result.stderr.lower(), (
            f"Unexpected port validation error with no env var set.\nstderr: {result.stderr!r}"
        )
