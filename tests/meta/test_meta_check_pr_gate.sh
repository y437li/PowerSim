#!/usr/bin/env bash
# Self-contained test harness for scripts/check_pr_gate.sh head-coverage hardening (task #36).
#
# Puts a fake `gh` on PATH. The stub inspects the requested --json fields and a scenario
# selector (env var GATE_SCENARIO) and echoes canned JSON for both queries the script makes:
#   - `gh pr view <pr> --json comments`            -> { "comments": [...] }
#   - `gh pr view <pr> --json headRefOid,commits`  -> { "headRefOid": ..., "commits": [...] }
#
# Run: bash tests/meta/test_meta_check_pr_gate.sh
# Exits non-zero if ANY case fails.
set -uo pipefail

# Resolve repo root from this test file's location (tests/meta/ -> repo root).
THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/../.." && pwd)"
GATE="$REPO_ROOT/scripts/check_pr_gate.sh"
[ -f "$GATE" ] || { echo "FATAL: cannot find $GATE" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
BIN="$WORK/bin"
mkdir -p "$BIN"

# ---- fake gh -------------------------------------------------------------------------------
# Reads GATE_SCENARIO from the environment. For each scenario it returns comments JSON and
# head JSON. The stub decides which response to emit by scanning its args for "comments" vs
# "headRefOid".
cat > "$BIN/gh" <<'STUB'
#!/usr/bin/env bash
# minimal fake gh: only supports `gh pr view ... --json <fields>`
want=""
for a in "$@"; do
  case "$a" in
    comments) want="comments" ;;
    headRefOid,commits|headRefOid|commits) want="head" ;;
  esac
done

emit_comments() {
  # $1 = scenario
  case "$1" in
    T1|T2)
      # required reviewer APPROVE + QA_PASS. Timestamps set per-scenario via env.
      cat <<JSON
{ "comments": [
  { "createdAt": "$MK_TS", "body": "VERDICT: APPROVE\nreviewer: backend-reviewer\n\nlooks good" },
  { "createdAt": "$MK_TS", "body": "VERDICT: QA_PASS\nreviewer: qa-engineer\n\nall green" }
] }
JSON
      ;;
    T3)
      # newest verdict is REQUEST_CHANGES; markers newer than head.
      cat <<JSON
{ "comments": [
  { "createdAt": "2026-06-11T07:50:00Z", "body": "VERDICT: QA_PASS\nreviewer: qa-engineer" },
  { "createdAt": "2026-06-11T07:51:00Z", "body": "VERDICT: REQUEST_CHANGES\nreviewer: backend-reviewer\n\nplease fix X" }
] }
JSON
      ;;
    T4)
      # QA_PASS_WITH_ISSUES + rl-architect APPROVE, both newer than head.
      cat <<JSON
{ "comments": [
  { "createdAt": "2026-06-11T07:50:00Z", "body": "VERDICT: QA_PASS_WITH_ISSUES\nreviewer: qa-engineer\n\nminor nits" },
  { "createdAt": "2026-06-11T07:52:00Z", "body": "VERDICT: APPROVE\nreviewer: rl-architect\n\nsign-off" }
] }
JSON
      ;;
    T5)
      # passing gate, but a gate-deciding marker body cites a mismatching SHA -> warning only.
      cat <<JSON
{ "comments": [
  { "createdAt": "2026-06-11T07:50:00Z", "body": "VERDICT: APPROVE\nreviewer: backend-reviewer\n\nscoped to deadbee" },
  { "createdAt": "2026-06-11T07:50:00Z", "body": "VERDICT: QA_PASS\nreviewer: qa-engineer" }
] }
JSON
      ;;
  esac
}

emit_head() {
  # $1 = scenario. head committedDate fixed at 07:40:00Z across scenarios.
  case "$1" in
    T1|T3|T4) HEAD_SHA="abc1234def5678" ;;
    T2)       HEAD_SHA="abc1234def5678" ;;
    T5)       HEAD_SHA="cafef00dbaadf00d" ;;  # head != deadbee -> warning fires
  esac
  cat <<JSON
{ "headRefOid": "$HEAD_SHA",
  "commits": [
    { "oid": "0000000aaa", "committedDate": "2026-06-11T07:30:00Z", "authoredDate": "2026-06-11T07:30:00Z" },
    { "oid": "$HEAD_SHA", "committedDate": "2026-06-11T07:40:00Z", "authoredDate": "2026-06-11T07:40:00Z" }
  ] }
