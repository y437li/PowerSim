#!/usr/bin/env bash
# Machine-checkable merge gate for Energy GO PRs (verdict-marker convention, CLAUDE.md).
#
# The GitHub account is shared across all agents, so `gh pr review --approve` 422s on a
# self-authored PR and cannot be the verdict mechanism. Instead every review/QA verdict is a
# TOP-LEVEL PR comment whose FIRST line is exactly one of:
#   VERDICT: APPROVE | REQUEST_CHANGES | COMMENT | QA_PASS | QA_FAIL | QA_PASS_WITH_ISSUES
# and whose SECOND line is:  reviewer: <agent-name>   (optionally followed by scope text)
# The NEWEST marker per reviewer wins.
#
# HEAD-COVERAGE REQUIREMENT (added after the PR #10 incident, 2026-06-11):
#   The gate-deciding markers must POST-DATE the current head commit. A verdict only counts if
#   it was posted AFTER the commit it is supposed to cover; otherwise a late push (code added
#   after the review/QA) would slip through — exactly what let a QA_FAIL cross the merge on
#   PR #10. Gate-deciding markers are:
#     (a) the required reviewer's marker (when --required is given),
#     (b) the operative QA marker (newest QA_PASS / QA_FAIL / QA_PASS_WITH_ISSUES),
#     (c) the rl-architect APPROVE marker (only on the QA_PASS_WITH_ISSUES path).
#   If any gate-deciding marker's timestamp is OLDER than the head commit's committedDate, the
#   gate is BLOCKED — re-review/re-QA the current head.
#
# LIMITATION (committedDate vs pushedDate): the coverage check compares the head commit's
#   committedDate against marker timestamps. A FORCE-PUSH of an OLD commit (or a rebase that
#   preserves an old committedDate) can present a head whose committedDate is older than the
#   markers, so the timestamp check will NOT catch it. The SHA-CITATION check below is the
#   secondary guard for that case: if a gate-deciding marker explicitly scopes itself to a SHA
#   that does not match the current head, a WARNING is printed (it never hard-blocks, to stay
#   low-false-positive). GitHub's API does not expose a reliable per-commit pushedDate here,
#   hence committedDate is used.
#
# Usage:
#   scripts/check_pr_gate.sh <pr-number> [--required <reviewer>] [--repo <owner/name>]
#
# Exit 0 = mergeable per the gate; exit 1 = blocked; exit 2 = usage/lookup error.
# Reports evidence; does NOT merge. rl-architect decision PRs (area meta, no implementation
# code) bypass this gate per CLAUDE.md. Portable to bash 3.2 (macOS) — no associative arrays.
set -uo pipefail

PR=""
REQUIRED=""
REPO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --required) REQUIRED="${2:-}"; shift 2 ;;
    --repo)     REPO="${2:-}"; shift 2 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          PR="$1"; shift ;;
  esac
done

[ -z "$PR" ] && { echo "usage: $0 <pr-number> [--required <reviewer>] [--repo <owner/name>]" >&2; exit 2; }

VALID='APPROVE|REQUEST_CHANGES|COMMENT|QA_PASS|QA_FAIL|QA_PASS_WITH_ISSUES'

# Read all top-level issue comments. Pass --repo only when provided (avoids empty-array
# expansion under `set -u` on bash 3.2).
if [ -n "$REPO" ]; then
  comments_json="$(gh pr view "$PR" --repo "$REPO" --json comments 2>/dev/null)" || comments_json=""
else
  comments_json="$(gh pr view "$PR" --json comments 2>/dev/null)" || comments_json=""
fi
[ -z "$comments_json" ] && { echo "ERROR: cannot read PR #$PR (check number / auth / --repo)." >&2; exit 2; }

# Read head commit info (for the head-coverage + sha-citation checks). Best-effort: if this
# fails, we warn loudly and fall through to the normal gate without changing the exit status.
if [ -n "$REPO" ]; then
  head_json="$(gh pr view "$PR" --repo "$REPO" --json headRefOid,commits 2>/dev/null)" || head_json=""
else
  head_json="$(gh pr view "$PR" --json headRefOid,commits 2>/dev/null)" || head_json=""
fi

