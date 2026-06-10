## 9. Install & launch scripts (deployment)
> **Owner:** serving-engineer

**Interpretation of the request** (user wording: *"launch scripts that we can install the app on mac or windows based on the server types"*): the rebuild ships **one-command install + launch scripts** for **macOS** and **Windows** that stand up the Energy GO app, and what gets installed/started is selected by a **`--server-type`** flag (the *role* the machine plays). This section specifies the contract those scripts satisfy; the implementation is a separate task. Linux is out of scope for v1 of this section (CI runs on Linux but uses `pyproject` extras directly, not these scripts).

### 9.1 Files (per `scripts/<verb>_<object>` convention)

| Script | OS | Role |
|---|---|---|
| `scripts/install_app.sh` | macOS (bash/zsh) | install dependencies for the chosen server type, then optionally launch |
| `scripts/install_app.ps1` | Windows (PowerShell 5.1+/7) | same, Windows-native |
| `scripts/run_app.sh` | macOS | launch an already-installed server type (no dependency work) |
| `scripts/run_app.ps1` | Windows | same, Windows-native |

`install_app` is **idempotent install (+ optional launch)**; `run_app` is **launch-only** and assumes a prior install. The two `.sh`/`.ps1` pairs are behavioural mirrors — same flags, same server-type taxonomy, same exit codes — differing only in platform mechanics (Homebrew/`uv` vs winget/`uv`; `venv/bin` vs `venv\Scripts`; SIGTERM vs `Stop-Process`).

### 9.2 Server types (`--server-type`)

The role selects which dependency groups install and which processes launch. Maps 1:1 to `pyproject` optional-dependency extras and to STACK.md areas.

| `--server-type` | Installs | Launches | Default accelerator |
|---|---|---|---|
| `dev` | full stack: JAX core, training (sbx/purejaxrl, optax, flax), serving (FastAPI), frontend (Node + Vite) | FastAPI backend (reload) + Vite dev server (HMR) | `gpu` if detected, else `cpu` |
| `training` | JAX core + training + eval + baselines; **no** Node/frontend | training/eval harness entrypoint (no web) | `gpu` if detected, else `cpu` |
| `serving` | JAX core (inference only) + FastAPI + exported policy runtime (ONNX or raw-MLP weights, §7 §5); **built** frontend static assets; **no** training deps | FastAPI backend serving the locked telemetry stream + static frontend bundle | `cpu` |
| `full` | union of `training` + `serving` (one box trains and serves) | training harness + FastAPI + built frontend | `gpu` if detected, else `cpu` |

- **Accelerator is orthogonal:** `--accel cpu|gpu` overrides the default and selects the **jaxlib** variant (CPU wheel vs CUDA/Metal wheel). The script must verify the toolchain (CUDA on Windows/Linux GPU boxes; on macOS, GPU = Metal via `jax-metal`, best-effort with a CPU fallback warning) and fail loudly with a remediation hint rather than silently installing the CPU wheel on a GPU box.
- The `serving` type never pulls training-only deps — this keeps the production serving image minimal (aligns with §7 "Go *would* make sense" optional path; the Python serving layer is the v1 default).

### 9.3 What `install_app` does (ordered)

1. **Preflight:** detect OS + arch (Apple Silicon vs Intel; Windows x64), check/install the base toolchain — Python (pinned in STACK.md) via `uv` (preferred) or `pyenv`/winget; **Node LTS** only for `dev`/`serving`/`full`. Refuse unsupported OS/arch with a clear message.
2. **Python env:** create a project-local virtualenv (`.venv/`), never touch system Python.
3. **Dependencies:** install the `pyproject` extras group for the server type; install the jaxlib variant per `--accel`.
4. **Config selection:** `--site <path>` (default `config/site_gansu.yaml`); validate it loads. Resolve checkpoint to serve via `--checkpoint <id|path>` for `serving`/`full` (error if absent and no default).
5. **Frontend (dev/serving/full):** `npm ci` then — `dev` leaves source for HMR; `serving`/`full` run `npm run build` to produce the static bundle the backend serves.
6. **Launch (unless `--no-launch`):** start the processes for the server type (§9.2), wire ports (`--backend-port`, default 8000; `--frontend-port`, default 5173), write a PID/run file under `.run/` so `run_app`/`--uninstall` can find them, and print the URLs.

`run_app` performs only steps 4 (config resolve) + 6 (launch), erroring if `.venv/`/build artifacts are missing ("run install_app first").

### 9.4 Idempotency, uninstall, errors

- **Idempotent:** re-running `install_app` with the same args detects an up-to-date `.venv`/lockfile/build and is a near-no-op; a changed lockfile triggers an upgrade. Never destructive to user-edited `config/` files.
- **`--uninstall`:** stops running services (via the `.run/` PID file), removes `.venv/`, frontend `node_modules/` + build output, and `.run/`. Leaves `config/` and checkpoints unless `--purge` is also given (which additionally clears local checkpoints/run artifacts). Prints exactly what it removed.
- **Errors:** every failure exits non-zero with a one-line cause + remediation. No partial silent success. Re-running after a fixed error resumes cleanly (idempotency).
- **No secrets in scripts:** any API keys (e.g. the §6 LLM analysis service, if enabled) come from environment/`.env`, never baked in.

### 9.5 Acceptance criteria (for the implementation task)

- `bash scripts/install_app.sh --server-type serving --accel cpu --no-launch` on macOS and `pwsh scripts/install_app.ps1 -ServerType serving -Accel cpu -NoLaunch` on Windows both complete green from a clean checkout, producing a `.venv` with serving (not training) deps and a built frontend bundle.
- `--server-type training --no-launch` installs training deps and **no** Node/frontend.
- Re-running the same command is idempotent (second run makes no dependency changes; exit 0).
- `run_app` launches a previously-installed `serving` box and the FastAPI health endpoint responds; killing via `--uninstall` stops it and removes `.venv`/build, leaving `config/` intact.
- An invalid `--server-type` / `--accel`, a GPU `--accel gpu` on a box with no detected accelerator, or a missing `--checkpoint` for `serving` each exit non-zero with a remediation message.
- The `.sh` and `.ps1` variants accept the same flag set and select the same server-type behaviour (cross-platform parity test, documented in the implementation's contract).
- All dependency versions/pins come from `pyproject` + STACK.md; the scripts hardcode no version not also recorded there.

---

