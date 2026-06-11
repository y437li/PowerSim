# Contract: Backend Port Configuration

- **Status:** DRAFT
- **Area:** serving
- **Spec:** REBUILD_SPEC.md §9.3 (install/launch); `contracts/frontend/configurable_ports.md` (companion, merged PR #55)
- **Reviewer:** backend-reviewer (APPROVE gate)
- **Amends:** `contracts/serving/launch_scripts.md` §6 (`run_app.sh` / `run_app.ps1` default resolution order)

## Purpose

The `ENERGY_GO_BACKEND_PORT` env var (defined in `contracts/frontend/configurable_ports.md`,
default `8000`) lets developers run two Energy GO instances simultaneously without port
collisions.  The frontend already reads this var at Vite startup (PR #55).  This contract
pins the **backend/serving** side: `app.py` programmatic launch and the launch scripts
must both honour the same env var so the two halves stay in sync without extra flags.

## Scope

Two changes only:

1. **`src/energy_go/serving/app.py`** — add a `__main__` block that reads
   `ENERGY_GO_BACKEND_PORT` and launches uvicorn programmatically:

   ```python
   if __name__ == "__main__":
       import os
       import uvicorn
       port = int(os.environ.get("ENERGY_GO_BACKEND_PORT", "8000"))
       uvicorn.run("energy_go.serving.app:app", host="0.0.0.0", port=port, reload=False)
   ```

   - `ENERGY_GO_BACKEND_PORT` is parsed as a decimal integer.
   - Non-integer values raise `ValueError` (stdlib `int()` semantics; not silently ignored).
   - Values outside 1–65535 are **not** further validated here (OS will reject them at
     `bind()`); the launch scripts validate the range explicitly.
   - Default `8000` when the var is absent or empty string.

2. **`scripts/run_app.sh`** and **`scripts/run_app.ps1`** (PR #10 / `contracts/serving/launch_scripts.md`)
   — change the hard-coded `BACKEND_PORT=8000` / `$BackendPort = 8000` default to read the
   env var first:

   **Bash (`run_app.sh`):**
   ```bash
   BACKEND_PORT="${ENERGY_GO_BACKEND_PORT:-8000}"
   ```

   **PowerShell (`run_app.ps1`):**
   ```powershell
   $BackendPort = if ($env:ENERGY_GO_BACKEND_PORT) { [int]$env:ENERGY_GO_BACKEND_PORT } else { 8000 }
   ```

   Priority (highest wins):
   1. Explicit `--backend-port` / `-BackendPort` flag on the command line
   2. `ENERGY_GO_BACKEND_PORT` environment variable
   3. Hard-coded default `8000`

   The existing range validation (`1–65535`) applies regardless of source.

## `app.py` docstring update

The module docstring must be updated from:
```
uvicorn energy_go.serving.app:app --host 0.0.0.0 --port 8000
```
to:
```
# Programmatic launch (honours ENERGY_GO_BACKEND_PORT, default 8000):
python -m energy_go.serving.app

# Manual uvicorn launch:
ENERGY_GO_BACKEND_PORT=9000 uvicorn energy_go.serving.app:app --host 0.0.0.0 --port 9000
```

## Out of scope

- SSL / TLS configuration.
- Host binding other than `0.0.0.0`.
- Reload mode in production (the `--reload` flag is only for `dev` server-type in
  `run_app.sh`; `__main__` launches without reload).
- `ENERGY_GO_FRONTEND_PORT` (frontend-only; not read by the serving process).

## Dependencies

- `contracts/frontend/configurable_ports.md` — defines `ENERGY_GO_BACKEND_PORT`.
- `contracts/serving/launch_scripts.md` (PR #10) — defines `run_app.sh` / `run_app.ps1`.
