#!/usr/bin/env bash
# check_nav_index.sh — CI staleness guard for per-folder navigation indexes.
#
# Regenerates each target folder's <!-- generated:start -->...<!-- generated:end -->
# block in memory and compares it with what is on disk.  Exits 1 if any folder's
# generated block is stale; exits 0 if everything is current.
#
# Run:
#   bash scripts/check_nav_index.sh
#
# Fix stale indexes:
#   python3 scripts/gen_nav_index.py
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Nav-index staleness check ==="
python3 scripts/gen_nav_index.py --check
