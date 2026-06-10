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

# jq → "reviewer<TAB>verdict<TAB>iso-timestamp", oldest first (later lines supersede).
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
  | "\($rev)\t\($verdict)\t\($c.createdAt)"
' 2>/dev/null)"

# awk: keep newest verdict per reviewer (input already oldest→newest), then evaluate the gate.
printf '%s\n' "$markers" | awk -v required="$REQUIRED" '
  BEGIN { FS="\t"; n=0 }
  NF>=2 {
    if (!($1 in seen)) { order[n++]=$1; seen[$1]=1 }
    verdict[$1]=$2; when[$1]=$3
  }
  END {
    print "== PR verdict markers (newest per reviewer) =="
    if (n==0) print "  (none found)"
    for (i=0;i<n;i++){ r=order[i]; printf "  %-22s %-22s %s\n", r, verdict[r], when[r] }

    blocked=0; nr=0
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

    print ""
    if (nr==0){ print "GATE: PASS — PR satisfies the merge gate."; exit 0 }
    print "GATE: BLOCKED — PR is not mergeable:"
    for (i=0;i<nr;i++) print "  - " reasons[i]
    exit 1
  }
'
