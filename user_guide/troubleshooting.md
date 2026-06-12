# Troubleshooting

The install/launch scripts exit non-zero with a one-line cause **and** a remediation hint on every failure (see [exit codes](installation.md#exit-codes)). The common cases below quote the scripts' actual messages.

## Port already in use (exit 5)

```
ERROR [5]: Backend port 8000 is already in use. Remediation: Use --backend-port <other-port> or stop the existing process.
```

Pick another port (the flag beats the env var beats the default):

```bash
bash scripts/run_app.sh --server-type serving --checkpoint <id> --backend-port 9001
# or:
ENERGY_GO_BACKEND_PORT=9001 bash scripts/run_app.sh --server-type serving --checkpoint <id>
```

The script checks ports **before** the expensive install step, so a busy port fails fast rather than after a long dependency install.

## Python / `uv` toolchain (exit 2 or 3)

The scripts use [`uv`](https://docs.astral.sh/uv/) to manage a project-local `.venv` with **Python ≥ 3.11** (never your system Python). If `uv` isn't found, the script tries to install it via `curl`; if that's unavailable:

```
ERROR [2]: uv and curl not found. Remediation: Install uv: https://docs.astral.sh/uv/getting-started/installation/
```

Install `uv` manually, then re-run — the install is idempotent and resumes cleanly.

## Apple Silicon / Rosetta (exit 2)

On Apple-Silicon Macs, JAX must use **native arm64** wheels. An x86_64 Python (e.g. one picked under Rosetta) pulls AVX-using `jaxlib` wheels that crash on import (Rosetta 2 doesn't translate AVX). The script detects this and stops:

```
ERROR [2]: ARM host but venv Python is x86_64 (Rosetta or x86_64-only uv). ...
Remediation: Reinstall uv as a native arm64 binary —
'curl -LsSf https://astral.sh/uv/install.sh | arch -arm64 sh' — then re-run this script.
```

It also re-checks after install that `import jax` actually works on Apple Silicon, failing with the same remediation if an x86_64 wheel slipped through. Follow the hint (reinstall `uv` as native arm64), then re-run.

## GPU requested but not detected (exit 6)

```
ERROR [6]: GPU accelerator requested but no GPU detected. Remediation: Use --accel cpu or install CUDA/Metal drivers. See STACK.md.
```

Either install the GPU toolchain (CUDA on NVIDIA boxes; Metal on macOS) or use `--accel cpu`. Note that `serving` always runs on CPU regardless of `--accel`.

## Missing checkpoint for serving (exit 4)

`serving` and `full` need a policy checkpoint:

```
ERROR [4]: --checkpoint is required for --server-type serving and no .run/last_checkpoint found. Remediation: Pass --checkpoint <id-or-path> or create .run/last_checkpoint with a checkpoint path.
```

Pass `--checkpoint <id-or-path>`. A previously-launched box records its checkpoint in `.run/last_checkpoint`, which is reused automatically if you omit the flag.

## Site config not found (exit 4)

```
ERROR [4]: Site YAML not found: 'config/site_gansu.yaml'. Remediation: Pass --site <path> or create config/site_gansu.yaml.
```

The default `config/site_gansu.yaml` is in the repository. This error usually means you are running the script from a directory other than the repository root, or you accidentally deleted the file. Run from the repo root, or pass `--site <path>` pointing to an existing site YAML.

## "Run install_app first" (run_app, exit 1)

```
ERROR: No virtualenv found at <dir>/.venv.
Remediation: Run install_app.sh --server-type serving first to install the environment.
```

`run_app` is launch-only — run `install_app` once first to create the `.venv` and (for `serving`/`full`) build the frontend.

## Dashboard stuck on "Waiting for live data…"

The dashboard shows live data only while an [inference session](sessions.md) is streaming, which needs a **policy loaded** on the backend. Check the backend:

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"1.0.0","policy_loaded":false,"run_id":null}
```

If `policy_loaded` is `false`, (re)launch a `serving`/`full` box with a valid `--checkpoint`. If the backend is on a non-default port, point your check at that port.

## Frontend can't reach the backend

The Vite dev server proxies `/api` and `/ws` to the backend, reading the backend port from `ENERGY_GO_BACKEND_PORT` (default 8000) at startup. If you launched the backend on a custom port, start the frontend with the **same** `ENERGY_GO_BACKEND_PORT` so the proxy targets it.
