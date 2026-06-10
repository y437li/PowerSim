#!/usr/bin/env bash
# install_app.sh — install and optionally launch Energy GO by server type.
# Contract:  contracts/serving/launch_scripts.md
# Spec:      REBUILD_SPEC.md §9.1–§9.5
# Exit codes: 0=ok 1=bad-arg 2=preflight 3=dep-install 4=config 5=launch 6=no-gpu
set -uo pipefail

# Work directory is wherever the caller invoked us from (repo root by convention).
WORK_DIR="$(pwd)"

# ── defaults ──────────────────────────────────────────────────────────────────
SERVER_TYPE=""
ACCEL=""               # empty = auto-detect
SITE="config/site_gansu.yaml"
CHECKPOINT=""
BACKEND_PORT=8000
FRONTEND_PORT=5173
NO_LAUNCH=0
UNINSTALL=0
PURGE=0

# ── helpers ───────────────────────────────────────────────────────────────────
die() {
    local code=$1; shift
    printf "ERROR [%s]: %s\n" "$code" "$*" >&2
    exit "$code"
}

warn() { printf "WARNING: %s\n" "$*" >&2; }
info() { printf "%s\n" "$*"; }

# ── usage / --help ────────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: install_app.sh --server-type <TYPE> [OPTIONS]

Install and optionally launch Energy GO for the given server role.
Run from the project root directory.

Server types (--server-type):
  dev        Full stack: JAX, training, serving, frontend dev server (HMR).
  training   JAX + training only; no Node/frontend installed.
  serving    JAX CPU + FastAPI + built frontend bundle; no training deps.
  full       training + serving on one box.

Options:
  --server-type <dev|training|serving|full>  (required)
  --accel <cpu|gpu>          Accelerator variant (default: auto-detect gpu→cpu).
  --site <PATH>              Site YAML config (default: config/site_gansu.yaml).
  --checkpoint <ID_OR_PATH>  Checkpoint ID or path (required for serving/full).
  --backend-port <PORT>      FastAPI listen port  (default: 8000, range 1-65535).
  --frontend-port <PORT>     Frontend dev/static port (default: 5173, range 1-65535).
  --no-launch                Install only; do not start processes.
  --uninstall                Stop services and remove .venv, node_modules, dist, .run/.
  --purge                    With --uninstall: also remove checkpoints/.
  --help                     Show this help and exit.

Exit codes:
  0  Success (install/launch OK, up-to-date, or uninstall complete).
  1  Invalid argument (unknown --server-type, --accel, bad port, unknown flag, etc.).
  2  Preflight failure (unsupported OS/arch, toolchain install failed).
  3  Dependency install failure.
  4  Config/checkpoint error (YAML not found, missing --checkpoint).
  5  Launch failure (port in use, process failed to start).
  6  GPU accelerator requested but no GPU detected.

Remediation hints are printed on every non-zero exit.
EOF
    exit 0
}

# ── flag parsing ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --server-type)
            [[ $# -ge 2 ]] || die 1 "--server-type requires a value. Remediation: Pass --server-type <dev|training|serving|full>."
            SERVER_TYPE="$2"; shift 2 ;;
        --accel)
            [[ $# -ge 2 ]] || die 1 "--accel requires a value. Remediation: Pass --accel <cpu|gpu>."
            ACCEL="$2"; shift 2 ;;
        --site)
            [[ $# -ge 2 ]] || die 1 "--site requires a value. Remediation: Pass --site <path-to-yaml>."
            SITE="$2"; shift 2 ;;
        --checkpoint)
            [[ $# -ge 2 ]] || die 1 "--checkpoint requires a value. Remediation: Pass --checkpoint <id-or-path>."
            CHECKPOINT="$2"; shift 2 ;;
        --backend-port)
            [[ $# -ge 2 ]] || die 1 "--backend-port requires a value. Remediation: Pass --backend-port <1-65535>."
            BACKEND_PORT="$2"; shift 2 ;;
        --frontend-port)
            [[ $# -ge 2 ]] || die 1 "--frontend-port requires a value. Remediation: Pass --frontend-port <1-65535>."
            FRONTEND_PORT="$2"; shift 2 ;;
        --no-launch)   NO_LAUNCH=1;  shift ;;
        --uninstall)   UNINSTALL=1;  shift ;;
        --purge)       PURGE=1;      shift ;;
        --help|-h)     usage ;;
        --*)
            die 1 "Unknown flag: $1. Remediation: Run install_app.sh --help for the full flag list." ;;
        *)
            die 1 "Unexpected argument: '$1'. Remediation: Run install_app.sh --help for usage." ;;
    esac
done

# ── validate --server-type ────────────────────────────────────────────────────
if [[ -z "$SERVER_TYPE" ]]; then
    die 1 "--server-type is required. Remediation: Pass --server-type <dev|training|serving|full>."
fi
case "$SERVER_TYPE" in
    dev|training|serving|full) ;;
    *)
        die 1 "Unknown --server-type '$SERVER_TYPE'. Remediation: Valid server-type values are dev, training, serving, full." ;;