JSON
}

if [ "$want" = "comments" ]; then
  emit_comments "$GATE_SCENARIO"
elif [ "$want" = "head" ]; then
  emit_head "$GATE_SCENARIO"
fi
STUB
chmod +x "$BIN/gh"

# ---- test runner ---------------------------------------------------------------------------
FAILS=0
run_case() {
  # name, scenario, mk_ts, expected_exit, needle_stdout, needle_stderr
  local name="$1" scenario="$2" mk_ts="$3" exp_exit="$4" needle_out="$5" needle_err="$6"
  local out err rc
  out="$WORK/out.$name"; err="$WORK/err.$name"
  PATH="$BIN:$PATH" GATE_SCENARIO="$scenario" MK_TS="$mk_ts" \
    /bin/bash "$GATE" 42 --required backend-reviewer >"$out" 2>"$err"
  rc=$?
  local ok=1 msg=""
  if [ "$rc" -ne "$exp_exit" ]; then ok=0; msg="$msg exit=$rc want=$exp_exit;"; fi
  if [ -n "$needle_out" ] && ! grep -qF "$needle_out" "$out"; then ok=0; msg="$msg stdout missing '$needle_out';"; fi
  if [ -n "$needle_err" ] && ! grep -qF "$needle_err" "$err"; then ok=0; msg="$msg stderr missing '$needle_err';"; fi
  if [ "$ok" -eq 1 ]; then
    printf 'PASS  %s\n' "$name"
  else
    printf 'FAIL  %s --%s\n' "$name" "$msg"
    echo "      --- stdout ---"; sed 's/^/      /' "$out"
    echo "      --- stderr ---"; sed 's/^/      /' "$err"
    FAILS=$((FAILS+1))
  fi
}

# Some cases override --required by re-invoking directly below.
run_case_norequired() {
  local name="$1" scenario="$2" exp_exit="$3" needle_out="$4" needle_err="$5"
  local out err rc
  out="$WORK/out.$name"; err="$WORK/err.$name"
  PATH="$BIN:$PATH" GATE_SCENARIO="$scenario" MK_TS="unused" \
    /bin/bash "$GATE" 42 >"$out" 2>"$err"
  rc=$?
  local ok=1 msg=""
  if [ "$rc" -ne "$exp_exit" ]; then ok=0; msg="$msg exit=$rc want=$exp_exit;"; fi
  if [ -n "$needle_out" ] && ! grep -qF "$needle_out" "$out"; then ok=0; msg="$msg stdout missing '$needle_out';"; fi
  if [ -n "$needle_err" ] && ! grep -qF "$needle_err" "$err"; then ok=0; msg="$msg stderr missing '$needle_err';"; fi
  if [ "$ok" -eq 1 ]; then printf 'PASS  %s\n' "$name"
  else
    printf 'FAIL  %s --%s\n' "$name" "$msg"
    echo "      --- stdout ---"; sed 's/^/      /' "$out"
    echo "      --- stderr ---"; sed 's/^/      /' "$err"
    FAILS=$((FAILS+1))
  fi
}

echo "== check_pr_gate.sh head-coverage tests =="

# T1 PASS: markers (07:50) newer than head committedDate (07:40) -> exit 0, GATE: PASS
run_case T1_pass T1 "2026-06-11T07:50:00Z" 0 "GATE: PASS" ""

# T2 BLOCK (the incident): markers (07:37) older than head (07:40) -> exit 1, "predates head"
run_case T2_block_incident T2 "2026-06-11T07:37:00Z" 1 "predates head" ""

# T3 BLOCK: newest verdict REQUEST_CHANGES, markers newer than head -> exit 1 (existing behavior)
run_case T3_block_request_changes T3 "unused" 1 "REQUEST_CHANGES" ""

# T4 PASS: QA_PASS_WITH_ISSUES + rl-architect APPROVE, both newer than head -> exit 0
# (no --required reviewer; QA path only)
run_case_norequired T4_pass_pwi T4 0 "GATE: PASS" ""

# T5 WARN: gate-deciding marker body "scoped to deadbee", head=cafef00d... -> warning + exit 0
run_case T5_warn_sha_citation T5 "unused" 0 "GATE: PASS" "scoped to deadbee"

echo ""
if [ "$FAILS" -eq 0 ]; then
  echo "ALL CASES PASSED"
  exit 0
else
  echo "$FAILS CASE(S) FAILED"
  exit 1
fi
