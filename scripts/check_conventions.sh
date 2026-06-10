#!/usr/bin/env bash
# Mechanical enforcement of the naming/location conventions in CLAUDE.md.
# Run by CI on every PR; agents should run it locally before pushing.
set -uo pipefail

fail=0
err() { echo "CONVENTION FAIL: $*" >&2; fail=1; }

# 1. Branch naming (only when running on a PR in CI)
if [ -n "${GITHUB_HEAD_REF:-}" ]; then
  if ! echo "$GITHUB_HEAD_REF" | grep -Eq '^(feat|fix|chore)/[a-z0-9][a-z0-9.-]*$'; then
    err "branch '$GITHUB_HEAD_REF' must match (feat|fix|chore)/<area>-<feature>, lowercase with hyphens"
  fi
fi

# 2. No test files outside the tests/ tree (contracts/_example is the exempt worked example)
stray=$(find . \( -path ./tests -o -path ./contracts/_example -o -path ./.git -o -path ./node_modules \) -prune \
        -o \( -name 'test_*.py' -o -name '*.test.ts' -o -name '*.test.tsx' -o -name '*.spec.ts' \) -print 2>/dev/null)
[ -n "$stray" ] && err "test files outside tests/: $stray"

# 3. Python tests follow tests/<area>/test_<area>_<feature>.py and have a matching contract
if [ -d tests ]; then
  while IFS= read -r f; do
    area=$(basename "$(dirname "$f")")
    base=$(basename "$f")
    case "$base" in
      test_"$area"_*.py)
        feature=${base#test_"$area"_}; feature=${feature%.py}
        [ -f "contracts/$area/$feature.md" ] || err "$f has no contract at contracts/$area/$feature.md"
        ;;
      *) err "$f must be named test_${area}_<feature>.py" ;;
    esac
  done < <(find tests -name 'test_*.py' -not -path 'tests/frontend*' 2>/dev/null)

  # Frontend unit tests only under tests/frontend* (Vitest+RTL)
  strayfe=$(find tests \( -name '*.test.ts' -o -name '*.test.tsx' \) -not -path 'tests/frontend*' 2>/dev/null)
  [ -n "$strayfe" ] && err "frontend unit tests must live under tests/frontend*/: $strayfe"

  # Playwright E2E tests (.spec.ts) only under tests/frontend_e2e/ (D20)
  straye2e=$(find tests -name '*.spec.ts' -not -path 'tests/frontend_e2e/*' 2>/dev/null)
  [ -n "$straye2e" ] && err "Playwright .spec.ts tests must live under tests/frontend_e2e/: $straye2e"
fi

# 4. Review record must exist for every non-example contract
if [ -d contracts ]; then
  while IFS= read -r c; do
    feature=$(basename "$c" .md)
    [ -f "contracts/reviews/$feature.md" ] || \
      echo "WARN: contracts/$(basename "$(dirname "$c")")/$feature.md has no review record yet (required before implementation merges)"
  done < <(find contracts -name '*.md' -not -path 'contracts/_example/*' -not -path 'contracts/reviews/*' 2>/dev/null)
fi

# 5. Banned version-suffix filenames — git history is the version record
banned=$(find . \( -path ./.git -o -path ./node_modules \) -prune \
         -o -type f \( -name '*_v[0-9]*.*' -o -name '*_final.*' -o -name '*_new.*' -o -name '*_old.*' \) -print 2>/dev/null)
[ -n "$banned" ] && err "version-suffix filenames are banned (_v2/_final/_new/_old): $banned"

if [ "$fail" -eq 0 ]; then
  echo "All convention checks passed."
fi
exit "$fail"