esac

# ── validate --accel ──────────────────────────────────────────────────────────
if [[ -n "$ACCEL" ]]; then
    case "$ACCEL" in
        cpu|gpu) ;;
        *)
            die 1 "Unknown --accel '$ACCEL'. Remediation: Valid accelerator values are cpu and gpu. Use --accel cpu for environments without CUDA/Metal." ;;
    esac
fi

# ── --purge requires --uninstall ──────────────────────────────────────────────
if [[ $PURGE -eq 1 && $UNINSTALL -eq 0 ]]; then
    die 1 "--purge must be combined with --uninstall. Remediation: Use install_app.sh --server-type <TYPE> --uninstall --purge."
fi

# ── uninstall / purge ─────────────────────────────────────────────────────────
if [[ $UNINSTALL -eq 1 ]]; then
    cd "$WORK_DIR"

    # Stop processes listed in .run/pids.json
    if [[ -f ".run/pids.json" ]] && command -v python3 &>/dev/null; then
        while IFS= read -r pid; do
            [[ "$pid" =~ ^[0-9]+$ ]] || continue
            if kill -0 "$pid" 2>/dev/null; then
                info "Stopping PID $pid..."
                kill "$pid" 2>/dev/null || true
                sleep 1
                # Force-kill if still alive
                kill -0 "$pid" 2>/dev/null && { kill -9 "$pid" 2>/dev/null || true; }
            else
                warn "PID $pid not running (already stopped)."
            fi
        done < <(python3 - <<'PYEOF'
import json, sys
try:
    d = json.load(open(".run/pids.json"))
    for v in d.values():
        print(int(v))
except Exception:
    pass
PYEOF
        )
    fi

    REMOVED=()
    [[ -d ".venv" ]]        && { rm -rf ".venv";        REMOVED+=(".venv"); }
    [[ -d "node_modules" ]] && { rm -rf "node_modules"; REMOVED+=("node_modules"); }
    [[ -d "dist" ]]         && { rm -rf "dist";         REMOVED+=("dist"); }
    [[ -d ".run" ]]         && { rm -rf ".run";         REMOVED+=(".run"); }

    if [[ $PURGE -eq 1 ]]; then
        [[ -d "checkpoints" ]] && { rm -rf "checkpoints"; REMOVED+=("checkpoints"); }
        # Remove any .run artifact files at the project root
        find . -maxdepth 1 -name "*.run" -delete 2>/dev/null || true
    fi

    if [[ ${#REMOVED[@]} -gt 0 ]]; then
        info "Removed: ${REMOVED[*]}"
    else
        info "Nothing to remove."
    fi
    exit 0
fi

# ── OS / arch preflight ───────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin) ;;
    Linux)  warn "Linux is not officially supported (§9); continuing as best-effort." ;;
    *)
        die 2 "Unsupported OS: $OS. Remediation: Supported OSes are macOS and Windows." ;;
esac
case "$ARCH" in
    x86_64|arm64|aarch64) ;;
    *)
        die 2 "Unsupported arch: $ARCH. Remediation: Supported architectures are x86_64 and arm64 (Apple Silicon)." ;;
esac

# ── serving always uses CPU ───────────────────────────────────────────────────
if [[ "$SERVER_TYPE" == "serving" && "${ACCEL:-}" == "gpu" ]]; then
    warn "serving type always uses CPU accelerator; --accel gpu ignored."
    ACCEL="cpu"
fi

