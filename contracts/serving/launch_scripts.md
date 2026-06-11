# Contract: Install & Launch Scripts (serving)

- **Status:** draft — awaiting backend-reviewer gate
- **Spec:** REBUILD_SPEC.md §9 (§9.1–§9.5 inclusive)
- **Owner:** serving-engineer · **Reviewer:** backend-reviewer

---

## 1. Files produced

| File | OS | Purpose |
|---|---|---|
| `scripts/install_app.sh` | macOS (bash ≥ 3.2, runs under zsh) | Install deps for chosen server type; optionally launch |
| `scripts/install_app.ps1` | Windows (PowerShell 5.1+ or pwsh 7+) | Same, Windows-native |
| `scripts/run_app.sh` | macOS | Launch-only (assumes prior install) |
| `scripts/run_app.ps1` | Windows | Launch-only |

These four files implement §9.1. File naming follows `scripts/<verb>_<object>` convention.

`pyproject.toml` is also modified to add the extras groups referenced by `--server-type` (§9.2 requires they exist).

---

## 2. CLI interface

### `install_app.sh` / `install_app.ps1`

```
install_app.sh --server-type <TYPE> [--accel <ACCEL>] [--site <PATH>]
               [--checkpoint <ID_OR_PATH>] [--backend-port <PORT>]
               [--frontend-port <PORT>] [--no-launch] [--uninstall [--purge]]

install_app.ps1 -ServerType <TYPE> [-Accel <ACCEL>] [-Site <PATH>]
                [-Checkpoint <ID_OR_PATH>] [-BackendPort <PORT>]
                [-FrontendPort <PORT>] [-NoLaunch] [-Uninstall] [-Purge]
```

### `run_app.sh` / `run_app.ps1`

```
run_app.sh --server-type <TYPE> [--accel <ACCEL>] [--site <PATH>]
           [--checkpoint <ID_OR_PATH>] [--backend-port <PORT>]
           [--frontend-port <PORT>]

run_app.ps1 -ServerType <TYPE> [-Accel <ACCEL>] [-Site <PATH>]
            [-Checkpoint <ID_OR_PATH>] [-BackendPort <PORT>]
            [-FrontendPort <PORT>]
```

`run_app` performs only steps 4 + 6 of §9.3 (config resolve + launch). It errors if `.venv/` is absent.

---

## 3. Flag definitions

| Flag (.sh / .ps1) | Required? | Valid values | Default |
|---|---|---|---|
| `--server-type` / `-ServerType` | **Yes** | `dev`, `training`, `serving`, `full` | — (error if absent) |
| `--accel` / `-Accel` | No | `cpu`, `gpu` | `gpu` if accelerator detected, else `cpu` (auto-detect per §9.2) |
| `--site` / `-Site` | No | path to YAML config | `config/site_gansu.yaml` |
| `--checkpoint` / `-Checkpoint` | Conditional | checkpoint ID or path | required for `serving`/`full` (error if absent, no default) |
| `--backend-port` / `-BackendPort` | No | integer 1–65535 | `8000` |
| `--frontend-port` / `-FrontendPort` | No | integer 1–65535 | `5173` |
| `--no-launch` / `-NoLaunch` | No | flag (no value) | off |
| `--uninstall` / `-Uninstall` | No | flag (no value) | off |
| `--purge` / `-Purge` | No | flag; only meaningful with `--uninstall` | off |

Cross-platform parity: every flag available in `.sh` is available in `.ps1` with the same semantics. The two pairs are behavioural mirrors.

---

## 4. Server-type → extras + process mapping

Maps directly to §9.2.

| `--server-type` | `pyproject` extras groups installed | Processes launched (unless `--no-launch`) | Default `--accel` |
|---|---|---|---|
| `dev` | `jax-cpu` or `jax-gpu-cuda`/`jax-gpu-metal` (OS-selected), `training`, `serving`, `frontend-dev` | FastAPI (`--reload`) + Vite dev server | auto-detect: `gpu` if found, else `cpu` |
| `training` | `jax-cpu` or `jax-gpu-cuda`/`jax-gpu-metal` (OS-selected), `training` | training/eval harness entrypoint | auto-detect |
| `serving` | `jax-cpu`, `serving` | FastAPI serving locked telemetry stream + static bundle | `cpu` (always; even if GPU present, §9.2) |
| `full` | `jax-cpu` or `jax-gpu-cuda`/`jax-gpu-metal` (OS-selected), `training`, `serving` | training harness + FastAPI + built frontend | auto-detect |

