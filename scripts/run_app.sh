#!/usr/bin/env bash
# run_app.sh — launch an already-installed Energy GO server type.
# Assumes install_app.sh has been run first (no dependency install).
# Contract:  contracts/serving/launch_scripts.md §6
# Spec:      REBUILD_SPEC.md §9.3 (run_app performs steps 4+6 only)
# Exit codes: 0=ok 1=bad-arg 4=config 5=launch
set -uo pipefail

WORK_DIR="$(pwd)"

# ── defaults ──────────────────────────────────────────────────────────────────
SERVER_TYPE=""
ACCEL="cpu"
SITE="config/site_gansu.yaml"
CHECKPOINT=""
BACKEND_PORT=8000
FRONTEND_PORT=5173

# ── helpers ───────────────────────────────────────────────────────────────────
die() {
    local code=$1; shift
    printf "ERROR [%s]: %s\n" "$code" "$*" >&2
    exit "$code"
}
info() { printf "%s\n" "$*"; }

# ── usage ─────────────────────────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: run_app.sh --server-type <TYPE> [OPTIONS]

Launch an already-installed Energy GO server type.
Run install_app.sh first if .venv/ is absent.

Options:
  --server-type <dev|training|serving|full>  (required)
  --accel <cpu|gpu>          Accelerator variant (default: cpu).
  --site <PATH>              Site YAML config (default: config/site_gansu.yaml).
  --checkpoint <ID_OR_PATH>  Checkpoint for serving/full.
  --backend-port <PORT>      FastAPI listen port  (default: 8000, range 1-65535).
  --frontend-port <PORT>     Frontend port (default: 5173, range 1-65535).
  --help                     Show this help and exit.

Exit codes: 0=ok 1=bad-arg 4=config 5=launch
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
            [[ $# -ge 2 ]] || die 1 "--backend-port requires a value."
            BACKEND_PORT="$2"; shift 2 ;;
        --frontend-port)
            [[ $# -ge 2 ]] || die 1 "--frontend-port requires a value."
            FRONTEND_PORT="$2"; shift 2 ;;
        --help|-h) usage ;;
        --*)
            die 1 "Unknown flag: $1. Remediation: Run run_app.sh --help for the full flag list." ;;
        *)
            die 1 "Unexpected argument: '$1'. Remediation: Run run_app.sh --help for usage." ;;
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

# ── check .venv exists ────────────────────────────────────────────────────────
cd "$WORK_DIR"
if [[ ! -d ".venv" ]]; then
    printf "ERROR: No virtualenv found at %s/.venv.\n" "$WORK_DIR" >&2
    printf "Remediation: Run install_app.sh --server-type %s first to install the environment.\n" "$SERVER_TYPE" >&2
    exit 1
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

# ── config resolve (step 4) ───────────────────────────────────────────────────
EFFECTIVE_CHECKPOINT="$CHECKPOINT"
if [[ "$SERVER_TYPE" == "serving" || "$SERVER_TYPE" == "full" ]]; then
    if [[ -z "$EFFECTIVE_CHECKPOINT" ]]; then
        if [[ -f ".run/last_checkpoint" ]]; then
            EFFECTIVE_CHECKPOINT="$(cat .run/last_checkpoint)"
        fi
    fi
    if [[ -z "$EFFECTIVE_CHECKPOINT" ]]; then
        die 4 "--checkpoint is required for --server-type $SERVER_TYPE and no .run/last_checkpoint found. Remediation: Pass --checkpoint <id-or-path>."
    fi
fi

if [[ ! -f "$SITE" ]]; then
    die 4 "Site YAML not found: '$SITE'. Remediation: Pass --site <path> or run install_app.sh to set up the environment."
fi

# ── launch (step 6) ───────────────────────────────────────────────────────────
mkdir -p ".run"
declare -A PIDS=()

check_port_free() {
    local port="$1" label="$2"
    if command -v lsof &>/dev/null; then
        if lsof -iTCP:"${port}" -sTCP:LISTEN &>/dev/null 2>&1; then
            die 5 "$label port $port is already in use. Remediation: Use --${label,,}-port <other-port> or stop the existing process."
        fi
    fi
}

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
        die 5 "FastAPI failed to start. Remediation: Check logs at /tmp/energy_go_api_${BACKEND_PORT}.log."
    fi
    PIDS[api]=$API_PID
    info "FastAPI started  →  http://localhost:${BACKEND_PORT}  (PID ${API_PID})"
fi

if [[ "$SERVER_TYPE" == "training" || "$SERVER_TYPE" == "full" ]]; then
    ".venv/bin/python" -m energy_go.harness.train --site "$SITE" \
        >"/tmp/energy_go_training.log" 2>&1 &
    TRAIN_PID=$!
    PIDS[training]=$TRAIN_PID
    info "Training harness started  (PID ${TRAIN_PID})"
fi

if [[ "$SERVER_TYPE" == "dev" ]]; then
    check_port_free "$FRONTEND_PORT" "Frontend"
    npx vite --port "$FRONTEND_PORT" \
        >"/tmp/energy_go_frontend_${FRONTEND_PORT}.log" 2>&1 &
    FRONT_PID=$!
    PIDS[frontend]=$FRONT_PID
    info "Vite dev server started  →  http://localhost:${FRONTEND_PORT}  (PID ${FRONT_PID})"
fi

# Write .run/ state files
PID_JSON="{"
SEP=""
for role in "${!PIDS[@]}"; do
    PID_JSON+="${SEP}\"${role}\": ${PIDS[$role]}"
    SEP=", "
done
PID_JSON+="}"
printf "%s\n" "$PID_JSON"               > ".run/pids.json"
printf "%s\n" "$EFFECTIVE_CHECKPOINT"   > ".run/last_checkpoint"
printf "%s\n" "$SERVER_TYPE"            > ".run/server_type"

info ""
info "Energy GO (${SERVER_TYPE}) is running."
info "  Stop:  bash scripts/install_app.sh --server-type ${SERVER_TYPE} --uninstall"
