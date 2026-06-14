# arm64 JAX venv — local test setup for Apple Silicon Macs

**Problem (task #11):** The project `.venv` is an x86_64 (Rosetta) venv on Apple Silicon
Macs. The jaxlib wheels for x86_64 require AVX2 instructions that Rosetta 2 does not
support → `import jax` fails with `RuntimeError: This version of jaxlib was built using
AVX instructions`. This forced all agents to push to CI (38-min wait) just to run any
JAX-touching test.

**Solution:** A separate `~/powersim-venv-arm64` venv using native arm64 CPython 3.11 with
arm64 jaxlib wheels (uses ARM NEON/XLA, no AVX). The existing `.venv` is not touched — the
arm64 venv is an opt-in for local development only.

---

## One-time setup

Run these commands from your normal terminal (the shell does not need to be arm64; all
commands explicitly use `arch -arm64`):

```bash
# 1. Install arm64 uv (separate from any x86_64 uv in /usr/local/bin)
arch -arm64 /bin/bash -c '
  export UV_INSTALL_DIR="$HOME/.uv-arm64/bin"
  mkdir -p "$UV_INSTALL_DIR"
  UV_NO_MODIFY_PATH=1 curl -LsSf https://astral.sh/uv/install.sh | sh
'

# 2. Verify the new uv binary is arm64
file ~/.uv-arm64/bin/uv
# Expected: Mach-O 64-bit executable arm64

# 3. Check that arm64 Python 3.11 is available (uv usually has it cached already)
arch -arm64 ~/.uv-arm64/bin/uv python list | grep "aarch64"
# Expected: cpython-3.11.x-macos-aarch64-none at ~/.local/share/uv/python/...
# If not shown as installed: arch -arm64 ~/.uv-arm64/bin/uv python install 3.11

# 4. Create the arm64 venv outside OneDrive (avoids sync overhead)
arch -arm64 ~/.uv-arm64/bin/uv venv ~/powersim-venv-arm64 \
  --python ~/.local/share/uv/python/cpython-3.11-macos-aarch64-none/bin/python3.11

# Confirm arm64
file ~/powersim-venv-arm64/bin/python3
# Expected: Mach-O 64-bit executable arm64

# 5. Install project (no-deps first to avoid sbx-rl etc.)
REPO=/Users/yangli/Library/CloudStorage/OneDrive-Personal/PowerSim
arch -arm64 ~/.uv-arm64/bin/uv pip install --python ~/powersim-venv-arm64/bin/python3 \
  --no-deps -e "$REPO"

# 6. Install all CI-mirrored deps (matches .github/workflows/ci.yml Python-tests step)
arch -arm64 ~/.uv-arm64/bin/uv pip install --python ~/powersim-venv-arm64/bin/python3 \
  "pytest>=8.0" "pytest-asyncio>=0.23" "anyio>=4.0" "pytest-xdist>=3.5" \
  "fastapi>=0.110" "httpx>=0.27" "starlette>=0.36" \
  "pyyaml>=6.0" "numpy>=1.26" "websockets>=12" "uvicorn[standard]>=0.29" \
  "jsonschema>=4.21" \
  "jax[cpu]>=0.4.25" "flax>=0.8.0" "optax>=0.2.0" "flashbax>=0.1.0"

# 7. Verify import jax works
arch -arm64 ~/powersim-venv-arm64/bin/python3 -c "
import jax
import jax.numpy as jnp
print('jax version:', jax.__version__)
print('devices:', jax.devices())
print('SUCCESS')
"
```

---

## Running tests locally

```bash
# Run a serving test suite (3-4s vs 38-min CI wait):
arch -arm64 ~/powersim-venv-arm64/bin/python3 -m pytest \
  tests/serving/ -q -m "not slow"

# Run the full test suite (excluding @pytest.mark.slow — same as CI):
arch -arm64 ~/powersim-venv-arm64/bin/python3 -m pytest \
  tests/ -q -m "not slow"

# Or activate the venv in a native arm64 shell:
arch -arm64 /bin/bash
source ~/powersim-venv-arm64/bin/activate
pytest tests/ -q -m "not slow"
```

---

## Dual-venv approach (current standard)

**Decision (team-lead, 2026-06-14):** Keep the dual-venv setup — do not swap `.venv`.
Rationale: the dual-venv already achieves the goal (local JAX testing via the explicit
`arch -arm64` path), the existing `.venv` is untouched and working for IDEs and non-JAX
work, and swapping risks disrupting agents mid-run. A canonical swap can be done later as
optional cleanup if the dual-path proves annoying.

| | `.venv` | `~/powersim-venv-arm64` |
|---|---|---|
| Architecture | x86_64 (Rosetta) | arm64 (native) |
| Location | `<repo>/.venv` | `~/powersim-venv-arm64` (outside OneDrive) |
| `import jax` | ❌ AVX guard fails | ✅ works (arm64 jaxlib) |
| Used by | IDEs that auto-detect `.venv`; non-JAX tests | JAX-touching tests; local serving/env suites |
| Status | Untouched — do not delete | **Current standard for local JAX testing** |

**Do not delete `.venv`** — IDEs and other agents depend on it.

---

## Optional future: canonical swap to arm64 as default

Not currently planned — the dual-venv is the standard. If the explicit `arch -arm64`
prefix becomes too ergonomically painful, the swap can be done at a quiet moment (no
agents mid-run) by:

```bash
# Requires team-lead approval + a quiet moment (no active test runs)
mv <repo>/.venv <repo>/.venv-x86-backup
arch -arm64 ~/.uv-arm64/bin/uv venv <repo>/.venv \
  --python ~/.local/share/uv/python/cpython-3.11-macos-aarch64-none/bin/python3.11
# Re-install deps (same pip install commands as setup steps 5-6)
# Verify, then: rm -rf <repo>/.venv-x86-backup
```

---

## Updating the arm64 venv

When `pyproject.toml` adds new deps, run the matching `uv pip install` command in the
`arch -arm64` wrapper. If the dep set diverges significantly from CI, prefer adding
`[dev]` extras to `pyproject.toml` so a single `uv pip install -e ".[dev]"` covers
both CI and local setups.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: This version of jaxlib was built using AVX instructions` | Running x86_64 Python (`.venv`) | Use `arch -arm64 ~/powersim-venv-arm64/bin/python3` |
| `arch -arm64 uname -m` returns `x86_64` | Your terminal is running under Rosetta | Open a new terminal with `arch -arm64 /bin/zsh` or use the arm64 prefix on each command |
| `uv: command not found` | The arm64 uv is at `~/.uv-arm64/bin/uv`, not in PATH | Use the full path or add `~/.uv-arm64/bin` to PATH in your arm64 shell |
| `jax.devices()` shows GPU/Metal | Normal on Apple Silicon — jax[cpu] may still use Metal | Set `JAX_PLATFORMS=cpu` env var to force CPU only |