`serving` type: never installs training-only deps (`optax`, `flax`, `sbx`, `purejaxrl`). This keeps the serving image minimal per §9.2.

### 4.1 `pyproject` extras groups (new in this task)

These groups are added to `pyproject.toml` under `[project.optional-dependencies]`:

| Group | Contents |
|---|---|
| `jax-cpu` | `jax[cpu]>=0.4.25` (installs both the `jax` core package and the CPU `jaxlib` wheel in one extra) |
| `jax-gpu-cuda` | `jax[cuda12]>=0.4.25` (Windows/Linux CUDA 12; installs `jax` core + CUDA jaxlib wheel) |
| `jax-gpu-metal` | `jax>=0.4.25`, `jax-metal>=0.0.5` (macOS Apple Silicon Metal backend) |
| `training` | `optax>=0.2`, `flax>=0.8`, `orbax-checkpoint>=0.5`, `sbx>=0.14` (or `purejaxrl` pinned ref), `numpy>=1.26`, `scipy>=1.12` |
| `serving` | `fastapi>=0.110`, `uvicorn[standard]>=0.29`, `websockets>=12`, `onnxruntime>=1.17`, `pyyaml>=6.0`, `numpy>=1.26` |
| `frontend-dev` | sentinel (lists Node requirement; script installs Node via Homebrew/winget, not pip) |
| `dev` | `pytest>=8.0`, `pytest-xdist>=3.5`, `pytest-asyncio>=0.23`, `httpx>=0.27` (all of `training` + `serving` + `frontend-dev` + test tools) |

**JAX extras design note (B3 / reviewer non-blocking):** A single `jax-gpu` group cannot resolve per-OS without PEP 508 environment markers (`platform_system=='Darwin' and platform_machine=='arm64'`). Rather than add markers (which only work for pip, not `uv sync`), the contract splits into `jax-gpu-cuda` (Windows/Linux) and `jax-gpu-metal` (macOS ARM). The install scripts select the correct group via OS/arch detection at runtime. The original `jax-gpu` name is not used; tests reference `jax-gpu-cuda` and `jax-gpu-metal`.