# ── GPU detection helper ──────────────────────────────────────────────────────
detect_gpu() {
    # JAX_PLATFORM_NAME=cpu is an explicit override — treat as no GPU.
    if [[ "${JAX_PLATFORM_NAME:-}" == "cpu" ]]; then
        return 1
    fi
    # CUDA: nvidia-smi present and responsive.
    if command -v nvidia-smi &>/dev/null; then
        if nvidia-smi &>/dev/null 2>&1; then
            return 0
        fi
    fi
    # macOS Metal: system_profiler reports a Metal-capable GPU.
    if [[ "$OS" == "Darwin" ]]; then
        if system_profiler SPDisplaysDataType 2>/dev/null | grep -qi "Metal"; then
            return 0
        fi
    fi
    return 1
}

# ── fail-loud GPU check (§9.2, contract §7) ───────────────────────────────────
if [[ "${ACCEL:-}" == "gpu" ]]; then
    if ! detect_gpu; then
        die 6 "GPU accelerator requested but no GPU detected. Remediation: Use --accel cpu or install CUDA/Metal drivers. See STACK.md."
    fi
fi

# ── auto-detect accel if not specified ────────────────────────────────────────
if [[ -z "$ACCEL" ]]; then
    if [[ "$SERVER_TYPE" == "serving" ]]; then
        ACCEL="cpu"
    elif detect_gpu 2>/dev/null; then
        ACCEL="gpu"
        info "Auto-detected GPU accelerator."
    else
        ACCEL="cpu"
        info "No GPU detected; using CPU accelerator."
    fi
fi

# ── port validation ───────────────────────────────────────────────────────────
validate_port() {
    local port="$1" flag_name="$2"
    if ! [[ "$port" =~ ^[0-9]+$ ]]; then
        die 1 "Invalid $flag_name: '$port' is not an integer. Remediation: Provide an integer in range 1-65535."
    fi
    if (( port < 1 || port > 65535 )); then
        die 1 "Invalid $flag_name: $port is out of range 1-65535. Remediation: Provide an integer in range 1-65535."
    fi
}
validate_port "$BACKEND_PORT"  "--backend-port"
validate_port "$FRONTEND_PORT" "--frontend-port"

# ── config resolve ────────────────────────────────────────────────────────────
cd "$WORK_DIR"

# Resolve checkpoint for serving/full (checkpoint check first, then site yaml).
EFFECTIVE_CHECKPOINT="$CHECKPOINT"
if [[ "$SERVER_TYPE" == "serving" || "$SERVER_TYPE" == "full" ]]; then
    if [[ -z "$EFFECTIVE_CHECKPOINT" ]]; then
        if [[ -f ".run/last_checkpoint" ]]; then
            EFFECTIVE_CHECKPOINT="$(cat .run/last_checkpoint)"
        fi
    fi
    if [[ -z "$EFFECTIVE_CHECKPOINT" ]]; then
        die 4 "--checkpoint is required for --server-type $SERVER_TYPE and no .run/last_checkpoint found. Remediation: Pass --checkpoint <id-or-path> or create .run/last_checkpoint with a checkpoint path."
    fi
fi

# Site YAML existence check (full yaml.safe_load happens in-venv after install).
if [[ ! -f "$SITE" ]]; then
    die 4 "Site YAML not found: '$SITE'. Remediation: Pass --site <path> or create $SITE."
fi

# ── toolchain preflight ───────────────────────────────────────────────────────
# Python via uv (preferred).
if ! command -v uv &>/dev/null; then
    info "uv not found; attempting to install via curl..."
    if command -v curl &>/dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh \
            || die 2 "uv install failed. Remediation: Install uv manually: https://github.com/astral-sh/uv or https://docs.astral.sh/uv/getting-started/installation/"
        # Re-source shell profile so uv is in PATH
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    else
        die 2 "uv and curl not found. Remediation: Install uv: https://docs.astral.sh/uv/getting-started/installation/"
    fi
fi

# Node for dev / serving / full.
if [[ "$SERVER_TYPE" == "dev" || "$SERVER_TYPE" == "serving" || "$SERVER_TYPE" == "full" ]]; then
    if ! command -v node &>/dev/null; then
        info "Node not found; attempting to install via Homebrew..."
        if command -v brew &>/dev/null; then
            brew install node \
                || die 2 "Node install via Homebrew failed. Remediation: Install Node LTS manually: https://nodejs.org"
        else
            die 2 "Node not found and Homebrew unavailable. Remediation: Install Node LTS from https://nodejs.org or install Homebrew first: https://brew.sh"
        fi
    fi
fi

