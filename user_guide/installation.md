# Installation & launch

Energy GO ships one-command install + launch scripts for **macOS** and **Windows**. What gets installed and started is chosen by a `--server-type` flag (the role the machine plays). Run the scripts from the **repository root**.

- `scripts/install_app.sh` (macOS) / `scripts/install_app.ps1` (Windows) — idempotent dependency install, then optional launch.
- `scripts/run_app.sh` / `scripts/run_app.ps1` — launch an **already-installed** server type (no dependency work).

The `.sh` and `.ps1` variants are behavioural mirrors: same flags, same server types, same exit codes. Linux is best-effort only (the script warns and continues). Spec: [`docs/spec/section_09_install_launch_scripts.md`](../docs/spec/section_09_install_launch_scripts.md); contract: `contracts/serving/launch_scripts.md`.

## Server types

| `--server-type` | Installs | Launches |
|---|---|---|
| `dev` | full stack: JAX, training, serving, frontend | FastAPI backend (auto-reload) + Vite dev server (HMR) |
| `training` | JAX + training/eval/baselines; **no** Node/frontend | training harness (no web) |
| `serving` | JAX **CPU** (inference only) + FastAPI + **built** frontend bundle; **no** training deps | FastAPI serving the telemetry stream + static frontend |
| `full` | union of `training` + `serving` | training harness + FastAPI + built frontend |

## Quick start

### Developer box (macOS)

```bash
bash scripts/install_app.sh --server-type dev
# → FastAPI on http://localhost:8000  and  Vite dev server on http://localhost:5173
# Open the frontend URL in a browser.
```

### Serving box (macOS)

```bash
# Install (CPU) + build the frontend, without launching:
bash scripts/install_app.sh --server-type serving --accel cpu --checkpoint <id-or-path> --no-launch
# Launch later:
bash scripts/run_app.sh --server-type serving --checkpoint <id-or-path>
# → FastAPI on http://localhost:8000 ; GET /health returns {"status":"ok",...}
```

### Windows (PowerShell)

```powershell
pwsh scripts/install_app.ps1 -ServerType serving -Accel cpu -Checkpoint <id-or-path> -NoLaunch
pwsh scripts/run_app.ps1 -ServerType serving -Checkpoint <id-or-path>
```

## Accelerator (`--accel`)

`--accel cpu|gpu` selects the **jaxlib** variant and is orthogonal to the server type:

- Default: auto-detect a GPU (NVIDIA via `nvidia-smi`, or Apple Metal) and fall back to CPU.
- `gpu` on a box with no detected accelerator **fails loudly** (exit code 6) rather than silently installing the CPU wheel.
- `serving` always uses CPU (a `--accel gpu` on `serving` is ignored with a warning).
- On Apple Silicon the GPU variant uses `jax-metal` (best-effort, with a CPU-fallback warning).

## Ports

Two ports, both configurable. Resolution order is **flag → environment variable → default**.

| | Flag | Env var | Default |
|---|---|---|---|
| Backend (FastAPI) | `--backend-port` | `ENERGY_GO_BACKEND_PORT` | `8000` |
| Frontend (Vite) | `--frontend-port` | `ENERGY_GO_FRONTEND_PORT` | `5173` |

```bash
# Run the backend on a custom port via env var (honoured by run_app.sh and by
# `python -m energy_go.serving.app`):
ENERGY_GO_BACKEND_PORT=9001 bash scripts/run_app.sh --server-type serving --checkpoint <id>

# …or via the flag (takes precedence over the env var):
bash scripts/run_app.sh --server-type serving --checkpoint <id> --backend-port 9001
```

If a port is already in use the script fails with **exit code 5** and tells you to pass a different `--*-port` or stop the other process.

## All flags

| Flag | Meaning | Default |
|---|---|---|
| `--server-type <dev\|training\|serving\|full>` | Machine role (**required**) | — |
| `--accel <cpu\|gpu>` | jaxlib variant | auto-detect (gpu→cpu) |
| `--site <PATH>` | Site YAML config | `config/site_gansu.yaml` |
| `--checkpoint <ID_OR_PATH>` | Policy checkpoint (**required** for `serving`/`full`) | `.run/last_checkpoint` if present |
| `--backend-port <PORT>` | FastAPI port (1–65535) | `8000` |
| `--frontend-port <PORT>` | Frontend port (1–65535) | `5173` |
| `--no-launch` | Install only; don't start processes | — |
| `--uninstall` | Stop services; remove `.venv`, `node_modules`, `dist`, `.run/` | — |
| `--purge` | With `--uninstall`: also remove `checkpoints/` | — |
| `--help` | Show usage and exit | — |

> **Note on `--site`.** The default `config/site_gansu.yaml` is checked into the repository and describes the Gansu/Jiuquan site (146 turbines × 4.2 MW, 330 MW PV, 294.5 MWh battery; see `contracts/shared/device_model_schema.md`). Pass `--site <path>` if you want to run a different site YAML.

## Idempotency & uninstall

- Re-running `install_app` with the same arguments is a near-no-op (prints `Environment up to date. Nothing to do.`); a changed lockfile triggers an upgrade. It never touches your edited `config/` files.
- `--uninstall` stops running services (via the `.run/pids.json` it wrote at launch) and removes `.venv`, `node_modules`, `dist`, and `.run/`, printing exactly what it removed. Add `--purge` to also clear local checkpoints.

```bash
bash scripts/install_app.sh --server-type dev --uninstall
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (install/launch OK, up-to-date, or uninstall complete) |
| 1 | Invalid argument (unknown server-type/accel, bad port, `--purge` without `--uninstall`, unknown flag) |
| 2 | Preflight failure (unsupported OS/arch, toolchain install failed, ARM/x86 Python mismatch) |
| 3 | Dependency install failure (`uv pip`, `npm ci`, `npm run build`) |
| 4 | Config/checkpoint error (site YAML not found, missing `--checkpoint`) |
| 5 | Launch failure (port in use, process failed to start) |
| 6 | GPU requested (`--accel gpu`) but no GPU detected |

Every non-zero exit prints a one-line cause **and** a remediation hint.