head_sha=""
head_committed=""
if [ -n "$head_json" ]; then
  head_sha="$(printf '%s' "$head_json" | jq -r '.headRefOid // ""' 2>/dev/null)"
  # committedDate of the commit whose oid==headRefOid; fall back to the last commit's date.
  head_committed="$(printf '%s' "$head_json" | jq -r '
    (.headRefOid // "") as $h
    | (([.commits[] | select(.oid == $h)] | .[0].committedDate) // (.commits[-1].committedDate) // "")
  ' 2>/dev/null)"
fi
[ "$head_sha" = "null" ] && head_sha=""
[ "$head_committed" = "null" ] && head_committed=""
head_sha7="$(printf '%s' "$head_sha" | cut -c1-7)"

if [ -z "$head_committed" ]; then
  echo "⚠ head-coverage check SKIPPED — could not read head commit (auth/API); verify head-vs-markers manually before merge" >&2
fi

# jq → "reviewer<TAB>verdict<TAB>iso-timestamp<TAB>body", oldest first (later lines supersede).
# The body has CR/LF/TAB collapsed to single spaces so it stays on one field / one line.
markers="$(printf '%s' "$comments_json" | jq -r --arg valid "$VALID" '
  .comments
  | sort_by(.createdAt)
  | .[]
  | . as $c
  | ($c.body | gsub("\r"; "") | split("\n")) as $lines
  | ($lines[0] // "") as $l0
  | ($lines[1] // "") as $l1
  | select($l0 | test("^VERDICT:[[:space:]]*(" + $valid + ")[[:space:]]*$"))
  | ($l0 | capture("^VERDICT:[[:space:]]*(?<v>[A-Z_]+)").v) as $verdict
  | (($l1 | capture("^reviewer:[[:space:]]*(?<r>[A-Za-z0-9_-]+)") // {}).r) as $rev
  | select($rev != null)
  | ($c.body | gsub("[\r\n\t]+"; " ")) as $body
  | "\($rev)\t\($verdict)\t\($c.createdAt)\t\($body)"
' 2>/dev/null)"

# awk: keep newest verdict per reviewer (input already oldest→newest), then evaluate the gate,
# including the head-coverage check against the head commit's committedDate.
printf '%s\n' "$markers" | awk \
  -v required="$REQUIRED" \
  -v head_committed="$head_committed" \
  -v head_sha="$head_sha" \
  -v head_sha7="$head_sha7" '
  # Extract an explicitly-scoped SHA (hex 7..40) from a marker body, using ONLY these phrases
  # (case-insensitive): "scoped to <sha>", "(commit <sha>)", "@ <sha>". Returns "" if none.
  # Deliberately does NOT match bare SHAs (e.g. "supersedes my <old> APPROVE") to stay low
  # false-positive. awk regex has no case-insensitivity, so we lower-case a working copy.
  function sha_cite(s,   t, m) {
    t = tolower(s)
    if (match(t, /scoped to [0-9a-f]{7,40}/))  { m=substr(t,RSTART,RLENGTH); sub(/^scoped to /,"",m); return m }
    if (match(t, /\(commit [0-9a-f]{7,40}\)/)) { m=substr(t,RSTART,RLENGTH); gsub(/[()]/,"",m); sub(/^commit /,"",m); return m }
    if (match(t, /@ [0-9a-f]{7,40}/))          { m=substr(t,RSTART,RLENGTH); sub(/^@ /,"",m); return m }
    return ""
  }
  BEGIN { FS="\t"; n=0 }
  NF>=2 {
    if (!($1 in seen)) { order[n++]=$1; seen[$1]=1 }
    verdict[$1]=$2; when[$1]=$3; body[$1]=$4
  }
  END {
    print "== PR verdict markers (newest per reviewer) =="
    if (n==0) print "  (none found)"
    for (i=0;i<n;i++){ r=order[i]; printf "  %-22s %-22s %s\n", r, verdict[r], when[r] }

    nr=0
    # QA: newest QA_* across reviewers (later in order wins)
    qa=""; qa_owner=""
    for (i=0;i<n;i++){ r=order[i]; v=verdict[r]
      if (v=="QA_PASS"||v=="QA_FAIL"||v=="QA_PASS_WITH_ISSUES"){ qa=v; qa_owner=r } }
    rl = (("rl-architect" in verdict) && verdict["rl-architect"]=="APPROVE") ? 1 : 0

    if (qa=="QA_PASS") {}
    else if (qa=="QA_PASS_WITH_ISSUES") {
      if (!rl) reasons[nr++]="QA is QA_PASS_WITH_ISSUES (" qa_owner ") but no rl-architect APPROVE sign-off marker present"
    }
    else if (qa=="QA_FAIL") reasons[nr++]="QA latest verdict is QA_FAIL (" qa_owner ")"
    else reasons[nr++]="no QA verdict marker (QA_PASS / QA_PASS_WITH_ISSUES) found"

    if (required!="") {
      if (!(required in verdict)) reasons[nr++]="required reviewer \x27" required "\x27 has no verdict marker"
      else if (verdict[required]!="APPROVE") reasons[nr++]="required reviewer \x27" required "\x27 latest verdict is " verdict[required] " (need APPROVE)"
    } else {
      print "  note: no --required reviewer given; checking QA gate only." > "/dev/stderr"
    }

    for (i=0;i<n;i++){ r=order[i]
      if (verdict[r]=="REQUEST_CHANGES") reasons[nr++]="\x27" r "\x27 latest verdict is REQUEST_CHANGES" }

    # ---- HEAD-COVERAGE CHECK (hard block) + SHA-CITATION CHECK (warning only) ----
    # Only run when we successfully read the head commit date. ISO8601-Z strings compare
    # lexicographically == chronologically.
    if (head_committed != "") {
      # Build the list of gate-deciding (role -> reviewer) pairs that actually exist.
      gc=0
      if (required!="" && (required in verdict)) { grole[gc]="required reviewer"; grev[gc]=required; gc++ }
      if (qa_owner!="") { grole[gc]="QA"; grev[gc]=qa_owner; gc++ }
      if (qa=="QA_PASS_WITH_ISSUES" && rl) { grole[gc]="rl-architect"; grev[gc]="rl-architect"; gc++ }
      for (i=0;i<gc;i++){
        role=grole[i]; rev=grev[i]; w=when[rev]
        if (w < head_committed) {
          reasons[nr++]=role " marker (" w ") predates head commit " head_sha7 " (committed " head_committed ") — re-review/re-QA the current head"
        }
        # SHA-citation: best-effort, explicit phrases only, warning only.
        cited=sha_cite(body[rev])
        if (cited != "") {
          lc=tolower(cited); lh=tolower(head_sha)
          # prefix-match either direction is considered covering the head
          if (lh != "" && index(lh, lc)!=1 && index(lc, lh)!=1) {
            printf "⚠ %s marker is scoped to %s but head is %s — verify it covers the current head\n", role, cited, head_sha7 > "/dev/stderr"
          }
        }
      }
    }

    print ""
    if (nr==0){ print "GATE: PASS — PR satisfies the merge gate."; exit 0 }
    print "GATE: BLOCKED — PR is not mergeable:"
    for (i=0;i<nr;i++) print "  - " reasons[i]
    exit 1
  }
'