All version pins must be consistent with STACK.md (task #19 owns that file; the versions here are floor pins from §9.5 and the standard ecosystem).

---

## 5. `install_app` ordered steps (§9.3)

1. **Preflight:** detect OS/arch; check/install Python (via `uv` preferred, `pyenv` fallback on macOS, winget fallback on Windows); install Node LTS only for `dev`/`serving`/`full`.
   - Unsupported OS (not macOS or Windows): `exit 2` with message `"ERROR [2]: Unsupported OS: <name>. Remediation: Supported OSes are macOS and Windows."`.
   - Unsupported arch: `exit 2` with `"ERROR [2]: Unsupported arch: <name>. Remediation: Supported architectures are x86_64 and arm64."`.
   - Toolchain install failure: `exit 2` with a message naming the tool and the remediation step.
2. **Python env:** create `.venv/` in the project root via `uv venv` (or `python -m venv`). Idempotent: skip if `.venv/` already exists and Python version matches.
3. **Dependency install:** `uv pip install -e ".[<extras>]"` with extras determined by server-type + accel (§4 above). Idempotent: up-to-date lock means no-op.
4. **Config resolve:** validate `--site` YAML loads (Python `yaml.safe_load`). For `serving`/`full`: resolve `--checkpoint`; error with `"--checkpoint required for server-type <X>"` if absent and no default found at `.run/last_checkpoint`.
5. **Frontend (dev/serving/full):** `npm ci` in the project root. `serving`/`full`: also run `npm run build`. `dev` leaves source for HMR.
6. **Launch:** start processes for the server type; write PIDs to `.run/pids.json` keyed by role (`api`, `training`, `frontend`); print URLs (`http://localhost:<backend-port>` and `http://localhost:<frontend-port>` where applicable). Unless `--no-launch`.

---

## 6. `run_app` steps

1. Check `.venv/` exists; error `"No virtualenv found. Run install_app first."` if absent.
2. Resolve config (same as install step 4).
3. Launch (same as install step 6).

---

## 7. Accelerator detection and fail-loud rule

- **Auto-detect (macOS):** run `python -c "import jax; jax.devices('gpu')"` in the venv; success → GPU (Metal) available, else CPU.
- **Auto-detect (Windows/Linux):** check for `nvidia-smi` in PATH; success → CUDA GPU present.
- **`--accel gpu` on a box with no detected GPU:** `exit 6` with message `"ERROR [6]: GPU accelerator requested but no GPU detected. Remediation: Use --accel cpu or install CUDA/Metal drivers. See STACK.md."`.
- **`--accel cpu` on any box:** always succeeds.
- `serving` type always uses `cpu` regardless of `--accel`; a `--accel gpu` combined with `--server-type serving` prints a warning `"Note: serving type always uses CPU accelerator; --accel gpu ignored."` and continues.

---

## 8. Idempotency

- Re-running `install_app` with identical args: checks hash of installed packages via `uv pip freeze` vs. extras group; no changes → exits 0 with message `"Environment up to date. Nothing to do."`.
- Changed lockfile or extras: upgrades/installs only the delta.
- Never deletes `config/` files or user-created checkpoints unless `--purge` is passed.
- `.venv/` created with `--copies` (not symlinks) to survive Python minor version updates.

---

## 9. Uninstall semantics

`--uninstall` (must be combined with `--server-type` to know which pids to stop):
1. Read `.run/pids.json`; send SIGTERM (macOS) / `Stop-Process` (Windows) to each PID; wait up to 5 s; SIGKILL / `Stop-Process -Force` if still alive.
2. Remove `.venv/`, `node_modules/`, `dist/` (or the configured build output dir).
3. Remove `.run/`.
4. Print a summary of removed paths.
5. Exit 0. If a PID is stale (process already gone), log a warning and continue.

`--purge` (only with `--uninstall`): additionally removes `checkpoints/` and any `*.run` artifact files under the project root. `config/` is NEVER removed.

---

## 10. Exit codes

| Code | Meaning |
|---|---|
| `0` | Success (install/launch OK, or already up-to-date, or uninstall complete) |
| `1` | Invalid argument (unknown `--server-type`, `--accel`, bad port, etc.) |
| `2` | Preflight failure (unsupported OS/arch, toolchain install failed) |
| `3` | Dependency install failure |
| `4` | Config/checkpoint error (YAML invalid, missing `--checkpoint`) |
| `5` | Launch failure (port in use, process failed to start) |
| `6` | GPU requested, no GPU detected |

Every non-zero exit prints exactly one line: `"ERROR [<exit-code>]: <cause>. Remediation: <hint>."`.

---

## 11. State files

`.run/` directory (created by install/run, removed by uninstall):

```
.run/
  pids.json         # {"api": 12345, "training": 12346, "frontend": 12347}
  last_checkpoint   # plain-text path/ID of the last checkpoint used for serving
  server_type       # plain-text current server type (for run_app to validate)
```

These are machine-local; never committed to git (`.run/` is in `.gitignore`).

---

## 12. Out of scope

- Linux support (§9 explicitly: "Linux is out of scope for v1 of this section").
- Docker / container packaging.
- TLS / HTTPS setup.
- Automated checkpoint export from a training run (§5/§7 task scope, not scripts).
- Any API keys baked into scripts (§9.4 "No secrets in scripts").
- Version management for Node (scripts require Node LTS already available or install via Homebrew/winget).

---

## 13. Spec sections implemented

- §9.1 (file list), §9.2 (server types + accelerator), §9.3 (install steps), §9.4 (idempotency, uninstall, errors), §9.5 (acceptance criteria).
- Also modifies `pyproject.toml` to add the extras groups referenced in §9.2 (prerequisite for scripts to function).

---

## 14. Deliberate deviations

- `serving` + `--accel gpu`: spec says `serving` default is `cpu` (§9.2). This contract makes it a warning + continue (not an error) when the user explicitly passes `--accel gpu` with `--server-type serving`, since the serving image is CPU-only regardless. The user is informed but not blocked.
- Exit code table (§10): the spec does not enumerate exit codes beyond "exit non-zero". This contract assigns specific codes (1–6) so tests can assert them precisely. No behavioral change from the spec's perspective.
- `jax-gpu` split into `jax-gpu-cuda` + `jax-gpu-metal`: the spec references a single `jax-gpu` group but a single group cannot resolve per-OS without PEP 508 markers (incompatible with `uv sync`). Splitting is a structural choice that has no user-visible effect — scripts select the right group automatically.
- Exit code for unsupported OS/arch is `2` (preflight), not `1` (bad argument): OS/arch failures are distinguished from flag-parse errors so remediation messages can be more specific. §10 table is the normative definition.
