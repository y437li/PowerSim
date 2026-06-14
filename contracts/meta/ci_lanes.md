# Contract: CI Lanes — 3-tier test execution (fast / slow / local)

**Area:** meta · **Owner/Lead:** rl-architect (owns #74 + gate-safety + branch protection) · **Implementer:** serving-engineer (workflow YAML; did #116) · **Reviewers:** backend-reviewer (required) + QA (gate) · **Status:** DRAFT → (reviewer-approve test cases) → IMPLEMENT → QA
**Tracks:** task #23 (CI speed) · un-defers #74 (D30 slow-lane) · composes with #116/D40 (docs-only skip) and the USER option-b decision (heavy e2e local at milestone)

---

## 1. Problem & goal

The single serial `checks` job (`.github/workflows/ci.yml`) runs the full suite on every PR
(~40 min typical). USER directive "CI 太慢了" → make CI fast, **FREE only** (no paid runner;
the repo is public and free quota is the hard constraint — the 2 GB `ubuntu-latest` runner).

**Goal:** typical PR wall-clock **~40 → ≤15 min** by (a) splitting the serial job into PARALLEL
jobs, (b) per-area PATH FILTERING (skip the jobs an area's diff can't affect), (c) `pytest-xdist`
parallelism where 2 GB allows, (d) cancelling superseded PR runs — **without ever weakening the
merge gate.**

**Non-goals (explicit):** no paid runners; no GPU; no caching rework beyond what #116/#10 landed;
no change to *which* tests exist (only how they are bucketed and scheduled). The marker migration
re-tags existing tests; it does not delete or weaken any test.

---

## 2. The 3 tiers

| Tier | Marker | Where it runs | Merge gate? | Memory budget |
|------|--------|---------------|-------------|---------------|
| **FAST** | (unmarked) | CI, **every PR** | **YES** (the `checks` gate) | fits 2 GB at `-n 2` |
| **SLOW** | `@pytest.mark.slow` | CI **nightly + on-demand** (`ci-nightly.yml`) | no | must fit 2 GB |
| **LOCAL** | `@pytest.mark.local` | **local only** (arm64 venv, milestone/release) | no | OOMs the 2 GB free runner |

**Marker taxonomy (the #74 decision):**
- **unmarked → FAST.** Unit, module-integration, schema-conformance, static checks. Every PR.
- **`slow` → SLOW (nightly CI).** Slower tests that **still fit the 2 GB runner**. NOT a gate.
- **`local` → LOCAL (milestone).** Tests that **OOM the 2 GB free runner**: the `@pytest.mark.slow`
  full-year JAX jit/vmap trajectories (8760-step synthetic year), the full config→finance pipeline,
  and Playwright E2E (`tests/frontend_e2e/`). Run locally per USER option-b.

**Migration (through backend-reviewer):** the full-year-JAX tests **currently tagged `slow`** are the
OOM ones → they are **re-tagged `local`** (add the `local` marker; `slow` may be dropped from them or
kept — see §4 selector). Nightly runs `-m "slow and not local"`.

> **HONESTY NOTE (keep verbatim in any status/PR description): the nightly SLOW lane is "wired but
> near-empty" until fits-2 GB `slow` tests actually exist.** After migration, the current `slow`
> tests are OOM → re-tagged `local`, so `-m "slow and not local"` selects ≈0 tests initially. The
> nightly workflow is the *plumbing*; coverage grows as genuinely-mid-weight tests are written.
> Do NOT imply nightly coverage we do not have.

---

## 3. Fast-lane job DAG (the every-PR workflow, `ci.yml`)

```
                 ┌─────────────┐
                 │  changes    │  in-house git-diff vs base_ref → outputs: backend, frontend, docs_only
                 └──────┬──────┘
        ┌───────────────┼────────────────────────────┐
        ▼               ▼                             ▼
 ┌────────────┐  ┌──────────────┐            ┌──────────────┐
 │ static-    │  │ backend-     │            │ frontend-    │
 │ checks     │  │ tests        │            │ tests        │
 │ (ALWAYS)   │  │ (if backend) │            │ (if frontend)│
 └──────┬─────┘  └──────┬───────┘            └──────┬───────┘
        └───────────────┴────────────────────────────┘
                         ▼
                 ┌──────────────┐
                 │   checks     │  AGGREGATOR — needs:[static-checks,backend-tests,frontend-tests]
                 │ (ALWAYS;     │  if: always(); fails iff any need .result ∈ {failure, cancelled}
                 │  the GATE)   │  (skipped / success → pass)
                 └──────────────┘
```

### 3.1 `changes` job (path filter — in-house, NO new third-party action)
- Generalizes the proven #116/D40 docs-only git-diff logic into a job emitting three outputs.
- On `pull_request`: `git diff --name-only <base..head>`; on `push` to main: **all outputs = true**
  (full suite, same as today). If base ref can't be fetched / diff empty → **safe default: all true**.
- Output computation (conservative; "anything I can't classify → run it"):
  - `docs_only=true` iff every changed path matches `^(docs/|contracts/|[^/]+\.md$)` (unchanged from #116).
  - `backend=true` iff any changed path matches: `src/energy_go/(env|training|harness|serving|finance|telemetry|config)/`, `tests/(env|training|harness|serving|finance|shared)/`, `pyproject.toml`, `config/`, `scripts/`, `assets/3d/registry.json`. **OR `docs_only=false` and the path is unclassified** (default-to-run).
  - `frontend=true` iff any changed path matches: `src/` web sources (`*.ts`, `*.tsx`, `*.css`, `index.html`, `vite.*`), `tests/frontend*/`, `package.json`, `package-lock.json`, `assets/3d/` (registry feeds the scene).
  - A path may set BOTH backend and frontend (e.g. `assets/3d/registry.json`) → both jobs run. Intentional.

### 3.2 `static-checks` job — **ALWAYS runs** (cheap, no heavy deps), part of the gate
- `bash scripts/check_conventions.sh`
- nav-index staleness check (the task #12 / #130 step)
- registry committed-copy drift check (`node scripts/copy_registry.js` + `git diff --exit-code`)
- **schema-conformance (the wire-drift auto-catch — team-lead nod #3):**
  - telemetry golden examples: `PYTHONPATH=src python scripts/validate_telemetry.py --examples`
  - **finance summary** producer output validates against locked `contracts/shared/finance_result_summary.md` v1.1.0 (#135)
  - **config artifact** validates against locked `contracts/shared/config_artifact_schema.md` v1.0.0 (#133)
  - *Implementation note:* the finance + config schema-conformance checks require a small validator
    invocation analogous to `validate_telemetry.py`. If a producer-output fixture + validator does not
    yet exist for a given schema, the step runs the schema's existing conformance tests
    (`tests/shared/...`) instead — and the contract for that producer owns adding the fixture. Do NOT
    fabricate a passing check; if a validator is absent, the step must say so (skip-with-notice), not
    silently green.

### 3.3 `backend-tests` job — `if: needs.changes.outputs.backend == 'true'`
- Setup (python 3.11 + pip cache + uv, per existing #10 steps), install deps (unchanged set).
- `pytest tests/ -q -m "not slow and not local" -n 2` (xdist; **`-n 2` conservative for 2 GB** —
  see §4 memory rule). `timeout-minutes: 25`.

### 3.4 `frontend-tests` job — `if: needs.changes.outputs.frontend == 'true'`
- Setup node 20 + npm cache; regenerate Linux lock; `npm install`; `npm test`; `npm run build`
  (tsc + vite, task #40). `timeout-minutes: 20`.

### 3.5 `checks` aggregator job — **ALWAYS runs; THE merge gate**
- `needs: [changes, static-checks, backend-tests, frontend-tests]`, `if: always()`.
- Fails (exit 1) iff **ANY need** — `changes`, `static-checks`, `backend-tests`, `frontend-tests` —
  has `.result ∈ {failure, cancelled}`. `skipped` and `success` → pass.
- **`changes` MUST be in the fail-set (backend-reviewer BLOCKER, #136 — the highest-likelihood
  false-green path):** if `changes` FAILS, both test jobs go `skipped` (their
  `if: needs.changes.outputs.*` can't evaluate) and static-checks passes → an aggregator that checked
  only the three would see `success + skipped + skipped` → **FALSE-GREEN with zero area tests run**.
  `changes` has no `if:` so it is never legitimately `skipped` → including it is safe and closes the
  hole. (This is the §3 DAG "any need" reading; the earlier three-job prose was the bug.)
- **The check-run name MUST remain exactly `checks`** so the required branch-protection status
  context is unchanged. **No branch-protection edit is made by this work.**

### 3.6 Concurrency (free-minutes quick-win)
```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```
Cancels superseded PR runs; **never cancels `push` to main**.

---

## 4. Memory & selector rules (the OOM lesson, D30)
- **2 GB `ubuntu-latest`** is the hard ceiling. The historical SIGTERM at ~40–60 min came from xdist
  workers each JIT-compiling the full 8760-step year → those tests are `local`, never in CI.
- **`-n 2`** for `backend-tests` is the conservative default. serving-engineer **must empirically
  validate** (the #116/#124 scratch-PR pattern) that `-m "not slow and not local" -n 2` does NOT OOM;
  if headroom exists, `-n auto` may be proposed in a follow-up with evidence. Acceptance criterion (F)
  gates this.
- Fast-lane selector is `not slow and not local` (so a test tagged both `slow` AND `local` is excluded
  from fast lane — correct). Nightly selector is `slow and not local`. Local runs `slow or local`.

---

## 5. Slow lane (`ci-nightly.yml` — new workflow)
- Triggers: `schedule:` (nightly cron) + `workflow_dispatch` (on-demand). **NOT** `pull_request`.
- Runs `pytest tests/ -q -m "slow and not local"` on `ubuntu-latest`. Not a merge gate.
- Reports green/red; failures notify (issue/log), do not block PRs.
- See §2 HONESTY NOTE: wired-but-near-empty until fits-2 GB `slow` tests exist.

## 6. Local lane (milestone/release — docs only, no workflow)
- Documented command (arm64 venv per #123 dev-guide): `pytest tests/ -m "local or slow"` + Playwright
  (`tests/frontend_e2e/`). Run at milestone/release locally. Never CI (OOM). Add to the arm64 dev-guide.

---

## 7. Gate-safety protocol (rl-architect owns — criterion B is the hard gate)

The "never break the merge gate" lesson (recorded; #116/#124) made empirical:

1. The required status context stays **`checks`** (verified: `gh api .../branches/main/protection` →
   `required_status_checks.contexts == ["checks"]`). This work does **not** edit branch protection.
2. **CANARY — must pass BEFORE the new gate is relied upon (criterion B):** on a scratch PR,
   - (B1) break a **backend** test → confirm the `checks` context reports **FAILURE** and GitHub
     **blocks merge**;
   - (B2) break a **frontend** test → confirm `checks` **FAILURE** + merge blocked;
   - (B3) a **docs-only** PR → `checks` **green** with `backend-tests`/`frontend-tests` **skipped**;
   - (B4) a **frontend-only** PR → `backend-tests` skipped, `frontend-tests` runs; and a
     **backend-only** PR → vice-versa (criterion D).
   - (B5) **`changes`-job failure** (`# reviewer:` backend-reviewer) — force the `changes` job to fail
     (e.g. unresolvable base ref / injected `exit 1`) → confirm `checks` reports **FAILURE** and merge
     is blocked, NOT a false-green from skipped test jobs. Directly exercises the §3.5 BLOCKER fix.
   - (B6) **default-to-run** (`# reviewer:` backend-reviewer) — a PR adding a NEW module dir or editing
     an unclassified path (e.g. `src/energy_go/__init__.py`) must **RUN `backend-tests`** (not skip) —
     pins the §3.1 "anything I can't classify → run it" safety net (currently unverified by B1–B4).
   - (B7) **cancelled-run via concurrency** (`# reviewer:` backend-reviewer) — push a second commit to
     supersede an in-flight run → confirm the superseded run's `checks` does NOT remain a green
     required status on the new head (no stale-green merge through the §3.6 cancel path).
   Each canary result is recorded (run URL + observed context state) on the implementing PR before
   merge. **Reasoning alone does not satisfy B — it must be demonstrated.**
3. If at any point the required context WOULD change (it should not under this design), rl-architect
   owns the branch-protection flip + re-runs B before relying on it. There must be **no window** in
   which nothing gates `main`.

---

## 8. Sequence
1. **Quick-wins PR** (immediate ~40→~12 min): `changes` + parallel `static-checks ∥ backend-tests ∥
   frontend-tests` + `-n 2` + concurrency + `checks` aggregator. → run §7 canary → merge.
2. **Slow-lane PR** (after): marker migration (`slow`→`local` for the OOM full-year tests, through
   backend-reviewer) + `ci-nightly.yml`. Local-lane doc note.

## 9. STACK.md
- Plan introduces **no new** stack element (no new action; xdist already present; pytest markers are
  config). If serving-engineer's implementation adds any tool/action/marker registry entry, it
  updates `STACK.md` in the same PR. Register the marker taxonomy (`slow`, `local`) in
  `pyproject.toml` `[tool.pytest.ini_options] markers` so unknown-marker warnings don't mask typos.

---

## 10. Acceptance criteria (A–G — QA verifies; B is the hard gate)

- **(A)** The required branch-protection status context on `main` is still exactly **`checks`**,
  unchanged (no branch-protection edit in this work). Evidence: `gh api` contexts before==after.
- **(B)** **Canary demonstrates the gate BLOCKS** (per §7.2, scenarios **B1–B7**): broken-backend PR
  AND broken-frontend PR each show `checks` FAILURE + merge blocked (B1/B2); **B5 (changes-job failure)
  shows FAILURE not false-green**; B6 (default-to-run) RUNS backend-tests; B7 (cancelled-run) leaves no
  stale-green on the new head. All recorded with run URLs. **Hard gate — no merge of the quick-wins PR
  until B is shown.**
- **(C)** A docs-only PR → `checks` **green** with `backend-tests` + `frontend-tests` **skipped**
  (static-checks still runs and passes).
- **(D)** A frontend-only PR **skips** `backend-tests`; a backend-only PR **skips** `frontend-tests`;
  a mixed PR runs both.
- **(E)** Typical mixed-PR wall-clock **≤ 15 min** (report the measured time on the PR).
- **(F)** No `-m "not slow and not local"` test OOMs at `-n 2` on the 2 GB runner. **Evidence must be
  positive, not just absence-of-SIGTERM** (`# reviewer:` backend-reviewer): report **peak RSS**
  (e.g. `/usr/bin/time -v` "Maximum resident set size" or a `tracemalloc`/`resource` sample) showing
  headroom under 2 GB at `-n 2`, plus clean completion. (#124 pattern, strengthened.)
- **(G)** `ci-nightly.yml` runs **green** on `-m "slow and not local"` (even if near-empty — it must
  not error); `workflow_dispatch` trigger works.
- **(H)** **Marker-migration completeness** (`# reviewer:` backend-reviewer): a deterministic test
  asserts every known full-year-JAX OOM module carries the `local` marker, so
  `-m "not slow and not local"` selects **none** of them — a static guard that does not rely on (F)
  actually OOM-ing to catch a mis-tagged heavy test.

---

## 11. Test cases (reviewer-gated before implementation)

CI workflows are validated empirically (canary PRs), not by unit tests, EXCEPT the new
schema-conformance validators, which ARE testable. Reviewer-approved cases:

- `# reviewer:` backend-reviewer canary scenarios **B5–B7** integrated into §7.2 (changes-job-failure,
  default-to-run, cancelled-run).
- **Schema-conformance unit cases** (under `tests/shared/`, owned by each schema's contract):
  - finance-summary: a known-good producer fixture validates against #135 v1.1.0; reject fixtures —
    `equity_irr_pct` as MetricPercentiles (not scalar); a non-NPV metric carrying `bootstrap_ci`
    (rule B); mismatched per-metric `confidence` at same q (rule A); **`sample_kind:"synthetic"`**
    (`# reviewer:` — the actual #134/#133-LOCK drift we hit); **`min_dscr ≥ 10`** unit-bug
    (`# reviewer:` — the INV-CE-16 ×100 canary) → all **rejected**.
  - config-artifact: a known-good artifact validates against #133 v1.0.0; reject fixtures —
    `finance_overrides` key outside the frozen allow-set; a secret-shaped value (D32); **dangling
    join-key** and **null-vs-absent confusion** (`# reviewer:` — #133 §8) → all **rejected**.
  - **Non-vacuity guard** (`# reviewer:` backend-reviewer): each validator MUST **fail on ≥1 drifted
    fixture** in its own test run — proves the validator actually validates (not a no-op that greens
    everything). A validator that passes every fixture → test failure.
- **Marker-migration completeness** (`# reviewer:` backend-reviewer, criterion H): assert every known
  full-year-JAX OOM module carries `local`; `-m "not slow and not local"` selects none of them.
- **skip-with-notice visibility** (`# reviewer:` backend-reviewer): when a schema validator is absent,
  the static-checks step MUST emit a visible **`::warning::`** (GitHub Actions annotation), never a
  silent green — so absent-validator coverage gaps are seen in the checks UI (§3.2).
- **Aggregator-logic cases** (the `checks` exit-code rule), expressed as canary scenarios **B1–B7** in
  §7.2 — including **B5 `changes`-job-failure** (the §3.5 BLOCKER), B6 default-to-run, B7 cancelled-run.

> Per CLAUDE.md: reviewer-added cases marked `# reviewer:`; never modify an approved test to make it
> pass. No implementation (workflow YAML) before backend-reviewer approves these test cases.