# ── select pyproject extras ───────────────────────────────────────────────────
if [[ "$ACCEL" == "gpu" ]]; then
    if [[ "$OS" == "Darwin" && ( "$ARCH" == "arm64" || "$ARCH" == "aarch64" ) ]]; then
        JAX_EXTRAS="jax-gpu-metal"
    else
        JAX_EXTRAS="jax-gpu-cuda"
    fi
else
    JAX_EXTRAS="jax-cpu"
fi

case "$SERVER_TYPE" in
    dev)      EXTRAS="${JAX_EXTRAS},training,serving,frontend-dev" ;;
    training) EXTRAS="${JAX_EXTRAS},training" ;;
    serving)  EXTRAS="jax-cpu,serving" ;;    # always jax-cpu for serving (§9.2)
    full)     EXTRAS="${JAX_EXTRAS},training,serving" ;;
esac

# ── port-in-use pre-flight (fail fast before the install step) ───────────────
# Defined here so it can be called both before install and at launch time.
check_port_free() {
    local port="$1" label="$2"
    if command -v lsof &>/dev/null; then
        # Use lsof without -sTCP:LISTEN so we detect any TCP socket on this port
        # (bound but not yet in LISTEN state, ESTABLISHED, etc.).  The LISTEN-only
        # filter caused false-negatives when the occupying socket had been bound
        # but not yet put into LISTEN state (e.g. during test fixture setup).
        if lsof -iTCP:"${port}" &>/dev/null 2>&1; then
            die 5 "$label port $port is already in use. Remediation: Use --${label,,}-port <other-port> or stop the existing process."
        fi
    fi
}

# Check ports early (before expensive install) when a launch will be attempted.
if [[ $NO_LAUNCH -eq 0 ]]; then
    if [[ "$SERVER_TYPE" == "serving" || "$SERVER_TYPE" == "full" || "$SERVER_TYPE" == "dev" ]]; then
        check_port_free "$BACKEND_PORT" "Backend"
    fi
    if [[ "$SERVER_TYPE" == "dev" ]]; then
        check_port_free "$FRONTEND_PORT" "Frontend"
    fi
fi

