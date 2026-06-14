# Review Record — `ci_lanes` (CI Lanes — 3-tier fast/slow/local)

**Contract:** `contracts/meta/ci_lanes.md` (D46, merged @ `0d3650b`)
**Area:** meta · **Owner/Lead:** rl-architect · **Implementer:** serving-engineer
**Reviewers:** backend-reviewer (required) + QA (gate) · rl-architect locks the contract on own authority
**Tests:** none of the usual unit kind — CI workflows are validated **empirically** (the §7.2 canary
B1–B7) + the §11 schema-conformance cases (owned by the schema contracts, task #24). This record
therefore covers (a) the **contract+tests-cases gate** on the contract PR and (b) the **YAML
implementation audit** on the quick-wins PR.

---

## Stage 1 — Contract + Test-Cases Gate (PR #136, `contracts/meta/ci_lanes.md`)

### backend-reviewer — REQUEST_CHANGES @ `eef53ca` (2026-06-14)

**BLOCKER found — §3.5 aggregator could FALSE-GREEN.** The fail-set was specified as
"any of `static-checks`/`backend-tests`/`frontend-tests` ∈ {failure, cancelled}" — `changes` was in
`needs` but NOT the fail-set. Trace: if the `changes` path-filter job FAILS, both test jobs go
`skipped` (their `if: needs.changes.outputs.* == 'true'` can't evaluate), `static-checks` passes →
aggregator sees `success + skipped + skipped` → **PASS with zero area tests run.** Also contradicted
the §3 DAG ("any need"). Required fix: fail-set = `[changes, static-checks, backend-tests,
frontend-tests]` (`changes` has no `if:` → never legitimately `skipped` → safe to include).

**Reviewer-added cases (all `# reviewer:`-attributed, integrated by rl-architect into v0.2):**

| Case | Rationale |
|---|---|
| §7.2 **B5** changes-job-failure | force `changes` to fail → `checks` FAILURE, not false-green (proves the BLOCKER fix) |
| §7.2 **B6** default-to-run | PR editing an unclassified path (`src/energy_go/__init__.py` / new module dir) must RUN `backend-tests` (pins §3.1 safety net) |
| §7.2 **B7** cancelled-run | concurrency supersede → head SHA's `checks` not stale-green, merge blocked |
| §10 **(F)** peak-RSS positive evidence | require measured peak RSS under 2 GB, not just absence-of-SIGTERM |
| §10 **(H)** marker-migration completeness | deterministic test: every full-year-JAX OOM module carries `local` → `not slow and not local` selects none |
| §11 finance `sample_kind:"synthetic"` → reject | the #133-LOCK / INV-CE-17 drift that bit #134 |
| §11 finance `min_dscr ≥ 10` → reject | INV-CE-16 ×100 unit-bug canary |
| §11 config dangling join-key + null-vs-absent → reject | #133 §8 cross-ref / merge-ambiguity classes |
| §11 non-vacuity guard | each validator must fail on ≥1 drifted fixture (no always-green no-op) |
| §11 skip-with-notice `::warning::` | absent-validator coverage gap must be visible, never silent green |

### backend-reviewer — APPROVE @ `f5e14b9` (2026-06-14)
BLOCKER resolved (§3.5 fail-set now "ANY need" incl. `changes`, with rationale); all reviewer cases
integrated faithfully (verified line-by-line). Marker taxonomy independently re-confirmed complete
(every (slow, local) combination maps to ≥1 lane; none falls through).

### backend-reviewer — APPROVE @ `cd52bc6` (2026-06-14, D29 re-stamp)
+10-line §10 PR-mapping clarification only ((A)–(F) on step-1; (G)+(H) on step-2, (H) atomic with the
`slow`→`local` migration). Verified no coverage window between the two PRs: step-1 fast-lane excludes
OOM tests via the `slow` tag pre-migration, with (F) backstopping.

---

## Stage 2 — Implementation Audit (PR #138, quick-wins YAML)

### backend-reviewer — APPROVE @ `03a6ad9` (2026-06-14)
Audited `ci.yml` + `ci-nightly.yml` + `pyproject.toml` + `STACK.md` against the contract. Gate logic
correct; false-green footguns avoided:
- §3.5 aggregator: `if: always()` + per-job result loop incl. `changes` in the fail-set → B5 hole
  closed (traced changes-fail → skip → catch end to end).
- `set -o pipefail` before `pytest | tee` (no exit-code masking); `/usr/bin/time` by full path;
  `checks` job-id unchanged (branch-protection context preserved).
- `changes` job: push-main → all-true; safe-defaults on fetch-fail/empty-diff; docs_only `$`-anchored
  regex (#116 fix); default-to-run for unclassified; `assets/3d/registry.json` dual-trigger.
- `::warning::` skip-with-notice for absent finance/config validators (§3.2, never silent green).
- Concurrency `cancel-in-progress: == 'pull_request'` → never cancels main push.

**Non-blocking note:** (F) peak-RSS via `/usr/bin/time -v` reports the single largest process, not the
2-xdist-worker aggregate → switch to the job-cgroup peak.

### backend-reviewer — APPROVE @ `b2a16b2` (2026-06-14, (F) fix re-stamp)
`/usr/bin/time -v` → `cat /sys/fs/cgroup/memory.peak` (cgroup v2 whole-job aggregate; honest
`::warning::` fallback). Re-verified gate-safety: removing the `| tee` pipe + explicit `pipefail` does
NOT regress exit-code propagation — GHA runs `shell: bash` as `bash -eo pipefail {0}` (errexit
default-on), and the standalone `pytest` is in the `then`-block (not an `if`-condition where `-e` is
suppressed) → a pytest failure still aborts the step → `backend-tests` fails → aggregator catches.

### backend-reviewer — REQUEST_CHANGES @ `b2a16b2` (2026-06-14)
**Nightly-OOM landmine** (caught by rl-architect; verified independently). #138 shipped
`ci-nightly.yml` (`-m "slow and not local"`) WITHOUT the `slow`→`local` migration → at head no test
carried `local`, so the selector resolved to the full D30 OOM set (`test_full_eval_episode_parity`
8760-step + the `lax.scan`/`synthetic_year` class) → nightly would OOM the 2 GB runner.
`schedule:`-triggered → invisible to the PR's fast-lane check (green-blind). Also contradicted the §10
PR-mapping (G+H = step-2). Recommended Option A: pull `ci-nightly.yml` + the `local` marker into the
step-2 PR with the migration + criterion-(H).

### backend-reviewer — APPROVE @ `62f5a22` (2026-06-14, Option A landed)
`ci-nightly.yml` removed (404 at head → no cron lane selects the OOM set); `local` marker cleanly
removed (no test references it pre-migration); selector `-m "not slow"` keeps the OOM `slow` set
excluded; STACK note = step-2. Re-verified the §3.5 aggregator + `changes`-in-fail-set (B5) survived
the branch's merge with main intact. **B7 (cancelled-run) demonstrated naturally** — the `62f5a22`
push cancelled the prior run and `checks` returned FAILURE, not stale-green (run `27507174579`).

### backend-reviewer — APPROVE @ `afba904` (2026-06-14, timeout re-stamp) — CURRENT
One-line `backend-tests` `timeout-minutes: 25 → 35` (cold pip/uv cache headroom). Benign — a timeout
is a safety ceiling; raising it lets a slow cold-cache run pass rather than spuriously time out, while
a real hang still trips it → aggregator catches. No test/gate/aggregator logic changed.
**Non-blocking follow-ups flagged:** (1) reconcile contract §3.3 `timeout-minutes: 25` → 35 (anti-drift);
(2) criterion-(E) heads-up — the ~20 min warm backend suite may exceed the ≤15 min target since
`-m "not slow"` runs the whole fast suite (QA to confirm; possible step-2 selector-granularity follow-up).

---

## Verdict

**backend-reviewer: APPROVE @ `afba904`** (latest marker; supersedes the intermediate RC, which was the
gate-safety round-trip working as designed). Merge path: backend APPROVE + QA_PASS + the §7.2 canary
(B1/B2/B5/B6 forced + B7 shown @ run 27507174579), per §10(B) the hard gate. The step-2 slow-lane PR
(re-introducing `ci-nightly.yml` + `local` marker + the `slow`→`local` migration + criterion-(H)
completeness test) returns to backend-reviewer — the migration must tag the **complete** OOM set
(env `test_env_parity_gansu.py` / `test_env_jax_env_core.py`, training `test_training_benchmark_baselines.py`
/ `test_training_eval_envstate_obs_fix.py`), not just one test.