# ── create / update virtualenv ────────────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
    info "Creating virtualenv (.venv)..."
    # On ARM macOS: install a uv-managed (native ARM64) Python first to avoid Rosetta
    # picking an x86 interpreter, which would install x86 jaxlib and fail with AVX errors.
    # The `|| true` lets us continue if the install fails (e.g. no internet); the venv
    # creation below falls back to any available Python.
    if [[ "$OS" == "Darwin" ]] && [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" ]]; then
        info "ARM macOS detected — ensuring native uv-managed Python 3.11..."
        uv python install 3.11 2>/dev/null || true
        # UV_PYTHON_PREFERENCE=only-managed forces the freshly installed native Python.
        # Fall back to unmanaged if no managed Python is available (e.g. offline CI).
        UV_PYTHON_PREFERENCE=only-managed uv venv --seed --python 3.11 .venv 2>/dev/null \
            || uv venv --seed --python 3.11 .venv \
            || die 2 "Failed to create virtualenv. Remediation: Ensure Python 3.11 is available ('uv python install 3.11')."
    else
        # --seed adds pip/setuptools/wheel so .venv/bin/pip is always present.
        uv venv --seed --python 3.11 .venv \
            || die 2 "Failed to create virtualenv. Remediation: Ensure Python 3.11 is available ('uv python install 3.11')."
    fi
fi

# ── install dependencies ──────────────────────────────────────────────────────
info "Installing extras: [$EXTRAS]..."
INSTALL_OUT="$(uv pip install --python ".venv/bin/python" -e ".[${EXTRAS}]" 2>&1)" || {
    printf "%s\n" "$INSTALL_OUT" >&2
    die 3 "Dependency install failed. Remediation: Check internet connection, uv installation, and pyproject extras. Run: uv pip install -e \".[${EXTRAS}]\" manually to see full output."
}

# Idempotency signal: uv emits an "Installed N packages" line only when REMOTE
# packages change.  Editable rebuilds of the local package (lines containing
# "from file://") are excluded — uv always reinstalls the local editable even
# when nothing changed, so counting them would suppress the "up to date" message.
REMOTE_INSTALL_OUT="$(printf "%s\n" "$INSTALL_OUT" | grep -v "from file://")"
if printf "%s\n" "$REMOTE_INSTALL_OUT" | grep -qiE "Installed [0-9]+ package|Downloading"; then
    printf "%s\n" "$INSTALL_OUT"
else
    info "Environment up to date. Nothing to do."
fi

# ── frontend build ────────────────────────────────────────────────────────────
if [[ "$SERVER_TYPE" == "dev" || "$SERVER_TYPE" == "serving" || "$SERVER_TYPE" == "full" ]]; then
    if [[ -f "package.json" ]]; then
        info "Running npm ci..."
        npm ci --quiet 2>&1 \
            || die 3 "npm ci failed. Remediation: Ensure Node LTS and npm are installed and package-lock.json is up to date."
        if [[ "$SERVER_TYPE" == "serving" || "$SERVER_TYPE" == "full" ]]; then
            info "Building frontend bundle (npm run build)..."
            npm run build --quiet 2>&1 \
                || die 3 "npm run build failed. Remediation: Check the frontend build configuration (vite.config.ts / package.json scripts)."
        fi
    else
        info "package.json not found; skipping frontend step (frontend not yet scaffolded)."
    fi
fi

# ── launch ────────────────────────────────────────────────────────────────────
if [[ $NO_LAUNCH -eq 1 ]]; then
    info "Install complete (--no-launch; processes not started)."
    exit 0
fi

mkdir -p ".run"
declare -A PIDS=()

# FastAPI backend (serving / full / dev)
if [[ "$SERVER_TYPE" == "serving" || "$SERVER_TYPE" == "full" || "$SERVER_TYPE" == "dev" ]]; then
    check_port_free "$BACKEND_PORT" "Backend"
    RELOAD=""
    [[ "$SERVER_TYPE" == "dev" ]] && RELOAD="--reload"
    # shellcheck disable=SC2086
    ".venv/bin/uvicorn" energy_go.serving.app:app \
        --host 0.0.0.0 --port "$BACKEND_PORT" $RELOAD \
        >"/tmp/energy_go_api_${BACKEND_PORT}.log" 2>&1 &
    API_PID=$!
    sleep 1
    if ! kill -0 "$API_PID" 2>/dev/null; then
        die 5 "FastAPI failed to start. Remediation: Check logs at /tmp/energy_go_api_${BACKEND_PORT}.log and ensure the serving package is installed."
    fi
    PIDS[api]=$API_PID
    info "FastAPI started  →  http://localhost:${BACKEND_PORT}  (PID ${API_PID})"
fi

# Training harness (training / full)
if [[ "$SERVER_TYPE" == "training" || "$SERVER_TYPE" == "full" ]]; then
    ".venv/bin/python" -m energy_go.harness.train --site "$SITE" \
        >"/tmp/energy_go_training.log" 2>&1 &
    TRAIN_PID=$!
    PIDS[training]=$TRAIN_PID
    info "Training harness started  (PID ${TRAIN_PID})  →  logs: /tmp/energy_go_training.log"
fi

# Vite dev server (dev only)
if [[ "$SERVER_TYPE" == "dev" ]]; then
    check_port_free "$FRONTEND_PORT" "Frontend"
    npx vite --port "$FRONTEND_PORT" \
        >"/tmp/energy_go_frontend_${FRONTEND_PORT}.log" 2>&1 &
    FRONT_PID=$!
    PIDS[frontend]=$FRONT_PID
    info "Vite dev server started  →  http://localhost:${FRONTEND_PORT}  (PID ${FRONT_PID})"
fi

# Write .run/pids.json and state files
PID_JSON="{"
SEP=""
for role in "${!PIDS[@]}"; do
    PID_JSON+="${SEP}\"${role}\": ${PIDS[$role]}"
    SEP=", "
done
PID_JSON+="}"
printf "%s\n" "$PID_JSON" > ".run/pids.json"
printf "%s\n" "$EFFECTIVE_CHECKPOINT" > ".run/last_checkpoint"
printf "%s\n" "$SERVER_TYPE"          > ".run/server_type"

info ""
info "Energy GO (${SERVER_TYPE}) is running."
info "  Backend:   http://localhost:${BACKEND_PORT}"
[[ "$SERVER_TYPE" == "dev" ]] && info "  Frontend:  http://localhost:${FRONTEND_PORT}"
info "  Stop:      bash scripts/install_app.sh --server-type ${SERVER_TYPE} --uninstall"
